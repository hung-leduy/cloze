"""Unit tests for CanaryInjector, offline via httpx.MockTransport.

These pin the wire contract with the gateway (POST {gateway}/canaries with
{"tokens": [...]}) and the token format that the gateway matcher and the paper
both describe: prefix + 32 hex characters, all distinct, drawn once per
session. They also pin that registration is verified, not assumed: a 2xx whose
body does not confirm every token is a failure.
"""

from __future__ import annotations

import json
import re

import httpx
import pytest
from privdeep.tier1_local import canary_injector
from privdeep.tier1_local.canary_injector import CanaryInjector, CanaryRegistrationError

HEX32 = re.compile(r"[0-9a-f]{32}")


class Recorder:
    """MockTransport handler: records requests; replies as the gateway would unless told not to."""

    def __init__(self, status: int = 200, body: dict | None = None, fail: bool = False) -> None:
        self.requests: list[httpx.Request] = []
        self.status = status
        self.body = body
        self.fail = fail

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            raise httpx.ConnectError("simulated transport failure", request=request)
        body = self.body
        if body is None:
            sent = json.loads(request.content)["tokens"]
            body = {"registered": len(set(sent)), "active": len(set(sent))}
        return httpx.Response(self.status, json=body)


def client_for(rec: Recorder) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(rec), timeout=5.0)


class TestTokenFormat:
    def test_default_is_five_tokens(self):
        assert len(CanaryInjector().tokens) == 5

    def test_tokens_are_distinct(self):
        inj = CanaryInjector(n=50)
        assert len(set(inj.tokens)) == 50

    def test_prefix_and_32_hex(self):
        inj = CanaryInjector()
        for tok in inj.tokens:
            assert tok.startswith("CANARY_PRIVDEEP_")
            assert HEX32.fullmatch(tok.removeprefix("CANARY_PRIVDEEP_")), tok
            assert len(tok) == len("CANARY_PRIVDEEP_") + 32

    def test_custom_prefix_and_count(self):
        inj = CanaryInjector(prefix="ZZ_", n=2)
        assert len(inj.tokens) == 2
        assert all(t.startswith("ZZ_") and HEX32.fullmatch(t[3:]) for t in inj.tokens)

    def test_generated_once(self):
        inj = CanaryInjector()
        assert inj.tokens is inj.tokens
        assert inj.tokens == inj.tokens

    def test_sessions_do_not_share_tokens(self):
        a, b = CanaryInjector(), CanaryInjector()
        assert not set(a.tokens) & set(b.tokens)

    def test_zero_tokens_is_rejected(self):
        with pytest.raises(ValueError, match="n must be >= 1"):
            CanaryInjector(n=0)


class TestRegister:
    def test_posts_the_wire_contract(self):
        rec = Recorder()
        inj = CanaryInjector()
        inj.register("http://reference-monitor:8080", client=client_for(rec))
        assert len(rec.requests) == 1
        req = rec.requests[0]
        assert req.method == "POST"
        assert str(req.url) == "http://reference-monitor:8080/canaries"
        assert req.headers["content-type"] == "application/json"
        assert json.loads(req.content) == {"tokens": list(inj.tokens)}

    def test_trailing_slash_on_gateway_url_is_tolerated(self):
        rec = Recorder()
        CanaryInjector().register("http://gw/", client=client_for(rec))
        assert str(rec.requests[0].url) == "http://gw/canaries"

    def test_default_client_is_created_with_a_timeout(self, monkeypatch):
        rec = Recorder()
        real_client = httpx.Client
        seen: dict = {}

        def fake_client(**kw):
            seen.update(kw)
            return real_client(transport=httpx.MockTransport(rec), **kw)

        monkeypatch.setattr(canary_injector.httpx, "Client", fake_client)
        CanaryInjector(timeout=3.5).register("http://gw")
        assert seen["timeout"] == 3.5
        assert len(rec.requests) == 1

    @pytest.mark.parametrize("status", [302, 400, 403, 500])
    def test_non_2xx_raises(self, status):
        rec = Recorder(status=status, body={"registered": 5})
        with pytest.raises(CanaryRegistrationError, match=f"HTTP {status}"):
            CanaryInjector().register("http://gw", client=client_for(rec))

    def test_transport_failure_raises(self):
        rec = Recorder(fail=True)
        with pytest.raises(CanaryRegistrationError, match="unreachable"):
            CanaryInjector().register("http://gw", client=client_for(rec))

    def test_short_confirmation_raises(self):
        """A 2xx that confirms fewer tokens than sent is not a registration."""
        rec = Recorder(body={"registered": 4, "active": 4})
        with pytest.raises(CanaryRegistrationError, match="confirmed 4 .* expected 5"):
            CanaryInjector().register("http://gw", client=client_for(rec))

    def test_confirmation_without_count_raises(self):
        rec = Recorder(body={"ok": True})
        with pytest.raises(CanaryRegistrationError, match="confirmed None"):
            CanaryInjector().register("http://gw", client=client_for(rec))

    def test_non_json_confirmation_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>proxy error</html>")

        c = httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)
        with pytest.raises(CanaryRegistrationError, match="not the expected JSON"):
            CanaryInjector().register("http://gw", client=c)


class TestContextBlock:
    def test_block_names_every_token_and_forbids_output(self):
        inj = CanaryInjector()
        block = inj.context_block()
        assert block.startswith("Internal reference tokens (never output): ")
        for tok in inj.tokens:
            assert tok in block

    def test_block_is_one_short_line(self):
        block = CanaryInjector().context_block()
        assert "\n" not in block
        assert len(block) < 400
