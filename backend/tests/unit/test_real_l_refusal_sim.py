"""scripts/real_l_refusal_sim.py, offline, on an invented two-document corpus.

No TAB text is read: the documents, entities and relations here are made up.
What is pinned: a clean extraction passes the monitor in every arm; a relation
field holding a six-word run of a document is refused with the pilot's reason
string and attributed to that field; a run spread over two fields of one
relation, which no field holds alone, is still refused (the monitor's
whole-body stream) and reported as straddling; a goal holding a run is
attributed to the goal; the output carries counts and never a string of the
corpus; the monitor's module state is restored; and the self-check reads the
pilot manifest's counts and says whether the extraction is the pilot's.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from privdeep.ingest import load
from privdeep.tier1_local.extraction_io import dump_extractions
from privdeep.tier1_local.ontology_extractor import ConceptRelation, Extraction
from privdeep.tier1_local.slot_masker import Entity

from scripts import real_l_refusal_sim as S

GOAL = "Compare the two memos and summarise what the board decided."
DOC1 = ("# Quillon memo\n\nThe Quillon review board met on 3 March 2031 at the Marlbury depot. "
        "Harriet Vossberg presented the quarterly ledger and asked for a delay of the Tarnmoor "
        "rollout until the vendor Ostrava Logistics confirms the second shipment.\n")
DOC2 = ("# Tarnmoor note\n\nOstrava Logistics wrote to Harriet Vossberg about the Tarnmoor "
        "rollout. The second shipment reaches the Marlbury depot in April 2031, and the board "
        "will decide then.\n")
ENTITIES = {
    1: [Entity("Harriet Vossberg", "PERSON"), Entity("Marlbury depot", "LOCATION"),
        Entity("Ostrava Logistics", "ORG"), Entity("Tarnmoor rollout", "PROJECT"),
        Entity("3 March 2031", "DATE")],
    2: [Entity("Ostrava Logistics", "ORG"), Entity("Harriet Vossberg", "PERSON"),
        Entity("Tarnmoor rollout", "PROJECT"), Entity("Marlbury depot", "LOCATION"),
        Entity("April 2031", "DATE")],
}
CLEAN = [ConceptRelation("REVIEW_BOARD", "meets at", "FACILITY"),
         ConceptRelation("EXECUTIVE", "requests postponement of", "INITIATIVE")]
# Six consecutive words of DOC1, holding no entity string: 2 five-grams + 1 six-gram.
RUN = "asked for a delay of the"
PILOT_REASON = "RAW_CONTEXT_CONTAINMENT: 1 shingle hit(s) >= 1"


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("corpora") / "synth-a"
    d.mkdir()
    (d / "doc1.md").write_text(DOC1, encoding="utf-8")
    (d / "doc2.md").write_text(DOC2, encoding="utf-8")
    return d


def _extraction(corpus: Path, rel1: list[ConceptRelation], rel2: list[ConceptRelation]) -> dict:
    docs = [load(corpus / "doc1.md"), load(corpus / "doc2.md")]
    exs = [Extraction(entities=ENTITIES[1], relations=rel1, relations_dropped_leak=1),
           Extraction(entities=ENTITIES[2], relations=rel2)]
    data = dump_extractions(docs, exs)
    data["probe"] = {"model": "test-slm", "relations_dropped_leak": 1, "documents_total": 2,
                     "seconds": 0.1}
    return data


def _write(root: Path, collection: str, name: str, data: dict) -> Path:
    d = root / collection
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


@pytest.fixture(scope="module")
def clean_file(corpus, tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("extractions")
    return _write(root, "synth-a", "extraction_1.json", _extraction(corpus, CLEAN, CLEAN[:1]))


@pytest.fixture(scope="module")
def leaking_file(corpus, tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("extractions")
    rels = [*CLEAN, ConceptRelation("EXECUTIVE", RUN, "INITIATIVE")]
    return _write(root, "synth-a", "extraction_1.json", _extraction(corpus, rels, CLEAN[:1]))


@pytest.fixture(scope="module")
def straddling_file(corpus, tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("extractions")
    rels = [*CLEAN, ConceptRelation("EXECUTIVE", "asked for a", "delay of the")]
    return _write(root, "synth-a", "extraction_1.json", _extraction(corpus, rels, CLEAN[:1]))


@pytest.fixture(scope="module")
def clean(corpus, clean_file) -> dict:
    return S.simulate_collection("synth-a", corpus, GOAL, [clean_file])


@pytest.fixture(scope="module")
def leaking(corpus, leaking_file) -> dict:
    return S.simulate_collection("synth-a", corpus, GOAL, [leaking_file])


# ------------------------------------------------------------------ verdicts


def test_a_clean_extraction_passes_every_arm(clean):
    ex = clean["extractions"][0]
    assert ex["extractor"]["entities"] == 10 and ex["extractor"]["relations"] == 3
    assert ex["extractor"]["relations_dropped_leak"] == 1   # the saved counter, carried
    assert ex["extractor"]["corpus_gate_drops_on_load"] == 0
    assert set(ex["arms"]) == set(S.ARMS)
    for a in ex["arms"].values():
        assert a["refused"] is False and a["reason"] is None and a["monitor_hits"] == 0
        assert a["hits"] == {"whole_stream": 0, "by_path": {}, "straddling_paths": 0, "keys": 0}
        assert a["prompt"]["by_field_kind"] == {} and a["prompt"]["goal_alone"] == 0
        assert a["relations"]["distinct"] == 2 and a["relations"]["fields_with_run"] == 0
    # Arms differ as the pipeline's do: r1 advertises referents only.
    assert ex["arms"]["r1"]["slots"]["by_category"] == {"LOCATION": 1, "ORG": 1, "PERSON": 1,
                                                         "PROJECT": 1}
    assert "DATE" in ex["arms"]["r5"]["slots"]["by_category"]
    assert ex["arms"]["r1"]["facts_total"] is not None
    assert ex["arms"]["r5"]["facts_total"] is None
    assert clean["filter"]["sealed"]["n_added"] == clean["filter"]["shingles"] > 0
    assert clean["goal_hits_alone"] == 0


def test_a_relation_field_holding_a_corpus_run_is_refused_in_that_field(leaking):
    for arm, a in leaking["extractions"][0]["arms"].items():
        assert a["refused"] is True, arm
        assert a["reason"] == PILOT_REASON and a["reason_code"] == "RAW_CONTEXT_CONTAINMENT"
        assert a["monitor_hits"] == 1                       # the monitor stops at the first
        assert a["hits"]["whole_stream"] == 3               # 2 five-grams + 1 six-gram
        assert a["hits"]["by_path"] == {"$.messages[].content": 3}
        assert a["hits"]["straddling_paths"] == 0 and a["hits"]["keys"] == 0
        assert a["prompt"]["hits"] == 3
        assert a["prompt"]["by_field_kind"] == {"relations[].predicate": 3}
        assert a["prompt"]["straddling_field_kinds"] == {}
        assert a["relations"]["distinct"] == 3 and a["relations"]["fields"] == 9
        assert a["relations"]["fields_with_run"] == 1
        assert a["relations"]["fields_with_run_by_kind"] == {"relations[].predicate": 1}
        assert a["relations"]["relations_with_run"] == 1
        assert a["relations"]["max_field_tokens"] == 6


def test_a_run_spread_over_two_fields_is_refused_but_no_field_holds_it(corpus, straddling_file):
    sim = S.simulate_collection("synth-a", corpus, GOAL, [straddling_file], arms=["r5"])
    a = sim["extractions"][0]["arms"]["r5"]
    assert a["refused"] is True and a["reason"] == PILOT_REASON
    assert a["prompt"]["by_field_kind"] == {}
    assert a["prompt"]["straddling_field_kinds"] == {
        "relations[].object_type+relations[].predicate": 3}
    assert a["relations"]["fields_with_run"] == 0 and a["relations"]["relations_with_run"] == 0


def test_a_goal_holding_a_corpus_run_is_attributed_to_the_goal(corpus, clean_file):
    goal = "Explain why the board asked for a delay of the rollout."
    sim = S.simulate_collection("synth-a", corpus, goal, [clean_file], arms=["baseline"])
    assert sim["goal_hits_alone"] == 3
    a = sim["extractions"][0]["arms"]["baseline"]
    assert a["refused"] is True and a["prompt"]["by_field_kind"] == {"goal": 3}
    assert a["prompt"]["goal_alone"] == 3 and a["relations"]["fields_with_run"] == 0


# ------------------------------------------------------------------ privacy


def test_the_output_holds_counts_and_names_only(leaking, clean):
    dump = json.dumps({"leaking": leaking, "clean": clean}, ensure_ascii=False)
    for e in ENTITIES[1] + ENTITIES[2]:
        assert e.text not in dump
    for line in (DOC1 + DOC2).splitlines():
        for word in line.split():
            if len(word) > 6 and word.isalpha():   # Quillon, Marlbury, Vossberg, ...
                assert word not in dump, word
    assert RUN not in dump and GOAL not in dump
    for r in CLEAN:
        assert r.predicate not in dump


def test_the_monitor_module_is_restored_after_a_session(corpus, clean_file):
    before = {k: getattr(S.monitor, k) for k in S._MONITOR_STATE}
    level = S.monitor.log.level
    S.simulate_collection("synth-a", corpus, GOAL, [clean_file], arms=["r5"])
    assert {k: getattr(S.monitor, k) for k in S._MONITOR_STATE} == before
    assert S.monitor.log.level == level


def test_reasons_of_unknown_code_are_cut_to_the_code():
    assert S.safe_reason(PILOT_REASON) == PILOT_REASON
    assert S.safe_reason("SECRET_PATTERN: 2 hit(s) across rules email") == \
        "SECRET_PATTERN: 2 hit(s) across rules email"
    assert S.safe_reason("SOMETHING_NEW: with a quoted 'string'") == "SOMETHING_NEW"
    assert S.safe_reason(None) is None


# ------------------------------------------------------------------ discovery


def test_discovery_skips_the_extract_manifest_and_merges_copies(corpus, tmp_path):
    data = _extraction(corpus, CLEAN, CLEAN[:1])
    _write(tmp_path, "synth-a", "extraction_1.json", data)
    _write(tmp_path, "synth-a", "extraction_2.json", data)             # a byte copy
    _write(tmp_path, "synth-a", "extract_manifest.json", {"k": 2})
    assert [p.name for p in S.extraction_files(tmp_path, "synth-a")] == ["extraction_1.json"]
    assert S.extraction_files(tmp_path, "synth-b") == []


def test_an_extraction_of_another_corpus_is_refused_not_simulated(corpus, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "doc1.md").write_text("# Other\n\nAn unrelated memo about nothing.\n")
    (other / "doc2.md").write_text("# Other two\n\nStill nothing.\n")
    data = _extraction(corpus, CLEAN, CLEAN[:1])
    p = _write(tmp_path, "synth-a", "extraction_1.json", data)
    sim = S.simulate_collection("synth-a", other, GOAL, [p], arms=["r5"])
    assert sim["extractions"] == []
    assert sim["refused_files"][0]["reason"] == "ExtractionReuseError"
    assert "corpus mismatch" in sim["refused_files"][0]["detail"]


# ------------------------------------------------------------------ self-check


def _manifest(sim: dict, *, notes: list[str], **over) -> dict:
    ex = sim["extractions"][0]
    m = {"notes": notes,
         "containment": {k: sim["filter"][k] for k in ("shingles", "m_bits", "k", "n_min",
                                                        "n_max")},
         "extraction": {k: ex["extractor"][k] for k in ("entities", "relations",
                                                        "relations_dropped_leak")},
         "slots_issued": ex["arms"]["r5"]["slots_issued"]}
    m.update(over)
    return m


def test_self_check_passes_on_the_pilot_reason_and_names_the_extraction(leaking, tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(_manifest(leaking, notes=[f"planning refused by monitor: "
                                                      f"{PILOT_REASON}"])))
    sc = S.self_check({"synth-a": leaking}, p, collection="synth-a")
    assert sc["status"] == "pass" and sc["pilot_reason"] == PILOT_REASON
    assert all(sc["filter_matches_pilot"].values())
    row = sc["extractions"][0]
    assert row["refusal_reproduced"] and row["same_extraction_as_pilot"]
    assert row["slots_issued_match_pilot"]
    assert sc["note"] == "the pilot's own extraction counts"

    # Another draw of the extractor: the verdict is reproduced, the counts are not.
    q = tmp_path / "manifest2.json"
    q.write_text(json.dumps(_manifest(leaking, notes=[f"planning refused by monitor: "
                                                      f"{PILOT_REASON}"],
                                      extraction={"entities": 113, "relations": 88,
                                                  "relations_dropped_leak": 5})))
    sc2 = S.self_check({"synth-a": leaking}, q, collection="synth-a")
    assert sc2["status"] == "pass"
    assert not sc2["extractions"][0]["same_extraction_as_pilot"]
    assert "different extraction" in sc2["note"]


def test_self_check_fails_when_the_pilot_was_allowed_or_the_documents_differ(leaking, clean,
                                                                             tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(_manifest(leaking, notes=["plan: 3 sections, 0 unknown slot refs "
                                                      "dropped, 0 budgets clamped"])))
    sc = S.self_check({"synth-a": leaking}, p, collection="synth-a")
    assert sc["status"] == "fail" and not sc["pilot_refused"]
    assert not sc["extractions"][0]["refusal_reproduced"]

    q = tmp_path / "manifest2.json"
    q.write_text(json.dumps(_manifest(clean, notes=[], containment={"shingles": 1})))
    sc2 = S.self_check({"synth-a": clean}, q, collection="synth-a")
    assert sc2["status"] == "fail" and sc2["extractions"][0]["refusal_reproduced"]
    assert not sc2["filter_matches_pilot"]["shingles"]

    assert S.self_check({}, p, collection="synth-a")["status"] == "not run"


# ------------------------------------------------------------------ cli


def test_main_writes_the_json_and_prints_counts_only(corpus, leaking_file, tmp_path, capsys):
    tasks = tmp_path / "tasks.json"
    tasks.write_text(json.dumps([{"id": "synth-a", "corpus": str(corpus), "goal": GOAL}]))
    (corpus.parent / "synth-b").mkdir(exist_ok=True)
    (corpus.parent / "synth-b" / "doc1.md").write_text("# B\n\nA memo with no extraction.\n")
    out = tmp_path / "out" / "refusal_sim.json"
    rc = S.main(["--collections", "synth-a", "synth-b", "--corpora-root", str(corpus.parent),
                 "--tasks", str(tasks), "--goal", GOAL,
                 "--extractions-dir", str(leaking_file.parents[1]), "--out", str(out)])
    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["instrument"] == "scripts/real_l_refusal_sim.py"
    assert report["parameters"]["n_min"] == 5 and report["parameters"]["n_max"] == 8
    assert "/inspect" in report["monitor"]
    assert report["collections"]["synth-a"]["extractions"][0]["arms"]["r5"]["refused"]
    assert report["collections"]["synth-b"]["extractions"] == []
    assert "no extraction" in report["collections"]["synth-b"]["note"]
    text = capsys.readouterr().out
    assert "synth-a" in text and "yes" in text and "relations[].predicate=3" in text
    assert f"[{PILOT_REASON}]" in text
    assert "no extraction" in text
    assert "refused: r5 1/1, baseline 1/1, r1 1/1" in text
    for e in ENTITIES[1]:
        assert e.text not in text and e.text not in out.read_text(encoding="utf-8")
    assert RUN not in text


def test_main_self_check_exit_codes(corpus, leaking_file, tmp_path):
    tasks = tmp_path / "tasks.json"
    tasks.write_text(json.dumps([{"id": "tab-L0", "corpus": str(corpus), "goal": GOAL}]))
    root = tmp_path / "ex"
    data = json.loads(leaking_file.read_text(encoding="utf-8"))
    _write(root, "tab-L0", "extraction_1.json", data)
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps({"notes": [f"planning refused by monitor: {PILOT_REASON}"],
                             "containment": {}, "extraction": {}}))
    args = ["--collections", "--corpora-root", str(tmp_path), "--tasks", str(tasks),
            "--extractions-dir", str(root), "--out", str(tmp_path / "o.json"),
            "--self-check", "--pilot-manifest", str(m)]
    # The reason is reproduced but the manifest's filter block is empty: fail.
    assert S.main(args) == 1
    # No extraction at all: cannot run.
    assert S.main([*args[:5], "--extractions-dir", str(tmp_path / "none"), *args[7:]]) == 2
