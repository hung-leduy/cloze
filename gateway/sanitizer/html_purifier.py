"""Read-only confinement of retrieved web content: HTML in, inert plain text out.

Why this exists
---------------
Retrieved pages are the one input the system accepts from an adversary by
design. They are placed inside a prompt, and a language model has no
channel-level way to tell instruction from data. This module does not try to
recognise instructions; ``injection_guard`` does that, on the output of this
module. It removes what a plain-text sanitiser can remove deterministically,
so that the guard and the model downstream see text and only text:

* active content: scripts, styles, embedded objects and every other tag;
* invisible characters: zero-width characters, bidirectional controls and
  C0/C1 controls, the carriers for instructions a human reviewer cannot see
  and a tokenizer can;
* the envelope's own delimiters, so that a page cannot close the
  ``<untrusted_web_evidence>`` block early and continue in the system's voice.

How it works
------------
1. Bytes are decoded once, here: BOM first, then a ``<meta charset>`` or XML
   declaration in the first 4 KiB, then UTF-8, then windows-1252 as the
   last resort. Nothing raises; undecodable bytes become U+FFFD.
2. The decoded HTML is run through the invisible-character pass before
   parsing. Removing a U+200B from the middle of ``<script>`` turns text a browser
   would display into a script element whose body is dropped, which is the
   safe direction.
3. ``trafilatura.extract`` (``include_comments=False``,
   ``include_tables=True``, ``favor_precision=True``) produces the main
   content. Measured on 2.0.0: a bare ``<p>hi</p>`` returns ``None``; the same
   fragment inside an ``<html><body>`` skeleton extracts. When it returns
   ``None`` or raises, a stdlib ``HTMLParser`` tag-stripper supplies the text
   instead. That parser runs on every page regardless, because it is also
   where the tag counts and the ``<title>`` come from. ``stripped["fallback"]``
   says which text was used.
4. The invisible-character pass runs again on the extracted text, because
   ``&#8203;`` in the source only becomes U+200B during parsing. Runs of
   horizontal whitespace collapse to one space and runs of blank lines to
   one, so paragraph boundaries survive for the model: trafilatura separates
   paragraphs with one newline, the fallback parser with a blank line.
5. Truncation to ``max_chars`` at a whitespace boundary.

``envelope`` wraps the result. Any ``<untrusted_web_evidence`` or
``</untrusted_web_evidence`` left in the text, in any case, has its ``<``
replaced by ``&lt;`` before wrapping, so the only real delimiters in the
output are the two the envelope writes.

What this buys, stated precisely
--------------------------------
* No tag, script body, style body or comment from the page reaches the
  output on either path. Trafilatura removes them on its path; the fallback
  parser drops the content of ``script``, ``style``, ``noscript``,
  ``template``, ``iframe``, ``object``, ``embed``, ``svg``, ``math`` and
  ``head`` and emits no tag text at all.
* None of the enumerated invisible characters survives on either path.
  Trafilatura strips every Unicode category-C character itself (measured),
  which is why the counts in ``stripped`` come from this module's own passes
  on the decoded input and on the output, not from trafilatura.
* The envelope cannot be closed early by page content. This is a prompt
  convention the model is instructed to honour, not a cryptographic boundary;
  the guarantee is that the delimiter string occurs exactly twice.
* Bounded time. Measured on the development machine, Python 3.12: a 1 MB
  article-shaped page takes about 0.07 s in the fallback parser and 0.5 s in
  trafilatura; the worst adversarial 1 MB inputs found (a megabyte of ``<``,
  or of ``<b></b>``) take 1.1 s and 1.9 s respectively. ``max_html_chars``
  caps the input so that bound holds whatever the fetcher passes in.

Limits, stated as limits
------------------------
* Visible text is passed through unchanged. "Ignore your instructions" in a
  paragraph is exactly what this module preserves; the injection guard is
  the component that judges it.
* Precision mode loses content by design: navigation, comments, footers and
  boilerplate are gone, and trafilatura drops the text after an unknown
  inline element inside a paragraph (measured on 2.0.0). Retrieval for
  evidence prefers a missed sentence to an injected one.
* The invisible-character set is enumerated, not category-wide. Variation
  selectors (U+FE00-FE0F, U+E0100-E01EF) are kept because CJK and emoji
  text need them, although they are a known low-bandwidth smuggling channel.
  Homoglyphs and confusables are not normalised.
* Markdown constructs in the text (links, images) are not neutralised here.
  The reintegrator's AST position check (scope Fix 2) is what stops a slot
  from landing inside one.
* Counts in ``stripped`` are diagnostics for the audit log, not verdicts.
"""

from __future__ import annotations

import codecs
import logging
import re
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser

import trafilatura

__all__ = ["ENVELOPE_TAG", "PurifiedPage", "envelope", "purify"]

log = logging.getLogger(__name__)

ENVELOPE_TAG = "untrusted_web_evidence"

# Invisible characters, enumerated. Each class is removed and counted
# separately so the audit log can tell a page with soft hyphens from one
# with bidirectional overrides.
#
# zero_width: ZWSP, ZWNJ, ZWJ (200B-200D); word joiner and the invisible
# mathematical operators (2060-2064); BOM/ZWNBSP (FEFF); soft hyphen (00AD);
# Mongolian vowel separator (180E); and the TAG block (E0000-E007F), which
# maps one-to-one onto ASCII and is the documented carrier for text a
# tokenizer reads and a screen does not show.
_ZERO_WIDTH_RE = re.compile(
    "[\u200b-\u200d\u2060-\u2064\ufeff\u00ad\u180e\U000e0000-\U000e007f]"
)
# bidi: embeddings, overrides and isolates (202A-202E, 2066-2069) plus the
# LRM/RLM/ALM marks (200E, 200F, 061C).
_BIDI_RE = re.compile("[\u202a-\u202e\u2066-\u2069\u200e\u200f\u061c]")
# control: C0 except tab and newline, DEL, and C1. Carriage returns are
# normalised to newlines before this pass and are not counted.
_CONTROL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x80-\x9f]")

_HORIZONTAL_WS_RE = re.compile(r"[^\S\n]+")
_SPACE_AROUND_NL_RE = re.compile(r" ?\n ?")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_ANY_WS_RE = re.compile(r"\s+")

# Charset sniff over the first 4 KiB of undecoded bytes. Matches
# <meta charset=x>, <meta http-equiv content="...; charset=x"> and
# <?xml encoding="x"?>.
_META_CHARSET_RE = re.compile(
    rb"""<meta[^>]*?charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)"""
    rb"""|<\?xml[^>]*?encoding\s*=\s*["']([A-Za-z0-9_.:-]+)""",
    re.IGNORECASE,
)
_SNIFF_BYTES = 4096

# The `<` of any envelope delimiter, opening or closing, any case, with any
# whitespace an LLM might still read through. Only the bracket is rewritten.
_ENVELOPE_FORGERY_RE = re.compile(rf"<(?=\s*/?\s*{ENVELOPE_TAG})", re.IGNORECASE)

_TITLE_MAX_CHARS = 256
_URL_MAX_CHARS = 2048


@dataclass(frozen=True)
class PurifiedPage:
    """Plain text of one retrieved page, plus what was removed to get there.

    ``stripped`` keys, all always present:
    ``scripts``, ``styles``, ``tags_total`` (tags seen by the fallback
    parser, counted on every page), ``zero_width``, ``bidi``, ``control``
    (characters removed by the two normalisation passes), ``fallback`` (1 if
    the tag-stripper's text was used, 0 if trafilatura's) and
    ``parser_error`` (1 if the stdlib parser raised, in which case the counts
    are zero and the fallback text is empty).
    """

    text: str = field(repr=False)
    title: str
    url: str
    truncated: bool
    stripped: dict[str, int]


class _TagStripper(HTMLParser):
    """Conservative text extraction and tag counting over one page.

    Emits the data of every element except those in ``SKIP`` (content that is
    never prose) and a newline at block boundaries. Comments, CDATA sections,
    processing instructions and declarations are dropped by the base class's
    default handlers. Character references are decoded by the base class,
    which is why the invisible-character pass must run again on the output.
    """

    SKIP = frozenset(
        {"script", "style", "noscript", "template", "iframe", "object", "embed", "svg",
         "math", "head"}
    )
    BLOCK = frozenset(
        {"address", "article", "aside", "blockquote", "br", "dd", "details", "div", "dt",
         "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5",
         "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section", "summary",
         "table", "td", "th", "title", "tr", "ul"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.tags = 0
        self.scripts = 0
        self.styles = 0
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags += 1
        if tag == "script":
            self.scripts += 1
        elif tag == "style":
            self.styles += 1
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        self.tags += 1
        if tag in self.SKIP:
            # An end tag with no matching start must not unlock skipping.
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        # <title> sits inside <head>, which is skipped; the title is collected
        # separately above and never enters the body text.
        if self._skip_depth == 0:
            self.parts.append(data)


def _decode(raw: bytes) -> str:
    """Decode a fetched body without ever raising."""
    if raw.startswith(codecs.BOM_UTF8):
        return raw[len(codecs.BOM_UTF8) :].decode("utf-8", errors="replace")
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16", errors="replace")
    m = _META_CHARSET_RE.search(raw[:_SNIFF_BYTES])
    if m:
        name = (m.group(1) or m.group(2) or b"").decode("ascii", errors="replace")
        try:
            codec = codecs.lookup(name).name
        except LookupError:
            codec = ""
        # A declared UTF-16/32 is self-contradictory (the declaration itself
        # was readable as ASCII); the HTML standard says treat it as UTF-8.
        if codec and not codec.startswith(("utf-16", "utf-32")):
            return raw.decode(codec, errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _strip_invisible(text: str, counts: dict[str, int]) -> str:
    """Remove the enumerated invisible characters, adding to ``counts``."""
    text, n = _ZERO_WIDTH_RE.subn("", text)
    counts["zero_width"] += n
    text, n = _BIDI_RE.subn("", text)
    counts["bidi"] += n
    text, n = _CONTROL_RE.subn("", text)
    counts["control"] += n
    return text


def _collapse_whitespace(text: str) -> str:
    text = _HORIZONTAL_WS_RE.sub(" ", text)
    text = _SPACE_AROUND_NL_RE.sub("\n", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    """Cut at the last whitespace before ``max_chars``, or hard if there is none nearby.

    After ``_collapse_whitespace`` the only whitespace is space and newline.
    A boundary in the first half is not used: cutting there to avoid
    splitting one huge token would discard most of the budget.
    """
    if len(text) <= max_chars:
        return text, False
    head = text[:max_chars]
    boundary = max(head.rfind(" "), head.rfind("\n"))
    if boundary >= max_chars // 2:
        head = head[:boundary]
    return head.rstrip(), True


def _clean_short_field(value: str, limit: int, *, drop_all_whitespace: bool = False) -> str:
    """Normalise a title or URL: untrusted, so the same passes, then a length cap."""
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = _strip_invisible(value, {"zero_width": 0, "bidi": 0, "control": 0})
    value = _ANY_WS_RE.sub("", value) if drop_all_whitespace else _ANY_WS_RE.sub(" ", value)
    return value.strip()[:limit]


def purify(
    html: str | bytes,
    url: str = "",
    *,
    max_chars: int = 20_000,
    max_html_chars: int = 2_000_000,
) -> PurifiedPage:
    """Turn one retrieved page into inert plain text. Never raises on page content.

    ``max_html_chars`` is the input cap that makes the time bound a property
    of this module rather than of the fetcher; input beyond it is dropped and
    the page is marked truncated.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be >= 1")
    if max_html_chars < 1:
        raise ValueError("max_html_chars must be >= 1")

    counts = {
        "scripts": 0, "styles": 0, "tags_total": 0,
        "zero_width": 0, "bidi": 0, "control": 0,
        "fallback": 0, "parser_error": 0,
    }

    source = _decode(html) if isinstance(html, bytes) else html
    # Cleaned first: trafilatura logs the URL it is given when it declines a
    # page, and that log lives on the dual-homed host.
    clean_url = _clean_short_field(url, _URL_MAX_CHARS, drop_all_whitespace=True)
    truncated = False
    if len(source) > max_html_chars:
        source = source[:max_html_chars]
        truncated = True
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    source = _strip_invisible(source, counts)

    # The stdlib pass runs on every page: it is the source of the tag counts
    # and the title, and of the text if trafilatura declines.
    stripper = _TagStripper()
    try:
        stripper.feed(source)
        stripper.close()
        counts["scripts"] = stripper.scripts
        counts["styles"] = stripper.styles
        counts["tags_total"] = stripper.tags
        fallback_text = "".join(stripper.parts)
        title = "".join(stripper.title_parts)
    except Exception:  # the parser has assert sites; a page must not take the gateway down
        log.warning("html parser raised on a %d-char page; counts unavailable", len(source))
        counts["parser_error"] = 1
        fallback_text = ""
        title = ""

    text: str | None = None
    try:
        text = trafilatura.extract(
            source,
            url=clean_url or None,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
            output_format="txt",
        )
    except Exception as exc:  # trafilatura is third-party code over adversarial input
        log.warning("trafilatura raised %s; using fallback stripper", type(exc).__name__)
    if text is None or not text.strip():
        text = fallback_text
        counts["fallback"] = 1

    text = _strip_invisible(text, counts)
    text = _collapse_whitespace(text)
    text, cut = _truncate(text, max_chars)
    truncated = truncated or cut

    return PurifiedPage(
        text=text,
        title=_clean_short_field(title, _TITLE_MAX_CHARS),
        url=clean_url,
        truncated=truncated,
        stripped=counts,
    )


def envelope(page: PurifiedPage, evidence_id: str) -> str:
    """Wrap purified text so the model can tell where the untrusted part begins and ends.

    The two delimiters written here are the only ones in the output: every
    ``<`` that starts an envelope tag inside the text becomes ``&lt;`` first.
    Attribute values are HTML-escaped; the URL is page-controlled.
    """
    body = _ENVELOPE_FORGERY_RE.sub("&lt;", page.text)
    return (
        f'<{ENVELOPE_TAG} id="{escape(evidence_id, quote=True)}" trust="LOW" '
        f'url="{escape(page.url, quote=True)}">\n{body}\n</{ENVELOPE_TAG}>'
    )
