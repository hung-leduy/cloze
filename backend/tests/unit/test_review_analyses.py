"""scripts/review_analyses.py: the review's analyses from frozen data.

The statistics are pinned on hand-worked examples, the chance model and the
slot counting on a toy key, the lexical overlap and the fact kinds on the
tracked keys and corpora (synthetic, committed), and the calibration sheet's
status on a sheet written here. The run over the frozen batch itself needs the
gitignored run directories and is skipped without them.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import pytest
from privdeep.eval.faithfulness import MATCH, MISMATCH, UNRESOLVED, FactKey, load_key, score

from scripts import review_analyses as RA

REPO = Path(__file__).resolve().parents[3]
KEY_B = REPO / "eval" / "corpora" / "portfolio-b" / "smoke_fact_key.json"
M, X, U = MATCH, MISMATCH, UNRESOLVED


# ------------------------------------------------------------- statistics

def test_agreement_statistics_match_a_hand_worked_example():
    human = [M, M, M, X, U]
    rule = [M, M, X, X, U]
    a = RA.agreement(human, rule, resamples=50, seed=1)
    assert (a["k"], a["n"], a["p_o"]) == (4, 5, 0.8)
    # p_e = .6*.4 + .2*.4 + .2*.2 = .36; kappa = (.8 - .36) / .64
    assert a["kappa_pe"] == pytest.approx(0.36)
    assert a["kappa"] == pytest.approx(0.6875)
    # PABAK over three categories: (3 * .8 - 1) / 2
    assert a["pabak"] == pytest.approx(0.7)
    # AC1: pi = (.5, .3, .2); p_e = (.25 + .21 + .16) / 2 = .31
    assert a["ac1"] == pytest.approx((0.8 - 0.31) / 0.69)
    assert a["human"] == {M: 3, X: 1, U: 1} and a["rule"] == {M: 2, X: 2, U: 1}
    assert a["confusion"][M] == {M: 2, X: 1, U: 0}
    assert sum(v for row in a["confusion"].values() for v in row.values()) == 5


def test_the_kappa_paradox_is_visible_beside_kappa():
    """High raw agreement on a skewed marginal: kappa near zero, PABAK and AC1
    high. This is why the review asks for both beside kappa."""
    human = [M] * 37 + [X] * 3
    rule = [M] * 34 + [X] * 3 + [M] * 3
    a = RA.agreement(human, rule, resamples=10, seed=1)
    assert a["p_o"] == pytest.approx(34 / 40)
    assert a["kappa"] < 0.1
    assert a["pabak"] > 0.7 and a["ac1"] > 0.8


def test_a_label_outside_the_three_categories_is_refused():
    with pytest.raises(ValueError, match="outside"):
        RA.agreement([M, "AMBIGUOUS"], [M, M], resamples=1, seed=1)
    with pytest.raises(ValueError, match="different numbers"):
        RA.agreement([M], [M, M], resamples=1, seed=1)


def test_the_bootstrap_is_seeded_and_counts_undefined_resamples():
    human = [M, M, X, X, U, M, X, M]
    rule = [M, X, X, M, U, M, X, M]
    a = RA.bootstrap_kappa(human, rule, resamples=500, seed=7)
    assert a == RA.bootstrap_kappa(human, rule, resamples=500, seed=7)
    assert a["ci95"] != RA.bootstrap_kappa(human, rule, resamples=500, seed=8)["ci95"]
    lo, hi = a["ci95"]
    assert -1 <= lo <= hi <= 1
    # One category throughout: kappa is undefined on every resample.
    same = RA.bootstrap_kappa([M] * 5, [M] * 5, resamples=40, seed=1)
    assert same == {"ci95": None, "resamples": 40, "undefined": 40}


def test_each_row_has_its_own_seed():
    assert RA._row_seed(1, "dev_A_r1") == RA._row_seed(1, "dev_A_r1")
    assert RA._row_seed(1, "dev_A_r1") != RA._row_seed(1, "heldout_B_r1")


def test_percentile_interval_takes_the_order_statistics():
    assert RA.percentile_ci(list(range(100))) == [2, 97]
    assert RA.percentile_ci([0.5]) == [0.5, 0.5]
    assert RA.percentile_ci([]) is None


# --------------------------------------------------------- chance model

TOY = FactKey(
    referents={"P": ["Project P"], "Q": ["Project Q"]},
    attributes={"AUTHORISED": ["authorised"], "SPENT": ["spent"]},
    facts=[{"fact_id": f"{s}.{a}", "subject": s, "subjects": [s], "attribute": a,
            "value": v, "match": "numeric", "derived": False}
           for s, a, v in (("P", "AUTHORISED", 100.0), ("P", "SPENT", 50.0),
                           ("Q", "AUTHORISED", 200.0), ("Q", "SPENT", 80.0))],
    string_facts=[], mask_patterns=[])
REPORT = ("Project P was authorised 200.00 USD.\n\n"
          "Project Q spent 100.00 USD.\n")


def test_the_chance_model_is_the_share_of_gold_slots_carrying_the_named_binding():
    res = score(REPORT, TOY)
    # Four gold slots, one per value, and a slot with no numeral (ignored).
    c = RA.chance_cell([[100.0, 50.0, 200.0, 80.0, None]], [res], TOY)
    # Each attribute is carried by 2 of 4 slots; each (referent, attribute) by 1.
    assert c["attribute"] == {"n": 2, "chance": 0.5, "observed_k": 1, "observed": 0.5}
    assert c["full"] == {"n": 2, "chance": 0.25, "observed_k": 0, "observed": 0.0}
    # Two spellings of one amount are two baseline slots: P's authority is then
    # carried by 2 of 5 slots, and AUTHORISED by 3 of 5.
    c2 = RA.chance_cell([[100.0, 100.0, 50.0, 200.0, 80.0]], [res], TOY)
    assert c2["attribute"]["chance"] == pytest.approx((3 / 5 + 2 / 5) / 2)
    # No gold slot: nothing to guess from, so no occurrence is counted.
    assert RA.chance_cell([[None]], [res], TOY)["attribute"]["n"] == 0
    pooled = RA._pool_chance([c["attribute"], c2["attribute"]])
    assert pooled["n"] == 4 and pooled["observed_k"] == 2


def test_money_slots_follow_each_arms_keying():
    ents = [{"text": "100.00 USD", "category": "MONEY"},
            {"text": "100 USD", "category": "MONEY"},
            {"text": "Scheme spend", "category": "MONEY"},
            {"text": "Project P", "category": "PROJECT"}]
    assert sorted(RA.money_slots(ents, "baseline"), key=str) == [100.0, 100.0, None]
    assert sorted(RA.money_slots(ents, "r5"), key=str) == [100.0, None]


# ------------------------------------------------------- lexical overlap

def test_the_derived_codes_meanings_bind_to_other_attributes_under_the_rule():
    keys = {p.parent.name: load_key(p)
            for p in sorted((REPO / "eval" / "corpora").glob("*/smoke_fact_key.json"))}
    lx = RA.lexical_overlap(keys, [])
    assert lx["lexicons_identical_across_keys"]
    assert lx["money_codes"]["own_only"] == ["AUTHAMT", "SPENTAMT"]
    assert lx["money_codes"]["other_only"] == ["UNSPNTAM", "OVRRUNAM", "PCTSPENT"]
    assert set(lx["phrases_in_meanings"]) <= set(RA._lexicon(keys)[0])
    assert lx["r1_draft_requests"] == 0 and lx["usage"]["oracle"]["hits"] == 0
    assert len(lx["codes"]) == 13


# ------------------------------------------------------------ fact kinds

@pytest.mark.parametrize(("corpus", "kinds"), [
    ("portfolio-b", {"table": 8, "prose": 6, "derived": 4}),
    ("prose-c", {"table": 0, "prose": 11, "derived": 3}),
])
def test_fact_kinds_split_stated_facts_by_where_the_documents_state_them(corpus, kinds):
    d = REPO / "eval" / "corpora" / corpus
    k = RA.fact_kinds(RA._docs(d), json.loads((d / "smoke_fact_key.json").read_text("utf-8")))
    assert {x: len(v) for x, v in k.items()} == kinds


# --------------------------------------------------------- calibration

def _sheet(path: Path, labels: list[tuple[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=("id", "section", "before", "sentence", "numeral",
                                           "referent_label", "attribute_label", "note"))
        w.writeheader()
        for i, (ref, att) in enumerate(labels, 1):
            w.writerow({"id": i, "sentence": "x", "numeral": "1",
                        "referent_label": ref, "attribute_label": att})


def test_a_sheet_not_fully_labelled_gives_its_status_and_no_figures(tmp_path):
    report = tmp_path / "r.md"
    report.write_text("nothing\n", encoding="utf-8")
    sheet = tmp_path / "s.csv"
    _sheet(sheet, [("", ""), ("", "")])
    row = RA.calibration_row("heldout_B_baseline", report, sheet, KEY_B, resamples=5, seed=1)
    assert row["status"] == "unlabelled" and "kappa" not in row
    assert (row["labeller"], row["blind"], row["in_sample"]) == ("author", True, False)
    _sheet(sheet, [("HALCYON", "SPENT"), ("", "")])
    row = RA.calibration_row("heldout_B_baseline", report, sheet, KEY_B, resamples=5, seed=1)
    assert row["status"] == "incomplete" and row["sheet_rows_labelled"] == 1
    assert RA.calibration_row("heldout_B_baseline", None, sheet, KEY_B, resamples=5,
                              seed=1)["status"] == "report absent"


def test_a_recorded_row_must_be_reproduced():
    row = {"id": "dev_A_r1", "status": "labelled", "occurrences": 21,
           "agreement": {"k": 20, "n": 21}, "kappa": 0.64407}
    RA._check_recorded(row, {"occurrences": 21, "agreement": {"k": 20, "n": 21},
                             "kappa": 0.644})
    with pytest.raises(SystemExit, match="calibration.json records"):
        RA._check_recorded(row, {"occurrences": 21, "agreement": {"k": 19, "n": 21},
                                 "kappa": 0.644})
    with pytest.raises(SystemExit, match="calibration.json records"):
        RA._check_recorded(row, {"occurrences": 21, "agreement": {"k": 20, "n": 21},
                                 "kappa": 0.65})


def test_a_cell_under_blind_labelling_has_its_per_run_figures_withheld(tmp_path):
    """The run whose report is being labelled, and its cell-mates, whose records
    would give it by subtraction from the cell's totals; not another arm's."""
    runs = []
    for name, arm, text in (("b__baseline", "baseline", "the labelled report\n"),
                            ("b__baseline__rep2", "baseline", "a second\n"),
                            ("b__r1", "r1", "the labelled report\n" * 2)):
        d = tmp_path / name
        d.mkdir()
        (d / "report.md").write_text(text, encoding="utf-8")
        runs.append(RA.Run(name, "b", "B", arm, 1, d, {}, {}, "", "", [], []))
    copy = tmp_path / "sheet_report.md"
    copy.write_text("the labelled report\n", encoding="utf-8")
    rows = [{"id": "heldout_B_baseline", "status": "unlabelled", "report": str(copy)},
            {"id": "heldout_B_r1", "status": "labelled", "report": str(copy)}]
    out = RA.pending_blind_runs(rows, runs)
    assert sorted(out) == ["b__baseline", "b__baseline__rep2"]
    assert "heldout_B_baseline" in out["b__baseline"]
    rows[0]["status"] = "labelled"
    assert RA.pending_blind_runs(rows, runs) == {}


# ------------------------------------------------------------- helpers

def test_a_lost_document_is_one_whose_every_reply_was_dropped():
    ext = {"documents": [
        {"doc_id": "a", "chunks": 1, "dropped_malformed": 1, "entities": 0, "relations": 0},
        {"doc_id": "b", "chunks": 2, "dropped_malformed": 1, "entities": 0, "relations": 0},
        {"doc_id": "c", "chunks": 1, "dropped_malformed": 1, "entities": 3, "relations": 0},
        {"doc_id": "d", "chunks": 1, "dropped_malformed": 0, "entities": 4, "relations": 2}]}
    assert RA._lost(ext) == ["a"]


def test_deployment_tokens_are_the_planner_and_drafter_exchanges():
    trace = [{"stage": "plan", "input_tokens": 10, "output_tokens": 2},
             {"stage": "draft:s1", "input_tokens": 5, "output_tokens": 1},
             {"stage": "draft:s2", "input_tokens": 7, "output_tokens": None},
             {"stage": "planner", "input_tokens": 99, "output_tokens": 99}]
    assert RA._usage(trace, "plan") == {"input_tokens": 10, "output_tokens": 2}
    assert RA._usage(trace, "draft") == {"input_tokens": 12, "output_tokens": 1}


# ------------------------------------------------- the frozen batch itself

FROZEN = (REPO / "eval" / "runs").is_dir() and (REPO / "eval" / "evaluation.json").is_file()


@pytest.mark.skipif(not FROZEN, reason="needs the frozen run directories (gitignored)")
def test_the_frozen_batch_reproduces_and_the_output_is_deterministic(tmp_path):
    def args(out: Path) -> argparse.Namespace:
        return argparse.Namespace(
            evaluation=REPO / "eval" / "evaluation.json", runs=REPO / "eval" / "runs",
            tasks=REPO / "eval" / "tasks.json", observation=REPO / "eval" / "observation.json",
            calibration=REPO / "eval" / "calibration" / "calibration.json", probe=None,
            insample_report=None, bootstrap=200, seed=RA.BOOTSTRAP_SEED, out=out)
    a = RA.build(args(tmp_path / "a.json"))
    assert a == RA.build(args(tmp_path / "b.json"))
    recorded = {r["id"] for r in json.loads(
        (REPO / "eval" / "calibration" / "calibration.json").read_text("utf-8"))["rows"]}
    for row in a["calibration"]["rows"]:
        assert row["status"] in ("labelled", "unlabelled", "incomplete", "report absent")
        if row["id"] in recorded and row["id"] != "insample_A_baseline":
            assert row["status"] == "labelled"
    text = json.dumps(a)
    assert "«" not in text and "»" not in text
    assert a["cost"]["totals"]["deploy_input_tokens"] > 0
