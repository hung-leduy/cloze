"""The drafter cleans what it can see and reports what it cleaned."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from privdeep.models.outline import Outline, Section
from privdeep.tier2_cloud.abstract_payload import AbstractPayload
from privdeep.tier2_cloud.cloud_client import CloudClient, EgressRefused
from privdeep.tier2_cloud.section_drafter import Evidence, SectionDrafter

P, Q = "⟦SLOT:PROJECT_a1b2c3d4⟧", "⟦SLOT:PERSON_0badf00d⟧"
PAYLOAD = AbstractPayload("d1", (("INITIATIVE", "led by", "STAKEHOLDER"),),
                          ((P, "PROJECT"), (Q, "PERSON")), 36, 0, 476)
OUTLINE = Outline("Assess Q3 position.", (
    Section("s1", "Context", "Situate the initiative.", 300, (P, Q)),
    Section("s2", "Findings", "Explain the decline.", 500, (P,)),
))
EVID = [Evidence("W1", "Regional pilots in 2026 saw 10-15% revenue dips on cancellation.",
                 "https://example.invalid/a")]


def reply(text: str) -> httpx.Response:
    return httpx.Response(200, json={
        "id": "m", "type": "message", "role": "assistant", "model": "claude-sonnet-5-20260901",
        "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
        "usage": {"input_tokens": 50, "output_tokens": 80}})


class Gate:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def __call__(self, req):
        self.calls.append(req)
        return self.resp


def drafter(resp):
    g = Gate(resp)
    return SectionDrafter(CloudClient("http://reference-monitor:5050",
                                      transport=httpx.MockTransport(g))), g


def run(c): return asyncio.run(c)


def test_prompt_carries_section_outline_shape_allowed_slots_and_evidence():
    d, g = drafter(reply("ok"))
    run(d.draft(OUTLINE.sections[1], OUTLINE, PAYLOAD, EVID))
    body = json.loads(g.calls[0].content)
    user = body["messages"][0]["content"]
    assert "THIS SECTION: Findings" in user and "WORD BUDGET: 500" in user
    assert "> s2: Findings" in user and "  s1: Context" in user
    assert "led by" in user and P in user
    assert Q not in user.split("PLACEHOLDERS YOU MAY USE")[1].split("PUBLIC EVIDENCE")[0], \
        "only the section's own slots are offered"
    assert "[W1] Regional pilots" in user
    assert body["stream"] is False and "Never invent" in body["system"]


def test_no_evidence_means_no_numeric_claims_instruction():
    d, g = drafter(reply("ok"))
    run(d.draft(OUTLINE.sections[0], OUTLINE, PAYLOAD))
    assert "make no numeric claims" in json.loads(g.calls[0].content)["messages"][0]["content"]


def test_permitted_slots_kept_invented_slots_replaced_and_counted():
    text = (f"{P} was led by {Q} and, separately, ⟦SLOT:ORG_deadbeef⟧ intervened "
            f"while {P} continued [W1].")
    d, _ = drafter(reply(text))
    r = run(d.draft(OUTLINE.sections[0], OUTLINE, PAYLOAD, EVID))
    assert "⟦SLOT:ORG_deadbeef⟧" not in r.text
    assert r.text.count("[unresolved reference]") == 1 and r.invented_slots == 1
    assert r.slots_used == (P, Q)
    assert r.citations_used == ("W1",)
    assert r.resolved_model == "claude-sonnet-5-20260901"


def test_known_but_not_section_slot_is_still_permitted():
    """A slot the core issued but the planner did not assign here is not 'invented'."""
    d, _ = drafter(reply(f"{P} and {Q}."))
    r = run(d.draft(OUTLINE.sections[1], OUTLINE, PAYLOAD))   # s2 lists only P
    assert r.invented_slots == 0 and set(r.slots_used) == {P, Q}


def test_word_count_and_budget_ratio():
    d, _ = drafter(reply("one two three four five six"))
    r = run(d.draft(OUTLINE.sections[0], OUTLINE, PAYLOAD))
    assert r.word_count == 6 and r.word_budget == 300
    assert r.over_budget_ratio == pytest.approx(0.02)


def test_refusal_propagates():
    d, g = drafter(httpx.Response(403, json={"allowed": False, "reason": "CANARY_TRIPPED: 1"}))
    with pytest.raises(EgressRefused):
        run(d.draft(OUTLINE.sections[0], OUTLINE, PAYLOAD))
    assert len(g.calls) == 1
