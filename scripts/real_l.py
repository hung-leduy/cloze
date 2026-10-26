#!/usr/bin/env python3
"""Track L, run side: which labelled identifiers of public court judgments reached C.

Why this exists
---------------
Scope §12 (drafted 2026-10-05, in force once the author signs it) adds track L:
the three private arms run over ECHR judgments from the Text Anonymization
Benchmark (TAB), public court judgments standing in for private documents,
whose personal identifiers were labelled by people unrelated to PrivDeep. The
question is whether any labelled identifier reaches C through PrivDeep's own
egress. ``scripts/real_corpora/`` builds the collections and their identifier
lists; this file reads the runs. No oracle and no judge run on L (§12.5), so
``run_evaluation.py measure`` and ``aggregate`` do not apply. Everything here
reuses that driver's instruments (``scan_trace``, ``token_hits``,
``health_check``, ``_run_entities``) and ``reconstruction.reconstruct``, so a
crossing on L means what H3's crossing means on A-D.

Subcommands
-----------
``scan``       free and offline. Per run and per arm: DIRECT and QUASI crossings
               k/n by entity type with the labels group apart, extractor recall,
               predicate echo, the utility proxy and the health gate; per
               collection the same recall and echo once per distinct extraction,
               and the G3 recovery net of the no-trace control; the archived
               phase-one attempts, scanned for crossings too; HL1 (§12.7), with
               the §12.8 digest check against the A-D batch when it is given.
``adversary``  BILLABLE with ``--yes``: the zero-shot reconstruction adversary on
               the rendered trace of each arm's first repeat, and per collection
               one control whose trace holds only the goal (§12.5). Without
               ``--yes`` it prints the estimate and exits 0 with no call and no key.
``estimate``   free: the itemised cost of what is still to run, and which whole
               collections a cap admits (§12.9), for ``freeze_batch_real.sh``.
``health``     free: one line per expected run, so the batch can re-run a
               transport failure once (§12.9), and only once.
``pending``    free: the collections a phase-one step may still run: not on disk,
               never attempted, and with the extraction it reuses (§12.9).
``budget``     free: what the runs on disk recorded spending (each traced
               exchange's tokens, each adversary call's usage) against the cap.
``verify``     free: a rebuilt collection's files against its MANIFEST.json and
               the committed summary ``eval/real/manifest_l.json`` (§12.8).
``extraction`` free: extractor recall and predicate echo from saved extractions
               alone, the fallback §12.9 names if no billable L run can start.
               The extractions come from ``tier1_probe.py extract`` (local GPU, no
               cloud call), written under the gitignored ``eval/real/out/``:
               ``tier1_probe.py extract eval/real/corpora/tab-L1 --k 1
               --out-dir eval/real/out/extractions/tab-L1``; the rules are the
               scan's, the output counts only. ``tier1_probe.py analyse`` is not
               for L: its rows list the surfaces they found.

What leaves this file
---------------------
Counts, rates, hashes and decisions. Never an identifier string, a judgment's
text or the adversary's output: the strings are TAB's labels of real people's
names, places and dates, and the output is an attempt to recover them. The one
place a string is written is ``real_l_crossings.json`` inside a run or attempt
directory, gitignored with it, which lists the strings that crossed there so
the author can trace a crossing; the scan reports their entity types, counts
and routes only, as §12.7 words it ("never the strings").

Usage
-----
    python scripts/real_l.py scan --tasks eval/real/tasks_l.json --runs eval/real/runs \\
        --out eval/real/out/real_l_scan.json [--reference-runs eval/runs]
    python scripts/real_l.py adversary --tasks eval/real/tasks_l.json --runs eval/real/runs
    python scripts/real_l.py adversary ... --yes          # billable
    python scripts/real_l.py estimate --tasks eval/real/tasks_l.json --runs eval/real/runs \\
        --cap 15 [--spent USD] [--admit-out FILE]
    python scripts/real_l.py health --tasks eval/real/tasks_l.json --runs eval/real/runs
    python scripts/real_l.py verify --tasks eval/real/tasks_l.json \\
        --manifest eval/real/manifest_l.json
    python scripts/real_l.py pending --tasks eval/real/tasks_l.json --runs eval/real/runs \\
        --arm baseline --rep 1 --reuse-from r5 --out FILE
    python scripts/real_l.py budget --runs eval/real/runs --cap 15 --spent USD [--need-reruns N]
    python scripts/real_l.py extraction --tasks eval/real/tasks_l.json \\
        --extractions eval/real/out/extractions --out eval/real/out/real_l_extraction.json
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "backend" / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from privdeep.eval.reconstruction import (  # noqa: E402
    _SYSTEM as ADVERSARY_SYSTEM,
)
from privdeep.eval.reconstruction import (  # noqa: E402
    TRACE_MAX_CHARS,
    _render_trace_full,
    reconstruct,
)
from privdeep.ingest import SUFFIXES, load  # noqa: E402
from privdeep.models.document import Document  # noqa: E402
from privdeep.tier1_local.extraction_io import text_sha256  # noqa: E402
from privdeep.tier1_local.slot_masker import Entity  # noqa: E402
from privdeep.tier2_cloud.cloud_client import CloudClient  # noqa: E402

from scripts import run_evaluation as R  # noqa: E402
from scripts.real_corpora import tab as T  # noqa: E402
from shared.shingle_filter import tokenize  # noqa: E402

__all__ = ["HL1", "HL1_RULE", "Identifier", "adversary_guard", "adversary_usd", "control_trace",
           "estimate", "extraction_scan", "health_lines", "load_identifiers", "main",
           "needle_groups", "pending", "phase_one_attempts", "plan_adversary", "present",
           "recorded_spend", "rule_of_three", "run_adversary", "scan", "verify"]

ARMS = R.ARMS
HOLDS, FAILS, NOT_TESTABLE = R.HOLDS, R.FAILS, R.NOT_TESTABLE
# The collections HL1 is registered on (§12.3, §12.7). L0 is development only.
REGISTERED = tuple(f"tab-L{i}" for i in range(1, 7))
# "baseline, r5 and r1, 2 repeats each" (§12.5). Fewer is named, not refused.
REGISTERED_REPEATS = 2
IDENTIFIER_TYPES = ("DIRECT", "QUASI")
# The utility proxy's types (§12.6): values a useful report would carry.
UTILITY_TYPES = ("DATETIME", "QUANTITY", "ORG")
EXCLUDED_SIDES = ("user-goal", "cloud-echo", "cloud-reply", "not-sent")

IDENTIFIERS_NAME = "identifiers.json"
COLLECTION_MANIFEST = "MANIFEST.json"
# Contract 1: what a collection directory holds, exactly. Anything else ending
# in .md would be ingested as a fifth document.
COLLECTION_FILES = ("doc1.md", "doc2.md", "doc3.md", "doc4.md", "surfaces.json",
                    "smoke_fact_key.json", IDENTIFIERS_NAME, COLLECTION_MANIFEST)
CROSSINGS_NAME = "real_l_crossings.json"
ADVERSARY_RUN_NAME = "adversary_run.json"
CONTROL_SUFFIX = "__control"

DEFAULT_TASKS = _REPO / "eval" / "real" / "tasks_l.json"
DEFAULT_RUNS = _REPO / "eval" / "real" / "runs"
DEFAULT_OUT = _REPO / "eval" / "real" / "out" / "real_l_scan.json"
DEFAULT_MANIFEST = _REPO / "eval" / "real" / "manifest_l.json"
# The only run directories inside the repository the billable adversary may
# write into: track L's and its pilot's. Anything else there (eval/runs, A-D's)
# is refused before a key is read.
ADVERSARY_RUNS = (_REPO / "eval" / "real" / "runs", _REPO / "eval" / "pilot" / "real-l" / "runs")
# Over-estimate of one phase-one run, run_evaluation.estimate_private_cost's basis.
PRIVATE_RUN_USD = R.PRIVATE_ARM_IN * R.USD_IN + R.PRIVATE_ARM_OUT * R.USD_OUT
# health_lines' status for a transport failure that has had its one re-run.
RERUN_USED = "transport-failure-rerun-used"

# The adversary's cost basis. Rates and characters per token are the A-D
# driver's (run_evaluation.estimate_cost); the trace cap and the reply cap are
# reconstruct()'s own, so the estimate assumes every cap is reached and is an
# over-estimate, as the driver's is. The prompt prefix is reconstruct()'s.
PER_CHAR_TOK = 1 / 3.5
ADVERSARY_OUT_TOKENS = 8192
_PROMPT_PREFIX = "Transcripts follow. Reconstruct the original private document.\n\n"
_TRUNCATION_MARK = "\n\n[trace truncated]"

# §12.7, verbatim (wrapped lines joined by one space); test_real_l pins each
# string against the scope text, so an edit to either side fails the suite.
HL1: dict[str, str] = {
    "label": "HL1", "section": "12.7",
    "wording": ("HL1 holds when no DIRECT identifier string crosses in any private-arm run of "
                "L1-L6, every run's trace was scanned and complete, and every collection has a "
                "valid run of every arm."),
    "reporting": ("Reported with k/n and, when k = 0, the rule-of-three 95% upper bound 3/n on "
                  "the per-string crossing probability (descriptive, not a test)."),
    "if_fails": ("If HL1 fails, the paper reports the entity types, counts and routes of the "
                 "crossings, never the strings."),
}
HL1_RULE = (
    "Over every private-arm run (r5, baseline, r1) of the tasks file, the health gate's "
    "exclusions included, and every archived phase-one attempt at one (a run --force "
    "replaced after a transport failure, or a pipeline that exited non-zero), whose requests "
    "reached C as well: fails if any non-label DIRECT identifier string has a core-sent hit in "
    "the egress trace of any of them (scan_trace, each string read on its own; spans of the "
    "goal, cloud echoes, cloud replies and requests the monitor refused are excluded, as in "
    "H3). Otherwise not testable if any run's trace is missing, empty or incomplete (a "
    "transport failure, or a run that did not complete), if a collection has no run of some "
    "arm that passes the health gate, if the §12.8 digest check was run and the runs' SLM "
    "image and model digests and resolved cloud model are not all equal to the A-D batch's, "
    "or if the tasks file is not the registered L1-L6; else holds. An attempt's own "
    "completeness decides nothing: a run replaced it, or its cell is uncovered. Label-group "
    "strings (one token of at most 2 characters, or only goal tokens and function words) are "
    "reported apart and decide nothing. k/n counts distinct non-label DIRECT strings over the "
    "collections, a string counted once however many runs or attempts it crossed in; run "
    "pairs are reported beside it, and the rule-of-three bound is given for these two DIRECT "
    "blocks only.")
DEFINITIONS = {
    "identifier_string": (
        "A span_text TAB's annotators labelled DIRECT or QUASI, distinct per collection by its "
        "containment-tokenizer tokens, DIRECT if any annotator said so (§12.4; identifiers.json). "
        "Strings whose tokens, joined by one separator, hold at most 2 characters (a single "
        "token of 1 or 2 characters), or whose tokens all occur in the goal or the "
        "function-word list, are the labels group, reported apart."),
    "crossing": (
        "A whole-token, case-insensitive hit (token_hits) of the string in what the core sent "
        "(scan_trace side core-sent): system, messages and tools of every exchange the monitor "
        "let through. Excluded and counted: the goal, spans repeating an earlier cloud reply, "
        "cloud replies, and requests the monitor refused. Each string is read on its own "
        "(strings are scanned in groups that share no token, which gives the same answer), so "
        "a string standing inside or overlapping another that crossed is found too; token_hits "
        "over all strings at once consumes such hits. That one-call reading, over the same "
        "non-label strings, is reported beside it ('one_call', 'direct_one_call'), descriptive "
        "only; presidio_residual.py counts its k and k_one_call the same two ways."),
    "attempts": (
        "Phase-one attempts archived under the attempts directory (attempt.json "
        "egress_trace_is_copy false): a run --force replaced, or a pipeline that exited "
        "non-zero. Their traces are scanned with the crossing rule and count for HL1; an "
        "attempt with no trace is listed as not scanned. Adversary copies are skipped: their "
        "trace is still in the runs directory."),
    "rule_of_three": ("3/n when k = 0: the 95% upper bound on a proportion; descriptive only, "
                      "and given for HL1's two DIRECT blocks only (§12.7)."),
    "extractor_recall": (
        "Share of non-label strings whose token tuple equals that of an entity the run masked "
        "(entities.json, else extractions.json): 'exact'. Beside it 'covered': the string's "
        "tokens stand, contiguous, inside the tokens of one such entity, so a longer masked "
        "entity takes it out of the text. Per run and pooled over runs, which share one "
        "extraction per collection; and once per distinct extractions.json ('extractions' per "
        "collection, 'extraction' pooled), from that file's entities."),
    "predicate_echo": (
        "Share of non-label strings with a token_hits hit in some field (subject type, "
        "predicate, object type) of a relation in the run's extractions.json, each string "
        "read on its own."),
    "utility_proxy": (
        "Sections delivered, refused, and failed in transport (a CloudError or GatewayError, "
        "not a refusal), from the manifest; and the share of the collection's non-label "
        "DATETIME, QUANTITY and ORG strings with a hit in report.md (Markdown escapes removed)."),
    "g3": (
        "Non-label strings with a token_hits hit in the reconstruction adversary's output on "
        "an arm's first repeat, net of those in the output of the collection's no-trace "
        "control, whose trace is one exchange holding only the goal (set difference)."),
    "integrity": (
        "§12.8: each L run's SLM image (id and repo digests), SLM model digest and resolved "
        "cloud model id(s) against the A-D batch manifests (the one read of eval/runs, "
        "manifest.json only). Checked when --reference-runs is given; a value that differs or "
        "is unrecorded makes HL1 not testable unless it fails."),
}


# --------------------------------------------------------------------- inputs


@dataclass(frozen=True, slots=True)
class Identifier:
    text: str
    identifier_type: str
    entity_types: tuple[str, ...]
    label: bool


def load_identifiers(task: R.Task) -> list[Identifier]:
    """The collection's identifier strings, refused rather than guessed at.

    A missing file, another collection's file, an unknown identifier type or two
    strings with one spelling would each make a k/n that is not the registered
    one, so each stops the scan.
    """
    p = task.corpus / IDENTIFIERS_NAME
    if not p.exists():
        raise SystemExit(f"task {task.id}: no {IDENTIFIERS_NAME} in {task.corpus}; rebuild the "
                         "collection with scripts/real_corpora")
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("collection") != task.id:
        raise SystemExit(f"task {task.id}: {p} is for collection {d.get('collection')!r}")
    out = [Identifier(str(s["text"]), str(s["identifier_type"]),
                      tuple(sorted(str(t) for t in s["entity_types"])), bool(s["label"]))
           for s in d["strings"]]
    bad = sorted({i.identifier_type for i in out} - set(IDENTIFIER_TYPES))
    if bad:
        raise SystemExit(f"task {task.id}: unknown identifier type(s) {bad} in {p}")
    if len({i.text for i in out}) != len(out):
        raise SystemExit(f"task {task.id}: {p} lists one spelling twice")
    return out


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _docs(corpus: Path) -> list[Document]:
    return [load(p) for p in sorted(corpus.iterdir()) if p.suffix.lower() in SUFFIXES]


_RUN_NAME = re.compile(r"__(" + "|".join(ARMS) + r")(?:__rep(\d+))?")


def discover_runs(runs: Path, task_id: str) -> list[tuple[str, int, Path]]:
    """Every run directory of a task in run_dir_for's layout: (arm, repeat, path),
    in arm order, then repeat. Named, not composed, so a repeat beyond the
    registered two is scanned rather than missed."""
    found = []
    for d in (runs.iterdir() if runs.is_dir() else ()):
        if not d.is_dir() or not d.name.startswith(f"{task_id}__"):
            continue
        m = _RUN_NAME.fullmatch(d.name[len(task_id):])
        if m:
            found.append((m.group(1), int(m.group(2) or 1), d))
    return sorted(found, key=lambda x: (ARMS.index(x[0]), x[1]))


# ------------------------------------------------------------------ matching


def needle_groups(needles: Iterable[str]) -> list[list[str]]:
    """Needles in groups whose members cannot hide one another's hits.

    `token_hits` consumes a matched run, longest needle first, so 'Zephyr'
    inside a hit on 'Project Zephyr' is not counted twice. That is right for
    counting occurrences and wrong for asking of each string whether it
    occurs: a string standing inside a longer one that crossed did cross, and
    of two strings that overlap in the text ('John Smith' and 'Smith Road' in
    'John Smith Road') only the first would be found. One needle can consume
    another's tokens only where both have the same token, so needles that
    share no token are scanned together and the rest apart. Greedy, longest
    first, deterministic; a needle with no token can never hit and is dropped.
    """
    groups: list[tuple[set[str], list[str]]] = []
    for n in sorted(set(needles), key=lambda s: (-len(tokenize(s)), s)):
        toks = set(tokenize(n))
        if not toks:
            continue
        for used, members in groups:
            if not used & toks:
                used |= toks
                members.append(n)
                break
        else:
            groups.append((toks, [n]))
    return [m for _, m in groups]


def present(text: str, groups: Sequence[Sequence[str]]) -> set[str]:
    """The needles with at least one token_hits hit in `text`."""
    out: set[str] = set()
    for g in groups:
        out.update(R.token_hits(text, list(g)))
    return out


def _kn(k: int, n: int) -> dict[str, Any]:
    return {"k": k, "n": n, "rate": k / n if n else None}


def rule_of_three(k: int, n: int) -> float | None:
    """3/n, the 95% upper bound on a proportion when none of n trials hit.

    Descriptive (§12.7): the runs of a collection share one extraction, so
    their strings are not independent trials and the bound is not a test.
    """
    return 3 / n if k == 0 and n > 0 else None


def _with_bound(b: dict[str, Any]) -> dict[str, Any]:
    """A DIRECT block with its rule-of-three bound, the one §12.7 asks for."""
    return {**b, "rule_of_three": rule_of_three(b["k"], b["n"])}


def tally(rows: Sequence[tuple[Identifier, bool]]) -> dict[str, Any]:
    """k/n over the non-label strings, each row once; then DIRECT and QUASI, each
    by entity type (a string typed several ways counts under each); then the
    labels group apart. A row is one string in one setting (a run, or a
    collection), so pooled rows give run pairs or distinct strings as built."""
    nonlabel = [(i, h) for i, h in rows if not i.label]

    def block(sel: list[tuple[Identifier, bool]]) -> dict[str, Any]:
        return _kn(sum(1 for _, h in sel if h), len(sel))

    out: dict[str, Any] = {"all": block(nonlabel)}
    for it in IDENTIFIER_TYPES:
        sel = [(i, h) for i, h in nonlabel if i.identifier_type == it]
        types = sorted({t for i, _ in sel for t in i.entity_types})
        out[it] = {**block(sel), "by_entity_type": {
            t: block([(i, h) for i, h in sel if t in i.entity_types]) for t in types}}
    out["labels"] = {it: block([(i, h) for i, h in rows if i.label and i.identifier_type == it])
                     for it in IDENTIFIER_TYPES}
    return out


def _one_call(idents: Sequence[Identifier], found: set[str]) -> dict[str, Any]:
    """Non-label k under the one-call reading, beside the n of `tally`."""
    nonlabel = [i for i in idents if not i.label]
    return {"all": sum(1 for i in nonlabel if i.text in found),
            **{it: sum(1 for i in nonlabel if i.identifier_type == it and i.text in found)
               for it in IDENTIFIER_TYPES}}


def _crossings(trace: list[dict[str, Any]], goal: str, idents: Sequence[Identifier],
               groups: Sequence[Sequence[str]]
               ) -> tuple[dict[str, list[dict[str, Any]]], set[str], dict[str, int]]:
    """What crossed in one trace: each string's core-sent occurrences, read string
    by string through `groups` (needle_groups of every string); the one-call
    reading over the non-label strings, as presidio_residual.py's k_one_call;
    and the occurrences on each excluded side, non-label strings only."""
    by_text = {i.text: i for i in idents}
    crossed: dict[str, list[dict[str, Any]]] = {}
    excluded = dict.fromkeys(EXCLUDED_SIDES, 0)
    for g in groups:
        for h in R.scan_trace(trace, list(g), goal=goal):
            if h["side"] == "core-sent":
                crossed.setdefault(h["needle"], []).append(
                    {k: h[k] for k in ("exchange", "stage", "field", "count")})
            elif not by_text[h["needle"]].label:
                excluded[h["side"]] += h["count"]
    one_call = {h["needle"] for h in R.scan_trace(trace, [i.text for i in idents if not i.label],
                                                  goal=goal)
                if h["side"] == "core-sent"}
    return crossed, one_call, excluded


def _write_crossings(d: Path, crossed: dict[str, list[dict[str, Any]]],
                     by_text: dict[str, Identifier], generated_by: str) -> None:
    """The one file with strings in it, beside the trace it was read from."""
    (d / CROSSINGS_NAME).write_text(json.dumps({
        "generated_by": generated_by,
        "note": ("TAB identifier strings that crossed in this run, core-sent side. Private to "
                 "the run directory: never copy them into a committed file or the paper "
                 "(scope §12.7)."),
        "run": d.name,
        "crossed": [{"text": t, "identifier_type": by_text[t].identifier_type,
                     "entity_types": list(by_text[t].entity_types), "label": by_text[t].label,
                     "occurrences": crossed[t]} for t in sorted(crossed)]},
        ensure_ascii=False, indent=2), encoding="utf-8")


def _tokens_of(i: Identifier) -> tuple[str, ...]:
    return tuple(tokenize(i.text))


def _recall_rows(nonlabel: Sequence[Identifier], entity_texts: Iterable[str]
                 ) -> tuple[list[tuple[Identifier, bool]], list[tuple[Identifier, bool]]]:
    """(exact, covered) rows: a string's tokens equal an entity's, or stand
    contiguous inside one entity's tokens (exact implies covered)."""
    exact = {tuple(tokenize(t)) for t in entity_texts}
    covered = {e[a:b] for e in exact for a in range(len(e)) for b in range(a + 1, len(e) + 1)}
    return ([(i, _tokens_of(i) in exact) for i in nonlabel],
            [(i, _tokens_of(i) in covered) for i in nonlabel])


def _echo_rows(nonlabel: Sequence[Identifier], relations: Sequence[Any],
               groups: Sequence[Sequence[str]]) -> list[tuple[Identifier, bool]]:
    echoed: set[str] = set()
    for f in sorted({f for r in relations for f in r if isinstance(f, str)}):
        echoed |= present(f, groups)
    return [(i, i.text in echoed) for i in nonlabel]


def extraction_measures(ex: dict[str, Any], idents: Sequence[Identifier],
                        groups: Sequence[Sequence[str]]
                        ) -> tuple[dict[str, Any], dict[str, list[tuple[Identifier, bool]]]]:
    """Recall and echo of one saved extraction, from its own entities and
    relations: the scan's per-extraction block and the free fallback (§12.9)
    use this one function. Returns the block and its rows, for pooling."""
    nonlabel = [i for i in idents if not i.label]
    docs = ex.get("documents") or []
    exact, covered = _recall_rows(nonlabel, (e["text"] for d in docs
                                             for e in d.get("entities") or []))
    rels = [r for d in docs for r in d.get("relations") or []]
    echo = _echo_rows(nonlabel, rels, groups)
    block = {"extractor_recall": {**tally(exact), "covered": tally(covered)},
             "predicate_echo": {"relations": len(rels), **tally(echo)}}
    return block, {"exact": exact, "covered": covered, "echo": echo}


def _routes(crossed: dict[str, list[dict[str, Any]]], by_text: dict[str, Identifier]
            ) -> dict[tuple[str, str, str, str], list[int]]:
    """(identifier type, entity type, stage kind, field) -> [strings, occurrences]
    for the non-label strings that crossed. The stage kind drops the section id
    ('draft:s3' -> 'draft'), which is the planner's numbering, not a route."""
    agg: dict[tuple[str, str, str, str], list[int]] = {}
    for text, occs in crossed.items():
        ident = by_text[text]
        if ident.label:
            continue
        per: dict[tuple[str, str], int] = {}
        for o in occs:
            key = (str(o["stage"]).split(":", 1)[0], str(o["field"]))
            per[key] = per.get(key, 0) + int(o["count"])
        for (stage, field), occ in per.items():
            for t in ident.entity_types:
                a = agg.setdefault((ident.identifier_type, t, stage, field), [0, 0])
                a[0] += 1
                a[1] += occ
    return agg


def _route_rows(agg: dict[tuple[str, str, str, str], list[int]]) -> list[dict[str, Any]]:
    return [{"identifier_type": it, "entity_type": t, "stage": s, "field": f,
             "strings": a[0], "occurrences": a[1]} for (it, t, s, f), a in sorted(agg.items())]


# ---------------------------------------------------------------------- scan


def _incomplete(trace: list[dict[str, Any]] | None, health: dict[str, Any]) -> str | None:
    """Why a run's trace does not show what the run sent, or None.

    H3's tests (run_evaluation._hypotheses): no trace, no exchange, or a
    forwarded request that failed upstream, which the tracer does not record
    (trace_gap). A run that did not complete is added: its trace cannot be
    shown to be whole either.
    """
    if trace is None:
        return "no egress_trace.jsonl"
    if not trace:
        return "no exchange traced: egress_trace.jsonl is empty"
    failed = [f for f in health["failures"]
              if "transport failure" in f or f.startswith("did not complete")]
    if failed:
        return ("trace incomplete, a forwarded request failed upstream and is not traced, or "
                "the run did not complete (trace_gap): " + "; ".join(failed))
    return None


def _utility(run_dir: Path, health: dict[str, Any], idents: Sequence[Identifier],
             groups: Sequence[Sequence[str]]) -> dict[str, Any]:
    manifest = R._read_json(run_dir / "manifest.json") or {}
    secs = manifest.get("sections") or []
    # A transport failure is not a refusal (run_evaluation._TRANSPORT_FAILURE):
    # the request did not arrive, nothing decided against it.
    transport = sum(1 for s in secs if R._TRANSPORT_FAILURE.match(str(s.get("refused") or "")))
    refused = sum(1 for s in secs if s.get("refused")) - transport
    out: dict[str, Any] = {
        "sections_planned": health["outcomes"].get("planned_sections"),
        "sections_delivered": len(secs) - refused - transport,
        "sections_refused": refused,
        "sections_transport_failed": transport,
        "plan_refused": bool(health["outcomes"].get("plan_refused")),
    }
    rp = run_dir / "report.md"
    if not rp.exists():
        out["report_strings"] = None
        return out
    found = present(R.de_escape(rp.read_text(encoding="utf-8")), groups)
    sel = [i for i in idents if not i.label and set(i.entity_types) & set(UTILITY_TYPES)]
    out["report_strings"] = {
        **{t: _kn(sum(1 for i in sel if t in i.entity_types and i.text in found),
                  sum(1 for i in sel if t in i.entity_types)) for t in UTILITY_TYPES},
        "any": _kn(sum(1 for i in sel if i.text in found), len(sel))}
    return out


def scan_run(run_dir: Path, arm: str, rep: int, task: R.Task, idents: Sequence[Identifier],
             *, groups: Sequence[Sequence[str]] | None = None,
             nl_groups: Sequence[Sequence[str]] | None = None, write_crossings: bool = True
             ) -> tuple[dict[str, Any], set[str], set[str]]:
    """One run's measures, and the strings that crossed, read string by string and
    in one call (kept in memory for the pooled blocks, never in the output)."""
    by_text = {i.text: i for i in idents}
    nonlabel = [i for i in idents if not i.label]
    groups = needle_groups(by_text) if groups is None else groups
    nl_groups = needle_groups(i.text for i in nonlabel) if nl_groups is None else nl_groups
    health = R.health_check(run_dir)
    trace = R._read_trace(run_dir)
    out: dict[str, Any] = {
        "run": run_dir.name, "arm": arm, "rep": rep,
        "health": {"valid": health["valid"], "failures": health["failures"],
                   "outcomes": health["outcomes"]},
        "trace": {"scanned": trace is not None, "exchanges": None if trace is None else len(trace),
                  "incomplete": _incomplete(trace, health)},
    }
    crossed: dict[str, list[dict[str, Any]]] = {}
    one_call: set[str] = set()
    if trace is not None:
        crossed, one_call, excluded = _crossings(trace, task.goal, idents, groups)
        out["crossing"] = {**tally([(i, i.text in crossed) for i in idents]),
                           "one_call": _one_call(idents, one_call),
                           "routes": _route_rows(_routes(crossed, by_text)),
                           "excluded_occurrences": excluded}
        if write_crossings:
            _write_crossings(run_dir, crossed, by_text, "scripts/real_l.py scan")
    else:
        out["crossing"] = None

    ents, src = R._run_entities(run_dir)
    if ents is None:
        out["extractor_recall"] = {"source": None, "reason": "no entities.json or "
                                                             "extractions.json"}
    else:
        exact, covered = _recall_rows(nonlabel, (t for t, _c in ents))
        out["extractor_recall"] = {"source": src, **tally(exact), "covered": tally(covered)}
    ex = R._read_json(run_dir / "extractions.json")
    if ex is None:
        out["predicate_echo"] = {"source": None, "reason": "no extractions.json"}
    else:
        rels = [r for d in ex.get("documents", []) for r in d.get("relations", [])]
        out["predicate_echo"] = {"source": "extractions.json", "relations": len(rels),
                                 **tally(_echo_rows(nonlabel, rels, nl_groups))}
    out["utility"] = _utility(run_dir, health, idents, nl_groups)
    return out, set(crossed), one_call


def _g3(task: R.Task, runs: Path, idents: Sequence[Identifier]
        ) -> tuple[dict[str, Any], dict[str, list[tuple[Identifier, bool]]],
                   dict[str, list[tuple[Identifier, bool]]]]:
    """G3 for one collection: gross per arm, the control, and net of it.

    Net is a set difference: a string the goal alone led the adversary to write
    is not evidence that the trace carried it. Returns the block and, per arm,
    the gross and net rows for pooling.
    """
    nonlabel = [i for i in idents if not i.label]
    groups = needle_groups(i.text for i in nonlabel)

    def read(d: Path) -> tuple[set[str] | None, dict[str, Any]]:
        p = d / "adversary_output.txt"
        if not p.exists():
            return None, {"present": False}
        rec = R._read_json(d / "reconstruction.json") or {}
        return present(p.read_text(encoding="utf-8"), groups), {
            "present": True, "adversary_model": rec.get("adversary_model"),
            "adversary_refused": rec.get("adversary_refused") is not None,
            "trace_truncated": rec.get("trace_truncated")}

    ctrl, ctrl_meta = read(runs / f"{task.id}{CONTROL_SUFFIX}")
    block: dict[str, Any] = {"control": {**ctrl_meta, "recovered": (
        tally([(i, i.text in ctrl) for i in nonlabel]) if ctrl is not None else None)},
        "arms": {}}
    gross_rows: dict[str, list[tuple[Identifier, bool]]] = {}
    net_rows: dict[str, list[tuple[Identifier, bool]]] = {}
    for arm in ARMS:
        d = R.run_dir_for(runs, task.id, arm, 1)
        got, meta = read(d)
        if got is None:
            block["arms"][arm] = {"run": d.name, **meta}
            continue
        gross_rows[arm] = [(i, i.text in got) for i in nonlabel]
        row: dict[str, Any] = {"run": d.name, **meta, "gross": tally(gross_rows[arm])}
        if ctrl is None:
            row["net"] = None
            row["net_reason"] = f"no control output under {task.id}{CONTROL_SUFFIX}"
        else:
            net_rows[arm] = [(i, i.text in got and i.text not in ctrl) for i in nonlabel]
            row["net"] = tally(net_rows[arm])
        block["arms"][arm] = row
    return block, gross_rows, net_rows


def _digest_fields(m: dict[str, Any] | None) -> dict[str, Any]:
    """The §12.8 identity of a run: SLM image, SLM model, resolved cloud model."""
    rt = (m or {}).get("runtime") or {}
    img = rt.get("ollama_image") if isinstance(rt.get("ollama_image"), dict) else {}
    lm = rt.get("local_model") if isinstance(rt.get("local_model"), dict) else {}
    digests = img.get("repo_digests")
    return {"slm_image_id": img.get("id"),
            "slm_image_repo_digests": (json.dumps(sorted(digests))
                                       if isinstance(digests, list) else None),
            "slm_model_digest": lm.get("digest"),
            "cloud_models_resolved": sorted((m or {}).get("cloud_models_resolved") or [])}


def integrity(run_dirs: Sequence[Path], reference_runs: Path) -> dict[str, Any]:
    """Each L run's SLM image and model digests and resolved cloud model id
    against those of the A-D batch manifests (§12.8). Digests are not private.

    This is track L's one read of the A-D runs, and it reads manifest.json
    only, never a measurement, rationale, adversary output or trace. A verdict
    other than 'equal' makes HL1 not testable (scan), so a mismatch cannot pass
    unseen.

    'equal' needs the A-D batch to have recorded exactly one value and the L
    run the same; several A-D values make the reference ambiguous, which is
    named; an unrecorded value is never read as equal.
    """
    refs = [_digest_fields(R._read_json(p))
            for p in sorted(reference_runs.glob("*/manifest.json"))]
    ref: dict[str, set[str]] = {k: set() for k in ("slm_image_id", "slm_image_repo_digests",
                                                    "slm_model_digest", "cloud_models_resolved")}
    for r in refs:
        for k in ("slm_image_id", "slm_image_repo_digests", "slm_model_digest"):
            if r[k] is not None:
                ref[k].add(r[k])
        ref["cloud_models_resolved"].update(r["cloud_models_resolved"])

    def verdict(k: str, values: list[str]) -> str:
        if not values or not ref[k]:
            return "unrecorded"
        if any(v not in ref[k] for v in values):
            return "differs"
        return "equal" if len(ref[k]) == 1 else "ambiguous reference"

    per_run: dict[str, dict[str, str]] = {}
    for d in run_dirs:
        f = _digest_fields(R._read_json(d / "manifest.json"))
        per_run[d.name] = {
            k: verdict(k, f[k] if k == "cloud_models_resolved"
                       else ([] if f[k] is None else [f[k]])) for k in ref}
    return {
        "rule": ("Each L run's SLM image (id and repo digests), SLM model digest and resolved "
                 "cloud model id(s) must equal those of the A-D batch manifests (§12.8)."),
        "reference": str(reference_runs), "reference_manifests": len(refs),
        "reference_values": {k: sorted(v) for k, v in ref.items()},
        "per_run": per_run,
        "all_equal": bool(per_run) and all(v == "equal" for r in per_run.values()
                                           for v in r.values()),
    }


def phase_one_attempts(runs: Path, task_id: str) -> list[tuple[str, int, Path]]:
    """The phase-one attempts archived beside the runs for one task: (arm,
    repeat, path), in arm, repeat and name order.

    A run --force replaced (the batch's transport re-run) and a pipeline that
    exited non-zero both leave one; their requests reached C. A copy archived
    before an adversary re-attack holds a duplicate of a trace still in the
    runs directory, and a control is not a private-arm run, so neither is
    returned. An attempt without attempt.json is kept: the safer reading.
    """
    root = R.attempts_dir_for(runs)
    pat = re.compile(re.escape(task_id) + r"__(" + "|".join(ARMS)
                     + r")(?:__rep(\d+))?__attempt\d+")
    out = []
    for d in (sorted(root.iterdir()) if root.is_dir() else ()):
        m = pat.fullmatch(d.name)
        if not d.is_dir() or not m:
            continue
        if (R._read_json(d / "attempt.json") or {}).get("egress_trace_is_copy"):
            continue
        out.append((m.group(1), int(m.group(2) or 1), d))
    return sorted(out, key=lambda x: (ARMS.index(x[0]), x[1], x[2].name))


def _attempted(runs: Path, run_name: str) -> bool:
    """Whether a run of this name has a phase-one attempt archived: it has been
    re-run once already, or its pipeline exited non-zero (§12.9: one re-run,
    and only for a transport failure)."""
    root = R.attempts_dir_for(runs)
    pat = re.compile(re.escape(run_name) + r"__attempt\d+")
    return any(d.is_dir() and pat.fullmatch(d.name)
               and not (R._read_json(d / "attempt.json") or {}).get("egress_trace_is_copy")
               for d in (root.iterdir() if root.is_dir() else ()))


def scan(tasks: Sequence[R.Task], runs: Path, *, reference_runs: Path | None = None,
         registered: Sequence[str] = REGISTERED, write_crossings: bool = True
         ) -> dict[str, Any]:
    """Track L's measures and HL1, from what is on disk. Free and offline."""
    collections: dict[str, Any] = {}
    run_rows: dict[str, list[tuple[Identifier, bool]]] = {a: [] for a in ARMS}
    distinct_rows: dict[str, list[tuple[Identifier, bool]]] = {a: [] for a in ARMS}
    any_rows: list[tuple[Identifier, bool]] = []
    one_call_rows: list[tuple[Identifier, bool]] = []
    attempt_rows: list[tuple[Identifier, bool]] = []
    routes: dict[str, dict[tuple[str, str, str, str], list[int]]] = {a: {} for a in ARMS}
    attempt_routes: dict[tuple[str, str, str, str], list[int]] = {}
    per_arm: dict[str, list[dict[str, Any]]] = {a: [] for a in ARMS}
    g3_gross: dict[str, list[tuple[Identifier, bool]]] = {a: [] for a in ARMS}
    g3_net: dict[str, list[tuple[Identifier, bool]]] = {a: [] for a in ARMS}
    ext_rows: dict[str, list[tuple[Identifier, bool]]] = {"exact": [], "covered": [], "echo": []}
    n_extractions = 0
    incomplete: dict[str, str] = {}
    uncovered: list[str] = []
    scanned_runs: list[str] = []
    attempts_scanned: list[str] = []
    attempts_without_trace: list[str] = []
    all_dirs: list[Path] = []

    def add_routes(into: dict[tuple[str, str, str, str], list[int]],
                   agg: dict[tuple[str, str, str, str], list[int]]) -> None:
        for key, a in agg.items():
            b = into.setdefault(key, [0, 0])
            b[0] += a[0]
            b[1] += a[1]

    for task in tasks:
        idents = load_identifiers(task)
        by_text = {i.text: i for i in idents}
        groups = needle_groups(by_text)
        nl_groups = needle_groups(i.text for i in idents if not i.label)
        found = discover_runs(runs, task.id)
        all_dirs += [d for _a, _r, d in found]
        rows: dict[str, Any] = {}
        crossed_by_arm: dict[str, set[str]] = {a: set() for a in ARMS}
        one_call_union: set[str] = set()
        scanned_by_arm: dict[str, int] = dict.fromkeys(ARMS, 0)
        for arm, rep, d in found:
            res, crossed, one = scan_run(d, arm, rep, task, idents, groups=groups,
                                         nl_groups=nl_groups, write_crossings=write_crossings)
            rows[d.name] = res
            per_arm[arm].append(res)
            if res["trace"]["incomplete"] is not None:
                incomplete[d.name] = res["trace"]["incomplete"]
            if res["crossing"] is None:
                continue
            scanned_runs.append(d.name)
            scanned_by_arm[arm] += 1
            crossed_by_arm[arm] |= crossed
            one_call_union |= one
            run_rows[arm] += [(i, i.text in crossed) for i in idents]
            for r in res["crossing"]["routes"]:
                b = routes[arm].setdefault(
                    (r["identifier_type"], r["entity_type"], r["stage"], r["field"]), [0, 0])
                b[0] += r["strings"]
                b[1] += r["occurrences"]
        # The archived phase-one attempts: their requests reached C, so a
        # crossing in one is a crossing (§12.7 "in any private-arm run").
        att_crossed: set[str] = set()
        att_here: list[str] = []
        for _arm, _rep, d in phase_one_attempts(runs, task.id):
            trace = R._read_trace(d)
            if not trace:
                attempts_without_trace.append(d.name)
                continue
            crossed, _one, _excluded = _crossings(trace, task.goal, idents, groups)
            att_here.append(d.name)
            att_crossed |= set(crossed)
            add_routes(attempt_routes, _routes(crossed, by_text))
            if write_crossings:
                _write_crossings(d, crossed, by_text, "scripts/real_l.py scan (attempt)")
        attempts_scanned += att_here
        for arm in ARMS:
            if scanned_by_arm[arm]:
                distinct_rows[arm] += [(i, i.text in crossed_by_arm[arm]) for i in idents]
            if not any(r["arm"] == arm and r["health"]["valid"] for r in rows.values()):
                uncovered.append(f"{task.id}: no {arm} run that passes the health gate")
        if any(scanned_by_arm.values()) or att_here:
            union = set().union(*crossed_by_arm.values()) | att_crossed
            any_rows += [(i, i.text in union) for i in idents]
        if any(scanned_by_arm.values()):
            one_call_rows += [(i, i.text in one_call_union) for i in idents]
        if att_here:
            attempt_rows += [(i, i.text in att_crossed) for i in idents]
        # Recall and echo once per distinct extraction: the runs of a
        # collection reuse one, and six copies of it are one measurement.
        by_sha: dict[str, list[str]] = {}
        for _a, _r, d in found:
            if (d / "extractions.json").is_file():
                by_sha.setdefault(_sha256(d / "extractions.json"), []).append(d.name)
        extractions = []
        for sha, names in sorted(by_sha.items()):
            block, xrows = extraction_measures(
                R._read_json(runs / names[0] / "extractions.json") or {}, idents, nl_groups)
            extractions.append({"sha256": sha, "runs": names, **block})
            for k, v in xrows.items():
                ext_rows[k] += v
            n_extractions += 1
        g3, gross, net = _g3(task, runs, idents)
        for arm in ARMS:
            g3_gross[arm] += gross.get(arm, [])
            g3_net[arm] += net.get(arm, [])
        counts = {it: sum(1 for i in idents if not i.label and i.identifier_type == it)
                  for it in IDENTIFIER_TYPES}
        collections[task.id] = {
            "corpus": (task.corpus.relative_to(_REPO).as_posix()
                       if task.corpus.is_relative_to(_REPO) else str(task.corpus)),
            "identifiers_sha256": _sha256(task.corpus / IDENTIFIERS_NAME),
            "strings": {**counts, "labels": sum(1 for i in idents if i.label)},
            "short_of_registered_repeats": {
                a: n for a in ARMS
                if (n := sum(1 for r in rows.values() if r["arm"] == a)) < REGISTERED_REPEATS},
            "runs": rows,
            "attempts_scanned": att_here,
            "extractions": extractions,
            "g3": g3,
        }

    def pooled(results: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
        ks = [r[key] for r in results if r[key] and r[key].get("source")]
        if not ks:
            return None
        out = {it: _kn(sum(x[it]["k"] for x in ks), sum(x[it]["n"] for x in ks))
               for it in ("all", *IDENTIFIER_TYPES)}
        cov = [x["covered"] for x in ks if "covered" in x]
        if cov:
            out["covered"] = {it: _kn(sum(x[it]["k"] for x in cov), sum(x[it]["n"] for x in cov))
                              for it in ("all", *IDENTIFIER_TYPES)}
        return out

    def utility(results: list[dict[str, Any]]) -> dict[str, Any]:
        us = [r["utility"] for r in results]
        rs = [u["report_strings"] for u in us if u["report_strings"]]
        return {"sections_delivered": sum(u["sections_delivered"] for u in us),
                "sections_refused": sum(u["sections_refused"] for u in us),
                "sections_transport_failed": sum(u["sections_transport_failed"] for u in us),
                "plans_refused": sum(1 for u in us if u["plan_refused"]),
                "report_strings": {t: _kn(sum(x[t]["k"] for x in rs), sum(x[t]["n"] for x in rs))
                                   for t in (*UTILITY_TYPES, "any")} if rs else None}

    by_arm = {arm: {
        "runs": [r["run"] for r in per_arm[arm]],
        "runs_scanned": sum(1 for r in per_arm[arm] if r["crossing"] is not None),
        "runs_valid": sum(1 for r in per_arm[arm] if r["health"]["valid"]),
        "crossing_run_pairs": tally(run_rows[arm]),
        "crossing_distinct": tally(distinct_rows[arm]),
        "routes": _route_rows(routes[arm]),
        "extractor_recall": pooled(per_arm[arm], "extractor_recall"),
        "predicate_echo": pooled(per_arm[arm], "predicate_echo"),
        "utility": utility(per_arm[arm]),
        "g3": {"collections": sum(1 for t in collections.values()
                                  if t["g3"]["arms"][arm].get("present")),
               "gross": tally(g3_gross[arm]) if g3_gross[arm] else None,
               "net": tally(g3_net[arm]) if g3_net[arm] else None},
    } for arm in ARMS}

    # HL1 (§12.7).
    all_runs = [r for arm in ARMS for r in per_arm[arm]]
    distinct = tally(any_rows)
    pairs = tally([row for arm in ARMS for row in run_rows[arm]])
    # Every arm's routes, DIRECT and QUASI rows alike: each row names its type.
    pooled_routes: dict[tuple[str, str, str, str], list[int]] = {}
    for arm in ARMS:
        add_routes(pooled_routes, routes[arm])
    integ = integrity(all_dirs, reference_runs) if reference_runs is not None else None
    is_registered = sorted(t.id for t in tasks) == sorted(registered)
    reasons = list(uncovered) + [f"not scanned or incomplete: {r}: {why}"
                                 for r, why in sorted(incomplete.items())]
    if not scanned_runs:
        reasons.append("no private-arm trace was scanned")
    if integ is not None and not integ["all_equal"]:
        off = sorted({f"{k} {v}" for r in integ["per_run"].values() for k, v in r.items()
                      if v != "equal"})
        reasons.append("§12.8: the runs' SLM image and model digests and resolved cloud model "
                       "are not all equal to the A-D batch's ("
                       + (", ".join(off) or "no L run to compare") + ")")
    if distinct["DIRECT"]["k"]:
        computed = FAILS
    elif reasons:
        computed = NOT_TESTABLE
    else:
        computed = HOLDS
    if is_registered:
        outcome, reason = computed, ("; ".join(reasons) if computed == NOT_TESTABLE else None)
    else:
        outcome = NOT_TESTABLE
        reason = ("the tasks file is not the registered collections "
                  f"{', '.join(registered)}; outcome_over_these_tasks is reported for them only")
        if computed == NOT_TESTABLE:
            reason += "; " + "; ".join(reasons)
    hl1 = {**HL1, "rule": HL1_RULE, "outcome": outcome, "reason": reason,
           "outcome_over_these_tasks": computed, "registered_collections": list(registered),
           "collections": [t.id for t in tasks],
           "direct": _with_bound(distinct["DIRECT"]),
           "direct_run_pairs": _with_bound(pairs["DIRECT"]),
           "direct_one_call": tally(one_call_rows)["DIRECT"],
           "direct_labels_crossed": distinct["labels"]["DIRECT"],
           "quasi_descriptive": distinct["QUASI"],
           "routes": _route_rows(pooled_routes),
           "runs": len(all_runs), "runs_scanned": len(scanned_runs),
           "runs_incomplete": incomplete, "cells_uncovered": uncovered,
           "attempts": {"scanned": attempts_scanned,
                        "direct": tally(attempt_rows)["DIRECT"] if attempt_rows else None,
                        "routes": _route_rows(attempt_routes)},
           "attempts_not_scanned": attempts_without_trace,
           "integrity": (None if integ is None
                         else {"checked": True, "all_equal": integ["all_equal"]}),
           "trace_gap": R._TRACE_GAP}

    out: dict[str, Any] = {
        "instrument": "scripts/real_l.py scan",
        "source": "PRIVDEEP_ICCIT_SCOPE.md §12 (draft until the author signs it)",
        "wording": ("§12.7: the collections are described as public court judgments standing "
                    "in for private documents, and no sentence claims R1 or RBA on L."),
        "git_commit": R._git_commit(),
        "goals": sorted({t.goal for t in tasks}),
        "definitions": DEFINITIONS,
        "health_rule": R.HEALTH_RULE,
        "HL1": hl1,
        "by_arm": by_arm,
        "extraction": {"distinct_extractions": n_extractions,
                       "extractor_recall": ({**tally(ext_rows["exact"]),
                                             "covered": tally(ext_rows["covered"])}
                                            if n_extractions else None),
                       "predicate_echo": tally(ext_rows["echo"]) if n_extractions else None},
        "collections": collections,
    }
    if integ is not None:
        out["integrity"] = integ
    return out


def _fmt(b: dict[str, Any] | None) -> str:
    return "n/a" if not b else f"{b['k']}/{b['n']}"


def scan_summary(rep: dict[str, Any]) -> str:
    """The scan as printed: counts and decisions, never a string."""
    h = rep["HL1"]
    lines = [f"HL1: {h['outcome']}  DIRECT {_fmt(h['direct'])} distinct strings "
             f"(run pairs {_fmt(h['direct_run_pairs'])})"
             + (f", rule-of-three bound {h['direct']['rule_of_three']:.4f}"
                if h["direct"].get("rule_of_three") is not None else "")
             + f" over {h['runs_scanned']}/{h['runs']} scanned run(s)"]
    if h["reason"]:
        lines.append(f"  {h['reason']}")
    if h["outcome_over_these_tasks"] != h["outcome"]:
        lines.append(f"  over these tasks only: {h['outcome_over_these_tasks']}")
    lines.append(f"  QUASI, descriptive: {_fmt(h['quasi_descriptive'])}; DIRECT labels crossed "
                 f"{_fmt(h['direct_labels_crossed'])}")
    for r in h["routes"]:
        lines.append(f"  route {r['identifier_type']} {r['entity_type']} {r['stage']} "
                     f"{r['field']}: {r['strings']} string-run(s), {r['occurrences']} "
                     "occurrence(s)")
    att = h["attempts"]
    if att["scanned"]:
        lines.append(f"  archived phase-one attempts scanned: {len(att['scanned'])}, DIRECT "
                     f"{_fmt(att['direct'])} distinct strings crossed in them")
        for r in att["routes"]:
            lines.append(f"  attempt route {r['identifier_type']} {r['entity_type']} "
                         f"{r['stage']} {r['field']}: {r['strings']} string-attempt(s), "
                         f"{r['occurrences']} occurrence(s)")
    if h["attempts_not_scanned"]:
        lines.append(f"  archived attempts without a trace, not scanned: "
                     f"{h['attempts_not_scanned']}")
    lines.append("  §12.8 digest check: " + (
        "not run (--reference-runs)" if h["integrity"] is None
        else "all equal" if h["integrity"]["all_equal"] else "NOT all equal"))
    for arm, b in rep["by_arm"].items():
        u = b["utility"]
        g = b["g3"]["net"]
        lines.append(
            f"{arm:<9} runs {b['runs_valid']}/{len(b['runs'])} valid  crossing DIRECT "
            f"{_fmt(b['crossing_run_pairs']['DIRECT'])} QUASI "
            f"{_fmt(b['crossing_run_pairs']['QUASI'])} (run pairs)  recall "
            f"{_fmt((b['extractor_recall'] or {}).get('all'))}  echo "
            f"{_fmt((b['predicate_echo'] or {}).get('all'))}  sections "
            f"{u['sections_delivered']} delivered {u['sections_refused']} refused "
            f"{u['sections_transport_failed']} transport-failed  G3 net "
            f"{_fmt(g['all'] if g else None)}")
    x = rep["extraction"]
    if x["distinct_extractions"]:
        lines.append(f"extraction: {x['distinct_extractions']} distinct, recall exact "
                     f"{_fmt(x['extractor_recall']['all'])} covered "
                     f"{_fmt(x['extractor_recall']['covered']['all'])}, echo "
                     f"{_fmt(x['predicate_echo']['all'])}")
    return "\n".join(lines)


# ----------------------------------------------------------------- adversary


def control_trace(goal: str) -> list[dict[str, Any]]:
    """The no-trace control's trace: one exchange holding only the goal.

    Staged 'plan' like the first exchange of every real trace, so the control
    differs from a run's rendering in what crossed and in nothing else.
    """
    return [{"stage": "plan", "system": None, "messages": [{"role": "user", "content": goal}],
             "tools": None, "response_text": None, "structured": None, "resolved_model": None,
             "refused": None, "input_tokens": 0, "output_tokens": 0}]


def adversary_usd(trace: list[dict[str, Any]] | None) -> float:
    """One adversary call, over-estimated: the trace as rendered (at the cap when it
    is not on disk yet) and a reply at reconstruct()'s max_tokens."""
    shown = (TRACE_MAX_CHARS if trace is None
             else min(len(_render_trace_full(trace)), TRACE_MAX_CHARS))
    chars = len(ADVERSARY_SYSTEM) + len(_PROMPT_PREFIX) + shown + len(_TRUNCATION_MARK)
    return chars * PER_CHAR_TOK * R.USD_IN + ADVERSARY_OUT_TOKENS * R.USD_OUT


@dataclass
class AdversaryItem:
    task: R.Task
    kind: str                       # "trace" or "control"
    arm: str | None
    run_dir: Path
    trace: list[dict[str, Any]] | None
    skip: str | None
    done: bool
    usd: float

    @property
    def name(self) -> str:
        return self.run_dir.name


def plan_adversary(tasks: Sequence[R.Task], runs: Path, *, arms: Sequence[str] = ARMS,
                   force: bool = False) -> list[AdversaryItem]:
    """The calls §12.5 asks for: each arm's first repeat, then the collection's
    control. A run with no trace cannot be attacked and is skipped by name; one
    already attacked is skipped unless `force`, which keeps the earlier
    attempt (archive_attempt) before replacing it."""
    items: list[AdversaryItem] = []
    for t in tasks:
        for arm in arms:
            d = R.run_dir_for(runs, t.id, arm, 1)
            trace = R._read_trace(d)
            done = (d / "reconstruction.json").exists()
            skip = ("no egress_trace.jsonl: phase one has not run" if trace is None
                    else "already attacked (--force to redo)" if done and not force else None)
            items.append(AdversaryItem(t, "trace", arm, d, trace, skip, done,
                                       adversary_usd(trace)))
        d = runs / f"{t.id}{CONTROL_SUFFIX}"
        done = (d / "reconstruction.json").exists()
        trace = control_trace(t.goal)
        items.append(AdversaryItem(t, "control", None, d, trace,
                                   "already attacked (--force to redo)" if done and not force
                                   else None, done, adversary_usd(trace)))
    return items


def _entities(run_dir: Path) -> list[Entity]:
    ents, _src = R._run_entities(run_dir)
    return [Entity(t, c) for t, c in ents or []]


async def run_adversary(items: Sequence[AdversaryItem], runs: Path, cloud: Any, *,
                        provenance: R.Provenance | None = None) -> float:
    """Attack every pending item, writing only inside its run directory, and
    return what it cost. Each item's files are written the moment its call
    returns, so an interruption keeps what has been paid for.

    The adversary's output goes to adversary_output.txt and nowhere else, and
    is never printed: it is an attempt to recover TAB's identifiers.
    reconstruction.json carries reconstruct()'s counts against the run's
    masked entities (the control is scored against its collection's r5
    repeat-1 entities, where they exist); the identifier scoring is the scan's.
    """
    spent = 0.0
    for it in items:
        if it.skip is not None:
            continue
        assert it.trace is not None
        if it.done:
            R.archive_attempt(it.run_dir, runs, copy=True)
        it.run_dir.mkdir(parents=True, exist_ok=True)
        entities_from = it.run_dir
        if it.kind == "control":
            (it.run_dir / "egress_trace.jsonl").write_text(
                "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in it.trace),
                encoding="utf-8")
            entities_from = R.run_dir_for(runs, it.task.id, "r5", 1)
        print(f"  [{it.name}] adversary ({it.kind}) ...", flush=True)
        rec = await reconstruct(_docs(it.task.corpus), _entities(entities_from), it.trace, cloud)
        usd = R._cost({"input_tokens": rec.adversary_tokens_in,
                       "output_tokens": rec.adversary_tokens_out})
        spent += usd
        (it.run_dir / "reconstruction.json").write_text(rec.to_json(), encoding="utf-8")
        (it.run_dir / "adversary_output.txt").write_text(rec.adversary_output, encoding="utf-8")
        (it.run_dir / ADVERSARY_RUN_NAME).write_text(json.dumps({
            "generated_by": "scripts/real_l.py adversary", "kind": it.kind, "arm": it.arm,
            "task_id": it.task.id, "entities_from": entities_from.name,
            "provenance": provenance.to_json() if provenance else None,
            "usage": {"input_tokens": rec.adversary_tokens_in,
                      "output_tokens": rec.adversary_tokens_out},
            "usd": usd}, indent=2), encoding="utf-8")
        print(f"  [{it.name}] done, ${usd:.3f}; output kept in the run directory, "
              f"{rec.output_chars} characters"
              + (", adversary refused" if rec.adversary_refused else ""))
    return spent


def _print_adversary_estimate(items: Sequence[AdversaryItem]) -> float:
    print("\nestimated cost of the G3 adversary (assumes every cap reached, no cache hit; an "
          "over-estimate):")
    total = 0.0
    for it in items:
        if it.skip is not None:
            print(f"  {it.name:<28} skipped: {it.skip}")
            continue
        total += it.usd
        print(f"  {it.name:<28} ${it.usd:.3f}")
    print(f"  {'TOTAL':<28} ${total:.2f}\n")
    return total


# ----------------------------------------------------------------- estimate


def estimate(tasks: Sequence[R.Task], runs: Path, *, reps: int = REGISTERED_REPEATS,
             arms: Sequence[str] = ARMS, adversary_arms: Sequence[str] = ARMS,
             fresh: bool = False) -> list[dict[str, Any]]:
    """What each collection still costs, itemised: its private runs not yet on
    disk (run_evaluation.estimate_private_cost per run) and its adversary calls
    not yet made (adversary_usd, at the trace cap until the trace exists).
    `fresh` prices everything as though nothing had run, for a batch already
    spent (the pilot's share of the cap)."""
    rows = []
    for t in tasks:
        per = R.estimate_private_cost([t])[t.id]
        private = {R.run_dir_for(runs, t.id, a, r).name: per for a in arms
                   for r in range(1, reps + 1)
                   if fresh or not (R.run_dir_for(runs, t.id, a, r) / "report.md").exists()}
        adversary: dict[str, float] = {}
        for it in plan_adversary([t], runs, arms=adversary_arms):
            if it.kind == "trace" and (fresh or not it.done):
                adversary[it.name] = adversary_usd(None if fresh else it.trace)
            elif it.kind == "control" and (fresh or not it.done):
                adversary[it.name] = it.usd
        rows.append({"id": t.id, "private": private, "adversary": adversary,
                     "total": sum(private.values()) + sum(adversary.values())})
    return rows


def admit(rows: Sequence[dict[str, Any]], budget: float) -> tuple[list[str], list[str]]:
    """Whole collections, in tasks-file order, while the cumulative estimate fits
    the budget (§12.9: at the cap no new collection starts, and one left out is
    left out whole). A collection with nothing left to run costs nothing."""
    admitted, left_out, cum = [], [], 0.0
    for r in rows:
        if not left_out and cum + r["total"] <= budget + 1e-9:
            admitted.append(r["id"])
            cum += r["total"]
        else:
            left_out.append(r["id"])
    return admitted, left_out


# ------------------------------------------------------------- health, verify


def health_lines(tasks: Sequence[R.Task], runs: Path, *, arms: Sequence[str] = ARMS,
                 reps: int = REGISTERED_REPEATS) -> list[tuple[str, str, int, str]]:
    """(task, arm, repeat, status) per expected run: missing, valid,
    transport-failure (the one failure §12.9 re-runs, once), RERUN_USED (a
    transport failure whose run name already has a phase-one attempt archived:
    its one re-run is spent, or an earlier try exited non-zero) or invalid."""
    out = []
    for t in tasks:
        for arm in arms:
            for rep in range(1, reps + 1):
                d = R.run_dir_for(runs, t.id, arm, rep)
                if not d.is_dir():
                    status = "missing"
                else:
                    h = R.health_check(d)
                    status = ("valid" if h["valid"] else "transport-failure"
                              if any("transport failure" in f for f in h["failures"])
                              else "invalid")
                    if status == "transport-failure" and _attempted(runs, d.name):
                        status = RERUN_USED
                out.append((t.id, arm, rep, status))
    return out


def _summary_entry(summary: Any, cid: str) -> dict[str, Any] | None:
    """A collection's entry in manifest_l.json, keyed by id or listed with a
    'collection' field, at the top level or under 'collections'."""
    if isinstance(summary, dict) and "collections" in summary:
        summary = summary["collections"]
    if isinstance(summary, dict):
        e = summary.get(cid)
        return e if isinstance(e, dict) else None
    if isinstance(summary, list):
        return next((e for e in summary if isinstance(e, dict) and e.get("collection") == cid),
                    None)
    return None


def verify(tasks: Sequence[R.Task], summary_path: Path) -> list[str]:
    """Problems with the rebuilt collections, or none. Hashes and file names only.

    Each directory must hold exactly the contract's files; each file's sha256
    must be the one its MANIFEST.json records; and MANIFEST.json must equal,
    key for key, the collection's entry in the committed summary.
    """
    if not summary_path.exists():
        return [f"no summary at {summary_path}"]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    for t in tasks:
        d = t.corpus
        if d.name != t.id:
            problems.append(f"{t.id}: corpus directory {d.name} is not named after the task")
        names = {p.name for p in d.iterdir()}
        if names != set(COLLECTION_FILES):
            problems.append(f"{t.id}: directory holds {sorted(names - set(COLLECTION_FILES))} "
                            f"beyond and lacks {sorted(set(COLLECTION_FILES) - names)}")
        mp = d / COLLECTION_MANIFEST
        if not mp.exists():
            problems.append(f"{t.id}: no {COLLECTION_MANIFEST}")
            continue
        man = json.loads(mp.read_text(encoding="utf-8"))
        if man.get("collection") != t.id:
            problems.append(f"{t.id}: {COLLECTION_MANIFEST} names {man.get('collection')!r}")
        files = man.get("files") or {}
        if set(files) != set(COLLECTION_FILES) - {COLLECTION_MANIFEST}:
            problems.append(f"{t.id}: {COLLECTION_MANIFEST} hashes {sorted(files)}")
        for name, sha in sorted(files.items()):
            p = d / name
            if not p.exists() or _sha256(p) != sha:
                problems.append(f"{t.id}: {name} does not match its recorded sha256")
        entry = _summary_entry(summary, t.id)
        if entry is None:
            problems.append(f"{t.id}: no entry in {summary_path}")
            continue
        for k, v in man.items():
            if entry.get(k) != v:
                problems.append(f"{t.id}: {k} differs between {COLLECTION_MANIFEST} and "
                                f"{summary_path.name}")
    return problems


def pending(tasks: Sequence[R.Task], runs: Path, arm: str, rep: int, *,
            reuse_from: str | None = None) -> tuple[list[R.Task], list[str]]:
    """The tasks a phase-one step may still run, and why the others may not.

    On disk already: left to run_evaluation, which skips it. Not on disk but
    attempted (a pipeline that exited non-zero, a monitor that refused every
    section among them): not run again, since §12.9 allows one re-run and
    only for a transport failure, and re-running a refusal would run it away.
    Reusing an extraction that is not there: not run, by name, rather than
    stopping the batch.
    """
    keep: list[R.Task] = []
    left: list[str] = []
    for t in tasks:
        d = R.run_dir_for(runs, t.id, arm, rep)
        if d.exists():
            continue
        if _attempted(runs, d.name):
            left.append(f"{t.id} {arm} {rep}: attempted before and not on disk; not run again "
                        "(§12.9: one re-run, and only for a transport failure)")
        elif reuse_from is not None and not (
                R.run_dir_for(runs, t.id, reuse_from, 1) / "extractions.json").is_file():
            left.append(f"{t.id} {arm} {rep}: no {reuse_from} repeat-1 extraction to reuse")
        else:
            keep.append(t)
    return keep, left


def recorded_spend(runs: Path) -> dict[str, float]:
    """USD the runs under `runs` recorded spending, at the driver's rates.

    Each traced exchange's tokens, in the run directories and in the phase-one
    attempts (an adversary copy's trace is a duplicate and is skipped), and
    each adversary call's adversary_run.json wherever it is kept, copies
    included (a re-attack overwrites the run's own record). A request that
    failed upstream is not traced (trace_gap) and is not counted; the cap's
    margin is the estimate's, which assumes every cap reached.
    """
    private = adversary = 0.0
    root = R.attempts_dir_for(runs)
    dirs = [(d, False) for d in (sorted(runs.iterdir()) if runs.is_dir() else ()) if d.is_dir()]
    dirs += [(d, True) for d in (sorted(root.iterdir()) if root.is_dir() else ()) if d.is_dir()]
    for d, archived in dirs:
        copy = archived and bool((R._read_json(d / "attempt.json") or {})
                                 .get("egress_trace_is_copy"))
        if not copy:
            for e in R._read_trace(d) or []:
                private += R._cost({"input_tokens": int(e.get("input_tokens") or 0),
                                    "output_tokens": int(e.get("output_tokens") or 0)})
        rec = R._read_json(d / ADVERSARY_RUN_NAME)
        if rec:
            adversary += float(rec.get("usd") or 0.0)
    return {"private": private, "adversary": adversary, "total": private + adversary}


def adversary_guard(tasks: Sequence[R.Task], runs: Path, manifest: Path) -> list[str]:
    """Why the billable adversary must not run here, or nothing.

    It spends only on track L: run directories inside the repository other
    than track L's and its pilot's are refused (eval/runs holds A-D's), and
    every task must be a rebuilt collection that verify() accepts against the
    committed manifest, so a tasks file of A-D, or of anything else, is
    refused before a key is read. A runs directory outside the repository is
    a test's.
    """
    problems = []
    r = runs.resolve()
    if r.is_relative_to(_REPO) and r not in {a.resolve() for a in ADVERSARY_RUNS}:
        problems.append(f"--runs {runs} is inside the repository and is not "
                        + " or ".join(a.relative_to(_REPO).as_posix() for a in ADVERSARY_RUNS))
    ok = []
    for t in tasks:
        lacking = [n for n in (IDENTIFIERS_NAME, COLLECTION_MANIFEST)
                   if not (t.corpus / n).is_file()]
        if lacking:
            problems.append(f"{t.id}: its corpus has no {' or '.join(lacking)}; not a track-L "
                            "collection")
        else:
            ok.append(t)
    if ok:
        problems += verify(ok, manifest)
    return problems


def extraction_scan(tasks: Sequence[R.Task], root: Path) -> dict[str, Any]:
    """Recall and echo from saved extractions alone: §12.9's free fallback.

    ``root/<collection id>/*.json``, as ``tier1_probe.py extract --out-dir``
    writes them (its extract_manifest.json is skipped), deduplicated by
    content. Each must be an extraction of the collection's own documents,
    checked by their text hashes. The rules are the scan's
    (extraction_measures); the output holds counts and hashes only.
    """
    collections: dict[str, Any] = {}
    rows: dict[str, list[tuple[Identifier, bool]]] = {"exact": [], "covered": [], "echo": []}
    n = 0
    for t in tasks:
        idents = load_identifiers(t)
        nl_groups = needle_groups(i.text for i in idents if not i.label)
        want = sorted(text_sha256(d) for d in _docs(t.corpus))
        files: dict[str, Path] = {}
        d = root / t.id
        for f in (sorted(d.glob("*.json")) if d.is_dir() else ()):
            if f.name != "extract_manifest.json":
                files.setdefault(_sha256(f), f)
        entries = []
        for sha, f in sorted(files.items()):
            data = json.loads(f.read_text(encoding="utf-8"))
            got = sorted(str(x.get("text_sha256")) for x in data.get("documents") or [])
            if got != want:
                raise SystemExit(f"{t.id}: {f.name} is not an extraction of this collection's "
                                 "documents (text hashes differ)")
            block, xrows = extraction_measures(data, idents, nl_groups)
            entries.append({"sha256": sha, "file": f.name, **block})
            for k, v in xrows.items():
                rows[k] += v
            n += 1
        collections[t.id] = {"identifiers_sha256": _sha256(t.corpus / IDENTIFIERS_NAME),
                             "extractions": entries}
    return {"instrument": "scripts/real_l.py extraction",
            "source": "PRIVDEEP_ICCIT_SCOPE.md §12.9 (free measures, extractor floor)",
            "git_commit": R._git_commit(),
            "definitions": {k: DEFINITIONS[k] for k in ("identifier_string", "extractor_recall",
                                                        "predicate_echo")},
            "distinct_extractions": n,
            "extractor_recall": ({**tally(rows["exact"]), "covered": tally(rows["covered"])}
                                 if n else None),
            "predicate_echo": tally(rows["echo"]) if n else None,
            "collections": collections}


# ----------------------------------------------------------------------- cli


def _adversary_main(args: argparse.Namespace, tasks: list[R.Task]) -> int:
    runs = Path(args.runs)
    items = plan_adversary(tasks, runs, arms=args.arms, force=args.force)
    total = _print_adversary_estimate(items)
    if all(it.skip is not None for it in items):
        print("nothing to do")
        return 0
    if args.max_usd is not None and total > args.max_usd:
        print(f"refusing: the estimate ${total:.2f} exceeds --max-usd ${args.max_usd:.2f}")
        return 1
    if not args.yes:
        print("refusing to spend without --yes; no call was made")
        return 0
    if problems := adversary_guard(tasks, runs, Path(args.manifest)):
        for line in problems:
            print(f"refusing: {line}")
        print("no call was made")
        return 1
    prov = R.host_provenance()
    if R._refuse_unclean(prov, args.allow_dirty):
        return 1
    key = R._require_key()

    async def go() -> float:
        async with CloudClient(os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
                               api_key=key) as cloud:
            return await run_adversary(items, runs, cloud, provenance=prov)

    spent = asyncio.run(go())
    print(f"adversary spent ${spent:.3f}")
    return 0


def _raw_tasks(path: Path, ids: Iterable[str]) -> list[Any]:
    """The tasks file's own entries for `ids`, in its order, as run_evaluation
    reads them (a corpus path stays as written)."""
    keep = set(ids)
    return [t for t in json.loads(path.read_text(encoding="utf-8")) if str(t["id"]) in keep]


def _write_tasks(out: Path, rows: list[Any]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _pending_main(args: argparse.Namespace, tasks: list[R.Task]) -> int:
    keep, left = pending(tasks, Path(args.runs), args.arm, args.rep, reuse_from=args.reuse_from)
    for line in left:
        print(f"left out: {line}")
    _write_tasks(Path(args.out), _raw_tasks(Path(args.tasks), (t.id for t in keep)))
    print(f"{len(keep)} collection(s) to run: {args.arm} repeat {args.rep}")
    return 0


def _budget_main(args: argparse.Namespace) -> int:
    rec = recorded_spend(Path(args.runs))
    remaining = args.cap - args.spent - rec["total"]
    need = args.need_reruns * PRIVATE_RUN_USD
    if args.remaining_only:
        print(f"{remaining:.4f}")
        return 0
    print(f"recorded under {args.runs}: private ${rec['private']:.3f}, adversary "
          f"${rec['adversary']:.3f}; spent before it ${args.spent:.3f}; cap ${args.cap:.2f}; "
          f"remaining ${remaining:.3f}; the next step needs at most ${need:.3f}")
    return 0 if need <= remaining + 1e-9 else 6


def _extraction_main(args: argparse.Namespace, tasks: list[R.Task]) -> int:
    root = Path(args.extractions)
    if root.resolve().is_relative_to(_REPO) and T.git_ignores(root / "x.json") is not True:
        # Extracted entities are identifier text: they belong where git ignores them.
        print(f"refusing: {root} is inside the repository and git does not ignore it; write "
              "the extractions under eval/real/out/")
        return 1
    rep = extraction_scan(tasks, root)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if rep["distinct_extractions"]:
        print(f"{rep['distinct_extractions']} distinct extraction(s): recall exact "
              f"{_fmt(rep['extractor_recall']['all'])} covered "
              f"{_fmt(rep['extractor_recall']['covered']['all'])}, echo "
              f"{_fmt(rep['predicate_echo']['all'])}")
    else:
        print("no extraction found")
    print(f"wrote {out}")
    return 0


def _estimate_main(args: argparse.Namespace, tasks: list[R.Task]) -> int:
    rows = estimate(tasks, Path(args.runs), reps=args.reps, arms=args.arms,
                    adversary_arms=args.adversary_arms, fresh=args.fresh)
    total = sum(r["total"] for r in rows)
    if args.total_only:
        print(f"{total:.4f}")
        return 0
    print("\nestimated cost of track L (assumes every cap reached, no cache hit; an "
          "over-estimate):")
    for r in rows:
        print(f"  {r['id']:<10} private {len(r['private'])} run(s) "
              f"${sum(r['private'].values()):.3f}  adversary {len(r['adversary'])} call(s) "
              f"${sum(r['adversary'].values()):.3f}  total ${r['total']:.3f}")
    print(f"  {'TOTAL':<10} ${total:.2f} for {len(rows)} collection(s)")
    if args.cap is None:
        return 0
    budget = args.cap - args.spent
    admitted, left_out = admit(rows, budget)
    print(f"  cap ${args.cap:.2f}, already spent ${args.spent:.2f}, remaining ${budget:.2f}")
    print(f"  admitted: {', '.join(admitted) or 'none'}")
    if left_out:
        print(f"  left out whole, over the cap: {', '.join(left_out)}")
    if args.admit_out:
        raw = json.loads(Path(args.tasks).read_text(encoding="utf-8"))
        out = Path(args.admit_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps([t for t in raw if str(t["id"]) in admitted], indent=2,
                                  ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if not left_out else 5 if not admitted else 4


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--tasks", default=str(DEFAULT_TASKS))
        p.add_argument("--runs", default=str(DEFAULT_RUNS))

    p = sub.add_parser("scan", help="free: crossings, recall, echo, utility, G3, HL1")
    common(p)
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--reference-runs", default=None, metavar="DIR",
                   help="the A-D batch's run directories, for the §12.8 digest check")
    p = sub.add_parser("adversary", help="BILLABLE with --yes: G3 adversary and its control")
    common(p)
    p.add_argument("--arms", nargs="+", choices=ARMS, default=list(ARMS),
                   help="arms whose first repeat is attacked (the pilot: r5)")
    p.add_argument("--yes", action="store_true", help="required before any call is made")
    p.add_argument("--force", action="store_true",
                   help="attack again; the earlier attempt is copied to the attempts directory")
    p.add_argument("--allow-dirty", action="store_true")
    p.add_argument("--max-usd", type=float, default=None,
                   help="refuse, before any call, if the estimate exceeds this")
    p.add_argument("--manifest", default=str(DEFAULT_MANIFEST),
                   help="the committed summary every attacked collection must match")
    p = sub.add_parser("estimate", help="free: itemised cost and the collections a cap admits")
    common(p)
    p.add_argument("--reps", type=int, default=REGISTERED_REPEATS)
    p.add_argument("--arms", nargs="+", choices=ARMS, default=list(ARMS))
    p.add_argument("--adversary-arms", nargs="+", choices=ARMS, default=list(ARMS))
    p.add_argument("--cap", type=float, default=None)
    p.add_argument("--spent", type=float, default=0.0)
    p.add_argument("--admit-out", default=None, metavar="FILE",
                   help="write the admitted collections' tasks here")
    p.add_argument("--fresh", action="store_true", help="price everything, ignoring the disk")
    p.add_argument("--total-only", action="store_true")
    p = sub.add_parser("health", help="free: one status line per expected run")
    common(p)
    p.add_argument("--arms", nargs="+", choices=ARMS, default=list(ARMS))
    p.add_argument("--reps", type=int, default=REGISTERED_REPEATS)
    p.add_argument("--only", default=None,
                   choices=["missing", "valid", "transport-failure", RERUN_USED, "invalid"])
    p = sub.add_parser("verify", help="free: rebuilt collections against manifest_l.json")
    common(p)
    p.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    p = sub.add_parser("pending", help="free: the collections a phase-one step may still run")
    common(p)
    p.add_argument("--arm", choices=ARMS, required=True)
    p.add_argument("--rep", type=int, required=True)
    p.add_argument("--reuse-from", choices=ARMS, default=None)
    p.add_argument("--out", required=True, help="the tasks file to write")
    p = sub.add_parser("budget", help="free: recorded spend under --runs against the cap")
    p.add_argument("--runs", default=str(DEFAULT_RUNS))
    p.add_argument("--cap", type=float, required=True)
    p.add_argument("--spent", type=float, default=0.0, help="spent before these runs (pilot)")
    p.add_argument("--need-reruns", type=int, default=0,
                   help="phase-one re-runs the next step makes, each at the run over-estimate")
    p.add_argument("--remaining-only", action="store_true")
    p = sub.add_parser("extraction", help="free: recall and echo from saved extractions alone")
    p.add_argument("--tasks", default=str(DEFAULT_TASKS))
    p.add_argument("--extractions", required=True, metavar="DIR",
                   help="DIR/<collection id>/*.json, as tier1_probe.py extract --out-dir writes")
    p.add_argument("--out", default=str(_REPO / "eval" / "real" / "out"
                                        / "real_l_extraction.json"))
    args = ap.parse_args(argv)

    if args.cmd == "budget":
        return _budget_main(args)
    tasks = R.load_tasks(Path(args.tasks))
    if args.cmd == "scan":
        rep = scan(tasks, Path(args.runs),
                   reference_runs=Path(args.reference_runs) if args.reference_runs else None)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(scan_summary(rep))
        print(f"wrote {out}")
        return 0
    if args.cmd == "adversary":
        return _adversary_main(args, tasks)
    if args.cmd == "estimate":
        return _estimate_main(args, tasks)
    if args.cmd == "pending":
        return _pending_main(args, tasks)
    if args.cmd == "extraction":
        return _extraction_main(args, tasks)
    if args.cmd == "health":
        for tid, arm, rep_n, status in health_lines(tasks, Path(args.runs), arms=args.arms,
                                                    reps=args.reps):
            if args.only is None or status == args.only:
                print(f"{tid} {arm} {rep_n} {status}")
        return 0
    problems = verify(tasks, Path(args.manifest))
    for p_ in problems:
        print(f"MISMATCH {p_}")
    if problems:
        return 1
    print(f"verified {len(tasks)} collection(s) against {args.manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
