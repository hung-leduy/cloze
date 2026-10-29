"""The paper's page and type format: the ICCIT Word Template Instruction
(paper/ICCIT2026_template.docx) on the two-column layout and styles of the IEEE
conference template (paper/IEEE_conference_template.pdf, sha256 509483fb...7bbb8).

Why this exists
---------------
Until 2026-10-03 the manuscript followed the ICCIT instruction in one column. The
author then set the IEEE conference template (two columns, 0.75 in side margins,
no pagination, IEEE references). On 2026-10-25 the author gave the ICCIT
instruction again as the required format and chose to apply it in full where it
speaks ("Áp dụng đầy đủ"), keeping the IEEE template where it is silent: margins
of one inch on all sides, numbered pages, the running head on the page, the
instruction's reference style, 10 pt abstract and keywords, and no text,
caption or note below 8 pt (figure text, the Fig. 2 listing's included, is 7 pt or
more). paper/tools/make_skeleton.py and paper/tools/assemble_manuscript.py call
:func:`apply` on their documents; they and the fill pass of
scripts/make_paper_tables.py call :func:`paginate` last, and the tables are built
on the skeleton's styles, so the format lives in one place.

=================  ==========================================================
page               US Letter, 612 x 792 pt
margins            1.0 in on all sides (ICCIT: "Allow margins of at least one
                   inch (3 cm) on all sides"); text 6.5 in wide
columns            two of 3.125 in, 0.25 in apart (the IEEE template's
                   arrangement; the instruction prescribes none); the title
                   and the author block span both
body               Times New Roman 10 pt (ICCIT: "10-point type (Times New
                   Roman)"), justified, first line indented 14.4 pt (0.2 in),
                   line pitch 0.95 of single, no space between paragraphs
title              14 pt bold, centred
author block       name 11 pt, affiliation lines 10 pt, centred
abstract           10 pt bold, justified, not indented, "Abstract" in bold
                   italic followed by an em dash
keywords           10 pt bold italic, first line indented 14.4 pt
heading 1          10 pt small capitals, centred, numbered "I.", "II.", ...;
                   8 pt before, 4 pt after
heading 2          10 pt italic, flush left, lettered "A.", "B.", ...; 6 pt
                   before, 3 pt after
run-in heads       italic
bullets            the bullet 14.4 pt in, the text 32.4 pt in
table caption      above the table, 8 pt, centred, "Table I." in sentence case (the
                   author's choice of 2026-10-19, as in the VERA paper)
table text         8 pt, column heads bold; a table note 8 pt
figure caption     below the figure, 8 pt, centred; "Fig. 1" in the text
references         a head "References" (small capitals, centred, not numbered);
                   entries 8 pt, the number hanging 18 pt; the ICCIT
                   instruction's example style (assemble_manuscript.
                   format_reference), every author listed, no "et al."
pagination         the page number centred in the footer and the running head
                   centred in the header, 10 pt, on every page (ICCIT:
                   "Manuscript pages should be numbered consecutively", and "a
                   shortened version of the title suitable for the running
                   head, not exceeding 50-character spaces")
=================  ==========================================================

Captions, table text and references stay at 8 pt: the instruction does not say
that its 10-point rule covers them, and all type at 10 pt would fill the 10-page
limit (the author's choice of 2026-10-25, "Abstract 10 pt, ghi chú ≥ 8 pt").
Figures are 600 dpi or more (the ICCIT site).

Tables and figures are wider than a column, so each sits in a one-column section
of its own (:func:`span`), as the template's two-column figure does; Word and
LibreOffice balance the two columns above it. The drafts keep their own numbering
("§4.2", "Section 3", "Table 3"); :func:`ieee_labels` writes it the template's way
("Section IV-B", "Section III", "Table III") in the rendered text.
"""

from __future__ import annotations

import copy
import re
from typing import Any

TEMPLATE_PDF = "paper/IEEE_conference_template.pdf"
# The running head (ICCIT: "not exceeding 50-character spaces"); the assembler and the
# skeleton keep their own copy, and a test pins the three.
RUNNING_HEAD = "Cloze: Egress Monitor and Role-Binding Problem"

# Twentieths of a point (twips), as Word stores them.
PAGE_W, PAGE_H = 12240, 15840
MARGINS = {"top": 1440, "right": 1440, "bottom": 1440, "left": 1440,
           "header": 720, "footer": 720, "gutter": 0}
COLUMN_GAP = 360
TEXT_WIDTH_IN = 6.5
COLUMN_WIDTH_IN = 3.125
LINE_SPACING = 0.95
INDENT_PT = 14.4
BULLET_INDENT_PT = 32.4
REFERENCE_HANG_PT = 18.0
TABLE_PT = 8
TABLE_NOTE_PT = 8
CAPTION_PT = 8
AUTHOR_BLOCK_AFTER_PT = 20

# Style names. The first four are the template's own and keep their names, since
# scripts/make_paper_tables.py and scripts/check_paper_numbers.py look them up.
BODY = "Body Text"
BULLETS = "List Paragraph"
CELL = "Table Paragraph"
TITLE = "Paper Title"
AUTHOR = "Author"
AFFILIATION = "Affiliation"
ABSTRACT = "Abstract"
KEYWORDS = "Keywords"
TABLE_CAPTION = "Table Caption"
TABLE_NOTE = "Table Note"
FIGURE_CAPTION = "Figure Caption"
REFERENCE = "Reference"

_ROMAN = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
          (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))


def roman(n: int) -> str:
    if n < 1:
        raise ValueError(f"no Roman numeral for {n}")
    out = []
    for value, sym in _ROMAN:
        while n >= value:
            out.append(sym)
            n -= value
    return "".join(out)


def letter(n: int) -> str:
    if not 1 <= n <= 26:
        raise ValueError(f"no heading letter for {n}")
    return chr(ord("A") + n - 1)


def section_label(number: str) -> str:
    """'4' -> 'IV', '4.2' -> 'IV-B'."""
    parts = [int(x) for x in number.split(".")]
    if len(parts) > 2:
        raise ValueError(f"the template has two heading levels, not {number!r}")
    return roman(parts[0]) + ("-" + letter(parts[1]) if len(parts) == 2 else "")


_NUM = r"\d+(?:\.\d+)?"
_SEP = r"(?:,\s*(?:and\s+|or\s+)?|\s+and\s+|\s+or\s+)"
_SEC_LIST = re.compile(rf"§\s*({_NUM})((?:{_SEP}§\s*{_NUM})*)")
_SECTION_WORD = re.compile(rf"\b(Sections?)\s+({_NUM})((?:{_SEP}{_NUM})*)")
_RANGE = r"\s*[–-]\s*"
_TABLE_LIST = re.compile(r"\b(Tables?)\s+(\d+)((?:(?:" + _SEP + "|" + _RANGE + r")\d+)*)")


def _relabel_list(head: str, rest: str, label) -> str:
    """'3' + ', §4 and §5' -> 'III, IV and V' (each number through `label`)."""
    out = [label(head)]
    for sep, num in re.findall(rf"({_SEP}|{_RANGE})§?\s*({_NUM})", rest):
        out.append(sep + label(num))
    return "".join(out)


def ieee_labels(text: str) -> str:
    """The drafts' section and table numbers written as the template numbers them:
    '§4.2' and 'Section 4.2' -> 'Section IV-B', '§1, §5 and §8' -> 'Sections I, V
    and VIII', 'Table 3' -> 'Table III', 'Tables 2 and 3' -> 'Tables II and III'.
    Figures keep Arabic numbers, as in the template."""
    def secs(m: re.Match[str]) -> str:
        many = bool(m.group(2))
        return ("Sections " if many else "Section ") + _relabel_list(
            m.group(1), m.group(2), section_label)

    def words(m: re.Match[str]) -> str:
        return m.group(1) + " " + _relabel_list(m.group(2), m.group(3), section_label)

    def tables(m: re.Match[str]) -> str:
        return m.group(1) + " " + _relabel_list(m.group(2), m.group(3),
                                                lambda s: roman(int(s)))

    text = _SEC_LIST.sub(secs, text)
    text = _SECTION_WORD.sub(words, text)
    return _TABLE_LIST.sub(tables, text)


def table_label(label: str) -> str:
    """'Table 3' -> 'Table III', the caption label. The IEEE template writes it in
    capitals ('TABLE III.'); since 2026-10-19 the author's choice is a sentence-case
    caption, as in the author's VERA paper, so the label keeps its case."""
    m = re.fullmatch(r"Table\s+(\d+)", label.strip())
    if not m:
        raise ValueError(f"not a table label: {label!r}")
    return f"Table {roman(int(m.group(1)))}"


def figure_label(label: str) -> str:
    """'Fig. 1' -> 'Figure 1', the template's caption label."""
    m = re.fullmatch(r"Fig\.\s*(\d+)", label.strip())
    if not m:
        raise ValueError(f"not a figure label: {label!r}")
    return f"Figure {m.group(1)}"


# ------------------------------------------------------------------ Word

def _qn(tag: str) -> str:
    from docx.oxml.ns import qn  # noqa: PLC0415 - system interpreter only
    return qn(tag)


def _set_fonts(rpr, name: str) -> None:
    """Every script slot to `name`, and no theme font left to override it."""
    from docx.oxml import OxmlElement  # noqa: PLC0415
    fonts = rpr.find(_qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for attr in list(fonts.attrib):
        if attr.endswith("Theme") or attr.endswith("theme"):
            del fonts.attrib[attr]
    for slot in ("ascii", "hAnsi", "cs", "eastAsia"):
        fonts.set(_qn(f"w:{slot}"), name)


def _style(doc, name: str, base: str | None = "Normal"):
    from docx.enum.style import WD_STYLE_TYPE  # noqa: PLC0415
    try:
        st = doc.styles[name]
    except KeyError:
        st = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    if base and st.name != base:
        st.base_style = doc.styles[base]
    return st


def _para_style(doc, name: str, *, size: float, bold: bool = False, italic: bool = False,
                small_caps: bool = False, align: str = "justify", first: float = 0.0,
                left: float = 0.0, before: float = 0.0, after: float = 0.0,
                line: float | None = LINE_SPACING, keep_next: bool = False,
                base: str | None = "Normal") -> Any:
    from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: PLC0415
    from docx.shared import Pt, RGBColor  # noqa: PLC0415
    st = _style(doc, name, base)
    f = st.font
    f.name = "Times New Roman"
    _set_fonts(st.element.get_or_add_rPr(), "Times New Roman")
    f.size = Pt(size)
    f.bold = bold
    f.italic = italic
    f.small_caps = small_caps
    f.color.rgb = RGBColor(0, 0, 0)
    pf = st.paragraph_format
    pf.alignment = {"justify": WD_ALIGN_PARAGRAPH.JUSTIFY, "center": WD_ALIGN_PARAGRAPH.CENTER,
                    "left": WD_ALIGN_PARAGRAPH.LEFT}[align]
    pf.left_indent = Pt(left)
    pf.right_indent = Pt(0)
    pf.first_line_indent = Pt(first)
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line if line is not None else 1.0
    pf.keep_with_next = keep_next
    pf.widow_control = True
    return st


def _section_layout(sect_pr, cols: int, start: str | None) -> None:
    """Page size, margins, `cols` equal columns and the section's start type; no
    header or footer reference of its own, so the section inherits the first
    section's (:func:`paginate`)."""
    from docx.oxml import OxmlElement  # noqa: PLC0415
    for tag in ("w:headerReference", "w:footerReference", "w:titlePg"):
        for el in sect_pr.findall(_qn(tag)):
            sect_pr.remove(el)
    for tag in ("w:type", "w:pgSz", "w:pgMar", "w:cols"):
        el = sect_pr.find(_qn(tag))
        if el is not None:
            sect_pr.remove(el)
    # CT_SectPr's sequence: (header/footer refs), footnotePr, endnotePr, type,
    # pgSz, pgMar, paperSrc, pgBorders, lnNumType, pgNumType, cols, ...
    anchor = None
    for tag in ("w:endnotePr", "w:footnotePr"):
        anchor = sect_pr.find(_qn(tag))
        if anchor is not None:
            break
    seq = []
    if start:
        t = OxmlElement("w:type")
        t.set(_qn("w:val"), start)
        seq.append(t)
    sz = OxmlElement("w:pgSz")
    sz.set(_qn("w:w"), str(PAGE_W))
    sz.set(_qn("w:h"), str(PAGE_H))
    seq.append(sz)
    mar = OxmlElement("w:pgMar")
    for k in ("top", "right", "bottom", "left", "header", "footer", "gutter"):
        mar.set(_qn(f"w:{k}"), str(MARGINS[k]))
    seq.append(mar)
    for el in reversed(seq):
        if anchor is not None:
            anchor.addnext(el)
        else:
            sect_pr.insert(0, el)
    c = OxmlElement("w:cols")
    c.set(_qn("w:num"), str(cols))
    c.set(_qn("w:space"), str(COLUMN_GAP))
    before = mar
    for tag in ("w:paperSrc", "w:pgBorders", "w:lnNumType", "w:pgNumType"):
        el = sect_pr.find(_qn(tag))
        if el is not None:
            before = el
    before.addnext(c)


def apply(doc) -> None:
    """Page setup and styles of the template, on a document whose body may be empty.
    The body's last section is the two-column one; a builder ends the one-column
    title block with :func:`end_section` and puts wide blocks in :func:`span`."""
    from docx.shared import Pt  # noqa: PLC0415
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(10)
    _set_fonts(normal.element.get_or_add_rPr(), "Times New Roman")
    npf = normal.paragraph_format
    npf.space_before = npf.space_after = Pt(0)
    _para_style(doc, BODY, size=10, first=INDENT_PT)
    _para_style(doc, BULLETS, size=10, left=BULLET_INDENT_PT,
                first=INDENT_PT - BULLET_INDENT_PT)
    _para_style(doc, CELL, size=TABLE_PT, align="left", line=1.0)
    _para_style(doc, "Heading 1", size=10, small_caps=True, align="center", before=8,
                after=4, keep_next=True)
    _para_style(doc, "Heading 2", size=10, italic=True, align="left", before=6, after=3,
                keep_next=True)
    for h in ("Heading 1", "Heading 2"):
        pf = doc.styles[h].paragraph_format
        pf.left_indent = pf.first_line_indent = Pt(0)
    _para_style(doc, TITLE, size=14, bold=True, align="center", after=18, line=1.0)
    _para_style(doc, AUTHOR, size=11, align="center", before=0, line=1.0)
    _para_style(doc, AFFILIATION, size=10, align="center", line=1.0)
    # 10 pt since 2026-10-25 (the ICCIT instruction's "10-point type"; was 9).
    _para_style(doc, ABSTRACT, size=10, bold=True, after=10, line=1.0)
    _para_style(doc, KEYWORDS, size=10, bold=True, italic=True, first=INDENT_PT, after=6,
                line=1.0)
    # Sentence case, not the template's small capitals: the author's choice of
    # 2026-10-19 ("Caption tables sử dụng viết thường").
    _para_style(doc, TABLE_CAPTION, size=CAPTION_PT, small_caps=False, align="center",
                before=6, after=4, keep_next=True, line=1.0)
    # 6 pt after the note, near a figure caption's 8 (final export check of
    # 2026-10-25: the note ran into the next body line).
    _para_style(doc, TABLE_NOTE, size=TABLE_NOTE_PT, line=1.0, after=6)
    _para_style(doc, FIGURE_CAPTION, size=CAPTION_PT, align="center", before=4, after=8,
                line=1.0)
    # Left-aligned since 2026-10-25 (pre-submission audit): justified 8 pt lines with
    # long URLs and DOIs stretched their word spaces. 0.5 pt after each entry (was 2), set
    # when the IEEE layout had to fit 8 pages.
    _para_style(doc, REFERENCE, size=8, left=REFERENCE_HANG_PT, first=-REFERENCE_HANG_PT,
                after=0.5, line=1.0, align="left")
    body = doc.element.body
    sect = body.find(_qn("w:sectPr"))
    if sect is None:
        from docx.oxml import OxmlElement  # noqa: PLC0415
        sect = OxmlElement("w:sectPr")
        body.append(sect)
    _section_layout(sect, 2, "continuous")


def _page_field(par) -> None:
    """A PAGE field in `par`, with no cached result: Word and LibreOffice write the
    number when they lay out the page, and the saved file holds no numeral
    (scripts/check_paper_numbers.py reads headers and footers)."""
    from docx.oxml import OxmlElement  # noqa: PLC0415
    for kind, instr in (("begin", None), (None, " PAGE "), ("separate", None), ("end", None)):
        r = OxmlElement("w:r")
        if kind:
            fc = OxmlElement("w:fldChar")
            fc.set(_qn("w:fldCharType"), kind)
            r.append(fc)
        else:
            it = OxmlElement("w:instrText")
            it.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            it.text = instr
            r.append(it)
        par._p.append(r)


def paginate(doc, running_head: str) -> None:
    """The ICCIT instruction's pagination: the running head centred in the header
    and the page number centred in the footer, 10 pt, on every page. Both belong
    to the first section; every later section has no reference of its own
    (:func:`_section_layout`) and so inherits them. A header or footer the first
    section already has is kept (an earlier pass's, or the author's), so calling
    this again changes nothing; a header or footer part that no section uses (the
    instruction's own footer, left in the template's package) is dropped."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: PLC0415
    from docx.opc.constants import RELATIONSHIP_TYPE as RT  # noqa: PLC0415
    if len(running_head) > 50:
        raise ValueError(f"a running head of at most 50 characters, not {len(running_head)}")
    refs = (_qn("w:headerReference"), _qn("w:footerReference"))
    used = {ref.get(_qn("r:id")) for sec in doc.sections for ref in sec._sectPr
            if ref.tag in refs}
    for rid, rel in list(doc.part.rels.items()):
        if rel.reltype in (RT.HEADER, RT.FOOTER) and rid not in used:
            doc.part.drop_rel(rid)
    sec = doc.sections[0]
    for part, fill in ((sec.header, running_head), (sec.footer, None)):
        if not part.is_linked_to_previous:
            continue
        part.is_linked_to_previous = False
        par = part.paragraphs[0]
        ppr = par._p.get_or_add_pPr()
        for el in ppr.findall(_qn("w:pStyle")):
            ppr.remove(el)
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if fill:
            par.add_run(fill)
        else:
            _page_field(par)


# The author block in the form the author gave on 2026-10-26 (a Springer-style block:
# the names with the corresponding author's mark, the affiliation, then the e-mail
# addresses, "{hung.ld2, tam.th}@vgu.edu.vn"). The corresponding author is named last,
# so the mark follows the last name. Since 2026-10-28 the ORCID iDs stand on a line of
# their own after the e-mail line (the author's choice "ORCID đứng riêng 1 dòng", which
# replaced the same day's superscript iDs after the names), each followed by its author's
# name; the line is the assistant's form (paper/VENUE_FACTS.md). The e-mail line is in the
# affiliation's face, Times New Roman, since the author's report of 2026-10-26 ("lỗi
# font email tác giả") that its monospaced face (Courier New) was wrong; the ICCIT
# instruction names no face for it.
# U+FE0E asks for the plain (text) glyph. DejaVu Sans has a plain U+2709; a face that is
# not installed (Segoe UI Symbol under LibreOffice) fell back to a colour emoji face.
# Word without DejaVu Sans substitutes, and its symbol fallback draws the plain glyph.
CORRESPONDING_MARK = "(\u2709\ufe0e)"
ORCID_LABEL = "ORCID: "
MARK_FONT = "DejaVu Sans"


def _run_font(run, name: str) -> None:
    run.font.name = name
    _set_fonts(run._r.get_or_add_rPr(), name)


def author_block(doc, authors, affiliation: str, email: str):
    """The names (AUTHOR style), `authors` being (name, ORCID iD) pairs in order:
    "A and B", or "A, B and C", the last name, the corresponding author's, followed
    by the mark in superscript. Then the affiliation, the e-mail line and the ORCID
    line, "ORCID: iD (name); iD (name)" (AFFILIATION style, all in its face);
    returns the last paragraph, which the title block's section ends at."""
    p = doc.add_paragraph(style=AUTHOR)
    last = len(authors) - 1
    for i, (name, _orcid) in enumerate(authors):
        if i:
            p.add_run(" and " if i == last else ", ")
        p.add_run(name)
    mark = p.add_run(CORRESPONDING_MARK)
    mark.font.superscript = True
    _run_font(mark, MARK_FONT)
    doc.add_paragraph(affiliation, style=AFFILIATION)
    doc.add_paragraph(email, style=AFFILIATION)
    return doc.add_paragraph(ORCID_LABEL + "; ".join(f"{orcid} ({name})"
                                                     for name, orcid in authors),
                             style=AFFILIATION)


def _body_sect(doc):
    return doc.element.body.find(_qn("w:sectPr"))


def end_section(doc, p_el, cols: int, start: str | None = "continuous") -> None:
    """End a section at paragraph `p_el`: it carries a copy of the body's section
    properties with `cols` columns (Word stores a section's properties in its last
    paragraph, and the type is how that section starts)."""
    ppr = p_el.get_or_add_pPr()
    old = ppr.find(_qn("w:sectPr"))
    if old is not None:
        ppr.remove(old)
    sect = copy.deepcopy(_body_sect(doc))
    _section_layout(sect, cols, start)
    ppr.append(sect)


def _section_cols(p_el) -> int | None:
    ppr = p_el.find(_qn("w:pPr"))
    sect = ppr.find(_qn("w:sectPr")) if ppr is not None else None
    if sect is None:
        return None
    c = sect.find(_qn("w:cols"))
    return int(c.get(_qn("w:num"), "1")) if c is not None else 1


def span(doc, first_el, last_el) -> None:
    """Put the body elements from `first_el` to `last_el` (a table, figure or
    listing with its caption and notes) in a one-column section between two-column
    text. A block that follows another spanning block joins its section."""
    from docx.oxml import OxmlElement  # noqa: PLC0415
    w_p = _qn("w:p")
    prev = first_el.getprevious()
    if prev is not None and prev.tag == w_p and _section_cols(prev) == 1:
        prev.find(_qn("w:pPr")).remove(prev.find(_qn("w:pPr")).find(_qn("w:sectPr")))
    else:
        if prev is None or prev.tag != w_p:
            prev = OxmlElement("w:p")
            first_el.addprevious(prev)
        end_section(doc, prev, 2)
    if last_el.tag != w_p:
        tail = OxmlElement("w:p")
        last_el.addnext(tail)
        last_el = tail
    end_section(doc, last_el, 1)
