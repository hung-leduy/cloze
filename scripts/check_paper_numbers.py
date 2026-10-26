#!/usr/bin/env python3
"""Fail on any numeral in the manuscript that the fill pass did not put there.

Why this exists
---------------
Plan task PAP8 step 2, built with PAP5a. The fill pass
(``make_paper_tables.py --fill``) writes every figure from
eval/paper/numbers.json and tags each value it writes: the value is a run of
its own between a Word bookmark named ``pv_<tag>_<n>``, where ``<tag>`` is
:func:`value_tag` of the key. This check is position-bound. A numeral passes
only where it stands:

* inside such a span whose text is exactly ``numbers.json[key]`` today, as the
  fill prints it (a negative sign as U+2212, :func:`presented`), so a value
  from an older build is a failure, not a pass;
* in a structural position on the explicit allow-list below;
* in the References section, which is bibliographic.

Everything else fails, including a hand-typed numeral that happens to equal
some numbers.json value. Nothing in numbers.json is allowed globally, and
author-supplied ``meta`` values (names, ORCID, references, the declaration)
are allowed only inside their own spans.

What counts as a numeral
------------------------
A run of digits, with ``.`` or ``,`` between digit groups (``0.41``,
``12,345``), or a decimal written without its leading zero (``.41``), that does
not follow a letter, digit, underscore, point or comma. So ``R5``, ``P1``,
``G3``, ``sha256`` and ``F03`` are identifiers, and so is a hex word of seven
or more characters with a letter in it (a commit prefix), while ``5-grams``,
``600dpi``, ``7/41`` (two numerals) and ``12.5%`` (``12.5``) are numerals.

What is allowed outside a value span (the list is explicit)
-----------------------------------------------------------
``STRUCTURAL_CONSTANTS``: fixed facts of the venue or the design, each bound
to the words it must stand with (``10 pages``, ``600 dpi``, ``Wilson 95%``,
``5-grams``, ``13 codes``, ...) and with its source. ``CONTEXT_RULES``: a
heading's own section number; a label (``Table n`` up to the paper's
``PAPER_TABLES``, ``Fig. n`` up to ``PAPER_FIGURES``, ``Tier n`` up to 3,
``Section n`` only for a section number some heading carries); a citation
bracket whose integers are all between 1 and the number of reference entries;
the judge's ``1-5 scale``; a statute the paper cites, by its full number
(``Law No. 91/2025/QH15``, ``Decree 356/2025/ND-CP`` or ``/NĐ-CP``,
``Regulation (EU) 2016/679``, ``Art. n``). The result of a PAGE, NUMPAGES or
SECTIONPAGES field is a page number. Text in ``mc:Fallback`` duplicates its
``mc:Choice`` and is read once.

``[EDIT: ...]`` notes are author instructions and are checked like any other
text: the skeleton's notes quote pilot figures and page budgets, and they must
be deleted before submission. So is a ``[TABLE ... PLACEHOLDER]`` or
``[FIGURE ... PLACEHOLDER]`` paragraph the fill pass had nothing to insert for.
``--allow-edit-notes`` lists both as warnings instead, for drafting. An
unfilled ``«key»``, a value span whose key is unknown or whose text is not the
current value, and a value of ``n/a`` in running text outside a table always
fail. Number words (``three corpora``) are warnings: they cannot be traced to
a key and should be one.

Parts read: document, every header and footer, footnotes and endnotes. A
document from which no numeral at all is read fails.

Prose branches
--------------
A manuscript assembled by paper/tools/assemble_manuscript.py carries, in
docProps/custom.xml, how the alternatives of its conditional blocks were
chosen (``BRANCH_MODE_PROPERTY``) and, in numbers mode, every key term that
was evaluated with its truth then (``BRANCH_TERM_PROPERTY``). A sentence
chosen because ``h1_A_outcome == holds`` is as stale as an old value once
numbers.json says otherwise, and no numeral in it shows that. So each key term
is evaluated again against numbers.json: one whose truth has changed, or whose
key is gone, fails (``stale-branch``); so does a manuscript whose branches were
chosen by length for a page estimate (``branches``). Author terms are recorded
for the reader and not checked: no key carries them. A document without the
record (the skeleton, filled directly) has no branches to check.

Usage
-----
    python scripts/check_paper_numbers.py paper/PrivDeep_ICCIT2026_filled.docx \
        [--numbers eval/paper/numbers.json] [--allow-edit-notes]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent

__all__ = ["BRANCH_MODE_PROPERTY", "BRANCH_TERM_PROPERTY", "CONTEXT_RULES", "NUMERAL_RE",
           "PAPER_FIGURES", "PAPER_TABLES", "STRUCTURAL_CONSTANTS", "Finding", "Para",
           "Result", "Span", "branch_findings", "check", "check_paragraphs",
           "docx_paragraphs", "main", "numerals", "presented", "value_tag"]

NUMERAL_RE = re.compile(r"(?<![\w.,])(?:\d+(?:[.,]\d+)*|\.\d+)")
_WORD = re.compile(r"\w+")
_HEX = re.compile(r"[0-9a-f]{7,}")
VALUE_BOOKMARK = re.compile(r"^pv_([0-9a-f]{10})_\d+$")
# S13(5) of the simulated review of 2026-10-26 and scope §13.2(c) (presentation only; the
# author's request "đồng ý với đề xuất, chỉnh sửa toàn bộ theo yêu cầu"; written by the AI
# assistant): the fill pass prints a negative value with the minus sign U+2212, and
# numbers.json keeps its ASCII hyphen-minus. A hyphen after a letter, digit, point or bracket
# (a date, an id, a range) is not a sign.
_NEG_SIGN = re.compile(r"(?<![\w.\])])-(?=\.?\d)")


def presented(value: str) -> str:
    """`value` as the fill pass prints it: each negative sign as U+2212."""
    return _NEG_SIGN.sub("−", value)

PAGE_FIELDS = {"PAGE", "NUMPAGES", "SECTIONPAGES"}
NA = "n/a"

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def _w(tag: str) -> str:
    return f"{{{W}}}{tag}"


def value_tag(key: str) -> str:
    """The bookmark prefix the fill pass writes around the value of `key`."""
    return "pv_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]


# The paper's numbered tables and figures (plan Part B §8, paper outline:
# Tables 1-4, Figs. 1-3; the writing fallback, invoked 2026-09-30 (plan Part D
# AD31), folded Tables 3 and 4 into Table 3, and the author removed Fig. 3, the
# strip plot, on 2026-10-02 (Part D AD33); the change set of 2026-10-10 added
# Table 4, the hypotheses table, on 2026-10-15 (paper/reviews/
# fix_proposals_2026-10-10.json, TAB-IV)); Fig. 3, the per-corpus binding figure,
# replaced Table 3's score cells on 2026-10-18 at the author's choice (re-review
# of that day). On 2026-10-19 the properties table became Fig. 2, the mechanism
# figure (the author's request): three tables and four figures. A label past
# these is not a label of this paper.
PAPER_TABLES = 1  # since later on 2026-10-21: the hypotheses
PAPER_FIGURES = 3  # since later on 2026-10-21: the example, the listing, the results
PAPER_TIERS = 3


@dataclass(frozen=True)
class Constant:
    pattern: re.Pattern[str]
    source: str


# Numerals allowed outside a value span, each only with the words it must stand
# with, and each a fixed fact of the venue or of the design.
STRUCTURAL_CONSTANTS: dict[str, Constant] = {
    "10": Constant(re.compile(r"\b10\s+pages\b"),
                   "page limit, including references (paper/VENUE_FACTS.md)"),
    "150": Constant(re.compile(r"\b150\s+words\b"),
                    "abstract word limit (paper/VENUE_FACTS.md, template instruction)"),
    "600": Constant(re.compile(r"\b600\s*dpi\b"),
                    "figure resolution in dpi (paper/VENUE_FACTS.md)"),
    "95": Constant(re.compile(r"(?i)\bWilson\s+95\s*%|\b95\s*%\s*(?:CI\b|confidence|Wilson)"),
                   "confidence level of the Wilson interval"),
    "5": Constant(re.compile(r"\b5\s*[–-]\s*(?:grams?|words?)\b|\b5\s*[–-]\s*8\s*[–-]\s*grams?\b"),
                  "shingle n_min: five-word runs and 5-grams (shared/shingle_filter.py; "
                  "gateway SHINGLE_N_MIN)"),
    "8": Constant(re.compile(r"\b5\s*[–-]\s*8\s*[–-]\s*grams?\b|\b8\s*[–-]\s*grams?\b"),
                  "shingle n_max (gateway SHINGLE_N_MAX)"),
    "64": Constant(re.compile(r"\b64\s+(?:carry\s+)?paths\b"),
                   "per-path carry bound (gateway/main.py _CARRY_MAX_PATHS)"),
    "13": Constant(re.compile(r"\b13\s+(?:attribute\s+)?codes\b|\b13-code\b"),
                   "attribute codes in ATTRIBUTE_SCHEMA (privdeep/models/facts.py)"),
    # Track L's design constants (PRIVDEEP_ICCIT_SCOPE.md §12.3, §12.9): a
    # judgment is eligible with at least 4 annotators and at most 8,000
    # characters, a collection holds 4 judgments, and the cap is $15. The
    # counts of collections, judgments, runs and strings are keys (l_*).
    "4": Constant(re.compile(r"\b4\s+(?:annotators|judgments)\b"),
                  "TAB eligibility: at least 4 annotators; 4 judgments per collection "
                  "(scope §12.3; scripts/real_corpora/)"),
    "8,000": Constant(re.compile(r"\b8,000\s+characters\b"),
                      "TAB eligibility: at most 8,000 characters of text (scope §12.3)"),
    "15": Constant(re.compile(r"\$15\b|\b15 USD\b"),
                   "track L's cost cap in USD (scope §12.9)"),
}

# Numerals whose role is structural by where they stand. A rule's match span
# allows the numerals inside it; the label and citation rules also check the
# number itself (see _structural_spans).
CONTEXT_RULES: dict[str, re.Pattern[str]] = {
    "citation bracket": re.compile(r"\[(\d+(?:\s*[,–-]\s*\d+)*)\]"),
    "label": re.compile(r"(?i)(?:\b(Tables?|Figs?\.|Figures?|Tiers?|Sections?)|(§))\s*"
                        r"(\d+(?:\.\d+)*)(?:\s*(?:[–-]|,|and)\s*(\d+(?:\.\d+)*))?"),
    "judge scale": re.compile(r"\b1\s*[–-]\s*5\b(?=\s+scale)"),
    # Only the instruments the paper cites (references.json vnpdpl2025, decree356,
    # gdpr), each by its full number; no other number/year pair passes. An article
    # chain joins only paragraph-qualified numbers (Art. 4(5)/5(1)(c)), so a bare
    # "Art. 13/2023" leaves its second numeral unallowed.
    "statute": re.compile(r"\bLaw\s+(?:on\s+Personal\s+Data\s+Protection\s+)?(?:No\.\s*)?"
                          r"91/2025/QH15\b"
                          r"|\bDecree\s+(?:No\.\s*)?356/2025/N[DĐ]-CP\b"
                          r"|\bRegulation\s+\(EU\)\s+2016/679"
                          r"|\bArt(?:icle)?\.?\s*\d+(?:\(\d+\))*(?:/\d+(?:\(\d+\))+"
                          r"(?:\([a-z]\))?)*"),
}
HEADING_NUMBER = re.compile(r"^\s*(\d+(?:\.\d+)*)")
EDIT_NOTE = re.compile(r"^\s*\[EDIT:")
PLACEHOLDER = re.compile(r"«[^»]*»")
BLOCK_PLACEHOLDER = re.compile(r"\[(?:TABLE|FIGURE)[^\]]*PLACEHOLDER\]")
REF_ENTRY = re.compile(r"^\s*\[(\d+)\]")
NUMBER_WORDS = re.compile(r"(?i)\b(two|three|four|five|six|seven|eight|nine|ten|eleven|"
                          r"twelve|twenty|thirty|hundred|dozen)\b")

# The branch record paper/tools/assemble_manuscript.py writes (see "Prose
# branches"): the mode, then one property per evaluated term, numbered from 001,
# each "true: <term>" or "false: <term>".
BRANCH_MODE_PROPERTY = "PrivDeep branches"
BRANCH_TERM_PROPERTY = "PrivDeep branch term "
_BRANCH_KEY_TERM = re.compile(r"(true|false): ([A-Za-z0-9_]+) (==|!=) (.+)")
_BRANCH_AUTHOR_TERM = re.compile(r"(true|false): author: .+")
_CUSTOM_PART = "docProps/custom.xml"
_CUSTOM = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"


def numerals(text: str) -> list[tuple[str, int, int]]:
    out = []
    for m in NUMERAL_RE.finditer(text):
        w = _WORD.match(text, m.start())
        word = w.group(0) if w else ""
        if _HEX.fullmatch(word) and re.search(r"[a-f]", word):
            continue          # a commit or digest prefix, not a number
        out.append((m.group(0), m.start(), m.end()))
    return out


@dataclass
class Finding:
    numeral: str
    where: str
    context: str
    kind: str = "numeral"   # numeral | placeholder | stale-value | unknown-value | na-in-prose
                            # | edit-note | block-placeholder | number-word | empty
                            # | stale-branch | branches

    def line(self) -> str:
        return f"{self.kind:<17} {self.numeral!r:<14} {self.where:<28} …{self.context}…"


@dataclass
class Span:
    """A stretch of a paragraph's text the checker treats apart: a value the fill
    pass wrote (``kind='value'``, with its bookmark name) or a page-number field
    result (``kind='field'``)."""

    start: int
    end: int
    kind: str
    name: str = ""


@dataclass
class Para:
    text: str
    style: str
    where: str
    spans: list[Span] = field(default_factory=list)
    in_table: bool = False


@dataclass
class Result:
    fails: list[Finding]
    warns: list[Finding]
    numerals: int = 0
    values: int = 0
    paragraphs: int = 0


# ------------------------------------------------------------ reading a .docx

_PART = re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$")


def _styles(z: zipfile.ZipFile) -> dict[str, str]:
    from lxml import etree  # noqa: PLC0415 - a python-docx dependency
    if "word/styles.xml" not in z.namelist():
        return {}
    root = etree.fromstring(z.read("word/styles.xml"))
    out = {}
    for s in root.iter(_w("style")):
        name = s.find(_w("name"))
        out[s.get(_w("styleId"))] = name.get(_w("val")) if name is not None else ""
    return out


def _para_segments(p) -> tuple[str, list[Span]]:
    """The paragraph's text and its value and field spans, in document order.
    Text under mc:Fallback is skipped (it repeats mc:Choice)."""
    text: list[str] = []
    spans: list[Span] = []
    pos = 0
    open_bm: dict[str, tuple[str, int]] = {}      # w:id -> (name, start)
    fld_stack: list[dict[str, object]] = []

    def walk(el) -> None:
        nonlocal pos
        for ch in el:
            tag = ch.tag if isinstance(ch.tag, str) else ""
            if tag == f"{{{MC}}}Fallback":
                continue
            if tag == _w("bookmarkStart"):
                name = ch.get(_w("name")) or ""
                if VALUE_BOOKMARK.match(name):
                    open_bm[ch.get(_w("id"))] = (name, pos)
            elif tag == _w("bookmarkEnd"):
                got = open_bm.pop(ch.get(_w("id")), None)
                if got:
                    spans.append(Span(got[1], pos, "value", got[0]))
            elif tag == _w("fldChar"):
                kind = ch.get(_w("fldCharType"))
                if kind == "begin":
                    fld_stack.append({"instr": "", "result": None})
                elif kind == "separate" and fld_stack:
                    fld_stack[-1]["result"] = pos
                elif kind == "end" and fld_stack:
                    f = fld_stack.pop()
                    instr = str(f["instr"]).split()
                    if f["result"] is not None and instr and instr[0].upper() in PAGE_FIELDS:
                        spans.append(Span(int(f["result"]), pos, "field", instr[0].upper()))
            elif tag == _w("instrText") and fld_stack:
                fld_stack[-1]["instr"] = str(fld_stack[-1]["instr"]) + (ch.text or "")
            elif tag == _w("fldSimple"):
                start = pos
                walk(ch)
                instr = (ch.get(_w("instr")) or "").split()
                if instr and instr[0].upper() in PAGE_FIELDS:
                    spans.append(Span(start, pos, "field", instr[0].upper()))
                continue
            elif tag == _w("t"):
                s = ch.text or ""
                text.append(s)
                pos += len(s)
                continue
            elif tag in (_w("tab"), _w("br"), _w("cr")):
                text.append(" ")
                pos += 1
                continue
            elif tag == _w("noBreakHyphen"):
                # Word's non-breaking hyphen is a visible "-" ("5-grams"); a soft hyphen
                # (w:softHyphen) is invisible unless the line breaks there, and reads as
                # nothing, as it did before.
                text.append("-")
                pos += 1
                continue
            walk(ch)          # a text box's paragraph is read with its host
    walk(p)
    return "".join(text), sorted(spans, key=lambda s: (s.start, s.end))


def docx_paragraphs(path: Path) -> list[Para]:
    """Every top-level paragraph of the document, headers, footers, footnotes and
    endnotes, in order, with its style, its value spans and whether it sits in a
    table."""
    from lxml import etree  # noqa: PLC0415
    out: list[Para] = []
    with zipfile.ZipFile(path) as z:
        styles = _styles(z)
        names = [n for n in z.namelist() if _PART.match(n)]
        names.sort(key=lambda n: (0 if n.endswith("document.xml") else 1, n))
        for name in names:
            root = etree.fromstring(z.read(name))
            for i, p in enumerate(root.iter(_w("p"))):
                if any(True for _ in p.iterancestors(_w("p"))):
                    continue
                ps = p.find(_w("pPr"))
                st = ps.find(_w("pStyle")) if ps is not None else None
                sid = st.get(_w("val")) if st is not None else "Normal"
                text, spans = _para_segments(p)
                in_table = any(True for _ in p.iterancestors(_w("tc")))
                out.append(Para(text, styles.get(sid, sid), f"{name.rsplit('/', 1)[1]}:p{i}",
                                spans, in_table))
    return out


# ------------------------------------------------------------ checking

def _structural_spans(text: str, headings: set[str], n_refs: int) -> list[tuple[int, int]]:
    covered: list[tuple[int, int]] = []
    for c in STRUCTURAL_CONSTANTS.values():
        covered += [m.span() for m in c.pattern.finditer(text)]
    for m in CONTEXT_RULES["citation bracket"].finditer(text):
        ints = [int(x) for x in re.findall(r"\d+", m.group(1))]
        if ints and all(1 <= x <= n_refs for x in ints):
            covered.append(m.span())
    for m in CONTEXT_RULES["label"].finditer(text):
        word = (m.group(1) or m.group(2) or "").lower()
        nums = [x for x in (m.group(3), m.group(4)) if x]
        if word.startswith("tab"):
            ok = all(re.fullmatch(r"\d+", x) and 1 <= int(x) <= PAPER_TABLES for x in nums)
        elif word.startswith("fig"):
            ok = all(re.fullmatch(r"\d+", x) and 1 <= int(x) <= PAPER_FIGURES for x in nums)
        elif word.startswith("tier"):
            ok = all(re.fullmatch(r"\d+", x) and 1 <= int(x) <= PAPER_TIERS for x in nums)
        else:                                   # Section, §: a number a heading carries
            ok = all(x in headings for x in nums)
        if ok:
            covered.append(m.span())
    for rule in ("judge scale", "statute"):
        covered += [m.span() for m in CONTEXT_RULES[rule].finditer(text)]
    return covered


def check_paragraphs(paras: list[Para], numbers: dict[str, str], *,
                     allow_edit_notes: bool = False) -> Result:
    """Failures and warnings over the paragraphs, in order."""
    by_tag = {value_tag(k): k for k in numbers}
    headings: set[str] = set()
    n_refs = 0
    in_refs = False
    for p in paras:                       # first pass: section numbers and references
        if p.style.lower().startswith("heading"):
            in_refs = p.text.strip().lower() in ("references", "bibliography")
            m = HEADING_NUMBER.match(p.text)
            if m:
                headings.add(m.group(1))
        elif in_refs:
            m = REF_ENTRY.match(p.text)
            if m:
                n_refs = max(n_refs, int(m.group(1)))
    res = Result([], [], paragraphs=len(paras))
    in_refs = False
    for p in paras:
        is_heading = p.style.lower().startswith("heading")
        if is_heading:
            in_refs = p.text.strip().lower() in ("references", "bibliography")
            text = HEADING_NUMBER.sub(lambda m: " " * len(m.group(0)), p.text)
        else:
            text = p.text
        note = bool(EDIT_NOTE.match(text))
        for m in PLACEHOLDER.finditer(text):
            res.fails.append(Finding(m.group(0), p.where, _ctx(text, m.start(), m.end()),
                                     "placeholder"))
        for m in BLOCK_PLACEHOLDER.finditer(text):
            f = Finding(m.group(0), p.where, _ctx(text, m.start(), m.end()),
                        "block-placeholder")
            (res.warns if allow_edit_notes else res.fails).append(f)
        allowed: list[tuple[int, int]] = []
        for s in p.spans:
            if s.kind == "field":
                allowed.append((s.start, s.end))
                continue
            res.values += 1
            got = text[s.start:s.end]
            bm = VALUE_BOOKMARK.match(s.name)
            key = by_tag.get("pv_" + bm.group(1)) if bm else None
            # A failed span is reported once, as itself; its numerals are not
            # reported again below.
            allowed.append((s.start, s.end))
            if key is None:
                res.fails.append(Finding(got, p.where, _ctx(text, s.start, s.end),
                                         "unknown-value"))
            elif got != presented(numbers[key]):
                res.fails.append(Finding(got, p.where, f"{key} is now {numbers[key]!r}",
                                         "stale-value"))
            elif got.strip() == NA and not p.in_table:
                res.fails.append(Finding(got, p.where, _ctx(text, s.start, s.end),
                                         "na-in-prose"))
        if in_refs and not is_heading and not note:
            res.numerals += len(numerals(text))
            continue          # a bibliographic entry; an [EDIT] note there is still checked
        covered = allowed + _structural_spans(text, headings, n_refs)
        for n, a, b in numerals(text):
            res.numerals += 1
            if any(lo <= a and b <= hi for lo, hi in covered):
                continue
            f = Finding(n, p.where, _ctx(text, a, b), "edit-note" if note else "numeral")
            (res.warns if note and allow_edit_notes else res.fails).append(f)
        if not note:
            for m in NUMBER_WORDS.finditer(text):
                if not any(lo <= m.start() and m.end() <= hi for lo, hi in allowed):
                    res.warns.append(Finding(m.group(0), p.where,
                                             _ctx(text, m.start(), m.end()), "number-word"))
    if res.numerals == 0:
        res.fails.append(Finding("", "document", f"{len(paras)} paragraph(s) read, no "
                                 "numeral found: is this the filled manuscript?", "empty"))
    return res


def _ctx(text: str, a: int, b: int, w: int = 40) -> str:
    return text[max(0, a - w):b + w].replace("\n", " ")


def branch_findings(path: Path, numbers: dict[str, str]) -> list[Finding]:
    """Failures of the branch record against today's numbers.json (see "Prose
    branches"); none for a document without the record."""
    from lxml import etree  # noqa: PLC0415
    with zipfile.ZipFile(path) as z:
        if _CUSTOM_PART not in z.namelist():
            return []
        root = etree.fromstring(z.read(_CUSTOM_PART))
    props = {p.get("name"): "".join(p.itertext()) for p in root.iter(f"{{{_CUSTOM}}}property")}
    mode = props.get(BRANCH_MODE_PROPERTY)
    if mode is None:
        return []
    out = []
    if mode != "numbers":
        out.append(Finding(mode, _CUSTOM_PART, f"the prose branches were chosen by {mode!r} "
                           "for a page estimate, not from numbers.json", "branches"))
    for name in sorted(n for n in props if n.startswith(BRANCH_TERM_PROPERTY)):
        m = _BRANCH_KEY_TERM.fullmatch(props[name])
        if m is None:
            if not _BRANCH_AUTHOR_TERM.fullmatch(props[name]):
                out.append(Finding(props[name][:40], _CUSTOM_PART,
                                   f"{name}: unreadable branch record", "stale-branch"))
            continue                  # an author term: no key can re-check it
        was, key, op, value = m.group(1) == "true", m.group(2), m.group(3), m.group(4)
        term = f"{key} {op} {value}"
        if key not in numbers:
            out.append(Finding(key, _CUSTOM_PART, f"{term!r} chose a branch, and numbers.json "
                               f"has no {key!r}: reassemble", "stale-branch"))
        elif ((numbers[key] == value) == (op == "==")) != was:
            out.append(Finding(key, _CUSTOM_PART, f"{term!r} was {str(was).lower()} at "
                               f"assembly and is {str(not was).lower()} now ({key} is "
                               f"{numbers[key]!r}): reassemble", "stale-branch"))
    return out


def check(docx_path: Path, numbers_path: Path, *, allow_edit_notes: bool = False) -> Result:
    values = json.loads(numbers_path.read_text(encoding="utf-8"))
    res = check_paragraphs(docx_paragraphs(docx_path), values,
                           allow_edit_notes=allow_edit_notes)
    res.fails += branch_findings(docx_path, values)
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("docx", type=Path)
    ap.add_argument("--numbers", type=Path, default=_REPO / "eval" / "paper" / "numbers.json")
    ap.add_argument("--allow-edit-notes", action="store_true",
                    help="report numerals inside [EDIT: ...] notes and unfilled block "
                         "placeholders as warnings")
    args = ap.parse_args(argv)
    r = check(args.docx, args.numbers, allow_edit_notes=args.allow_edit_notes)
    for f in r.warns:
        print("WARN " + f.line())
    for f in r.fails:
        print("FAIL " + f.line())
    print(f"{args.docx}: {r.paragraphs} paragraph(s), {r.numerals} numeral(s) read, "
          f"{r.values} filled value(s); {len(r.fails)} failure(s), {len(r.warns)} warning(s)")
    return 1 if r.fails else 0


if __name__ == "__main__":
    sys.exit(main())
