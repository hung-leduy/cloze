"""Build the containment filter inside the partition and hand the gateway its bits.

The filter is built HERE, where the raw documents are, and only the sealed
Bloom bits cross to the gateway. The class itself lives in ``shared/`` so both
containers run byte-identical shingling; a divergence there would make every
gateway lookup miss silently, which is why the shingling parameters also ride
along in the wire header rather than being assumed.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable

import httpx

from privdeep.models.document import Document
from shared.shingle_filter import ShingleFilter

log = logging.getLogger(__name__)

__all__ = ["SealError", "build_filter", "seal_gateway"]


class SealError(RuntimeError):
    """The gateway did not confirm the seal. Egress stays closed."""


def build_filter(docs: Iterable[Document], *, salt: bytes | None = None,
                 n_min: int | None = None, n_max: int | None = None,
                 hit_threshold: int | None = None) -> ShingleFilter:
    salt = salt if salt is not None else os.environ.get("SHINGLE_HMAC_SALT", "").encode()
    if not salt:
        raise SealError("SHINGLE_HMAC_SALT is not set; refusing to build an unsalted filter")
    f = ShingleFilter(
        salt=salt,
        n_min=n_min or int(os.environ.get("SHINGLE_N_MIN", "5")),
        n_max=n_max or int(os.environ.get("SHINGLE_N_MAX", "8")),
        hit_threshold=hit_threshold or int(os.environ.get("SHINGLE_HIT_THRESHOLD", "1")),
    )
    total = 0
    for d in docs:
        total += f.index_document(d.text)
    f.seal()
    log.info("containment filter built: %d shingles", total)
    return f


def seal_gateway(f: ShingleFilter, gateway_url: str | None = None,
                 client: httpx.Client | None = None, timeout: float = 10.0) -> dict:
    url = (gateway_url or os.environ.get("GATEWAY_URL", "http://reference-monitor:5050")).rstrip("/")
    own = client is None
    c = client or httpx.Client(timeout=timeout)
    try:
        r = c.post(f"{url}/containment/seal", content=f.to_wire(),
                   headers={"content-type": "application/octet-stream"})
    except httpx.TransportError as exc:
        raise SealError(f"gateway unreachable: {exc}") from exc
    finally:
        if own:
            c.close()
    if r.status_code != 200:
        raise SealError(f"gateway refused seal: HTTP {r.status_code} {r.text[:200]}")
    body = r.json()
    if not body.get("sealed") or body.get("n_added") != f.bloom.n_added:
        raise SealError(f"gateway seal did not confirm: {body}")
    return body
