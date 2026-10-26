"""The W2 leak gate is corpus-wide, through the running pipeline.

Found by the EXP3 pilot on corpus C (2026-09-27): the extractor typed the word
"authority" as an ORG in one document, and another document's relation had the
predicate "has authority". The gate then compared a document's relations with
that same document's entities only, so the relation passed and crossed in the
merged payload. `run_pipeline` now runs `drop_corpus_leaking_relations` over
every document once all are extracted, against the union of their entity
strings.

These run the real `run_pipeline` over a two-document corpus with the local SLM
and the monitor scripted (no network, no Docker). The stub uses "harbourmaster"
rather than the pilot's "authority" because the R1 attribute schema, a module
constant sent on every R1 request, contains the word "authority", so its absence
from the request bodies could not be asserted. What is pinned:

* the cross-document relation is dropped and counted, in either document
  order, and the entity string is on no request body the core sends;
* the check is not vacuous: with the corpus pass removed, the relation reaches
  the planner;
* the saved extraction holds only corpus-clean relations and reloads strictly;
* the reuse path refuses a saved file with such a relation, before any model
  call, naming the category only;
* a clean two-document run sends the same requests with and without the pass.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from privdeep import pipeline as P
from privdeep.models.document import Document, DocumentKind
from privdeep.pipeline import PipelineResult, run_pipeline
from privdeep.tier1_local.extraction_io import dump_extractions, load_extractions
from privdeep.tier1_local.ontology_extractor import ConceptRelation, Extraction, OntologyLeak
from privdeep.tier1_local.slm_client import AsyncSLMClient
from privdeep.tier1_local.slot_masker import Entity
from privdeep.tier2_cloud.cloud_client import CloudClient
from privdeep.tier3_reconcile.evidence_bank import EvidenceBank

from .test_leak_gate_drop import GW, GW_SALT, SALT, Monitor

pytestmark = pytest.mark.security

TEXT_A = ("# Scheme Fallowbeck\n\nScheme Fallowbeck carries a contingency of 41,500 GBP "
          "for the October board.\n")
TEXT_B = "# Berth request\n\nAoife Brannock asked the harbourmaster for a winter berth.\n"
ENTS_A = [Entity("Scheme Fallowbeck", "PROJECT"), Entity("41,500 GBP", "MONEY")]
ENTS_B = [Entity("Aoife Brannock", "PERSON"), Entity("harbourmaster", "ORG")]
ENTITY = "harbourmaster"                                # extracted from B only
CROSS = ("INITIATIVE", "reports to harbourmaster", "FINANCIAL_METRIC")  # a relation of A
CLEAN_A = ("INITIATIVE", "carries", "FINANCIAL_METRIC")
CLEAN_B = ("PERSON", "asked", "ORGANISATION")
PREFIX = "CANARY_PRIVDEEP_"


def docs(order: str = "ab") -> list[Document]:
    by = {"a": Document("scheme", DocumentKind.MARKDOWN, Path("scheme.md"), TEXT_A),
          "b": Document("berth", DocumentKind.MARKDOWN, Path("berth.md"), TEXT_B)}
    return [by[k] for k in order]


def slm(rels_a: list[tuple[str, str, str]]):  # type: ignore[no-untyped-def]
    """Replies by document: A's entities and `rels_a`, or B's entities and CLEAN_B."""
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:14b"}]})
        prompt = json.loads(req.content)["messages"][-1]["content"]
        ents, rels = (ENTS_A, rels_a) if "Fallowbeck" in prompt else (ENTS_B, [CLEAN_B])
        reply = json.dumps({
            "entities": [{"text": e.text, "category": e.category} for e in ents],
            "relations": [{"subject_type": s, "predicate": p, "object_type": o}
                          for s, p, o in rels]})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": reply},
                                         "prompt_eval_count": 1, "eval_count": 1,
                                         "eval_duration": 10**8})
    return handler


def run(rels_a: list[tuple[str, str, str]], arm: str = "r5", order: str = "ab",
        reuse: dict | None = None, mon: Monitor | None = None,
        without_corpus_pass: bool = False) -> tuple[PipelineResult, Monitor]:
    mon = mon if mon is not None else Monitor()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("SHINGLE_HMAC_SALT", GW_SALT.decode())
        if without_corpus_pass:
            mp.setattr(P, "drop_corpus_leaking_relations", lambda exs: 0)
            mp.setattr(P, "assert_no_corpus_leak", lambda exs: None)
        res = asyncio.run(run_pipeline(
            docs(order), "Summarise the two papers.",
            slm=AsyncSLMClient("http://local-slm:11434", model="qwen3:14b",
                               transport=httpx.MockTransport(slm(rels_a))),
            cloud=CloudClient(GW, transport=httpx.MockTransport(mon)),
            gateway_url=GW, evidence=EvidenceBank(),
            gw_client=httpx.Client(transport=httpx.MockTransport(mon)),
            session_salt=SALT, run_id=f"w2c-{arm}", arm=arm, reuse_extraction=reuse))
    return res, mon


def _line(r: tuple[str, str, str]) -> str:
    return f"- ({r[0]}) --{r[1]}--> ({r[2]})"


def _plan_prompt(mon: Monitor) -> str:
    (plan,) = [b for b in mon.messages() if b.get("tool_choice")]
    return plan["messages"][0]["content"]


@pytest.mark.parametrize("order", ["ab", "ba"])
@pytest.mark.parametrize("arm", ["baseline", "r5", "r1"])
def test_a_relation_carrying_another_documents_entity_is_dropped_and_never_sent(arm, order):
    res, mon = run([CROSS, CLEAN_A], arm, order)

    assert (res.sections_ok, res.sections_refused) == (1, 0)
    assert {p for p, _ in mon.requests} == {"/canaries", "/containment/seal", "/v1/messages"}
    for path, body in mon.requests:
        text = body.decode("utf-8", errors="replace").casefold()
        assert ENTITY not in text, f"the other document's entity string is on a {path} request"
    # Both clean relations still cross.
    plan = _plan_prompt(mon)
    assert _line(CLEAN_A) in plan and _line(CLEAN_B) in plan

    # Counted in A's own counter, once; the manifest sums it and carries no content.
    by_id = {d.doc_id: ex for d, ex in zip(docs(order), res.extractions, strict=True)}
    assert by_id["scheme"].relations_dropped_leak == 1
    assert by_id["berth"].relations_dropped_leak == 0
    ex = res.manifest.extraction
    assert ex["relations_dropped_leak"] == 1 and ex["relations"] == 2
    assert ex["documents_all_relations_dropped"] == 0
    assert ENTITY not in res.manifest.to_json().casefold()

    # What `_main` saves is corpus-clean and passes the strict reuse check.
    saved = dump_extractions(docs(order), res.extractions)
    assert CROSS[1] not in json.dumps(saved)
    load_extractions(saved, docs(order), canary_prefix=PREFIX)


def test_without_the_corpus_pass_the_relation_would_cross():
    """The gap the corpus pass closes, shown on the same stub: the per-document
    gate in `extract` passes the relation, and it reaches the planner."""
    _, mon = run([CROSS, CLEAN_A], without_corpus_pass=True)
    assert _line(CROSS) in _plan_prompt(mon)


def test_a_document_left_with_no_relation_is_counted():
    res, _ = run([CROSS])
    assert res.manifest.extraction["relations_dropped_leak"] == 1
    assert res.manifest.extraction["documents_all_relations_dropped"] == 1


def test_a_saved_extraction_with_a_cross_document_leak_is_refused_before_any_call():
    saved = dump_extractions(docs(), [
        Extraction(entities=list(ENTS_A),
                   relations=[ConceptRelation(*CROSS), ConceptRelation(*CLEAN_A)]),
        Extraction(entities=list(ENTS_B), relations=[ConceptRelation(*CLEAN_B)])])
    mon = Monitor()
    with pytest.raises(OntologyLeak, match=r"another document \(ORG\)$") as exc:
        run([CLEAN_A], reuse=saved, mon=mon)
    assert ENTITY not in str(exc.value) and CROSS[1] not in str(exc.value)
    assert [p for p, _ in mon.requests] == ["/canaries"]


@pytest.mark.parametrize("arm", ["baseline", "r5", "r1"])
def test_a_clean_two_document_run_is_unchanged_by_the_corpus_pass(arm):
    res, mon = run([CLEAN_A], arm)
    ref, ref_mon = run([CLEAN_A], arm, without_corpus_pass=True)
    assert mon.messages() == ref_mon.messages()
    assert res.manifest.extraction == ref.manifest.extraction
    assert res.manifest.extraction["relations_dropped_leak"] == 0
    assert [ex.relations for ex in res.extractions] == [ex.relations for ex in ref.extractions]
