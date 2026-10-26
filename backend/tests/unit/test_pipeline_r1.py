"""The r1 arm through the whole pipeline, offline.

What R1 exists to deliver, asserted on the wire and on the report: a value the
cloud never sees is written into the report by the core.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from privdeep.models.document import Cell, Document, DocumentKind, Span
from privdeep.pipeline import run_pipeline
from privdeep.tier1_local.slm_client import AsyncSLMClient
from privdeep.tier1_local.slot_masker import SLOT_RE, Entity, LocalMappingTable
from privdeep.tier2_cloud.cloud_client import CloudClient
from privdeep.tier3_reconcile.evidence_bank import EvidenceBank

from shared.shingle_filter import ShingleFilter

SALT = b"pipeline-r1-salt"
GW_SALT = b"unit-gw-salt"
ROWS = [["Project", "Budget (USD)"], ["Project Zephyr", "250000"]]
ENTS = [Entity("Project Zephyr", "PROJECT"), Entity("250000", "MONEY")]
ZEPHYR = LocalMappingTable(SALT).slot_for(ENTS[0])
HEX = SLOT_RE.fullmatch(ZEPHYR).group("hex")


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SHINGLE_HMAC_SALT", GW_SALT.decode())


def doc() -> Document:
    lines, cells, pos = [], [], 0
    for r, row in enumerate(ROWS, start=1):
        for c, v in enumerate(row, start=1):
            cells.append(Cell("Budget", r, c, v, Span(pos, pos + len(v))))
            pos += len(v) + 1
        lines.append("\t".join(row))
    return Document("budget", DocumentKind.XLSX, Path("budget.xlsx"),
                    "\n".join(lines) + "\n", cells=cells)


def slm(req: httpx.Request) -> httpx.Response:
    if req.url.path == "/api/tags":
        return httpx.Response(200, json={"models": [{"name": "qwen3:14b"}]})
    reply = json.dumps({"entities": [{"text": e.text, "category": e.category} for e in ENTS],
                        "relations": [{"subject_type": "INITIATIVE", "predicate": "has",
                                       "object_type": "FINANCIAL_METRIC"}]})
    return httpx.Response(200, json={"message": {"role": "assistant", "content": reply},
                                     "prompt_eval_count": 1, "eval_count": 1,
                                     "eval_duration": 10**8})


class Gateway:
    def __init__(self) -> None:
        self.bodies: list[dict] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.url.path == "/canaries":
            return httpx.Response(200, json={"registered": 5, "active": 5})
        if req.url.path == "/containment/seal":
            g = ShingleFilter.from_wire(req.content, salt=GW_SALT)
            return httpx.Response(200, json={"sealed": True, "n_added": g.bloom.n_added,
                                             "m_bits": g.bloom.m_bits, "k": g.bloom.k,
                                             "n_min": g.n_min, "n_max": g.n_max,
                                             "hit_threshold": g.hit_threshold})
        body = json.loads(req.content)
        self.bodies.append(body)
        usage = {"input_tokens": 10, "output_tokens": 5}
        if body.get("tool_choice"):
            return httpx.Response(200, json={
                "id": "m", "type": "message", "role": "assistant", "model": "claude-sonnet-5",
                "stop_reason": "tool_use", "usage": usage,
                "content": [{"type": "tool_use", "id": "t", "name": "plan_outline", "input": {
                    "sections": [{"title": "Budget", "objective": "State the authority.",
                                  "word_budget": 200, "slot_ids": [ZEPHYR]}]}}]})
        text = (f"The authority for {ZEPHYR} stood at ⟦FACT:{HEX}.AUTHAMT⟧, and its revised "
                f"date is ⟦FACT:{HEX}.DATEREV⟧.")
        return httpx.Response(200, json={
            "id": "m", "type": "message", "role": "assistant", "model": "claude-sonnet-5",
            "stop_reason": "end_turn", "usage": usage,
            "content": [{"type": "text", "text": text}]})


def run_r1():
    gw = Gateway()
    res = asyncio.run(run_pipeline(
        [doc()], "Assess the budget.",
        slm=AsyncSLMClient("http://local-slm:11434", model="qwen3:14b",
                           transport=httpx.MockTransport(slm)),
        cloud=CloudClient("http://reference-monitor:5050", transport=httpx.MockTransport(gw)),
        gateway_url="http://reference-monitor:5050", evidence=EvidenceBank(),
        gw_client=httpx.Client(transport=httpx.MockTransport(gw)),
        session_salt=SALT, run_id="r1", arm="r1"))
    return res, gw


def test_the_value_reaches_the_report_but_never_the_wire(env):
    res, gw = run_r1()
    assert "Project Zephyr stood at 250000 USD" in res.report_markdown
    sent = json.dumps(gw.bodies, ensure_ascii=False)
    assert "250000" not in sent, "a fact value crossed the boundary"
    assert "⟦FACT:" not in res.report_markdown and "⟦SLOT:" not in res.report_markdown


def test_an_absent_attribute_is_written_as_not_recorded(env):
    res, _ = run_r1()
    assert "revised date is not recorded." in res.report_markdown
    (sec,) = res.manifest.sections
    assert (sec.facts_resolved, sec.facts_unavailable) == (1, 1)


def test_the_planner_is_offered_referents_and_the_schema_not_value_slots(env):
    _, gw = run_r1()
    planner = next(b for b in gw.bodies if b.get("tool_choice"))
    user = planner["messages"][0]["content"]
    assert "[MONEY]" not in user and "[PROJECT]" in user
    assert "ATTRIBUTES every placeholder" in user


def test_the_manifest_records_the_arm_and_the_store(env):
    res, _ = run_r1()
    m = res.manifest
    assert m.arm == "r1"
    assert m.facts["facts_structural"] == 1 and m.facts["facts_total"] >= 1
    assert m.sections[0].unbacked_numbers == 0, "a core-written value counted as unbacked"
