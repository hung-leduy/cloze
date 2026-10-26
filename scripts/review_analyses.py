#!/usr/bin/env python3
"""Analyses from frozen data that the simulated review of 2026-10-10 asks for.

Why this exists
---------------
``paper/reviews/critical_review_2026-10-10.md`` is a simulated review written by
the AI assistant. Among its fixes the author chose the text-only ones and the
analyses from frozen data: figures the frozen A-D batch of 2026-10-07 already
holds but the paper does not state. This script computes them, offline and
free, from the frozen inputs, and writes ``eval/paper/review_analyses.json``;
``make_paper_tables.py --review-analyses`` turns each figure into a «key».
Written by the AI assistant on 2026-10-10.

Every analysis here is post hoc and exploratory. None tests a registered
hypothesis, and none changes an instrument, a gold key, a lexicon or a frozen
number (PRIVDEEP_ICCIT_SCOPE.md §8.7-§8.9). Where an analysis rescores a report
it uses the frozen scorer (``privdeep.eval.faithfulness.score``), and it first
checks that the frozen key reproduces the run's ``measurement.json`` exactly,
so a figure beside a frozen one is the same instrument's. Inputs are read-only.

What it computes (review item: section of the output)
----------------------------------------------------
* MR3a ``resolution``: for every pooled run and its oracle report, the scorer's
  own denominators: occurrences scanned (numerals and spelled-out gold values),
  gold-valued occurrences, and those whose referent, attribute and both the rule
  resolved; summed per arm and corpus and per arm, with each run's resolution
  rates (resolved over gold-valued). While a calibration sheet is not fully
  labelled, the run whose report it describes, and every run of the same corpus
  and arm (whose records would give it by subtraction), count in their cell and
  arm and have their own records withheld (the labelling instructions say not to
  open that run's measurement before the sheet is finished).
* MR3b ``lexical_overlap``: which RBA attribute-lexicon phrases (the gold keys'
  ``attributes``, the scoring side; not the header lexicon of R1's structural
  route) occur in the 13 R1 code meanings the drafter is shown
  (``privdeep.models.facts.ATTRIBUTE_MEANINGS``), found by the scorer's own
  longest-match regex, and which attribute each binds to; whether every r1
  drafter request carried that block; and, per arm, how many lexicon hits the
  reports make and how many fall on a phrase the meanings contain.
* MR3b ``coverage_split``: coverage_correct over the key's document-stated facts
  and over its derived facts (``derived``: no document states them), per arm
  and corpus, and for the oracle.
* MR3b ``without_share_spent``: corpus A rescored with its key minus the
  share-spent facts and their attribute (``PCT_SPENT``, added to A's key after
  the first r1 run stated these shares), per arm and for the oracle.
* MR4b ``binding``: what each arm's payload lets the cloud bind. Baseline and
  r5 list MONEY slots in canonical order and no relation names a slot, so
  nothing on the wire says which MONEY slot is which referent's which
  attribute. The chance model, stated plainly: the drafter's choice of MONEY
  slot is independent of the referent and attribute its sentence names. An
  occurrence whose attribute the rule resolves to *a* is then a MATCH with
  probability p_a, the share of the run's gold-valued MONEY slots whose value
  carries *a*; and a both-resolved occurrence naming referent *r* is CORRECT
  with probability p_(r,a). The expected (chance) accuracy is the mean of p
  over the run's resolved money occurrences, given the attributes the rule
  resolved; the observed accuracy over the same occurrences is beside it. r1
  receives no MONEY slot: its cloud names a referent slot and one of 13 codes,
  and the value is resolved locally, so the value-referent-attribute triple is
  fixed by the reference; the store's fact count is given.
* MR2 ``calibration``: for each calibration row (``make_paper_tables.CAL_ROWS``,
  from its report, its labels and the frozen rule through
  ``scripts/calibrate_faithfulness.py``), over gold-valued occurrences on the
  attribute axis, whose three categories are MATCH (correct), MISMATCH
  (misbound) and UNRESOLVED: each reader's label counts, the 3x3 confusion
  counts (human by rule), raw agreement, Cohen's kappa and its chance agreement,
  PABAK and Gwet's AC1 (both over the three categories), and a percentile
  bootstrap 95% interval for kappa (occurrences resampled with replacement,
  seeded per row, so a row's interval does not move when another row is added;
  a resample on which kappa is undefined is left out and counted). Occurrences
  in one sentence are not independent, which the bootstrap ignores. A row whose
  sheet is not yet labelled, or only partly, gives its status and no figures.
  The four rows calibration.json records must reproduce exactly.
* MR9a ``corpus_stats``: per corpus, documents, characters and words of the
  loaded text (whitespace-separated tokens), table data cells (the aggregate's
  rule), referents, and the key's facts by kind: stated in a table (a numeric
  table data cell whose value is the fact's, in a row whose key cell names the
  fact's subject), stated in prose only (every other stated fact, including a
  value written inside a table cell's sentence), and derived.
* MR9b ``maskdoc_without_lost``: the masked-document exposure of every probe
  extraction, with any document the extraction lost (every extractor reply
  dropped, no entity and no relation; on C, document 73087ca0…) left out: it was
  never masked, and a sanitiser would fail closed on it. The filter still indexes
  the whole corpus, as deployed. An extraction that lost nothing keeps the
  probe's own figures; one that lost a document is recomputed with
  tier1_probe.py's masking, after the full recomputation reproduces the probe.
* Minor 8 ``cost``: per run, the deployment cost (phase one: planner and
  drafter, from the egress trace's tokens at run_evaluation.py's list rates)
  apart from the evaluation cost (oracle, judge, adversary, from the
  measurement), and phase one's wall-clock time from the manifest, with the
  runs that ran the local extraction apart from those that reused it.

Output
------
Counts, rates, constants and repository paths only: never a report sentence,
a gold value or a corpus string beyond the constant lexicon phrases and code
meanings, so the file can sit beside numbers.json. ``inputs`` records the
sha256 of every file read (the run files as one digest), and make_paper_tables
refuses an analysis built from another evaluation.json, observation.json or
calibration.json than the one it is given. The bootstrap is seeded; the same
inputs give the same bytes.

Run it from the checkout root with either interpreter; it needs the frozen run
directories (``eval/runs/``, gitignored) and, for the in-sample calibration row,
the pilot report that row's labels describe (``--insample-report``; without it
that row gives no figures).
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import math
import random
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "backend" / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from privdeep.eval.faithfulness import (  # noqa: E402
    CORRECT,
    FABRICATED,
    MATCH,
    MISMATCH,
    UNRESOLVED,
    FactKey,
    FaithfulnessResult,
    _correctly_bound,
    de_escape,
    load_key,
    score,
)
from privdeep.ingest import SUFFIXES, load  # noqa: E402
from privdeep.models.facts import (  # noqa: E402
    ATTRIBUTE_CODES,
    ATTRIBUTE_MEANINGS,
    REFERENT_CATEGORIES,
)
from privdeep.tier1_local.normalise import canonical_key  # noqa: E402
from privdeep.tier3_reconcile.citation_grounder import _NUM_RE  # noqa: E402

from scripts import calibrate_faithfulness as CF  # noqa: E402
from scripts import run_evaluation as R  # noqa: E402
from scripts import tier1_probe as T  # noqa: E402
from scripts.make_paper_tables import CAL_ROWS  # noqa: E402

__all__ = ["CAL_SOURCES", "CODE_ATTRIBUTE", "agreement", "bootstrap_kappa", "build",
           "chance_cell", "coverage_split", "fact_kinds", "gwet_ac1", "kappa_chance",
           "lexical_overlap", "main", "money_slots", "pabak", "pending_blind_runs",
           "percentile_ci"]

INSTRUMENT = "scripts/review_analyses.py"
DEFAULT_OUT = _REPO / "eval" / "paper" / "review_analyses.json"
ARMS = ("baseline", "r5", "r1")
SLOT_ARMS = ("baseline", "r5")          # the arms whose payload carries MONEY slots
CATEGORIES = (MATCH, MISMATCH, UNRESOLVED)   # the attribute axis's verdicts
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261010
# The R1 codes whose value an RBA attribute names (the money codes); the other
# eight (dates, owner, site, code, quantities, status) have no RBA attribute.
CODE_ATTRIBUTE: dict[str, str] = {
    "AUTHAMT": "AUTHORISED", "SPENTAMT": "SPENT", "UNSPNTAM": "UNSPENT",
    "OVRRUNAM": "OVERRUN", "PCTSPENT": "PCT_SPENT",
}
# The share-spent facts and their attribute: added to A's key after the first
# r1 run on A stated these shares (commit 9d8d4c6; paper §5 "Corpora").
SHARE_SPENT = "PCT_SPENT"
SHARE_SPENT_LETTER = "A"
# The in-sample calibration row's report: the pilot baseline report on A that
# eval/calibration/smoke-q3_hand_labels.json describes. It was archived with the
# pilot on 2026-10-07 (eval/BATCH_A-D.md); its bytes are pinned here, so a copy
# found elsewhere is used only if it is the same report.
INSAMPLE_REPORT_SHA256 = "51410e059139b6c0796ff5b94fe4b7b6ba5f6ce5a76df27a6f39eaee3534f956"
INSAMPLE_REPORT_GLOBS = ("eval/runs/smoke-q3/report.md",
                         "eval/pilot/runs-before-paper-freeze-*/smoke-q3/report.md")
_CAL = _REPO / "eval" / "calibration"
# Calibration row id -> (report, labels, task id of the frozen key that scores
# it). None as the report means --insample-report. Every id of CAL_ROWS needs one.
CAL_SOURCES: dict[str, tuple[str | None, str, str]] = {
    "insample_A_baseline": (None, "smoke-q3_hand_labels.json", "smoke-q3"),
    "dev_A_r1": ("blind/smoke-q3__r1.report.md", "blind/smoke-q3__r1.report.csv", "smoke-q3"),
    "dev_A_oracle": ("blind/smoke-q3__r1.oracle_report.md",
                     "blind/smoke-q3__r1.oracle_report.csv", "smoke-q3"),
    "heldout_B_r1": ("heldout/portfolio-b__r1.report.md",
                     "heldout/portfolio-b__r1.report.csv", "portfolio-b"),
    "heldout_B_baseline": ("heldout/portfolio-b__baseline.report.md",
                           "heldout/portfolio-b__baseline.report.csv", "portfolio-b"),
}
if set(CAL_SOURCES) != set(CAL_ROWS):
    raise RuntimeError("every calibration row of make_paper_tables.CAL_ROWS needs a source here")

_TAG = re.compile(r"<[^>]+>")        # faithfulness.score's own normalisation
_RESOLVED = (MATCH, MISMATCH)
RES_FIELDS = ("scanned", "gold_shaped", "referent", "attribute", "full")


def _rel(p: Path) -> str:
    p = Path(p).resolve()
    return p.relative_to(_REPO).as_posix() if p.is_relative_to(_REPO) else str(p)


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _read(p: Path) -> Any:
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"missing input: {p}") from None


# --------------------------------------------------------------- statistics

def kappa_chance(a: Sequence[str], b: Sequence[str]) -> float | None:
    """Cohen's chance agreement p_e: the product of the two readers' marginals."""
    n = len(a)
    if n == 0 or n != len(b):
        return None
    return sum((a.count(c) / n) * (b.count(c) / n) for c in set(a) | set(b))


def pabak(p_o: float, q: int) -> float:
    """Prevalence- and bias-adjusted kappa over q categories: (q p_o - 1)/(q - 1)."""
    return (q * p_o - 1) / (q - 1)


def gwet_ac1(a: Sequence[str], b: Sequence[str], categories: Sequence[str]) -> float | None:
    """Gwet's AC1 for two readers over a fixed category set.

    p_e = sum_k pi_k (1 - pi_k) / (q - 1), with pi_k the share of the 2n labels
    in category k; AC1 = (p_o - p_e) / (1 - p_e). p_e never exceeds 1/q, so AC1
    is defined whenever there is an item."""
    n, q = len(a), len(categories)
    if n == 0 or n != len(b) or q < 2:
        return None
    if (set(a) | set(b)) - set(categories):
        raise ValueError(f"a label outside {list(categories)}")
    p_o = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pis = [(a.count(c) + b.count(c)) / (2 * n) for c in categories]
    p_e = sum(p * (1 - p) for p in pis) / (q - 1)
    return (p_o - p_e) / (1 - p_e)


def percentile_ci(values: Sequence[float], level: float = 0.95) -> list[float] | None:
    """The percentile interval: the order statistics at floor(m (1-level)/2) and
    ceil(m (1+level)/2) - 1 of the m sorted values."""
    v = sorted(values)
    m = len(v)
    if m == 0:
        return None
    lo = v[min(m - 1, math.floor(m * (1 - level) / 2))]
    hi = v[max(0, math.ceil(m * (1 + level) / 2) - 1)]
    return [lo, hi]


def _row_seed(seed: int, rid: str) -> int:
    """A row's own seed, so one row's interval does not depend on the others."""
    return int.from_bytes(hashlib.sha256(f"{seed}:{rid}".encode()).digest()[:8], "big")


def bootstrap_kappa(a: Sequence[str], b: Sequence[str], *, resamples: int,
                    seed: int) -> dict[str, Any]:
    """Percentile bootstrap 95% interval for Cohen's kappa over paired items.

    Items are resampled with replacement; a resample on which kappa is undefined
    (both readers used one and the same category) is left out and counted."""
    n = len(a)
    rng = random.Random(seed)  # noqa: S311 - a reproducible statistic, not a secret
    vals: list[float] = []
    undefined = 0
    for _ in range(resamples if n else 0):
        idx = [rng.randrange(n) for _ in range(n)]
        k = CF.cohen_kappa([a[i] for i in idx], [b[i] for i in idx])
        if k is None:
            undefined += 1
        else:
            vals.append(k)
    return {"ci95": percentile_ci(vals), "resamples": resamples, "undefined": undefined}


def agreement(human: Sequence[str], rule: Sequence[str], *, resamples: int, seed: int,
              categories: Sequence[str] = CATEGORIES) -> dict[str, Any]:
    """Every agreement figure MR2 asks for, over paired attribute-axis verdicts."""
    if len(human) != len(rule):
        raise ValueError("the two readers label different numbers of items")
    bad = (set(human) | set(rule)) - set(categories)
    if bad:
        raise ValueError(f"labels outside {list(categories)}: {sorted(bad)}")
    n = len(human)
    k = sum(h == r for h, r in zip(human, rule, strict=True))
    p_o = k / n if n else None
    return {
        "n": n, "k": k, "p_o": p_o,
        "kappa": CF.cohen_kappa(list(human), list(rule)),
        "kappa_pe": kappa_chance(list(human), list(rule)),
        "pabak": None if p_o is None else pabak(p_o, len(categories)),
        "ac1": gwet_ac1(human, rule, categories),
        "human": {c: sum(h == c for h in human) for c in categories},
        "rule": {c: sum(r == c for r in rule) for c in categories},
        "confusion": {h: {r: sum(1 for x, y in zip(human, rule, strict=True)
                                 if x == h and y == r) for r in categories}
                      for h in categories},
        "bootstrap": bootstrap_kappa(human, rule, resamples=resamples, seed=seed),
    }


def _spread(values: Iterable[float | None]) -> dict[str, Any]:
    """run_evaluation.spread without its per-run ``values``: a cell's summary
    only, so that no figure of one run (one under blind labelling, say) is
    written beside it."""
    out = R.spread([v for v in values if v is not None])
    out.pop("values", None)
    return out


def _rate(k: int, n: int) -> float | None:
    return k / n if n else None


# ------------------------------------------------------------------ inputs

@dataclass
class Run:
    """One pooled run: its files and both sides' faithfulness, as measured."""

    name: str
    task: str
    letter: str
    arm: str
    rep: int
    dir: Path
    measurement: dict[str, Any]
    manifest: dict[str, Any]
    report: str
    oracle_report: str
    trace: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    private: FaithfulnessResult | None = None
    oracle: FaithfulnessResult | None = None
    files: list[Path] = field(default_factory=list)


def _corpora(ev: dict[str, Any]) -> dict[str, str]:
    letters = (ev.get("hypotheses") or {}).get("corpora") or {}
    if not letters:
        raise SystemExit("evaluation.json: no hypotheses.corpora; run the INS2b aggregate")
    return {L: t for L, t in sorted(letters.items()) if t}


def _pooled(ev: dict[str, Any], corpora: dict[str, str]) -> list[tuple[str, str, str, str]]:
    """(letter, task, arm, run) for every run the aggregate pooled."""
    out = []
    for L, tid in corpora.items():
        arms = ((ev.get("by_task") or {}).get(tid) or {}).get("arms") or {}
        for arm in ARMS:
            for run in (arms.get(arm) or {}).get("runs") or []:
                out.append((L, tid, arm, run))
    return out


def _keys(tasks: dict[str, R.Task]) -> dict[str, Path]:
    return {tid: t.corpus / R.FACT_KEY_NAME for tid, t in tasks.items()}


def load_runs(runs_dir: Path, ev: dict[str, Any], corpora: dict[str, str],
              key_paths: dict[str, Path]) -> list[Run]:
    """Every pooled run, each side rescored with its task's frozen key and checked
    against the measurement: a report on disk that no longer scores as measured
    stops the script, since nothing computed from it would be the paper's."""
    keys = {tid: load_key(p) for tid, p in key_paths.items()}
    shas = {tid: _sha(p) for tid, p in key_paths.items()}
    runs: list[Run] = []
    for L, tid, arm, name in _pooled(ev, corpora):
        d = runs_dir / name
        files = [d / f for f in ("measurement.json", "manifest.json", "report.md",
                                 "oracle_report.md", "entities.json", "egress_trace.jsonl")]
        for f in files:
            if not f.is_file():
                raise SystemExit(f"{name}: no {f.name} under {runs_dir}; give --runs the "
                                 "run directories the aggregate read")
        m = _read(d / "measurement.json")
        if (m.get("task_id"), m.get("arm")) != (tid, arm):
            raise SystemExit(f"{name}: measurement.json is for {m.get('task_id')}/{m.get('arm')}")
        faith = m.get("faithfulness") or {}
        if faith.get("key_sha256") != shas[tid]:
            raise SystemExit(f"{name}: measured against key {faith.get('key_sha256')}, not the "
                             f"frozen {key_paths[tid]} ({shas[tid]})")
        trace = [json.loads(ln) for ln in (d / "egress_trace.jsonl").read_text(
            encoding="utf-8").splitlines() if ln.strip()]
        r = Run(name, tid, L, arm, int(m.get("rep") or 1), d, m, _read(d / "manifest.json"),
                (d / "report.md").read_text(encoding="utf-8"),
                (d / "oracle_report.md").read_text(encoding="utf-8"),
                trace, _read(d / "entities.json"), files=files)
        r.private = score(r.report, keys[tid])
        r.oracle = score(r.oracle_report, keys[tid])
        for side, res in (("private", r.private), ("oracle", r.oracle)):
            if res.to_json() != faith.get(side):
                raise SystemExit(f"{name}: the {side} report no longer scores as its "
                                 "measurement.json records; nothing here would be the "
                                 "frozen instrument's")
        runs.append(r)
    if not runs:
        raise SystemExit("no pooled run in evaluation.json")
    return runs


def _runs_digest(runs: Sequence[Run]) -> str:
    h = hashlib.sha256()
    for r in sorted(runs, key=lambda r: r.name):
        for f in r.files:
            h.update(f"{r.name}/{f.name} {_sha(f)}\n".encode())
    return h.hexdigest()


# ------------------------------------------------------------- MR3a resolution

def _denominators(r: Run, side: str) -> dict[str, int]:
    """A side's denominators as the run's measurement.json records them (which
    load_runs has checked the frozen key reproduces)."""
    den = r.measurement["faithfulness"][side]["denominators"]
    return {f: int(den[f]) for f in RES_FIELDS}


def _resolution_cell(rows: Sequence[dict[str, int]]) -> dict[str, Any]:
    sums = {f: sum(r[f] for r in rows) for f in RES_FIELDS}
    rates = {f: _spread(_rate(r[f], r["gold_shaped"]) for r in rows)
             for f in ("referent", "attribute", "full")}
    return {"runs": len(rows), "sum": sums, "rates": rates}


def resolution(runs: Sequence[Run], corpora: dict[str, str],
               withheld: dict[str, str] | None = None) -> dict[str, Any]:
    """The denominators per run, per cell and per arm. A run in `withheld` (run
    -> reason; pending_blind_runs) counts in its cell and arm, and its own record
    is left out, so no per-run key shows the labeller what the rule resolved in a
    report under blind labelling."""
    withheld = withheld or {}
    per_run, cells, arms = [], {}, {}
    for r in runs:
        per_run.append({"run": r.name, "letter": r.letter, "arm": r.arm, "rep": r.rep,
                        "private": _denominators(r, "private"),
                        "oracle": _denominators(r, "oracle")})
    shown = [x if x["run"] not in withheld else
             {k: x[k] for k in ("run", "letter", "arm", "rep")} | {"withheld": withheld[x["run"]]}
             for x in per_run]
    for side_arm in (*ARMS, "oracle"):
        def rows(L: str | None, a: str = side_arm) -> list[dict[str, int]]:
            if a == "oracle":
                return [x["oracle"] for x in per_run if L in (None, x["letter"])]
            return [x["private"] for x in per_run if x["arm"] == a and L in (None, x["letter"])]
        for L in corpora:
            if rows(L):
                cells.setdefault(L, {})[side_arm] = _resolution_cell(rows(L))
        if rows(None):
            arms[side_arm] = _resolution_cell(rows(None))
    return {"fields": {"scanned": "occurrences scanned (numerals and spelled-out gold values)",
                       "gold_shaped": "occurrences of a gold value",
                       "referent": "of those, referent resolved",
                       "attribute": "of those, attribute resolved",
                       "full": "of those, both resolved (RBA's pool)"},
            "runs": shown, "cells": cells, "arms": arms}


# -------------------------------------------------------- MR3b lexical overlap

def _lexicon(keys: dict[str, FactKey]) -> tuple[dict[str, str], bool]:
    """Phrase (casefolded) -> RBA attribute over every key, and whether the keys
    carry one and the same lexicon. A phrase two keys give two attributes stops it."""
    table: dict[str, str] = {}
    tables = []
    for tid in sorted(keys):
        _, t = keys[tid].lexicon_regex()
        tables.append(t)
        for p, a in t.items():
            if table.get(p, a) != a:
                raise SystemExit(f"the keys disagree on lexicon phrase {p!r}: "
                                 f"{table[p]} vs {a}")
            table[p] = a
    return table, all(t == tables[0] for t in tables)


def _lexicon_rx(table: dict[str, str]) -> re.Pattern[str]:
    """The scorer's own matcher (FactKey.lexicon_regex) over the union lexicon."""
    attrs: dict[str, list[str]] = {}
    for p, a in table.items():
        attrs.setdefault(a, []).append(p)
    rx, _ = FactKey(referents={}, attributes=attrs, facts=[], string_facts=[],
                    mask_patterns=[]).lexicon_regex()
    return rx


def _normalised(markdown: str) -> str:
    return _TAG.sub(" ", de_escape(unicodedata.normalize("NFKC", markdown)))


def _meaning_lines(code: str) -> str:
    return f"- {code}: {ATTRIBUTE_MEANINGS[code]}"


def lexical_overlap(keys: dict[str, FactKey], runs: Sequence[Run]) -> dict[str, Any]:
    table, same = _lexicon(keys)
    rx = _lexicon_rx(table)
    codes, shared = [], set()
    for code in ATTRIBUTE_CODES:
        hits = [m.group(0).casefold() for m in rx.finditer(ATTRIBUTE_MEANINGS[code])]
        shared |= set(hits)
        attrs = sorted({table[h] for h in hits})
        own = CODE_ATTRIBUTE.get(code)
        cls = None
        if own is not None:
            cls = ("none" if not attrs else "own_only" if attrs == [own]
                   else "mixed" if own in attrs else "other_only")
        codes.append({"code": code, "meaning": ATTRIBUTE_MEANINGS[code],
                      "rba_attribute": own,
                      "phrases": [{"phrase": h, "attribute": table[h]} for h in hits],
                      "attributes": attrs, "class": cls})
    money = [c for c in codes if c["rba_attribute"]]

    # Did the cloud see the meanings? Every r1 drafter request should carry
    # the block, line for line.
    drafts = [e for r in runs if r.arm == "r1" for e in r.trace
              if str(e.get("stage", "")).startswith("draft")]
    carried = sum(1 for e in drafts
                  if all(_meaning_lines(c) in "\n".join(
                      str(m.get("content", "")) for m in e.get("messages") or [])
                      for c in ATTRIBUTE_CODES))

    def usage(texts: Iterable[str]) -> dict[str, int]:
        hits = shr = words = 0
        for md in texts:
            t = _normalised(md)
            words += len(t.split())
            for m in rx.finditer(t):
                hits += 1
                shr += m.group(0).casefold() in shared
        return {"hits": hits, "shared": shr, "words": words}

    use: dict[str, Any] = {}
    for arm in ARMS:
        mine = [r for r in runs if r.arm == arm]
        if mine:
            use[arm] = {"runs": len(mine), **usage(r.report for r in mine)}
    use["oracle"] = {"runs": len(runs), **usage(r.oracle_report for r in runs)}
    return {
        "lexicon": "the gold keys' RBA attribute lexicon (scripts/corpora/rba_lexicon.py), "
                   "not R1's header lexicon",
        "lexicons_identical_across_keys": same,
        "lexicon_phrases": len(table),
        "codes": codes,
        "meanings_with_phrase": sum(1 for c in codes if c["phrases"]),
        "phrases_in_meanings": sorted(shared),
        "money_codes": {cls: [c["code"] for c in money if c["class"] == cls]
                        for cls in ("own_only", "mixed", "other_only", "none")},
        "r1_draft_requests": len(drafts),
        "r1_draft_requests_with_meanings": carried,
        "usage": use,
    }


# ------------------------------------------------------- MR3b coverage split

def _fact_sets(key: FactKey) -> tuple[set[str], set[str]]:
    stated = {f["fact_id"] for f in key.facts if not f.get("derived")}
    derived = {f["fact_id"] for f in key.facts if f.get("derived")}
    return stated, derived


def _covsplit_row(res: FaithfulnessResult, key: FactKey) -> dict[str, int]:
    stated, derived = _fact_sets(key)
    correct = _correctly_bound(res.occurrences, key.facts) & (stated | derived)
    return {"stated": len(correct & stated), "derived": len(correct & derived)}


def coverage_split(runs: Sequence[Run], keys: dict[str, FactKey],
                   corpora: dict[str, str]) -> dict[str, Any]:
    facts, cells = {}, {}
    for L, tid in corpora.items():
        stated, derived = _fact_sets(keys[tid])
        facts[L] = {"stated": len(stated), "derived": len(derived)}
        mine = [r for r in runs if r.letter == L]
        for side in (*ARMS, "oracle"):
            rs = mine if side == "oracle" else [r for r in mine if r.arm == side]
            if not rs:
                continue
            rows = [_covsplit_row(r.oracle if side == "oracle" else r.private, keys[tid])
                    for r in rs]
            for r, row in zip(rs, rows, strict=True):   # coverage_correct, as measured
                res = r.oracle if side == "oracle" else r.private
                if row["stated"] + row["derived"] != round(
                        res.coverage_correct * (len(stated) + len(derived))):
                    raise SystemExit(f"{r.name}: the split does not add up to coverage_correct")
            cell: dict[str, Any] = {"runs": len(rs)}
            for kind in ("stated", "derived"):
                n = facts[L][kind]
                cell[kind] = _spread(_rate(row[kind], n) for row in rows)
                cell[f"{kind}_pooled"] = {"k": sum(row[kind] for row in rows),
                                          "n": n * len(rows)}
            cells.setdefault(L, {})[side] = cell
    return {"facts": facts, "cells": cells}


# ------------------------------------------------- MR3b A without share-spent

def _without(key_raw: dict[str, Any], attribute: str) -> tuple[FactKey, list[str]]:
    removed = sorted(f["fact_id"] for f in key_raw["facts"] if f["attribute"] == attribute)
    if not removed or attribute not in key_raw["attributes"]:
        raise SystemExit(f"the key has no {attribute} facts or attribute to leave out")
    return FactKey(
        referents=key_raw["referents"],
        attributes={k: v["lexicon"] for k, v in key_raw["attributes"].items()
                    if k != attribute},
        facts=[f for f in key_raw["facts"] if f["attribute"] != attribute],
        string_facts=key_raw.get("string_facts", []),
        mask_patterns=key_raw.get("mask_patterns", []),
    ), removed


def _rate_cell(results: Sequence[FaithfulnessResult]) -> dict[str, Any]:
    """RBA, attribute accuracy and coverage_correct over runs, as the aggregate
    takes them: nulls left out, and RBA left out below MIN_RBA_POOL."""
    return {
        "runs": len(results),
        "rba": _spread(r.rba for r in results
                       if r.denominators["full"] >= R.MIN_RBA_POOL),
        "attribute_accuracy": _spread(r.attribute_accuracy for r in results),
        "coverage_correct": _spread(r.coverage_correct for r in results),
    }


def without_share_spent(runs: Sequence[Run], key_paths: dict[str, Path],
                        corpora: dict[str, str]) -> dict[str, Any]:
    tid = corpora.get(SHARE_SPENT_LETTER)
    if tid is None:
        raise SystemExit(f"no corpus {SHARE_SPENT_LETTER} in evaluation.json")
    key, removed = _without(_read(key_paths[tid]), SHARE_SPENT)
    mine = [r for r in runs if r.task == tid]
    cells: dict[str, Any] = {}
    for arm in ARMS:
        rs = [r for r in mine if r.arm == arm]
        if rs:
            cells[arm] = _rate_cell([score(r.report, key) for r in rs])
    cells["oracle"] = _rate_cell([score(r.oracle_report, key) for r in mine])
    return {"letter": SHARE_SPENT_LETTER, "task": tid, "removed_attribute": SHARE_SPENT,
            "removed_facts": removed, "facts": len(key.facts), "cells": cells}


# ---------------------------------------------------------------- MR4b binding

def _value_of(text: str) -> float | None:
    """A MONEY surface's amount, as the scorer normalises a numeral."""
    m = _NUM_RE.search(text)
    if not m:
        return None
    t = m.group(0).replace(",", "").rstrip("%")
    try:
        return round(float(t), 2)
    except ValueError:
        return None


def money_slots(entities: Sequence[dict[str, Any]], arm: str) -> list[float | None]:
    """The value of each MONEY slot the arm's payload lists: one slot per
    distinct surface for baseline, one per canonical key for r5 (R5's
    normalisation); None for a slot whose text holds no numeral."""
    groups: dict[str, set[float | None]] = {}
    for e in entities:
        if e["category"] != "MONEY":
            continue
        k = e["text"] if arm == "baseline" else canonical_key("MONEY", e["text"])
        groups.setdefault(k, set()).add(_value_of(e["text"]))
    out = []
    for k in sorted(groups):
        vals = groups[k]
        if len(vals) != 1:
            raise SystemExit(f"one {arm} MONEY slot holds texts of different amounts")
        out.append(next(iter(vals)))
    return out


def _owners(key: FactKey, value: float | None) -> list[tuple[str, str]]:
    return list(key.by_value.get(value, [])) if value is not None else []


def chance_cell(slot_sets: Sequence[list[float | None]],
                results: Sequence[FaithfulnessResult], key: FactKey) -> dict[str, Any]:
    """The chance model over one cell's runs (see the module docstring)."""
    attr_p, attr_hit, full_p, full_hit = [], 0, [], 0
    for slots, res in zip(slot_sets, results, strict=True):
        gold = [s for s in slots if _owners(key, s)]
        if not gold:
            continue
        values = set(gold)
        for o in res.occurrences:
            if o.verdict == FABRICATED or o.value not in values:
                continue
            if o.attribute_verdict in _RESOLVED:
                attr_p.append(sum(1 for s in gold if o.attribute in
                                  {a for _, a in _owners(key, s)}) / len(gold))
                attr_hit += o.attribute_verdict == MATCH
                if o.referent_verdict in _RESOLVED:
                    full_p.append(sum(1 for s in gold if (o.referent, o.attribute) in
                                      set(_owners(key, s))) / len(gold))
                    full_hit += o.verdict == CORRECT
    return {
        "attribute": {"n": len(attr_p), "chance": _mean(attr_p), "observed_k": attr_hit,
                      "observed": _rate(attr_hit, len(attr_p))},
        "full": {"n": len(full_p), "chance": _mean(full_p), "observed_k": full_hit,
                 "observed": _rate(full_hit, len(full_p))},
    }


def _mean(xs: Sequence[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _attrs_per_referent(slot_values: Iterable[float | None], key: FactKey) -> dict[str, Any]:
    per: dict[str, set[str]] = {}
    for v in slot_values:
        for subj, a in _owners(key, v):
            per.setdefault(subj, set()).add(a)
    sizes = sorted(len(a) for a in per.values())
    return {"referents": len(per), "min": sizes[0] if sizes else None,
            "max": sizes[-1] if sizes else None, "mean": _mean(sizes)}


def _advertised(obs_rows: dict[str, dict[str, Any]], run: str) -> dict[str, int]:
    row = obs_rows.get(run)
    if row is None:
        raise SystemExit(f"observation.json has no frozen row for {run}")
    return dict(row.get("slots_advertised") or {})


def binding(runs: Sequence[Run], keys: dict[str, FactKey], corpora: dict[str, str],
            obs_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cells: dict[str, Any] = {}
    pooled: dict[str, list[tuple[list[float | None], FaithfulnessResult, FactKey]]] = {}
    for L, tid in corpora.items():
        key = keys[tid]
        mine = [r for r in runs if r.letter == L]
        for arm in SLOT_ARMS:
            rs = [r for r in mine if r.arm == arm]
            if not rs:
                continue
            slot_sets = []
            for r in rs:
                slots = money_slots(r.entities, arm)
                adv = _advertised(obs_rows, r.name).get("MONEY", 0)
                if len(slots) != adv:
                    raise SystemExit(f"{r.name}: {len(slots)} MONEY slots from entities.json, "
                                     f"but its planner request lists {adv}")
                slot_sets.append(slots)
            gold = [[s for s in ss if _owners(key, s)] for ss in slot_sets]
            cells.setdefault(L, {})[arm] = {
                "runs": len(rs),
                "money_slots": sorted({len(s) for s in slot_sets}),
                "gold_money_slots": sorted({len(g) for g in gold}),
                "gold_money_values": sorted({len(set(g)) for g in gold}),
                "attributes_per_referent": _attrs_per_referent(
                    [v for g in gold for v in g], key),
                **chance_cell(slot_sets, [r.private for r in rs], key),
            }
            pooled.setdefault(arm, []).extend(
                (s, r.private, key) for s, r in zip(slot_sets, rs, strict=True))
        r1 = [r for r in mine if r.arm == "r1"]
        if r1:
            ref_slots = sorted({sum(n for c, n in _advertised(obs_rows, r.name).items()
                                    if c in REFERENT_CATEGORIES) for r in r1})
            money = sorted({_advertised(obs_rows, r.name).get("MONEY", 0) for r in r1})
            facts = sorted({int((r.manifest.get("facts") or {}).get("facts_total") or 0)
                            for r in r1})
            cells.setdefault(L, {})["r1"] = {"runs": len(r1), "referent_slots": ref_slots,
                                             "money_slots": money, "codes": len(ATTRIBUTE_CODES),
                                             "facts_in_store": facts}
    arms: dict[str, Any] = {}
    for arm, items in pooled.items():
        parts = [chance_cell([s], [res], key) for s, res, key in items]
        arms[arm] = {ax: _pool_chance([p[ax] for p in parts]) for ax in ("attribute", "full")}
    return {
        "model": ("baseline and r5: the payload lists MONEY slots in canonical order and no "
                  "relation names a slot, so nothing on the wire tells the drafter which MONEY "
                  "slot is which referent's which attribute. Chance model: the drafter's "
                  "choice of MONEY slot is independent of the referent and attribute its "
                  "sentence names. An occurrence of a gold MONEY value whose attribute the "
                  "rule resolves to a is then a MATCH with probability p_a, the share of the "
                  "run's gold-valued MONEY slots whose value carries a; a both-resolved one "
                  "naming referent r is CORRECT with probability p_(r,a). Chance accuracy is "
                  "the mean of p over the cell's resolved money occurrences, given the "
                  "attributes (and referents) the rule resolved; observed accuracy is over "
                  "the same occurrences. r1: no MONEY slot crosses; the cloud names a "
                  "referent slot and one of the 13 codes, and the value is resolved locally "
                  "from the store, so the reference fixes the value-referent-attribute "
                  "triple."),
        "cells": cells, "arms": arms,
    }


def _pool_chance(parts: Sequence[dict[str, Any]]) -> dict[str, Any]:
    n = sum(p["n"] for p in parts)
    k = sum(p["observed_k"] for p in parts)
    s = sum(p["chance"] * p["n"] for p in parts if p["n"])
    return {"n": n, "chance": s / n if n else None, "observed_k": k, "observed": _rate(k, n)}


# --------------------------------------------------------------- MR2 calibration

def _sheet_progress(path: Path) -> tuple[int, int]:
    """(rows with both labels filled, rows) of a blind sheet."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    filled = sum(1 for r in rows if (r.get("referent_label") or "").strip()
                 and (r.get("attribute_label") or "").strip())
    return filled, len(rows)


def _insample_report(given: Path | None) -> Path | None:
    cands = [given] if given else [Path(p) for g in INSAMPLE_REPORT_GLOBS
                                   for p in sorted(glob.glob(str(_REPO / g)))]
    for c in cands:
        if c and c.is_file() and _sha(c) == INSAMPLE_REPORT_SHA256:
            return c
    if given:
        raise SystemExit(f"--insample-report {given} is not the report the in-sample labels "
                         f"describe (sha256 {INSAMPLE_REPORT_SHA256})")
    return None


def calibration_row(rid: str, report: Path | None, labels: Path, key_path: Path, *,
                    resamples: int, seed: int) -> dict[str, Any]:
    labeller, blind, in_sample = CAL_ROWS[rid]
    row: dict[str, Any] = {"id": rid, "labeller": labeller, "blind": blind,
                           "in_sample": in_sample, "labels": _rel(labels),
                           "report": _rel(report) if report else None,
                           "key_sha256": _sha(key_path)}
    if report is None or not report.is_file():
        row["status"] = "report absent"
        return row
    if labels.suffix.lower() == ".csv":
        filled, total = _sheet_progress(labels)
        row["sheet_rows"], row["sheet_rows_labelled"] = total, filled
        if filled == 0:
            row["status"] = "unlabelled"
            return row
        if filled < total:
            row["status"] = "incomplete"
            return row
    _report, _res, pairs, _labels = CF._one_report(str(report), str(labels),
                                                   CF._key(str(key_path)))
    gold = [(o, lab) for o, lab in pairs if o.verdict != FABRICATED]
    stats = agreement([lab["attribute"] for _, lab in gold],
                      [o.attribute_verdict for o, _ in gold],
                      resamples=resamples, seed=_row_seed(seed, rid))
    row.update(status="labelled", occurrences=len(pairs),
               agreement={"k": stats["k"], "n": stats["n"]}, **{
                   k: stats[k] for k in ("kappa", "kappa_pe", "pabak", "ac1", "human", "rule",
                                         "confusion", "bootstrap")})
    return row


def _check_recorded(row: dict[str, Any], recorded: dict[str, Any] | None) -> None:
    """A row calibration.json records must be reproduced: same occurrences, k/n
    and kappa (recorded to 3 dp)."""
    if recorded is None or row.get("status") != "labelled":
        return
    same = (recorded.get("occurrences") == row["occurrences"]
            and recorded.get("agreement") == row["agreement"]
            and (recorded.get("kappa") is None) == (row["kappa"] is None)
            and (row["kappa"] is None or abs(recorded["kappa"] - row["kappa"]) < 5e-4))
    if not same:
        raise SystemExit(f"calibration row {row['id']!r}: recomputed {row['occurrences']} "
                         f"occurrences, {row['agreement']}, kappa {row['kappa']}, but "
                         f"calibration.json records {recorded.get('occurrences')}, "
                         f"{recorded.get('agreement')}, kappa {recorded.get('kappa')}")


def calibration(cal_json: dict[str, Any], tasks: dict[str, R.Task], *,
                insample_report: Path | None, resamples: int, seed: int,
                cal_dir: Path = _CAL) -> dict[str, Any]:
    recorded = {r.get("id"): r for r in cal_json.get("rows") or []}
    rows = []
    for rid in CAL_ROWS:
        rep, lab, tid = CAL_SOURCES[rid]
        report = insample_report if rep is None else cal_dir / rep
        row = calibration_row(rid, report, cal_dir / lab, _keys(tasks)[tid],
                              resamples=resamples, seed=seed)
        _check_recorded(row, recorded.get(rid))
        if rid in recorded and row.get("status") != "labelled":
            print(f"warning: calibration row {rid} is in calibration.json but gives no "
                  f"figures here ({row['status']})", file=sys.stderr)
        rows.append(row)
    return {"axis": "attribute, gold-valued occurrences",
            "categories": {MATCH: "correct", MISMATCH: "misbound", UNRESOLVED: "unresolved"},
            "bootstrap": {"resamples": resamples, "seed": seed,
                          "method": "percentile, occurrences resampled with replacement, "
                                    "seeded per row; kappa-undefined resamples left out"},
            "rows": rows}


def pending_blind_runs(cal_rows: Sequence[dict[str, Any]],
                       runs: Sequence[Run]) -> dict[str, str]:
    """Run -> reason, for every run in a cell (corpus and arm) that holds a run
    whose report.md is a byte copy of a calibration report whose sheet is not
    yet fully labelled. The labelling instructions
    (eval/calibration/heldout/README.md) say not to open that run's measurement
    until the sheet is finished, so its per-run figures are held back, and so
    are its cell-mates', since the cell's totals minus theirs would give it."""
    pending = {}
    for row in cal_rows:
        if row.get("status") in ("unlabelled", "incomplete") and row.get("report"):
            pending[_sha(_REPO / row["report"])] = row["id"]
    cells = {}
    for r in runs:
        rid = pending.get(_sha(r.dir / "report.md"))
        if rid:
            cells[(r.letter, r.arm)] = (f"its cell holds the report of calibration row {rid}, "
                                        "whose blind sheet is not yet labelled")
    return {r.name: cells[(r.letter, r.arm)] for r in runs if (r.letter, r.arm) in cells}


# ------------------------------------------------------------ MR9a corpus

def _docs(corpus: Path) -> list[Any]:
    return [load(p) for p in sorted(corpus.iterdir()) if p.suffix.lower() in SUFFIXES]


def _cell_value(text: str) -> float | None:
    t = text.strip().replace(",", "")
    try:
        return round(float(t), 2)
    except ValueError:
        return None


def fact_kinds(docs: Sequence[Any], key_raw: dict[str, Any]) -> dict[str, list[str]]:
    """The key's facts by kind: derived; stated in a table (a table data cell,
    below the header row and outside the key column, whose whole content is the
    fact's value, in a row whose key cell names one of the fact's subjects);
    stated in prose only (every other stated fact)."""
    surfaces = {s: [x.casefold() for x in v] for s, v in key_raw["referents"].items()}
    cells: list[tuple[float, str]] = []
    for d in docs:
        sheets: dict[str, dict[tuple[int, int], str]] = {}
        for c in d.cells:
            sheets.setdefault(c.sheet, {})[(c.row, c.col)] = c.value
        for grid in sheets.values():
            head, kcol = min(r for r, _ in grid), min(c for _, c in grid)
            for (r, c), v in grid.items():
                val = _cell_value(v) if r != head and c != kcol else None
                if val is not None:
                    cells.append((val, (grid.get((r, kcol)) or "").casefold()))
    out: dict[str, list[str]] = {"table": [], "prose": [], "derived": []}
    for f in key_raw["facts"]:
        if f.get("derived"):
            out["derived"].append(f["fact_id"])
            continue
        in_table = f.get("match") == "numeric" and any(
            val == round(float(f["value"]), 2)
            and any(s in rowkey for subj in f["subjects"] for s in surfaces.get(subj, []))
            for val, rowkey in cells)
        out["table" if in_table else "prose"].append(f["fact_id"])
    return {k: sorted(v) for k, v in out.items()}


def corpus_stats(tasks: dict[str, R.Task], corpora: dict[str, str], runs: Sequence[Run],
                 ev: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for L, tid in corpora.items():
        corpus = tasks[tid].corpus
        docs = _docs(corpus)
        chars = sum(len(d.text) for d in docs)
        for r in runs:
            m = r.measurement
            if r.task == tid and (m.get("corpus_chars"), m.get("corpus_documents")) != (
                    chars, len(docs)):
                raise SystemExit(f"{r.name}: the measurement read {m.get('corpus_documents')} "
                                 f"documents, {m.get('corpus_chars')} characters; the corpus "
                                 f"on disk has {len(docs)}, {chars}")
        cells = R._table_data_cells(corpus)
        agg = ((ev.get("by_task") or {}).get(tid) or {}).get("table_data_cells")
        if agg is not None and agg != cells:
            raise SystemExit(f"{tid}: {cells} table data cells on disk, {agg} in the aggregate")
        key_raw = _read(corpus / R.FACT_KEY_NAME)
        kinds = fact_kinds(docs, key_raw)
        out[L] = {"task": tid, "documents": len(docs), "characters": chars,
                  "words": sum(len(d.text.split()) for d in docs),
                  "table_data_cells": cells, "referents": len(key_raw["referents"]),
                  "facts": len(key_raw["facts"]),
                  "facts_by_kind": {k: len(v) for k, v in kinds.items()},
                  "fact_ids_by_kind": kinds}
    return out


# ------------------------------------------------------- MR9b masked documents

def _lost(extraction: dict[str, Any]) -> list[str]:
    """Documents whose every extractor reply was dropped: no entity, no relation
    (make_paper_tables._maskdoc_facts's rule)."""
    return sorted(d.get("doc_id") for d in extraction.get("documents") or []
                  if d.get("chunks") and (d.get("dropped_malformed") or 0) >= d["chunks"]
                  and not d.get("entities") and not d.get("relations"))


def _exposure_rows(corpus: Any, ex: Any) -> list[dict[str, Any]]:
    """tier1_probe.masked_exposure's per-document loop, keeping each document's
    surviving surfaces so a document can be left out afterwards."""
    f = T.build_filter(corpus.docs, salt=T.FILTER_SALT, n_min=T.SHINGLE_N_MIN,
                       n_max=T.SHINGLE_N_MAX, hit_threshold=T.SHINGLE_HIT_THRESHOLD)
    masker = T.SlotMasker(T.ANALYSIS_SALT, normalise=True)
    surfaces = list((corpus.surfaces or {}).get("surfaces", []))
    rows = []
    for d, dex in zip(corpus.docs, ex.extractions, strict=True):
        m = masker.mask(d, dex.entities)
        t = T.tokenize(m.masked_text)
        grams5 = [" ".join(t[i:i + 5]) for i in range(len(t) - 4)]
        rows.append({"doc_id": d.doc_id, "refused": f.inspect(m.masked_text).blocked,
                     "masked_5grams": len(grams5),
                     "masked_5grams_hit": sum(1 for g in grams5
                                              if g.encode("utf-8") in f.bloom),
                     "surviving": T._surviving(T._strip_slots(m.masked_text), surfaces)})
    return rows


def _exposure_of(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    masked = sum(r["masked_5grams"] for r in rows)
    survived: Counter[str] = Counter()
    for r in rows:
        survived.update(r["surviving"])
    return {"documents": len(rows), "refused_documents": sum(r["refused"] for r in rows),
            "masked_5gram_hit_share": (sum(r["masked_5grams_hit"] for r in rows) / masked
                                       if masked else None),
            "surfaces_distinct": len(survived), "surfaces_occurrences": sum(survived.values())}


def maskdoc_without_lost(probe_paths: Sequence[Path], corpora: dict[str, str],
                         tasks: dict[str, R.Task]) -> dict[str, Any]:
    letter_of = {t: L for L, t in corpora.items()}
    out: dict[str, Any] = {}
    for pp in probe_paths:
        pr = _read(pp)
        cid = (pr.get("corpus") or {}).get("id")
        L = letter_of.get(cid)
        if L is None:
            continue
        exts = []
        for x, meta in zip(pr.get("per_extraction") or [], pr.get("extractions") or [],
                           strict=True):
            me = x["masked_exposure"]
            files = meta.get("files") or []
            path = _REPO / files[0] if files else None
            row = {"index": meta.get("index"), "file": files[0] if files else None,
                   "lost_documents": [],
                   "probe": {"documents": len(me["documents"]),
                             "masked_5gram_hit_share": me["masked_5gram_hit_share"],
                             "surfaces_distinct": me["generator_surfaces_surviving"]["distinct"]}}
            if path is None or not path.is_file():
                row["status"] = "extraction file absent; the probe's figures"
                row["kept"] = row["probe"]
                exts.append(row)
                continue
            lost = _lost(_read(path))
            row["lost_documents"] = lost
            if not lost:
                row["status"] = "nothing lost; the probe's figures"
                row["kept"] = row["probe"]
                exts.append(row)
                continue
            corpus = T.load_corpus(tasks[cid].corpus)
            loaded, refused = T.read_extractions([path], corpus)
            if len(loaded) != 1 or refused:
                raise SystemExit(f"{files[0]}: tier1_probe.py does not load it as one "
                                 f"extraction ({refused})")
            rows = _exposure_rows(corpus, loaded[0])
            full = _exposure_of(rows)
            want = (len(me["documents"]), me["masked_5gram_hit_share"],
                    me["generator_surfaces_surviving"]["distinct"],
                    me["generator_surfaces_surviving"]["occurrences"])
            got = (full["documents"], full["masked_5gram_hit_share"],
                   full["surfaces_distinct"], full["surfaces_occurrences"])
            if want != got or [(r["doc_id"], r["refused"], r["masked_5grams_hit"])
                               for r in rows] != [(d["doc_id"], d["refused"],
                                                   d["masked_5grams_hit"])
                                                  for d in me["documents"]]:
                raise SystemExit(f"{pp.name}, extraction {meta.get('index')}: recomputing "
                                 f"the masked exposure gives {got}, the probe records {want}")
            row["status"] = "recomputed without the lost documents"
            row["kept"] = _exposure_of([r for r in rows if r["doc_id"] not in set(lost)])
            exts.append(row)
        out[L] = {"probe": _rel(pp), "task": cid, "extractions": exts}
    return out


# ------------------------------------------------------------------ minor 8

def _usage(trace: Sequence[dict[str, Any]], prefix: str) -> dict[str, int]:
    es = [e for e in trace if str(e.get("stage", "")) == prefix
          or str(e.get("stage", "")).startswith(prefix + ":")]
    return {"input_tokens": sum(int(e.get("input_tokens") or 0) for e in es),
            "output_tokens": sum(int(e.get("output_tokens") or 0) for e in es)}


def cost(runs: Sequence[Run], obs_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    per_run = []
    for r in runs:
        plan, draft = _usage(r.trace, "plan"), _usage(r.trace, "draft")
        orow = obs_rows.get(r.name) or {}
        if (orow.get("usage") or {}).get("plan") != plan or \
                (orow.get("usage") or {}).get("draft") != draft:
            raise SystemExit(f"{r.name}: the trace's planner and drafter tokens are not "
                             "observation.json's")
        usd = r.measurement.get("usd") or {}
        if any(k not in usd for k in ("oracle", "judge", "adversary")):
            raise SystemExit(f"{r.name}: the measurement records no evaluation cost")
        m = r.manifest
        per_run.append({
            "run": r.name, "letter": r.letter, "arm": r.arm,
            "deploy_input_tokens": plan["input_tokens"] + draft["input_tokens"],
            "deploy_output_tokens": plan["output_tokens"] + draft["output_tokens"],
            "deploy_usd": R._cost(plan) + R._cost(draft),
            "eval_usd": usd["oracle"] + usd["judge"] + usd["adversary"],
            "eval_usd_by_role": {k: usd[k] for k in ("oracle", "judge", "adversary")},
            "phase_one_seconds": float(m["finished_at"]) - float(m["started_at"]),
            "extracted": m.get("extraction_source") == "extracted",
        })

    def block(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
        return {"runs": len(rows),
                "deploy_usd": _spread(x["deploy_usd"] for x in rows),
                "eval_usd": _spread(x["eval_usd"] for x in rows),
                "seconds_reused": _spread(x["phase_one_seconds"] for x in rows
                                          if not x["extracted"]),
                "seconds_extracted": _spread(x["phase_one_seconds"] for x in rows
                                             if x["extracted"])}
    return {
        "prices_usd_per_token": {"input": R.USD_IN, "output": R.USD_OUT},
        "note": "deployment = phase one's planner and drafter calls (egress trace tokens at "
                "the list rates); evaluation = oracle, judge and adversary (the measurement's "
                "usd). Seconds: phase one's wall-clock time (manifest finished_at - "
                "started_at), on this host's local GPU and the cloud; a run marked extracted "
                "also ran the local extraction, the others reused it.",
        "runs": per_run,
        "arms": {arm: block([x for x in per_run if x["arm"] == arm]) for arm in ARMS
                 if any(x["arm"] == arm for x in per_run)},
        "all": block(per_run),
        "totals": {"deploy_input_tokens": sum(x["deploy_input_tokens"] for x in per_run),
                   "deploy_output_tokens": sum(x["deploy_output_tokens"] for x in per_run),
                   "deploy_usd": sum(x["deploy_usd"] for x in per_run),
                   "eval_usd": sum(x["eval_usd"] for x in per_run),
                   "eval_usd_by_role": {k: sum(x["eval_usd_by_role"][k] for x in per_run)
                                        for k in ("oracle", "judge", "adversary")}},
    }


# --------------------------------------------------------------------- build

def build(args: argparse.Namespace) -> dict[str, Any]:
    ev = _read(args.evaluation)
    corpora = _corpora(ev)
    tasks = {t.id: t for t in R.load_tasks(args.tasks)}
    missing = [t for t in corpora.values() if t not in tasks]
    if missing:
        raise SystemExit(f"{args.tasks} lacks task {', '.join(missing)}")
    key_paths = {tid: p for tid, p in _keys(tasks).items() if tid in corpora.values()}
    keys = {tid: load_key(p) for tid, p in key_paths.items()}
    runs = load_runs(args.runs, ev, corpora, key_paths)
    obs = _read(args.observation)
    obs_rows = {r["run"]: r for r in obs.get("runs") or [] if not r.get("attempt")}
    cal_json = _read(args.calibration)
    probe_paths = args.probe or sorted(Path(p) for p in glob.glob(
        str(_REPO / "eval" / "probe" / "*.json")))
    insample = _insample_report(args.insample_report)
    if insample is None:
        print("warning: the in-sample calibration row's report (the pilot baseline report "
              f"on A, sha256 {INSAMPLE_REPORT_SHA256[:12]}…) is not found; that row gives no "
              "figures (--insample-report)", file=sys.stderr)

    cal = calibration(cal_json, tasks, insample_report=insample,
                      resamples=args.bootstrap, seed=args.seed)
    used = [p for r in cal["rows"] for p in (r["labels"], r["report"]) if p]
    withheld = pending_blind_runs(cal["rows"], runs)
    for name, why in sorted(withheld.items()):
        print(f"note: {name}'s per-run figures are withheld: {why}", file=sys.stderr)
    return {
        "instrument": INSTRUMENT,
        "note": "Written by scripts/review_analyses.py (the AI assistant, 2026-10-10) for the "
                "simulated review paper/reviews/critical_review_2026-10-10.md. Post-hoc, "
                "exploratory analyses of the frozen A-D batch; no instrument, key, lexicon or "
                "registered number changes.",
        "inputs": {
            "evaluation.json": _sha(args.evaluation),
            "observation.json": _sha(args.observation),
            "calibration.json": _sha(args.calibration),
            "keys": {tid: _sha(p) for tid, p in sorted(key_paths.items())},
            "runs": {"directory": _rel(args.runs), "runs": len(runs),
                     "files_sha256": _runs_digest(runs)},
            "probes": {_rel(p): _sha(p) for p in probe_paths},
            "calibration_files": {p: _sha(_REPO / p) for p in sorted(set(used))},
        },
        "corpora": corpora,
        "min_rba_pool": R.MIN_RBA_POOL,
        "resolution": resolution(runs, corpora, withheld),
        "lexical_overlap": lexical_overlap(keys, runs),
        "coverage_split": coverage_split(runs, keys, corpora),
        "without_share_spent": without_share_spent(runs, key_paths, corpora),
        "binding": binding(runs, keys, corpora, obs_rows),
        "calibration": cal,
        "corpus_stats": corpus_stats(tasks, corpora, runs, ev),
        "maskdoc_without_lost": maskdoc_without_lost(probe_paths, corpora, tasks),
        "cost": cost(runs, obs_rows),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--evaluation", type=Path, default=_REPO / "eval" / "evaluation.json")
    ap.add_argument("--runs", type=Path, default=_REPO / "eval" / "runs")
    ap.add_argument("--tasks", type=Path, default=_REPO / "eval" / "tasks.json")
    ap.add_argument("--observation", type=Path, default=_REPO / "eval" / "observation.json")
    ap.add_argument("--calibration", type=Path,
                    default=_REPO / "eval" / "calibration" / "calibration.json")
    ap.add_argument("--probe", type=Path, action="append", default=None,
                    help="a tier1_probe.py analysis (repeatable; default eval/probe/*.json)")
    ap.add_argument("--insample-report", type=Path, default=None,
                    help="the pilot baseline report on A that the in-sample labels describe "
                         "(default: found under eval/runs/ or eval/pilot/ by its sha256)")
    ap.add_argument("--bootstrap", type=int, default=BOOTSTRAP_RESAMPLES,
                    help="bootstrap resamples for kappa's interval")
    ap.add_argument("--seed", type=int, default=BOOTSTRAP_SEED)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    if args.bootstrap < 1:
        ap.error("--bootstrap must be at least 1")
    out = build(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    rows = {r["id"]: r["status"] for r in out["calibration"]["rows"]}
    print(f"wrote {_rel(args.out)}: {out['inputs']['runs']['runs']} runs; calibration rows "
          + ", ".join(f"{k} {v}" for k, v in rows.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
