#!/usr/bin/env python3
"""Produce every number in the paper's evaluation, from one command, as artifacts.

Why this exists
---------------
Scope §6 block M3 says "one driver script emits every table in the paper as
JSON artifacts under ``eval/``. No table is hand-copied." That sentence is the
whole specification. Before this file, four instruments existed and nothing
joined them: the private arm, the oracle arm, the pairwise judge and the
reconstruction adversary each ran alone, and turning four outputs into a table
was a manual step with no record of which run produced which figure.

The partition decides the shape
--------------------------------
The two arms cannot run in the same place, and that is not an inconvenience,
it is the claim:

* The **private arm** runs *inside* ``privdeep-core``, which has no default
  route. It reaches the cloud only through the reference monitor.
* The **oracle arm** must run *outside* the partition, on the host, with a
  direct client. Sending raw documents to the cloud is the thing the partition
  exists to prevent, so the baseline is defined by bypassing it.

So this is a two-phase driver. Phase one runs in the container; its local
extraction is free, but its planner and section drafts are billable cloud
calls made through the monitor. Phase two runs on the host and costs more.
They are separate subcommands on purpose: phase two is re-runnable against a
phase-one result without paying for phase one again, and a phase-two crash
never destroys the expensive part of what came before it.

``privdeep-data`` is a named volume, so the host cannot read the run directory
directly; phase one copies it out with ``docker compose cp``.

What leaves the partition here, stated
---------------------------------------
This driver performs the evaluation-only egress that ``THREAT_MODEL.md`` §5
discloses. The oracle arm sends raw documents to the cloud. The judge is
reached directly and sees the private arm's reintegrated report, which carries
real values. The adversary is sent the egress trace as rendered by
``reconstruction._render_trace_full``: what crossed, with each request the
monitor refused replaced by a marker naming its stage and rule. None of the
three runs in a deployment; all three are disclosed as leaks rather than
counted as system behaviour.

What the numbers can and cannot carry
--------------------------------------
* **Small N.** Utility is a mean over a handful of tasks. Every per-task value
  is written out beside the aggregate so a reader sees the spread rather than a
  mean standing alone; with N in the tens, the spread is the finding.
* **The judge is not repeatable, and one reading is not a measurement.** Sonnet
  5 rejects the sampling parameters, so no setting makes a judge call
  reproducible. Measured on the first live run: the same report pair scored
  1.75 for the private arm on its first judging and 2.125-2.375 on four
  re-judgings; position bias read 0.375 once and 0.75-0.875 after. A single
  draw can sit half a point from the others, so ``--judge-repeats`` defaults
  to 3 and the spread travels with every mean. Both orderings are still
  scored inside each repeat, and the disagreement is reported as position
  bias rather than averaged away.
* **Recovery is a lower bound.** One adversary tells you "at least this much
  leaks", never "at most". ``reconstruction.py`` says so and so does the
  threat model.
* **Truncation is not symmetric.** The oracle is capped at ``max_doc_chars``
  while the private arm abstracts the whole corpus locally, so a corpus over
  the cap makes the baseline read a prefix. Any run that truncates records the
  dropped character count and this driver refuses to aggregate silently over
  it — see ``truncated_tasks`` in the output.

Spending real money
--------------------
Every phase-two task costs roughly $0.50 at the current rates and caps (the
adversary's trace cap doubled to 120,000 characters in INS4, adding about
$0.03 to the estimate). The
driver prints an itemised estimate and refuses to start without ``--yes``, and
it writes each task's artifacts the moment they exist, so an interruption keeps
what has been paid for. Re-running skips tasks whose artifacts are already on
disk unless ``--force`` is given, and ``--force`` never deletes: the earlier
attempt is moved (phase one) or copied (phase two) to
``eval/attempts/<run>__attempt<k>/``, egress trace included. A refused or
failed attempt is an outcome, and deleting it would bias the refusal count
towards zero by construction.

What ran, recorded
-------------------
``eval/runs/`` is gitignored and the source is bind-mounted, so the manifest is
the only record of which code produced a run. Before a billable phase the
driver computes, on the host, the commit, whether tracked files (or untracked
files under the mounted code) differ from it, and a sha256 over the mounted
code; phase one passes them into the container, where ``RunManifest`` records
them. A dirty tree is refused unless ``--allow-dirty`` is given. The code is
hashed again before and after every run, and a change stops the batch: each
task's pipeline imports what is on disk when it starts. After the run
the driver adds what only the host can see: the Ollama image and model
digests, whether the model sits on the GPU, and when the monitor last started
(``--recreate`` restarts it and the core once per batch, so a batch runs
against the monitor code on disk). Those are recorded, never gated on.

Usage
-----
    # phase one, once per task, runs in the container; billable planner and drafts
    python scripts/run_evaluation.py private --tasks eval/tasks.json --yes

    # phase two, costs money, runs on the host
    python scripts/run_evaluation.py measure --tasks eval/tasks.json --yes

    # aggregate whatever is on disk into the paper's tables (free, offline)
    python scripts/run_evaluation.py aggregate --tasks eval/tasks.json \
        [--alt-key PATH]      # also score r1 against another gold key, or a directory
                              # of <task_id>.json keys (eval/calibration/prefix_keys)

``eval/tasks.json`` is a list of ``{"id", "corpus", "goal"}``, tracked, one task
per corpus under ``eval/corpora/``. ``corpus`` is a host path, and a relative
one is resolved against the repository root rather than the caller's working
directory. The container sees it at ``/corpus`` through the compose bind mount,
so one corpus directory per task means re-pointing ``PRIVDEEP_CORPUS_DIR``, and
the driver does that per task. No goal may contain a generator surface of its
corpus (a test holds them to it): the goal crosses in the clear, and the
surface scan excludes it.

What ``aggregate`` pools, and what it keeps apart (plan task INS2)
------------------------------------------------------------------
Every run first passes a health gate on the pipeline only (``health_check``).
A refused plan or draft is an outcome and stays in the pool; a transport
failure, a missing section record, nothing offered, or a planner that dropped
10% or more of its references excludes the run, by name. A measurement with no
arm (``legacy``) is listed and pooled nowhere. Over the rest it writes blocks
per corpus x arm (n, mean, sd, range, and pooled k/n for a rate), an oracle
block, paired deltas per corpus with ranges, the judge per criterion and per
presentation order, and three crossing measurements that are never summed: (a)
generator surfaces in what the core sent, (b) the run's own entities anywhere in
the trace, (c) what the G3 adversary recovered. No p-values, bootstrap or Wilson
intervals: the runs of a corpus share one corpus and one extraction.

Measured on the nine pilot runs (smoke-q3, baseline/r5/r1 x 3): 9/9 valid; RBA
baseline 0.315, r5 0.178, r1 0.771; position bias 0.685 without the legacy run;
(a) 0 hits, the one surface token in any request ('High' in "at a high level")
being a plan objective the cloud wrote, quoted back; (b) one hit, 'High' in
smoke-q3__baseline__rep3, cloud-authored; (c) 'High' (baseline rep2) and
'August' (r5 rep1).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "backend" / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from privdeep.audit.manifest import RunManifest  # noqa: E402
from privdeep.eval.faithfulness import de_escape, load_key, score  # noqa: E402
from privdeep.eval.judge import judge_pair  # noqa: E402
from privdeep.eval.oracle import run_oracle  # noqa: E402
from privdeep.eval.reconstruction import (  # noqa: E402
    TRACE_MAX_CHARS,
    _contains_run,
    reconstruct,
)
from privdeep.ingest import SUFFIXES, load  # noqa: E402
from privdeep.models.document import Document  # noqa: E402
from privdeep.tier1_local.slot_masker import Entity  # noqa: E402
from privdeep.tier2_cloud.cloud_client import CloudClient  # noqa: E402

from shared.shingle_filter import tokenize  # noqa: E402

__all__ = ["Provenance", "Task", "aggregate", "archive_attempt", "collect_runtime",
           "estimate_cost", "estimate_private_cost", "health_check", "host_provenance",
           "load_tasks", "measure_task", "recreate_services", "scan_trace",
           "surface_groups_for", "token_hits", "tree_sha256", "wilson_interval"]

# Sonnet 5 first-party rates, $ per token. Cache reads bill at a fraction of the
# input rate and writes at a premium; both are counted separately because the
# oracle arm's whole cost profile is a cache-hit question.
USD_IN, USD_OUT = 2.00 / 1e6, 10.00 / 1e6
USD_CACHE_READ, USD_CACHE_WRITE = 0.20 / 1e6, 2.50 / 1e6

DEFAULT_ARTIFACT = _REPO / "eval" / "evaluation.json"
DEFAULT_RUNS = _REPO / "eval" / "runs"

# BASELINE is the pre-R5 behaviour, reached by a flag rather than by checking
# out an old commit: an arm that has to be recovered from a different tree is an
# arm nobody re-runs, and comparing two differently-built binaries measures the
# build rather than the change.
ARMS = ("r5", "baseline", "r1")

# What one phase-one run costs. Measured on the archived smoke-q3 manifest:
# 16,810 input and 6,002 output tokens over eight section drafts ($0.094), and
# the planner call's tokens are not in the manifest at all, so that is a lower
# bound. Rounded up, because this figure exists to be shown before money is
# spent. Unlike the oracle it does not scale with corpus size: the payload the
# cloud sees is abstracted, which is the point of the system.
PRIVATE_ARM_IN, PRIVATE_ARM_OUT = 24_000, 9_000
FACT_KEY_NAME = "smoke_fact_key.json"
# A run whose RBA rests on fewer fully resolved occurrences than this has its
# RBA left out of the arm mean (INS1): at n=2 one sentence moves it by 0.5.
MIN_RBA_POOL = 5


def run_dir_for(runs_dir: Path, task_id: str, arm: str, rep: int = 1) -> Path:
    """One directory per (task, arm).

    `runs_dir / task_id` alone would make a task's second arm reuse the first
    arm's phase-one output, because `run_private_arm` skips when the directory
    already exists. The comparison would then report a difference of zero
    between an arm and itself, from an artifact that was never produced. It also
    leaves `eval/runs/smoke-q3/` alone, which is the frozen report the
    faithfulness metric is calibrated against.
    """
    if rep < 1:
        raise ValueError("repeats are numbered from 1")
    # Repeat 1 keeps the original name, so runs made before repeats existed are
    # the first repeat. `rep` rather than `r2` so a repeat cannot be read as the
    # r1 or r5 arm.
    return runs_dir / (f"{task_id}__{arm}" if rep == 1 else f"{task_id}__{arm}__rep{rep}")


def _faithfulness(task: Task, run_dir: Path, private_report: str,
                  oracle_report: str) -> dict[str, Any]:
    """Role-Binding Accuracy for both arms, against the authored gold key.

    Local, deterministic and free, so it runs on every measurement rather than
    on request. The per-occurrence detail quotes report sentences, which for the
    private arm means private values, so it is written beside the run and never
    returned into `measurement.json`.

    A missing key records *why* it is missing. Returning nothing would leave an
    artifact carrying no faithfulness numbers and no statement that none were
    computed, which reads exactly like a run where the metric found nothing.
    """
    key_path = task.corpus / FACT_KEY_NAME
    if not key_path.exists():
        return {"skipped": f"no gold fact key at {key_path}; regenerate the corpus "
                           "with scripts/make_smoke_corpus.py (scenario A) or "
                           "'python scripts/corpora --scenario all'"}
    key = load_key(key_path)
    # Which key scored this: a measurement scored against a different key is not
    # comparable, and the key has already changed once.
    out: dict[str, Any] = {"key_sha256": hashlib.sha256(key_path.read_bytes()).hexdigest()}
    detail: dict[str, Any] = {}
    for name, text in (("private", private_report), ("oracle", oracle_report)):
        res = score(text, key)
        out[name] = res.to_json()
        detail[name] = res.detail_json()
    (run_dir / "faithfulness_occurrences.json").write_text(
        json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    corpus: Path
    goal: str


def _repo_path(p: str) -> Path:
    """A task's corpus path. Relative means relative to the repository root:
    resolving against the caller's working directory made one tasks file point
    at different corpora depending on where the driver was started."""
    q = Path(p).expanduser()
    return (q if q.is_absolute() else _REPO / q).resolve()


def load_tasks(path: Path) -> list[Task]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    tasks = [Task(str(t["id"]), _repo_path(t["corpus"]), str(t["goal"])) for t in raw]
    ids = [t.id for t in tasks]
    if len(set(ids)) != len(ids):
        raise SystemExit("task ids must be unique; they name the artifact directories")
    for t in tasks:
        if not t.corpus.is_dir():
            raise SystemExit(f"task {t.id}: corpus {t.corpus} is not a directory")
        if not any(p.suffix.lower() in SUFFIXES for p in t.corpus.iterdir()):
            raise SystemExit(f"task {t.id}: no supported documents in {t.corpus}")
    return tasks


def wilson_interval(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """Wilson score interval for a proportion. Sane at 0/N and N/N, unlike Wald."""
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (0.0 if k == 0 else max(0.0, centre - half),
            1.0 if k == n else min(1.0, centre + half))


def spread(values: list[float]) -> dict[str, Any]:
    """Mean with the raw values kept.

    At N in the tens a confidence interval on a mean invites more weight than
    it can carry, so the per-task values travel with it and the paper can show
    them. `stdev` is None for N<2 rather than 0.0, which would read as
    agreement where there is only one observation.
    """
    if not values:
        return {"n": 0, "mean": None, "stdev": None, "min": None, "max": None, "values": []}
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else None,
        "min": min(values), "max": max(values),
        "values": values,
    }


# --------------------------------------------------------------------- phase one


def _docker() -> str:
    """Resolved once, the way `audit/manifest.py` resolves git: a full path, so
    the executable cannot be picked up from a caller's PATH."""
    exe = shutil.which("docker")
    if not exe:
        raise SystemExit("docker is not on PATH; phase one runs the private arm in a container")
    return exe


def _run(argv: list[str], *, env: dict[str, str] | None = None
         ) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - argv list, no shell; executable via shutil.which
        argv, cwd=_REPO, env=env, capture_output=True, text=True, check=False)


def _compose(*args: str, env: dict[str, str] | None = None
             ) -> subprocess.CompletedProcess[str]:
    return _run([_docker(), "compose", *args], env=env)


CORE, MONITOR, SLM = "privdeep-core", "reference-monitor", "local-slm"

# What `privdeep-core` bind-mounts and so executes: the commit cannot say what
# ran if these were edited after it, and they were, mid-measurement (F14).
TREE_DIRS = ("backend/src", "shared", "gateway")
# Byte-code and tool caches are derived from the sources, differ between
# machines, and would make two identical trees hash apart.
_TREE_SKIP_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})


def tree_sha256(root: Path = _REPO) -> str:
    """sha256 over the code the container runs, as it is on disk.

    Sorted relative paths, each followed by its content's sha256, so a rename
    changes the digest as well as an edit. Contents on disk rather than the
    git index, because the bind mount serves the disk: an uncommitted edit is
    exactly what this must see. A missing directory is hashed as missing
    rather than skipped, so it cannot hash equal to an empty one.
    """
    h = hashlib.sha256()
    for d in TREE_DIRS:
        base = root / d
        if not base.is_dir():
            h.update(f"missing:{d}\n".encode())
            continue
        rels = sorted(q.relative_to(root).as_posix() for q in base.rglob("*")
                      if q.is_file() and q.suffix != ".pyc"
                      and not _TREE_SKIP_DIRS.intersection(q.relative_to(root).parts))
        for rel in rels:
            h.update(rel.encode("utf-8") + b"\0")
            h.update(hashlib.sha256((root / rel).read_bytes()).digest())
    return h.hexdigest()


@dataclass(frozen=True, slots=True)
class Provenance:
    """Which code a billable phase is about to run, computed on the host.

    `tree_dirty` is None when git could not say (no git, not a repository):
    unknown, which the refusal treats like dirty, because an unchecked tree
    cannot be shown to be the committed one.
    """
    git_commit: str
    tree_sha256: str
    tree_dirty: bool | None
    dirty_paths: tuple[str, ...] = ()

    def env_args(self) -> list[str]:
        """`docker compose exec -e` arguments; RunManifest reads these names."""
        dirty = "unknown" if self.tree_dirty is None else str(self.tree_dirty).lower()
        return ["-e", f"PRIVDEEP_GIT_COMMIT={self.git_commit}",
                "-e", f"PRIVDEEP_TREE_SHA={self.tree_sha256}",
                "-e", f"PRIVDEEP_TREE_DIRTY={dirty}"]

    def to_json(self) -> dict[str, Any]:
        # Not the paths: they are for the refusal message, and a file name can
        # itself be something a manifest should not carry.
        return {"git_commit": self.git_commit, "tree_sha256": self.tree_sha256,
                "tree_dirty": self.tree_dirty}


# Set by git for hooks, and absolute in a worktree: inherited, they would make
# `git -C root` read another checkout's index instead of root's.
_GIT_REPO_ENV = ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")


def _git_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _GIT_REPO_ENV}


def host_provenance(root: Path = _REPO) -> Provenance:
    """Commit, dirty flag and tree digest of `root`.

    Dirty means a tracked file anywhere differs from HEAD, or an untracked,
    non-ignored file sits under the mounted code. Untracked files elsewhere do
    not count: eval/ fills with outputs during a batch, and a flag that trips
    on the batch's own artifacts would be switched off rather than read. An
    untracked module under backend/src, on the other hand, is imported by the
    run and is not in the commit.
    """
    sha = tree_sha256(root)
    git = shutil.which("git")
    if not git:
        return Provenance("unknown", sha, None)
    env = _git_env()
    head = _run([git, "-C", str(root), "rev-parse", "HEAD"], env=env)
    tracked = _run([git, "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
                   env=env)
    code = _run([git, "-C", str(root), "status", "--porcelain", "--untracked-files=all",
                 "--", *TREE_DIRS], env=env)
    if head.returncode != 0 or tracked.returncode != 0 or code.returncode != 0:
        return Provenance("unknown", sha, None)
    paths = [ln[3:] for ln in tracked.stdout.splitlines() if ln.strip()]
    paths += [ln[3:] for ln in code.stdout.splitlines() if ln.startswith("??")]
    return Provenance(head.stdout.strip() or "unknown", sha, bool(paths), tuple(paths))


def _refuse_unclean(prov: Provenance, allow_dirty: bool) -> int:
    """0 to go ahead, 1 to refuse. Printed either way, so the batch log has it."""
    state = {True: "DIRTY", False: "clean", None: "UNKNOWN"}[prov.tree_dirty]
    print(f"code: commit {prov.git_commit[:12]}  tree {prov.tree_sha256[:12]}  {state}")
    if prov.tree_dirty is False or allow_dirty:
        return 0
    if prov.tree_dirty is None:
        print("refusing to spend: git could not say whether the tree is clean, so no "
              "commit describes the code that would run (--allow-dirty to override)")
        return 1
    shown = ", ".join(prov.dirty_paths[:10]) + (" ..." if len(prov.dirty_paths) > 10 else "")
    print(f"refusing to spend on a dirty tree ({shown}); commit first, or pass "
          "--allow-dirty and the manifest records tree_dirty=true")
    return 1


def _changed_since(batch: Provenance, now: Provenance) -> str | None:
    """Why `now` no longer describes the code `batch` recorded, or None.

    Every task is a fresh `python -m privdeep.pipeline` that imports whatever
    the bind mount holds when it starts, while the provenance a batch passes in
    is computed once. An edit or a commit mid-batch would leave every later
    manifest naming code that did not run (F14). All three recorded values are
    compared, the dirty flag included, so each is true of every run it is
    written into. Recording the new values instead would not help: the monitor
    was started, or recreated, from the code at the start of the batch.
    """
    fields = [f for f, a, b in (("git_commit", batch.git_commit, now.git_commit),
                                ("tree_sha256", batch.tree_sha256, now.tree_sha256),
                                ("tree_dirty", batch.tree_dirty, now.tree_dirty))
              if a != b]
    if not fields:
        return None
    return (f"the code changed during the batch ({', '.join(fields)}: commit "
            f"{batch.git_commit[:12]} tree {batch.tree_sha256[:12]} dirty {batch.tree_dirty}"
            f" -> commit {now.git_commit[:12]} tree {now.tree_sha256[:12]} dirty "
            f"{now.tree_dirty}); stopping rather than record code that did not run. "
            "Re-run the remaining tasks, with --recreate so the monitor runs the new code too")


def attempts_dir_for(runs_dir: Path) -> Path:
    """eval/attempts/ beside eval/runs/, or beside whatever --runs points at."""
    return runs_dir.parent / "attempts"


def _next_attempt(root: Path, name: str) -> Path:
    pat = re.compile(re.escape(name) + r"__attempt(\d+)")
    ks = [int(m.group(1)) for q in (root.iterdir() if root.is_dir() else ())
          if (m := pat.fullmatch(q.name))]
    return root / f"{name}__attempt{max(ks, default=0) + 1}"


def archive_attempt(run_dir: Path, runs_dir: Path, *, copy: bool = False) -> Path:
    """Keep an earlier attempt at a run under eval/attempts/<run>__attempt<k>/.

    Replaces the `shutil.rmtree` that `--force` used to do, which was the only
    deletion in the driver and deleted the refused or failed attempt's egress
    trace with it: re-running a refused run until it passed would leave no
    trace of the refusal, so the operational-refusal count was zero by
    construction. `k` counts up from the attempts already archived under that
    name; nothing is overwritten and nothing is deleted.

    Phase one moves the directory, since it is about to be produced again.
    Phase two copies it, because the phase-one output inside is what it is
    about to measure again. Both share one namespace, so attempt.json says
    which phase archived it: a phase-two copy carries a duplicate of an egress
    trace that is still in eval/runs, and a refusal count summed over
    eval/attempts must skip it or count those refusals twice.
    """
    root = attempts_dir_for(runs_dir)
    root.mkdir(parents=True, exist_ok=True)
    dest = _next_attempt(root, run_dir.name)
    if dest.exists():   # pragma: no cover - _next_attempt picks an unused k
        raise SystemExit(f"{dest} already exists; refusing to overwrite an attempt")
    if copy:
        shutil.copytree(run_dir, dest)
    else:
        shutil.move(str(run_dir), str(dest))
    _write_attempt_record(dest, {"phase": "measure" if copy else "private",
                                 "reason": "replaced under --force",
                                 "egress_trace_is_copy": copy})
    print(f"  earlier attempt kept at {dest}")
    return dest


def _write_attempt_record(dest: Path, record: dict[str, Any]) -> None:
    """attempt.json, merged into one an earlier archiving already wrote."""
    path = dest / "attempt.json"
    prior = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    path.write_text(json.dumps({**prior, **record}, ensure_ascii=False, indent=2),
                    encoding="utf-8")


# Moves a stale run directory on the volume aside, inside the container. The
# whole directory is copied out after the run, so a file an earlier attempt
# left there would otherwise be copied out as this attempt's.
_SET_ASIDE = """\
import os, sys
src = sys.argv[1].rstrip("/")
if os.path.exists(src):
    root = "/data/attempts"
    os.makedirs(root, exist_ok=True)
    k = 1
    while os.path.exists(f"{root}/{os.path.basename(src)}__attempt{k}"):
        k += 1
    os.rename(src, f"{root}/{os.path.basename(src)}__attempt{k}")
"""

# Run in privdeep-core, which reaches local-slm on the internal network; the
# SLM publishes no port on the host. /api/tags carries the model digest (the
# /api/show reply has none), /api/show the quantisation, and /api/ps is what
# `ollama ps` prints: size against size_vram is the GPU placement.
_OLLAMA_PROBE = """\
import json, os, httpx
base = os.environ.get("LOCAL_SLM_URL", "http://local-slm:11434/v1").rstrip("/")
base = base[:-3] if base.endswith("/v1") else base
model = os.environ.get("LOCAL_SLM_MODEL", "qwen3:14b")
out = {"name": model}
with httpx.Client(timeout=10) as c:
    tags = c.get(base + "/api/tags").json().get("models", [])
    out["digest"] = next((m.get("digest") for m in tags
                          if model in (m.get("name"), m.get("model"))), None)
    show = c.post(base + "/api/show", json={"model": model}).json()
    out["details"] = show.get("details", {})
    out["modified_at"] = show.get("modified_at")
    out["loaded"] = [{"name": m.get("name"), "size": m.get("size"),
                      "size_vram": m.get("size_vram"), "expires_at": m.get("expires_at")}
                     for m in c.get(base + "/api/ps").json().get("models", [])]
print(json.dumps(out))
"""


def _placement(model: dict[str, Any]) -> dict[str, Any]:
    """`ollama ps`'s PROCESSOR column, from the numbers it is computed from."""
    name = model.get("name")
    row = next((m for m in model.get("loaded", []) if m.get("name") == name), None)
    if row is None or not row.get("size"):
        # A --reuse-extraction run never calls the model (in every arm, r1
        # included: the pipeline's only SLM caller is the extractor), so this
        # is expected there, and says nothing about where it would have run.
        return {"loaded": False}
    frac = (row.get("size_vram") or 0) / row["size"]
    proc = ("100% GPU" if frac >= 1 else "100% CPU" if frac <= 0
            else f"{round((1 - frac) * 100)}%/{round(frac * 100)}% CPU/GPU")
    # expires_at is load time plus OLLAMA_KEEP_ALIVE (10 minutes), so it tells
    # a reader whether the placement is this run's or a model an earlier run
    # left loaded, which after a reuse run it can be.
    return {"loaded": True, "size": row["size"], "size_vram": row.get("size_vram"),
            "gpu_fraction": frac, "processor": proc, "expires_at": row.get("expires_at")}


def _container_field(service: str, fmt: str) -> str:
    """One `docker inspect` field of a compose service's container."""
    cid = _compose("ps", "-q", service).stdout.strip()
    if not cid:
        raise RuntimeError(f"no running container for {service}")
    r = _run([_docker(), "inspect", "--format", fmt, cid.splitlines()[0]])
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"docker inspect {service}: {r.stderr.strip() or 'no output'}")
    return r.stdout.strip()


def _probe(fn: Any) -> Any:
    """Recorded, never refused on: a probe that fails says why, and the run stands."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - a broken probe must not end a paid run
        return {"unavailable": f"{type(exc).__name__}: {exc}"}


def collect_runtime(*, recreated: bool) -> dict[str, Any]:
    """What the host sees around a run and the container cannot.

    Collected after the pipeline exits, because GPU placement is only
    meaningful once the model has been loaded: before the run it may be
    unloaded (OLLAMA_KEEP_ALIVE is 10 minutes). The monitor's StartedAt is
    later than the run's own start if the monitor restarted mid-run. None of
    it gates the run; F13's "an SLM silently on CPU is accepted" is answered
    by recording the placement, and the decision is the reader's.
    """
    def image() -> dict[str, Any]:
        img = _container_field(SLM, "{{.Image}}")
        r = _run([_docker(), "image", "inspect", "--format", "{{json .RepoDigests}}", img])
        return {"id": img,
                "repo_digests": json.loads(r.stdout) if r.returncode == 0 else None}

    def model() -> dict[str, Any]:
        r = _compose("exec", "-T", CORE, "python", "-c", _OLLAMA_PROBE)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or f"exit {r.returncode}")
        m = json.loads(r.stdout.strip().splitlines()[-1])
        return {"name": m.get("name"), "digest": m.get("digest"),
                "details": m.get("details"), "modified_at": m.get("modified_at"),
                "placement": _placement(m)}

    return {
        "collected_at": time.time(),
        "recreated_this_batch": recreated,
        "monitor_started_at": _probe(lambda: _container_field(MONITOR, "{{.State.StartedAt}}")),
        "core_started_at": _probe(lambda: _container_field(CORE, "{{.State.StartedAt}}")),
        "ollama_image": _probe(image),
        "local_model": _probe(model),
    }


def recreate_services(corpus: Path) -> None:
    """Restart the monitor and the core once, before a batch.

    Both run bind-mounted code, and a long-running monitor keeps executing
    whatever it imported when it started: a commit that lands mid-batch is on
    disk and in the tree digest but not in the process enforcing egress. The
    core is recreated with the first task's corpus mounted, since `up` with a
    different PRIVDEEP_CORPUS_DIR recreates it again anyway.
    """
    env = {**os.environ, "PRIVDEEP_CORPUS_DIR": str(corpus)}
    print(f"recreating {MONITOR} and {CORE}")
    r = _compose("up", "-d", "--force-recreate", MONITOR, CORE, env=env)
    if r.returncode != 0:
        raise SystemExit(f"could not recreate {MONITOR} and {CORE}:\n{r.stderr}")


def _merge_runtime(manifest_path: Path, runtime: dict[str, Any]) -> None:
    d = json.loads(manifest_path.read_text(encoding="utf-8"))
    d["runtime"] = runtime
    # The same guard the pipeline applies: the manifest is the publishable file.
    RunManifest._assert_publishable(d)
    manifest_path.write_text(json.dumps(d, ensure_ascii=False, indent=2, sort_keys=True),
                             encoding="utf-8")


def run_private_arm(task: Task, runs_dir: Path, *, force: bool,
                    arm: str = "r5", reuse_from: str | None = None, rep: int = 1,
                    provenance: Provenance | None = None, recreated: bool = False) -> Path:
    """Phase one: the private arm, inside the partition, then copied out.

    Runs `python -m privdeep.pipeline` in `privdeep-core` with the task's corpus
    bind-mounted at /corpus. The run directory lands on the `privdeep-data` named
    volume, which the host cannot read, so it is copied out with
    `docker compose cp`.

    **This is not free.** The docstring said "free apart from local GPU time"
    until the archived manifest was checked: nine egress attempts, all allowed,
    against claude-sonnet-5. Only the local extraction is free; the planner and
    every section draft are billable Tier-2 calls made through the monitor. The
    gateway sits in the path, not in place of the API.

    A run whose pipeline exits non-zero is still an attempt: whatever it wrote
    is copied to eval/attempts/ with its exit code before this raises, so a
    run that ends with every section refused leaves its trace behind.

    `provenance` is what the batch checked at its start. The code is hashed
    again before the run and after it; if either differs, the task is not
    started, or its run is kept only as an attempt, and this raises, which
    stops the batch.
    """
    out = run_dir_for(runs_dir, task.id, arm, rep)
    if out.exists() and not force:
        print(f"  [{task.id}] private arm already on disk, skipping")
        return out
    # A batch passes in the provenance it checked when it started. The code is
    # hashed again before this task and after it, because this task's pipeline
    # imports whatever the bind mount holds when it starts, not what it held
    # when the batch did (F14).
    now = host_provenance()
    prov = provenance or now
    if (why := _changed_since(prov, now)) is not None:
        raise SystemExit(f"[{task.id}] not started: {why}")

    reuse_argv: list[str] = []
    src: Path | None = None
    if reuse_from is not None:
        # Repeats reuse repeat 1's extraction, including an arm's own: that is
        # what holds Tier 1 fixed so the spread measures the cloud alone. Only
        # repeat 1 reusing itself is meaningless.
        if reuse_from == arm and rep == 1:
            raise SystemExit(f"an arm cannot reuse its own extraction ({arm})")
        src = run_dir_for(runs_dir, task.id, reuse_from) / "extractions.json"
        if not src.exists():
            raise SystemExit(
                f"no extraction to reuse at {src}; run phase one for arm "
                f"{reuse_from!r} first. Without it the two arms mask different "
                "entity sets and the comparison is not about the arm.")

    container_run = f"/data/runs/{out.name}"
    env = {**os.environ, "PRIVDEEP_CORPUS_DIR": str(task.corpus)}
    print(f"  [{task.id}] private arm ({arm}, repeat {rep}): corpus={task.corpus}")
    up = _compose("up", "-d", CORE, env=env)
    if up.returncode != 0:
        raise SystemExit(f"could not start privdeep-core:\n{up.stderr}")
    aside = _compose("exec", "-T", CORE, "python", "-c", _SET_ASIDE, container_run, env=env)
    if aside.returncode != 0:
        raise SystemExit(f"could not set aside {container_run} on the volume:\n{aside.stderr}")

    if src is not None:
        # The host copy is the one that is kept; the volume's copy is not. It
        # used to be read from the volume, where it survives only as long as
        # the named volume does and cannot be checked from the host (F15).
        # Copied to the source run's own path, so extraction_source keeps
        # naming the arm whose extraction it is.
        container_src = f"/data/runs/{src.parent.name}"
        mk = _compose("exec", "-T", CORE, "mkdir", "-p", container_src, env=env)
        cp_in = _compose("cp", str(src), f"{CORE}:{container_src}/extractions.json", env=env)
        if mk.returncode != 0 or cp_in.returncode != 0:
            raise SystemExit(f"could not copy {src} into the container:\n"
                             f"{mk.stderr}{cp_in.stderr}")
        reuse_argv = ["--reuse-extraction", f"{container_src}/extractions.json"]

    proc = _compose("exec", "-T", *prov.env_args(), CORE,
                    "python", "-m", "privdeep.pipeline", "/corpus", task.goal, container_run,
                    "--arm", arm, *reuse_argv, env=env)
    print("   ", (proc.stdout or proc.stderr).strip().splitlines()[-1] if
          (proc.stdout or proc.stderr).strip() else "(no output)")
    runtime = collect_runtime(recreated=recreated)
    after = host_provenance()
    changed = _changed_since(prov, after)

    if proc.returncode != 0 or changed is not None:
        # Either way an attempt, not a result: a failed run is an outcome, and
        # a run during which the code changed may have imported code its
        # manifest does not name. An earlier result for the task stays put.
        root = attempts_dir_for(runs_dir)
        root.mkdir(parents=True, exist_ok=True)
        dest = _next_attempt(root, out.name)
        if _compose("cp", f"{CORE}:{container_run}", str(dest), env=env).returncode != 0:
            dest.mkdir(parents=True, exist_ok=True)      # the pipeline wrote nothing
        record: dict[str, Any] = {
            "phase": "private", "exit_code": proc.returncode, "egress_trace_is_copy": False,
            "reason": ("pipeline exited non-zero" if changed is None
                       else "code changed during the run"),
            "provenance": prov.to_json(), "runtime": runtime}
        if changed is not None:
            record["provenance_after"] = after.to_json()
        _write_attempt_record(dest, record)
        # Beside the attempt, not in attempt.json: a traceback can quote a value.
        (dest / "attempt_output.txt").write_text(
            f"{proc.stdout}\n--- stderr ---\n{proc.stderr}", encoding="utf-8")
        if changed is not None:
            raise SystemExit(f"[{task.id}] kept only as an attempt, at {dest}: {changed}")
        raise SystemExit(f"private arm failed for {task.id} (exit {proc.returncode}); the "
                         f"attempt is kept at {dest}:\n{proc.stdout}\n{proc.stderr}")

    # Archived only now, just before its replacement is copied out: a batch
    # that stops earlier leaves the earlier result in eval/runs rather than
    # no run at all for `aggregate` to find.
    if out.exists():
        archive_attempt(out, runs_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    cp = _compose("cp", f"{CORE}:{container_run}", str(out), env=env)
    if cp.returncode != 0:
        raise SystemExit(f"could not copy the run out of the container:\n{cp.stderr}")
    if (out / "manifest.json").exists():
        _merge_runtime(out / "manifest.json", runtime)
    else:
        print(f"  [{task.id}] WARNING no manifest.json in {out}; runtime facts not recorded")
    return out


# --------------------------------------------------------------------- phase two


def _load_run(run_dir: Path) -> tuple[str, list[dict], list[Entity]]:
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    trace = [json.loads(ln) for ln in
             (run_dir / "egress_trace.jsonl").read_text(encoding="utf-8").splitlines() if ln]
    ents_path = run_dir / "entities.json"
    if not ents_path.exists():
        raise SystemExit(
            f"{run_dir} has no entities.json. The adversary must be scored against the "
            "entity set the run actually masked; re-extracting them now would run a "
            "probabilistic model a second time and score against entities this run never "
            "issued a slot for. Re-run phase one.")
    ents = [Entity(e["text"], e["category"]) for e in json.loads(ents_path.read_text("utf-8"))]
    return report, trace, ents


# CommonMark backslash escapes: a backslash before any ASCII punctuation.
def _for_judge(markdown: str) -> str:
    """The text a reader sees, for both arms alike.

    The judge reads raw Markdown. The private arm's report passes through the
    reintegrator, which backslash-escapes private values so they cannot
    restructure the page; the oracle's report never does. On the first live run
    that left 42 escapes in one arm and none in the other, in front of a judge
    scoring coherence and specificity. Removing them from both, symmetrically,
    means a presentation artefact cannot move a utility score, whatever the
    reintegrator's escaping policy is later changed to.
    """
    return de_escape(markdown)


def _cost(usage: dict[str, int]) -> float:
    return (usage.get("input_tokens", 0) * USD_IN
            + usage.get("output_tokens", 0) * USD_OUT
            + usage.get("cache_read_tokens", 0) * USD_CACHE_READ
            + usage.get("cache_write_tokens", 0) * USD_CACHE_WRITE)


async def measure_task(task: Task, run_dir: Path, cloud: CloudClient, *,
                       judge_repeats: int, max_doc_chars: int,
                       arm: str = "r5", rep: int = 1,
                       provenance: Provenance | None = None) -> dict[str, Any]:
    """Phase two for one task: oracle, judge, adversary. This is what costs money.

    `provenance` is the host code that ran the oracle, judge and adversary. It
    can differ from the commit in the run's manifest, which is the code that
    produced the report being measured, so both are kept.
    """
    docs: list[Document] = [load(p) for p in sorted(task.corpus.iterdir())
                            if p.suffix.lower() in SUFFIXES]
    private_report, trace, entities = _load_run(run_dir)

    oracle = await run_oracle(docs, task.goal, cloud, max_doc_chars=max_doc_chars)
    (run_dir / "oracle.json").write_text(oracle.record_json(), encoding="utf-8")
    (run_dir / "oracle_report.md").write_text(oracle.report_markdown, encoding="utf-8")

    judgements = []
    rationales = []
    priv_j, orac_j = _for_judge(private_report), _for_judge(oracle.report_markdown)
    for i in range(judge_repeats):
        j = await judge_pair(task.goal, priv_j, orac_j, cloud)
        rationales.append({"repeat": i, "rationales": j.rationales})
        judgements.append({
            "repeat": i,
            "private": j.a_scores, "oracle": j.b_scores,
            "private_mean": j.a_mean, "oracle_mean": j.b_mean,
            "position_bias": j.position_bias,
            "private_by_order": j.a_by_order, "oracle_by_order": j.b_by_order,
            "criteria": list(j.criteria), "judge_models": j.judge_models,
            "input_tokens": j.input_tokens, "output_tokens": j.output_tokens,
        })
    (run_dir / "judge.json").write_text(
        json.dumps(judgements, ensure_ascii=False, indent=2), encoding="utf-8")
    # Why the judge scored as it did. Paid for on every call and previously
    # discarded. Run-directory only: a rationale may quote the private report.
    (run_dir / "judge_rationales.json").write_text(
        json.dumps(rationales, ensure_ascii=False, indent=2), encoding="utf-8")

    rec = await reconstruct(docs, entities, trace, cloud)
    (run_dir / "reconstruction.json").write_text(rec.to_json(), encoding="utf-8")
    # The adversary's actual reconstruction, which the counts cannot show: what
    # it inferred about roles and relations is the G2 question. Run-directory
    # only, never aggregated — it is an attempt to recover private text.
    (run_dir / "adversary_output.txt").write_text(
        getattr(rec, "adversary_output", ""), encoding="utf-8")

    usage = {
        "oracle": {"input_tokens": oracle.input_tokens, "output_tokens": oracle.output_tokens,
                   "cache_read_tokens": oracle.cache_read_tokens,
                   "cache_write_tokens": oracle.cache_write_tokens},
        "judge": {"input_tokens": sum(j["input_tokens"] for j in judgements),
                  "output_tokens": sum(j["output_tokens"] for j in judgements)},
        # Billed like the other two and, before INS4, left out of the spend.
        "adversary": {"input_tokens": rec.adversary_tokens_in,
                      "output_tokens": rec.adversary_tokens_out},
    }
    manifest_path = run_dir / "manifest.json"
    extraction_source = (json.loads(manifest_path.read_text(encoding="utf-8"))
                         .get("extraction_source", "unrecorded")
                         if manifest_path.exists() else "unrecorded")
    result = {
        "task_id": task.id,
        "arm": arm,
        "rep": rep,
        "extraction_source": extraction_source,
        "provenance": provenance.to_json() if provenance else None,
        "goal": task.goal,
        "faithfulness": _faithfulness(task, run_dir, private_report,
                                      oracle.report_markdown),
        "corpus_chars": sum(len(d.text) for d in docs),
        "corpus_documents": len(docs),
        "oracle_truncated_chars": oracle.truncated_chars,
        "oracle_max_doc_chars": oracle.max_doc_chars,
        "judgements": judgements,
        "reconstruction": json.loads(rec.to_json()),
        "usage": usage,
        "usd": {k: _cost(v) for k, v in usage.items()},
    }
    (run_dir / "measurement.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def estimate_private_cost(tasks: list[Task]) -> dict[str, float]:
    """What phase *one* will cost, which was long assumed to be nothing.

    The private arm runs inside the partition, so it reads as local and
    therefore free — the docstring on `run_private_arm` said exactly that. It is
    not: the planner and every section draft are billable Tier-2 calls, which
    the monitor forwards rather than replaces. Phase one had no estimate and no
    `--yes` gate while phase two had both, so the cheaper-looking half of the
    driver was the unguarded one.
    """
    per = PRIVATE_ARM_IN * USD_IN + PRIVATE_ARM_OUT * USD_OUT
    est = {t.id: per for t in tasks}
    est["TOTAL"] = per * len(tasks)
    return est


def estimate_cost(tasks: list[Task], *, judge_repeats: int, max_doc_chars: int) -> dict[str, float]:
    """What phase two will cost, itemised, before a cent is spent.

    Phase one is deliberately not in this total: it is spent by a different
    subcommand, and folding it in would misreport whichever one the caller is
    about to run. `estimate_private_cost` covers that half.

    Deliberately an over-estimate: it assumes every cap is reached and no cache
    hit lands. The oracle line is the one that moves, because that arm resends
    the corpus on all nine of its calls.
    """
    per_char_tok = 1 / 3.5
    est: dict[str, float] = {}
    total = 0.0
    for t in tasks:
        chars = min(sum(p.stat().st_size for p in t.corpus.iterdir()
                        if p.suffix.lower() in SUFFIXES), max_doc_chars)
        docs_tok = chars * per_char_tok
        oracle_in = docs_tok * 1.25 + 8 * (docs_tok * 0.1)      # write once, read eight times
        oracle = oracle_in * USD_IN + 9_600 * USD_OUT
        judge = judge_repeats * (2 * (2 * 40_000 * per_char_tok) * USD_IN + 2_000 * USD_OUT)
        adv = TRACE_MAX_CHARS * per_char_tok * USD_IN + 2_000 * USD_OUT
        est[t.id] = oracle + judge + adv
        total += est[t.id]
    est["TOTAL"] = total
    return est


# --------------------------------------------------------------------- aggregate


def _git_commit() -> str:
    git = shutil.which("git")
    if not git:
        return "unknown"
    return _run([git, "rev-parse", "HEAD"]).stdout.strip() or "unknown"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ------------------------------------------------------------ the health gate

# The planner note every manifest carries. Before INS3 gave the counters their
# own fields it was the only record of them, so the nine pilot runs are read
# from it; a run that has the fields is read from the fields.
_PLAN_NOTE = re.compile(r"plan: (?P<sections>\d+) sections, (?P<dropped>\d+) unknown slot refs "
                        r"dropped")
_PLAN_REFUSED = "planning refused by monitor"
# A transport failure is not a refusal: nothing decided against the request,
# it simply did not arrive (see observation_table.py). It is the one section
# outcome that says the pipeline, not the policy, failed.
_TRANSPORT_FAILURE = re.compile(r"^draft: (CloudError|GatewayError)\b")
MAX_DROPPED_SHARE = 0.10
HEALTH_RULE = (
    "A run is valid when (1) it completed: manifest.json and report.md exist; (2) the "
    "slots offered over its sections total more than zero (slots issued, when the "
    "planning call itself was refused); (3) every planned section has a drafter reply or "
    "a recorded refusal reason, a CloudError or GatewayError being a transport failure "
    "and not a reason; (4) planner_refs_dropped / planner_refs_returned is under 10%, read "
    "from the manifest note where the fields predate the run, where an unrecorded "
    "'returned' passes only with nothing dropped. Monitor and reintegrator refusals, "
    "relations the W2 leak gate dropped and the faithfulness pool size are outcomes: "
    "reported, never gated on. A run that fails is left out of every pooled block and "
    "named under 'excluded'.")


def _refusal_rule(reason: str) -> str:
    """'draft: SHINGLE_HIT: 3 shingles ...' -> 'draft: SHINGLE_HIT'. The stage and
    the rule name only: what follows can be counts today and anything tomorrow."""
    stage, _, rest = reason.partition(":")
    return f"{stage.strip()}: {rest.split(':', 1)[0].strip() or 'UNSPECIFIED'}"


def health_check(run_dir: Path) -> dict[str, Any]:
    """Whether one run's pipeline worked, which is not whether its policy let it.

    The gate is on pipeline health only (plan task INS2, with the Part D
    correction): a monitor refusal of the planning call or of a draft is what
    the system is for, and gating on it would re-run refusals away until the
    refusal count read zero. `outcomes` reports them beside the verdict, and
    with them the W2 leak gate's drops from the manifest's extraction counters
    (`relations_dropped_leak`, and `documents_all_relations_dropped`, the
    documents the gate left with no relation). Those are None in a manifest
    written before the gate dropped instead of aborting (2026-09-27).
    """
    failures: list[str] = []
    manifest = _read_json(run_dir / "manifest.json")
    if manifest is None:
        failures.append("did not complete: no manifest.json")
    if not (run_dir / "report.md").exists():
        failures.append("did not complete: no report.md")
    if manifest is None:
        return {"valid": False, "failures": failures, "outcomes": {}}

    notes = [str(n) for n in manifest.get("notes") or []]
    plan_refused = next((n for n in notes if n.startswith(_PLAN_REFUSED)), None)
    plan_note = next((m for n in notes if (m := _PLAN_NOTE.search(n))), None)
    sections = manifest.get("sections") or []

    # (2) Something was offered. A refused plan has no sections, so what the
    # payload put in front of the planner stands in for them.
    offered = sum(int(s.get("slots_offered") or 0) for s in sections)
    if plan_refused is not None:
        offered = int(manifest.get("slots_issued") or 0)
    if offered <= 0:
        failures.append("no slots offered: the payload carried nothing to write about")

    # (3) Every planned section answered, one way or the other.
    planned = int(plan_note.group("sections")) if plan_note else None
    refused: list[str] = []
    if plan_refused is None:
        if planned is None:
            failures.append("no plan record: the manifest names neither a plan nor its refusal")
        elif len(sections) < planned:
            failures.append(f"{planned - len(sections)} of {planned} planned sections have "
                            "no record")
        for s in sections:
            why = str(s.get("refused") or "")
            if not why:
                continue
            if _TRANSPORT_FAILURE.match(why):
                failures.append(f"section {s.get('section_id')}: transport failure "
                                f"({_TRANSPORT_FAILURE.match(why).group(1)}), not a refusal")
            else:
                refused.append(_refusal_rule(why))

    # (4) The planner mostly referred to slots that exist.
    returned = manifest.get("planner_refs_returned")
    dropped = manifest.get("planner_refs_dropped")
    source = "manifest fields"
    if dropped is None and plan_note is not None:
        dropped, source = int(plan_note.group("dropped")), "manifest note (pre-INS3)"
    share: float | None = None
    if plan_refused is None:
        if dropped is None:
            failures.append("planner counters not recorded, in fields or note")
        elif returned is None:
            if dropped:
                failures.append(f"planner dropped {dropped} unknown slot refs and the number "
                                "returned is not recorded, so the share cannot be shown under "
                                "10%")
        else:
            share = dropped / returned if returned else (0.0 if not dropped else math.inf)
            if share >= MAX_DROPPED_SHARE:
                failures.append(f"planner dropped {dropped} of {returned} slot refs "
                                f"({share:.0%}), at or over {MAX_DROPPED_SHARE:.0%}")

    return {
        "valid": not failures,
        "failures": failures,
        "outcomes": {
            "plan_refused": (_refusal_rule("plan: " + plan_refused[len(_PLAN_REFUSED):]
                                           .lstrip(": ")) if plan_refused else None),
            "planned_sections": planned,
            "sections_recorded": len(sections),
            "refused_sections": refused,
            "slots_offered": offered,
            "planner_refs_returned": returned,
            "planner_refs_dropped": dropped,
            "planner_counters_from": source,
            "dropped_share": share,
            "relations_dropped_leak": (manifest.get("extraction") or {}).get(
                "relations_dropped_leak"),
            "documents_all_relations_dropped": (manifest.get("extraction") or {}).get(
                "documents_all_relations_dropped"),
            # Where the counters above came from ("extracted", or the reused
            # file), and the commit phase one ran at: the paper build reads
            # the drops once per extraction and binds the freeze commit.
            "extraction_source": manifest.get("extraction_source"),
            "git_commit": manifest.get("git_commit"),
        },
    }


# ------------------------------------------------- the three crossing scans

SURFACES_NAME = "surfaces.json"
# The scenario files' own caveat (surfaces.json 'note'): these are ordinary
# English words, reported apart so a hit on "high" in the cloud's prose is not
# read as the corpus's severity label crossing.
LABEL_GROUPS = ("labels",)
# A reply fragment shorter than this is not treated as quotable: a one-word
# section title would otherwise mark every later occurrence of that word in a
# core-built prompt as cloud-authored.
ECHO_MIN_TOKENS = 2


def _as_text(v: Any) -> str:
    if v is None:
        return ""
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def _sent_fields(e: dict[str, Any]) -> dict[str, str]:
    """What the core put in the request (observation_table.py's definition)."""
    msgs = e.get("messages") or []
    return {"system": _as_text(e.get("system")),
            "messages": "\n".join(_as_text(m.get("content") if isinstance(m, dict) else m)
                                  for m in msgs),
            "tools": _as_text(e.get("tools"))}


def _received_fields(e: dict[str, Any]) -> dict[str, str]:
    return {"response_text": _as_text(e.get("response_text")),
            "structured": _as_text(e.get("structured"))}


def _string_leaves(obj: Any) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _string_leaves(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _string_leaves(v)]
    return []


def _cloud_segments(e: dict[str, Any]) -> list[str]:
    """The verbatim pieces of one reply that a later prompt can quote.

    Both received fields, not only `response_text`: the planner answers with a
    tool call, so its section titles and objectives are in `structured`, and
    every drafter prompt after it quotes them. Checked on the pilot, where the
    only generator-surface token in any request ('high', in 'at a high level')
    is a plan objective the cloud wrote, quoted back in the next prompt.
    """
    pieces = [_as_text(e.get("response_text")), *_string_leaves(e.get("structured"))]
    return [ln.strip() for p in pieces for ln in p.splitlines()
            if len(tokenize(ln)) >= ECHO_MIN_TOKENS]


def _cut(text: str, spans: list[str]) -> tuple[str, list[str]]:
    """`text` with every occurrence of each span replaced by a line break, longest
    first, and the pieces cut out. Verbatim, since an echo is a copy, but never
    starting or ending inside a word: a goal of 'g' must not cut the 'g' out of
    'High'."""
    cut: list[str] = []
    for s in sorted(set(spans), key=len, reverse=True):
        if not s or s not in text:
            continue
        rx = re.compile((r"(?<!\w)" if s[0].isalnum() or s[0] == "_" else "") + re.escape(s)
                        + (r"(?!\w)" if s[-1].isalnum() or s[-1] == "_" else ""))
        text, k = rx.subn("\n", text)
        cut += [s] * k
    return text, cut


def token_hits(text: str, needles: list[str]) -> dict[str, int]:
    """Whole-token, case-insensitive occurrences of each needle in `text`.

    Tokens are the containment tokenizer's (NFKC, casefolded, punctuation as a
    separator), the ones the reconstruction scorer matches on, so '340' does
    not hit inside '1340' and 'High' does not hit inside 'Highway'. Longest
    needle first, and a matched run is consumed: 'Zephyr' inside a hit on
    'Project Zephyr' is not counted a second time.
    """
    toks: list[str | None] = list(tokenize(text))
    hits: dict[str, int] = {}
    for needle in sorted(set(needles), key=lambda s: (-len(tokenize(s)), -len(s), s)):
        nt = tokenize(needle)
        n = len(nt)
        if not n:
            continue
        i = 0
        while i <= len(toks) - n:
            if toks[i] == nt[0] and toks[i:i + n] == nt:
                hits[needle] = hits.get(needle, 0) + 1
                toks[i:i + n] = [None] * n
                i += n
            else:
                i += 1
    return hits


def scan_trace(trace: list[dict[str, Any]], needles: list[str], *,
               goal: str = "") -> list[dict[str, Any]]:
    """Every whole-token occurrence of `needles` in one run's egress trace, with
    where it was and who wrote it.

    `side` is one of:
    * ``core-sent``: request content the core built (system, messages, tools)
      that crossed;
    * ``user-goal``: inside the research goal, which crosses verbatim by design;
    * ``cloud-echo``: request content that repeats, verbatim, a piece of an
      earlier reply in the same run (`_cloud_segments`), so the cloud wrote it;
    * ``cloud-reply``: a reply field (response_text, structured);
    * ``not-sent``: request content of an exchange the monitor refused: not
      sent, and not shown to the adversary either, whose rendering uses the
      same test (``reconstruction._refused``) and puts a marker line in its
      place (THREAT_MODEL §5; P8 for a delivered request traced as refused).
      Goal and echo spans of a refused request keep the sides above though
      they were not sent then: an echo crossed in the reply it repeats, and
      the goal in the planning request unless that request was the refused one.
    """
    out: list[dict[str, Any]] = []
    earlier: list[str] = []
    for i, e in enumerate(trace):
        stage = e.get("stage")
        for field, text in _sent_fields(e).items():
            rest, in_goal = _cut(text, [goal] if goal.strip() else [])
            rest, echo = _cut(rest, earlier)
            parts = (("not-sent" if e.get("refused") else "core-sent", rest),
                     ("user-goal", "\n".join(in_goal)), ("cloud-echo", "\n".join(echo)))
            for side, t in parts:
                for needle, k in token_hits(t, needles).items():
                    out.append({"exchange": i, "stage": stage, "field": field, "side": side,
                                "needle": needle, "count": k})
        for field, text in _received_fields(e).items():
            for needle, k in token_hits(text, needles).items():
                out.append({"exchange": i, "stage": stage, "field": field,
                            "side": "cloud-reply", "needle": needle, "count": k})
        earlier += _cloud_segments(e)
    return out


def surface_groups_for(task: Task) -> tuple[dict[str, list[str]] | None, str | None]:
    """A task's generator surfaces, and where they came from.

    The corpus directory's surfaces.json when there is one. Otherwise the
    scenario module whose ID is the task's id: the pilot's tasks file named the
    user mount corpus/, which holds the same documents as eval/corpora/smoke-q3
    (pinned by test_corpus_scenarios) and no surfaces list.
    """
    p = task.corpus / SURFACES_NAME
    if p.exists():
        return (json.loads(p.read_text(encoding="utf-8"))["groups"],
                p.relative_to(_REPO).as_posix() if p.is_relative_to(_REPO) else str(p))
    scripts = str(_REPO / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        from corpora import SCENARIOS
    except ImportError:     # pragma: no cover - the writers' dependencies are absent
        return None, None
    for name, mod in SCENARIOS.items():
        if mod.ID == task.id:
            return mod.surface_groups(), f"scripts/corpora/{name}.py surface_groups()"
    return None, None


def _run_entities(run_dir: Path) -> tuple[list[tuple[str, str]] | None, str | None]:
    """The distinct (text, category) pairs a run masked, and the file they came from:
    entities.json, which the pipeline writes as the masked set, else the per-document
    entities in extractions.json."""
    ents = _read_json(run_dir / "entities.json")
    if ents is not None:
        return list(dict.fromkeys((e["text"], e["category"]) for e in ents)), "entities.json"
    ex = _read_json(run_dir / "extractions.json")
    if ex is not None:
        return list(dict.fromkeys((e["text"], e["category"]) for d in ex.get("documents", [])
                                  for e in d.get("entities", []))), "extractions.json"
    return None, None


def _read_trace(run_dir: Path) -> list[dict[str, Any]] | None:
    p = run_dir / "egress_trace.jsonl"
    if not p.exists():
        return None
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _table_data_cells(corpus: Path) -> int:
    """Non-empty table cells below the header row and outside the key column,
    over every sheet and docx table: the facts a table holds, whatever its
    headers say. The grid rule is fact_store.build_fact_store's, so this is the
    denominator facts_structural is read against; no manifest records it."""
    total = 0
    for p in sorted(corpus.iterdir()):
        if p.suffix.lower() not in SUFFIXES:
            continue
        sheets: dict[str, dict[tuple[int, int], str]] = {}
        for c in load(p).cells:
            sheets.setdefault(c.sheet, {})[(c.row, c.col)] = c.value
        for grid in sheets.values():
            head, key = min(r for r, _ in grid), min(c for _, c in grid)
            total += sum(1 for (r, c), v in grid.items() if r != head and c != key and v.strip())
    return total


def _key_counts(task: Task) -> tuple[str | None, int | None, int | None]:
    """The task key's sha256, gold-fact count and stated-fact count: the
    denominators of coverage and coverage_stated, which `denominators` omits."""
    p = task.corpus / FACT_KEY_NAME
    if not p.exists():
        return None, None, None
    facts = json.loads(p.read_text(encoding="utf-8"))["facts"]
    return (hashlib.sha256(p.read_bytes()).hexdigest(), len(facts),
            sum(1 for f in facts if not f.get("derived")))


# ------------------------------------------------------------- the artifact

# Faithfulness rates, and the entry of `denominators` each is a share of.
# "gold" and "stated" are counts of the task key's facts, not in `denominators`.
_FAITH_KEYS = ("rba", "attribute_accuracy", "referent_accuracy", "coverage",
               "coverage_correct", "coverage_stated", "numerals_outside_key", "faithfulness_f1")
_DENOMINATOR = {"rba": "full", "attribute_accuracy": "attribute", "referent_accuracy": "referent",
                "numerals_outside_key": "scanned", "coverage": "gold",
                "coverage_correct": "gold", "coverage_stated": "stated"}
# numerals_outside_key is a private-arm figure (INS1); the oracle is free to
# compute a figure the key does not hold, so on it the rate means nothing.
_ORACLE_KEYS = tuple(k for k in _FAITH_KEYS if k != "numerals_outside_key")
# Counts per run, read from the manifest.
_PIPELINE_KEYS = ("sentences_pruned", "not_recorded", "facts_structural", "refused_sections",
                  "relations_dropped_leak")
_DELTA_PAIRS = (("baseline", "r1"), ("r5", "r1"), ("baseline", "r5"))
# The tracer (backend tracing.py) appends an exchange on success or on
# EgressRefused only. A request the monitor forwarded whose upstream call then
# failed (CloudError, GatewayError: a 529, say) may have crossed and is not in
# egress_trace.jsonl, so no scan here can see it. Such a run fails the health
# gate and is not pooled, but "every trace scanned" does not cover it.
_TRACE_GAP = ("egress_trace.jsonl holds exchanges that succeeded or that the monitor refused; "
              "a forwarded request whose upstream call then failed (CloudError, GatewayError) "
              "is not traced, so a crossing in it cannot be seen by (a) or (b).")
_DELTA_KEYS = ("rba", "attribute_accuracy", "referent_accuracy", "coverage", "coverage_correct",
               "coverage_stated", "judge_private_mean")
GROUNDEDNESS = "groundedness"


def _pipeline_values(manifest: dict[str, Any] | None) -> dict[str, int | None]:
    """sentences_pruned, the 'not recorded' fills, facts_structural, refused
    sections and the relations the W2 leak gate dropped (from the manifest's
    extraction counters) for one run, None where the manifest does not record it.

    A manifest whose sections predate a section field (the pilot's baseline
    and r5 smoke-q3 runs carry neither sentences_pruned nor facts_unavailable)
    gives None for it, not 0, so the run is left out of that key's n instead
    of counting as a measured zero.

    'not recorded' is the sum of the sections' facts_unavailable, the count of
    fills the reintegrator wrote; on the pilot it equals the '[not recorded]'
    count in each r1 report. The report text is not counted instead, because
    the fill is now plain words the cloud's own prose can also contain.
    """
    if manifest is None:
        return dict.fromkeys(_PIPELINE_KEYS)
    secs = manifest.get("sections") or []
    fills = [s["facts_unavailable"] for s in secs if "facts_unavailable" in s]
    pruned = [int(s["sentences_pruned"] or 0) for s in secs if "sentences_pruned" in s]
    return {
        "sentences_pruned": sum(pruned) if pruned or not secs else None,
        "not_recorded": sum(fills) if fills or not secs else None,
        "facts_structural": (manifest.get("facts") or {}).get("facts_structural"),
        "refused_sections": sum(1 for s in secs if s.get("refused")),
        # Before 2026-09-27 the gate aborted the run instead, so an older
        # manifest has no such counter and gives None, not a measured zero.
        "relations_dropped_leak": (manifest.get("extraction") or {}).get(
            "relations_dropped_leak"),
    }


def _judge_block(rows: list[dict[str, Any]], evidence_empty: bool | None) -> dict[str, Any]:
    """Judge scores per criterion and per presentation order, with position bias.

    Every repeat of every run is one value. `private_first` is the ordering in
    which the private report was shown as A. The mean without groundedness is
    there because groundedness asks whether claims cite evidence, and with an
    empty evidence bank no report can cite any: the criterion then scores the
    judge's impression and nothing the system did.
    """
    js = [j for m in rows for j in m.get("judgements", [])]
    crits = next((list(j["criteria"]) for j in js if j.get("criteria")), [])
    informative = [c for c in crits if c != GROUNDEDNESS]

    def order(side: str, i: int) -> dict[str, Any]:
        return {c: spread([j[f"{side}_by_order"][i][c] for j in js
                           if len(j.get(f"{side}_by_order") or []) > i
                           and c in j[f"{side}_by_order"][i]]) for c in crits}

    def without_groundedness(side: str) -> dict[str, Any]:
        return spread([statistics.fmean(j[side][c] for c in informative) for j in js
                       if informative and all(c in j.get(side, {}) for c in informative)])

    return {
        "judgements": len(js),
        "private_mean": spread([j["private_mean"] for j in js]),
        "oracle_mean": spread([j["oracle_mean"] for j in js]),
        "by_criterion": {c: {"private": spread([j["private"][c] for j in js if c in j["private"]]),
                             "oracle": spread([j["oracle"][c] for j in js if c in j["oracle"]])}
                         for c in crits},
        "by_order": {"private_first": {"private": order("private", 0),
                                       "oracle": order("oracle", 0)},
                     "oracle_first": {"private": order("private", 1),
                                      "oracle": order("oracle", 1)}},
        "position_bias": spread([j["position_bias"] for j in js]),
        "mean_excluding_groundedness": {"private": without_groundedness("private"),
                                        "oracle": without_groundedness("oracle")},
        "groundedness_uninformative": evidence_empty,
        "groundedness_note": (
            "The evidence bank is empty in every run here (manifest 'evidence' is []), so no "
            "claim in either report can cite evidence and groundedness scores only the "
            "judge's impression. Quote mean_excluding_groundedness." if evidence_empty else
            "Evidence was recorded in at least one run, or no manifest was found; "
            "groundedness is not flagged."),
    }


def _thin_rba(f: dict[str, Any]) -> bool:
    """A run's RBA rests on fewer than MIN_RBA_POOL scored occurrences (INS1)."""
    full = (f.get("denominators") or {}).get("full")
    return full is not None and full < MIN_RBA_POOL


# ------------------------------------------------------------ the hypotheses

# Which registered corpus each task id is (scope §8.7: A = eval/corpora/smoke-q3,
# B = portfolio-b, C = prose-c, D = offlex-d). Read by task id from the tasks
# file and never inferred: a task id not listed here, or one whose corpus
# directory is not named after it (eval/corpora/<id>), is named in the block as
# unmapped and takes part in no per-corpus hypothesis. H3 is not per corpus: it
# covers every private-arm run of the tasks file, mapped or not.
CORPUS_OF_TASK = {"smoke-q3": "A", "portfolio-b": "B", "prose-c": "C", "offlex-d": "D"}
# "three repeats each" (§8.7). A cell with fewer pooled runs is named, not refused:
# the every-run form is easier to satisfy over fewer runs, so the reader is told,
# in the block and on every comparison line that reads such a cell.
REGISTERED_REPEATS = 3
HOLDS, FAILS, NOT_TESTABLE = "holds", "fails", "not testable"

# Each hypothesis and its claim restriction, verbatim from PRIVDEEP_ICCIT_SCOPE.md
# (wrapped lines joined by one space). test_run_evaluation pins every string
# against the scope text, so an edit to either side fails the suite.
HYPOTHESES: dict[str, dict[str, str]] = {
    "H1": {
        "label": "H1", "section": "8.7",
        "wording": ("on each of A and B, every r1 run's RBA and attribute accuracy exceed "
                    "every baseline run's. A is a replication at the tag, because the pilot "
                    "already shows the outcome; B is out-of-sample."),
        "if_fails": ("If H1 fails on a corpus, the R1 sentence names only the corpora where "
                     "it holds."),
        # The scope's definition bullet for H1, carried with it: the block reads
        # whatever key each run was scored against and cannot see the lexicon.
        "definition": ("H1 is tested under the frozen RBA attribute lexicon (§8.8, after its "
                       "one-time fix). The pre-fix figure is reported beside it and is not "
                       "tested, and corpus A is marked in-sample for the fix."),
    },
    "H2": {
        "label": "H2", "section": "8.7",
        "wording": ("on C, r1's coverage_stated and coverage_correct are below baseline's, "
                    "because R1 has no prose route. RBA on C is reported with its n and "
                    "suppressed below the minimum n."),
        "if_fails": ("If H2 fails, meaning r1 states prose-only values, that is reported and "
                     "traced, and the prose sentence is withdrawn."),
        # Added after the C and D pilot, before the batch (§8.7a).
        "floor_rule": ("A half of H2 in which the largest r1 value and the smallest baseline "
                       "value on C are both 0 cannot show r1 below baseline, because no value "
                       "is below 0. Such a half is reported as not testable (a floor), not as "
                       "a failure, and H2 is decided by its other half; if both halves are at "
                       "the floor, H2 is not testable. The restriction \"If H2 fails, meaning "
                       "r1 states prose-only values\" applies only to a failure of a half that "
                       "is not at the floor."),
    },
    "H3": {
        "label": "H3", "section": "8.7",
        "wording": ("the generator-surface scan finds zero hits in core-sent content of any "
                    "private-arm trace."),
        "if_fails": ("If H3 fails, the crossing strings are reported and the first bullet of "
                     "the claim (§8.10) is withdrawn."),
    },
    "H4-D": {
        "label": "H4-D", "section": "8.7",
        "wording": ("on D, facts_structural against total table facts falls below A and B, "
                    "and r1's RBA gain over baseline shrinks accordingly."),
        "if_fails": ("If H4-D fails, the paper reports that the gain on D did not shrink with "
                     "lexicon coverage and does not attribute R1's gain to the lexicon on the "
                     "evidence of D."),
    },
    "H4-D'": {
        "label": "H4-D′", "section": "8.7a",
        "wording": ("on D, every r1 run's coverage_correct is below every r1 run's "
                    "coverage_correct on A and on B."),
        "if_fails": ("If H4-D′ fails, the paper reports that r1's coverage did not fall with "
                     "lexicon coverage on D and does not attribute R1's coverage limits to the "
                     "header lexicon on the evidence of D."),
    },
}

# How each outcome is computed. Every comparison is in the every-run form H1 and
# H4-D′ are worded in, and strict: a tie is not "below". Where the scope wording
# does not say "every" (H2, H4-D) the every-run form is the reading applied, the
# stricter of the two, so a "holds" never rests on a difference of means.
HYPOTHESIS_RULES = {
    "H1": ("Per corpus (A, B): the smallest r1 value is above the largest baseline value, "
           "for RBA and for attribute_accuracy, over the pooled runs."),
    "H2": ("On C: the largest r1 value is below the smallest baseline value, for "
           "coverage_stated and for coverage_correct, over the pooled runs. A half whose "
           "largest r1 and smallest baseline values are both 0 is a floor: not testable, "
           "and H2 is the other half (§8.7a). RBA on C is listed per arm with its "
           "suppressed runs and not tested."),
    "H3": ("Crossing (a): no core-sent hit in any trace of any private-arm run of the tasks "
           "file, runs the health gate excluded included. Label-group hits and hits in the "
           "tools field count; only the user goal and cloud echoes are excluded, as the scan "
           "defines. It holds only when every such run's trace was scanned and is complete, "
           "and every corpus A-D has a run of every arm: a run whose trace is missing, empty "
           "(no exchange traced) or incomplete (a transport failure, see trace_gap), a "
           "phase-one run with no measurement, and a missing corpus or arm each make it not "
           "testable."),
    "H4-D": ("facts_structural / table data cells for every r1 run on D is below that of "
             "every r1 run on A and on B; and every r1-minus-baseline RBA pair difference on D "
             "is below every such difference on A and on B."),
    "H4-D'": ("The largest r1 coverage_correct on D is below the smallest r1 "
              "coverage_correct on A, and below the smallest on B."),
}

_OUTCOME_NOTE = (
    "Computed from the pooled runs, never judged. 'fails' needs only one violating pair of "
    "values, whatever else is missing; otherwise a run with no value (null or NaN, RBA under "
    "the minimum n or with its pool size unrecorded, a stale key, a field the measurement "
    "predates) or a corpus with no pooled "
    "run makes the outcome 'not testable', with the reason. A conjunction fails if any part "
    "fails, else is not testable if any part is, else holds.")


def _conjoin(outcomes: list[str]) -> str:
    return FAILS if FAILS in outcomes else NOT_TESTABLE if NOT_TESTABLE in outcomes else HOLDS


def _run_value(m: dict[str, Any], k: str, corpus_sha: str | None
               ) -> tuple[float | None, str | None]:
    """One pooled run's private-arm rate `k`, or None and why it has none.

    A run scored against a key other than its corpus's current key has no value
    here: H1 is tested under the frozen key (§8.7), and a stale score would decide
    it against a key that is no longer the instrument."""
    f = m.get("faithfulness")
    priv = f.get("private") if isinstance(f, dict) else None
    if not isinstance(priv, dict):
        return None, "not scored"
    if corpus_sha is None:
        return None, "the corpus has no gold key"
    if f.get("key_sha256") != corpus_sha:
        return None, (f"scored against key {str(f.get('key_sha256'))[:8]}, not the corpus "
                      f"key {corpus_sha[:8]}; rescore")
    if k not in priv:
        return None, f"no {k} in the measurement (scored before the field existed)"
    v = priv[k]
    if v is None:
        return None, f"{k} is null (empty pool)"
    if _is_nan(v):
        return None, f"{k} is NaN"
    if k == "rba":
        # _thin_rba passes an unrecorded pool size; a hypothesis must not, since
        # the minimum-n check (§8.7) cannot be shown to hold for it.
        full = (priv.get("denominators") or {}).get("full")
        if full is None:
            return None, "RBA pool size not recorded (denominators.full)"
        if full < MIN_RBA_POOL:
            return None, f"RBA suppressed: {full} scored occurrences, under {MIN_RBA_POOL}"
    return float(v), None


def _is_nan(v: Any) -> bool:
    return isinstance(v, float) and math.isnan(v)


def _every_below(test: str, lower: dict[str, Any], upper: dict[str, Any]) -> dict[str, Any]:
    """Every value on `lower` is strictly below every value on `upper`."""
    lo, hi = list(lower["values"].values()), list(upper["values"].values())
    absent = [f"{s['label']}: {s['absent']}" for s in (lower, upper) if s.get("absent")]
    missing = []
    for s in (lower, upper):
        by_why: dict[str, list[str]] = {}
        for r, why in s["missing"].items():
            by_why.setdefault(why, []).append(r)
        missing += [f"{s['label']}, no value for {', '.join(rs)}: {why}"
                    for why, rs in by_why.items()]
    if lo and hi and max(lo) >= min(hi):
        outcome, reason = FAILS, None
    elif absent or missing:
        outcome, reason = NOT_TESTABLE, "; ".join(absent + missing)
    else:
        outcome, reason = HOLDS, None
    # A side pooled over fewer runs than registered is named on the comparison
    # itself, not only in the block's header: "every run" over fewer runs is an
    # easier test, and a gate exclusion should not make it so unnoticed.
    short = [f"{s['label']}: {s['runs']} pooled run(s)" for s in (lower, upper)
             if s.get("runs") and s["runs"] < REGISTERED_REPEATS]
    return {"test": test, "outcome": outcome, "reason": reason,
            "short_of_registered_repeats": short,
            "lower": {**lower, "max": max(lo) if lo else None},
            "upper": {**upper, "min": min(hi) if hi else None}}


def _hypotheses(tasks: list[Task], measured: list[dict[str, Any]],
                armed: list[dict[str, Any]], excluded: dict[str, list[str]],
                pipeline: dict[str, dict[str, int | None]],
                cells: dict[str, int | None],
                key_info: dict[str, tuple[str | None, int | None, int | None]],
                crossing_a: dict[str, Any], unmeasured: list[str] | None = None,
                attempts: list[str] | None = None) -> dict[str, Any]:
    """H1, H2, H3, H4-D and H4-D′ (scope §8.7, §8.7a), each decided mechanically
    from the per-run values the aggregate already holds."""
    # A registered id whose corpus directory is not eval/corpora/<id> is not
    # taken to be that corpus: the id alone would be a guess.
    path_mismatch = {t.id: str(t.corpus) for t in tasks
                     if t.id in CORPUS_OF_TASK and Path(t.corpus).name != t.id}
    task_of = {CORPUS_OF_TASK[t.id]: t.id for t in tasks
               if t.id in CORPUS_OF_TASK and t.id not in path_mismatch}
    unmapped = [t.id for t in tasks if t.id not in task_of.values()]
    pooled_n: dict[str, int] = {}

    def rows_of(letter: str, arm: str, *, tested: bool = True
                ) -> tuple[list[dict[str, Any]], str | None]:
        tid = task_of.get(letter)
        if tid is None:
            return [], f"no task in the tasks file is corpus {letter}"
        rows = [m for m in measured if m["task_id"] == tid and m["arm"] == arm]
        if tested:
            pooled_n[f"{arm} on {letter}"] = len(rows)
        if rows:
            return rows, None
        gated = sorted(m["run"] for m in armed
                       if m["task_id"] == tid and m["arm"] == arm and m["run"] in excluded)
        return [], (f"no pooled {arm} run on {letter} ({tid})"
                    + (f"; excluded by the health gate: {gated}" if gated else ""))

    def rate_side(letter: str, arm: str, k: str, *, tested: bool = True) -> dict[str, Any]:
        rows, absent = rows_of(letter, arm, tested=tested)
        sha = key_info.get(task_of.get(letter, ""), (None, None, None))[0]
        values: dict[str, float] = {}
        missing: dict[str, str] = {}
        for m in rows:
            v, why = _run_value(m, k, sha)
            if v is None:
                missing[m["run"]] = str(why)
            else:
                values[m["run"]] = v
        return {"label": f"{arm} {k} on {letter}", "values": values, "missing": missing,
                "absent": absent, "runs": len(rows)}

    def structural_side(letter: str) -> dict[str, Any]:
        rows, absent = rows_of(letter, "r1")
        n = cells.get(task_of.get(letter, ""))
        if absent is None and not n:
            absent = f"no table data cells counted on {letter}"
        values: dict[str, float] = {}
        missing: dict[str, str] = {}
        for m in rows if n else []:
            fs = pipeline[m["run"]]["facts_structural"]
            if fs is None:
                missing[m["run"]] = "facts_structural not in the manifest"
            else:
                values[m["run"]] = fs / n
        return {"label": f"r1 facts_structural / table data cells on {letter}",
                "table_data_cells": n, "values": values, "missing": missing,
                "absent": absent, "runs": len(rows)}

    def gain_side(letter: str) -> dict[str, Any]:
        r1, base = rate_side(letter, "r1", "rba"), rate_side(letter, "baseline", "rba")
        absent = "; ".join(dict.fromkeys(s["absent"] for s in (r1, base)
                                         if s["absent"])) or None
        return {"label": f"r1 - baseline RBA, every run pair on {letter}",
                "values": {f"{a} - {b}": va - vb for a, va in r1["values"].items()
                           for b, vb in base["values"].items()},
                "missing": {**r1["missing"], **base["missing"]}, "absent": absent,
                "runs": min(r1["runs"], base["runs"])}

    # H1, per corpus.
    h1: dict[str, Any] = {}
    for letter in ("A", "B"):
        comps = {k: _every_below(f"every r1 run's {k} above every baseline run's on {letter}",
                                 rate_side(letter, "baseline", k), rate_side(letter, "r1", k))
                 for k in ("rba", "attribute_accuracy")}
        h1[letter] = {"task": task_of.get(letter),
                      "outcome": _conjoin([c["outcome"] for c in comps.values()]),
                      "components": comps}

    # H2, on C.
    h2 = {k: _every_below(f"every r1 run's {k} below every baseline run's on C",
                          rate_side("C", "r1", k), rate_side("C", "baseline", k))
          for k in ("coverage_stated", "coverage_correct")}
    # The floor rule (§8.7a, added after the pilot): with baseline's smallest
    # value at 0 no r1 value can be strictly below it, so a tie at zero is a
    # floor, not the failure the §8.7 restriction reads as "r1 states prose-only
    # values". Only a tie at zero is a floor: an r1 value above 0 against a
    # baseline at 0 is a real failure of that half.
    for c in h2.values():
        c["floor"] = (c["upper"]["min"] == 0)
        if c["floor"] and c["lower"]["max"] == 0 and c["outcome"] == FAILS:
            c["outcome"] = NOT_TESTABLE
            c["reason"] = "floor: the largest r1 and the smallest baseline value are both 0"
            c["floor_rule_applied"] = True
    h2_decided = [c["outcome"] for c in h2.values() if not c.get("floor_rule_applied")]
    rba_c = {}
    for arm in ARMS:
        s = rate_side("C", arm, "rba", tested=False)
        rba_c[arm] = {"values": s["values"], "no_value": s["missing"], "absent": s["absent"]}

    # H3, from crossing (a), over every private-arm run of the tasks file: the
    # scope says "any private-arm trace", which is not a per-corpus reading.
    h3_runs = {m["run"] for m in armed if m["arm"] in ARMS}
    hits = [h for h in crossing_a["hits"] + crossing_a["label_hits"] if h["run"] in h3_runs]
    unscanned = {r: why for r, why in crossing_a["runs_not_scanned"].items() if r in h3_runs}
    for r in crossing_a["runs_scanned"]:
        if r not in h3_runs:
            continue
        failed = [f for f in excluded.get(r, []) if "transport failure" in f]
        if failed:
            # The gate's own exclusion says a call was forwarded and failed
            # upstream: that request is not in the trace (_TRACE_GAP), so a
            # clean scan of the rest is not a scan of the run.
            unscanned[r] = ("trace incomplete, a forwarded request failed upstream and is "
                            "not traced (trace_gap): " + "; ".join(failed))
        elif crossing_a["exchanges_traced"].get(r) == 0:
            unscanned[r] = "no exchange traced: egress_trace.jsonl is empty"
    # A phase-one run with no measurement sent what it sent, but crossing (a)
    # reads only measured runs, so its trace is not scanned.
    for r in unmeasured or []:
        unscanned[r] = "no measurement.json, so crossing (a) did not read its trace"
    scanned = [r for r in crossing_a["runs_scanned"] if r in h3_runs and r not in unscanned]
    # Zero hits over a set that is missing a corpus or an arm is not the
    # registered test, which covers A-D under every arm.
    uncovered = [f"no task in the tasks file is corpus {x}" for x in "ABCD" if x not in task_of]
    uncovered += [f"no {arm} run on {x} ({tid})" for x, tid in sorted(task_of.items())
                  for arm in ARMS
                  if not any(m["task_id"] == tid and m["arm"] == arm for m in armed)]
    if hits:
        h3_outcome, h3_reason = FAILS, None
    elif uncovered or unscanned or not scanned:
        h3_outcome = NOT_TESTABLE
        h3_reason = "; ".join(
            uncovered
            + ([f"not scanned: {r}: {why}" for r, why in sorted(unscanned.items())])
            + ([] if scanned else ["no private-arm trace was scanned"]))
    else:
        h3_outcome, h3_reason = HOLDS, None
    by_field: dict[str, int] = {}
    for h in hits:
        by_field[h["field"]] = by_field.get(h["field"], 0) + h["count"]

    # H4-D and H4-D′, on D against A and B.
    h4d = {}
    for ref in ("A", "B"):
        h4d[f"structural_share_vs_{ref}"] = _every_below(
            f"every r1 run's facts_structural share on D below every r1 run's on {ref}",
            structural_side("D"), structural_side(ref))
        h4d[f"rba_gain_vs_{ref}"] = _every_below(
            f"every r1-minus-baseline RBA pair difference on D below every one on {ref}",
            gain_side("D"), gain_side(ref))
    h4dp = {f"vs_{ref}": _every_below(
                f"every r1 run's coverage_correct on D below every r1 run's on {ref}",
                rate_side("D", "r1", "coverage_correct"),
                rate_side(ref, "r1", "coverage_correct"))
            for ref in ("A", "B")}

    def entry(name: str, **body: Any) -> dict[str, Any]:
        return {**HYPOTHESES[name], "rule": HYPOTHESIS_RULES[name], **body}

    return {
        "source": "PRIVDEEP_ICCIT_SCOPE.md §8.7 and §8.7a",
        "note": _OUTCOME_NOTE,
        "corpora": {letter: task_of.get(letter) for letter in "ABCD"},
        "unmapped_tasks": unmapped,
        "corpus_path_mismatch": path_mismatch,
        "registered_repeats": REGISTERED_REPEATS,
        "short_of_registered_repeats": {cell: n for cell, n in sorted(pooled_n.items())
                                        if n < REGISTERED_REPEATS},
        "H1": entry("H1", per_corpus=h1,
                    holds_on=[x for x in ("A", "B") if h1[x]["outcome"] == HOLDS]),
        "H2": entry("H2", outcome=_conjoin(h2_decided) if h2_decided else NOT_TESTABLE,
                    components=h2, rba_on_C_reported_not_tested=rba_c),
        "H3": entry("H3", outcome=h3_outcome, reason=h3_reason,
                    hits=sum(h["count"] for h in hits),
                    label_group_hits=sum(h["count"] for h in hits if h["label_group"]),
                    hits_by_field=by_field,
                    crossing_strings=sorted({h["surface"] for h in hits}),
                    runs_scanned=len(scanned), runs_not_scanned=unscanned,
                    cells_uncovered=uncovered, trace_gap=_TRACE_GAP,
                    # Earlier attempts --force archived: their requests were
                    # sent and no block scans them. Listed, not decided: whether
                    # H3 covers them is the author's call (and, if not, the
                    # paper's to say).
                    attempts_not_scanned=sorted(attempts or [])),
        "H4-D": entry("H4-D", outcome=_conjoin([c["outcome"] for c in h4d.values()]),
                      components=h4d),
        "H4-D'": entry("H4-D'", outcome=_conjoin([c["outcome"] for c in h4dp.values()]),
                       components=h4dp),
    }


def aggregate(tasks: list[Task], runs_dir: Path, *,
              alt_key: Path | None = None) -> dict[str, Any]:
    """Turn per-run artifacts into the paper's tables. Offline and free.

    One function, as the plan asks, so every table comes from one pass over one
    set of runs: the health gate first, then per-corpus x arm blocks over the
    runs that pass it, the oracle, paired deltas per corpus, the judge, and the
    three crossing measurements, each its own block and never summed.

    What is deliberately absent: p-values, bootstrap intervals, and Wilson
    intervals over pooled occurrences. The runs share one extraction and one
    corpus, so occurrences within them are not independent draws, and an
    interval computed as though they were would claim a precision the design
    does not have. Ranges and k/n are what is reported.
    """
    # Discovered, not composed: reading `runs_dir / t.id` would miss every
    # per-arm directory, and a driver that silently finds nothing reports an
    # empty aggregate as though the runs had produced no numbers.
    by_id = {t.id: t for t in tasks}
    found: list[tuple[Path, dict[str, Any]]] = []
    for p in sorted(runs_dir.glob("*/measurement.json")):
        m = json.loads(p.read_text(encoding="utf-8"))
        if m.get("task_id") in by_id:
            # "legacy", never "r5": a measurement written before the arm
            # existed predates R5, and defaulting it to r5 would pool a
            # pre-R5 run into the comparison R5 is judged by. It is listed
            # under its own name and pooled nowhere.
            m.setdefault("arm", "legacy")
            m["run"] = p.parent.name
            found.append((p.parent, m))
    dirs = {m["run"]: d for d, m in found}
    manifests = {m["run"]: _read_json(d / "manifest.json") for d, m in found}
    health = {m["run"]: health_check(d) for d, m in found}
    legacy = [m for _, m in found if m["arm"] == "legacy"]
    armed = [m for _, m in found if m["arm"] != "legacy"]
    # The pool: every run with an arm that passed the health gate. Every block
    # below is over it unless it says otherwise.
    measured = [m for m in armed if health[m["run"]]["valid"]]
    excluded = {m["run"]: health[m["run"]]["failures"] for m in armed
                if not health[m["run"]]["valid"]}
    measured_names = set(dirs)
    unmeasured = sorted(d.name for d in (runs_dir.iterdir() if runs_dir.is_dir() else ())
                        if d.is_dir() and d.name not in measured_names
                        and any(d.name.startswith(f"{t}__") for t in by_id))
    values = {m["run"]: _pipeline_values(manifests[m["run"]]) for _, m in found}
    key_info = {t.id: _key_counts(t) for t in tasks}

    def evidence_empty(rows: list[dict[str, Any]]) -> bool | None:
        mans = [manifests[m["run"]] for m in rows if manifests[m["run"]] is not None]
        return (not any(x.get("evidence") for x in mans)) if mans else None

    thin_rba = _thin_rba

    def faith(m: dict[str, Any], side: str) -> dict[str, Any] | None:
        f = m.get("faithfulness")
        return f.get(side) if isinstance(f, dict) and isinstance(f.get(side), dict) else None

    def rate_stats(rows: list[dict[str, Any]], k: str, side: str = "private") -> dict[str, Any]:
        """One rate over runs, nulls excluded, with its pooled k/n.

        A rate is null when its pool was empty (INS1), and a missing field is a
        measurement scored before the field existed; both mean "no number", and
        averaging either in as 0.0 would give the worst score to a run that made
        no binding. RBA also leaves out any run whose RBA pool is under
        MIN_RBA_POOL, named in `rba_suppressed`. Pooled k/n sums numerators and
        denominators over the same runs; for coverage the denominator is the
        task key's fact count, used only when the run was scored against that
        key.
        """
        vals: list[float] = []
        k_sum = n_sum = 0
        pooled_ok = k in _DENOMINATOR
        for m in rows:
            f = faith(m, side)
            v = None if f is None else f.get(k)
            # NaN is "no number" too: JSON can carry it, and round(v * n)
            # would raise on it before any block below is computed.
            if v is None or _is_nan(v) or (k == "rba" and thin_rba(f)):
                continue
            vals.append(v)
            if not pooled_ok:
                continue
            den = _DENOMINATOR[k]
            if den in ("gold", "stated"):
                sha, gold, stated = key_info.get(m["task_id"], (None, None, None))
                n = (gold if den == "gold" else stated) \
                    if sha and sha == m["faithfulness"].get("key_sha256") else None
            else:
                n = (f.get("denominators") or {}).get(den)
            if n is None:
                pooled_ok = False
                continue
            k_sum, n_sum = k_sum + round(v * n), n_sum + n
        out = spread(vals)
        if k in _DENOMINATOR:
            out["pooled"] = ({"k": k_sum, "n": n_sum, "rate": k_sum / n_sum if n_sum else None}
                             if pooled_ok and vals else None)
        return out

    def g3_row(m: dict[str, Any]) -> dict[str, Any]:
        """Reconstruction for one run, re-scored offline when the adversary's
        output is on disk so the recovered entities can be named. The scorer's
        own matching (reconstruction.py), over unique (text, category) pairs."""
        rec = m.get("reconstruction") or {}
        row: dict[str, Any] = {
            "run": m["run"], "arm": m["arm"], "task_id": m["task_id"],
            "recorded": {k: rec.get(k) for k in ("entities_recovered", "entities_total",
                                                 "fivegrams_recovered", "fivegrams_total")},
            "fivegrams_recovered": rec.get("fivegrams_recovered", 0),
            "fivegrams_total": rec.get("fivegrams_total", 0),
            "by_category": rec.get("by_category", {}),
        }
        ents, _src = _run_entities(dirs[m["run"]])
        out_p = dirs[m["run"]] / "adversary_output.txt"
        if ents is not None and out_p.exists():
            out_toks = tokenize(out_p.read_text(encoding="utf-8"))
            hits = [(t, c) for t, c in ents if _contains_run(out_toks, tokenize(t))]
            by_cat: dict[str, dict[str, int]] = {}
            for t, c in ents:
                slot = by_cat.setdefault(c, {"total": 0, "recovered": 0})
                slot["total"] += 1
                slot["recovered"] += (t, c) in hits
            row.update(source="re-scored offline from adversary_output.txt",
                       entities_total=len(ents), entities_recovered=len(hits),
                       recovered=[{"entity": t, "category": c} for t, c in hits],
                       by_category=by_cat, unique_denominator=True,
                       agrees_with_measurement=(len(hits) == rec.get("entities_recovered")
                                                and len(ents) == rec.get("entities_total")))
        else:
            # A measurement scored before the unique-entity denominator counted
            # occurrences (95 for 61 entities on smoke-q3); without the output
            # it cannot be re-scored, so it is flagged rather than corrected.
            row.update(source="measurement.json (no adversary output or entity file on disk, "
                              "so the recovered entities cannot be named)",
                       entities_total=rec.get("entities_total", 0),
                       entities_recovered=rec.get("entities_recovered", 0),
                       unique_denominator=(None if ents is None
                                           else rec.get("entities_total") == len(ents)),
                       recovered=None, agrees_with_measurement=None)
        return row

    g3 = {m["run"]: g3_row(m) for _, m in found}

    def recon_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
        rs = [g3[m["run"]] for m in rows]
        et, er = sum(r["entities_total"] for r in rs), sum(r["entities_recovered"] for r in rs)
        ft, fr = sum(r["fivegrams_total"] for r in rs), sum(r["fivegrams_recovered"] for r in rs)
        cats: dict[str, dict[str, int]] = {}
        for r in rs:
            for c, d in r["by_category"].items():
                slot = cats.setdefault(c, {"total": 0, "recovered": 0})
                slot["total"] += d["total"]
                slot["recovered"] += d["recovered"]
        return {
            "runs": len(rs),
            "entity_recovery": {"recovered": er, "total": et, "rate": er / et if et else None,
                                "per_run": spread([r["entities_recovered"] / r["entities_total"]
                                                   for r in rs if r["entities_total"]])},
            "fivegram_recovery": {"recovered": fr, "total": ft, "rate": fr / ft if ft else None,
                                  "per_run": spread([r["fivegrams_recovered"] / r["fivegrams_total"]
                                                     for r in rs if r["fivegrams_total"]])},
            "by_category": {c: {**d, "rate": d["recovered"] / d["total"] if d["total"] else None}
                            for c, d in sorted(cats.items())},
            "occurrence_denominators": [r["run"] for r in rs if r["unique_denominator"] is False],
        }

    def arm_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
        scored = [m for m in rows if faith(m, "private") is not None]
        return {
            "runs": [m["run"] for m in rows],
            "tasks": len({m["task_id"] for m in rows}),
            "key_sha256": sorted({m["faithfulness"].get("key_sha256") for m in scored
                                  if m["faithfulness"].get("key_sha256")}),
            "private_mean": spread([j["private_mean"] for m in rows for j in m["judgements"]]),
            "faithfulness": ({k: rate_stats(scored, k) for k in _FAITH_KEYS}
                             if scored else None),
            "rba_suppressed": [m["run"] for m in scored if thin_rba(faith(m, "private"))],
            "pipeline": {k: spread([v for m in rows if (v := values[m["run"]][k]) is not None])
                         for k in _PIPELINE_KEYS},
            "judge": _judge_block(rows, evidence_empty(rows)),
            "reconstruction": recon_block(rows),
        }

    def oracle_block(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Every measurement ran its own oracle, so the oracle is pooled over
        the task's runs of every arm; which arm it was measured beside does not
        change what it read."""
        scored = [m for m in rows if faith(m, "oracle")]
        if not rows:
            return None
        return {
            "runs": len(rows),
            "faithfulness": ({k: rate_stats(scored, k, "oracle") for k in _ORACLE_KEYS}
                             if scored else None),
            "judge_mean": spread([j["oracle_mean"] for m in rows for j in m["judgements"]]),
        }

    arm_names = sorted({m["arm"] for m in measured})
    arm_of = {m["run"]: m["arm"] for m in armed}
    by_arm = {a: arm_block([m for m in measured if m["arm"] == a]) for a in arm_names}

    def extraction_of(arm: str, rows: list[dict[str, Any]]) -> str | None:
        """Which arm's extraction these runs of `arm` masked, or None if not one arm's."""
        src = sorted({m.get("extraction_source", "unrecorded") for m in rows})
        if not src:
            return None
        # Resolve every source to the arm whose extraction it is; repeats of one
        # arm mix "extracted" (repeat 1) with "reused <arm>" (later repeats).
        canon = set()
        for one in src:
            if one == "extracted":
                canon.add(arm)
                continue
            m = re.search(r"__(" + "|".join(ARMS) + r")(?:__rep\d+)?/extractions\.json$", one)
            canon.add(m.group(1) if m else None)
        return canon.pop() if len(canon) == 1 else None

    def per_run_values(rows: list[dict[str, Any]], k: str) -> list[float]:
        if k == "judge_private_mean":
            return [statistics.fmean(j["private_mean"] for j in m["judgements"])
                    for m in rows if m["judgements"]]
        out = []
        for m in rows:
            f = faith(m, "private")
            v = None if f is None else f.get(k)
            if v is not None and not _is_nan(v) and not (k == "rba" and thin_rba(f)):
                out.append(v)
        return out

    def paired(a: list[float], b: list[float]) -> dict[str, Any] | None:
        if not a or not b:
            return None
        return {"from": statistics.fmean(a), "to": statistics.fmean(b),
                "delta": statistics.fmean(b) - statistics.fmean(a),
                "range": [min(b) - max(a), max(b) - min(a)],
                "n": {"from": len(a), "to": len(b)},
                "every_run_higher": min(b) > max(a), "every_run_lower": max(b) < min(a)}

    by_task: dict[str, Any] = {}
    for t in tasks:
        rows = [m for m in measured if m["task_id"] == t.id]
        arms_here = {a: [m for m in rows if m["arm"] == a]
                     for a in sorted({m["arm"] for m in rows})}
        sha, gold, stated = key_info[t.id]
        deltas: dict[str, Any] = {}
        for a, b in _DELTA_PAIRS:
            if a in arms_here and b in arms_here:
                ea, eb = extraction_of(a, arms_here[a]), extraction_of(b, arms_here[b])
                deltas[f"{a}->{b}"] = {
                    "extraction_shared": ea is not None and ea == eb,
                    **{k: paired(per_run_values(arms_here[a], k), per_run_values(arms_here[b], k))
                       for k in _DELTA_KEYS}}
        by_task[t.id] = {
            "corpus": str(t.corpus),
            "key_sha256": sha, "key_facts": gold, "key_facts_stated": stated,
            # Runs scored against a key other than the corpus's current one. The
            # blocks here still average them; the hypotheses block gives them no
            # value. Flagged so a table figure the hypotheses call "not testable"
            # is not quoted unnoticed: rescore them.
            "stale_key_runs": sorted(m["run"] for m in rows if faith(m, "private") is not None
                                     and m["faithfulness"].get("key_sha256") != sha),
            "table_data_cells": _table_data_cells(t.corpus) if rows else None,
            "arms": {a: arm_block(rs) for a, rs in arms_here.items()},
            "oracle": oracle_block(rows),
            "paired_deltas": deltas,
        }

    delta_summary: dict[str, Any] = {}
    for a, b in _DELTA_PAIRS:
        pair = f"{a}->{b}"
        per = {tid: bt["paired_deltas"][pair] for tid, bt in by_task.items()
               if pair in bt["paired_deltas"]}
        if not per:
            continue
        delta_summary[pair] = {}
        for k in _DELTA_KEYS:
            ds = {tid: d[k] for tid, d in per.items() if d[k] is not None}
            if not ds:
                continue
            up = sum(1 for d in ds.values() if d["delta"] > 0)
            sep = sum(1 for d in ds.values() if d["every_run_higher"])
            delta_summary[pair][k] = {
                "corpora": len(ds), "higher": up,
                "lower": sum(1 for d in ds.values() if d["delta"] < 0),
                "every_run_higher": sep,
                "delta_range": [min(d["delta"] for d in ds.values()),
                                max(d["delta"] for d in ds.values())],
                "statement": (f"{b} above {a} in {up} of {len(ds)} corpora; every {b} run above "
                              f"every {a} run in {sep} of {len(ds)}"),
            }

    # The crossings are scanned over every run with an arm, the gate's exclusions
    # included: a run that failed on pipeline health still sent what it sent,
    # and H3 is about every private-arm trace. Each hit says whether its run is
    # in the pool.
    pooled = {m["run"] for m in measured}
    crossing_arms = sorted({m["arm"] for m in armed})

    # ---------------------------------------------------- crossing (a)
    surfaces = {t.id: surface_groups_for(t) for t in tasks}
    # (b) and (c) name corpus entity strings. That is only safe for a corpus
    # the generators built (scope D5), which is exactly a task with a surface
    # list; on any other corpus the strings are private values, so the blocks
    # keep their counts and categories and leave the string out (None).
    named = {tid: groups is not None for tid, (groups, _src) in surfaces.items()}
    a_rows: list[dict[str, Any]] = []
    a_scanned: list[str] = []
    a_unscanned: dict[str, str] = {}
    a_exchanges: dict[str, int] = {}
    for m in armed:
        groups, _src = surfaces[m["task_id"]]
        trace = _read_trace(dirs[m["run"]])
        if groups is None or trace is None:
            a_unscanned[m["run"]] = ("no generator-surface list for the task" if groups is None
                                     else "no egress_trace.jsonl")
            continue
        group_of: dict[str, list[str]] = {}
        for g, ss in groups.items():
            for s in ss:
                group_of.setdefault(s, []).append(g)
        a_scanned.append(m["run"])
        a_exchanges[m["run"]] = len(trace)
        for h in scan_trace(trace, list(group_of), goal=by_id[m["task_id"]].goal):
            if h["side"] in ("cloud-reply",):
                continue    # replies are (b)'s business; (a) is the request side
            gs = group_of[h["needle"]]
            a_rows.append({"run": m["run"], "arm": m["arm"], "task_id": m["task_id"],
                           "pooled": m["run"] in pooled, "stage": h["stage"],
                           "field": h["field"], "side": h["side"], "groups": gs,
                           "surface": h["needle"], "count": h["count"],
                           "label_group": all(g in LABEL_GROUPS for g in gs)})
    crossed = [r for r in a_rows if r["side"] == "core-sent" and not r["label_group"]]
    crossed_labels = [r for r in a_rows if r["side"] == "core-sent" and r["label_group"]]
    crossing_a = {
        "definition": (
            "Whole-token, case-insensitive hits of every generator surface (the scenario's "
            "surfaces list) in core-sent request content: system, messages and tools of every "
            "exchange the monitor let through, over every run with an arm, runs the health "
            "gate excluded included ('pooled' says which). Excluded, and listed: spans inside "
            "the user goal, which crosses verbatim by design, and spans repeating an earlier "
            "reply of "
            "the same run (response_text or the planner's structured outline), which the cloud "
            "wrote. 'Crossed' means request side. Surfaces of the 'labels' group are ordinary "
            "words and are reported apart."),
        "surfaces_from": {tid: src for tid, (_g, src) in surfaces.items()},
        "trace_gap": _TRACE_GAP,
        "runs_scanned": a_scanned,
        "runs_not_scanned": a_unscanned,
        # A scanned run with no exchange read nothing: zero hits there is no
        # evidence, and H3 counts it as not scanned.
        "exchanges_traced": a_exchanges,
        "hits": crossed,
        "label_hits": crossed_labels,
        "by_arm": {a: {"runs": sum(1 for r in a_scanned if arm_of[r] == a),
                       "hits": sum(r["count"] for r in crossed if r["arm"] == a),
                       "label_hits": sum(r["count"] for r in crossed_labels if r["arm"] == a)}
                   for a in crossing_arms},
        "excluded": {side: [r for r in a_rows if r["side"] == side]
                     for side in ("user-goal", "cloud-echo", "not-sent")},
    }

    # ---------------------------------------------------- crossing (b)
    b_hits: list[dict[str, Any]] = []
    b_scanned: list[str] = []
    b_unscanned: dict[str, str] = {}
    for m in armed:
        ents, src = _run_entities(dirs[m["run"]])
        trace = _read_trace(dirs[m["run"]])
        if ents is None or trace is None:
            b_unscanned[m["run"]] = ("no entities.json or extractions.json" if ents is None
                                     else "no egress_trace.jsonl")
            continue
        b_scanned.append(m["run"])
        cats: dict[str, list[str]] = {}
        for t, c in ents:
            cats.setdefault(t, []).append(c)
        occ: dict[str, list[dict[str, Any]]] = {}
        for h in scan_trace(trace, list(cats), goal=by_id[m["task_id"]].goal):
            occ.setdefault(h["needle"], []).append(
                {k: h[k] for k in ("stage", "field", "side", "count")})
        for text, os_ in occ.items():
            sides = {o["side"] for o in os_}
            marked = ("core-sent" if "core-sent" in sides else
                      "user-goal" if "user-goal" in sides else
                      "not-sent" if sides == {"not-sent"} else "cloud-authored")
            b_hits.append({"run": m["run"], "arm": m["arm"], "task_id": m["task_id"],
                           "pooled": m["run"] in pooled,
                           "entity": text if named[m["task_id"]] else None,
                           "categories": cats[text], "marked": marked,
                           # A cloud-authored hit can also sit in a request the
                           # monitor refused; the mark alone would hide that.
                           "also_not_sent": marked != "not-sent" and "not-sent" in sides,
                           "entity_file": src,
                           "occurrences": os_})
    crossing_b = {
        "definition": (
            "Whole-token, case-insensitive hits of each run's own extracted entity strings "
            "(the masked set, entities.json) in every trace field, request and reply. One hit "
            "is one (run, entity); it is marked core-sent if any occurrence is in request "
            "content the core built, else cloud-authored (a reply, or a request span repeating "
            "an earlier reply); also_not_sent says a refused request carried it too. Strings "
            "are named only for a task whose corpus has a generator-surface list (a synthetic "
            "corpus, scope D5); elsewhere 'entity' is None and the string stays in the run "
            "directory."),
        "entities_named": named,
        "trace_gap": _TRACE_GAP,
        "runs_scanned": b_scanned,
        "runs_not_scanned": b_unscanned,
        "hits": b_hits,
        "by_arm": {a: {"hits": sum(1 for h in b_hits if h["arm"] == a),
                       "core_sent": sum(1 for h in b_hits
                                        if h["arm"] == a and h["marked"] == "core-sent"),
                       "cloud_authored": sum(1 for h in b_hits
                                             if h["arm"] == a
                                             and h["marked"] == "cloud-authored")}
                   for a in crossing_arms},
    }

    # ---------------------------------------------------- crossing (c)
    c_rows = [g3[m["run"]] for m in armed]
    crossing_c = {
        "definition": (
            "Entities the G3 reconstruction adversary's output recovers, as its scorer counts "
            "them (reconstruction.py: whole-token runs over unique (text, category) pairs). "
            "A recovery is the adversary's guess matching an extracted entity, not a string "
            "found crossing; it is reported only as a G3 recovery, a direct-access lower "
            "bound, and never added to (a) or (b)."),
        "hits": [{"run": r["run"], "arm": r["arm"], "pooled": r["run"] in pooled, **h,
                  "entity": h["entity"] if named[r["task_id"]] else None}
                 for r in c_rows for h in (r["recovered"] or [])],
        "distinct_entities": sorted({h["entity"] for r in c_rows if named[r["task_id"]]
                                     for h in (r["recovered"] or [])}),
        "unnamed_recoveries": sum(len(r["recovered"] or []) for r in c_rows
                                  if not named[r["task_id"]]),
        "entities_named": named,
        "runs_unnamed": [r["run"] for r in c_rows if r["recovered"] is None],
        "disagreements_with_measurement": [r["run"] for r in c_rows
                                           if r["agrees_with_measurement"] is False],
        "by_arm": {a: {"entities_recovered": sum(r["entities_recovered"] for r in c_rows
                                                 if r["arm"] == a),
                       "entities_total": sum(r["entities_total"] for r in c_rows
                                             if r["arm"] == a)}
                   for a in crossing_arms},
    }

    # ---------------------------------------------------- alternate key
    alt: dict[str, Any] | None = None
    if alt_key is not None:
        # A directory holds one key per task, <task_id>.json: each corpus has its own
        # key, so the pre-fix lexicon is scored with that corpus's pre-fix key
        # (eval/calibration/prefix_keys/, EXP2). A single file is one key for every
        # task, as before; with four corpora it would score B, C and D against A's.
        if alt_key.is_dir():
            key_files = {tid: alt_key / f"{tid}.json" for tid in sorted({m["task_id"]
                                                                       for m in measured})}
            key_files = {tid: p for tid, p in key_files.items() if p.exists()}
        else:
            key_files = {tid: alt_key for tid in sorted({m["task_id"] for m in measured})}
        keys = {tid: load_key(p) for tid, p in key_files.items()}
        rescored = []
        for m in measured:
            rp = dirs[m["run"]] / "report.md"
            if m["arm"] != "r1" or not rp.exists() or m["task_id"] not in keys:
                continue
            res = score(rp.read_text(encoding="utf-8"), keys[m["task_id"]]).to_json()
            rescored.append({"run": m["run"], "task_id": m["task_id"], "arm": "r1",
                             "faithfulness": {"private": res}})
        shas = {tid: hashlib.sha256(p.read_bytes()).hexdigest() for tid, p in key_files.items()}
        alt = {
            "path": str(alt_key),
            "key_sha256": (shas[next(iter(shas))] if not alt_key.is_dir() and shas
                           else hashlib.sha256(json.dumps(shas, sort_keys=True)
                                               .encode("utf-8")).hexdigest()),
            "keys": {tid: {"path": str(p), "key_sha256": shas[tid]}
                     for tid, p in key_files.items()},
            "tasks_without_key": sorted({m["task_id"] for m in measured} - set(key_files)),
            "note": "r1's reports scored offline from report.md against this key; the "
                    "blocks above use the key each measurement records.",
            "by_task": {tid: {k: rate_stats([r for r in rescored if r["task_id"] == tid], k)
                              for k in ("rba", "attribute_accuracy")}
                        for tid in sorted({r["task_id"] for r in rescored})},
            "rba_suppressed": [r["run"] for r in rescored
                               if thin_rba(r["faithfulness"]["private"])],
            "per_run": {r["run"]: {k: r["faithfulness"]["private"][k]
                                   for k in ("rba", "attribute_accuracy", "denominators")}
                        for r in rescored},
        }

    truncated = sorted({m["task_id"] for m in measured if m["oracle_truncated_chars"] > 0})
    # `bucket`, not `arm`: these are cost lines, and "arm" now names something
    # else in this file.
    # A bucket some measured task never recorded (the adversary, before INS4) is
    # None, not 0.0: a zero there would read as "cost nothing", and the total is
    # then a floor, which `cost_usd.incomplete` names.
    usd = {bucket: (sum(m["usd"][bucket] for m in measured)
                    if all(bucket in m["usd"] for m in measured) else None)
           for bucket in ("oracle", "judge", "adversary")}
    usd_incomplete = [b for b, v in usd.items() if v is None]
    sources = {a: sorted({m.get("extraction_source", "unrecorded") for m in measured
                          if m["arm"] == a}) for a in by_arm}

    def compare(a: str, b: str) -> dict[str, Any] | None:
        if not (by_arm.get(a) and by_arm[a]["faithfulness"]
                and by_arm.get(b) and by_arm[b]["faithfulness"]):
            return None
        ea = extraction_of(a, [m for m in measured if m["arm"] == a])
        eb = extraction_of(b, [m for m in measured if m["arm"] == b])
        shared = ea is not None and ea == eb
        fa, fb = by_arm[a]["faithfulness"], by_arm[b]["faithfulness"]
        return {
            "extraction_sources": {a: sources.get(a), b: sources.get(b)},
            "extraction_shared": shared,
            "extraction_warning": (None if shared else
                "The arms ran separate extractions. The extractor samples at "
                f"temperature 0.1 with no seed, so they masked different entity sets "
                f"and this delta is not attributable to {b} over {a}."),
            "pooled_over": sorted({m["task_id"] for m in measured if m["arm"] in (a, b)}),
            **{k: {a: fa[k]["mean"], b: fb[k]["mean"], "delta": fb[k]["mean"] - fa[k]["mean"],
                   "n": {a: fa[k]["n"], b: fb[k]["n"]}}
               for k in _FAITH_KEYS
               if fa[k]["mean"] is not None and fb[k]["mean"] is not None},
        }

    comparisons = {f"{a}_vs_{b}": c for a, b in (("baseline", "r5"), ("baseline", "r1"),
                                                ("r5", "r1"))
                   if (c := compare(a, b)) is not None}

    att_root = attempts_dir_for(runs_dir)
    attempts = [d.name for d in (att_root.iterdir() if att_root.is_dir() else ())
                if d.is_dir() and any(d.name.startswith(f"{t}__") for t in by_id)]
    hypotheses = _hypotheses(tasks, measured, armed, excluded, values,
                             {tid: bt["table_data_cells"] for tid, bt in by_task.items()},
                             key_info, crossing_a, unmeasured, attempts)

    return {
        "instrument": "scripts/run_evaluation.py",
        "git_commit": _git_commit(),
        "tasks_defined": len(tasks),
        # Distinct tasks, not runs: nine repeats of one corpus are one task.
        "tasks_measured": len({m["task_id"] for m in measured}),
        "runs_measured": len(measured),
        "resolved_models": sorted({m for x in measured for j in x["judgements"]
                                   for m in j["judge_models"]}),
        "health_gate": {
            "rule": HEALTH_RULE,
            "summary": f"{len(measured)}/{len(armed)} valid",
            "runs_checked": len(armed),
            "valid": [m["run"] for m in measured],
            "excluded": excluded,
            "outcomes": {m["run"]: health[m["run"]]["outcomes"] for m in armed},
            "unmeasured_runs": unmeasured,
        },
        "utility": {
            "note": "Over the runs that pass the health gate, legacy excluded. The oracle's "
                    "own scores are reported beside PrivDeep's because a retention percentage "
                    "is uninterpretable without them (scope section 7). Per-run values are "
                    "kept: at this N the spread is the finding, not the mean.",
            **_judge_block(measured, evidence_empty(measured)),
            "judge_is_not_repeatable": (
                "Sonnet 5 rejects the sampling parameters, so no setting makes a judge "
                "call reproducible. Both orderings are scored and the disagreement is "
                "reported above rather than averaged away."),
        },
        "reconstruction": {
            "note": "One adversary yields a LOWER bound on what is recoverable, never a "
                    "worst case. The metric is surface-string recovery, which "
                    "pseudonymisation suppresses by construction; THREAT_MODEL.md section 7 "
                    "says so, and a referee will. Denominators are unique (text, category) "
                    "entities per run. No interval: the runs share a corpus and an extraction.",
            **recon_block(measured),
            "by_arm": {a: b["reconstruction"] for a, b in by_arm.items()},
        },
        "cost_usd": {**usd, "total": sum(v for v in usd.values() if v is not None),
                     "incomplete": usd_incomplete,
                     "note": "Over the pooled runs; legacy and excluded runs are not in it."},
        "truncated_tasks": {
            "ids": truncated,
            "note": "The oracle is capped at max_doc_chars while the private arm abstracts "
                    "the whole corpus locally. A task listed here had its baseline read a "
                    "prefix while PrivDeep read everything, so its utility gap is partly "
                    "the cap and must not be pooled with the rest without saying so.",
        },
        "arms": by_arm,
        "by_task": by_task,
        "paired_deltas": delta_summary,
        "paired_deltas_note": (
            "'Paired' means paired by corpus: both arms ran on the same corpus from one shared "
            "extraction. Runs are not paired by repeat, so 'range' is [min(to) - max(from), "
            "max(to) - min(from)] over every cross-arm run pair, and the delta is a difference "
            "of arm means, not a paired difference in the statistical sense."),
        "oracle": {"note": "Pooled over every pooled run's oracle, all tasks; per task in "
                           "by_task. numerals_outside_key is a private-arm figure (INS1).",
                   **(oracle_block(measured) or {})},
        "baseline_vs_r5": comparisons.get("baseline_vs_r5"),
        "comparisons": comparisons,
        "crossings": {
            "note": "Three separate measurements, never summed: (a) generator surfaces the "
                    "core sent, (b) the run's extracted entities anywhere in the trace, (c) "
                    "what the G3 adversary recovered.",
            "a_generator_surfaces": crossing_a,
            "b_extracted_entities": crossing_b,
            "c_reconstruction": crossing_c,
        },
        "hypotheses": hypotheses,
        "alt_key": alt,
        "legacy": {
            "note": "Measured before the arm flag existed, so no arm is recorded. Listed here "
                    "and pooled nowhere: its arm cannot be established, and pooling it would "
                    "put a pre-R5 run into the comparison R5 is judged by.",
            "runs": [m["run"] for m in legacy],
            "health": {m["run"]: health[m["run"]] for m in legacy},
            "summary": arm_block(legacy) if legacy else None,
        },
        "per_task": [m for _, m in found],
    }


# --------------------------------------------------------------------- cli


def rescore(tasks: list[Task], runs_dir: Path) -> int:
    """Recompute faithfulness for every measured run against the current key.

    Local and free: it reads report.md and oracle_report.md already on disk and
    changes nothing else in the measurement. It exists because the key gained
    facts after runs had been scored, and runs scored against different keys are
    not comparable. Each rewritten measurement records the key's hash.
    """
    by_id = {t.id: t for t in tasks}
    n = 0
    for mpath in sorted(runs_dir.glob("*/measurement.json")):
        run_dir = mpath.parent
        m = json.loads(mpath.read_text(encoding="utf-8"))
        task = by_id.get(m.get("task_id"))
        if task is None or not (run_dir / "oracle_report.md").exists():
            continue
        m["faithfulness"] = _faithfulness(
            task, run_dir, (run_dir / "report.md").read_text(encoding="utf-8"),
            (run_dir / "oracle_report.md").read_text(encoding="utf-8"))
        mpath.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
        n += 1
        print(f"  rescored {run_dir.name}")
    print(f"rescored {n} measurement(s)")
    return 0


def _require_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key or key.startswith("sk-ant-placeholder") or len(key) < 20:
        raise SystemExit(
            "ANTHROPIC_API_KEY is unset or a placeholder. Phase two is the arm that "
            "bypasses the monitor by definition and needs a funded key; phase one does "
            "not. Set a real key or run `private` / `aggregate` only.")
    return key


async def _measure_all(args: argparse.Namespace, tasks: list[Task]) -> int:
    runs = Path(args.runs)
    est = estimate_cost(tasks, judge_repeats=args.judge_repeats, max_doc_chars=args.max_doc_chars)
    pending = [t for t in tasks
               if args.force
               or not (run_dir_for(runs, t.id, args.arm, args.rep)
                       / "measurement.json").exists()]
    print("\nestimated cost (assumes every cap reached, no cache hits — an over-estimate):")
    for t in pending:
        print(f"  {t.id:<24} ${est[t.id]:.3f}")
    print(f"  {'TOTAL for ' + str(len(pending)) + ' task(s)':<24} "
          f"${sum(est[t.id] for t in pending):.2f}\n")
    if not pending:
        print("nothing to do; every task already has measurement.json (use --force to "
              "redo; the earlier measurement is copied to eval/attempts/ first)")
        return 0
    if not args.yes:
        print("refusing to spend without --yes")
        return 1
    prov = host_provenance()
    if _refuse_unclean(prov, args.allow_dirty):
        return 1

    key = _require_key()
    t0 = time.time()
    async with CloudClient(os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
                           api_key=key) as cloud:
        for t in pending:
            run_dir = run_dir_for(runs, t.id, args.arm, args.rep)
            if not (run_dir / "report.md").exists():
                print(f"  [{t.id}] no phase-one run at {run_dir}; run `private` first. Skipping.")
                continue
            if (run_dir / "measurement.json").exists():
                # --force re-measures in place; the paid-for readings it would
                # overwrite are kept first.
                archive_attempt(run_dir, runs, copy=True)
            print(f"  [{t.id}] measuring ...", flush=True)
            res = await measure_task(t, run_dir, cloud, judge_repeats=args.judge_repeats,
                                     max_doc_chars=args.max_doc_chars, arm=args.arm,
                                     rep=args.rep, provenance=prov)
            spent = sum(res["usd"].values())
            print(f"  [{t.id}] done, ${spent:.3f}, "
                  f"private {res['judgements'][0]['private_mean']:.2f} vs "
                  f"oracle {res['judgements'][0]['oracle_mean']:.2f}, "
                  f"entity recovery {res['reconstruction']['entity_recovery']:.3f}")
    print(f"\nphase two finished in {time.time() - t0:.0f}s")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("phase", choices=["private", "measure", "aggregate", "rescore"])
    ap.add_argument("--tasks", default=str(_REPO / "eval" / "tasks.json"))
    ap.add_argument("--runs", default=str(DEFAULT_RUNS))
    ap.add_argument("--out", default=str(DEFAULT_ARTIFACT))
    ap.add_argument("--judge-repeats", type=int, default=3,
                    help="score each pair this many times (default 3). The judge has no "
                         "determinism setting and one reading was measured half a point "
                         "from its own repeats, so a single call is not a measurement")
    ap.add_argument("--arm", choices=ARMS, default="r5",
                    help="which arm to produce or measure. Each arm gets its own run "
                         "directory; sharing one would make the second arm reuse the "
                         "first arm's phase-one output.")
    ap.add_argument("--reuse-extraction-from", choices=ARMS, default=None,
                    help="phase one: reuse that arm's saved extraction instead of "
                         "extracting again, so both arms mask the same entity set")
    ap.add_argument("--rep", type=int, default=1,
                    help="repeat number; repeat 1 is the arm's original run directory")
    ap.add_argument("--max-doc-chars", type=int, default=60_000)
    ap.add_argument("--force", action="store_true",
                    help="redo runs already on disk. Nothing is deleted: the earlier "
                         "attempt is kept under eval/attempts/<run>__attempt<k>/")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="spend even though the tree differs from its commit; the "
                         "manifest then records tree_dirty=true")
    ap.add_argument("--recreate", action="store_true",
                    help="phase one: force-recreate the monitor and the core once before "
                         "the batch, so both run the code on disk")
    ap.add_argument("--yes", action="store_true",
                    help="required before either phase spends money. Phase one is not "
                         "free: the planner and every section draft are billable cloud "
                         "calls made through the monitor.")
    ap.add_argument("--alt-key", default=None, metavar="PATH",
                    help="aggregate: also score r1's reports offline against this gold key "
                         "(e.g. the pre-fix RBA attribute lexicon), reported apart")
    args = ap.parse_args(argv)

    tasks = load_tasks(Path(args.tasks))
    runs = Path(args.runs)

    if args.phase == "private":
        runs.mkdir(parents=True, exist_ok=True)
        est = estimate_private_cost(tasks)
        pending = [t for t in tasks if args.force
                   or not (run_dir_for(runs, t.id, args.arm, args.rep) / "report.md").exists()]
        print(f"\nestimated cost of the private arm ({args.arm}) - billable Tier-2 calls "
              "through the monitor; only the local extraction is free:")
        for t in pending:
            print(f"  {t.id:<24} ${est[t.id]:.3f}")
        print(f"  {'TOTAL for ' + str(len(pending)) + ' task(s)':<24} "
              f"${sum(est[t.id] for t in pending):.2f}\n")
        if not pending:
            print("nothing to do; every task already has a phase-one run "
                  "(use --force to redo; the earlier attempt is moved to eval/attempts/, "
                  "never deleted)")
            return 0
        if not args.yes:
            print("refusing to spend without --yes")
            return 1
        prov = host_provenance()
        if _refuse_unclean(prov, args.allow_dirty):
            return 1
        if args.recreate:
            recreate_services(pending[0].corpus)     # once per batch, not per task
        for t in pending:
            # The start-of-batch values, checked again around each run: a
            # change raises and ends the batch, since the monitor still runs
            # the code it started with.
            run_private_arm(t, runs, force=args.force, arm=args.arm,
                            reuse_from=args.reuse_extraction_from, rep=args.rep,
                            provenance=prov, recreated=args.recreate)
        return 0

    if args.phase == "measure":
        return asyncio.run(_measure_all(args, tasks))

    if args.phase == "rescore":
        return rescore(tasks, runs)

    out = Path(args.out)
    report = aggregate(tasks, runs, alt_key=Path(args.alt_key) if args.alt_key else None)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary(report))
    print(f"wrote {out}")
    return 0


def _show(x: dict[str, Any] | None) -> str:
    if not x or x["mean"] is None:
        return "n/a (n=0)"
    sd = f" sd {x['stdev']:.3f}" if x["stdev"] is not None else ""
    rng = f" [{x['min']:.3f}-{x['max']:.3f}]" if x["n"] > 1 else ""
    pooled = x.get("pooled")
    kn = f" pooled {pooled['k']}/{pooled['n']}" if pooled else ""
    return f"{x['mean']:.3f}{sd}{rng} (n={x['n']}){kn}"


def _num(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def _component_line(name: str, c: dict[str, Any]) -> str:
    lo, hi = c["lower"], c["upper"]
    why = f"; {c['reason']}" if c["reason"] else ""
    short = (f"; under the {REGISTERED_REPEATS} registered repeats: "
             f"{', '.join(c['short_of_registered_repeats'])}"
             if c.get("short_of_registered_repeats") else "")
    floor = (f"; FLOOR: the smallest {hi['label']} is 0, so no value can be below it"
             if c.get("floor") else "")
    return (f"      {name}: {c['outcome']}  max {lo['label']} {_num(lo['max'])} "
            f"(n={len(lo['values'])}) vs min {hi['label']} {_num(hi['min'])} "
            f"(n={len(hi['values'])}){why}{short}{floor}")


def _hypothesis_lines(h: dict[str, Any]) -> list[str]:
    """The hypotheses block as printed: each outcome, the two values that decide
    it, and the reason when it is not testable."""
    corpora = " ".join(f"{k}={v or '-'}" for k, v in h["corpora"].items())
    unmapped = (f"; unmapped tasks, in no hypothesis: {h['unmapped_tasks']}"
                if h["unmapped_tasks"] else "")
    lines = [f"hypotheses ({h['source']}; computed from the pooled runs, not judged):",
             f"  corpora {corpora}{unmapped}"]
    if h["corpus_path_mismatch"]:
        lines.append(f"  registered id whose corpus directory is not named after it, so not "
                     f"mapped: {h['corpus_path_mismatch']}")
    if h["short_of_registered_repeats"]:
        lines.append(f"  fewer pooled runs than the {h['registered_repeats']} registered: "
                     f"{h['short_of_registered_repeats']}")
    lines.append(f"  H1, as registered: {h['H1']['definition']}")
    for letter, pc in h["H1"]["per_corpus"].items():
        lines.append(f"  H1 on {letter}: {pc['outcome']}")
        lines += [_component_line(k, c) for k, c in pc["components"].items()]
    for name in ("H2", "H3", "H4-D", "H4-D'"):
        x = h[name]
        if name != "H3":
            lines.append(f"  {x['label']}: {x['outcome']}")
            lines += [_component_line(k, c) for k, c in x["components"].items()]
            if name == "H2":
                for arm, r in x["rba_on_C_reported_not_tested"].items():
                    vals = ", ".join(f"{v:.3f}" for v in r["values"].values()) or "none"
                    lines.append(f"      RBA on C, {arm}, reported and not tested: {vals}"
                                 + (f"; no value for {len(r['no_value'])} run(s)"
                                    if r["no_value"] else "")
                                 + (f"; {r['absent']}" if r["absent"] else ""))
            continue
        why = f"; {x['reason']}" if x["reason"] else ""
        lines.append(f"  H3: {x['outcome']}  {x['hits']} core-sent hit(s) "
                     f"({x['label_group_hits']} label-group) over {x['runs_scanned']} "
                     f"scanned run(s){why}")
        if x["crossing_strings"]:
            lines.append(f"      crossing strings: {x['crossing_strings']} by field "
                         f"{x['hits_by_field']}")
        lines.append(f"      trace gap: {x['trace_gap']}")
        if x["attempts_not_scanned"]:
            lines.append(f"      archived attempts, sent and not scanned by any block: "
                         f"{x['attempts_not_scanned']}")
    return lines


def summary(report: dict[str, Any]) -> str:
    """The aggregate's console summary: the gate, the per-corpus x arm figures the
    paper quotes, and the three crossing measurements, each apart."""
    lines: list[str] = []
    g = report["health_gate"]
    lines.append(f"health gate: {g['summary']} (pipeline health only; refusals are outcomes)")
    for run, why in g["excluded"].items():
        lines.append(f"  EXCLUDED {run}: {'; '.join(why)}")
    refused = {r: o["refused_sections"] for r, o in g["outcomes"].items()
               if o.get("refused_sections")}
    plan_refused = [r for r, o in g["outcomes"].items() if o.get("plan_refused")]
    leak = {r: o["relations_dropped_leak"] for r, o in g["outcomes"].items()
            if o.get("relations_dropped_leak")}
    lines.append(f"  outcomes, not gated: {sum(len(v) for v in refused.values())} refused "
                 f"section(s) in {len(refused)} run(s), {len(plan_refused)} refused plan(s), "
                 f"{sum(leak.values())} relation(s) dropped by the leak gate in "
                 f"{len(leak)} run(s)")
    if g["unmeasured_runs"]:
        lines.append(f"  phase-one runs with no measurement: {g['unmeasured_runs']}")
    if report["legacy"]["runs"]:
        lines.append(f"  legacy, listed and pooled nowhere: {report['legacy']['runs']}")
    lines.append(f"tasks measured: {report['tasks_measured']}/{report['tasks_defined']} "
                 f"({report['runs_measured']} runs)")
    if report["runs_measured"]:
        u = report["utility"]
        eg = u["mean_excluding_groundedness"]
        lines.append(f"  judge  private {_show(u['private_mean'])}  oracle "
                     f"{_show(u['oracle_mean'])}  position bias {_show(u['position_bias'])}")
        if u["groundedness_uninformative"]:
            lines.append(f"         without groundedness (evidence bank empty): private "
                         f"{_show(eg['private'])}  oracle {_show(eg['oracle'])}")
        floor = (f" (a floor: {', '.join(report['cost_usd']['incomplete'])} not recorded)"
                 if report["cost_usd"]["incomplete"] else "")
        lines.append(f"  spent ${report['cost_usd']['total']:.2f}{floor}")
    for tid, bt in report["by_task"].items():
        if not bt["arms"]:
            continue
        lines.append(f"task {tid}  (key {str(bt['key_sha256'])[:8]}, "
                     f"{bt['table_data_cells']} table data cells)")
        if bt["stale_key_runs"]:
            lines.append(f"  WARNING scored against another key, averaged here but given no "
                         f"value by the hypotheses: {bt['stale_key_runs']}")
        for arm_name, info in bt["arms"].items():
            f = info["faithfulness"] or {}
            p = info["pipeline"]
            lines.append(f"  {arm_name:<9} runs={len(info['runs'])}  RBA {_show(f.get('rba'))}"
                         f"  attribute {_show(f.get('attribute_accuracy'))}")
            lines.append(f"  {'':<9} coverage_correct {_show(f.get('coverage_correct'))}  "
                         f"coverage_stated {_show(f.get('coverage_stated'))}")
            lines.append(f"  {'':<9} pruned {_show(p['sentences_pruned'])}  not recorded "
                         f"{_show(p['not_recorded'])}  facts_structural "
                         f"{_show(p['facts_structural'])}  refused sections "
                         f"{_show(p['refused_sections'])}  leak-gate drops "
                         f"{_show(p['relations_dropped_leak'])}")
            if info["rba_suppressed"]:
                lines.append(f"  {'':<9} RBA left out, under {MIN_RBA_POOL} scored "
                             f"occurrences: {info['rba_suppressed']}")
        o = bt["oracle"]
        if o and o["faithfulness"]:
            lines.append(f"  {'oracle':<9} runs={o['runs']}  RBA {_show(o['faithfulness']['rba'])}"
                         f"  attribute {_show(o['faithfulness']['attribute_accuracy'])}")
        for pair, d in bt["paired_deltas"].items():
            r = d.get("rba")
            if r:
                lines.append(f"  {pair:<14} RBA delta {r['delta']:+.3f} "
                             f"[{r['range'][0]:+.3f}, {r['range'][1]:+.3f}]"
                             f"{'  every run higher' if r['every_run_higher'] else ''}")
    for pair, d in report["paired_deltas"].items():
        if "rba" in d:
            lines.append(f"  {pair}: RBA {d['rba']['statement']}")
    c = report["crossings"]
    a, b, cc = c["a_generator_surfaces"], c["b_extracted_entities"], c["c_reconstruction"]
    unscanned = f", not scanned: {a['runs_not_scanned']}" if a["runs_not_scanned"] else ""
    lines.append(f"(a) generator surfaces in core-sent content: {len(a['hits'])} hit(s) "
                 f"over {len(a['runs_scanned'])} runs{unscanned}")
    for h in a["hits"] + a["label_hits"]:
        lines.append(f"    {h['run']} {h['stage']} {h['field']} {h['groups']} "
                     f"{h['surface']!r} x{h['count']}")
    excl = {k: sum(r["count"] for r in v) for k, v in a["excluded"].items()}
    lines.append(f"    label-group hits {len(a['label_hits'])}; excluded occurrences {excl}")
    lines.append(f"(b) extracted entities in the trace: {len(b['hits'])} hit(s) over "
                 f"{len(b['runs_scanned'])} runs")
    for h in b["hits"]:
        also = " (a refused request carried it too)" if h["also_not_sent"] else ""
        lines.append(f"    {h['run']} {h['entity'] or '(unnamed)'!r} {h['categories']} "
                     f"{h['marked']}{also}")
    lines.append(f"(c) G3 adversary recoveries: {len(cc['hits'])} over "
                 f"{len({h['run'] for h in cc['hits']})} run(s), distinct "
                 f"{cc['distinct_entities']}")
    for h in cc["hits"]:
        lines.append(f"    {h['run']} {h['entity'] or '(unnamed)'!r} {h['category']}")
    if cc["runs_unnamed"]:
        lines.append(f"    recoveries not nameable (no adversary output): {cc['runs_unnamed']}")
    if cc["disagreements_with_measurement"]:
        lines.append(f"    WARNING offline re-score differs from measurement.json in: "
                     f"{cc['disagreements_with_measurement']}")
    lines += _hypothesis_lines(report["hypotheses"])
    if report["alt_key"]:
        ak = report["alt_key"]
        lines.append(f"alternate key {ak['key_sha256'][:8]} ({ak['path']}), r1:")
        for tid, d in ak["by_task"].items():
            lines.append(f"  {tid}: RBA {_show(d['rba'])}  attribute "
                         f"{_show(d['attribute_accuracy'])}")
    if report["truncated_tasks"]["ids"]:
        lines.append(f"  WARNING truncated oracle corpus in: {report['truncated_tasks']['ids']}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
