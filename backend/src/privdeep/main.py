"""Trusted orchestrator. Holds raw C_user and has no route off the host.

At this stage the process exists so the Network Partitioning Invariant can be
verified against a live container, and so the local SLM path can be smoke
tested from inside the partition. The pipeline itself lands in W2-W5.
"""

from __future__ import annotations

import logging
import os
import time

import httpx

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("privdeep-core")

SLM_URL = os.environ.get("LOCAL_SLM_URL", "http://local-slm:11434/v1")
SLM_MODEL = os.environ.get("LOCAL_SLM_MODEL", "qwen3:14b")
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://reference-monitor:5050")


def check_slm(timeout: float = 10.0) -> tuple[bool, str]:
    """Confirm the local SLM answers on the internal network."""
    try:
        r = httpx.get(f"{SLM_URL}/models", timeout=timeout)
        r.raise_for_status()
        ids = [m["id"] for m in r.json().get("data", [])]
        present = SLM_MODEL in ids
        return present, f"{len(ids)} model(s); target {'present' if present else 'MISSING'}"
    except Exception as exc:  # noqa: BLE001 - this is a reachability probe
        return False, f"unreachable: {type(exc).__name__}"


def check_gateway(timeout: float = 5.0) -> tuple[bool, str]:
    try:
        r = httpx.get(f"{GATEWAY_URL}/health", timeout=timeout)
        return r.status_code == 200, str(r.json())
    except Exception as exc:  # noqa: BLE001
        return False, f"unreachable: {type(exc).__name__}"


def main() -> None:
    log.info("privdeep-core starting; confined to privdeep-internal by design")
    slm_ok, slm_detail = check_slm()
    log.info("local SLM   %s  (%s)", "OK" if slm_ok else "DOWN", slm_detail)
    gw_ok, gw_detail = check_gateway()
    log.info("gateway     %s  (%s)", "OK" if gw_ok else "DOWN", gw_detail)

    # Stay resident so the partition can be inspected against a live container.
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
