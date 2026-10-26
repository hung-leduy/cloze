#!/usr/bin/env python3
"""Would the monitor refuse the planner request? Per collection and arm, offline, for free.

Why this exists
---------------
Track L's pilot (scope §12.5) ran the r5 arm on tab-L0 and the reference
monitor refused the planner request: ``RAW_CONTEXT_CONTAINMENT: 1 shingle
hit(s) >= 1`` (the attempt's manifest notes). The abstract payload rendered
into the planner prompt therefore carried a contiguous run of five to eight
words of the collection's text, and the free-text relation fields the local
SLM writes are the only part of that prompt that can. A refused request costs
nothing and the pipeline fails closed, but a collection whose planner request
is refused yields no report, and the batch budget is better spent knowing that
beforehand. This instrument answers, with no cloud call and no container: for
each collection and arm, would the planner request be refused, how many
shingle hits would it carry, and in which field of the prompt.

What it does
------------
Per collection, from one saved local extraction (``tier1_probe.py extract``,
read through ``load_extractions`` as the pipeline's reuse path reads it):

1. the core's steps, with the pipeline's own functions in ``run_pipeline``'s
   order: ``drop_corpus_leaking_relations``, the session table
   (``_session_table``), ``SlotMasker.mask`` per document,
   ``build_abstract_payload`` and ``_merge_payloads``, and on the r1 arm
   ``build_fact_store`` inside the same collision check;
2. the planner request, byte for byte: ``MacroPlanner.plan`` is called on a
   ``CloudClient`` whose transport records the request and answers with a
   refusal, so the body is what ``CloudClient.messages`` serialises and
   nothing is sent anywhere;
3. the monitor's verdict: the collection's containment filter is built as the
   core builds it (``containment.build_filter``), and the gateway's own module
   (``gateway/main.py``) is imported and run in-process through its two
   endpoints, ``POST /containment/seal`` with the filter's wire form and then
   ``POST /inspect`` with the recorded body. ``/inspect`` runs the whole chain
   (canaries, entropy, regex screen, containment over the whole-body, per-path
   and key streams) and, as a dry run, does not advance the carry; the planner
   request is the first after the seal, so the carry is empty on the live path
   too, and the verdict is the one the live path gives;
4. the attribution, which the verdict lacks: the monitor stops at the first
   hit, so its reason always says 1. Here every 5-8-gram window of the request
   is counted against the sealed filter (``ShingleFilter.inspect_tokens`` with
   ``collect=True``, for its count only), per JSON path of the body and,
   inside the prompt, per field kind: ``goal``, ``relations[].subject_type``,
   ``relations[].predicate``, ``relations[].object_type``, ``slots``, or
   ``template`` (the planner's own wording, the DOCUMENT STATS line and the r1
   ATTRIBUTES line). A window spanning two kinds is counted as straddling
   them. Each relation field is also inspected alone, so the output says how
   many relation fields hold a corpus run by themselves.

Privacy
-------
The collections under ``eval/real/corpora/tab-L*`` hold court-judgment text
(TAB, scope §12.2). The script reads them and the extractions in memory only.
The JSON and the table carry counts, hashes, field names, JSON paths and the
monitor's reason strings, which by their contracts hold counts, lengths and
rule names and never matched text; never a document string, an entity, a
relation field or a shingle. The pilot's trace, report and entities are never
read; its ``manifest.json`` (counts) is, for ``--self-check``.

Divergences from a live run, stated
-----------------------------------
* The salts are fixed instrument salts (session and filter), not the
  deployment's secrets: the slot ids differ from a live run's; the hit counts
  do not (the filter's false-positive rate is 1e-7 either way).
* The pipeline re-salts once on a slot collision with fresh random bytes; here
  the second salt is derived from the first, so a run is reproducible.
* The request is serialised by this interpreter's httpx and a live one by the
  container's; the monitor decodes the JSON and inspects the decoded strings,
  so the serialisation cannot move the verdict.
* A live session registers five canaries; none is registered here. The
  planner prompt does not carry the extractor's context block and
  ``load_extractions`` refuses an extraction holding a canary-prefixed
  string, so the canary screen cannot fire on this request either way.
* Only the planner request is simulated: the drafter requests depend on the
  plan the cloud returns, which does not exist offline.
* The pilot's own extraction was not saved outside the container
  (``extraction_source: extracted``), so a simulation of tab-L0 runs on
  another extraction of the same documents, and the self-check says so.

Usage
-----
    $VPY scripts/real_l_refusal_sim.py                 # tab-L0..L6 that have an extraction
    $VPY scripts/real_l_refusal_sim.py --collections tab-L1 tab-L2 \\
        --extractions-dir eval/real/out/extractions --out eval/real/out/refusal_sim.json
    $VPY scripts/real_l_refusal_sim.py --self-check    # tab-L0 against the pilot manifest

``$VPY`` is the venv interpreter (``.venv/bin/python``):
the gateway module needs FastAPI. The extractions are read from
``<extractions-dir>/<collection>/*.json`` as ``tier1_probe.py extract
--out-dir`` writes them.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import logging
import re
import sys
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "backend" / "src", _REPO / "gateway"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from privdeep.ingest import SUFFIXES, load  # noqa: E402
from privdeep.models.document import Document  # noqa: E402
from privdeep.pipeline import _merge_payloads, _session_table  # noqa: E402
from privdeep.tier1_local.containment import build_filter  # noqa: E402
from privdeep.tier1_local.extraction_io import ExtractionReuseError, load_extractions  # noqa: E402
from privdeep.tier1_local.fact_store import build_fact_store  # noqa: E402
from privdeep.tier1_local.ontology_extractor import (  # noqa: E402
    Extraction,
    OntologyLeak,
    assert_no_corpus_leak,
    drop_corpus_leaking_relations,
)
from privdeep.tier1_local.slot_masker import SlotCollisionError, SlotMasker  # noqa: E402
from privdeep.tier2_cloud.abstract_payload import (  # noqa: E402
    AbstractPayload,
    build_abstract_payload,
)
from privdeep.tier2_cloud.cloud_client import CloudClient, EgressRefused  # noqa: E402
from privdeep.tier2_cloud.macro_planner import MacroPlanner  # noqa: E402
from privdeep.tier2_cloud.tracing import TracingCloudClient  # noqa: E402

from scripts import run_evaluation as R  # noqa: E402
from shared.shingle_filter import ShingleFilter, tokenize  # noqa: E402

try:
    import main as monitor  # gateway/main.py: the reference monitor itself
    from fastapi.testclient import TestClient
except ImportError as _exc:  # pragma: no cover - the venv has both
    raise SystemExit(
        f"the reference monitor cannot be imported ({_exc}); run with the venv interpreter "
        ".venv/bin/python, which has FastAPI") from _exc

__all__ = ["ARMS", "PROMPT_FIELD_KINDS", "build_planner_request", "extraction_files",
           "inspect_request", "labelled_prompt_tokens", "load_docs", "load_extraction", "main",
           "monitor_session", "run", "safe_reason", "self_check", "simulate_collection",
           "summary"]

ARMS = R.ARMS
DEFAULT_CORPORA = _REPO / "eval" / "real" / "corpora"
DEFAULT_COLLECTIONS = tuple(f"tab-L{i}" for i in range(7))
DEFAULT_EXTRACTIONS_DIR = _REPO / "eval" / "real" / "out" / "extractions"
DEFAULT_OUT = _REPO / "eval" / "real" / "out" / "refusal_sim.json"
DEFAULT_TASKS = (_REPO / "eval" / "real" / "tasks_l_dev.json",
                 _REPO / "eval" / "real" / "tasks_l.json")
PILOT_MANIFEST = (_REPO / "eval" / "pilot" / "real-l" / "attempts" / "tab-L0__r5__attempt1"
                  / "manifest.json")
SELF_CHECK_COLLECTION, SELF_CHECK_ARM = "tab-L0", "r5"
# The canary prefix `load_extractions` screens with: the deployed injector's.
CANARY_PREFIX = "CANARY_PRIVDEEP_"
# Instrument salts, not secrets: the slot ids and the filter built here protect
# nothing, and fixed salts make every count reproducible from the inputs.
SESSION_SALT = b"privdeep-real-l-refusal-sim-session"
FILTER_SALT = b"privdeep-real-l-refusal-sim-filter"
# The deployed containment parameters (docker-compose.yml defaults; the pilot
# manifest's containment block), passed explicitly so the environment cannot
# move them, on the core side and on the monitor side alike.
N_MIN, N_MAX, HIT_THRESHOLD = 5, 8, 1
# The model the pipeline asks for (the pilot manifest's cloud_model_requested
# and CloudClient's default); a string value in the body, so inspected too.
CLOUD_MODEL = "claude-sonnet-5"
PROMPT_FIELD_KINDS = ("goal", "relations[].subject_type", "relations[].predicate",
                      "relations[].object_type", "slots", "template")
_RELATION_KINDS = ("subject_type", "predicate", "object_type")
_CAPTURED = "SIMULATION_CAPTURED: the request was recorded, not sent"
# The monitor's reason codes. Each verdict string is content-free by its
# module's contract (counts, lengths, rule names); any other code is cut to
# the code alone before it is recorded.
_REASON_CODES = frozenset({"RAW_CONTEXT_CONTAINMENT", "SECRET_PATTERN", "COVERT_CHANNEL_DETECTED",
                           "CANARY_TRIPPED", "CONTAINMENT_FILTER_UNSEALED", "INSPECTION_ERROR"})
_CONTAINMENT_RE = re.compile(r"RAW_CONTEXT_CONTAINMENT: (\d+) shingle hit\(s\) >= (\d+)")
_SENTINEL = "zqsim{:05d}zq"
_SENTINEL_RE = re.compile(r"zqsim(\d{5})zq")
_MONITOR_STATE = ("SHINGLE_HMAC_SALT", "SHINGLE_N_MIN", "SHINGLE_N_MAX", "SHINGLE_HIT_THRESHOLD",
                  "STRICT_FAIL_CLOSED", "_shingle", "_carry", "_carry_last")


def _rel(p: Path) -> str:
    """Repository-relative when inside it, so the output names no checkout."""
    p = p.resolve()
    try:
        return str(p.relative_to(_REPO))
    except ValueError:
        return p.name


# ----------------------------------------------------------------------- inputs


def load_docs(corpus: Path) -> list[Document]:
    """As ``privdeep.pipeline._main`` loads ``/corpus``: the supported files, sorted."""
    files = sorted(p for p in corpus.iterdir() if p.suffix.lower() in SUFFIXES)
    if not files:
        raise SystemExit(f"no supported documents in {corpus}")
    return [load(p) for p in files]


def extraction_files(root: Path, collection: str) -> list[Path]:
    """``root/<collection>/*.json`` as ``tier1_probe.py extract --out-dir`` writes them,
    without its extract_manifest.json, one file per distinct content."""
    d = root / collection
    seen: dict[str, Path] = {}
    for f in (sorted(d.glob("*.json")) if d.is_dir() else ()):
        if f.name != "extract_manifest.json":
            seen.setdefault(hashlib.sha256(f.read_bytes()).hexdigest(), f)
    return sorted(seen.values(), key=lambda p: p.name)


@dataclass
class LoadedExtraction:
    file: str                        # the file's name; never its content
    sha256: str
    extractions: list[Extraction]    # in corpus document order
    counters: dict[str, int]         # summed per document, as run_pipeline fills the manifest
    corpus_gate_drops: int           # drop_corpus_leaking_relations on load; 0 on the reuse path
    probe: dict[str, Any]            # the probe block's counts and model name


def load_extraction(path: Path, docs: Sequence[Document]) -> LoadedExtraction:
    """One saved extraction, read as ``run_pipeline`` reads a reused one.

    ``load_extractions`` refuses another corpus, a canary-prefixed string, an
    entity absent from the text and a relation carrying an entity string (the
    strict corpus-wide W2 gate); then, as in the pipeline, the dropping form of
    the gate runs and its postcondition is asserted.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    exs = load_extractions(data, docs, canary_prefix=CANARY_PREFIX)
    drops = drop_corpus_leaking_relations(exs)
    assert_no_corpus_leak(exs)
    counters: dict[str, int] = {}
    for ex in exs:
        for k, n in ex.counters().items():
            counters[k] = counters.get(k, 0) + n
    probe = data.get("probe") or {}
    return LoadedExtraction(path.name, hashlib.sha256(path.read_bytes()).hexdigest(), exs,
                            counters, drops,
                            {k: probe.get(k) for k in ("model", "relations_dropped_leak",
                                                       "documents_total", "seconds")})


# ---------------------------------------------------------------- the request


@dataclass
class PlannerRequest:
    arm: str
    payload: AbstractPayload
    raw: bytes                 # the body CloudClient.messages serialised; stays in memory
    slots_issued: int
    surface_forms: int
    facts_total: int | None


class _Recorder:
    """The transport under the CloudClient: records the one request and refuses it."""

    def __init__(self) -> None:
        self.raw: bytes | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.raw = request.content
        return httpx.Response(403, json={"allowed": False, "reason": _CAPTURED})


async def _record_planner_request(payload: AbstractPayload, goal: str, model: str) -> bytes:
    rec = _Recorder()
    async with CloudClient("http://reference-monitor.simulated", model,
                           transport=httpx.MockTransport(rec), max_retries=1) as cloud:
        tracer = TracingCloudClient(cloud)
        tracer.label("plan")
        try:
            await MacroPlanner(tracer).plan(payload, goal)
        except EgressRefused as exc:
            if exc.reason != _CAPTURED:
                raise
    if rec.raw is None:  # pragma: no cover - the planner always sends one request
        raise RuntimeError("the planner sent no request")
    return rec.raw


def build_planner_request(docs: Sequence[Document], extractions: Sequence[Extraction], arm: str,
                          goal: str, *, session_salt: bytes = SESSION_SALT,
                          model: str = CLOUD_MODEL) -> PlannerRequest:
    """The planner request as ``run_pipeline`` sends it for `arm` from these extractions.

    The same functions in the same order; the one difference is the salt (see
    the module docstring).
    """
    all_entities = [e for ex in extractions for e in ex.entities]
    normalise = arm != "baseline"
    facts = arm == "r1"
    salt = session_salt
    for attempt in (1, 2):
        try:
            table = _session_table(salt, all_entities, normalise=normalise)
            store = build_fact_store(docs, table) if facts else None
            break
        except SlotCollisionError:
            if attempt == 2:
                raise
            salt = hashlib.sha256(salt).digest()
    masker = SlotMasker(salt, normalise=normalise)
    payloads = [
        build_abstract_payload(d.doc_id, ex, masker.mask(d, ex.entities), n_cells=len(d.cells),
                               n_blocks=len(d.blocks), n_chars=len(d.text), facts=facts)
        for d, ex in zip(docs, extractions, strict=True)]
    payload = _merge_payloads(payloads)
    raw = asyncio.run(_record_planner_request(payload, goal, model))
    return PlannerRequest(arm, payload, raw, len(table), len(set(all_entities)),
                          len(store) if store is not None else None)


# ---------------------------------------------------------------- the monitor


@contextmanager
def monitor_session(f: ShingleFilter) -> Iterator[tuple[TestClient, dict[str, Any]]]:
    """The reference monitor in-process, sealed with `f` through its own endpoint.

    Its policy globals are set to the deployed values for the duration and
    restored after, as its own tests set them; sealing clears the carry, as it
    does at the start of a live session. Its logger is quietened: its refusal
    lines would only repeat the table's reason strings.
    """
    saved = {k: getattr(monitor, k) for k in _MONITOR_STATE}
    level = monitor.log.level
    try:
        monitor.SHINGLE_HMAC_SALT = FILTER_SALT
        monitor.SHINGLE_N_MIN, monitor.SHINGLE_N_MAX = N_MIN, N_MAX
        monitor.SHINGLE_HIT_THRESHOLD = HIT_THRESHOLD
        monitor.STRICT_FAIL_CLOSED = True
        monitor._shingle = None
        monitor.log.setLevel(logging.ERROR)
        client = TestClient(monitor.app)
        r = client.post("/containment/seal", content=f.to_wire(),
                        headers={"content-type": "application/octet-stream"})
        seal = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code != 200 or not seal.get("sealed") or seal.get("n_added") != f.bloom.n_added:
            raise RuntimeError(f"the monitor did not confirm the seal: HTTP {r.status_code} "
                               f"{seal.get('reason')}")
        yield client, seal
    finally:
        for k, v in saved.items():
            setattr(monitor, k, v)
        monitor.log.setLevel(level)


def safe_reason(reason: str | None) -> str | None:
    """The monitor's reason as recorded: whole for a known code, else the code alone."""
    if reason is None:
        return None
    code = reason.split(":", 1)[0].strip()
    return reason if code in _REASON_CODES else code


def _count_hits(f: ShingleFilter, tokens: Sequence[str]) -> int:
    """Every window in the filter, not only the first: the count, never the shingles."""
    return f.inspect_tokens(list(tokens), collect=True).hit_count


def _window_hits(f: ShingleFilter, tokens: Sequence[str]) -> Iterator[tuple[int, int]]:
    """(start, length) of every window of `tokens` in the sealed filter.

    The filter's own windows (``ShingleFilter._shingles``) looked up in its
    Bloom filter, with their positions, which ``inspect_tokens`` does not
    return; the caller checks the total against ``inspect_tokens``.
    """
    bloom = f.bloom
    for n in range(f.n_min, f.n_max + 1):
        for i in range(len(tokens) - n + 1):
            if " ".join(tokens[i:i + n]).encode("utf-8") in bloom:
                yield i, n


def labelled_prompt_tokens(payload: AbstractPayload, goal: str) -> tuple[list[str], list[str]]:
    """The rendered planner prompt's tokens, each labelled with the field it came from.

    ``MacroPlanner._user_prompt`` renders the prompt a second time with every
    field value replaced by a one-token sentinel; expanding each sentinel to
    its field's tokens must reproduce the real prompt's tokens exactly, or the
    attribution is refused. Nothing here re-implements the rendering, and
    every token the planner writes itself is ``template``.
    """
    fields: list[tuple[str, str]] = [("goal", goal)]

    def sentinel(kind: str, value: str) -> str:
        fields.append((kind, value))
        return _SENTINEL.format(len(fields) - 1)

    shadow = dataclasses.replace(
        payload,
        relations=tuple(tuple(sentinel(f"relations[].{k}", v)
                              for k, v in zip(_RELATION_KINDS, rel, strict=True))
                        for rel in payload.relations),
        slots=tuple((sentinel("slots", sid), sentinel("slots", cat)) for sid, cat in payload.slots),
    )
    tokens: list[str] = []
    labels: list[str] = []
    for tok in tokenize(MacroPlanner._user_prompt(shadow, _SENTINEL.format(0))):
        m = _SENTINEL_RE.fullmatch(tok)
        if m:
            kind, value = fields[int(m.group(1))]
            vt = tokenize(value)
            tokens += vt
            labels += [kind] * len(vt)
        else:
            tokens.append(tok)
            labels.append("template")
    if tokens != tokenize(MacroPlanner._user_prompt(payload, goal)):
        raise RuntimeError("the prompt attribution does not reproduce the rendered planner "
                           "prompt; MacroPlanner._user_prompt changed")
    return tokens, labels


def inspect_request(client: TestClient, f: ShingleFilter, req: PlannerRequest, goal: str
                    ) -> dict[str, Any]:
    """The monitor's verdict on `req`, then the exhaustive counts behind it."""
    r = client.post("/inspect", content=req.raw, headers={"content-type": "application/json"})
    verdict = r.json()
    refused = not verdict.get("allowed", False)
    reason = safe_reason(str(verdict.get("reason"))) if refused else None
    m = _CONTAINMENT_RE.fullmatch(reason or "")

    # The streams `_containment` inspects, from the gateway's own walkers, each
    # counted exhaustively. The per-path streams have no carry on the first
    # request after a seal, so a path's count is its leaf's count.
    _text, parsed = monitor._decoded_text(req.raw)
    leaves = list(monitor._value_paths(parsed))
    whole = _count_hits(f, tokenize("\n".join(leaf for _, leaf in leaves)))
    by_path: Counter[str] = Counter()
    for path, leaf in leaves:
        h = _count_hits(f, tokenize(leaf))
        if h:
            by_path[path] += h
    key_hits = _count_hits(f, tokenize("\n".join(monitor._key_strings(parsed))))

    # Inside the prompt: which field each window falls in.
    content = parsed["messages"][0]["content"]
    if content != MacroPlanner._user_prompt(req.payload, goal):
        raise RuntimeError("the recorded request does not carry the rendered planner prompt")
    tokens, labels = labelled_prompt_tokens(req.payload, goal)
    by_kind: Counter[str] = Counter()
    straddling: Counter[str] = Counter()
    n_prompt = 0
    for i, n in _window_hits(f, tokens):
        n_prompt += 1
        kinds = sorted(set(labels[i:i + n]))
        if len(kinds) == 1:
            by_kind[kinds[0]] += 1
        else:
            straddling["+".join(kinds)] += 1
    if n_prompt != _count_hits(f, tokens):  # pragma: no cover - the same lookups
        raise RuntimeError("the window count disagrees with inspect_tokens")

    # Each relation field alone: does it hold a corpus run by itself?
    fields_with_run: Counter[str] = Counter()
    relations_with_run = fields_ge_n_min = max_field_tokens = 0
    for rel in req.payload.relations:
        hit_any = False
        for kind, value in zip(_RELATION_KINDS, rel, strict=True):
            vt = tokenize(value)
            max_field_tokens = max(max_field_tokens, len(vt))
            fields_ge_n_min += len(vt) >= f.n_min
            if vt and _count_hits(f, vt):
                fields_with_run[f"relations[].{kind}"] += 1
                hit_any = True
        relations_with_run += hit_any

    return {
        "refused": refused,
        "reason": reason,
        "reason_code": reason.split(":", 1)[0] if reason else None,
        "monitor_hits": int(m.group(1)) if m else 0,
        "request_bytes": len(req.raw),
        "hits": {"whole_stream": whole, "by_path": dict(sorted(by_path.items())),
                 "straddling_paths": whole - sum(by_path.values()), "keys": key_hits},
        "prompt": {"tokens": len(tokens), "hits": n_prompt,
                   "by_field_kind": dict(sorted(by_kind.items())),
                   "straddling_field_kinds": dict(sorted(straddling.items())),
                   "goal_alone": _count_hits(f, tokenize(goal))},
        "relations": {"distinct": len(req.payload.relations),
                      "fields": 3 * len(req.payload.relations),
                      "fields_with_run": sum(fields_with_run.values()),
                      "fields_with_run_by_kind": dict(sorted(fields_with_run.items())),
                      "relations_with_run": relations_with_run,
                      "fields_with_at_least_n_min_tokens": fields_ge_n_min,
                      "max_field_tokens": max_field_tokens},
        "slots": {"advertised": len(req.payload.slots),
                  "by_category": dict(sorted(Counter(c for _, c in req.payload.slots).items()))},
        "slots_issued": req.slots_issued,
        "surface_forms": req.surface_forms,
        "facts_total": req.facts_total,
        "stats": req.payload.wire_stats(),
    }


# ------------------------------------------------------------- per collection


def simulate_collection(collection: str, corpus: Path, goal: str, files: Sequence[Path], *,
                        arms: Sequence[str] = ARMS) -> dict[str, Any]:
    docs = load_docs(corpus)
    f = build_filter(docs, salt=FILTER_SALT, n_min=N_MIN, n_max=N_MAX,
                     hit_threshold=HIT_THRESHOLD)
    out: dict[str, Any] = {
        "collection": collection,
        "corpus": _rel(corpus),
        "documents": [{"doc_id": d.doc_id, "kind": str(d.kind), "chars": len(d.text),
                       "cells": len(d.cells), "blocks": len(d.blocks)} for d in docs],
        "filter": {"shingles": f.bloom.n_added, "m_bits": f.bloom.m_bits, "k": f.bloom.k,
                   "n_min": f.n_min, "n_max": f.n_max, "hit_threshold": f.hit_threshold,
                   "fp_est": f.bloom.estimated_fp_rate()},
        "goal_sha256": hashlib.sha256(goal.encode("utf-8")).hexdigest(),
        "goal_tokens": len(tokenize(goal)),
        "goal_hits_alone": _count_hits(f, tokenize(goal)),
        "extractions": [],
        "refused_files": [],
    }
    with monitor_session(f) as (client, seal):
        out["filter"]["sealed"] = seal
        for path in files:
            try:
                lx = load_extraction(path, docs)
            except ExtractionReuseError as exc:
                out["refused_files"].append({"file": path.name, "reason": "ExtractionReuseError",
                                             "detail": str(exc)})
                continue
            except OntologyLeak as exc:
                cat = re.search(r"\(([A-Z]+)\)\s*$", str(exc))
                out["refused_files"].append({"file": path.name, "reason": "OntologyLeak",
                                             "category": cat.group(1) if cat else "unknown"})
                continue
            entry: dict[str, Any] = {
                "file": lx.file, "sha256": lx.sha256,
                "extractor": {**lx.counters, "corpus_gate_drops_on_load": lx.corpus_gate_drops,
                              "probe": lx.probe},
                "arms": {}}
            for arm in arms:
                req = build_planner_request(docs, lx.extractions, arm, goal)
                entry["arms"][arm] = inspect_request(client, f, req, goal)
            out["extractions"].append(entry)
    return out


# ---------------------------------------------------------------- self-check


def self_check(collections: dict[str, Any], manifest_path: Path, *,
               collection: str = SELF_CHECK_COLLECTION, arm: str = SELF_CHECK_ARM
               ) -> dict[str, Any]:
    """Does the simulation give the pilot's verdict? Read from the pilot manifest's
    counts, never from its trace. 'pass' needs the same verdict and reason on every
    extraction simulated, and a filter of the pilot's size (the same documents)."""
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    notes = [n for n in m.get("notes") or [] if n.startswith(R._PLAN_REFUSED)]
    pilot_reason = notes[0].split(": ", 1)[1] if notes else None
    out: dict[str, Any] = {"collection": collection, "arm": arm,
                           "pilot_manifest": _rel(manifest_path),
                           "pilot_refused": bool(notes), "pilot_reason": pilot_reason}
    coll = collections.get(collection)
    if coll is None or not coll["extractions"]:
        out.update(status="not run", reason=f"no extraction simulated for {collection}")
        return out
    pc = m.get("containment") or {}
    out["filter_matches_pilot"] = {k: coll["filter"].get(k) == pc.get(k)
                                   for k in ("shingles", "m_bits", "k", "n_min", "n_max")}
    pe = m.get("extraction") or {}
    rows = []
    for ex in coll["extractions"]:
        a = ex["arms"][arm]
        counts = {k: ex["extractor"].get(k) == pe.get(k)
                  for k in ("entities", "relations", "relations_dropped_leak")}
        rows.append({"file": ex["file"], "simulated_refused": a["refused"],
                     "simulated_reason": a["reason"],
                     "refusal_reproduced": a["refused"] == bool(notes)
                     and (a["reason"] == pilot_reason if notes else True),
                     "extraction_counts_match_pilot": counts,
                     "same_extraction_as_pilot": all(counts.values()),
                     "slots_issued_match_pilot": a["slots_issued"] == m.get("slots_issued")})
    out["extractions"] = rows
    reproduced = all(r["refusal_reproduced"] for r in rows)
    same = any(r["same_extraction_as_pilot"] for r in rows)
    out["status"] = ("pass" if reproduced and all(out["filter_matches_pilot"].values())
                     else "fail")
    out["note"] = ("the pilot's own extraction counts" if same else
                   "a different extraction of the same documents: the pilot's own was not "
                   "saved outside the container, so this reproduces the verdict under another "
                   "draw of the extractor, not the pilot's request byte for byte")
    return out


# ----------------------------------------------------------------------- run


def _goals(tasks_files: Sequence[Path]) -> dict[str, R.Task]:
    out: dict[str, R.Task] = {}
    for p in tasks_files:
        if p.is_file():
            for t in R.load_tasks(p):
                out.setdefault(t.id, t)
    return out


def run(collections: Sequence[str], *, corpora_root: Path = DEFAULT_CORPORA,
        extractions_dir: Path = DEFAULT_EXTRACTIONS_DIR,
        tasks_files: Sequence[Path] = DEFAULT_TASKS, goal: str | None = None,
        arms: Sequence[str] = ARMS, check: bool = False,
        pilot_manifest: Path = PILOT_MANIFEST) -> dict[str, Any]:
    tasks = _goals(tasks_files)
    report: dict[str, Any] = {
        "instrument": "scripts/real_l_refusal_sim.py",
        "git_commit": R._git_commit(),
        "monitor": "gateway/main.py in-process: POST /containment/seal, then POST /inspect on "
                   "the recorded planner request (the full chain, dry run, empty carry)",
        "parameters": {"n_min": N_MIN, "n_max": N_MAX, "hit_threshold": HIT_THRESHOLD,
                       "salts": "fixed instrument salts (session, filter)", "model": CLOUD_MODEL,
                       "arms": list(arms), "extractions_dir": _rel(extractions_dir),
                       "field_kinds": list(PROMPT_FIELD_KINDS)},
        "collections": {},
    }
    for cid in collections:
        task = tasks.get(cid)
        corpus = task.corpus if task else corpora_root / cid
        if not corpus.is_dir():
            raise SystemExit(f"{cid}: no collection at {corpus}")
        g = goal if goal is not None else (task.goal if task else None)
        if g is None:
            raise SystemExit(f"{cid}: no goal; give a tasks file naming it, or --goal")
        files = extraction_files(extractions_dir, cid)
        if not files:
            report["collections"][cid] = {"collection": cid, "corpus": _rel(corpus),
                                          "extractions": [], "refused_files": [],
                                          "note": f"no extraction under "
                                                  f"{_rel(extractions_dir)}/{cid}"}
            continue
        report["collections"][cid] = simulate_collection(cid, corpus, g, files, arms=arms)
    if check:
        report["self_check"] = self_check(report["collections"], pilot_manifest)
    return report


def summary(report: dict[str, Any]) -> str:
    """The counts-only table."""
    lines = [f"{'collection':<10} {'extraction':<20} {'arm':<8} {'refused':<7} {'hits':>4} "
             f"{'rels':>4} {'fields':>6} {'w/run':>5}  where (windows per field kind)  [reason]"]
    refused: Counter[str] = Counter()
    simulated: Counter[str] = Counter()
    for cid, c in report["collections"].items():
        if not c["extractions"]:
            lines.append(f"{cid:<10} {c.get('note', 'no extraction')}")
        for ex in c["extractions"]:
            for arm, a in ex["arms"].items():
                simulated[arm] += 1
                refused[arm] += a["refused"]
                where = ", ".join(f"{k}={v}" for k, v in a["prompt"]["by_field_kind"].items())
                where += "".join(f", straddling {k}={v}"
                                 for k, v in a["prompt"]["straddling_field_kinds"].items())
                if a["hits"]["straddling_paths"] or a["hits"]["keys"]:
                    where += (f", straddling paths={a['hits']['straddling_paths']}, "
                              f"keys={a['hits']['keys']}")
                lines.append(
                    f"{cid:<10} {ex['file']:<20} {arm:<8} {'yes' if a['refused'] else 'no':<7} "
                    f"{a['hits']['whole_stream']:>4} {a['relations']['distinct']:>4} "
                    f"{a['relations']['fields']:>6} {a['relations']['fields_with_run']:>5}  "
                    f"{where or '-'}  [{a['reason'] or 'allowed'}]")
        for rf in c["refused_files"]:
            lines.append(f"{cid:<10} {rf['file']:<20} refused by load_extractions: "
                         f"{rf['reason']}" + (f" ({rf['category']})" if "category" in rf else ""))
    lines.append("refused: " + (", ".join(f"{arm} {refused[arm]}/{simulated[arm]}"
                                          for arm in simulated) or "nothing simulated"))
    sc = report.get("self_check")
    if sc:
        line = f"self-check {sc['collection']} {sc['arm']}: {sc['status']}"
        if sc["status"] != "not run":
            line += (f"; pilot [{sc['pilot_reason'] or 'allowed'}] vs simulated "
                     + ", ".join(f"{r['file']} [{r['simulated_reason'] or 'allowed'}]"
                                 for r in sc["extractions"])
                     + f"; filter matches pilot: {sc['filter_matches_pilot']}; {sc['note']}")
        else:
            line += f": {sc['reason']}"
        lines.append(line)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--collections", nargs="*", default=None,
                    help="default: tab-L0..tab-L6 that exist under --corpora-root")
    ap.add_argument("--corpora-root", type=Path, default=DEFAULT_CORPORA)
    ap.add_argument("--extractions-dir", type=Path, default=DEFAULT_EXTRACTIONS_DIR,
                    help="<dir>/<collection>/*.json as tier1_probe.py extract --out-dir writes")
    ap.add_argument("--tasks", nargs="*", type=Path, default=list(DEFAULT_TASKS),
                    help="tasks files naming each collection's goal")
    ap.add_argument("--goal", default=None, help="one goal for every collection instead")
    ap.add_argument("--arms", nargs="+", choices=ARMS, default=list(ARMS))
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--self-check", action="store_true",
                    help=f"on {SELF_CHECK_COLLECTION}, compare the {SELF_CHECK_ARM} verdict "
                         "with the pilot manifest's refusal note; exit 1 on a mismatch, 2 when "
                         "it cannot run")
    ap.add_argument("--pilot-manifest", type=Path, default=PILOT_MANIFEST)
    args = ap.parse_args(argv)
    collections = args.collections
    if collections is None:
        collections = [c for c in DEFAULT_COLLECTIONS if (args.corpora_root / c).is_dir()]
    if args.self_check and SELF_CHECK_COLLECTION not in collections:
        collections = [SELF_CHECK_COLLECTION, *collections]
    report = run(collections, corpora_root=args.corpora_root, extractions_dir=args.extractions_dir,
                 tasks_files=args.tasks, goal=args.goal, arms=args.arms, check=args.self_check,
                 pilot_manifest=args.pilot_manifest)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(summary(report))
    print(f"\nwrote {_rel(args.out)}")
    if args.self_check:
        return {"pass": 0, "fail": 1}.get(report["self_check"]["status"], 2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
