#!/usr/bin/env python3
"""Short echoes against entity masking (S6), and dispersion and effect sizes (S13).

Why this exists
---------------
The simulated review of 2026-10-26 (``paper/reviews/simulated_review_2026-10-26.md``)
asks two things the frozen A-D batch can answer offline. S6: how much corpus
text shorter than the monitor's 5-word run reaches C, set against masking the
entities and sending the documents. S13: the dispersion and an interval of
judged quality, and effect sizes between the arms. ``PRIVDEEP_ICCIT_SCOPE.md``
§13, signed by the author on 2026-10-26, fixes what is computed before any
value was seen; this script computes exactly that, offline and free, from
``eval/runs/``, ``eval/evaluation.json`` and ``eval/probe/``, and writes
``eval/paper/posthoc.json``, which ``make_paper_tables.py`` reads into
numbers.json. Written by the AI assistant on 2026-10-26 under scope §13.

Every figure here is post hoc and exploratory (§13.3). None tests, replaces or
reinterprets a registered hypothesis or outcome, and none changes a frozen
number, an instrument, a gold key or a lexicon. No model or network service is
called. Inputs are read-only.

What it computes (§13.2)
------------------------
(a) **S6, short echoes.** Per corpus A-D, for each of its nine pooled runs
    (three arms, three repeats): the distinct word n-grams of 2, 3 and 4
    tokens in the run's core-sent content that also occur in the corpus
    documents, with every n-gram made only of stopwords dropped; per n and
    for 2-4 together (the sum of the three), per run and as min-max over the
    nine. Beside it, the same count for the entity-masked documents of the
    masking probe under the shared extraction.

    * *Core-sent content* is H3's: ``run_evaluation.scan_trace``, whose
      ``core-sent`` side is the system, messages and tools fields
      (``_sent_fields``) of every exchange the monitor let through, with the
      user goal cut out verbatim and then every span repeating an earlier
      reply of the same run (``_cloud_segments``: both reply fields, lines of
      at least ``ECHO_MIN_TOKENS`` tokens), by the scan's own ``_cut``. A
      refused exchange is the scan's ``not-sent`` side and is left out; reply
      fields are never request content.
    * *Normalisation* is the monitor's: ``shared.shingle_filter.tokenize``
      (NFKC, casefold, confusable folding, default-ignorables removed, words
      ``[^\\W_]+``), and an n-gram is its tokens joined by one space, as
      ``ShingleFilter._shingles`` builds the shingles the 5-word check looks
      up. Nothing is reimplemented.
    * *Corpus n-grams* are those of each document of ``eval/corpora/<task>``
      (``tier1_probe.load_corpus``, the pipeline's loader), never across two
      documents, as ``containment.build_filter`` indexes one document at a
      time. Every document counts, C's lost one included: the filter indexes
      the whole corpus, as deployed.
    * *Stopwords*: ``STOPWORDS``, the 127 words of NLTK's English list,
      typed out. An n-gram every token of which is a stopword is dropped, on
      both sides and from the corpus sets.
    * *The masked documents* are those behind ``maskdoc_*_shared_nolost``:
      the probe's first extraction (``runs/<task>__r5/extractions.json``,
      the one all nine runs of the corpus masked), each document masked by
      ``tier1_probe``'s ``SlotMasker(ANALYSIS_SALT, normalise=True)``, one
      masker over the corpus in document order, and the documents that
      extraction lost (every extractor reply dropped: no entity, no relation;
      ``review_analyses._lost``) left out, as ``maskdoc_without_lost`` does.

(b) **S13, dispersion and effect size.**

    * Per arm, over its twelve pooled runs: each run's judged quality, the
      mean over its judgements of each judgement's mean over the criteria
      other than groundedness (``run_evaluation._judge_block``'s
      ``without_groundedness``, the source of ``judge_mean_exgr_<arm>``);
      their mean, sample SD (n-1), min and max; and a percentile-bootstrap
      95% interval of the mean over runs: 10,000 resamples of the runs with
      replacement, ``random.Random(BOOTSTRAP_SEED)``.
    * Per corpus, Cliff's delta between r1's runs (x) and baseline's (y) for
      attribute accuracy and for RBA, the frozen rule's per-run scores behind
      ``attr_<arm>_<L>`` and ``rba_<arm>_<L>``:
      delta = (#(x > y) - #(x < y)) / (n1 n2), positive when r1 is higher.

Choices the repository forces, stated
-------------------------------------
* N-grams are formed within each piece of core-written text the scan's cuts
  leave, never across a cut: the words on either side of a removed goal or
  echo span were not adjacent on the wire. ``_cut`` marks a cut with a line
  break, which ``tokenize`` treats as any separator, so the text's own line
  breaks are first written as U+2028 (a separator to ``tokenize`` and to
  ``_cut``'s lookarounds alike) and the pieces are split at ``_cut``'s breaks
  only; each field's tokens are checked equal to the scan's own. The text's
  own line breaks do not end a piece, as they do not for the monitor, which
  tokenises a whole value.
* An n-gram lies within one field of one exchange (the messages field joins
  its messages with a line break, as ``_sent_fields`` does); distinct is over
  the whole run.
* Slot placeholders stay in the text and are tokens (``slot``, the category,
  the id) on the wire and in the masked documents alike, so no n-gram joins
  the words on either side of a masked entity.
* The arm's judged quality is the mean of its runs' values. Each run has the
  same number of judgements (three), so this is the judgement-pooled mean
  ``judge_mean_exgr_<arm>`` reads, which the reproduction check confirms.
* The bootstrap: the runs in run-id order, a fresh ``random.Random`` seeded
  with ``BOOTSTRAP_SEED`` per arm (so an arm's interval does not depend on
  which arms are computed before it), the statistic the mean
  (``statistics.fmean``), and the interval the order statistics at
  floor(0.025 m) and ceil(0.975 m) - 1 of the m sorted resample means
  (``review_analyses.percentile_ci``'s rule, the repository's percentile
  interval): the 2.5th and 97.5th percentiles without interpolation.
* The missing-value rule is the aggregate's (``rate_stats``): a None or NaN
  value is no value, and so is an RBA resting on fewer than ``MIN_RBA_POOL``
  scored occurrences (``_thin_rba``). Cliff's delta is over the runs with a
  value, with n1 and n2 their counts, and None when either side has none:
  r1 on C for both measures, as the paper's n/a.

Checks before anything is written
---------------------------------
The script stops, and writes nothing, unless every one of these holds:
each pooled run's ``measurement.json`` is the row ``evaluation.json`` pooled
(faithfulness and judgements equal); each run's manifest names the documents
of ``eval/corpora/<task>`` (doc ids and lengths) and records the shingle count
those documents give; the goal is the tasks file's; the per-run inputs,
aggregated as ``make_paper_tables.py`` aggregates them, give the frozen keys of
``numbers.json`` (``judge_mean_exgr_<arm>``, ``attr_<arm>_<L>`` and ``_n``,
``rba_<arm>_<L>`` and ``_n``); the masking reproduces the probe's per-document
records and gives ``maskdoc_5gram_pct_shared_nolost_<L>`` and
``maskdoc_surfaces_surviving_shared_nolost_<L>``; and the scan of the same
traces gives H3's ``h3_hits``, ``h3_label_group_hits`` and ``h3_runs_scanned``.

Output
------
Counts, statistics, run ids, repository paths and sha256 digests only: never
an n-gram, a document string or a report sentence. Judge rationales,
adversary output and faithfulness occurrences are never opened. The same
inputs give the same bytes.

Usage
-----
    /usr/bin/python3 scripts/posthoc_2026_10_26.py
    /usr/bin/python3 scripts/posthoc_2026_10_26.py --out build/posthoc.json
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import random
import re
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "backend" / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts import run_evaluation as R  # noqa: E402
from scripts import tier1_probe as T  # noqa: E402
from shared.shingle_filter import ShingleFilter, tokenize  # noqa: E402

__all__ = ["ALL", "BOOTSTRAP_RESAMPLES", "BOOTSTRAP_SEED", "NS", "STOPWORDS", "bootstrap_mean_ci",
           "build", "cliffs_delta", "core_sent_segments", "gram_sets", "informative",
           "judged_quality", "lost_documents", "main", "mismatches", "ngrams", "percentile_ci",
           "run_rate", "shared_counts", "spread"]

INSTRUMENT = "scripts/posthoc_2026_10_26.py"
DEFAULT_OUT = _REPO / "eval" / "paper" / "posthoc.json"
DEFAULT_EVALUATION = _REPO / "eval" / "evaluation.json"
DEFAULT_RUNS = _REPO / "eval" / "runs"
DEFAULT_TASKS = _REPO / "eval" / "tasks.json"
DEFAULT_NUMBERS = _REPO / "eval" / "paper" / "numbers.json"
DEFAULT_PROBES = "eval/probe/*.json"
ARMS = ("baseline", "r5", "r1")
NS = (2, 3, 4)
ALL = "2-4"
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261026
NA = "n/a"
# make_paper_tables._RUN_EXTRACTION: the probe extraction a run directory holds,
# which is the runs' shared one.
_RUN_EXTRACTION = re.compile(r"(^|/)runs/[^/]+/extractions\.json$")
# A separator to `tokenize` and to `_cut`'s lookarounds, as "\n" is; it stands in
# for the text's own line breaks so that `_cut`'s are the only "\n" left.
_BREAK = " "

# NLTK's English stopword list as it stood with 127 words (nltk.corpus.stopwords,
# before the 2018 additions), typed out so that nothing is downloaded and the
# list cannot move. The clitic pieces "s", "t" and "don" are on it, which suits
# a tokenizer that splits "don't" into "don" and "t".
STOPWORDS = frozenset("""
i me my myself we our ours ourselves you your yours yourself yourselves
he him his himself she her hers herself it its itself they them their theirs
themselves what which who whom this that these those am is are was were be
been being have has had having do does did doing a an the and but if or
because as until while of at by for with about against between into through
during before after above below to from up down in out on off over under
again further then once here there when where why how all any both each few
more most other some such no nor not only own same so than too very s t can
will just don should now
""".split())
if len(STOPWORDS) != 127:
    raise RuntimeError(f"STOPWORDS holds {len(STOPWORDS)} words, not NLTK's 127")


# ------------------------------------------------------------------ helpers

def _rel(p: Path) -> str:
    p = p.resolve()
    return p.relative_to(_REPO).as_posix() if p.is_relative_to(_REPO) else str(p)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _read(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def _fmt(x: float | None, dp: int = 2) -> str:
    """make_paper_tables.fmt_num (fmt_fixed): fixed point, no negative zero."""
    if x is None:
        return NA
    s = f"{x:.{dp}f}"
    return s[1:] if s.startswith("-") and float(s) == 0 else s


def _fmt_pct(share: float | None) -> str:
    """make_paper_tables.fmt_pct at 1 dp."""
    return NA if share is None else f"{_fmt(100 * share, 1)}%"


def spread(values: Sequence[float]) -> dict[str, Any]:
    """n, mean, sample SD (n-1; None for one value), min and max."""
    v = list(values)
    if not v:
        return {"n": 0, "mean": None, "sd": None, "min": None, "max": None}
    return {"n": len(v), "mean": statistics.fmean(v),
            "sd": statistics.stdev(v) if len(v) > 1 else None, "min": min(v), "max": max(v)}


# ----------------------------------------------------------------- (a) S6

def ngrams(tokens: Sequence[str], n: int) -> set[str]:
    """The distinct n-grams of `tokens`, built as the monitor builds a shingle."""
    return set(ShingleFilter._shingles(list(tokens), n, n))


def informative(gram: str) -> bool:
    """False for an n-gram made only of stopwords. Tokens hold no space."""
    return any(t not in STOPWORDS for t in gram.split(" "))


def gram_sets(token_streams: Iterable[Sequence[str]]) -> dict[int, set[str]]:
    """Per n in NS, the distinct informative n-grams over the streams, none of
    which spans two streams."""
    out: dict[int, set[str]] = {n: set() for n in NS}
    for toks in token_streams:
        for n in NS:
            out[n] |= {g for g in ngrams(toks, n) if informative(g)}
    return out


def shared_counts(content: dict[int, set[str]], corpus: dict[int, set[str]]) -> dict[str, int]:
    """How many of the content's n-grams are corpus n-grams, per n and together."""
    c = {str(n): len(content[n] & corpus[n]) for n in NS}
    c[ALL] = sum(c[str(n)] for n in NS)
    return c


def core_sent_segments(trace: Sequence[dict[str, Any]], goal: str) -> list[str]:
    """One run's core-sent content, as H3's scan defines it, in the pieces its
    cuts leave.

    The loop is ``run_evaluation.scan_trace``'s: per exchange, per field of
    ``_sent_fields``, the goal cut out and then every earlier reply segment;
    a refused exchange is the scan's not-sent side and is skipped, and every
    exchange's reply segments join ``earlier`` after it, refused or not."""
    goal_spans = [goal] if goal.strip() else []
    segments: list[str] = []
    earlier: list[str] = []
    for i, e in enumerate(trace):
        if not e.get("refused"):
            for field, text in R._sent_fields(e).items():
                rest, _ = R._cut(text.replace("\n", _BREAK), goal_spans)
                rest, _ = R._cut(rest, earlier)
                h3_rest, _ = R._cut(R._cut(text, goal_spans)[0], earlier)
                if tokenize(rest) != tokenize(h3_rest):
                    raise SystemExit(f"exchange {i}, field {field}: the pieces do not hold the "
                                     "tokens H3's scan reads")
                segments += rest.split("\n")
        earlier += R._cloud_segments(e)
    return segments


def lost_documents(extraction: dict[str, Any]) -> list[str]:
    """Documents whose every extractor reply was dropped, with no entity and no
    relation (review_analyses._lost, make_paper_tables._maskdoc_facts's rule)."""
    return sorted(d.get("doc_id") for d in extraction.get("documents") or []
                  if d.get("chunks") and (d.get("dropped_malformed") or 0) >= d["chunks"]
                  and not d.get("entities") and not d.get("relations"))


def _shingle_count(docs: Sequence[Any], n_min: int, n_max: int) -> int:
    """What the sealed filter's n_added counts: every window of n_min..n_max
    tokens of every document, repeats included (ShingleFilter.index_document)."""
    return sum(max(0, len(t) - n + 1) for t in (tokenize(d.text) for d in docs)
               for n in range(n_min, n_max + 1))


def _masked(corpus: Any, loaded: Any) -> list[tuple[str, str]]:
    """(doc_id, masked text) per document: tier1_probe.masked_exposure's masking."""
    masker = T.SlotMasker(T.ANALYSIS_SALT, normalise=True)
    return [(d.doc_id, masker.mask(d, dex.entities).masked_text)
            for d, dex in zip(corpus.docs, loaded.extractions, strict=True)]


def _exposure(corpus: Any, masked: Sequence[tuple[str, str]]) -> list[dict[str, Any]]:
    """tier1_probe.masked_exposure's per-document figures (review_analyses.
    _exposure_rows), kept per document so a lost one can be left out."""
    f = T.build_filter(corpus.docs, salt=T.FILTER_SALT, n_min=T.SHINGLE_N_MIN,
                       n_max=T.SHINGLE_N_MAX, hit_threshold=T.SHINGLE_HIT_THRESHOLD)
    surfaces = list((corpus.surfaces or {}).get("surfaces", []))
    rows = []
    for doc_id, text in masked:
        t = tokenize(text)
        grams5 = [" ".join(t[i:i + 5]) for i in range(len(t) - 4)]
        rows.append({"doc_id": doc_id, "refused": f.inspect(text).blocked,
                     "masked_5grams": len(grams5),
                     "masked_5grams_hit": sum(1 for g in grams5 if g.encode("utf-8") in f.bloom),
                     "surviving": T._surviving(T._strip_slots(text), surfaces)})
    return rows


def _exposure_of(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    masked = sum(r["masked_5grams"] for r in rows)
    survived: Counter[str] = Counter()
    for r in rows:
        survived.update(r["surviving"])
    return {"documents": len(rows),
            "masked_5gram_hit_share": (sum(r["masked_5grams_hit"] for r in rows) / masked
                                       if masked else None),
            "surfaces_distinct": len(survived), "surfaces_occurrences": sum(survived.values())}


def masked_comparator(probe: dict[str, Any], probe_label: str, corpus: Any,
                      corpus_grams: dict[int, set[str]], run_extractions: Sequence[Path]
                      ) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """The masked documents' count, the figures it reproduces, and its files."""
    meta = (probe.get("extractions") or [{}])[0]
    files = meta.get("files") or []
    if not files or not _RUN_EXTRACTION.search(files[0]):
        raise SystemExit(f"{probe_label}: its first extraction is not a run's shared one")
    path = _REPO / files[0]
    data = _read(path)
    if T._content_sha(data) != meta.get("sha256"):
        raise SystemExit(f"{probe_label}: {files[0]} is not the extraction the probe read")
    loaded, refused = T.read_extractions([path], corpus)
    if len(loaded) != 1 or refused:
        raise SystemExit(f"{files[0]}: tier1_probe.py does not load it as one extraction")
    masked = _masked(corpus, loaded[0])
    rows = _exposure(corpus, masked)
    me = probe["per_extraction"][0]["masked_exposure"]
    full = _exposure_of(rows)
    want = (len(me["documents"]), me["masked_5gram_hit_share"],
            me["generator_surfaces_surviving"]["distinct"],
            me["generator_surfaces_surviving"]["occurrences"])
    got = (full["documents"], full["masked_5gram_hit_share"], full["surfaces_distinct"],
           full["surfaces_occurrences"])
    per_doc = [(r["doc_id"], r["refused"], r["masked_5grams_hit"]) for r in rows]
    if want != got or per_doc != [(d["doc_id"], d["refused"], d["masked_5grams_hit"])
                                  for d in me["documents"]]:
        raise SystemExit(f"{probe_label}: the masking does not reproduce the probe's records")
    lost = set(lost_documents(data))
    kept_rows = [r for r in rows if r["doc_id"] not in lost]
    kept = _exposure_of(kept_rows)
    grams = gram_sets(tokenize(text) for doc_id, text in masked if doc_id not in lost)
    sharing = sum(1 for p in run_extractions if T._content_sha(_read(p)) == meta["sha256"])
    out = {"extraction": files[0], "extraction_sha256": meta["sha256"],
           "runs_sharing_it": sharing, "documents": len(kept_rows),
           "lost_documents_left_out": len(lost), **shared_counts(grams, corpus_grams)}
    figures = {"maskdoc_5gram_pct_shared_nolost": _fmt_pct(kept["masked_5gram_hit_share"]),
               "maskdoc_surfaces_surviving_shared_nolost": str(kept["surfaces_distinct"])}
    return out, figures, [files[0]]


# ---------------------------------------------------------------- (b) S13

def judged_quality(judgements: Sequence[dict[str, Any]] | None) -> float | None:
    """One run's judged quality: the mean over its judgements of each one's mean
    over the criteria other than groundedness (_judge_block's
    without_groundedness, per run); None when no judgement has them all."""
    js = list(judgements or [])
    crits = next((list(j["criteria"]) for j in js if j.get("criteria")), [])
    inf = [c for c in crits if c != R.GROUNDEDNESS]
    vals = [statistics.fmean(j["private"][c] for c in inf) for j in js
            if inf and all(c in j.get("private", {}) for c in inf)]
    return statistics.fmean(vals) if vals else None


def run_rate(faithfulness: dict[str, Any] | None, key: str) -> float | None:
    """A run's private-side rate under the aggregate's rule (rate_stats): None
    for a missing, None or NaN value, and for an RBA under MIN_RBA_POOL."""
    f = faithfulness.get("private") if isinstance(faithfulness, dict) else None
    if not isinstance(f, dict):
        return None
    v = f.get(key)
    if v is None or R._is_nan(v) or (key == "rba" and R._thin_rba(f)):
        return None
    return v


def cliffs_delta(xs: Iterable[float | None], ys: Iterable[float | None]) -> dict[str, Any]:
    """Cliff's delta of xs against ys over the values present:
    (#(x > y) - #(x < y)) / (n1 n2); None when either side has no value."""
    a = [x for x in xs if x is not None]
    b = [y for y in ys if y is not None]
    n1, n2 = len(a), len(b)
    if not n1 or not n2:
        return {"n1": n1, "n2": n2, "greater": None, "less": None, "ties": None, "delta": None}
    gt = sum(1 for x in a for y in b if x > y)
    lt = sum(1 for x in a for y in b if x < y)
    return {"n1": n1, "n2": n2, "greater": gt, "less": lt, "ties": n1 * n2 - gt - lt,
            "delta": (gt - lt) / (n1 * n2)}


def percentile_ci(values: Sequence[float], level: float = 0.95) -> list[float] | None:
    """The percentile interval: the order statistics at floor(m (1-level)/2) and
    ceil(m (1+level)/2) - 1 of the m sorted values (review_analyses.percentile_ci)."""
    v = sorted(values)
    m = len(v)
    if m == 0:
        return None
    return [v[min(m - 1, math.floor(m * (1 - level) / 2))],
            v[max(0, math.ceil(m * (1 + level) / 2) - 1)]]


def bootstrap_mean_ci(values: Sequence[float], *, resamples: int = BOOTSTRAP_RESAMPLES,
                      seed: int = BOOTSTRAP_SEED) -> list[float] | None:
    """Percentile-bootstrap 95% interval of the mean: `resamples` resamples of
    the values with replacement, from a generator seeded with `seed`."""
    v = list(values)
    if not v:
        return None
    rng = random.Random(seed)  # noqa: S311 - a reproducible statistic, not a secret
    n = len(v)
    return percentile_ci([statistics.fmean([v[rng.randrange(n)] for _ in range(n)])
                          for _ in range(resamples)])


# -------------------------------------------------------------- the checks

def mismatches(expected: dict[str, str], got: dict[str, str]) -> list[str]:
    """Each key whose recomputed value is not the frozen one, as 'key: frozen
    X, recomputed Y'; a key the frozen file lacks counts as a mismatch."""
    return [f"{k}: frozen {expected.get(k, '(absent)')!r}, recomputed {v!r}"
            for k, v in sorted(got.items()) if expected.get(k) != v]


def _pooled(ev: dict[str, Any], letters: dict[str, str]) -> dict[str, dict[str, list[str]]]:
    """Letter -> arm -> the runs the aggregate pooled, in run-id order."""
    out: dict[str, dict[str, list[str]]] = {}
    for L, tid in letters.items():
        arms = ((ev.get("by_task") or {}).get(tid) or {}).get("arms") or {}
        out[L] = {a: sorted((arms.get(a) or {}).get("runs") or []) for a in ARMS}
    return out


def _letters(ev: dict[str, Any]) -> dict[str, str]:
    got = {L: t for L, t in sorted(((ev.get("hypotheses") or {}).get("corpora") or {}).items())
           if t}
    if got != {L: t for t, L in sorted(R.CORPUS_OF_TASK.items(), key=lambda x: x[1])}:
        raise SystemExit(f"evaluation.json maps the corpora as {got}, not as "
                         "run_evaluation.CORPUS_OF_TASK does")
    return got


# ------------------------------------------------------------------- build

def build(args: argparse.Namespace) -> dict[str, Any]:
    ev_path, runs_dir, numbers_path = Path(args.evaluation), Path(args.runs), Path(args.numbers)
    ev = _read(ev_path)
    numbers = _read(numbers_path)
    tasks = {t.id: t for t in R.load_tasks(Path(args.tasks))}
    letters = _letters(ev)
    pooled = _pooled(ev, letters)
    rows = {r["run"]: r for r in ev.get("per_task") or []}
    probe_paths = sorted(Path(p) for p in (args.probe or glob.glob(str(_REPO / DEFAULT_PROBES))))
    probes = {}
    for p in probe_paths:
        pr = _read(p)
        probes[(pr.get("corpus") or {}).get("id")] = (pr, p)

    run_files: list[tuple[str, str, str]] = []
    expected: dict[str, str] = {}
    got: dict[str, str] = {}
    s6: dict[str, Any] = {}
    per_run: dict[str, dict[str, Any]] = {}
    h3_hits = h3_label = h3_runs = 0
    extraction_files: list[str] = []
    for L, tid in letters.items():
        task = tasks.get(tid)
        if task is None or tid not in probes:
            raise SystemExit(f"corpus {L} ({tid}): no task in the tasks file or no probe")
        corpus = T.load_corpus(task.corpus)
        corpus_grams = gram_sets(tokenize(d.text) for d in corpus.docs)
        docs = sorted((d.doc_id, len(d.text)) for d in corpus.docs)
        groups, _src = R.surface_groups_for(task)
        group_of: dict[str, list[str]] = {}
        for g, ss in (groups or {}).items():
            for s in ss:
                group_of.setdefault(s, []).append(g)
        runs_out: dict[str, Any] = {}
        for arm in ARMS:
            for run in pooled[L][arm]:
                d = runs_dir / run
                paths = [d / f for f in ("measurement.json", "manifest.json",
                                         "egress_trace.jsonl", "extractions.json")]
                for p in paths:
                    if not p.is_file():
                        raise SystemExit(f"{run}: no {p.name} under {runs_dir}")
                    run_files.append((run, p.name, _sha(p)))
                m, man = _read(paths[0]), _read(paths[1])
                row = rows.get(run)
                if (row is None or (m.get("task_id"), m.get("arm")) != (tid, arm)
                        or m.get("faithfulness") != row.get("faithfulness")
                        or m.get("judgements") != row.get("judgements")):
                    raise SystemExit(f"{run}: measurement.json is not the row evaluation.json "
                                     "pooled")
                if row.get("goal") != task.goal:
                    raise SystemExit(f"{run}: measured with another goal than the tasks file's")
                cont = man.get("containment") or {}
                if (sorted((x["doc_id"], x["chars"]) for x in man.get("documents") or []) != docs
                        or cont.get("shingles") != _shingle_count(corpus.docs, cont["n_min"],
                                                                  cont["n_max"])):
                    raise SystemExit(f"{run}: its manifest does not name the documents of "
                                     f"{_rel(task.corpus)}")
                trace = R._read_trace(d) or []
                if not trace:
                    raise SystemExit(f"{run}: no exchange traced")
                # H3's own scan of the same trace, for the reproduction check.
                for h in R.scan_trace(trace, list(group_of), goal=task.goal):
                    if h["side"] == "core-sent":
                        if all(g in R.LABEL_GROUPS for g in group_of[h["needle"]]):
                            h3_label += h["count"]
                        else:
                            h3_hits += h["count"]
                h3_runs += 1
                grams = gram_sets(tokenize(s) for s in core_sent_segments(trace, task.goal))
                runs_out[run] = {"arm": arm, **shared_counts(grams, corpus_grams)}
                per_run[run] = {"letter": L, "arm": arm,
                                "judged_quality": judged_quality(m.get("judgements")),
                                "attribute_accuracy": run_rate(m.get("faithfulness"),
                                                               "attribute_accuracy"),
                                "rba": run_rate(m.get("faithfulness"), "rba")}
        pr, pp = probes[tid]
        if (_REPO / pr["corpus"]["path"]).resolve() != task.corpus.resolve():
            raise SystemExit(f"{_rel(pp)}: probes another directory than {_rel(task.corpus)}")
        masked, figures, files = masked_comparator(
            pr, _rel(pp), corpus, corpus_grams,
            [runs_dir / r / "extractions.json" for a in ARMS for r in pooled[L][a]])
        extraction_files += files
        for k, v in figures.items():
            expected[f"{k}_{L}"] = numbers.get(f"{k}_{L}", "(absent)")
            got[f"{k}_{L}"] = v
        s6[L] = {"task": tid, "corpus": _rel(task.corpus), "corpus_documents": len(corpus.docs),
                 "corpus_ngrams": {**{str(n): len(corpus_grams[n]) for n in NS},
                                   ALL: sum(len(corpus_grams[n]) for n in NS)},
                 "n_runs": len(runs_out), "runs": runs_out,
                 "range_over_runs": {k: {"min": min(r[k] for r in runs_out.values()),
                                         "max": max(r[k] for r in runs_out.values())}
                                     for k in [*map(str, NS), ALL]},
                 "masked_documents": masked}

    # The frozen keys, aggregated as make_paper_tables aggregates them.
    s13_quality: dict[str, Any] = {}
    for arm in ARMS:
        runs = sorted(r for r, x in per_run.items() if x["arm"] == arm)
        vals = [per_run[r]["judged_quality"] for r in runs]
        if any(v is None for v in vals):
            raise SystemExit(f"{arm}: a pooled run has no judged quality")
        st = spread(vals)
        frozen = (((ev.get("arms") or {}).get(arm) or {}).get("judge") or {}).get(
            "mean_excluding_groundedness", {}).get("private", {}).get("mean")
        if frozen is None or abs(st["mean"] - frozen) > 1e-9:
            raise SystemExit(f"{arm}: the runs' mean judged quality {st['mean']} is not the "
                             f"aggregate's {frozen}")
        expected[f"judge_mean_exgr_{arm}"] = numbers.get(f"judge_mean_exgr_{arm}", "(absent)")
        got[f"judge_mean_exgr_{arm}"] = _fmt(st["mean"])
        s13_quality[arm] = {**st, "ci95_bootstrap": bootstrap_mean_ci(vals),
                            "runs": {r: per_run[r]["judged_quality"] for r in runs}}
    cliff: dict[str, Any] = {}
    for L in letters:
        for arm in ARMS:
            for short, k in (("attr", "attribute_accuracy"), ("rba", "rba")):
                vs = [per_run[r][k] for r in pooled[L][arm]]
                have = [v for v in vs if v is not None]
                key = f"{short}_{arm}_{L}"
                expected[key] = numbers.get(key, "(absent)")
                got[key] = _fmt(statistics.fmean(have)) if have else NA
                expected[key + "_n"] = numbers.get(key + "_n", "(absent)")
                got[key + "_n"] = f"{len(have)}/{len(vs)}"
        cliff[L] = {}
        for k in ("attribute_accuracy", "rba"):
            r1 = {r: per_run[r][k] for r in pooled[L]["r1"]}
            b = {r: per_run[r][k] for r in pooled[L]["baseline"]}
            cliff[L][k] = {**cliffs_delta(r1.values(), b.values()), "r1": r1, "baseline": b}
    for k, v in (("h3_hits", h3_hits), ("h3_label_group_hits", h3_label),
                 ("h3_runs_scanned", h3_runs)):
        expected[k] = numbers.get(k, "(absent)")
        got[k] = str(v)
    bad = mismatches(expected, got)
    if bad:
        raise SystemExit("the per-run inputs do not reproduce the frozen keys of "
                         f"{_rel(numbers_path)}; nothing is written:\n  " + "\n  ".join(bad))

    h = hashlib.sha256()
    for run, name, sha in sorted(run_files):
        h.update(f"{run}/{name} {sha}\n".encode())
    corpus_files = {_rel(p): _sha(p) for tid in letters.values()
                    for p in sorted(tasks[tid].corpus.iterdir()) if p.is_file()}
    return {
        "instrument": INSTRUMENT,
        "scope": "PRIVDEEP_ICCIT_SCOPE.md §13",
        "_notes": NOTES,
        "inputs": {"evaluation.json": _sha(ev_path), "numbers.json": _sha(numbers_path),
                   "tasks.json": _sha(Path(args.tasks)),
                   "probes": {_rel(p): _sha(p) for p in probe_paths},
                   "extractions": {f: _sha(_REPO / f) for f in extraction_files},
                   "corpora": corpus_files,
                   "run_files": {"files": len(run_files), "sha256": h.hexdigest()}},
        "reproduced": {k: got[k] for k in sorted(got)},
        "s6": s6,
        "s13": {
            "judged_quality": s13_quality,
            "bootstrap": {"resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED,
                          "level": 0.95, "statistic": "mean over runs"},
            "cliffs_delta_r1_vs_baseline": cliff,
        },
    }


NOTES: dict[str, Any] = {
    "written_by": ("the AI assistant, 2026-10-26, under PRIVDEEP_ICCIT_SCOPE.md §13 (signed by "
                   "the author on 2026-10-26)"),
    "status": ("post hoc and exploratory (§13.3): no figure here tests, replaces or reinterprets "
               "a registered hypothesis or outcome, and no frozen number changes"),
    "s6": ("Per corpus and pooled run: distinct word n-grams (n = 2, 3, 4) of the run's core-sent "
           "content, as H3's scan defines it (run_evaluation.scan_trace: system, messages and "
           "tools of every exchange the monitor let through, the user goal and every span "
           "repeating an earlier reply of the run cut out), that are also n-grams of a corpus "
           "document, after the monitor's normalisation (shared.shingle_filter.tokenize; an "
           "n-gram is its tokens joined by one space, ShingleFilter._shingles) and with every "
           "n-gram made only of stopwords dropped (STOPWORDS: NLTK's 127 English stopwords). "
           "'2-4' is the sum over n. range_over_runs is min-max over the corpus's nine runs "
           "(three arms, three repeats). masked_documents: the same count for the documents "
           "masked under the probe's shared extraction, lost documents left out (the documents "
           "behind maskdoc_*_shared_nolost)."),
    "s13": ("judged_quality: per arm over its pooled runs, each run's mean over its judgements of "
            "the judgement's mean over the criteria other than groundedness (as "
            "judge_mean_exgr_<arm>); sd is the sample SD (n-1); ci95_bootstrap is the "
            "percentile-bootstrap 95% interval of the mean over runs. cliffs_delta_r1_vs_baseline: "
            "per corpus, (#(r1 > baseline) - #(r1 < baseline)) / (n1 n2) over the runs' frozen "
            "attribute accuracy and RBA; positive means r1 higher; None where either arm has no "
            "run with a value."),
    "choices": [
        "N-grams are formed within each piece of core-written text the scan's cuts leave, never "
        "across a cut (the words either side of a removed goal or echo span were not adjacent on "
        "the wire); the text's own line breaks do not end a piece, as they do not for the "
        "monitor. Each field's tokens are checked equal to the scan's.",
        "An n-gram lies within one field of one exchange; distinct is over the whole run. Corpus "
        "n-grams lie within one document, every document of eval/corpora/<task> counted (C's lost "
        "one included), as the containment filter indexes them.",
        "Slot placeholders stay in the text as tokens, on the wire and in the masked documents "
        "alike, so no n-gram joins the words either side of a masked entity.",
        "The stopword filter applies to the content, the masked documents and the corpus alike.",
        "The masked documents: tier1_probe's SlotMasker(ANALYSIS_SALT, normalise=True) over the "
        "probe's first extraction (runs/<task>__r5/extractions.json, the one all nine runs of the "
        "corpus masked), without the documents it lost (review_analyses._lost); the masking "
        "reproduces the probe's per-document records and the maskdoc_*_shared_nolost keys.",
        "The arm's judged quality is the mean of its runs' values; every run has three "
        "judgements, so it equals the judgement-pooled judge_mean_exgr_<arm>.",
        "Bootstrap: runs in run-id order; random.Random(20261026), seeded afresh for each arm; "
        "10,000 resamples of the runs with replacement; the statistic the mean; the interval the "
        "order statistics at floor(0.025 m) and ceil(0.975 m) - 1 of the m sorted means "
        "(review_analyses.percentile_ci's rule), i.e. the 2.5th and 97.5th percentiles without "
        "interpolation.",
        "Missing values follow the aggregate (run_evaluation.rate_stats): a None or NaN value is "
        "no value, and so is an RBA on fewer than MIN_RBA_POOL (5) scored occurrences. Cliff's "
        "delta is over the runs with a value (n1 r1's, n2 baseline's) and None when either is 0.",
    ],
}


def _summary(out: dict[str, Any]) -> str:
    lines = ["S6: distinct corpus n-grams in core-sent content, min-max over the runs "
             "(2 | 3 | 4 | 2-4), against the masked documents"]
    for L, c in out["s6"].items():
        rr, md = c["range_over_runs"], c["masked_documents"]
        cells = " | ".join(f"{rr[k]['min']}-{rr[k]['max']}" for k in [*map(str, NS), ALL])
        mask = " | ".join(str(md[k]) for k in [*map(str, NS), ALL])
        lines.append(f"  {L} ({c['n_runs']} runs): {cells}    masked: {mask}")
    lines.append("S13: judged quality per arm over runs: mean, SD, min-max, bootstrap 95% CI")
    for arm, q in out["s13"]["judged_quality"].items():
        ci = q["ci95_bootstrap"]
        lines.append(f"  {arm} (n={q['n']}): {q['mean']:.3f}, SD {q['sd']:.3f}, "
                     f"{q['min']:.3f}-{q['max']:.3f}, [{ci[0]:.3f}, {ci[1]:.3f}]")
    lines.append("S13: Cliff's delta, r1 against baseline (n1, n2)")
    for L, c in out["s13"]["cliffs_delta_r1_vs_baseline"].items():
        parts = []
        for k in ("attribute_accuracy", "rba"):
            d = c[k]
            v = "None" if d["delta"] is None else f"{d['delta']:.2f}"
            parts.append(f"{k} {v} ({d['n1']}, {d['n2']})")
        lines.append(f"  {L}: " + "; ".join(parts))
    lines.append(f"reproduced {len(out['reproduced'])} frozen keys")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--evaluation", default=str(DEFAULT_EVALUATION))
    ap.add_argument("--runs", default=str(DEFAULT_RUNS))
    ap.add_argument("--tasks", default=str(DEFAULT_TASKS))
    ap.add_argument("--numbers", default=str(DEFAULT_NUMBERS),
                    help="the frozen numbers.json the per-run inputs must reproduce")
    ap.add_argument("--probe", action="append",
                    help=f"a tier1_probe.py analysis (repeatable; default {DEFAULT_PROBES})")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)
    out = build(args)
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(_summary(out))
    print(f"wrote {_rel(p)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
