"""scripts/posthoc_2026_10_26.py: the post-hoc analyses of scope §13 (S6, S13).

The n-gram counting, the stopword filter, H3's core-sent pieces, the missing-value
rule, the bootstrap and Cliff's delta are pinned on small synthetic fixtures. The
run over the frozen batch needs the gitignored run directories and the build
outputs under eval/paper/, and is skipped without them. Written by the AI
assistant on 2026-10-26 under scope §13.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from scripts import posthoc_2026_10_26 as P
from shared.shingle_filter import tokenize

REPO = Path(__file__).resolve().parents[3]


def _grams(*texts: str) -> dict[int, set[str]]:
    return P.gram_sets(tokenize(t) for t in texts)


# ------------------------------------------------------------- stopwords

def test_the_stopword_list_is_nltks_127_words_and_each_is_one_token():
    assert len(P.STOPWORDS) == 127
    for w in P.STOPWORDS:
        assert tokenize(w) == [w]
    assert {"the", "of", "s", "t", "don"} <= P.STOPWORDS
    assert not {"budget", "risk", "q3"} & P.STOPWORDS


def test_only_an_ngram_made_entirely_of_stopwords_is_dropped():
    assert not P.informative("of the")
    assert not P.informative("at the to")
    assert P.informative("the budget")
    assert P.informative("budget of the")
    assert _grams("of the at the")[2] == set()


# ---------------------------------------------------------- the counting

def test_counts_are_distinct_shared_ngrams_after_the_monitors_normalisation():
    corpus = _grams("The budget overrun at the Hanoi site was approved.")
    # Fullwidth letters and capitals fold as the monitor folds them, and a
    # repeat adds nothing: the count is of distinct n-grams.
    content = _grams("Ｂｕｄｇｅｔ OVERRUN at the Hanoi; budget overrun at the hanoi")
    c = P.shared_counts(content, corpus)
    # 2: budget overrun, overrun at, the hanoi ('at the' is all stopwords);
    # 3: budget overrun at, overrun at the, at the hanoi; 4: two.
    assert c == {"2": 3, "3": 3, "4": 2, "2-4": 8}
    assert P.ngrams(tokenize("a b c"), 2) == {"a b", "b c"}


def test_no_ngram_spans_two_documents_or_two_streams():
    corpus = _grams("alpha beta", "gamma delta")
    assert P.shared_counts(_grams("beta gamma"), corpus)["2"] == 0
    assert P.shared_counts(_grams("alpha beta gamma delta"), corpus)["2"] == 2
    assert P.shared_counts(P.gram_sets([["alpha"], ["beta"]]), corpus)["2"] == 0


def test_a_slot_placeholder_is_tokens_and_breaks_the_ngram_it_sits_in():
    corpus = _grams("paid Acme Ltd the fee")
    masked = _grams("paid ⟦SLOT:ORG_1a2b3c4d⟧ the fee")
    assert P.shared_counts(masked, corpus) == {"2": 1, "3": 0, "4": 0, "2-4": 1}  # 'the fee'


# ------------------------------------------------- H3's core-sent pieces

GOAL = "Assess the risks now."
TRACE = [
    {"stage": "plan", "system": "You plan.", "tools": None, "refused": False,
     "messages": [{"role": "user", "content": "Goal: Assess the risks now.\nbudget overrun"}],
     "response_text": "Section Alpha Title\nok", "structured": {"title": "Risk register review"}},
    {"stage": "draft:s1", "system": "", "tools": None, "refused": False,
     "messages": [{"role": "user", "content": "Write Risk register review using budget overrun"}],
     "response_text": "Drafted text here", "structured": None},
    {"stage": "draft:s2", "system": "", "tools": None, "refused": True,
     "messages": [{"role": "user", "content": "Hanoi site details"}],
     "response_text": "", "structured": None},
]
CORPUS = ("Write using budget overrun. Risk register review. Assess the risks now. "
          "Hanoi site details. Drafted text here.")


def test_core_sent_content_leaves_out_the_goal_echoes_replies_and_refused_requests():
    segs = P.core_sent_segments(TRACE, GOAL)
    toks = [t for s in segs for t in tokenize(s)]
    for absent in ("assess", "risks", "register", "hanoi", "drafted"):
        assert absent not in toks
    assert toks.count("budget") == 2 and "write" in toks and "using" in toks
    c = P.shared_counts(P.gram_sets(tokenize(s) for s in segs), _grams(CORPUS))
    # 'budget overrun', 'using budget' and 'using budget overrun'; nothing that
    # joins 'Write' to 'using' across the cut-out echo.
    assert c == {"2": 2, "3": 1, "4": 0, "2-4": 3}


def test_the_texts_own_line_breaks_do_not_end_a_piece():
    trace = [{"stage": "plan", "system": "", "tools": None, "refused": False,
              "messages": [{"role": "user", "content": "budget\noverrun"}],
              "response_text": "", "structured": None}]
    segs = P.core_sent_segments(trace, GOAL)
    assert P.shared_counts(P.gram_sets(tokenize(s) for s in segs),
                           _grams("budget overrun"))["2"] == 1


# ------------------------------------------------------- per-run values

def test_judged_quality_is_the_runs_mean_without_groundedness():
    crit = ["goal_coverage", "coherence", "groundedness", "specificity"]
    js = [{"criteria": crit, "private": {"goal_coverage": 3, "coherence": 3,
                                         "groundedness": 1, "specificity": 0}},
          {"criteria": crit, "private": {"goal_coverage": 2, "coherence": 2,
                                         "groundedness": 5, "specificity": 2}}]
    assert P.judged_quality(js) == pytest.approx((2 + 2) / 2)
    assert P.judged_quality([]) is None


def test_the_missing_value_rule_is_the_aggregates():
    def f(**private):
        return {"private": private}
    assert P.run_rate(f(attribute_accuracy=0.5), "attribute_accuracy") == 0.5
    assert P.run_rate(f(attribute_accuracy=None), "attribute_accuracy") is None
    assert P.run_rate(f(attribute_accuracy=math.nan), "attribute_accuracy") is None
    assert P.run_rate(None, "rba") is None
    assert P.run_rate({"private": None}, "rba") is None
    # An RBA on fewer than MIN_RBA_POOL (5) scored occurrences is no value.
    assert P.run_rate(f(rba=0.75, denominators={"full": 4}), "rba") is None
    assert P.run_rate(f(rba=0.75, denominators={"full": 5}), "rba") == 0.75
    assert P.run_rate(f(attribute_accuracy=0.4, denominators={"full": 0}),
                      "attribute_accuracy") == 0.4


def test_a_lost_document_is_one_whose_every_reply_was_dropped():
    ex = {"documents": [
        {"doc_id": "a", "chunks": 2, "dropped_malformed": 2, "entities": [], "relations": []},
        {"doc_id": "b", "chunks": 2, "dropped_malformed": 1, "entities": [], "relations": []},
        {"doc_id": "c", "chunks": 1, "dropped_malformed": 1, "entities": [{"t": 1}],
         "relations": []},
        {"doc_id": "d", "chunks": 0, "dropped_malformed": 0}]}
    assert P.lost_documents(ex) == ["a"]


# ----------------------------------------------------------- statistics

def test_cliffs_delta_on_hand_worked_examples():
    assert P.cliffs_delta([3, 4], [1, 2])["delta"] == 1.0
    assert P.cliffs_delta([1, 2], [3, 4])["delta"] == -1.0
    d = P.cliffs_delta([3, 4], [1, 3])     # >, =, >, >
    assert (d["n1"], d["n2"], d["greater"], d["less"], d["ties"]) == (2, 2, 3, 0, 1)
    assert d["delta"] == 0.75
    assert P.cliffs_delta([1, 2, 3], [2, 2])["delta"] == 0.0
    # A missing run value is left out, and no value on a side gives None.
    d = P.cliffs_delta([0.8, None, 0.7], [0.5, None, None])
    assert (d["n1"], d["n2"], d["delta"]) == (2, 1, 1.0)
    d = P.cliffs_delta([None, None], [0.5])
    assert (d["n1"], d["n2"], d["delta"]) == (0, 1, None)


def test_the_percentile_interval_takes_order_statistics():
    assert P.percentile_ci(list(range(10_000))) == [250, 9749]
    assert P.percentile_ci([]) is None


def test_the_bootstrap_is_deterministic_for_the_seed_and_brackets_the_mean():
    v = [1.0, 2.31, 2.5, 4.07, 1.52, 3.3, 0.97, 2.86]
    a = P.bootstrap_mean_ci(v, resamples=2000, seed=P.BOOTSTRAP_SEED)
    assert a == P.bootstrap_mean_ci(v, resamples=2000, seed=P.BOOTSTRAP_SEED)
    assert a != P.bootstrap_mean_ci(v, resamples=2000, seed=P.BOOTSTRAP_SEED + 1)
    assert min(v) <= a[0] <= sum(v) / len(v) <= a[1] <= max(v)
    assert P.bootstrap_mean_ci([2.0] * 6, resamples=100) == [2.0, 2.0]
    assert P.bootstrap_mean_ci([]) is None
    assert P.BOOTSTRAP_RESAMPLES == 10_000 and P.BOOTSTRAP_SEED == 20261026


def test_spread_uses_the_sample_sd():
    s = P.spread([1.0, 2.0, 3.0])
    assert (s["n"], s["mean"], s["sd"], s["min"], s["max"]) == (3, 2.0, 1.0, 1.0, 3.0)
    assert P.spread([2.0])["sd"] is None


def test_mismatches_name_every_key_that_differs_or_is_absent():
    assert P.mismatches({"a": "0.50", "b": "1/3"}, {"a": "0.50", "b": "1/3"}) == []
    bad = P.mismatches({"a": "0.50"}, {"a": "0.51", "c": "2"})
    assert len(bad) == 2 and bad[0].startswith("a:") and "(absent)" in bad[1]


# ------------------------------------------------- the frozen batch itself

FROZEN = all(p.exists() for p in (REPO / "eval" / "runs", REPO / "eval" / "evaluation.json",
                                  REPO / "eval" / "paper" / "numbers.json",
                                  REPO / "eval" / "probe" / "smoke-q3.json"))


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


@pytest.mark.skipif(not FROZEN, reason="needs the frozen run directories (gitignored) and "
                                       "eval/paper/numbers.json")
def test_the_frozen_batch_reproduces_and_the_output_holds_no_corpus_text(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    assert P.main(["--out", str(a)]) == 0
    assert P.main(["--out", str(b)]) == 0
    assert a.read_bytes() == b.read_bytes()
    out = json.loads(a.read_text("utf-8"))
    assert set(out["s6"]) == {"A", "B", "C", "D"}
    for c in out["s6"].values():
        assert c["n_runs"] == len(c["runs"]) == 9
        for k in ("2", "3", "4", "2-4"):
            vals = [r[k] for r in c["runs"].values()]
            assert c["range_over_runs"][k] == {"min": min(vals), "max": max(vals)}
        assert c["masked_documents"]["2-4"] == sum(c["masked_documents"][k] for k in "234")
    q = out["s13"]["judged_quality"]
    assert set(q) == {"baseline", "r5", "r1"} and all(x["n"] == 12 for x in q.values())
    # No string outside the notes carries a corpus 3-gram.
    corpus = P.gram_sets(tokenize(d.text) for c in out["s6"].values()
                         for d in P.T.load_corpus(REPO / c["corpus"]).docs)
    data = {k: v for k, v in out.items() if k != "_notes"}
    for s in _strings(data):
        assert not (P.gram_sets([tokenize(s)])[3] & corpus[3]), s[:20]
