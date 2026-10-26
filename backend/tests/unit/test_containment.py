"""The core must never believe the gateway is sealed unless the gateway said so."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from privdeep.models.document import Document, DocumentKind
from privdeep.tier1_local.containment import SealError, build_filter, seal_gateway

from shared.shingle_filter import ShingleFilter

SALT = b"unit-salt"
DOC = Document(
    "d", DocumentKind.MARKDOWN, Path("d.md"),
    "Project Zephyr's Q3 revenue fell twelve percent after the Hanoi pilot was cancelled.",
)


def test_build_requires_salt(monkeypatch):
    monkeypatch.delenv("SHINGLE_HMAC_SALT", raising=False)
    with pytest.raises(SealError, match="SALT"):
        build_filter([DOC])


def test_build_indexes_and_seals():
    f = build_filter([DOC], salt=SALT, n_min=5, n_max=8, hit_threshold=1)
    assert f.sealed and f.bloom.n_added > 0
    assert f.inspect("Project Zephyr's Q3 revenue fell twelve percent").blocked


def test_seal_round_trips_through_the_wire_the_gateway_will_receive():
    f = build_filter([DOC], salt=SALT)
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        g = ShingleFilter.from_wire(req.content, salt=SALT)
        return httpx.Response(200, json={"sealed": True, "n_added": g.bloom.n_added})

    body = seal_gateway(f, "http://gw", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert seen["path"] == "/containment/seal" and body["sealed"]


@pytest.mark.parametrize("status,payload", [
    (503, {"sealed": False, "reason": "NO_SALT"}),
    (422, {"sealed": False, "reason": "BAD_WIRE"}),
    (200, {"sealed": True, "n_added": 0}),
    (200, {"sealed": False}),
])
def test_unconfirmed_seal_raises(status, payload):
    f = build_filter([DOC], salt=SALT)
    tr = httpx.MockTransport(lambda r: httpx.Response(status, json=payload))
    with pytest.raises(SealError):
        seal_gateway(f, "http://gw", client=httpx.Client(transport=tr))


def test_transport_failure_raises():
    f = build_filter([DOC], salt=SALT)

    def boom(r):
        raise httpx.ConnectError("down", request=r)

    with pytest.raises(SealError, match="unreachable"):
        seal_gateway(f, "http://gw", client=httpx.Client(transport=httpx.MockTransport(boom)))
