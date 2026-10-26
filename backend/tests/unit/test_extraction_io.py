"""Reusing one extraction across arms, and the three ways reuse could lie."""

from __future__ import annotations

from pathlib import Path

import pytest
from privdeep.models.document import Document, DocumentKind
from privdeep.tier1_local.extraction_io import (
    ExtractionReuseError,
    dump_extractions,
    load_extractions,
)
from privdeep.tier1_local.ontology_extractor import ConceptRelation, Extraction, OntologyLeak
from privdeep.tier1_local.slot_masker import Entity

PREFIX = "CANARY_PRIVDEEP_"


def doc(doc_id: str, text: str) -> Document:
    return Document(doc_id, DocumentKind.MARKDOWN, Path(f"{doc_id}.md"), text)


def ext(*ents: tuple[str, str], rels=(("INITIATIVE", "has budget", "FINANCIAL_METRIC"),),
        **counters) -> Extraction:
    return Extraction(entities=[Entity(t, c) for t, c in ents],
                      relations=[ConceptRelation(*r) for r in rels], **counters)


DOCS = [doc("memo", "Project Zephyr was authorised 250,000.00 USD."),
        doc("sheet", "Zephyr\t250000\n")]
EXTS = [ext(("Project Zephyr", "PROJECT"), ("250,000.00", "MONEY"), dropped_malformed=2),
        ext(("Zephyr", "PROJECT"), ("250000", "MONEY"), chunks=3)]


class TestRoundTrip:
    def test_entities_relations_and_counters_survive(self):
        back = load_extractions(dump_extractions(DOCS, EXTS), DOCS, canary_prefix=PREFIX)
        assert [e.entities for e in back] == [e.entities for e in EXTS]
        assert [e.relations for e in back] == [e.relations for e in EXTS]
        assert back[0].dropped_malformed == 2 and back[1].chunks == 3

    def test_the_leak_gate_drop_count_survives_and_defaults_to_zero(self):
        """Every arm that reuses an extraction reports the drops it made. A file
        written before the counter existed loads 0, which is true of it: the
        extractor of that date aborted instead of dropping."""
        exts = [ext(("Project Zephyr", "PROJECT"), relations_dropped_leak=2), EXTS[1]]
        data = dump_extractions(DOCS, exts)
        back = load_extractions(data, DOCS, canary_prefix=PREFIX)
        assert [e.relations_dropped_leak for e in back] == [2, 0]
        for row in data["documents"]:
            del row["relations_dropped_leak"]
        back = load_extractions(data, DOCS, canary_prefix=PREFIX)
        assert [e.relations_dropped_leak for e in back] == [0, 0]

    def test_order_follows_this_runs_documents_not_the_file(self):
        back = load_extractions(dump_extractions(DOCS, EXTS), list(reversed(DOCS)),
                                canary_prefix=PREFIX)
        assert back[0].entities == EXTS[1].entities

    def test_raw_replies_are_not_saved(self):
        e = ext(("Zephyr", "PROJECT"))
        e.raw_replies.append("private SLM output")
        data = dump_extractions([doc("s", "Zephyr")], [e])
        assert "private SLM output" not in repr(data)


class TestRefusals:
    def test_a_different_corpus_is_refused(self):
        """Otherwise the entities are just unmatched and the run carries on."""
        data = dump_extractions(DOCS, EXTS)
        edited = [doc("memo", "Project Zephyr was authorised 250,000.01 USD."), DOCS[1]]
        with pytest.raises(ExtractionReuseError, match="corpus mismatch"):
            load_extractions(data, edited, canary_prefix=PREFIX)

    def test_a_missing_or_extra_document_is_refused(self):
        data = dump_extractions(DOCS, EXTS)
        with pytest.raises(ExtractionReuseError, match="corpus mismatch"):
            load_extractions(data, DOCS[:1], canary_prefix=PREFIX)
        with pytest.raises(ExtractionReuseError, match="corpus mismatch"):
            load_extractions(data, [*DOCS, doc("extra", "x")], canary_prefix=PREFIX)

    def test_an_earlier_runs_canary_is_refused_in_entities(self):
        d = [doc("m", f"see {PREFIX}0123456789abcdef0123456789abcdef here")]
        data = dump_extractions(d, [ext((f"{PREFIX}0123456789abcdef0123456789abcdef",
                                         "IDENTIFIER"))])
        with pytest.raises(ExtractionReuseError, match="canary"):
            load_extractions(data, d, canary_prefix=PREFIX)

    def test_an_earlier_runs_canary_is_refused_in_relations(self):
        d = [doc("m", "Zephyr")]
        data = dump_extractions(d, [ext(("Zephyr", "PROJECT"),
                                        rels=((f"{PREFIX}abc", "leaks", "X"),))])
        with pytest.raises(ExtractionReuseError, match="canary"):
            load_extractions(data, d, canary_prefix=PREFIX)

    def test_an_entity_absent_from_the_text_is_refused(self):
        data = dump_extractions(DOCS, EXTS)
        data["documents"][0]["entities"].append({"text": "Project Aurora", "category": "PROJECT"})
        with pytest.raises(ExtractionReuseError, match="do not occur"):
            load_extractions(data, DOCS, canary_prefix=PREFIX)

    def test_a_foreign_file_is_refused(self):
        with pytest.raises(ExtractionReuseError, match="format"):
            load_extractions({"documents": []}, DOCS, canary_prefix=PREFIX)

    def test_screening_without_a_prefix_is_refused(self):
        with pytest.raises(ExtractionReuseError, match="canary prefix"):
            load_extractions(dump_extractions(DOCS, EXTS), DOCS, canary_prefix="")

    def test_a_relation_carrying_an_entity_string_is_refused(self):
        """Relations cross the boundary. The extractor drops a leaking relation
        and never saves one; reused relations must pass the same rule or they
        are ungated input. On reuse the gate is strict: an older or altered file
        is refused, not repaired by dropping."""
        d = [doc("m", "Project Zephyr was cancelled.")]
        data = dump_extractions(d, [ext(("Project Zephyr", "PROJECT"))])
        data["documents"][0]["relations"] = [["Project Zephyr", "was", "CANCELLED"]]
        with pytest.raises(OntologyLeak):
            load_extractions(data, d, canary_prefix=PREFIX)

    def test_a_relation_carrying_another_documents_entity_is_refused(self):
        """Corpus-wide on reuse: the payload merges every document's relations,
        so a relation of one document that carries an entity string saved for
        another is refused too, with the category and not the string."""
        d = [doc("a", "Scheme Fallowbeck is funded."),
             doc("b", "Aoife Brannock asked the port authority.")]
        data = dump_extractions(d, [
            ext(("Scheme Fallowbeck", "PROJECT"),
                rels=(("INITIATIVE", "has authority", "FINANCIAL_METRIC"),)),
            ext(("Aoife Brannock", "PERSON"), ("authority", "ORG"))])
        with pytest.raises(OntologyLeak, match=r"^document 1 of 2: .* another document \(ORG\)$"):
            load_extractions(data, d, canary_prefix=PREFIX)

    def test_a_clean_multi_document_file_still_loads(self):
        d = [doc("a", "Scheme Fallowbeck is funded."),
             doc("b", "Aoife Brannock asked the port authority.")]
        exs = [ext(("Scheme Fallowbeck", "PROJECT")),
               ext(("Aoife Brannock", "PERSON"), ("authority", "ORG"),
                   rels=(("PERSON", "asked", "ORGANISATION"),))]
        back = load_extractions(dump_extractions(d, exs), d, canary_prefix=PREFIX)
        assert [x.relations for x in back] == [x.relations for x in exs]
