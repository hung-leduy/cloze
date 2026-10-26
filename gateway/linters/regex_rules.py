"""Deterministic secret and identifier screen: third linter in the egress chain.

Why this exists
---------------
The two linters ahead of this one in the chain each catch a class of leak by
a structural property, and each is blind to the complement of that property:

* the canary matcher matches only tokens the system itself planted;
* the entropy linter fires only on whitespace tokens longer than 24 characters
  with H > 4.85 bits/char. An AWS access key id is 20 characters. A UUID is
  36 characters drawn from 17 symbols, so its entropy cannot exceed 4.09. An
  email address, an IPv4 address, a national id number and a phone number are
  short, structured and low-entropy by construction.

The containment filter behind this one (``shared.shingle_filter``) catches
verbatim spans of C_user, five words or more; a single identifier is not five
words. So a credential or an identifier that is short or low-entropy has no
other deterministic check on the egress path. This module supplies it: values
whose *shape* identifies them, matched by compiled patterns, with no model in
the loop and no dependence on how random any particular sample happens to be.

The last three default rules (Vietnamese mobile numbers, the 12-digit CCCD
national id, and 10- or 13-digit tax codes) exist because the deployment is a
Vietnamese university and those are the identifiers its spreadsheets carry.

Boundaries, and the one identifier that must pass
-------------------------------------------------
Every rule asserts a left boundary (not preceded by a word character, and for
the numeric rules not by a dot either) and, wherever the match has a bounded
length, a right boundary. This is what keeps an 8-hex slot id, a 40-hex sha1,
a 64-hex sha256 or a version string from firing: none of them has the shape
the rules describe once the boundaries are enforced, and a hex run without
hyphens is not a UUID.

The slot placeholder ``⟦SLOT:CATEGORY_hex8⟧`` is the only identifier-shaped
token that legitimately crosses the boundary. ``RegexScreen`` refuses at
construction any rule set or custom dictionary that would fire on it, because
a screen that refuses every abstract payload is not a screen.

Why the boundary follows the head, and what that measured
---------------------------------------------------------
CPython's ``re`` uses its fast literal-prefix / first-character skip only when
a pattern *begins* with a literal or a character class. A leading ``\\b`` or
lookbehind disables it, and the engine then attempts the pattern at every one
of the ~10^6 offsets in a 1 MB payload. Measured on 1 MB of clean prose
(Python 3.12): ``(?<!\\w)sk-ant-…`` 16.0 ms against ``sk-ant-(?<!\\wsk-ant-)…``
1.0 ms; a leading-lookbehind IPv4 rule 19.7 ms against 0.7 ms anchored on the
first dot; ``\\b\\d{12}\\b`` 13.5 ms against 4.3 ms. So each rule starts with
its rarest fixed-width head (``sk-ant-``, ``AIza``, ``@``, the first ``-`` of a
UUID, the first ``.`` of an IPv4 address, the first ``:`` of an IPv6 address)
and asserts the left boundary by looking back over that head. This makes the
patterns read oddly at first; the alternative is a linter that costs more than
every other check in the chain combined. The full default rule set scans 1 MB
of clean prose in about 19 ms on this machine (see the tests).

Custom terms are matched by one compiled alternation over the casefolded text,
never by a per-term loop, and share the same head-first construction.

Known false positives, stated
-----------------------------
* A bare dotted quad whose parts are all <= 255, such as ``1.2.3.4``, fires
  as IPv4. It is indistinguishable from an address by shape. ``v1.2.3.4``,
  ``1.2.3`` and ``1.2.3.4.5`` do not fire. ``999.1.1.1`` does not fire.
* Any 10-digit number fires as a Vietnamese tax code, and any 13-digit run
  does too: that includes epoch-second and epoch-millisecond timestamps and
  EAN-13 barcodes written without separators. A 10-digit mobile number
  satisfies both the mobile and the tax-code grammar and is counted under
  both rules.
* ``sk-`` followed by twenty or more identifier characters fires as an OpenAI
  key; a 20-character all-caps word beginning ``AKIA``/``ASIA`` fires as an
  AWS key id. Two hex-looking words around ``::`` (``de::ad``) fire as IPv6.

Limits, stated as limits
------------------------
* Matching is exact-shape. A value that is split, re-encoded, spelled out or
  wrapped in markup is not matched here; the entropy linter covers encoding.
* Only credential formats listed in ``DEFAULT_RULES`` are known. Add rules;
  the screen has no notion of "looks like a secret" beyond them.
* UUIDs are recognised in hyphenated 8-4-4-4-12 form only, versions 1-8.
* IPv6 is a subset: the uncompressed 8-group form and ``::``-compressed
  forms. Zone ids (``%eth0``) are not consumed; IPv4-mapped addresses are
  caught by the IPv4 rule.
* Vietnamese mobile numbers are recognised as ``0``/``+84`` plus a current
  prefix, contiguous or grouped 4-3-3 / 3-3-4 with a space or dot; other
  groupings and the ``0084`` form are not. The old 9-digit CMND is not.
* Email addresses need an ASCII local-part character before ``@`` and an
  ASCII domain; internationalised domains are not matched.
* Matched content never appears in a verdict. The reason string carries a
  count and rule names only, because it is written to the gateway log and
  returned in the 403 body, and both leave the trusted zone.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ["DEFAULT_RULES", "SEVERITIES", "RegexRule", "RegexScreen", "RegexVerdict"]

SEVERITIES: frozenset[str] = frozenset({"critical", "high", "medium", "low"})

_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")

# A slot-shaped snippet no rule may match. Categories vary; the format does not.
_SLOT_PROBE = (
    "Revenue at ⟦SLOT:ORG_0a1b2c3d⟧ fell after ⟦SLOT:PERSON_ffffffff⟧ left; "
    "⟦SLOT:MONEY_00000000⟧ is owed to ⟦SLOT:PROJECT_deadbeef⟧."
)

# A fact-reference snippet no rule may match (R1). Measured before this probe
# existed: a custom rule `[0-9a-f]{8}\.[A-Z]+` constructed cleanly and then
# refused every FACT payload, while the equivalent slot-matching rule was already
# refused at construction. Built from punctuation rather than prose: every word
# in a probe becomes a term nobody can add as a custom sensitive term (the slot
# probe already makes "revenue", "owed" and "fell" unaddable), so this one costs
# a single non-content word, "fact". Every attribute code is in it, because a
# code missing from the probe could be added as a custom term and would then
# refuse every payload referencing that attribute.
_FACT_PROBE = (
    "⟦FACT:0a1b2c3d.AUTHAMT⟧ ⟦FACT:ffffffff.SPENTAMT⟧,⟦FACT:00000000.UNSPNTAM⟧; "
    "⟦FACT:deadbeef.OVRRUNAM⟧ (⟦FACT:12345678.PCTSPENT⟧) \"⟦FACT:abcdef01.DATESTRT⟧\" "
    "[⟦FACT:9a8b7c6d.DATEREV⟧] ⟦FACT:5e4f3a2b.OWNERREF⟧: ⟦FACT:1c0d9e8f.SITEREF⟧ "
    "⟦FACT:7a6b5c4d.REFCODE⟧/⟦FACT:3e2f1a0b.DELIVQTY⟧ ⟦FACT:c9d8e7f6.COMMQTY⟧ "
    "'⟦FACT:b5a49382.STATNOTE⟧'"
)


@dataclass(frozen=True, slots=True)
class RegexRule:
    """One compiled rule. ``name`` is what the verdict reports; it is never content."""

    name: str
    pattern: re.Pattern[str]
    severity: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _NAME_RE.fullmatch(self.name):
            raise ValueError(f"rule name must match [a-z][a-z0-9_]*, got {self.name!r}")
        if not isinstance(self.pattern, re.Pattern):
            raise TypeError("rule pattern must be a compiled re.Pattern")
        if self.severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {sorted(SEVERITIES)}, got {self.severity!r}")


@dataclass(frozen=True, slots=True)
class RegexVerdict:
    """Outcome of one regex inspection. Carries counts and rule names, never matches."""

    blocked: bool
    rule_names: tuple[str, ...]
    total_hits: int

    @property
    def reason(self) -> str:
        if not self.blocked:
            return "OK"
        return (
            f"SECRET_PATTERN: {self.total_hits} hit(s) across rules "
            f"{', '.join(self.rule_names)}"
        )


# --------------------------------------------------------------------------- rule grammar
#
# Every pattern below is built as  HEAD (?<! \w HEAD ) REST  or, where the head
# is not the first character of the value,  HEAD (?<= (?<!\w) PREFIX HEAD ) REST.
# The lookbehind immediately after the head is the left boundary; putting it
# there rather than first is what keeps `re`'s prefix skip enabled (see the
# module docstring). Lookbehinds must be fixed-width, so a variable-width
# prefix (the first IPv4 octet, the first IPv6 group) becomes an alternation
# of fixed-width lookbehinds, one per width.

_H = r"[0-9A-Fa-f]"
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_G = rf"{_H}{{1,4}}"  # one IPv6 group
# Current Vietnamese mobile prefixes (second and third digits after the
# leading 0): Viettel 32-39/86/96-98, Vinaphone 81-85/88/91/94, Mobifone
# 70/76-79/89/90/93, Vietnamobile 52/56/58/92, Gmobile 59/99, iTel 87, Reddi 55.
_VN_MOBILE_PREFIX = r"(?:3[2-9]|5[2-9]|7[06-9]|8[1-9]|9\d)"
# After the leading 0 or +84 and the two-digit prefix: seven digits, contiguous
# or written 4-3-3 (0912 345 678) or 3-3-4 (091 234 5678), space or dot.
_VN_MOBILE_TAIL = r"(?:\d{7}|\d[ .]\d{3}[ .]\d{3}|[ .]\d{3}[ .]\d{4})"
# Not glued to a word character, and not the integer part of a decimal.
_NUM_END = r"(?!\w|\.\d)"

_IPV6_FIRST_GROUP_BEHIND = "|".join(
    rf"(?<=(?<![\w:]){_H}{{{w}}}:)" for w in (1, 2, 3, 4)
)
_IPV6_REST_UNCOMPRESSED = rf"(?:{_G}:){{6}}{_G}"
_IPV6_REST_COMPRESSED = rf"(?:{_G}:){{0,5}}:(?:{_G}(?::{_G}){{0,5}})?"

DEFAULT_RULES: tuple[RegexRule, ...] = (
    RegexRule(
        "anthropic_api_key",
        re.compile(r"sk-ant-(?<!\wsk-ant-)[A-Za-z0-9_-]{20,}"),
        "critical",
    ),
    RegexRule(
        "openai_api_key",
        # Covers legacy sk-…, sk-proj-…, sk-svcacct-…; the lookahead keeps an
        # Anthropic key from being counted twice.
        re.compile(r"sk-(?<!\wsk-)(?!ant-)[A-Za-z0-9_-]{20,}"),
        "critical",
    ),
    RegexRule(
        "aws_access_key_id",
        re.compile(r"A(?<!\wA)(?:KIA|SIA)[0-9A-Z]{16}(?!\w)"),
        "critical",
    ),
    RegexRule(
        "github_token",
        re.compile(r"gh(?<!\wgh)[pousr]_[A-Za-z0-9]{36}(?!\w)"),
        "critical",
    ),
    RegexRule(
        "github_fine_grained_pat",
        re.compile(r"github_pat_(?<!\wgithub_pat_)[A-Za-z0-9_]{82}(?!\w)"),
        "critical",
    ),
    RegexRule(
        "google_api_key",
        re.compile(r"AIza(?<!\wAIza)[0-9A-Za-z_-]{35}(?![\w-])"),
        "critical",
    ),
    RegexRule(
        "slack_token",
        re.compile(r"xox(?<!\wxox)[abprs]-[0-9A-Za-z-]{10,}"),
        "critical",
    ),
    RegexRule(
        "private_key_pem",
        re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY(?: BLOCK)?-----"),
        "critical",
    ),
    RegexRule(
        "jwt",
        # header.payload.signature; header and payload are JSON objects, so
        # both base64url segments begin with the encoding of '{"'.
        re.compile(r"eyJ(?<!\weyJ)[A-Za-z0-9_-]{5,}\.eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{10,}"),
        "critical",
    ),
    RegexRule(
        "uuid",
        # Anchored on the first hyphen; the eight hex digits before it and the
        # boundary before those sit in the lookbehind. RFC 9562 versions 1-8.
        re.compile(
            rf"-(?<=(?<!\w){_H}{{8}}-){_H}{{4}}-[1-8]{_H}{{3}}-[89abAB]{_H}{{3}}-{_H}{{12}}(?!\w)"
        ),
        "medium",
    ),
    RegexRule(
        "ipv4",
        # Anchored on the first dot. The first octet is 1, 2 or 3 digits, so
        # its range check is three fixed-width lookbehinds; 999.1.1.1 fails all
        # three and 1.2.3.4 is the stated false positive.
        re.compile(
            r"\.(?:"
            r"(?<=(?<![\w.])\d\.)"
            r"|(?<=(?<![\w.])[1-9]\d\.)"
            r"|(?<=(?<![\w.])(?:1\d\d|2[0-4]\d|25[0-5])\.)"
            rf"){_OCTET}(?:\.{_OCTET}){{2}}{_NUM_END}"
        ),
        "medium",
    ),
    RegexRule(
        "ipv6",
        # Anchored on the first colon. Either a bounded 1-4 hex group precedes
        # it and seven more groups or a `::`-compressed remainder follow, or
        # the address itself begins with `::` and at least one group follows.
        re.compile(
            rf":(?:(?:{_IPV6_FIRST_GROUP_BEHIND})"
            rf"(?:{_IPV6_REST_UNCOMPRESSED}|{_IPV6_REST_COMPRESSED})"
            rf"|(?<=(?<![\w:]):):{_G}(?::{_G}){{0,6}}"
            r")(?![\w:])"
        ),
        "medium",
    ),
    RegexRule(
        "email",
        # Anchored on '@'. One local-part character before it is enough to
        # decide presence; the address is not extracted.
        re.compile(r"@(?<=[A-Za-z0-9._%+-]@)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])"),
        "high",
    ),
    RegexRule(
        "vn_mobile",
        re.compile(
            rf"(?:\+84(?<!\w\+84) ?|0(?<![\w.]0)){_VN_MOBILE_PREFIX}{_VN_MOBILE_TAIL}{_NUM_END}"
        ),
        "high",
    ),
    RegexRule(
        "vn_national_id",
        # CCCD: 3-digit province code 001-096, then 9 digits. Requiring the
        # leading 0 and a real province code is what separates this from any
        # 12-digit number.
        re.compile(rf"0(?<![\w.]0)(?:[0-8]\d|9[0-6])\d{{9}}{_NUM_END}"),
        "high",
    ),
    RegexRule(
        "vn_tax_code",
        # 10 digits, optionally followed by a 3-digit branch suffix with or
        # without the customary hyphen.
        re.compile(r"\d(?<![\w.]\d)\d{9}(?:-?\d{3})?(?!\w|\.\d|-\d)"),
        "high",
    ),
)

_CUSTOM_RULE_NAME = "custom_term"


def _compile_custom_terms(terms: Iterable[str]) -> tuple[re.Pattern[str] | None, int]:
    """One alternation over every term, word-bounded, for use on casefolded text.

    Each branch is  c (?<!\\w c) rest (?!\\w)  so that the alternation still
    begins with a literal per branch and `re` keeps its first-character skip.
    Whitespace inside a term matches any whitespace run. Terms are casefolded
    here and the payload is casefolded at scan time; no IGNORECASE flag, which
    would also disable the skip.
    """
    branches: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if not isinstance(term, str):
            raise TypeError(f"custom term must be str, got {type(term).__name__}")
        pieces = term.casefold().split()
        if not pieces:
            raise ValueError("custom term must contain a non-whitespace character")
        key = " ".join(pieces)
        if key in seen:
            continue
        seen.add(key)
        head, rest = pieces[0][0], pieces[0][1:]
        body = re.escape(rest) + "".join(r"\s+" + re.escape(p) for p in pieces[1:])
        branches.append(rf"{re.escape(head)}(?<!\w{re.escape(head)}){body}(?!\w)")
    if not branches:
        return None, 0
    # Longest first so a term that extends another wins the position.
    branches.sort(key=len, reverse=True)
    return re.compile("(?:" + "|".join(branches) + ")"), len(branches)


class RegexScreen:
    """Runs every rule and the custom-term alternation over a payload."""

    def __init__(
        self,
        rules: Iterable[RegexRule] = DEFAULT_RULES,
        custom_terms: Iterable[str] = (),
    ) -> None:
        self._rules = tuple(rules)
        names = [r.name for r in self._rules]
        if len(set(names)) != len(names) or _CUSTOM_RULE_NAME in names:
            raise ValueError("rule names must be unique and must not be 'custom_term'")
        self._custom, self._n_custom = _compile_custom_terms(custom_terms)
        # Fail at construction, not at the first refused payload.
        for probe, what in ((_SLOT_PROBE, "slot placeholder"), (_FACT_PROBE, "fact reference")):
            v = self.scan(probe)
            if v.blocked:
                raise ValueError(
                    f"rule(s) {', '.join(v.rule_names)} match the {what} format; "
                    "a screen that refuses every abstract payload is misconfigured"
                )

    @property
    def rules(self) -> tuple[RegexRule, ...]:
        return self._rules

    @property
    def custom_term_count(self) -> int:
        return self._n_custom

    def scan(self, text: str) -> RegexVerdict:
        """Count every match of every rule. No short-circuit: the verdict names them all."""
        names: list[str] = []
        total = 0
        for rule in self._rules:
            n = len(rule.pattern.findall(text))
            if n:
                names.append(rule.name)
                total += n
        if self._custom is not None:
            n = len(self._custom.findall(text.casefold()))
            if n:
                names.append(_CUSTOM_RULE_NAME)
                total += n
        return RegexVerdict(blocked=total > 0, rule_names=tuple(names), total_hits=total)
