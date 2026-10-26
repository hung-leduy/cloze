"""Unit tests for AsyncSLMClient, offline via httpx.MockTransport.

These pin the two design facts measured inside the partition on 2026-09-06:
the client must speak the native /api/chat (never /v1), and it must send
think=false with num_ctx=8192 by default. If either regresses, ontology
extraction silently returns empty strings, which is exactly the failure that
first surfaced when the stack came up.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from privdeep.tier1_local import slm_client
from privdeep.tier1_local.slm_client import AsyncSLMClient, SLMError, SLMReply


def canned_reply(content: str = "Vast, deep, blue.") -> dict:
    return {
        "message": {"role": "assistant", "content": content},
        "prompt_eval_count": 25,
        "eval_count": 8,
        "eval_duration": int(0.125e9),  # 8 tok in 0.125 s -> 64 tok/s
        "load_duration": 0,
    }


class Recorder:
    """MockTransport handler that records requests and can fail N times first."""

    def __init__(self, fail_first: int = 0, body: dict | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.fail_first = fail_first
        self.body = body if body is not None else canned_reply()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:14b"}, {"name": "x"}]})
        if self.fail_first > 0:
            self.fail_first -= 1
            raise httpx.ConnectError("simulated transport failure", request=request)
        return httpx.Response(200, json=self.body)


def make(rec: Recorder, **kw) -> AsyncSLMClient:
    return AsyncSLMClient(
        base_url=kw.pop("base_url", "http://local-slm:11434/v1"),
        model="qwen3:14b",
        transport=httpx.MockTransport(rec),
        **kw,
    )


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def no_backoff_sleep(monkeypatch):
    """Retries back off with real sleeps; skip them in unit tests."""

    async def _nop(_):
        return None

    monkeypatch.setattr(slm_client.asyncio, "sleep", _nop)


class TestEndpointChoice:
    def test_v1_suffix_is_stripped_and_native_api_is_used(self):
        rec = Recorder()
        c = make(rec, base_url="http://local-slm:11434/v1")
        run(c.chat([{"role": "user", "content": "hi"}]))
        assert rec.requests[0].url.path == "/api/chat"
        assert "/v1" not in str(rec.requests[0].url)

    def test_base_url_without_v1_also_works(self):
        rec = Recorder()
        c = make(rec, base_url="http://local-slm:11434")
        run(c.chat([{"role": "user", "content": "hi"}]))
        assert rec.requests[0].url.path == "/api/chat"


class TestDefaultsThatMatter:
    def test_thinking_off_and_ctx_8192_by_default(self):
        rec = Recorder()
        run(make(rec).chat([{"role": "user", "content": "hi"}]))
        body = json.loads(rec.requests[0].content)
        assert body["think"] is False
        assert body["stream"] is False
        assert body["options"]["num_ctx"] == 8192
        assert body["model"] == "qwen3:14b"

    def test_caller_can_opt_into_thinking_and_larger_ctx(self):
        rec = Recorder()
        run(make(rec).chat([{"role": "user", "content": "hi"}], think=True, num_ctx=32768))
        body = json.loads(rec.requests[0].content)
        assert body["think"] is True
        assert body["options"]["num_ctx"] == 32768


class TestReply:
    def test_reply_is_parsed_with_throughput(self):
        r = run(make(Recorder()).chat([{"role": "user", "content": "hi"}]))
        assert isinstance(r, SLMReply)
        assert r.content == "Vast, deep, blue."
        assert r.prompt_tokens == 25 and r.completion_tokens == 8
        assert r.tokens_per_second == pytest.approx(64.0)

    def test_malformed_reply_raises(self):
        rec = Recorder(body={"unexpected": True})
        with pytest.raises(SLMError, match="malformed"):
            run(make(rec).chat([{"role": "user", "content": "hi"}]))

    def test_list_models_uses_native_tags_endpoint(self):
        rec = Recorder()
        names = run(make(rec).list_models())
        assert rec.requests[0].url.path == "/api/tags"
        assert "qwen3:14b" in names


class TestRetry:
    def test_recovers_after_transient_failures(self):
        rec = Recorder(fail_first=2)
        r = run(make(rec, retries=3).chat([{"role": "user", "content": "hi"}]))
        assert r.content == "Vast, deep, blue."
        assert len(rec.requests) == 3

    def test_gives_up_after_retries_exhausted(self):
        rec = Recorder(fail_first=5)
        with pytest.raises(SLMError, match="after 3 attempts"):
            run(make(rec, retries=3).chat([{"role": "user", "content": "hi"}]))
        assert len(rec.requests) == 3
