"""The partition holds for storage as well as for networks.

`test_partition.py` guards the networks: exactly one service is dual-homed.
That is not enough on its own. Until REC3 the dual-homed monitor mounted the
core's named volume `privdeep-data` read-write at /data, so the one container
holding the API key and a route out could read every report.md, entities.json
and extraction the core wrote, with the network partition intact and every
network test green (F06). A shared volume is a channel across the partition
that no packet capture sees.

These tests read the compose file the way `test_partition.py` does and check
the mounts: the dual-homed service shares no named volume with any
internal-only service, the core does not mount the monitor's audit volume, and
the monitor's audit log still has a writable home on its own volume. The last
one matters because the gateway refuses to deliver a response it cannot audit
(`AUDIT_UNAVAILABLE`), so a split that left the log path unmounted or
read-only would fail closed on the first egress rather than fail a test.

Bind mounts (`./gateway`, `./shared`, the corpus directory) are out of scope
here: they are host paths, the monitor's are read-only code, and the corpus is
bound only into the core.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))

INTERNAL = "privdeep-internal"
EXTERNAL = "privdeep-external"
CORE = "privdeep-core"
SERVICES: dict[str, dict] = COMPOSE["services"]
NAMED_VOLUMES: set[str] = set((COMPOSE.get("volumes") or {}).keys())


def networks_of(service: dict) -> set[str]:
    """Compose accepts `networks` as a list or as a mapping; handle both."""
    nets = service.get("networks") or []
    return set(nets) if isinstance(nets, list) else set(nets.keys())


def mounts_of(service: dict) -> list[tuple[str, str, bool]]:
    """(source, target, read_only) for every entry of `volumes`.

    Compose accepts the short form `source:target[:mode]` and the long form
    `{type, source, target, read_only}`; both are handled, so rewriting a mount
    in the other syntax cannot slip it past these tests.
    """
    out = []
    for v in service.get("volumes") or []:
        if isinstance(v, str):
            parts = v.split(":")
            # An anonymous volume is a bare target; it is private to the
            # container and cannot be shared.
            if len(parts) == 1:
                continue
            mode = parts[2] if len(parts) > 2 else ""
            out.append((parts[0], parts[1], "ro" in mode.split(",")))
        else:
            src = v.get("source")
            if src is None:
                continue
            out.append((src, v["target"], bool(v.get("read_only"))))
    return out


def named_volumes_of(service: dict) -> set[str]:
    return {src for src, _, _ in mounts_of(service) if src in NAMED_VOLUMES}


def _dual_homed() -> list[str]:
    return [n for n, s in SERVICES.items() if {INTERNAL, EXTERNAL} <= networks_of(s)]


def _internal_only() -> list[str]:
    return [n for n, s in SERVICES.items() if networks_of(s) == {INTERNAL}]


def _audit_volume(monitor: dict) -> str:
    """The named volume the monitor's AUDIT_LOG_PATH lands on, writable."""
    log_path = monitor["environment"]["AUDIT_LOG_PATH"]
    homes = [
        (src, tgt)
        for src, tgt, ro in mounts_of(monitor)
        if src in NAMED_VOLUMES and not ro
        and (log_path == tgt or log_path.startswith(tgt.rstrip("/") + "/"))
    ]
    assert homes, (
        f"AUDIT_LOG_PATH={log_path} is not under a writable named volume of the "
        "monitor; the gateway would refuse every egress with AUDIT_UNAVAILABLE"
    )
    # The longest matching target is the mount the path actually resolves to.
    return max(homes, key=lambda h: len(h[1]))[0]


@pytest.mark.security
def test_the_dual_homed_service_shares_no_named_volume_with_the_internal_side():
    dual = _dual_homed()
    assert dual, "no dual-homed service; test_partition.py should already have failed"
    for d in dual:
        mine = named_volumes_of(SERVICES[d])
        for other in _internal_only():
            shared = mine & named_volumes_of(SERVICES[other])
            assert not shared, (
                f"{d} (dual-homed) and {other} (internal-only) share {sorted(shared)}: "
                "a channel across the partition that no network check sees"
            )


@pytest.mark.security
def test_the_monitor_audit_log_has_a_writable_home_on_its_own_volume():
    for d in _dual_homed():
        vol = _audit_volume(SERVICES[d])
        users = sorted(n for n, s in SERVICES.items() if vol in named_volumes_of(s))
        assert users == [d], f"audit volume {vol} is mounted by {users}, not {d} alone"


@pytest.mark.security
def test_the_core_does_not_mount_the_monitor_audit_volume():
    for d in _dual_homed():
        vol = _audit_volume(SERVICES[d])
        assert vol not in named_volumes_of(SERVICES[CORE]), (
            f"{CORE} mounts the monitor's audit volume {vol}"
        )


@pytest.mark.security
def test_the_core_keeps_its_data_volume():
    """The split must not strand the core: its run directories and DuckDB state
    live on privdeep-data at /data, and run_evaluation.py copies runs out from
    /data/runs."""
    assert ("privdeep-data", "/data", False) in mounts_of(SERVICES[CORE])
    assert SERVICES[CORE]["environment"]["DUCKDB_PATH"].startswith("/data/")
