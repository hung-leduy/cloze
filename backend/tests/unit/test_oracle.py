"""The oracle arm sends the raw document, directly, with the credential; and says so."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from privdeep.eval.oracle import run_oracle
from privdeep.models.document import Document, DocumentKind
from privdeep.tier2_cloud.cloud_client import CloudClient

TEXT = "Project Zephyr's Q3 revenue fell after the Hanoi pilot was cancelled."
DOC = Document("d1", DocumentKind.MARKDOWN, Path("d1.md"), TEXT)


class Direct:
    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        body = json.loads(req.content)
        if body.get("tool_choice"):
            plan = {"sections": [{"title": "Context", "objective": "Situate.", "word_budget": 200,
                                  "slot_ids": []},
                                 {"title": "Findings", "objective": "Explain.", "word_budget": 9,
                                  "slot_ids": []}]}
            content = [{"type": "tool_use", "id": "t", "name": "plan_outline", "input": plan}]
        else:
            content = [{"type": "text", "text": "Project Zephyr lost revenue in Hanoi."}]
        return httpx.Response(200, json={
            "id": "m", "type": "message", "role": "assistant", "model": "claude-sonnet-5-o",
            "content": content, "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 40}})


def run(c):
    return asyncio.run(c)


def test_direct_client_sends_credential_and_monitored_client_does_not():
    seen = []
    tr = httpx.MockTransport(lambda r: (seen.append(dict(r.headers)), httpx.Response(200, json={
        "id": "m", "type": "message", "role": "assistant", "model": "x",
        "content": [{"type": "text", "text": "ok"}], "usage": {}}))[1])
    run(CloudClient("https://api.anthropic.invalid", api_key="sk-ant-test", transport=tr)
        .messages([{"role": "user", "content": "hi"}]))
    run(CloudClient("http://reference-monitor:5050", transport=tr)
        .messages([{"role": "user", "content": "hi"}]))
    assert seen[0]["x-api-key"] == "sk-ant-test" and "anthropic-version" in seen[0]
    assert "x-api-key" not in seen[1]


def test_an_infinite_budget_is_clamped_as_in_the_private_arm():
    """JSON's 1e400 is inf, and int(inf) raised an OverflowError the oracle did
    not catch until 2026-10-27, after its plan call had been paid for."""
    d = Direct()

    def handler(req: httpx.Request) -> httpx.Response:
        r = d(req)
        if json.loads(req.content).get("tool_choice"):
            body = json.dumps(json.loads(r.content)).replace('"word_budget": 200',
                                                             '"word_budget": 1e400', 1)
            return httpx.Response(200, content=body.encode())
        return r
    cloud = CloudClient("https://api.anthropic.invalid", api_key="sk-ant-test",
                        transport=httpx.MockTransport(handler))
    res = run(run_oracle([DOC], "Assess Q3.", cloud, min_budget=150))
    assert res.sections[0]["word_budget"] == 150


def test_oracle_refuses_a_monitored_client():
    with pytest.raises(ValueError, match="direct"):
        run(run_oracle([DOC], "goal", CloudClient("http://reference-monitor:5050")))


def test_oracle_puts_raw_text_in_every_prompt_and_reuses_the_plan_tool():
    d = Direct()
    cloud = CloudClient("https://api.anthropic.invalid", api_key="sk-ant-test",
                        transport=httpx.MockTransport(d))
    res = run(run_oracle([DOC], "Assess Q3.", cloud, min_budget=150))
    assert len(d.calls) == 3                       # plan + 2 drafts
    for req in d.calls:
        blocks = json.loads(req.content)["messages"][0]["content"]
        assert TEXT in "".join(b["text"] for b in blocks)
        assert req.headers["x-api-key"] == "sk-ant-test"
    plan_body = json.loads(d.calls[0].content)
    assert plan_body["tools"][0]["name"] == "plan_outline"
    assert res.report_markdown.startswith("# Assess Q3.") and "## Findings" in res.report_markdown
    assert res.sections[1]["word_budget"] == 150       # clamped like the private arm
    assert res.resolved_models == ["claude-sonnet-5-o"]
    assert res.input_tokens == 300 and res.direct
    rec = json.loads(res.record_json())
    assert "report_markdown" not in rec and rec["arm"] == "oracle-unconstrained"


def _blocks(req) -> list[dict]:
    return json.loads(req.content)["messages"][0]["content"]


def test_the_cached_prefix_is_byte_identical_across_every_call():
    """The property that makes caching work, and the one that silently breaks.

    Caching is a prefix match, so one varying byte anywhere before the
    breakpoint costs the whole saving with no error and no signal other than a
    cache-read count stuck at zero. The corpus is resent on the plan call and
    on every section call; if those prefixes are equal, eight of the nine reads
    bill at a fraction of the input rate instead of in full.

    The original prompt put the documents *after* the per-section objective,
    which is the one arrangement under which no two calls can ever share a
    prefix.
    """
    d = Direct()
    cloud = CloudClient("https://api.anthropic.invalid", api_key="sk-ant-test",
                        transport=httpx.MockTransport(d))
    run(run_oracle([DOC], "Assess Q3.", cloud, min_budget=150))

    prefixes = {_blocks(req)[0]["text"] for req in d.calls[1:]}   # the section calls
    assert len(prefixes) == 1, "section prompts do not share a prefix; nothing will cache"
    assert TEXT in prefixes.pop(), "the corpus must be inside the cached prefix, not after it"

    for req in d.calls:
        blocks = _blocks(req)
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in blocks[-1], "the varying block must not be a breakpoint"


def test_the_section_marker_is_not_inside_the_cached_prefix():
    """The outline is stable; marking the current section inside it would put a
    per-section byte in the prefix and defeat the cache from the second call
    on. The section identity belongs in the varying block."""
    d = Direct()
    cloud = CloudClient("https://api.anthropic.invalid", api_key="sk-ant-test",
                        transport=httpx.MockTransport(d))
    run(run_oracle([DOC], "Assess Q3.", cloud, min_budget=150))
    for req in d.calls[1:]:
        stable, varying = _blocks(req)[0]["text"], _blocks(req)[-1]["text"]
        assert "THIS SECTION" in varying and "THIS SECTION" not in stable


def test_no_sampling_parameters_are_sent():
    """Sonnet 5 rejects temperature / top_p / top_k with a 400. Every cloud call
    in this system carried `temperature` until it was removed, so the first live
    run would have failed on the very first request."""
    d = Direct()
    cloud = CloudClient("https://api.anthropic.invalid", api_key="sk-ant-test",
                        transport=httpx.MockTransport(d))
    run(run_oracle([DOC], "Assess Q3.", cloud, min_budget=150))
    for req in d.calls:
        body = json.loads(req.content)
        for banned in ("temperature", "top_p", "top_k"):
            assert banned not in body, f"{banned} is rejected with a 400 on this model"
        assert body["output_config"]["effort"] in {"low", "medium", "high", "xhigh", "max"}


def test_truncation_is_reported_not_swallowed():
    """The oracle is the baseline the utility claim is measured against, and it
    is capped while the private arm reads the whole corpus. A run that dropped
    corpus has to carry that fact next to its number."""
    from pathlib import Path

    from privdeep.models.document import Document, DocumentKind

    big = Document("big", DocumentKind.MARKDOWN, Path("big.md"), "word " * 5_000)
    d = Direct()
    cloud = CloudClient("https://api.anthropic.invalid", api_key="sk-ant-test",
                        transport=httpx.MockTransport(d))
    res = run(run_oracle([big], "Assess.", cloud, max_doc_chars=1_000, min_budget=150))
    assert res.truncated_chars > 0 and res.max_doc_chars == 1_000
    assert json.loads(res.record_json())["truncated_chars"] == res.truncated_chars

    res2 = run(run_oracle([DOC], "Assess.", cloud, min_budget=150))
    assert res2.truncated_chars == 0


def test_both_arms_plan_and_draft_at_one_effort():
    """Effort parity (INS2). The oracle's PLAN_EFFORT and DRAFT_EFFORT said they
    were the private arm's defaults, imported; they were literals, and the
    planner and drafter hard-coded their own. One constant now feeds all three,
    and what the oracle actually sends is checked, not only the names."""
    import inspect

    from privdeep.eval.oracle import DRAFT_EFFORT, PLAN_EFFORT
    from privdeep.tier2_cloud.cloud_client import REPORT_EFFORT
    from privdeep.tier2_cloud.macro_planner import MacroPlanner
    from privdeep.tier2_cloud.section_drafter import SectionDrafter

    planner = inspect.signature(MacroPlanner).parameters["effort"].default
    drafter = inspect.signature(SectionDrafter).parameters["effort"].default
    assert planner == drafter == PLAN_EFFORT == DRAFT_EFFORT == REPORT_EFFORT
    d = Direct()
    cloud = CloudClient("https://api.anthropic.invalid", api_key="sk-ant-test",
                        transport=httpx.MockTransport(d))
    run(run_oracle([DOC], "Assess Q3.", cloud, min_budget=150))
    assert {json.loads(r.content)["output_config"]["effort"] for r in d.calls} == {REPORT_EFFORT}
