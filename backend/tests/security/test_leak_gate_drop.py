"""The W2 leak gate drops and counts, through the running pipeline.

Found by the EXP3 pilot on corpus D (2026-09-27): qwen3 typed the common phrase
"recovery plan" as a PROJECT entity, the relation
("PERSON", "will present a recovery plan", "PROJECT") contained it, and the
gate, which then raised, ended the run. Every arm reuses one extraction per
corpus, so one such relation lost the corpus.

These run the real `run_pipeline` on each arm with the local SLM and the
monitor scripted (no network, no Docker). The SLM returns that relation and a
clean one. What is pinned:

* the run completes;
* the leaking relation is on no request the core makes to the monitor, and
  neither is the entity string, over every request body (canary registration,
  the containment seal, the planner and every drafter call);
* the clean relation still crosses;
* the manifest counts the drop, as a number, and passes its publishability
  guard with no entity or relation text in it.

A document whose every relation is dropped still completes, with the planner
told "- (none)". The reuse path stays strict: a saved extraction carrying the
leaking relation raises `OntologyLeak` before any model call.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from privdeep.models.document import Document, DocumentKind
from privdeep.pipeline import PipelineResult, run_pipeline
from privdeep.tier1_local.extraction_io import dump_extractions
from privdeep.tier1_local.ontology_extractor import ConceptRelation, Extraction, OntologyLeak
from privdeep.tier1_local.slm_client import AsyncSLMClient
from privdeep.tier1_local.slot_masker import SLOT_RE, Entity
from privdeep.tier2_cloud.cloud_client import CloudClient
from privdeep.tier3_reconcile.evidence_bank import EvidenceBank

from shared.shingle_filter import ShingleFilter

pytestmark = pytest.mark.security

SALT = b"leak-gate-drop-salt"
GW_SALT = b"unit-gw-salt"
GW = "http://reference-monitor:5050"
TEXT = ("# Scheme Fallowbeck\n\nAoife Brannock will present a recovery plan for "
        "Scheme Fallowbeck at the October board. The contingency is 41,500 GBP.\n")
ENTITY = "recovery plan"
ENTS = [Entity("Aoife Brannock", "PERSON"), Entity(ENTITY, "PROJECT"),
        Entity("Scheme Fallowbeck", "PROJECT"), Entity("41,500 GBP", "MONEY")]
LEAKING = ("PERSON", "will present a recovery plan", "PROJECT")
CLEAN = ("PERSON", "owns", "ACTION")


def doc() -> Document:
    return Document("board", DocumentKind.MARKDOWN, Path("board.md"), TEXT)


def slm(relations: list[tuple[str, str, str]]):  # type: ignore[no-untyped-def]
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:14b"}]})
        reply = json.dumps({
            "entities": [{"text": e.text, "category": e.category} for e in ENTS],
            "relations": [{"subject_type": s, "predicate": p, "object_type": o}
                          for s, p, o in relations]})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": reply},
                                         "prompt_eval_count": 1, "eval_count": 1,
                                         "eval_duration": 10**8})
    return handler


class Monitor:
    """The monitor's control endpoints and a cloud that plans one section; every
    request the core makes to it is kept, body and all."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, bytes]] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append((req.url.path, req.content))
        if req.url.path == "/canaries":
            return httpx.Response(200, json={"registered": 5, "active": 5})
        if req.url.path == "/containment/seal":
            g = ShingleFilter.from_wire(req.content, salt=GW_SALT)
            return httpx.Response(200, json={"sealed": True, "n_added": g.bloom.n_added,
                                             "m_bits": g.bloom.m_bits, "k": g.bloom.k,
                                             "n_min": g.n_min, "n_max": g.n_max,
                                             "hit_threshold": g.hit_threshold})
        body = json.loads(req.content)
        usage = {"input_tokens": 10, "output_tokens": 5}
        if body.get("tool_choice"):
            first = SLOT_RE.search(body["messages"][0]["content"])
            assert first, "the planner was offered no slot"
            return httpx.Response(200, json={
                "id": "m", "type": "message", "role": "assistant", "model": "claude-sonnet-5",
                "stop_reason": "tool_use", "usage": usage,
                "content": [{"type": "tool_use", "id": "t", "name": "plan_outline", "input": {
                    "sections": [{"title": "Board", "objective": "State the plan.",
                                  "word_budget": 150, "slot_ids": [first.group(0)]}]}}]})
        return httpx.Response(200, json={
            "id": "m", "type": "message", "role": "assistant", "model": "claude-sonnet-5",
            "stop_reason": "end_turn", "usage": usage,
            "content": [{"type": "text", "text": "The board will hear the plan."}]})

    def messages(self) -> list[dict]:
        return [json.loads(b) for p, b in self.requests if p == "/v1/messages"]


def run(relations: list[tuple[str, str, str]], arm: str, reuse: dict | None = None,
        mon: Monitor | None = None) -> tuple[PipelineResult, Monitor]:
    mon = mon if mon is not None else Monitor()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("SHINGLE_HMAC_SALT", GW_SALT.decode())
        res = asyncio.run(run_pipeline(
            [doc()], "Summarise the board paper.",
            slm=AsyncSLMClient("http://local-slm:11434", model="qwen3:14b",
                               transport=httpx.MockTransport(slm(relations))),
            cloud=CloudClient(GW, transport=httpx.MockTransport(mon)),
            gateway_url=GW, evidence=EvidenceBank(),
            gw_client=httpx.Client(transport=httpx.MockTransport(mon)),
            session_salt=SALT, run_id=f"w2-{arm}", arm=arm, reuse_extraction=reuse))
    return res, mon


def _plan_prompt(mon: Monitor) -> str:
    (plan,) = [b for b in mon.messages() if b.get("tool_choice")]
    return plan["messages"][0]["content"]


@pytest.mark.parametrize("arm", ["baseline", "r5", "r1"])
def test_a_leaking_relation_is_dropped_counted_and_never_sent(arm):
    res, mon = run([LEAKING, CLEAN], arm)

    # The run completes.
    assert (res.sections_ok, res.sections_refused) == (1, 0)
    assert len(mon.messages()) == 2                     # the plan and one draft

    # Neither the relation nor the entity is on any request, of any kind.
    assert {p for p, _ in mon.requests} == {"/canaries", "/containment/seal", "/v1/messages"}
    for path, body in mon.requests:
        text = body.decode("utf-8", errors="replace").casefold()
        assert ENTITY not in text, f"the entity string is on a {path} request"
        assert LEAKING[1].casefold() not in text, f"the leaking relation is on {path}"
    # The clean relation still crosses, to the planner and to the drafter.
    line = f"- ({CLEAN[0]}) --{CLEAN[1]}--> ({CLEAN[2]})"
    for body in mon.messages():
        assert line in body["messages"][0]["content"]
    assert [list(r.fields()) for r in res.extractions[0].relations] == [list(CLEAN)]

    # The manifest counts it, and carries no content.
    ex = res.manifest.extraction
    assert ex["relations_dropped_leak"] == 1
    assert ex["documents_all_relations_dropped"] == 0 and ex["relations"] == 1
    published = res.manifest.to_json()                  # runs the structural guard
    assert ENTITY not in published.casefold() and "will present" not in published


def test_a_document_whose_every_relation_is_dropped_still_runs():
    res, mon = run([LEAKING], "r5")
    assert (res.sections_ok, res.sections_refused) == (1, 0)
    assert "DOCUMENT SHAPE (abstract concept relations):\n- (none)\n" in _plan_prompt(mon)
    assert res.manifest.extraction["relations_dropped_leak"] == 1
    assert res.manifest.extraction["documents_all_relations_dropped"] == 1
    assert res.manifest.slots_issued > 0                # slots and stats still go
    assert all(ENTITY not in b.decode("utf-8", errors="replace").casefold()
               for _, b in mon.requests)


def test_a_saved_extraction_with_a_leaking_relation_is_refused_before_any_call():
    """The reuse path is strict: the extractor never saves a leaking relation, so
    one in a saved file means an older or altered file, and the run ends."""
    saved = dump_extractions([doc()], [Extraction(
        entities=list(ENTS), relations=[ConceptRelation(*LEAKING), ConceptRelation(*CLEAN)])])
    mon = Monitor()
    with pytest.raises(OntologyLeak, match=r"\(PROJECT\)$"):
        run([CLEAN], "r5", reuse=saved, mon=mon)
    # Only canary registration precedes the reuse screen, which needs this
    # run's canary prefix; no model call is made.
    assert [p for p, _ in mon.requests] == ["/canaries"]
