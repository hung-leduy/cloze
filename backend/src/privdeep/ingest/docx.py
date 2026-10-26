"""Word (.docx) loader: body order preserved, tables serialised like spreadsheets.

Why the body is walked by hand
------------------------------
python-docx exposes ``document.paragraphs`` and ``document.tables`` as two
separate lists, and its ``iter_inner_content()`` walks only the body's direct
``w:p`` and ``w:tbl`` children. Concatenating the two lists loses the
interleaving: a table that sits between paragraph 2 and paragraph 3 in Word
lands after every paragraph in the text, and the ontology extractor, which
reads the canonical text top to bottom, binds it to the wrong context. All
three views also skip block-level content controls (``w:sdt``), which is how
contract and form templates carry their text, so that text would never reach
the shingle filter and would be missing from the report. This loader therefore
iterates ``document.element.body`` children in order, dispatches on the XML
tag, and descends into ``w:sdtContent``.

Serialisation, chosen for offset stability
------------------------------------------
* A body paragraph contributes its text plus one ``"\\n"`` and one block
  ``("para N", Span)`` covering the text without the newline. N is 1-based
  over body paragraphs, empty ones included, so ``para 12`` is the twelfth
  paragraph a reader counts in Word. Soft line breaks (``w:br``, ``w:cr``)
  stay as ``"\\n"`` inside the paragraph and tabs stay as ``"\\t"``; a block
  span is the unit of structure, not a line.
* Table i (1-based) contributes a header line ``"## table: i\\n"``, one line
  per row with cells joined by ``"\\t"``, then a blank line. Every non-blank
  cell becomes ``Cell(sheet=f"table{i}", row, col, value, span)`` with 1-based
  grid coordinates. This is the xlsx loader's row format, so the local SLM
  sees one tabular convention whatever the source file was.
* A tab or a newline inside a cell would read as a column or row boundary of
  that serialisation, so each ``"\\t"`` and each ``"\\n"`` becomes one space
  before the cell is written, and ``Cell.value`` is the flattened string. This
  is the xlsx loader's rule, character for character, including that a
  carriage return is left alone (python-docx never produces one: ``w:cr``
  renders as ``"\\n"``). It is lossy for such cells; the original is not
  recoverable from the Document. python-docx renders a multi-paragraph cell as
  newline-joined paragraphs, so this is the common case, not a corner.
* A merged cell has one ``w:tc`` element but occupies several grid positions,
  and python-docx returns that same element at every position it spans, both
  across columns (``gridSpan``) and down rows (``vMerge``). The value is
  written once, at the first position, and the other positions are written
  blank: the row keeps the grid width and the text is not duplicated.

Limits
------
* A table nested inside a cell is dropped: ``_Cell.text`` joins the cell's
  own paragraphs only. Headers, footers, footnotes, comments and text boxes are
  outside the body and are not read.
* Everything Word stores is a string, so there is no number rendering rule
  here; ``"1.250.000"`` is emitted as typed.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Iterator
from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml.etree import _Element

from privdeep.models.document import Cell, Document, DocumentKind, Span

__all__ = ["FIELD_SEP", "ROW_END", "load_docx"]

# Column and row delimiters of the tabular serialisation, as in the xlsx loader.
FIELD_SEP = "\t"
ROW_END = "\n"

_P = qn("w:p")
_TBL = qn("w:tbl")
_SDT = qn("w:sdt")
_SDT_CONTENT = qn("w:sdtContent")


def _flatten(s: str) -> str:
    """One space for each tab or newline, so a value cannot masquerade as a boundary."""
    return s.replace(FIELD_SEP, " ").replace(ROW_END, " ")


def _block_elements(container: _Element) -> Iterator[_Element]:
    """Yield ``w:p`` and ``w:tbl`` elements under `container` in document order.

    ``w:sectPr``, bookmarks and other non-content children are skipped. A
    ``w:sdt`` is transparent: its ``w:sdtContent`` is walked in place.
    """
    for child in container.iterchildren():
        if child.tag in (_P, _TBL):
            yield child
        elif child.tag == _SDT:
            content = child.find(_SDT_CONTENT)
            if content is not None:
                yield from _block_elements(content)


def _serialise_table(
    table: Table, index: int, pos: int, parts: list[str], cells: list[Cell]
) -> int:
    """Append table `index` to `parts` starting at offset `pos`; return the new offset."""
    header = f"## table: {index}{ROW_END}"
    parts.append(header)
    pos += len(header)
    sheet = f"table{index}"
    # w:tc elements already written. Holding the elements themselves keeps their
    # lxml proxies alive, which is what makes identity comparison valid.
    written: set[_Element] = set()
    for r, row in enumerate(table.rows, start=1):
        for c, cell in enumerate(row.cells, start=1):
            if c > 1:
                parts.append(FIELD_SEP)
                pos += 1
            tc = cell._tc  # the only handle python-docx gives on the underlying element
            if tc in written:
                continue  # continuation position of a merged cell: left blank
            written.add(tc)
            value = _flatten(cell.text)
            if value.strip():
                cells.append(Cell(sheet, r, c, value, Span(pos, pos + len(value))))
            parts.append(value)
            pos += len(value)
        parts.append(ROW_END)
        pos += 1
    parts.append(ROW_END)  # the blank line that closes the table
    return pos + 1


def load_docx(path: Path, doc_id: str | None = None) -> Document:
    """Load a .docx into the canonical document model (``kind=DocumentKind.DOCX``).

    `doc_id` defaults to the file stem. The file's SHA-256 is recorded in
    ``metadata["sha256"]`` for the audit manifest, alongside the paragraph and
    table counts.
    """
    path = Path(path)
    data = path.read_bytes()
    document = docx.Document(io.BytesIO(data))

    parts: list[str] = []
    cells: list[Cell] = []
    blocks: list[tuple[str, Span]] = []
    pos = 0
    n_para = 0
    n_table = 0
    for element in _block_elements(document.element.body):
        if element.tag == _P:
            n_para += 1
            text = Paragraph(element, document).text
            blocks.append((f"para {n_para}", Span(pos, pos + len(text))))
            parts.append(text + ROW_END)
            pos += len(text) + 1
        else:
            n_table += 1
            pos = _serialise_table(Table(element, document), n_table, pos, parts, cells)

    return Document(
        doc_id=doc_id or path.stem,
        kind=DocumentKind.DOCX,
        source_path=path,
        text="".join(parts),
        cells=cells,
        blocks=blocks,
        metadata={
            "sha256": hashlib.sha256(data).hexdigest(),
            "paragraphs": str(n_para),
            "tables": str(n_table),
        },
    )
