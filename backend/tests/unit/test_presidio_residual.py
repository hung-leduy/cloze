"""scripts/presidio_residual.py: what Presidio leaves of track L's identifier strings.

The scoring, the collection check and the output are tested with a fake
anonymiser on a synthetic collection written by the track-L builder, so they run
in the main venv, which has no Presidio. The one test that runs Presidio itself
is skipped there; run this file with .venv-presidio/bin/python
to include it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import presidio_residual as P
from scripts.real_corpora import tab as T
from shared.shingle_filter import tokenize

NAME, PLACE, DATE, NESTED = "Zebulon Quixote", "Leeds Infirmary", "3 March 2091", "March 2091"


def mention(text: str, span: str, itype: str, etype: str, k: int) -> dict:
    start = text.find(span)
    return {"entity_type": etype, "entity_mention_id": f"m{k}", "start_offset": start,
            "end_offset": start + len(span), "span_text": span, "edit_type": "check",
            "identifier_type": itype, "entity_id": f"e{k}", "confidential_status": "NOT"}


def judgment(doc_id: str, text: str, spans: list[tuple[str, str, str]]) -> dict:
    return {"doc_id": doc_id, "text": text,
            "meta": {"countries": "GBR", "applicant": "not written"}, "task": "not written",
            "annotations": {f"annotator{a}": {"entity_mentions": [
                mention(text, s, it, et, k) for k, (s, it, et) in enumerate(spans)]}
                for a in range(1, 5)}}


def docs() -> list[dict]:
    first = f"{NAME} was treated at {PLACE} on {DATE}, in the UK."
    return [judgment("001-1", first, [(NAME, "DIRECT", "PERSON"), (PLACE, "QUASI", "LOC"),
                                      (PLACE, "QUASI", "ORG"), (DATE, "QUASI", "DATETIME"),
                                      (NESTED, "QUASI", "DATETIME"), ("UK", "QUASI", "LOC")]),
            *(judgment(f"001-{i}", f"Nothing to report in file {i}.", []) for i in (2, 3, 4))]


def strings() -> list[dict]:
    return [s.to_json() for s in T.identifier_strings(docs(), T.GOAL, T.load_function_words())]


@pytest.fixture
def corpus(tmp_path) -> Path:
    c = T.build_collection("tab-L9", "dev", docs(), "0" * 64, T.load_function_words())
    d = tmp_path / "corpora" / "tab-L9"
    d.mkdir(parents=True)
    for name, data in c.files.items():
        (d / name).write_bytes(data)
    return d


def summary_of(corpus: Path) -> dict:
    """A committed summary holding this collection, as manifest_l.json holds L0-L6."""
    return {"collections": {"tab-L9": json.loads((corpus / "MANIFEST.json").read_text())}}


def cli(corpus: Path, tmp_path: Path) -> list[str]:
    tasks, manifest = tmp_path / "tasks.json", tmp_path / "manifest_l.json"
    tasks.write_text(json.dumps([{"id": "tab-L9", "corpus": str(corpus), "goal": T.GOAL}]))
    manifest.write_text(json.dumps(summary_of(corpus)))
    return ["--tasks", str(tasks), "--manifest", str(manifest), "--out", str(tmp_path / "out")]


def fake(text: str) -> tuple[str, dict[str, int]]:
    """Redacts the name only, as a redactor that knows people but not dates would."""
    return text.replace(NAME, "<PERSON>"), {"PERSON": text.count(NAME)}


# ---------------------------------------------------------------------- scoring


def test_k_over_n_per_identifier_and_entity_type():
    originals = [d["text"] for d in docs()]
    res = P.score(strings(), originals, [fake(t)[0] for t in originals])
    d, q = res["by_type"]["DIRECT"], res["by_type"]["QUASI"]
    assert d["PERSON"] == {"k": 0, "k_one_call": 0, "n": 1, "present": 1, "present_one_call": 1}
    # The place has two types and is counted under each, once in the total.
    assert q["LOC"]["n"] == q["ORG"]["n"] == 1 and q["LOC"]["k"] == q["ORG"]["k"] == 1
    # The nested date is found on its own (primary) and consumed by the longer
    # one in a single call (descriptive).
    assert q["DATETIME"] == {"k": 2, "k_one_call": 1, "n": 2, "present": 2,
                             "present_one_call": 1}
    assert q["total"] == {"k": 3, "k_one_call": 2, "n": 3, "present": 3, "present_one_call": 2}
    assert res["labels_excluded"] == 1          # "UK"


def test_nothing_survives_a_redactor_that_removes_every_string():
    originals = [d["text"] for d in docs()]
    gone = [t.replace(NAME, "<P>").replace(PLACE, "<L>").replace(DATE, "<D>") for t in originals]
    res = P.score(strings(), originals, gone)
    assert all(r["k"] == r["k_one_call"] == 0 for rows in res["by_type"].values()
               for r in rows.values())


def test_score_needs_one_anonymised_text_per_original():
    with pytest.raises(ValueError, match="one anonymised text per original"):
        P.score(strings(), ["a", "b"], ["a"])


# --------------------------------------------------------------- the collection check


def test_read_collection_accepts_the_builders_output(corpus):
    c = P.read_collection("tab-L9", corpus, summary_of(corpus))
    assert [n for n, _ in c.documents] == list(T.DOC_NAMES)
    assert NAME in c.documents[0][1] and len(c.strings) == 5      # "UK" is a label


@pytest.mark.parametrize("damage,match", [
    (lambda d: (d / "doc2.md").write_text("edited"), "doc2.md does not match"),
    (lambda d: (d / "notes.md").write_text("stray"), "notes.md"),
    (lambda d: (d / "MANIFEST.json").unlink(), "no MANIFEST.json"),
])
def test_read_collection_refuses_anything_but_the_manifested_build(corpus, damage, match):
    damage(corpus)
    with pytest.raises(P.Refusal, match=match):
        P.read_collection("tab-L9", corpus, None)


def test_read_collection_refuses_another_collections_directory(corpus):
    with pytest.raises(P.Refusal, match="names another collection"):
        P.read_collection("tab-L1", corpus, None)


def test_read_collection_refuses_a_build_the_committed_manifest_does_not_hold(corpus):
    summary = summary_of(corpus)
    summary["collections"]["tab-L9"]["doc_ids"][0] = "001-0"
    with pytest.raises(P.Refusal, match="not the committed manifest's entry"):
        P.read_collection("tab-L9", corpus, summary)
    with pytest.raises(P.Refusal, match="not the committed manifest's entry"):
        P.read_collection("tab-L9", corpus, {"collections": {}})


# ------------------------------------------------------------------------ output


def test_run_writes_counts_and_versions_and_no_text(corpus, tmp_path):
    versions = {"presidio-analyzer": "2.2.362", "model_loaded": "en_core_web_lg 3.8.0"}
    out = tmp_path / "out"
    [rec] = P.run([P.read_collection("tab-L9", corpus, None)], out, fake, versions)
    raw = (out / "presidio_tab-L9.json").read_text(encoding="utf-8")
    assert json.loads(raw) == rec
    assert rec["versions"] == versions and rec["configuration"]["language"] == "en"
    assert rec["by_type"]["DIRECT"]["total"]["n"] == 1
    assert rec["documents"][0] == {"name": "doc1.md", "sha256": rec["documents"][0]["sha256"],
                                   "presidio_results": {"PERSON": 1}}
    manifest = json.loads((corpus / "MANIFEST.json").read_text(encoding="utf-8"))
    assert rec["identifiers_sha256"] == manifest["files"]["identifiers.json"]
    for s in (NAME, PLACE, DATE, NESTED, "Zebulon", "Infirmary", "treated", "report"):
        assert s not in raw
    assert "2091" not in tokenize(raw)          # whole-token: a hex digest may hold the digits


def test_main_prints_counts_only(corpus, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(P, "presidio_engine", lambda: (fake, {"presidio-analyzer": "x"}))
    assert P.main(cli(corpus, tmp_path)) == 0
    printed = capsys.readouterr().out
    assert "DIRECT survived 0/1 (present 1); one call 0/1 (present 1)" in printed
    assert "QUASI survived 3/3 (present 3); one call 2/3 (present 2)" in printed
    assert NAME not in printed and PLACE not in printed and "2091" not in printed


def test_a_refusal_happens_before_presidio_loads(corpus, tmp_path, monkeypatch, capsys):
    argv = cli(corpus, tmp_path)
    (corpus / "doc3.md").write_text("edited")

    def engine():
        raise AssertionError("Presidio loaded for a collection that does not match its manifest")

    monkeypatch.setattr(P, "presidio_engine", engine)
    assert P.main(argv) == 1
    assert "doc3.md does not match" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_other_versions_are_refused_before_presidio_is_imported(monkeypatch):
    from importlib import metadata
    monkeypatch.setattr(metadata, "version", lambda p: "0.0.1")
    with pytest.raises(P.Refusal, match=r"presidio-analyzer 0.0.1 \(pinned 2.2.362\)"):
        P.presidio_engine()


def test_the_pins_are_the_scope_pins():
    scope = " ".join((Path(__file__).resolve().parents[3] / "PRIVDEEP_ICCIT_SCOPE.md")
                     .read_text(encoding="utf-8").split())
    assert "presidio-analyzer and presidio-anonymizer 2.2.362" in scope
    assert "en_core_web_lg 3.8.0" in scope
    assert P.PINNED == {"presidio-analyzer": "2.2.362", "presidio-anonymizer": "2.2.362",
                        "en-core-web-lg": "3.8.0"}


# ----------------------------------------------------------------- Presidio itself


def test_presidio_default_configuration_on_a_synthetic_sentence():
    pytest.importorskip("presidio_analyzer")
    anonymise, versions = P.presidio_engine()
    assert versions["model_loaded"] == "en_core_web_lg 3.8.0"
    text, counts = anonymise(f"Mr {NAME} wrote to the court in Leeds on {DATE}.")
    assert NAME not in text and "<PERSON>" in text and counts.get("PERSON", 0) >= 1
