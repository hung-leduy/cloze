"""scripts/real_corpora/tab.py: track L's collections, built from TAB by rule (scope §12).

Everything but the last test runs on small synthetic judgments in TAB's format,
written to tmp_path with their own SHA256SUMS, so the rule is pinned without
the download. The synthetic applicant's name sits in ``meta`` and ``task``
only, so finding it in any written file means a field the rule forbids was
copied. The last test rebuilds from ``data/tab`` in memory, when the download is
present, and compares hashes with the committed manifest; it reads no text.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from privdeep.eval.faithfulness import load_key

from scripts import run_evaluation as R
from scripts.real_corpora import tab as T
from shared.shingle_filter import tokenize

REPO = Path(__file__).resolve().parents[3]
PINNED_SOURCES = T.SOURCE_SHA256       # taken before the autouse fixture unpins it
APPLICANT = "Zebulon Quixote"          # meta.applicant and task only, never in a text


def judgment(doc_id: str, text: str, mentions=(), *, annotators: int = 4,
             country: str = "GBR") -> dict:
    """A TAB-format judgment. `mentions` are (annotator index, span, identifier
    type, entity type); every annotator gets the mentions given for it."""
    ann: dict = {f"annotator{i}": {"entity_mentions": []} for i in range(1, annotators + 1)}
    for k, (a, span, itype, etype) in enumerate(mentions):
        start = max(text.find(span), 0)
        ann[f"annotator{a}"]["entity_mentions"].append({
            "entity_type": etype, "entity_mention_id": f"{doc_id}_a{a}_em{k}",
            "start_offset": start, "end_offset": start + len(span), "span_text": span,
            "edit_type": "check", "identifier_type": itype, "entity_id": f"{doc_id}_e{k}",
            "confidential_status": "NOT_CONFIDENTIAL"})
    return {"doc_id": doc_id, "text": text,
            "meta": {"year": 2001, "legal_branch": "CHAMBER", "articles": ["8"],
                     "countries": country, "applicant": APPLICANT},
            "task": f"Task: Annotate the document to anonymise the following person: {APPLICANT}",
            "annotations": ann, "quality_checked": [], "dataset_type": "dev"}


def plain(doc_id: str, n: int, **kw) -> dict:
    """An eligible judgment with one DIRECT name and one QUASI place of its own."""
    text = f"The applicant, Mr Alder{n}, was born in Harbourtown{n} and complained.\r\nÉtude {n}."
    return judgment(doc_id, text, [(1, f"Mr Alder{n}", "DIRECT", "PERSON"),
                                   (2, f"Harbourtown{n}", "QUASI", "LOC")], **kw)


def write_tab(d: Path, dev: list[dict], test: list[dict], extra: dict[str, bytes] | None = None
              ) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    files = {"echr_dev.json": json.dumps(dev).encode(), "echr_test.json": json.dumps(test).encode(),
             **(extra or {})}
    for name, data in files.items():
        (d / name).write_bytes(data)
    (d / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(b).hexdigest()}  {n}\n"
                                          for n, b in sorted(files.items())))
    return d


def default_dev() -> list[dict]:
    return [plain(f"001-{100 + i}", i) for i in range(6)]


def default_test() -> list[dict]:
    return [plain(f"001-{500 + i}", 50 + i) for i in range(26)]


@pytest.fixture(autouse=True)
def _unpinned(monkeypatch):
    # The synthetic splits are not the download scope §12.2 pins.
    monkeypatch.setattr(T, "SOURCE_SHA256", None)


@pytest.fixture
def paths(tmp_path):
    return {"tab": tmp_path / "tab", "out": tmp_path / "corpora",
            "manifest": tmp_path / "manifest_l.json", "tasks_dir": tmp_path}


def build_and_write(paths, dev=None, test=None, **kw) -> T.Build:
    if not paths["tab"].exists():
        write_tab(paths["tab"], dev or default_dev(), test or default_test())
    b = T.build(paths["tab"], paths["out"])
    T.write(b, paths["out"], paths["manifest"], paths["tasks_dir"], **kw)
    return b


# ---------------------------------------------------------------------------- the rule


def test_eligibility_and_order_follow_scope_12_3(paths):
    dev = [plain("001-9", 1), plain("001-10", 2),                 # "001-10" < "001-9"
           plain("001-11", 3, annotators=3),                        # too few annotators
           plain("001-12", 4, country="TUR"),                       # another state
           judgment("001-13", "x " * 4001, annotators=4),           # 8,002 characters
           plain("001-14", 5), plain("001-15", 6), plain("001-16", 7)]
    test = [plain(f"001-{900 - i}", 100 + i) for i in range(25)]
    write_tab(paths["tab"], dev, test)
    b = T.build(paths["tab"], paths["out"])
    ids = {c.id: (c.split, c.doc_ids) for c in b.collections}
    assert list(ids) == ["tab-L0", *(f"tab-L{i}" for i in range(1, 7))]
    assert ids["tab-L0"] == ("dev", ("001-10", "001-14", "001-15", "001-16"))
    first24 = sorted(d["doc_id"] for d in test)[:24]
    assert [d for i in range(1, 7) for d in ids[f"tab-L{i}"][1]] == first24
    assert all(ids[f"tab-L{i}"][0] == "test" for i in range(1, 7))


def test_exactly_8000_characters_is_eligible():
    assert T.is_eligible(judgment("a", "x" * 8000)) and not T.is_eligible(judgment("a", "x" * 8001))


@pytest.mark.parametrize("dev_n,test_n,which", [(3, 24, "dev"), (4, 23, "test")])
def test_too_few_eligible_judgments_refuses(paths, dev_n, test_n, which):
    write_tab(paths["tab"], default_dev()[:dev_n], default_test()[:test_n])
    with pytest.raises(T.Refusal, match=f"the {which} split has"):
        T.build(paths["tab"], paths["out"])


def test_checksums_are_verified_before_anything_is_read(paths):
    write_tab(paths["tab"], default_dev(), default_test(), {"README.md": b"readme"})
    (paths["tab"] / "README.md").write_bytes(b"changed")
    with pytest.raises(T.Refusal, match="README.md does not match"):
        T.build(paths["tab"], paths["out"])
    (paths["tab"] / "SHA256SUMS").unlink()
    with pytest.raises(T.Refusal, match="missing"):
        T.build(paths["tab"], paths["out"])


def test_a_split_missing_from_the_sums_refuses(paths):
    write_tab(paths["tab"], default_dev(), default_test())
    sums = paths["tab"] / "SHA256SUMS"
    sums.write_text("".join(ln + "\n" for ln in sums.read_text().splitlines()
                            if "echr_test" not in ln))
    with pytest.raises(T.Refusal, match="does not list echr_test.json"):
        T.build(paths["tab"], paths["out"])


def test_the_scope_pin_refuses_another_download(paths, monkeypatch):
    write_tab(paths["tab"], default_dev(), default_test())
    monkeypatch.setattr(T, "SOURCE_SHA256", {"echr_dev.json": "0" * 64})
    with pytest.raises(T.Refusal, match="not the download scope"):
        T.build(paths["tab"], paths["out"])


def test_the_scope_pin_is_the_scope_record():
    scope = (REPO / "PRIVDEEP_ICCIT_SCOPE.md").read_text(encoding="utf-8")
    pins = {"echr_dev.json": "8c3c7306f46b8d54debeb38ae11d8b0b8bcf4bdccbc3b6f13c12ad7be16893ec",
            "echr_test.json": "cd0f0f15f84a8739654c7cf30c6be8ce27b051ef73974d39d792a0cb8c846379"}
    for name, sha in pins.items():
        assert f"{sha[:8]}…{sha[-4:]}" in scope, name
    assert PINNED_SOURCES == pins


def test_goal_sharing_a_5gram_with_any_judgment_refuses(paths):
    # Ineligible (another state), and still refused: the scope's claim is
    # about every TAB judgment, not only the selected ones.
    dev = [*default_dev(), judgment("001-999", "Then the domestic proceedings described in "
                                               "these files ended.", country="TUR")]
    write_tab(paths["tab"], dev, default_test())
    with pytest.raises(T.Refusal, match=r"shares 2 5-gram\(s\) with judgment 001-999$") as e:
        T.build(paths["tab"], paths["out"])
    assert "proceedings" not in str(e.value)        # judgment text is never quoted


def test_four_goal_words_in_a_row_do_not_refuse():
    T.check_goal(T.GOAL, [judgment("a", "the domestic proceedings described, then nothing")])


def test_the_goal_is_the_scope_goal():
    scope = (REPO / "PRIVDEEP_ICCIT_SCOPE.md").read_text(encoding="utf-8")
    assert f'"{T.GOAL}"' in " ".join(scope.split())


# ---------------------------------------------------------------------------- the gold


def strings_of(docs, **kw) -> dict[str, T.IdentifierString]:
    return {s.text: s for s in T.identifier_strings(docs, T.GOAL, T.load_function_words(), **kw)}


def test_identifier_strings_are_unified_by_tokens_and_typed_per_scope_12_4():
    text = "Mr Alder met MR. ALDER in Leeds; the Leeds Trust, the applicants and the UK."
    doc = judgment("d1", text, [
        (2, "MR. ALDER", "QUASI", "PERSON"),     # annotator2 sorts after annotator10
        (10, "Mr Alder", "DIRECT", "PERSON"),    # DIRECT wins; annotator10's spelling first
        (1, "Leeds", "QUASI", "LOC"), (3, "Leeds", "QUASI", "ORG"),
        (1, "the Leeds Trust", "NO_MASK", "ORG"),      # not an identifier
        (1, "the applicants", "QUASI", "DEM"),         # goal and function words only
        (1, "UK", "QUASI", "LOC"),                     # two characters
    ], annotators=10)
    s = strings_of([doc])
    assert set(s) == {"Mr Alder", "Leeds", "the applicants", "UK"}
    assert s["Mr Alder"].identifier_type == "DIRECT"
    assert s["Mr Alder"].entity_types == ("PERSON",) and not s["Mr Alder"].label
    assert s["Leeds"].identifier_type == "QUASI" and s["Leeds"].entity_types == ("LOC", "ORG")
    assert s["the applicants"].label and s["UK"].label


def test_the_first_seen_spelling_follows_offsets_within_an_annotator():
    text = "MR ALDER then Mr Alder."
    doc = judgment("d1", text, [(1, "Mr Alder", "QUASI", "PERSON"),
                                (1, "MR ALDER", "QUASI", "PERSON")])
    assert list(strings_of([doc])) == ["MR ALDER"]


@pytest.mark.parametrize("span,label", [("UK", True), ("7", True), ("12", True), ("(7)", True),
                                        ("123", False), ("—", True), ("the Court", False),
                                        ("in their case", True), ("Smith's", False),
                                        # Two tokens need a separator: initials stay identifiers.
                                        ("U.K.", False), ("A.B.", False), ("J B", False)])
def test_the_labels_rule_reads_tokens(span, label):
    fw = T.load_function_words()
    assert T.is_label(tokenize(span), frozenset(tokenize(T.GOAL)), fw) is label


def test_a_type_tab_does_not_define_refuses_without_quoting_the_span():
    doc = judgment("d1", "Secret Name here", [(1, "Secret Name", "QUASI", "NAME")])
    with pytest.raises(T.Refusal, match="d1, annotator1 mention 0") as e:
        T.identifier_strings([doc])
    assert "Secret" not in str(e.value)


def test_function_words_are_single_lowercase_tokens_and_hold_no_goal_content_word():
    fw = T.load_function_words()
    assert {"the", "of", "and", "s"} <= fw and 50 < len(fw) < 200
    assert not fw & {"compare", "applicants", "situations", "complaints", "domestic",
                     "proceedings", "described", "case", "files"}


# ---------------------------------------------------------------------------- the files


def test_a_collection_directory_holds_exactly_the_contract_files(paths):
    b = build_and_write(paths)
    for c in b.collections:
        d = paths["out"] / c.id
        assert {p.name for p in d.iterdir()} == set(T.COLLECTION_NAMES)
        assert len([p for p in d.iterdir() if p.suffix == ".md"]) == 4


def test_documents_are_written_verbatim_in_doc_id_order(paths):
    dev = default_dev()
    build_and_write(paths, dev=dev)
    for name, doc in zip(T.DOC_NAMES, sorted(dev, key=lambda d: d["doc_id"]), strict=False):
        assert (paths["out"] / "tab-L0" / name).read_bytes() == doc["text"].encode("utf-8")
    assert b"\r\n" in (paths["out"] / "tab-L0" / "doc1.md").read_bytes()


def test_surfaces_identifiers_and_key_shapes(paths):
    dev = default_dev()
    dev[0] = judgment("001-100", "Mr Alder of Leeds, aged 7, of the UK.", [
        (1, "Mr Alder", "DIRECT", "PERSON"), (1, "Leeds", "QUASI", "LOC"),
        (2, "Leeds", "QUASI", "ORG"), (1, "7", "QUASI", "QUANTITY"),
        (3, "UK", "DIRECT", "LOC")])                     # DIRECT and a label
    build_and_write(paths, dev=dev)
    d = paths["out"] / "tab-L0"
    groups = json.loads((d / "surfaces.json").read_text())["groups"]
    assert set(groups) == {"direct", "labels", *(f"quasi_{t.lower()}" for t in T.ENTITY_TYPES)}
    assert "Mr Alder" in groups["direct"] and "UK" not in groups["direct"]
    assert {"7", "UK"} <= set(groups["labels"])
    assert "Leeds" in groups["quasi_loc"] and "Leeds" in groups["quasi_org"]

    ident = json.loads((d / "identifiers.json").read_text())
    assert ident["collection"] == "tab-L0"
    row = next(s for s in ident["strings"] if s["text"] == "Leeds")
    assert row == {"text": "Leeds", "identifier_type": "QUASI", "entity_types": ["LOC", "ORG"],
                   "label": False}
    assert ident["strings"][0]["identifier_type"] == "DIRECT"

    raw = json.loads((d / "smoke_fact_key.json").read_text())
    assert raw["generated_by"] == "scripts/real_corpora/tab.py" and raw["scenario"] == "tab-L0"
    assert (raw["referents"], raw["attributes"], raw["facts"], raw["mask_patterns"]) == (
        {}, {}, [], [])
    facts = raw["string_facts"]
    assert [f["fact_id"] for f in facts] == [f"tab-L0.S{i}" for i in range(1, len(facts) + 1)]
    assert {(f["attribute"], f["value"]) for f in facts if f["value"] == "Leeds"} == {
        ("QUASI_LOC", "Leeds"), ("QUASI_ORG", "Leeds")}
    assert all(f["subject"] == "TAB" for f in facts)
    assert not {"7", "UK"} & {f["value"] for f in facts}           # labels are apart
    assert load_key(d / "smoke_fact_key.json").string_facts == facts


def test_manifests_hash_every_file_and_the_summary_repeats_them(paths):
    b = build_and_write(paths)
    summary = json.loads(paths["manifest"].read_text())
    for c in b.collections:
        d = paths["out"] / c.id
        m = json.loads((d / "MANIFEST.json").read_text())
        assert set(m) == {"collection", "split", "doc_ids", "source_sha256", "files"}
        assert m["files"] == {n: hashlib.sha256((d / n).read_bytes()).hexdigest()
                              for n in T.DATA_NAMES}
        src = paths["tab"] / T.SPLITS[m["split"]]
        assert m["source_sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()
        assert summary["collections"][c.id] == m
    assert summary["rule"]["function_words_sha256"] == hashlib.sha256(
        T.FUNCTION_WORDS.read_bytes()).hexdigest()


def test_no_meta_task_or_identifier_string_reaches_a_committed_file(paths):
    b = build_and_write(paths)
    for p in paths["out"].rglob("*"):
        if p.is_file():
            assert APPLICANT not in p.read_text(encoding="utf-8"), p
    strings = [s.text for c in b.collections for s in c.strings]
    for p in (paths["manifest"], paths["tasks_dir"] / "tasks_l.json",
              paths["tasks_dir"] / "tasks_l_dev.json"):
        text = p.read_text(encoding="utf-8")
        assert APPLICANT not in text
        assert not R.token_hits(text, strings), p


def test_building_twice_is_byte_identical(paths):
    a = build_and_write(paths)
    b = T.build(paths["tab"], paths["out"])
    assert a.summary == b.summary and a.tasks == b.tasks
    assert [c.files for c in a.collections] == [c.files for c in b.collections]


def test_tasks_files_load_and_point_at_the_collections(paths):
    build_and_write(paths)
    dev = R.load_tasks(paths["tasks_dir"] / "tasks_l_dev.json")
    test = R.load_tasks(paths["tasks_dir"] / "tasks_l.json")
    assert [t.id for t in dev] == ["tab-L0"]
    assert [t.id for t in test] == [f"tab-L{i}" for i in range(1, 7)]
    assert all(t.goal == T.GOAL and t.corpus == (paths["out"] / t.id).resolve()
               for t in dev + test)
    groups, src = R.surface_groups_for(dev[0])
    assert "direct" in groups and src.endswith("tab-L0/surfaces.json")


def test_file_names_are_the_ones_run_evaluation_reads():
    assert T.KEY_NAME == R.FACT_KEY_NAME and T.SURFACES_NAME == R.SURFACES_NAME


# ------------------------------------------------------------------ write, check, refuse


def test_check_passes_on_a_fresh_build_and_names_each_difference(paths):
    b = build_and_write(paths)
    args = (b, paths["out"], paths["manifest"], paths["tasks_dir"])
    assert T.check(*args) == []
    (paths["out"] / "tab-L3" / "doc2.md").write_text("edited")
    (paths["out"] / "tab-L1" / "notes.md").write_text("stray")
    (paths["out"] / "tab-L2" / "surfaces.json").unlink()
    problems = T.check(*args)
    assert "tab-L3/doc2.md differs from this build" in problems
    assert any("tab-L1 holds entries the rule does not write: notes.md" in p for p in problems)
    assert "tab-L2 lacks surfaces.json" in problems


def test_check_writes_nothing_and_fails_on_a_missing_build(paths, capsys):
    write_tab(paths["tab"], default_dev(), default_test())
    argv = ["--tab", str(paths["tab"]), "--out", str(paths["out"]), "--manifest",
            str(paths["manifest"]), "--tasks-dir", str(paths["tasks_dir"])]
    assert T.main([*argv, "--check"]) == 1
    assert not paths["out"].exists() and not paths["manifest"].exists()
    assert T.main(argv) == 0
    assert T.main([*argv, "--check"]) == 0
    out = capsys.readouterr()
    assert "check: ok, 7 collections" in out.out
    assert "Alder" not in out.out + out.err and "Harbourtown" not in out.out + out.err


def test_a_changed_build_does_not_silently_rewrite_the_committed_manifest(paths):
    build_and_write(paths)
    before = paths["manifest"].read_bytes()
    dev = default_dev()
    dev[0] = plain("001-100", 77)
    write_tab(paths["tab"], dev, default_test())
    b = T.build(paths["tab"], paths["out"])
    with pytest.raises(T.Refusal, match=r"manifest_l.json \(entries sources, collections.tab-L0\)"):
        T.write(b, paths["out"], paths["manifest"], paths["tasks_dir"])
    assert paths["manifest"].read_bytes() == before
    assert T.check(b, paths["out"], paths["manifest"], paths["tasks_dir"])
    T.write(b, paths["out"], paths["manifest"], paths["tasks_dir"], update_committed=True)
    assert T.check(b, paths["out"], paths["manifest"], paths["tasks_dir"]) == []


GIT = shutil.which("git")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    assert GIT
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")}
    return subprocess.run([GIT, "-C", str(cwd), *args], env=env,  # noqa: S603
                          capture_output=True, text=True, check=False)


@pytest.mark.skipif(GIT is None, reason="needs git")
def test_judgment_text_is_written_only_where_git_ignores_it(paths, tmp_path, monkeypatch):
    """Inside the repository a collection directory must be gitignored, or the
    builder writes nothing: TAB text is never to be staged (scope §12.2)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "-q").returncode == 0
    (repo / ".gitignore").write_text("ignored/\n")
    monkeypatch.setattr(T, "_REPO", repo)
    write_tab(paths["tab"], default_dev(), default_test())
    b = T.build(paths["tab"], repo / "kept")
    with pytest.raises(T.Refusal, match=r"only be written where git ignores it; kept/tab-L0 "
                                        r"\(not ignored\)"):
        T.write(b, repo / "kept", paths["manifest"], paths["tasks_dir"])
    assert not (repo / "kept").exists() and not paths["manifest"].exists()
    T.write(b, repo / "ignored", paths["manifest"], paths["tasks_dir"])
    assert (repo / "ignored" / "tab-L6" / "doc4.md").is_file()


@pytest.mark.skipif(GIT is None, reason="needs git")
def test_the_repository_ignores_every_track_l_path_that_holds_tab_text():
    """The .gitignore lines track L depends on, pinned: judgment text, run
    directories, attempts, outputs, the pilot and the download stay ignored,
    and the three committed files do not."""
    ignored = ["eval/real/corpora/tab-L1/doc1.md", "eval/real/corpora/tab-L1/identifiers.json",
               "eval/real/runs/tab-L1__r5/egress_trace.jsonl",
               "eval/real/runs/tab-L1__control/adversary_output.txt",
               "eval/real/attempts/tab-L1__r5__attempt1/egress_trace.jsonl",
               "eval/real/out/presidio_tab-L1.json", "eval/real/out/real_l_scan.json",
               "eval/pilot/real-l/runs/tab-L0__r5/egress_trace.jsonl",
               "eval/pilot/real-l/attempts/tab-L0__r5__attempt1/report.md",
               "data/tab/echr_test.json", "data/tab/echr_dev.json"]
    for rel in ignored:
        assert _git(REPO, "check-ignore", "-q", "--", rel).returncode == 0, rel
    for rel in ("eval/real/manifest_l.json", "eval/real/tasks_l.json",
                "eval/real/tasks_l_dev.json", "scripts/real_corpora/tab.py"):
        assert _git(REPO, "check-ignore", "-q", "--", rel).returncode == 1, rel


def test_a_directory_with_foreign_files_is_refused_before_anything_is_written(paths):
    paths["out"].joinpath("tab-L4").mkdir(parents=True)
    paths["out"].joinpath("tab-L4", "doc5.md").write_text("left over")
    with pytest.raises(T.Refusal, match=r"tab-L4 holds entries the rule does not write \(doc5"):
        build_and_write(paths)
    assert not paths["out"].joinpath("tab-L0").exists() and not paths["manifest"].exists()


# ---------------------------------------------------------------- the committed record


def test_the_committed_tasks_and_manifest_agree_with_the_rule():
    real = REPO / "eval" / "real"
    dev = json.loads((real / "tasks_l_dev.json").read_text(encoding="utf-8"))
    test = json.loads((real / "tasks_l.json").read_text(encoding="utf-8"))
    assert dev == [{"id": "tab-L0", "corpus": "eval/real/corpora/tab-L0", "goal": T.GOAL}]
    assert test == [{"id": f"tab-L{i}", "corpus": f"eval/real/corpora/tab-L{i}", "goal": T.GOAL}
                    for i in range(1, 7)]
    summary = json.loads((real / "manifest_l.json").read_text(encoding="utf-8"))
    assert list(summary["collections"]) == ["tab-L0", *(f"tab-L{i}" for i in range(1, 7))]
    assert summary["rule"]["goal"] == T.GOAL
    assert summary["rule"]["function_words_sha256"] == hashlib.sha256(
        T.FUNCTION_WORDS.read_bytes()).hexdigest()
    for cid, m in summary["collections"].items():
        assert len(m["doc_ids"]) == 4 and set(m["files"]) == set(T.DATA_NAMES)
        assert m["split"] == ("dev" if cid == "tab-L0" else "test")
        assert m["source_sha256"] == summary["sources"][m["split"]]["sha256"]
    ids = [d for m in summary["collections"].values() for d in m["doc_ids"]]
    assert len(set(ids)) == len(ids) == 28


@pytest.mark.skipif(not (REPO / "data" / "tab" / "SHA256SUMS").is_file(),
                    reason="the TAB download (data/tab, gitignored) is not here")
def test_the_committed_manifest_is_what_the_rule_builds_from_tab(monkeypatch):
    monkeypatch.setattr(T, "SOURCE_SHA256", PINNED_SOURCES)     # the real download is pinned
    b = T.build(REPO / "data" / "tab", T.DEFAULT_OUT)
    assert b.summary == (REPO / "eval" / "real" / "manifest_l.json").read_bytes()
    for name, data in b.tasks.items():
        assert data == (REPO / "eval" / "real" / name).read_bytes()


# The files track L commits or will commit: the rule, the scripts, the record and
# the tests. None may hold a real identifier string, even by coincidence.
TRACK_L_FILES = ("scripts/real_corpora/__init__.py", "scripts/real_corpora/tab.py",
                 "scripts/real_corpora/function_words.txt", "scripts/real_l.py",
                 "scripts/presidio_residual.py", "scripts/freeze_batch_real.sh",
                 "eval/real/manifest_l.json", "eval/real/tasks_l.json",
                 "eval/real/tasks_l_dev.json", "backend/tests/unit/test_real_tab.py",
                 "backend/tests/unit/test_real_l.py",
                 "backend/tests/unit/test_presidio_residual.py")


def _ngrams(tokens: list[str], lengths: set[int]) -> set[tuple[str, ...]]:
    return {tuple(tokens[i:i + n]) for n in lengths for i in range(len(tokens) - n + 1)}


@pytest.mark.skipif(not (REPO / "data" / "tab" / "SHA256SUMS").is_file(),
                    reason="the TAB download (data/tab, gitignored) is not here")
def test_no_real_identifier_string_stands_in_a_track_l_file(monkeypatch):
    """Every non-label DIRECT string and every string of two or more tokens, of
    every collection, against the track-L files, each string on its own and
    whole-token. A failure names the file, the collection, the type and the
    token count, never the string: the test collections' strings are not to be
    read. Single-token QUASI strings are left out, as they are ordinary words
    and numerals (descriptive by scope §12.7) and would match code at random."""
    monkeypatch.setattr(T, "SOURCE_SHA256", PINNED_SOURCES)
    b = T.build(REPO / "data" / "tab", T.DEFAULT_OUT)
    files = {rel: tokenize((REPO / rel).read_text(encoding="utf-8"))
             for rel in TRACK_L_FILES if (REPO / rel).is_file()}
    found = []
    for c in b.collections:
        wanted = [s for s in c.strings
                  if (s.identifier_type == "DIRECT" and not s.label) or len(s.tokens) > 1]
        lengths = {len(s.tokens) for s in wanted}
        for rel, toks in files.items():
            grams = _ngrams(toks, lengths)
            found += [(rel, c.id, s.identifier_type, len(s.tokens))
                      for s in wanted if s.tokens in grams]
    assert found == [], f"{len(found)} real identifier string(s) in track-L files: {found}"
