"""The abstract payload must carry shape and slots, and nothing the filter can see."""

from __future__ import annotations

from pathlib import Path

from privdeep.models.document import Document, DocumentKind
from privdeep.tier1_local.ontology_extractor import ConceptRelation, Extraction
from privdeep.tier1_local.slot_masker import Entity, SlotMasker
from privdeep.tier2_cloud.abstract_payload import build_abstract_payload

from shared.shingle_filter import ShingleFilter

TEXT = (
    "Project\tOwner\tSite\tBudget (USD)\n"
    "Project Zephyr\tNguyễn Thị Lan\tHanoi\t250000\n"
    "Risk\tHanoi pilot cancelled; revenue fell twelve percent after the June review\n"
)
ENTS = [Entity("Project Zephyr", "PROJECT"), Entity("Nguyễn Thị Lan", "PERSON"),
        Entity("Hanoi", "LOCATION")]
RELS = [ConceptRelation("INITIATIVE", "led by", "STAKEHOLDER"),
        ConceptRelation("INITIATIVE", "reported decline in", "FINANCIAL_METRIC")]


def setup():
    doc = Document("d1", DocumentKind.XLSX, Path("d.xlsx"), TEXT)
    mask = SlotMasker(b"salt").mask(doc, ENTS)
    ex = Extraction(entities=list(ENTS), relations=list(RELS))
    payload = build_abstract_payload("d1", ex, mask, n_cells=9, n_chars=len(TEXT))
    f = ShingleFilter(salt=b"gw")
    f.index_document(doc.text)
    f.seal()
    return doc, mask, payload, f


def test_payload_carries_slots_and_relations_but_no_originals():
    _, mask, payload, _ = setup()
    j = payload.to_json()
    assert len(payload.slots) == 3
    assert all(c in ("PROJECT", "PERSON", "LOCATION") for _, c in payload.slots)
    assert "reported decline in" in j and "FINANCIAL_METRIC" in j
    for e in ENTS:
        assert e.text not in j
    for sid, _ in payload.slots:
        assert sid in j and mask.table.original(sid) not in j


def test_masked_prose_is_refused_but_abstract_payload_is_admitted():
    """The finding from the first live run, pinned: masked text must NOT cross."""
    _, mask, payload, f = setup()
    assert f.inspect(mask.masked_text).blocked, "masked prose still carries verbatim 5-grams"
    assert not f.inspect(payload.to_json()).blocked, "abstract payload tripped containment"


def test_only_placed_slots_are_advertised():
    doc = Document("d", DocumentKind.MARKDOWN, Path("d.md"), "nothing here")
    mask = SlotMasker(b"s").mask(doc, [Entity("Absent", "ORG")])
    payload = build_abstract_payload("d", Extraction(entities=[], relations=[]), mask)
    assert payload.slots == () and mask.unmatched


# ---------------------------------------------------------------- R1 payload

import pytest  # noqa: E402
from privdeep.models.facts import ATTRIBUTE_CODES, FACT_RE  # noqa: E402
from privdeep.tier2_cloud.abstract_payload import (  # noqa: E402
    ATTRIBUTE_SCHEMA,
    AbstractPayload,
    ClosedVocabularyError,
    assert_closed_vocabulary,
)


def r1_setup(text: str, ents: list[Entity], salt: bytes = b"salt"):
    doc = Document("d1", DocumentKind.XLSX, Path("d.xlsx"), text)
    mask = SlotMasker(salt).mask(doc, ents)
    return doc, build_abstract_payload("d1", Extraction(entities=list(ents), relations=list(RELS)),
                                       mask, facts=True)


VALUE_TEXT = TEXT + "Spent\t187432.55\tContract\tNB-2026-0917\tStart\t2026-06-01\n"
VALUE_ENTS = [*ENTS, Entity("250000", "MONEY"), Entity("187432.55", "MONEY"),
              Entity("NB-2026-0917", "IDENTIFIER"), Entity("2026-06-01", "DATE")]


class TestR1Payload:
    def test_value_categories_are_not_advertised(self):
        _, p = r1_setup(VALUE_TEXT, VALUE_ENTS)
        assert {c for _, c in p.slots} == {"PROJECT", "PERSON", "LOCATION"}
        # Not vacuous: the same input without facts does advertise the values.
        doc = Document("d1", DocumentKind.XLSX, Path("d.xlsx"), VALUE_TEXT)
        mask = SlotMasker(b"salt").mask(doc, VALUE_ENTS)
        plain = build_abstract_payload("d1", Extraction(entities=VALUE_ENTS, relations=[]), mask)
        assert {"MONEY", "IDENTIFIER", "DATE"} <= {c for _, c in plain.slots}

    def test_every_referent_category_advertises_every_code(self):
        _, p = r1_setup(VALUE_TEXT, VALUE_ENTS)
        assert dict(p.attribute_schema) == {c: ATTRIBUTE_CODES
                                            for c in ("PERSON", "ORG", "PROJECT", "LOCATION")}

    def test_the_schema_block_is_identical_for_corpora_differing_only_in_values(self):
        """The privacy claim, executable. The same fixture's reports differ;
        that is the utility claim and it is asserted at reintegration."""
        other_text = VALUE_TEXT.replace("250000", "910000").replace("187432.55", "12.50")
        other_ents = [e if e.category != "MONEY" else Entity(
            {"250000": "910000", "187432.55": "12.50"}[e.text], "MONEY") for e in VALUE_ENTS]
        _, a = r1_setup(VALUE_TEXT, VALUE_ENTS)
        _, b = r1_setup(other_text, other_ents)
        assert a.schema_json() == b.schema_json()

    def test_the_schema_block_is_identical_even_when_categories_differ(self):
        """Stronger than the design asked: a corpus with no person still
        advertises the PERSON schema, so the block is a constant."""
        _, a = r1_setup(VALUE_TEXT, VALUE_ENTS)
        _, b = r1_setup("Only Acme Ltd here.\n", [Entity("Acme Ltd", "ORG")])
        assert a.schema_json() == b.schema_json()

    def test_the_payload_carries_no_fact_reference(self):
        _, p = r1_setup(VALUE_TEXT, VALUE_ENTS)
        assert not FACT_RE.search(p.to_json())

    def test_the_r1_payload_does_not_trip_containment(self):
        doc, p = r1_setup(VALUE_TEXT, VALUE_ENTS)
        f = ShingleFilter(salt=b"gw")
        f.index_document(doc.text)
        f.seal()
        assert not f.inspect(p.to_json()).blocked

    def test_the_baseline_and_r5_wire_form_is_unchanged(self):
        _, _, payload, _ = setup()
        assert "attribute_schema" not in payload.to_json()
        assert payload.attribute_schema == () and payload.fact_ref_format == ""


class TestClosedVocabulary:
    def _payload(self, **over):
        base = dict(doc_id="d", relations=(), slots=(("⟦SLOT:PROJECT_a1b2c3d4⟧", "PROJECT"),),
                    n_cells=0, n_blocks=0, n_chars=0, attribute_schema=ATTRIBUTE_SCHEMA,
                    fact_ref_format="x")
        base.update(over)
        return AbstractPayload(**base)

    def test_the_shipped_schema_passes(self):
        assert_closed_vocabulary(self._payload())

    def test_a_code_outside_the_vocabulary_is_refused(self):
        with pytest.raises(ClosedVocabularyError):
            assert_closed_vocabulary(self._payload(
                attribute_schema=(("PROJECT", (*ATTRIBUTE_CODES, "SALARY")),)))

    def test_a_substring_of_a_code_is_not_a_code(self):
        with pytest.raises(ClosedVocabularyError):
            assert_closed_vocabulary(self._payload(attribute_schema=(("PROJECT", ("AUTH",)),)))

    def test_a_value_category_in_the_schema_is_refused(self):
        with pytest.raises(ClosedVocabularyError):
            assert_closed_vocabulary(self._payload(attribute_schema=(("MONEY", ATTRIBUTE_CODES),)))

    def test_a_value_slot_alongside_facts_is_refused(self):
        with pytest.raises(ClosedVocabularyError):
            assert_closed_vocabulary(self._payload(
                slots=(("⟦SLOT:MONEY_a1b2c3d4⟧", "MONEY"),)))



# ------------------------------------------------------------ G2: the character count

import json  # noqa: E402

from privdeep.tier2_cloud.abstract_payload import CHARS_QUANTUM, coarse_chars  # noqa: E402


class TestCoarseChars:
    """The character count crosses rounded to the nearest 1,000, half up, with a floor of
    1,000. The abstract_payload module docstring says why, and states the limit."""

    @pytest.mark.parametrize(("n", "wire"), [
        # the floor: rounding would say 0 below 500
        (0, 1000), (1, 1000), (499, 1000), (500, 1000), (501, 1000), (1499, 1000),
        # half up at every boundary, no banker's rounding
        (1500, 2000), (2499, 2000), (2500, 3000), (3499, 3000), (3500, 4000), (4500, 5000),
        # corpus A and the two permutations that moved it; B, C and D
        (3476, 3000), (3479, 3000), (3482, 3000), (3576, 4000), (3014, 3000), (3693, 4000),
        # large
        (64_634, 65_000), (1_234_499, 1_234_000), (1_234_500, 1_235_000),
    ])
    def test_rounding(self, n, wire):
        assert coarse_chars(n) == wire

    def test_every_value_is_a_positive_multiple_of_the_quantum(self):
        assert CHARS_QUANTUM == 1000
        assert all(coarse_chars(n) % CHARS_QUANTUM == 0 and coarse_chars(n) >= CHARS_QUANTUM
                   for n in range(0, 20_000, 7))

    def test_a_negative_count_is_refused(self):
        with pytest.raises(ValueError):
            coarse_chars(-1)


def test_the_payload_json_carries_only_the_coarse_count():
    p = AbstractPayload(doc_id="d", relations=(), slots=(), n_cells=60, n_blocks=15,
                        n_chars=3479)
    assert json.loads(p.to_json())["stats"] == {"cells": 60, "blocks": 15, "chars": 3000}
    assert p.wire_stats() == {"cells": 60, "blocks": 15, "chars": 3000}
    assert "3479" not in p.to_json()
    assert p.n_chars == 3479, "the exact count stays on the local object"


def test_the_builder_keeps_the_exact_count_and_the_wire_rounds_it():
    _, _, payload, _ = setup()
    assert payload.n_chars == len(TEXT) < 500
    assert json.loads(payload.to_json())["stats"]["chars"] == 1000
