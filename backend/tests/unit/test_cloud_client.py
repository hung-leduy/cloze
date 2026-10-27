"""CloudClient against a scripted gateway. The rule under test: a refusal is never retried."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from privdeep.tier2_cloud import cloud_client
from privdeep.tier2_cloud.cloud_client import (
    CloudClient,
    CloudError,
    EgressRefused,
    GatewayError,
)


def ok_body(text: str = "Draft text.", model: str = "claude-sonnet-5-20260901", **extra) -> dict:
    return {
        "id": "msg_1", "type": "message", "role": "assistant", "model": model,
        "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
        "usage": {"input_tokens": 12, "output_tokens": 7}, **extra,
    }


class Gateway:
    def __init__(self, script: list[httpx.Response]) -> None:
        self.script = list(script)
        self.calls: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        if not self.script:
            raise AssertionError("gateway called more times than scripted")
        return self.script.pop(0)


def client(script: list[httpx.Response], **kw) -> tuple[CloudClient, Gateway]:
    g = Gateway(script)
    c = CloudClient("http://reference-monitor:5050", transport=httpx.MockTransport(g), **kw)
    return c, g


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _nop(_):
        return None
    monkeypatch.setattr(cloud_client.asyncio, "sleep", _nop)


class TestShape:
    def test_posts_messages_shape_to_the_gateway_only(self):
        c, g = client([httpx.Response(200, json=ok_body())])
        r = run(c.messages([{"role": "user", "content": "hi"}], system="sys", max_tokens=99))
        req = g.calls[0]
        assert req.url.host == "reference-monitor" and req.url.path == "/v1/messages"
        body = json.loads(req.content)
        assert body["stream"] is False
        assert body["model"] == "claude-sonnet-5" and body["max_tokens"] == 99
        assert body["system"] == "sys" and body["messages"][0]["content"] == "hi"
        assert r.text == "Draft text." and r.stop_reason == "end_turn"

    def test_resolved_model_id_is_captured_for_the_manifest(self):
        c, _ = client([httpx.Response(200, json=ok_body(model="claude-sonnet-5-20260901"))])
        r = run(c.messages([{"role": "user", "content": "hi"}]))
        assert r.model == "claude-sonnet-5-20260901" != c.model
        assert (r.input_tokens, r.output_tokens) == (12, 7)

    def test_tool_use_lands_in_structured(self):
        body = ok_body()
        body["content"] = [{"type": "tool_use", "id": "t1", "name": "plan",
                            "input": {"sections": ["a", "b"]}}]
        c, g = client([httpx.Response(200, json=body)])
        r = run(c.messages([{"role": "user", "content": "plan"}],
                           tools=[{"name": "plan", "input_schema": {"type": "object"}}],
                           tool_choice={"type": "tool", "name": "plan"}))
        assert r.structured == {"sections": ["a", "b"]} and r.text == ""
        sent = json.loads(g.calls[0].content)
        assert sent["tool_choice"] == {"type": "tool", "name": "plan"}


class TestRefusalIsFinal:
    def test_403_refusal_raises_and_is_never_retried(self):
        c, g = client([httpx.Response(403, json={"allowed": False,
                                                  "reason": "RAW_CONTEXT_CONTAINMENT: 1 hit"})],
                      max_retries=3)
        with pytest.raises(EgressRefused) as ei:
            run(c.messages([{"role": "user", "content": "x"}]))
        assert "RAW_CONTEXT_CONTAINMENT" in ei.value.reason
        assert len(g.calls) == 1, "a refusal must not be retried"

    def test_streaming_refusal_is_also_final(self):
        c, g = client([httpx.Response(400, json={"allowed": False,
                                                  "reason": "STREAMING_NOT_SUPPORTED"})])
        with pytest.raises(EgressRefused):
            run(c.messages([{"role": "user", "content": "x"}]))
        assert len(g.calls) == 1


class TestUpstreamErrors:
    def test_401_is_terminal(self):
        c, g = client([httpx.Response(401, json={"type": "error", "error": {
            "type": "authentication_error", "message": "API key is invalid."}})], max_retries=3)
        with pytest.raises(CloudError) as ei:
            run(c.messages([{"role": "user", "content": "x"}]))
        assert ei.value.status == 401 and "invalid" in ei.value.message
        assert len(g.calls) == 1

    def test_529_then_200_is_retried(self):
        c, g = client([
            httpx.Response(529, json={"type": "error", "error": {"type": "overloaded_error",
                                                                  "message": "Overloaded"}}),
            httpx.Response(200, json=ok_body()),
        ])
        r = run(c.messages([{"role": "user", "content": "x"}]))
        assert r.text == "Draft text." and len(g.calls) == 2

    def test_retry_after_header_is_honoured(self, monkeypatch):
        delays: list[float] = []

        async def rec(d):
            delays.append(d)
        monkeypatch.setattr(cloud_client.asyncio, "sleep", rec)
        c, _ = client([
            httpx.Response(429, headers={"retry-after": "7"},
                           json={"type": "error", "error": {"type": "rate_limit_error",
                                                            "message": "slow down"}}),
            httpx.Response(200, json=ok_body()),
        ])
        run(c.messages([{"role": "user", "content": "x"}]))
        assert delays == [7.0]

    def test_exhausted_retries_raise_last_error(self):
        c, g = client([httpx.Response(503, json={"type": "error", "error": {
            "type": "api_error", "message": "down"}})] * 3, max_retries=3)
        with pytest.raises(CloudError) as ei:
            run(c.messages([{"role": "user", "content": "x"}]))
        assert ei.value.status == 503 and len(g.calls) == 3


class TestAnUnparseableReply:
    """A 200 that is not a Messages reply raised an untyped error until 2026-10-27,
    so a drafter's ended the run instead of its section. It is a CloudError now,
    not retried, whose message names the error class and quotes nothing."""

    @pytest.mark.parametrize("resp", [
        httpx.Response(200, content=b"<html>upstream proxy page for Project Zephyr</html>"),
        httpx.Response(200, json=dict(ok_body("Project Zephyr"), usage=None)),
        httpx.Response(200, json=["Project Zephyr"]),
        httpx.Response(200, content=json.dumps(ok_body("Project Zephyr")).replace(
            '"input_tokens": 12', '"input_tokens": 1e400').encode()),
        httpx.Response(200, content=b"[" * 100_000 + b"]" * 100_000),
        httpx.Response(200, json=dict(ok_body("Project Zephyr"), content=None)),
    ], ids=["not JSON", "usage null", "not an object", "a count of 1e400", "nested too deep",
            "content null"])
    def test_is_a_cloud_error_that_quotes_nothing(self, resp):
        c, g = client([resp], max_retries=3)
        with pytest.raises(CloudError) as ei:
            run(c.messages([{"role": "user", "content": "x"}]))
        assert ei.value.status == 200 and ei.value.message.startswith("unparseable reply (")
        assert "Zephyr" not in str(ei.value) and len(g.calls) == 1


class TestAMalformedErrorAnswer:
    """An upstream error whose "error" field is not an object, or whose body is
    nested too deep to decode, raised an untyped error until 2026-10-27 (a body
    that was not JSON, or not an object, was already a CloudError); it is a
    CloudError of its status, retried when the status is transient."""

    @pytest.mark.parametrize("error", ["overloaded", None, ["x"]])
    def test_an_error_field_that_is_not_an_object(self, error):
        c, g = client([httpx.Response(401, json={"type": "error", "error": error})])
        with pytest.raises(CloudError) as ei:
            run(c.messages([{"role": "user", "content": "x"}]))
        assert ei.value.status == 401 and len(g.calls) == 1

    def test_a_body_nested_too_deep_is_still_a_typed_error(self):
        deep = b"[" * 100_000 + b"]" * 100_000
        c, g = client([httpx.Response(503, content=deep)] * 2, max_retries=2)
        with pytest.raises(CloudError) as ei:
            run(c.messages([{"role": "user", "content": "x"}]))
        assert ei.value.status == 503 and len(g.calls) == 2


class TestGatewayFailures:
    def test_monitor_503_is_gateway_error(self):
        c, _ = client([httpx.Response(503, json={"allowed": False,
                                                  "reason": "AUDIT_UNAVAILABLE"})] * 3)
        with pytest.raises(GatewayError, match="AUDIT_UNAVAILABLE"):
            run(c.messages([{"role": "user", "content": "x"}]))

    def test_transport_error_is_gateway_error_after_retries(self):
        calls = []

        def boom(req):
            calls.append(req)
            raise httpx.ConnectError("no route", request=req)
        c = CloudClient("http://reference-monitor:5050", transport=httpx.MockTransport(boom),
                        max_retries=2)
        with pytest.raises(GatewayError, match="unreachable"):
            run(c.messages([{"role": "user", "content": "x"}]))
        assert len(calls) == 2


class TestToolArgumentsArriveMisshapen:
    """A forced tool call constrains the schema, not the model's serialisation.

    Observed on the first real planner call: `sections` was declared as an
    array and arrived as a JSON-encoded string that re-wrapped the whole object
    under its own key. The planner's isinstance check failed and the run died
    after Tier 1 had already done every local step, which is the expensive half
    in wall-clock and the only half that touches the private corpus.
    """

    def test_a_json_encoded_field_is_decoded(self):
        got = CloudClient._unwrap_tool_input({"sections": '[{"title": "A"}]'})
        assert got == {"sections": [{"title": "A"}]}

    def test_a_field_rewrapping_the_whole_object_is_unwrapped(self):
        """The exact shape that broke the live run."""
        got = CloudClient._unwrap_tool_input(
            {"sections": '{"sections": [{"title": "A", "word_budget": 120}]}'})
        assert got == {"sections": [{"title": "A", "word_budget": 120}]}

    def test_a_genuine_string_argument_is_left_alone(self):
        got = CloudClient._unwrap_tool_input({"rationale": "B is better organised."})
        assert got == {"rationale": "B is better organised."}

    def test_a_string_that_merely_starts_like_json_is_left_alone(self):
        got = CloudClient._unwrap_tool_input({"rationale": "{not json at all"})
        assert got == {"rationale": "{not json at all"}

    def test_a_rewrap_under_a_different_key_is_not_flattened(self):
        """Only a field re-wrapping itself is unwrapped; anything else keeps
        the decoded structure rather than being silently reshaped."""
        got = CloudClient._unwrap_tool_input({"a": '{"b": 1}'})
        assert got == {"a": {"b": 1}}

    def test_non_dict_input_yields_none(self):
        assert CloudClient._unwrap_tool_input(["not", "a", "dict"]) is None
        assert CloudClient._unwrap_tool_input(None) is None

    def test_the_parser_applies_it_end_to_end(self):
        reply = CloudClient._parse({
            "model": "claude-sonnet-5", "stop_reason": "tool_use",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": [{"type": "tool_use", "name": "plan_outline",
                         "input": {"sections": '{"sections": [{"title": "A"}]}'}}],
        })
        assert isinstance(reply.structured["sections"], list)
