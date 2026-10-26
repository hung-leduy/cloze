"""The Network Partitioning Invariant, guarded statically.

`docker-compose.yml` says, in a comment at the top of the services block, that
if a second service ever appears on both networks the invariant is void and
*this file* must fail. The file did not exist. `scripts/verify_partition.sh`
does check the invariant, but it needs a running stack, a working probe tool
and a human to type `make verify-partition`; nothing ran on every change, and
an edit to the compose file could void Invariant 2 with the suite still green.

These tests read the compose file and nothing else, so they run in the ordinary
suite in milliseconds and fail on the edit that causes the problem rather than
on the deployment that reveals it. They do not replace the live script: a
static file cannot prove a container has no route. They cover the one failure
mode the script cannot catch early — a change committed before anyone runs it.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
COMPOSE_PATH = ROOT / "docker-compose.yml"
COMPOSE = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))

INTERNAL = "privdeep-internal"
EXTERNAL = "privdeep-external"
MONITOR = "reference-monitor"


def networks_of(service: dict) -> set[str]:
    """Compose accepts `networks` as a list or as a mapping; handle both."""
    nets = service.get("networks") or []
    return set(nets) if isinstance(nets, list) else set(nets.keys())


SERVICES: dict[str, dict] = COMPOSE["services"]


@pytest.mark.security
def test_exactly_one_service_is_dual_homed():
    """The whole architecture rests on this. Every byte that leaves the trusted
    zone has to pass the one service that can reach both sides."""
    dual = {n for n, s in SERVICES.items() if {INTERNAL, EXTERNAL} <= networks_of(s)}
    assert dual == {MONITOR}, f"expected only {MONITOR} on both networks, got {sorted(dual)}"


@pytest.mark.security
def test_every_other_service_is_internal_only():
    for name, svc in SERVICES.items():
        if name == MONITOR:
            continue
        nets = networks_of(svc)
        assert nets == {INTERNAL}, f"{name} is on {sorted(nets)}, not {INTERNAL} alone"


@pytest.mark.security
def test_the_internal_network_is_declared_internal():
    """`internal: true` is what makes Docker install no default route. Without
    it every container on the network can reach the internet directly and the
    monitor becomes decorative."""
    assert COMPOSE["networks"][INTERNAL].get("internal") is True


@pytest.mark.security
def test_no_service_publishes_a_port_to_the_host():
    """A published port would put the monitor's unauthenticated control plane —
    /containment/seal, /inspect, /canaries — on the host's interfaces."""
    published = {n: s["ports"] for n, s in SERVICES.items() if s.get("ports")}
    assert not published, f"services publishing ports: {published}"


@pytest.mark.security
def test_the_compose_file_still_points_at_this_test():
    """The comment in docker-compose.yml names this file as the guard. If the
    file is renamed or moved, the pointer rots silently and the next reader
    believes in a check that no longer exists."""
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    assert "backend/tests/security/test_partition.py" in text
