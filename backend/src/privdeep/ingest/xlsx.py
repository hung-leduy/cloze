r"""Loader for .xlsx workbooks into the canonical `Document` model.

Why a fixed serialisation
-------------------------
Everything downstream of ingestion (the shingle filter, the slot masker, the
reintegrator) works on `Document.text` and on character offsets into it;
nothing re-opens the source file. So a workbook has to become ONE string under
a rule that (a) is byte-for-byte reproducible across loads and (b) keeps every
cell locatable by a `Span` that slices exactly to the cell's rendered value.
The contract's `Document.__post_init__` re-checks (b) for every cell, so a
loader whose offsets drift fails at construction rather than at reintegration.

The rule
--------
For each worksheet, in workbook order::

    ## sheet: <name>\n
    <r1c1>\t<r1c2>\t...\t<r1cN>\n
    ...
    <rMc1>\t...\t<rMcN>\n

with one blank line between sheets and none after the last. The rectangle is
A1 through (max_row, max_column) as openpyxl reports them, so within a sheet
line k after the header is row k and tab-separated field j is column j, for
every row. Empty cells render as "" and still occupy their field. openpyxl
reports A1:A1 for a sheet with no cells, so an empty sheet renders as its
header plus one empty row.

Values render by the Python type openpyxl returns:

* ``str``: as is, except that each ``\t`` and each ``\n`` becomes one space.
  A tab or newline inside a value is indistinguishable from a field or row
  boundary, which is the one thing the offset scheme cannot survive. This is
  lossy for such cells: `Cell.value` and the text hold the flattened form,
  and the original is not recoverable from the Document.
* ``bool``: ``TRUE`` / ``FALSE``. Checked before ``int`` because ``bool`` is
  an ``int`` subclass.
* ``int``: ``str(v)``.
* ``float``: ``str(int(v))`` when integral, else ``repr(v)``. xlsx
  stores every number as a double and readers differ on whether ``42`` comes
  back as ``int`` or ``float``; collapsing integral floats makes the text
  independent of that. ``repr`` is the shortest string that round-trips to the
  same double, so no digit of a stored figure is lost.

  This rule and the code disagreed until 13 September: the code used
  ``format(v, "g")``, which keeps six significant digits, and the same bullet
  both promised ``repr`` and described ``"g"``. The effect was not cosmetic.
  A budget cell holding ``187432.55`` entered ``Document.text`` as ``187433``,
  ``51237.75`` as ``51237.8``. Every figure the spreadsheet actually contained
  was therefore absent from the canonical text, from the slot masker, from the
  shingle index that enforces Invariant 1, and from any report built on it.
* ``datetime`` / ``date`` / ``time``: ``isoformat()``. xlsx has no date-only
  type (a date is a serial number with a date format), so openpyxl returns
  date cells as ``datetime`` and they render with a ``T00:00:00`` suffix.
* ``None``: ``""``.
* anything else (``timedelta`` for duration formats, error literals):
  ``str(v)``, flattened like a ``str``.

A `Cell` is emitted for every cell whose rendered value is non-empty, so no
zero-length spans exist. `Cell.row` / `Cell.col` are openpyxl's own 1-based
coordinates, taken from the cell object rather than recomputed.

Limits, stated as limits
------------------------
* The workbook is opened with ``data_only=True``: a formula cell contributes
  its cached value, which is what the user saw in Excel, not the formula
  text. A file saved without cached values (openpyxl itself writes none)
  renders such cells as "".
* Hidden sheets, rows and columns are included; they are part of C_user.
  Chartsheets have no cells and are skipped. A merged range renders its value
  in the anchor cell and "" in the cells it covers.
* The whole workbook is materialised in memory (openpyxl's normal mode, whose
  extents are computed from the cells actually present). Read-only mode was
  rejected because its extents come from a header the writer may have left
  stale, and a stale extent would move every offset in the sheet.
* A carriage return inside a value is left alone. It does not disturb the
  offset scheme, but ``str.splitlines()`` would split on it, so consumers
  that count rows must split on ``\n`` only.
"""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path

import openpyxl

from privdeep.models.document import Cell, Document, DocumentKind, Span

__all__ = ["FIELD_SEP", "ROW_END", "SHEET_HEADER", "load_xlsx", "render_value"]

SHEET_HEADER = "## sheet: "
FIELD_SEP = "\t"
ROW_END = "\n"


def _flatten(s: str) -> str:
    """One space for each tab or newline, so a value cannot masquerade as a boundary."""
    return s.replace(FIELD_SEP, " ").replace(ROW_END, " ")


def render_value(v: object) -> str:
    """Render one cell value under the fixed rule in the module docstring."""
    if v is None:
        return ""
    if isinstance(v, str):
        return _flatten(v)
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    if isinstance(v, datetime | date | time):
        return v.isoformat()
    return _flatten(str(v))


def load_xlsx(path: Path, doc_id: str | None = None) -> Document:
    """Load a workbook into a Document whose text follows the module's fixed rule.

    `doc_id` defaults to the file stem. Loading the same file twice yields
    byte-identical text and equal cell lists.
    """
    path = Path(path)
    wb = openpyxl.load_workbook(path, data_only=True)

    parts: list[str] = []
    cells: list[Cell] = []
    pos = 0  # len("".join(parts)), maintained incrementally, in code points

    def emit(s: str) -> None:
        nonlocal pos
        parts.append(s)
        pos += len(s)

    for index, ws in enumerate(wb.worksheets):
        if index:
            emit(ROW_END)  # the blank line between sheets
        emit(f"{SHEET_HEADER}{_flatten(ws.title)}{ROW_END}")
        rows = ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=ws.max_column)
        for row in rows:
            for j, cell in enumerate(row):
                if j:
                    emit(FIELD_SEP)
                rendered = render_value(cell.value)
                if rendered:
                    cells.append(
                        Cell(
                            sheet=ws.title,
                            row=cell.row,
                            col=cell.column,
                            value=rendered,
                            span=Span(pos, pos + len(rendered)),
                        )
                    )
                    emit(rendered)
            emit(ROW_END)

    return Document(
        doc_id=doc_id or path.stem,
        kind=DocumentKind.XLSX,
        source_path=path,
        text="".join(parts),
        cells=cells,
        metadata={"sheet_count": str(len(wb.worksheets))},
    )
