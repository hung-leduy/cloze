"""R1's local ledger, on the smoke corpus's real tables.

The corpus is generated into a temporary directory by the same script that
writes the gold key, so these tests read exactly the cells a live run reads.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from privdeep.ingest import load
from privdeep.models.document import Cell, Document, DocumentKind, Span
from privdeep.models.facts import ATTRIBUTE_CODES, FACT_RE, fact_token
from privdeep.tier1_local.fact_store import build_fact_store
from privdeep.tier1_local.header_lexicon import attribute_for_header, unit_for_header
from privdeep.tier1_local.slot_masker import SLOT_RE, Entity, LocalMappingTable, SlotCollisionError

SALT = b"fact-store-test-salt"
_GEN = Path(__file__).resolve().parents[3] / "scripts" / "make_smoke_corpus.py"


def _generator():
    spec = importlib.util.spec_from_file_location("make_smoke_corpus", _GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    g = _generator()
    d = tmp_path_factory.mktemp("corpus")
    g.write_xlsx(d / "budget.xlsx")
    g.write_docx(d / "board-minutes.docx")
    return [load(d / "budget.xlsx"), load(d / "board-minutes.docx")]


def session_table(*names: tuple[str, str]) -> LocalMappingTable:
    t = LocalMappingTable(SALT)
    for text, cat in names:
        t.slot_for(Entity(text, cat))
    return t


REFERENTS = (("Project Zephyr", "PROJECT"), ("Project Aurora", "PROJECT"),
             ("Pilot Kestrel", "PROJECT"))


@pytest.fixture(scope="module")
def store(corpus):
    table = session_table(*REFERENTS)
    return build_fact_store(corpus, table), table


def hex_of(table, text, cat="PROJECT"):
    return SLOT_RE.fullmatch(table.slot_for(Entity(text, cat))).group("hex")


def value(store_table, name, attr):
    s, t = store_table
    f = s.get(hex_of(t, name), attr)
    return None if f is None else f.rendering()


class TestVocabulary:
    def test_thirteen_codes_none_longer_than_eight(self):
        assert len(ATTRIBUTE_CODES) == 13 and max(map(len, ATTRIBUTE_CODES)) <= 8

    def test_the_bare_token_stays_within_the_entropy_skip_length(self):
        for code in ATTRIBUTE_CODES:
            assert len(fact_token("389a0ca5", code)) <= 24, code

    def test_fact_re_recognises_invented_attributes_so_they_can_be_refused(self):
        assert FACT_RE.fullmatch("⟦FACT:389a0ca5.SALARY⟧")
        assert not FACT_RE.fullmatch("⟦FACT:389A0CA5.AUTHAMT⟧")
        with pytest.raises(ValueError):
            fact_token("389a0ca5", "SALARY")


class TestHeaderLexicon:
    @pytest.mark.parametrize("header,code", [
        ("Budget (USD)", "AUTHAMT"), ("Authorised (USD)", "AUTHAMT"), ("Spent", "SPENTAMT"),
        ("Spent (USD)", "SPENTAMT"), ("Owner", "OWNERREF"), ("Site", "SITEREF"),
        ("Start", "DATESTRT"), ("Contract", "REFCODE")])
    def test_the_corpus_headers(self, header, code):
        assert attribute_for_header(header) == code

    @pytest.mark.parametrize("header", ["Raised by", "Date", "Risk", "Severity", "Project"])
    def test_headers_that_would_manufacture_a_fact_map_to_nothing(self, header):
        """`Raised by` is not ownership, however often the two coincide."""
        assert attribute_for_header(header) is None

    def test_a_header_matching_two_codes_is_dropped(self):
        assert attribute_for_header("Budget spent") is None

    def test_unit(self):
        assert unit_for_header("Budget (USD)") == "USD" and unit_for_header("Spent") is None


class TestTheZephyrRowFromCellsAlone:
    def test_authority_and_spend(self, store):
        assert value(store, "Project Zephyr", "AUTHAMT") == "250,000.00"
        assert value(store, "Project Zephyr", "SPENTAMT") == "187,432.55"

    def test_owner_site_start_contract(self, store):
        assert value(store, "Project Zephyr", "OWNERREF") == "Sarah Whitfield"
        assert value(store, "Project Zephyr", "SITEREF") == "Manchester"
        start = store[0].get(hex_of(store[1], "Project Zephyr"), "DATESTRT")
        assert start.value_key == "2026-06-01"
        assert value(store, "Project Zephyr", "REFCODE") == "NB-2026-0917"

    def test_sheet_and_minutes_agree_so_both_are_provenance(self, store):
        f = store[0].get(hex_of(store[1], "Project Zephyr"), "AUTHAMT")
        assert {p.sheet for p in f.provenance} == {"Budget", "table1"}
        assert set(f.surfaces) == {"250000", "250,000.00"} and f.unit == "USD"
        assert store[0].counters["fact_conflicts"] == 0

    def test_nothing_is_bound_from_the_risks_sheet(self, store):
        risks = [f for f in store[0].facts() for p in f.provenance if p.sheet == "Risks"]
        assert risks == []


class TestDerivations:
    def test_unspent_matches_the_figure_three_documents_state(self, store):
        f = store[0].get(hex_of(store[1], "Project Zephyr"), "UNSPNTAM")
        assert f.rendering() == "62,567.45" and f.derived

    def test_overrun_matches_the_figure_two_documents_state(self, store):
        assert value(store, "Pilot Kestrel", "OVRRUNAM") == "6,237.75"
        assert value(store, "Pilot Kestrel", "UNSPNTAM") is None

    def test_a_derived_figure_no_document_states_is_marked_derived(self, store):
        f = store[0].get(hex_of(store[1], "Project Aurora"), "UNSPNTAM")
        assert f.rendering() == "21,790.00" and f.derived

    def test_percentage(self, store):
        assert value(store, "Project Zephyr", "PCTSPENT") == "75.0%"


def table_doc(doc_id: str, rows: list[list[str]], sheet: str = "t1") -> Document:
    lines, cells, pos = [], [], 0
    for r, row in enumerate(rows, start=1):
        for c, v in enumerate(row, start=1):
            cells.append(Cell(sheet, r, c, v, Span(pos, pos + len(v))))
            pos += len(v) + 1
        lines.append("\t".join(row))
    return Document(doc_id, DocumentKind.XLSX, Path(f"{doc_id}.xlsx"),
                    "\n".join(lines) + "\n", cells=cells)


class TestRefusals:
    def test_two_sources_that_disagree_are_withheld_not_resolved(self):
        a = table_doc("a", [["Project", "Budget"], ["Project Zephyr", "250000"]])
        b = table_doc("b", [["Project", "Budget"], ["Project Zephyr", "260000"]])
        table = session_table(("Project Zephyr", "PROJECT"))
        s = build_fact_store([a, b], table)
        assert s.get(hex_of(table, "Project Zephyr"), "AUTHAMT") is None
        assert s.counters["fact_conflicts"] == 1

    def test_a_row_whose_key_was_never_masked_is_dropped(self):
        d = table_doc("a", [["Project", "Budget"], ["Project Nobody", "1"]])
        s = build_fact_store([d], session_table(("Project Zephyr", "PROJECT")))
        assert len(s) == 0 and s.counters["fact_dropped_no_referent"] == 1

    def test_different_currencies_do_not_merge(self):
        a = table_doc("a", [["Project", "Budget (USD)"], ["Project Zephyr", "100"]])
        b = table_doc("b", [["Project", "Budget (EUR)"], ["Project Zephyr", "100"]])
        s = build_fact_store([a, b], session_table(("Project Zephyr", "PROJECT")))
        assert len(s) == 0 and s.counters["fact_conflicts"] == 1

    def test_referents_sharing_hex_across_categories_are_refused(self, monkeypatch):
        d = table_doc("a", [["Project", "Budget"], ["Zephyr", "1"], ["Kestrel", "2"]])
        table = session_table(("Zephyr", "PROJECT"), ("Kestrel", "PERSON"))
        ids = list(table)
        fake = {ids[0]: "⟦SLOT:PROJECT_aaaaaaaa⟧", ids[1]: "⟦SLOT:PERSON_aaaaaaaa⟧"}
        from privdeep.tier1_local import fact_store as FS
        real = FS._referent_surfaces
        monkeypatch.setattr(FS, "_referent_surfaces",
                            lambda t: {k: fake[v] for k, v in real(t).items()})
        with pytest.raises(SlotCollisionError, match="share hex"):
            build_fact_store([d], table)

    def test_repr_carries_no_value(self, store):
        r = repr(store[0]) + repr(store[0].facts())
        # Spellings that cannot occur inside a slot id's hex by chance.
        for v in ("250,000.00", "187,432.55", "Whitfield", "Manchester", "NB-2026"):
            assert v not in r
