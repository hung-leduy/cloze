"""The whole chain, offline, under scripted SLM and gateway transports.

The scripted gateway plays the reference monitor: it accepts canaries and the
seal, returns a tool-use plan when the planner forces the tool, and returns a
draft that refers to entities by the slot ids the session table will issue
(deterministic under the test salt). One section's draft is refused by the
"monitor" to prove failure isolation.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from privdeep.models.document import Document, DocumentKind
from privdeep.pipeline import run_pipeline
from privdeep.tier1_local.slm_client import AsyncSLMClient
from privdeep.tier1_local.slot_masker import Entity, LocalMappingTable
from privdeep.tier2_cloud.cloud_client import CloudClient
from privdeep.tier3_reconcile.evidence_bank import EvidenceBank

from shared.shingle_filter import ShingleFilter

SALT = b"pipeline-test-salt"
GW_SALT = b"unit-gw-salt"


def seal_reply(req: httpx.Request) -> httpx.Response:
    """Play the monitor honestly: confirm the count the wire actually carries."""
    g = ShingleFilter.from_wire(req.content, salt=GW_SALT)
    b = g.bloom
    return httpx.Response(200, json={"sealed": True, "n_added": b.n_added, "m_bits": b.m_bits,
                                     "k": b.k, "n_min": g.n_min, "n_max": g.n_max,
                                     "hit_threshold": g.hit_threshold})
TEXT = ("Project Zephyr's Q3 revenue fell twelve percent after the Hanoi pilot was "
        "cancelled in August. Nguyễn Thị Lan raised the risk in the June review.")
ENTS = [Entity("Project Zephyr", "PROJECT"), Entity("Hanoi", "LOCATION"),
        Entity("Nguyễn Thị Lan", "PERSON")]
T = LocalMappingTable(SALT)
SID = {e.text: T.slot_for(e) for e in ENTS}


def slm_handler(req: httpx.Request) -> httpx.Response:
    if req.url.path == "/api/tags":
        return httpx.Response(200, json={"models": [{"name": "qwen3:14b"}]})
    reply = json.dumps({
        "entities": [{"text": e.text, "category": e.category} for e in ENTS],
        "relations": [{"subject_type": "INITIATIVE", "predicate": "led by",
                       "object_type": "STAKEHOLDER"}],
    })
    return httpx.Response(200, json={"message": {"role": "assistant", "content": reply},
                                     "prompt_eval_count": 10, "eval_count": 5,
                                     "eval_duration": 10**8})


class GatewayScript:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req.url.path)
        if req.url.path == "/canaries":
            return httpx.Response(200, json={"registered": 5, "active": 5})
        if req.url.path == "/containment/seal":
            return seal_reply(req)
        body = json.loads(req.content)
        if body.get("tool_choice"):
            plan = {"sections": [
                {"title": "Context", "objective": "Situate the initiative.", "word_budget": 200,
                 "slot_ids": [SID["Project Zephyr"], SID["Nguyễn Thị Lan"]]},
                {"title": "Refused", "objective": "This one the monitor blocks.",
                 "word_budget": 200, "slot_ids": [SID["Hanoi"]]},
                {"title": "Findings", "objective": "Explain the decline.", "word_budget": 200,
                 "slot_ids": [SID["Project Zephyr"], SID["Hanoi"]]},
            ]}
            return httpx.Response(200, json={
                "id": "m", "type": "message", "role": "assistant", "model": "claude-sonnet-5-x",
                "content": [{"type": "tool_use", "id": "t", "name": "plan_outline", "input": plan}],
                "stop_reason": "tool_use", "usage": {"input_tokens": 1, "output_tokens": 1}})
        user = body["messages"][0]["content"]
        if "THIS SECTION: Refused" in user:
            return httpx.Response(403, json={"allowed": False,
                                             "reason": "RAW_CONTEXT_CONTAINMENT: 1 hit"})
        if "THIS SECTION: Context" in user:
            text = (f"{SID['Project Zephyr']} was led by {SID['Nguyễn Thị Lan']} and reported "
                    f"a decline of 12% [W1]. Delays followed.")
        else:
            text = f"{SID['Project Zephyr']} paused work in {SID['Hanoi']} [W1]."
        return httpx.Response(200, json={
            "id": "m", "type": "message", "role": "assistant", "model": "claude-sonnet-5-x",
            "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
            "usage": {"input_tokens": 30, "output_tokens": 20}})


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SHINGLE_HMAC_SALT", GW_SALT.decode())


def test_full_chain_offline(env, tmp_path):
    doc = Document("d1", DocumentKind.MARKDOWN, Path("d1.md"), TEXT)
    gw = GatewayScript()
    bank = EvidenceBank()
    bank.add("https://example.invalid/w1", "Pilot cancellations cut revenue 10-15%.",
             "Regional pilot cancellations reduced revenue by 10-15%.")
    slm = AsyncSLMClient("http://local-slm:11434", model="qwen3:14b",
                         transport=httpx.MockTransport(slm_handler))
    cloud = CloudClient("http://reference-monitor:5050", transport=httpx.MockTransport(gw))

    res = asyncio.run(run_pipeline(
        [doc], "Assess Q3.", slm=slm, cloud=cloud, gateway_url="http://reference-monitor:5050",
        evidence=bank, gw_client=httpx.Client(transport=httpx.MockTransport(gw)),
        session_salt=SALT, run_id="t1"))

    # boundary setup happened before any cloud call
    assert gw.calls[:2] == ["/canaries", "/containment/seal"]
    assert gw.calls.count("/v1/messages") == 4          # plan + 3 drafts (one refused)

    # report carries the real values, in prose, and only for the sections that survived
    r = res.report_markdown
    assert r.startswith("# Assess Q3.")
    assert "Project Zephyr was led by Nguyễn Thị Lan" in r
    assert "paused work in Hanoi" in r
    assert "## Refused" not in r and "⟦SLOT:" not in r
    assert res.sections_ok == 2 and res.sections_refused == 1
    assert res.outline_titles == ["Context", "Refused", "Findings"]

    # manifest: counters, resolved model, refusal recorded, no content
    m = res.manifest
    assert m.slots_issued == 3 and m.canaries_registered == 5
    # R5: spellings collapse into referents, so there can never be fewer
    # surface forms than slots. Asserted as a relation rather than a magic
    # number so it keeps meaning if the fixture's entities change.
    assert m.surface_forms >= m.slots_issued
    assert all(v >= 1 for v in m.fragmentation.values())
    assert m.cloud_models_resolved == ["claude-sonnet-5-x"]
    assert m.egress == {"attempts": 4, "allowed": 3, "refused": 1, "bytes_out": 0, "bytes_in": 0}
    recs = {s.section_id: s for s in m.sections}
    assert recs["s2"].refused.startswith("draft: RAW_CONTEXT_CONTAINMENT")
    assert recs["s1"].citations_valid == 1 and recs["s1"].unbacked_numbers == 0
    assert recs["s1"].slots_used == 2 and recs["s3"].slots_used == 2
    assert m.extraction["entities"] == 3 and m.extraction["dropped_not_in_text"] == 0
    # Structured fields, not only the note: the plan returned five references
    # (2 + 1 + 2) and every one named an issued slot.
    assert (m.planner_refs_returned, m.planner_refs_dropped) == (5, 0)
    d = json.loads(m.to_json())
    assert (d["planner_refs_returned"], d["planner_refs_dropped"]) == (5, 0)
    blob = m.to_json()
    for private in ("Project Zephyr", "Nguyễn", "Hanoi", TEXT[:20]):
        assert private not in blob
    assert m.evidence[0]["tag"] == "W1"


def test_planning_refusal_ends_the_run_cleanly(env):
    doc = Document("d1", DocumentKind.MARKDOWN, Path("d1.md"), TEXT)

    def gw(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/canaries":
            return httpx.Response(200, json={"registered": 5, "active": 5})
        if req.url.path == "/containment/seal":
            return seal_reply(req)
        return httpx.Response(403, json={"allowed": False, "reason": "CANARY_TRIPPED: 1"})

    slm = AsyncSLMClient("http://local-slm:11434", transport=httpx.MockTransport(slm_handler))
    cloud = CloudClient("http://reference-monitor:5050", transport=httpx.MockTransport(gw))
    res = asyncio.run(run_pipeline(
        [doc], "goal", slm=slm, cloud=cloud, gateway_url="http://reference-monitor:5050",
        gw_client=httpx.Client(transport=httpx.MockTransport(gw)), session_salt=SALT))
    assert res.report_markdown == "" and res.sections_ok == 0
    assert res.manifest.egress["refused"] == 1
    assert any("planning refused" in n for n in res.manifest.notes)
    # No plan came back, which is not a plan with zero references.
    assert res.manifest.planner_refs_returned is None
    assert res.manifest.planner_refs_dropped is None
