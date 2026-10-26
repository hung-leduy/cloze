"""Unit tests for the .xlsx loader.

Every workbook is built with openpyxl into tmp_path; no binary fixture is
committed. The tests pin the serialisation rule literally (an exact expected
text), then the properties downstream stages rely on: every Cell's span slices
to its value, the text is identical across loads, find_all() lands on cell
spans, and row/col are openpyxl's own 1-based coordinates.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

import openpyxl
import pytest
from privdeep.ingest.xlsx import FIELD_SEP, ROW_END, load_xlsx, render_value
from privdeep.models.document import Document, DocumentKind, Span


@pytest.fixture
def book(tmp_path: Path) -> Path:
    """Two sheets; mixed types; an empty cell mid-row; a tab and a newline in values."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "People"
    ws.append(["Name", "Age", "Score", "Active", "Joined", "Note"])
    ws.append(["Alice Nguyen", 34, 91.5, True, datetime(2024, 1, 15, 10, 30), "line1\nline2"])
    ws.append(["Bob Tran", 28, None, False, date(2024, 3, 1), "tab\there"])
    ws.append(["Carol", 40.0, 3.14159265358979, True, time(9, 5), ""])
    budget = wb.create_sheet("Budget")
    budget.append(["Project", "Amount"])
    budget.append(["Zephyr", 1234567.5])
    budget.append(["Kestrel", 1200000])
    budget.append([None, "=B2+B3"])  # openpyxl writes no cached value for formulas
    path = tmp_path / "book.xlsx"
    wb.save(path)
    return path


EXPECTED_TEXT = (
    "## sheet: People\n"
    "Name\tAge\tScore\tActive\tJoined\tNote\n"
    "Alice Nguyen\t34\t91.5\tTRUE\t2024-01-15T10:30:00\tline1 line2\n"
    "Bob Tran\t28\t\tFALSE\t2024-03-01T00:00:00\ttab here\n"
    "Carol\t40\t3.14159265358979\tTRUE\t09:05:00\t\n"
    "\n"
    "## sheet: Budget\n"
    "Project\tAmount\n"
    "Zephyr\t1234567.5\n"
    "Kestrel\t1200000\n"
    "\t\n"
)


class TestSerialisationRule:
    def test_text_is_exactly_the_fixed_rule(self, book: Path):
        assert load_xlsx(book).text == EXPECTED_TEXT

    def test_document_identity(self, book: Path):
        doc = load_xlsx(book)
        assert isinstance(doc, Document)
        assert doc.kind is DocumentKind.XLSX
        assert doc.doc_id == "book"
        assert doc.source_path == book
        assert doc.metadata["sheet_count"] == "2"
        assert load_xlsx(book, doc_id="custom").doc_id == "custom"

    def test_rows_stay_rectangular(self, book: Path):
        """Every data line of a sheet carries max_column - 1 tabs, empty cells included."""
        doc = load_xlsx(book)
        widths = {"People": 6, "Budget": 2}
        sheet = None
        for line in doc.text.split(ROW_END)[:-1]:
            if line.startswith("## sheet: "):
                sheet = line.removeprefix("## sheet: ")
            elif line == "" and sheet is not None and widths[sheet] > 1:
                continue  # the blank line between sheets
            else:
                assert line.count(FIELD_SEP) == widths[sheet] - 1, (sheet, line)

    def test_empty_cell_mid_row_keeps_its_field(self, book: Path):
        doc = load_xlsx(book)
        bob = [c for c in doc.cells if c.sheet == "People" and c.row == 3]
        assert [c.col for c in bob] == [1, 2, 4, 5, 6]  # C3 is empty and is not a Cell
        line = doc.text.split(ROW_END)[3]
        assert line.split(FIELD_SEP)[2] == ""

    def test_formula_without_cached_value_renders_empty(self, book: Path):
        """Documents the data_only limit: no cached value, no text."""
        doc = load_xlsx(book)
        assert not [c for c in doc.cells if c.sheet == "Budget" and c.row == 4]
        assert doc.text.endswith("Kestrel\t1200000\n\t\n")


class TestOffsets:
    def test_every_cell_span_slices_to_its_value(self, book: Path):
        doc = load_xlsx(book)
        assert len(doc.cells) == 22 + 6
        for c in doc.cells:
            assert c.span.slice(doc.text) == c.value, c
            assert c.value, "empty values must not become cells"
            assert FIELD_SEP not in c.value and ROW_END not in c.value

    def test_tab_and_newline_in_values_are_flattened(self, book: Path):
        doc = load_xlsx(book)
        by_value = {c.value: c for c in doc.cells}
        assert "line1 line2" in by_value and "tab here" in by_value
        assert by_value["line1 line2"].span.slice(doc.text) == "line1 line2"
        assert by_value["tab here"].span.slice(doc.text) == "tab here"
        assert "line1\nline2" not in doc.text and "tab\there" not in doc.text

    def test_find_all_on_a_known_value_returns_the_cell_span(self, book: Path):
        doc = load_xlsx(book)
        alice = next(c for c in doc.cells if c.value == "Alice Nguyen")
        assert doc.find_all("Alice Nguyen") == [alice.span]
        zephyr = next(c for c in doc.cells if c.value == "Zephyr")
        assert doc.find_all("Zephyr") == [zephyr.span]

    def test_find_all_returns_every_cell_holding_a_repeated_value(self, tmp_path: Path):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "S"
        ws.append(["Hanoi", "x", "Hanoi"])
        ws.append(["y", "Hanoi", "z"])
        path = tmp_path / "rep.xlsx"
        wb.save(path)
        doc = load_xlsx(path)
        hanoi = [c.span for c in doc.cells if c.value == "Hanoi"]
        assert doc.find_all("Hanoi") == hanoi == sorted(hanoi, key=lambda s: s.start)
        assert len(hanoi) == 3

    def test_offsets_count_code_points_not_bytes(self, tmp_path: Path):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Unicode"
        ws.append(["Hà Nội", "Nguyễn Văn 😀", "after"])
        path = tmp_path / "u.xlsx"
        wb.save(path)
        doc = load_xlsx(path)
        after = next(c for c in doc.cells if c.value == "after")
        assert after.span.slice(doc.text) == "after"
        assert doc.text.encode("utf-8") != doc.text.encode("utf-32-le")  # sanity: non-ASCII
        for c in doc.cells:
            assert c.span.slice(doc.text) == c.value

    def test_spans_are_disjoint_and_in_text_order(self, book: Path):
        doc = load_xlsx(book)
        for a, b in zip(doc.cells, doc.cells[1:], strict=False):
            assert a.span.end <= b.span.start
            assert not a.span.overlaps(b.span)


class TestDeterminism:
    def test_loading_twice_is_byte_identical(self, book: Path):
        first, second = load_xlsx(book), load_xlsx(book)
        assert first.text == second.text
        assert first.text.encode("utf-8") == second.text.encode("utf-8")
        assert first.cells == second.cells

    def test_same_content_different_file_is_identical(self, book: Path, tmp_path: Path):
        copy = tmp_path / "copy.xlsx"
        copy.write_bytes(book.read_bytes())
        assert load_xlsx(copy).text == load_xlsx(book).text
        assert load_xlsx(copy).cells == load_xlsx(book).cells


class TestCoordinates:
    def test_row_col_are_one_based_and_match_openpyxl(self, book: Path):
        doc = load_xlsx(book)
        wb = openpyxl.load_workbook(book, data_only=True)
        assert min(c.row for c in doc.cells) == 1 and min(c.col for c in doc.cells) == 1
        for c in doc.cells:
            assert render_value(wb[c.sheet].cell(row=c.row, column=c.col).value) == c.value
        alice = next(c for c in doc.cells if c.value == "Alice Nguyen")
        assert (alice.sheet, alice.row, alice.col) == ("People", 2, 1)
        assert wb["People"]["A2"].value == "Alice Nguyen"

    def test_sheet_starting_away_from_a1_keeps_line_and_field_positions(self, tmp_path: Path):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Offset"
        ws.cell(row=3, column=3, value="far")
        path = tmp_path / "off.xlsx"
        wb.save(path)
        doc = load_xlsx(path)
        assert doc.text == "## sheet: Offset\n\t\t\n\t\t\n\t\tfar\n"
        (far,) = doc.cells
        assert (far.row, far.col) == (3, 3)
        lines = doc.text.split(ROW_END)
        assert lines[far.row].split(FIELD_SEP)[far.col - 1] == "far"

    def test_empty_sheet_renders_header_and_one_empty_row(self, tmp_path: Path):
        wb = openpyxl.Workbook()
        wb.active.title = "Empty"
        wb.create_sheet("Data").append(["v"])
        path = tmp_path / "e.xlsx"
        wb.save(path)
        doc = load_xlsx(path)
        assert doc.text == "## sheet: Empty\n\n\n## sheet: Data\nv\n"
        assert [(c.sheet, c.row, c.col) for c in doc.cells] == [("Data", 1, 1)]


class TestRenderValue:
    @pytest.mark.parametrize(
        ("value", "rendered"),
        [
            (None, ""),
            ("plain", "plain"),
            ("a\tb\nc", "a b c"),
            (True, "TRUE"),
            (False, "FALSE"),
            (7, "7"),
            (-3, "-3"),
            (40.0, "40"),
            (-0.0, "0"),
            (91.5, "91.5"),
            (0.1 + 0.2, "0.30000000000000004"),
            (1234567.5, "1234567.5"),
            (3.14159265358979, "3.14159265358979"),
            (datetime(2024, 1, 15, 10, 30), "2024-01-15T10:30:00"),
            (date(2024, 3, 1), "2024-03-01"),
            (time(9, 5), "09:05:00"),
            (timedelta(hours=1, minutes=30), "1:30:00"),
        ],
    )
    def test_fixed_rule(self, value: object, rendered: str):
        assert render_value(value) == rendered

    def test_bool_is_not_rendered_as_int(self):
        assert render_value(True) != "1" and render_value(False) != "0"


def test_contract_rejects_a_drifted_span(book: Path):
    """The contract, not this loader, is the last line of defence; show it is armed."""
    doc = load_xlsx(book)
    bad = doc.cells[0]
    with pytest.raises(ValueError, match="claims"):
        Document(
            doc_id=doc.doc_id,
            kind=doc.kind,
            source_path=doc.source_path,
            text=doc.text,
            cells=[type(bad)(bad.sheet, bad.row, bad.col, bad.value, Span(1, 1 + bad.span.length))],
        )


class TestNoDigitOfAStoredFigureIsLost:
    """The rule the module docstring always promised, and the code did not keep.

    Until 13 September `render_value` used `format(v, "g")` — six significant
    digits — while the docstring in the same file said `repr(v)`. A budget cell
    holding 187432.55 entered `Document.text` as 187433.

    That is not a display concern. `Document.text` is the canonical text: the
    slot masker reads it, and the shingle filter that enforces Invariant 1
    indexes it. A figure absent from the text is absent from the index.
    Measured against an index built the old way, four of five spans carrying
    the true spreadsheet figures were ALLOWED out — "Zephyr spent 187432.55 of
    the authorised 250000 by August" among them. The tokeniser shows why:
    187432.55 is the two tokens 187432 and 55, while 187433 is one, so no
    window of the real figure ever matched.
    """

    @pytest.mark.parametrize("stored", [187432.55, 51237.75, 62567.45, 98210.5, 0.07])
    def test_a_fractional_figure_survives_verbatim(self, stored: float):
        assert render_value(stored) == repr(stored)
        assert float(render_value(stored)) == stored

    def test_a_large_fraction_does_not_become_scientific_notation(self):
        """1234567.5 rendered as 1.23457e+06 lost the figure and the cent."""
        assert render_value(1234567.5) == "1234567.5"

    def test_integral_floats_still_collapse(self):
        """Unchanged: readers disagree on whether 42 comes back int or float,
        so the text must not depend on which."""
        assert render_value(40.0) == "40" and render_value(-0.0) == "0"

    def test_the_figure_reaches_the_canonical_text(self, tmp_path):
        wb = openpyxl.Workbook()
        wb.active.append(["Spent", 187432.55])
        f = tmp_path / "b.xlsx"
        wb.save(f)
        assert "187432.55" in load_xlsx(f).text
