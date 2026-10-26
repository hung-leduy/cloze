"""The calibration script's blind sheet, its read-back, and its statistics.

The sheet is the one place a labeller meets the metric, so what matters most is
what it leaves out: no column may carry the metric's verdict or its binding.
The read-back matters second: a filled sheet has to be turned into verdicts by
the metric's own comparison against the key, or agreement would measure two
different rules rather than two readers.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import calibrate_faithfulness as C  # noqa: E402
from privdeep.eval.faithfulness import AMBIGUOUS, FABRICATED, score  # noqa: E402

REPORT = """# Budget

Of the 250,000.00 USD authorised for Project Zephyr, 187,432.55 USD had been
committed, leaving 62,567.45 USD uncommitted. Pilot Kestrel was reviewed.

Committed funds of 51,237.75 USD were recorded. Project Aurora and Project
Zephyr report 120,000.00 USD as the unspent balance. A further 999,111.22 USD
was noted.

| Project | Authorised (USD) | Spent (USD) |
| --- | --- | --- |
| Project Zephyr | 187,432.55 | 250,000.00 |
"""


@pytest.fixture
def key():
    return C._key()


@pytest.fixture
def sheet(tmp_path, key) -> tuple[Path, Path]:
    report = tmp_path / "report.md"
    report.write_text(REPORT, encoding="utf-8")
    out = tmp_path / "blind" / "report.csv"
    C.export_sheet(report, key, out)
    return report, out


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _fill(path: Path, labels: list[tuple[str, str]]) -> None:
    rows = _rows(path)
    for row, (ref, att) in zip(rows, labels, strict=True):
        row["referent_label"], row["attribute_label"] = ref, att
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=C.SHEET_COLUMNS)
        w.writeheader()
        w.writerows(rows)


def _as_metric(o) -> tuple[str, str]:
    """The labels a reader who agreed with the metric would write."""
    ref = C.UNCLEAR if o.referent_verdict == AMBIGUOUS else (o.referent or C.NONE)
    return ref, o.attribute or C.NONE


class TestBlindSheet:
    def test_one_row_per_occurrence_and_no_verdict_columns(self, sheet, key):
        report, out = sheet
        rows = _rows(out)
        assert len(rows) == len(score(REPORT, key).occurrences)
        assert tuple(rows[0]) == C.SHEET_COLUMNS
        for leak in ("verdict", "referent", "attribute", "scope", "belongs", "value",
                     "tied", "fact"):
            assert not [c for c in C.SHEET_COLUMNS
                        if leak in c and not c.endswith("_label")], leak

    def test_label_columns_are_empty(self, sheet):
        for row in _rows(sheet[1]):
            assert row["referent_label"] == row["attribute_label"] == row["note"] == ""

    def test_no_metric_output_appears_in_any_cell(self, sheet, key):
        verdicts = {"CORRECT", "MISBOUND", "PARTIAL", "UNBOUND", "FABRICATED",
                    "MATCH", "MISMATCH", "UNRESOLVED", "AMBIGUOUS"}
        names = set(key.attributes) | set(key.referents)
        for row in _rows(sheet[1]):
            for cell in row.values():
                assert not (set(cell.split()) & (verdicts | names)), cell

    def test_each_row_marks_its_own_numeral(self, sheet):
        rows = _rows(sheet[1])
        for row in rows:
            assert f"[[{row['numeral']}]]" in row["sentence"]
        # Two occurrences in one sentence get two different marks.
        first = [r["sentence"] for r in rows[:3]]
        assert len(set(first)) == 3

    def test_a_table_row_carries_its_header(self, sheet):
        rows = [r for r in _rows(sheet[1]) if r["sentence"].startswith("|")]
        assert len(rows) == 2
        assert all("Authorised (USD)" in r["before"] for r in rows)

    def test_prose_carries_the_paragraph_before_it(self, sheet):
        (row,) = [r for r in _rows(sheet[1]) if "[[51,237.75]]" in r["sentence"]]
        assert row["before"] == ""   # first sentence of its paragraph
        (row,) = [r for r in _rows(sheet[1]) if "[[120,000.00]]" in r["sentence"]]
        assert "Committed funds" in row["before"]
        assert row["section"] == "Budget"


DUPLICATED = """# Summary

Spending was reviewed. Project Zephyr had 187,432.55 USD committed of 250,000.00 USD.

| Project | Spent (USD) |
| --- | --- |
| Project Zephyr | 187,432.55 |

# Detail

The second review restated it. Project Zephyr had 187,432.55 USD committed of 250,000.00 USD.

| Project | Authorised (USD) |
| --- | --- |
| Project Zephyr | 187,432.55 |
"""


class TestDuplicatedText:
    """A sentence or table row repeated verbatim gets each copy's own surroundings.

    Locating a row by `text.find(context)` gave every later copy the first
    copy's section and paragraph, so a labeller would read the summary's
    heading above a figure that sits in the detail section.
    """

    @pytest.fixture
    def rows(self, tmp_path, key):
        report = tmp_path / "dup.md"
        report.write_text(DUPLICATED, encoding="utf-8")
        out = tmp_path / "dup.csv"
        assert C.export_sheet(report, key, out) == 6
        return _rows(out)

    def test_each_copy_of_a_sentence_has_its_own_section_and_paragraph(self, rows):
        prose = [r for r in rows if not r["sentence"].startswith("|")]
        assert [r["section"] for r in prose] == ["Summary"] * 2 + ["Detail"] * 2
        assert [r["before"] for r in prose] == (
            ["Spending was reviewed."] * 2 + ["The second review restated it."] * 2)
        # Both numerals of each copy are still marked in turn.
        assert "[[187,432.55]]" in prose[2]["sentence"]
        assert "[[250,000.00]]" in prose[3]["sentence"]

    def test_each_copy_of_a_table_row_has_its_own_header(self, rows):
        table = [r for r in rows if r["sentence"].startswith("|")]
        assert [r["section"] for r in table] == ["Summary", "Detail"]
        assert "Spent (USD)" in table[0]["before"]
        assert "Authorised (USD)" in table[1]["before"]

    def test_starts_follow_document_order(self, key):
        occ = score(DUPLICATED, key).occurrences
        text = C._normalised(DUPLICATED)
        starts = C._context_starts(text, occ)
        assert -1 not in starts
        numerals = [at + o.offset for o, at in zip(occ, starts, strict=True)]
        assert numerals == sorted(numerals) and len(set(numerals)) == len(numerals)
        for o, at in zip(occ, starts, strict=True):
            assert text[at + o.offset:].startswith(o.surface)


class TestReadBack:
    def test_an_unfilled_sheet_is_refused(self, sheet, key):
        with pytest.raises(SystemExit, match="unfilled"):
            C.main(["--report", str(sheet[0]), "--labels", str(sheet[1])])

    def test_a_label_outside_the_vocabulary_is_refused(self, sheet, key):
        occ = score(REPORT, key).occurrences
        _fill(sheet[1], [("ZEPHYR", "BUDGETISH")] + [_as_metric(o) for o in occ[1:]])
        with pytest.raises(SystemExit, match="BUDGETISH"):
            C.main(["--report", str(sheet[0]), "--labels", str(sheet[1])])

    def test_a_reader_who_agrees_with_the_metric_agrees_on_every_axis(
            self, sheet, key, capsys):
        occ = score(REPORT, key).occurrences
        _fill(sheet[1], [_as_metric(o) for o in occ])
        labels = C._sheet_labels(sheet[1], occ, key)
        for o, lab in zip(occ, labels, strict=True):
            assert (o.verdict, o.referent_verdict, o.attribute_verdict) == (
                lab["overall"], lab["referent"], lab["attribute"])
        assert C.main(["--report", str(sheet[0]), "--labels", str(sheet[1])]) == 0
        out = capsys.readouterr().out
        n = len(occ)
        gold = sum(o.verdict != FABRICATED for o in occ)
        assert gold < n       # the fixture has a numeral outside the key
        head, rest = out.split("attribute axis, gold-valued occurrences (headline)")[1] \
            .split(f"attribute axis, all rows (includes {n - gold} outside the key")
        assert f"agreement                  {gold}/{gold}" in head
        assert "Cohen kappa                1.000" in head
        assert f"agreement                  {n}/{n}" in rest

    def test_labels_become_verdicts_through_the_key(self, sheet, key):
        occ = score(REPORT, key).occurrences
        labels = [_as_metric(o) for o in occ]
        labels[0] = ("ZEPHYR", "SPENT")      # 250,000.00 is Zephyr's authority
        labels[1] = ("OTHER", "OTHER")       # a binding the key has no name for
        _fill(sheet[1], labels)
        got = C._sheet_labels(sheet[1], occ, key)
        assert (got[0]["referent"], got[0]["attribute"], got[0]["overall"]) == (
            "MATCH", "MISMATCH", "MISBOUND")
        assert (got[1]["referent"], got[1]["attribute"]) == ("MISMATCH", "MISMATCH")

    def test_a_numeral_outside_the_key_cannot_disagree(self, sheet, key):
        occ = score(REPORT, key).occurrences
        i = next(i for i, o in enumerate(occ) if o.verdict == FABRICATED)
        labels = [_as_metric(o) for o in occ]
        labels[i] = ("ZEPHYR", "SPENT")
        _fill(sheet[1], labels)
        got = C._sheet_labels(sheet[1], occ, key)[i]
        assert (got["overall"], got["attribute"]) == (FABRICATED, "UNRESOLVED")

    def test_a_stale_sheet_is_refused(self, sheet, key):
        occ = score(REPORT, key).occurrences
        _fill(sheet[1], [_as_metric(o) for o in occ])
        sheet[0].write_text(REPORT.replace("Of the 250,000.00", "Of the 250,000"),
                            encoding="utf-8")
        with pytest.raises(SystemExit, match="re-export"):
            C.main(["--report", str(sheet[0]), "--labels", str(sheet[1])])

    def test_several_reports_pool(self, sheet, key, tmp_path, capsys):
        occ = score(REPORT, key).occurrences
        _fill(sheet[1], [_as_metric(o) for o in occ])
        assert C.main(["--report", str(sheet[0]), "--labels", str(sheet[1]),
                       "--report", str(sheet[0]), "--labels", str(sheet[1])]) == 0
        out = capsys.readouterr().out
        assert f"pooled over 2 reports ({2 * len(occ)} occurrences)" in out

    def test_attribute_disagreements_are_printed(self, sheet, key, capsys):
        occ = score(REPORT, key).occurrences
        labels = [_as_metric(o) for o in occ]
        labels[0] = ("ZEPHYR", "SPENT")
        _fill(sheet[1], labels)
        C.main(["--report", str(sheet[0]), "--labels", str(sheet[1])])
        out = capsys.readouterr().out.split("--- attribute-axis disagreements ---")[1]
        assert "[1] '250,000.00'  metric=MATCH/AUTHORISED" in out
        assert "hand=MISMATCH (labelled SPENT)" in out


class TestAttributeKappa:
    """Kappa is headlined on gold-valued rows; rows outside the key agree trivially."""

    @staticmethod
    def _pair(verdict: str, metric: str, hand: str):
        return SimpleNamespace(verdict=verdict, attribute_verdict=metric), {"attribute": hand}

    def test_rows_outside_the_key_inflate_the_all_rows_kappa(self):
        gold = [self._pair("CORRECT", "MATCH", "MATCH"),
                self._pair("MISBOUND", "MISMATCH", "MISMATCH"),
                self._pair("MISBOUND", "MATCH", "MISMATCH"),
                self._pair("PARTIAL", "UNRESOLVED", "MATCH")]
        outside = [self._pair(FABRICATED, "UNRESOLVED", "UNRESOLVED")] * 4
        k = C._attribute_kappas(gold + outside)
        assert k["attribute_gold"] == pytest.approx(C.cohen_kappa(
            ["MATCH", "MISMATCH", "MISMATCH", "MATCH"],
            ["MATCH", "MISMATCH", "MATCH", "UNRESOLVED"]))
        assert k["attribute"] > k["attribute_gold"] + 0.3

    def test_all_outside_the_key_leaves_the_headline_undefined(self):
        k = C._attribute_kappas([self._pair(FABRICATED, "UNRESOLVED", "UNRESOLVED")] * 3)
        assert k["attribute_gold"] is None


class TestKappa:
    def test_perfect_agreement(self):
        assert C.cohen_kappa(["A", "B", "A"], ["A", "B", "A"]) == 1.0

    def test_textbook_value(self):
        # 2x2 with po = 0.7, pe = 0.5 -> 0.4.
        a = ["Y"] * 5 + ["N"] * 5
        b = ["Y"] * 4 + ["N"] + ["Y"] * 2 + ["N"] * 3
        assert C.cohen_kappa(a, b) == pytest.approx(0.4)

    def test_undefined_when_both_raters_use_one_category(self):
        assert C.cohen_kappa(["A", "A"], ["A", "A"]) is None
        assert C.cohen_kappa([], []) is None
