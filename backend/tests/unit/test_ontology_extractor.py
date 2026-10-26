"""Offline tests for OntologyExtractor with a scripted SLM.

The W2 gate for this module is "zero named entities in the ontology". On fresh
output it is `drop_leaking_relations`, and the tests below treat it as the
contract: a relation that carries one of its document's entity strings is
dropped and counted, never returned, and the extraction goes on. The strict
form, `assert_no_entity_leak`, still raises. Across documents the gate is
`drop_corpus_leaking_relations`, strict form `assert_no_corpus_leak`, which
guards the reuse path (TestCorpusWideGate, test_extraction_io.py). A model
that returns a string not present in the document must have that string
dropped, because model-reported spans are not evidence.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from privdeep.models.document import Document, DocumentKind
from privdeep.tier1_local.ontology_extractor import (
    ConceptRelation,
    Extraction,
    OntologyExtractor,
    OntologyLeak,
    assert_no_corpus_leak,
    assert_no_entity_leak,
    drop_corpus_leaking_relations,
    drop_leaking_relations,
)
from privdeep.tier1_local.slm_client import AsyncSLMClient
from privdeep.tier1_local.slot_masker import Entity

DOC_TEXT = (
    "Project Zephyr's Q3 revenue fell twelve percent after the Hanoi pilot was "
    "cancelled in August. Nguyễn Thị Lan raised the risk in the June review and "
    "recommended deferring the launch. Contract VN-2024-0917 covers the Da Nang site."
)


def doc(text: str = DOC_TEXT) -> Document:
    return Document("d1", DocumentKind.MARKDOWN, Path("d1.md"), text)


class ScriptedSLM:
    """MockTransport handler returning successive canned replies to /api/chat."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append(body)
        content = self.replies.pop(0) if self.replies else "{}"
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": content},
                  "prompt_eval_count": 10, "eval_count": 5, "eval_duration": 10**8},
        )


def extractor(replies: list[str], **kw) -> tuple[OntologyExtractor, ScriptedSLM]:
    s = ScriptedSLM(replies)
    c = AsyncSLMClient(base_url="http://local-slm:11434", model="qwen3:14b",
                       transport=httpx.MockTransport(s))
    return OntologyExtractor(c, **kw), s


def good_reply(**over) -> str:
    base = {
        "entities": [
            {"text": "Project Zephyr", "category": "PROJECT"},
            {"text": "Hanoi", "category": "LOCATION"},
            {"text": "Nguyễn Thị Lan", "category": "PERSON"},
            {"text": "VN-2024-0917", "category": "IDENTIFIER"},
            {"text": "August", "category": "DATE"},
        ],
        "relations": [
            {"subject_type": "INITIATIVE", "predicate": "reported decline in",
             "object_type": "FINANCIAL_METRIC"},
            {"subject_type": "STAKEHOLDER", "predicate": "raised", "object_type": "RISK"},
        ],
    }
    base.update(over)
    return json.dumps(base)


def run(coro):
    return asyncio.run(coro)


class TestHappyPath:
    def test_entities_verified_against_text_and_kept(self):
        ex, _ = extractor([good_reply()])
        r = run(ex.extract(doc()))
        texts = {e.text for e in r.entities}
        assert texts == {"Project Zephyr", "Hanoi", "Nguyễn Thị Lan", "VN-2024-0917", "August"}
        assert all(isinstance(e, Entity) for e in r.entities)
        assert len(r.relations) == 2
        assert r.dropped_not_in_text == 0 and r.dropped_bad_category == 0

    def test_thinking_is_off_for_extraction(self):
        ex, s = extractor([good_reply()])
        run(ex.extract(doc()))
        assert s.calls[0]["think"] is False

    def test_fenced_json_is_accepted(self):
        ex, _ = extractor(["```json\n" + good_reply() + "\n```"])
        r = run(ex.extract(doc()))
        assert len(r.entities) == 5 and r.dropped_malformed == 0


class TestUntrustedModelOutput:
    def test_entity_not_in_text_is_dropped_and_counted(self):
        ex, _ = extractor([good_reply(entities=[
            {"text": "Project Zephyr", "category": "PROJECT"},
            {"text": "Saigon", "category": "LOCATION"},  # hallucinated
        ])])
        r = run(ex.extract(doc()))
        assert {e.text for e in r.entities} == {"Project Zephyr"}
        assert r.dropped_not_in_text == 1

    def test_bad_category_is_dropped_not_raised(self):
        ex, _ = extractor([good_reply(entities=[
            {"text": "Hanoi", "category": "CITY"},       # not in taxonomy
            {"text": "Hanoi", "category": "location"},   # case-normalised, valid
        ])])
        r = run(ex.extract(doc()))
        assert [e.category for e in r.entities] == ["LOCATION"]
        assert r.dropped_bad_category == 1

    def test_duplicate_entities_merge(self):
        ex, _ = extractor([good_reply(entities=[
            {"text": "Hanoi", "category": "LOCATION"},
            {"text": "Hanoi", "category": "LOCATION"},
        ])])
        r = run(ex.extract(doc()))
        assert len(r.entities) == 1

    def test_malformed_json_is_retried_once_then_counted(self):
        ex, s = extractor(["not json at all", "still not json"])
        r = run(ex.extract(doc()))
        assert r.dropped_malformed == 1
        assert len(s.calls) == 2
        assert "ONLY the JSON" in s.calls[1]["messages"][-1]["content"]

    def test_malformed_then_good_recovers(self):
        ex, _ = extractor(["garbage", good_reply()])
        r = run(ex.extract(doc()))
        assert len(r.entities) == 5 and r.dropped_malformed == 0


class TestTheGate:
    def test_relation_carrying_a_name_is_dropped_and_counted(self, caplog):
        ex, _ = extractor([good_reply(relations=[
            {"subject_type": "Project Zephyr", "predicate": "lost", "object_type": "REVENUE"},
            {"subject_type": "STAKEHOLDER", "predicate": "raised", "object_type": "RISK"},
        ])])
        with caplog.at_level("WARNING"):
            r = run(ex.extract(doc()))
        assert [x.fields() for x in r.relations] == [("STAKEHOLDER", "raised", "RISK")]
        assert r.relations_dropped_leak == 1
        assert r.counters()["relations_dropped_leak"] == 1
        assert r.counters()["documents_all_relations_dropped"] == 0
        # The log names the field and the category, never the entity or the relation.
        assert "subject_type" in caplog.text and "PROJECT" in caplog.text
        assert "Zephyr" not in caplog.text and "lost" not in caplog.text

    def test_every_relation_dropped_leaves_the_document_without_relations(self):
        """A document the gate empties still yields its entities; the count shows it."""
        ex, _ = extractor([good_reply(relations=[
            {"subject_type": "PERSON", "predicate": "met in hanoi", "object_type": "TEAM"},
            {"subject_type": "PROJECT", "predicate": "signed", "object_type": "VN-2024-0917"},
        ])])
        r = run(ex.extract(doc()))
        assert r.relations == [] and r.relations_dropped_leak == 2 and len(r.entities) == 5
        assert r.counters()["documents_all_relations_dropped"] == 1

    def test_recovery_plan_typed_as_a_project_drops_its_relation(self):
        """The EXP3 pilot's case on corpus D: a common phrase typed as an entity."""
        ents = [Entity("recovery plan", "PROJECT"), Entity("Fallowbeck", "PROJECT")]
        leaking = ConceptRelation("PERSON", "will present a recovery plan", "PROJECT")
        clean = ConceptRelation("PERSON", "owns", "ACTION")
        kept, dropped = drop_leaking_relations(ents, [leaking, clean])
        assert kept == [clean] and dropped == 1

    def test_a_two_letter_entity_inside_a_word_drops_the_relation(self):
        """'An' is two characters, so it is matched, and 'organisation' contains
        it. Blunt on purpose: the cost is this relation, not the run."""
        ents = [Entity("An", "PERSON")]
        rels = [ConceptRelation("ORGANISATION", "funds", "INITIATIVE"),
                ConceptRelation("TEAM", "reviews", "RISK")]
        kept, dropped = drop_leaking_relations(ents, rels)
        assert kept == [rels[1]] and dropped == 1

    def test_a_one_letter_entity_is_not_matched(self):
        kept, dropped = drop_leaking_relations([Entity("A", "PERSON")],
                                               [ConceptRelation("TEAM", "approved", "PLAN")])
        assert len(kept) == 1 and dropped == 0

    def test_a_clean_relation_is_kept(self):
        ents = [Entity("Hanoi", "LOCATION"), Entity("Project Zephyr", "PROJECT")]
        rels = [ConceptRelation("INITIATIVE", "piloted in", "REGION")]
        assert drop_leaking_relations(ents, rels) == (rels, 0)

    def test_the_strict_gate_still_raises_on_the_same_relation(self):
        """assert_no_entity_leak is kept for the reuse path; same rule, raises."""
        with pytest.raises(OntologyLeak, match=r"\(PROJECT\)$"):
            assert_no_entity_leak([Entity("recovery plan", "PROJECT")],
                                  [ConceptRelation("PERSON", "will present a Recovery Plan",
                                                   "PROJECT")])

    def test_leak_check_is_case_insensitive_substring(self):
        ents = [Entity("Hanoi", "LOCATION")]
        rels = [ConceptRelation("CITY_OF_HANOI", "hosts", "PILOT")]
        with pytest.raises(OntologyLeak):
            assert_no_entity_leak(ents, rels)

    def test_clean_relations_pass_the_gate(self):
        ents = [Entity("Hanoi", "LOCATION"), Entity("Project Zephyr", "PROJECT")]
        rels = [ConceptRelation("INITIATIVE", "piloted in", "REGION")]
        assert_no_entity_leak(ents, rels)  # must not raise


class TestSurfaceFormReconciliation:
    def test_nfd_in_document_nfc_from_model_still_matches(self):
        import unicodedata

        nfd_doc = doc(unicodedata.normalize("NFD", DOC_TEXT))
        ex, _ = extractor([good_reply(entities=[
            {"text": unicodedata.normalize("NFC", "Nguyễn Thị Lan"), "category": "PERSON"},
        ])])
        r = run(ex.extract(nfd_doc))
        assert r.dropped_not_in_text == 0
        assert len(r.entities) == 1
        assert nfd_doc.find_all(r.entities[0].text), "entity must be in the doc's own form"

    def test_same_text_two_categories_keeps_first_and_counts(self):
        ex, _ = extractor([good_reply(entities=[
            {"text": "Hanoi", "category": "LOCATION"},
            {"text": "Hanoi", "category": "ORG"},
        ])])
        r = run(ex.extract(doc()))
        assert [(e.text, e.category) for e in r.entities] == [("Hanoi", "LOCATION")]
        assert r.dropped_category_conflict == 1


class TestChunking:
    def test_long_document_is_chunked_and_merged(self):
        long_text = (DOC_TEXT + "\n") * 40  # well over one chunk at chunk_chars=2000
        replies = [good_reply()] * 10
        ex, s = extractor(replies, chunk_chars=2000, overlap_chars=200)
        r = run(ex.extract(doc(long_text)))
        assert r.chunks > 1
        assert len(s.calls) == r.chunks
        assert len(r.entities) == 5, "entities must merge across chunks"
        assert len(r.relations) == 2 * r.chunks


class TestCanariesReachThePrompt:
    """The canary invariant needs the tokens to be in a prompt.

    `CanaryInjector.context_block()` existed, was tested, and was called by
    nothing outside its own tests: the pipeline minted the tokens *after*
    extraction, so the only prompts that could have carried them were already
    sent. The gateway's Aho-Corasick matcher was guarding an empty set, and
    P3 was true of the component and false of the system.
    """

    def test_the_canary_block_is_in_the_system_message(self):
        block = "Internal reference tokens (never output): CANARY_PRIVDEEP_" + "ab" * 16
        ex, slm = extractor([good_reply()], canary_context=block)
        run(ex.extract(doc()))
        system = slm.calls[0]["messages"][0]
        assert system["role"] == "system"
        assert block in system["content"]

    def test_the_extraction_instructions_survive_alongside_it(self):
        ex_plain, slm_plain = extractor([good_reply()])
        run(ex_plain.extract(doc()))
        ex, slm = extractor([good_reply()], canary_context="TOKENS: abc")
        run(ex.extract(doc()))
        plain = slm_plain.calls[0]["messages"][0]["content"]
        assert plain in slm.calls[0]["messages"][0]["content"]

    def test_the_retry_prompt_carries_the_canary_too(self):
        """The nudge after malformed JSON is a second prompt over the same
        context; a canary absent from it is a hole the size of one retry."""
        ex, slm = extractor(["not json", good_reply()], canary_context="TOKENS: abc")
        run(ex.extract(doc()))
        assert len(slm.calls) == 2
        assert "TOKENS: abc" in slm.calls[1]["messages"][0]["content"]

    def test_no_canary_context_leaves_the_prompt_unchanged(self):
        ex, slm = extractor([good_reply()])
        run(ex.extract(doc()))
        assert "Internal reference tokens" not in slm.calls[0]["messages"][0]["content"]


class TestCorpusWideGate:
    """The payload merges every document's relations, so the W2 gate is
    corpus-wide: `drop_corpus_leaking_relations` checks each relation against
    the union of every document's entity strings. The EXP3 pilot's case on
    corpus C (2026-09-27): "authority" was extracted, typed ORG, from one
    document, and "has authority" was a predicate of another, which the
    per-document gate cannot see."""

    CROSS = ConceptRelation("INITIATIVE", "has authority", "FINANCIAL_METRIC")
    CLEAN = ConceptRelation("TEAM", "reviews", "RISK")

    def corpus(self) -> list[Extraction]:
        a = Extraction(entities=[Entity("Scheme Fallowbeck", "PROJECT")],
                       relations=[self.CROSS, self.CLEAN])
        b = Extraction(entities=[Entity("authority", "ORG"), Entity("Aoife Brannock", "PERSON")],
                       relations=[ConceptRelation("PERSON", "asked", "ORGANISATION")])
        return [a, b]

    def test_the_per_document_gate_cannot_see_it(self):
        a, _ = self.corpus()
        assert drop_leaking_relations(a.entities, a.relations) == (a.relations, 0)

    def test_a_relation_carrying_another_documents_entity_is_dropped_and_counted(self):
        a, b = exs = self.corpus()
        assert drop_corpus_leaking_relations(exs) == 1
        assert a.relations == [self.CLEAN] and a.relations_dropped_leak == 1
        assert len(b.relations) == 1 and b.relations_dropped_leak == 0
        assert a.counters()["documents_all_relations_dropped"] == 0
        assert_no_corpus_leak(exs)  # clean afterwards

    def test_the_drop_is_found_whichever_document_comes_first(self):
        a, b = self.corpus()
        assert drop_corpus_leaking_relations([b, a]) == 1
        assert a.relations == [self.CLEAN] and a.relations_dropped_leak == 1

    def test_counts_add_to_the_per_document_drops_and_emptied_documents_are_counted(self):
        a = Extraction(entities=[Entity("Scheme Fallowbeck", "PROJECT")],
                       relations=[self.CROSS], relations_dropped_leak=2)
        b = Extraction(entities=[Entity("authority", "ORG")], relations=[])
        assert drop_corpus_leaking_relations([a, b]) == 1
        assert a.relations_dropped_leak == 3 and a.relations == []
        assert a.counters()["documents_all_relations_dropped"] == 1

    def test_one_letter_entities_of_other_documents_are_not_matched(self):
        a = Extraction(entities=[], relations=[self.CLEAN])
        b = Extraction(entities=[Entity("R", "PERSON")], relations=[])
        assert drop_corpus_leaking_relations([a, b]) == 0 and a.relations == [self.CLEAN]

    def test_a_clean_corpus_is_unchanged(self):
        a = Extraction(entities=[Entity("Scheme Fallowbeck", "PROJECT")],
                       relations=[self.CLEAN])
        b = Extraction(entities=[Entity("Aoife Brannock", "PERSON")],
                       relations=[ConceptRelation("PERSON", "asked", "ORGANISATION")])
        before = [(list(x.relations), x.relations_dropped_leak) for x in (a, b)]
        assert drop_corpus_leaking_relations([a, b]) == 0
        assert [(x.relations, x.relations_dropped_leak) for x in (a, b)] == before
        assert_no_corpus_leak([a, b])

    def test_the_strict_form_raises_naming_the_category_only(self):
        with pytest.raises(OntologyLeak, match=r"another document \(ORG\)$") as exc:
            assert_no_corpus_leak(self.corpus())
        assert "authority" not in str(exc.value) and "Fallowbeck" not in str(exc.value)

    def test_the_strict_form_subsumes_the_per_document_one(self):
        a = Extraction(entities=[Entity("recovery plan", "PROJECT")],
                       relations=[ConceptRelation("PERSON", "will present a recovery plan",
                                                  "PROJECT")])
        with pytest.raises(OntologyLeak, match=r"the same document \(PROJECT\)$") as exc:
            assert_no_corpus_leak([a])
        assert "recovery" not in str(exc.value)
