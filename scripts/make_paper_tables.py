#!/usr/bin/env python3
"""Every number, table and data figure in the paper, built from frozen JSON.

Why this exists
---------------
Plan task PAP5a (PRIVDEEP_COMPLETION_PLAN.md Part B §5, PAP workstream, with the
Part D corrections and paper/VENUE_FACTS.md). No number in the manuscript is
typed by hand: each one is a ``«key»`` placeholder in the Word source, and this
script is the only thing that turns a key into a figure. That is the plan's
defence against stale and pilot figures, so the script refuses rather than
guesses: a skeleton key it cannot produce, a placeholder the fill pass has no
value for, a run scored against a stale key, or a wire excerpt that carries a
generator surface all stop it.

Run it with the system interpreter (``/usr/bin/python3``: python-docx 1.2.0 and
matplotlib 3.10.6, plan correction RF21). The project venv has neither
matplotlib nor python-docx 1.2.0; nothing here is installed into it.

Build mode (the default)
------------------------
Inputs, each a file another instrument wrote:

* ``--evaluation``: ``run_evaluation.py aggregate`` output, with the INS2b
  ``hypotheses`` block (refused without it). Refused too while any run of any
  task is scored against a key other than the corpus's current one, on the
  private side (``by_task[*].stale_key_runs``) or the oracle side (a
  ``per_task`` row whose oracle faithfulness carries another ``key_sha256``):
  the aggregate still averages such runs into the per-task blocks that the
  abstract and Table 3 read, so they must be rescored first;
* ``--probe`` (repeatable; default ``eval/probe/*.json``): ``tier1_probe.py
  analyse`` output, one per corpus. The pooled masked-document keys
  (``maskdoc_5gram_pct``, ``maskdoc_surfaces_surviving``) are n/a unless every
  corpus with runs in the aggregate has a probe; ``maskdoc_corpora`` names the
  corpora they cover. Table 3's G1 rows come from a probe's comparison of
  every measured corpus under its saved extraction, else under the stub; a
  stub-based G1 (``g1_stub_corpora`` names its corpora) stops the build unless
  ``--allow-stub-g1``;
* ``--fp``: ``measure_false_positives.py`` output with its ``deployed_chain``
  block (refused without it: the committed ``eval/fp_report.json`` predates it);
* ``--observation``: ``observation_table.py --out`` output;
* ``--calibration`` (optional): the calibration figures as JSON, shape
  ``{"rows": [{"id", "labeller", "blind", "in_sample", "occurrences",
  "agreement": {"k", "n"}, "kappa"}]}`` (a ``label`` is allowed and ignored).
  §5 states them in one sentence instead of a table (PRIVDEEP_COMPLETION_PLAN.md
  Part D AD32), and binds each row by its ``id``, never by its position in the
  file (CAL_ROWS): ``insample_A_baseline``, the baseline report on A labelled
  non-blind by the AI assistant that built the rule, in the same commit (the
  in-sample row: labeller ``assistant``, blind false, in_sample true);
  ``dev_A_r1`` and ``dev_A_oracle``, the development r1 report on A and its
  oracle report, and ``heldout_B_r1``, the held-out r1 report on B, each
  labelled blind by the author (labeller ``author``, blind true, in_sample
  false); and, added after the simulated review of 2026-10-10 as an
  exploratory row (CAL_EXPLORATORY), ``heldout_B_baseline``, the baseline report
  of the same corpus and repeat, labelled the same way, whose keys exist only
  once its labels do. A row whose id is unknown or repeated, or whose labeller, blind or
  in_sample is not what the sentence states for its id, is refused; so is a row
  without a labeller, a blind row not the author's, or a non-blind row that is
  not the assistant-written in-sample row. Each row gives
  ``cal_<id>_occurrences`` (occurrences labelled), ``cal_<id>_agreement`` (k/N
  over gold-valued occurrences, attribute axis), ``cal_<id>_agreement_pct`` and
  ``cal_<id>_kappa`` (Cohen's kappa; n/a when undefined, which the fill refuses
  in prose). A row that is absent, such as the held-out row before its labels
  exist, produces no keys, so a manuscript that quotes them stops the build and
  the fill instead of printing n/a. ``calibrate_faithfulness.py`` prints text
  only, so EXP8 writes this file;
* ``--review-analyses`` (optional): ``scripts/review_analyses.py`` output, the
  analyses from frozen data that the simulated review of 2026-10-10 asks for
  (resolution denominators, lexical overlap, coverage split, A without the
  share-spent facts, binding and its chance model, the calibration rows'
  agreement statistics, corpus statistics, masked-document exposure without
  lost documents, deployment and evaluation cost). Refused when it was built
  from another evaluation.json, observation.json or calibration.json than this
  build reads (by sha256), or for other corpora; a calibration figure that
  calibration.json also gives must agree with it. numbers_from_review lists
  the keys; none replaces an existing one;
* ``--posthoc`` (optional): ``scripts/posthoc_2026_10_26.py`` output
  (``eval/paper/posthoc.json``), the two offline analyses of scope §13 (signed
  2026-10-26), every figure post hoc and exploratory: S6's distinct corpus
  n-grams shorter than the 5-word run in core-sent content against the masked
  documents, and S13's per-arm spread and bootstrap interval of judged quality
  and per-corpus Cliff's delta. Refused when built from another evaluation.json
  (by sha256), for other corpora, or when a frozen key it reproduced differs
  from this build's. numbers_from_posthoc lists the keys; none replaces an
  existing one, and without the option the build is unchanged;
* ``--meta``: the author's non-numeric keys (names, affiliation, keywords,
  artifact URL, commits, AI-use declaration, formatted references), a flat
  JSON map. They are copied into numbers.json with ``meta`` as their source.
  Its ``freeze_commit`` must be the commit the aggregate records (its own
  ``git_commit``, or the one commit every pooled run records: phase one's
  manifest, else the measurement's provenance), or the build stops;
  ``--allow-commit-mismatch`` makes that a warning, for drafts only. Its dates
  (any ``*_date`` key, YYYY-MM-DD) are checked against their records
  (check_meta_dates): ``prereg_date`` the scope §8 signature, ``freeze_tag_date``
  the tag paper-freeze in git, ``batch_date`` the pooled runs' manifests; so are
  ``slm_model_id`` and ``cloud_model_id`` against the manifests;
* ``--real-l`` (optional): ``scripts/real_l.py scan`` output
  (``eval/real/out/real_l_scan.json``), track L (scope §12, signed
  2026-10-15): the three private arms over public ECHR judgments from TAB,
  standing in for private documents. Its keys are ``l_*`` and ``hl1_*``
  (numbers_from_real_l): ``hl1_outcome`` is the scan's own HL1 decision,
  never recomputed, with ``hl1_reason`` ("none" when there is none),
  ``hl1_computed`` (the outcome over the scanned collections alone, which
  differs from ``hl1_outcome`` only off the registered L1-L6) and
  ``hl1_registered``; ``l_digest_check`` (ok / mismatch / unrecorded) is the
  §12.8 check; the DIRECT block gives ``l_direct_strings``,
  ``l_direct_crossed_kn``, ``l_direct_bound`` (the rule-of-three 3/n when
  k = 0, else n/a; descriptive, §12.7), ``l_direct_pairs`` (string-by-run
  pairs) with its bound, ``l_direct_onecall_kn`` (the single-call reading H3
  uses, beside it) and ``l_direct_labels_crossed_kn`` (apart); QUASI is
  descriptive (``l_quasi_strings``, ``l_quasi_crossed_kn``, per arm
  ``l_quasi_crossed_<arm>_kn``, per entity type ``l_quasi_type_<T>_kn``);
  ``l_cross_route_summary`` words the routes (identifier type, entity type,
  stage, field, with counts; empty when none crossed); extractor recall and
  predicate echo once per extraction (``l_recall_exact_pct``,
  ``l_recall_covered_pct``, ``l_echo_pct``, each with its ``_kn``); G3 net of
  the no-trace control per arm (``l_g3_<arm>_net_kn``, an upper bound,
  §12.11) and the control (``l_g3_control_kn``); health and refusals
  (``l_health_valid_kn``, ``l_refused_attempts_kn``, ``l_plans_refused_kn``);
  the utility proxy (``l_sections_delivered_mean``, ``l_sections_refused_mean``,
  ``l_utility_strings_pct``). A scan over other collections than L1-L6 (the
  pilot) builds with a warning, and its hl1_outcome is "not testable";
* ``--presidio`` (optional, repeatable): ``scripts/presidio_residual.py``
  output, one file per collection (``eval/real/out/presidio_<id>.json``),
  pooled by summing into ``l_presidio_direct_kn``, ``l_presidio_quasi_kn``
  (strings surviving in the anonymised text, the per-string rule), the
  ``_onecall_kn`` readings beside them, ``_pct``, ``_present_kn``, per entity
  type ``l_presidio_<it>_type_<T>_kn``, and the versions it ran
  (``l_presidio_version``, ``l_presidio_model``). With ``--real-l`` the files
  must cover the scan's collections exactly, from the same identifiers.json
  and string counts (refused otherwise): the two figures stand side by side,
  never as one ranking (§12.6);
* ``--real-l-cost`` (optional): track L's recorded spend, which the scan JSON
  does not carry: the line ``scripts/real_l.py budget`` prints, captured to a
  file, or a JSON object ``{"private", "adversary", "spent_before"}`` in USD
  (``l_cost_usd`` = private + adversary; ``l_cost_total_usd`` adds what was
  spent before the batch);
* ``--skeleton``: the Word source. Every ``«key»`` in it must be produced, or
  the build fails and names the missing keys;
* ``--threat-model``: THREAT_MODEL.md, whose §4 table is condensed into Table 1.
  Its "Pinned by" column names each test or script by its file stem (Part D
  AD32), and the build stops unless each stem names exactly one .py or .sh
  file in the repository (_stem_index);
* ``--fig2-run`` (optional): an r1 run directory for the Fig. 2 excerpt;
* ``--runs`` (default ``eval/runs``): the run directories the aggregate read.
  Only Table 3's facts_structural cells read them: a run whose fact store ran
  and counted no structural fact writes no counter, which the aggregate reads
  as no value, and its manifest says it is 0 (_facts_structural). Without the
  directory the cells are the aggregate's. The probes' masked-document notes
  also read the shared extraction file each probe names first
  (_maskdoc_facts). The pooled runs' manifests also give the sealed Bloom
  filter's size (``mon_bloom_*``, checked against the --fp report's target rate)
  and the local model's quantisation (numbers_from_deployment), which, with the
  monitor's and extractor's code constants, §4 states.

Two options change what the paper shows. ``--fig2-full`` pastes the full Fig. 2
listing instead of the writing fallback's listing of at most six lines (the
fallback is invoked: PRIVDEEP_COMPLETION_PLAN.md §6 and Part D AD31).
``--traffic-rows`` puts back Table 3's per-arm traffic rows (slots on the wire,
relations sent, FACT references returned, request and response bytes, plan and
draft tokens): the author approved leaving them out on 2026-10-01 (Part D AD32),
so they are out by default and numbers.json keeps their keys for the artifact
(see table3: Table 3 is the fallback's fold of the former what-crosses table
into the faithfulness table).

Outputs, under ``--out`` (default ``eval/paper/``):

* ``numbers.json``: a flat, sorted map of key to formatted string. Every
  hypothesis outcome comes with its caveats as keys of their own: the reason
  when it is not testable (``*_reason``), the comparisons pooled over fewer
  runs than registered (``*_short_of_repeats``), and H2's floor flag
  (``h2_*_floor``). A skeleton key whose outcome is 'holds' over fewer pooled
  runs than registered stops the build unless ``--allow-short-repeats``;
* ``numbers.sources.json``: for every key, the file and JSON pointer (or code
  constant) it was read from, the raw value, and the format applied;
* ``tables.docx``: Tables 1-4, built on the skeleton's own styles (the ICCIT
  template's ``Normal Table`` with ``Table Paragraph`` cells; the template
  defines no other table style). When the skeleton carries the IEEE template's
  styles (scripts/paper_format.py, since 2026-10-03), each caption is "TABLE I."
  and its title in the Table Caption style above the table, notes are in the
  Table Note style, and the columns are widened to the template's text width,
  since the fill pass puts every table, and Figs 1-2, in a one-column section
  across both columns (paper_format.span), with figure captions "Figure n."
  below. Each
  table's caption carries a bookmark ``pap_<id>`` that the fill pass finds it
  by. Every figure in a table is a tagged value, as in the fill pass below;
* ``fig3_rba_strip.png`` (600 dpi, the venue's minimum) and ``.svg``, the
  per-run RBA strip plot with the oracle band, for the artifact only: the
  author removed it from the manuscript on 2026-10-02 to save page space
  (PRIVDEEP_COMPLETION_PLAN.md Part D AD33; Table 3 keeps each arm's and the
  oracle's [min–max] per corpus), so the fill pass never reads it and no
  caption is written (``fig3_points``, the points it draws, stays a key);
* ``fig2_wire_excerpt.txt``, when ``--fig2-run`` is given, and beside it
  ``fig2_listing.txt``, what the paper shows: by default the writing
  fallback's listing of at most six rendered lines (a label column; SENT: the
  referent's slot line with its fact stem, the ATTRIBUTES line and the code
  lines the sentence uses; RECEIVED: the sentence; LOCAL: its resolution; a
  line too long for its one line is cut with a visible ellipsis), or with
  ``--fig2-full`` the whole excerpt without its ``#`` header lines (their bare
  counts are not values, so check_paper_numbers.py would reject them); and
  ``fig2_caption.txt``, a ``«key»`` template for that listing. Each listing
  line is also a key (``fig2_listing_<nn>``), so the fill pass writes it as a
  tagged value; the run, exchange and the checked counts from the header are
  keys too.

Numbers that are counted once per extraction
--------------------------------------------
The leak gate's drops (``leak_gate_drops_<L>``, ``leak_gate_docs_emptied_<L>``
and their ``_total``) are read once per extraction: from the run that
extracted (``extraction_source`` "extracted"), else from one run that reused
it, whose manifest carries the extraction file's own counters. The
observation table's ``op_leak_gate_drops`` sums every run's manifest, so each
reuse run re-reports its source's drops; it is kept as a key but no table
quotes it.

Fill mode
---------
``--fill SRC.docx DST.docx`` reads numbers.json and tables.docx from ``--out``
and writes DST. It replaces each ``«key»`` in every Word XML part python-docx
parses (body, tables, headers, footers), including a placeholder Word has split
across several runs: the value becomes a run of its own, with the formatting of
the run that held the opening guillemet, between a bookmark named
``pv_<tag>_<n>`` (``check_paper_numbers.value_tag(key)``) and its end. That tag
is what check_paper_numbers.py binds each numeral to. It refuses, and writes
nothing, if any placeholder has no value, a guillemet is unmatched, a Word part
it cannot edit (footnotes, endnotes, comments) holds a guillemet, or a value is
``n/a`` in a paragraph outside a table (unless ``--allow-na``). A paragraph
that begins ``[TABLE n PLACEHOLDER]`` gets the table in front of it, when that
table exists; the marker and the skeleton's own description after it are then
removed, and any other text the author put in that paragraph stays. Since
2026-10-21 the manuscript's tables are Table 1 (the extraction and r1's store per
corpus, ``table_extraction``) and Table 2 (the hypotheses, outcome cells shaded);
``[FIGURE 3 PLACEHOLDER]`` to ``[FIGURE 6 PLACEHOLDER]`` get the result figures
the build draws from its own values (``DATA_FIGURES``: the monitor's refusals,
what crosses, the binding figure, judged quality and track L), each with its
caption file; the old tables 1 and 2 are written to ``tables_artifact.docx``.
``[FIGURE 1 PLACEHOLDER]`` gets ``paper/figures/fig_example.png`` (the TikZ
example figure, rendered by ``paper/figures/build_figs.sh``), FIG1_WIDTH_IN
(6.5 in, the text width) wide and centred, and its caption
``paper/figures/fig_example_caption.txt``, neither of them a build input; while
either file is missing the marker is left in place.
The filled document is marked "Do not compress images in file"
(``w:doNotAutoCompressPictures``), so that Word does not compress Fig. 1 to its
default resolution; the exported PDF's figure resolution is checked at PAP9
(``pdfimages -list``).
``[FIGURE 2 PLACEHOLDER]`` gets ``fig2_listing.txt`` as a monospaced block, one
paragraph per line (the short listing under a hanging indent the width of its
label column), each line a tagged value, and its caption; the fill refuses
when a listing line is not the current value of its key (a listing from
another build).
No other text is touched, so the author's edits in SRC survive every refill,
except that a source in the paper's format without the running head or page
number gets them (``paper_format.paginate``; an existing header or footer is
kept). ``--banner TEXT`` also writes TEXT into every page header (the pilot demo
uses it).

Formats (one per kind of quantity, so the numeral checker can match them)
-------------------------------------------------------------------------
rates and accuracies 2 dp; a per-cell summary is ``mean [min–max]`` over
runs (just the value when n=1, ``n/a`` when n=0; since the evaluation rewrite of
2026-10-15 without the sd, which only judge_position_bias keeps, as
``mean ± SD [min–max]``), followed by ``(k of N runs)``
when fewer runs have a value than the cell has runs; a bare mean has a
companion key ``<key>_n`` = ``k/N``; judge scores 2 dp; FP rates and interval
ends 3 dp; shares quoted as percentages 1 dp with ``%``; counts as integers;
run-level and attempt-level counts as ``k/N``; USD 2 dp.
"""

from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "backend" / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.check_paper_numbers import presented, value_tag  # noqa: E402

__all__ = ["ARM_ORDER", "BANNER_PILOT", "FillError", "MissingKeys", "Numbers",
           "build", "fill", "fmt_ci", "fmt_fixed", "fmt_kn", "fmt_pct", "fmt_stat",
           "load_real_l_cost", "main", "numbers_from_crossings", "numbers_from_evaluation",
           "numbers_from_presidio", "numbers_from_probes", "numbers_from_real_l",
           "numbers_from_real_l_cost", "numbers_from_review", "check_review_inputs",
           "numbers_from_posthoc", "placeholder_keys", "wire_excerpt"]

DEFAULT_OUT = _REPO / "eval" / "paper"
DEFAULT_SKELETON = _REPO / "paper" / "PrivDeep_ICCIT2026.docx"
PLACEHOLDER_RE = re.compile(r"«([A-Za-z0-9_]+)»")
ARM_ORDER = ("baseline", "r5", "r1")
BANNER_PILOT = "PILOT DATA — NOT CITABLE"
FIG_DPI = 600          # paper/VENUE_FACTS.md: "600 dpi or more"
NA = "n/a"

# The paragraph that marks where a block goes, and the bookmark that names the
# block in tables.docx.
# The writing fallback folded the former Tables 3 and 4 into Table 3 (see table3),
# leaving three numbered tables until Table 4 below; there is no calibration table since
# the author's approval of 2026-10-01 (PRIVDEEP_COMPLETION_PLAN.md Part D AD32):
# §5 states the calibration figures in one sentence (CAL_ROWS). It has two
# figures since the author removed Fig. 3, the strip plot, on 2026-10-02 (Part D
# AD33): make_fig3 still draws it for the artifact, and no marker takes it.
# Fig. 1 is drawn from the code, not from data: since 2026-10-15 the TikZ concept
# figure (paper/figures/fig_concept.tex, built by paper/figures/build_figs.sh);
# the fill takes it and its caption from FIG1_DIR.
# Table 4, the hypotheses table (table_hypotheses), was added on 2026-10-15 from the
# simulated review's change set (paper/reviews/fix_proposals_2026-10-10.json,
# TAB-IV); §6.3 carries its marker after its first paragraph. No earlier table is
# renumbered.
# Since 2026-10-19 (the author's request: Table 1 shown as a figure of the
# mechanism, tables easier to read) the numbering is: Table 1 the monitor's
# refusals (formerly Table 2), Table 2 what crosses (formerly Table 3), Table 3 the
# hypotheses (formerly Table 4); Fig. 1 the architecture, Fig. 2 the mechanism
# figure that replaces the properties table (paper/figures/fig_mechanism.tex,
# drawn by hand from THREAT_MODEL.md section 4; table1_from_threat_model still
# builds the table for the artifact), Fig. 3 the wire listing (formerly Fig. 2),
# Fig. 4 the per-corpus binding figure (formerly Fig. 3). The block ids follow the
# printed numbers; the listing's files keep their fig2_* names.
# Later on 2026-10-19 (the author's request: "Figure nhìn không rõ, hãy mô tả bằng
# ví dụ", with the author's own example figure, and short, title-like captions)
# the architecture and the mechanism figures are one: Fig. 1, the pipeline on an
# illustrative example with each property placed and graded
# (paper/figures/fig_example.tex). The wire listing is Fig. 2 and the binding
# figure Fig. 3; fig_concept.tex and fig_mechanism.tex stay for the artifact.
# Since 2026-10-21 (the author's request: "thay đổi hoàn toàn cách trình bày, nhất
# là phần Evaluation cho hấp dẫn hơn thay vì bắt người dùng tự phân tích các bảng khô
# khan"): Table 1 is the extraction and r1's store per corpus (in §5, formerly
# Table 2(b) without its echo column), Table 2 the hypotheses (formerly Table 3,
# now opening §6, its outcomes shaded); Fig. 3 the monitor's refusals (formerly
# Table 1), Fig. 4 what crosses (formerly Table 2(a) and the echo column), Fig. 5
# the binding figure (formerly Fig. 3). table2 and table3 still build the old
# tables for the artifact.
# Later on 2026-10-21 (the author's request: "quá nhiều tham số, quá nhiều thông tin
# trong phần Evaluation và Result ... thay đổi 1 cách đơn giản và ngắn gọn"; the
# author chose three questions, secondary results to the artifact and three plain
# figures): one table, the hypotheses (Table 1), and three figures, the example
# (Fig. 1), the listing (Fig. 2) and one results figure (Fig. 3, make_fig_results).
# The monitor, crossings, binding, quality and extraction figures and tables of
# earlier the same day are built for the artifact only.
BLOCKS = {
    "t1": "[TABLE 1 PLACEHOLDER]",
    "fig1": "[FIGURE 1 PLACEHOLDER]",
    "fig2": "[FIGURE 2 PLACEHOLDER]",
    "fig3": "[FIGURE 3 PLACEHOLDER]",
}
# The skeleton's own description after each marker (paper/PrivDeep_ICCIT2026.docx).
# The fill removes the marker and this text; anything else in the paragraph is
# the author's and stays. If the author edited the description itself, only the
# marker is removed, and the fill says so.
BLOCK_DESCRIPTIONS = {
    "t1": "Hypotheses: registered rule and outcome.",
    "fig1": "Cloze on an illustrative example: the steps, what crosses, and where each "
            "enforced property acts, with its grade.",
    "fig2": "Wire excerpt from a frozen r1 trace: ATTRIBUTES line, a cloud sentence with "
            "FACT references, local resolution (a 6-line listing under the writing "
            "fallback).",
    "fig3": "What crosses, how values are bound and what it costs.",
}
# Fig. 1 and its caption: since 2026-10-15 the TikZ concept figure (T, M and C,
# what crosses each way, what never leaves T), which paper/figures/build_figs.sh
# renders at 600 dpi, and its caption file, written by hand from the change set's
# FIG-1 caption. The fill gives it the template's full text width (the figure
# spans both columns, paper_format.span), its height following from the PNG's own
# aspect. paper/figures/fig1_architecture.py, the matplotlib drawing that was
# Fig. 1 until then (6.0 in wide, plan Part D AD32), stays in the repository for
# the artifact; the fill no longer reads it.
# Since 2026-10-19, Fig. 1 is the example figure (paper/figures/fig_example.tex),
# which replaced the concept and mechanism figures at the author's request.
FIG1_DIR = _REPO / "paper" / "figures"
FIG1_PNG = "fig_example.png"
FIG1_CAPTION = "fig_example_caption.txt"
FIG1_WIDTH_IN = 6.5     # scripts/paper_format.py TEXT_WIDTH_IN (a test pins the two)
# Space above Fig. 1, whose grey T band starts at the picture's top edge: at the ICCIT
# margins §1's text runs on above it on page 2, and with none the band touched that
# text's descenders (verification of 2026-10-25). Fig. 3's PNG has its own white margin.
FIG1_SPACE_BEFORE_PT = 6


# ------------------------------------------------------------------ formats

def fmt_fixed(x: float, dp: int) -> str:
    s = f"{x:.{dp}f}"
    return s[1:] if s.startswith("-") and float(s) == 0 else s


def fmt_stat(stat: dict[str, Any] | None, dp: int = 2) -> str:
    """``mean [min–max]`` over runs; the bare value for one run; n/a for none.
    The one formatter for every per-cell summary (the t4_* cells, the review
    analyses' per-run rates): since the evaluation rewrite of 2026-10-15 the SD
    is not shown, with n = 3 the range says more; fmt_stat_sd keeps it for the
    one key §6 quotes as mean ± SD."""
    if not stat or not stat.get("n") or stat.get("mean") is None:
        return NA
    if stat["n"] == 1 or stat.get("stdev") is None:
        return fmt_fixed(stat["mean"], dp)
    return (f"{fmt_fixed(stat['mean'], dp)} "
            f"[{fmt_fixed(stat['min'], dp)}–{fmt_fixed(stat['max'], dp)}]")


def fmt_stat_sd(stat: dict[str, Any] | None, dp: int = 2) -> str:
    """``mean ± SD [min–max]`` over runs; the bare value for one run; n/a for
    none. Only judge_position_bias, which §6 quotes as mean ± SD."""
    if not stat or not stat.get("n") or stat.get("mean") is None:
        return NA
    if stat["n"] == 1 or stat.get("stdev") is None:
        return fmt_fixed(stat["mean"], dp)
    return (f"{fmt_fixed(stat['mean'], dp)} ± {fmt_fixed(stat['stdev'], dp)} "
            f"[{fmt_fixed(stat['min'], dp)}–{fmt_fixed(stat['max'], dp)}]")


def fmt_pct(share: float | None, dp: int = 1) -> str:
    return NA if share is None else f"{fmt_fixed(100 * share, dp)}%"


def fmt_kn(k: int | None, n: int | None) -> str:
    return NA if k is None or n is None else f"{int(k)}/{int(n)}"


def fmt_ci(ci: list[float] | None, dp: int = 3) -> str:
    return NA if not ci else f"[{fmt_fixed(ci[0], dp)}, {fmt_fixed(ci[1], dp)}]"


def fmt_num(x: float | None, dp: int = 2) -> str:
    return NA if x is None else fmt_fixed(x, dp)


def fmt_p(p: float) -> str:
    """A p-value to two significant digits, in fixed point, at least two decimals
    and no trailing zero beyond them: 1/20 -> '0.05', 1/70 -> '0.014'."""
    import math  # noqa: PLC0415
    if not 0 < p <= 1:
        raise ValueError(f"not a p-value: {p!r}")
    dp = max(2, 1 - math.floor(math.log10(p)))
    s = fmt_fixed(p, dp)
    while s.endswith("0") and len(s.split(".")[1]) > 2:
        s = s[:-1]
    return s


def every_run_exact_p(n: int) -> float:
    """1/C(2n, n): with n runs on each side and every ordering of the 2n values
    equally likely, the probability that every run of one side exceeds every run
    of the other, so the smallest one-sided p an every-run rule over n and n runs
    can reach (an exact rank test; plan scope §8.7's 'every run' comparisons)."""
    import math  # noqa: PLC0415
    if n < 1:
        raise ValueError(f"repeats must be positive: {n!r}")
    return 1 / math.comb(2 * n, n)


def fmt_range(values: list[str]) -> str:
    """One value when every formatted value agrees, else ``lo–hi`` in order of
    magnitude; used where one sentence covers several corpora. n/a when any
    value is n/a: a range that silently left one out would cover less than it
    says."""
    vals = list(values)
    if not vals or NA in vals:
        return NA
    uniq = sorted(set(vals), key=lambda v: float(v.rstrip("%")))
    return uniq[0] if len(uniq) == 1 else f"{uniq[0]}–{uniq[-1]}"


# ------------------------------------------------------------ numbers store

class MissingKeys(SystemExit):
    pass


@dataclass
class Numbers:
    """numbers.json and its sidecar: every value is put with where it came from."""

    values: dict[str, str] = field(default_factory=dict)
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    # outcome key -> the comparisons pooled over fewer runs than registered
    caveats: dict[str, list[str]] = field(default_factory=dict)
    # bare-mean key -> (runs with a value, runs in the cell)
    thin: dict[str, tuple[int, int]] = field(default_factory=dict)

    def put(self, key: str, value: str, source: str, raw: Any = None,
            fmt: str = "") -> str:
        if not re.fullmatch(r"[A-Za-z0-9_]+", key):
            raise ValueError(f"bad key {key!r}")
        if "«" in value or "»" in value:
            raise ValueError(f"{key}: a value may not hold a guillemet: {value!r}")
        if key in self.values and self.values[key] != value:
            raise ValueError(f"key {key} produced twice with different values: "
                             f"{self.values[key]!r} vs {value!r}")
        self.values[key] = value
        self.sources[key] = {"source": source, "raw": raw, "format": fmt}
        return value

    def __getitem__(self, key: str) -> str:
        return self.values[key]


def _ptr(obj: Any, pointer: str) -> Any:
    """JSON-pointer lookup ('/a/b/0'); None when any step is missing."""
    cur = obj
    for part in [p.replace("~1", "/").replace("~0", "~") for p in pointer.split("/")[1:]]:
        if isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def _esc(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")


def _p(*parts: Any) -> str:
    return "/" + "/".join(_esc(str(p)) for p in parts)


@dataclass
class Src:
    """One input file: its label in the sidecar and its parsed JSON."""

    label: str
    data: Any

    def get(self, *parts: Any) -> tuple[Any, str]:
        ptr = _p(*parts)
        return _ptr(self.data, ptr), f"{self.label}#{ptr}"


# ------------------------------------------------------------ build: numbers

def _corpora(ev: Src) -> dict[str, str]:
    """Letter -> task id, from the aggregate's own hypotheses block."""
    letters, _ = ev.get("hypotheses", "corpora")
    return {k: v for k, v in (letters or {}).items() if v}


def stale_key_runs(ev: Src) -> dict[str, list[str]]:
    """Runs scored against a key other than their corpus's current one, per task
    and side. The private side is the aggregate's own ``stale_key_runs``; the
    aggregate lists no oracle side, so it is read from ``per_task``: a row whose
    oracle faithfulness exists and whose ``key_sha256`` is not the task's."""
    out: dict[str, list[str]] = {}
    rows = ev.data.get("per_task") or []
    for tid, bt in (ev.data.get("by_task") or {}).items():
        bt = bt or {}
        if bt.get("stale_key_runs"):
            out[f"{tid} (private)"] = sorted(bt["stale_key_runs"])
        sha = bt.get("key_sha256")
        orc = sorted(m.get("run") for m in rows if m.get("task_id") == tid
                     and isinstance((m.get("faithfulness") or {}).get("oracle"), dict)
                     and m["faithfulness"].get("key_sha256") != sha)
        if orc:
            out[f"{tid} (oracle)"] = orc
    return out


def _facts_structural(stat: dict[str, Any] | None, src: str, fmt: str, runs: list[str],
                      runs_dir: Path) -> tuple[dict[str, Any] | None, str, str]:
    """A cell's facts_structural, with a measured zero read as zero.

    The fact store counts structural facts in a Counter, which writes no
    ``facts_structural`` key when it counts none (tier1_local/fact_store.py:215),
    and the pipeline copies the counters into the manifest as they are, beside
    ``facts_total`` (pipeline.py:236). The aggregate reads the absent key as
    None (scripts/run_evaluation.py, _pipeline_values), so an r1 run whose fact
    store ran and held no structural fact drops out of the cell as if nothing
    were recorded. Here each run's manifest under `runs_dir` is read: the
    counter where it is recorded; 0 where the manifest records ``facts_total``
    and no counter (the store ran); nothing where it records neither (no fact
    store: baseline and r5, pipeline.py:207). run_evaluation.py itself is left
    as it was at the tag paper-freeze (review 2026-10-09, T3-facts-structural-na).

    The aggregate's own values are kept unless a zero is added, and only when
    the manifests' recorded counters are exactly the aggregate's values: a
    manifest that disagrees, or a run with no manifest, stops the build or
    leaves the aggregate's figure, never a mix."""
    agg = sorted((stat or {}).get("values") or [])
    values: dict[str, int | None] = {}
    zeros: list[str] = []
    for run in runs:
        path = runs_dir / run / "manifest.json"
        if not path.exists():
            print(f"warning: no manifest for {run} under {runs_dir}; its cell's "
                  "facts_structural is the aggregate's", file=sys.stderr)
            return stat, src, fmt
        facts = json.loads(path.read_text(encoding="utf-8")).get("facts") or {}
        if "facts_structural" in facts:
            values[run] = facts["facts_structural"]
        elif "facts_total" in facts:
            values[run] = 0
            zeros.append(run)
        else:
            values[run] = None
    recorded = sorted(v for r, v in values.items() if v is not None and r not in zeros)
    if recorded != agg:
        raise SystemExit(f"{src}: the aggregate's facts_structural values {agg} are not the "
                         f"counters the manifests under {runs_dir} record ({recorded}); "
                         "build from the run directories the aggregate read")
    if not zeros:
        return stat, src, fmt
    from scripts.run_evaluation import spread
    rel = (runs_dir.relative_to(_REPO).as_posix() if runs_dir.is_relative_to(_REPO)
           else str(runs_dir))
    return (spread([v for v in (values[r] for r in runs) if v is not None]),
            f"{rel}/<run>/manifest.json#/facts/facts_structural for {', '.join(runs)}; 0 for "
            f"{', '.join(zeros)}, whose manifest records facts_total and no facts_structural "
            f"counter (the aggregate, {src}, reads the absent counter as no value)",
            fmt + "; a run whose fact store ran and wrote no facts_structural counter "
                  "counts 0 (backend/src/privdeep/pipeline.py:236, "
                  "tier1_local/fact_store.py:215)")


def numbers_from_evaluation(nb: Numbers, ev: Src, runs_dir: Path | None = None) -> None:
    """The aggregate's figures. With `runs_dir` (the run directories the
    aggregate read, eval/runs by default in build), each facts_structural cell
    also reads the runs' manifests, so that a measured zero is not n/a
    (_facts_structural)."""
    if not isinstance(ev.data.get("hypotheses"), dict):
        raise SystemExit(f"{ev.label}: no 'hypotheses' block; run the INS2b aggregate "
                         "(scripts/run_evaluation.py aggregate) first")
    stale = stale_key_runs(ev)
    if stale:
        raise SystemExit(
            f"{ev.label}: runs scored against a key other than their corpus's current one: "
            + "; ".join(f"{t}: {', '.join(rs)}" for t, rs in stale.items())
            + ". The aggregate still averages them into by_task[*].arms and .oracle, which "
            "the abstract and Table 3 read; rescore them against the current key "
            "(run_evaluation.py measure) and re-aggregate before building the paper.")
    corpora = _corpora(ev)
    n_private = 0
    for arm in ARM_ORDER:
        runs, s = ev.get("arms", arm, "runs")
        runs = runs or []
        n_private += len(runs)
        nb.put(f"n_runs_{arm}", str(len(runs)), s, len(runs), "count")
    nb.put("n_private_runs", str(n_private), f"{ev.label}#/arms/*/runs", n_private,
           "count: pooled runs over the three arms")
    rr, s = ev.get("hypotheses", "registered_repeats")
    nb.put("n_registered_repeats", NA if rr is None else str(rr), s, rr, "count")
    p = every_run_exact_p(rr) if isinstance(rr, int) and not isinstance(rr, bool) else None
    nb.put("every_run_exact_p", NA if p is None else fmt_p(p), s, p,
           "1/C(2n, n) with n the registered repeats: under exchangeability, the chance "
           "that every one of n runs exceeds every one of n others, the smallest one-sided "
           "p an every-run comparison of n runs with n can reach (exact rank test); two "
           "significant digits")
    measured = measured_letters(ev)
    nb.put("n_corpora_measured", str(len(measured)), f"{ev.label}#/by_task/*/arms",
           measured, "count")
    commit, s = ev.get("git_commit")
    nb.put("aggregate_commit", str(commit)[:12] if commit else NA, s, commit, "sha[:12]")
    from scripts.run_evaluation import MIN_RBA_POOL
    nb.put("min_rba_pool", str(MIN_RBA_POOL), "scripts/run_evaluation.py:MIN_RBA_POOL",
           MIN_RBA_POOL, "count")
    numbers_from_truncation(nb, ev)
    numbers_from_leak_gate(nb, ev)

    metrics = {"rba": "rba", "attr": "attribute_accuracy",
               "covcorrect": "coverage_correct", "covstated": "coverage_stated"}
    for L, tid in corpora.items():
        bt, _ = ev.get("by_task", tid)
        if not bt:
            continue
        cells, s = ev.get("by_task", tid, "table_data_cells")
        nb.put(f"table_cells_{L}", NA if cells is None else str(cells), s, cells, "count")
        for arm in ARM_ORDER:
            info, _ = ev.get("by_task", tid, "arms", arm)
            if not info:
                continue
            n_runs = len(info["runs"])
            _, s = ev.get("by_task", tid, "arms", arm, "runs")
            nb.put(f"t4_{L}_{arm}_runs", str(n_runs), s, n_runs, "count")
            for short, m in metrics.items():
                stat, s = ev.get("by_task", tid, "arms", arm, "faithfulness", m)
                _put_mean(nb, f"{short}_{arm}_{L}", stat, n_runs, s)
                nb.put(f"t4_{L}_{arm}_{short}", _fmt_cell(stat, n_runs), s, stat,
                       "mean [min–max], 2 dp; (k of N runs) when k < N")
            for pk, short in (("sentences_pruned", "pruned"),
                              ("facts_structural", "factsstruct"),
                              ("not_recorded", "notrecorded")):
                stat, s = ev.get("by_task", tid, "arms", arm, "pipeline", pk)
                fmt = "mean [min–max], 1 dp; (k of N runs) when k < N"
                if pk == "facts_structural" and runs_dir is not None:
                    stat, s, fmt = _facts_structural(stat, s, fmt, info["runs"], runs_dir)
                nb.put(f"t4_{L}_{arm}_{short}", _fmt_cell(stat, n_runs, 1), s, stat, fmt)
        orc, s = ev.get("by_task", tid, "oracle")
        if orc and orc.get("faithfulness"):
            n_runs = orc["runs"]
            nb.put(f"t4_{L}_oracle_runs", str(n_runs), s + "/runs", n_runs, "count")
            for short, m in metrics.items():
                stat, s2 = ev.get("by_task", tid, "oracle", "faithfulness", m)
                nb.put(f"t4_{L}_oracle_{short}", _fmt_cell(stat, n_runs), s2, stat,
                       "mean [min–max], 2 dp; (k of N runs) when k < N")
                for end in ("min", "max"):
                    v = (stat or {}).get(end)
                    nb.put(f"{short}_oracle_{L}_{end}", fmt_num(v), f"{s2}/{end}", v, "2 dp")
                _put_mean(nb, f"{short}_oracle_{L}", stat, n_runs, s2)
        alt, s = ev.get("alt_key")
        if alt:
            d = (alt.get("by_task") or {}).get(tid)
            if d:
                n_runs = len(((bt.get("arms") or {}).get("r1") or {}).get("runs") or [])
                for short, m in (("rba", "rba"), ("attr", "attribute_accuracy")):
                    stat = d.get(m)
                    ptr = f"{s}/by_task/{_esc(tid)}/{m}"
                    nb.put(f"t4_{L}_r1prefix_{short}", _fmt_cell(stat, n_runs), ptr, stat,
                           "mean [min–max], 2 dp; the same r1 runs rescored under "
                           "the pre-fix RBA attribute lexicon")
                    _put_mean(nb, f"{short}_r1prefix_{L}", stat, n_runs, ptr)
    # Judge: pooled per criterion, per arm without groundedness, position bias.
    for crit in ("goal_coverage", "coherence", "groundedness", "specificity"):
        for side in ("private", "oracle"):
            st, s = ev.get("utility", "by_criterion", crit, side)
            v = (st or {}).get("mean")
            nb.put(f"judge_{crit}_{side}", fmt_num(v), s + "/mean", v, "mean, 2 dp")
    for arm in ARM_ORDER:
        st, s = ev.get("arms", arm, "judge", "mean_excluding_groundedness", "private")
        v = (st or {}).get("mean")
        nb.put(f"judge_mean_exgr_{arm}", fmt_num(v), s + "/mean", v, "mean, 2 dp")
    st, s = ev.get("utility", "mean_excluding_groundedness", "oracle")
    v = (st or {}).get("mean")
    nb.put("judge_mean_exgr_oracle", fmt_num(v), s + "/mean", v,
           "mean, 2 dp; every oracle judgement pooled, beside every arm (the like-for-like "
           "comparison with judge_mean_exgr_r1 is judge_mean_exgr_oracle_r1pairs)")
    st, s = ev.get("arms", "r1", "judge", "mean_excluding_groundedness", "oracle")
    v = (st or {}).get("mean")
    nb.put("judge_mean_exgr_oracle_r1pairs", fmt_num(v), s + "/mean", v,
           "mean, 2 dp; the oracle side of r1's own judgements")
    st, s = ev.get("utility", "position_bias")
    nb.put("judge_position_bias", fmt_stat_sd(st), s, st,
           "mean ± SD [min–max], 2 dp (the one key that keeps the SD: §6 quotes it so)")
    v = (st or {}).get("mean")
    nb.put("judge_position_bias_mean", fmt_num(v), s + "/mean", v, "mean, 2 dp")
    st, s = ev.get("utility", "judgements")
    nb.put("judge_judgements", NA if st is None else str(st), s, st, "count")
    numbers_from_judge_repeats(nb, ev)
    numbers_from_crossings(nb, ev)
    _numbers_from_hypotheses(nb, ev)
    numbers_ranges(nb, list(corpora))


# The keys of the evaluation rewrite of 2026-10-15, for §6's lead: one range
# over corpora, or over the private arms, where the prose had quoted every
# value. Each is "lo–hi" of the bare means already in numbers.json, over the
# corpora (or arms) that have a value, 2 dp, formatted as those keys are;
# "lo" alone when every value agrees; n/a when none has a value. The corpora
# left out for want of a value (r1 on C) are in the sidecar's raw.
RANGE_KEYS = (("attr_baseline_range", "attr_baseline_{L}"),
              ("attr_r5_range", "attr_r5_{L}"),
              ("attr_r1_range", "attr_r1_{L}"),
              ("attr_oracle_range", "attr_oracle_{L}"),
              ("covstated_baseline_range", "covstated_baseline_{L}"),
              ("covstated_r1_range", "covstated_r1_{L}"))


def _range_of(nb: Numbers, key: str, parts: list[str], what: str) -> None:
    present = [k for k in parts if nb.values.get(k, NA) != NA]
    vals = [nb.values[k] for k in present]
    uniq = sorted(set(vals), key=float)
    value = NA if not uniq else uniq[0] if len(uniq) == 1 else f"{uniq[0]}–{uniq[-1]}"
    src = "numbers.json " + ", ".join(present or parts) + " (" + "; ".join(
        nb.sources[k]["source"] for k in (present or parts) if k in nb.sources) + ")"
    nb.put(key, value, src, {"over": present, "without_value": [k for k in parts
                                                                if k not in present]},
           f"lo–hi of the bare means over the {what} with a value, 2 dp; lo alone when "
           "they agree; n/a when none has a value")


def numbers_ranges(nb: Numbers, letters: list[str]) -> None:
    """attr_<arm>_range and covstated_<arm>_range over the corpora, and
    judge_private_range over the private arms' judge means."""
    for key, tpl in RANGE_KEYS:
        _range_of(nb, key, [tpl.format(L=L) for L in letters], "corpora")
    _range_of(nb, "judge_private_range", [f"judge_mean_exgr_{a}" for a in ARM_ORDER],
              "private arms")


def numbers_from_judge_repeats(nb: Numbers, ev: Src) -> None:
    """``judge_repeats``: the judgements each pooled private run's measurement
    holds (``per_task[*].judgements``, one judge call per repeat, each scoring
    both reports in both orders; run_evaluation.py measure --judge-repeats). One
    count when every pooled run has the same, else lo–hi with a warning; n/a when
    no pooled run records judgements. A sum that is not the aggregate's
    ``utility.judgements`` is warned about, not refused: the aggregate counts
    what it pooled."""
    pooled = {r for a in ARM_ORDER for r in (_ptr(ev.data, _p("arms", a, "runs")) or [])}
    counts: dict[str, int] = {}
    for m in ev.data.get("per_task") or []:
        if m.get("run") in pooled and isinstance(m.get("judgements"), list):
            counts[m["run"]] = len(m["judgements"])
    src = f"{ev.label}#/per_task/*/judgements (pooled private runs)"
    vals = sorted(set(counts.values()))
    if not vals:
        nb.put("judge_repeats", NA, src, None, "n/a: no pooled run records judgements")
        return
    if len(vals) > 1:
        print(f"warning: the pooled runs hold {vals[0]}-{vals[-1]} judgements each; "
              "judge_repeats is a range", file=sys.stderr)
    total = (ev.data.get("utility") or {}).get("judgements")
    if isinstance(total, int) and total != sum(counts.values()):
        print(f"warning: the pooled runs hold {sum(counts.values())} judgements, the "
              f"aggregate's utility.judgements {total}", file=sys.stderr)
    nb.put("judge_repeats", _fmt_lohi(vals), src, dict(sorted(counts.items())),
           "count of judgements per pooled private run's measurement (lo–hi when runs "
           "differ)")


def numbers_from_truncation(nb: Numbers, ev: Src) -> None:
    """The tasks whose oracle read a capped prefix (the aggregate's
    ``truncated_tasks.ids``), as corpus letters."""
    trunc, s = ev.get("truncated_tasks", "ids")
    if not isinstance(trunc, list):
        # An aggregate without the block (or with a malformed one) does not
        # say the cap truncated nothing; it says nothing.
        print(f"warning: {ev.label} has no truncated_tasks.ids list; "
              "oracle_truncated_tasks and oracle_truncated_count are n/a", file=sys.stderr)
        for key in ("oracle_truncated_tasks", "oracle_truncated_count"):
            nb.put(key, NA, s + " (absent)", trunc,
                   "n/a: the aggregate records no truncated_tasks.ids list")
        return
    letter_of = {t: L for L, t in _corpora(ev).items()}
    ids = list(trunc)
    nb.put("oracle_truncated_tasks",
           ", ".join(letter_of.get(t, t) for t in ids) or "none", s, ids,
           "corpus letters (task id where unmapped) whose oracle read a prefix capped at "
           "max_doc_chars; 'none' when the aggregate's list is empty")
    nb.put("oracle_truncated_count", str(len(ids)), s, len(ids), "count of tasks")


def _extraction_of(m: dict[str, Any]) -> str | None:
    """The run whose extraction a measured run masked: itself when it extracted,
    else the run directory the reused extractions.json sits in; None when the
    measurement does not say."""
    src = m.get("extraction_source")
    if src == "extracted":
        return m.get("run")
    if isinstance(src, str) and src.endswith("extractions.json"):
        return Path(src).parent.name or None
    return None


def _root_extraction(run: str | None, es_of) -> str | None:
    """The run that extracted what `run` masked. A reused extraction names the
    run directory it was copied from, and every run writes its own
    extractions.json, so a run may reuse a run that itself reused: the chain is
    followed through each named run's own extraction_source to the run that
    recorded 'extracted'. None when `run`'s own source is not recorded; a
    named run whose source is not recorded (or a cycle) ends the chain there."""
    ext = _extraction_of({"run": run, "extraction_source": es_of(run)})
    seen = {run}
    while ext is not None and ext not in seen:
        seen.add(ext)
        nxt = _extraction_of({"run": ext, "extraction_source": es_of(ext)})
        if nxt is None or nxt == ext:
            break
        ext = nxt
    return ext


def numbers_from_leak_gate(nb: Numbers, ev: Src) -> None:
    """The relations the leak gate dropped and the documents it left with no
    relation, per corpus, read once per extraction.

    Every run that reuses an extraction carries that extraction's counters in
    its own manifest, so summing over runs (as ``op_leak_gate_drops`` does)
    counts one extraction's drops once per arm and repeat. Here the armed runs
    of a task are grouped by the extraction they masked (a reuse of a reuse is
    followed to the run that extracted), and each group is read once: from the
    run that extracted when it was measured, else from one run that reused it
    (whose manifest holds the extraction file's own counters as loaded; a file
    written before the counter existed loads it as 0, which is true of it,
    backend/src/privdeep/tier1_local/extraction_io.py).
    A corpus is n/a when a run's extraction cannot be named or no run of an
    extraction records the counters (None: every manifest predates them); the
    totals are n/a unless every measured corpus has a value."""
    corpora = _corpora(ev)
    outcomes, so = ev.get("health_gate", "outcomes")
    outcomes = outcomes or {}
    rows = [m for m in ev.data.get("per_task") or [] if m.get("arm") in ARM_ORDER]
    measured = measured_letters(ev)
    row_es = {m.get("run"): m.get("extraction_source") for m in rows}

    def es_of(run: str | None) -> Any:
        es = row_es.get(run)
        if es in (None, "unrecorded"):
            es = (outcomes.get(run) or {}).get("extraction_source")
        return es

    totals: dict[str, list[int | None]] = {"drops": [], "emptied": []}
    for L, tid in corpora.items():
        mine = [m for m in rows if m.get("task_id") == tid]
        if not mine:
            continue
        groups: dict[str, list[dict[str, Any]]] = {}
        unnamed = []
        for m in mine:
            ext = _root_extraction(m.get("run"), es_of)
            if ext is None:
                unnamed.append(m.get("run"))
            else:
                groups.setdefault(ext, []).append(m)
        read: dict[str, tuple[str, Any, Any]] = {}
        for ext, ms in sorted(groups.items()):
            names = [m["run"] for m in ms]

            def counters(r: str) -> tuple[Any, Any]:
                o = outcomes.get(r) or {}
                return o.get("relations_dropped_leak"), o.get("documents_all_relations_dropped")

            # The extracting run first; a manifest written before the counters
            # existed gives None, and then a reuse run's manifest, which holds
            # the file's own counters as loaded, is read instead.
            order = ([ext] if ext in names else []) + sorted(r for r in names if r != ext)
            by = next((r for r in order if r in outcomes and None not in counters(r)),
                      next((r for r in order if r in outcomes), None))
            d, e = counters(by) if by else (None, None)
            read[ext] = (by or "none", d, e)
            seen = {counters(r) for r in names if None not in counters(r)}
            if len(seen) > 1:
                print(f"warning: the runs masking extraction {ext} disagree on its leak-gate "
                      f"counters ({sorted(seen)}); read from {by}", file=sys.stderr)
        vals = list(read.values())
        ok = bool(not unnamed and vals
                  and all(d is not None and e is not None for _, d, e in vals))
        drops = sum(d for _, d, _ in vals) if ok else None
        emptied = sum(e for _, _, e in vals) if ok else None
        via_reuse = sorted(ext for ext, (by, _, _) in read.items() if by not in (ext, "none"))
        src = (f"{so}/<run>/relations_dropped_leak and /documents_all_relations_dropped, "
               "read once per extraction from: "
               + "; ".join(f"{ext} via {by}" for ext, (by, _, _) in sorted(read.items()))
               + (f"; runs whose extraction is not recorded: {', '.join(unnamed)}"
                  if unnamed else "")
               + (f"; for {', '.join(via_reuse)} the counters are a reuse run's, i.e. the "
                  "extraction file's own as loaded, and a file written before "
                  "relations_dropped_leak existed loads it as 0, which is true of it "
                  "(backend/src/privdeep/tier1_local/extraction_io.py)" if via_reuse else ""))
        raw = {ext: {"read_from": by, "relations_dropped_leak": d,
                     "documents_all_relations_dropped": e}
               for ext, (by, d, e) in read.items()}
        nb.put(f"leak_gate_drops_{L}", NA if drops is None else str(drops), src, raw,
               "relations dropped, summed over the corpus's distinct extractions")
        nb.put(f"leak_gate_docs_emptied_{L}", NA if emptied is None else str(emptied), src,
               raw, "documents left with no relation, summed over distinct extractions")
        nb.put(f"leak_gate_extractions_{L}", str(len(read)), src, sorted(read),
               "count of distinct extractions read")
        if L in measured:
            totals["drops"].append(drops)
            totals["emptied"].append(emptied)
    for k, key in (("drops", "leak_gate_drops_total"),
                   ("emptied", "leak_gate_docs_emptied_total")):
        vs = totals[k]
        v = NA if not vs or any(x is None for x in vs) else str(sum(vs))
        nb.put(key, v, f"sum of leak_gate_{'drops' if k == 'drops' else 'docs_emptied'}"
               f"_<L> over the measured corpora {', '.join(measured) or 'none'}", vs,
               "count; n/a unless every measured corpus has a value")


def measured_letters(ev: Src) -> list[str]:
    """The corpus letters with at least one arm's runs in the aggregate."""
    return [L for L, t in _corpora(ev).items()
            if (_ptr(ev.data, _p("by_task", t, "arms")) or {})]


def _fmt_cell(stat: dict[str, Any] | None, n_runs: int, dp: int = 2) -> str:
    """fmt_stat, with ``(k of N runs)`` when fewer runs have a value than the cell
    has: a mean over two of three runs must not read like one over all three."""
    s = fmt_stat(stat, dp)
    k = (stat or {}).get("n") or 0
    if s != NA and k < n_runs:
        s += f" ({k} of {n_runs} runs)"
    return s


def _put_mean(nb: Numbers, key: str, stat: dict[str, Any] | None, n_runs: int,
              src: str) -> None:
    """A bare mean for running text, and its companion ``<key>_n`` = k/N."""
    mean = (stat or {}).get("mean")
    k = (stat or {}).get("n") or 0
    nb.put(key, fmt_num(mean), src + "/mean", mean, "mean, 2 dp; see <key>_n for k/N")
    nb.put(f"{key}_n", fmt_kn(k, n_runs), src + "/n", [k, n_runs],
           "runs with a value / runs in the cell")
    if mean is not None and k < n_runs:
        nb.thin[key] = (k, n_runs)


def _arm_of(ev: Src):
    """Run name -> arm: from the measured rows and the crossing hits, else from
    the run directory's name (``<task>__<arm>[__repN]``), else None."""
    known: dict[str, str] = {m["run"]: m.get("arm") for m in ev.data.get("per_task") or []
                             if m.get("run")}
    for blk in ((ev.data.get("crossings") or {}).get(k) or {}
                for k in ("a_generator_surfaces", "b_extracted_entities")):
        for h in (blk.get("hits") or []) + (blk.get("label_hits") or []):
            if h.get("run") and h.get("arm"):
                known.setdefault(h["run"], h["arm"])

    def arm(run: str) -> str | None:
        if run in known:
            return known[run]
        parts = run.split("__")
        return parts[1] if len(parts) > 1 and parts[1] in ARM_ORDER else None
    return arm


def numbers_from_crossings(nb: Numbers, ev: Src) -> None:
    """The three crossing measurements, each apart. A count is n/a for an arm
    the block has no entry for, and every per-arm count comes with how many of
    that arm's runs were scanned, so a 0 over unscanned runs cannot read as a
    clean result.

    Units differ and are stated: ``cross_a_hits`` and ``cross_a_label_hits``
    count hit records (one per run, exchange stage, field and surface), while
    ``cross_a_<arm>``, ``cross_a_label_<arm>`` and ``h3_hits`` sum occurrences
    over those records. Crossing (b) counts (run, entity) records throughout."""
    a, s = ev.get("crossings", "a_generator_surfaces")
    b, sb = ev.get("crossings", "b_extracted_entities")
    c, sc = ev.get("crossings", "c_reconstruction")
    a, b, c = a or {}, b or {}, c or {}
    arm_of = _arm_of(ev)
    nb.put("cross_a_hits", str(len(a.get("hits") or [])), s + "/hits",
           len(a.get("hits") or []), "count of hit records (run, stage, field, surface)")
    nb.put("cross_a_label_hits", str(len(a.get("label_hits") or [])), s + "/label_hits",
           len(a.get("label_hits") or []), "count of hit records (run, stage, field, surface)")
    nb.put("cross_a_occurrences", str(sum(h.get("count", 0) for h in a.get("hits") or [])),
           s + "/hits/*/count", None, "occurrences summed over the hit records")
    nb.put("cross_b_hits", str(len(b.get("hits") or [])), sb + "/hits",
           len(b.get("hits") or []), "count of (run, entity) records")
    nb.put("cross_c_hits", str(len(c.get("hits") or [])), sc + "/hits",
           len(c.get("hits") or []), "count")
    nb.put("cross_c_distinct", str(len(c.get("distinct_entities") or [])),
           sc + "/distinct_entities", len(c.get("distinct_entities") or []), "count")
    for label, blk, src in (("a", a, s), ("b", b, sb)):
        scanned = list(blk.get("runs_scanned") or [])
        unscanned = dict(blk.get("runs_not_scanned") or {})
        nb.put(f"cross_{label}_runs", str(len(scanned)), src + "/runs_scanned",
               len(scanned), "count of runs scanned")
        nb.put(f"cross_{label}_runs_not_scanned", str(len(unscanned)),
               src + "/runs_not_scanned", unscanned, "count of runs not scanned")
        nb.put(f"cross_{label}_not_scanned_reasons",
               "; ".join(f"{r}: {why}" for r, why in sorted(unscanned.items())) or "none",
               src + "/runs_not_scanned", unscanned, "run: reason; ...")
        by_arm = blk.get("by_arm") or {}
        for arm in ARM_ORDER:
            k = sum(1 for r in scanned if arm_of(r) == arm)
            if label == "a" and isinstance(by_arm.get(arm), dict) \
                    and by_arm[arm].get("runs") is not None:
                k = by_arm[arm]["runs"]
            n = k + sum(1 for r in unscanned if arm_of(r) == arm)
            nb.put(f"cross_{label}_scanned_{arm}",
                   fmt_kn(k, n) if arm in by_arm and n else NA,
                   f"{src}/by_arm/{arm}/runs" if label == "a" else f"{src}/runs_scanned",
                   [k, n], "runs scanned / runs of the arm (scanned and not)")
    for arm in ARM_ORDER:
        x = (a.get("by_arm") or {}).get(arm)
        nb.put(f"cross_a_{arm}", NA if x is None else str(x.get("hits", 0)),
               f"{s}/by_arm/{arm}/hits", None if x is None else x.get("hits"),
               "occurrences summed; n/a when the arm has no entry")
        nb.put(f"cross_a_label_{arm}", NA if x is None else str(x.get("label_hits", 0)),
               f"{s}/by_arm/{arm}/label_hits", None if x is None else x.get("label_hits"),
               "occurrences summed; n/a when the arm has no entry")
        y = (b.get("by_arm") or {}).get(arm)
        nb.put(f"cross_b_core_{arm}", NA if y is None else str(y.get("core_sent", 0)),
               f"{sb}/by_arm/{arm}/core_sent", None if y is None else y.get("core_sent"),
               "(run, entity) records; n/a when the arm has no entry")
        nb.put(f"cross_b_cloud_{arm}", NA if y is None else str(y.get("cloud_authored", 0)),
               f"{sb}/by_arm/{arm}/cloud_authored",
               None if y is None else y.get("cloud_authored"),
               "(run, entity) records; n/a when the arm has no entry")
        for kind, short in (("entity_recovery", "g3_entities"),
                            ("fivegram_recovery", "g3_5grams")):
            r, sr = ev.get("reconstruction", "by_arm", arm, kind)
            r = r or {}
            nb.put(f"{short}_{arm}", fmt_kn(r.get("recovered"), r.get("total")), sr,
                   r, "recovered/total")


def _side(comp: dict[str, Any], side: str, end: str) -> Any:
    return (comp.get(side) or {}).get(end)


def _comparison(nb: Numbers, prefix: str, cp: str, comp: dict[str, Any],
                lower: str, upper: str) -> tuple[str | None, list[str]]:
    """One pre-registered comparison: its outcome, the two deciding values named
    by which side they are (``<prefix>_<lower>_max``, ``<prefix>_<upper>_min``),
    each side's pooled run count, the reason, the sides short of the registered
    repeats and, for H2, the floor flag. Returns (reason, short)."""
    v = _side(comp, "lower", "max")
    nb.put(f"{prefix}_{lower}_max", fmt_num(v), cp + "/lower/max", v, "2 dp")
    v = _side(comp, "upper", "min")
    nb.put(f"{prefix}_{upper}_min", fmt_num(v), cp + "/upper/min", v, "2 dp")
    for side, name in (("lower", lower), ("upper", upper)):
        n = _side(comp, side, "runs")
        nb.put(f"{prefix}_{name}_runs", NA if n is None else str(n), f"{cp}/{side}/runs",
               n, "pooled runs")
    nb.put(f"{prefix}_outcome", comp["outcome"], cp + "/outcome", comp["outcome"], "text")
    reason = comp.get("reason")
    nb.put(f"{prefix}_reason", reason or "none", cp + "/reason", reason, "text")
    short = list(comp.get("short_of_registered_repeats") or [])
    nb.put(f"{prefix}_short_of_repeats", "; ".join(short) or "none",
           cp + "/short_of_registered_repeats", short, "text")
    nb.caveats[f"{prefix}_outcome"] = short
    if "floor" in comp:
        nb.put(f"{prefix}_floor", "yes" if comp["floor"] else "no", cp + "/floor",
               comp["floor"], "yes: the smallest baseline value is 0, so a tie at 0 "
               "decides 'fails'")
    return reason, short


def _numbers_from_hypotheses(nb: Numbers, ev: Src) -> None:
    """Every outcome with its caveats. The aggregate names, on each comparison,
    the sides pooled over fewer runs than registered ('every run' over fewer runs
    is an easier test), the reason for each 'not testable', and H2's floor; all
    of it is exported beside the outcome word, so an outcome never reaches
    numbers.json without them."""
    h, s = ev.get("hypotheses")
    rr = h.get("registered_repeats")
    short_all = h.get("short_of_registered_repeats") or {}
    nb.put("h_short_of_registered_repeats",
           "; ".join(f"{cell}: {n} of {rr}" for cell, n in sorted(short_all.items())) or "none",
           s + "/short_of_registered_repeats", short_all, "cell: pooled runs of registered")

    def entry(key: str, ptr: str, outcome: str, parts: list[tuple[str | None, list[str]]]):
        nb.put(f"{key}_outcome", outcome, ptr + "/outcome", outcome, "text")
        reasons = [r for r, _ in parts if r]
        # Components that share a side give the same clause each (H4-D's two RBA
        # gains both name D's baseline runs), so a clause is printed once, in
        # first-seen order (review 2026-10-09, S6-12 lead item).
        clauses = list(dict.fromkeys(c for r in reasons for c in r.split("; ")))
        short = list(dict.fromkeys(x for _, sh in parts for x in sh))
        nb.put(f"{key}_reason", "; ".join(clauses) or "none", ptr + "/components/*/reason",
               reasons, "text")
        nb.put(f"{key}_short_of_repeats", "; ".join(short) or "none",
               ptr + "/components/*/short_of_registered_repeats", short, "text")
        nb.caveats[f"{key}_outcome"] = short

    for L, pc in (h["H1"].get("per_corpus") or {}).items():
        base = f"{s}/H1/per_corpus/{L}"
        parts = []
        for comp_name, comp in pc["components"].items():
            short = {"rba": "rba", "attribute_accuracy": "attr"}.get(comp_name, comp_name)
            parts.append(_comparison(nb, f"h1_{L}_{short}",
                                     f"{base}/components/{comp_name}", comp,
                                     "baseline", "r1"))
        entry(f"h1_{L}", base, pc["outcome"], parts)
    holds = h["H1"].get("holds_on") or []
    nb.put("h1_holds_on", " and ".join(holds) if holds else "none", s + "/H1/holds_on",
           holds, "text")
    for name, key in (("H2", "h2"), ("H4-D", "h4d"), ("H4-D'", "h4dp")):
        x = h[name]
        ptr = f"{s}/{_esc(name)}"
        parts = []
        for comp_name, comp in x["components"].items():
            if key == "h2":
                lower, upper = "r1", "baseline"      # H2: r1 below baseline, on C
            else:                                     # H4: D below the named corpus
                m = re.search(r"vs_([A-D])$", comp_name)
                lower, upper = "D", (m.group(1) if m else "ref")
            parts.append(_comparison(nb, f"{key}_{comp_name}",
                                     f"{ptr}/components/{comp_name}", comp, lower, upper))
        entry(key, ptr, x["outcome"], parts)
    h3 = h["H3"]
    nb.put("h3_outcome", h3["outcome"], s + "/H3/outcome", h3["outcome"], "text")
    nb.put("h3_reason", h3.get("reason") or "none", s + "/H3/reason", h3.get("reason"), "text")
    for k, fmt in (("hits", "occurrences summed"), ("label_group_hits", "occurrences summed"),
                   ("runs_scanned", "count of runs")):
        nb.put(f"h3_{k}", str(h3[k]), f"{s}/H3/{k}", h3[k], fmt)
    uns = h3.get("runs_not_scanned") or {}
    nb.put("h3_runs_not_scanned", str(len(uns)), s + "/H3/runs_not_scanned", uns, "count")
    nb.put("h3_runs_not_scanned_list",
           "; ".join(f"{r}: {why}" for r, why in sorted(uns.items())) or "none",
           s + "/H3/runs_not_scanned", uns, "run: reason; ...")
    cells = h3.get("cells_uncovered") or []
    nb.put("h3_cells_uncovered", "; ".join(cells) or "none", s + "/H3/cells_uncovered",
           cells, "text")
    att = h3.get("attempts_not_scanned") or []
    nb.put("h3_attempts_not_scanned", str(len(att)), s + "/H3/attempts_not_scanned", att,
           "count")


def numbers_from_probes(nb: Numbers, probes: list[Src], corpora: dict[str, str],
                        measured: list[str] | None = None) -> None:
    """Per-corpus probe keys, and the pooled masked-document keys the introduction
    quotes. The pooled keys cover a claim about every corpus, so they are n/a
    unless every corpus in `measured` (the letters with runs in the aggregate;
    all of `corpora` when None) has a probe; ``maskdoc_corpora`` and
    ``maskdoc_corpora_missing`` say which corpora the range covers."""
    letter_of = {t: L for L, t in corpora.items()}
    pooled: dict[str, list[str]] = {"maskdoc_5gram_pct": [], "maskdoc_surfaces_surviving": []}
    covered: list[str] = []
    firsts: list[bool] = []
    g1: list[tuple[Src, str, dict[str, Any], list[str]]] = []
    shared_echo: dict[str, tuple[str, str]] = {}
    for pr in probes:
        cid, _ = pr.get("corpus", "id")
        L = letter_of.get(cid)
        if L is None:
            print(f"warning: probe {pr.label} is for corpus {cid!r}, which the aggregate "
                  "does not map to a letter; skipped", file=sys.stderr)
            continue
        if L in covered:
            raise SystemExit(f"two probes for corpus {L} ({cid}); pass one per corpus")
        covered.append(L)
        per = pr.data.get("per_extraction") or []
        vals: dict[str, list[str]] = {}
        for x in per:
            me = x["masked_exposure"]
            vals.setdefault("maskdoc_5gram_pct", []).append(
                fmt_pct(me["masked_5gram_hit_share"]))
            vals.setdefault("maskdoc_corpus5_surviving_pct", []).append(
                fmt_pct(me["corpus_5grams_surviving_share"]))
            vals.setdefault("maskdoc_surfaces_surviving", []).append(
                str(me["generator_surfaces_surviving"]["distinct"]))
            vals.setdefault("maskdoc_surfaces_extractor_miss", []).append(
                str(len(me["generator_surfaces_surviving"]["extractor_misses"])))
            vals.setdefault("maskdoc_refused_docs", []).append(
                fmt_kn(me["refused_documents"], len(me["documents"])))
            p = x["predicates"]
            vals.setdefault("pred_echo_pct", []).append(fmt_pct(p["echo_share"]))
            vals.setdefault("pred_whole_pct", []).append(fmt_pct(p["whole_match_share"]))
            vals.setdefault("pred_max_tokens", []).append(str(p["max_tokens"]))
            vals.setdefault("pred_n", []).append(str(p["n_predicates"]))
            rr = x["r5_residue"]
            vals.setdefault("r5_residue", []).append(
                fmt_kn(rr["referents_with_residue"], rr["referents_total"]))
            rec = x["recall"]["referents"]
            vals.setdefault("recall_referents_exact", []).append(
                fmt_kn(rec.get("exact"), rec.get("n")))
        for k, vs in vals.items():
            v = vs[0] if len(set(vs)) == 1 else (fmt_range(vs) if k not in (
                "maskdoc_refused_docs", "r5_residue", "recall_referents_exact")
                else "; ".join(vs))
            nb.put(f"{k}_{L}", v, f"{pr.label}#/per_extraction/*", vs,
                   "per distinct extraction; a range when they differ")
        _residue_split(nb, pr, L, vals.get("r5_residue", []))
        firsts.append(_shared_first(pr))
        _maskdoc_facts(nb, pr, L, per)
        for k in pooled:
            pooled[k] += vals.get(k, [])
        pc, s = pr.get("predicate_control", "expected_echo_share")
        nb.put(f"pred_control_echo_pct_{L}", fmt_pct(pc), s, pc, "%, 1 dp")
        shared_echo[L] = _shared_predicate_echo(nb, pr, L, per)
        var, s = pr.get("variance")
        for k in ("entity_jaccard", "relation_jaccard"):
            v = (var or {}).get(k)
            v = v.get("mean") if isinstance(v, dict) else v
            nb.put(f"extraction_{k}_{L}", fmt_num(v), f"{s}/{k}", v, "2 dp")
        de = (var or {}).get("distinct_extractions")
        nb.put(f"extractions_distinct_{L}", NA if de is None else str(de),
               s + "/distinct_extractions", de, "count")
        comps, s = pr.get("g1", "comparisons")
        # The comparisons of every corpus under one extraction rule (each its
        # saved extraction, or every one the stub), and only those: the mixed
        # one sets a real extraction against stubs, so it cannot stand under a
        # panel that says one rule for every corpus.
        one_rule = [(i, c) for i, c in enumerate(comps or []) if c.get("name") in G1_COMPARISONS]
        if not one_rule and comps:
            print(f"warning: probe {pr.label} has no G1 comparison named "
                  f"{' or '.join(repr(n) for n in G1_COMPARISONS)} "
                  f"({', '.join(repr(c.get('name')) for c in comps)}); "
                  "its G1 comparisons are not used", file=sys.stderr)
        for ci, comp in one_rule:
            g1_letters = sorted({letter_of[lab.split(":")[0]]
                                 for lab in comp.get("corpora") or []
                                 if lab.split(":")[0] in letter_of})
            g1.append((pr, f"{s}/{ci}", comp, g1_letters))
    need = list(corpora) if measured is None else list(measured)
    _numbers_from_g1(nb, g1, need, letter_of)
    _pooled_shared_echo(nb, shared_echo, need)
    missing = [L for L in need if L not in covered]
    covered.sort()
    nb.put("maskdoc_corpora", ", ".join(covered) or "none", "probe#/corpus/id (every probe)",
           covered, "corpus letters the pooled maskdoc_* keys cover")
    nb.put("maskdoc_corpora_missing", ", ".join(missing) or "none",
           "evaluation.json#/by_task/*/arms without a probe", missing,
           "corpora with runs and no probe")
    nb.put("maskdoc_shared_first", "yes" if firsts and all(firsts) else "no",
           "probe#/extractions/0/files (every probe)", firsts,
           "yes when every probe's first extraction is a run's extractions.json (the runs' "
           "shared extraction), so per-extraction figures list it first")
    if missing:
        print(f"warning: no probe for corpus {', '.join(missing)}, which has runs; the "
              f"pooled {', '.join(pooled)} are n/a", file=sys.stderr)
    for k, vs in pooled.items():
        src = (f"probe#/per_extraction/*/masked_exposure over corpora "
               f"{', '.join(covered) or 'none'}"
               + (f"; no probe for {', '.join(missing)}, so n/a" if missing else ""))
        nb.put(k, NA if missing else fmt_range(vs), src, vs,
               "one value, or lo–hi over the corpora named; n/a unless every corpus with "
               "runs has a probe")


_RUN_EXTRACTION = re.compile(r"(^|/)runs/[^/]+/extractions\.json$")


def _and_list(items: list[str]) -> str:
    """'a', 'a and b', 'a, b and c': the drafts' lists, without a serial comma
    (fig. 2's caption keeps _and's)."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _residue_split(nb: Numbers, pr: Src, L: str, vs: list[str]) -> None:
    """``r5_residue_shared_L``, the shared extraction's residue k/N, and
    ``r5_residue_further_L``, the further unseeded extractions' k/N in probe order,
    joined with 'and' ('none' when the probe analysed no further extraction), so
    that running text can state the runs' figure apart from the '; '-joined list
    ``r5_residue_L`` (review 2026-10-09, follow-up F11). Both are n/a unless the
    probe's first extraction is a run's extractions.json (_shared_first), which
    alone makes it the shared one."""
    ptr = f"{pr.label}#/per_extraction"
    fmt = "k/N, referents with residue / referents"
    known = bool(vs) and _shared_first(pr)
    nb.put(f"r5_residue_shared_{L}", vs[0] if known else NA, f"{ptr}/0/r5_residue",
           vs[:1], fmt + "; the shared extraction (the probe's first, a run's "
           "extractions.json); n/a otherwise")
    nb.put(f"r5_residue_further_{L}", (_and_list(vs[1:]) if vs[1:] else "none") if known
           else NA, f"{ptr}/1-/r5_residue", vs[1:],
           fmt + " per further unseeded extraction, in probe order, joined with 'and'; "
           "none without one; n/a unless the first extraction is the shared one")


def _shared_first(pr: Src) -> bool:
    """Whether the probe's first extraction is a run's extractions.json, i.e. the
    extraction the corpus's runs shared, which its per-extraction lists then
    give first."""
    exts = pr.data.get("extractions") or []
    files = (exts[0] or {}).get("files") or [] if exts else []
    return any(_RUN_EXTRACTION.search(str(f)) for f in files)


def _shared_predicate_echo(nb: Numbers, pr: Src, L: str,
                           per: list[dict[str, Any]]) -> tuple[str, str]:
    """``pred_echo_pct_shared_L``, the predicate echo share of the shared
    extraction alone (the relations C receives), and
    ``pred_control_echo_pct_shared_L``, its control on unrelated prose at that
    extraction's own predicate lengths: tier1_probe.predicate_control's expected
    share (the per-length shares averaged over the predicates' lengths), taken
    over the shared extraction's predicates only, where the probe's
    ``expected_echo_share`` takes every analysed extraction's. Both n/a unless the
    probe's first extraction is a run's extractions.json (_shared_first), or when
    the probe records no per-length control for one of its lengths. Returns the
    two formatted values (review 2026-10-10, CON-1: the further probe extractions
    were never sent)."""
    ptr = f"{pr.label}#/per_extraction/0/predicates"
    echo = ctrl = NA
    raw_echo = raw_ctrl = None
    if per and _shared_first(pr):
        p = per[0].get("predicates") or {}
        raw_echo = p.get("echo_share")
        echo = fmt_pct(raw_echo)
        lengths = p.get("length_tokens") or {}
        per_len = (pr.data.get("predicate_control") or {}).get("per_length") or {}
        shares = []
        for n, count in lengths.items():
            x = (per_len.get(str(n)) or {}).get("echo_share")
            if x is None:
                shares = []
                break
            shares += [x] * int(count)
        if shares:
            raw_ctrl = sum(shares) / len(shares)
            ctrl = fmt_pct(raw_ctrl)
    nb.put(f"pred_echo_pct_shared_{L}", echo, f"{ptr}/echo_share", raw_echo,
           "%, 1 dp; the runs' shared extraction only; n/a unless the probe's first "
           "extraction is a run's extractions.json")
    nb.put(f"pred_control_echo_pct_shared_{L}", ctrl,
           f"{pr.label}#/predicate_control/per_length/<n>/echo_share, averaged over "
           f"{ptr}/length_tokens", raw_ctrl,
           "%, 1 dp; unrelated prose at the shared extraction's predicate lengths, each "
           "predicate weighted once (tier1_probe.predicate_control's expected share over "
           "that extraction alone)")
    return echo, ctrl


def _pooled_shared_echo(nb: Numbers, shared: dict[str, tuple[str, str]],
                        need: list[str]) -> None:
    """``pred_echo_pct_all`` and ``pred_control_echo_pct_all``: one value, or lo–hi
    over the corpora, of the shared extraction's per-corpus figures
    (_shared_predicate_echo); n/a unless every corpus in `need` has both."""
    covered = [L for L in need if L in shared]
    missing = [L for L in need if L not in shared]
    for i, key, what in ((0, "pred_echo_pct_all", "pred_echo_pct_shared"),
                         (1, "pred_control_echo_pct_all", "pred_control_echo_pct_shared")):
        vs = [shared[L][i] for L in covered]
        nb.put(key, NA if missing or not vs else fmt_range(vs),
               f"{what}_<L> over corpora {', '.join(covered) or 'none'}"
               + (f"; no probe for {', '.join(missing)}, so n/a" if missing else ""),
               dict(zip(covered, vs, strict=True)),
               "one value, or lo–hi over the corpora (shared extraction only); n/a unless "
               "every measured corpus has a probe whose first extraction is the shared one")


def _maskdoc_facts(nb: Numbers, pr: Src, L: str, per: list[dict[str, Any]]) -> None:
    """What Table 2's masked-document note may say about corpus L.

    The construction fact under P2 is per document: a masked document that keeps
    a corpus 5-gram is refused. Every document of every extraction is checked,
    and one that keeps a corpus 5-gram (or a shingle hit) and is not refused
    stops the build, since the table states the fact. ``maskdoc_passed_shared_L``
    and ``maskdoc_passed_further_L`` count the documents the filter passes, under
    the shared extraction and under the further ones (each, by the check, keeps
    no corpus 5-gram).

    ``extraction_docs_lost_L`` counts the shared extraction's documents whose
    every extractor reply did not parse and was dropped, so that it holds no
    entity and no relation for them (ontology_extractor.py:388-393), read from the
    extraction file the probe names first; ``extraction_replies_lost_L`` counts
    those replies. ``maskdoc_lost_unmasked_L`` is 'yes' when each such document
    carries no placeholder in the masked copy, and ``maskdoc_upper_from_lost_L``
    'yes' when the corpus's upper masked-document figures come from them: the
    shared extraction holds the strict maximum of both the 5-gram share and the
    surviving surfaces, its share without those documents is no higher than
    another extraction's, and those documents hold more surviving-surface
    occurrences than its other documents together (review 2026-10-09,
    C-extraction-dropped-doc)."""
    docs_of = [(x.get("masked_exposure") or {}).get("documents") or [] for x in per]
    known = bool(per) and all(isinstance(d, dict) and "refused" in d
                              for ds in docs_of for d in ds)
    base = f"{pr.label}#/per_extraction"
    if known:
        for i, ds in enumerate(docs_of):
            for j, d in enumerate(ds):
                if (d.get("masked_5grams_hit") or d.get("shingle_hits_5_8")) and not d["refused"]:
                    raise SystemExit(
                        f"{base}/{i}/masked_exposure/documents/{j}: document "
                        f"{d.get('doc_id', j)} keeps a corpus 5-gram after masking and was not "
                        "refused; the construction fact under P2 that Table 2 states does not "
                        "hold for it")
    # What follows names the probe's first extraction "the shared extraction",
    # which it is only when it is a run's extractions.json.
    first = _shared_first(pr)
    known = known and first
    fmt = ("count of masked documents the filter passes; each keeps no corpus 5-gram "
           "(checked); n/a when the probe records no per-document verdicts or its first "
           "extraction is not a run's")
    shared = str(sum(1 for d in docs_of[0] if not d["refused"])) if known else NA
    further = str(sum(1 for ds in docs_of[1:] for d in ds if not d["refused"])) if known else NA
    nb.put(f"maskdoc_passed_shared_{L}", shared, f"{base}/0/masked_exposure/documents/*/refused",
           None if not known else [d.get("doc_id") for d in docs_of[0] if not d["refused"]],
           fmt + "; the shared extraction")
    nb.put(f"maskdoc_passed_further_{L}", further,
           f"{base}/1-/masked_exposure/documents/*/refused",
           None if not known else [[d.get("doc_id") for d in ds if not d["refused"]]
                                   for ds in docs_of[1:]],
           fmt + "; summed over the further extractions")

    exts = pr.data.get("extractions") or []
    files = list((exts[0] or {}).get("files") or []) if exts else []
    path = _REPO / files[0] if files else None
    keys = (f"extraction_docs_lost_{L}", f"extraction_replies_lost_{L}",
            f"maskdoc_lost_unmasked_{L}", f"maskdoc_upper_from_lost_{L}")
    if path is None or not path.is_file() or not first:
        for k in keys:
            nb.put(k, NA, f"{pr.label}#/extractions/0/files"
                   + (f" ({files[0]} not found)" if files and first
                      else " (not a run's extractions.json)" if files else " (absent)"),
                   files, "n/a: the shared extraction file cannot be read")
        return
    edocs = json.loads(path.read_text(encoding="utf-8")).get("documents") or []
    lost = [d for d in edocs if d.get("chunks") and (d.get("dropped_malformed") or 0)
            >= d["chunks"] and not d.get("entities") and not d.get("relations")]
    raw = [{k: d.get(k) for k in ("doc_id", "chunks", "dropped_malformed")} for d in lost]
    src = f"{files[0]}#/documents/*/dropped_malformed"
    nb.put(keys[0], str(len(lost)), src, raw,
           "count of the shared extraction's documents whose every extractor reply did not "
           "parse and was dropped (no entity, no relation)")
    nb.put(keys[1], str(sum(d["dropped_malformed"] for d in lost)), src, raw,
           "count of the extractor replies dropped for those documents")
    ids = {d.get("doc_id") for d in lost}
    if not lost or not known:
        for k in keys[2:]:
            nb.put(k, NA, src, None, "n/a: no lost document, or no per-document verdicts")
        return
    mdocs = {d.get("doc_id"): d for d in docs_of[0]}
    unmasked = all(i in mdocs and mdocs[i].get("placeholders") == 0 for i in ids)
    nb.put(keys[2], "yes" if unmasked else "no",
           f"{base}/0/masked_exposure/documents/*/placeholders",
           {i: (mdocs.get(i) or {}).get("placeholders") for i in sorted(ids)},
           "yes when every lost document carries no placeholder in the masked copy")
    me = [x.get("masked_exposure") or {} for x in per]
    share = [m.get("masked_5gram_hit_share") for m in me]
    dist = [(m.get("generator_surfaces_surviving") or {}).get("distinct") for m in me]
    rest = [d for d in docs_of[0] if d.get("doc_id") not in ids]
    masked = sum(d.get("masked_5grams") or 0 for d in rest)
    without = (sum(d.get("masked_5grams_hit") or 0 for d in rest) / masked) if masked else 0.0
    occ_lost = sum(d.get("surfaces_surviving") or 0 for d in docs_of[0] if d.get("doc_id") in ids)
    occ_rest = sum(d.get("surfaces_surviving") or 0 for d in rest)
    upper = (len(per) > 1 and None not in share and None not in dist
             and share[0] > max(share[1:]) and dist[0] > max(dist[1:])
             and without <= max(share[1:]) and occ_lost > occ_rest)
    nb.put(keys[3], "yes" if upper else "no", f"{base}/*/masked_exposure",
           {"share": share, "distinct_surfaces": dist, "shared_share_without_lost": without,
            "surface_occurrences_lost": occ_lost, "surface_occurrences_rest": occ_rest},
           "yes when the shared extraction holds the strict maximum of the 5-gram share and "
           "the surviving surfaces, its share without the lost documents is no higher than "
           "another extraction's, and the lost documents hold most of its surviving-surface "
           "occurrences")


# scripts/tier1_probe.py G1_SAVED and G1_STUB, in order of preference: the
# payloads the pipeline builds from each corpus's own extraction, and only
# failing a full one, every corpus under the stub (named as such).
G1_SAVED_COMPARISON = "all corpora under their saved extractions"
G1_STUB_COMPARISON = "all corpora under the stub extraction"
G1_COMPARISONS = (G1_SAVED_COMPARISON, G1_STUB_COMPARISON)
# scripts/tier1_probe.py _fields, each named in words for running text, word for
# word what Table 3's G1 rows show as identifiers; a field not listed is named by
# its identifier with spaces (review 2026-10-09, follow-up F11).
G1_FIELD_NAMES = {"document_stats": "document statistics",   # the DOCUMENT STATS line
                  "slot_counts": "slot counts",               # per category
                  "relation_multiset": "relation multiset",
                  "attribute_schema": "attribute schema",
                  "documents": "document count"}              # content-hash ids in doc_id


def _g1_stub_labels(comp: dict[str, Any]) -> list[str]:
    """The comparison's rows built from the stub extraction: its own
    ``stub_corpora``, and any ':stub' label (a probe written before that field)."""
    labels = list(comp.get("stub_corpora") or [])
    labels += [lab for lab in comp.get("corpora") or []
               if lab.endswith(":stub") and lab not in labels]
    return labels


def _numbers_from_g1(nb: Numbers, g1: list[tuple[Src, str, dict[str, Any], list[str]]],
                     need: list[str], letter_of: dict[str, str] | None = None) -> None:
    """The G1 inventory's rows, only from a comparison that covers every measured
    corpus: a field listed as identical across two of four corpora says nothing
    about the other two. The saved-extraction comparison is taken first, the
    stub one only when no saved one covers every measured corpus; then
    ``g1_stub_corpora`` names the corpora whose rows rest on the stub, and the
    build refuses it unless --allow-stub-g1. Otherwise no g1_differs_/g1_same_
    key is written, and ``g1_corpora_missing`` and a warning name the corpora no
    comparison covers."""
    letter_of = letter_of or {}
    rank = {G1_SAVED_COMPARISON: 0, G1_STUB_COMPARISON: 1}
    ordered = sorted(g1, key=lambda x: rank.get(x[2].get("name"), 2))
    full = next((x for x in ordered if not [L for L in need if L not in x[3]]), None)
    best = full or max(ordered, key=lambda x: len(x[3]), default=None)
    covered = best[3] if best else []
    missing = [L for L in need if L not in covered]
    src = (f"{best[1]}/corpora" if best
           else "probe#/g1 (no probe carries a G1 comparison)")
    nb.put("g1_corpora", ", ".join(covered) or "none", src, covered,
           "corpus letters the G1 comparison covers")
    nb.put("g1_corpora_missing", ", ".join(missing) or "none", src, missing,
           "measured corpora the G1 comparison does not cover")
    stub_labels = _g1_stub_labels(full[2]) if full else []
    stub = sorted(set(letter_of.get(lab.split(":")[0], lab.split(":")[0])
                      for lab in stub_labels))
    kind = "none" if full is None else "stub" if stub else "saved"
    nb.put("g1_extraction", kind, f"{full[1]}/name" if full else src,
           full[2].get("name") if full else None,
           "saved, stub, or none: the extraction the G1 rows are built from")
    nb.put("g1_stub_corpora", ", ".join(stub) or "none",
           f"{full[1]}/stub_corpora" if full else src, stub_labels,
           "corpora whose G1 row is built from the stub extraction, not an extractor run")
    if full is None:
        print("warning: the G1 rows are left out of Table 3: "
              + (f"the probe's G1 comparison does not cover corpus {', '.join(missing)}"
                 if best else "no probe carries a G1 comparison")
              + f" (measured: {', '.join(need) or 'none'})", file=sys.stderr)
        return
    if stub:
        print(f"warning: the G1 rows rest on the stub extraction for corpus "
              f"{', '.join(stub)} ({full[2].get('name')!r}), not on an extractor run; "
              "give tier1_probe.py each corpus's extraction as --g1 CORPUS=EXTRACTIONS.json",
              file=sys.stderr)
    ptr, comp = full[1], full[2]
    for arm in ARM_ORDER:
        d = (comp.get("by_arm") or dict()).get(arm) or dict()
        s = f"{ptr}/by_arm/{arm}"
        for which in ("differs", "same"):
            fields = list(d.get(which, []))
            key = f"g1_{which}_{arm}"
            nb.put(key, ", ".join(fields) or "none", f"{s}/{which}", d.get(which), "text")
            nb.put(key + "_text", _and_list([G1_FIELD_NAMES.get(f, f.replace("_", " "))
                                             for f in fields]) if fields else "none",
                   f"{s}/{which}", d.get(which),
                   "text: the fields named in words (G1_FIELD_NAMES), joined with 'and'")


def _check_stub_g1(nb: Numbers, allow: bool) -> None:
    """A G1 statement resting on the stub is not the payload the pipeline builds;
    at the freeze every corpus has a real extraction, so the build stops."""
    stub = nb.values.get("g1_stub_corpora", "none")
    if stub == "none":
        return
    msg = (f"the G1 rows rest on the stub extraction for corpus {stub}, not on the "
           "payloads the pipeline builds; give tier1_probe.py analyse every other "
           "corpus's extraction as --g1 CORPUS=EXTRACTIONS.json")
    if not allow:
        raise SystemExit(msg + ", or pass --allow-stub-g1 for a draft.")
    print(f"warning: {msg} (allowed: --allow-stub-g1)", file=sys.stderr)


def numbers_from_fp(nb: Numbers, fp: Src) -> None:
    dc, s = fp.get("deployed_chain")
    if not dc:
        raise SystemExit(f"{fp.label}: no 'deployed_chain' block; run "
                         "scripts/measure_false_positives.py at the tag (EXP5)")
    for mode, short in (("reset_per_payload", "reset"), ("session_per_stratum", "session")):
        m = dc["modes"][mode]
        b = f"{s}/modes/{mode}"
        nb.put(f"fp_deployed_{short}", fmt_kn(m["refusals"], m["n"]), b, m, "k/N")
        nb.put(f"fp_deployed_{short}_rate", fmt_num(m["rate"], 3), b + "/rate", m["rate"], "3 dp")
        nb.put(f"fp_deployed_{short}_ci", fmt_ci(m.get("wilson95")), b + "/wilson95",
               m.get("wilson95"), "Wilson 95%, 3 dp")
        for st, x in m["by_stratum"].items():
            nb.put(f"fp_deployed_{short}_{st}", fmt_kn(x["refusals"], x["n"]),
                   f"{b}/by_stratum/{st}", x, "k/N")
            nb.put(f"fp_deployed_{short}_{st}_ci", fmt_ci(x.get("wilson95")),
                   f"{b}/by_stratum/{st}/wilson95", x.get("wilson95"), "Wilson 95%, 3 dp")
    pc = dc["positive_control"]
    nb.put("fp_poscontrol_deployed", fmt_kn(pc["caught"], pc["n_sentences"]),
           s + "/positive_control", pc, "k/N")
    lin, s = fp.get("linters")
    for name, x in (lin or {}).items():
        b = f"{s}/{name}"
        nb.put(f"fp_standalone_{name}", fmt_kn(x["refusals"], x["n"]), b, x, "k/N")
        nb.put(f"fp_standalone_{name}_rate", fmt_num(x["rate"], 3), b + "/rate", x["rate"], "3 dp")
        nb.put(f"fp_standalone_{name}_ci", fmt_ci(x.get("wilson95")), b + "/wilson95",
               x.get("wilson95"), "Wilson 95%, 3 dp")
    _deployed_rules(nb, fp, dc, lin or {})
    pc, s = fp.get("positive_control")
    if pc:
        nb.put("fp_poscontrol_standalone", fmt_kn(pc["caught"], pc["n_sentences"]), s, pc, "k/N")
    n, s = fp.get("corpus", "n_payloads")
    nb.put("fp_n_payloads", NA if n is None else str(n), s, n, "count")
    n, s = fp.get("n_per_stratum")
    nb.put("fp_n_per_stratum", NA if n is None else str(n), s, n, "count")
    c, s = fp.get("git", "commit")
    nb.put("fp_commit", str(c)[:12] if c else NA, s, c, "sha[:12]")


def _deployed_rules(nb: Numbers, fp: Src, dc: dict[str, Any],
                    lin: dict[str, Any]) -> None:
    """``fp_deployed_rules_standalone``: 'yes' when, in every carry mode, the
    rules the deployed chain fired on clean payloads are exactly the entropy and
    regex screens' standalone rules, rule by rule and count by count, so that no
    containment rule fired; 'no' otherwise, and n/a when the report records no
    rules. Table 2 says so only on 'yes' (review 2026-10-09,
    T2-deployed-rate-composition)."""
    _, s = fp.get("deployed_chain", "modes")
    modes = {m: (x or {}).get("rules_fired") for m, x in (dc.get("modes") or {}).items()}
    screens = [(lin.get(n) or {}).get("rules_fired") for n in ("entropy", "regex")]
    if not modes or any(r is None for r in (*modes.values(), *screens)):
        nb.put("fp_deployed_rules_standalone", NA, f"{s}/*/rules_fired", modes,
               "n/a: the report records no rules_fired for a mode or a screen")
        return
    want: dict[str, int] = {}
    for r in screens:
        for rule, n in r.items():
            want[rule] = want.get(rule, 0) + n
    same = all(dict(r) == want for r in modes.values())
    nb.put("fp_deployed_rules_standalone", "yes" if same else "no",
           f"{s}/*/rules_fired against {fp.label}#/linters/entropy/rules_fired and "
           "#/linters/regex/rules_fired", {"modes": modes, "entropy_and_regex": want},
           "yes when every carry mode's rules_fired equals the entropy and regex screens' "
           "standalone rules_fired summed, so no containment rule fired")
    if not same:
        print("warning: the deployed chain's rules_fired differ from the entropy and regex "
              "screens' standalone rules; Table 2 does not say which rules its refusals fired",
              file=sys.stderr)


# ------------------------------------------- build: deployment constants

# Where the monitor's and the extractor's settings are read (review 2026-10-10,
# DES-1 and DES-5): the code at the checkout this build runs from, which the
# freeze binding (check_commit_binding) ties to the batch's commit, and the run
# manifests the batch wrote.
GATEWAY_MAIN = _REPO / "gateway" / "main.py"
ENTROPY_LINTER = _REPO / "gateway" / "linters" / "entropy_linter.py"
REGEX_RULES = _REPO / "gateway" / "linters" / "regex_rules.py"
COMPOSE_FILE = _REPO / "docker-compose.yml"
SLM_CLIENT = _REPO / "backend" / "src" / "privdeep" / "tier1_local" / "slm_client.py"
EXTRACTOR = _REPO / "backend" / "src" / "privdeep" / "tier1_local" / "ontology_extractor.py"
_SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def fmt_pow10(x: float) -> str:
    """A small rate as one in a power of ten: 1e-07 -> '1 in 10⁷'; a rate that is
    not a power of ten as one in its rounded reciprocal: 2.5e-07 -> '1 in 4,000,000'.
    The exponent is in superscript digits, which the numeral checker does not read
    as numerals, so the value's span covers it whole; no superscript minus is used,
    since the body font (Times New Roman, Liberation Serif) lacks that glyph."""
    import math  # noqa: PLC0415
    if not 0 < x < 1:
        raise ValueError(f"not a rate below one: {x!r}")
    e = math.floor(math.log10(x) + 1e-12)
    m = round(x / 10 ** e, 6)
    if m == 1:
        return f"1 in 10{str(-e).translate(_SUPERSCRIPT)}"
    return f"1 in {round(1 / x):,}"


def _fmt_int_range(values: list[int]) -> str:
    """One integer with thousands separators, or lo–hi."""
    lo, hi = min(values), max(values)
    return f"{lo:,}" if lo == hi else f"{lo:,}–{hi:,}"


def _function_default(path: Path, func: str, arg: str, cls: str | None = None) -> Any:
    """The literal default of `arg` in `func` (a method of `cls` when given), read
    from the source without importing it."""
    import ast  # noqa: PLC0415
    tree = ast.parse(path.read_text(encoding="utf-8"))
    scope = tree.body
    if cls is not None:
        scope = next((n.body for n in tree.body
                      if isinstance(n, ast.ClassDef) and n.name == cls), [])
    for n in scope:
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == func:
            a = n.args
            pos = a.posonlyargs + a.args
            for p, d in zip(pos[len(pos) - len(a.defaults):], a.defaults, strict=True):
                if p.arg == arg:
                    return ast.literal_eval(d)
            for p, d in zip(a.kwonlyargs, a.kw_defaults, strict=True):
                if p.arg == arg and d is not None:
                    return ast.literal_eval(d)
    raise SystemExit(f"{path}: no default for {arg!r} in {cls + '.' if cls else ''}{func}")


def _calls_passing(path: Path, attr: str, keyword: str) -> list[int]:
    """Lines of `path` where a call to ``.attr(...)`` or ``attr(...)`` passes
    `keyword`."""
    import ast  # noqa: PLC0415
    out = []
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if name == attr and any(k.arg == keyword for k in n.keywords):
                out.append(n.lineno)
    return out


def _load_by_path(path: Path, name: str):
    import importlib.util  # noqa: PLC0415
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod          # dataclasses look their module up there
    spec.loader.exec_module(mod)
    return mod


def gateway_constants() -> dict[str, Any]:
    """The deployed monitor's screen settings, from the code: the entropy
    threshold (gateway/main.py's default, which docker-compose.yml's default must
    repeat), the entropy screen's minimum token length (scan_payload's default,
    which main.py must not override), and the regex screen's rule count
    (DEFAULT_RULES, the screen main.py builds with no custom term). A deployment's
    .env could override the threshold; it is not read (CLAUDE.md), and
    numbers_from_deployment checks the value against the false-positive report
    measured through the deployed chain at the tag."""
    main = GATEWAY_MAIN.read_text(encoding="utf-8")
    m = re.search(r'ENTROPY_THRESHOLD\s*=\s*float\(os\.environ\.get\(\s*'
                  r'"SHANNON_ENTROPY_THRESHOLD",\s*"([0-9.]+)"\s*\)\)', main)
    c = re.search(r"SHANNON_ENTROPY_THRESHOLD:\s*\$\{SHANNON_ENTROPY_THRESHOLD:-([0-9.]+)\}",
                  COMPOSE_FILE.read_text(encoding="utf-8")) if COMPOSE_FILE.is_file() else None
    if not m:
        raise SystemExit(f"{GATEWAY_MAIN}: no ENTROPY_THRESHOLD default found")
    if c and c.group(1) != m.group(1):
        raise SystemExit(f"{COMPOSE_FILE} defaults SHANNON_ENTROPY_THRESHOLD to {c.group(1)}, "
                         f"{GATEWAY_MAIN} to {m.group(1)}")
    calls = re.findall(r"scan_payload\(([^)]*)\)", main)
    if not calls or any("min_length" in a for a in calls):
        raise SystemExit(f"{GATEWAY_MAIN}: the entropy screen is not called with "
                         "scan_payload's default min_length")
    if not re.search(r"\bRegexScreen\(\)\.scan\b", main):
        raise SystemExit(f"{GATEWAY_MAIN}: the regex screen is not built as RegexScreen() "
                         "(default rules, no custom term)")
    rules = _load_by_path(REGEX_RULES, "_paper_gateway_regex_rules").DEFAULT_RULES
    return {"entropy_threshold": m.group(1),
            "entropy_min_len": _function_default(ENTROPY_LINTER, "scan_payload", "min_length"),
            "regex_rules": len(rules)}


def slm_constants() -> dict[str, Any]:
    """The extractor's sampling temperature: AsyncSLMClient.chat's default, which every
    extractor call must leave alone."""
    passing = _calls_passing(EXTRACTOR, "chat", "temperature")
    if passing:
        raise SystemExit(f"{EXTRACTOR} passes its own temperature at line(s) "
                         f"{', '.join(map(str, passing))}; slm_temperature reads the default")
    return {"temperature": _function_default(SLM_CLIENT, "chat", "temperature",
                                             cls="AsyncSLMClient")}


def _pooled_manifests(ev: Src, runs_dir: Path | None) -> dict[str, dict[str, Any]] | None:
    """Each pooled private run's manifest.json under `runs_dir`; None when the
    directory is not given or a pooled run has no manifest there."""
    if runs_dir is None:
        return None
    out = {}
    for a in ARM_ORDER:
        for r in _ptr(ev.data, _p("arms", a, "runs")) or []:
            path = runs_dir / r / "manifest.json"
            if not path.is_file():
                print(f"warning: no manifest for pooled run {r} under {runs_dir}", file=sys.stderr)
                return None
            out[r] = json.loads(path.read_text(encoding="utf-8"))
    return out


def numbers_from_deployment(nb: Numbers, ev: Src, fp: Src | None,
                            runs_dir: Path | None) -> None:
    """The deployment's monitor and extractor settings that §4 states.

    From the code (gateway_constants, slm_constants): ``mon_entropy_threshold``
    (bits per character), ``mon_entropy_min_len`` (characters a token must exceed
    to be scanned), ``mon_regex_rules`` (formats the regex screen matches) and
    ``slm_temperature``. From the pooled runs' manifests: ``mon_bloom_bits``
    (the sealed Bloom filter's bits, one value or lo–hi over corpora, each corpus
    also as ``mon_bloom_bits_<L>``), ``mon_bloom_k`` (its index count),
    ``mon_bloom_fpr`` (the false-positive rate per shingle it is sized for, the
    false-positive report's target, checked against every run: each run's bits
    and index count must be BloomFilter.sized_for its shingles at that rate) and
    ``slm_quantisation`` (the local model's quantisation level). The manifest keys
    are n/a without the run directories; a disagreement between code, report and
    runs stops the build."""
    g = gateway_constants()
    want = (fp.data.get("entropy_threshold") if fp is not None and isinstance(fp.data, dict)
            else None)
    if want is not None and float(want) != float(g["entropy_threshold"]):
        raise SystemExit(f"{fp.label}#/entropy_threshold is {want}, the gateway's default "
                         f"{g['entropy_threshold']}: the deployed threshold was overridden")
    nb.put("mon_entropy_threshold", g["entropy_threshold"],
           "gateway/main.py ENTROPY_THRESHOLD default (docker-compose.yml repeats it; "
           "fp_report.json#/entropy_threshold agrees)", g["entropy_threshold"],
           "bits per character, as written in the code")
    nb.put("mon_entropy_min_len", str(g["entropy_min_len"]),
           "gateway/linters/entropy_linter.py scan_payload min_length default (gateway/main.py "
           "does not pass one)", g["entropy_min_len"],
           "count: characters a whitespace token must exceed to be scanned")
    nb.put("mon_regex_rules", str(g["regex_rules"]),
           "gateway/linters/regex_rules.py len(DEFAULT_RULES) (gateway/main.py builds "
           "RegexScreen() with no custom term)", g["regex_rules"], "count of regex rules")
    t = slm_constants()["temperature"]
    nb.put("slm_temperature", f"{t:g}",
           "backend/src/privdeep/tier1_local/slm_client.py AsyncSLMClient.chat temperature default "
           "(ontology_extractor.py passes none)", t, "as written in the code")

    target, ts = fp.get("shingle_filter", "target_fp_rate") if fp is not None else (None, "")
    manifests = _pooled_manifests(ev, runs_dir)
    keys = ("mon_bloom_bits", "mon_bloom_k", "mon_bloom_fpr", "slm_quantisation")
    if manifests is None or not manifests:
        for k in keys:
            nb.put(k, NA, "eval/runs/<run>/manifest.json (not read)", None,
                   "n/a: the pooled runs' manifests were not read (--runs)")
        return
    rel = (runs_dir.relative_to(_REPO).as_posix() if runs_dir.is_relative_to(_REPO)
           else str(runs_dir))
    letter_of = {t_: L for L, t_ in _corpora(ev).items()}
    task_of = {m.get("run"): m.get("task_id") for m in ev.data.get("per_task") or []}
    from shared.shingle_filter import BloomFilter  # noqa: PLC0415
    bits: dict[str, set[int]] = {}
    ks: set[int] = set()
    quant: set[str] = set()
    for run, man in sorted(manifests.items()):
        c = man.get("containment") or {}
        if not all(isinstance(c.get(f), int) for f in ("m_bits", "k", "shingles")):
            raise SystemExit(f"{rel}/{run}/manifest.json records no containment m_bits, k "
                             "and shingles")
        if target is not None:
            b = BloomFilter.sized_for(c["shingles"], float(target), b"size-only")
            if (b.m_bits, b.k) != (c["m_bits"], c["k"]):
                raise SystemExit(f"{rel}/{run}/manifest.json: a filter of {c['m_bits']} bits "
                                 f"and k = {c['k']} is not sized for {c['shingles']} shingles "
                                 f"at {target} ({ts}), which gives {b.m_bits} and {b.k}")
        L = letter_of.get(task_of.get(run) or run.split("__")[0], run.split("__")[0])
        bits.setdefault(L, set()).add(c["m_bits"])
        ks.add(c["k"])
        q = (((man.get("runtime") or {}).get("local_model") or {}).get("details") or {}) \
            .get("quantization_level")
        quant.add(q if isinstance(q, str) and q else NA)
    src = f"{rel}/<pooled run>/manifest.json#/containment"
    for L, vs in sorted(bits.items()):
        nb.put(f"mon_bloom_bits_{L}", _fmt_int_range(sorted(vs)), f"{src}/m_bits (corpus {L})",
               sorted(vs), "count of bits, thousands separated; lo–hi if its runs differ")
    allbits = sorted(v for vs in bits.values() for v in vs)
    nb.put("mon_bloom_bits", _fmt_int_range(allbits), src + "/m_bits", allbits,
           "count of bits, thousands separated; one value, or lo–hi over the corpora")
    nb.put("mon_bloom_k", _fmt_lohi(sorted(ks)), src + "/k", sorted(ks),
           "count of indices per item; lo–hi if runs differ")
    nb.put("mon_bloom_fpr", NA if target is None else fmt_pow10(float(target)),
           f"{ts}, checked against {src} (BloomFilter.sized_for)", target,
           "target false-positive rate per shingle, as a power of ten")
    if len(quant) > 1:
        print(f"warning: the pooled runs record quantisation levels {sorted(quant)}",
              file=sys.stderr)
    nb.put("slm_quantisation", " and ".join(sorted(quant)),
           f"{rel}/<pooled run>/manifest.json#/runtime/local_model/details/quantization_level",
           sorted(quant), "text, as Ollama reports it")


def numbers_from_observation(nb: Numbers, ob: Src) -> None:
    sm, s = ob.get("summary")
    if not sm:
        raise SystemExit(f"{ob.label}: no 'summary'; is this observation_table.py output?")
    nb.put("op_refused_attempts", fmt_kn(sm["refused_attempts"], sm["egress_attempts"]),
           s, [sm["refused_attempts"], sm["egress_attempts"]], "k/N")
    nb.put("op_runs_with_refusal", fmt_kn(sm["runs_with_any_refusal"], sm["runs"]), s,
           [sm["runs_with_any_refusal"], sm["runs"]], "k/N")
    nb.put("op_egress_attempts", str(sm["egress_attempts"]), s + "/egress_attempts",
           sm["egress_attempts"], "count")
    nb.put("op_runs", str(sm["runs"]), s + "/runs", sm["runs"], "count")
    nb.put("op_archived_attempts", str(sm["archived_attempts"]), s + "/archived_attempts",
           sm["archived_attempts"], "count")
    for kind in ("monitor", "reintegrator", "leak_gate_aborts", "transport_failures"):
        x = sm["refusals"][kind]
        nb.put(f"op_{kind}", str(x["count"]), f"{s}/refusals/{kind}/count", x["count"], "count")
        reasons = ", ".join(f"{r} {n}" for r, n in sorted(x["reasons"].items()))
        nb.put(f"op_{kind}_reasons", reasons or "none", f"{s}/refusals/{kind}/reasons",
               x["reasons"], "rule count, ...")
    d = sm["leak_gate_drops"]
    nb.put("op_leak_gate_drops", str(d["relations"]), s + "/leak_gate_drops/relations",
           d["relations"], "count summed over every run's manifest: a run that reuses an "
           "extraction re-reports its drops, so this over-counts; quote "
           "leak_gate_drops_total (once per extraction) instead")
    nb.put("op_leak_gate_drops_recorded", fmt_kn(d["runs_recorded"], sm["runs"]),
           s + "/leak_gate_drops/runs_recorded", d["runs_recorded"], "runs recorded/runs")
    for arm in ARM_ORDER:
        x = (sm.get("by_arm") or {}).get(arm)
        if not x:
            continue
        b = f"{s}/by_arm/{arm}"
        nb.put(f"obs_{arm}_runs", str(len(x["runs"])), b + "/runs", len(x["runs"]), "count")
        for fld, short, dp in (("slots_advertised_total", "slots_adv", 1),
                               ("slots_on_wire", "slots_wire", 1),
                               ("relations", "relations", 1),
                               ("fact_refs_returned", "fact_refs", 1),
                               ("sentences_pruned", "pruned", 1),
                               ("request_bytes", "req_bytes", 0),
                               ("response_bytes", "resp_bytes", 0)):
            nb.put(f"obs_{arm}_{short}", _fmt_obs(x[fld], dp), f"{b}/{fld}", x[fld],
                   f"mean [min–max] over frozen runs, {dp} dp")
        for stage in ("plan", "draft"):
            for io in ("input_tokens", "output_tokens"):
                y = x["tokens"][stage][io]
                nb.put(f"obs_{arm}_{stage}_{io.split('_')[0]}", _fmt_obs(y, 0),
                       f"{b}/tokens/{stage}/{io}", y, "mean [min–max], 0 dp")
        u = x["usd_total"]
        nb.put(f"obs_{arm}_usd", fmt_num(u.get("mean"), 2), b + "/usd_total/mean",
               u.get("mean"), "USD mean per run, 2 dp")
        nb.put(f"obs_{arm}_cost_complete", fmt_kn(x["cost_complete_runs"], len(x["runs"])),
               b + "/cost_complete_runs", x["cost_complete_runs"], "k/N")


def _fmt_obs(x: dict[str, Any], dp: int) -> str:
    if not x or x.get("mean") is None:
        return NA
    lo, hi = x.get("min"), x.get("max")
    m = fmt_fixed(x["mean"], dp)
    if lo is None or lo == hi:
        return m
    return f"{m} [{fmt_fixed(lo, 0)}–{fmt_fixed(hi, 0)}]"


def numbers_from_calibration(nb: Numbers, cal: Src) -> None:
    """The calibration keys, cal_<id>_*, bound to each row by its id (CAL_ROWS),
    never by its position in the file. A row the file lacks gives no keys."""
    rows, s = cal.get("rows")
    if not isinstance(rows, list) or not rows:
        raise SystemExit(f"{cal.label}: expected {{'rows': [...]}}")
    seen: set[str] = set()
    for i, r in enumerate(rows, 1):
        if not isinstance(r, dict):
            raise SystemExit(f"{cal.label}: row {i} is not an object")
        _check_labeller(cal.label, i, r)
        rid = _check_row_id(cal.label, i, r, seen)
        b = f"{s}/{i - 1}"
        ag = r.get("agreement")
        k, n = (ag.get("k"), ag.get("n")) if isinstance(ag, dict) else (None, None)
        occ = r.get("occurrences")
        if not all(isinstance(x, int) and not isinstance(x, bool) for x in (k, n, occ)) \
                or not 0 <= k <= n <= occ:
            raise SystemExit(f"{cal.label}: row {rid!r} needs integer occurrences and "
                             "agreement k and n with 0 <= k <= n <= occurrences (n counts "
                             f"the gold-valued occurrences among those labelled); got {occ!r}, "
                             f"{ag!r}")
        if "kappa" not in r or not _kappa_ok(r["kappa"]):
            raise SystemExit(f"{cal.label}: row {rid!r} needs kappa, a number in [-1, 1] or "
                             f"null when undefined; got {r.get('kappa', '(missing)')!r}")
        nb.put(f"cal_{rid}_occurrences", str(occ), b + "/occurrences", occ, "count")
        nb.put(f"cal_{rid}_agreement", fmt_kn(k, n), b + "/agreement", ag, "k/N")
        nb.put(f"cal_{rid}_agreement_pct", fmt_pct(k / n if n else None, 0),
               b + "/agreement", ag, "%, 0 dp")
        nb.put(f"cal_{rid}_kappa", fmt_num(r.get("kappa"), 2), b + "/kappa", r.get("kappa"),
               "2 dp")


CAL_LABELLERS = ("author", "assistant")
# The rows §5's calibration sentence states (paper/sections/05_setup.md; plan X5
# "Produces"), by stable id: id -> (labeller, blind, in_sample). The sentence
# names each row's report and says who labelled it and whether it is blind and
# in-sample, so a calibration file that says otherwise for an id is refused
# (_check_row_id), whatever order its rows are in.
CAL_ROWS: dict[str, tuple[str, bool, bool]] = {
    "insample_A_baseline": ("assistant", False, True),   # baseline report on A
    "dev_A_r1": ("author", True, False),                  # development r1 report on A
    "dev_A_oracle": ("author", True, False),              # its oracle report
    "heldout_B_r1": ("author", True, False),              # held-out r1 report on B
    # Added on 2026-10-10 after the simulated review (MR1-MR2): the baseline report
    # of the same corpus and repeat, labelled blind by the author after the batch
    # (eval/calibration/heldout/README.md). An exploratory row: its keys exist only
    # once its labels do, from calibration.json or from --review-analyses.
    "heldout_B_baseline": ("author", True, False),        # held-out baseline report on B
}
# Rows added after the batch as exploratory analyses: §5's registered calibration
# sentence need not state them, and a manuscript that quotes one before its labels
# exist stops the fill, like any absent row.
CAL_EXPLORATORY = frozenset({"heldout_B_baseline"})
CAL_FIELDS = ("occurrences", "agreement", "agreement_pct", "kappa")


def _kappa_ok(x: Any) -> bool:
    """Cohen's kappa as calibrate_faithfulness.py gives it: a number in [-1, 1], or
    null when undefined (both readers used one label)."""
    return x is None or (isinstance(x, int | float) and not isinstance(x, bool)
                         and -1 <= x <= 1)


def _check_labeller(label: str, i: int, r: dict[str, Any]) -> None:
    """Who labelled a calibration row, and that the sentence tells the truth about
    it: blind rows are the author's; a non-blind row is the in-sample row the
    assistant wrote."""
    who = r.get("labeller")
    name = f"{label}: row {i} ({r.get('id', r.get('label', ''))!r})"
    if who not in CAL_LABELLERS:
        raise SystemExit(f"{name} has labeller {who!r}; each row must say who labelled it, "
                         f"one of {', '.join(CAL_LABELLERS)}")
    if r.get("blind") and who != "author":
        raise SystemExit(f"{name} is blind but labelled by {who}; the sentence says the blind "
                         "rows are the author's")
    if not r.get("blind") and (who != "assistant" or not r.get("in_sample")):
        raise SystemExit(f"{name} is not blind, so the sentence calls it the in-sample row "
                         "the assistant wrote; it must be in_sample with labeller 'assistant'")


def _check_row_id(label: str, i: int, r: dict[str, Any], seen: set[str]) -> str:
    """The row's id, once it is known, not repeated, and its labeller, blind and
    in_sample (booleans) are what CAL_ROWS, and so the sentence, say of it."""
    rid = r.get("id")
    if rid not in CAL_ROWS:
        raise SystemExit(f"{label}: row {i} has id {rid!r}; each row must carry one of "
                         f"{', '.join(CAL_ROWS)}, the rows §5's sentence states")
    if rid in seen:
        raise SystemExit(f"{label}: row id {rid!r} appears twice")
    seen.add(rid)
    want = dict(zip(("labeller", "blind", "in_sample"), CAL_ROWS[rid], strict=True))
    got = {f: r.get(f) for f in want}
    if any(got[f] != v or type(got[f]) is not type(v) for f, v in want.items()):
        raise SystemExit(f"{label}: row {rid!r} is {got}, but §5's sentence states {want} "
                         "for it")
    return rid


# ------------------------------------------------- build: review analyses

REVIEW_INSTRUMENT = "scripts/review_analyses.py"
_CAT_SHORT = {"MATCH": "match", "MISMATCH": "mismatch", "UNRESOLVED": "unresolved"}
_RES_SHORT = {"scanned": "scanned", "gold_shaped": "gold", "referent": "ref",
              "attribute": "attr", "full": "both"}
_REVIEW_SIDES = (*ARM_ORDER, "oracle")


def check_review_inputs(ra: Src, files: dict[str, Path | None],
                        instrument: str = REVIEW_INSTRUMENT) -> None:
    """The analyses must be built from the inputs this build reads: an
    evaluation.json, observation.json or calibration.json other than the one
    review_analyses.py recorded (by sha256) stops the build. The post-hoc
    analyses of scope §13 (``--posthoc``) are held to the same rule, with their
    own instrument named."""
    import hashlib  # noqa: PLC0415 - only this check hashes
    recorded = ra.data.get("inputs") or {}
    for name, path in files.items():
        if path is None:
            continue
        want = recorded.get(name)
        got = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if want != got:
            raise SystemExit(f"{ra.label} was built from another {name} (sha256 {want}) than "
                             f"{path} ({got}); rerun {instrument}")


def _fmt_mean_range(stat: dict[str, Any] | None, dp: int) -> str:
    """``mean [min–max]``, every figure at `dp`; the bare mean when min = max."""
    if not stat or stat.get("mean") is None:
        return NA
    m, lo, hi = (fmt_fixed(stat[k], dp) for k in ("mean", "min", "max"))
    return m if lo == hi else f"{m} [{lo}–{hi}]"


def _fmt_lohi(values: list[int]) -> str:
    """One count, or ``lo–hi`` when the runs of a cell differ."""
    if not values:
        return NA
    lo, hi = min(values), max(values)
    return str(lo) if lo == hi else f"{lo}–{hi}"


def numbers_from_review(nb: Numbers, ra: Src) -> None:
    """The keys of review_analyses.py's figures (the simulated review of
    2026-10-10, analyses from frozen data; each one post hoc and exploratory).

    * MR3a ``res_<L>_<side>_*`` per corpus and side (baseline, r5, r1, oracle),
      ``res_<side>_*`` pooled over corpora, ``res_<L>_<arm>_rep<n>_*`` per run
      (none for a run whose report is under blind labelling):
      ``scanned`` and ``gold`` (gold-valued occurrences) as counts, ``ref``,
      ``attr`` and ``both`` as k/N of the gold-valued ones whose referent,
      attribute or both the rule resolved, their pooled ``_pct``, and per cell
      the per-run ``_rate`` (mean [min–max]).
    * MR3b ``lex_*``: the RBA attribute-lexicon phrases in the 13 code meanings
      the r1 drafter is shown, the money codes whose meaning binds only to their
      own attribute or only to others, and per side ``lex_use_<side>_*``: lexicon
      hits in the reports and the share on a phrase the meanings contain.
    * MR3b ``covsplit_<L>_<side>_{stated,derived}`` (per-run cell) and ``_kn``
      (pooled k/N): coverage_correct over document-stated and derived facts.
    * MR3b ``noshare_<L>_<side>_{rba,attr,covcorrect}`` and the means
      ``noshare_<m>_<side>_<L>`` (with ``_n``): corpus A without the share-spent
      facts; ``noshare_<L>_facts`` and ``noshare_<L>_removed``.
    * MR4b ``bind_<L>_<arm>_*`` (MONEY slots, gold-valued ones, distinct gold
      values, money attributes per referent; for r1 referent slots, MONEY slots
      and facts in the store), ``bind_r1_codes``, and the chance model
      ``chance_<L>_<arm>_{attr,full}`` (2 dp), ``_obs`` (2 dp) and ``_kn``
      (observed k/N over the same occurrences), pooled as ``chance_<arm>_*``.
    * MR2 ``cal_<id>_*`` for every labelled row: the four CAL_FIELDS when
      calibration.json has not produced them (they must agree when it has), the
      readers' label counts ``cal_<id>_{human,rule}_<cat>`` (k/N), the confusion
      counts ``cal_<id>_cm_<human>_<rule>``, ``_kappa_pe``, ``_pabak``, ``_ac1``
      (2 dp), ``_kappa_ci`` ([lo, hi], 2 dp) and ``_kappa_ci_undefined`` (k/N
      resamples left out); ``cal_bootstrap_resamples``. A row whose sheet is not
      fully labelled gives no key.
    * MR9a ``corpus_*_<L>`` and the ranges over corpora ``corpus_*``: documents,
      characters, words, referents, table data cells, facts by kind.
    * MR9b ``maskdoc_*_nolost_<L>`` (per extraction, a range when they differ),
      ``maskdoc_*_shared_nolost_<L>`` and the pooled ``maskdoc_*_nolost``: the
      masked-document exposure without the documents an extraction lost;
      ``maskdoc_lost_docs_<L>`` and ``maskdoc_lost_docs``.
    * Minor 8 ``cost_*`` (USD, 2 dp: deployment, phase one's planner and
      drafter, apart from evaluation, oracle, judge and adversary) and
      ``latency_phase_one_*`` (seconds, 0 dp)."""
    if ra.data.get("instrument") != REVIEW_INSTRUMENT:
        raise SystemExit(f"{ra.label}: not {REVIEW_INSTRUMENT} output")
    _review_resolution(nb, ra)
    _review_lexicon(nb, ra)
    _review_covsplit(nb, ra)
    _review_noshare(nb, ra)
    _review_binding(nb, ra)
    _review_calibration(nb, ra)
    _review_corpus(nb, ra)
    _review_maskdoc(nb, ra)
    _review_cost(nb, ra)


def _res_keys(nb: Numbers, prefix: str, cell: dict[str, Any], src: str) -> None:
    s = cell.get("sum") or cell
    gold = s["gold_shaped"]
    nb.put(f"{prefix}_scanned", str(s["scanned"]), f"{src}/scanned", s["scanned"],
           "count: occurrences scanned (numerals and spelled-out gold values)")
    nb.put(f"{prefix}_gold", str(gold), f"{src}/gold_shaped", gold,
           "count: occurrences of a gold value")
    for f in ("referent", "attribute", "full"):
        short = _RES_SHORT[f]
        what = "referent and attribute" if f == "full" else f
        nb.put(f"{prefix}_{short}", fmt_kn(s[f], gold), f"{src}/{f}", [s[f], gold],
               f"k/N: gold-valued occurrences whose {what} the rule resolved / gold-valued "
               "occurrences")
        if "sum" in cell:
            nb.put(f"{prefix}_{short}_pct", fmt_pct(s[f] / gold if gold else None),
                   f"{src}/{f}", [s[f], gold], "%, 1 dp, pooled over the cell's runs")


def _review_resolution(nb: Numbers, ra: Src) -> None:
    res, s = ra.get("resolution")
    for L, sides in (res.get("cells") or {}).items():
        for side, cell in sides.items():
            b = f"{s}/cells/{L}/{side}"
            _res_keys(nb, f"res_{L}_{side}", cell, b + "/sum")
            for f in ("referent", "attribute", "full"):
                nb.put(f"res_{L}_{side}_{_RES_SHORT[f]}_rate",
                       _fmt_cell(cell["rates"][f], cell["runs"]), f"{b}/rates/{f}",
                       cell["rates"][f], "per-run resolved / gold-valued, mean "
                       "[min–max], 2 dp; (k of N runs) when a run has no gold-valued "
                       "occurrence")
    for side, cell in (res.get("arms") or {}).items():
        _res_keys(nb, f"res_{side}", cell, f"{s}/arms/{side}/sum")
    for i, r in enumerate(res.get("runs") or []):
        if "withheld" in r:          # its report is under blind labelling
            continue
        _res_keys(nb, f"res_{r['letter']}_{r['arm']}_rep{r['rep']}", r["private"],
                  f"{s}/runs/{i}/private")


def _review_lexicon(nb: Numbers, ra: Src) -> None:
    lx, s = ra.get("lexical_overlap")
    codes = lx["codes"]
    money = [c for c in codes if c.get("rba_attribute")]
    nb.put("lex_codes", str(len(codes)), f"{s}/codes", len(codes), "count: R1's codes")
    nb.put("lex_meanings_with_phrase", fmt_kn(lx["meanings_with_phrase"], len(codes)),
           f"{s}/meanings_with_phrase", lx["meanings_with_phrase"],
           "k/N: code meanings holding an RBA attribute-lexicon phrase")
    shared = lx["phrases_in_meanings"]
    nb.put("lex_phrases_in_meanings", fmt_kn(len(shared), lx["lexicon_phrases"]),
           f"{s}/phrases_in_meanings", shared,
           "k/N: distinct RBA lexicon phrases the meanings contain / lexicon phrases")
    nb.put("lex_phrases_in_meanings_list", _and_list([f"“{p}”" for p in shared]) if shared
           else "none", f"{s}/phrases_in_meanings", shared, "text, in the lexicon's order")
    nb.put("lex_money_codes", str(len(money)), f"{s}/codes", [c["code"] for c in money],
           "count: the codes an RBA attribute names")
    for cls, ids in (lx.get("money_codes") or {}).items():
        nb.put(f"lex_money_codes_{cls}", fmt_kn(len(ids), len(money)),
               f"{s}/money_codes/{cls}", ids,
               "k/N: money codes whose meaning binds, under the rule, to "
               + {"own_only": "its own attribute only", "mixed": "its own and another",
                  "other_only": "other attributes only", "none": "no attribute"}[cls])
        nb.put(f"lex_money_codes_{cls}_list", _and_list(ids) if ids else "none",
               f"{s}/money_codes/{cls}", ids, "text")
    nb.put("lex_identical_across_keys", "yes" if lx["lexicons_identical_across_keys"]
           else "no", f"{s}/lexicons_identical_across_keys",
           lx["lexicons_identical_across_keys"], "yes when the four keys carry one lexicon")
    nb.put("lex_r1_requests_with_meanings", fmt_kn(lx["r1_draft_requests_with_meanings"],
                                                   lx["r1_draft_requests"]),
           f"{s}/r1_draft_requests_with_meanings", lx["r1_draft_requests"],
           "k/N: r1 drafter requests carrying every code-meaning line")
    for side, u in (lx.get("usage") or {}).items():
        b = f"{s}/usage/{side}"
        nb.put(f"lex_use_{side}_hits", str(u["hits"]), f"{b}/hits", u["hits"],
               "count: RBA lexicon hits in the side's reports, every pooled run")
        nb.put(f"lex_use_{side}_shared", fmt_kn(u["shared"], u["hits"]), f"{b}/shared",
               [u["shared"], u["hits"]], "k/N: hits on a phrase the code meanings contain")
        nb.put(f"lex_use_{side}_shared_pct", fmt_pct(u["shared"] / u["hits"] if u["hits"]
                                                     else None), f"{b}/shared",
               [u["shared"], u["hits"]], "%, 1 dp")
        nb.put(f"lex_use_{side}_per_kword", fmt_num(1000 * u["hits"] / u["words"]
                                                    if u["words"] else None, 1),
               f"{b}/words", [u["hits"], u["words"]], "hits per 1000 report words, 1 dp")


def _review_covsplit(nb: Numbers, ra: Src) -> None:
    cs, s = ra.get("coverage_split")
    for L, sides in (cs.get("cells") or {}).items():
        for side, cell in sides.items():
            b = f"{s}/cells/{L}/{side}"
            for kind in ("stated", "derived"):
                nb.put(f"covsplit_{L}_{side}_{kind}", _fmt_cell(cell[kind], cell["runs"]),
                       f"{b}/{kind}", cell[kind], f"coverage_correct over the key's {kind} "
                       "facts, mean [min–max] over runs, 2 dp")
                p = cell[f"{kind}_pooled"]
                nb.put(f"covsplit_{L}_{side}_{kind}_kn", fmt_kn(p["k"], p["n"]),
                       f"{b}/{kind}_pooled", p, f"k/N: {kind} facts correctly bound, summed "
                       "over runs / facts × runs")


def _review_noshare(nb: Numbers, ra: Src) -> None:
    ns, s = ra.get("without_share_spent")
    L = ns["letter"]
    nb.put(f"noshare_{L}_facts", str(ns["facts"]), f"{s}/facts", ns["facts"],
           "count: facts in the key without the share-spent facts")
    nb.put(f"noshare_{L}_removed", str(len(ns["removed_facts"])), f"{s}/removed_facts",
           ns["removed_facts"], "count: share-spent facts left out, with their attribute")
    for side, cell in (ns.get("cells") or {}).items():
        for short, m in (("rba", "rba"), ("attr", "attribute_accuracy"),
                         ("covcorrect", "coverage_correct")):
            b = f"{s}/cells/{side}/{m}"
            nb.put(f"noshare_{L}_{side}_{short}", _fmt_cell(cell[m], cell["runs"]), b,
                   cell[m], "mean [min–max], 2 dp; (k of N runs) when k < N (RBA "
                   "leaves out a run under the minimum pool)")
            _put_mean(nb, f"noshare_{short}_{side}_{L}", cell[m], cell["runs"], b)
    # Whether the baseline's attribute accuracy is unchanged without the
    # share-spent facts, as the two values are printed (review 2026-10-10, SET-2d:
    # §5 says 'unchanged' only on 'yes'). Only once the aggregate's own key exists.
    old, new = nb.values.get(f"attr_baseline_{L}"), nb.values.get(f"noshare_attr_baseline_{L}")
    if old is not None and new is not None:
        nb.put(f"noshare_baseline_{L}_unchanged",
               "yes" if old == new and old != NA else "no",
               f"numbers.json attr_baseline_{L} and noshare_attr_baseline_{L}", [old, new],
               "yes when the two formatted means are equal (and not n/a)")


def _review_binding(nb: Numbers, ra: Src) -> None:
    bd, s = ra.get("binding")
    codes = set()
    for L, sides in (bd.get("cells") or {}).items():
        for arm, c in sides.items():
            b = f"{s}/cells/{L}/{arm}"
            nb.put(f"bind_{L}_{arm}_money_slots", _fmt_lohi(c["money_slots"]),
                   f"{b}/money_slots", c["money_slots"],
                   "count of MONEY slots the payload lists (lo–hi when runs differ)")
            if arm == "r1":
                nb.put(f"bind_{L}_r1_referent_slots", _fmt_lohi(c["referent_slots"]),
                       f"{b}/referent_slots", c["referent_slots"],
                       "count of referent slots (PERSON, ORG, PROJECT, LOCATION) listed")
                nb.put(f"bind_{L}_r1_facts", _fmt_lohi(c["facts_in_store"]),
                       f"{b}/facts_in_store", c["facts_in_store"],
                       "count of facts in the r1 store (manifest facts_total)")
                codes.add(c["codes"])
                continue
            nb.put(f"bind_{L}_{arm}_gold_slots", _fmt_lohi(c["gold_money_slots"]),
                   f"{b}/gold_money_slots", c["gold_money_slots"],
                   "count of MONEY slots whose value is a gold value")
            nb.put(f"bind_{L}_{arm}_gold_values", _fmt_lohi(c["gold_money_values"]),
                   f"{b}/gold_money_values", c["gold_money_values"],
                   "count of distinct gold values among those slots")
            apr = c["attributes_per_referent"]
            nb.put(f"bind_{L}_{arm}_attrs_per_referent",
                   _fmt_lohi([v for v in (apr["min"], apr["max"]) if v is not None]),
                   f"{b}/attributes_per_referent", apr,
                   "count of money attributes per referent among the gold-valued slots "
                   "(lo–hi over referents)")
            _chance_keys(nb, f"chance_{L}_{arm}", c, b)
    if codes:
        nb.put("bind_r1_codes", _fmt_lohi(sorted(codes)), f"{s}/cells/*/r1/codes",
               sorted(codes), "count of R1's attribute codes")
    for arm, c in (bd.get("arms") or {}).items():
        _chance_keys(nb, f"chance_{arm}", c, f"{s}/arms/{arm}")


def _chance_keys(nb: Numbers, prefix: str, c: dict[str, Any], b: str) -> None:
    for ax, short in (("attribute", "attr"), ("full", "full")):
        x = c[ax]
        nb.put(f"{prefix}_{short}", fmt_num(x["chance"]), f"{b}/{ax}/chance", x["chance"],
               "chance accuracy under the model (review_analyses.json#/binding/model), 2 dp")
        nb.put(f"{prefix}_{short}_obs", fmt_num(x["observed"]), f"{b}/{ax}/observed",
               x["observed"], "observed accuracy over the same occurrences, 2 dp")
        nb.put(f"{prefix}_{short}_kn", fmt_kn(x["observed_k"], x["n"]), f"{b}/{ax}",
               [x["observed_k"], x["n"]], "k/N observed over the resolved money occurrences")


def _review_calibration(nb: Numbers, ra: Src) -> None:
    cal, s = ra.get("calibration")
    seen: set[str] = set()
    nb.put("cal_bootstrap_resamples", str(cal["bootstrap"]["resamples"]),
           f"{s}/bootstrap/resamples", cal["bootstrap"]["resamples"], "count")
    for i, r in enumerate(cal.get("rows") or [], 1):
        _check_labeller(ra.label, i, r)
        rid = _check_row_id(ra.label, i, r, seen)
        if r.get("status") != "labelled":
            continue
        b = f"{s}/rows/{i - 1}"
        k, n = r["agreement"]["k"], r["agreement"]["n"]
        base = {"occurrences": str(r["occurrences"]), "agreement": fmt_kn(k, n),
                "agreement_pct": fmt_pct(k / n if n else None, 0),
                "kappa": fmt_num(r.get("kappa"), 2)}
        for f in CAL_FIELDS:
            key = f"cal_{rid}_{f}"
            if key in nb.values:
                if nb.values[key] != base[f]:
                    raise SystemExit(f"{ra.label}: {key} is {base[f]!r}, but calibration.json "
                                     f"gives {nb.values[key]!r}")
                continue
            nb.put(key, base[f], f"{b}/{f if f != 'agreement_pct' else 'agreement'}",
                   r.get(f if f != "agreement_pct" else "agreement"),
                   "as numbers_from_calibration formats it")
        for who in ("human", "rule"):
            for cat, short in _CAT_SHORT.items():
                c = r[who][cat]
                nb.put(f"cal_{rid}_{who}_{short}", fmt_kn(c, n), f"{b}/{who}/{cat}", c,
                       f"k/N: gold-valued occurrences the {who} put in {cat}")
        for h, hs in _CAT_SHORT.items():
            for q, qs in _CAT_SHORT.items():
                c = r["confusion"][h][q]
                nb.put(f"cal_{rid}_cm_{hs}_{qs}", str(c), f"{b}/confusion/{h}/{q}", c,
                       "count: human label (first) by rule verdict (second)")
        for f in ("kappa_pe", "pabak", "ac1"):
            nb.put(f"cal_{rid}_{f}", fmt_num(r.get(f), 2), f"{b}/{f}", r.get(f), "2 dp")
        bs = r["bootstrap"]
        nb.put(f"cal_{rid}_kappa_ci", fmt_ci(bs.get("ci95"), 2), f"{b}/bootstrap/ci95",
               bs.get("ci95"), "percentile bootstrap 95% interval, 2 dp")
        nb.put(f"cal_{rid}_kappa_ci_undefined", fmt_kn(bs["undefined"], bs["resamples"]),
               f"{b}/bootstrap/undefined", bs["undefined"],
               "k/N: resamples on which kappa is undefined, left out")


_CORPUS_FIELDS = (("docs", "documents"), ("chars", "characters"), ("words", "words"),
                  ("referents", "referents"), ("table_cells", "table_data_cells"),
                  ("facts", "facts"))


def _review_corpus(nb: Numbers, ra: Src) -> None:
    cs, s = ra.get("corpus_stats")
    split = (ra.data.get("coverage_split") or {}).get("facts") or {}
    ranges: dict[str, list[str]] = {}
    for L, c in cs.items():
        b = f"{s}/{L}"
        vals = {short: c[f] for short, f in _CORPUS_FIELDS}
        kinds = c["facts_by_kind"]
        vals.update({f"facts_{k}": kinds[k] for k in ("table", "prose", "derived")})
        vals["facts_stated"] = kinds["table"] + kinds["prose"]
        if L in split and (split[L]["stated"], split[L]["derived"]) != (
                vals["facts_stated"], kinds["derived"]):
            raise SystemExit(f"{ra.label}: corpus {L}'s stated and derived facts differ "
                             "between corpus_stats and coverage_split")
        cells = nb.values.get(f"table_cells_{L}")
        if cells not in (None, NA) and cells != str(c["table_data_cells"]):
            raise SystemExit(f"{ra.label}: corpus {L} has {c['table_data_cells']} table data "
                             f"cells, the aggregate {cells}")
        for short, v in vals.items():
            nb.put(f"corpus_{short}_{L}", str(v), f"{b}/{short}", v, "count")
            ranges.setdefault(short, []).append(str(v))
    for short, vs in ranges.items():
        nb.put(f"corpus_{short}", fmt_range(vs), f"{s}/*/{short}", vs,
               "one count, or lo–hi over the corpora")


def _review_maskdoc(nb: Numbers, ra: Src) -> None:
    md, s = ra.get("maskdoc_without_lost")
    pooled: dict[str, list[str]] = {"surfaces": [], "pct": []}
    shared: dict[str, list[str]] = {"surfaces": [], "pct": []}
    lost_total = 0
    for L, c in md.items():
        exts = c["extractions"]
        b = f"{s}/{L}/extractions"
        surf = [str(e["kept"]["surfaces_distinct"]) for e in exts]
        pct = [fmt_pct(e["kept"]["masked_5gram_hit_share"]) for e in exts]
        lost = sum(len(e["lost_documents"]) for e in exts)
        lost_total += lost
        nb.put(f"maskdoc_surfaces_surviving_nolost_{L}", surf[0] if len(set(surf)) == 1
               else fmt_range(surf), f"{b}/*/kept/surfaces_distinct", surf,
               "distinct generator surfaces left standing, per extraction without the "
               "documents it lost; a range when they differ")
        nb.put(f"maskdoc_5gram_pct_nolost_{L}", pct[0] if len(set(pct)) == 1
               else fmt_range(pct), f"{b}/*/kept/masked_5gram_hit_share", pct,
               "%, 1 dp, per extraction without the documents it lost")
        nb.put(f"maskdoc_lost_docs_{L}", str(lost), f"{b}/*/lost_documents", lost,
               "count of (extraction, document) pairs left out")
        first = exts[0] if exts else None
        if first and _RUN_EXTRACTION.search(str(first.get("file") or "")):
            nb.put(f"maskdoc_surfaces_surviving_shared_nolost_{L}", surf[0],
                   f"{b}/0/kept/surfaces_distinct", surf[0],
                   "the runs' shared extraction, without the documents it lost")
            nb.put(f"maskdoc_5gram_pct_shared_nolost_{L}", pct[0],
                   f"{b}/0/kept/masked_5gram_hit_share", pct[0],
                   "%, 1 dp; the runs' shared extraction without the documents it lost")
            shared["surfaces"].append(surf[0])
            shared["pct"].append(pct[0])
        pooled["surfaces"] += surf
        pooled["pct"] += pct
    nb.put("maskdoc_surfaces_surviving_nolost", fmt_range(pooled["surfaces"]),
           f"{s}/*/extractions/*/kept/surfaces_distinct", pooled["surfaces"],
           "lo–hi over every corpus's extractions, lost documents left out")
    nb.put("maskdoc_5gram_pct_nolost", fmt_range(pooled["pct"]),
           f"{s}/*/extractions/*/kept/masked_5gram_hit_share", pooled["pct"],
           "lo–hi over every corpus's extractions, lost documents left out")
    nb.put("maskdoc_lost_docs", str(lost_total), f"{s}/*/extractions/*/lost_documents",
           lost_total, "count of (extraction, document) pairs left out, every corpus")
    # The runs' shared extraction only, the values Fig. 3(a) draws (pre-submission
    # audit of 2026-10-25): the pooled keys above also range over the probe's
    # further offline extractions, which the paper does not describe. Derived from
    # the same frozen values; no measurement changes.
    if shared["surfaces"] and len(shared["surfaces"]) == len(md):
        nb.put("maskdoc_surfaces_surviving_shared_nolost", fmt_range(shared["surfaces"]),
               f"{s}/*/extractions/0/kept/surfaces_distinct", shared["surfaces"],
               "lo–hi over the runs' shared extractions, lost documents left out")
        nb.put("maskdoc_5gram_pct_shared_nolost", fmt_range(shared["pct"]),
               f"{s}/*/extractions/0/kept/masked_5gram_hit_share", shared["pct"],
               "lo–hi over the runs' shared extractions, lost documents left out")


def _review_cost(nb: Numbers, ra: Src) -> None:
    co, s = ra.get("cost")
    blocks = {**{a: x for a, x in (co.get("arms") or {}).items()}, "all": co["all"]}
    for side, x in blocks.items():
        b = f"{s}/{'all' if side == 'all' else 'arms/' + side}"
        tag = "" if side == "all" else f"_{side}"
        for what in ("deploy", "eval"):
            st = x[f"{what}_usd"]
            nb.put(f"cost_{what}_usd{tag}", fmt_num(st.get("mean")), f"{b}/{what}_usd/mean",
                   st.get("mean"), "USD per run, mean, 2 dp")
            nb.put(f"cost_{what}_usd{tag}_range", _fmt_mean_range(st, 2), f"{b}/{what}_usd",
                   st, "USD per run, mean [min–max], 2 dp")
        nb.put(f"latency_phase_one_s{tag}", _fmt_mean_range(x["seconds_reused"], 0),
               f"{b}/seconds_reused", x["seconds_reused"], "seconds, mean [min–max], 0 dp, "
               "runs that reused the shared extraction")
    ext = co["all"]["seconds_extracted"]
    nb.put("latency_phase_one_extract_s", _fmt_mean_range(ext, 0), f"{s}/all/seconds_extracted",
           ext, "seconds, mean [min–max], 0 dp, runs that also ran the local extraction")
    nb.put("latency_phase_one_extract_n", str(ext.get("n") or 0),
           f"{s}/all/seconds_extracted/n", ext.get("n"), "count")
    t = co["totals"]
    nb.put("cost_deploy_usd_total", fmt_num(t["deploy_usd"]), f"{s}/totals/deploy_usd",
           t["deploy_usd"], "USD over every pooled run, 2 dp")
    nb.put("cost_eval_usd_total", fmt_num(t["eval_usd"]), f"{s}/totals/eval_usd",
           t["eval_usd"], "USD over every pooled run, 2 dp")
    for role, v in t["eval_usd_by_role"].items():
        nb.put(f"cost_eval_usd_total_{role}", fmt_num(v), f"{s}/totals/eval_usd_by_role/{role}",
               v, "USD, 2 dp")
    for io in ("input", "output"):
        v = t[f"deploy_{io}_tokens"]
        nb.put(f"cost_deploy_tokens_{io}_total", str(v), f"{s}/totals/deploy_{io}_tokens", v,
               "count of phase-one tokens, every pooled run")


# ------------------------------------------------- build: post-hoc analyses

# PRIVDEEP_ICCIT_SCOPE.md §13 (signed by the author on 2026-10-26): two offline
# analyses after the numbers freeze, S6 and S13 of the simulated review of that
# day, computed by scripts/posthoc_2026_10_26.py into eval/paper/posthoc.json.
# Read here by the AI assistant's change of 2026-10-26. Every key is post hoc and
# exploratory (§13.3) and is called so wherever the paper quotes it; none
# replaces an existing key.
POSTHOC_INSTRUMENT = "scripts/posthoc_2026_10_26.py"
_POSTHOC_ALL = "2-4"                 # posthoc.json's sum over n = 2, 3, 4
_CLIFF_MEASURES = (("attribute_accuracy", "attr"), ("rba", "rba"))


def _count(x: Any, where: str) -> int:
    if not isinstance(x, int) or isinstance(x, bool) or x < 0:
        raise SystemExit(f"{where}: expected a count, got {x!r}")
    return x


def _real(x: Any, where: str, lo: float | None = None, hi: float | None = None) -> float | None:
    """A number, or None (no value); out of [lo, hi] or not a number stops the build."""
    if x is None:
        return None
    if (not isinstance(x, int | float) or isinstance(x, bool) or x != x
            or (lo is not None and x < lo) or (hi is not None and x > hi)):
        raise SystemExit(f"{where}: expected a number in [{lo}, {hi}], got {x!r}")
    return float(x)


def _lohi_2dp(lo: float | None, hi: float | None) -> str:
    """``lo–hi`` at 2 dp, lo alone when they agree; n/a without both."""
    if lo is None or hi is None:
        return NA
    a, b = fmt_fixed(lo, 2), fmt_fixed(hi, 2)
    return a if a == b else f"{a}–{b}"


def numbers_from_posthoc(nb: Numbers, ph: Src, corpora: dict[str, str]) -> None:
    """The keys of scope §13's post-hoc analyses (posthoc.json), each post hoc
    and exploratory (§13.3).

    * S6 (§13.2(a)): ``s6_core_ngrams_<L>``, the distinct word n-grams of two to
      four tokens in a run's core-sent content (H3's definition) that are also
      corpus n-grams, stopword-only n-grams dropped, summed over n, lo–hi over the
      corpus's runs and arms (lo alone when they agree); ``s6_masked_ngrams_<L>``,
      the same count for the entity-masked documents of the shared extraction;
      ``s6_core_ngrams_range`` and ``s6_masked_ngrams_range``, lo–hi over the
      corpora.
    * S13 (§13.2(b)): per arm, over its pooled runs, the run-level judged quality
      (as ``judge_mean_exgr_<arm>``): ``judge_sd_<arm>`` (sample SD, 2 dp),
      ``judge_minmax_<arm>`` (min–max, 2 dp), ``judge_ci_<arm>`` (percentile
      bootstrap 95% interval of the mean, ``[lo, hi]``, 2 dp), with
      ``judge_sd_range`` over the arms and ``judge_ci_resamples``; per corpus,
      Cliff's delta of r1 against baseline on the frozen rule's per-run scores,
      ``cliff_attr_<L>`` (attribute accuracy) and ``cliff_rba_<L>`` (RBA), 2 dp,
      n/a where a side has no run with a value, each with the runs it compares,
      ``cliff_<m>_<L>_n_r1`` and ``cliff_<m>_<L>_n_baseline``, and
      ``cliff_attr_runs``, lo–hi of those runs over the corpora with a delta.

    The file must be the instrument's, its corpora the aggregate's, and every
    frozen key it reproduced (``reproduced``) the value this build gives it: a
    difference means it was computed from other data, and stops the build. A
    reproduced key this build does not produce (its input not given) is named."""
    if ph.data.get("instrument") != POSTHOC_INSTRUMENT:
        raise SystemExit(f"{ph.label}: not {POSTHOC_INSTRUMENT} output")
    rep, _ = ph.get("reproduced")
    if not rep:
        # The cross-check with the frozen keys is what ties the file to this build.
        raise SystemExit(f"{ph.label}: no reproduced frozen keys")
    differ = [f"{k} ({ph.label} {v!r}, this build {nb.values[k]!r})"
              for k, v in sorted((rep or {}).items()) if k in nb.values and nb.values[k] != v]
    if differ:
        raise SystemExit(f"{ph.label} reproduced frozen keys whose value this build does not "
                         f"give: {'; '.join(differ)}; rerun {POSTHOC_INSTRUMENT}")
    absent = sorted(k for k in (rep or {}) if k not in nb.values)
    if absent:
        print(f"warning: {ph.label} reproduced keys this build does not produce (their input "
              f"was not given): {', '.join(absent)}", file=sys.stderr)

    s6, s = ph.get("s6")
    if not isinstance(s6, dict) or not s6:
        raise SystemExit(f"{ph.label}: no s6 block")
    # Every corpus the aggregate measures, or the ranges over corpora would silently
    # cover fewer (final check of 2026-10-26).
    if set(s6) != set(corpora):
        raise SystemExit(f"{ph.label}: s6 covers {sorted(s6)}, the aggregate measures "
                         f"{sorted(corpora)}")
    los, his, masked_all = [], [], []
    for L in sorted(s6):
        c = s6[L]
        if corpora.get(L) != c.get("task"):
            raise SystemExit(f"{ph.label}: corpus {L} is {c.get('task')!r}, the aggregate's "
                             f"{corpora.get(L)!r}")
        b = f"{s}/{_esc(L)}"
        rr = (c.get("range_over_runs") or {}).get(_POSTHOC_ALL) or {}
        lo = _count(rr.get("min"), f"{b}/range_over_runs/{_POSTHOC_ALL}/min")
        hi = _count(rr.get("max"), f"{b}/range_over_runs/{_POSTHOC_ALL}/max")
        los.append(lo)
        his.append(hi)
        nb.put(f"s6_core_ngrams_{L}", _fmt_lohi([lo, hi]), f"{b}/range_over_runs/{_POSTHOC_ALL}",
               rr, "count: distinct corpus n-grams (n = 2-4, stopword-only dropped) in a run's "
               "core-sent content, lo–hi over the corpus's runs (lo alone when they agree); "
               "post hoc (scope §13)")
        m = _count((c.get("masked_documents") or {}).get(_POSTHOC_ALL),
                   f"{b}/masked_documents/{_POSTHOC_ALL}")
        masked_all.append(m)
        nb.put(f"s6_masked_ngrams_{L}", str(m), f"{b}/masked_documents/{_POSTHOC_ALL}", m,
               "count: distinct corpus n-grams (n = 2-4, stopword-only dropped) in the "
               "entity-masked documents of the shared extraction, lost documents left out; "
               "post hoc (scope §13)")
    letters = ", ".join(sorted(s6))
    nb.put("s6_core_ngrams_range", _fmt_lohi(los + his), f"{s}/*/range_over_runs/{_POSTHOC_ALL}",
           {"min": min(los), "max": max(his)},
           f"count, lo–hi over the runs of corpora {letters}; post hoc (scope §13)")
    nb.put("s6_masked_ngrams_range", _fmt_lohi(masked_all),
           f"{s}/*/masked_documents/{_POSTHOC_ALL}", masked_all,
           f"count, lo–hi over corpora {letters}; post hoc (scope §13)")

    jq, s = ph.get("s13", "judged_quality")
    if not isinstance(jq, dict):
        raise SystemExit(f"{ph.label}: no s13/judged_quality block")
    sds = []
    for arm in ARM_ORDER:
        q = jq.get(arm)
        b = f"{s}/{arm}"
        if not isinstance(q, dict):
            raise SystemExit(f"{ph.label}: no judged quality for arm {arm}")
        n = _count(q.get("n"), f"{b}/n")
        if nb.values.get(f"n_runs_{arm}", str(n)) != str(n):
            raise SystemExit(f"{b}/n is {n}, but the aggregate pools "
                             f"{nb.values[f'n_runs_{arm}']} {arm} runs")
        mean = _real(q.get("mean"), f"{b}/mean", 1, 5)
        if nb.values.get(f"judge_mean_exgr_{arm}", fmt_num(mean)) != fmt_num(mean):
            raise SystemExit(f"{b}/mean is {fmt_num(mean)}, but judge_mean_exgr_{arm} is "
                             f"{nb.values[f'judge_mean_exgr_{arm}']}")
        sd = _real(q.get("sd"), f"{b}/sd", 0, 4)
        sds.append(fmt_num(sd))
        nb.put(f"judge_sd_{arm}", fmt_num(sd), f"{b}/sd", sd,
               "sample SD (n−1) over the arm's runs of the run's judged quality, 2 dp; post hoc "
               "(scope §13)")
        lo, hi = (_real(q.get(k), f"{b}/{k}", 1, 5) for k in ("min", "max"))
        nb.put(f"judge_minmax_{arm}", _lohi_2dp(lo, hi), b, [lo, hi],
               "min–max over the arm's runs of the run's judged quality, 2 dp; post hoc "
               "(scope §13)")
        ci = q.get("ci95_bootstrap")
        if ci is not None and (not isinstance(ci, list) or len(ci) != 2):
            raise SystemExit(f"{b}/ci95_bootstrap: expected [lo, hi], got {ci!r}")
        ci = None if ci is None else [_real(x, f"{b}/ci95_bootstrap", 1, 5) for x in ci]
        nb.put(f"judge_ci_{arm}", fmt_ci(ci, 2), f"{b}/ci95_bootstrap", ci,
               "[lo, hi], 2 dp: percentile-bootstrap 95% interval of the mean over the arm's "
               "runs; post hoc (scope §13)")
    nb.put("judge_sd_range", fmt_range(sds), f"{s}/*/sd", sds,
           "lo–hi of judge_sd_<arm> over the private arms (one value when they agree); post hoc "
           "(scope §13)")
    bs, sb = ph.get("s13", "bootstrap")
    nb.put("judge_ci_resamples", str(_count((bs or {}).get("resamples"), f"{sb}/resamples")),
           f"{sb}/resamples", (bs or {}).get("resamples"), "count of bootstrap resamples")

    cd, s = ph.get("s13", "cliffs_delta_r1_vs_baseline")
    if not isinstance(cd, dict) or not cd:
        raise SystemExit(f"{ph.label}: no s13/cliffs_delta_r1_vs_baseline block")
    if set(cd) != set(corpora):
        raise SystemExit(f"{ph.label}: Cliff's delta covers {sorted(cd)}, the aggregate "
                         f"measures {sorted(corpora)}")
    runs: list[int] = []
    for L in sorted(cd):
        if L not in corpora:
            raise SystemExit(f"{ph.label}: Cliff's delta for corpus {L}, which the aggregate "
                             "does not measure")
        for m, short in _CLIFF_MEASURES:
            x = cd[L].get(m)
            b = f"{s}/{_esc(L)}/{m}"
            if not isinstance(x, dict):
                raise SystemExit(f"{ph.label}: no Cliff's delta for {m} on corpus {L}")
            n1, n2 = _count(x.get("n1"), f"{b}/n1"), _count(x.get("n2"), f"{b}/n2")
            delta = _real(x.get("delta"), f"{b}/delta", -1, 1)
            if (delta is None) != (not n1 or not n2):
                raise SystemExit(f"{b}: a delta needs a run with a value on each side "
                                 f"(n1 {n1}, n2 {n2}, delta {delta!r})")
            nb.put(f"cliff_{short}_{L}", fmt_num(delta), f"{b}/delta", delta,
                   "Cliff's delta of r1's runs against baseline's on the frozen rule's per-run "
                   "scores, 2 dp; n/a when a side has no run with a value; post hoc (scope §13)")
            nb.put(f"cliff_{short}_{L}_n_r1", str(n1), f"{b}/n1", n1,
                   "count: r1 runs with a value")
            nb.put(f"cliff_{short}_{L}_n_baseline", str(n2), f"{b}/n2", n2,
                   "count: baseline runs with a value")
            if short == "attr" and delta is not None:
                runs += [n1, n2]
    nb.put("cliff_attr_runs", _fmt_lohi(runs), f"{s}/*/attribute_accuracy/n1, n2", runs,
           "count of runs on each side of an attribute-accuracy delta, lo–hi over the corpora "
           "with a delta (one count when they agree)")


def numbers_from_meta(nb: Numbers, meta: Src) -> None:
    if not isinstance(meta.data, dict):
        raise SystemExit(f"{meta.label}: expected a flat JSON object of key -> string")
    for k, v in meta.data.items():
        if k.startswith("_"):
            continue
        if not isinstance(v, str):
            raise SystemExit(f"{meta.label}: {k} is not a string")
        if k.endswith("_date"):
            _check_iso_date(meta.label, k, v)
        nb.put(k, v, f"{meta.label}#{_p(k)}", v, "author-supplied text")


# ------------------------------------------------------------ build: track L

# Track L (scope §12, signed 2026-10-15): the three private arms over public ECHR
# judgments from TAB, standing in for private documents. Its instruments write
# counts and decisions only (never an identifier string), and this block turns
# them into keys: scripts/real_l.py scan (--real-l), scripts/presidio_residual.py
# (--presidio, one file per collection) and the recorded spend (--real-l-cost).
# L is reported beside A-D and never pooled with it (§12.1), so every key here
# has its own prefix (l_, hl1_) and no A-D key is touched.
REAL_L_INSTRUMENT = "scripts/real_l.py scan"
PRESIDIO_INSTRUMENT = "scripts/presidio_residual.py"
L_OUTCOMES = ("holds", "fails", "not testable")   # run_evaluation HOLDS, FAILS, NOT_TESTABLE
L_IDENTIFIER_TYPES = ("DIRECT", "QUASI")           # TAB's, scope §12.4
L_UTILITY_TYPES = ("DATETIME", "QUANTITY", "ORG")  # the utility proxy's, scope §12.6
# What `real_l.py budget` prints; `--real-l-cost` reads that line (or a JSON
# object with the same three amounts) because the scan JSON carries no spend.
_BUDGET_LINE = re.compile(r"private \$(\d+(?:\.\d+)?), adversary \$(\d+(?:\.\d+)?); "
                          r"spent before it \$(\d+(?:\.\d+)?)")


def _l_block(nb: Numbers, key: str, block: dict[str, Any] | None, src: str, what: str,
             *, pct: str | None = None) -> None:
    """One ``{"k", "n", "rate"}`` block of the scan as a k/n key, and as a
    percentage key beside it when ``pct`` names one; n/a for an absent block."""
    if not block:
        nb.put(key, NA, src, None, what + "; absent in the scan")
        if pct:
            nb.put(pct, NA, src, None, what + ", %; absent in the scan")
        return
    nb.put(key, fmt_kn(block.get("k"), block.get("n")), src, block, what + ", k/n")
    if pct:
        nb.put(pct, fmt_pct(block.get("rate")), src + "/rate", block.get("rate"),
               what + ", %, 1 dp")


def _l_sum_blocks(blocks: list[dict[str, Any] | None]) -> dict[str, Any] | None:
    """k/n blocks pooled by summing; None when there is none to pool."""
    got = [b for b in blocks if b]
    if not got:
        return None
    k, n = sum(int(b["k"]) for b in got), sum(int(b["n"]) for b in got)
    return {"k": k, "n": n, "rate": k / n if n else None}


def _l_route_words(rows: list[dict[str, Any]], where: str) -> str:
    """Routes in words (§12.7: entity types, counts and routes, never the strings):
    identifier type, entity type, stage, field, with the string-run pairs and
    occurrences each carried."""
    def count(n: Any, noun: str) -> str:
        return f"{n} {noun}" + ("" if int(n) == 1 else "s")

    # Singular or plural, not "pair(s)", which read as template residue (simulated
    # review of 2026-10-18).
    return "; ".join(
        f"{r['identifier_type']} {r['entity_type']} at the {r['stage']} stage in the "
        f"{r['field']} field{where}: {count(r['strings'], 'string-run pair')}, "
        f"{count(r['occurrences'], 'occurrence')}" for r in rows)


def _l_crossing_keys(nb: Numbers, h: dict[str, Any], hs: str) -> None:
    d = h["direct"]
    nb.put("l_direct_strings", str(d["n"]), f"{hs}/direct/n", d["n"],
           "count of distinct non-label DIRECT strings over the scanned collections")
    _l_block(nb, "l_direct_crossed_kn", d, f"{hs}/direct",
             "distinct non-label DIRECT strings that crossed in any private-arm run or "
             "archived attempt")
    nb.put("l_direct_bound", fmt_num(d.get("rule_of_three"), 3), f"{hs}/direct/rule_of_three",
           d.get("rule_of_three"), "rule-of-three 95% upper bound 3/n when k = 0, else n/a; "
           "3 dp; descriptive (§12.7)")
    p = h["direct_run_pairs"]
    _l_block(nb, "l_direct_pairs", p, f"{hs}/direct_run_pairs",
             "DIRECT string-by-run pairs that crossed")
    nb.put("l_direct_pairs_bound", fmt_num(p.get("rule_of_three"), 3),
           f"{hs}/direct_run_pairs/rule_of_three", p.get("rule_of_three"),
           "rule-of-three bound over the string-by-run pairs when k = 0, else n/a; 3 dp")
    _l_block(nb, "l_direct_onecall_kn", h.get("direct_one_call"), f"{hs}/direct_one_call",
             "DIRECT strings crossed under the single-call reading H3 uses (descriptive)")
    _l_block(nb, "l_direct_labels_crossed_kn", h.get("direct_labels_crossed"),
             f"{hs}/direct_labels_crossed",
             "label-group DIRECT strings that crossed, reported apart; they decide nothing")
    q = h["quasi_descriptive"]
    nb.put("l_quasi_strings", str(q["n"]), f"{hs}/quasi_descriptive/n", q["n"],
           "count of distinct non-label QUASI strings")
    _l_block(nb, "l_quasi_crossed_kn", q, f"{hs}/quasi_descriptive",
             "distinct non-label QUASI strings that crossed; descriptive, no threshold",
             pct="l_quasi_crossed_pct")
    for it, name, b in (("direct", "direct", d), ("quasi", "quasi_descriptive", q)):
        for t, x in sorted((b.get("by_entity_type") or {}).items()):
            _l_block(nb, f"l_{it}_type_{t}_kn", x, f"{hs}/{name}/by_entity_type/{t}",
                     f"distinct {it.upper()} strings of entity type {t} that crossed")
    words = _l_route_words(h.get("routes") or [], "")
    att = h.get("attempts") or {}
    if att.get("routes"):
        words = "; ".join(w for w in (words, _l_route_words(att["routes"],
                                                            " of an archived attempt")) if w)
    nb.put("l_cross_route_summary", words, f"{hs}/routes (and /attempts/routes)",
           [h.get("routes"), att.get("routes")],
           "routes of the crossings in words; empty when none crossed")
    nb.put("l_attempts_scanned", str(len(att.get("scanned") or [])), f"{hs}/attempts/scanned",
           att.get("scanned"), "count of archived phase-one attempts scanned")
    _l_block(nb, "l_attempts_direct_kn", att.get("direct"), f"{hs}/attempts/direct",
             "distinct DIRECT strings that crossed in an archived attempt; n/a when none "
             "was scanned")


def _l_arm_keys(nb: Numbers, sc: Src) -> None:
    by_arm, bs = sc.get("by_arm")
    valid: list[dict[str, Any]] = []
    sections = {"delivered": 0, "refused": 0, "transport_failed": 0}
    plans_refused = 0
    runs_total = 0
    reports: list[dict[str, Any] | None] = []
    per_type: dict[str, list[dict[str, Any] | None]] = {t: [] for t in L_UTILITY_TYPES}
    for arm in ARM_ORDER:
        x = (by_arm or {}).get(arm)
        if not x:
            continue
        b = f"{bs}/{arm}"
        n_runs = len(x["runs"])
        runs_total += n_runs
        nb.put(f"l_runs_{arm}", str(n_runs), b + "/runs", n_runs, "count of private runs")
        v = {"k": x["runs_valid"], "n": n_runs}
        valid.append(v)
        nb.put(f"l_health_valid_{arm}_kn", fmt_kn(v["k"], v["n"]), b + "/runs_valid", v,
               "runs that pass the health gate, k/n")
        for it in L_IDENTIFIER_TYPES:
            _l_block(nb, f"l_{it.lower()}_crossed_{arm}_kn", x["crossing_distinct"].get(it),
                     f"{b}/crossing_distinct/{it}",
                     f"distinct non-label {it} strings that crossed in a {arm} run")
            _l_block(nb, f"l_{it.lower()}_pairs_{arm}_kn", x["crossing_run_pairs"].get(it),
                     f"{b}/crossing_run_pairs/{it}",
                     f"{it} string-by-run pairs that crossed, {arm} runs")
        g = x.get("g3") or {}
        nb.put(f"l_g3_{arm}_collections", str(g.get("collections") or 0),
               b + "/g3/collections", g.get("collections"),
               "count of collections whose repeat-1 run the adversary attacked")
        _l_block(nb, f"l_g3_{arm}_net_kn", (g.get("net") or {}).get("all"), f"{b}/g3/net/all",
                 "non-label strings the adversary recovered from the rendered trace of the "
                 "arm's repeat 1, net of the no-trace control; an upper bound (§12.11)")
        _l_block(nb, f"l_g3_{arm}_gross_kn", (g.get("gross") or {}).get("all"),
                 f"{b}/g3/gross/all", "non-label strings in the adversary's output, gross")
        u = x["utility"]
        for what in sections:
            sections[what] += int(u[f"sections_{what}"])
        plans_refused += int(u.get("plans_refused") or 0)
        for what in ("delivered", "refused"):
            nb.put(f"l_sections_{what}_mean_{arm}",
                   fmt_num(u[f"sections_{what}"] / n_runs if n_runs else None, 1),
                   f"{b}/utility/sections_{what}", u[f"sections_{what}"],
                   f"sections {what} per run, mean over the arm's runs, 1 dp")
        rs = u.get("report_strings")
        reports.append((rs or {}).get("any"))
        for t in L_UTILITY_TYPES:
            per_type[t].append((rs or {}).get(t))
        _l_block(nb, f"l_utility_strings_{arm}_kn", (rs or {}).get("any"),
                 f"{b}/utility/report_strings/any",
                 f"DATETIME, QUANTITY and ORG strings present in the final report, {arm} "
                 "runs, pooled over runs", pct=f"l_utility_strings_{arm}_pct")
    _l_block(nb, "l_health_valid_kn", _l_sum_blocks(valid), f"{bs}/*/runs_valid",
             "private runs that pass the health gate, every arm")
    for what, n in sections.items():
        nb.put(f"l_sections_{what}_total", str(n), f"{bs}/*/utility/sections_{what}", n,
               f"count of sections {what}, every private run")
        if what != "transport_failed":
            nb.put(f"l_sections_{what}_mean", fmt_num(n / runs_total if runs_total else None, 1),
                   f"{bs}/*/utility/sections_{what}", n,
                   f"sections {what} per run, mean over every private run, 1 dp")
    nb.put("l_plans_refused_kn", fmt_kn(plans_refused, runs_total), f"{bs}/*/utility/plans_refused",
           plans_refused, "runs whose plan request the monitor refused, k/n")
    attempts = sum(sections.values()) + runs_total
    nb.put("l_refused_attempts_kn", fmt_kn(sections["refused"] + plans_refused, attempts),
           f"{bs}/*/utility", {"sections": sections, "plans_refused": plans_refused,
                               "runs": runs_total},
           "operational refusals, k/n: refused section and plan requests over every request "
           "(one plan per run, plus every section delivered, refused or failed in transport)")
    _l_block(nb, "l_utility_strings_kn", _l_sum_blocks(reports),
             f"{bs}/*/utility/report_strings/any",
             "DATETIME, QUANTITY and ORG strings present in the final report, pooled over "
             "every private run", pct="l_utility_strings_pct")
    for t in L_UTILITY_TYPES:
        _l_block(nb, f"l_utility_{t}_kn", _l_sum_blocks(per_type[t]),
                 f"{bs}/*/utility/report_strings/{t}",
                 f"{t} strings present in the final report, pooled over every private run",
                 pct=f"l_utility_{t}_pct")


def _l_extraction_keys(nb: Numbers, sc: Src) -> None:
    x, xs = sc.get("extraction")
    n = (x or {}).get("distinct_extractions") or 0
    nb.put("l_extractions", str(n), f"{xs}/distinct_extractions", n,
           "count of distinct extractions (one per collection when every run reused it)")
    rec = (x or {}).get("extractor_recall") or {}
    _l_block(nb, "l_recall_exact_kn", rec.get("all"), f"{xs}/extractor_recall/all",
             "identifier strings the extraction masked (token-tuple equality), once per "
             "extraction", pct="l_recall_exact_pct")
    cov = rec.get("covered") or {}
    _l_block(nb, "l_recall_covered_kn", cov.get("all"), f"{xs}/extractor_recall/covered/all",
             "identifier strings covered by a masked entity (contiguous inside one), once per "
             "extraction", pct="l_recall_covered_pct")
    for it in L_IDENTIFIER_TYPES:
        _l_block(nb, f"l_recall_exact_{it.lower()}_kn", rec.get(it),
                 f"{xs}/extractor_recall/{it}", f"{it} strings the extraction masked",
                 pct=f"l_recall_exact_{it.lower()}_pct")
        _l_block(nb, f"l_recall_covered_{it.lower()}_kn", cov.get(it),
                 f"{xs}/extractor_recall/covered/{it}",
                 f"{it} strings covered by a masked entity",
                 pct=f"l_recall_covered_{it.lower()}_pct")
    echo = (x or {}).get("predicate_echo") or {}
    _l_block(nb, "l_echo_kn", echo.get("all"), f"{xs}/predicate_echo/all",
             "identifier strings occurring in a relation field (predicate echo), once per "
             "extraction", pct="l_echo_pct")
    for it in L_IDENTIFIER_TYPES:
        _l_block(nb, f"l_echo_{it.lower()}_kn", echo.get(it), f"{xs}/predicate_echo/{it}",
                 f"{it} strings occurring in a relation field", pct=f"l_echo_{it.lower()}_pct")


def numbers_from_real_l(nb: Numbers, sc: Src) -> None:
    """Track L's keys (``l_*``, ``hl1_*``) from ``scripts/real_l.py scan`` output.

    ``hl1_outcome`` is the scan's own decision (``HL1.outcome``), never recomputed
    here; ``hl1_reason`` is its reason or "none"; ``hl1_computed`` is the outcome
    over the scanned collections alone, which differs only when they are not the
    registered L1-L6 (the pilot, for one), and ``hl1_registered`` says whether
    they are. ``l_digest_check`` is the §12.8 check: ok, mismatch, or unrecorded
    when the scan ran without ``--reference-runs``. Counts are k/n (``*_kn``),
    shares ``*_pct`` (1 dp), the rule-of-three bound 3 dp or n/a; a block the
    scan lacks (no run, no adversary output) gives n/a, never a missing key,
    except the per-arm and per-entity-type keys, which exist only for the arms
    and types the scan carries.
    """
    inst, _ = sc.get("instrument")
    if inst != REAL_L_INSTRUMENT:
        raise SystemExit(f"{sc.label}: not {REAL_L_INSTRUMENT} output (instrument {inst!r})")
    h, hs = sc.get("HL1")
    if not isinstance(h, dict) or h.get("outcome") not in L_OUTCOMES:
        raise SystemExit(f"{sc.label}: no HL1 block with an outcome in {L_OUTCOMES}")
    nb.put("hl1_outcome", h["outcome"], f"{hs}/outcome", h["outcome"],
           "the scan's own HL1 decision (§12.7), not recomputed")
    nb.put("hl1_reason", h.get("reason") or "none", f"{hs}/reason", h.get("reason"),
           "why HL1 is not testable, in the scan's words; none otherwise")
    computed = h.get("outcome_over_these_tasks") or h["outcome"]
    nb.put("hl1_computed", computed, f"{hs}/outcome_over_these_tasks", computed,
           "the outcome over the scanned collections alone")
    registered = sorted(h.get("collections") or []) == sorted(h.get("registered_collections")
                                                               or [])
    nb.put("hl1_registered", "yes" if registered else "no", f"{hs}/collections",
           [h.get("collections"), h.get("registered_collections")],
           "whether the scanned collections are exactly the registered L1-L6")
    if not registered:
        print(f"warning: {sc.label} scans {h.get('collections')}, not the registered "
              f"{h.get('registered_collections')}: hl1_outcome is {h['outcome']!r} and no "
              "key of this build is a track-L result (a pilot or a partial batch)",
              file=sys.stderr)
    integ = h.get("integrity")
    check = ("unrecorded" if not integ or not integ.get("checked")
             else "ok" if integ.get("all_equal") else "mismatch")
    nb.put("l_digest_check", check, f"{hs}/integrity", integ,
           "§12.8: ok when every L run's SLM image and model digests and resolved cloud model "
           "equal the A-D batch's; mismatch otherwise; unrecorded when the scan ran without "
           "--reference-runs")
    cols, cs = sc.get("collections")
    cols = cols or {}
    nb.put("l_collections", str(len(cols)), cs, sorted(cols), "count of collections scanned")
    nb.put("l_collection_list", ", ".join(sorted(cols)) or "none", cs, sorted(cols),
           "the collections scanned, by id")
    labels = sum(int((c.get("strings") or {}).get("labels") or 0) for c in cols.values())
    nb.put("l_labels_strings", str(labels), f"{cs}/*/strings/labels", labels,
           "count of label-group strings over the collections, reported apart")
    short = [f"{cid} {arm} {n}" for cid, c in sorted(cols.items())
             for arm, n in sorted((c.get("short_of_registered_repeats") or {}).items())]
    nb.put("l_short_of_repeats", "; ".join(short) or "none",
           f"{cs}/*/short_of_registered_repeats", short,
           "collection, arm and runs found where fewer than the registered repeats ran; "
           "none otherwise")
    runs, scanned = int(h["runs"]), int(h["runs_scanned"])
    incomplete = h.get("runs_incomplete") or {}
    nb.put("l_runs", str(runs), f"{hs}/runs", runs, "count of private-arm runs scanned")
    nb.put("l_runs_scanned_kn", fmt_kn(scanned, runs), f"{hs}/runs_scanned", scanned,
           "private runs whose egress trace was read, k/n")
    nb.put("l_runs_complete_kn", fmt_kn(runs - len(incomplete), runs), f"{hs}/runs_incomplete",
           sorted(incomplete), "private runs whose trace was scanned and complete, k/n")
    nb.put("l_runs_incomplete", str(len(incomplete)), f"{hs}/runs_incomplete",
           sorted(incomplete), "count of runs whose trace is missing, empty or incomplete")
    nb.put("l_cells_uncovered", str(len(h.get("cells_uncovered") or [])),
           f"{hs}/cells_uncovered", h.get("cells_uncovered"),
           "count of collection-arm cells without a run that passes the health gate")
    _l_crossing_keys(nb, h, hs)
    _l_arm_keys(nb, sc)
    _l_extraction_keys(nb, sc)
    ctrl = _l_sum_blocks([(((c.get("g3") or {}).get("control") or {}).get("recovered") or {})
                          .get("all") for c in cols.values()])
    _l_block(nb, "l_g3_control_kn", ctrl, f"{cs}/*/g3/control/recovered/all",
             "non-label strings in the no-trace control's output, pooled over collections "
             "with a control")


def numbers_from_presidio(nb: Numbers, files: list[Src], sc: Src | None) -> None:
    """The Presidio reference (``l_presidio_*``) from ``scripts/presidio_residual.py``
    output, one file per collection, pooled by summing. With the scan given, each
    file must be of a collection the scan holds, built from the same
    identifiers.json (sha256) and over the same string counts, and the two sets
    of collections must be equal, so that the two figures §12.6 sets side by side
    (never as one ranking) are over the same strings. The files must agree on
    the versions they ran."""
    if not files:
        return
    recs: dict[str, Src] = {}
    for f in files:
        gen, _ = f.get("generated_by")
        if gen != PRESIDIO_INSTRUMENT:
            raise SystemExit(f"{f.label}: not {PRESIDIO_INSTRUMENT} output (generated_by {gen!r})")
        cid, _ = f.get("collection")
        if not isinstance(cid, str) or not cid:
            raise SystemExit(f"{f.label}: no collection id")
        if cid in recs:
            raise SystemExit(f"{f.label}: {cid} is also {recs[cid].label}")
        recs[cid] = f
    versions = {json.dumps(f.get("versions")[0], sort_keys=True) for f in recs.values()}
    if len(versions) != 1:
        raise SystemExit("the Presidio files disagree on the versions they ran: "
                         + ", ".join(sorted(f.label for f in recs.values())))
    if sc is not None:
        cols = sc.get("collections")[0] or {}
        if sorted(cols) != sorted(recs):
            raise SystemExit(f"{sc.label} covers {sorted(cols)} and the Presidio files cover "
                             f"{sorted(recs)}; the two must be over the same collections")
        for cid, f in sorted(recs.items()):
            sha, _ = f.get("identifiers_sha256")
            if sha != cols[cid].get("identifiers_sha256"):
                raise SystemExit(f"{f.label}: identifiers.json sha256 differs from the scan's "
                                 f"for {cid}: the two are not over the same strings")
            for it in L_IDENTIFIER_TYPES:
                n = ((f.get("by_type", it, "total")[0] or {}).get("n"))
                if n != (cols[cid].get("strings") or {}).get(it):
                    raise SystemExit(f"{f.label}: {n} {it} strings scored, and the scan counts "
                                     f"{(cols[cid].get('strings') or {}).get(it)} for {cid}")
    first = recs[sorted(recs)[0]]
    labels = ", ".join(f.label for _, f in sorted(recs.items()))

    def src(*parts: Any) -> str:
        """The pointer into the first file, and the files it is pooled over."""
        return f"{first.label}#{_p(*parts)} (pooled over {len(recs)} file(s): {labels})"

    ver = first.get("versions")[0] or {}
    nb.put("l_presidio_version", str(ver.get("presidio-analyzer") or NA),
           src("versions", "presidio-analyzer"), ver, "version string, as installed")
    nb.put("l_presidio_model", str(ver.get("model_loaded") or NA),
           src("versions", "model_loaded"), ver,
           "the spaCy pipeline the analyzer loaded, name and version")
    nb.put("l_presidio_collections", str(len(recs)), src("collection"), sorted(recs),
           "count of collections Presidio scored")
    docs = sum(len(f.get("documents")[0] or []) for f in recs.values())
    nb.put("l_judgments", str(docs), src("documents"), docs,
           "count of judgments over the collections, as Presidio's per-document results list "
           "them")
    excluded = sum(int(f.get("labels_excluded")[0] or 0) for f in recs.values())
    nb.put("l_presidio_labels_excluded", str(excluded), src("labels_excluded"), excluded,
           "count of label-group strings left out of the Presidio figures")
    for it in L_IDENTIFIER_TYPES:
        low = it.lower()
        rows = [f.get("by_type", it)[0] or {} for _, f in sorted(recs.items())]
        types = sorted({t for r in rows for t in r} - {"total"})
        for t in ("total", *types):
            cells = [r.get(t) or {} for r in rows]
            tot = {c: sum(int(x.get(c) or 0) for x in cells)
                   for c in ("k", "k_one_call", "n", "present", "present_one_call")}
            ptr = src("by_type", it, t)
            tag = "" if t == "total" else f"_type_{t}"
            what = f"{it} strings{'' if t == 'total' else ' of entity type ' + t}"
            nb.put(f"l_presidio_{low}{tag}_kn", fmt_kn(tot["k"], tot["n"]), ptr, tot,
                   f"{what} surviving whole-token in Presidio's anonymised text, each string "
                   "read on its own (the per-string rule), k/n")
            if t == "total":
                nb.put(f"l_presidio_{low}_pct", fmt_pct(tot["k"] / tot["n"] if tot["n"]
                                                        else None), ptr, tot,
                       f"{what} surviving Presidio, %, 1 dp")
                nb.put(f"l_presidio_{low}_onecall_kn", fmt_kn(tot["k_one_call"], tot["n"]), ptr,
                       tot, f"{what} surviving Presidio under the single-call reading "
                       "(descriptive), k/n")
                nb.put(f"l_presidio_{low}_present_kn", fmt_kn(tot["present"], tot["n"]), ptr,
                       tot, f"{what} found whole-token in the original documents, k/n")


def load_real_l_cost(path: Path) -> Src:
    """The recorded spend of track L, as ``real_l.py budget`` prints it (its one
    line, captured to a file) or as a JSON object ``{"private", "adversary",
    "spent_before"}`` in USD."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SystemExit(f"missing input: {path}") from None
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict) and {"private", "adversary"} <= set(data):
        return Src(path.name, {"private": float(data["private"]),
                               "adversary": float(data["adversary"]),
                               "spent_before": float(data.get("spent_before") or 0.0),
                               "form": "json"})
    m = _BUDGET_LINE.search(text)
    if not m:
        raise SystemExit(f"{path}: neither a JSON object with 'private' and 'adversary' nor "
                         "the line scripts/real_l.py budget prints")
    return Src(path.name, {"private": float(m.group(1)), "adversary": float(m.group(2)),
                           "spent_before": float(m.group(3)), "form": "budget line"})


REFUSAL_SIM_INSTRUMENT = "scripts/real_l_refusal_sim.py"
_RELATION_KIND = "relations[]."


def _relation_windows(prompt: dict[str, Any]) -> int:
    """Windows the simulation attributes to relation fields: a field kind that
    starts with ``relations[].`` or a straddling window whose every kind does."""
    n = 0
    for kind, c in (prompt.get("by_field_kind") or {}).items():
        if str(kind).startswith(_RELATION_KIND):
            n += int(c)
    for kinds, c in (prompt.get("straddling_field_kinds") or {}).items():
        if all(k.startswith(_RELATION_KIND) for k in str(kinds).split("+")):
            n += int(c)
    return n


def numbers_from_refusal_sim(nb: Numbers, sim: Src) -> None:
    """Keys from scripts/real_l_refusal_sim.py (2026-10-15): for each arm, the
    collections whose planner request the monitor's chain refuses offline when
    rebuilt from the run's saved extraction (``l_sim_refused_<arm>_kn``), and,
    over the refused collections under r5 (the arm that ran first), how many
    5-8-gram windows the simulation found (``l_sim_windows``) and how many of
    them lie in or straddle relation fields (``l_sim_windows_relation_kn``), the
    relations with a corpus run (``l_sim_relations_with_run``) and the longest
    relation field in tokens (``l_sim_max_field_tokens``). Counts only: the
    simulation writes no string."""
    if sim.data.get("instrument") != REFUSAL_SIM_INSTRUMENT:
        raise SystemExit(f"{sim.label}: not {REFUSAL_SIM_INSTRUMENT} output "
                         f"(instrument {sim.data.get('instrument')!r})")
    cols = sim.data.get("collections") or {}
    if not isinstance(cols, dict) or not cols:
        raise SystemExit(f"{sim.label}: no collections")
    s = sim.label
    per_arm: dict[str, tuple[int, int]] = {}
    windows = relation = rels_run = 0
    max_tokens = 0
    n_sim = 0
    for cid in sorted(cols):
        exs = cols[cid].get("extractions") or []
        if not exs:
            continue
        n_sim += 1
        arms = exs[0].get("arms") or {}
        for arm, a in arms.items():
            k, n = per_arm.get(arm, (0, 0))
            per_arm[arm] = (k + (1 if a.get("refused") else 0), n + 1)
        r5 = arms.get("r5")
        if r5 and r5.get("refused"):
            prompt = r5.get("prompt") or {}
            windows += int(prompt.get("hits") or 0)
            relation += _relation_windows(prompt)
            rel = r5.get("relations") or {}
            rels_run += int(rel.get("relations_with_run") or 0)
            max_tokens = max(max_tokens, int(rel.get("max_field_tokens") or 0))
    nb.put("l_sim_collections", str(n_sim), f"{s}/collections (with an extraction)", n_sim,
           "count")
    for arm in ARM_ORDER:
        if arm in per_arm:
            k, n = per_arm[arm]
            nb.put(f"l_sim_refused_{arm}_kn", fmt_kn(k, n),
                   f"{s}/collections/*/extractions/0/arms/{arm}/refused", {"k": k, "n": n},
                   "k/N collections refused offline")
    if "r5" in per_arm:
        nb.put("l_sim_refused_kn", nb.values["l_sim_refused_r5_kn"],
               f"{s}/collections/*/extractions/0/arms/r5/refused", per_arm["r5"],
               "k/N collections refused offline, r5 (the arm run first)")
    nb.put("l_sim_windows", str(windows),
           f"{s}/collections/*/extractions/0/arms/r5/prompt/hits (refused collections)",
           windows, "count")
    nb.put("l_sim_windows_relation_kn", fmt_kn(relation, windows),
           f"{s}/collections/*/extractions/0/arms/r5/prompt/by_field_kind and "
           "/straddling_field_kinds (relations[].* kinds)", {"k": relation, "n": windows},
           "k/N windows in or straddling relation fields")
    nb.put("l_sim_relations_with_run", str(rels_run),
           f"{s}/collections/*/extractions/0/arms/r5/relations/relations_with_run", rels_run,
           "count over the refused collections")
    nb.put("l_sim_max_field_tokens", str(max_tokens),
           f"{s}/collections/*/extractions/0/arms/r5/relations/max_field_tokens", max_tokens,
           "max over the refused collections")


PLANNER_REFUSED_NOTE = "planning refused by monitor: "


def numbers_from_real_l_attempts(nb: Numbers, attempts: Path, sc: Src | None) -> None:
    """Keys from the archived phase-one attempts' manifests (counts only): the
    collections whose first r5 run the monitor refused at its planner request
    (``l_collections_planner_refused_kn``, over the scan's registered collections
    when the scan is given), those attempts' count, and the monitor's reason
    code, one code or "mixed". The manifest note is the pipeline's own
    (scope §12.13); no trace or report is read."""
    if not attempts.is_dir():
        raise SystemExit(f"{attempts}: no attempts directory")
    refused: dict[str, int] = {}
    codes: set[str] = set()
    n_attempts = 0
    for d in sorted(attempts.glob("*__*__attempt*")):
        m = d / "manifest.json"
        if not m.is_file():
            continue
        notes = json.loads(m.read_text(encoding="utf-8")).get("notes") or []
        for note in notes:
            if isinstance(note, str) and note.startswith(PLANNER_REFUSED_NOTE):
                cid = d.name.split("__", 1)[0]
                refused[cid] = refused.get(cid, 0) + 1
                n_attempts += 1
                codes.add(note[len(PLANNER_REFUSED_NOTE):].split(":", 1)[0].strip())
    if sc is not None:
        registered = sc.data.get("HL1", {}).get("registered_collections") or []
        n = len(registered) if registered else len(sc.data.get("collections") or {})
        k = sum(1 for c in refused if not registered or c in registered)
    else:
        n = len(refused)
        k = len(refused)
    src = f"{attempts}/*__*__attempt*/manifest.json#/notes ({PLANNER_REFUSED_NOTE.strip()})"
    nb.put("l_collections_planner_refused_kn", fmt_kn(k, n), src,
           {"collections": sorted(refused), "n": n},
           "k/N registered collections whose first run the monitor refused at the planner")
    # The admitted collections, n - k, so that the text can say how many the 12
    # runs cover (readability review of 2026-10-19); the same two counts, not a
    # new measurement.
    nb.put("l_collections_admitted", str(n - k), src, n - k,
           "count of registered collections whose first run the monitor did not refuse")
    nb.put("l_planner_refused_attempts", str(n_attempts), src, n_attempts, "count")
    nb.put("l_planner_refusal_code", (NA if not codes else
                                      next(iter(codes)) if len(codes) == 1 else "mixed"),
           src, sorted(codes), "the monitor's reason code, one or 'mixed'")


def numbers_from_real_l_cost(nb: Numbers, cost: Src) -> None:
    d = cost.data
    form = d.get("form", "json")
    nb.put("l_cost_private_usd", fmt_num(d["private"]), f"{cost.label}#/private ({form})",
           d["private"], "USD the private runs and archived attempts recorded, 2 dp")
    nb.put("l_cost_adversary_usd", fmt_num(d["adversary"]), f"{cost.label}#/adversary ({form})",
           d["adversary"], "USD the adversary calls recorded, 2 dp")
    nb.put("l_cost_usd", fmt_num(d["private"] + d["adversary"]),
           f"{cost.label}#/private + /adversary ({form})", [d["private"], d["adversary"]],
           "USD recorded for the batch's runs and adversary calls, 2 dp")
    nb.put("l_cost_before_usd", fmt_num(d["spent_before"]), f"{cost.label}#/spent_before ({form})",
           d["spent_before"], "USD spent before the batch (the pilot), as the budget counts it, "
           "2 dp")
    nb.put("l_cost_total_usd", fmt_num(d["private"] + d["adversary"] + d["spent_before"]),
           f"{cost.label}#/private + /adversary + /spent_before ({form})",
           [d["private"], d["adversary"], d["spent_before"]],
           "USD counted against the track-L cap, 2 dp")


# The dates §5 states (review 2026-10-10, SET-4), each checked against its record
# by check_meta_dates: the scope §8 amendment's signature (the pre-registration),
# the tag paper-freeze, and the frozen batch's runs.
SCOPE_FILE = _REPO / "PRIVDEEP_ICCIT_SCOPE.md"
FREEZE_TAG = "paper-freeze"


def _check_iso_date(label: str, key: str, value: str) -> None:
    import datetime  # noqa: PLC0415
    try:
        ok = datetime.date.fromisoformat(value).isoformat() == value
    except ValueError:
        ok = False
    if not ok:
        raise SystemExit(f"{label}: {key} must be a date as YYYY-MM-DD; got {value!r}")


def scope_signature_date(scope: Path = SCOPE_FILE) -> str | None:
    """The date the author signed the scope's §8 amendment (its **Status:**
    line), which holds H1-H3 and H4-D; None when the file or the line is absent."""
    if not scope.is_file():
        return None
    text = scope.read_text(encoding="utf-8")
    i = text.find("\n## 8.")
    m = re.search(r"\*\*Status:\*\*\s*signed by the author on (\d{4}-\d{2}-\d{2})",
                  text[i:] if i >= 0 else "")
    return m.group(1) if m else None


def tag_date_and_commit(tag: str = FREEZE_TAG, repo: Path = _REPO) -> tuple[str, str] | None:
    """(date, commit) of `tag` in git: an annotated tag's tagger date, else the
    commit's committer date, each in its own time zone, as YYYY-MM-DD; None when
    git or the tag is unavailable."""
    import shutil  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    git = shutil.which("git")
    if git is None:
        return None
    try:
        out = subprocess.run(  # noqa: S603 - argv list, no shell; executable via shutil.which
            [git, "-C", str(repo), "for-each-ref", f"refs/tags/{tag}",
             "--format=%(taggerdate:short)|%(committerdate:short)|%(*objectname)|%(objectname)"],
            capture_output=True, text=True, check=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out:
        return None
    tagger, committer, peeled, obj = out.split("|")
    return (tagger or committer), (peeled or obj)


def check_meta_dates(meta: Src | None, ev: Src, runs_dir: Path | None,
                     scope: Path = SCOPE_FILE, tag_info: tuple[str, str] | None | bool = True
                     ) -> None:
    """Each date --meta gives must be its record's: ``prereg_date`` the scope §8
    signature (scope_signature_date), ``freeze_tag_date`` the tag paper-freeze's
    date in git, at the commit ``freeze_commit`` names when both are given, and
    ``batch_date`` the UTC date on which every pooled run's manifest started and
    finished. A date whose record cannot be read (no scope file, no git or tag, no
    run directories) is warned about; one that disagrees stops the build. Pass
    `tag_info` (date, commit) or None to stand in for git."""
    import datetime  # noqa: PLC0415
    data = meta.data if meta is not None and isinstance(meta.data, dict) else {}
    if "prereg_date" in data:
        want = scope_signature_date(scope)
        if want is None:
            print(f"warning: no signed §8 amendment found in {scope}; prereg_date unchecked",
                  file=sys.stderr)
        elif data["prereg_date"] != want:
            raise SystemExit(f"--meta prereg_date {data['prereg_date']} is not the date the "
                             f"scope's §8 amendment was signed ({want}, {scope.name})")
    if "freeze_tag_date" in data:
        info = tag_date_and_commit() if tag_info is True else tag_info
        if not info:
            print(f"warning: the tag {FREEZE_TAG} cannot be read from git; freeze_tag_date "
                  "unchecked", file=sys.stderr)
        else:
            date, commit = info
            if data["freeze_tag_date"] != date:
                raise SystemExit(f"--meta freeze_tag_date {data['freeze_tag_date']} is not the "
                                 f"date of the tag {FREEZE_TAG} ({date})")
            fc = str(data.get("freeze_commit") or "").strip().lower()
            if fc and re.fullmatch(r"[0-9a-f]{7,40}", fc) and not commit.startswith(fc):
                raise SystemExit(f"--meta freeze_commit {fc} is not the commit the tag "
                                 f"{FREEZE_TAG} names ({commit[:12]})")
    models = _pooled_manifests(ev, runs_dir) if (
        "slm_model_id" in data or "cloud_model_id" in data) else None
    for key, field_, get in (
            ("slm_model_id", "local_model", lambda m: {m.get("local_model")}),
            ("cloud_model_id", "cloud_models_resolved",
             lambda m: set(m.get("cloud_models_resolved") or []))):
        if key in data and models:
            seen = set().union(*(get(m) for m in models.values()))
            if seen != {data[key]}:
                raise SystemExit(f"--meta {key} {data[key]!r} is not what every pooled run's "
                                 f"manifest records as {field_} ({sorted(map(str, seen))})")
    if "batch_date" in data:
        manifests = _pooled_manifests(ev, runs_dir)
        if not manifests:
            print("warning: the pooled runs' manifests are not read; batch_date unchecked",
                  file=sys.stderr)
            return
        days = set()
        for man in manifests.values():
            for f in ("started_at", "finished_at"):
                t = man.get(f)
                if isinstance(t, int | float):
                    days.add(datetime.datetime.fromtimestamp(t, datetime.UTC).date().isoformat())
        if days != {data["batch_date"]}:
            raise SystemExit(f"--meta batch_date {data['batch_date']} is not the date every "
                             f"pooled run started and finished on (UTC: "
                             f"{', '.join(sorted(days)) or 'none recorded'})")


# ------------------------------------------------------------ docx helpers

def _docx():
    import docx  # noqa: PLC0415 - optional dependency, system interpreter
    return docx


def _qn(tag: str) -> str:
    from docx.oxml.ns import qn  # noqa: PLC0415
    return qn(tag)


_SKIP_PARTS = ("styles.xml", "settings.xml", "fontTable.xml", "numbering.xml",
               "webSettings.xml", "stylesWithEffects.xml")


def _xml_part_items(document) -> list[tuple[str, Any]]:
    """(partname, root element) of every Word XML part python-docx parses that
    holds text: body, headers and footers. python-docx 1.x keeps footnotes,
    endnotes and comments as opaque parts; :func:`_unparsed_guillemets` covers
    those."""
    out, seen = [], set()
    for rel_part in [document.part, *document.part.package.iter_parts()]:
        el = getattr(rel_part, "_element", None)
        if el is None or id(rel_part) in seen:
            continue
        name = str(getattr(rel_part, "partname", ""))
        if not name.startswith("/word/") or name.endswith(_SKIP_PARTS):
            continue
        seen.add(id(rel_part))
        out.append((name, el))
    return out


def _xml_parts(document) -> list[Any]:
    return [el for _, el in _xml_part_items(document)]


def _unparsed_guillemets(src: Path, parsed: set[str]) -> list[str]:
    """Every /word/*.xml entry of the package, read raw, that the fill does not
    edit and that holds a guillemet (a «key» in a footnote, endnote or comment
    would otherwise be neither filled nor refused)."""
    import zipfile  # noqa: PLC0415
    out = []
    with zipfile.ZipFile(src) as z:
        for name in z.namelist():
            if not re.fullmatch(r"word/.+\.xml", name) or "/" + name in parsed:
                continue
            if "«".encode() in z.read(name) or "»".encode() in z.read(name):
                out.append("/" + name)
    return out


def _paragraph_ts(p_el) -> list[Any]:
    return list(p_el.iter(_qn("w:t")))


def placeholder_keys(document) -> list[str]:
    """Every «key» in the document, in order, split runs joined."""
    keys: list[str] = []
    for root in _xml_parts(document):
        for p in root.iter(_qn("w:p")):
            text = "".join(t.text or "" for t in _paragraph_ts(p))
            keys += PLACEHOLDER_RE.findall(text)
    return keys


def _unmatched_guillemets(text: str) -> bool:
    rest = PLACEHOLDER_RE.sub("", text)
    return "«" in rest or "»" in rest


class FillError(SystemExit):
    pass


def _in_table(p_el) -> bool:
    return any(True for _ in p_el.iterancestors(_qn("w:tc")))


def _set_text(t, text: str) -> None:
    t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def _run_is_empty(r) -> bool:
    kids = [c for c in r if c.tag != _qn("w:rPr")]
    return all(c.tag == _qn("w:t") and not (c.text or "") for c in kids)


def _tag_value(t, a: int, key: str, value: str, serial: list[int]) -> None:
    """Split the run holding w:t `t` at offset `a` and put `value` between the two
    halves as a run of its own (same rPr), bracketed by a bookmark
    ``pv_<tag>_<n>``. Names and ids are made unique by _renumber_value_bookmarks."""
    from docx.oxml import OxmlElement  # noqa: PLC0415
    r = t.getparent()
    if r.tag != _qn("w:r"):
        raise FillError(f"placeholder for {key} is not inside a text run")
    kids = list(r)
    idx = kids.index(t)
    s = t.text or ""
    tail = copy.deepcopy(r)
    for ch in kids[idx + 1:]:
        r.remove(ch)
    _set_text(t, s[:a])
    tkids = list(tail)
    for ch in tkids[:idx]:
        if ch.tag != _qn("w:rPr"):
            tail.remove(ch)
    _set_text(tkids[idx], s[a:])
    vr = copy.deepcopy(r)
    for ch in list(vr):
        if ch.tag != _qn("w:rPr"):
            vr.remove(ch)
    vt = OxmlElement("w:t")
    _set_text(vt, presented(value))    # S13(5), 2026-10-26: a negative sign as U+2212
    vr.append(vt)
    serial[0] += 1
    bid = str(900000 + serial[0])
    bs = OxmlElement("w:bookmarkStart")
    bs.set(_qn("w:id"), bid)
    bs.set(_qn("w:name"), f"{value_tag(key)}_{serial[0]}")
    be = OxmlElement("w:bookmarkEnd")
    be.set(_qn("w:id"), bid)
    r.addnext(bs)
    bs.addnext(vr)
    vr.addnext(be)
    be.addnext(tail)
    for x in (r, tail):
        if _run_is_empty(x):
            x.getparent().remove(x)


def _replace_in_paragraph(p_el, values: dict[str, str], serial: list[int] | None = None) -> int:
    """Replace every «key» in one paragraph, across w:t boundaries, with a tagged
    run holding its value (see _tag_value): the placeholder's characters are cut
    from every w:t they span, and the value takes the formatting of the run that
    held the opening guillemet. Returns the number replaced."""
    serial = serial if serial is not None else [0]
    n = 0
    while True:
        ts = _paragraph_ts(p_el)
        texts = [t.text or "" for t in ts]
        m = PLACEHOLDER_RE.search("".join(texts))
        if not m:
            return n
        key, (start, end) = m.group(1), m.span()
        first: tuple[Any, int] | None = None
        pos = 0
        for t, tx in zip(ts, texts, strict=True):
            lo, hi = pos, pos + len(tx)
            pos = hi
            if hi <= start or lo >= end or lo == hi:
                continue
            a, b = max(start, lo) - lo, min(end, hi) - lo
            if first is None:
                first = (t, a)
            _set_text(t, tx[:a] + tx[b:])
        assert first is not None
        _tag_value(first[0], first[1], key, values[key], serial)
        n += 1


def _renumber_value_bookmarks(roots: list[Any]) -> int:
    """Give every value bookmark a unique id and name across the document, after
    blocks from tables.docx were copied in: ``pv_<tag>_<n>``, n in document
    order, ids above every other bookmark's."""
    starts = [b for root in roots for b in root.iter(_qn("w:bookmarkStart"))]
    rx = re.compile(r"^(pv_[0-9a-f]{10})_\d+$")
    others = [int(b.get(_qn("w:id"))) for b in starts
              if not rx.match(b.get(_qn("w:name")) or "")
              and (b.get(_qn("w:id")) or "").isdigit()]
    nxt = max(others, default=0) + 1
    i = 0
    for b in starts:
        m = rx.match(b.get(_qn("w:name")) or "")
        if not m:
            continue
        old = b.get(_qn("w:id"))
        end = next((e for e in b.itersiblings() if e.tag == _qn("w:bookmarkEnd")
                    and e.get(_qn("w:id")) == old), None)
        if end is None:
            raise FillError(f"value bookmark {b.get(_qn('w:name'))} has no end in its "
                            "paragraph")
        i += 1
        b.set(_qn("w:name"), f"{m.group(1)}_{i}")
        b.set(_qn("w:id"), str(nxt))
        end.set(_qn("w:id"), str(nxt))
        nxt += 1
    return i


def _para_text(p_el) -> str:
    return "".join(t.text or "" for t in _paragraph_ts(p_el))


def _delete_span(p_el, start: int, end: int) -> None:
    """Cut characters [start, end) of the paragraph's text, across w:t elements."""
    pos = 0
    for t in _paragraph_ts(p_el):
        tx = t.text or ""
        lo, hi = pos, pos + len(tx)
        pos = hi
        if hi <= start or lo >= end:
            continue
        a, b = max(start, lo) - lo, min(end, hi) - lo
        _set_text(t, tx[:a] + tx[b:])


def _load_blocks(tables_docx: Path) -> dict[str, list[Any]]:
    """tables.docx body elements grouped by the pap_<id> bookmark on a caption."""
    docx = _docx()
    d = docx.Document(str(tables_docx))
    blocks: dict[str, list[Any]] = {}
    cur: str | None = None
    for el in d.element.body:
        if el.tag == _qn("w:sectPr"):
            continue
        bm = [b.get(_qn("w:name")) for b in el.iter(_qn("w:bookmarkStart"))]
        ids = [b[4:] for b in bm if b and b.startswith("pap_")]
        if ids:
            cur = ids[0]
            blocks[cur] = []
        if cur is not None:
            blocks[cur].append(el)
    return blocks


def _caption_keys(out_dir: Path, name: str) -> list[str]:
    cap = out_dir / name
    return PLACEHOLDER_RE.findall(cap.read_text(encoding="utf-8")) if cap.exists() else []


FIG2_FONT = "Courier New"
FIG2_PT = 7             # the listing's font size, in points
FIG2_ADVANCE = 0.6      # a Courier New character's advance, in ems
FIG2_BAND_PAD_PT = 4.5  # a band border's space (4 pt) and width (0.5 pt), _shade_paragraph


def _fig2_lines(out_dir: Path, values: dict[str, str]) -> list[tuple[str | None, str]]:
    """fig2_listing.txt as (key, line) pairs, a blank line with no key. Each
    non-empty line must be the current value of ``fig2_listing_<nn>`` and the
    count must be ``fig2_lines``: a listing from another build is refused."""
    lines = (out_dir / "fig2_listing.txt").read_text(encoding="utf-8").split("\n")
    while lines and not lines[-1]:
        lines.pop()
    out: list[tuple[str | None, str]] = []
    bad: list[str] = []
    n = 0
    for line in lines:
        if not line:
            out.append((None, ""))
            continue
        n += 1
        key = f"fig2_listing_{n:02d}"
        if values.get(key) != line:
            bad.append(key)
        out.append((key, line))
    if values.get("fig2_lines") != str(n):
        bad.append(f"fig2_lines ({values.get('fig2_lines')} in numbers.json, {n} in the file)")
    if bad:
        raise FillError(f"{out_dir / 'fig2_listing.txt'} is not the listing numbers.json "
                        f"holds ({', '.join(bad)}); rebuild with --fig2-run")
    return out


def _has_marker(d, bid: str) -> bool:
    return any(_para_text(p).lstrip().startswith(BLOCKS[bid])
               for p in d.element.body.iter(_qn("w:p")))


def fill(src: Path, dst: Path, out_dir: Path, banner: str | None = None,
         allow_na: bool = False, fig1_dir: Path = FIG1_DIR) -> dict[str, Any]:
    """The fill pass. Refuses, writing nothing, on any placeholder without a value,
    an unmatched guillemet, a guillemet in a part it cannot edit, or (unless
    `allow_na`) an n/a value in a paragraph outside a table. Fig. 1 and its
    caption are read from `fig1_dir`, the figure's source directory, not from
    the build's `out_dir`."""
    docx = _docx()
    numbers_path = out_dir / "numbers.json"
    values: dict[str, str] = json.loads(numbers_path.read_text(encoding="utf-8"))
    bad = sorted(k for k, v in values.items() if "«" in v or "»" in v)
    if bad:
        raise FillError(f"{numbers_path}: values holding a guillemet: {', '.join(bad)}")
    d = docx.Document(str(src))
    items = _xml_part_items(d)
    missing: dict[str, int] = {}
    broken: list[str] = []
    na_prose: list[str] = []
    for _, root in items:
        for p in root.iter(_qn("w:p")):
            text = _para_text(p)
            for k in PLACEHOLDER_RE.findall(text):
                if k not in values:
                    missing[k] = missing.get(k, 0) + 1
                elif values[k] == NA and not _in_table(p):
                    na_prose.append(k)
            if _unmatched_guillemets(text):
                broken.append(text[:120])
    msg = []
    if (out_dir / "fig2_listing.txt").exists() and _has_marker(d, "fig2"):
        for k in _caption_keys(out_dir, "fig2_caption.txt"):
            if k not in values:
                missing[k] = missing.get(k, 0) + 1
        try:
            _fig2_lines(out_dir, values)
        except FillError as exc:
            msg.append(str(exc))
    if _fig1_ready(fig1_dir) and _has_marker(d, "fig1"):
        for k in _caption_keys(fig1_dir, FIG1_CAPTION):
            if k not in values:
                missing[k] = missing.get(k, 0) + 1
    for bid, (png, caption) in DATA_FIGURES.items():
        if (out_dir / png).is_file() and _has_marker(d, bid):
            for k in _caption_keys(out_dir, caption):
                if k not in values:
                    missing[k] = missing.get(k, 0) + 1
    opaque = _unparsed_guillemets(src, {name for name, _ in items})
    if missing:
        msg.append(f"no value in {numbers_path} for: {', '.join(sorted(missing))}")
    if broken:
        msg.append("unmatched guillemet in: " + " | ".join(broken))
    if opaque:
        msg.append("a guillemet in a part the fill cannot edit (move the placeholder into "
                   "the body): " + ", ".join(opaque))
    if na_prose and not allow_na:
        msg.append("the value is n/a in running text for: "
                   + ", ".join(sorted(set(na_prose)))
                   + " (reword the sentence, or pass --allow-na for a draft)")
    if msg:
        raise FillError("refusing to fill " + str(src) + ": " + "; ".join(msg))
    serial = [0]
    replaced = 0
    for _, root in items:
        for p in list(root.iter(_qn("w:p"))):
            replaced += _replace_in_paragraph(p, values, serial)
    inserted, left, kept = _insert_blocks(d, out_dir, values, serial, fig1_dir)
    _nbsp_labels(d.element.body)
    from scripts import paper_format  # noqa: PLC0415
    # The running head and page numbers, if a source in the paper's format lacks them
    # (idempotent; a document without the paper's styles is left as it is).
    if _style(d, paper_format.FIGURE_CAPTION) is not None:
        paper_format.paginate(d, paper_format.RUNNING_HEAD)
    _keep_pictures_uncompressed(d)
    tagged = _renumber_value_bookmarks([root for _, root in items])
    if banner:
        _add_banner(d, banner)
    dst.parent.mkdir(parents=True, exist_ok=True)
    _save_deterministic(d, dst)
    return {"replaced": replaced, "inserted": inserted, "placeholders_left": left,
            "text_kept": kept, "values_tagged": tagged,
            "na_in_prose": sorted(set(na_prose))}


# A label and its number never part at a line end (pre-submission audit of
# 2026-10-25: "(Fig." / "3(b)" and "(Table" / "I)" broke across lines): the space
# after "Fig.", "Figs.", "Table(s)" and "Section(s)" before a number or a Roman
# numeral becomes a no-break space. The listing's lines (monospaced, tagged values)
# carry no such label.
_LABEL_SPACE_RE = re.compile(r"\b(Figs?\.|Tables?|Sections?) (?=[0-9]|[IVX]+\b)")


def _nbsp_labels(body) -> int:
    n = 0
    for t in body.iter(_qn("w:t")):
        if t.text and _LABEL_SPACE_RE.search(t.text):
            t.text, k = _LABEL_SPACE_RE.subn("\\1\u00a0", t.text)
            n += k
    return n


def _fig1_ready(fig1_dir: Path) -> bool:
    return (fig1_dir / FIG1_PNG).is_file() and (fig1_dir / FIG1_CAPTION).is_file()


def _insert_blocks(d, out_dir: Path, values: dict[str, str], serial: list[int],
                   fig1_dir: Path = FIG1_DIR) -> tuple[list[str], list[str], list[str]]:
    """Put each table, Fig. 1 or the Fig. 2 listing in front of its marker
    paragraph, then remove the marker and the skeleton's description; any other
    text there is the author's and stays (its block id is listed in the third
    return value)."""
    tables = out_dir / "tables.docx"
    blocks = _load_blocks(tables) if tables.exists() else {}
    fig2 = out_dir / "fig2_listing.txt"
    inserted, left, kept = [], [], []
    body = d.element.body
    from scripts import paper_format  # noqa: PLC0415
    two_columns = _style(d, paper_format.FIGURE_CAPTION) is not None
    for p in list(body.iter(_qn("w:p"))):
        full = _para_text(p)
        text = full.lstrip()
        for bid, marker in BLOCKS.items():
            if not text.startswith(marker):
                continue
            before = p.getprevious()
            if bid == "fig1":
                if not _fig1_ready(fig1_dir):
                    left.append(marker)
                    break
                _insert_figure(d, p, fig1_dir / FIG1_PNG, fig1_dir / FIG1_CAPTION, values,
                               serial, space_before_pt=FIG1_SPACE_BEFORE_PT)
            elif bid == "fig2":
                if not fig2.exists():
                    left.append(marker)
                    break
                _insert_listing(d, p, out_dir, values, serial)
            elif bid in DATA_FIGURES:
                png, caption = DATA_FIGURES[bid]
                if not (out_dir / png).is_file():
                    left.append(marker)
                    break
                _insert_figure(d, p, out_dir / png, out_dir / caption, values,
                               serial, width_in=FIG_RESULTS_WIDTH_IN)
            elif bid in blocks:
                for el in blocks[bid]:
                    p.addprevious(copy.deepcopy(el))
            else:
                left.append(marker)
                break
            inserted.append(bid)
            if two_columns:
                # Every table and figure is wider than a column: it spans both, in
                # a one-column section of its own (paper_format.span).
                first = before.getnext() if before is not None else body[0]
                if first is not p:
                    paper_format.span(d, first, p.getprevious())
            start = len(full) - len(text)
            rest = text[len(marker):]
            desc = BLOCK_DESCRIPTIONS.get(bid, "")
            if rest.strip() in ("", desc):
                p.getparent().remove(p)
                break
            cut = start + len(marker)
            if rest.lstrip().startswith(desc):
                cut += len(rest) - len(rest.lstrip()) + len(desc)
            else:
                print(f"warning: the text after {marker} is not the skeleton's description; "
                      "only the marker was removed, and the rest is left for the author",
                      file=sys.stderr)
            after = full[cut:]
            cut += len(after) - len(after.lstrip())
            _delete_span(p, 0, cut)
            kept.append(bid)
            break
    return inserted, left, kept


def _insert_caption(d, placeholder_p, path: Path, values: dict[str, str],
                    serial: list[int]) -> None:
    """A figure caption from its «key» template: in the IEEE template's form,
    'Figure n.' in the Figure Caption style (8 pt, centred), with the drafts' section
    numbers written as the template numbers them; else 'Fig. n.' in bold."""
    from scripts import paper_format  # noqa: PLC0415
    caption = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    if not caption:
        return
    m = re.match(r"(Fig\.\s*\d+)\.\s*(.*)", caption, re.S)
    head, rest = (m.group(1), m.group(2)) if m else ("", caption)
    if _style(d, paper_format.FIGURE_CAPTION):
        cap = d.add_paragraph(style=paper_format.FIGURE_CAPTION)
        cap.add_run((paper_format.figure_label(head) + ". " if head else "")
                    + paper_format.ieee_labels(rest))
    else:
        cap = d.add_paragraph(style=_style(d, "Body Text"))
        if head:
            cap.add_run(head + ".").bold = True
        cap.add_run((" " if head else "") + rest)
    _replace_in_paragraph(cap._p, values, serial)
    placeholder_p.addprevious(cap._p)


def _insert_figure(d, placeholder_p, png: Path, caption: Path, values: dict[str, str],
                   serial: list[int], width_in: float | None = None,
                   space_before_pt: float = 0) -> None:
    """Fig. 1 (or Fig. 3): the picture, FIG1_WIDTH_IN (or `width_in`) wide and
    centred in a paragraph of its own kept with the caption, `space_before_pt`
    below the text above it, then the caption."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: PLC0415
    from docx.shared import Inches, Pt  # noqa: PLC0415
    pic = d.add_paragraph(style=_style(d, "Body Text"))
    pic.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf = pic.paragraph_format
    pf.space_before, pf.space_after = Pt(space_before_pt), Pt(0)
    pf.left_indent = pf.right_indent = pf.first_line_indent = Pt(0)
    # Single line spacing: the body's 0.95 (the IEEE template's) would clip the top
    # of an inline picture, as Word and LibreOffice lay out a proportional spacing
    # below single.
    pf.line_spacing = 1.0
    pf.keep_with_next = True
    shape = pic.add_run().add_picture(str(png), width=Inches(width_in or FIG1_WIDTH_IN))
    # No distance from the text around it: python-docx writes none, and LibreOffice
    # then offsets the picture 0.125 in to the right, past the right margin (ICCIT
    # compliance check of 2026-10-25).
    for side in ("T", "B", "L", "R"):
        shape._inline.set(f"dist{side}", "0")
    placeholder_p.addprevious(pic._p)
    _insert_caption(d, placeholder_p, caption, values, serial)


# The children of w:settings that follow w:doNotAutoCompressPictures in the schema's
# sequence (ECMA-376 CT_Settings). The sequence's elements are in the w, m and sl
# namespaces; Word writes its extension elements (w14:docId, w15:docId, ...) after
# them, and ignores their place in the sequence.
_AFTER_NO_COMPRESS = ("w:forceUpgrade", "w:captions", "w:readModeInkLockDown",
                      "w:smartTagType", "sl:schemaLibrary", "w:shapeDefaults",
                      "w:doNotEmbedSmartTags", "w:decimalSymbol", "w:listSeparator")


def _keep_pictures_uncompressed(d) -> None:
    """Mark the filled document "Do not compress images in file" (Word: File >
    Options > Advanced > Image Size and Quality; w:doNotAutoCompressPictures in
    word/settings.xml), so that Word does not compress Fig. 1, put in at 600 dpi
    or more (paper/VENUE_FACTS.md), to its default resolution. The setting is per
    document, and the template does not carry it. Whether the exported PDF keeps
    600 dpi is checked at PAP9 with `pdfimages -list`. Idempotent."""
    settings = d.settings.element
    tag = _qn("w:doNotAutoCompressPictures")
    if settings.find(tag) is not None:
        return
    after = {_qn(t) for t in _AFTER_NO_COMPRESS}
    sequence_ns = tuple(_qn(p + ":x")[:-1] for p in ("w", "m", "sl"))
    el = settings.makeelement(tag, {})
    last = None
    for child in settings:
        name = child.tag if isinstance(child.tag, str) else ""
        if name in after:               # the first successor: it goes just before
            child.addprevious(el)
            return
        if name.startswith(sequence_ns):
            last = child
    # No successor: after the last element of the sequence, before any extension.
    if last is None:
        settings.insert(0, el)
    else:
        last.addnext(el)


def _insert_listing(d, placeholder_p, out_dir: Path, values: dict[str, str],
                    serial: list[int]) -> None:
    """Fig. 2: fig2_listing.txt as a monospaced block, one paragraph per line,
    each non-empty line a tagged value (its key's text, checked by _fig2_lines),
    then the caption. The writing fallback's short listing (every line starting
    with its label column) wraps under a hanging indent the width of that
    column, so a wrapped line continues under its text, not under the label."""
    from docx.oxml import OxmlElement  # noqa: PLC0415
    from docx.shared import Pt  # noqa: PLC0415
    lines = _fig2_lines(out_dir, values)
    labels = {x.ljust(FIG2_LABEL_W) for x in ("", *FIG2_LABELS)}
    short = all(t[:FIG2_LABEL_W] in labels for k, t in lines if k)
    from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: PLC0415
    paras: list[tuple[Any, str]] = []
    for i, (key, _) in enumerate(lines):
        para = d.add_paragraph(style=_style(d, "Body Text"))
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT     # a listing is never justified
        pf = para.paragraph_format
        pf.space_before = pf.space_after = Pt(0)
        pf.first_line_indent = Pt(0)
        if short:
            # The text sits FIG2_BAND_PAD_PT inside the column on both sides, so the
            # band's left and right borders (_shade_paragraph), which Word and
            # LibreOffice draw outside the indent, stay within the margins
            # (verification of 2026-10-25: they reached 4.5 pt into both).
            label_w = FIG2_LABEL_W * FIG2_PT * FIG2_ADVANCE
            pf.left_indent = Pt(FIG2_BAND_PAD_PT + label_w)
            pf.first_line_indent = Pt(-label_w)
            pf.right_indent = Pt(FIG2_BAND_PAD_PT)
        pf.keep_with_next = i < len(lines) - 1
        if key:
            r = para.add_run(f"«{key}»")
            r.font.name = FIG2_FONT
            r.font.size = Pt(FIG2_PT)
            fonts = r._r.get_or_add_rPr().find(_qn("w:rFonts"))
            if fonts is None:
                fonts = OxmlElement("w:rFonts")
                r._r.get_or_add_rPr().insert(0, fonts)
            for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
                fonts.set(_qn(attr), FIG2_FONT)
            _replace_in_paragraph(para._p, values, serial)
        placeholder_p.addprevious(para._p)
        paras.append((para, values.get(key, "") if key else ""))
    if short:
        _style_listing(paras)
    _insert_caption(d, placeholder_p, out_dir / "fig2_caption.txt", values, serial)


# The listing's look (2026-10-21, the author's request "Nhìn rối và không thuyết
# phục"), in Fig. 1's colour code: what C observes (SENT, RECEIVED) on C's tint,
# the local rendering (LOCAL) on T's, with a dashed rule where the text stops
# crossing; the labels bold in their side's colour; slot ids and fact references
# in the orange of what crosses M; on the LOCAL line, the values that took the
# place of a fact reference in bold green. Only formatting changes: each line is
# still one tagged value whose text is the key's, so check_paper_numbers.py
# reads the same text as before.
FIG2_TINT = {"C": "FDF2E9", "T": "EFF6F1"}
FIG2_INK = {"C": "C2571A", "T": "2E7D4F"}
FIG2_RULE = "C62828"
FIG2_SIDE = {"SENT": "C", "RECEIVED": "C", "LOCAL": "T"}


def _listing_pieces(text: str, side: str, resolved: list[tuple[int, int]]
                    ) -> list[tuple[str, dict[str, Any]]]:
    """(text, format) pieces of one listing line: the label column, then the
    content with its tokens and resolved values marked."""
    label, content = text[:FIG2_LABEL_W], text[FIG2_LABEL_W:]
    pieces: list[tuple[str, dict[str, Any]]] = []
    if label.strip():
        pieces.append((label, {"bold": True, "color": FIG2_INK[side]}))
    else:
        pieces.append((label, {}))
    marks: list[tuple[int, int, dict[str, Any]]] = [
        (m.start(), m.end(), {"color": FIG2_INK["C"]}) for m in _TOKEN.finditer(content)]
    marks += [(a, b, {"bold": True, "color": FIG2_INK["T"]}) for a, b in resolved]
    marks.sort()
    pos = 0
    for a, b, fmt in marks:
        if a < pos:
            continue
        if a > pos:
            pieces.append((content[pos:a], {}))
        pieces.append((content[a:b], fmt))
        pos = b
    if pos < len(content):
        pieces.append((content[pos:], {}))
    return [(t, f) for t, f in pieces if t]


def _resolved_spans(received: str, local: str) -> list[tuple[int, int]]:
    """The spans of the LOCAL content that took the place of a slot id or fact
    reference in the RECEIVED content it renders: the received text's literal
    parts must match in order, and each token's place is what lies between them.
    None when the two do not line up (a line cut at a different point)."""
    parts = _TOKEN.split(received)
    if len(parts) < 2:
        return []
    rx = "(.+?)".join(re.escape(x) for x in parts[:-1]) + "(.+?)" + re.escape(parts[-1])
    m = re.fullmatch(rx, local, re.S)
    if not m:
        return []
    return [m.span(i) for i in range(1, (m.lastindex or 0) + 1)]


def _restyle_value_run(p_el, pieces: list[tuple[str, dict[str, Any]]]) -> bool:
    """Replace the one run inside the paragraph's value bookmark by one run per
    piece (same rPr, plus the piece's bold and colour), inside the same bookmark,
    so the tagged text is unchanged. False if the paragraph is not that shape."""
    from docx.oxml import OxmlElement  # noqa: PLC0415
    bs = p_el.find(_qn("w:bookmarkStart"))
    if bs is None:
        return False
    runs = []
    for el in bs.itersiblings():
        if el.tag == _qn("w:bookmarkEnd"):
            break
        if el.tag == _qn("w:r"):
            runs.append(el)
    if len(runs) != 1 or "".join(t for t, _ in pieces) != "".join(
            t.text or "" for t in runs[0].iter(_qn("w:t"))):
        return False
    run = runs[0]
    anchor = run
    for text, fmt in pieces:
        r = copy.deepcopy(run)
        for ch in list(r):
            if ch.tag != _qn("w:rPr"):
                r.remove(ch)
        rpr = r.find(_qn("w:rPr"))
        if rpr is None:
            rpr = OxmlElement("w:rPr")
            r.insert(0, rpr)
        if fmt.get("bold"):
            rpr.append(OxmlElement("w:b"))
        if fmt.get("color"):
            c = OxmlElement("w:color")
            c.set(_qn("w:val"), fmt["color"])
            rpr.append(c)
        t = OxmlElement("w:t")
        _set_text(t, text)
        r.append(t)
        anchor.addnext(r)
        anchor = r
    run.getparent().remove(run)
    return True


def _shade_paragraph(para, fill: str, top_rule: bool = False) -> None:
    from docx.oxml import OxmlElement  # noqa: PLC0415
    ppr = para._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    # The rule where the text stops crossing (dashed, the boundary's red), and a
    # left and right border in the band's own colour, which pads the text from the
    # band's edges.
    # Every band paragraph carries the same three edges (a top edge in the band's
    # colour where no rule is drawn), so LibreOffice and Word place the left edge of
    # both bands at the same point.
    edges = [("w:top", "dashSmallGap", "6", "1", FIG2_RULE) if top_rule
             else ("w:top", "single", "6", "1", fill)]
    edges += [("w:left", "single", "4", "4", fill), ("w:right", "single", "4", "4", fill)]
    for tag, val, sz, space, color in edges:
        e = OxmlElement(tag)
        for k, v in (("w:val", val), ("w:sz", sz), ("w:space", space), ("w:color", color)):
            e.set(_qn(k), v)
        bdr.append(e)
    ppr.append(bdr)
    shd = OxmlElement("w:shd")
    for k, v in (("w:val", "clear"), ("w:color", "auto"), ("w:fill", fill)):
        shd.set(_qn(k), v)
    ppr.append(shd)


def _style_listing(paras: list[tuple[Any, str]]) -> None:
    """The short listing's colour code (see FIG2_TINT): a band per side, the
    labels, the tokens and the resolved values."""
    from docx.shared import Pt  # noqa: PLC0415
    side, label = "C", ""
    received = ""
    rows = []
    for para, text in paras:
        if text and text[:FIG2_LABEL_W].strip():
            label = text[:FIG2_LABEL_W].strip()
            side = FIG2_SIDE.get(label, side)
        if label == "RECEIVED" and text:
            received = text[FIG2_LABEL_W:]
        rows.append((para, text, side, label))
    first_t = True
    for i, (para, text, side, label) in enumerate(rows):
        if not text:
            continue
        resolved = (_resolved_spans(received, text[FIG2_LABEL_W:])
                    if label == "LOCAL" and received else [])
        _restyle_value_run(para._p, _listing_pieces(text, side, resolved))
        _shade_paragraph(para, FIG2_TINT[side], top_rule=side == "T" and first_t)
        if side == "T":
            first_t = False
        pf = para.paragraph_format
        if i == 0:
            pf.space_before = Pt(2)
        if i == len(rows) - 1:
            pf.space_after = Pt(2)


def _add_banner(d, text: str) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: PLC0415
    from docx.shared import Pt, RGBColor  # noqa: PLC0415
    for i, sec in enumerate(d.sections):
        heads = [sec.header]
        if sec.different_first_page_header_footer:
            heads.append(sec.first_page_header)
        if d.settings.odd_and_even_pages_header_footer:
            heads.append(sec.even_page_header)
        for h in heads:
            # A later section's header that is linked to the previous one inherits
            # the banner with the running head (paper_format.paginate); unlinking it
            # would give it a header of its own without the running head.
            if i and h.is_linked_to_previous:
                continue
            h.is_linked_to_previous = False
            p = h.paragraphs[0] if h.paragraphs and not h.paragraphs[0].text else \
                h.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(text)
            r.bold = True
            r.font.size = Pt(12)
            r.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
    body = d.element.body
    first = next(iter(body.iterchildren(_qn("w:p"))), None)
    title = d.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run(text)
    r.bold = True
    r.font.size = Pt(14)
    r.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
    if first is not None:
        first.addprevious(title._p)


# ------------------------------------------------------------ tables.docx

def _save_deterministic(d, path: Path) -> None:
    """Save with every zip entry dated 1980-01-01, so the same inputs give the same
    bytes (PAP5b: regenerated byte-identically from the frozen JSON)."""
    import io  # noqa: PLC0415
    import zipfile  # noqa: PLC0415
    buf = io.BytesIO()
    d.save(buf)
    buf.seek(0)
    out = io.BytesIO()
    with zipfile.ZipFile(buf) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            zi = zipfile.ZipInfo(info.filename, date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zout.writestr(zi, zin.read(info.filename))
    path.write_bytes(out.getvalue())


def _style(d, name: str) -> str | None:
    return name if any(s.name == name for s in d.styles) else None


@dataclass
class TableSpec:
    bid: str
    label: str
    caption: str
    header: list[str]
    # a tuple is a panel row, ("panel", text), across every column; a wide row,
    # ("wide", label, text): the label, then one cell across the other columns; or
    # a header row inside the table, ("head", cell, ...): one bold cell per column
    # with a rule under it, for a row block whose columns differ from the header's
    rows: list[list[str] | tuple[str, ...]]
    notes: list[str] = field(default_factory=list)
    widths: list[float] | None = None
    # the columns of a second table, one a ("panel", ...) row followed by a
    # ("head", ...) row starts (write_tables_docx); `widths` when None
    widths2: list[float] | None = None
    # a column whose cells are outcomes: shaded and set bold by OUTCOME_TINTS
    # (2026-10-21, the hypotheses table)
    shade_col: int | None = None
    # the manuscript's hypotheses table (2026-10-27): a column whose leading tag
    # (T1_TAGS) is italic, a column whose leading «key» is bold, and a grey hairline
    # under each data row that another data row follows
    tag_col: int | None = None
    lead_bold_col: int | None = None
    row_rules: bool = False


def _set_borders(tbl, top: bool = True) -> None:
    """A top rule (unless `top` is False: a table continuing the one above it), a
    bottom rule and a rule under the header; no verticals."""
    from docx.oxml import OxmlElement  # noqa: PLC0415
    tbl_pr = tbl._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge, val in (("top", "single" if top else "nil"), ("left", "nil"),
                      ("bottom", "single"),
                      ("right", "nil"), ("insideH", "nil"), ("insideV", "nil")):
        e = OxmlElement(f"w:{edge}")
        e.set(_qn("w:val"), val)
        if val == "single":
            e.set(_qn("w:sz"), "8")
            e.set(_qn("w:space"), "0")
            e.set(_qn("w:color"), "000000")
        borders.append(e)
    tbl_pr.append(borders)


def _cell_bottom_rule(cell, size: str = "4", color: str = "000000") -> None:
    from docx.oxml import OxmlElement  # noqa: PLC0415
    tc_pr = cell._tc.get_or_add_tcPr()
    b = OxmlElement("w:tcBorders")
    e = OxmlElement("w:bottom")
    for k, v in (("w:val", "single"), ("w:sz", size), ("w:space", "0"), ("w:color", color)):
        e.set(_qn(k), v)
    b.append(e)
    tc_pr.append(b)


def _write_cell(d, cell, text: str, *, bold: bool = False, italic: bool = False) -> None:
    _write_segments(d, cell, [(text, bold, italic)])


def _write_segments(d, cell, segments: list[tuple[str, bool, bool]]) -> None:
    """A cell's text as runs of (text, bold, italic), each line break a break."""
    from docx.shared import Pt  # noqa: PLC0415
    para = cell.paragraphs[0]
    st = _style(d, "Table Paragraph")
    if st:
        para.style = d.styles[st]
    for text, bold, italic in segments:
        lines = text.split("\n")
        for i, line in enumerate(lines):
            r = para.add_run(line)
            r.font.size = Pt(8)
            r.bold = bold
            r.italic = italic
            if i < len(lines) - 1:
                r.add_break()


def _lead_segments(text: str, *, tag: bool = False, bold_key: bool = False
                   ) -> list[tuple[str, bool, bool]]:
    """A cell whose leading tag (T1_TAGS) is italic, or whose leading «key» is bold."""
    if tag:
        for t in T1_TAGS:
            if text.startswith(t):
                return [(t, False, True), (text[len(t):], False, False)]
    if bold_key and (m := re.match(r"«[^»]+»", text)):
        return [(m.group(0), True, False), (text[m.end():], False, False)]
    return [(text, False, False)]


# The hypotheses table's outcome cells (2026-10-21): what an outcome is, at a
# glance. A cell that names several outcomes takes the least favourable one's.
# The tints mark the outcome, not a benefit (H2 and H4-D' hold as costs to r1), so
# "holds" is a neutral blue, not a green (review of 2026-10-21).
# Since 2026-10-26 (simulated review of that day, R4(5); the author's request "đồng ý với đề
# xuất, chỉnh sửa toàn bộ theo yêu cầu"; written by the AI assistant): an outcome decided under a
# rule registered after the pilot (its cell says "post-pilot": H2's floor rule, H4-D′) takes a
# light amber, apart from H3's pre-pilot "holds"; a less favourable outcome in the cell still wins.
OUTCOME_TINTS = (("fails", "F6D5D1"), ("not testable", "E8E8E4"), ("post-pilot", "F2E3C0"),
                 ("holds", "DCE7F3"))


def _outcome_tint(text: str) -> str | None:
    for word, tint in OUTCOME_TINTS:
        if word in text:
            return tint
    return None


def _shade_cell(cell, fill: str | None) -> None:
    if not fill:
        return
    from docx.oxml import OxmlElement  # noqa: PLC0415
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    for k, v in (("w:val", "clear"), ("w:color", "auto"), ("w:fill", fill)):
        shd.set(_qn(k), v)
    tc_pr.append(shd)


def _add_bookmark(para, name: str, bid: int) -> None:
    from docx.oxml import OxmlElement  # noqa: PLC0415
    s = OxmlElement("w:bookmarkStart")
    s.set(_qn("w:id"), str(bid))
    s.set(_qn("w:name"), name)
    e = OxmlElement("w:bookmarkEnd")
    e.set(_qn("w:id"), str(bid))
    para._p.insert(0 if para._p.pPr is None else 1, s)
    para._p.append(e)


def write_tables_docx(skeleton: Path, specs: list[TableSpec], out: Path,
                      values: dict[str, str] | None = None) -> None:
    """tables.docx on the skeleton's own styles: its body emptied, then each table
    as a bookmarked caption, the table, and its notes. Cells, captions and notes
    may hold «key» placeholders; each is replaced by its value from `values` as a
    tagged run, exactly as the fill pass writes one, so check_paper_numbers.py
    can bind every figure in a table to its key."""
    docx = _docx()
    from docx.enum.table import WD_TABLE_ALIGNMENT  # noqa: PLC0415
    from docx.enum.text import WD_LINE_SPACING  # noqa: PLC0415
    from docx.oxml import OxmlElement  # noqa: PLC0415
    from docx.shared import Inches, Pt  # noqa: PLC0415
    d = docx.Document(str(skeleton))
    body = d.element.body
    for el in list(body):
        if el.tag != _qn("w:sectPr"):
            body.remove(el)
    from scripts import paper_format  # noqa: PLC0415
    ieee = _style(d, paper_format.TABLE_CAPTION) is not None
    for n, spec in enumerate(specs, 1):
        if ieee:
            # The IEEE template: "TABLE I." and the title in small capitals, centred,
            # above the table (the skeleton's Table Caption style).
            cap = d.add_paragraph(style=paper_format.TABLE_CAPTION)
            cap.add_run(f"{paper_format.table_label(spec.label)}. "
                        + paper_format.ieee_labels(spec.caption))
        else:
            cap = d.add_paragraph(style=_style(d, "Body Text"))
            cap.add_run(spec.label + ".").bold = True
            cap.add_run(" " + spec.caption)
        cap.paragraph_format.keep_with_next = True
        _add_bookmark(cap, f"pap_{spec.bid}", 9000 + n)
        ncol = len(spec.header)

        def _repeat(row) -> None:
            th = OxmlElement("w:tblHeader")
            th.set(_qn("w:val"), "true")
            row._tr.get_or_add_trPr().append(th)

        def _new_table(cols: int, top_rule: bool = True):
            tb = d.add_table(rows=0, cols=cols)
            tb.alignment = WD_TABLE_ALIGNMENT.CENTER
            _set_borders(tb, top=top_rule)
            return tb

        t = _new_table(ncol)
        tables = [t]
        hdr = t.add_row()
        _repeat(hdr)
        for c, text in zip(hdr.cells, spec.header, strict=True):
            _write_cell(d, c, text, bold=True)
            _cell_bottom_rule(c)
        rows = list(spec.rows)
        for i, row in enumerate(rows):
            nxt = rows[i + 1] if i + 1 < len(rows) else None
            block = (isinstance(row, tuple) and row[0] == "panel"
                     and isinstance(nxt, tuple) and nxt[0] == "head")
            if block:
                ncol = len(nxt) - 1      # the second table's columns are its own
                # A panel row followed by its own header row starts a second table
                # under the same caption, whose two rows repeat on a new page in
                # place of the first table's header, which would otherwise repeat
                # above them with other columns' names (re-review of 2026-10-18,
                # N2: "RBA" above "Slots advertised"). A one-point paragraph keeps
                # Word from merging the two; the second table has no top rule, the
                # first table's bottom rule separating them.
                gap = d.add_paragraph()
                gap.paragraph_format.space_before = Pt(0)
                gap.paragraph_format.space_after = Pt(0)
                gap.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
                gap.paragraph_format.line_spacing = Pt(1)
                gap.paragraph_format.keep_with_next = True
                t = _new_table(ncol, top_rule=False)
                tables.append(t)
            r = t.add_row()
            if block or (isinstance(row, tuple) and row[0] == "head"
                         and len(tables) > 1 and len(t.rows) == 2):
                _repeat(r)
            # A row never breaks across pages, so a cell's value is never split
            # ("28.7 [20.0–" / "37.0]"; simulated review of 2026-10-18).
            r._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
            if isinstance(row, tuple) and row[0] == "head":
                if len(row) - 1 != ncol:
                    raise ValueError(f"{spec.label}: head row of {len(row) - 1} cells, "
                                     f"header has {ncol}")
                for c, text in zip(r.cells, row[1:], strict=True):
                    _write_cell(d, c, text, bold=True)
                    _cell_bottom_rule(c)
                continue
            if isinstance(row, tuple) and row[0] == "wide":
                _write_cell(d, r.cells[0], row[1])
                merged = r.cells[1].merge(r.cells[-1]) if ncol > 2 else r.cells[1]
                _write_cell(d, merged, row[2])
                continue
            if isinstance(row, tuple):
                merged = r.cells[0].merge(r.cells[-1])
                _write_cell(d, merged, row[1], italic=True)
                continue
            if len(row) != ncol:
                raise ValueError(f"{spec.label}: row of {len(row)} cells, header has {ncol}")
            for j, (c, text) in enumerate(zip(r.cells, row, strict=True)):
                if j == spec.shade_col:
                    _write_cell(d, c, text, bold=True)
                    _shade_cell(c, _outcome_tint(PLACEHOLDER_RE.sub(
                        lambda m: (values or {}).get(m.group(1), NA), text)))
                elif j in (spec.tag_col, spec.lead_bold_col):
                    _write_segments(d, c, _lead_segments(
                        text, tag=j == spec.tag_col, bold_key=j == spec.lead_bold_col))
                else:
                    _write_cell(d, c, text)
            if spec.row_rules and isinstance(nxt, list):
                for c in r.cells:
                    _cell_bottom_rule(c, size="2", color="A6A6A6")
        if spec.widths:
            for n_tb, tb in enumerate(tables):
                widths = (spec.widths2 or spec.widths) if n_tb else spec.widths
                if ieee:
                    # A table spans both columns (paper_format.span): its columns
                    # grow in proportion to the template's text width.
                    scale = paper_format.TEXT_WIDTH_IN / sum(widths)
                    widths = [w * scale for w in widths]
                tb.autofit = False
                for gc, w in zip(tb._tbl.tblGrid.iter(_qn("w:gridCol")), widths,
                                 strict=False):
                    gc.set(_qn("w:w"), str(int(w * 1440)))      # twentieths of a point
                for row in tb.rows:
                    for c, w in zip(row.cells, widths, strict=False):
                        c.width = Inches(w)
        # Every table is shorter than a page: each row is kept with the next, so a
        # table and its second part move to a page together instead of breaking
        # over two (2026-10-19; the hypotheses table had split before its last row).
        last = tables[-1].rows[-1]._tr
        for tb in tables:
            for row in tb.rows:
                if row._tr is last:
                    continue
                for cell in row.cells:
                    for para in cell.paragraphs:
                        para.paragraph_format.keep_with_next = True
        for note in spec.notes:
            if ieee:
                np_ = d.add_paragraph(style=paper_format.TABLE_NOTE)
                np_.add_run(paper_format.ieee_labels(note))
            else:
                np_ = d.add_paragraph(style=_style(d, "Body Text"))
                r = np_.add_run(note)
                r.font.size = Pt(8)
    paras = list(body.iter(_qn("w:p")))
    wanted = {k for p in paras for k in PLACEHOLDER_RE.findall(_para_text(p))}
    missing = sorted(wanted - set(values or {}))
    if missing:
        raise SystemExit(f"tables reference keys with no value: {', '.join(missing)}")
    serial = [0]
    for p in paras:
        _replace_in_paragraph(p, values or {}, serial)
    _renumber_value_bookmarks([d.element])
    out.parent.mkdir(parents=True, exist_ok=True)
    _save_deterministic(d, out)


# ------------------------------------------------------------ table content



# Table 1's Mechanism cells in words, one per property of THREAT_MODEL.md §4
# (review 2026-10-10, MR10, change TAB-I): the module names they replace meant
# nothing to a reader without the repository. Each is a short gloss of the
# document's own mechanism cell (THREAT_MODEL.md §4) and of §4 of the paper; a
# P-row without one stops the build, so a new property cannot reach the table
# without its mechanism.
T1_MECHANISM = {
    "P1": "No default route out of T; only M is dual-homed",
    "P2": "Salted 5-8-gram shingles in a Bloom filter, checked per stream",
    "P3": "Per-session canary tokens, matched exactly",
    "P4": "No egress until the filter is sealed",
    "P5": "Source check, then a render with inert sentinels",
    "P6": "Drafter scrubs and counts; reintegrator refuses",
    "P7": "Grounder over a hashed evidence bank",
    "P8": "Audit record written before forwarding",
    "P9": "Table facts via the header lexicon; absences written, never guessed",
}
# The threat model's internal names, in the paper's terms, in the Property
# cells (TAB-I; review minor 4): the network name is a compose identifier, and
# C_user is the threat model's symbol for what the paper calls the corpus. P2's
# threshold is written as the text writes it everywhere else, "5-word", the form
# check_paper_numbers.py admits (copyedit 2026-10-15); the terms apply in order,
# so the C_user term comes first.
T1_PROPERTY_TERMS = (("privdeep-internal", "T's internal network"), ("C_user", "the corpus"),
                     ("run of five or more words of the corpus",
                      "5-word or longer run of corpus words"))


def _t1_property(prop: str) -> str:
    out = _md_plain(_first_clause(prop))
    for old, new in T1_PROPERTY_TERMS:
        out = out.replace(old, new)
    return out


def table1_from_threat_model(tm_path: Path) -> TableSpec:
    """Table 1, condensed mechanically from THREAT_MODEL.md §4, so it never drifts
    from the file the drift test pins: the property up to its first colon or
    semicolon (with the threat model's internal names in the paper's terms,
    T1_PROPERTY_TERMS), the mechanism in words (T1_MECHANISM, one per P-row), the
    bold lead of the grade (with the qualifier that bounds a one-word lead,
    _grade), and the tests and scripts that pin it (from the grade text and the
    src citation)."""
    text = tm_path.read_text(encoding="utf-8")
    rows = []
    for line in text.splitlines():
        m = re.match(r"^\|\s*(P\d+)\s*\|(.*)\|\s*$", line)
        if not m:
            continue
        cells = [c.strip() for c in _split_md_row(m.group(2))]
        if len(cells) < 3:
            continue
        prop, mech, grade = cells[0], cells[1], cells[2]
        src = " ".join(re.findall(r"<!--\s*src:(.*?)-->", grade))
        grade_nc = re.sub(r"<!--.*?-->", "", grade)
        g = _grade(grade_nc)
        pinned = _pinned(grade_nc + " " + mech, src)
        if pinned != "—" and re.search(r"\bnot exercised\b", g, re.I):
            pinned += " (unit tests; not exercised)"
        pid = m.group(1)
        if pid not in T1_MECHANISM:
            raise SystemExit(f"{tm_path}: property {pid} has no mechanism in words "
                             "(make_paper_tables.T1_MECHANISM); add one before the table "
                             f"shows it (its document cell: {_mechanism(mech)})")
        rows.append([pid, _t1_property(prop), T1_MECHANISM[pid], g, pinned])
    if not rows:
        raise SystemExit(f"{tm_path}: no P-rows found in the §4 table")
    rows.append(("panel", "Tests beyond the enforced properties"))
    rows += _table1_tests(text)
    index = _stem_index(_REPO)
    for r in rows:
        if isinstance(r, list):
            r[4] = _as_stems(r[4], index)
    return TableSpec(
        "props", "Table 1",
        "Enforced properties: mechanism, strength grade, and the test or script that "
        "pins each.",
        ["", "Property", "Mechanism", "Grade", "Pinned by"], rows,
        notes=["Grades are quoted from the threat model; a property graded 'built, not "
               "exercised' is not exercised by the reported runs. Tests and scripts "
               "are named by file stem, each unique in the artifact."],
        # "Pinned by" holds test_threat_model_claims on one line (re-review of
        # 2026-10-18, N24: it broke as "test_threat_model_claim" / "s").
        widths=[0.35, 1.85, 1.6, 1.2, 1.3])


# Table 1's "Pinned by" column names each test or script by its file stem, not
# its path (the author's approval of 2026-10-01, PRIVDEEP_COMPLETION_PLAN.md
# Part D AD32). A stem is shown only while it names exactly one .py or .sh file
# in the repository, so a second file with the same stem stops the build rather
# than make the cell ambiguous. Top-level directories that hold data or build
# output, not code, are not searched, nor are hidden ones (.git, .venv, a
# checkout's worktrees) or caches.
_STEM_SKIP_TOP = frozenset({"build", "eval", "corpus", "data"})
_STEM_SKIP_ANY = frozenset({"__pycache__", "node_modules"})
_STEM_FILE = re.compile(r"[\w./-]+\.(?:py|sh)\b")


def _stem_index(root: Path) -> dict[str, list[str]]:
    """File stem -> the root-relative paths of the .py and .sh files with it."""
    out: dict[str, list[str]] = {}
    for here, dirs, files in os.walk(root):
        top = Path(here) == root
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in _STEM_SKIP_ANY
                         and not (top and d in _STEM_SKIP_TOP))
        for f in sorted(files):
            p = Path(here, f)
            if p.suffix in (".py", ".sh"):
                out.setdefault(p.stem, []).append(p.relative_to(root).as_posix())
    return out


def _as_stems(cell: str, index: dict[str, list[str]]) -> str:
    """A Pinned-by cell with each file path replaced by its stem; every other word
    ('(unit tests; not exercised)') stays. Refuses a path whose stem does not name
    that one file."""
    def one(m: re.Match[str]) -> str:
        path = m.group(0)
        stem = Path(path).stem
        if index.get(stem) != [path]:
            raise SystemExit(f"Table 1 names {path} by its stem {stem!r}, which must name "
                             "exactly one .py or .sh file in the repository; files with "
                             f"that stem: {', '.join(index.get(stem, [])) or 'none'}")
        return stem
    return _STEM_FILE.sub(one, cell)


# The two tests Table 1 names beside P1-P9 (plan Part B §8: "including MX6 and
# the invariance test"). Each is found in THREAT_MODEL.md §2 by the sentence
# that grades it, and its test file is the backticked path in the same
# paragraph, so the row fails the build rather than drift from the document.
# The id cell is what the paper shows: MX6 is a plan identifier and "second
# threat source" the threat model's wording, neither of which the paper
# defines, so the MX6 row shows no id and names itself as the
# adversarial-drafter test that Sections III and VI-A cite (review 2026-10-09,
# T1-mx6-label). Property and mechanism are in words, as the P-rows' are since
# the change set of 2026-10-10 (TAB-I); the G2 property keeps §2's caveat as
# "unless the rounded character count changes", and the build still checks that
# §2 states it ("Quantisation is not invariance").
_T1_TESTS = (
    # (id in THREAT_MODEL.md, id cell, property, mechanism, grade sentence(s) in §2,
    #  grade cell, paragraph anchor)
    ("MX6", "", "Adversarial-drafter test: a draft that puts a private value in a "
                "transport position has its section refused, and no private value reaches "
                "the report",
     "Scripted drafter in the running r1 pipeline",
     "MX6 is defence in depth, not a claim about the evaluated runs.",
     "Defence in depth, not a claim about the evaluated runs",
     "The pipeline-level adversarial-drafter test MX6"),
    ("G2", "G2", "Planner and drafter requests are equal under the tested permutations of "
                 "values and referents, up to slot-id renaming and listing order, unless the "
                 "rounded character count changes",
     "Payload of typed relations, slot ids and coarse statistics",
     ("This is a construction property of the core-built payload",
      "with the character count quantised to 1,000",
      "Quantisation is not invariance"),
     "Construction property of the core-built payload",
     "**G2 attribute inference**"),
)


def _table1_tests(text: str) -> list[list[str]]:
    sec2 = text[text.index("## 2. Adversary"):text.index("## 3. ")]
    rows = []
    flat = re.sub(r"\s+", " ", sec2)
    for tid, shown, prop, mech, sentences, grade, anchor in _T1_TESTS:
        i = sec2.find(anchor)
        for sentence in (sentences,) if isinstance(sentences, str) else sentences:
            if i < 0 or re.sub(r"\s+", " ", sentence) not in flat:
                raise SystemExit(f"THREAT_MODEL.md §2 no longer states the {tid} test as "
                                 f"Table 1 quotes it ({anchor!r}, {sentence!r})")
        para = sec2[i:].split("\n\n")[0].split("\n- ")[0]
        tests = [c for c in re.findall(r"`([^`]+\.py)`", para)
                 if re.search(r"(^|/)tests?/", c)]
        if not tests:
            raise SystemExit(f"THREAT_MODEL.md §2: no test file named for {tid}")
        rows.append([shown, prop, mech, grade, tests[0]])
    return rows


def _split_md_row(s: str) -> list[str]:
    out, cur, code = [], [], False
    for ch in s:
        if ch == "`":
            code = not code
        if ch == "|" and not code:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def _first_clause(s: str) -> str:
    s = re.sub(r"<!--.*?-->", "", s)
    depth, code = 0, False
    for i, ch in enumerate(s):
        if ch == "`":
            code = not code
        elif ch == "(" and not code:
            depth += 1
        elif ch == ")" and not code:
            depth -= 1
        elif ch in ":;" and depth == 0 and not code:
            return s[:i].strip()
    return s.strip()


def _md_plain(s: str) -> str:
    s = re.sub(r"\$C_\{user\}\$", "C_user", s)
    s = re.sub(r"\$([^$]*)\$", r"\1", s)
    s = s.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", s).strip()


def _mechanism(mech: str) -> str:
    names = []
    for code in re.findall(r"`([^`]+)`", mech):
        c = code.strip()
        if re.fullmatch(r"[A-Za-z0-9_./-]+", c) and ("/" in c or "." in c) \
                and not c.startswith(".") and not re.search(r"\.\w+\(", c):
            short = c
            if short not in names:
                names.append(short)
    if names:
        return "; ".join(names)
    return _md_plain(_first_clause(mech))


def _grade(grade: str) -> str:
    """The grade's bold lead. A one-word lead that does not end its sentence
    ('**Deterministic**, for the exact token'; '**Deterministic** given the
    extraction: ...') keeps the qualifier after it, up to the first colon,
    semicolon or full stop, since that qualifier is what bounds the grade
    (review 2026-10-09, T1-grades-truncated: P3 and P9). A longer lead carries
    its own bound, and what follows it is elaboration (P2's section reference,
    P8's test path), so it stands alone, as does a lead that ends its sentence."""
    m = re.search(r"\*\*(.+?)\*\*", grade)
    if not m:
        return _md_plain(_first_clause(grade)).rstrip(".")
    g = m.group(1)
    if len(g.split()) == 1 and not g.rstrip().endswith((".", ":", ";", "!", "?")):
        tail = re.split(r"[:;]|\.(?=\s|$)", grade[m.end():], maxsplit=1)[0]
        g += tail.rstrip()
    return _md_plain(g).rstrip(".")


def _pinned(text: str, src: str) -> str:
    """The tests (and the partition script) a row names. A measurement script
    (scripts/*.py) records a rate, it does not pin the property, so it is not
    listed."""
    found: list[str] = []
    for code in re.findall(r"`([^`]+)`", text) + re.findall(r"([\w./-]+\.(?:py|sh))", src):
        c = code.strip()
        if re.search(r"(^|/)(tests?/|test_)|\.sh$", c) and c not in found:
            found.append(c)
    return "; ".join(found) if found else "—"


def _k(v: dict[str, str], key: str) -> str:
    """A table cell's reference to a numbers.json key: the placeholder, filled and
    tagged when tables.docx is written; n/a when the build has no such key."""
    return f"«{key}»" if key in v else NA


# Table 2's row labels for the false-positive strata and the standalone linters,
# in the paper's terms: §4.4 names "an entropy screen, a regex screen ... and
# containment", and §6.1 names the compact stratum by this row's label
# (scripts/measure_false_positives.py:32-37 builds both JSON strata from
# AbstractPayload.to_json()). An id without a label is shown as it is named,
# underscores as spaces (review 2026-10-09, T2-labels).
T2_STRATUM_LABEL = {"abstract_json": "Abstract-payload JSON",
                    "abstract_json_compact": "Compact abstract-payload JSON in one message "
                                             "string",
                    "code_snippet": "Code snippets",
                    "english_prose": "English prose",
                    "vietnamese_prose": "Vietnamese prose"}
T2_LINTER_LABEL = {"entropy": "Entropy screen", "regex": "Regex screen",
                   "shingle": "Containment"}
# The masked-document block's own column meanings, one sub-header row under its
# panel (evaluation rewrite 2026-10-15): the block's three figures per corpus sit
# in the grid's Count, Rate and interval columns, so the row says what they are.
T2_MASKDOC_HEAD = ("Corpus", "Masked documents refused", "Corpus 5-grams left after masking",
                   "Generator-written constants left")
T2_MASKDOC_WIDTHS = [1.0, 1.8, 2.1, 2.1]


def _maskdoc_note_short(v: dict[str, str], letters: list[str]) -> str:
    """Table 1(b)'s note: what the ranges run over, and a document a corpus's
    shared extraction lost to an unparsed extractor reply: with the figures
    without it (review_analyses.json, MR9b), the row shows those (marked †) and
    the note the figures with the unmasked document; without them, the note says
    the document stays unmasked (and gives the corpus's upper figures, when the
    probe says so)."""
    order = ("the shared one first" if v.get("maskdoc_shared_first") == "yes"
             else "in the probe's order")
    # The construction fact moved here from the panel heading on 2026-10-19 (the
    # captions and headings are short titles).
    out = ("(b) The sealed filter refuses any masked document that keeps a corpus 5-gram (true "
           f"by construction). Over each corpus's extractions, {order}: equal figures once, "
           "differing document counts in that order, shares and counts as min–max.")
    for L in letters:
        n = v.get(f"extraction_docs_lost_{L}", NA)
        if n in (NA, "0"):
            continue
        one = n == "1"
        what = ("one extractor reply did not parse" if one else
                f"«extraction_docs_lost_{L}» extractor replies did not parse")
        doc = "that document" if one else "those documents"
        if f"maskdoc_5gram_pct_nolost_{L}" in v and f"maskdoc_surfaces_surviving_nolost_{L}" in v:
            # The refused count has no parsed-only variant: an unmasked document is
            # refused too, and the note says so (claim-preservation review of
            # 2026-10-19, finding 4).
            counted = (f"; the refused count includes {doc}, which "
                       f"{'stays' if one else 'stay'} unmasked"
                       if v.get(f"maskdoc_lost_unmasked_{L}") == "yes" else "")
            out += (f" †Corpus {L}'s shares and counts are over its parsed documents "
                    f"({what}){counted}; with {doc}, its figures are «maskdoc_5gram_pct_{L}» "
                    f"and «maskdoc_surfaces_surviving_{L}».")
        elif v.get(f"maskdoc_lost_unmasked_{L}") == "yes":
            out += (f" On corpus {L}, {what}; {doc} {'stays' if one else 'stay'} unmasked in "
                    "its masked copy"
                    + (f" and {'gives' if one else 'give'} its upper figures"
                       if v.get(f"maskdoc_upper_from_lost_{L}") == "yes" else "") + ".")
    if v.get("maskdoc_corpora_missing", "none") != "none":
        out += " Corpora with runs and no probe: «maskdoc_corpora_missing»."
    return out


def table2(nb: Numbers) -> TableSpec:
    """Table 1 since 2026-10-19 (the author's request for readable tables): (a)
    the inputs M saw, grouped by what a refusal means: clean payloads, where any
    refusal is a false positive (the deployed chain over all strata and per
    stratum, and each screen alone), the positive control, and the runs on A-D;
    (b) the entity-masked documents per corpus, offline, as a second table under
    the same caption. Dropped from the paper (their keys stay for the artifact):
    the Rate column (k/N says it), the carry-kept row (the note says it gives the
    same count), runs with any refusal, leak-gate aborts and documents left with
    no relation."""
    v = nb.values
    strata = sorted({k[len("fp_deployed_reset_"):] for k in v
                     if k.startswith("fp_deployed_reset_") and not k.endswith(("_ci", "_rate"))
                     and k != "fp_deployed_reset"})
    # The runs and the positive control first: the reassuring rows were read
    # after the 122/500 they explain (readability review of 2026-10-19).
    # Corpus letters carry "corpus"/"corpora" (the author's request of 2026-10-19:
    # A and C also name the adversary and the cloud provider).
    rows: list[Any] = [("panel", "(a) The runs on corpora A–D, the positive control and clean "
                                  "payloads")]
    rows.append(["Egress attempts refused by M", _k(v, "op_refused_attempts"), "—"])
    rows.append(["Sections refused by the reintegrator", _k(v, "op_reintegrator"), "—"])
    # A drop is not a refusal (review 2026-10-09, T2-leakgate-cell); counted once
    # per shared extraction.
    # Counted once per extraction (claim-preservation review of 2026-10-19).
    rows.append(["Relations dropped by the leak gate, once per extraction (not a refusal)",
                 _k(v, "leak_gate_drops_total"), "—"])
    rows.append(("panel", "Positive control: private sentences, where every refusal is wanted"))
    rows.append(["Deployed chain", _k(v, "fp_poscontrol_deployed"), "—"])
    rows.append(("panel", "Clean payloads, where any refusal is a false positive"))
    rows.append(["Deployed chain, all strata (entropy and regex screens)",
                 _k(v, "fp_deployed_reset"), _k(v, "fp_deployed_reset_ci")])
    for st in strata:
        rows.append([f"  {T2_STRATUM_LABEL.get(st, st.replace('_', ' '))}",
                     _k(v, f"fp_deployed_reset_{st}"), _k(v, f"fp_deployed_reset_{st}_ci")])
    for name in sorted(k[len("fp_standalone_"):] for k in v
                       if k.startswith("fp_standalone_") and k.count("_") == 2):
        rows.append([f"{T2_LINTER_LABEL.get(name, f'{name} linter')} alone",
                     _k(v, f"fp_standalone_{name}"), _k(v, f"fp_standalone_{name}_ci")])
    letters = sorted({k.rsplit("_", 1)[1] for k in v if k.startswith("maskdoc_refused_docs_")})
    if letters:
        # The construction fact is per document (review 2026-10-09, S6-16): the
        # panel says so, and that it is offline, not a test of the runs.
        rows.append(("panel", "(b) What entity masking alone would send, offline (P2)"))
        rows.append(("head", *T2_MASKDOC_HEAD))
        for L in letters:
            nolost = (f"maskdoc_5gram_pct_nolost_{L}" in v
                      and f"maskdoc_surfaces_surviving_nolost_{L}" in v)
            sfx = "_nolost" if nolost else ""
            mark = "†" if nolost and v.get(f"extraction_docs_lost_{L}", "0") not in ("0", NA) \
                else ""
            rows.append([L + mark, _k(v, f"maskdoc_refused_docs_{L}"),
                         _k(v, f"maskdoc_5gram_pct{sfx}_{L}"),
                         _k(v, f"maskdoc_surfaces_surviving{sfx}_{L}")])
    note = "(a) "
    if v.get("fp_deployed_rules_standalone") == "yes":
        # The payloads share no 5-gram with the corpus by construction, so the
        # note points to the refusals they cannot measure (re-review 2026-10-18, A7).
        note += ("containment refuses no clean payload (a refusal would be a Bloom "
                 "collision; benign text sharing a corpus run is not among these payloads, "
                 "Section VII); the chain's refusals are the entropy and regex screens', and "
                 "keeping the carry over each stratum gives the same «fp_deployed_session». ")
    if "fp_n_per_stratum" in v and v["fp_n_per_stratum"] != NA:
        note += "Strata weigh equally, so the all-strata rate is not a traffic rate; "
    note += ("refusals within one run are not independent, and the counts and the positive "
             "control get no interval.")
    notes = [note]
    if letters:
        notes.append(_maskdoc_note_short(v, letters))
    return TableSpec(
        "t1", "Table 1",
        "Monitor refusals (RQ1).",
        ["Input", "Refused (k/N)", "Wilson 95% CI"], rows, notes=notes,
        widths=[3.6, 1.4, 2.0], widths2=list(T2_MASKDOC_WIDTHS))


# Table 1 since 2026-10-21: the extraction every arm shares and r1's store, per
# corpus, in §5 (formerly Table 2(b); its echo column is Fig. 4(b)).
T_EXTRACT_HEAD = ("Corpus", "Table data cells", "r1 store: cells held",
                  "r1 sentences deleted per run", "Gold referents extracted exactly",
                  "Jaccard, entities / relations", "Longest predicate (tokens)")
T_EXTRACT_WIDTHS = [0.75, 0.85, 0.95, 1.2, 1.2, 1.15, 0.9]


def table_extraction(nb: Numbers, corpora: dict[str, str] | None = None,
                     letters: list[str] | None = None) -> TableSpec:
    """Table 1 since 2026-10-21: per corpus, the extraction every arm shares and
    r1's store. Puts r1_store_cells_<L>, as table3 does."""
    v = nb.values
    corpora = dict(corpora or {})
    if letters is None:
        letters = sorted({k.rsplit("_", 1)[1] for k in v if k.startswith("pred_n_")})
    order = list(corpora) + sorted(L for L in letters if L not in corpora)
    rows: list[Any] = []
    for L in order:
        has_arms = any(f"t4_{L}_{a}_rba" in v for a in (*ARM_ORDER, "oracle"))
        if not has_arms and L not in letters:
            continue
        store = f"t4_{L}_r1_factsstruct"
        if store in v:
            nb.put(f"r1_store_cells_{L}", _collapse_range(v[store]),
                   f"{store} (one value when min = max)", v[store], "count")

        def probe(tpl: str, L: str = L) -> str:
            cell = tpl.format(L=L)
            keys = re.findall(r"«([^»]+)»", cell)
            return cell if L in letters and all(k in v for k in keys) else NA

        rows.append([L + ("*" if L == "A" else ""), _k(v, f"table_cells_{L}"),
                     _k(v, f"r1_store_cells_{L}"), _k(v, f"t4_{L}_r1_pruned"),
                     *(probe(t) for _, t in T3_CORPUS_CELLS[:3])])
    na = any(NA in c for r in rows for c in r[1:])
    note = ("*Corpus A is in-sample for the RBA attribute lexicon's fix. Referents and longest "
            "predicate span the unseeded extractions (a range where they differ), and Jaccard "
            "compares a corpus's unseeded extractions with each other; deleted: sentences whose "
            "fact references are all absent (Section IV-C); r1 sentences: mean [min–max] per run"
            + ("; n/a: no probe or no value." if na else "."))
    return TableSpec("t1", "Table 1", "Extraction and r1's store per corpus.",
                     list(T_EXTRACT_HEAD), rows, notes=[note], widths=list(T_EXTRACT_WIDTHS))


# Table 2 (formerly Table 3) since 2026-10-19: what crosses per arm and the
# per-corpus extraction and store figures; the per-corpus scores are Fig. 3. The
# per-arm traffic figures (slots on the wire, relations sent, FACT references
# returned, bytes, tokens), which no draft sentence quotes, are left out since the
# author's approval of 2026-10-01 (Part D AD32); --traffic-rows puts them back.
# Table 2(a): one row per arm, A-D pooled (the author's request of 2026-10-19:
# tables a newcomer can read); each column one measurement, named in full.
T3_ARM_HEAD = ("Arm", "Slot ids listed per run", "Generator-written constants and label "
               "words in core-sent content (H3)", "Extracted-entity strings in core-sent content",
               "Extracted-entity strings in cloud-written spans",
               "Adversary matches: extracted entities", "Adversary matches: document 5-grams")
T3_ARM_WIDTHS = [0.7, 0.9, 1.25, 1.15, 1.15, 1.0, 1.0]
T3_ARM_CELLS = ("{obs_%s_slots_adv}",
                # H3 counts label surfaces too (run_evaluation.py), so the cell gives
                # both (claim-preservation review of 2026-10-19, finding 1).
                "{cross_a_%s} and {cross_a_label_%s} in {cross_a_scanned_%s} runs",
                "{cross_b_core_%s} in {cross_b_scanned_%s} runs", "{cross_b_cloud_%s}",
                "{g3_entities_%s}", "{g3_5grams_%s}")
# Table 2(b): one row per corpus; the shared extraction's probe figures (the same
# for every arm) and r1's store.
T3_CORPUS_HEAD = ("Corpus", "Table data cells", "r1 store: cells held",
                  "r1 sentences deleted per run", "Gold referents extracted exactly",
                  "Jaccard, entities / relations", "Longest predicate (tokens)",
                  "Predicates echoing a short corpus n-gram (control)")
T3_CORPUS_WIDTHS = [0.6, 0.6, 0.75, 1.0, 0.8, 1.0, 0.8, 1.45]
T3_CORPUS_CELLS = (
    ("referents found exactly", "«recall_referents_exact_{L}»"),
    ("Jaccard", "«extraction_entity_jaccard_{L}» / «extraction_relation_jaccard_{L}»"),
    ("longest predicate", "«pred_max_tokens_{L}»"),
    ("echo, shared", "«pred_echo_pct_shared_{L}» («pred_control_echo_pct_shared_{L}»)"),
)
T3_TRAFFIC = (("slots on the wire", "{obs_%s_slots_wire}"),
              ("relations sent", "{obs_%s_relations}"),
              ("FACT references returned", "{obs_%s_fact_refs}"),
              ("request / response bytes", "{obs_%s_req_bytes} / {obs_%s_resp_bytes}"),
              ("plan tokens in / out", "{obs_%s_plan_input} / {obs_%s_plan_output}"),
              ("draft tokens in / out", "{obs_%s_draft_input} / {obs_%s_draft_output}"))


def table3(nb: Numbers, corpora: dict[str, str] | None = None,
           letters: list[str] | None = None, traffic: bool = False) -> TableSpec:
    """Table 2 since 2026-10-19 (the author's request for readable tables): (a)
    what crosses per arm, A-D pooled, one row per arm, each figure in its own
    column under a header that names it; (b) per corpus, the extraction every arm
    shares and r1's store, as a second table under the same caption. The scores
    per corpus and arm are Fig. 3 (make_fig3_binding). Left for the artifact (keys
    kept): the label-word counts, the per-arm cost (Section VI-D gives the
    deployment and evaluation split), the pooled pruning, the all-extraction echo
    ranges. `corpora`: letter -> task id, in order; `letters`: the corpora whose
    probe figures are shown, by default every corpus with a probe key. `traffic`
    True puts the per-arm traffic rows back (--traffic-rows; Part D AD32)."""
    v = nb.values
    corpora = dict(corpora or {})
    if letters is None:
        letters = sorted({k.rsplit("_", 1)[1] for k in v if k.startswith("pred_n_")})
    order = list(corpora) + sorted(L for L in letters if L not in corpora)
    # Panel (a) is labelled in the table, as Table 1's is (review of 2026-10-19: the
    # text cites Table 2(a) and the caption is a title).
    rows: list[Any] = [("panel", "(a) Per arm, corpora A–D pooled")]
    arms = [a for a in ARM_ORDER if f"obs_{a}_runs" in v or f"cross_a_{a}" in v]
    for a in arms:
        rows.append([a] + [_fill_arm(f, a, v) for f in T3_ARM_CELLS])
    if traffic:
        rows += [("wide", a, "; ".join(f"{label} {_fill_arm(f, a, v)}"
                                       for label, f in T3_TRAFFIC)) for a in arms]
    corpus_rows = []
    for L in order:
        has_arms = any(f"t4_{L}_{a}_rba" in v for a in (*ARM_ORDER, "oracle"))
        if not has_arms and L not in letters:
            continue
        store = f"t4_{L}_r1_factsstruct"
        if store in v:
            # Every r1 run on a corpus holds the same store, so "18.0 [18.0–18.0]"
            # is printed as "18": the same value, written once.
            nb.put(f"r1_store_cells_{L}", _collapse_range(v[store]),
                   f"{store} (one value when min = max)", v[store], "count")

        def probe(tpl: str, L: str = L) -> str:
            cell = tpl.format(L=L)
            keys = re.findall(r"«([^»]+)»", cell)
            return cell if L in letters and all(k in v for k in keys) else NA

        corpus_rows.append([L + ("*" if L == "A" else ""), _k(v, f"table_cells_{L}"),
                            _k(v, f"r1_store_cells_{L}"), _k(v, f"t4_{L}_r1_pruned"),
                            *(probe(t) for _, t in T3_CORPUS_CELLS)])
    if corpus_rows:
        rows.append(("panel", "(b) Per corpus: the extraction every arm shares (RQ2), and r1's "
                              "store (RQ3)"))
        rows.append(("head", *T3_CORPUS_HEAD))
        rows += corpus_rows
    # Units and scopes as the claim-preservation and consistency reviews of
    # 2026-10-19 found them: H3's columns sum occurrences, crossing (b) counts
    # (run, string) pairs; referents and the longest predicate range over every
    # unseeded extraction, echo uses the shared one (sources of the keys).
    note = ("(a) Each arm's runs on corpora A–D pooled; slot ids: mean [min–max] per run; "
            "constants and label words (constants that are ordinary English words, counted "
            "apart) count occurrences, extracted-entity strings (run, string) pairs; an "
            "adversary match's N sums the run's extracted entities (document 5-grams) over "
            "the arm's runs.")
    if corpus_rows:
        na = any(NA in c for r in corpus_rows for c in r[1:])
        note += (" (b) *Corpus A is in-sample for the RBA attribute lexicon's fix. Referents "
                 "and longest "
                 "predicate span the unseeded extractions (a range where they differ), and "
                 "Jaccard compares a corpus's unseeded extractions with each other; deleted: "
                 "sentences whose fact references are all absent (Section IV-C); echo, over the "
                 "shared extraction: predicates repeating a corpus n-gram shorter than the "
                 "monitor's run; control: unrelated prose of the same lengths"
                 + ("; n/a: no probe or no value." if na else "."))
    return TableSpec(
        "t2", "Table 2",
        "What crosses the boundary and what an adversary matches (RQ2).",
        list(T3_ARM_HEAD), rows, notes=[note], widths=list(T3_ARM_WIDTHS),
        widths2=list(T3_CORPUS_WIDTHS))


def _collapse_range(s: str) -> str:
    """'18.0 [18.0–18.0]' -> '18'; any other mean [min–max] is kept as given."""
    m = re.fullmatch(r"(\S+) \[(\S+)–(\S+)\]", s.strip())
    if not m or len({m.group(1), m.group(2), m.group(3)}) != 1:
        return s
    x = m.group(1)
    return x[:-2] if x.endswith(".0") else x


# Table 4: the pre-registered hypotheses (scope §8.7 and §8.7a), each with when it
# was registered, its decision rule, its outcome and the reason for it, from the
# change set of 2026-10-10 (TAB-IV, review MR4a). The decision rules are the
# registered ones as §5 words them; the outcomes and every figure are keys; a
# reason clause that holds only for some outcomes is written only for them
# (_t4_reason_*). "tests R1" and "design check" are the labels the
# author confirms (TAB-IV needs_author).
T4_HEADER = ["Hypothesis", "Registered rule", "Outcome"]
T4_WIDTHS = [0.9, 4.6, 1.5]
T4_WIDTHS_REASONS = [0.85, 2.75, 0.9, 2.5]
# Table 3's row groups, by what each hypothesis checks (the author's request of
# 2026-10-19 for readable tables); when each was registered goes to the note.
T4_GROUPS = (("Design checks", ("H3 (A–D)", "H2 (C)")),
             # "Hypotheses on R1", not "Tests of R1": H4-D′ is not a test (note).
             ("Hypotheses on R1", ("H1 (A, B)", "H4-D (D)", "H4-D′ (D)")),
             ("Real documents", ("HL1 (L)",)))
T4_AFTER_PILOT = ("H4-D′ (D)",)
T4_RULES = (
    ("H1 (A, B)", "Before the pilot; tests R1",
     "On each corpus, every r1 run's RBA and attribute accuracy above every baseline run's"),
    ("H2 (C)", "Before the pilot; design check; floor rule after it",
     "r1's coverage_stated and coverage_correct below baseline's"),
    ("H3 (A–D)", "Before the pilot; design check",
     # §5's wording, with H3's object under its one name, generator-written
     # constant (the author's request of 2026-10-19); the scope registers it as
     # "the generator-surface scan finds zero hits in core-sent content".
     "No generator-written constant, in any rendered form, in core-sent content of any "
     "private-arm trace"),
    ("H4-D (D)", "Before the pilot; tests R1",
     "D's facts_structural share below A's and B's, and r1's RBA gain over baseline smaller "
     "on D than on A and B"),
    ("H4-D′ (D)", "After the pilot, before the batch",
     "Every r1 run's coverage_correct on D below every r1 run's on A and on B"),
)
T4_NOT_TESTABLE = "not testable"
# Track L's row (scope §12.7), added when the build carries hl1_outcome.
T4_HL1 = ("HL1 (L)", "Before the L batch; tests what crosses",
          "No DIRECT identifier string crosses in any private-arm run; every trace "
          "scanned and complete and every collection with a valid run of every arm")


def _t4_reason_hl1(v: dict[str, str]) -> str:
    """HL1: the planner refusals that left collections without a valid run, when
    the scan says not testable for that reason; then the crossings on the rest."""
    crossed = "DIRECT «l_direct_crossed_kn» on the «l_runs» runs of the rest"
    if v.get("hl1_outcome") == T4_NOT_TESTABLE and "l_collections_planner_refused_kn" in v:
        return ("M refused the planner request on «l_collections_planner_refused_kn» "
                "collections, which have no valid run; " + crossed)
    return crossed


def _t4_reason_h1(v: dict[str, str]) -> str:
    """H1: while neither corpus's RBA half is testable, how few baseline runs have
    an RBA; otherwise each half's outcome. Since 2026-10-19 the attribute half on
    its own, with B's margin and its chance-level caveat (re-review of 2026-10-18,
    R7), is Section VI-C's text, not the cell's (the author's request for readable
    tables). The arm name keeps its case, as in the H4-D cell and §6.3."""
    if all(v.get(f"h1_{L}_rba_outcome") == T4_NOT_TESTABLE for L in "AB"):
        return ("baseline has an RBA (at least «min_rba_pool» scored occurrences) in "
                "«rba_baseline_A_n» runs on corpus A and «rba_baseline_B_n» on corpus B "
                "(Section VI-C)")
    return ("RBA half: «h1_A_rba_outcome» on corpus A, «h1_B_rba_outcome» on corpus B; "
            "attribute half: «h1_A_attr_outcome» on corpus A (in-sample), "
            "«h1_B_attr_outcome» on corpus B")


def _t4_reason_h2(v: dict[str, str]) -> str:
    """H2: the coverage_stated comparison; coverage_correct at the floor, and what
    the pre-pilot reading (both halves, a tie at zero failing) would decide, only
    when the floor rule applied (h2_coverage_correct_floor == yes); otherwise its
    two deciding values."""
    s = "coverage_stated «h2_coverage_stated_r1_max» against «h2_coverage_stated_baseline_min»"
    if v.get("h2_coverage_correct_floor") == "yes":
        # "holds" beside "would not hold" read as a contradiction (readability
        # review of 2026-10-19): the cell names the half that decides and the rule
        # (added after the pilot, as the table's note says) that sets the other aside.
        return (s + " decides; coverage_correct is at the floor, not testable under the "
                    "floor rule (registered after the pilot); under the pre-pilot reading, "
                    "which needs both halves, H2 "
                    "would not hold")
    return (s + "; coverage_correct «h2_coverage_correct_r1_max» against "
                "«h2_coverage_correct_baseline_min»")


def _t4_reason_h4d(v: dict[str, str]) -> str:
    """H4-D: 'Share half holds' only when both share comparisons hold, else each
    one's outcome; then, while both RBA-gain comparisons are not testable, how few
    baseline runs on D have an RBA, else their outcomes."""
    if all(v.get(f"h4d_structural_share_vs_{L}_outcome") == "holds" for L in "AB"):
        share = "Share half holds"
    else:
        share = ("Share half: «h4d_structural_share_vs_A_outcome» against corpus A, "
                 "«h4d_structural_share_vs_B_outcome» against corpus B")
    if all(v.get(f"h4d_rba_gain_vs_{L}_outcome") == T4_NOT_TESTABLE for L in "AB"):
        return share + "; baseline has an RBA in «rba_baseline_D_n» runs on corpus D"
    return (share + "; RBA-gain half: «h4d_rba_gain_vs_A_outcome» against corpus A, "
                    "«h4d_rba_gain_vs_B_outcome» against corpus B")


# The manuscript's Table 1 since 2026-10-27 (the author's request "Table I không rõ nghĩa
# là gì? nên thay đổi"; written by the AI assistant from workflow wf_2c363a10-a15: three
# independent redesigns, a judge, an AI claim-fidelity critic and an AI reader-clarity
# critic): a column saying what each hypothesis checks, in a question "holds" answers
# yes to, tagged as §5.3 classes it (TAB-IV: design check, test of R1; H4-D′ not a
# test); the registered rule as before, H3's with its registered exclusions and H2's
# with the post-pilot floor rule that decided it; the outcome word in bold with its
# reason in a few words; rows grouped under §6's questions; no tints, which the
# outcome words repeat and which grey scale cannot tell apart; a note saying what "not
# testable" and "post-pilot" mean. The artifact's table (reasons=True) is unchanged.
T1_HEADER = ["Hypothesis", "What it checks", "Holds when (registered rule, Section V-C)",
             "Outcome"]
T1_WIDTHS = [0.70, 1.86, 2.46, 1.48]
T1_GROUPS = (("Does private text cross? (Sections VI-A, VI-C)", ("H3 (A–D)", "HL1 (L)")),
             ("Does the cloud bind values to roles? (Section VI-B)",
              ("H1 (A, B)", "H4-D (D)", "H4-D′ (D)", "H2 (C)")))
# The tags lead their cells in italic (TableSpec.tag_col).
T1_TAGS = ("Design check:", "Test of R1:", "Not a test:")
T1_CHECKS = {
    "H3 (A–D)": "Design check: does the core keep out of its requests each value, name and "
                "date the corpus generator wrote?",
    "HL1 (L)": "On public court judgments, is every string identifying a person on its own "
               "(DIRECT) kept from the cloud?",
    "H1 (A, B)": "Test of R1: does r1 exceed baseline on RBA and attribute accuracy?",
    "H4-D (D)": "Test of R1: is r1's RBA gain smaller on D? The header lexicon lacks about "
                "half its budget-column headers",
    "H4-D′ (D)": "Not a test: does r1 cover less on D than on A and B?",
    "H2 (C)": "Design check: with no prose route in R1, does r1 cover less than baseline on "
              "C, whose figures are in prose?",
}
# H3's registered exclusions (scope §8.7: the goal and spans repeating a cloud reply)
# and H2's floor rule (scope §8.7a), so that the cell is the rule that decided.
T1_RULE_TAILS = {
    "H3 (A–D)": " (goal and spans repeating a cloud reply excluded)",
    "H2 (C)": "; post-pilot, a half at the floor is not testable and the other half decides",
}
T1_NOTE = ("Not testable (neither holds nor fails): a value or run the rule needs is missing "
           "and none available violates it (a run with fewer than «min_rba_pool» scored "
           "occurrences has no RBA). At H2's floor, r1's highest and baseline's lowest value "
           "are both zero. Post-pilot: registered after the pilot, before the batch; HL1 was "
           "registered before the L batch, the rest before the pilot. Arm r1 runs R1, the "
           "local fact store; baseline does not. In parentheses: the corpora (A–D synthetic; "
           "L, court judgments).")


def _t1_outcomes(v: dict[str, str]) -> dict[str, str]:
    """The manuscript table's outcome cells: the outcome key, then its reason in a few
    words, each clause written only for the outcomes it is true of (§6's text)."""
    nt = T4_NOT_TESTABLE
    h3 = "«h3_outcome»" + (": «h3_hits» hits in «h3_runs_scanned» private-arm traces, over "
                           "«n_corpora_measured» extractions, one per corpus"
                           if v.get("h3_outcome") == "holds" else "")
    hl1 = "«hl1_outcome»" + (": no valid run on «l_collections_planner_refused_kn» "
                             "collections, whose planner request M refused"
                             if v.get("hl1_outcome") == nt
                             and "l_collections_planner_refused_kn" in v else "")
    h1 = ("«h1_A_outcome»" if v.get("h1_A_outcome") == v.get("h1_B_outcome")
          else "A: «h1_A_outcome»; B: «h1_B_outcome»")
    if (v.get("h1_A_outcome") == v.get("h1_B_outcome") == nt
            and all(v.get(f"h1_{L}_rba_outcome") == nt for L in "AB")):
        h1 += (": baseline has an RBA in «rba_baseline_A_n» runs per corpus"
               if v.get("rba_baseline_A_n") == v.get("rba_baseline_B_n")
               else ": baseline has an RBA in «rba_baseline_A_n» runs on A, "
                    "«rba_baseline_B_n» on B")
    parts = []
    if (v.get("h4d_outcome") == nt
            and all(v.get(f"h4d_rba_gain_vs_{L}_outcome") == nt for L in "AB")):
        parts.append("baseline has an RBA in «rba_baseline_D_n» runs on D")
    if all(v.get(f"h4d_structural_share_vs_{L}_outcome") == "holds" for L in "AB"):
        parts.append("share half (not a test) holds")
    else:
        parts.append("share half: «h4d_structural_share_vs_A_outcome» against A, "
                     "«h4d_structural_share_vs_B_outcome» against B")
    h2 = "«h2_outcome»" + (" on coverage_stated alone (post-pilot floor rule)"
                           if v.get("h2_coverage_correct_floor") == "yes"
                           and v.get("h2_outcome") == "holds" else "")
    return {"H3 (A–D)": h3, "HL1 (L)": hl1, "H1 (A, B)": h1,
            "H4-D (D)": "«h4d_outcome»: " + "; ".join(parts),
            "H4-D′ (D)": "«h4dp_outcome» (post-pilot; scored by the RBA rule, not validated)",
            "H2 (C)": h2}


def _table_hypotheses_manuscript(nb: Numbers) -> TableSpec:
    """The manuscript's Table 1 (T1_HEADER): what each hypothesis checks, its
    registered rule, and its outcome with the reason."""
    v = nb.values

    def keyed(text: str) -> str:
        return re.sub(r"«([^»]+)»", lambda m: _k(v, m.group(1)), text)

    rules = {h: rule + T1_RULE_TAILS.get(h, "") for h, _reg, rule in T4_RULES}
    outcome = _t1_outcomes(v)
    if "hl1_outcome" in v:
        rules[T4_HL1[0]] = T4_HL1[2]
    rows: list[Any] = []
    for group, hyps in T1_GROUPS:
        present = [h for h in hyps if h in rules]
        if present:
            rows.append(("panel", group))
            rows += [[h, T1_CHECKS[h], rules[h], keyed(outcome[h])] for h in present]
    return TableSpec("t1", "Table 1", "Registered hypotheses and outcomes.", list(T1_HEADER),
                     rows, notes=[keyed(T1_NOTE)], widths=list(T1_WIDTHS), tag_col=1,
                     lead_bold_col=3, row_rules=True)


def table_hypotheses(nb: Numbers, reasons: bool = False) -> TableSpec:
    """Table 4 (TAB-IV): one row per pre-registered hypothesis. Every outcome and
    figure is a key (n/a where the build has none); the note states what an
    every-run comparison of n runs with n can show (every_run_exact_p). Without
    `reasons`, the manuscript's table (_table_hypotheses_manuscript)."""
    if not reasons:
        return _table_hypotheses_manuscript(nb)
    v = nb.values
    # Pre-submission audit of 2026-10-25: one outcome for both corpora when they
    # agree, and H2's cell says it holds under the floor rule when it does.
    h1 = ("«h1_A_outcome»" if v.get("h1_A_outcome") == v.get("h1_B_outcome")
          else "A: «h1_A_outcome»; B: «h1_B_outcome»")
    # R4(5) of the simulated review of 2026-10-26 (written by the AI assistant at the author's
    # request "đồng ý với đề xuất, chỉnh sửa toàn bộ theo yêu cầu"): each post-pilot outcome says
    # so in its cell, and H4-D′'s that it rests on coverage_correct, a score of the unvalidated
    # RBA rule (§7); the word "post-pilot" also selects its tint (OUTCOME_TINTS). Never "not
    # supported": h2_outcome is the registered outcome under the floor rule signed before the
    # batch (scope §8.7a).
    h2 = "«h2_outcome»" + (" (post-pilot floor rule)"
                           if v.get("h2_coverage_correct_floor") == "yes"
                           and v.get("h2_outcome") == "holds" else "")
    outcome = {"H1 (A, B)": h1,
               "H2 (C)": h2, "H3 (A–D)": "«h3_outcome»",
               "H4-D (D)": "«h4d_outcome»",
               "H4-D′ (D)": "«h4dp_outcome» (post-pilot; RBA-rule score)"}
    reason = {"H1 (A, B)": _t4_reason_h1(v), "H2 (C)": _t4_reason_h2(v),
              "H3 (A–D)": "«h3_hits» hits in «h3_runs_scanned» runs, over one shared "
                          "extraction per corpus",
              "H4-D (D)": _t4_reason_h4d(v),
              "H4-D′ (D)": "corpus D at most «h4dp_vs_A_D_max»; corpora A and B at least "
                           "«h4dp_vs_A_A_min» and «h4dp_vs_B_B_min»"}

    def keyed(text: str) -> str:
        # A figure the build has no key for reads n/a, as in every other table.
        return re.sub(r"«([^»]+)»", lambda m: _k(v, m.group(1)), text)

    rules = {h: rule for h, _reg, rule in T4_RULES}
    if "hl1_outcome" in v:
        # Track L's registered hypothesis (scope §12.7), so that "Table 3 gives each
        # hypothesis" holds once the L batch is built (simulated review of
        # 2026-10-18, R1 W2).
        rules[T4_HL1[0]] = T4_HL1[2]
        outcome[T4_HL1[0]] = "«hl1_outcome»"
        reason[T4_HL1[0]] = _t4_reason_hl1(v)
    rows: list[Any] = []
    for group, hyps in T4_GROUPS:
        present = [h for h in hyps if h in rules]
        if not present:
            continue
        rows.append(("panel", group))
        # Since 2026-10-21 (the author's request for a short evaluation) the
        # manuscript's table gives rule and outcome; each outcome's reason is §6's
        # text. `reasons` True adds the Reason column (the artifact's table).
        # No dagger since 2026-10-25 (the author's request before submission: "còn các †
        # trong bài"); the note names the hypothesis registered after the pilot.
        rows += [[h, rules[h], keyed(outcome[h])]
                 + ([keyed(reason[h])] if reasons else []) for h in present]
    # H2 holds only under the floor rule registered after the pilot (review of
    # 2026-10-21): the note says so, and since 2026-10-26 (R4(5), the AI assistant at the
    # author's request) that amber marks an outcome under a rule registered after the pilot.
    after = " and ".join(h.split(" ")[0] for h in T4_AFTER_PILOT)
    note = (f"{after} was registered after the pilot, before the batch, as was H2's floor rule, "
            "under which H2 holds on its coverage_stated half alone (Section VI-B); HL1 before "
            "the L batch; the others before the pilot; Section V-C defines the test. Letters name "
            "corpora; L is track L. Shading marks the outcome, not a benefit; amber marks an "
            "outcome under a rule registered after the pilot.")
    return TableSpec(
        "t1", "Table 1",
        "Registered hypotheses and outcomes.",
        list(T4_HEADER) + (["Reason"] if reasons else []), rows, notes=[keyed(note)],
        widths=list(T4_WIDTHS_REASONS if reasons else T4_WIDTHS), shade_col=2)


def _fill_arm(fmt: str, arm: str, v: dict[str, str]) -> str:
    keys = re.findall(r"\{([^}]+)\}", fmt)
    out = fmt
    for k in keys:
        out = out.replace("{" + k + "}", _k(v, k % ((arm,) * k.count("%s"))))
    return out


# ------------------------------------------------------------ the strip plot (artifact)
# Fig. 3 until the author removed it from the manuscript on 2026-10-02 (plan Part D
# AD33); the build still draws it, for the artifact, and the fill never reads it.

ARM_COLOURS = {"baseline": "#2a78d6", "r5": "#eb6834", "r1": "#1baf7a"}   # slots 1-3
ARM_MARKERS = {"baseline": "o", "r5": "s", "r1": "^"}
ORACLE_BAND = "#dddcd7"
INK, INK_2, GRID = "#0b0b0b", "#52514e", "#e8e7e3"


def fig3_points(ev: Src, corpora: dict[str, str]) -> dict[str, Any]:
    """Per corpus: each pooled run's RBA by arm (None when suppressed or stale), and
    the oracle band. Runs are the aggregate's own pooled runs. A corpus with no
    runs is kept, with no points, so the figure shows it as an empty group."""
    from scripts.run_evaluation import MIN_RBA_POOL
    pooled = {r for a in ARM_ORDER for r in (_ptr(ev.data, _p("arms", a, "runs")) or [])}
    out: dict[str, Any] = {}
    for L, tid in corpora.items():
        bt = _ptr(ev.data, _p("by_task", tid)) or {}
        if not bt.get("arms"):
            out[L] = {"task": tid, "points": {a: [] for a in ARM_ORDER}, "oracle": None}
            continue
        stale = set(bt.get("stale_key_runs") or [])
        pts: dict[str, list[tuple[str, float | None]]] = {a: [] for a in ARM_ORDER}
        for m in ev.data.get("per_task", []):
            if m.get("task_id") != tid or m.get("run") not in pooled or m.get("arm") not in pts:
                continue
            f = (m.get("faithfulness") or {}).get("private") or {}
            full = (f.get("denominators") or {}).get("full")
            ok = (f.get("rba") is not None and full is not None and full >= MIN_RBA_POOL
                  and m["run"] not in stale)
            pts[m["arm"]].append((m["run"], f["rba"] if ok else None))
        o = ((bt.get("oracle") or {}).get("faithfulness") or {}).get("rba") or {}
        out[L] = {"task": tid, "points": {a: sorted(p) for a, p in pts.items()},
                  "oracle": (o.get("min"), o.get("max")) if o.get("n") else None}
    return out


def make_fig3(data: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    import matplotlib  # noqa: PLC0415
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415
    from matplotlib.lines import Line2D  # noqa: PLC0415
    from matplotlib.patches import Patch  # noqa: PLC0415

    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Liberation Serif", "DejaVu Serif"],
        "font.size": 8, "axes.edgecolor": INK_2, "axes.labelcolor": INK,
        "xtick.color": INK_2, "ytick.color": INK_2, "svg.hashsalt": "pap5a",
        "svg.fonttype": "none",
    })
    letters = list(data)
    fig, ax = plt.subplots(figsize=(6.3, 2.6))
    offs = {"baseline": -0.25, "r5": 0.0, "r1": 0.25}
    for gi, L in enumerate(letters):
        if not any(data[L]["points"][a] for a in ARM_ORDER):
            ax.text(gi, 0.5, "no runs", ha="center", va="center", fontsize=7,
                    color=INK_2, zorder=3)
            continue
        band = data[L]["oracle"]
        if band and band[0] is not None:
            ax.add_patch(plt.Rectangle((gi - 0.45, band[0]), 0.9, band[1] - band[0],
                                       facecolor=ORACLE_BAND, edgecolor="none", zorder=0))
        for arm in ARM_ORDER:
            pts = data[L]["points"][arm]
            vals = [p for _, p in pts if p is not None]
            k = len(vals)
            xs = [gi + offs[arm] + (j - (k - 1) / 2) * 0.05 for j in range(k)]
            if vals:
                ax.scatter(xs, vals, s=22, marker=ARM_MARKERS[arm], c=ARM_COLOURS[arm],
                           edgecolors="white", linewidths=0.6, zorder=3)
            if len(vals) < len(pts):
                ax.text(gi + offs[arm], 0.02, "n/a", ha="center", va="bottom",
                        fontsize=6.5, color=INK_2, zorder=3)
    ax.set_xlim(-0.6, len(letters) - 0.4)
    ax.set_ylim(0, 1.05)                       # room for a marker at 1.0
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.spines["left"].set_bounds(0, 1.0)
    ax.set_xticks(range(len(letters)))
    ax.set_xticklabels([f"{L}\n{data[L]['task']}" + (" (in-sample)" if L == "A" else "")
                        for L in letters])
    ax.set_xlabel("Corpus")
    ax.set_ylabel("Role-binding accuracy (RBA)")
    ax.yaxis.grid(True, color=GRID, linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(axis="x", length=0)
    handles = [Line2D([], [], linestyle="none", marker=ARM_MARKERS[a], markersize=5,
                      markerfacecolor=ARM_COLOURS[a], markeredgecolor="white", label=a)
               for a in ARM_ORDER]
    handles.append(Patch(facecolor=ORACLE_BAND, edgecolor="none", label="oracle range"))
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False,
              fontsize=7)
    fig.tight_layout()
    png, svg = out_dir / "fig3_rba_strip.png", out_dir / "fig3_rba_strip.svg"
    fig.savefig(png, dpi=FIG_DPI, metadata={"Software": None})
    fig.savefig(svg, metadata={"Date": None, "Creator": None})
    plt.close(fig)
    return png, svg



# Fig. 3 (re-review of 2026-10-18, the author's choice of the same day: Table 3's
# per-corpus scores become a figure, its probe and pooled rows stay a table): the
# frozen rule's four per-run scores, one panel each, per corpus and private arm,
# with the oracle's range as the reference band. Every marker is a run's value
# from evaluation.json; the caption carries no figure but keys.
# Panels in the order Section VI-C reads them, lettered (2026-10-19).
FIG3_METRICS = (("attribute_accuracy", "(a) Attribute accuracy"), ("rba", "(b) RBA"),
                ("coverage_stated", "(c) coverage_stated"),
                ("coverage_correct", "(d) coverage_correct"))
# Fig. 5 since 2026-10-21 (Fig. 3 before); the constants keep their names.
FIG3_PNG = "fig5_binding.png"
FIG3_CAPTION = "fig5_caption.txt"
FIG3_WIDTH_IN = 7.0
# Fig. 3's own palette (2026-10-21): the proposed arm r1 in the one saturated
# colour, in T's green of Fig. 1, where its fact store lives; baseline and r5
# muted, and neither in Fig. 1's orange (what passes through M) or red (refusal).
# The marker shapes stay ARM_MARKERS, so the arms part in greyscale too.
FIG3_COLOURS = {"baseline": "#7f8ea3", "r5": "#a58bbf", "r1": "#1a7f4f"}
FIG3_SIZE = {"baseline": 10, "r5": 10, "r1": 15}
FIG3_ORACLE_FILL, FIG3_ORACLE_EDGE = "#efeee9", "#a9a79f"
FIG3_NA = "#55544f"
# A short, title-like caption since 2026-10-19 (the author's request); the
# reading of the panels is in the legend and §6.3 (oracle band an upper
# reference, corpus A in-sample, a run without a value has no marker, the scores
# the RBA rule's).
FIG3_CAPTION_TEXT = "Fig. 5. Role binding and coverage per corpus and private arm (RQ3)."


def fig3_binding_points(ev: Src, corpora: dict[str, str]) -> dict[str, Any]:
    """Per corpus and metric: each pooled private run's value by arm (None when the
    run has none: RBA under MIN_RBA_POOL scored occurrences or a stale key, as
    fig3_points, or a null metric), and the oracle's (min, max) over its reports."""
    from scripts.run_evaluation import MIN_RBA_POOL
    pooled = {r for a in ARM_ORDER for r in (_ptr(ev.data, _p("arms", a, "runs")) or [])}
    out: dict[str, Any] = {}
    for L, tid in corpora.items():
        bt = _ptr(ev.data, _p("by_task", tid)) or {}
        stale = set(bt.get("stale_key_runs") or [])
        per: dict[str, dict[str, list[float | None]]] = {
            m: {a: [] for a in ARM_ORDER} for m, _ in FIG3_METRICS}
        runs = sorted((m for m in ev.data.get("per_task", [])
                       if m.get("task_id") == tid and m.get("run") in pooled
                       and m.get("arm") in ARM_ORDER), key=lambda m: m["run"])
        for m in runs:
            f = (m.get("faithfulness") or {}).get("private") or {}
            for metric, _ in FIG3_METRICS:
                x = f.get(metric)
                if metric == "rba":
                    full = (f.get("denominators") or {}).get("full")
                    if full is None or full < MIN_RBA_POOL:
                        x = None
                if m["run"] in stale:
                    x = None
                per[metric][m["arm"]].append(x)
        ofa = ((bt.get("oracle") or {}).get("faithfulness") or {})
        band = {}
        for metric, _ in FIG3_METRICS:
            o = ofa.get(metric) or {}
            band[metric] = (o.get("min"), o.get("max")) if o.get("n") else None
        out[L] = {"task": tid, "runs": per, "oracle": band}
    return out


def make_fig3_binding(data: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    """Four panels side by side, 7.0 in wide (FIG3_WIDTH_IN, the artifact's width):
    attribute accuracy, RBA, coverage_stated and coverage_correct, corpora on the x axis, the arms
    side by side within a corpus, the oracle's range behind them.

    Restyled on 2026-10-21 at the author's request ("Nhìn rối và không thuyết
    phục"): the proposed arm, r1, is the one saturated colour and the largest
    marker, the two comparison arms are muted; the oracle's range is a light band
    with a hairline at each end instead of a solid grey block; the axis leaves room
    below 0 and above 1, so a run at either end is drawn whole; the legend is one
    line and names A*. The data, the panels, their order and their letters are
    unchanged."""
    import matplotlib  # noqa: PLC0415
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415
    from matplotlib.lines import Line2D  # noqa: PLC0415
    from matplotlib.patches import Patch  # noqa: PLC0415

    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Liberation Serif", "DejaVu Serif"],
        "font.size": 7, "axes.edgecolor": INK_2, "axes.labelcolor": INK,
        "xtick.color": INK, "ytick.color": INK_2, "svg.hashsalt": "fig3b",
        "svg.fonttype": "none", "axes.linewidth": 0.6,
    })
    letters = list(data)
    fig, axes = plt.subplots(1, len(FIG3_METRICS), figsize=(FIG3_WIDTH_IN, 1.78),
                             sharey=True)
    offs = {"baseline": -0.25, "r5": 0.0, "r1": 0.25}
    for ax, (metric, title) in zip(axes, FIG3_METRICS, strict=True):
        for gi, L in enumerate(letters):
            band = data[L]["oracle"].get(metric)
            if band and band[0] is not None:
                lo, hi = band[0], max(band[1], band[0] + 0.008)
                ax.add_patch(plt.Rectangle((gi - 0.42, lo), 0.84, hi - lo,
                                           facecolor=FIG3_ORACLE_FILL, edgecolor="none",
                                           zorder=0))
                for y in (lo, hi):
                    ax.plot([gi - 0.42, gi + 0.42], [y, y], color=FIG3_ORACLE_EDGE,
                            linewidth=0.5, zorder=1, solid_capstyle="butt")
            for arm in ARM_ORDER:
                vals = [x for x in data[L]["runs"][metric][arm] if x is not None]
                x0 = gi + offs[arm]
                if not vals:
                    if data[L]["runs"][metric][arm]:
                        ax.text(x0, 0.06, "n/a", ha="center", va="bottom", fontsize=6.5,
                                color=FIG3_NA, zorder=3, rotation=90)
                    continue
                k = len(vals)
                xs = [x0 + (j - (k - 1) / 2) * 0.05 for j in range(k)]
                ax.scatter(xs, vals, s=FIG3_SIZE[arm], marker=ARM_MARKERS[arm],
                           c=FIG3_COLOURS[arm], edgecolors="white", linewidths=0.35,
                           zorder=3 if arm != "r1" else 4, clip_on=False)
                mean = sum(vals) / k
                ax.plot([x0 - 0.1, x0 + 0.1], [mean, mean], color=INK, linewidth=0.9,
                        zorder=5, solid_capstyle="butt", clip_on=False)
        ax.set_title(title, fontsize=7.5, pad=3, loc="left")
        ax.set_xlim(-0.55, len(letters) - 0.45)
        # A little room below 0 and above 1, so a run at either end is a whole
        # marker, not a sliver under its mean bar.
        ax.set_ylim(-0.05, 1.05)
        ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
        ax.set_yticklabels(["0", "0.25", "0.50", "0.75", "1"])
        ax.spines["left"].set_bounds(0, 1.0)
        ax.set_xticks(range(len(letters)))
        ax.set_xticklabels([L + ("*" if L == "A" else "") for L in letters])
        ax.yaxis.grid(True, color=GRID, linewidth=0.45, zorder=0)
        ax.set_axisbelow(True)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.tick_params(axis="x", length=0, pad=2)
        ax.tick_params(axis="y", length=2, pad=1.5)
    axes[0].set_ylabel("Share")
    handles = [Line2D([], [], linestyle="none", marker=ARM_MARKERS[a],
                      markersize=3.4 if a != "r1" else 4.2, markerfacecolor=FIG3_COLOURS[a],
                      markeredgecolor="white", markeredgewidth=0.3, label=a)
               for a in ARM_ORDER]
    handles.append(Line2D([], [], color=INK, linewidth=0.9, label="arm mean"))
    handles.append(Patch(facecolor=FIG3_ORACLE_FILL, edgecolor=FIG3_ORACLE_EDGE,
                         linewidth=0.5, label="oracle range (upper reference)"))
    handles.append(Line2D([], [], linestyle="none",
                          label="A*: in-sample for the RBA lexicon fix"))
    fig.legend(handles=handles, loc="upper center", ncol=len(handles), frameon=False,
               fontsize=6.5, bbox_to_anchor=(0.5, 1.0), handletextpad=0.35,
               columnspacing=1.3, handlelength=1.4)
    fig.tight_layout(rect=(0, 0, 1, 0.9), w_pad=0.8)
    png, svg = out_dir / FIG3_PNG, out_dir / "fig5_binding.svg"
    fig.savefig(png, dpi=FIG_DPI, metadata={"Software": None})
    fig.savefig(svg, metadata={"Date": None, "Creator": None})
    plt.close(fig)
    return png, svg

# ------------------------------------------------------------ result figures
# Since 2026-10-21 (the author's request: "thay đổi hoàn toàn cách trình bày, nhất
# là phần Evaluation cho hấp dẫn hơn thay vì bắt người dùng tự phân tích các bảng khô
# khan") the monitor's refusals (formerly Table 1) and what crosses (formerly
# Table 2(a) and the echo column of 2(b)) are figures, each panel titled with what
# it shows. They are drawn from the build's own values (numbers.json), parsed back
# from the strings the text prints, so a figure never shows a figure the text does
# not: _kn, _ci and _pct_range refuse a value in any other form.
FIG_MONITOR_PNG, FIG_MONITOR_CAPTION = "fig3_monitor.png", "fig3_monitor_caption.txt"
FIG_MONITOR_CAPTION_TEXT = "Fig. 3. Monitor refusals (RQ1)."
FIG_CROSS_PNG, FIG_CROSS_CAPTION = "fig4_crossings.png", "fig4_crossings_caption.txt"
FIG_CROSS_CAPTION_TEXT = "Fig. 4. What crosses the boundary and what an adversary matches (RQ2)."
# Result colours, none an arm's (FIG3_COLOURS): a wanted refusal in M's blue, an
# unwanted one in red, none or a neutral count in grey (review of 2026-10-21).
RES_GOOD, RES_BAD, RES_ZERO = "#1f4e8c", "#c0392b", "#9a9993"
RES_TINT_OK, RES_TINT_HIT, RES_TINT_NEUTRAL = "#e1ebf6", "#fbe3c9", "#f1f1ee"


def _kn(s: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)/(\d+)\s*", s or "")
    if not m:
        raise ValueError(f"not a k/N value: {s!r}")
    return int(m.group(1)), int(m.group(2))


def _ci(s: str) -> tuple[float, float] | None:
    m = re.fullmatch(r"\[([\d.]+), ([\d.]+)\]", s or "")
    return (float(m.group(1)), float(m.group(2))) if m else None


def _pct_range(s: str) -> tuple[float, float]:
    m = re.fullmatch(r"([\d.]+)%(?:–([\d.]+)%)?", s or "")
    if not m:
        raise ValueError(f"not a percentage or a range of them: {s!r}")
    lo = float(m.group(1))
    return lo, float(m.group(2) or lo)


def _res_style(plt) -> None:
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Liberation Serif", "DejaVu Serif"],
        "font.size": 7, "axes.edgecolor": INK_2, "axes.labelcolor": INK,
        "xtick.color": INK_2, "ytick.color": INK, "svg.hashsalt": "resfig",
        "svg.fonttype": "none", "axes.linewidth": 0.6,
    })


def monitor_rows(v: dict[str, str]) -> list[list[tuple[str, ...]]]:
    """The two panels of the monitor figure as rows: ("head", text) or
    (label, value key, interval key or "", role, detail), role "wanted" where a
    refusal is wanted and "unwanted" where it is a false positive or a pipeline
    request; detail a muted second label (the masked documents' kept shares)."""
    letters = sorted({k.rsplit("_", 1)[1] for k in v if k.startswith("maskdoc_refused_docs_")})
    a: list[tuple[str, ...]] = [("head", "Refusal wanted")]
    a.append(("Positive control: private sentences", "fp_poscontrol_deployed", "", "wanted",
              ""))
    if letters:
        a.append(("Entity-masked documents, offline (P2):", "", "", "label", ""))
    for L in letters:
        sfx = "_nolost" if f"maskdoc_5gram_pct_nolost_{L}" in v else ""
        dag = "†" if sfx and v.get(f"extraction_docs_lost_{L}", "0") not in ("0", NA) else ""
        a.append((f"   corpus {L}{dag}", f"maskdoc_refused_docs_{L}", "",
                  "wanted", f"kept {v[f'maskdoc_5gram_pct{sfx}_{L}']} of 5-grams, "
                            f"{v[f'maskdoc_surfaces_surviving{sfx}_{L}']} constants"))
    # The pipeline's own runs carry no verdict (the old table's grouping): a refusal
    # there is neither wanted nor a false positive by construction (review of
    # 2026-10-21).
    a.append(("head", "The pipeline's own runs, corpora A–D"))
    a.append(("Egress attempts refused", "op_refused_attempts", "", "neutral",
              f"over {v.get('op_runs', NA)} attempted runs"))
    a.append(("Sections refused by the reintegrator", "op_reintegrator", "", "count", ""))
    a.append(("Relations dropped by the leak gate", "leak_gate_drops_total", "", "count",
              "not a refusal; once per extraction"))
    strata = sorted({k[len("fp_deployed_reset_"):] for k in v
                     if k.startswith("fp_deployed_reset_") and not k.endswith(("_ci", "_rate"))})
    b: list[tuple[str, ...]] = [("head", "Deployed chain")]
    b.append(("All strata", "fp_deployed_reset", "fp_deployed_reset_ci", "unwanted", ""))
    for st in strata:
        b.append((FIG_MONITOR_STRATUM.get(st, st.replace("_", " ")),
                  f"fp_deployed_reset_{st}", f"fp_deployed_reset_{st}_ci", "unwanted", ""))
    b.append(("head", "Each screen alone, all strata"))
    for name in sorted(k[len("fp_standalone_"):] for k in v
                       if k.startswith("fp_standalone_") and k.count("_") == 2):
        b.append((T2_LINTER_LABEL.get(name, f"{name} linter"),
                  f"fp_standalone_{name}", f"fp_standalone_{name}_ci", "unwanted", ""))
    return [a, b]


def monitor_notes(v: dict[str, str]) -> tuple[str, str]:
    """The two panels' notes: (a) how the masked-document figures are read, and
    the lost document of a corpus marked †; (b) what the clean-payload rates are
    and are not."""
    a = ("Masked documents: refused if a corpus 5-gram is kept (true by construction); over\n"
         "each corpus's extractions, the shared one first; shares, counts min–max. Refusals\n"
         "within one run are not independent; counts and the positive control get no interval.")
    lost = [L for L in sorted({k.rsplit("_", 1)[1] for k in v
                               if k.startswith("maskdoc_refused_docs_")})
            if v.get(f"extraction_docs_lost_{L}", "0") not in ("0", NA)
            and f"maskdoc_5gram_pct_nolost_{L}" in v]
    for L in lost:
        pct, kept = (v.get(f"maskdoc_5gram_pct_{L}", NA),
                     v.get(f"maskdoc_surfaces_surviving_{L}", NA))
        a += (f"\n†{L}: over parsed documents; with the unparsed one (unmasked, refused): "
              f"{pct}, {kept}.")
    b = "Wilson 95% intervals. Strata weigh equally, so the all-strata rate\nis not a traffic rate"
    # Each statement only where the build's own keys say so (review of 2026-10-21).
    if v.get("fp_standalone_shingle", "").startswith("0/"):
        b += ("; containment refuses none (a refusal\nwould be a Bloom collision)")
    if v.get("fp_deployed_session") and v.get("fp_deployed_session") == v.get(
            "fp_deployed_reset"):
        b += f"; keeping the carry gives\nthe same {v['fp_deployed_session']}"
    b += "."
    return a, b


FIG_MONITOR_STRATUM = {"abstract_json": "Abstract-payload JSON",
                       "abstract_json_compact": "Compact JSON in one string",
                       "code_snippet": "Code snippets", "english_prose": "English prose",
                       "vietnamese_prose": "Vietnamese prose"}
# Panel geometry, in inches from the figure's left edge: label column, plot, k/N.
FIG_MONITOR_PANELS = ((0.02, 2.50, 3.25, 3.32), (4.40, 5.62, 6.35, 6.42))
FIG_MONITOR_DETAIL_X = 1.02     # where a row's muted detail starts, from its label column
FIG_MONITOR_TITLES = ("(a) Where a refusal is wanted, and the pipeline's own requests",
                      "(b) Clean payloads, where every refusal is a false positive")


def make_fig_monitor(v: dict[str, str], out_dir: Path) -> tuple[Path, Path]:
    """Fig. 3 since 2026-10-21: the monitor's refusals as shares, with their
    Wilson intervals where the build has one and k/N beside each row. Left, where
    a refusal is wanted (the positive control, the entity-masked documents,
    offline) and the pipeline's own requests on corpora A-D; right, the clean
    payloads, where every refusal is a false positive. Green: a wanted refusal;
    red: an unwanted one; grey: none."""
    import matplotlib  # noqa: PLC0415
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415
    _res_style(plt)
    panels = monitor_rows(v)
    n = max(len(p) for p in panels)
    row_h, top, bottom = 0.134, 0.26, 0.64
    height = top + bottom + row_h * n
    fig = plt.figure(figsize=(FIG3_WIDTH_IN, height))
    for (x_lab, x0, x1, x_val), rows, title in zip(FIG_MONITOR_PANELS, panels,
                                                   FIG_MONITOR_TITLES, strict=True):
        ax = fig.add_axes((x0 / FIG3_WIDTH_IN, bottom / height, (x1 - x0) / FIG3_WIDTH_IN,
                           row_h * n / height))
        ys = list(range(n - 1, n - 1 - len(rows), -1))
        blend = matplotlib.transforms.blended_transform_factory(fig.transFigure, ax.transData)
        for y, row in zip(ys, rows, strict=True):
            if row[0] == "head":
                fig.text(x_lab / FIG3_WIDTH_IN, y, row[1], fontsize=6.8, style="italic",
                         color=INK_2, va="center", ha="left", transform=blend)
                continue
            label, key, ci_key, role, detail = row
            if role in ("label", "count"):
                fig.text(x_lab / FIG3_WIDTH_IN + 0.012, y, label, fontsize=6.8, color=INK,
                         va="center", ha="left", transform=blend)
                if detail:
                    fig.text((x_lab + FIG_MONITOR_DETAIL_X + 0.75) / FIG3_WIDTH_IN, y, detail,
                             fontsize=6.5, color=INK_2, va="center", ha="left",
                             transform=blend)
                if role == "count":
                    fig.text(x_val / FIG3_WIDTH_IN, y, v.get(key, NA), fontsize=6.8,
                             color=RES_ZERO, fontweight="bold", va="center", ha="left",
                             transform=blend)
                continue
            val = v.get(key, NA)
            parts = [_kn(x) for x in val.split(";")]
            shares = [k / nn for k, nn in parts]
            ci = _ci(v.get(ci_key, "")) if ci_key else None
            hit = any(x > 0 for x in shares)
            colour = (RES_GOOD if role == "wanted" else RES_ZERO if role == "neutral"
                      else RES_BAD if hit else RES_ZERO)
            if y % 2 == 0:
                ax.axhspan(y - 0.5, y + 0.5, color="#f5f5f2", zorder=0, lw=0)
            for lo_hi in ([ci] if ci else []) + ([(min(shares), max(shares))]
                                                 if len(shares) > 1 else []):
                ax.plot(lo_hi, [y, y], color=colour, lw=2.2, alpha=0.35, zorder=2,
                        solid_capstyle="round")
            ax.scatter(shares, [y] * len(shares), s=15, color=colour, zorder=3,
                       edgecolors="white", linewidths=0.4, clip_on=False)
            fig.text(x_lab / FIG3_WIDTH_IN + 0.012, y, label, fontsize=6.8, color=INK,
                     va="center", ha="left", transform=blend)
            if detail:
                fig.text((x_lab + FIG_MONITOR_DETAIL_X) / FIG3_WIDTH_IN, y, detail,
                         fontsize=6.5, color=INK_2, va="center", ha="left", transform=blend)
            fig.text(x_val / FIG3_WIDTH_IN, y, val.replace("; ", ", "), fontsize=6.8,
                     color=colour, fontweight="bold", va="center", ha="left",
                     transform=blend)
        ax.set_ylim(-0.5, n - 0.5)
        ax.set_yticks([])
        ax.set_xlim(0, 1)
        ax.set_xticks([0, 0.5, 1])
        ax.set_xticklabels(["0%", "50%", "100%"])
        ax.xaxis.grid(True, color=GRID, linewidth=0.45, zorder=0)
        ax.set_axisbelow(True)
        for sp in ("top", "right", "left"):
            ax.spines[sp].set_visible(False)
        ax.tick_params(axis="x", length=2, pad=1.5, labelsize=6.5)
        ax.set_xlabel("share refused", fontsize=6.5, labelpad=1)
        fig.text(x_lab / FIG3_WIDTH_IN, 1 - 0.05 / height, title, fontsize=7.2,
                 fontweight="bold", va="top", ha="left", color=INK)
    # What the old table notes said, under each panel (Table 1's notes until
    # 2026-10-21), so the figure carries its own reading.
    notes = monitor_notes(v)
    for (x_lab, *_rest), note in zip(FIG_MONITOR_PANELS, notes, strict=True):
        fig.text(x_lab / FIG3_WIDTH_IN, 0.04 / height, note, fontsize=6.5, color=INK_2,
                 va="bottom", ha="left", linespacing=1.15)
    png, svg = out_dir / FIG_MONITOR_PNG, out_dir / "fig3_monitor.svg"
    fig.savefig(png, dpi=FIG_DPI, metadata={"Software": None})
    fig.savefig(svg, metadata={"Date": None, "Creator": None})
    plt.close(fig)
    (out_dir / FIG_MONITOR_CAPTION).write_text(FIG_MONITOR_CAPTION_TEXT + "\n",
                                               encoding="utf-8")
    return png, svg


# Fig. 4 (2026-10-21): (a) what crossed per arm, as a grid coloured by what a
# cell means (green: nothing of the kind crossed; amber: something did; grey: a
# count with no good or bad side); (b) the shared extraction's relation predicates
# that echo a corpus n-gram shorter than the monitor's run, against control prose.
FIG_CROSS_COLS = (
    ("Slot ids\nlisted\nper run", "slots"),
    ("Generator-written\nconstants and label\nwords, core-sent (H3)", "h3"),
    ("Extracted-entity\nstrings in core-\nsent content", "core"),
    ("Extracted-entity\nstrings in cloud-\nwritten spans", "cloud"),
    ("Adversary\nmatches: extracted\nentities", "g3e"),
    ("Adversary\nmatches: document\n5-grams", "g3g"),
)


def crossing_cells(v: dict[str, str], arm: str) -> dict[str, tuple[str, str, str]]:
    """Per column: (main text, small text under it, tint)."""
    def tint_count(x: str) -> str:
        return RES_TINT_OK if x == "0" else RES_TINT_HIT
    h3 = (v.get(f"cross_a_{arm}", NA), v.get(f"cross_a_label_{arm}", NA))
    return {
        "slots": (v.get(f"obs_{arm}_slots_adv", NA), "", RES_TINT_NEUTRAL),
        "h3": (f"{h3[0]} and {h3[1]}", f"in {v.get(f'cross_a_scanned_{arm}', NA)} runs",
               RES_TINT_OK if h3 == ("0", "0") else RES_TINT_HIT),
        "core": (v.get(f"cross_b_core_{arm}", NA),
                 f"in {v.get(f'cross_b_scanned_{arm}', NA)} runs",
                 tint_count(v.get(f"cross_b_core_{arm}", NA))),
        # Cloud-written spans are C's own words, not something T sent: no colour.
        "cloud": (v.get(f"cross_b_cloud_{arm}", NA), "", RES_TINT_NEUTRAL),
        "g3e": (v.get(f"g3_entities_{arm}", NA), "", RES_TINT_NEUTRAL),
        "g3g": (v.get(f"g3_5grams_{arm}", NA), "", RES_TINT_NEUTRAL),
    }


def make_fig_crossings(v: dict[str, str], out_dir: Path) -> tuple[Path, Path]:
    """Fig. 4 since 2026-10-21 (formerly Table 2(a) and the echo column of
    Table 2(b)); see FIG_CROSS_COLS."""
    import matplotlib  # noqa: PLC0415
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415
    from matplotlib.patches import FancyBboxPatch  # noqa: PLC0415
    _res_style(plt)
    height = 1.66
    fig = plt.figure(figsize=(FIG3_WIDTH_IN, height))
    # ---- (a) the grid, in inches: arm column, then six equal columns
    x_arm, x0, col_w = 0.02, 0.44, 0.745
    head_y, row_h = height - 0.25, 0.25
    fig.text(0.02 / FIG3_WIDTH_IN, 1 - 0.04 / height,
             "(a) What crossed, per arm (corpora A–D pooled)", fontsize=7.2,
             fontweight="bold", va="top", ha="left", color=INK)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, FIG3_WIDTH_IN)
    ax.set_ylim(0, height)
    ax.axis("off")
    for j, (head, _col) in enumerate(FIG_CROSS_COLS):
        ax.text(x0 + col_w * (j + 0.5), head_y - 0.02, head, fontsize=6.5, color=INK_2,
                ha="center", va="top", linespacing=1.05)
    for i, arm in enumerate(ARM_ORDER):
        yc = head_y - 0.50 - row_h * i
        ax.text(x_arm, yc, arm, fontsize=7, fontweight="bold", va="center", ha="left",
                color=FIG3_COLOURS.get(arm, INK))
        cells = crossing_cells(v, arm)
        for j, (_head, col) in enumerate(FIG_CROSS_COLS):
            main, small, tint = cells[col]
            xc = x0 + col_w * (j + 0.5)
            ax.add_patch(FancyBboxPatch((x0 + col_w * j + 0.025, yc - row_h / 2 + 0.018),
                                        col_w - 0.05, row_h - 0.036,
                                        boxstyle="round,pad=0,rounding_size=0.03",
                                        facecolor=tint, edgecolor="none"))
            if small:
                ax.text(xc, yc + 0.035, main, fontsize=7, ha="center", va="center",
                        color=INK, fontweight="bold")
                ax.text(xc, yc - 0.065, small, fontsize=6.3, ha="center", va="center",
                        color=INK_2)
            else:
                ax.text(xc, yc, main, fontsize=7, ha="center", va="center", color=INK,
                        fontweight="bold")
    note_y = head_y - 0.50 - row_h * (len(ARM_ORDER) - 0.5) - 0.05
    ax.text(x_arm, note_y, "(a) Slot ids: mean [min–max] per run. Constants and label words "
            "(constants that are ordinary English words): occurrences; entity strings: (run, "
            "string) pairs;\nan adversary match's N sums the run's extracted entities "
            "(document 5-grams) over the arm's runs. Blue: none in core-sent content; "
            "amber: some.", fontsize=6.5, color=INK_2, va="top", ha="left", linespacing=1.15)
    # ---- (b) echo against control, per corpus
    letters = sorted({k.rsplit("_", 1)[1] for k in v if k.startswith("pred_echo_pct_shared_")})
    bx0 = x0 + col_w * len(FIG_CROSS_COLS) + 0.55
    fig.text((bx0 - 0.52) / FIG3_WIDTH_IN, 1 - 0.04 / height,
             "(b) Predicates echoing a corpus n-gram", fontsize=7.2,
             fontweight="bold", va="top", ha="left", color=INK)
    fig.text((bx0 - 0.52) / FIG3_WIDTH_IN, 1 - 0.20 / height,
             "shorter than M's 5-word run, so they pass;\nshared extraction; control: "
             "unrelated prose\nof the same lengths", linespacing=1.1,
             fontsize=6.3, style="italic",
             va="top", ha="left", color=INK_2)
    bax = fig.add_axes((bx0 / FIG3_WIDTH_IN, 0.24 / height,
                        (FIG3_WIDTH_IN - bx0 - 0.05) / FIG3_WIDTH_IN, (height - 0.80) / height))
    ys = list(range(len(letters)))[::-1]
    echo = [_pct_range(v[f"pred_echo_pct_shared_{L}"])[0] for L in letters]
    ctrl = [_pct_range(v[f"pred_control_echo_pct_shared_{L}"])[0] for L in letters]
    bh = 0.36
    bax.barh([y + bh / 2 for y in ys], echo, height=bh, color=RES_BAD, alpha=0.85, lw=0)
    bax.barh([y - bh / 2 for y in ys], ctrl, height=bh, color=RES_ZERO, alpha=0.75, lw=0)
    for y, L, e, c in zip(ys, letters, echo, ctrl, strict=True):
        bax.text(e + 1, y + bh / 2, v[f"pred_echo_pct_shared_{L}"], fontsize=6.3,
                 va="center", color=RES_BAD, fontweight="bold")
        bax.text(c + 1, y - bh / 2, v[f"pred_control_echo_pct_shared_{L}"], fontsize=6.3,
                 va="center", color=INK_2)
    from matplotlib.patches import Patch  # noqa: PLC0415
    bax.legend(handles=[Patch(color=RES_BAD, alpha=0.85, label="predicates"),
                        Patch(color=RES_ZERO, alpha=0.75, label="control")],
               fontsize=6.5, frameon=False, loc="lower right", handlelength=0.9,
               handletextpad=0.4, borderaxespad=0.0, labelspacing=0.25)
    bax.set_yticks(ys)
    bax.set_yticklabels([f"corpus {L}" for L in letters], fontsize=6.8)
    bax.set_xlim(0, max(echo) * 2.0)
    bax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(decimals=0))
    bax.tick_params(axis="x", labelsize=6.3, length=2, pad=1)
    bax.tick_params(axis="y", length=0, pad=2)
    for sp in ("top", "right"):
        bax.spines[sp].set_visible(False)
    bax.xaxis.grid(True, color=GRID, linewidth=0.45)
    bax.set_axisbelow(True)
    png, svg = out_dir / FIG_CROSS_PNG, out_dir / "fig4_crossings.svg"
    fig.savefig(png, dpi=FIG_DPI, metadata={"Software": None})
    fig.savefig(svg, metadata={"Date": None, "Creator": None})
    plt.close(fig)
    (out_dir / FIG_CROSS_CAPTION).write_text(FIG_CROSS_CAPTION_TEXT + "\n", encoding="utf-8")
    return png, svg


# Fig. 6 (2026-10-21): RQ4 and RQ5, which had no figure. (a) The judge's means on
# the 1-5 scale, the private arms' against the oracle's, per criterion pooled over
# the private arms and per arm with groundedness excluded, as §6.4 reports them;
# (b) track L in Fig. 3's terms: shares with k/N beside each row.
FIG_QR_PNG, FIG_QR_CAPTION = "fig6_quality_real.png", "fig6_caption.txt"
FIG_QR_CAPTION_TEXT = "Fig. 6. Judged quality (RQ4) and real court judgments (RQ5)."
# The figures the fill takes from the build's output directory, by block id.
DATA_FIGURES = {"fig3": ("fig3_results.png", "fig3_results_caption.txt")}  # make_fig_results
FIG_QR_CRITERIA = (("goal_coverage", "Goal coverage"), ("coherence", "Coherence"),
                   ("specificity", "Specificity"))


def real_rows(v: dict[str, str]) -> list[tuple[str, ...]]:
    """Fig. 6(b)'s rows, as monitor_rows' (label, key, interval key, role, detail)."""
    rows: list[tuple[str, ...]] = [("head", "What M did")]
    # Neutral: the refusals are M's rule at work and also the cost of failing
    # closed (§7, §8); the adversary's recoveries are upper bounds with no arm
    # difference claimed (§6.5). Review of 2026-10-21.
    rows.append(("Collections whose planner request M refused", "l_collections_planner_refused_kn",
                 "", "neutral", ""))
    rows.append(("head", "What crossed in the admitted runs"))
    rows.append(("DIRECT identifier strings", "l_direct_crossed_kn", "", "unwanted", ""))
    rows.append(("QUASI identifier strings", "l_quasi_crossed_kn", "", "unwanted", ""))
    rows.append(("head", "Adversary recoveries, net of control: upper bounds"))
    for arm in ARM_ORDER:
        rows.append((f"   {arm} traces", f"l_g3_{arm}_net_kn", "", "neutral", ""))
    return rows


def make_fig_quality_real(v: dict[str, str], out_dir: Path) -> tuple[Path, Path]:
    """Fig. 6 since 2026-10-21; see FIG_QR_CRITERIA and real_rows."""
    import matplotlib  # noqa: PLC0415
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415
    _res_style(plt)
    rows_b = real_rows(v)
    n = len(rows_b)
    row_h, top, bottom = 0.134, 0.26, 0.64
    height = top + bottom + row_h * n
    fig = plt.figure(figsize=(FIG3_WIDTH_IN, height))
    # ---- (a) judged quality, a dumbbell per row on the 1-5 scale
    items = [(label, f"judge_{c}_private", f"judge_{c}_oracle", "pooled")
             for c, label in FIG_QR_CRITERIA]
    items += [(f"Mean, {arm}", f"judge_mean_exgr_{arm}", "judge_mean_exgr_oracle", arm)
              for arm in ARM_ORDER]
    ax = fig.add_axes((1.25 / FIG3_WIDTH_IN, bottom / height, 1.85 / FIG3_WIDTH_IN,
                       row_h * n / height))
    blend = matplotlib.transforms.blended_transform_factory(fig.transFigure, ax.transData)
    nc = len(FIG_QR_CRITERIA)
    # One row per item, a head row above each group, from the top row down.
    ys = [n - 2 - i for i in range(nc)] + [n - 3 - i for i in range(nc, len(items))]
    fig.text(0.02 / FIG3_WIDTH_IN, n - 1, "Per criterion, private arms pooled", fontsize=6.8,
             style="italic", color=INK_2, va="center", ha="left", transform=blend)
    fig.text(0.02 / FIG3_WIDTH_IN, n - 2 - nc, "Means without groundedness", fontsize=6.8,
             style="italic", color=INK_2, va="center", ha="left", transform=blend)
    for y, (label, kp, ko, who) in zip(ys, items, strict=True):
        pv, ov = float(v[kp]), float(v[ko])
        colour = FIG3_COLOURS.get(who, INK_2)
        ax.plot([pv, ov], [y, y], color=GRID, lw=2.2, zorder=1, solid_capstyle="round")
        ax.scatter([ov], [y], s=15, color="white", edgecolors=INK_2, linewidths=0.8, zorder=3)
        ax.scatter([pv], [y], s=15, color=colour, edgecolors="white", linewidths=0.4,
                   zorder=4)
        ax.text(pv - 0.12, y, v[kp], fontsize=6.5, color=colour, fontweight="bold",
                va="center", ha="right")
        fig.text(0.14 / FIG3_WIDTH_IN, y, label, fontsize=6.8, color=INK, va="center",
                 ha="left", transform=blend)
    ax.text(float(v[items[0][2]]), ys[0] + 0.62, "oracle", fontsize=6.5, color=INK_2,
            ha="center", va="bottom")
    ax.set_xlim(1, 5.25)
    ax.set_ylim(-1.0, n - 0.5)
    ax.set_xticks([1, 2, 3, 4, 5])
    ax.set_yticks([])
    ax.xaxis.grid(True, color=GRID, linewidth=0.45, zorder=0)
    ax.set_axisbelow(True)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(axis="x", length=2, pad=1.5, labelsize=6.5)
    ax.set_xlabel("judged score, 1–5 scale", fontsize=6.5, labelpad=1)
    fig.text(0.02 / FIG3_WIDTH_IN, 1 - 0.05 / height,
             "(a) Judged quality: the private arms against the oracle", fontsize=7.2,
             fontweight="bold", va="top", ha="left", color=INK)
    fig.text(0.02 / FIG3_WIDTH_IN, 0.04 / height,
             "The oracle is the judge model's own unconstrained report, an upper reference;\n"
             f"the gap is not usability. Position bias per judgement: "
             f"{v.get('judge_position_bias', NA)}.", fontsize=6.5, color=INK_2,
             va="bottom", ha="left", linespacing=1.15)
    # ---- (b) track L, in Fig. 3's terms
    x_lab, x0, x1, x_val = 3.62, 5.62, 6.35, 6.42
    bx = fig.add_axes((x0 / FIG3_WIDTH_IN, bottom / height, (x1 - x0) / FIG3_WIDTH_IN,
                       row_h * n / height))
    bblend = matplotlib.transforms.blended_transform_factory(fig.transFigure, bx.transData)
    for y, row in zip(range(n - 1, -1, -1), rows_b, strict=True):
        if row[0] == "head":
            fig.text(x_lab / FIG3_WIDTH_IN, y, row[1], fontsize=6.8, style="italic",
                     color=INK_2, va="center", ha="left", transform=bblend)
            continue
        label, key, _ci_key, role, detail = row
        val = v.get(key, NA)
        k, nn = _kn(val)
        share = k / nn if nn else 0.0
        colour = (RES_GOOD if role == "wanted" and k
                  else RES_BAD if role == "unwanted" and k else RES_ZERO)
        if y % 2 == 0:
            bx.axhspan(y - 0.5, y + 0.5, color="#f5f5f2", zorder=0, lw=0)
        bx.scatter([share], [y], s=15, color=colour, zorder=3, edgecolors="white",
                   linewidths=0.4, clip_on=False)
        fig.text((x_lab + 0.12) / FIG3_WIDTH_IN, y, label, fontsize=6.8, color=INK,
                 va="center", ha="left", transform=bblend)
        fig.text(x_val / FIG3_WIDTH_IN, y, val, fontsize=6.8, color=colour,
                 fontweight="bold", va="center", ha="left", transform=bblend)
        if detail:
            fig.text((x0 - 0.06) / FIG3_WIDTH_IN, y - 0.42, detail, fontsize=5.9, color=INK_2,
                     va="center", ha="right", transform=bblend)
    bx.set_ylim(-0.5, n - 0.5)
    bx.set_yticks([])
    bx.set_xlim(0, 1)
    bx.set_xticks([0, 0.5, 1])
    bx.set_xticklabels(["0%", "50%", "100%"])
    bx.xaxis.grid(True, color=GRID, linewidth=0.45, zorder=0)
    bx.set_axisbelow(True)
    for sp in ("top", "right", "left"):
        bx.spines[sp].set_visible(False)
    bx.tick_params(axis="x", length=2, pad=1.5, labelsize=6.5)
    bx.set_xlabel("share", fontsize=6.5, labelpad=1)
    fig.text(x_lab / FIG3_WIDTH_IN, 1 - 0.05 / height,
             f"(b) Real court judgments: {v.get('l_collections', NA)} collections (track L)",
             fontsize=7.2, fontweight="bold", va="top", ha="left", color=INK)
    fig.text(x_lab / FIG3_WIDTH_IN, 0.04 / height,
             "Refused: the SLM's relation fields echoed a 5-word run; the cost of failing\n"
             "closed. Crossings are conditional on admission; the rule-of-three 95% bound\n"
             f"per DIRECT string, {v.get('l_direct_bound', NA)}, is descriptive. No arm difference "
             "is claimed.",
             fontsize=6.5, color=INK_2, va="bottom", ha="left", linespacing=1.15)
    png, svg = out_dir / FIG_QR_PNG, out_dir / "fig6_quality_real.svg"
    fig.savefig(png, dpi=FIG_DPI, metadata={"Software": None})
    fig.savefig(svg, metadata={"Date": None, "Creator": None})
    plt.close(fig)
    (out_dir / FIG_QR_CAPTION).write_text(FIG_QR_CAPTION_TEXT + "\n", encoding="utf-8")
    return png, svg


# Fig. 3 since later on 2026-10-21 (see BLOCKS): one plain results figure, one
# panel per question of §6, in grey with one accent for r1 and Cloze, no notes in
# the figure (the text and the caption carry the reading). Drawn from numbers.json
# values only, and refused where a value it needs is not in the expected form.
FIG_RESULTS_PNG, FIG_RESULTS_CAPTION = "fig3_results.png", "fig3_results_caption.txt"
# The text width since the ICCIT margins of 2026-10-25 (was FIG3_WIDTH_IN, 7.0 in, which
# the artifact's figures keep); drawn at print size, so its type keeps its point sizes.
FIG_RESULTS_WIDTH_IN = 6.5
# R3(g) of the simulated review of 2026-10-26 (written by the AI assistant at the author's
# request "đồng ý với đề xuất, chỉnh sửa toàn bộ theo yêu cầu"): the printed caption names the
# rule as unvalidated. The placeholder description (BLOCK_DESCRIPTIONS["fig3"],
# make_skeleton.py:227 and the draft's [FIGURE 3 PLACEHOLDER] line) keeps the old title: the
# fill matches marker plus description and removes both, and test_assemble_manuscript.py:558
# and test_make_paper_tables.py:1417-1425 bind the three to the committed skeleton, which this
# revision does not rebuild.
FIG_RESULTS_CAPTION_TEXT = ("Fig. 3. What crosses, attribute accuracy under the unvalidated RBA "
                            "rule, and what it costs.")
FIG_RESULTS_SHADES = {"baseline": "#c9c9c9", "r5": "#8a8a8a", "r1": "#1f4e79",
                      "oracle": "white", "masking": "#6b6b6b"}


def _num(v: dict[str, str], key: str) -> float | None:
    x = v.get(key, NA)
    if x == NA:
        return None
    return float(x)


# Every text in the figure is 7 pt or more and panel (b) says its bars are means
# (pre-submission audit of 2026-10-25), and since 2026-10-26 (R3(g)) that its rule is not
# validated.
def make_fig_results(v: dict[str, str], out_dir: Path) -> tuple[Path, Path]:
    """(a) generator-written constants a masked document keeps per corpus (the
    shared extraction, parsed documents) against Cloze's core-sent content, where
    H3 found none; (b) mean attribute accuracy per corpus and arm, the oracle's
    mean with its min-max; (c) judged quality per arm and the oracle's."""
    import matplotlib  # noqa: PLC0415
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415
    from matplotlib.patches import Patch  # noqa: PLC0415
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Liberation Serif", "DejaVu Serif"],
        "font.size": 7.5, "axes.edgecolor": "#333333", "axes.labelcolor": "#111111",
        "xtick.color": "#111111", "ytick.color": "#333333", "axes.linewidth": 0.6,
        "svg.hashsalt": "results", "svg.fonttype": "none",
    })
    letters = sorted({k.rsplit("_", 1)[1] for k in v
                      if k.startswith("maskdoc_surfaces_surviving_shared_nolost_")})
    if v.get("h3_outcome") != "holds" or any(
            v.get(f"cross_a_{a}") != "0" or v.get(f"cross_a_label_{a}") != "0"
            for a in ARM_ORDER):
        raise ValueError("Fig. 3(a) draws Cloze's constants as zero only where H3 holds "
                         "and every arm's count is 0")
    fig, axes = plt.subplots(1, 3, figsize=(FIG_RESULTS_WIDTH_IN, 1.7),
                             gridspec_kw={"width_ratios": [1.0, 1.55, 0.9]})
    shade = FIG_RESULTS_SHADES
    # (a)
    ax = axes[0]
    xs = range(len(letters))
    kept = [float(v[f"maskdoc_surfaces_surviving_shared_nolost_{L}"]) for L in letters]
    # The masked documents are an offline probe, never sent (M refuses them); hatched,
    # in no arm's colour. Cloze's value is H3's scan of core-sent content, all arms.
    ax.bar([x - 0.19 for x in xs], kept, width=0.36, color="white", edgecolor="#333333",
           hatch="////", lw=0.5)
    ax.scatter([x + 0.19 for x in xs], [0.0] * len(letters), marker="D", s=10,
               color="#111111", zorder=3, clip_on=False)
    for x, k in zip(xs, kept, strict=True):
        ax.text(x - 0.19, k + 0.15, f"{k:g}", ha="center", va="bottom", fontsize=7)
        ax.text(x + 0.19, 0.35, "0", ha="center", va="bottom", fontsize=7)
    ax.set_xticks(list(xs))
    ax.set_xticklabels(letters)
    ax.set_ylim(0, max(kept) * 1.8)
    ax.set_yticks([0, 2, 4, 6])
    ax.set_ylabel("distinct constants")
    ax.set_title("(a) Generator-written constants", fontsize=7.5, loc="left")
    from matplotlib.lines import Line2D  # noqa: PLC0415
    ax.legend(handles=[Patch(facecolor="white", edgecolor="#333333", hatch="////", lw=0.5,
                             label="left by entity masking (offline)"),
                       Line2D([], [], marker="D", ls="none", color="#111111", markersize=3,
                              label="core-sent content (H3)")],
              fontsize=7, frameon=False, loc="upper left", handlelength=1.0,
              borderaxespad=0.1, labelspacing=0.25, handletextpad=0.4)
    # (b)
    ax = axes[1]
    arms = [*ARM_ORDER, "oracle"]
    w = 0.2
    for i, arm in enumerate(arms):
        for gi, L in enumerate(letters):
            x = gi + (i - 1.5) * w
            val = _num(v, f"attr_{arm}_{L}")
            if val is None:
                ax.text(x, 0.02, "n/a", rotation=90, ha="center", va="bottom", fontsize=7,
                        color="#555555")
                continue
            ax.bar(x, val, width=w * 0.92, color=shade[arm], edgecolor="#333333",
                   lw=0.5 if arm == "oracle" else 0)
            if arm == "oracle":
                lo = _num(v, f"attr_oracle_{L}_min")
                hi = _num(v, f"attr_oracle_{L}_max")
                if lo is not None and hi is not None:
                    ax.plot([x, x], [lo, hi], color="#333333", lw=0.6)
    ax.set_xticks(range(len(letters)))
    ax.set_xticklabels([L + ("*" if L == "A" else "") for L in letters])
    # Two lines above the bars since the 6.5 in width of 2026-10-25: on one line the note
    # was wider than the panel and ran into panel (a)'s legend.
    # R3(g) of the simulated review of 2026-10-26 (the AI assistant, at the author's request
    # "đồng ý với đề xuất, chỉnh sửa toàn bộ theo yêu cầu"): the title says the rule is not
    # validated and a third note line gives its held-out κ on r1, a numbers.json value; the
    # y-limit makes room for the third line above the tallest bar and whisker.
    ax.set_ylim(0, 1.5)
    ax.set_yticks([0, 0.5, 1.0])
    ax.spines["left"].set_bounds(0, 1.0)
    ax.set_ylabel("mean attribute accuracy")
    ax.set_title("(b) Attribute accuracy (RBA rule, not validated)", fontsize=7.5, loc="left")
    kappa = presented(v.get("cal_heldout_B_r1_kappa", NA))  # U+2212, as the fill prints the text
    ax.text(len(letters) - 0.5, 1.49,
            f"private-arm bars: means of {v.get('n_registered_repeats', NA)} runs;\noracle: mean "
            f"and min–max; *in-sample;\nrule's held-out κ on r1: {kappa}", ha="right", va="top",
            fontsize=7, color="#333333", linespacing=1.1)
    # (c)
    ax = axes[2]
    vals = [_num(v, f"judge_mean_exgr_{a}") for a in arms]
    ax.bar(range(len(arms)), [x - 1 for x in vals], bottom=1, width=0.62,
           color=[shade[a] for a in arms], edgecolor="#333333",
           linewidth=[0.5 if a == "oracle" else 0 for a in arms])
    for i, x in enumerate(vals):
        ax.text(i, x + 0.08, f"{x:.2f}", ha="center", va="bottom", fontsize=7)
    ax.set_xticks(range(len(arms)))
    ax.set_xticklabels(arms, fontsize=7)
    ax.set_ylim(1, 5.6)
    ax.set_yticks([1, 2, 3, 4, 5])
    ax.set_ylabel("judged quality (1–5)")
    ax.set_title("(c) Judged quality", fontsize=7.5, loc="left")
    for ax in axes:
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.tick_params(length=2, pad=1.5)
    fig.legend(handles=[Patch(facecolor=shade[a], edgecolor="#333333",
                              linewidth=0.5 if a == "oracle" else 0, label=a) for a in arms],
               loc="upper center", ncol=4, frameon=False, fontsize=7,
               bbox_to_anchor=(0.66, 1.0), handlelength=1.0, columnspacing=1.2)
    fig.tight_layout(rect=(0, 0, 1, 0.9), w_pad=1.2)
    png, svg = out_dir / FIG_RESULTS_PNG, out_dir / "fig3_results.svg"
    fig.savefig(png, dpi=FIG_DPI, metadata={"Software": None})
    fig.savefig(svg, metadata={"Date": None, "Creator": None})
    plt.close(fig)
    (out_dir / FIG_RESULTS_CAPTION).write_text(FIG_RESULTS_CAPTION_TEXT + "\n",
                                               encoding="utf-8")
    return png, svg


# ------------------------------------------------------------ Fig. 2

_TOKEN = re.compile(r"⟦(?:SLOT|FACT):[^⟧]+⟧")
_FACT = re.compile(r"⟦FACT:([0-9a-f]{8})\.([A-Z0-9_]+)⟧")
_SLOT = re.compile(r"⟦SLOT:([A-Z_]+)_([0-9a-f]{8})⟧")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z⟦])")

# The writing fallback's Fig. 2 (PRIVDEEP_COMPLETION_PLAN.md §6, gate of Fri 16
# Oct; invoked 2026-09-30, Part D AD31): a listing of at most FIG2_SHORT_LINES
# rendered lines, each at most FIG2_WIDTH characters. 7-pt Courier New holds 108
# on the 6.3-in text width; the margin covers a wider fallback glyph for the
# brackets in Word. A label column of FIG2_LABEL_W characters names the side of
# the boundary; a line too long for the rest wraps under a hanging indent, so a
# wrapped line costs one rendered line more. --fig2-full keeps the full listing.
FIG2_SHORT_LINES = 6
FIG2_WIDTH = 104
FIG2_LABEL_W = 9
FIG2_LABELS = ("SENT", "RECEIVED", "LOCAL")
FIG2_CUT = " …"


def _fig2_rows(text: str) -> int:
    """Rendered lines of `text` in the listing's content column, word-wrapped."""
    import textwrap  # noqa: PLC0415
    return max(1, len(textwrap.wrap(text, FIG2_WIDTH - FIG2_LABEL_W,
                                    break_long_words=True, break_on_hyphens=False)))


def _fig2_cut(text: str) -> tuple[str, bool]:
    """`text` on one rendered line: whole, or cut at the last space that leaves
    room for a visible ellipsis. Returns (line, whether it was cut)."""
    w = FIG2_WIDTH - FIG2_LABEL_W
    if len(text) <= w:
        return text, False
    head = text[:w - len(FIG2_CUT) + 1]
    sp = head.rfind(" ")
    head = head[:sp] if sp > 0 else text[:w - len(FIG2_CUT)]
    return head.rstrip() + FIG2_CUT, True


def _labelled(label: str, texts: list[str]) -> list[str]:
    """The group's label on its first line, the label column blank after it."""
    return [(label if i == 0 else "").ljust(FIG2_LABEL_W) + t for i, t in enumerate(texts)]


@dataclass
class Excerpt:
    run: str
    exchange: int
    stage: str
    sent_lines: list[str]
    cloud_sentence: str
    resolution: str
    checked_surfaces: int
    checked_entities: int
    hits: dict[str, int]
    # For the short listing: the request's slot lines for the sentence's
    # referents, its ATTRIBUTES line and the code lines the sentence uses, all
    # verbatim; and, per token of the sentence, where its value ends in the
    # resolution (so both can be cut after the same token).
    slot_lines: list[str] = field(default_factory=list)
    attr_line: str = ""
    code_lines: list[str] = field(default_factory=list)
    value_ends: list[int] = field(default_factory=list)

    def render(self) -> str:
        return "\n".join([
            f"# Fig. 2 wire excerpt: run {self.run}, exchange {self.exchange} ({self.stage})",
            "# Verbatim from egress_trace.jsonl (SENT, RECEIVED) and report.md (LOCAL).",
            f"# Check: SENT and RECEIVED lines hold none of the corpus's "
            f"{self.checked_surfaces} generator surfaces and none of the run's "
            f"{self.checked_entities} extracted entity strings (whole-token, "
            f"case-insensitive, run_evaluation.token_hits).",
            "# LOCAL is the Tier-3 rendering on the user's machine; it never crosses.",
            "",
            *self.listing_lines()])

    def listing(self) -> str:
        """The excerpt without its '#' header lines: the full listing
        (--fig2-full). The header's bare counts are keys of their own (fig2_*),
        not listing text."""
        return "\n".join(self.listing_lines())

    def listing_lines(self) -> list[str]:
        return [
            "SENT (drafter request, excerpt; [...] marks elided lines):",
            *self.sent_lines,
            "",
            "RECEIVED (the cloud's sentence, with FACT references):",
            self.cloud_sentence,
            "",
            "LOCAL (resolution in report.md):",
            self.resolution,
            ""]

    def _slot_line(self) -> str | None:
        """The slot line of the referent the sentence's first fact reference
        names (its fact stem), else the first slot line, else None."""
        facts = _FACT.findall(self.cloud_sentence)
        first = facts[0][0] if facts else None
        return next((ln for ln in self.slot_lines if first and f"_{first}⟧" in ln),
                    self.slot_lines[0] if self.slot_lines else None)

    def _reply_room(self) -> int:
        """Rendered lines left for RECEIVED and LOCAL: the budget less the
        ATTRIBUTES line and the referent's slot line."""
        return FIG2_SHORT_LINES - 1 - (1 if self._slot_line() else 0)

    def reply_fits(self) -> bool:
        """Whether the short listing shows the sentence and its resolution uncut."""
        return (_fig2_rows(self.cloud_sentence) + _fig2_rows(self.resolution)
                <= self._reply_room())

    def _cut_reply(self) -> tuple[str, str, bool]:
        """The sentence and its resolution cut after the same token, the latest
        one at which both fit the room left; each cut is marked. Uncut (the
        listing then runs over its budget) when not even the first token fits:
        a cut before any reference would show none."""
        toks = list(_TOKEN.finditer(self.cloud_sentence))
        for k in range(len(toks) - 1, -1, -1):
            if k >= len(self.value_ends):
                continue
            s = self.cloud_sentence[:toks[k].end()] + FIG2_CUT
            r = self.resolution[:self.value_ends[k]] + FIG2_CUT
            if _fig2_rows(s) + _fig2_rows(r) <= self._reply_room():
                return s, r, True
        return self.cloud_sentence, self.resolution, False

    def short(self) -> dict[str, Any]:
        """The writing fallback's listing and what it shows: at most
        FIG2_SHORT_LINES rendered lines, every line verbatim from the trace or
        report.md up to a visible ellipsis. SENT: the referent's slot line with
        its fact stem, the ATTRIBUTES line, then the code lines the sentence
        uses, in the order it uses them, while room is left; RECEIVED: the
        sentence; LOCAL: its resolution. The sentence and resolution are never
        cut when they fit; otherwise both are cut after the same token."""
        slot = self._slot_line()
        sent, res, cut = self.cloud_sentence, self.resolution, False
        if not self.reply_fits():
            sent, res, cut = self._cut_reply()
        used = list(dict.fromkeys(c for _, c in _FACT.findall(self.cloud_sentence)))

        def code_of(ln: str) -> str:
            return ln[2:].split(":", 1)[0].strip()
        codes = sorted(self.code_lines,
                       key=lambda ln: used.index(code_of(ln)) if code_of(ln) in used
                       else len(used))
        sent_side = [x for x in (slot, self.attr_line) if x]
        room = FIG2_SHORT_LINES - len(sent_side) - _fig2_rows(sent) - _fig2_rows(res)
        sent_side += codes[:max(room, 0)]
        shown = [_fig2_cut(x) for x in sent_side]
        cut = cut or any(c for _, c in shown)
        lines = (_labelled("SENT", [x for x, _ in shown]) + _labelled("RECEIVED", [sent])
                 + _labelled("LOCAL", [res]))
        # What the request lists that the listing leaves out: the slot lines of
        # the sentence's other referents (the caption says so, so that a fact
        # stem in RECEIVED does not look unissued; review 2026-10-09, F2-sent-lines).
        named = list(dict.fromkeys([h for _, h in _SLOT.findall(self.cloud_sentence)]
                                   + [h for h, _ in _FACT.findall(self.cloud_sentence)]))
        others = [h for h in named if not (slot and f"_{h}⟧" in slot)
                  and any(f"_{h}⟧" in ln for ln in self.slot_lines)]
        facts = _FACT.findall(self.cloud_sentence)
        return {"lines": lines, "cut": cut, "slot": slot is not None,
                "slot_first": bool(slot and facts and f"_{facts[0][0]}⟧" in slot),
                "others": len(others),
                "codes": max(min(room, len(codes)), 0), "codes_used": len(codes),
                "rows": len(shown) + _fig2_rows(sent) + _fig2_rows(res)}

    def short_lines(self) -> list[str]:
        return self.short()["lines"]


def _resolution_match(report: str, sentence: str) -> re.Match[str] | None:
    parts = _TOKEN.split(sentence)
    if len(parts) < 2:
        return None
    # Each reference resolves to at least one character on one line and never spans a
    # sentence end ('. '); the match starts at a word and ends before whitespace, so
    # a decimal value ('75.0%') is not cut at its point by the closing full stop.
    value = r"((?:(?!\.\s)[^\n])+?)"
    rx = r"(?:^|(?<=\s))" + value.join(re.escape(p) for p in parts) + r"(?=\s|$)"
    return re.search(rx, report, re.M)


def _resolution_in(report: str, sentence: str) -> str | None:
    m = _resolution_match(report, sentence)
    return m.group(0) if m else None


def wire_excerpt(run_dir: Path, surfaces: list[str], entities: list[str],
                 max_words: int = 45, prefer_fit: bool = True) -> Excerpt:
    """The first drafter sentence with at least two FACT references that crossed,
    was resolved verbatim into report.md with every fact recorded, and whose sent
    and received excerpt holds no generator surface and no extracted entity.
    With `prefer_fit` (the writing fallback's short listing), a later sentence
    with exactly as many FACT references as that first one is taken instead when
    the first does not fit the short listing uncut and it does
    (Excerpt.reply_fits); when none does, the first is taken and cut. The
    preference never trades fact references for fit. Without it (--fig2-full)
    the first is taken, as before the fallback."""
    from scripts.run_evaluation import token_hits
    trace = [json.loads(ln) for ln in (run_dir / "egress_trace.jsonl")
             .read_text(encoding="utf-8").splitlines() if ln.strip()]
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    needles = list(dict.fromkeys([*surfaces, *entities]))

    def candidates(want: int):
        for i, e in enumerate(trace):
            if e.get("refused") or not str(e.get("stage", "")).startswith("draft"):
                continue
            req = "\n".join(m.get("content", "") if isinstance(m, dict) else str(m)
                            for m in e.get("messages") or [])
            lines = req.splitlines()
            attr_i = next((k for k, ln in enumerate(lines) if ln.startswith("ATTRIBUTES")),
                          None)
            if attr_i is None:
                continue
            for para in (e.get("response_text") or "").split("\n"):
                for sent in _SENT_SPLIT.split(para.strip()):
                    facts = _FACT.findall(sent)
                    if len(facts) < want or len(sent.split()) > max_words:
                        continue
                    m = _resolution_match(report, sent)
                    if m is None or "not recorded" in m.group(0):
                        continue
                    slots = {h for _, h in _SLOT.findall(sent)} | {h for h, _ in facts}
                    codes = {c for _, c in facts}
                    slot_lines = [ln for ln in lines if any(f"_{h}⟧" in ln for h in slots)
                                  and ln.lstrip().startswith("- ⟦SLOT:")]
                    sent_lines = [*slot_lines, "[...]", lines[attr_i]]
                    attr_block = []
                    for ln in lines[attr_i + 1:]:
                        if not ln.startswith("- "):
                            break
                        attr_block.append(ln)
                    kept = [ln for ln in attr_block
                            if ln[2:].split(":", 1)[0].strip() in codes]
                    sent_lines += kept
                    if len(kept) < len(attr_block):
                        sent_lines.append("[...]")
                    wire = "\n".join(sent_lines) + "\n" + sent
                    hits = token_hits(wire, needles)
                    if hits:
                        continue
                    yield Excerpt(run_dir.name, i, str(e.get("stage")), sent_lines, sent,
                                  m.group(0), len(set(surfaces)), len(set(entities)), hits,
                                  slot_lines=slot_lines, attr_line=lines[attr_i],
                                  code_lines=kept,
                                  value_ends=[m.end(g) - m.start()
                                              for g in range(1, (m.re.groups or 0) + 1)])

    def n_refs(ex: Excerpt) -> int:
        return len(_FACT.findall(ex.cloud_sentence))

    for want in (2, 1):
        first = None
        for ex in candidates(want):
            if first is None:
                first = ex
                if not prefer_fit or ex.reply_fits():
                    return ex
            elif n_refs(ex) == n_refs(first) and ex.reply_fits():
                return ex
        if first is not None:
            return first
    raise SystemExit(f"{run_dir}: no drafter sentence with FACT references whose excerpt "
                     "is resolvable and free of generator surfaces and entity strings")


# The caption names the run's corpus, not its run directory and exchange, which are
# the artifact's identifiers (change set of 2026-10-10, FIG-2; review MR10); the
# fig2_run and fig2_exchange keys stay in numbers.json for the artifact.
FIG2_CAPTION_HEAD = "Fig. 2. r1 egress excerpt from a frozen run on corpus «fig2_corpus»: "
FIG2_CAPTION_TAIL = (
    "SENT and RECEIVED hold none of the «fig2_surfaces_checked» rendered forms of the "
    "corpus's generator-written constants and none of the run's «fig2_entities_checked» "
    "extracted entity strings.")
FIG2_CAPTION_LOCAL = ("the cloud's sentence with fact references (RECEIVED); and its local "
                      "resolution (LOCAL), which C never observes. ")
FIG2_CAPTION_SHORT = "Fig. 2. Wire excerpt of arm r1 from a frozen run on corpus «fig2_corpus»."
# The full listing's caption (--fig2-full).
FIG2_CAPTION_FULL = (
    FIG2_CAPTION_HEAD
    + "lines of one drafter request, with its attribute list (SENT); " + FIG2_CAPTION_LOCAL
    + FIG2_CAPTION_TAIL)


def _fig2_codes_phrase(shown: int, used: int) -> list[str]:
    """What the short listing's code lines are: all of the sentence's, or, when
    the six lines leave room for fewer, `shown` of its `used` (the first it
    uses; keys fig2_codes_shown and fig2_codes_used), so the caption never says
    the sentence uses only the lines shown."""
    if not shown:
        return []
    if shown < used:
        return ["«fig2_codes_shown» of the «fig2_codes_used» code lines the sentence uses"]
    return ["the code line" + ("s" if shown > 1 else "") + " the sentence uses"]


def _and(items: list[str], comma: bool = False) -> str:
    """'a', 'a and b' ('a, and b' when a holds a comma, or with `comma`),
    'a, b, and c'."""
    if len(items) < 2:
        return "".join(items)
    if len(items) == 2:
        return items[0] + (", and " if comma or "," in items[0] else " and ") + items[1]
    return ", ".join(items[:-1]) + ", and " + items[-1]


def fig2_caption(ex: Excerpt, full: bool = False) -> str:
    """The caption template for the listing the build writes: the full one, or
    the short one. Since 2026-10-19 (the author's request for short, title-like
    captions) the short one is a title: the listing's own labels name its three
    parts (SENT, RECEIVED, LOCAL), and §4's text states the check that SENT and
    RECEIVED hold no generator-written constant and no extracted entity string
    (fig2_surfaces_checked, fig2_entities_checked). It still says that a line
    ending in an ellipsis is cut there, when one is."""
    if full:
        return FIG2_CAPTION_FULL
    s = ex.short()
    # When the six lines leave room for fewer code lines than the sentence uses,
    # the caption still says so, so it never implies the listing shows them all.
    part = ("" if not s["codes"] or s["codes"] >= s["codes_used"] else
            " SENT shows " + _fig2_codes_phrase(s["codes"], s["codes_used"])[0] + ".")
    # The cut-line convention is §4's text since the review of 2026-10-19 (the
    # caption is a title); "cut" stays in the excerpt's record.
    return FIG2_CAPTION_SHORT + part


def fig2_lines_of(ex: Excerpt, full: bool = False) -> list[str]:
    """The listing the paper shows: the short one, or the full one."""
    return ex.listing_lines() if full else ex.short_lines()


def numbers_from_fig2(nb: Numbers, ex: Excerpt, full: bool = False,
                     corpora: dict[str, str] | None = None) -> None:
    """The header's facts as keys, and every non-empty line of the listing the
    paper shows (the writing fallback's short listing, or with `full` the full
    one) as a key ``fig2_listing_<nn>`` (1-based, in order), so the pasted
    listing is made of tagged values: its resolved figures are the run's, not
    typed text. ``fig2_corpus`` is the run's corpus letter under `corpora`
    (letter -> task id), from the run directory's task; the task id itself when
    no letter maps to it."""
    src = f"{ex.run}/egress_trace.jsonl exchange {ex.exchange} and report.md"
    task = ex.run.split("__")[0]
    letter = next((L for L, t in (corpora or {}).items() if t == task), task)
    nb.put("fig2_corpus", letter, f"{ex.run} (run directory name; task {task})", task,
           "corpus letter of the run's task")
    nb.put("fig2_run", ex.run, src, ex.run, "run directory name")
    nb.put("fig2_exchange", str(ex.exchange), src, ex.exchange, "trace line index")
    nb.put("fig2_surfaces_checked", str(ex.checked_surfaces), src, ex.checked_surfaces,
           "count of the corpus's distinct generator surfaces checked")
    nb.put("fig2_entities_checked", str(ex.checked_entities), src, ex.checked_entities,
           "count of the run's distinct extracted entity strings checked")
    n = 0
    for line in fig2_lines_of(ex, full):
        if line:
            n += 1
            nb.put(f"fig2_listing_{n:02d}", line, src, None,
                   "verbatim listing line" + ("" if full else
                                              "; label column, cut marked with …"))
    nb.put("fig2_lines", str(n), src, n, "count of non-empty listing lines")
    if not full:
        s = ex.short()
        nb.put("fig2_codes_shown", str(s["codes"]), src, s["codes"],
               "count of the sentence's code lines the short listing shows")
        nb.put("fig2_codes_used", str(s["codes_used"]), src, s["codes_used"],
               "count of the ATTRIBUTES code lines the sentence uses")


def check_commit_binding(ev: Src, meta: Src | None, allow: bool) -> None:
    """The --meta freeze_commit is the commit the paper says the numbers come
    from, so it must be one the aggregate records: the aggregate's own
    ``git_commit``, or the single commit every pooled run records (phase one's
    manifest, ``health_gate.outcomes[run].git_commit``, where the aggregate
    carries it, else the measurement's provenance). A prefix of at least seven
    hex digits matches. Otherwise the build stops, unless `allow` (a draft)."""
    fc = meta.data.get("freeze_commit") if meta and isinstance(meta.data, dict) else None
    if fc is None:
        return
    want = str(fc).strip().lower()
    agg = str(ev.data.get("git_commit") or "")
    pooled = sorted({r for a in ARM_ORDER for r in (_ptr(ev.data, _p("arms", a, "runs")) or [])})
    outcomes = _ptr(ev.data, "/health_gate/outcomes") or {}
    prov = {m.get("run"): (m.get("provenance") or {}).get("git_commit")
            for m in ev.data.get("per_task") or []}
    batch = {r: (outcomes.get(r) or {}).get("git_commit") or prov.get(r) for r in pooled}
    commits = sorted({str(c) for c in batch.values() if c})
    hexlike = re.fullmatch(r"[0-9a-f]{7,40}", want) is not None

    def is_(c: str) -> bool:
        return hexlike and c.lower().startswith(want)

    if agg and is_(agg):
        print(f"freeze_commit {fc} is the aggregate's commit")
        if not (pooled and len(commits) == 1 and all(batch.values()) and is_(commits[0])):
            # The aggregate's commit is only where 'aggregate' ran, which can be
            # any commit; the stronger binding is the batch the runs came from.
            print("warning: the pooled runs do not all record freeze_commit ("
                  + (", ".join(c[:12] for c in commits) or "none recorded")
                  + "); the aggregate's commit is where 'aggregate' ran, not where the "
                  "runs were measured", file=sys.stderr)
        return
    if pooled and len(commits) == 1 and all(batch.values()) and is_(commits[0]):
        print(f"freeze_commit {fc} is the commit every pooled run records")
        return
    unrecorded = sorted(r for r, c in batch.items() if not c)
    msg = (f"--meta freeze_commit {fc!r} is neither the aggregate's commit "
           f"({agg[:12] or 'unrecorded'}) nor the one commit of the pooled runs ("
           + (", ".join(c[:12] for c in commits) or "none recorded")
           + (f"; not recorded for {', '.join(unrecorded)}" if unrecorded else "") + ")")
    if not allow:
        raise SystemExit(msg + ". The paper would name a commit its numbers do not come "
                         "from; fix the meta value, or pass --allow-commit-mismatch for a "
                         "draft.")
    print(f"warning: {msg} (allowed: --allow-commit-mismatch)", file=sys.stderr)


def fig2_from_run(run_dir: Path, tasks_path: Path, prefer_fit: bool = True) -> Excerpt:
    from scripts.run_evaluation import _run_entities, load_tasks, surface_groups_for
    tasks = {t.id: t for t in load_tasks(tasks_path)}
    m = json.loads((run_dir / "measurement.json").read_text(encoding="utf-8")) \
        if (run_dir / "measurement.json").exists() else {}
    tid = m.get("task_id") or run_dir.name.split("__")[0]
    if tid not in tasks:
        raise SystemExit(f"{run_dir}: task {tid!r} not in {tasks_path}")
    groups, _ = surface_groups_for(tasks[tid])
    if groups is None:
        raise SystemExit(f"{run_dir}: no generator surfaces for task {tid}")
    surfaces = [s for g in groups.values() for s in g]
    ents, _ = _run_entities(run_dir)
    if ents is None:
        raise SystemExit(f"{run_dir}: no entities.json or extractions.json")
    return wire_excerpt(run_dir, surfaces, [t for t, _ in ents], prefer_fit=prefer_fit)


# ------------------------------------------------------------ build

def _load(path: Path, label: str | None = None) -> Src:
    try:
        return Src(label or path.name, json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        raise SystemExit(f"missing input: {path}") from None


def build(args: argparse.Namespace) -> Numbers:
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    nb = Numbers()
    ev = _load(args.evaluation, "evaluation.json")
    corpora = _corpora(ev)
    runs_dir = getattr(args, "runs", None)
    if runs_dir is not None and not runs_dir.is_dir():
        print(f"warning: no run directories at {runs_dir}; facts_structural is the "
              "aggregate's, which reads a fact store's absent counter as no value",
              file=sys.stderr)
        runs_dir = None
    numbers_from_evaluation(nb, ev, runs_dir)
    probe_paths = args.probe or [Path(p) for p in sorted(glob.glob(
        str(_REPO / "eval" / "probe" / "*.json")))]
    probes = [_load(p, f"probe/{p.name}") for p in probe_paths]
    numbers_from_probes(nb, probes, corpora, measured_letters(ev))
    _check_stub_g1(nb, getattr(args, "allow_stub_g1", False))
    fp = _load(args.fp, "fp_report.json")
    numbers_from_fp(nb, fp)
    numbers_from_deployment(nb, ev, fp, runs_dir)
    numbers_from_observation(nb, _load(args.observation, "observation.json"))
    cal = _load(args.calibration, "calibration.json") if args.calibration else None
    if cal:
        numbers_from_calibration(nb, cal)
    review = getattr(args, "review_analyses", None)
    if review:
        ra = _load(review, "review_analyses.json")
        check_review_inputs(ra, {"evaluation.json": args.evaluation,
                                 "observation.json": args.observation,
                                 "calibration.json": args.calibration})
        if ra.data.get("corpora") != corpora:
            raise SystemExit(f"{review}: corpora {ra.data.get('corpora')} are not the "
                             f"aggregate's {corpora}")
        numbers_from_review(nb, ra)
    meta = _load(args.meta, "meta.json") if args.meta else None
    if meta:
        numbers_from_meta(nb, meta)
    # Track L (scope §12): each input is optional, and without them the build is
    # the A-D build, key for key.
    real_l = getattr(args, "real_l", None)
    sc = _load(real_l, "real_l_scan.json") if real_l else None
    if sc:
        numbers_from_real_l(nb, sc)
    presidio = getattr(args, "presidio", None) or []
    if presidio:
        numbers_from_presidio(nb, [_load(p, f"presidio/{p.name}") for p in presidio], sc)
    cost = getattr(args, "real_l_cost", None)
    if cost:
        numbers_from_real_l_cost(nb, load_real_l_cost(cost))
    sim = getattr(args, "refusal_sim", None)
    if sim:
        numbers_from_refusal_sim(nb, _load(sim, "refusal_sim.json"))
    attempts = getattr(args, "real_l_attempts", None)
    if attempts:
        numbers_from_real_l_attempts(nb, attempts, sc)
    # Scope §13 (2026-10-26): optional, read last, so that every frozen key it
    # reproduced is already built and can be compared; without it the build is
    # the one before, key for key.
    posthoc = getattr(args, "posthoc", None)
    if posthoc:
        ph = _load(posthoc, "posthoc.json")
        check_review_inputs(ph, {"evaluation.json": args.evaluation}, POSTHOC_INSTRUMENT)
        numbers_from_posthoc(nb, ph, corpora)
    check_commit_binding(ev, meta, getattr(args, "allow_commit_mismatch", False))
    check_meta_dates(meta, ev, runs_dir)

    fig2_full = getattr(args, "fig2_full", False)
    ex = (fig2_from_run(args.fig2_run, args.tasks, prefer_fit=not fig2_full)
          if args.fig2_run else None)
    if ex:
        numbers_from_fig2(nb, ex, full=fig2_full, corpora=corpora)

    # The strip plot is the artifact's, not the manuscript's (plan Part D AD33):
    # fig3_points stays a key for it, and no manuscript sentence needs it.
    fig = fig3_points(ev, corpora)
    n_fig = sum(1 for d in fig.values() for a in ARM_ORDER for _, v in d["points"][a]
                if v is not None)
    nb.put("fig3_points", str(n_fig), "evaluation.json#/per_task (pooled, RBA scored)",
           n_fig, "count (the artifact's strip plot)")

    docx = _docx()
    if not args.skeleton.exists():
        raise SystemExit(f"missing skeleton: {args.skeleton} (pass --skeleton)")
    skel = docx.Document(str(args.skeleton))
    wanted = sorted(set(placeholder_keys(skel)))
    missing = [k for k in wanted if k not in nb.values]
    if missing:
        raise MissingKeys(
            f"{args.skeleton} uses keys this build does not produce: {', '.join(missing)}. "
            "Data keys come from the inputs; author keys (names, keywords, commits, "
            "declaration, references) from --meta.")

    _check_short_holds(nb, wanted, getattr(args, "allow_short_repeats", False))

    measured = measured_letters(ev)
    t3_letters = [L for L in corpora if L in measured or f"pred_n_{L}" in nb.values]
    # The properties table is Fig. 2 since 2026-10-19 (the mechanism figure); its
    # builder, table1_from_threat_model, stays for the artifact and the drift tests.
    # Since 2026-10-21 the manuscript's tables are the extraction table and the
    # hypotheses; the monitor's refusals and what crosses are Figs. 3 and 4. table2
    # and table3 still run, for their keys (table3 puts r1_store_cells_<L>) and for
    # the artifact's tables_artifact.docx.
    # Later on 2026-10-21 the manuscript's one table is the hypotheses (Table 1);
    # the monitor, crossings and extraction tables go to tables_artifact.docx.
    old = [table2(nb), table3(nb, corpora, t3_letters,
                              traffic=getattr(args, "traffic_rows", False)),
           table_extraction(nb, corpora, t3_letters), table_hypotheses(nb, reasons=True)]
    specs = [table_hypotheses(nb)]
    write_tables_docx(args.skeleton, specs, out / "tables.docx", nb.values)
    write_tables_docx(args.skeleton, old, out / "tables_artifact.docx", nb.values)

    # Fig. 3 is the per-corpus binding figure since the re-review of 2026-10-18
    # (make_fig3_binding); the RBA strip plot stays the artifact's.
    (out / FIG3_CAPTION).write_text(FIG3_CAPTION_TEXT + "\n", encoding="utf-8")
    try:
        make_fig3(fig, out)
        make_fig3_binding(fig3_binding_points(ev, corpora), out)
        make_fig_monitor(nb.values, out)
        make_fig_crossings(nb.values, out)
        if "l_collections" in nb.values:
            make_fig_quality_real(nb.values, out)
        make_fig_results(nb.values, out)
    except ImportError as exc:
        raise SystemExit(f"matplotlib is required for the strip plot ({exc}); run with "
                         "/usr/bin/python3") from None

    fig2_files = ("fig2_wire_excerpt.txt", "fig2_listing.txt", "fig2_caption.txt")
    if ex:
        (out / "fig2_wire_excerpt.txt").write_text(ex.render(), encoding="utf-8")
        (out / "fig2_listing.txt").write_text(
            "\n".join(fig2_lines_of(ex, fig2_full)) + ("" if fig2_full else "\n"),
            encoding="utf-8")
        (out / "fig2_caption.txt").write_text(fig2_caption(ex, fig2_full) + "\n",
                                              encoding="utf-8")
        rows = None if fig2_full else ex.short()["rows"]
        if rows is not None and rows > FIG2_SHORT_LINES:
            print(f"warning: the Fig. 2 listing takes {rows} rendered lines, more than the "
                  f"writing fallback's {FIG2_SHORT_LINES}: no drafter sentence of "
                  f"{args.fig2_run.name} fits, and cutting it before its first reference "
                  "would show none", file=sys.stderr)
    else:
        # A listing left from an earlier build would be pasted by the fill pass.
        for name in fig2_files:
            (out / name).unlink(missing_ok=True)

    (out / "numbers.json").write_text(
        json.dumps(dict(sorted(nb.values.items())), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    (out / "numbers.sources.json").write_text(
        json.dumps(dict(sorted(nb.sources.items())), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    na = sorted(k for k in wanted if nb.values[k] == NA)
    print(f"wrote {out}/numbers.json ({len(nb.values)} keys; the skeleton uses "
          f"{len(wanted)}), numbers.sources.json, tables.docx ({len(specs)} tables), "
          f"fig3_rba_strip.png/.svg (the artifact's strip plot)"
          + (", fig2_wire_excerpt.txt, fig2_listing.txt ("
             + ("full" if fig2_full else "the writing fallback's short listing")
             + "), fig2_caption.txt" if ex else ""))
    if na:
        print(f"warning: skeleton keys whose value is n/a: {', '.join(na)}")
    thin = sorted(k for k in wanted if k in nb.thin)
    if thin:
        print("warning: skeleton keys that are a mean over fewer runs than the cell has: "
              + ", ".join(f"{k} ({nb.thin[k][0]} of {nb.thin[k][1]})" for k in thin))
    return nb


def short_holds(nb: Numbers) -> dict[str, list[str]]:
    """Outcome keys that read 'holds' although a side was pooled over fewer runs
    than registered, with those sides."""
    return {k: sh for k, sh in nb.caveats.items() if sh and nb.values.get(k) == "holds"}


def _check_short_holds(nb: Numbers, wanted: list[str], allow: bool) -> None:
    short = short_holds(nb)
    used = {k: v for k, v in short.items() if k in wanted}
    for k, v in sorted(short.items()):
        if k not in used:
            print(f"warning: {k} is 'holds' short of the registered repeats: {'; '.join(v)}")
    if used and not allow:
        raise SystemExit(
            "the skeleton quotes an outcome that holds over fewer pooled runs than "
            "registered ('every run' over fewer runs is an easier test): "
            + "; ".join(f"{k} ({', '.join(v)})" for k, v in sorted(used.items()))
            + ". Quote its *_short_of_repeats key beside it, or pass --allow-short-repeats.")
    for k, v in sorted(used.items()):
        print(f"warning: {k} is 'holds' short of the registered repeats (allowed): "
              f"{'; '.join(v)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--evaluation", type=Path, default=_REPO / "eval" / "evaluation.json")
    ap.add_argument("--probe", type=Path, action="append", default=None)
    ap.add_argument("--fp", type=Path, default=_REPO / "eval" / "fp_report.json")
    ap.add_argument("--observation", type=Path, default=_REPO / "eval" / "observation.json")
    ap.add_argument("--calibration", type=Path, default=None)
    ap.add_argument("--review-analyses", type=Path, default=None,
                    help="build: scripts/review_analyses.py output (eval/paper/"
                         "review_analyses.json); each of its figures becomes a key")
    ap.add_argument("--meta", type=Path, default=None)
    ap.add_argument("--real-l", type=Path, default=None, metavar="SCAN_JSON",
                    help="build: scripts/real_l.py scan output (eval/real/out/real_l_scan.json), "
                         "track L's crossings, recall, echo, utility, G3 and HL1 (scope §12); "
                         "its keys are l_* and hl1_*, and hl1_outcome is the scan's own "
                         "decision")
    ap.add_argument("--presidio", type=Path, action="append", default=None,
                    metavar="PRESIDIO_JSON",
                    help="build: scripts/presidio_residual.py output, one file per collection "
                         "(eval/real/out/presidio_<id>.json), repeatable; pooled into "
                         "l_presidio_*, and checked against --real-l's collections and strings")
    ap.add_argument("--real-l-cost", type=Path, default=None, metavar="FILE",
                    help="build: track L's recorded spend, the line scripts/real_l.py budget "
                         "prints (captured to a file) or a JSON object {private, adversary, "
                         "spent_before} in USD; the scan JSON carries no spend")
    ap.add_argument("--refusal-sim", type=Path, default=None, metavar="SIM_JSON",
                    help="build: scripts/real_l_refusal_sim.py output "
                         "(eval/real/out/refusal_sim.json): which collections' planner "
                         "requests the monitor's chain refuses offline and where the corpus "
                         "runs fall (l_sim_*)")
    ap.add_argument("--real-l-attempts", type=Path, default=None, metavar="DIR",
                    help="build: track L's archived attempts (eval/real/attempts): the "
                         "collections whose first run the monitor refused at the planner, "
                         "from the attempts' manifest notes (counts only)")
    ap.add_argument("--posthoc", type=Path, default=None, metavar="POSTHOC_JSON",
                    help="build: scripts/posthoc_2026_10_26.py output (eval/paper/posthoc.json), "
                         "the post-hoc and exploratory analyses of scope §13 (S6's short "
                         "n-grams, S13's judged-quality spread and interval and Cliff's delta); "
                         "keys s6_*, judge_sd_*, judge_minmax_*, judge_ci_* and cliff_*")
    ap.add_argument("--skeleton", type=Path, default=DEFAULT_SKELETON)
    ap.add_argument("--threat-model", type=Path, default=_REPO / "THREAT_MODEL.md")
    ap.add_argument("--fig2-run", type=Path, default=None)
    ap.add_argument("--fig2-full", action="store_true",
                    help="build: paste the full Fig. 2 listing (every excerpted request "
                         "line, with elision markers) instead of the writing fallback's "
                         f"listing of at most {FIG2_SHORT_LINES} lines")
    traffic = ap.add_mutually_exclusive_group()
    traffic.add_argument("--traffic-rows", action="store_true",
                         help="build: put Table 3's per-arm traffic rows (slots on the wire, "
                              "relations, FACT references returned, bytes, tokens) back; they "
                              "are out by default since the author's approval of 2026-10-01 "
                              "(plan Part D AD32), and numbers.json keeps their keys")
    traffic.add_argument("--drop-traffic-rows", action="store_true",
                         help="build: leave the traffic rows out, the default (kept so that "
                              "earlier commands still run)")
    ap.add_argument("--tasks", type=Path, default=_REPO / "eval" / "tasks.json")
    ap.add_argument("--runs", type=Path, default=_REPO / "eval" / "runs",
                    help="build: the run directories the aggregate read; each "
                         "facts_structural cell reads their manifests, so that a fact "
                         "store that recorded no structural fact counts 0, not n/a")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--fill", nargs=2, type=Path, metavar=("SRC", "DST"), default=None)
    ap.add_argument("--banner", default=None,
                    help=f"fill: write this text into every page header, e.g. "
                         f"'{BANNER_PILOT}' for a pilot demo")
    ap.add_argument("--allow-na", action="store_true",
                    help="fill: write n/a into running text instead of refusing (drafts "
                         "only; check_paper_numbers.py still fails on it)")
    ap.add_argument("--allow-commit-mismatch", action="store_true",
                    help="build: let the --meta freeze_commit differ from the commit the "
                         "aggregate records (a warning instead of a refusal; drafts only)")
    ap.add_argument("--allow-stub-g1", action="store_true",
                    help="build: let Table 3's G1 rows rest on the probe's stub extraction "
                         "(a warning and a table note instead of a refusal; drafts only)")
    ap.add_argument("--allow-short-repeats", action="store_true",
                    help="build: let a skeleton outcome read 'holds' over fewer pooled "
                         "runs than registered (a warning instead of a refusal)")
    args = ap.parse_args(argv)
    if args.fill:
        src, dst = args.fill
        if src.resolve() == dst.resolve():
            ap.error("--fill writes a new file; SRC and DST must differ")
        r = fill(src, dst, args.out, banner=args.banner, allow_na=args.allow_na)
        print(f"filled {dst}: {r['replaced']} placeholder(s) replaced, "
              f"{r['values_tagged']} tagged value(s) in all, blocks inserted {r['inserted']}"
              + (f"; left in place (nothing to insert): {r['placeholders_left']}"
                 if r["placeholders_left"] else "")
              + (f"; author text kept after the marker of {r['text_kept']}"
                 if r["text_kept"] else ""))
        if r["na_in_prose"]:
            print(f"warning: n/a written into running text for {', '.join(r['na_in_prose'])} "
                  "(--allow-na); check_paper_numbers.py fails on each")
        return 0
    build(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
