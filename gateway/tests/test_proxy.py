"""The live egress path, exercised with a mock upstream.

The test that earns this file its place is
`test_unicode_escaped_private_text_is_still_refused`: the raw request body
contains no private 5-gram (it is all `\\uXXXX`), and a monitor that inspected
bytes would wave it through. Everything else here is the proxy being a proxy.
"""

from __future__ import annotations

import json
import logging

import httpx
import main
import pytest
from fastapi.testclient import TestClient

from shared.shingle_filter import ShingleFilter

SALT = b"proxy-test-salt"
PRIVATE = ("Nguyễn Thị Lan raised the risk in the June review and recommended "
           "deferring the launch until the following year.")
CANARY = "CANARY_PRIVDEEP_" + "ab" * 16


class Upstream:
    """Records what reached 'Anthropic' and returns a canned reply."""

    def __init__(self, status: int = 200, reply_text: str = "Here is the draft.") -> None:
        self.calls: list[httpx.Request] = []
        self.status = status
        self.reply_text = reply_text

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        body = {"id": "msg_x", "type": "message", "role": "assistant", "model": "claude-sonnet-5",
                "content": [{"type": "text", "text": self.reply_text}],
                "usage": {"input_tokens": 10, "output_tokens": 5}}
        return httpx.Response(self.status, json=body,
                              headers={"content-type": "application/json"})


@pytest.fixture
def gw(monkeypatch, tmp_path):
    """A sealed, credentialed monitor with a mock upstream and a temp audit log."""
    monkeypatch.setattr(main, "SHINGLE_HMAC_SALT", SALT)
    monkeypatch.setattr(main, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(main, "ANTHROPIC_BASE_URL", "https://api.anthropic.invalid")
    monkeypatch.setattr(main, "AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(main, "_shingle", None)
    monkeypatch.setattr(main, "_canaries", type(main._canaries)())
    monkeypatch.setattr(main, "_EXTRA_SCREENS", [])
    up = Upstream()
    monkeypatch.setattr(main, "_upstream", httpx.AsyncClient(transport=httpx.MockTransport(up)))
    client = TestClient(main.app)

    f = ShingleFilter(salt=SALT)
    f.index_document(PRIVATE)
    f.seal()
    assert client.post("/containment/seal", content=f.to_wire()).json()["sealed"]
    assert client.post("/canaries", json={"tokens": [CANARY]}).json()["registered"] == 1
    return client, up, tmp_path / "audit.jsonl"


def msg(text: str, **extra) -> dict:
    return {"model": "claude-sonnet-5", "max_tokens": 64,
            "messages": [{"role": "user", "content": text}], **extra}


def audit_lines(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


class TestOutboundRefusals:
    def test_verbatim_private_span_is_refused_and_never_forwarded(self, gw):
        client, up, audit = gw
        r = client.post("/v1/messages", json=msg(f"Summarise: {PRIVATE}"))
        assert r.status_code == 403 and "RAW_CONTEXT_CONTAINMENT" in r.json()["reason"]
        assert up.calls == [], "upstream must not be contacted after a refusal"
        assert audit_lines(audit)[-1]["verdict"] == "refused"

    def test_unicode_escaped_private_text_is_still_refused(self, gw):
        """json.dumps default escaping must not be an evasion."""
        client, up, _ = gw
        body = json.dumps(msg(PRIVATE), ensure_ascii=True).encode()
        assert b"Nguy\\u1ec5n" in body and "Nguyễn".encode() not in body
        r = client.post("/v1/messages", content=body,
                        headers={"content-type": "application/json"})
        assert r.status_code == 403
        assert "RAW_CONTEXT_CONTAINMENT" in r.json()["reason"]
        assert up.calls == []

    def test_canary_in_request_is_refused_critical(self, gw, caplog):
        client, up, _ = gw
        with caplog.at_level(logging.CRITICAL, logger="reference-monitor"):
            r = client.post("/v1/messages", json=msg(f"note {CANARY} end"))
        assert r.status_code == 403 and "CANARY_TRIPPED" in r.json()["reason"]
        assert up.calls == []
        assert any(rec.levelno == logging.CRITICAL for rec in caplog.records)

    def test_streaming_is_refused_not_downgraded(self, gw):
        client, up, _ = gw
        r = client.post("/v1/messages", json=msg("hello", stream=True))
        assert r.status_code == 400 and "STREAMING_NOT_SUPPORTED" in r.json()["reason"]
        assert up.calls == []

    def test_no_api_key_refuses_503(self, gw, monkeypatch):
        client, up, _ = gw
        monkeypatch.setattr(main, "ANTHROPIC_API_KEY", "")
        r = client.post("/v1/messages", json=msg("hello"))
        assert r.status_code == 503 and up.calls == []

    def test_unsealed_filter_refuses_under_fail_closed(self, gw, monkeypatch):
        client, up, _ = gw
        monkeypatch.setattr(main, "_shingle", None)
        r = client.post("/v1/messages", json=msg("hello"))
        assert r.status_code == 403 and "UNSEALED" in r.json()["reason"]
        assert up.calls == []


class TestForwarding:
    def test_clean_request_is_forwarded_verbatim_and_reply_returned(self, gw):
        client, up, audit = gw
        payload = msg("Draft a section on ⟦SLOT:PROJECT_a1b2c3d4⟧ from these relations.")
        r = client.post("/v1/messages", json=payload)
        assert r.status_code == 200
        assert r.json()["content"][0]["text"] == "Here is the draft."
        assert len(up.calls) == 1
        sent = up.calls[0]
        assert sent.url.path == "/v1/messages" and sent.url.host == "api.anthropic.invalid"
        assert json.loads(sent.content) == payload
        assert sent.headers["x-api-key"] == "sk-ant-test"
        assert sent.headers["anthropic-version"] == main.ANTHROPIC_VERSION
        rec = audit_lines(audit)[-1]
        assert rec["verdict"] == "allowed" and rec["upstream_status"] == 200
        assert rec["model"] == "claude-sonnet-5" and rec["response_flags"] == []

    def test_upstream_error_status_passes_through_and_is_audited(self, gw, monkeypatch):
        client, _, audit = gw
        bad = Upstream(status=529)
        monkeypatch.setattr(main, "_upstream",
                            httpx.AsyncClient(transport=httpx.MockTransport(bad)))
        r = client.post("/v1/messages", json=msg("hello"))
        assert r.status_code == 529
        assert audit_lines(audit)[-1]["upstream_status"] == 529

    def test_upstream_unreachable_is_502(self, gw, monkeypatch):
        client, _, _ = gw

        def boom(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down", request=req)

        monkeypatch.setattr(main, "_upstream",
                            httpx.AsyncClient(transport=httpx.MockTransport(boom)))
        r = client.post("/v1/messages", json=msg("hello"))
        assert r.status_code == 502 and "UPSTREAM_UNREACHABLE" in r.json()["reason"]


class TestInboundFindings:
    def test_canary_in_response_is_delivered_but_flagged_critical(self, gw, monkeypatch, caplog):
        client, _, audit = gw
        leaky = Upstream(reply_text=f"as you said, {CANARY}")
        monkeypatch.setattr(main, "_upstream",
                            httpx.AsyncClient(transport=httpx.MockTransport(leaky)))
        with caplog.at_level(logging.CRITICAL, logger="reference-monitor"):
            r = client.post("/v1/messages", json=msg("hello"))
        assert r.status_code == 200, "inbound findings never block delivery to the trusted core"
        flags = audit_lines(audit)[-1]["response_flags"]
        assert any(f.startswith("CANARY_IN_RESPONSE") for f in flags)
        assert any(rec.levelno == logging.CRITICAL for rec in caplog.records)

    def test_containment_hit_in_response_is_delivered_and_flagged(self, gw, monkeypatch):
        client, _, audit = gw
        echo = Upstream(reply_text=f"I recall that {PRIVATE}")
        monkeypatch.setattr(main, "_upstream",
                            httpx.AsyncClient(transport=httpx.MockTransport(echo)))
        r = client.post("/v1/messages", json=msg("hello"))
        assert r.status_code == 200
        flags = audit_lines(audit)[-1]["response_flags"]
        assert any(f.startswith("CONTAINMENT_HIT_IN_RESPONSE") for f in flags)


class TestAudit:
    def test_audit_never_contains_content(self, gw):
        client, _, audit = gw
        payload_text = "Draft about ⟦SLOT:ORG_deadbeef⟧ in the third quarter"
        client.post("/v1/messages", json=msg(payload_text))
        client.post("/v1/messages", json=msg(f"x {PRIVATE}"))
        blob = audit.read_text()
        assert "third quarter" not in blob and "Nguyễn" not in blob and CANARY not in blob
        for rec in audit_lines(audit):
            assert {"direction", "path", "bytes_in", "verdict", "ts"} <= rec.keys()

    def test_unwritable_audit_refuses_delivery(self, gw, monkeypatch, tmp_path):
        client, up, _ = gw
        monkeypatch.setattr(main, "AUDIT_LOG_PATH", str(tmp_path / "no-such-dir" / "a.jsonl"))
        r = client.post("/v1/messages", json=msg("hello"))
        assert r.status_code == 503 and "AUDIT_UNAVAILABLE" in r.json()["reason"]
        assert up.calls == [], "an unaccountable request must never reach the upstream"


def _fail_audit_when(monkeypatch, verdict: str) -> None:
    """Make only the audit write of one verdict fail, as a full disk would."""
    real = main._audit

    def audit(record):
        if record.get("verdict") == verdict:
            raise main.AuditWriteError("stub: disk full")
        real(record)

    monkeypatch.setattr(main, "_audit", audit)


class TestAuditBeforeForward:
    """No audit line, no delivery: the pre-forward record precedes the upstream call."""

    def test_failing_pre_forward_write_means_the_upstream_is_never_called(self, gw, monkeypatch):
        client, up, audit = gw
        _fail_audit_when(monkeypatch, "forwarding")
        r = client.post("/v1/messages", json=msg("hello"))
        assert r.status_code == 503 and "AUDIT_UNAVAILABLE" in r.json()["reason"]
        assert up.calls == []
        assert not audit.exists() or audit_lines(audit) == []

    def test_a_forwarded_request_writes_exactly_two_linked_records_in_order(self, gw):
        client, up, audit = gw
        r = client.post("/v1/messages", json=msg("hello"))
        assert r.status_code == 200 and len(up.calls) == 1
        pre, out = audit_lines(audit)
        assert pre["verdict"] == "forwarding" and out["verdict"] == "allowed"
        assert pre["request_id"] == out["request_id"] and len(pre["request_id"]) == 32
        for k in ("direction", "path", "bytes_in", "model"):
            assert pre[k] == out[k]
        assert "upstream_status" not in pre and "bytes_out" not in pre
        assert out["upstream_status"] == 200 and out["bytes_out"] == len(r.content)
        assert pre["ts"] <= out["ts"] and pre["elapsed_ms"] <= out["elapsed_ms"]

    def test_each_request_gets_its_own_request_id(self, gw):
        client, _, audit = gw
        client.post("/v1/messages", json=msg("hello"))
        client.post("/v1/messages", json=msg("hello again"))
        ids = [rec["request_id"] for rec in audit_lines(audit)]
        assert ids[0] == ids[1] and ids[2] == ids[3] and ids[0] != ids[2]

    def test_a_refused_request_writes_only_its_refusal_record_and_never_forwards(self, gw):
        client, up, audit = gw
        r = client.post("/v1/messages", json=msg(f"Summarise: {PRIVATE}"))
        assert r.status_code == 403 and up.calls == []
        (rec,) = audit_lines(audit)
        assert rec["verdict"] == "refused" and rec["request_id"]
        assert rec["reason"].startswith("RAW_CONTEXT_CONTAINMENT")

    def test_an_exception_before_forwarding_is_audited_as_a_refusal(self, gw, monkeypatch):
        client, up, audit = gw

        def broken(*a, **kw):
            raise RuntimeError("screen crashed")

        monkeypatch.setattr(main, "_inspect_text", broken)
        r = client.post("/v1/messages", json=msg("hello"))
        assert r.status_code == 403 and "PROXY_ERROR" in r.json()["reason"]
        assert up.calls == []
        (rec,) = audit_lines(audit)
        assert rec["verdict"] == "refused" and rec["reason"] == "PROXY_ERROR: RuntimeError"

    def test_upstream_transport_error_leaves_pre_forward_and_error_outcome(self, gw, monkeypatch):
        client, _, audit = gw

        def boom(req: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=req)

        monkeypatch.setattr(main, "_upstream",
                            httpx.AsyncClient(transport=httpx.MockTransport(boom)))
        r = client.post("/v1/messages", json=msg("hello"))
        assert r.status_code == 502
        pre, out = audit_lines(audit)
        assert pre["verdict"] == "forwarding"
        assert out["verdict"] == "upstream_error" and out["reason"] == "ReadTimeout"
        assert out["request_id"] == pre["request_id"]

    def test_an_exception_after_the_upstream_reply_leaves_an_error_outcome(self, gw, monkeypatch):
        """This used to leave no audit line at all for a request C had answered."""
        client, up, audit = gw

        def broken(text):
            raise RuntimeError("response screen crashed")

        monkeypatch.setattr(main, "_inbound_findings", broken)
        r = client.post("/v1/messages", json=msg("hello"))
        assert r.status_code == 403 and "PROXY_ERROR" in r.json()["reason"]
        assert len(up.calls) == 1
        pre, out = audit_lines(audit)
        assert pre["verdict"] == "forwarding" and out["request_id"] == pre["request_id"]
        assert out["verdict"] == "proxy_error" and out["reason"] == "RuntimeError"
        assert out["upstream_status"] == 200

    def test_failing_outcome_write_withholds_the_reply_and_the_pre_forward_record_stays(
            self, gw, monkeypatch):
        client, up, audit = gw
        _fail_audit_when(monkeypatch, "allowed")
        r = client.post("/v1/messages", json=msg("hello"))
        assert r.status_code == 503 and "AUDIT_UNAVAILABLE" in r.json()["reason"]
        assert "Here is the draft." not in r.text
        assert len(up.calls) == 1
        (pre,) = audit_lines(audit)
        assert pre["verdict"] == "forwarding"


class TestInspectDecodes:
    def test_inspect_endpoint_also_decodes_json(self, gw):
        client, _, _ = gw
        body = json.dumps({"text": PRIVATE}, ensure_ascii=True).encode()
        r = client.post("/inspect", content=body)
        assert r.status_code == 403 and "RAW_CONTEXT_CONTAINMENT" in r.json()["reason"]


class TestRegexScreenInChain:
    def test_credential_shaped_string_is_refused_and_never_forwarded(self, gw, monkeypatch):
        """The screen runs on the live path, not only in its own unit tests."""
        from linters.regex_rules import RegexScreen

        client, up, audit = gw
        monkeypatch.setattr(main, "_EXTRA_SCREENS", [RegexScreen().scan])
        leak = "Use this key: sk-ant-api03-" + "A" * 48 + " for the run."
        r = client.post("/v1/messages", json=msg(leak))
        assert r.status_code == 403 and "SECRET_PATTERN" in r.json()["reason"]
        assert up.calls == []
        assert audit_lines(audit)[-1]["reason"].startswith("SECRET_PATTERN")

    def test_slot_ids_and_hashes_pass_the_screen_on_the_live_path(self, gw, monkeypatch):
        from linters.regex_rules import RegexScreen

        client, up, _ = gw
        monkeypatch.setattr(main, "_EXTRA_SCREENS", [RegexScreen().scan])
        r = client.post("/v1/messages", json=msg(
            "Refer to ⟦SLOT:ORG_0badf00d⟧; evidence hash " + "f" * 64 + " [W1]."))
        assert r.status_code == 200 and len(up.calls) == 1


class TestSerialisationIsNotContent:
    def test_compact_json_with_many_slot_ids_is_not_refused_for_entropy(self, gw):
        """The FP instrument found the entropy screen refusing 100/100 compact
        abstract payloads. The monitor now inspects decoded leaves only."""
        client, up, _ = gw
        slots = " ".join(f"⟦SLOT:ORG_{i:08x}⟧" for i in range(40))
        body = json.dumps(msg(f"Plan sections for {slots}"), separators=(",", ":")).encode()
        inspected, parsed = main._decoded_text(body)
        assert parsed is not None
        assert '"model":' not in inspected and "{" not in inspected, \
            "the serialisation must never be part of what is inspected"
        assert "⟦SLOT:ORG_00000027⟧" in inspected, "decoded leaves are inspected"
        r = client.post("/v1/messages", content=body,
                        headers={"content-type": "application/json"})
        assert r.status_code == 200 and len(up.calls) == 1

    def test_encoded_blob_inside_a_string_leaf_is_still_caught(self, gw):
        import base64
        import secrets

        client, up, _ = gw
        blob = base64.b64encode(secrets.token_bytes(256)).decode()
        r = client.post("/v1/messages", json=msg(f"data: {blob}"))
        assert r.status_code == 403 and "COVERT_CHANNEL" in r.json()["reason"]
        assert up.calls == []


class TestFailOpenFlag:
    """`STRICT_FAIL_CLOSED=false`, which is neither the code's nor compose's default (P4).

    With the flag off an unsealed monitor drops one screen, containment, and
    admits what only containment would refuse. The canary, entropy and regex
    screens run before the seal is checked, so they still refuse.
    """

    @pytest.fixture
    def fail_open(self, gw, monkeypatch):
        from linters.regex_rules import RegexScreen

        monkeypatch.setattr(main, "STRICT_FAIL_CLOSED", False)
        monkeypatch.setattr(main, "_shingle", None)
        monkeypatch.setattr(main, "_EXTRA_SCREENS", [RegexScreen().scan])
        return gw

    def test_an_unsealed_filter_skips_containment_and_forwards(self, fail_open):
        client, up, audit = fail_open
        assert client.get("/health").json()["fail_closed"] is False
        r = client.post("/v1/messages", json=msg(f"Summarise: {PRIVATE}"))
        assert r.status_code == 200 and len(up.calls) == 1, \
            "a verbatim private span crosses: nothing but containment refuses it"
        assert audit_lines(audit)[-1]["verdict"] == "allowed"

    @pytest.mark.parametrize("rule", ["CANARY_TRIPPED", "COVERT_CHANNEL", "SECRET_PATTERN"])
    def test_the_other_screens_still_refuse(self, fail_open, rule):
        import base64

        client, up, audit = fail_open
        text = {
            "CANARY_TRIPPED": f"note {CANARY} end",
            "COVERT_CHANNEL": "data: " + base64.b64encode(bytes(range(256))).decode(),
            "SECRET_PATTERN": "Use this key: sk-ant-api03-" + "A" * 48 + " for the run.",
        }[rule]
        r = client.post("/v1/messages", json=msg(text))
        assert r.status_code == 403 and rule in r.json()["reason"]
        assert up.calls == []
        assert audit_lines(audit)[-1]["reason"].startswith(rule)


class TestAuditModelField:
    """The record's `model` is read from the body before inspection, so refused
    records carry it too: only an id the deployment sends is copied."""

    @pytest.mark.parametrize("model", [
        f"Summarise: {PRIVATE}", {"name": PRIVATE}, [PRIVATE], "x" * 5000, 7,
    ], ids=["private-string", "object", "array", "long", "number"])
    def test_a_sender_chosen_model_value_is_not_written(self, gw, model):
        client, _, audit = gw
        client.post("/v1/messages", json={**msg("hello"), "model": model})
        blob = audit.read_text()
        assert "Nguyễn" not in blob and "x" * 64 not in blob
        assert {rec["model"] for rec in audit_lines(audit)} == {"unlisted"}

    def test_the_refusal_for_a_private_model_value_is_still_recorded(self, gw):
        client, up, audit = gw
        r = client.post("/v1/messages", json={**msg("hello"), "model": PRIVATE})
        assert r.status_code == 403 and up.calls == []
        (rec,) = audit_lines(audit)
        assert rec["verdict"] == "refused" and rec["reason"].startswith("RAW_CONTEXT_CONTAINMENT")

    def test_a_listed_id_is_recorded_and_a_missing_one_is_null(self, gw, monkeypatch):
        client, _, audit = gw
        monkeypatch.setattr(main, "_AUDIT_MODEL_IDS", frozenset({"claude-opus-5-5"}))
        client.post("/v1/messages", json={**msg("hello"), "model": "claude-opus-5-5"})
        client.post("/v1/messages", json=msg("hello"))  # claude-sonnet-5, not listed here
        body = msg("hello")
        del body["model"]
        client.post("/v1/messages", json=body)
        models = [rec["model"] for rec in audit_lines(audit)]
        assert models == ["claude-opus-5-5"] * 2 + ["unlisted"] * 2 + [None] * 2
