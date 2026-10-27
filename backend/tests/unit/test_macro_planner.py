"""Outline validation and the planner's treatment of the model as untrusted input."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from privdeep.models.outline import Outline, Section
from privdeep.tier2_cloud.abstract_payload import AbstractPayload
from privdeep.tier2_cloud.cloud_client import CloudClient, EgressRefused
from privdeep.tier2_cloud.macro_planner import (  # noqa: F401
    MacroPlanner,
    PlannerError,
    _canonical_slot,
)

PAYLOAD = AbstractPayload(
    doc_id="d1",
    relations=(("INITIATIVE", "led by", "STAKEHOLDER"),
               ("INITIATIVE", "reported decline in", "FINANCIAL_METRIC")),
    slots=(("⟦SLOT:PROJECT_a1b2c3d4⟧", "PROJECT"), ("⟦SLOT:PERSON_0badf00d⟧", "PERSON")),
    n_cells=36, n_blocks=0, n_chars=476,
)


def tool_reply(sections: list[dict], model: str = "claude-sonnet-5-20260901") -> dict:
    return {"id": "m", "type": "message", "role": "assistant", "model": model,
            "content": [{"type": "tool_use", "id": "t", "name": "plan_outline",
                         "input": {"sections": sections}}],
            "stop_reason": "tool_use", "usage": {"input_tokens": 40, "output_tokens": 30}}


class Gate:
    def __init__(self, resp: httpx.Response) -> None:
        self.resp, self.calls = resp, []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        return self.resp


def planner(resp: httpx.Response, **kw) -> tuple[MacroPlanner, Gate]:
    g = Gate(resp)
    c = CloudClient("http://reference-monitor:5050", transport=httpx.MockTransport(g))
    return MacroPlanner(c, **kw), g


def run(coro):
    return asyncio.run(coro)


GOOD = [
    {"title": "Context", "objective": "Situate the initiative and its stakeholders.",
     "word_budget": 400, "slot_ids": ["⟦SLOT:PROJECT_a1b2c3d4⟧", "⟦SLOT:PERSON_0badf00d⟧"]},
    {"title": "Findings", "objective": "Explain the reported decline abstractly.",
     "word_budget": 600, "slot_ids": ["⟦SLOT:PROJECT_a1b2c3d4⟧"]},
]


class TestOutline:
    def test_validate_flags_unknown_slots_and_structure(self):
        known, bogus = "⟦SLOT:PROJECT_a1b2c3d4⟧", "⟦SLOT:ORG_ffffffff⟧"
        o = Outline("g", (Section("s1", "T", "O", 100, (known, bogus)),
                          Section("s1", "", "O", 0)))
        problems = o.validate({"⟦SLOT:PROJECT_a1b2c3d4⟧"})
        joined = " | ".join(problems)
        assert "unknown slot" in joined and "duplicate section id" in joined
        assert "empty title" in joined and "non-positive word budget" in joined

    def test_without_unknown_slots_drops_and_counts(self):
        known, bogus = "⟦SLOT:PROJECT_a1b2c3d4⟧", "⟦SLOT:ORG_ffffffff⟧"
        o = Outline("g", (Section("s1", "T", "O", 100, (known, bogus)),))
        o2, dropped = o.without_unknown_slots({"⟦SLOT:PROJECT_a1b2c3d4⟧"})
        assert dropped == 1 and o2.sections[0].slot_ids == ("⟦SLOT:PROJECT_a1b2c3d4⟧",)
        assert o2.validate({"⟦SLOT:PROJECT_a1b2c3d4⟧"}) == []


class TestPlannerPrompt:
    def test_prompt_carries_relations_slots_goal_and_forces_the_tool(self):
        p, g = planner(httpx.Response(200, json=tool_reply(GOOD)))
        run(p.plan(PAYLOAD, "Assess the initiative's Q3 position."))
        body = json.loads(g.calls[0].content)
        user = body["messages"][0]["content"]
        assert "reported decline in" in user and "FINANCIAL_METRIC" in user
        assert "⟦SLOT:PROJECT_a1b2c3d4⟧" in user and "[PERSON]" in user
        assert "Assess the initiative" in user
        assert body["tool_choice"] == {"type": "tool", "name": "plan_outline"}
        assert body["stream"] is False
        assert "never invent" in body["system"].lower()

    def test_the_prompt_carries_the_coarse_character_count_only(self):
        """G2: the exact count moved with which project held which amount, so the
        prompt reads `wire_stats`, which rounds it (see abstract_payload.py)."""
        p, g = planner(httpx.Response(200, json=tool_reply(GOOD)))
        big = AbstractPayload(doc_id="d1", relations=PAYLOAD.relations, slots=PAYLOAD.slots,
                              n_cells=60, n_blocks=15, n_chars=3479)
        run(p.plan(big, "Assess the initiative's Q3 position."))
        user = json.loads(g.calls[0].content)["messages"][0]["content"]
        assert ("DOCUMENT STATS: 60 cells, 15 blocks, about 3000 characters "
                "(to the nearest 1000).") in user
        assert "3479" not in user
        assert "about 1000 characters" in MacroPlanner._user_prompt(PAYLOAD, "g")  # 476: floor


class TestPlannerValidation:
    def test_good_plan_round_trips(self):
        p, _ = planner(httpx.Response(200, json=tool_reply(GOOD)))
        r = run(p.plan(PAYLOAD, "goal"))
        assert [s.title for s in r.outline.sections] == ["Context", "Findings"]
        assert r.outline.sections[0].id == "s1" and r.outline.total_words == 1000
        assert r.resolved_model == "claude-sonnet-5-20260901"
        assert (r.dropped_unknown_slots, r.dropped_sections, r.clamped_budgets) == (0, 0, 0)

    def test_invented_slot_id_is_dropped_and_counted(self):
        bad = [dict(GOOD[0], slot_ids=GOOD[0]["slot_ids"] + ["⟦SLOT:ORG_deadbeef⟧"])]
        p, _ = planner(httpx.Response(200, json=tool_reply(bad)))
        r = run(p.plan(PAYLOAD, "goal"))
        assert r.dropped_unknown_slots == 1
        assert "⟦SLOT:ORG_deadbeef⟧" not in r.outline.sections[0].slot_ids
        assert r.outline.validate({s for s, _ in PAYLOAD.slots}) == []

    def test_references_returned_are_counted_beside_the_ones_dropped(self):
        """The health gate reads dropped over returned; the drop count alone
        cannot tell one bad reference in eighty from one in one."""
        bad = [dict(GOOD[0], slot_ids=GOOD[0]["slot_ids"] + ["⟦SLOT:ORG_deadbeef⟧"]), GOOD[1]]
        p, _ = planner(httpx.Response(200, json=tool_reply(bad)))
        r = run(p.plan(PAYLOAD, "goal"))
        assert (r.refs_returned, r.dropped_unknown_slots) == (4, 1)

    def test_a_clean_plan_returns_references_and_drops_none(self):
        p, _ = planner(httpx.Response(200, json=tool_reply(GOOD)))
        r = run(p.plan(PAYLOAD, "goal"))
        assert (r.refs_returned, r.dropped_unknown_slots) == (3, 0)

    def test_budgets_are_clamped_and_sections_capped(self):
        many = [dict(GOOD[0], word_budget=5), dict(GOOD[1], word_budget=99999)] + [GOOD[1]] * 10
        p, _ = planner(httpx.Response(200, json=tool_reply(many)), max_sections=3,
                       min_budget=150, max_budget=1500)
        r = run(p.plan(PAYLOAD, "goal"))
        assert len(r.outline.sections) == 3
        assert r.outline.sections[0].word_budget == 150
        assert r.outline.sections[1].word_budget == 1500
        assert r.clamped_budgets == 2 and r.dropped_sections == 9

    def test_an_infinite_budget_is_clamped(self):
        """JSON's 1e400 parses to inf, and int(inf) raised an OverflowError the
        planner did not catch until 2026-10-27."""
        body = json.dumps(tool_reply(GOOD)).replace('"word_budget": 400', '"word_budget": 1e400')
        p, _ = planner(httpx.Response(200, content=body.encode(),
                                      headers={"content-type": "application/json"}),
                       min_budget=150, max_budget=1500)
        r = run(p.plan(PAYLOAD, "goal"))
        assert r.outline.sections[0].word_budget == 150 and r.clamped_budgets == 1

    def test_empty_or_malformed_sections_are_dropped(self):
        junk = [{"title": "", "objective": "x", "word_budget": 300, "slot_ids": []},
                "not a dict", GOOD[1]]
        p, _ = planner(httpx.Response(200, json=tool_reply(junk)))
        r = run(p.plan(PAYLOAD, "goal"))
        assert len(r.outline.sections) == 1 and r.dropped_sections == 2

    def test_no_usable_sections_raises(self):
        p, _ = planner(httpx.Response(200, json=tool_reply([{"title": "", "objective": "",
                                                               "word_budget": 1, "slot_ids": []}])))
        with pytest.raises(PlannerError, match="no usable sections"):
            run(p.plan(PAYLOAD, "goal"))

    def test_text_reply_without_tool_use_raises(self):
        body = tool_reply(GOOD)
        body["content"] = [{"type": "text", "text": "Here is a plan: ..."}]
        body["stop_reason"] = "end_turn"
        p, _ = planner(httpx.Response(200, json=body))
        with pytest.raises(PlannerError, match="no structured plan"):
            run(p.plan(PAYLOAD, "goal"))

    def test_gateway_refusal_propagates_untouched(self):
        p, g = planner(httpx.Response(403, json={"allowed": False,
                                                 "reason": "RAW_CONTEXT_CONTAINMENT: 1"}))
        with pytest.raises(EgressRefused):
            run(p.plan(PAYLOAD, "goal"))
        assert len(g.calls) == 1


class TestSlotReferenceSpelling:
    """The planner is shown delimited slot ids and answers with bare ones.

    Found by the first live run, and it is the worst failure shape available:
    every one of 78 references was dropped as unknown, every section got an
    empty slot list, the drafter was told there were no placeholders, and the
    pipeline reported seven sections and zero refusals. A green run whose
    report contained not one private value — the system carrying nothing, and
    nothing in the exit code to say so.
    """

    def test_a_bare_reference_resolves_to_the_issued_id(self):
        known = {"⟦SLOT:PROJECT_389a0ca5⟧"}
        assert _canonical_slot("PROJECT_389a0ca5", known) == "⟦SLOT:PROJECT_389a0ca5⟧"

    def test_the_delimited_reference_still_resolves(self):
        known = {"⟦SLOT:PROJECT_389a0ca5⟧"}
        assert _canonical_slot("⟦SLOT:PROJECT_389a0ca5⟧", known) == "⟦SLOT:PROJECT_389a0ca5⟧"

    def test_an_id_the_core_never_issued_is_still_unknown(self):
        """Resolving spellings must not launder an invented reference into a
        valid one; that is the case the reintegrator refuses on."""
        known = {"⟦SLOT:PROJECT_389a0ca5⟧"}
        assert _canonical_slot("PROJECT_deadbeef", known) is None
        assert _canonical_slot("revenue_actual", known) is None

    def test_a_plan_using_bare_ids_keeps_its_slots(self):
        """End to end through the planner, which is where the drop happened.

        The bare spellings are the two ids PAYLOAD actually issued; the third
        is invented and must still be dropped."""
        bare = [sid[len("⟦SLOT:"):-1] for sid, _ in PAYLOAD.slots]
        p, _g = planner(httpx.Response(200, json=tool_reply([{
            "title": "Position", "objective": "o", "word_budget": 300,
            "slot_ids": [*bare, "PROJECT_notissued"]}])))
        res = run(p.plan(PAYLOAD, "goal"))
        assert res.outline.sections[0].slot_ids == tuple(sid for sid, _ in PAYLOAD.slots)
        assert res.dropped_unknown_slots == 1


class TestEverySpellingTheModelHasUsed:
    """Three live runs, three spellings of the same references.

    The model is shown ``⟦SLOT:ORG_3a8f4003⟧`` and answers inside a JSON array
    with whatever delimiters it pleases: bare twice, and on the baseline arm
    with the prefix kept and the brackets gone. Each unaccepted spelling
    dropped every reference and produced a green run with no values in it.
    """

    KNOWN = {"⟦SLOT:ORG_3a8f4003⟧"}

    @pytest.mark.parametrize("ref", [
        "⟦SLOT:ORG_3a8f4003⟧",          # as issued
        "ORG_3a8f4003",                  # first run, R5 arm
        "SLOT:ORG_3a8f4003",             # baseline arm, 83 of 83
        "[SLOT:ORG_3a8f4003]", "⟦ORG_3a8f4003⟧", " ORG_3a8f4003 ", "\"ORG_3a8f4003\"",
        "slot: ORG_3a8f4003",
    ])
    def test_delimiter_noise_does_not_change_which_slot_is_meant(self, ref):
        assert _canonical_slot(ref, self.KNOWN) == "⟦SLOT:ORG_3a8f4003⟧"

    @pytest.mark.parametrize("ref", [
        "SLOT:ORG_deadbeef",                    # well-formed, never issued
        "not ORG_3a8f4003",                     # a word is not delimiter noise
        "ORG_3a8f4003 and ORG_3a8f4003",        # two ids is not one reference
        "XORG_3a8f4003", "ORG_3a8f4003x",       # part of a longer identifier
        "ORG_3A8F4003",                         # issued ids are lower-case hex
        "revenue_actual", "",
    ])
    def test_anything_else_is_still_unknown(self, ref):
        assert _canonical_slot(ref, self.KNOWN) is None

    def test_the_baseline_arms_spelling_keeps_its_slots_end_to_end(self):
        prefixed = [sid[1:-1] for sid, _ in PAYLOAD.slots]      # "SLOT:PROJECT_a1b2c3d4"
        p, _g = planner(httpx.Response(200, json=tool_reply([{
            "title": "Position", "objective": "o", "word_budget": 300, "slot_ids": prefixed}])))
        res = run(p.plan(PAYLOAD, "goal"))
        assert res.outline.sections[0].slot_ids == tuple(sid for sid, _ in PAYLOAD.slots)
        assert res.dropped_unknown_slots == 0


class TestAPlanThatDropsEveryReferenceIsRefused:
    """Twice a run exited 0 with every section offered no placeholders. The
    count was logged; nothing stopped the run. It now fails closed."""

    def test_all_references_unresolvable_raises(self):
        p, _g = planner(httpx.Response(200, json=tool_reply([
            {"title": "A", "objective": "o", "word_budget": 300,
             "slot_ids": ["SLOT-PROJECT-a1b2c3d4", "PROJECT/a1b2c3d4"]},
            {"title": "B", "objective": "o", "word_budget": 300, "slot_ids": ["nope"]}])))
        with pytest.raises(PlannerError, match="none matched an issued id"):
            run(p.plan(PAYLOAD, "goal"))

    def test_numeric_references_are_counted_and_fail_closed(self):
        """A number where the schema asks for an array raised a TypeError, after the
        request had crossed, until 2026-10-27; it is one reference naming no issued id."""
        p, _g = planner(httpx.Response(200, json=tool_reply([
            {"title": "A", "objective": "o", "word_budget": 300, "slot_ids": 3},
            {"title": "B", "objective": "o", "word_budget": 300, "slot_ids": True}])))
        with pytest.raises(PlannerError, match="returned 2 slot reference.*none matched"):
            run(p.plan(PAYLOAD, "goal"))

    def test_a_numeric_reference_beside_issued_ones_is_dropped_and_counted(self):
        p, _g = planner(httpx.Response(200, json=tool_reply([GOOD[0], dict(GOOD[1], slot_ids=7)])))
        res = run(p.plan(PAYLOAD, "goal"))
        assert (res.refs_returned, res.dropped_unknown_slots) == (3, 1)
        assert res.outline.sections[1].slot_ids == ()

    def test_elements_that_are_not_strings_are_counted_and_fail_closed(self):
        """Until 2026-10-27 a non-string element was dropped before it was counted,
        so a plan made only of such elements was drafted with no placeholders. A
        nested array whose text is an issued id is not resolved either."""
        p, _g = planner(httpx.Response(200, json=tool_reply([
            {"title": "A", "objective": "o", "word_budget": 300, "slot_ids": [1, 2]},
            {"title": "B", "objective": "o", "word_budget": 300, "slot_ids": [{"id": "x"}]},
            {"title": "C", "objective": "o", "word_budget": 300,
             "slot_ids": [["⟦SLOT:PROJECT_a1b2c3d4⟧"]]}])))
        with pytest.raises(PlannerError, match="returned 4 slot reference.*none matched"):
            run(p.plan(PAYLOAD, "goal"))

    def test_a_non_string_element_beside_an_issued_id_is_counted(self):
        bad = dict(GOOD[1], slot_ids=["⟦SLOT:PROJECT_a1b2c3d4⟧", 5])
        p, _g = planner(httpx.Response(200, json=tool_reply([GOOD[0], bad])))
        res = run(p.plan(PAYLOAD, "goal"))
        assert (res.refs_returned, res.dropped_unknown_slots) == (4, 1)
        assert res.outline.sections[1].slot_ids == ("⟦SLOT:PROJECT_a1b2c3d4⟧",)

    @pytest.mark.parametrize("refs", [None, [], 0, False, "", {}, "absent"])
    def test_an_empty_or_absent_array_is_no_reference(self, refs):
        """As before 2026-10-27: these give no reference, and a plan of them is the
        reference-free plan that is accepted, not one that fails closed."""
        sec = {"title": "A", "objective": "o", "word_budget": 300}
        if refs != "absent":
            sec["slot_ids"] = refs
        p, _g = planner(httpx.Response(200, json=tool_reply([GOOD[0], sec])))
        res = run(p.plan(PAYLOAD, "goal"))
        assert (res.refs_returned, res.dropped_unknown_slots) == (2, 0)
        assert res.outline.sections[1].slot_ids == ()

    def test_sections_too_deeply_nested_to_decode_are_no_plan(self):
        """A JSON-encoded field nested past the decoder's depth raised a
        RecursionError from the client until 2026-10-27; it stays a string, and a
        string is not a plan."""
        body = tool_reply(GOOD)
        body["content"][0]["input"] = {"sections": "[" * 100_000 + "]" * 100_000}
        p, _g = planner(httpx.Response(200, json=body))
        with pytest.raises(PlannerError, match="no structured plan"):
            run(p.plan(PAYLOAD, "goal"))

    def test_partial_drops_are_counted_not_refused(self):
        bad = [dict(GOOD[0], slot_ids=GOOD[0]["slot_ids"] + ["⟦SLOT:ORG_deadbeef⟧"])]
        p, _g = planner(httpx.Response(200, json=tool_reply(bad)))
        assert run(p.plan(PAYLOAD, "goal")).dropped_unknown_slots == 1

    def test_a_plan_with_no_references_at_all_is_not_refused(self):
        """An outline that legitimately needs no slots is not the failure."""
        p, _g = planner(httpx.Response(200, json=tool_reply([
            {"title": "A", "objective": "o", "word_budget": 300, "slot_ids": []}])))
        assert run(p.plan(PAYLOAD, "goal")).outline.sections[0].slot_ids == ()
