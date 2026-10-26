"""Both orderings are judged; the averages and the position bias are both visible."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from privdeep.eval.judge import RUBRIC, judge_pair
from privdeep.tier2_cloud.cloud_client import CloudClient, EgressRefused

CRIT = [c for c, _ in RUBRIC]


class Judge:
    """Scores slot A higher than slot B by a fixed margin: a position-biased judge."""

    def __init__(self, a=4, b=3) -> None:
        self.calls: list[dict] = []
        self.a, self.b = a, b

    def __call__(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        self.calls.append(body)
        scores = {"A": dict.fromkeys(CRIT, self.a), "B": dict.fromkeys(CRIT, self.b),
                  "rationale": "A read better."}
        return httpx.Response(200, json={
            "id": "m", "type": "message", "role": "assistant", "model": "judge-1",
            "content": [{"type": "tool_use", "id": "t", "name": "score_reports", "input": scores}],
            "stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 5}})


def run(c):
    return asyncio.run(c)


def test_both_orders_are_judged_and_bias_is_measured():
    j = Judge()
    cloud = CloudClient("http://gw", transport=httpx.MockTransport(j))
    r = run(judge_pair("goal", "REPORT ONE", "REPORT TWO", cloud))
    assert len(j.calls) == 2
    first, second = j.calls[0]["messages"][0]["content"], j.calls[1]["messages"][0]["content"]
    assert "REPORT A ===\nREPORT ONE" in first and "REPORT A ===\nREPORT TWO" in second
    assert j.calls[0]["tool_choice"]["name"] == "score_reports"
    # A biased judge gives each report 4 in slot A and 3 in slot B -> both average 3.5
    assert r.a_mean == pytest.approx(3.5) and r.b_mean == pytest.approx(3.5)
    assert r.position_bias == pytest.approx(1.0)
    assert r.a_by_order == [dict.fromkeys(CRIT, 4), dict.fromkeys(CRIT, 3)]
    assert r.judge_models == ["judge-1"] and r.input_tokens == 20
    assert len(r.rationales) == 2


def test_reports_are_truncated_for_judging():
    j = Judge()
    cloud = CloudClient("http://gw", transport=httpx.MockTransport(j))
    run(judge_pair("goal", "x" * 50_000, "short", cloud, max_chars=1000))
    assert "[report truncated for judging]" in j.calls[0]["messages"][0]["content"]


def test_monitor_refusal_propagates():
    cloud = CloudClient("http://gw", transport=httpx.MockTransport(
        lambda r: httpx.Response(403, json={"allowed": False,
                                            "reason": "RAW_CONTEXT_CONTAINMENT: 3"})))
    with pytest.raises(EgressRefused):
        run(judge_pair("goal", "private values here", "oracle", cloud))
