#!/usr/bin/env python3
"""What crossed, what was refused, and what it cost, over every attempted run.

Why this exists
---------------
Plan task EXP5, experiment X3 part 3. Two questions the paper has to answer
from artifacts rather than recollection: how often does the system refuse
legitimate traffic, counted over every attempt and not only the runs that
were kept; and, per arm, what exactly goes on the wire and what one run
costs. Before this script both answers existed only as figures read off
individual files by hand.

What it reads, and where each figure comes from
-----------------------------------------------
Every run directory under two kinds of root, kept apart from discovery on:
*frozen* roots (by default ``eval/runs``), the runs the paper reports, and
*attempt* roots (by default ``eval/attempts``, given with ``--attempts``),
where INS3 archives a run before its re-run. Each row carries ``attempt``,
set by which kind of root it was found under, never guessed from a
directory name. Per run:

* ``egress_trace.jsonl``, the core's own record of every cloud exchange
  (``tier2_cloud/tracing.py``). One line is one egress attempt the monitor
  answered with a verdict: ``tracing.py`` writes a line on success or on
  ``EgressRefused`` (the monitor's 403) and on nothing else. Sent content is
  ``system`` + ``messages`` + ``tools``; received content is
  ``response_text`` + ``structured``. A monitor refusal is a line whose
  ``refused`` holds the monitor's reason. Checked against the pilot files:
  those are the field names, and ``tools`` also crosses (the planner's tool
  schema), so it is counted as sent even though it is a constant.
* ``manifest.json``: the arm, the egress counters (cross-checked against the
  trace), per-section ``refused`` (a ``reintegrate:`` prefix is a
  reintegrator refusal; ``draft: CloudError``/``GatewayError`` is a transport
  failure, not a refusal), ``sentences_pruned``, and the notes. The
  classification is a choice and moves a count: the monitor's own 502/503
  answers (``NO_API_KEY``, ``AUDIT_UNAVAILABLE``, ``UPSTREAM_UNREACHABLE``)
  reach the core as ``GatewayError``, leave no trace line, and so are
  transport failures here, not monitor refusals. A transport failure on the
  *plan* call has no section record. Since 2026-10-27 its run writes a
  manifest whose note names it ("planning failed: CloudError" or "...:
  GatewayError"; the message is in the pipeline's stderr, which an archived
  attempt keeps as ``attempt_output.txt``, not read here), and it is counted
  from that note, its reason keeping the stage (``plan: GatewayError``). Before
  that date such a run wrote no run file, so it is no row and is not counted.
  What separates it from an unusable plan (``planning failed: PlannerError``)
  is the trace, not whether the request crossed (after a ``CloudError`` it
  always did): the unusable plan's exchange is a trace line the manifest counts
  as allowed, so it is an allowed egress attempt and no transport failure.
* ``measurement.json`` and ``reconstruction.json`` (phase two): oracle, judge
  and adversary token usage, for the full per-run cost.
* The monitor's audit log, if one was archived beside the run as
  ``audit_eventlog.jsonl``. The gateway writes one log for its whole lifetime
  to its own volume, and nothing copies a per-run slice today, so for the
  pilot this source is absent and the table says so rather than implying it
  was read. The monitor writes a pre-forward record (``verdict:
  "forwarding"``) before it calls the upstream and an outcome record after,
  both under one ``request_id``; a refusal is a single record. One attempt is
  counted once: a ``forwarding`` record is dropped when an outcome record
  shares its ``request_id``, and kept, under ``forwarding``, when none does,
  since that request may have reached C with its outcome unrecorded. A log
  written before the monitor audited first has no ``forwarding`` records and
  is counted as before.
* Leak-gate drops. Since 2026-09-27 the W2 gate drops a relation that
  carries an entity string extracted from any document of the corpus (the
  corpus-wide pass runs after every document is extracted), counts it in its
  own document's counter, and the run goes on; the manifest's
  ``extraction.relations_dropped_leak`` is read per run (None where a manifest
  predates the counter) and summed under
  ``leak_gate_drops``. A drop is not a refusal: nothing was asked of the
  cloud and refused, a relation was simply never sent, so it does not count
  towards ``refused_any``.
* A leak-gate abort (``OntologyLeak``, today from ``assert_no_corpus_leak`` on
  the reuse path, earlier from ``assert_no_entity_leak``) happens
  before any egress, so it leaves no trace line. A fresh extraction no longer
  aborts; a run still does when it reuses a saved extraction whose relation
  carries an entity string (an older or altered file), and every run before
  2026-09-27 did. It is counted when the run directory's manifest notes or an
  archived ``error.txt``/``stderr.txt`` name ``OntologyLeak``. The strict
  corpus gate's message names only the category; messages from before it
  quoted the offending entity. Either way only the category is kept, never
  the text.

Definitions that move a number
------------------------------
* **Slots advertised** are the ``AVAILABLE PLACEHOLDERS`` lines of the plan
  request, by category: what the planner is told exists. **Slots on the
  wire** are the distinct slot ids in core-sent messages and tools on any
  exchange. The system prompts are left out: they are code constants, and the
  drafter's carries the example id ``⟦SLOT:PROJECT_a1b2c3d4⟧``, which a first
  version counted as one extra slot on every run. On the pilot the two
  figures then agree. Only that one literal is left out: any other slot id
  in a system prompt is counted on the wire and reported as
  ``system_slots``, so a run-specific id placed there later cannot be
  undercounted silently.
* **Relations** are the ``DOCUMENT SHAPE`` lines of the plan request.
* **FACT references returned** are ``⟦FACT:hex8.ATTR⟧`` tokens in the cloud's
  replies, before the reintegrator resolves, reports unavailable or prunes
  them; the manifest's ``facts_resolved`` counts only what survived.
* **Bytes** are the UTF-8 length of the sent (or received) fields serialised
  compactly. They measure content, not the HTTP body, which adds the model
  name and parameters. The manifest's ``bytes_in``/``bytes_out`` are zero on
  every pilot run and are not used.
* **Cost** uses the price constants in ``run_evaluation.py``. The private arm
  (plan and drafts) is priced at the uncached rates, since the trace carries
  no cache counts. A run is ``cost_complete`` only when every component was
  recorded; the pilot runs predate INS4, so their adversary tokens are
  missing and their totals are floors.
* **Run-level k/N** counts runs with at least one refusal of any kind. No
  interval is reported: attempts inside a run are not independent.
* **Frozen and attempted.** The refusal counts, ``egress_attempts`` and the
  run-level k/N are over every attempted run, frozen and archived alike: a
  refusal in a run that was then re-run still happened. The per-arm
  observation and cost columns (``by_arm``, which feed Table 3) are over the
  frozen runs only, so they describe the runs Table 1 reports; an archived
  attempt that aborted at the leak gate (0 bytes, 0 slots), was refused at the
  plan call (0 bytes before 2026-10-27; since then its trace holds the request
  M refused, counted as a refused drafter request is), ended there on an
  unusable reply (its trace holds the exchange, counted as an allowed one) or a
  failed call (no trace line), both rows only since that day, or was superseded
  by its re-run would otherwise move the means. The
  attempts' spend is reported beside them, under ``attempts``.

Measured, the nine pilot runs (smoke-q3, baseline/r5/r1 x 3)
------------------------------------------------------------
78 egress attempts, 0 monitor refusals, 0 reintegrator refusals, 0 leak-gate
aborts, so 0/78 attempts and 0/9 runs; trace and manifest agree on every
run. Slots advertised, and on the wire, per run: r1 14 (LOCATION 5, ORG 2,
PERSON 3, PROJECT 4), r5 47, baseline 61; 43 relations on every arm. r1's
replies returned 52-65 FACT references per run, and it pruned 10-15
sentences. The legacy ``smoke-q3`` directory, written before arms
existed, is left out unless ``--include-legacy`` is given, as ``aggregate``
in ``run_evaluation.py`` labels it ``legacy`` rather than pooling it.

Nothing private reaches the output: counts, category names, stage names,
reason rule names and run names only.

Usage
-----
    python scripts/observation_table.py                 # eval/runs + eval/attempts
    python scripts/observation_table.py DIR [DIR ...] [--attempts DIR ...] \
        [--task TASK_ID] --out eval/observation.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "backend" / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from privdeep.models.facts import FACT_RE  # noqa: E402
from privdeep.tier1_local.slot_masker import SLOT_RE  # noqa: E402

from scripts.run_evaluation import ARMS, USD_IN, USD_OUT, _cost  # noqa: E402

__all__ = ["DEFAULT_ATTEMPT_ROOTS", "DEFAULT_ROOTS", "SYSTEM_EXAMPLE_SLOT", "aggregate",
           "discover", "discover_runs", "main", "observe_run"]

DEFAULT_ROOTS = (Path("eval/runs"),)
DEFAULT_ATTEMPT_ROOTS = (Path("eval/attempts"),)
# The one slot id the core's system prompts carry (section_drafter.py, both
# prompts): a constant example that names no referent.
SYSTEM_EXAMPLE_SLOT = "⟦SLOT:PROJECT_a1b2c3d4⟧"
_RUN_FILES = ("egress_trace.jsonl", "manifest.json", "error.txt", "stderr.txt")
_ABORT_FILES = ("error.txt", "stderr.txt")
AUDIT_FILE = "audit_eventlog.jsonl"

# The planner's rendering (tier2_cloud/macro_planner.py `_user_prompt`).
_PLACEHOLDER_LINE = re.compile(r"^- (?P<slot>\S+)\s+\[(?P<cat>[A-Z_]+)\]\s*$", re.M)
_RELATION_LINE = re.compile(r"^- \((?P<s>[^)]*)\) --(?P<p>.+?)--> \((?P<o>[^)]*)\)\s*$", re.M)
# The raised exception as a traceback or a note renders it: "OntologyLeak: <message>",
# the message ending in "(<CATEGORY>)". A `raise OntologyLeak(` source line in the
# same traceback must not count as a second abort.
_ONTOLOGY_LEAK = re.compile(r"OntologyLeak: [^\n]*?(?:\((?P<cat>[A-Z_]+)\))?[ \t]*$", re.M)
_TRANSPORT_FAILURE = re.compile(r"^draft: (CloudError|GatewayError)\b")
# The pipeline's note for a failed plan call (pipeline.py), written since 2026-10-27.
_PLAN_TRANSPORT_FAILURE = re.compile(r"^planning failed: (CloudError|GatewayError)$")
_ARM_IN_NAME = re.compile(r"__(" + "|".join(ARMS) + r")(?=__|$)")


def _rule(reason: str) -> str:
    """A reason's leading rule name. Monitor and reintegrator reasons lead with one
    and carry counts after it; keeping only the name keeps the histogram small."""
    return reason.split(":", 1)[0].strip() or "UNSPECIFIED"


def _compact_bytes(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _read_trace(run_dir: Path) -> list[dict[str, Any]]:
    p = run_dir / "egress_trace.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _arm(manifest: dict[str, Any] | None, run_name: str = "") -> str:
    """The manifest's arm; for a run that died before writing one (a leak-gate
    abort), the arm its directory is named for (`<task>__<arm>[__rep<k>]`); else
    "legacy", never a default arm: see `aggregate` in run_evaluation.py."""
    if manifest is not None:
        return manifest.get("arm") or "legacy"
    m = _ARM_IN_NAME.search(run_name)
    return m.group(1) if m else "legacy"


def _task_matches(run_name: str, task: str | None) -> bool:
    """Run names are `<task>__<arm>[__rep<k>]`, attempts `<run>__attempt<k>`."""
    return task is None or run_name.startswith(f"{task}__")


def discover_runs(roots: list[Path], *, include_legacy: bool = False,
                  task: str | None = None) -> list[Path]:
    """Every directory directly under each root that holds a run artifact.

    A root that is itself a run directory is taken as one. Legacy runs (no arm
    in the manifest) are left out unless asked for; with `task`, only that
    task's runs are kept.
    """
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        cands = [root] if any((root / f).exists() for f in _RUN_FILES) else sorted(
            p for p in root.iterdir() if p.is_dir())
        for d in cands:
            if not any((d / f).exists() for f in _RUN_FILES) or not _task_matches(d.name, task):
                continue
            if not include_legacy and _arm(_read_json(d / "manifest.json")) == "legacy" \
                    and (d / "manifest.json").exists():
                continue
            found.append(d)
    return found


def discover(frozen_roots: list[Path], attempt_roots: list[Path], *,
             include_legacy: bool = False,
             task: str | None = None) -> list[tuple[Path, bool]]:
    """(run directory, is_attempt) over both kinds of root. The flag comes from
    the root a directory was found under; a directory reachable from both is
    taken once, as an attempt, the side whose rows stay out of `by_arm`."""
    attempts = discover_runs(attempt_roots, include_legacy=include_legacy, task=task)
    seen = {d.resolve() for d in attempts}
    frozen = [d for d in discover_runs(frozen_roots, include_legacy=include_legacy, task=task)
              if d.resolve() not in seen]
    return [(d, False) for d in frozen] + [(d, True) for d in attempts]


def _sent(e: dict[str, Any]) -> dict[str, Any]:
    return {"system": e.get("system"), "messages": e.get("messages") or [],
            "tools": e.get("tools")}


def _received(e: dict[str, Any]) -> dict[str, Any]:
    return {"response_text": e.get("response_text"), "structured": e.get("structured")}


def _payload_text(e: dict[str, Any]) -> str:
    """Core-sent content that varies with the run: messages and tools."""
    parts = [str(m.get("content", "")) for m in e.get("messages") or []]
    parts.append(json.dumps(e.get("tools") or [], ensure_ascii=False))
    return "\n".join(parts)


def _system_slots(e: dict[str, Any]) -> set[str]:
    """Slot ids in the system prompt other than the constant example. The drafter's
    system prompt carries ``SYSTEM_EXAMPLE_SLOT``; counted, it put one phantom slot
    on every run. Any other id there is real and crosses like any other."""
    system = e.get("system")
    text = system if isinstance(system, str) else json.dumps(system or "", ensure_ascii=False)
    return {m.group(0) for m in SLOT_RE.finditer(text)} - {SYSTEM_EXAMPLE_SLOT}


def _plan_prompt(trace: list[dict[str, Any]]) -> str:
    for e in trace:
        if e.get("stage") == "plan":
            return "\n".join(str(m.get("content", "")) for m in e.get("messages") or [])
    return ""


def _section(text: str, header: str) -> str:
    """The block of `text` after the line starting with `header`, up to a blank line."""
    i = text.find(header)
    if i < 0:
        return ""
    body = text[text.find("\n", i) + 1:]
    end = body.find("\n\n")
    return body if end < 0 else body[:end]


def _leak_gate_aborts(run_dir: Path, manifest: dict[str, Any] | None) -> list[str]:
    texts = [str(n) for n in (manifest or {}).get("notes", [])]
    for name in _ABORT_FILES:
        p = run_dir / name
        if p.exists():
            texts.append(p.read_text(encoding="utf-8", errors="replace"))
    for t in texts:
        m = _ONTOLOGY_LEAK.search(t)
        if m:
            # A run aborts at most once. Older messages quote the entity, so keep
            # the category and never the text.
            return [f"OntologyLeak ({m.group('cat')})" if m.group("cat") else "OntologyLeak"]
    return []


def _audit(run_dir: Path) -> dict[str, Any] | None:
    p = run_dir / AUDIT_FILE
    if not p.exists():
        return None
    verdicts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    recs = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    # One attempt, one count: a pre-forward record is an attempt only when no
    # outcome record carries its request id (see the module docstring).
    has_outcome = {r.get("request_id") for r in recs
                   if r.get("verdict") != "forwarding" and r.get("request_id")}
    for rec in recs:
        if rec.get("verdict") == "forwarding" and rec.get("request_id") in has_outcome:
            continue
        verdicts[str(rec.get("verdict"))] += 1
        if rec.get("verdict") == "refused":
            reasons[_rule(str(rec.get("reason", "")))] += 1
    return {"records": sum(verdicts.values()), "verdicts": dict(verdicts),
            "refusal_reasons": dict(reasons)}


def _usage(e_list: list[dict[str, Any]]) -> dict[str, int]:
    return {"input_tokens": sum(int(e.get("input_tokens") or 0) for e in e_list),
            "output_tokens": sum(int(e.get("output_tokens") or 0) for e in e_list)}


def _adversary_usage(run_dir: Path, measurement: dict[str, Any] | None) -> dict[str, int] | None:
    rec = _read_json(run_dir / "reconstruction.json")
    if isinstance(rec, dict) and "adversary_tokens_in" in rec:
        return {"input_tokens": int(rec["adversary_tokens_in"]),
                "output_tokens": int(rec["adversary_tokens_out"])}
    adv = ((measurement or {}).get("usage") or {}).get("adversary")
    return dict(adv) if isinstance(adv, dict) else None


def observe_run(run_dir: Path, *, attempt: bool = False) -> dict[str, Any]:
    """One run directory's row. Counts and names only. `attempt` is the tag from
    discovery (`discover`): an archived attempt rather than a frozen run."""
    trace = _read_trace(run_dir)
    manifest = _read_json(run_dir / "manifest.json")
    measurement = _read_json(run_dir / "measurement.json")
    sections = (manifest or {}).get("sections", [])

    monitor = [str(e["refused"]) for e in trace if e.get("refused")]
    reintegrator = [str(s["refused"])[len("reintegrate:"):].strip() for s in sections
                    if str(s.get("refused") or "").startswith("reintegrate:")]
    transport = [_rule(str(s["refused"])[len("draft:"):]) for s in sections
                 if _TRANSPORT_FAILURE.match(str(s.get("refused") or ""))]
    transport += [f"plan: {m.group(1)}" for n in (manifest or {}).get("notes") or []
                  if (m := _PLAN_TRANSPORT_FAILURE.match(str(n)))]
    aborts = _leak_gate_aborts(run_dir, manifest)

    discrepancies: list[str] = []
    eg = (manifest or {}).get("egress")
    if eg is not None:
        if eg.get("attempts") != len(trace):
            discrepancies.append(f"manifest egress.attempts={eg.get('attempts')} but the "
                                 f"trace has {len(trace)} lines")
        if eg.get("refused") != len(monitor):
            discrepancies.append(f"manifest egress.refused={eg.get('refused')} but the "
                                 f"trace has {len(monitor)} refused lines")

    plan_entries = [e for e in trace if e.get("stage") == "plan"]
    draft_entries = [e for e in trace if str(e.get("stage", "")).startswith("draft")]
    prompt = _plan_prompt(trace)
    advertised = Counter(m.group("cat") for m in _PLACEHOLDER_LINE.finditer(
        _section(prompt, "AVAILABLE PLACEHOLDERS")))
    relations = len(_RELATION_LINE.findall(_section(prompt, "DOCUMENT SHAPE")))
    system_slots = {sid for e in trace for sid in _system_slots(e)}
    on_wire = {m.group(0) for e in trace for m in SLOT_RE.finditer(_payload_text(e))} \
        | system_slots
    replies = "\n".join((e.get("response_text") or "")
                        + json.dumps(e.get("structured") or {}, ensure_ascii=False)
                        for e in trace)
    facts = FACT_RE.findall(replies)

    usage: dict[str, dict[str, int] | None] = {
        "plan": _usage(plan_entries),
        "draft": _usage(draft_entries),
        "oracle": ((measurement or {}).get("usage") or {}).get("oracle"),
        "judge": ((measurement or {}).get("usage") or {}).get("judge"),
        "adversary": _adversary_usage(run_dir, measurement),
    }
    usd = {k: (_cost(v) if v is not None else None) for k, v in usage.items()}
    missing = [k for k, v in usd.items() if v is None]

    return {
        "run": run_dir.name,
        "source": run_dir.parent.name,
        "attempt": attempt,
        "arm": _arm(manifest, run_dir.name),
        "has_manifest": manifest is not None,
        "egress_attempts": len(trace),
        "monitor_refusals": [_rule(r) for r in monitor],
        "reintegrator_refusals": [_rule(r) for r in reintegrator],
        "transport_failures": transport,
        "leak_gate_aborts": aborts,
        "relations_dropped_leak": ((manifest or {}).get("extraction") or {}).get(
            "relations_dropped_leak"),
        "refused_any": bool(monitor or reintegrator or aborts),
        "audit": _audit(run_dir),
        "discrepancies": discrepancies,
        "request_bytes": sum(_compact_bytes(_sent(e)) for e in trace),
        "response_bytes": sum(_compact_bytes(_received(e)) for e in trace),
        "slots_advertised": dict(sorted(advertised.items())),
        "slots_advertised_total": sum(advertised.values()),
        "slots_on_wire": len(on_wire),
        "system_slots": len(system_slots),
        "relations": relations,
        "fact_refs_returned": len(facts),
        "fact_refs_returned_distinct": len(set(facts)),
        "facts_resolved": sum(int(s.get("facts_resolved") or 0) for s in sections),
        "facts_unavailable": sum(int(s.get("facts_unavailable") or 0) for s in sections),
        "sentences_pruned": sum(int(s.get("sentences_pruned") or 0) for s in sections),
        "usage": usage,
        "usd": usd,
        "usd_total": sum(v for v in usd.values() if v is not None),
        "cost_complete": not missing,
        "cost_missing": missing,
    }


def _minmax(xs: list[int]) -> dict[str, Any]:
    return {"per_run": xs, "min": min(xs), "max": max(xs), "mean": sum(xs) / len(xs)}


def _spend(rs: list[dict[str, Any]]) -> dict[str, Any]:
    return {"runs": [r["run"] for r in rs],
            "usd_total": sum(r["usd_total"] for r in rs),
            "cost_complete_runs": sum(1 for r in rs if r["cost_complete"])}


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The run-level counts and the per-arm columns. Plain counts, no intervals.

    Refusals, egress attempts and k/N are over every row. `by_arm` is over the
    frozen rows only (`attempt` false); the archived attempts' spend is reported
    apart, under `attempts`.
    """
    attempts = sum(r["egress_attempts"] for r in rows)
    mon = Counter(x for r in rows for x in r["monitor_refusals"])
    rei = Counter(x for r in rows for x in r["reintegrator_refusals"])
    abo = Counter(x for r in rows for x in r["leak_gate_aborts"])
    tra = Counter(x for r in rows for x in r["transport_failures"])
    # The note names the plan call only when one of its failures is counted, so an
    # output with none, the frozen eval/observation.json among them, reads as before.
    tra_note = ("CloudError/GatewayError on a draft, or on the plan call where the reason "
                "says 'plan:'; not a refusal" if any(k.startswith("plan: ") for k in tra)
                else "CloudError/GatewayError on a draft; not a refusal")
    drops = [r for r in rows if r["relations_dropped_leak"] is not None]
    refusals = {
        "monitor": {"count": sum(mon.values()), "reasons": dict(mon)},
        "reintegrator": {"count": sum(rei.values()), "reasons": dict(rei)},
        "leak_gate_aborts": {"count": sum(abo.values()), "reasons": dict(abo)},
        "transport_failures": {"count": sum(tra.values()), "reasons": dict(tra),
                               "note": tra_note},
    }
    frozen = [r for r in rows if not r["attempt"]]
    archived = [r for r in rows if r["attempt"]]
    by_arm: dict[str, Any] = {}
    for arm in sorted({r["arm"] for r in frozen}):
        rs = [r for r in frozen if r["arm"] == arm]
        cats = sorted({c for r in rs for c in r["slots_advertised"]})
        by_arm[arm] = {
            "runs": [r["run"] for r in rs],
            "egress_attempts": sum(r["egress_attempts"] for r in rs),
            "request_bytes": _minmax([r["request_bytes"] for r in rs]),
            "response_bytes": _minmax([r["response_bytes"] for r in rs]),
            "slots_advertised_total": _minmax([r["slots_advertised_total"] for r in rs]),
            "slots_advertised_by_category": {
                c: _minmax([r["slots_advertised"].get(c, 0) for r in rs]) for c in cats},
            "slots_on_wire": _minmax([r["slots_on_wire"] for r in rs]),
            "system_slots": _minmax([r["system_slots"] for r in rs]),
            "relations": _minmax([r["relations"] for r in rs]),
            "fact_refs_returned": _minmax([r["fact_refs_returned"] for r in rs]),
            "sentences_pruned": _minmax([r["sentences_pruned"] for r in rs]),
            "tokens": {
                stage: {io: _minmax([int((r["usage"][stage] or {}).get(io, 0)) for r in rs])
                        for io in ("input_tokens", "output_tokens")}
                for stage in ("plan", "draft", "adversary")},
            "adversary_tokens_recorded": sum(1 for r in rs if r["usage"]["adversary"] is not None),
            "usd_total": {"per_run": [r["usd_total"] for r in rs],
                          "mean": sum(r["usd_total"] for r in rs) / len(rs)},
            "cost_complete_runs": sum(1 for r in rs if r["cost_complete"]),
        }
    return {
        "runs": len(rows),
        "frozen_runs": len(frozen),
        "archived_attempts": len(archived),
        "egress_attempts": attempts,
        "refused_attempts": sum(len(r["monitor_refusals"]) for r in rows),
        "runs_with_any_refusal": sum(1 for r in rows if r["refused_any"]),
        "refusals": refusals,
        "leak_gate_drops": {
            "relations": sum(r["relations_dropped_leak"] for r in drops),
            "runs_with_drops": sum(1 for r in drops if r["relations_dropped_leak"]),
            "runs_recorded": len(drops),
            "note": "relations the W2 gate dropped at extraction and never sent; a count "
                    "from manifest.extraction, None (not recorded) before 2026-09-27",
        },
        "audit_logs_read": sum(1 for r in rows if r["audit"] is not None),
        "discrepancies": {r["run"]: r["discrepancies"] for r in rows if r["discrepancies"]},
        "prices_usd_per_token": {"input": USD_IN, "output": USD_OUT},
        "by_arm": by_arm,
        "attempts": {
            **_spend(archived),
            "by_arm": {arm: _spend([r for r in archived if r["arm"] == arm])
                       for arm in sorted({r["arm"] for r in archived})},
            "note": "archived attempts: counted in the refusals, egress attempts and k/N "
                    "above, not in by_arm",
        },
    }


def _table(summary: dict[str, Any]) -> str:
    s = summary
    lines = [
        f"runs {s['runs']} ({s['frozen_runs']} frozen, {s['archived_attempts']} archived "
        f"attempts), egress attempts {s['egress_attempts']}",
        f"monitor refusals {s['refused_attempts']}/{s['egress_attempts']} attempts; "
        f"runs with any refusal {s['runs_with_any_refusal']}/{s['runs']}",
    ]
    for kind, v in s["refusals"].items():
        lines.append(f"  {kind:<20} {v['count']:>3}  {v['reasons'] or ''}")
    ld = s["leak_gate_drops"]
    lines.append(f"leak-gate drops: {ld['relations']} relation(s) in {ld['runs_with_drops']} "
                 f"run(s), recorded in {ld['runs_recorded']}/{s['runs']}")
    lines.append(f"audit logs read: {s['audit_logs_read']}/{s['runs']}")
    if s["discrepancies"]:
        lines.append(f"DISCREPANCIES: {s['discrepancies']}")
    lines.append("")
    lines.append("per arm, frozen runs only:")
    hdr = (f"{'arm':<9} {'runs':>4} {'req B':>8} {'resp B':>8} {'slots':>6} {'wire':>5} "
           f"{'rels':>5} {'FACT':>5} {'pruned':>6} {'plan tok':>12} {'draft tok':>13} "
           f"{'$/run':>7}")
    lines.append(hdr)
    for arm, a in s["by_arm"].items():
        plan = {io: v["mean"] for io, v in a["tokens"]["plan"].items()}
        draft = {io: v["mean"] for io, v in a["tokens"]["draft"].items()}
        lines.append(
            f"{arm:<9} {len(a['runs']):>4} {a['request_bytes']['mean']:>8.0f} "
            f"{a['response_bytes']['mean']:>8.0f} {a['slots_advertised_total']['mean']:>6.1f} "
            f"{a['slots_on_wire']['mean']:>5.1f} {a['relations']['mean']:>5.1f} "
            f"{a['fact_refs_returned']['mean']:>5.1f} {a['sentences_pruned']['mean']:>6.1f} "
            f"{plan['input_tokens']:>6.0f}/{plan['output_tokens']:<5.0f} "
            f"{draft['input_tokens']:>6.0f}/{draft['output_tokens']:<6.0f} "
            f"{a['usd_total']['mean']:>7.3f}")
        cats = ", ".join(f"{c} {v['min']}" + (f"-{v['max']}" if v["max"] != v["min"] else "")
                         for c, v in a["slots_advertised_by_category"].items())
        lines.append(f"{'':<9} slots advertised: {cats}")
        if a["cost_complete_runs"] < len(a["runs"]):
            lines.append(f"{'':<9} cost is a floor on {len(a['runs']) - a['cost_complete_runs']} "
                         "run(s): adversary tokens not recorded (pre-INS4)")
        if a["system_slots"]["max"]:
            lines.append(f"{'':<9} WARNING: system prompts carry up to {a['system_slots']['max']} "
                         "slot id(s) other than the constant example")
    at = s["attempts"]
    if at["runs"]:
        floor = " (a floor)" if at["cost_complete_runs"] < len(at["runs"]) else ""
        lines.append(f"archived attempts, not in the per-arm columns: {len(at['runs'])} run(s), "
                     f"${at['usd_total']:.3f}{floor}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("roots", nargs="*", type=Path,
                    help="frozen run roots or run directories (default: eval/runs)")
    ap.add_argument("--attempts", nargs="+", type=Path, default=None, metavar="DIR",
                    help="archived-attempt roots or run directories (default: eval/attempts "
                         "when no root at all is given, else none)")
    ap.add_argument("--task", default=None,
                    help="keep only this task's runs (`<task>__<arm>...`)")
    ap.add_argument("--out", type=Path, default=None, help="write the JSON here")
    ap.add_argument("--include-legacy", action="store_true",
                    help="include runs whose manifest names no arm")
    args = ap.parse_args(argv)
    defaults = not args.roots and args.attempts is None
    roots = args.roots or [p if p.is_absolute() else _REPO / p for p in DEFAULT_ROOTS]
    attempt_roots = args.attempts or (
        [p if p.is_absolute() else _REPO / p for p in DEFAULT_ATTEMPT_ROOTS] if defaults else [])
    # An attempts root given as frozen would put its runs into by_arm, the pooling
    # the two kinds of root exist to prevent.
    misplaced = [str(r) for r in roots
                 if "attempts" in (r.resolve().name, r.resolve().parent.name)]
    if misplaced:
        raise SystemExit(f"{misplaced} look like archived attempts; pass them with --attempts")
    runs = discover(roots, attempt_roots, include_legacy=args.include_legacy, task=args.task)
    if not runs:
        raise SystemExit(f"no run directories under {[str(r) for r in roots + attempt_roots]}")
    rows = [observe_run(d, attempt=is_attempt) for d, is_attempt in runs]
    report = {
        "instrument": "scripts/observation_table.py",
        "roots": [str(r) for r in roots],
        "attempt_roots": [str(r) for r in attempt_roots],
        "task": args.task,
        "summary": aggregate(rows),
        "runs": rows,
    }
    print(_table(report["summary"]))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        print(f"\nwrote {args.out}")
    return report


if __name__ == "__main__":
    main()
