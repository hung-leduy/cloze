"""Invariant tests for the Aho-Corasick canary matcher and its gateway wiring.

The straddle test is the one that justifies `CanaryStream` existing: scanned
per packet, as the harness spec (Task 1.4) describes, a token split across two
chunks passes. Every split point of a token is exercised, not a sample. The
wiring tests pin that a canary hit is the first verdict /inspect reaches and
that nothing else about /inspect changed.
"""

from __future__ import annotations

import base64
import json
import logging
import secrets
import time

import main
import pytest
from fastapi.testclient import TestClient
from linters.canary_matcher import CanaryMatcher, CanaryStream, CanaryVerdict
from privdeep.tier1_local.canary_injector import CanaryInjector

PREFIX = "CANARY_PRIVDEEP_"

CLEAN = (
    "The reference monitor mediates every outbound request from the trusted zone. "
    "Retrieval augmented generation grounds model output in retrieved passages. "
)


def canary() -> str:
    return PREFIX + secrets.token_hex(16)


def matcher_with(*tokens: str) -> CanaryMatcher:
    m = CanaryMatcher()
    m.add(tokens)
    return m


class TestScan:
    def test_exact_hit(self):
        tok = canary()
        v = matcher_with(tok).scan(f"draft text {tok} more text")
        assert v.blocked and v.hits == 1

    def test_no_hit_on_clean_prose(self):
        v = matcher_with(canary()).scan(CLEAN)
        assert not v.blocked and v.hits == 0

    def test_hit_inside_json_payload(self):
        tok = canary()
        payload = json.dumps(
            {"model": "x", "messages": [{"role": "user", "content": f"Summarise: {tok}"}]}
        )
        assert matcher_with(tok).scan(payload).blocked

    def test_counts_every_occurrence(self):
        tok = canary()
        assert matcher_with(tok).scan(f"{tok} {tok}{tok}").hits == 3

    def test_prefix_alone_is_not_a_hit(self):
        assert not matcher_with(canary()).scan(f"the {PREFIX} prefix by itself").blocked

    def test_one_character_off_is_not_a_hit(self):
        tok = canary()
        near = tok[:-1] + ("0" if tok[-1] != "0" else "1")
        assert not matcher_with(tok).scan(near).blocked

    def test_empty_matcher_never_blocks(self):
        m = CanaryMatcher()
        assert len(m) == 0
        v = m.scan(f"even {canary()} is fine when nothing is registered")
        assert not v.blocked and v.hits == 0
        assert not m.scan("").blocked

    def test_add_accumulates_and_rebuilds(self):
        a, b = canary(), canary()
        m = matcher_with(a)
        assert m.scan(a).blocked and not m.scan(b).blocked
        m.add([b])
        assert len(m) == 2
        assert m.scan(a).blocked and m.scan(b).blocked

    def test_duplicates_do_not_inflate_the_set(self):
        tok = canary()
        m = matcher_with(tok, tok)
        m.add([tok])
        assert len(m) == 1

    def test_empty_token_is_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            CanaryMatcher().add([canary(), ""])

    def test_non_string_token_is_rejected(self):
        with pytest.raises(TypeError):
            CanaryMatcher().add([b"bytes-not-str"])  # type: ignore[list-item]

    def test_verdict_carries_a_count_and_never_the_token(self):
        tok = canary()
        v = matcher_with(tok).scan(tok)
        assert set(CanaryVerdict.__dataclass_fields__) == {"blocked", "hits"}
        assert tok not in v.reason
        assert v.reason == "CANARY_TRIPPED: 1 active canary token(s) in egress"


@pytest.mark.security
class TestStream:
    def test_token_split_at_every_boundary_is_caught(self):
        """The case per-packet scanning misses. Every split point, not a sample."""
        tok = canary()
        text = f"Report draft: {tok} end."
        m = matcher_with(tok)
        for k in range(len(text) + 1):
            s = CanaryStream(m)
            first = s.feed(text[:k])
            second = s.feed(text[k:])
            assert second.blocked, f"missed at split {k}"
            assert second.hits == 1, f"split {k}: hits {second.hits}"
            # If the whole token was in the first chunk it was caught there.
            assert first.blocked == (k >= text.index(tok) + len(tok))

    def test_token_fed_one_character_at_a_time(self):
        tok = canary()
        s = CanaryStream(matcher_with(tok))
        verdicts = [s.feed(ch) for ch in f"x{tok}y"]
        assert verdicts[-1].blocked and verdicts[-1].hits == 1
        assert not verdicts[0].blocked

    def test_straddle_then_whole_token_counts_two(self):
        """hits >= 1 is the contract; the count is exact anyway."""
        tok = canary()
        s = CanaryStream(matcher_with(tok))
        s.feed("a" + tok[:20])
        s.feed(tok[20:] + " b")
        assert s.hits == 1
        v = s.feed(f" then again {tok} whole")
        assert v.blocked and v.hits == 2

    def test_shorter_token_inside_a_longer_tail_is_not_double_counted(self):
        """Different token lengths: the tail is sized for the longest and can hold a shorter one."""
        long_tok, short_tok = canary(), "SHORT_" + secrets.token_hex(4)
        m = matcher_with(long_tok, short_tok)
        s = CanaryStream(m)
        v1 = s.feed("preamble " + short_tok)  # short token ends the chunk, sits inside the tail
        assert v1.hits == 1
        assert len(s._tail) <= m.longest - 1
        v2 = s.feed(" a clean chunk that follows")
        assert v2.hits == 1
        v3 = s.feed(" and another")
        assert v3.hits == 1

    def test_blocked_is_sticky(self):
        tok = canary()
        s = CanaryStream(matcher_with(tok))
        assert s.feed(tok).blocked
        assert s.feed(" perfectly clean afterwards").blocked
        assert s.tripped

    def test_clean_stream_never_blocks(self):
        s = CanaryStream(matcher_with(canary()))
        for i in range(0, len(CLEAN), 7):
            assert not s.feed(CLEAN[i : i + 7]).blocked
        assert s.hits == 0 and not s.tripped

    def test_empty_matcher_stream_never_blocks(self):
        s = CanaryStream(CanaryMatcher())
        tok = canary()
        assert not s.feed(tok[:10]).blocked
        assert not s.feed(tok[10:]).blocked


class TestCost:
    def test_one_megabyte_of_clean_text_scans_well_under_a_second(self):
        m = CanaryMatcher()
        m.add(CanaryInjector().tokens)
        text = CLEAN * (1_000_000 // len(CLEAN) + 1)
        assert len(text) >= 1_000_000
        t0 = time.perf_counter()
        v = m.scan(text)
        elapsed = time.perf_counter() - t0
        assert not v.blocked
        assert elapsed < 1.0, f"1 MB scan took {elapsed:.3f}s"

    def test_one_megabyte_streamed_in_small_chunks(self):
        m = CanaryMatcher()
        m.add(CanaryInjector().tokens)
        text = CLEAN * (1_000_000 // len(CLEAN) + 1)
        s = CanaryStream(m)
        t0 = time.perf_counter()
        for i in range(0, len(text), 1024):
            s.feed(text[i : i + 1024])
        elapsed = time.perf_counter() - t0
        assert not s.tripped
        assert elapsed < 1.0, f"1 MB streamed scan took {elapsed:.3f}s"


@pytest.fixture
def gateway(monkeypatch):
    """A gateway with a fresh, empty canary set and no containment filter."""
    monkeypatch.setattr(main, "_canaries", CanaryMatcher())
    monkeypatch.setattr(main, "_shingle", None)
    return TestClient(main.app)


@pytest.mark.security
class TestGatewayWiring:
    def test_register_then_health(self, gateway):
        toks = [canary() for _ in range(5)]
        r = gateway.post("/canaries", json={"tokens": toks})
        assert r.status_code == 200
        assert r.json() == {"registered": 5, "active": 5}
        assert gateway.get("/health").json()["canaries"] == 5

    def test_second_registration_accumulates(self, gateway):
        gateway.post("/canaries", json={"tokens": [canary(), canary()]})
        r = gateway.post("/canaries", json={"tokens": [canary()]})
        assert r.json() == {"registered": 1, "active": 3}

    def test_malformed_registration_is_rejected(self, gateway):
        assert gateway.post("/canaries", json={"nope": []}).status_code == 422
        assert gateway.post("/canaries", json={"tokens": "not-a-list"}).status_code == 422
        r = gateway.post("/canaries", json={"tokens": [canary(), ""]})
        assert r.status_code == 422
        assert gateway.get("/health").json()["canaries"] == 0

    def test_canary_in_egress_is_refused_with_the_documented_reason(self, gateway, caplog):
        tok = canary()
        gateway.post("/canaries", json={"tokens": [tok]})
        with caplog.at_level(logging.CRITICAL, logger="reference-monitor"):
            r = gateway.post("/inspect", content=f"please summarise {tok}".encode())
        assert r.status_code == 403
        assert r.json() == {
            "allowed": False,
            "reason": "CANARY_TRIPPED: 1 active canary token(s) in egress",
        }
        critical = [rec for rec in caplog.records if rec.levelno == logging.CRITICAL]
        assert critical and "CANARY_TRIPPED" in critical[0].getMessage()
        assert tok not in caplog.text

    def test_canary_verdict_precedes_entropy(self, gateway):
        tok = canary()
        gateway.post("/canaries", json={"tokens": [tok]})
        blob = base64.b64encode(secrets.token_bytes(256)).decode()
        r = gateway.post("/inspect", content=f"{blob} {tok}".encode())
        assert r.json()["reason"].startswith("CANARY_TRIPPED")

    def test_canary_verdict_precedes_the_unsealed_refusal(self, gateway):
        tok = canary()
        gateway.post("/canaries", json={"tokens": [tok]})
        assert gateway.post("/inspect", content=tok.encode()).json()["reason"].startswith(
            "CANARY_TRIPPED"
        )

    def test_other_inspect_behaviour_is_unchanged(self, gateway):
        gateway.post("/canaries", json={"tokens": [canary()]})
        r = gateway.post("/inspect", content=CLEAN.encode())
        assert r.status_code == 403
        assert r.json()["reason"].startswith("CONTAINMENT_FILTER_UNSEALED")
        blob = base64.b64encode(secrets.token_bytes(256)).decode()
        assert gateway.post("/inspect", content=blob.encode()).json()["reason"].startswith(
            "COVERT_CHANNEL_DETECTED"
        )

    def test_injector_and_gateway_agree_end_to_end(self, gateway):
        """The two halves of the invariant, joined on the real wire format."""
        inj = CanaryInjector()
        inj.register("http://testserver", client=gateway)
        assert gateway.get("/health").json()["canaries"] == 5
        r = gateway.post("/inspect", content=inj.context_block().encode())
        assert r.status_code == 403
        assert r.json()["reason"] == "CANARY_TRIPPED: 5 active canary token(s) in egress"
