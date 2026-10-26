"""The evaluation driver, exercised offline against a scripted cloud.

A driver is the one script whose first real execution costs money, so its
failure modes have to be found without spending any. What is pinned here is
mostly refusal behaviour: no key, no phase-one run, no `--yes`, an entity file
that is missing. Each of those, unguarded, either burns credit for nothing or
produces a number scored against the wrong thing.

The aggregation half is pure arithmetic over on-disk artifacts and is tested
directly, because that is what turns into the paper's tables.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest import mock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import run_evaluation as R  # noqa: E402
from privdeep.audit.manifest import RunManifest  # noqa: E402
from privdeep.eval.judge import RUBRIC  # noqa: E402
from privdeep.tier2_cloud.cloud_client import CloudClient  # noqa: E402

CORPUS_TEXT = "Project Zephyr revenue fell after the Hanoi pilot was cancelled in August."

CLEAN = R.Provenance("c0ffee" * 6 + "abcd", "f" * 64, False)
_REAL_HOST_PROVENANCE = R.host_provenance


@pytest.fixture(autouse=True)
def clean_tree(monkeypatch):
    """Every test runs as though on a clean, committed tree.

    Without this the suite's result would depend on whether the checkout
    running it has uncommitted edits, which during development it always
    does. The refusal itself is tested on its own, with the tree set dirty.
    """
    monkeypatch.setattr(R, "host_provenance", lambda root=R._REPO: CLEAN)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A corpus, a completed phase-one run, and a tasks file pointing at them."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "memo.md").write_text(CORPUS_TEXT, encoding="utf-8")

    runs = tmp_path / "runs"
    run_dir = runs / "t1"
    run_dir.mkdir(parents=True)
    (run_dir / "report.md").write_text("# Goal\n\nHanoi hosted the pilot.", encoding="utf-8")
    (run_dir / "egress_trace.jsonl").write_text(
        json.dumps({"label": "plan", "request_text": "abstract payload"}) + "\n",
        encoding="utf-8")
    (run_dir / "entities.json").write_text(
        json.dumps([{"text": "Hanoi", "category": "LOCATION"},
                    {"text": "Project Zephyr", "category": "PROJECT"}]), encoding="utf-8")

    tasks = tmp_path / "tasks.json"
    tasks.write_text(json.dumps(
        [{"id": "t1", "corpus": str(corpus), "goal": "Assess the pilot."}]), encoding="utf-8")
    return tasks, runs, corpus


class Cloud:
    """Answers the oracle's plan tool, then drafts, then the judge, then the adversary."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        self.calls.append(body)
        usage = {"input_tokens": 100, "output_tokens": 20,
                 "cache_read_input_tokens": 40, "cache_creation_input_tokens": 10}
        tool = (body.get("tools") or [{}])[0].get("name")
        if tool == "plan_outline":
            return httpx.Response(200, json={
                "model": "claude-sonnet-5-x", "stop_reason": "tool_use", "usage": usage,
                "content": [{"type": "tool_use", "input": {"sections": [
                    {"title": "Findings", "objective": "o", "word_budget": 200,
                     "slot_ids": []}]}}]})
        if tool == "score_reports":
            # Keyed by the real RUBRIC, so a criterion rename breaks this test
            # rather than silently scoring every criterion 0.
            scores = {name: 4 for name, _ in RUBRIC}
            return httpx.Response(200, json={
                "model": "claude-sonnet-5-x", "stop_reason": "tool_use", "usage": usage,
                "content": [{"type": "tool_use",
                             "input": {"A": scores, "B": dict(scores, **{RUBRIC[0][0]: 2}),
                                       "rationale": "r"}}]})
        return httpx.Response(200, json={
            "model": "claude-sonnet-5-x", "stop_reason": "end_turn", "usage": usage,
            "content": [{"type": "text", "text": "Hanoi appears here."}]})


class TestRefusalsThatSaveMoney:
    def test_measure_refuses_without_yes(self, workspace, monkeypatch, capsys):
        tasks, runs, _ = workspace
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-" + "y" * 40)
        rc = R.main(["measure", "--tasks", str(tasks), "--runs", str(runs)])
        assert rc == 1
        assert "refusing to spend" in capsys.readouterr().out

    @pytest.mark.parametrize("key", ["", "sk-ant-placeholder", "short"])
    def test_measure_refuses_a_missing_or_placeholder_key(self, workspace, monkeypatch, key):
        """The two live egress attempts on record are placeholder-key 401s. A
        driver that starts anyway burns the phase-two budget on nothing."""
        tasks, runs, _ = workspace
        monkeypatch.setenv("ANTHROPIC_API_KEY", key)
        with pytest.raises(SystemExit, match="placeholder|unset"):
            R.main(["measure", "--tasks", str(tasks), "--runs", str(runs), "--yes"])

    def test_an_estimate_is_printed_before_anything_is_spent(self, workspace, capsys):
        tasks, runs, _ = workspace
        R.main(["measure", "--tasks", str(tasks), "--runs", str(runs)])
        out = capsys.readouterr().out
        assert "estimated cost" in out and "TOTAL" in out and "$" in out

    def test_a_task_without_a_phase_one_run_is_skipped_not_measured(
            self, workspace, monkeypatch, capsys):
        tasks, runs, _ = workspace
        (runs / "t1" / "report.md").unlink()
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-" + "y" * 40)
        R.main(["measure", "--tasks", str(tasks), "--runs", str(runs), "--yes"])
        assert "run `private` first" in capsys.readouterr().out

    def test_a_missing_entity_file_is_an_error_not_a_re_extraction(self, workspace):
        """Re-extracting would run a probabilistic model a second time and score
        recovery against entities the run never issued a slot for."""
        _tasks, runs, _ = workspace
        (runs / "t1" / "entities.json").unlink()
        with pytest.raises(SystemExit, match="entities.json"):
            R._load_run(runs / "t1")

    def test_duplicate_task_ids_are_refused(self, tmp_path, workspace):
        tasks, _runs, corpus = workspace
        dup = tmp_path / "dup.json"
        dup.write_text(json.dumps([
            {"id": "t1", "corpus": str(corpus), "goal": "a"},
            {"id": "t1", "corpus": str(corpus), "goal": "b"}]), encoding="utf-8")
        with pytest.raises(SystemExit, match="unique"):
            R.load_tasks(dup)

    def test_an_empty_corpus_is_refused_before_the_container_starts(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        f = tmp_path / "t.json"
        f.write_text(json.dumps([{"id": "x", "corpus": str(empty), "goal": "g"}]), "utf-8")
        with pytest.raises(SystemExit, match="no supported documents"):
            R.load_tasks(f)


class TestPhaseTwoProducesTheArtifacts:
    def test_one_task_end_to_end_against_a_scripted_cloud(self, workspace):
        tasks_file, runs, _ = workspace
        task = R.load_tasks(tasks_file)[0]
        c = Cloud()
        cloud = CloudClient("https://api.anthropic.invalid", api_key="k",
                            transport=httpx.MockTransport(c))
        res = run(R.measure_task(task, runs / "t1", cloud, judge_repeats=1,
                                 max_doc_chars=60_000))

        for name in ("oracle.json", "oracle_report.md", "judge.json",
                     "reconstruction.json", "measurement.json"):
            assert (runs / "t1" / name).exists(), name

        assert res["task_id"] == "t1"
        # This scripted judge is purely positional: whatever sits in slot A
        # scores 4 everywhere, whatever sits in B loses two points on the first
        # criterion. Scoring both orderings therefore has to cancel it out to
        # equal means and surface it as bias instead — which is the entire
        # reason both orderings are run, and the only defence left now that
        # Sonnet 5 has no determinism setting.
        j = res["judgements"][0]
        assert j["private_mean"] == pytest.approx(j["oracle_mean"]), "position bias not cancelled"
        assert j["private_mean"] == pytest.approx(3.75)
        assert j["position_bias"] > 0, "a positional judge must be reported, not averaged away"
        assert res["reconstruction"]["entities_total"] == 2
        assert res["usd"]["oracle"] > 0

    def test_the_adversary_is_accounted_like_the_oracle_and_the_judge(self, workspace):
        """INS4: its tokens reach reconstruction.json and the per-run spend.
        Before, the adversary call was billed and counted nowhere."""
        tasks_file, runs, _ = workspace
        task = R.load_tasks(tasks_file)[0]
        cloud = CloudClient("https://api.anthropic.invalid", api_key="k",
                            transport=httpx.MockTransport(Cloud()))
        res = run(R.measure_task(task, runs / "t1", cloud, judge_repeats=1,
                                 max_doc_chars=60_000))
        on_disk = json.loads((runs / "t1" / "reconstruction.json").read_text("utf-8"))
        for k in ("trace_chars", "trace_truncated", "adversary_tokens_in",
                  "adversary_tokens_out"):
            assert k in on_disk, k
        assert on_disk["trace_truncated"] is False and on_disk["trace_chars"] > 0
        assert res["usage"]["adversary"] == {"input_tokens": 100, "output_tokens": 20}
        assert res["usd"]["adversary"] == pytest.approx(100 * R.USD_IN + 20 * R.USD_OUT)

    def test_judge_repeats_give_a_spread_for_a_judge_with_no_determinism_knob(self, workspace):
        tasks_file, runs, _ = workspace
        task = R.load_tasks(tasks_file)[0]
        cloud = CloudClient("https://api.anthropic.invalid", api_key="k",
                            transport=httpx.MockTransport(Cloud()))
        res = run(R.measure_task(task, runs / "t1", cloud, judge_repeats=3,
                                 max_doc_chars=60_000))
        assert len(res["judgements"]) == 3
        assert [j["repeat"] for j in res["judgements"]] == [0, 1, 2]

    def test_cache_tokens_are_carried_into_the_cost(self, workspace):
        """A breakpoint that stops working shows up nowhere else."""
        tasks_file, runs, _ = workspace
        task = R.load_tasks(tasks_file)[0]
        cloud = CloudClient("https://api.anthropic.invalid", api_key="k",
                            transport=httpx.MockTransport(Cloud()))
        res = run(R.measure_task(task, runs / "t1", cloud, judge_repeats=1,
                                 max_doc_chars=60_000))
        assert res["usage"]["oracle"]["cache_read_tokens"] > 0
        assert res["usage"]["oracle"]["cache_write_tokens"] > 0


def _healthy_manifest(arm: str | None, **over) -> dict:
    """A manifest that passes the INS2 health gate: one planned section with a
    drafter reply, slots offered, and the planner counters in their fields."""
    m = {"arm": arm, "evidence": [], "facts": {}, "slots_issued": 2,
         "notes": ["plan: 1 sections, 0 unknown slot refs dropped, 0 budgets clamped"],
         "planner_refs_returned": 2, "planner_refs_dropped": 0,
         "sections": [{"section_id": "s1", "slots_offered": 2, "refused": None,
                       "sentences_pruned": 0, "facts_unavailable": 0}]}
    m.update(over)
    return m


class TestAggregation:
    def _measured(self, runs: Path, *, dirname: str | None = None,
                  manifest: dict | None = None, **over) -> None:
        """One measured run. `arm` defaults to r5; `arm=None` writes a
        measurement with no arm at all, as runs made before the flag were.
        The run directory also gets a healthy manifest and a report, unless
        `manifest` says otherwise, so the health gate lets it into the pool."""
        base = {
            "task_id": "t1", "arm": "r5", "goal": "g", "corpus_chars": 100,
            "corpus_documents": 1,
            "oracle_truncated_chars": 0, "oracle_max_doc_chars": 60_000,
            "judgements": [{"repeat": 0, "private": {"coverage": 4}, "oracle": {"coverage": 2},
                            "private_mean": 4.0, "oracle_mean": 2.0, "position_bias": 0.5,
                            "private_by_order": [], "oracle_by_order": [],
                            "criteria": ["coverage"], "judge_models": ["m"],
                            "input_tokens": 1, "output_tokens": 1}],
            "reconstruction": {"entities_total": 10, "entities_recovered": 1,
                               "entity_recovery": 0.1, "fivegrams_total": 20,
                               "fivegrams_recovered": 0, "fivegram_recovery": 0.0,
                               "by_category": {"LOCATION": {"total": 10, "recovered": 1}},
                               "adversary_model": "m"},
            "usage": {}, "usd": {"oracle": 0.4, "judge": 0.1},
        }
        base.update(over)
        base = {k: v for k, v in base.items() if not (k == "arm" and v is None)}
        d = runs / (dirname or base["task_id"])
        d.mkdir(parents=True, exist_ok=True)
        (d / "measurement.json").write_text(json.dumps(base), encoding="utf-8")
        (d / "manifest.json").write_text(
            json.dumps(manifest if manifest is not None else _healthy_manifest(base.get("arm"))),
            encoding="utf-8")
        if not (d / "report.md").exists():
            (d / "report.md").write_text("# g\n\nA report.", encoding="utf-8")

    def test_tables_carry_both_arms_and_no_interval(self, tmp_path, workspace):
        """INS2: no Wilson interval over pooled entities. The runs share one
        corpus and one extraction, so the pooled entities are not independent
        draws; the per-run spread is reported instead."""
        _tasks, runs, corpus = workspace
        self._measured(runs)
        tasks = [R.Task("t1", corpus, "g")]
        rep = R.aggregate(tasks, runs)
        assert rep["utility"]["private_mean"]["mean"] == 4.0
        assert rep["utility"]["oracle_mean"]["mean"] == 2.0, "the oracle's own score must be there"
        ent = rep["reconstruction"]["entity_recovery"]
        assert ent["recovered"] == 1 and ent["total"] == 10
        assert "wilson95" not in json.dumps(rep)
        assert ent["per_run"]["values"] == [0.1]
        assert rep["cost_usd"]["total"] == pytest.approx(0.5)
        # A pre-INS4 measurement recorded no adversary spend: unknown, not $0.
        assert rep["cost_usd"]["adversary"] is None
        assert rep["cost_usd"]["incomplete"] == ["adversary"]

    def test_a_recorded_adversary_bucket_is_summed(self, tmp_path, workspace):
        _tasks, runs, corpus = workspace
        self._measured(runs, usd={"oracle": 0.4, "judge": 0.1, "adversary": 0.05})
        rep = R.aggregate([R.Task("t1", corpus, "g")], runs)
        assert rep["cost_usd"]["adversary"] == pytest.approx(0.05)
        assert rep["cost_usd"]["total"] == pytest.approx(0.55)
        assert rep["cost_usd"]["incomplete"] == []

    def test_per_task_values_survive_into_the_artifact(self, tmp_path, workspace):
        """At this N the spread is the finding; a mean alone cannot be checked."""
        _tasks, runs, corpus = workspace
        self._measured(runs)
        self._measured(runs, task_id="t2",
                       judgements=[{"repeat": 0, "private": {"coverage": 2},
                                    "oracle": {"coverage": 2}, "private_mean": 2.0,
                                    "oracle_mean": 2.0, "position_bias": 0.0,
                                    "private_by_order": [], "oracle_by_order": [],
                                    "criteria": ["coverage"], "judge_models": ["m"],
                                    "input_tokens": 1, "output_tokens": 1}])
        rep = R.aggregate([R.Task("t1", corpus, "g"), R.Task("t2", corpus, "g")], runs)
        assert rep["utility"]["private_mean"]["values"] == [4.0, 2.0]
        assert rep["utility"]["private_mean"]["stdev"] is not None
        assert rep["tasks_measured"] == 2

    def test_a_truncated_oracle_is_named_in_the_artifact(self, tmp_path, workspace):
        """A task whose baseline read a prefix while PrivDeep read everything
        must not be pooled silently."""
        _tasks, runs, corpus = workspace
        self._measured(runs, oracle_truncated_chars=5_000)
        rep = R.aggregate([R.Task("t1", corpus, "g")], runs)
        assert rep["truncated_tasks"]["ids"] == ["t1"]

    def test_aggregating_nothing_does_not_crash_or_invent_a_mean(self, workspace, corpus=None):
        _tasks, runs, corpus = workspace
        rep = R.aggregate([R.Task("t1", corpus, "g")], runs)
        assert rep["tasks_measured"] == 0
        assert rep["utility"]["private_mean"]["mean"] is None
        assert rep["reconstruction"]["entity_recovery"]["rate"] is None

    def test_the_artifact_records_its_own_provenance(self, workspace):
        _tasks, runs, corpus = workspace
        self._measured(runs)
        rep = R.aggregate([R.Task("t1", corpus, "g")], runs)
        assert rep["instrument"] == "scripts/run_evaluation.py"
        assert rep["git_commit"] and rep["resolved_models"] == ["m"]


class TestWhatTheJudgeSeesAndWhatIsKept:
    """Two things the first live measurement showed the driver doing wrong."""

    def _escaped_workspace(self, workspace):
        tasks_file, runs, _ = workspace
        (runs / "t1" / "report.md").write_text(
            "# Goal\n\nSpend was 187,432\\.55 on 2026\\-06\\-01 at Hanoi.", encoding="utf-8")
        return R.load_tasks(tasks_file)[0], runs

    def test_the_judge_reads_both_arms_without_markdown_escapes(self, workspace):
        """42 escapes in the private report and none in the oracle's is a
        presentation difference between arms, and the judge scores coherence."""
        task, runs = self._escaped_workspace(workspace)
        c = Cloud()
        cloud = CloudClient("https://api.anthropic.invalid", api_key="k",
                            transport=httpx.MockTransport(c))
        run(R.measure_task(task, runs / "t1", cloud, judge_repeats=1, max_doc_chars=60_000))
        judged = [b for b in c.calls if (b.get("tools") or [{}])[0].get("name") == "score_reports"]
        assert judged, "the judge was never called"
        for body in judged:
            text = body["messages"][0]["content"]
            assert "187,432.55" in text and "2026-06-01" in text
            assert "\\." not in text and "\\-" not in text

    def test_rationales_and_adversary_output_are_kept_beside_the_run(self, workspace):
        """Both are paid for on every call. Both were discarded."""
        task, runs = self._escaped_workspace(workspace)
        cloud = CloudClient("https://api.anthropic.invalid", api_key="k",
                            transport=httpx.MockTransport(Cloud()))
        run(R.measure_task(task, runs / "t1", cloud, judge_repeats=2, max_doc_chars=60_000))
        rat = json.loads((runs / "t1" / "judge_rationales.json").read_text("utf-8"))
        assert [r["repeat"] for r in rat] == [0, 1]
        assert (runs / "t1" / "adversary_output.txt").read_text("utf-8") == "Hanoi appears here."

    def test_neither_reaches_the_aggregate(self, workspace):
        """The aggregate is the artifact meant for tables. A rationale can quote
        the private report and the adversary output is an attempt to recover it,
        so neither may appear in measurement.json or evaluation.json."""
        task, runs = self._escaped_workspace(workspace)
        cloud = CloudClient("https://api.anthropic.invalid", api_key="k",
                            transport=httpx.MockTransport(Cloud()))
        run(R.measure_task(task, runs / "t1", cloud, judge_repeats=1, max_doc_chars=60_000))
        measured = (runs / "t1" / "measurement.json").read_text("utf-8")
        assert "Hanoi appears here" not in measured
        assert "adversary_output" not in measured and "rationale" not in measured
        agg = json.dumps(R.aggregate([task], runs))
        assert "Hanoi appears here" not in agg


class TestArmsDoNotShareADirectory:
    """Two arms of one task in one directory is a comparison against itself."""

    def test_each_arm_gets_its_own_run_directory(self, tmp_path):
        a = R.run_dir_for(tmp_path, "t1", "r5")
        b = R.run_dir_for(tmp_path, "t1", "baseline")
        assert a != b and a.parent == b.parent == tmp_path

    def test_the_archived_calibration_run_is_not_a_target(self, tmp_path):
        """eval/runs/smoke-q3 is the frozen report the metric is calibrated
        against. No arm may be written over it."""
        assert R.run_dir_for(tmp_path, "smoke-q3", "r5").name != "smoke-q3"

    def test_the_arm_flag_reaches_the_pipeline_cli(self, workspace, monkeypatch):
        """The flag is useless if the container is invoked without it."""
        tasks_file, runs, _ = workspace
        task = R.load_tasks(tasks_file)[0]
        seen: list[list[str]] = []

        def fake_run(argv, *, env=None):
            seen.append(argv)
            class P:
                returncode = 0
                stdout = "ok"
                stderr = ""
            return P()

        monkeypatch.setattr(R, "_docker", lambda: "/usr/bin/docker")
        monkeypatch.setattr(R, "_run", fake_run)
        monkeypatch.setattr(R, "_compose", lambda *a, **k: fake_run(list(a)))
        R.run_private_arm(task, runs, force=True, arm="baseline")
        execs = [a for a in seen if "privdeep.pipeline" in a]
        assert execs, "the pipeline was never invoked"
        assert "--arm" in execs[0] and "baseline" in execs[0]
        assert any("t1__baseline" in x for x in execs[0])


class TestFaithfulnessIsWiredIn:
    KEY = {
        "referents": {"ZEPHYR": ["Project Zephyr", "Zephyr"]},
        "attributes": {"AUTHORISED": {"lexicon": ["authorised", "budget"]},
                       "SPENT": {"lexicon": ["spent"]}},
        "facts": [{"fact_id": "ZEPHYR.AUTHORISED", "subject": "ZEPHYR",
                   "subjects": ["ZEPHYR"], "attribute": "AUTHORISED", "match": "numeric",
                   "value": 250000.0, "derived": False,
                   "surfaces": ["250,000.00", "250000"]}],
        "string_facts": [], "mask_patterns": [],
    }

    def _cloud(self):
        return CloudClient("https://api.anthropic.invalid", api_key="k",
                           transport=httpx.MockTransport(Cloud()))

    def test_a_missing_key_says_so_instead_of_reporting_nothing(self, workspace):
        """An artifact with no faithfulness numbers and no note reads exactly
        like one where the metric ran and found nothing."""
        tasks_file, runs, _ = workspace
        task = R.load_tasks(tasks_file)[0]
        res = run(R.measure_task(task, runs / "t1", self._cloud(),
                                 judge_repeats=1, max_doc_chars=60_000))
        assert "skipped" in res["faithfulness"]
        assert "make_smoke_corpus" in res["faithfulness"]["skipped"]

    def test_both_arms_are_scored_when_the_key_is_present(self, workspace):
        tasks_file, runs, corpus = workspace
        (corpus / R.FACT_KEY_NAME).write_text(json.dumps(self.KEY), encoding="utf-8")
        (runs / "t1" / "report.md").write_text(
            "# Goal\n\nProject Zephyr was authorised 250,000.00 USD.", encoding="utf-8")
        task = R.load_tasks(tasks_file)[0]
        res = run(R.measure_task(task, runs / "t1", self._cloud(),
                                 judge_repeats=1, max_doc_chars=60_000))
        f = res["faithfulness"]
        assert f["private"]["counts"]["CORRECT"] == 1
        assert f["private"]["coverage"] == 1.0
        assert "oracle" in f, "both arms must be scored or the comparison is one-sided"

    def test_the_measurement_records_which_arm_produced_it(self, workspace):
        tasks_file, runs, _ = workspace
        task = R.load_tasks(tasks_file)[0]
        res = run(R.measure_task(task, runs / "t1", self._cloud(), judge_repeats=1,
                                 max_doc_chars=60_000, arm="baseline"))
        assert res["arm"] == "baseline"
        assert json.loads((runs / "t1" / "measurement.json").read_text("utf-8"))[
            "arm"] == "baseline"

    def test_per_occurrence_detail_stays_beside_the_run(self, workspace):
        """Occurrences quote report sentences, which for the private arm means
        private values. Same rule as the judge rationales."""
        tasks_file, runs, corpus = workspace
        (corpus / R.FACT_KEY_NAME).write_text(json.dumps(self.KEY), encoding="utf-8")
        (runs / "t1" / "report.md").write_text(
            "# Goal\n\nProject Zephyr was authorised 250,000.00 USD.", encoding="utf-8")
        task = R.load_tasks(tasks_file)[0]
        run(R.measure_task(task, runs / "t1", self._cloud(), judge_repeats=1,
                           max_doc_chars=60_000))
        detail = json.loads((runs / "t1" / "faithfulness_occurrences.json").read_text("utf-8"))
        assert detail["private"]["occurrences"], "detail was not written"
        measured = (runs / "t1" / "measurement.json").read_text("utf-8")
        assert "occurrences" not in measured
        assert "Project Zephyr was authorised" not in measured


class TestArmAwareAggregation(TestAggregation):
    def _faith(self, rba, attr, cov, f1):
        return {"private": {"rba": rba, "attribute_accuracy": attr,
                            "referent_accuracy": 0.5, "coverage": cov,
                            "faithfulness_f1": f1},
                "oracle": {}}

    def test_runs_are_discovered_not_composed(self, workspace):
        """Composing runs_dir/task_id would miss every per-arm directory and
        report an empty aggregate as though nothing had been measured."""
        _tasks, runs, corpus = workspace
        self._measured(runs, dirname="t1__r5", arm="r5")
        rep = R.aggregate([R.Task("t1", corpus, "g")], runs)
        assert rep["tasks_measured"] == 1

    def test_arms_are_reported_separately(self, workspace):
        _tasks, runs, corpus = workspace
        self._measured(runs, dirname="t1__r5", arm="r5",
                       faithfulness=self._faith(0.8, 0.9, 1.0, 0.88))
        self._measured(runs, dirname="t1__baseline", arm="baseline",
                       faithfulness=self._faith(0.2, 0.5, 1.0, 0.33))
        rep = R.aggregate([R.Task("t1", corpus, "g")], runs)
        assert set(rep["arms"]) == {"r5", "baseline"}
        assert rep["arms"]["r5"]["faithfulness"]["rba"]["mean"] == 0.8
        cmp_ = rep["baseline_vs_r5"]
        assert cmp_["rba"]["delta"] == pytest.approx(0.6)
        assert cmp_["attribute_accuracy"]["baseline"] == 0.5

    def test_one_arm_alone_produces_no_comparison(self, workspace):
        """A delta needs two arms. Emitting one from a single arm would be a
        number with nothing on the other side of it."""
        _tasks, runs, corpus = workspace
        self._measured(runs, dirname="t1__r5", arm="r5",
                       faithfulness=self._faith(0.8, 0.9, 1.0, 0.88))
        rep = R.aggregate([R.Task("t1", corpus, "g")], runs)
        assert rep["baseline_vs_r5"] is None

    def test_a_run_predating_the_arm_flag_is_not_relabelled_as_r5(self, workspace):
        """eval/runs/smoke-q3 was measured before R5 existed and carries no arm.
        Defaulting it to "r5" would pool a pre-R5 run into the comparison R5 is
        judged by, and the delta would be computed against the wrong thing."""
        _tasks, runs, corpus = workspace
        self._measured(runs, dirname="t1__old", arm=None)     # no "arm" key at all
        rep = R.aggregate([R.Task("t1", corpus, "g")], runs)
        # INS2: listed apart and pooled nowhere, not an arm among the arms.
        assert rep["arms"] == {} and rep["runs_measured"] == 0
        assert rep["legacy"]["runs"] == ["t1__old"]
        assert rep["legacy"]["summary"]["private_mean"]["mean"] == 4.0
        assert rep["utility"]["private_mean"]["n"] == 0
        assert rep["reconstruction"]["entity_recovery"]["total"] == 0


class TestPhaseOneAlsoSpends:
    """The guarded half of the driver was the expensive-looking one.

    Phase one runs inside the partition, which reads as local and therefore
    free. The archived manifest says otherwise: nine egress attempts, all
    allowed, against claude-sonnet-5. The planner and every section draft are
    billable calls the monitor forwards rather than replaces.
    """

    def test_private_refuses_without_yes(self, workspace, capsys):
        tasks, runs, _ = workspace
        rc = R.main(["private", "--tasks", str(tasks), "--runs", str(runs)])
        assert rc == 1
        assert "refusing to spend" in capsys.readouterr().out

    def test_private_prints_an_estimate_before_spending(self, workspace, capsys):
        tasks, runs, _ = workspace
        R.main(["private", "--tasks", str(tasks), "--runs", str(runs)])
        out = capsys.readouterr().out
        assert "estimated cost of the private arm" in out
        assert "only the local extraction is free" in out
        assert "$" in out

    def test_the_estimate_is_not_zero(self, workspace):
        tasks_file, _runs, _ = workspace
        est = R.estimate_private_cost(R.load_tasks(tasks_file))
        assert est["TOTAL"] > 0.05, "a free-looking estimate is what hid this"

    def test_phase_two_does_not_fold_in_phase_one(self, workspace):
        """Each subcommand reports what that subcommand spends. Pooling them
        would misreport whichever one the caller is about to run."""
        tasks_file, _runs, _ = workspace
        tasks = R.load_tasks(tasks_file)
        two = R.estimate_cost(tasks, judge_repeats=1, max_doc_chars=60_000)
        one = R.estimate_private_cost(tasks)
        assert two["TOTAL"] != pytest.approx(two["TOTAL"] + one["TOTAL"])
        assert one["TOTAL"] not in (two["TOTAL"],)

    def test_an_existing_run_is_not_re_billed(self, workspace, capsys):
        tasks, runs, _ = workspace
        (runs / "t1__r5").mkdir(parents=True, exist_ok=True)
        (runs / "t1__r5" / "report.md").write_text("done", encoding="utf-8")
        rc = R.main(["private", "--tasks", str(tasks), "--runs", str(runs)])
        assert rc == 0
        assert "nothing to do" in capsys.readouterr().out


class TestSharedExtraction:
    """The extractor samples at temperature 0.1 with no seed; arms that each
    extract mask different entity sets and the delta is not about the arm."""

    def _capture(self, monkeypatch):
        seen: list[list[str]] = []

        def fake_run(argv, *, env=None):
            seen.append(argv)
            class P:
                returncode, stdout, stderr = 0, "ok", ""
            return P()
        monkeypatch.setattr(R, "_docker", lambda: "/usr/bin/docker")
        monkeypatch.setattr(R, "_run", fake_run)
        monkeypatch.setattr(R, "_compose", lambda *a, **k: fake_run(list(a)))
        return seen

    def test_the_reuse_path_reaches_the_pipeline(self, workspace, monkeypatch):
        tasks_file, runs, _ = workspace
        task = R.load_tasks(tasks_file)[0]
        src = R.run_dir_for(runs, "t1", "r5")
        src.mkdir(parents=True)
        (src / "extractions.json").write_text("{}", encoding="utf-8")
        seen = self._capture(monkeypatch)
        R.run_private_arm(task, runs, force=True, arm="baseline", reuse_from="r5")
        (execs,) = [a for a in seen if "privdeep.pipeline" in a]
        i = execs.index("--reuse-extraction")
        assert execs[i + 1] == "/data/runs/t1__r5/extractions.json"

    def test_reusing_an_extraction_that_does_not_exist_is_refused(self, workspace, monkeypatch):
        tasks_file, runs, _ = workspace
        self._capture(monkeypatch)
        with pytest.raises(SystemExit, match="run phase one for arm 'r5' first"):
            R.run_private_arm(R.load_tasks(tasks_file)[0], runs, force=True,
                              arm="baseline", reuse_from="r5")

    def test_an_arm_cannot_reuse_itself(self, workspace, monkeypatch):
        tasks_file, runs, _ = workspace
        self._capture(monkeypatch)
        with pytest.raises(SystemExit, match="its own extraction"):
            R.run_private_arm(R.load_tasks(tasks_file)[0], runs, force=True,
                              arm="r5", reuse_from="r5")


class TestComparisonStatesWhetherExtractionWasShared(TestArmAwareAggregation):
    def test_shared_extraction_is_recognised(self, workspace):
        _tasks, runs, corpus = workspace
        self._measured(runs, dirname="t1__r5", arm="r5", extraction_source="extracted",
                       faithfulness=self._faith(0.8, 0.9, 1.0, 0.88))
        self._measured(runs, dirname="t1__baseline", arm="baseline",
                       extraction_source="/data/runs/t1__r5/extractions.json",
                       faithfulness=self._faith(0.2, 0.5, 1.0, 0.33))
        cmp_ = R.aggregate([R.Task("t1", corpus, "g")], runs)["baseline_vs_r5"]
        assert cmp_["extraction_shared"] is True and cmp_["extraction_warning"] is None

    def test_separate_extractions_carry_a_warning(self, workspace):
        _tasks, runs, corpus = workspace
        for arm in ("r5", "baseline"):
            self._measured(runs, dirname=f"t1__{arm}", arm=arm, extraction_source="extracted",
                           faithfulness=self._faith(0.5, 0.5, 1.0, 0.5))
        cmp_ = R.aggregate([R.Task("t1", corpus, "g")], runs)["baseline_vs_r5"]
        assert cmp_["extraction_shared"] is False
        assert "not attributable to r5 over baseline" in cmp_["extraction_warning"]


class TestR1Comparisons(TestArmAwareAggregation):
    def test_arms_that_reused_the_same_extraction_are_recognised_as_shared(self, workspace):
        """baseline and r1 both reused r5's extraction; neither extracted itself."""
        _tasks, runs, corpus = workspace
        self._measured(runs, dirname="t1__r5", arm="r5", extraction_source="extracted",
                       faithfulness=self._faith(0.1, 0.4, 0.9, 0.2))
        for arm, faith in (("baseline", self._faith(0.3, 0.6, 0.9, 0.4)),
                           ("r1", self._faith(0.9, 0.95, 0.8, 0.85))):
            self._measured(runs, dirname=f"t1__{arm}", arm=arm,
                           extraction_source="/data/runs/t1__r5/extractions.json",
                           faithfulness=faith)
        rep = R.aggregate([R.Task("t1", corpus, "g")], runs)
        cmps = rep["comparisons"]
        assert set(cmps) == {"baseline_vs_r5", "baseline_vs_r1", "r5_vs_r1"}
        assert all(c["extraction_shared"] for c in cmps.values())
        assert cmps["baseline_vs_r1"]["rba"]["delta"] == pytest.approx(0.6)
        assert rep["baseline_vs_r5"] is cmps["baseline_vs_r5"]

    def test_the_r1_arm_is_accepted_by_the_cli(self):
        assert "r1" in R.ARMS


class TestRepeats:
    def test_repeat_one_keeps_the_original_directory(self, tmp_path):
        assert R.run_dir_for(tmp_path, "t1", "r1").name == "t1__r1"
        assert R.run_dir_for(tmp_path, "t1", "r1", 3).name == "t1__r1__rep3"

    def test_a_repeat_may_reuse_its_own_arms_first_extraction(self, workspace, monkeypatch):
        tasks_file, runs, _ = workspace
        src = R.run_dir_for(runs, "t1", "r5")
        src.mkdir(parents=True)
        (src / "extractions.json").write_text("{}", encoding="utf-8")
        seen = TestSharedExtraction()._capture(monkeypatch)
        R.run_private_arm(R.load_tasks(tasks_file)[0], runs, force=True, arm="r5",
                          reuse_from="r5", rep=2)
        (execs,) = [a for a in seen if "privdeep.pipeline" in a]
        assert "/data/runs/t1__r5/extractions.json" in execs
        assert "/data/runs/t1__r5__rep2" in execs


class TestRepeatAggregation(TestArmAwareAggregation):
    def test_repeats_that_all_masked_one_extraction_count_as_shared(self, workspace):
        _tasks, runs, corpus = workspace
        for arm in ("r5", "r1"):
            for rep in (1, 2, 3):
                src = ("extracted" if (arm, rep) == ("r5", 1)
                       else "/data/runs/t1__r5/extractions.json")
                name = f"t1__{arm}" if rep == 1 else f"t1__{arm}__rep{rep}"
                self._measured(runs, dirname=name, arm=arm, rep=rep, extraction_source=src,
                               faithfulness=self._faith(0.1 * rep, 0.5, 0.9, 0.3))
        rep = R.aggregate([R.Task("t1", corpus, "g")], runs)
        assert len(rep["arms"]["r5"]["runs"]) == 3 and rep["arms"]["r5"]["tasks"] == 1
        # Distinct tasks, not runs: six repeats over one corpus are one task.
        assert rep["tasks_measured"] == 1 and rep["runs_measured"] == 6
        assert rep["arms"]["r1"]["faithfulness"]["rba"]["stdev"] is not None
        assert rep["comparisons"]["r5_vs_r1"]["extraction_shared"] is True


class TestNullFaithfulness:
    """INS1: an empty pool is null, not 0.0, and the aggregate says how many
    runs a mean is over rather than averaging the nulls in as zeros."""

    def _write(self, runs: Path, name: str, arm: str, rep: int, private: dict) -> None:
        TestArmAwareAggregation()._measured(
            runs, dirname=name, arm=arm, rep=rep,
            faithfulness={"private": private, "oracle": {}})

    def test_nulls_are_left_out_and_n_says_so(self, workspace):
        _tasks, runs, corpus = workspace
        self._write(runs, "t1__r1", "r1", 1,
                    {"rba": 0.8, "attribute_accuracy": 0.9, "coverage": 1.0,
                     "denominators": {"full": 10}})
        self._write(runs, "t1__r1__rep2", "r1", 2,
                    {"rba": None, "attribute_accuracy": None, "coverage": 0.5,
                     "denominators": {"full": 0}})
        f = R.aggregate([R.Task("t1", corpus, "g")], runs)["arms"]["r1"]["faithfulness"]
        assert f["rba"]["n"] == 1 and f["rba"]["mean"] == 0.8
        assert f["attribute_accuracy"]["values"] == [0.9]
        assert f["coverage"]["n"] == 2

    def test_a_measurement_without_the_new_fields_still_aggregates(self, workspace):
        _tasks, runs, corpus = workspace
        self._write(runs, "t1__r5", "r5", 1,
                    {"rba": 0.5, "attribute_accuracy": 0.5, "referent_accuracy": 0.5,
                     "coverage": 1.0, "faithfulness_f1": 0.66, "fabrication_rate": 0.1})
        f = R.aggregate([R.Task("t1", corpus, "g")], runs)["arms"]["r5"]["faithfulness"]
        assert f["coverage_correct"]["n"] == 0 and f["coverage_correct"]["mean"] is None
        assert f["numerals_outside_key"]["n"] == 0

    def test_rba_on_a_thin_pool_is_suppressed_and_named(self, workspace):
        _tasks, runs, corpus = workspace
        self._write(runs, "t1__r1", "r1", 1,
                    {"rba": 1.0, "attribute_accuracy": 1.0,
                     "denominators": {"full": R.MIN_RBA_POOL - 1}})
        self._write(runs, "t1__r1__rep2", "r1", 2,
                    {"rba": 0.5, "attribute_accuracy": 0.5,
                     "denominators": {"full": R.MIN_RBA_POOL}})
        arm = R.aggregate([R.Task("t1", corpus, "g")], runs)["arms"]["r1"]
        assert arm["faithfulness"]["rba"]["values"] == [0.5]
        assert arm["faithfulness"]["attribute_accuracy"]["n"] == 2
        assert arm["rba_suppressed"] == ["t1__r1"]

    def test_the_summary_prints_n_and_survives_an_all_null_arm(self, workspace, capsys):
        tasks, runs, _ = workspace
        self._write(runs, "t1__r1", "r1", 1, {"rba": None, "attribute_accuracy": None})
        self._write(runs, "t1__r5", "r5", 1,
                    {"rba": 0.25, "attribute_accuracy": 0.5, "denominators": {"full": 8}})
        out_file = runs.parent / "evaluation.json"
        assert R.main(["aggregate", "--tasks", str(tasks), "--runs", str(runs),
                       "--out", str(out_file)]) == 0
        out = capsys.readouterr().out
        assert "RBA n/a (n=0)" in out
        assert "RBA 0.250 (n=1)" in out

    def test_rescore_writes_the_renamed_field_and_nulls(self, workspace):
        _tasks, runs, corpus = workspace
        (corpus / R.FACT_KEY_NAME).write_text(
            json.dumps(TestFaithfulnessIsWiredIn.KEY), encoding="utf-8")
        run_dir = runs / "t1__r1"
        run_dir.mkdir(parents=True)
        (run_dir / "report.md").write_text("Nothing checkable is said.", encoding="utf-8")
        (run_dir / "oracle_report.md").write_text(
            "Project Zephyr was authorised 250,000.00 USD.", encoding="utf-8")
        (run_dir / "measurement.json").write_text(
            json.dumps({"task_id": "t1", "arm": "r1"}), encoding="utf-8")
        R.rescore([R.Task("t1", corpus, "g")], runs)
        f = json.loads((run_dir / "measurement.json").read_text("utf-8"))["faithfulness"]
        assert f["private"]["rba"] is None
        assert f["private"]["numerals_outside_key"] is None
        assert "fabrication_rate" not in f["private"]
        assert f["oracle"]["coverage_correct"] == 1.0


# ------------------------------------------------------------ INS3: what ran


class P:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class FakeDocker:
    """Plays `docker` and `docker compose` for the driver. No container is touched.

    Copying a run out plays the container too: the manifest it writes is built
    by the real RunManifest under the environment the pipeline's `exec -e` was
    given, so the env-to-manifest path is exercised end to end.
    """

    def __init__(self, *, pipeline_rc: int = 0, placement: tuple[int, int] = (100, 100),
                 containers: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.pipeline_rc = pipeline_rc
        self.size, self.size_vram = placement
        self.containers = containers
        self.exec_env: dict[str, str] = {}

    def install(self, monkeypatch) -> FakeDocker:
        monkeypatch.setattr(R, "_docker", lambda: "/usr/bin/docker")
        monkeypatch.setattr(R, "_run", self.run)
        monkeypatch.setattr(R, "_compose", self.compose)
        return self

    def compose_calls(self) -> list[list[str]]:
        return [c[1:] for c in self.calls if c[0] == "compose"]

    def pipeline_exec(self) -> list[str]:
        (argv,) = [c for c in self.compose_calls() if "privdeep.pipeline" in c]
        return argv

    def compose(self, *args: str, env: dict | None = None) -> P:
        a = list(args)
        self.calls.append(["compose", *a])
        if a[:2] == ["ps", "-q"]:
            return P(0, f"cid-{a[2]}\n" if self.containers else "")
        if a[0] == "exec" and "privdeep.pipeline" in a:
            self.exec_env = dict(a[i + 1].split("=", 1) for i, x in enumerate(a) if x == "-e")
            return P(self.pipeline_rc, "sections ok=2 refused=0")
        if a[0] == "exec" and "-c" in a and a[a.index("-c") + 1] == R._OLLAMA_PROBE:
            return P(0, json.dumps({
                "name": "qwen3:14b", "digest": "d" * 64,
                "details": {"quantization_level": "Q4_K_M", "parameter_size": "14.8B"},
                "modified_at": "2026-09-01T00:00:00Z",
                "loaded": [{"name": "qwen3:14b", "size": self.size,
                            "size_vram": self.size_vram}]}))
        if a[0] == "cp" and a[1].startswith("privdeep-core:"):
            self._container_writes(Path(a[2]))
        return P(0, "")

    def _container_writes(self, dest: Path) -> None:
        dest.mkdir(parents=True)
        with mock.patch.dict(os.environ, self.exec_env):
            m = RunManifest(run_id=dest.name)
        (dest / "manifest.json").write_text(m.to_json(), encoding="utf-8")
        (dest / "egress_trace.jsonl").write_text('{"label": "plan"}\n', encoding="utf-8")
        (dest / "report.md").write_text("# g\n", encoding="utf-8")

    def run(self, argv: list[str], *, env: dict | None = None) -> P:
        self.calls.append(list(argv))
        if argv[1] == "inspect":
            if not self.containers:
                return P(1, "", "no such container")
            return P(0, "2026-09-27T08:00:00.1Z" if "StartedAt" in argv[3]
                     else "sha256:" + "e" * 64)
        if argv[1:3] == ["image", "inspect"]:
            return P(0, json.dumps(["ollama/ollama@sha256:" + "a" * 64]))
        return P(0, "")


def _task(workspace) -> R.Task:
    return R.load_tasks(workspace[0])[0]


class TestProvenanceIsRecorded:
    def test_commit_tree_and_dirty_flag_reach_the_container(self, workspace, monkeypatch):
        d = FakeDocker().install(monkeypatch)
        R.run_private_arm(_task(workspace), workspace[1], force=True, provenance=CLEAN)
        argv = d.pipeline_exec()
        # The -e flags belong to exec, so they must precede the service name.
        assert argv.index("-e") < argv.index("privdeep-core")
        assert f"PRIVDEEP_GIT_COMMIT={CLEAN.git_commit}" in argv
        assert f"PRIVDEEP_TREE_SHA={CLEAN.tree_sha256}" in argv
        assert "PRIVDEEP_TREE_DIRTY=false" in argv

    def test_the_manifest_carries_provenance_digests_and_placement(self, workspace,
                                                                    monkeypatch):
        FakeDocker().install(monkeypatch)
        out = R.run_private_arm(_task(workspace), workspace[1], force=True, provenance=CLEAN)
        m = json.loads((out / "manifest.json").read_text("utf-8"))
        assert (m["git_commit"], m["tree_sha256"], m["tree_dirty"]) == (
            CLEAN.git_commit, CLEAN.tree_sha256, False)
        rt = m["runtime"]
        assert rt["monitor_started_at"] == "2026-09-27T08:00:00.1Z"
        assert rt["ollama_image"]["repo_digests"] == ["ollama/ollama@sha256:" + "a" * 64]
        assert rt["local_model"]["digest"] == "d" * 64
        assert rt["local_model"]["placement"]["processor"] == "100% GPU"
        assert rt["recreated_this_batch"] is False

    def test_a_model_partly_on_cpu_is_recorded_not_refused(self, workspace, monkeypatch):
        FakeDocker(placement=(100, 40)).install(monkeypatch)
        out = R.run_private_arm(_task(workspace), workspace[1], force=True, provenance=CLEAN)
        pl = json.loads((out / "manifest.json").read_text("utf-8"))["runtime"][
            "local_model"]["placement"]
        assert pl["processor"] == "60%/40% CPU/GPU" and pl["gpu_fraction"] == pytest.approx(0.4)

    def test_a_probe_that_fails_says_why_and_the_run_stands(self, workspace, monkeypatch):
        FakeDocker(containers=False).install(monkeypatch)
        out = R.run_private_arm(_task(workspace), workspace[1], force=True, provenance=CLEAN)
        rt = json.loads((out / "manifest.json").read_text("utf-8"))["runtime"]
        assert "no running container" in rt["monitor_started_at"]["unavailable"]
        assert "unavailable" in rt["ollama_image"]

    def test_phase_two_records_the_host_code_that_measured(self, workspace):
        """The oracle, judge and adversary run on the host, from code that can
        differ from the commit that produced the report."""
        task = _task(workspace)
        cloud = CloudClient("https://api.anthropic.invalid", api_key="k",
                            transport=httpx.MockTransport(Cloud()))
        res = run(R.measure_task(task, workspace[1] / "t1", cloud, judge_repeats=1,
                                 max_doc_chars=60_000, provenance=CLEAN))
        assert res["provenance"] == CLEAN.to_json()
        assert "dirty_paths" not in res["provenance"]

    def test_an_unloaded_model_is_not_placed(self):
        """A --reuse-extraction run never calls the model."""
        assert R._placement({"name": "qwen3:14b", "loaded": []}) == {"loaded": False}

    def test_placement_says_when_the_loaded_model_expires(self):
        """keep_alive is 10 minutes, so a model loaded by an earlier run can
        still be placed after a reuse run; expires_at lets a reader tell."""
        pl = R._placement({"name": "qwen3:14b", "loaded": [
            {"name": "qwen3:14b", "size": 10, "size_vram": 10,
             "expires_at": "2026-09-27T08:10:00Z"}]})
        assert pl["expires_at"] == "2026-09-27T08:10:00Z"


class TestADirtyTreeIsRefused:
    DIRTY = R.Provenance("a" * 40, "b" * 64, True, ("backend/src/privdeep/pipeline.py",))

    def test_private_refuses_before_any_container_is_touched(self, workspace, monkeypatch,
                                                             capsys):
        tasks, runs, _ = workspace
        monkeypatch.setattr(R, "host_provenance", lambda root=R._REPO: self.DIRTY)
        d = FakeDocker().install(monkeypatch)
        rc = R.main(["private", "--tasks", str(tasks), "--runs", str(runs), "--yes"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "dirty tree" in out and "backend/src/privdeep/pipeline.py" in out
        assert d.calls == []

    def test_an_unknown_tree_state_is_refused_too(self, workspace, monkeypatch, capsys):
        tasks, runs, _ = workspace
        monkeypatch.setattr(R, "host_provenance",
                            lambda root=R._REPO: R.Provenance("unknown", "b" * 64, None))
        d = FakeDocker().install(monkeypatch)
        assert R.main(["private", "--tasks", str(tasks), "--runs", str(runs), "--yes"]) == 1
        assert "could not say" in capsys.readouterr().out and d.calls == []

    def test_allow_dirty_goes_ahead_and_says_so_in_the_manifest(self, workspace, monkeypatch):
        tasks, runs, _ = workspace
        monkeypatch.setattr(R, "host_provenance", lambda root=R._REPO: self.DIRTY)
        d = FakeDocker().install(monkeypatch)
        rc = R.main(["private", "--tasks", str(tasks), "--runs", str(runs), "--yes",
                     "--allow-dirty"])
        assert rc == 0
        assert "PRIVDEEP_TREE_DIRTY=true" in d.pipeline_exec()
        m = json.loads((runs / "t1__r5" / "manifest.json").read_text("utf-8"))
        assert m["tree_dirty"] is True

    def test_measure_refuses_a_dirty_tree_before_the_key_is_read(self, workspace, monkeypatch,
                                                                 capsys):
        tasks, runs, _ = workspace
        monkeypatch.setattr(R, "host_provenance", lambda root=R._REPO: self.DIRTY)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")     # would raise if it were reached
        assert R.main(["measure", "--tasks", str(tasks), "--runs", str(runs), "--yes"]) == 1
        assert "dirty tree" in capsys.readouterr().out


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
class TestHostProvenanceOnARealRepository:
    def _git(self, root: Path, *args: str) -> None:
        exe = shutil.which("git")
        assert exe
        # Without the strip, a pre-commit hook running this suite from a
        # worktree would hand `git add` the committing worktree's index.
        subprocess.run([exe, "-C", str(root), "-c", "user.email=t@t",  # noqa: S603
                        "-c", "user.name=t", *args], check=True, capture_output=True,
                       env=R._git_env())

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        for rel in ("backend/src/privdeep/a.py", "shared/b.py", "gateway/c.py"):
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text("x = 1\n", encoding="utf-8")
        (tmp_path / ".gitignore").write_text("eval/runs/\n", encoding="utf-8")
        self._git(tmp_path, "init", "-q")
        self._git(tmp_path, "add", "-A")
        self._git(tmp_path, "commit", "-qm", "init")
        return tmp_path

    def test_a_committed_tree_is_clean(self, repo):
        prov = _REAL_HOST_PROVENANCE(repo)
        assert prov.tree_dirty is False and len(prov.git_commit) == 40

    def test_untracked_batch_outputs_do_not_make_it_dirty(self, repo):
        """eval/ fills with outputs during a batch; a flag that trips on them
        would be switched off rather than read."""
        (repo / "eval" / "attempts").mkdir(parents=True)
        (repo / "eval" / "attempts" / "x.json").write_text("{}", encoding="utf-8")
        (repo / "eval" / "runs").mkdir()
        (repo / "eval" / "runs" / "y.json").write_text("{}", encoding="utf-8")
        assert _REAL_HOST_PROVENANCE(repo).tree_dirty is False

    def test_an_edited_tracked_file_is_dirty(self, repo):
        (repo / "shared" / "b.py").write_text("x = 2\n", encoding="utf-8")
        prov = _REAL_HOST_PROVENANCE(repo)
        assert prov.tree_dirty is True and "shared/b.py" in prov.dirty_paths

    def test_an_untracked_module_under_the_mounted_code_is_dirty(self, repo):
        """It is imported by the run and is not in the commit."""
        (repo / "backend" / "src" / "privdeep" / "new.py").write_text("", encoding="utf-8")
        assert _REAL_HOST_PROVENANCE(repo).tree_dirty is True

    def test_not_a_repository_is_unknown(self, tmp_path):
        assert _REAL_HOST_PROVENANCE(tmp_path / "nowhere").tree_dirty is None

    def test_a_hooks_git_environment_does_not_redirect_it(self, repo, tmp_path, monkeypatch):
        """Git exports an absolute GIT_INDEX_FILE to hooks in a worktree; read
        from, it would describe another checkout's index."""
        monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "elsewhere" / "index"))
        monkeypatch.setenv("GIT_DIR", str(tmp_path / "elsewhere"))
        monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "elsewhere"))
        prov = _REAL_HOST_PROVENANCE(repo)
        assert prov.tree_dirty is False and len(prov.git_commit) == 40


class TestTreeDigest:
    def _tree(self, root: Path) -> Path:
        for rel in ("backend/src/privdeep/a.py", "shared/b.py", "gateway/c.py"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("x = 1\n", encoding="utf-8")
        return root

    def test_an_edit_or_a_rename_changes_it(self, tmp_path):
        root = self._tree(tmp_path)
        before = R.tree_sha256(root)
        (root / "gateway" / "c.py").write_text("x = 2\n", encoding="utf-8")
        edited = R.tree_sha256(root)
        (root / "gateway" / "c.py").rename(root / "gateway" / "d.py")
        assert len({before, edited, R.tree_sha256(root)}) == 3

    def test_byte_code_does_not(self, tmp_path):
        root = self._tree(tmp_path)
        before = R.tree_sha256(root)
        cache = root / "backend" / "src" / "privdeep" / "__pycache__"
        cache.mkdir()
        (cache / "a.cpython-312.pyc").write_bytes(b"\x00")
        (root / "shared" / "stray.pyc").write_bytes(b"\x00")
        assert R.tree_sha256(root) == before

    def test_code_outside_the_mount_does_not(self, tmp_path):
        root = self._tree(tmp_path)
        before = R.tree_sha256(root)
        (root / "scripts").mkdir()
        (root / "scripts" / "x.py").write_text("", encoding="utf-8")
        assert R.tree_sha256(root) == before


class TestForceKeepsEveryAttempt:
    """--force used to rmtree the run, egress trace included."""

    def _prior(self, runs: Path, marker: str) -> Path:
        d = runs / "t1__r5"
        d.mkdir(parents=True, exist_ok=True)
        (d / "egress_trace.jsonl").write_text(marker, encoding="utf-8")
        return d

    def test_the_prior_attempt_is_moved_under_eval_attempts(self, workspace, monkeypatch):
        _tasks, runs, _ = workspace
        self._prior(runs, "first\n")
        monkeypatch.setattr(shutil, "rmtree", mock.Mock(side_effect=AssertionError("deleted")))
        FakeDocker().install(monkeypatch)
        R.run_private_arm(_task(workspace), runs, force=True, provenance=CLEAN)
        kept = runs.parent / "attempts" / "t1__r5__attempt1"
        assert (kept / "egress_trace.jsonl").read_text("utf-8") == "first\n"
        assert (runs / "t1__r5" / "manifest.json").exists(), "the new run is in place"

    def test_attempts_count_up_and_none_is_overwritten(self, workspace, monkeypatch):
        _tasks, runs, _ = workspace
        FakeDocker().install(monkeypatch)
        self._prior(runs, "first\n")
        R.run_private_arm(_task(workspace), runs, force=True, provenance=CLEAN)
        R.run_private_arm(_task(workspace), runs, force=True, provenance=CLEAN)
        attempts = sorted(q.name for q in (runs.parent / "attempts").iterdir())
        assert attempts == ["t1__r5__attempt1", "t1__r5__attempt2"]
        assert (runs.parent / "attempts" / "t1__r5__attempt1" / "egress_trace.jsonl"
                ).read_text("utf-8") == "first\n"

    def test_a_stale_run_on_the_volume_is_set_aside_not_reused(self, workspace, monkeypatch):
        """The whole container directory is copied out, so an earlier attempt's
        file left on the volume would come out as this attempt's."""
        d = FakeDocker().install(monkeypatch)
        R.run_private_arm(_task(workspace), workspace[1], force=True, provenance=CLEAN)
        calls = d.compose_calls()
        aside = next(i for i, c in enumerate(calls) if R._SET_ASIDE in c)
        assert calls[aside][-1] == "/data/runs/t1__r5"
        assert aside < calls.index(d.pipeline_exec())

    def test_a_failed_pipeline_is_kept_as_an_attempt(self, workspace, monkeypatch):
        """A run that ends with every section refused exits 1. Its trace is an
        outcome, and used to be lost with the exception."""
        _tasks, runs, _ = workspace
        FakeDocker(pipeline_rc=1).install(monkeypatch)
        with pytest.raises(SystemExit, match="attempt is kept at"):
            R.run_private_arm(_task(workspace), runs, force=True, provenance=CLEAN)
        kept = runs.parent / "attempts" / "t1__r5__attempt1"
        rec = json.loads((kept / "attempt.json").read_text("utf-8"))
        assert rec["exit_code"] == 1 and rec["provenance"]["git_commit"] == CLEAN.git_commit
        assert (kept / "egress_trace.jsonl").exists()
        assert not (runs / "t1__r5").exists(), "a failed run must not look like a result"

    def test_phase_two_copies_rather_than_moves(self, tmp_path):
        runs = tmp_path / "runs"
        run_dir = runs / "t1__r5"
        run_dir.mkdir(parents=True)
        (run_dir / "measurement.json").write_text("{}", encoding="utf-8")
        kept = R.archive_attempt(run_dir, runs, copy=True)
        assert (kept / "measurement.json").exists() and (run_dir / "measurement.json").exists()

    def test_each_attempt_says_which_phase_kept_it(self, tmp_path):
        """Both phases archive into one namespace, and a phase-two copy holds a
        duplicate of a trace still in eval/runs: a refusal count summed over
        eval/attempts has to be able to tell them apart."""
        runs = tmp_path / "runs"
        run_dir = runs / "t1__r5"
        run_dir.mkdir(parents=True)
        (run_dir / "egress_trace.jsonl").write_text("{}\n", encoding="utf-8")
        copied = json.loads((R.archive_attempt(run_dir, runs, copy=True) / "attempt.json"
                             ).read_text("utf-8"))
        moved = json.loads((R.archive_attempt(run_dir, runs) / "attempt.json"
                            ).read_text("utf-8"))
        assert (copied["phase"], copied["egress_trace_is_copy"]) == ("measure", True)
        assert (moved["phase"], moved["egress_trace_is_copy"]) == ("private", False)

    def test_a_failed_rerun_leaves_the_earlier_result_in_place(self, workspace, monkeypatch):
        """Archived only once its replacement is ready: a batch that stops
        before then must not leave `aggregate` with no run for the task."""
        _tasks, runs, _ = workspace
        self._prior(runs, "first\n")
        FakeDocker(pipeline_rc=1).install(monkeypatch)
        with pytest.raises(SystemExit, match="attempt is kept at"):
            R.run_private_arm(_task(workspace), runs, force=True, provenance=CLEAN)
        assert (runs / "t1__r5" / "egress_trace.jsonl").read_text("utf-8") == "first\n"
        rec = json.loads((runs.parent / "attempts" / "t1__r5__attempt1" / "attempt.json"
                          ).read_text("utf-8"))
        assert (rec["phase"], rec["reason"]) == ("private", "pipeline exited non-zero")

    def test_the_set_aside_moves_a_stale_run_and_keeps_earlier_ones(self, tmp_path):
        """The snippet runs in the container; here against a tmp root for /data."""
        data = tmp_path / "data"
        stale = data / "runs" / "t1__r5"
        stale.mkdir(parents=True)
        (stale / "egress_trace.jsonl").write_text("stale\n", encoding="utf-8")
        (data / "attempts" / "t1__r5__attempt1").mkdir(parents=True)
        code = R._SET_ASIDE.replace('"/data/attempts"', repr(str(data / "attempts")))
        assert code != R._SET_ASIDE
        for _ in range(2):      # the second finds nothing to move and does nothing
            subprocess.run([sys.executable, "-c", code, str(stale) + "/"],  # noqa: S603
                           check=True, capture_output=True)
        assert not stale.exists()
        kept = data / "attempts" / "t1__r5__attempt2" / "egress_trace.jsonl"
        assert kept.read_text("utf-8") == "stale\n"
        assert sorted(q.name for q in (data / "attempts").iterdir()) == [
            "t1__r5__attempt1", "t1__r5__attempt2"]


class TestTheCodeIsCheckedAroundEveryRun:
    """Provenance used to be computed once per batch and handed to every task,
    while each task is a fresh process importing whatever the bind mount held
    then. A commit mid-batch would leave later manifests naming code that did
    not run (F14)."""

    MOVED = R.Provenance(CLEAN.git_commit, "9" * 64, False)

    class Tree:
        def __init__(self) -> None:
            self.now = CLEAN
            self.calls = 0

        def __call__(self, root: Path = R._REPO) -> R.Provenance:
            self.calls += 1
            return self.now

    def _two_tasks(self, tmp_path: Path, corpus: Path) -> Path:
        f = tmp_path / "two.json"
        f.write_text(json.dumps([{"id": "t1", "corpus": str(corpus), "goal": "g"},
                                 {"id": "t2", "corpus": str(corpus), "goal": "g"}]), "utf-8")
        return f

    def test_a_change_after_the_batch_started_runs_nothing_stale(self, tmp_path, workspace,
                                                                  monkeypatch):
        _tasks, runs, corpus = workspace
        calls = iter([CLEAN])
        monkeypatch.setattr(R, "host_provenance",
                            lambda root=R._REPO: next(calls, self.MOVED))
        d = FakeDocker().install(monkeypatch)
        with pytest.raises(SystemExit, match="code changed during the batch"):
            R.main(["private", "--tasks", str(self._two_tasks(tmp_path, corpus)),
                    "--runs", str(runs), "--yes"])
        assert not any("privdeep.pipeline" in c for c in d.compose_calls())

    def test_a_commit_between_tasks_stops_the_batch(self, tmp_path, workspace, monkeypatch):
        _tasks, runs, corpus = workspace
        tree = self.Tree()
        monkeypatch.setattr(R, "host_provenance", tree)

        class Docker(FakeDocker):
            def _container_writes(self, dest: Path) -> None:
                super()._container_writes(dest)
                tree.now = TestTheCodeIsCheckedAroundEveryRun.MOVED   # lands after t1

        d = Docker().install(monkeypatch)
        with pytest.raises(SystemExit, match=r"\[t2\] not started: .*tree_sha256"):
            R.main(["private", "--tasks", str(self._two_tasks(tmp_path, corpus)),
                    "--runs", str(runs), "--yes"])
        execs = [c for c in d.compose_calls() if "privdeep.pipeline" in c]
        assert len(execs) == 1, "t2 must not run under t1's provenance"
        m = json.loads((runs / "t1__r5" / "manifest.json").read_text("utf-8"))
        assert m["tree_sha256"] == CLEAN.tree_sha256
        assert not (runs / "t2__r5").exists()

    def test_a_change_during_a_run_keeps_it_only_as_an_attempt(self, workspace, monkeypatch):
        _tasks, runs, _ = workspace
        tree = self.Tree()
        monkeypatch.setattr(R, "host_provenance", tree)

        class Docker(FakeDocker):
            def compose(self, *args: str, env: dict | None = None) -> P:
                r = super().compose(*args, env=env)
                if "privdeep.pipeline" in args:
                    tree.now = TestTheCodeIsCheckedAroundEveryRun.MOVED
                return r

        Docker().install(monkeypatch)
        with pytest.raises(SystemExit, match="kept only as an attempt"):
            R.run_private_arm(_task(workspace), runs, force=True, provenance=CLEAN)
        assert not (runs / "t1__r5").exists(), "it may have imported the new code"
        kept = runs.parent / "attempts" / "t1__r5__attempt1"
        rec = json.loads((kept / "attempt.json").read_text("utf-8"))
        assert rec["reason"] == "code changed during the run"
        assert rec["provenance"]["tree_sha256"] == CLEAN.tree_sha256
        assert rec["provenance_after"]["tree_sha256"] == self.MOVED.tree_sha256
        assert (kept / "egress_trace.jsonl").exists(), "a paid run is kept"

    @pytest.mark.parametrize("now", [
        R.Provenance("b" * 40, CLEAN.tree_sha256, False),
        R.Provenance(CLEAN.git_commit, "9" * 64, False),
        R.Provenance(CLEAN.git_commit, CLEAN.tree_sha256, True),
    ])
    def test_each_recorded_value_is_compared(self, now):
        assert R._changed_since(CLEAN, now) is not None
        assert R._changed_since(CLEAN, CLEAN) is None


class TestCopyBeforeReuse:
    """The reused extraction was read from the named volume, where it lives
    only as long as the volume and cannot be checked from the host (F15)."""

    def test_the_host_copy_is_placed_in_the_container_before_the_run(self, workspace,
                                                                       monkeypatch):
        _tasks, runs, _ = workspace
        src = R.run_dir_for(runs, "t1", "r5")
        src.mkdir(parents=True)
        (src / "extractions.json").write_text("{}", encoding="utf-8")
        d = FakeDocker().install(monkeypatch)
        R.run_private_arm(_task(workspace), runs, force=True, arm="baseline", reuse_from="r5",
                          provenance=CLEAN)
        calls = d.compose_calls()
        mk = calls.index(["exec", "-T", "privdeep-core", "mkdir", "-p", "/data/runs/t1__r5"])
        cp = calls.index(["cp", str(src / "extractions.json"),
                          "privdeep-core:/data/runs/t1__r5/extractions.json"])
        run_ = calls.index(d.pipeline_exec())
        assert mk < cp < run_
        argv = d.pipeline_exec()
        assert argv[argv.index("--reuse-extraction") + 1] == "/data/runs/t1__r5/extractions.json"

    def test_no_copy_without_reuse(self, workspace, monkeypatch):
        d = FakeDocker().install(monkeypatch)
        R.run_private_arm(_task(workspace), workspace[1], force=True, provenance=CLEAN)
        assert not any(c[0] == "cp" and not c[1].startswith("privdeep-core:")
                       for c in d.compose_calls())


class TestRecreate:
    RECREATE = ["up", "-d", "--force-recreate", "reference-monitor", "privdeep-core"]

    def _two_tasks(self, tmp_path: Path, corpus: Path) -> Path:
        f = tmp_path / "two.json"
        f.write_text(json.dumps([{"id": "t1", "corpus": str(corpus), "goal": "g"},
                                 {"id": "t2", "corpus": str(corpus), "goal": "g"}]), "utf-8")
        return f

    def test_the_batch_recreates_the_monitor_and_core_once(self, tmp_path, workspace,
                                                           monkeypatch):
        _tasks, runs, corpus = workspace
        d = FakeDocker().install(monkeypatch)
        rc = R.main(["private", "--tasks", str(self._two_tasks(tmp_path, corpus)),
                     "--runs", str(runs), "--yes", "--recreate"])
        assert rc == 0
        calls = d.compose_calls()
        assert calls.count(self.RECREATE) == 1
        first_run = next(i for i, c in enumerate(calls) if "privdeep.pipeline" in c)
        assert calls.index(self.RECREATE) < first_run
        m = json.loads((runs / "t2__r5" / "manifest.json").read_text("utf-8"))
        assert m["runtime"]["recreated_this_batch"] is True

    def test_no_recreate_unless_asked(self, tmp_path, workspace, monkeypatch):
        _tasks, runs, corpus = workspace
        d = FakeDocker().install(monkeypatch)
        R.main(["private", "--tasks", str(self._two_tasks(tmp_path, corpus)),
                "--runs", str(runs), "--yes"])
        assert not any("--force-recreate" in c for c in d.compose_calls())


class TestTaskPaths:
    def test_a_relative_corpus_resolves_against_the_repository(self, tmp_path, monkeypatch):
        """Resolving against the working directory made one tasks file point
        at different corpora depending on where the driver was started."""
        repo = tmp_path / "repo"
        (repo / "corpus").mkdir(parents=True)
        (repo / "corpus" / "memo.md").write_text(CORPUS_TEXT, encoding="utf-8")
        f = tmp_path / "t.json"
        f.write_text(json.dumps([{"id": "x", "corpus": "corpus", "goal": "g"}]), "utf-8")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        monkeypatch.setattr(R, "_REPO", repo)
        assert R.load_tasks(f)[0].corpus == (repo / "corpus").resolve()


# ---------------------------------------------- INS2: the tracked tasks file

TASKS_FILE = R._REPO / "eval" / "tasks.json"


class TestTrackedTasks:
    """eval/tasks.json is tracked (INS2, RF37): one task per corpus, relative
    paths, and goals that carry no generator surface, because the goal crosses
    the boundary verbatim and the surface scan (X4(a)) excludes it."""

    def test_one_task_per_corpus_with_relative_paths_that_load(self):
        raw = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
        assert [(t["id"], t["corpus"]) for t in raw] == [
            ("smoke-q3", "eval/corpora/smoke-q3"), ("portfolio-b", "eval/corpora/portfolio-b"),
            ("prose-c", "eval/corpora/prose-c"), ("offlex-d", "eval/corpora/offlex-d")]
        tasks = R.load_tasks(TASKS_FILE)
        assert all(t.corpus == (R._REPO / t.corpus.relative_to(R._REPO)) for t in tasks)

    def test_the_pilot_goal_is_unchanged_and_each_goal_is_its_scenarios(self):
        from corpora import SCENARIOS
        goals = {t.id: t.goal for t in R.load_tasks(TASKS_FILE)}
        assert goals["smoke-q3"] == ("Assess the Q3 budget position and the risks to the "
                                     "delivery schedule.")
        assert goals == {m.ID: m.GOAL for m in SCENARIOS.values()}

    @pytest.mark.parametrize("task", R.load_tasks(TASKS_FILE), ids=lambda t: t.id)
    def test_no_goal_contains_a_surface_of_its_corpus(self, task):
        """Matched as the scan matches, whole tokens and case-insensitively, over
        every group including the ordinary-word labels."""
        groups, src = R.surface_groups_for(task)
        assert src and src.endswith("surfaces.json") and groups
        assert R.token_hits(task.goal, [s for ss in groups.values() for s in ss]) == {}

    def test_the_pilot_corpus_path_falls_back_to_the_scenario_module(self, tmp_path):
        """The nine pilot runs' tasks file named the user mount corpus/, which
        has no surfaces.json; the task id finds scenario A's list instead."""
        from corpora import smoke_q3
        mount = tmp_path / "corpus"
        mount.mkdir()
        groups, src = R.surface_groups_for(R.Task("smoke-q3", mount, "g"))
        assert groups == smoke_q3.surface_groups() and "smoke_q3.py" in src
        assert R.surface_groups_for(R.Task("unknown", mount, "g")) == (None, None)


# ------------------------------------------------ INS2: the health gate


def _run_dir(root: Path, name: str, manifest: dict | None, *, report: bool = True) -> Path:
    d = root / name
    d.mkdir(parents=True)
    if manifest is not None:
        (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if report:
        (d / "report.md").write_text("# g\n", encoding="utf-8")
    return d


def _section(sid: str, refused: str | None = None, offered: int = 2) -> dict:
    return {"section_id": sid, "slots_offered": offered, "refused": refused,
            "sentences_pruned": 0, "facts_unavailable": 0}


class TestHealthGate:
    """Pipeline health only (INS2 with Part D's B07/N01): a refusal is an
    outcome of the policy, never a reason to exclude or re-run a run."""

    def test_a_healthy_run_is_valid(self, tmp_path):
        h = R.health_check(_run_dir(tmp_path, "r", _healthy_manifest("r1")))
        assert h["valid"] and h["failures"] == []
        assert h["outcomes"]["planner_counters_from"] == "manifest fields"

    def test_a_monitor_refused_draft_is_an_outcome(self, tmp_path):
        m = _healthy_manifest("r1", notes=["plan: 2 sections, 0 unknown slot refs dropped"],
                              sections=[_section("s1"),
                                        _section("s2", "draft: SHINGLE_HIT: 3 shingles")])
        h = R.health_check(_run_dir(tmp_path, "r", m))
        assert h["valid"]
        assert h["outcomes"]["refused_sections"] == ["draft: SHINGLE_HIT"]

    def test_a_reintegrator_refusal_is_an_outcome(self, tmp_path):
        m = _healthy_manifest("r1", sections=[_section("s1", "reintegrate: UNSAFE_POSITION: 1")])
        h = R.health_check(_run_dir(tmp_path, "r", m))
        assert h["valid"] and h["outcomes"]["refused_sections"] == ["reintegrate: UNSAFE_POSITION"]

    def test_a_refused_planning_call_is_an_outcome(self, tmp_path):
        """pipeline.py returns an empty report after a refused plan: no sections,
        no planner counters. The run completed; the policy said no."""
        m = _healthy_manifest("r1", notes=["planning refused by monitor: EXFIL_PATTERN: key"],
                              sections=[], planner_refs_returned=None,
                              planner_refs_dropped=None, slots_issued=12)
        h = R.health_check(_run_dir(tmp_path, "r", m))
        assert h["valid"], h["failures"]
        assert h["outcomes"]["plan_refused"] == "plan: EXFIL_PATTERN"
        assert h["outcomes"]["slots_offered"] == 12

    def test_leak_gate_drops_are_an_outcome_never_a_failure(self, tmp_path):
        """A document the W2 gate left with no relation still leaves a valid run;
        the drops are reported beside the verdict, and are None in a manifest
        written before the gate dropped instead of aborting."""
        m = _healthy_manifest("r1", extraction={"relations_dropped_leak": 3,
                                                "documents_all_relations_dropped": 1})
        h = R.health_check(_run_dir(tmp_path, "r", m))
        assert h["valid"], h["failures"]
        assert h["outcomes"]["relations_dropped_leak"] == 3
        assert h["outcomes"]["documents_all_relations_dropped"] == 1
        old = R.health_check(_run_dir(tmp_path, "old", _healthy_manifest("r1")))
        assert old["valid"] and old["outcomes"]["relations_dropped_leak"] is None
        assert "leak gate dropped" in R.HEALTH_RULE

    def test_the_outcome_names_the_extraction_and_the_commit(self, tmp_path):
        """PAP5b: the paper build counts drops once per extraction and binds the
        freeze commit, so each run's outcome says which extraction its counters
        are and which commit phase one ran at."""
        m = _healthy_manifest("baseline", extraction_source="/data/runs/t__r5/extractions.json",
                              git_commit="c0ffee" * 6 + "abcd")
        h = R.health_check(_run_dir(tmp_path, "r", m))
        assert h["outcomes"]["extraction_source"] == "/data/runs/t__r5/extractions.json"
        assert h["outcomes"]["git_commit"] == "c0ffee" * 6 + "abcd"

    def test_a_transport_failure_is_a_health_failure(self, tmp_path):
        m = _healthy_manifest("r1", sections=[_section("s1", "draft: CloudError: HTTP 529")])
        h = R.health_check(_run_dir(tmp_path, "r", m))
        assert not h["valid"]
        assert "transport failure (CloudError)" in h["failures"][0]

    def test_a_planned_section_without_a_record_fails(self, tmp_path):
        m = _healthy_manifest("r1", notes=["plan: 3 sections, 0 unknown slot refs dropped"])
        h = R.health_check(_run_dir(tmp_path, "r", m))
        assert h["failures"] == ["2 of 3 planned sections have no record"]

    def test_nothing_offered_fails(self, tmp_path):
        m = _healthy_manifest("r1", sections=[_section("s1", offered=0)])
        assert "no slots offered" in R.health_check(_run_dir(tmp_path, "r", m))["failures"][0]

    @pytest.mark.parametrize("returned,dropped,valid", [(20, 1, True), (10, 1, False),
                                                        (0, 0, True), (5, 0, True)])
    def test_the_planner_may_drop_under_ten_percent(self, tmp_path, returned, dropped, valid):
        m = _healthy_manifest("r1", planner_refs_returned=returned,
                              planner_refs_dropped=dropped)
        assert R.health_check(_run_dir(tmp_path, "r", m))["valid"] is valid

    def test_a_pilot_manifest_is_read_from_its_note(self, tmp_path):
        """The nine pilot runs predate the fields: dropped comes from the note,
        returned is unknown, and only dropped == 0 can pass."""
        m = _healthy_manifest("r1")
        del m["planner_refs_returned"], m["planner_refs_dropped"]
        ok = R.health_check(_run_dir(tmp_path, "ok", m))
        assert ok["valid"] and ok["outcomes"]["planner_counters_from"] == \
            "manifest note (pre-INS3)"
        m["notes"] = ["plan: 1 sections, 2 unknown slot refs dropped, 0 budgets clamped"]
        bad = R.health_check(_run_dir(tmp_path, "bad", m))
        assert not bad["valid"] and "not recorded" in bad["failures"][0]

    def test_an_incomplete_run_fails(self, tmp_path):
        assert R.health_check(_run_dir(tmp_path, "a", None, report=False))["failures"] == [
            "did not complete: no manifest.json", "did not complete: no report.md"]
        h = R.health_check(_run_dir(tmp_path, "b", _healthy_manifest("r1"), report=False))
        assert h["failures"] == ["did not complete: no report.md"]


class TestTheGateInTheAggregate(TestArmAwareAggregation):
    def test_a_failing_run_is_excluded_and_named_and_a_refused_one_is_pooled(self, workspace):
        _tasks, runs, corpus = workspace
        self._measured(runs, dirname="t1__r1", arm="r1",
                       faithfulness=self._faith(0.8, 0.8, 1.0, 0.8))
        self._measured(runs, dirname="t1__r1__rep2", arm="r1", rep=2,
                       faithfulness=self._faith(0.6, 0.6, 1.0, 0.6),
                       manifest=_healthy_manifest(
                           "r1", sections=[_section("s1", "draft: SHINGLE_HIT: 2")]))
        self._measured(runs, dirname="t1__r1__rep3", arm="r1", rep=3,
                       faithfulness=self._faith(0.0, 0.0, 1.0, 0.0),
                       manifest=_healthy_manifest(
                           "r1", sections=[_section("s1", "draft: GatewayError: 502")]))
        rep = R.aggregate([R.Task("t1", corpus, "g")], runs)
        g = rep["health_gate"]
        assert g["summary"] == "2/3 valid"
        assert list(g["excluded"]) == ["t1__r1__rep3"]
        assert g["outcomes"]["t1__r1__rep2"]["refused_sections"] == ["draft: SHINGLE_HIT"]
        assert rep["arms"]["r1"]["faithfulness"]["rba"]["values"] == [0.8, 0.6]
        assert rep["arms"]["r1"]["pipeline"]["refused_sections"]["values"] == [0, 1]

    def test_a_phase_one_run_without_a_measurement_is_listed(self, workspace):
        _tasks, runs, corpus = workspace
        _run_dir(runs, "t1__r5__rep2", _healthy_manifest("r5"))
        rep = R.aggregate([R.Task("t1", corpus, "g")], runs)
        assert rep["health_gate"]["unmeasured_runs"] == ["t1__r5__rep2"]


# ------------------------------------------- INS2: per-corpus x arm blocks


class TestBlocks(TestArmAwareAggregation):
    def _faith_full(self, rba, attr, full=10, attribute=10, cov=0.5, key_sha=None,
                    **extra):
        private = {"rba": rba, "attribute_accuracy": attr, "referent_accuracy": 1.0,
                   "coverage": cov, "coverage_correct": cov / 2, "coverage_stated": cov,
                   "numerals_outside_key": 0.1,
                   "denominators": {"full": full, "attribute": attribute, "referent": full,
                                    "scanned": 10}, **extra}
        oracle = dict(private, rba=0.9, numerals_outside_key=0.5)
        f = {"private": private, "oracle": oracle}
        if key_sha:
            f["key_sha256"] = key_sha
        return f

    def test_per_task_arm_blocks_carry_spread_pooled_k_over_n_and_pipeline_counts(
            self, workspace):
        _tasks, runs, corpus = workspace
        man = _healthy_manifest("r1", facts={"facts_structural": 18},
                                sections=[dict(_section("s1"), sentences_pruned=4,
                                               facts_unavailable=3)])
        self._measured(runs, dirname="t1__r1", arm="r1", manifest=man,
                       faithfulness=self._faith_full(0.8, 0.9))
        self._measured(runs, dirname="t1__r1__rep2", arm="r1", rep=2, manifest=man,
                       faithfulness=self._faith_full(0.5, 0.6, full=20, attribute=5))
        b = R.aggregate([R.Task("t1", corpus, "g")], runs)["by_task"]["t1"]["arms"]["r1"]
        rba = b["faithfulness"]["rba"]
        assert (rba["n"], rba["min"], rba["max"]) == (2, 0.5, 0.8)
        assert rba["pooled"] == {"k": 18, "n": 30, "rate": 0.6}
        assert b["faithfulness"]["attribute_accuracy"]["pooled"]["k"] == 9 + 3
        p = b["pipeline"]
        assert p["sentences_pruned"]["values"] == [4, 4]
        assert p["not_recorded"]["values"] == [3, 3]
        assert p["facts_structural"]["mean"] == 18
        assert p["refused_sections"]["values"] == [0, 0]

    def test_a_manifest_that_predates_the_section_fields_is_left_out_of_their_n(
            self, workspace):
        # The pilot's baseline and r5 smoke-q3 manifests carry neither section
        # field: the run is unrecorded for both, not a measured zero.
        _tasks, runs, corpus = workspace
        old = [{k: v for k, v in _section("s1").items()
                if k not in ("sentences_pruned", "facts_unavailable")}]
        assert R._pipeline_values({"sections": old})["sentences_pruned"] is None
        assert R._pipeline_values({"sections": old})["not_recorded"] is None
        assert R._pipeline_values({"sections": []})["sentences_pruned"] == 0
        # The leak-gate drop counter: None before 2026-09-27, when the gate aborted.
        assert R._pipeline_values({"sections": []})["relations_dropped_leak"] is None
        assert R._pipeline_values({"sections": [], "extraction": {
            "relations_dropped_leak": 2}})["relations_dropped_leak"] == 2
        self._measured(runs, dirname="t1__r5", arm="r5",
                       manifest=_healthy_manifest("r5", sections=old),
                       faithfulness=self._faith_full(0.2, 0.2))
        self._measured(runs, dirname="t1__r5__rep2", arm="r5", rep=2,
                       manifest=_healthy_manifest("r5", sections=[
                           dict(_section("s1"), sentences_pruned=2)]),
                       faithfulness=self._faith_full(0.2, 0.2))
        p = R.aggregate([R.Task("t1", corpus, "g")], runs)["by_task"]["t1"]["arms"]["r5"][
            "pipeline"]
        assert p["sentences_pruned"]["values"] == [2]
        assert p["not_recorded"]["n"] == 1
        assert p["refused_sections"]["n"] == 2

    def test_coverage_is_pooled_only_against_the_key_it_was_scored_with(self, workspace):
        _tasks, runs, corpus = workspace
        (corpus / R.FACT_KEY_NAME).write_text(
            json.dumps(TestFaithfulnessIsWiredIn.KEY), encoding="utf-8")
        sha = hashlib.sha256((corpus / R.FACT_KEY_NAME).read_bytes()).hexdigest()
        self._measured(runs, dirname="t1__r1", arm="r1",
                       faithfulness=self._faith_full(0.8, 0.9, cov=1.0, key_sha=sha))
        f = R.aggregate([R.Task("t1", corpus, "g")], runs)["arms"]["r1"]["faithfulness"]
        assert f["coverage"]["pooled"] == {"k": 1, "n": 1, "rate": 1.0}
        self._measured(runs, dirname="t1__r1__rep2", arm="r1", rep=2,
                       faithfulness=self._faith_full(0.8, 0.9, cov=1.0, key_sha="0" * 64))
        f = R.aggregate([R.Task("t1", corpus, "g")], runs)["arms"]["r1"]["faithfulness"]
        assert f["coverage"]["pooled"] is None and f["coverage"]["n"] == 2

    def test_the_oracle_block_has_the_same_keys_but_no_numerals_outside_key(self, workspace):
        _tasks, runs, corpus = workspace
        for arm in ("baseline", "r1"):
            self._measured(runs, dirname=f"t1__{arm}", arm=arm,
                           faithfulness=self._faith_full(0.5, 0.5))
        rep = R.aggregate([R.Task("t1", corpus, "g")], runs)
        o = rep["by_task"]["t1"]["oracle"]
        assert o["runs"] == 2 and o["faithfulness"]["rba"]["values"] == [0.9, 0.9]
        assert "numerals_outside_key" not in o["faithfulness"]
        assert set(o["faithfulness"]) == set(R._FAITH_KEYS) - {"numerals_outside_key"}
        assert rep["oracle"]["faithfulness"]["rba"]["mean"] == 0.9

    def test_paired_deltas_per_corpus_with_ranges_and_direction(self, tmp_path, workspace):
        _tasks, runs, corpus = workspace
        for tid, base, r1 in (("t1", (0.2, 0.3), (0.7, 0.8)), ("t2", (0.4, 0.6), (0.5, 0.9))):
            for arm, vals in (("baseline", base), ("r1", r1)):
                for rep, v in enumerate(vals, start=1):
                    name = f"{tid}__{arm}" + (f"__rep{rep}" if rep > 1 else "")
                    self._measured(runs, dirname=name, task_id=tid, arm=arm, rep=rep,
                                   faithfulness=self._faith_full(v, v))
        rep = R.aggregate([R.Task("t1", corpus, "g"), R.Task("t2", corpus, "g")], runs)
        d1 = rep["by_task"]["t1"]["paired_deltas"]["baseline->r1"]["rba"]
        assert d1["delta"] == pytest.approx(0.5)
        assert d1["range"] == pytest.approx([0.4, 0.6]) and d1["every_run_higher"]
        d2 = rep["by_task"]["t2"]["paired_deltas"]["baseline->r1"]["rba"]
        assert d2["range"] == pytest.approx([-0.1, 0.5]) and not d2["every_run_higher"]
        s = rep["paired_deltas"]["baseline->r1"]["rba"]
        assert (s["corpora"], s["higher"], s["every_run_higher"]) == (2, 2, 1)
        assert s["statement"] == ("r1 above baseline in 2 of 2 corpora; every r1 run above "
                                  "every baseline run in 1 of 2")
        assert "r5->r1" not in rep["paired_deltas"]
        assert "Deltas at N=1" not in json.dumps(rep)

    def test_judge_by_criterion_and_order_with_groundedness_flagged(self, workspace):
        _tasks, runs, corpus = workspace
        crit = ["coverage", "groundedness"]
        j = {"repeat": 0, "private": {"coverage": 3, "groundedness": 1},
             "oracle": {"coverage": 5, "groundedness": 4}, "private_mean": 2.0,
             "oracle_mean": 4.5, "position_bias": 0.5,
             "private_by_order": [{"coverage": 4, "groundedness": 1},
                                  {"coverage": 2, "groundedness": 1}],
             "oracle_by_order": [{"coverage": 5, "groundedness": 4},
                                 {"coverage": 5, "groundedness": 4}],
             "criteria": crit, "judge_models": ["m"], "input_tokens": 1, "output_tokens": 1}
        self._measured(runs, dirname="t1__r1", arm="r1", judgements=[j])
        u = R.aggregate([R.Task("t1", corpus, "g")], runs)["utility"]
        assert u["by_order"]["private_first"]["private"]["coverage"]["mean"] == 4
        assert u["by_order"]["oracle_first"]["private"]["coverage"]["mean"] == 2
        assert u["mean_excluding_groundedness"]["private"]["mean"] == 3
        assert u["groundedness_uninformative"] is True
        assert u["position_bias"]["mean"] == 0.5
        self._measured(runs, dirname="t1__r1", arm="r1", judgements=[j],
                       manifest=_healthy_manifest("r1", evidence=[{"tag": "W1"}]))
        u = R.aggregate([R.Task("t1", corpus, "g")], runs)["utility"]
        assert u["groundedness_uninformative"] is False

    def test_an_alternate_key_rescores_r1_from_its_report(self, tmp_path, workspace):
        _tasks, runs, corpus = workspace
        self._measured(runs, dirname="t1__r1", arm="r1",
                       faithfulness=self._faith_full(0.1, 0.1))
        (runs / "t1__r1" / "report.md").write_text(
            "Project Zephyr was authorised 250,000.00 USD. Zephyr's budget is 250000. "
            "Project Zephyr: authorised 250000. Zephyr authorised 250,000.00. "
            "Project Zephyr authorised 250000.", encoding="utf-8")
        alt = tmp_path / "alt_key.json"
        alt.write_text(json.dumps(TestFaithfulnessIsWiredIn.KEY), encoding="utf-8")
        rep = R.aggregate([R.Task("t1", corpus, "g")], runs, alt_key=alt)
        ak = rep["alt_key"]
        assert ak["key_sha256"] == hashlib.sha256(alt.read_bytes()).hexdigest()
        run1 = ak["per_run"]["t1__r1"]
        assert run1["rba"] == 1.0 and run1["denominators"]["full"] >= R.MIN_RBA_POOL
        assert ak["by_task"]["t1"]["rba"]["mean"] == 1.0
        assert rep["arms"]["r1"]["faithfulness"]["rba"]["mean"] == 0.1   # untouched
        assert R.aggregate([R.Task("t1", corpus, "g")], runs)["alt_key"] is None

    def test_an_alternate_key_directory_scores_each_task_with_its_own_key(
            self, tmp_path, workspace):
        """EXP2 keeps one pre-fix key per corpus; a directory of <task_id>.json
        files scores each task's r1 reports with its own, and names a task it
        has no key for instead of scoring it with another corpus's."""
        _tasks, runs, corpus = workspace
        for task in ("t1", "t2"):
            self._measured(runs, dirname=f"{task}__r1", arm="r1", task_id=task,
                           faithfulness=self._faith_full(0.1, 0.1))
            (runs / f"{task}__r1" / "report.md").write_text(
                "Project Zephyr was authorised 250,000.00 USD. Zephyr's budget is 250000. "
                "Project Zephyr: authorised 250000. Zephyr authorised 250,000.00. "
                "Project Zephyr authorised 250000.", encoding="utf-8")
        keys = tmp_path / "prefix_keys"
        keys.mkdir()
        (keys / "t1.json").write_text(json.dumps(TestFaithfulnessIsWiredIn.KEY),
                                      encoding="utf-8")
        tasks = [R.Task("t1", corpus, "g"), R.Task("t2", corpus, "g")]
        ak = R.aggregate(tasks, runs, alt_key=keys)["alt_key"]
        assert set(ak["by_task"]) == {"t1"} and ak["tasks_without_key"] == ["t2"]
        assert ak["keys"]["t1"]["key_sha256"] == hashlib.sha256(
            (keys / "t1.json").read_bytes()).hexdigest()
        assert ak["by_task"]["t1"]["rba"]["mean"] == 1.0


# ------------------------------------------- INS2: three crossing measurements


def _exchange(stage: str, sent: str = "", *, system: str = "", reply: str = "",
              structured: dict | None = None, refused: str | None = None) -> dict:
    return {"stage": stage, "system": system,
            "messages": [{"role": "user", "content": sent}], "tools": None,
            "response_text": reply, "structured": structured, "refused": refused}


class TestTokenHits:
    def test_whole_tokens_case_insensitive_longest_first(self):
        text = "Project ZEPHYR and zephyr; 1340 units, not 340; the Highway is high."
        hits = R.token_hits(text, ["Project Zephyr", "Zephyr", "340", "High"])
        assert hits == {"Project Zephyr": 1, "Zephyr": 1, "340": 1, "High": 1}

    def test_a_surface_split_by_punctuation_still_matches_as_a_token_run(self):
        assert R.token_hits("spent 6,237.75 USD", ["6,237.75"]) == {"6,237.75": 1}
        assert R.token_hits("PROJECT_34d42447 took 2027", ["2027", "34"]) == {"2027": 1}


class TestScanTrace:
    GOAL = "Assess the Leeds position."

    def _sides(self, hits):
        return {(h["stage"], h["field"], h["side"], h["needle"]): h["count"] for h in hits}

    def test_every_side_is_told_apart(self):
        trace = [
            _exchange("plan", f"REPORT GOAL:\n{self.GOAL}\n- Leeds site", system="You plan.",
                      structured={"sections": [{"title": "Risks",
                                                "objective": "Review the Leeds overrun risk."}]}),
            _exchange("draft:s1", "OBJECTIVE: Review the Leeds overrun risk.\nLeeds",
                      reply="Leeds was reviewed."),
            _exchange("draft:s2", "Leeds again", refused="SHINGLE_HIT: 1"),
        ]
        s = self._sides(R.scan_trace(trace, ["Leeds"], goal=self.GOAL))
        assert s == {
            ("plan", "messages", "user-goal", "Leeds"): 1,
            ("plan", "messages", "core-sent", "Leeds"): 1,
            ("plan", "structured", "cloud-reply", "Leeds"): 1,
            ("draft:s1", "messages", "cloud-echo", "Leeds"): 1,
            ("draft:s1", "messages", "core-sent", "Leeds"): 1,
            ("draft:s1", "response_text", "cloud-reply", "Leeds"): 1,
            ("draft:s2", "messages", "not-sent", "Leeds"): 1,
        }

    def test_a_one_word_reply_does_not_launder_later_core_text(self):
        """A title of one word is not treated as quotable: otherwise the cloud
        writing 'Leeds' once would mark every later core-sent 'Leeds' as echo."""
        trace = [_exchange("plan", "x", structured={"sections": [{"title": "Leeds"}]}),
                 _exchange("draft:s1", "Leeds")]
        s = self._sides(R.scan_trace(trace, ["Leeds"]))
        assert s[("draft:s1", "messages", "core-sent", "Leeds")] == 1

    def test_an_excluded_span_never_starts_or_ends_inside_a_word(self):
        s = self._sides(R.scan_trace([_exchange("plan", "severity High")], ["High"], goal="g"))
        assert s == {("plan", "messages", "core-sent", "High"): 1}

    def test_only_earlier_replies_count_as_echo(self):
        trace = [_exchange("plan", "Leeds overrun risk", reply="Leeds overrun risk")]
        s = self._sides(R.scan_trace(trace, ["Leeds"]))
        assert ("plan", "messages", "core-sent", "Leeds") in s


class TestCrossingsInTheAggregate(TestArmAwareAggregation):
    SURFACES = {"groups": {"sites": ["Leeds"], "labels": ["High"], "amounts": ["340"]}}

    def _trace_run(self, runs: Path, name: str, arm: str, trace: list[dict],
                   entities: list[dict], adversary: str | None = None, **over) -> None:
        self._measured(runs, dirname=name, arm=arm, **over)
        d = runs / name
        (d / "egress_trace.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in trace), encoding="utf-8")
        (d / "entities.json").write_text(json.dumps(entities), encoding="utf-8")
        if adversary is not None:
            (d / "adversary_output.txt").write_text(adversary, encoding="utf-8")

    def test_the_three_measurements_are_separate_blocks(self, workspace):
        _tasks, runs, corpus = workspace
        (corpus / "surfaces.json").write_text(json.dumps(self.SURFACES), encoding="utf-8")
        goal = "Assess the pilot."
        ents = [{"text": "Leeds", "category": "LOCATION"},
                {"text": "August", "category": "DATE"}]
        self._trace_run(runs, "t1__r1", "r1", [
            _exchange("plan", "- Leeds [LOCATION]\n- 340 units",
                      structured={"sections": [{"objective": "At a High level view."}]}),
            _exchange("draft:s1", "OBJECTIVE: At a High level view.", reply="In August."),
        ], ents, adversary="The site was Leeds, in August.",
            reconstruction={"entities_total": 2, "entities_recovered": 2,
                            "fivegrams_total": 5, "fivegrams_recovered": 0,
                            "by_category": {}, "adversary_model": "m"})
        rep = R.aggregate([R.Task("t1", corpus, goal)], runs)
        a = rep["crossings"]["a_generator_surfaces"]
        assert {(h["surface"], h["side"]) for h in a["hits"]} == {("Leeds", "core-sent"),
                                                                  ("340", "core-sent")}
        assert a["label_hits"] == []
        assert [h["surface"] for h in a["excluded"]["cloud-echo"]] == ["High"]
        assert a["by_arm"]["r1"] == {"runs": 1, "hits": 2, "label_hits": 0}
        b = rep["crossings"]["b_extracted_entities"]
        assert {(h["entity"], h["marked"]) for h in b["hits"]} == {
            ("Leeds", "core-sent"), ("August", "cloud-authored")}
        assert b["by_arm"]["r1"] == {"hits": 2, "core_sent": 1, "cloud_authored": 1}
        c = rep["crossings"]["c_reconstruction"]
        assert c["distinct_entities"] == ["August", "Leeds"]
        assert c["disagreements_with_measurement"] == []
        assert rep["reconstruction"]["entity_recovery"]["total"] == 2

    def test_a_label_word_the_core_sends_is_reported_apart(self, workspace):
        _tasks, runs, corpus = workspace
        (corpus / "surfaces.json").write_text(json.dumps(self.SURFACES), encoding="utf-8")
        self._trace_run(runs, "t1__baseline", "baseline",
                        [_exchange("plan", "severity High")], [])
        a = R.aggregate([R.Task("t1", corpus, "g")], runs)["crossings"]["a_generator_surfaces"]
        assert a["hits"] == [] and [h["surface"] for h in a["label_hits"]] == ["High"]

    def test_a_run_the_gate_excludes_is_still_scanned(self, workspace):
        """It still sent what it sent: out of the faithfulness pool, not out of
        the crossing scans."""
        _tasks, runs, corpus = workspace
        (corpus / "surfaces.json").write_text(json.dumps(self.SURFACES), encoding="utf-8")
        self._trace_run(runs, "t1__r5", "r5", [_exchange("plan", "Leeds")], [],
                        manifest=_healthy_manifest(
                            "r5", sections=[_section("s1", "draft: GatewayError: 503")]))
        rep = R.aggregate([R.Task("t1", corpus, "g")], runs)
        assert rep["health_gate"]["excluded"] and rep["runs_measured"] == 0
        (hit,) = rep["crossings"]["a_generator_surfaces"]["hits"]
        assert hit["surface"] == "Leeds" and hit["pooled"] is False

    def test_a_task_without_surfaces_is_named_not_scanned_as_clean(self, workspace):
        _tasks, runs, corpus = workspace
        self._trace_run(runs, "t1__r5", "r5", [_exchange("plan", "Leeds")], [])
        a = R.aggregate([R.Task("t1", corpus, "g")], runs)["crossings"]["a_generator_surfaces"]
        assert a["runs_scanned"] == [] and a["runs_not_scanned"] == {
            "t1__r5": "no generator-surface list for the task"}

    def test_entity_strings_are_named_only_for_a_generator_built_corpus(self, workspace):
        """(b) and (c) put corpus strings into an aggregate meant to be tracked;
        without a surface list the corpus is not known to be synthetic."""
        _tasks, runs, corpus = workspace
        ents = [{"text": "Leeds", "category": "LOCATION"}]
        self._trace_run(runs, "t1__r5", "r5", [_exchange("plan", "Leeds")], ents,
                        adversary="Leeds",
                        reconstruction={"entities_total": 1, "entities_recovered": 1,
                                        "fivegrams_total": 0, "fivegrams_recovered": 0,
                                        "by_category": {}, "adversary_model": "m"})
        rep = R.aggregate([R.Task("t1", corpus, "g")], runs)
        b, c = rep["crossings"]["b_extracted_entities"], rep["crossings"]["c_reconstruction"]
        (hit,) = b["hits"]
        assert hit["entity"] is None and hit["marked"] == "core-sent"
        assert b["entities_named"] == {"t1": False}
        assert [h["entity"] for h in c["hits"]] == [None]
        assert c["distinct_entities"] == [] and c["unnamed_recoveries"] == 1
        assert "Leeds" not in json.dumps(rep["crossings"])
        assert "Leeds" not in R.summary(rep)
        (corpus / "surfaces.json").write_text(json.dumps(self.SURFACES), encoding="utf-8")
        rep = R.aggregate([R.Task("t1", corpus, "g")], runs)
        assert rep["crossings"]["b_extracted_entities"]["hits"][0]["entity"] == "Leeds"
        assert rep["crossings"]["c_reconstruction"]["distinct_entities"] == ["Leeds"]

    def test_a_cloud_authored_hit_says_a_refused_request_carried_it_too(self, workspace):
        _tasks, runs, corpus = workspace
        (corpus / "surfaces.json").write_text(json.dumps(self.SURFACES), encoding="utf-8")
        self._trace_run(runs, "t1__r5", "r5", [
            _exchange("plan", "x", reply="In August."),
            _exchange("draft:s1", "August", refused="SHINGLE_HIT: 1")],
            [{"text": "August", "category": "DATE"}])
        b = R.aggregate([R.Task("t1", corpus, "g")], runs)["crossings"]["b_extracted_entities"]
        (hit,) = b["hits"]
        assert hit["marked"] == "cloud-authored" and hit["also_not_sent"] is True
        assert b["trace_gap"].startswith("egress_trace.jsonl")

    def test_a_recovery_that_disagrees_with_the_measurement_is_named(self, workspace):
        _tasks, runs, corpus = workspace
        self._trace_run(runs, "t1__r5", "r5", [], [{"text": "Leeds", "category": "LOCATION"}],
                        adversary="Leeds")      # the fixture's measurement says 1 of 10
        c = R.aggregate([R.Task("t1", corpus, "g")], runs)["crossings"]["c_reconstruction"]
        assert c["disagreements_with_measurement"] == ["t1__r5"]


# ------------------------------------------- INS2b: the pre-registered outcomes


SCOPE_FILE = R._REPO / "PRIVDEEP_ICCIT_SCOPE.md"


def _scope_section(start: str, end: str) -> str:
    text = SCOPE_FILE.read_text(encoding="utf-8")
    i = text.index(f"\n{start}\n")
    return text[i:text.index(f"\n{end}\n", i)]


def _items(section: str) -> list[str]:
    """The section's bullets and paragraphs, each with its wrapped lines joined by
    one space and the bullet marker removed."""
    items: list[list[str]] = []
    cur: list[str] | None = None
    for line in section.splitlines():
        if not line.strip():
            cur = None
        elif line.startswith("- "):
            cur = [line[2:].strip()]
            items.append(cur)
        elif cur is None:
            cur = [line.strip()]
            items.append(cur)
        else:
            cur.append(line.strip())
    return [" ".join(i) for i in items]


class TestHypothesisWordingMatchesTheScope:
    """Each constant is the scope's text, whole: a sentence added to or dropped from
    either side fails here, so the block cannot drift from what was registered."""

    SECTIONS = {"8.7": ("### 8.7 Pre-registration", "### 8.7a Amendment after the C and D "
                        "pilot, 2026-09-27, before any frozen-batch run"),
                "8.7a": ("### 8.7a Amendment after the C and D pilot, 2026-09-27, before any "
                         "frozen-batch run", "### 8.8 Freeze rules")}

    def _one(self, items: list[str], prefix: str) -> str:
        found = [i for i in items if i.startswith(prefix)]
        assert len(found) == 1, (prefix, found)
        return found[0]

    @pytest.mark.parametrize("name", ["H1", "H2", "H3", "H4-D'"])
    def test_a_bulleted_hypothesis_is_its_scope_bullet(self, name):
        h = R.HYPOTHESES[name]
        items = _items(_scope_section(*self.SECTIONS[h["section"]]))
        prefix = f"**{h['label']}:** "
        assert self._one(items, prefix) == prefix + h["wording"]
        assert self._one(items, f"If {h['label']} fails") == h["if_fails"]

    def test_h4_d_is_its_scope_paragraph(self):
        h = R.HYPOTHESES["H4-D"]
        items = _items(_scope_section(*self.SECTIONS["8.7"]))
        prefix = "**H4-D** (corpus D is included): "
        assert self._one(items, prefix) == f"{prefix}{h['wording']} {h['if_fails']}"

    def test_the_h2_floor_rule_is_its_scope_bullet(self):
        items = _items(_scope_section(*self.SECTIONS["8.7a"]))
        prefix = "**H2 floor rule.** "
        assert self._one(items, prefix) == prefix + R.HYPOTHESES["H2"]["floor_rule"]

    def test_h1_carries_its_definition_bullet(self):
        items = _items(_scope_section(*self.SECTIONS["8.7"]))
        assert self._one(items, "H1 is tested under") == R.HYPOTHESES["H1"]["definition"]

    def test_every_hypothesis_has_a_rule(self):
        assert set(R.HYPOTHESIS_RULES) == set(R.HYPOTHESES) == {"H1", "H2", "H3", "H4-D",
                                                                 "H4-D'"}


class TestCorpusMapping:
    def test_the_mapping_is_the_registered_one_and_covers_the_tracked_tasks(self):
        assert R.CORPUS_OF_TASK == {"smoke-q3": "A", "portfolio-b": "B", "prose-c": "C",
                                    "offlex-d": "D"}
        assert {t.id for t in R.load_tasks(TASKS_FILE)} == set(R.CORPUS_OF_TASK)

    def test_an_unknown_task_id_is_named_and_never_guessed(self, workspace):
        """'t1' and 'smoke-q3-copy' are not corpus A: no hypothesis reads them."""
        _tasks, runs, corpus = workspace
        TestArmAwareAggregation()._measured(runs, dirname="smoke-q3-copy__r1",
                                            task_id="smoke-q3-copy", arm="r1")
        h = R.aggregate([R.Task("t1", corpus, "g"), R.Task("smoke-q3-copy", corpus, "g")],
                        runs)["hypotheses"]
        assert h["unmapped_tasks"] == ["t1", "smoke-q3-copy"]
        assert h["corpora"] == {"A": None, "B": None, "C": None, "D": None}
        assert h["H1"]["per_corpus"]["A"]["outcome"] == R.NOT_TESTABLE
        assert "no task in the tasks file is corpus A" in (
            h["H1"]["per_corpus"]["A"]["components"]["rba"]["reason"])
        assert h["H3"]["outcome"] == R.NOT_TESTABLE and h["H3"]["runs_scanned"] == 0
        for name in ("H2", "H4-D", "H4-D'"):
            assert h[name]["outcome"] == R.NOT_TESTABLE

    def test_a_registered_id_whose_corpus_is_elsewhere_is_not_mapped(self, workspace):
        """A task 'smoke-q3' whose corpus is not a directory named smoke-q3 is not taken
        to be corpus A on its id alone."""
        _tasks, runs, corpus = workspace
        h = R.aggregate([R.Task("smoke-q3", corpus, "g")], runs)["hypotheses"]
        assert h["corpora"]["A"] is None and h["unmapped_tasks"] == ["smoke-q3"]
        assert h["corpus_path_mismatch"] == {"smoke-q3": str(corpus)}
        assert "corpus directory is not named after it" in "\n".join(
            R._hypothesis_lines(h))


IDS = {"A": "smoke-q3", "B": "portfolio-b", "C": "prose-c", "D": "offlex-d"}
CELLS = {"smoke-q3": 24, "portfolio-b": 24, "prose-c": 0, "offlex-d": 24}
STRUCTURAL = {"A": 18, "B": 20, "C": None, "D": 10}
SURFACE_LIST = {"groups": {"sites": ["Leeds"], "labels": ["High"]}}


def _cols(**cols: list) -> list[dict]:
    n = len(next(iter(cols.values())))
    return [{k: v[i] for k, v in cols.items()} for i in range(n)]


def _all_hold() -> dict[tuple[str, str], list[dict]]:
    """Three runs per (corpus, arm) under which every hypothesis holds.

    Gains per run pair: A [0.3, 0.7], B [0.4, 0.6], D [0.05, 0.25]. The facts_structural
    share: A 18/24, B 20/24, D 10/24. r5 is in no comparison, but H3 covers every arm
    on every corpus, so each corpus has its three r5 runs too."""
    same = [0.9, 0.9, 0.9]
    return {
        **{(x, "r5"): _cols(rba=[.5, .5, .5]) for x in "ABCD"},
        ("A", "baseline"): _cols(rba=[.2, .3, .4], attribute_accuracy=[.2, .3, .4],
                                 coverage_correct=[.5, .5, .5], coverage_stated=same),
        ("A", "r1"): _cols(rba=[.7, .8, .9], attribute_accuracy=[.7, .8, .9],
                           coverage_correct=[.6, .7, .8], coverage_stated=same),
        ("B", "baseline"): _cols(rba=[.25, .3, .35], attribute_accuracy=[.25, .3, .35],
                                 coverage_correct=[.5, .5, .5], coverage_stated=same),
        ("B", "r1"): _cols(rba=[.75, .8, .85], attribute_accuracy=[.75, .8, .85],
                           coverage_correct=[.6, .65, .7], coverage_stated=same),
        ("C", "baseline"): _cols(rba=[.5, .5, .5], coverage_stated=[.8, .9, .85],
                                 coverage_correct=[.6, .7, .65]),
        ("C", "r1"): _cols(rba=[1.0, 1.0, 1.0], full=[2, 2, 2], coverage_stated=[.2, .3, .25],
                           coverage_correct=[.1, .2, .15]),
        ("D", "baseline"): _cols(rba=[.3, .35, .4], coverage_correct=[.5, .5, .5]),
        ("D", "r1"): _cols(rba=[.45, .5, .55], coverage_correct=[.2, .3, .25]),
    }


class TestHypothesesBlock(TestArmAwareAggregation):
    """Synthetic run sets for 'holds', 'fails' and 'not testable' of each hypothesis."""

    @pytest.fixture(autouse=True)
    def _cells(self, monkeypatch):
        monkeypatch.setattr(R, "_table_data_cells", lambda corpus: CELLS.get(corpus.name, 0))

    def _block(self, tmp_path: Path, spec: dict | None = None, *, letters: str = "ABCD",
               traces: dict[str, list[dict]] | None = None) -> dict:
        """Write the run set and aggregate it. `traces` maps a run name to its egress
        trace; every other run gets one benign exchange (no surface, nothing of the
        goal), so crossing (a) scans a trace that holds something: an empty trace
        is 'no exchange traced', which H3 does not count as scanned."""
        spec = _all_hold() if spec is None else spec
        runs = tmp_path / "runs"
        tasks, sha = [], {}
        for letter in letters:
            c = tmp_path / "corpora" / IDS[letter]
            c.mkdir(parents=True)
            (c / "memo.md").write_text(CORPUS_TEXT, encoding="utf-8")
            (c / "surfaces.json").write_text(json.dumps(SURFACE_LIST), encoding="utf-8")
            (c / R.FACT_KEY_NAME).write_text(
                json.dumps({**TestFaithfulnessIsWiredIn.KEY, "corpus": letter}),
                encoding="utf-8")
            sha[letter] = hashlib.sha256((c / R.FACT_KEY_NAME).read_bytes()).hexdigest()
            tasks.append(R.Task(IDS[letter], c, "Assess the pilot."))
        for (letter, arm), rows in spec.items():
            if letter not in letters:
                continue
            for rep, row in enumerate(rows, start=1):
                row = dict(row)
                name = f"{IDS[letter]}__{arm}" + (f"__rep{rep}" if rep > 1 else "")
                facts = ({"facts_structural": STRUCTURAL[letter]}
                         if arm == "r1" and STRUCTURAL[letter] is not None else {})
                private = {"denominators": {"full": row.pop("full", 10)}, **row}
                key = private.pop("key", sha[letter])
                self._measured(runs, dirname=name, task_id=IDS[letter], arm=arm, rep=rep,
                               manifest=private.pop("manifest", _healthy_manifest(arm,
                                                                                  facts=facts)),
                               faithfulness={"key_sha256": key, "private": private,
                                             "oracle": {}})
                (runs / name / "egress_trace.jsonl").write_text(
                    "".join(json.dumps(e) + "\n" for e in (traces or {}).get(
                        name, [_exchange("plan", "Write about [ORG_1] and [SITE_2].")])),
                    encoding="utf-8")
        return R.aggregate(tasks, runs)["hypotheses"]

    # ------------------------------------------------------------------ all hold

    def test_every_hypothesis_holds_on_the_all_hold_set(self, tmp_path):
        h = self._block(tmp_path)
        assert h["corpora"] == {"A": "smoke-q3", "B": "portfolio-b", "C": "prose-c",
                                "D": "offlex-d"}
        assert h["unmapped_tasks"] == [] and h["short_of_registered_repeats"] == {}
        assert h["H1"]["holds_on"] == ["A", "B"]
        for name in ("H2", "H3", "H4-D", "H4-D'"):
            assert h[name]["outcome"] == R.HOLDS, (name, h[name])
        assert h["H3"]["runs_scanned"] == 36 and h["H3"]["hits"] == 0
        assert h["H3"]["runs_not_scanned"] == {} and h["H3"]["cells_uncovered"] == []

    # ------------------------------------------------------------------ H1

    def test_h1_reports_the_min_r1_and_max_baseline_values(self, tmp_path):
        h1 = self._block(tmp_path)["H1"]
        assert h1["wording"] == R.HYPOTHESES["H1"]["wording"] and h1["rule"]
        a = h1["per_corpus"]["A"]
        rba = a["components"]["rba"]
        assert a["task"] == "smoke-q3" and a["outcome"] == R.HOLDS
        assert rba["upper"]["min"] == 0.7 and rba["lower"]["max"] == 0.4
        assert rba["upper"]["values"] == {"smoke-q3__r1": 0.7, "smoke-q3__r1__rep2": 0.8,
                                          "smoke-q3__r1__rep3": 0.9}

    def test_h1_fails_on_one_corpus_and_names_only_the_other(self, tmp_path):
        spec = _all_hold()
        spec[("B", "baseline")][2]["attribute_accuracy"] = 0.75    # ties r1's lowest
        h1 = self._block(tmp_path, spec)["H1"]
        b = h1["per_corpus"]["B"]
        assert b["outcome"] == R.FAILS and b["components"]["rba"]["outcome"] == R.HOLDS
        assert b["components"]["attribute_accuracy"]["lower"]["max"] == 0.75
        assert h1["holds_on"] == ["A"]

    def test_h1_is_not_testable_without_the_corpus_or_with_a_suppressed_rba(self, tmp_path):
        spec = _all_hold()
        spec[("A", "r1")][1]["full"] = R.MIN_RBA_POOL - 1
        h1 = self._block(tmp_path, spec, letters="ACD")["H1"]["per_corpus"]
        assert h1["B"]["outcome"] == R.NOT_TESTABLE and h1["B"]["task"] is None
        assert "no task in the tasks file is corpus B" in h1["B"]["components"]["rba"]["reason"]
        a = h1["A"]
        assert a["outcome"] == R.NOT_TESTABLE
        assert a["components"]["attribute_accuracy"]["outcome"] == R.HOLDS
        assert "smoke-q3__r1__rep2" in a["components"]["rba"]["reason"]
        assert "RBA suppressed" in a["components"]["rba"]["reason"]

    def test_one_violating_pair_fails_h1_whatever_else_is_missing(self, tmp_path):
        spec = _all_hold()
        spec[("A", "r1")][0]["rba"] = None
        spec[("A", "r1")][1]["rba"] = 0.35                         # below baseline's 0.4
        c = self._block(tmp_path, spec)["H1"]["per_corpus"]["A"]["components"]["rba"]
        assert c["outcome"] == R.FAILS and c["upper"]["missing"] == {
            "smoke-q3__r1": "rba is null (empty pool)"}

    def test_a_run_scored_against_a_stale_key_has_no_value(self, tmp_path):
        spec = _all_hold()
        spec[("A", "baseline")][0]["key"] = "4" * 64
        c = self._block(tmp_path, spec)["H1"]["per_corpus"]["A"]["components"]["rba"]
        assert c["outcome"] == R.NOT_TESTABLE and "rescore" in c["reason"]
        assert "smoke-q3__baseline" not in c["lower"]["values"]

    def test_a_run_the_gate_excludes_is_not_in_the_test_and_is_named(self, tmp_path):
        spec = {k: v for k, v in _all_hold().items() if k != ("A", "baseline")}
        spec[("A", "baseline")] = [dict(
            rba=.99, attribute_accuracy=.99,
            manifest=_healthy_manifest("baseline",
                                       sections=[_section("s1", "draft: CloudError: 529")]))]
        h = self._block(tmp_path, spec)
        c = h["H1"]["per_corpus"]["A"]["components"]["rba"]
        assert c["outcome"] == R.NOT_TESTABLE
        assert "excluded by the health gate: ['smoke-q3__baseline']" in c["reason"]
        assert h["short_of_registered_repeats"]["baseline on A"] == 0

    # ------------------------------------------------------------------ H2

    def test_h2_fails_when_r1_states_as_much_as_baseline(self, tmp_path):
        spec = _all_hold()
        spec[("C", "r1")][0]["coverage_correct"] = 0.6              # ties baseline's lowest
        h2 = self._block(tmp_path, spec)["H2"]
        assert h2["outcome"] == R.FAILS
        assert h2["components"]["coverage_stated"]["outcome"] == R.HOLDS
        assert h2["components"]["coverage_correct"]["lower"]["max"] == 0.6

    def test_h2_a_tie_at_zero_is_a_floor_and_h2_is_the_other_half(self, tmp_path):
        """The §8.7a floor rule: r1 and baseline both at 0 on coverage_correct cannot
        show r1 below baseline, so that half is not testable and H2 is decided by
        coverage_stated alone, not failed on the tie."""
        spec = _all_hold()
        spec[("C", "baseline")][0]["coverage_correct"] = 0.0
        for run in spec[("C", "r1")]:
            run["coverage_correct"] = 0.0
        h2 = self._block(tmp_path, spec)["H2"]
        c = h2["components"]["coverage_correct"]
        assert c["floor"] is True and c["floor_rule_applied"] is True
        assert c["outcome"] == R.NOT_TESTABLE and c["reason"].startswith("floor:")
        assert h2["components"]["coverage_stated"]["outcome"] == R.HOLDS
        assert h2["outcome"] == R.HOLDS
        assert "FLOOR: the smallest baseline coverage_correct on C is 0" in R._component_line(
            "coverage_correct", c)

    def test_h2_an_r1_value_above_a_zero_baseline_is_a_real_failure(self, tmp_path):
        """Only a tie at zero is a floor: r1 binding a prose fact correctly while
        baseline's lowest run binds none still fails that half."""
        spec = _all_hold()
        spec[("C", "baseline")][0]["coverage_correct"] = 0.0
        spec[("C", "r1")][0]["coverage_correct"] = 0.1
        h2 = self._block(tmp_path, spec)["H2"]
        c = h2["components"]["coverage_correct"]
        assert c["floor"] is True and not c.get("floor_rule_applied")
        assert c["outcome"] == R.FAILS and h2["outcome"] == R.FAILS

    def test_h2_both_halves_at_the_floor_is_not_testable(self, tmp_path):
        spec = _all_hold()
        for arm in ("baseline", "r1"):
            for run in spec[("C", arm)]:
                run["coverage_correct"] = 0.0
                run["coverage_stated"] = 0.0
        h2 = self._block(tmp_path, spec)["H2"]
        assert h2["outcome"] == R.NOT_TESTABLE

    def test_h2_is_not_testable_for_a_measurement_without_the_field(self, tmp_path):
        spec = _all_hold()
        del spec[("C", "baseline")][1]["coverage_correct"]
        h2 = self._block(tmp_path, spec)["H2"]
        assert h2["outcome"] == R.NOT_TESTABLE
        assert "scored before the field existed" in (
            h2["components"]["coverage_correct"]["reason"])

    def test_rba_on_c_is_listed_with_its_suppressed_runs_and_not_tested(self, tmp_path):
        rba = self._block(tmp_path)["H2"]["rba_on_C_reported_not_tested"]
        assert rba["baseline"]["values"] == {"prose-c__baseline": 0.5,
                                             "prose-c__baseline__rep2": 0.5,
                                             "prose-c__baseline__rep3": 0.5}
        assert rba["r1"]["values"] == {} and len(rba["r1"]["no_value"]) == 3
        assert rba["r5"]["values"] == {"prose-c__r5": 0.5, "prose-c__r5__rep2": 0.5,
                                       "prose-c__r5__rep3": 0.5}

    # ------------------------------------------------------------------ H3

    def test_h3_fails_on_a_core_sent_surface_and_names_it(self, tmp_path):
        h3 = self._block(tmp_path, traces={
            "offlex-d__baseline__rep2": [_exchange("plan", "- Leeds [LOCATION]")]})["H3"]
        assert h3["outcome"] == R.FAILS and h3["hits"] == 1
        assert h3["crossing_strings"] == ["Leeds"] and h3["hits_by_field"] == {"messages": 1}

    def test_h3_counts_a_label_word_the_core_sent(self, tmp_path):
        h3 = self._block(tmp_path, traces={
            "smoke-q3__r1": [_exchange("plan", "", system="severity High")]})["H3"]
        assert h3["outcome"] == R.FAILS and h3["label_group_hits"] == 1

    def test_h3_ignores_the_goal_and_cloud_echoes(self, tmp_path):
        trace = [_exchange("plan", "Assess the pilot.",
                           structured={"sections": [{"objective": "Review the Leeds site."}]}),
                 _exchange("draft:s1", "OBJECTIVE: Review the Leeds site.")]
        assert self._block(tmp_path, traces={"smoke-q3__r1": trace})["H3"]["outcome"] == R.HOLDS

    def test_h3_is_not_testable_while_a_private_trace_is_unscanned(self, tmp_path):
        h = tmp_path / "runs" / "prose-c__r5"
        block = self._block(tmp_path)
        assert block["H3"]["outcome"] == R.HOLDS
        (h / "egress_trace.jsonl").unlink()
        tasks = [R.Task(i, tmp_path / "corpora" / i, "Assess the pilot.") for i in IDS.values()]
        h3 = R.aggregate(tasks, tmp_path / "runs")["hypotheses"]["H3"]
        assert h3["outcome"] == R.NOT_TESTABLE
        assert h3["runs_not_scanned"] == {"prose-c__r5": "no egress_trace.jsonl"}

    def test_h3_is_not_testable_on_an_empty_trace(self, tmp_path):
        """Zero exchanges is zero hits over nothing read, not a clean scan."""
        h3 = self._block(tmp_path, traces={"smoke-q3__r1": []})["H3"]
        assert h3["outcome"] == R.NOT_TESTABLE and h3["hits"] == 0
        assert h3["runs_not_scanned"] == {
            "smoke-q3__r1": "no exchange traced: egress_trace.jsonl is empty"}
        assert h3["runs_scanned"] == 35 and "not scanned: smoke-q3__r1" in h3["reason"]

    def test_h3_is_not_testable_on_a_gate_excluded_transport_failure(self, tmp_path):
        """The reviewer's probe: an r1 run on A whose draft failed with a 529. The gate
        excludes it, H3 still reads it, and its trace cannot hold the failed request."""
        spec = _all_hold()
        spec[("A", "r1")][0]["manifest"] = _healthy_manifest(
            "r1", facts={"facts_structural": STRUCTURAL["A"]},
            sections=[_section("s1", "draft: CloudError: 529")])
        h = self._block(tmp_path, spec)
        h3 = h["H3"]
        assert h3["outcome"] == R.NOT_TESTABLE and h3["hits"] == 0
        why = h3["runs_not_scanned"]["smoke-q3__r1"]
        assert why.startswith("trace incomplete") and "transport failure (CloudError)" in why
        assert list(h3["runs_not_scanned"]) == ["smoke-q3__r1"] and h3["runs_scanned"] == 35
        assert h["H1"]["per_corpus"]["A"]["outcome"] == R.HOLDS    # the pool is not H3's

    def test_h3_still_fails_on_a_hit_in_a_run_with_an_incomplete_trace(self, tmp_path):
        spec = _all_hold()
        spec[("A", "r1")][0]["manifest"] = _healthy_manifest(
            "r1", facts={"facts_structural": STRUCTURAL["A"]},
            sections=[_section("s1", "draft: GatewayError: upstream")])
        h3 = self._block(tmp_path, spec, traces={
            "smoke-q3__r1": [_exchange("plan", "- Leeds [LOCATION]")]})["H3"]
        assert h3["outcome"] == R.FAILS and h3["crossing_strings"] == ["Leeds"]

    def test_h3_is_not_testable_without_corpus_b(self, tmp_path):
        """The pilot's shape: A, C and D, and no B. Zero hits over three corpora is not
        the registered test over four."""
        h3 = self._block(tmp_path, letters="ACD")["H3"]
        assert h3["outcome"] == R.NOT_TESTABLE and h3["runs_scanned"] == 27
        assert h3["runs_not_scanned"] == {}
        assert h3["cells_uncovered"] == ["no task in the tasks file is corpus B"]
        assert h3["reason"] == "no task in the tasks file is corpus B"

    def test_h3_is_not_testable_when_a_corpus_lacks_an_arm(self, tmp_path):
        spec = {k: v for k, v in _all_hold().items() if k != ("B", "r5")}
        h3 = self._block(tmp_path, spec)["H3"]
        assert h3["outcome"] == R.NOT_TESTABLE
        assert h3["cells_uncovered"] == ["no r5 run on B (portfolio-b)"]

    def test_h3_reads_the_runs_of_an_unmapped_task(self, tmp_path):
        """'any private-arm trace' (§8.7): a task outside A-D takes part in no per-corpus
        hypothesis, but what its runs sent is still H3's."""
        self._block(tmp_path)
        extra = tmp_path / "corpora" / "extra"
        extra.mkdir()
        (extra / "memo.md").write_text(CORPUS_TEXT, encoding="utf-8")
        (extra / "surfaces.json").write_text(json.dumps(SURFACE_LIST), encoding="utf-8")
        runs = tmp_path / "runs"
        self._measured(runs, dirname="extra__r1", task_id="extra", arm="r1",
                       manifest=_healthy_manifest("r1"))
        (runs / "extra__r1" / "egress_trace.jsonl").write_text(
            json.dumps(_exchange("plan", "- Leeds [LOCATION]")) + "\n", encoding="utf-8")
        tasks = [R.Task(i, tmp_path / "corpora" / i, "Assess the pilot.") for i in IDS.values()]
        h = R.aggregate(tasks + [R.Task("extra", extra, "Assess the pilot.")],
                        runs)["hypotheses"]
        assert h["unmapped_tasks"] == ["extra"]
        assert h["H3"]["outcome"] == R.FAILS and h["H3"]["crossing_strings"] == ["Leeds"]
        assert h["H1"]["holds_on"] == ["A", "B"]

    def test_h3_is_not_testable_with_a_phase_one_run_never_measured(self, tmp_path):
        self._block(tmp_path)
        late = tmp_path / "runs" / "smoke-q3__r1__rep4"
        late.mkdir()
        (late / "egress_trace.jsonl").write_text(
            json.dumps(_exchange("plan", "Write about [ORG_1].")) + "\n", encoding="utf-8")
        tasks = [R.Task(i, tmp_path / "corpora" / i, "Assess the pilot.") for i in IDS.values()]
        h3 = R.aggregate(tasks, tmp_path / "runs")["hypotheses"]["H3"]
        assert h3["outcome"] == R.NOT_TESTABLE
        assert h3["runs_not_scanned"] == {
            "smoke-q3__r1__rep4": "no measurement.json, so crossing (a) did not read its trace"}

    def test_h3_lists_archived_attempts_and_leaves_them_to_the_author(self, tmp_path):
        self._block(tmp_path)
        (tmp_path / "attempts" / "smoke-q3__r1__attempt1").mkdir(parents=True)
        tasks = [R.Task(i, tmp_path / "corpora" / i, "Assess the pilot.") for i in IDS.values()]
        report = R.aggregate(tasks, tmp_path / "runs")
        h3 = report["hypotheses"]["H3"]
        assert h3["outcome"] == R.HOLDS
        assert h3["attempts_not_scanned"] == ["smoke-q3__r1__attempt1"]
        assert ("      archived attempts, sent and not scanned by any block: "
                "['smoke-q3__r1__attempt1']") in R.summary(report)

    # ------------------------------------------------------------------ H4-D

    def test_h4_d_fails_when_the_gain_on_d_does_not_shrink(self, tmp_path):
        spec = _all_hold()
        spec[("D", "r1")][2]["rba"] = 0.7                          # a D pair gains 0.4
        h = self._block(tmp_path, spec)["H4-D"]
        assert h["outcome"] == R.FAILS
        c = h["components"]
        assert c["structural_share_vs_A"]["outcome"] == R.HOLDS
        assert c["structural_share_vs_A"]["lower"]["max"] == pytest.approx(10 / 24)
        assert c["rba_gain_vs_A"]["outcome"] == R.FAILS
        assert c["rba_gain_vs_A"]["lower"]["max"] == pytest.approx(0.4)
        assert c["rba_gain_vs_A"]["upper"]["min"] == pytest.approx(0.3)

    def test_h4_d_is_not_testable_when_rba_on_d_is_suppressed(self, tmp_path):
        """Synthetic: every r1 run on D has too few scored occurrences for an RBA."""
        spec = _all_hold()
        for row in spec[("D", "r1")]:
            row["full"] = 2
        h = self._block(tmp_path, spec)["H4-D"]
        assert h["outcome"] == R.NOT_TESTABLE
        assert "RBA suppressed" in h["components"]["rba_gain_vs_B"]["reason"]

    def test_an_rba_whose_pool_size_was_never_recorded_has_no_value(self, tmp_path):
        """_thin_rba lets an unrecorded pool through; a hypothesis must not, since the
        minimum n cannot be shown to hold."""
        spec = _all_hold()
        spec[("D", "r1")][0]["full"] = None
        c = self._block(tmp_path, spec)["H4-D"]["components"]["rba_gain_vs_A"]
        assert c["outcome"] == R.NOT_TESTABLE
        assert c["lower"]["missing"] == {
            "offlex-d__r1": "RBA pool size not recorded (denominators.full)"}
        assert all(not k.startswith("offlex-d__r1 ") for k in c["lower"]["values"])

    def test_a_nan_rate_is_no_value_and_does_not_crash_the_tables(self, tmp_path):
        spec = _all_hold()
        spec[("A", "r1")][0]["rba"] = float("nan")
        c = self._block(tmp_path, spec)["H1"]["per_corpus"]["A"]["components"]["rba"]
        assert c["outcome"] == R.NOT_TESTABLE
        assert c["upper"]["missing"] == {"smoke-q3__r1": "rba is NaN"}

    def test_a_stale_key_run_is_flagged_in_the_tables(self, tmp_path):
        spec = _all_hold()
        spec[("A", "baseline")][0]["key"] = "4" * 64
        self._block(tmp_path, spec)
        tasks = [R.Task(i, tmp_path / "corpora" / i, "Assess the pilot.") for i in IDS.values()]
        report = R.aggregate(tasks, tmp_path / "runs")
        assert report["by_task"]["smoke-q3"]["stale_key_runs"] == ["smoke-q3__baseline"]
        assert report["by_task"]["portfolio-b"]["stale_key_runs"] == []
        assert ("  WARNING scored against another key, averaged here but given no value by "
                "the hypotheses: ['smoke-q3__baseline']") in R.summary(report)

    def test_h4_d_fails_on_the_structural_share_alone(self, tmp_path, monkeypatch):
        monkeypatch.setitem(STRUCTURAL, "D", 22)                    # 22/24 above A and B
        h = self._block(tmp_path)["H4-D"]
        assert h["outcome"] == R.FAILS
        assert h["components"]["rba_gain_vs_A"]["outcome"] == R.HOLDS

    def test_h4_d_is_not_testable_without_table_cells(self, tmp_path, monkeypatch):
        monkeypatch.setitem(CELLS, "offlex-d", 0)
        c = self._block(tmp_path)["H4-D"]["components"]["structural_share_vs_A"]
        assert c["outcome"] == R.NOT_TESTABLE
        assert c["reason"] == ("r1 facts_structural / table data cells on D: no table data "
                               "cells counted on D")

    # ------------------------------------------------------------------ H4-D'

    def test_h4_d_prime_fails_when_one_d_run_reaches_one_a_run(self, tmp_path):
        spec = _all_hold()
        spec[("D", "r1")][1]["coverage_correct"] = 0.6
        h = self._block(tmp_path, spec)["H4-D'"]
        assert h["outcome"] == R.FAILS and h["label"] == "H4-D′"
        assert h["components"]["vs_A"]["outcome"] == R.FAILS
        assert h["components"]["vs_B"]["outcome"] == R.FAILS

    def test_h4_d_prime_is_not_testable_without_b(self, tmp_path):
        h = self._block(tmp_path, letters="ACD")["H4-D'"]
        assert h["components"]["vs_A"]["outcome"] == R.HOLDS
        assert h["outcome"] == R.NOT_TESTABLE

    # ------------------------------------------------------------------ printing

    def test_the_summary_prints_the_block(self, tmp_path, monkeypatch):
        spec = _all_hold()
        spec[("A", "r1")] = spec[("A", "r1")][:2]
        self._block(tmp_path, spec, letters="ACD")
        tasks = [R.Task(IDS[x], tmp_path / "corpora" / IDS[x], "Assess the pilot.")
                 for x in "ACD"]
        out = R.summary(R.aggregate(tasks, tmp_path / "runs"))
        assert "hypotheses (PRIVDEEP_ICCIT_SCOPE.md §8.7 and §8.7a" in out
        assert "corpora A=smoke-q3 B=- C=prose-c D=offlex-d" in out
        assert "fewer pooled runs than the 3 registered: {'r1 on A': 2}" in out
        assert "  H1 on A: holds" in out and "  H1 on B: not testable" in out
        assert ("      rba: holds  max baseline rba on A 0.400 (n=3) vs min r1 rba on A "
                "0.700 (n=2)") in out
        assert "  H4-D′: not testable" in out
        assert ("  H3: not testable  0 core-sent hit(s) (0 label-group) over 26 scanned "
                "run(s); no task in the tasks file is corpus B") in out
        assert f"      trace gap: {R._TRACE_GAP}" in out
        assert f"  H1, as registered: {R.HYPOTHESES['H1']['definition']}" in out
        assert ("      rba: holds  max baseline rba on A 0.400 (n=3) vs min r1 rba on A 0.700 "
                "(n=2); under the 3 registered repeats: r1 rba on A: 2 pooled run(s)") in out
        assert "      RBA on C, baseline, reported and not tested: 0.500, 0.500, 0.500" in out
        assert "      RBA on C, r1, reported and not tested: none; no value for 3 run(s)" in out
