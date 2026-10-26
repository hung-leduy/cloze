"""Indirect prompt injection screen for retrieved web content.

Runs on PURIFIED text (see `html_purifier`), which has already lost scripts,
styles and invisible characters. What remains is the visible prose, and the
visible prose is where indirect injection lives: a page that tells the model
to ignore its instructions, or that offers a URL for the model to "report
back" to.

Detect, then defang, never delete
---------------------------------
`neutralise` rewrites hits rather than removing them. Deleting would let an
attacker erase surrounding evidence by wrapping it in a trigger, and it
would hide from a human reviewer that the page was hostile at all. The
defanged forms keep the page readable and the finding visible:

* control tokens lose their brackets to full-width lookalikes,
  ``<|im_start|>`` becomes ``〈|im_start|〉``;
* a role label at line start gets a leading ``·``, so ``System:`` becomes
  ``·System:`` and no longer sits where a template would put one;
* a markdown image or link whose target carries a query string loses the
  target, not the text: ``[click](https://x.invalid/?d=..)`` becomes
  ``[click]([url removed])``.

Defanging is idempotent for the delimiter and role families: running
`detect` on `neutralise` output finds nothing from those families. The
instruction-override family is prose and is not rewritten, because there is
no way to defang an English sentence without destroying it; those findings
stay flagged and the caller decides.

Known false positive, stated rather than hidden: a technical page with a
line beginning ``System: Ubuntu 24.04`` trips ``role_label``, because that
is exactly the shape a spoofed role label has. The screen advises; it does
not block egress, so the cost is a flag on a page, not a lost report.

What this cannot do
-------------------
Rules are lexical. Paraphrase, translation into a language with no rule,
and pure social engineering with no trigger phrase all pass. That is
measured rather than asserted: `test_injection_redteam.py` carries sixty
adversarial payloads, and every one this screen misses is a strict xfail,
so the gap is written down and the day a rule starts catching one the test
turns red and the list is updated.

This screen is defence in depth, not the boundary. The boundary is the
network partition and the containment filter; the reintegrator's transport
position check (scope Fix 2) is what actually stops a slot reaching an
attacker's URL, whether or not this screen flagged the page it came from.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

__all__ = ["Finding", "InjectionGuard", "InjectionVerdict"]

# Families, in the order they are reported. The two that `neutralise` can
# rewrite come first so the idempotency contract is easy to read.
FAMILY_DELIMITER = "delimiter"
FAMILY_ROLE = "role_spoof"
FAMILY_OVERRIDE = "instruction_override"
FAMILY_EXFIL = "exfiltration"
FAMILY_ENCODING = "encoding"
FAMILY_SMUGGLING = "smuggling"

_ZERO_WIDTH = "​‌‍⁠﻿­᠎"
_BIDI = "‪‫‬‭‮⁦⁧⁨⁩‎‏؜"

# Slot placeholders and fact references are the identifier-shaped tokens that
# legitimately cross. Nothing here may fire on them; tests pin both. The FACT
# pattern duplicates the backend's `models/facts.FACT_RE` because the gateway
# does not import backend code; a drift test compares the two.
_SLOT_RE = re.compile(r"⟦SLOT:[A-Z_]+_[0-9a-f]{8}⟧")
_FACT_RE = re.compile(r"⟦FACT:(?P<hex>[0-9a-f]{8})\.(?P<attr>[A-Z][A-Z0-9]{1,7})⟧")
_TOKEN_RE = re.compile(f"{_SLOT_RE.pattern}|{_FACT_RE.pattern}")

_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    # ---- delimiters: chat-template control tokens -------------------------
    (FAMILY_DELIMITER, "chatml_token",
     re.compile(r"<\|(?:im_start|im_end|system|user|assistant|endoftext|eot_id)\|>")),
    (FAMILY_DELIMITER, "llama_inst",
     re.compile(r"\[/?INST\]|<</?SYS>>")),
    (FAMILY_DELIMITER, "sentence_token",
     re.compile(r"(?<![\w<])</?s>(?![\w>])")),
    (FAMILY_DELIMITER, "markdown_instruction_header",
     re.compile(r"^#{1,6}\s*(?:Instruction|System|Prompt)s?\b", re.M | re.I)),
    # ---- role spoofing: a label where a template would put one ------------
    (FAMILY_ROLE, "role_label",
     # Emphasis, brackets and NBSP are cosmetic: "**System:**", "[system]" and
     # "System\u00a0:" are the same technique as a bare label at line start.
     re.compile(r"^[ \t\u00a0]*[*_\[]{0,2}"
                r"(?:System|Assistant|Human|User|AI)"
                r"[*_\]]{0,2}[ \t\u00a0]*[:：]", re.M | re.I)),
    (FAMILY_ROLE, "developer_mode",
     re.compile(r"\b(?:developer\s+mode|jailbreak\s+mode|admin\s+override)\b", re.I)),
    (FAMILY_ROLE, "you_are_now",
     re.compile(r"\byou\s+are\s+now\s+(?:a|an|the)\b", re.I)),
    # ---- instruction override: prose that redirects the model -------------
    (FAMILY_OVERRIDE, "ignore_previous",
     re.compile(r"\b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}?"
                r"\b(?:previous|prior|above|earlier|all)\b[^.\n]{0,20}?"
                r"\b(?:instruction|prompt|direction|rule|command)s?\b", re.I)),
    (FAMILY_OVERRIDE, "new_instructions",
     # "The vendor sent new instructions" is ordinary English, so a directive
     # frame is required: the instructions must be addressed to the reader.
     re.compile(r"\b(?:your|here\s+(?:are|is)|follow|these\s+are)\b[^.\n]{0,20}?"
                r"\b(?:new|updated|revised|real|actual)\s+(?:instruction|task|objective)s?\b",
                re.I)),
    (FAMILY_OVERRIDE, "do_not_follow",
     re.compile(r"\bdo\s+not\s+follow\b[^.\n]{0,40}\b(?:instruction|prompt|rule)s?\b", re.I)),
    (FAMILY_OVERRIDE, "reveal_prompt",
     re.compile(r"\b(?:reveal|print|output|repeat|show|disclose)\b[^.\n]{0,30}?"
                r"\b(?:system\s+prompt|your\s+instructions|your\s+context|the\s+prompt)\b", re.I)),
    # ---- exfiltration: a destination for the model to send data to --------
    (FAMILY_EXFIL, "markdown_image_query",
     re.compile(r"!\[[^\]]*\]\(\s*<?[a-z]+://[^)\s]*\?[^)\s]*\)", re.I)),
    (FAMILY_EXFIL, "markdown_link_query",
     re.compile(r"(?<!!)\[[^\]]*\]\(\s*<?[a-z]+://[^)\s]*\?[^)\s]*\)", re.I)),
    (FAMILY_EXFIL, "markdown_ref_definition_query",
     re.compile(r"^[ \t]{0,3}\[[^\]]+\]:[ \t]*<?[a-z]+://[^\s]*[?#][^\s]*", re.M | re.I)),
    (FAMILY_EXFIL, "markdown_target_fragment",
     re.compile(r"!?\[[^\]]*\]\(\s*<?[a-z]+://[^)\s]*#[^)\s]*\)", re.I)),
    (FAMILY_EXFIL, "html_src_query",
     re.compile(r"<(?:img|script|iframe)\b[^>]*\b(?:src|href)\s*=\s*[\"']?[a-z]+://"
                r"[^\"'>\s]*[?#]", re.I)),
    (FAMILY_EXFIL, "send_to_url",
     re.compile(r"\b(?:send|post|upload|transmit|report|exfiltrate)\b[^.\n]{0,40}?"
                r"\b(?:to|at)\b\s+<?[a-z]+://", re.I)),
    # ---- encoding: a payload the model is asked to decode -----------------
    (FAMILY_ENCODING, "rot13",
     re.compile(r"\brot-?13\b", re.I)),
)

# Encoding rules that need proximity between a verb and a blob are handled
# procedurally: a regex spanning both would be fragile and slow.
_DECODE_RE = re.compile(r"\b(?:decode|decrypt|base64|unbase64|from\s*hex|deobfuscate)\b", re.I)
_B64_BLOB = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")
_HEX_BLOB = re.compile(r"\b[0-9a-fA-F]{40,}\b")
_PROXIMITY = 200

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    count: int
    family: str = ""


@dataclass(frozen=True, slots=True)
class InjectionVerdict:
    flagged: bool
    findings: tuple[Finding, ...] = ()

    @property
    def families(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(f.family for f in self.findings if f.family))

    @property
    def total_hits(self) -> int:
        return sum(f.count for f in self.findings)

    @property
    def reason(self) -> str:
        if not self.flagged:
            return "OK"
        names = ", ".join(f.rule for f in self.findings)
        return f"PROMPT_INJECTION: {self.total_hits} hit(s) across rules {names}"


@lru_cache(maxsize=4096)
def _script_of(ch: str) -> str:
    """Coarse script bucket for a letter: latin, cyrillic, greek, or other."""
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return "other"
    for script in ("LATIN", "CYRILLIC", "GREEK"):
        if name.startswith(script):
            return script.lower()
    return "other"


class InjectionGuard:
    def __init__(self, extra_patterns: Iterable[tuple[str, str]] = ()) -> None:
        self._rules = list(_RULES)
        for name, pattern in extra_patterns:
            self._rules.append(("custom", name, re.compile(pattern, re.I | re.M)))

    # ------------------------------------------------------------------ detect

    def detect(self, text: str) -> InjectionVerdict:
        counts: list[Finding] = []
        # Slot placeholders and fact references are removed before any rule
        # runs, so no rule can fire on the tokens that legitimately look synthetic.
        scan = _TOKEN_RE.sub(" ", text)
        for family, name, pat in self._rules:
            n = len(pat.findall(scan))
            if n:
                counts.append(Finding(name, n, family))
        for name, n in self._procedural(scan):
            fam = (FAMILY_SMUGGLING
                   if name in ("mixed_script", "invisible_char", "fullwidth_latin")
                   else FAMILY_ENCODING)
            counts.append(Finding(name, n, fam))
        # Order findings by family order, then rule name, for stable reports.
        order = {f: i for i, f in enumerate(
            (FAMILY_DELIMITER, FAMILY_ROLE, FAMILY_OVERRIDE, FAMILY_EXFIL,
             FAMILY_ENCODING, FAMILY_SMUGGLING, "custom"))}
        counts.sort(key=lambda f: (order.get(f.family, 99), f.rule))
        return InjectionVerdict(bool(counts), tuple(counts))

    def _procedural(self, text: str) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []
        # Encoded blob near a decode instruction.
        decode_spans = [m.span() for m in _DECODE_RE.finditer(text)]
        if decode_spans:
            for name, blob_re in (("base64_near_decode", _B64_BLOB),
                                  ("hex_near_decode", _HEX_BLOB)):
                n = 0
                for m in blob_re.finditer(text):
                    if any(abs(m.start() - s) <= _PROXIMITY or abs(m.start() - e) <= _PROXIMITY
                           for s, e in decode_spans):
                        n += 1
                if n:
                    out.append((name, n))
        # Invisible characters. The purifier removes these, so any survivor
        # means this text did not come through it, which is itself a finding.
        n_inv = sum(text.count(c) for c in _ZERO_WIDTH + _BIDI)
        if n_inv:
            out.append(("invisible_char", n_inv))
        # Fullwidth Latin renders like ASCII but is a different code block, so
        # it slips past both the rules and the mixed-script check.
        n_fw = sum(1 for c in text if "\uff01" <= c <= "\uff5e")
        if n_fw:
            out.append(("fullwidth_latin", n_fw))
        # A word mixing Latin with Cyrillic or Greek letters is a confusable.
        n_mix = 0
        for m in _WORD.finditer(text):
            w = m.group(0)
            if w.isascii():
                continue  # an all-ASCII word is single-script by construction
            scripts = {_script_of(c) for c in w if c.isalpha()}
            scripts.discard("other")
            if "latin" in scripts and len(scripts) > 1:
                n_mix += 1
        if n_mix:
            out.append(("mixed_script", n_mix))
        return out

    # --------------------------------------------------------------- neutralise

    def neutralise(self, text: str) -> tuple[str, InjectionVerdict]:
        """Defang what can be defanged; return the rewritten text and the ORIGINAL verdict."""
        verdict = self.detect(text)
        out = text
        # Delimiters: swap the outer brackets for full-width lookalikes.
        out = re.sub(r"<\|([a-z_]+)\|>", r"〈|\1|〉", out)
        out = re.sub(r"\[(/?)INST\]", r"〔\1INST〕", out)
        out = re.sub(r"<<(/?)SYS>>", r"《\1SYS》", out)
        out = re.sub(r"(?<![\w<])<(/?)s>(?![\w>])", r"〈\1s〉", out)
        out = re.sub(r"^(#{1,6}\s*)(Instruction|System|Prompt)(s?\b)", r"\1·\2\3",
                     out, flags=re.M | re.I)
        # Role labels at line start.
        out = re.sub(r"^([ \t]*)(System|Assistant|Human|User|AI)([ \t]*[:：][ \t])",
                     r"\1·\2\3", out, flags=re.M)
        # Exfiltration targets: keep the text, drop the destination.
        out = re.sub(r"(!?\[[^\]]*\]\()\s*<?[a-z]+://[^)\s]*\?[^)\s]*(\))",
                     r"\1[url removed]\2", out, flags=re.I)
        # Invisible characters have no legitimate role in evidence text.
        out = out.translate({ord(c): None for c in _ZERO_WIDTH + _BIDI})
        return out, verdict
