"""scripts/tier1_probe.py and its container-side extractor, offline.

``analyse`` is pinned on the real input: corpus A (tracked) and the pilot's
saved extraction (the security suite's fixture, a byte copy of the one all nine
pilot runs share). The figures asserted are the pilot figures the probe
reports, so a change to the instrument that moves one is seen. ``extract`` is
tested only through a faked ``_compose``: it restarts the core with a corpus
mounted and runs the SLM, so it is never run for real here.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import httpx
import pytest
from privdeep.tier1_local import probe_extract
from privdeep.tier1_local.extraction_io import load_extractions
from privdeep.tier1_local.slm_client import AsyncSLMClient

from scripts import run_evaluation as R
from scripts import tier1_probe as T

REPO = Path(__file__).resolve().parents[3]
A = REPO / "eval" / "corpora" / "smoke-q3"
B = REPO / "eval" / "corpora" / "portfolio-b"
C = REPO / "eval" / "corpora" / "prose-c"
PILOT = REPO / "backend" / "tests" / "security" / "fixtures" / "smoke-q3_extractions.json"


@pytest.fixture(scope="module")
def pilot() -> dict:
    return T.analyse(A, [PILOT, PILOT], [B, C], g1_stub=True)


# --------------------------------------------------------------------- analyse on the pilot


def test_copies_of_one_extraction_are_one_extraction(pilot):
    assert pilot["extraction_files"] == 2 and len(pilot["extractions"]) == 1
    assert pilot["variance"]["pairs"] == [] and pilot["variance"]["entity_jaccard"] is None
    assert "no pair" in pilot["variance"]["note"]


def test_pilot_recall(pilot):
    r = pilot["per_extraction"][0]["recall"]
    assert (r["referents"]["covered"], r["referents"]["n"]) == (5, 5)
    assert (r["string_facts"]["covered"], r["string_facts"]["n"]) == (9, 9)
    assert (r["generator_surfaces"]["covered"], r["generator_surfaces"]["n"]) == (57, 58)
    assert r["generator_surfaces"]["missed"] == ["22 August 2026"]
    assert r["surfaces_in_relations"] == {"hits": [], "labels_group_hits": []}


def test_pilot_predicate_echo_is_the_plan_figure(pilot):
    p = pilot["per_extraction"][0]["predicates"]
    assert (p["echo_2_4gram"], p["n_predicates"]) == (18, 43)   # the plan's 18/43
    assert p["whole_match"] == 16 and p["max_tokens"] == 4
    assert p["length_tokens"] == {1: 4, 2: 23, 3: 14, 4: 2}
    c = pilot["predicate_control"]
    assert c["stratum"] == "english_prose" and c["payloads"] == 100
    assert c["expected_echo_share"] < p["echo_share"] / 4


def test_pilot_r5_residue(pilot):
    d = pilot["per_extraction"][0]["r5_residue"]
    assert d["by_category"] == {"DATE": 1, "IDENTIFIER": 2, "LOCATION": 2, "QUANTITY": 2}
    assert ["nb20260917", "contractnb20260917"] in d["pairs"]["IDENTIFIER"]
    assert ["manchester", "manchester site"] in d["pairs"]["LOCATION"]


def test_pilot_masked_documents_are_refused_and_what_survives(pilot):
    e = pilot["per_extraction"][0]["masked_exposure"]
    assert e["refused_any"] and e["refused_documents"] == 4
    assert 0 < e["masked_5gram_hit_share"] < 1 and 0 < e["corpus_5grams_surviving_share"] < 1
    s = e["generator_surfaces_surviving"]
    assert s["extracted_elsewhere"] == ["62,567.45", "NB-2026-0917", "NB-2026-1044",
                                        "twelve percent"]
    assert s["extractor_misses"] == []


def test_the_payload_builder_matches_the_pilot_runs(pilot):
    """Slots advertised per run, as observation_table.py read them off the pilot traces:
    r1 14, r5 47, baseline 61."""
    saved = next(r for r in pilot["g1"]["corpora"] if r["label"] == "smoke-q3:saved")
    assert {a: sum(saved["arms"][a]["slot_counts"].values()) for a in T.ARMS} == \
        {"r5": 47, "baseline": 61, "r1": 14}
    assert saved["arms"]["r1"]["slot_counts"] == {"LOCATION": 5, "ORG": 2, "PERSON": 3,
                                                  "PROJECT": 4}
    assert saved["arms"]["r5"]["relation_multiset"]["n"] == 43


def test_g1_inventory_under_the_stub_fallback(pilot):
    g = pilot["g1"]
    assert "stub" in g["note"]
    assert g["stub_corpora"] == ["portfolio-b", "prose-c", "smoke-q3"]
    by_name = dict((c["name"], c) for c in g["comparisons"])
    # Only A has a saved extraction: no saved comparison of two corpora.
    assert sorted(by_name) == sorted([T.G1_STUB, T.G1_MIXED])
    stubbed = by_name[T.G1_STUB]
    assert stubbed["corpora"] == ["smoke-q3:stub", "portfolio-b:stub", "prose-c:stub"]
    assert stubbed["extraction"] == "stub" and stubbed["stub_corpora"] == stubbed["corpora"]
    for arm in T.ARMS:
        assert sorted(stubbed["by_arm"][arm]["differs"]) == ["document_stats", "slot_counts"]
        assert "attribute_schema" in stubbed["by_arm"][arm]["same"]
    mixed = by_name[T.G1_MIXED]
    assert mixed["corpora"] == ["smoke-q3:saved", "portfolio-b:stub", "prose-c:stub"]
    assert mixed["extraction"] == "mixed"
    assert mixed["stub_corpora"] == ["portfolio-b:stub", "prose-c:stub"]
    assert "relation_multiset" in mixed["by_arm"]["r1"]["differs"]
    rows = dict((r["label"], r) for r in g["corpora"])
    assert rows["smoke-q3:saved"]["extraction"] == "saved"
    assert rows["smoke-q3:saved"]["source"] == \
        "backend/tests/security/fixtures/smoke-q3_extractions.json"
    assert rows["prose-c:stub"]["source"] == "stub from eval/corpora/prose-c/surfaces.json"


def test_the_output_names_no_checkout(pilot):
    assert pilot["extractions"][0]["files"] == [
        "backend/tests/security/fixtures/smoke-q3_extractions.json"] * 2
    assert T._rel(Path("/elsewhere/wt/eval/runs/x/extractions.json")) == \
        "eval/runs/x/extractions.json"


# --------------------------------------------------------------------- G1 from real extractions


def _extraction_file(tmp_path: Path, corpus_dir: Path, relations: int = 0) -> Path:
    """A saved-extraction file for `corpus_dir`: the stub's entities without its
    'stub' mark, and `relations` extra relations on the first document, so the
    row built from it can be told from the stub's."""
    data = T.stub_extraction(T.load_corpus(corpus_dir))
    del data["stub"]
    data["documents"][0]["relations"] = [["INITIATIVE", f"step {i}", "RISK"]
                                         for i in range(relations)]
    p = tmp_path / f"{corpus_dir.name}.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_g1_builds_every_corpus_from_the_extraction_given_for_it(tmp_path):
    c_file = _extraction_file(tmp_path, C, relations=2)
    report = T.analyse(C, [c_file], [f"{A}={PILOT}"])
    g = report["g1"]
    assert g["stub_corpora"] == []
    rows = dict((r["label"], r) for r in g["corpora"])
    assert list(rows) == ["prose-c:saved", "smoke-q3:saved"]
    a = rows["smoke-q3:saved"]
    assert a["extraction"] == "saved"
    assert a["source"] == "backend/tests/security/fixtures/smoke-q3_extractions.json"
    # A's row is the pilot extraction's payload, not the stub's: the pilot figures.
    assert dict((arm, sum(a["arms"][arm]["slot_counts"].values())) for arm in T.ARMS) == \
        dict(r5=47, baseline=61, r1=14)
    assert a["arms"]["r5"]["relation_multiset"]["n"] == 43
    assert rows["prose-c:saved"]["arms"]["r5"]["relation_multiset"]["n"] == 2
    assert [c["name"] for c in g["comparisons"]] == [T.G1_SAVED]
    comp = g["comparisons"][0]
    assert comp["extraction"] == "saved" and comp["stub_corpora"] == []
    assert comp["corpora"] == ["prose-c:saved", "smoke-q3:saved"]
    for arm in T.ARMS:
        assert "relation_multiset" in comp["by_arm"][arm]["differs"]


def test_a_g1_corpus_without_an_extraction_needs_the_explicit_stub_flag(tmp_path):
    with pytest.raises(SystemExit, match="--g1-stub"):
        T.analyse(A, [PILOT], [C])
    report = T.analyse(A, [PILOT], [f"{C}={_extraction_file(tmp_path, C)}", B], g1_stub=True)
    g = report["g1"]
    labels = [r["label"] for r in g["corpora"]]
    assert labels == ["smoke-q3:saved", "prose-c:saved", "smoke-q3:stub", "prose-c:stub",
                      "portfolio-b:stub"]
    by_name = dict((c["name"], c) for c in g["comparisons"])
    assert by_name[T.G1_SAVED]["corpora"] == ["smoke-q3:saved", "prose-c:saved"]
    assert by_name[T.G1_SAVED]["stub_corpora"] == []
    assert by_name[T.G1_STUB]["stub_corpora"] == ["smoke-q3:stub", "prose-c:stub",
                                                   "portfolio-b:stub"]
    # The fallback names the one corpus that has no saved extraction.
    assert by_name[T.G1_MIXED]["corpora"] == ["smoke-q3:saved", "prose-c:saved",
                                              "portfolio-b:stub"]
    assert by_name[T.G1_MIXED]["stub_corpora"] == ["portfolio-b:stub"]


def test_a_g1_extraction_the_pipeline_would_refuse_is_refused(tmp_path):
    with pytest.raises(SystemExit, match="refused"):
        T.analyse(A, [PILOT], [f"{C}={PILOT}"])     # A's extraction given for C
    with pytest.raises(SystemExit, match="no extraction file"):
        T.analyse(A, [PILOT], [f"{C}={tmp_path / 'missing.json'}"])
    with pytest.raises(SystemExit, match="already in the inventory"):
        T.analyse(A, [PILOT], [f"{A}={PILOT}"])


def test_a_stub_written_to_a_file_is_never_read_as_a_saved_extraction(tmp_path):
    stub = tmp_path / "prose-c-stub.json"
    stub.write_text(json.dumps(T.stub_extraction(T.load_corpus(C))), encoding="utf-8")
    exs, refused = T.read_extractions([stub], T.load_corpus(C))
    assert exs == [] and refused == [{"file": str(stub.resolve()), "reason": "stub"}]
    # As another corpus's G1 extraction (CORPUS=FILE): refused, not a saved row.
    with pytest.raises(SystemExit, match="refused.*stub"):
        T.analyse(A, [PILOT], [f"{C}={stub}"])
    # As the primary --extractions: refused, so no saved row for the primary either.
    with pytest.raises(SystemExit, match="first extraction.*refused"):
        T.analyse(C, [stub], [f"{A}={PILOT}"])
    with pytest.raises(SystemExit, match="first extraction.*refused"):
        T.main(["analyse", str(C), "--extractions", str(stub), "--g1", f"{A}={PILOT}",
                "--out", str(tmp_path / "out.json")])
    # Without --g1 it is only listed as refused.
    report = T.analyse(C, [stub])
    assert report["extractions"] == [] and report["refused_files"][0]["reason"] == "stub"


def test_the_primary_g1_row_is_never_built_from_a_later_file(tmp_path):
    c_file = _extraction_file(tmp_path, C, relations=2)
    other = _extraction_file(tmp_path, B)        # another corpus: refused for C
    with pytest.raises(SystemExit, match="first extraction.*ExtractionReuseError"):
        T.analyse(C, [other, c_file], [f"{A}={PILOT}"])
    # A refused later file does not stop it: the first file is the row's source.
    report = T.analyse(C, [c_file, other], [f"{A}={PILOT}"])
    assert report["refused_files"][0]["reason"] == "ExtractionReuseError"
    assert report["g1"]["corpora"][0]["source"] == str(c_file.resolve())


def test_parse_g1():
    assert T.parse_g1("eval/corpora/prose-c") == (Path("eval/corpora/prose-c"), None)
    assert T.parse_g1("c=eval/runs/c__r5/extractions.json") == (
        Path("c"), Path("eval/runs/c__r5/extractions.json"))
    assert T.parse_g1(Path("c")) == (Path("c"), None)
    for bad in ("c=", "=x.json"):
        with pytest.raises(SystemExit):
            T.parse_g1(bad)


def test_the_cli_takes_g1_extractions(tmp_path):
    out = tmp_path / "c.json"
    c_file = str(_extraction_file(tmp_path, C))
    report = T.main(["analyse", str(C), "--extractions", c_file, "--g1", f"{A}={PILOT}",
                     "--out", str(out)])
    assert json.loads(out.read_text(encoding="utf-8"))["g1"]["stub_corpora"] == []
    assert [c["name"] for c in report["g1"]["comparisons"]] == [T.G1_SAVED]
    with pytest.raises(SystemExit, match="--g1-stub"):
        T.main(["analyse", str(C), "--extractions", c_file, "--g1", str(A), "--out", str(out)])


# --------------------------------------------------------------------- analyse, synthetic


def _variant(tmp_path: Path, drop: int) -> Path:
    data = json.loads(PILOT.read_text(encoding="utf-8"))
    data["documents"][0]["entities"] = data["documents"][0]["entities"][drop:]
    data["documents"][0]["relations"] = data["documents"][0]["relations"][drop:]
    p = tmp_path / f"drop{drop}.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_variance_over_two_extractions(tmp_path):
    corpus = T.load_corpus(A)
    exs, refused = T.read_extractions([PILOT, _variant(tmp_path, 4)], corpus)
    assert refused == [] and len(exs) == 2
    v = T.variance(exs)
    ents = len({(e.text, e.category) for e in exs[0].entities})
    pair = v["pairs"][0]
    assert 0 < pair["entity_jaccard"] < 1
    assert pair["relation_jaccard"] == pytest.approx((43 - 4) / 43)
    assert pair["entity_jaccard"] >= (ents - 4) / ents


def test_an_extraction_of_another_corpus_is_refused_not_measured(tmp_path):
    other = tmp_path / "b.json"
    data = T.stub_extraction(T.load_corpus(B))
    del data["stub"]            # else it is refused as a stub before the corpus check
    other.write_text(json.dumps(data), encoding="utf-8")
    exs, refused = T.read_extractions([other], T.load_corpus(A))
    assert exs == [] and refused[0]["reason"] == "ExtractionReuseError"


def test_a_leaky_relation_is_refused_by_class_and_category_only(tmp_path):
    data = json.loads(PILOT.read_text(encoding="utf-8"))
    data["documents"][0]["relations"].append(["INITIATIVE", "led by Sarah Whitfield", "PERSON"])
    p = tmp_path / "leak.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    _, refused = T.read_extractions([p], T.load_corpus(A))
    assert refused == [{"file": str(p.resolve()), "reason": "OntologyLeak",
                        "category": "PERSON"}]


def test_the_stub_extraction_is_loadable_and_has_no_relations():
    for d in (A, B, C):
        corpus = T.load_corpus(d)
        exs = load_extractions(T.stub_extraction(corpus), corpus.docs,
                               canary_prefix=T.CANARY_PREFIX)
        assert all(ex.relations == [] for ex in exs)
        assert {e.category for ex in exs for e in ex.entities} >= {"PERSON", "MONEY", "PROJECT"}


def test_residue_is_substring_not_token_matching():
    ex = T.LoadedExtraction(["x"], "sha", [T.Extraction(
        entities=[T.Entity("contract NB-2026-0917", "IDENTIFIER"),
                  T.Entity("NB-2026-0917", "IDENTIFIER"), T.Entity("Leeds", "LOCATION"),
                  T.Entity("Zephyr", "PROJECT"), T.Entity("Project Zephyr", "PROJECT")],
        relations=[])])
    d = T.r5_residue(ex)
    assert d["pairs"] == {"IDENTIFIER": [["nb20260917", "contractnb20260917"]],
                          "PROJECT": [["zephyr", "project zephyr"]]}
    assert d["referents_with_residue"] == 2


def test_surviving_surfaces_claim_the_longest_first():
    got = T._surviving("Project Zephyr and Zephyr; 2027 but not ab2027 or 20271",
                       ["Zephyr", "Project Zephyr", "2027"])
    assert got == {"Project Zephyr": 1, "Zephyr": 1, "2027": 1}


def test_the_cli_writes_the_default_path(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "DEFAULT_OUT_DIR", tmp_path)
    report = T.main(["analyse", str(A), "--extractions", str(PILOT)])
    assert (tmp_path / "smoke-q3.json").exists() and "g1" not in report


# --------------------------------------------------------------------- extract, faked


class FakeCompose:
    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[tuple[tuple[str, ...], dict | None]] = []
        self.fail_on = fail_on

    def __call__(self, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        self.calls.append((args, env))
        if self.fail_on and self.fail_on in args:
            return subprocess.CompletedProcess(args, 1, "", "boom")
        if args[0] == "cp":
            Path(args[2]).write_text(json.dumps({"from": args[1]}), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "extracted 4/4 document(s)\n", "")


@pytest.fixture
def fake(monkeypatch):
    clean = R.Provenance("c0ffee", "t" * 64, False)
    monkeypatch.setattr(R, "host_provenance", lambda root=None: clean)
    f = FakeCompose()
    monkeypatch.setattr(T, "_compose", f)
    return f


def test_extract_runs_the_extractor_inside_the_core_and_copies_out(fake, tmp_path):
    written = T.extract(A, 3, tmp_path)
    assert [p.name for p in written] == [f"extraction_{i}.json" for i in (1, 2, 3)]
    up, mk, *rest = fake.calls
    assert up[0] == ("up", "-d", R.CORE)
    assert up[1]["PRIVDEEP_CORPUS_DIR"] == str(A.resolve())
    assert mk[0] == ("exec", "-T", R.CORE, "mkdir", "-p", "/data/probe/smoke-q3")
    execs = [a for a, _ in rest if a[0] == "exec"]
    assert len(execs) == 3
    assert execs[0][-5:] == ("python", "-m", "privdeep.tier1_local.probe_extract", "/corpus",
                             "/data/probe/smoke-q3/extraction_1.json")
    assert "PRIVDEEP_GIT_COMMIT=c0ffee" in execs[0]
    cps = [a for a, _ in rest if a[0] == "cp"]
    assert cps[2] == ("cp", f"{R.CORE}:/data/probe/smoke-q3/extraction_3.json",
                      str(tmp_path / "extraction_3.json"))
    m = json.loads((tmp_path / "extract_manifest.json").read_text(encoding="utf-8"))
    assert m["k"] == 3 and m["provenance"]["git_commit"] == "c0ffee" and not m["changed_during"]
    assert not any("up" in a and "--force-recreate" in a for a, _ in fake.calls)


def test_extract_keeps_what_exists_and_force_moves_it_aside(fake, tmp_path):
    (tmp_path / "extraction_1.json").write_text("old", encoding="utf-8")
    assert [p.name for p in T.extract(A, 2, tmp_path)] == ["extraction_2.json"]
    assert (tmp_path / "extraction_1.json").read_text(encoding="utf-8") == "old"
    T.extract(A, 1, tmp_path, force=True)
    assert (tmp_path / "extraction_1.attempt1.json").read_text(encoding="utf-8") == "old"
    assert (tmp_path / "extraction_1.json").read_text(encoding="utf-8") != "old"


def test_extract_stops_on_a_failed_run(fake, tmp_path):
    fake.fail_on = "privdeep.tier1_local.probe_extract"
    with pytest.raises(SystemExit, match="extraction 1 failed"):
        T.extract(A, 2, tmp_path)


def test_extract_refuses_a_dirty_tree(monkeypatch, tmp_path):
    dirty = R.Provenance("c0ffee", "t" * 64, True, ("backend/src/x.py",))
    monkeypatch.setattr(R, "host_provenance", lambda root=None: dirty)
    f = FakeCompose()
    monkeypatch.setattr(T, "_compose", f)
    with pytest.raises(SystemExit):
        T.extract(A, 1, tmp_path)
    assert f.calls == []


# --------------------------------------------------------------------- the container side


def _slm_reply(entities: list[dict], relations: list[dict]):
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert "Internal reference tokens" in body["messages"][0]["content"], "no canary block"
        reply = json.dumps({"entities": entities, "relations": relations})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": reply},
                                         "prompt_eval_count": 1, "eval_count": 1,
                                         "eval_duration": 10**8})
    return handler


def test_probe_extract_writes_the_saved_extraction_format():
    corpus = T.load_corpus(A)
    handler = _slm_reply([{"text": "Project Zephyr", "category": "PROJECT"}],
                         [{"subject_type": "INITIATIVE", "predicate": "has",
                           "object_type": "FINANCIAL_METRIC"}])
    slm = AsyncSLMClient("http://local-slm:11434", model="qwen3:14b",
                         transport=httpx.MockTransport(handler))
    data = asyncio.run(probe_extract.extract_corpus(corpus.docs, slm))
    exs = load_extractions(data, corpus.docs, canary_prefix=T.CANARY_PREFIX)
    assert len(exs) == 4 and data["probe"]["relations_dropped_leak"] == 0
    assert data["probe"]["model"] == "qwen3:14b" and data["probe"]["canary_context"]


def test_probe_extract_counts_leak_gate_drops_without_the_entity():
    corpus = T.load_corpus(A)
    handler = _slm_reply([{"text": "Sarah Whitfield", "category": "PERSON"}],
                         [{"subject_type": "PERSON", "predicate": "is Sarah Whitfield",
                           "object_type": "PERSON"}])
    slm = AsyncSLMClient("http://local-slm:11434", model="qwen3:14b",
                         transport=httpx.MockTransport(handler))
    data = asyncio.run(probe_extract.extract_corpus(corpus.docs, slm))
    # Every document names her, so each drops its one relation and is still kept.
    assert len(data["documents"]) == 4 and data["probe"]["relations_dropped_leak"] == 4
    assert all(d["relations"] == [] and d["relations_dropped_leak"] == 1
               for d in data["documents"])
    assert "Sarah Whitfield" not in json.dumps(data["probe"])
    assert "is Sarah Whitfield" not in json.dumps(data)
    # The saved file passes the strict gate on reuse: nothing leaking was saved.
    exs = load_extractions(data, corpus.docs, canary_prefix=T.CANARY_PREFIX)
    assert [ex.relations_dropped_leak for ex in exs] == [1, 1, 1, 1]


def test_probe_extract_drops_a_relation_carrying_another_documents_entity():
    """The corpus-wide gate runs here too, so the saved file passes the reuse
    path's corpus-wide check: "authority" is extracted only from the second
    document and "has authority" is a relation of the first."""
    from privdeep.models.document import Document, DocumentKind

    docs = [Document("a", DocumentKind.MARKDOWN, Path("a.md"), "Scheme Fallowbeck is funded."),
            Document("b", DocumentKind.MARKDOWN, Path("b.md"), "Ask the port authority.")]

    def handler(req: httpx.Request) -> httpx.Response:
        prompt = json.loads(req.content)["messages"][-1]["content"]
        if "Fallowbeck" in prompt:
            ents = [{"text": "Scheme Fallowbeck", "category": "PROJECT"}]
            rels = [{"subject_type": "INITIATIVE", "predicate": "has authority",
                     "object_type": "FINANCIAL_METRIC"},
                    {"subject_type": "TEAM", "predicate": "reviews", "object_type": "RISK"}]
        else:
            ents, rels = [{"text": "authority", "category": "ORG"}], []
        return _slm_reply(ents, rels)(req)

    slm = AsyncSLMClient("http://local-slm:11434", model="qwen3:14b",
                         transport=httpx.MockTransport(handler))
    data = asyncio.run(probe_extract.extract_corpus(docs, slm))
    assert data["probe"]["relations_dropped_leak"] == 1
    assert [d["relations_dropped_leak"] for d in data["documents"]] == [1, 0]
    assert data["documents"][0]["relations"] == [["TEAM", "reviews", "RISK"]]
    assert "has authority" not in json.dumps(data)
    load_extractions(data, docs, canary_prefix=T.CANARY_PREFIX)  # must not raise
