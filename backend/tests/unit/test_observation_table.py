"""scripts/observation_table.py over small run directories built here.

The real inputs, the pilot's run directories, are gitignored, so these
fixtures reproduce their shape: the trace field names (`system`, `messages`,
`tools` sent; `response_text`, `structured` received; `refused`), the
planner's placeholder and relation lines, the manifest's egress counters and
per-section records, and the phase-two usage files. What is pinned is the
counting: every kind of refusal as a plain count with its rule name, the run
level k/N, what is and is not counted as a slot or a FACT reference, and the
cost, including when it is only a floor; and that archived attempts count in
the refusals and k/N but never in the per-arm columns that feed Table 3.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import observation_table as ot
from scripts import run_evaluation as R

SYSTEM_DRAFT = ("Refer to any project ONLY by its exact slot id, copied verbatim, "
                "e.g. ⟦SLOT:PROJECT_a1b2c3d4⟧.")
PLAN_PROMPT = (
    "GOAL:\nAssess Q3.\n\n"
    "DOCUMENT SHAPE (abstract concept relations):\n"
    "- (PROJECT) --has_budget--> (FINANCIAL_METRIC)\n"
    "- (PERSON) --raised risk--> (INITIATIVE)\n\n"
    "AVAILABLE PLACEHOLDERS (slot id, category):\n"
    "- ⟦SLOT:PROJECT_11111111⟧  [PROJECT]\n"
    "- ⟦SLOT:PROJECT_22222222⟧  [PROJECT]\n"
    "- ⟦SLOT:PERSON_33333333⟧  [PERSON]\n\n"
    "DOCUMENT STATS: 1 cells, 1 blocks, 10 characters.\n\nProduce the outline now."
)
PRIVATE_NAME = "Nguyễn Văn An"


def _plan(**kw) -> dict:
    e = {"stage": "plan", "system": "S", "messages": [{"role": "user", "content": PLAN_PROMPT}],
         "tools": [{"name": "plan_outline"}], "response_text": "",
         "structured": {"sections": [{"slot_ids": ["SLOT:PROJECT_11111111"]}]},
         "resolved_model": "m", "refused": None, "input_tokens": 1000, "output_tokens": 200}
    e.update(kw)
    return e


def _draft(sid: str, reply: str = "", refused: str | None = None, **kw) -> dict:
    e = {"stage": f"draft:{sid}", "system": SYSTEM_DRAFT,
         "messages": [{"role": "user",
                       "content": "SECTION SLOTS:\n- ⟦SLOT:PROJECT_11111111⟧  [PROJECT]\n"
                                  "facts: ⟦FACT:11111111.<ATTR>⟧"}],
         "tools": None, "response_text": None if refused else reply, "structured": None,
         "resolved_model": None if refused else "m", "refused": refused,
         "input_tokens": 0 if refused else 2000, "output_tokens": 0 if refused else 500}
    e.update(kw)
    return e


def _section(sid: str, refused: str | None = None, pruned: int = 0) -> dict:
    return {"section_id": sid, "refused": refused, "sentences_pruned": pruned,
            "facts_resolved": 1, "facts_unavailable": 0}


def _run(root: Path, name: str, *, arm: str | None, trace: list[dict],
         sections: list[dict] | None = None, egress: dict | None = None,
         measurement: bool = True, adversary: tuple[int, int] | None = None,
         notes: list[str] | None = None, extraction: dict | None = None) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "egress_trace.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in trace) + "\n", encoding="utf-8")
    refused = sum(1 for e in trace if e.get("refused"))
    manifest = {"arm": arm, "sections": sections or [], "notes": notes or [],
                "egress": egress or {"attempts": len(trace), "allowed": len(trace) - refused,
                                     "refused": refused, "bytes_in": 0, "bytes_out": 0}}
    if extraction is not None:
        manifest["extraction"] = extraction
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if measurement:
        usage = {"oracle": {"input_tokens": 500, "output_tokens": 3000,
                            "cache_read_tokens": 9000, "cache_write_tokens": 4000},
                 "judge": {"input_tokens": 40000, "output_tokens": 2000}}
        (d / "measurement.json").write_text(json.dumps({"usage": usage}), encoding="utf-8")
        rec = {"entities_total": 1}
        if adversary is not None:
            rec.update(adversary_tokens_in=adversary[0], adversary_tokens_out=adversary[1])
        (d / "reconstruction.json").write_text(json.dumps(rec), encoding="utf-8")
    return d


@pytest.fixture
def tree(tmp_path) -> dict[str, Path]:
    runs, attempts = tmp_path / "runs", tmp_path / "attempts"
    reply = "The project ⟦SLOT:PROJECT_11111111⟧ spent ⟦FACT:11111111.SPENTAMT⟧ of " \
            "⟦FACT:11111111.AUTHAMT⟧, and ⟦FACT:11111111.SPENTAMT⟧ again."
    _run(runs, "t__r1", arm="r1", adversary=(16_000, 700),
         trace=[_plan(), _draft("s1", reply), _draft("s2", "x")],
         sections=[_section("s1", pruned=2),
                   _section("s2", refused="reintegrate: INVENTED_FACT: 1 fact reference(s)")])
    _run(runs, "t__r1__rep2", arm="r1",
         trace=[_plan(), _draft("s1", reply),
                _draft("s2", refused="RAW_CONTEXT_CONTAINMENT: 3 hit(s)")],
         sections=[_section("s1", pruned=1),
                   _section("s2", refused="draft: RAW_CONTEXT_CONTAINMENT: 3 hit(s)")])
    _run(runs, "t__baseline", arm="baseline", adversary=(15_000, 600),
         trace=[_plan(), _draft("s1", "plain")],
         sections=[_section("s1"), _section("s2", refused="draft: CloudError: 529 overloaded")])
    _run(runs, "t", arm=None, trace=[_plan()])                     # legacy: no arm
    (runs / "t-judgecheck").mkdir()                                 # not a run
    (runs / "t-judgecheck" / "judge_confound.json").write_text("{}")
    _run(attempts, "t__r1__attempt1", arm="r1", measurement=False, trace=[_plan()])
    abort = attempts / "t__r5__attempt1"
    abort.mkdir()
    (abort / "error.txt").write_text(
        "Traceback (most recent call last):\n"
        "    raise OntologyLeak(\n"
        "privdeep.tier1_local.ontology_extractor.OntologyLeak: relation ('PROJECT', "
        f"'led by', 'PERSON') contains entity '{PRIVATE_NAME}' (PERSON)\n", encoding="utf-8")
    return {"runs": runs, "attempts": attempts}


def _rows(tree, **kw) -> list[dict]:
    return [ot.observe_run(d, attempt=a)
            for d, a in ot.discover([tree["runs"]], [tree["attempts"]], **kw)]


class TestDiscovery:
    def test_frozen_runs_and_archived_attempts_legacy_left_out(self, tree):
        names = [d.name for d in ot.discover_runs([tree["runs"], tree["attempts"]])]
        assert names == ["t__baseline", "t__r1", "t__r1__rep2",
                         "t__r1__attempt1", "t__r5__attempt1"]

    def test_legacy_on_request(self, tree):
        names = [d.name for d in ot.discover_runs([tree["runs"]], include_legacy=True)]
        assert "t" in names and "t-judgecheck" not in names

    def test_a_run_directory_given_directly_is_one_run(self, tree):
        assert ot.discover_runs([tree["runs"] / "t__r1"]) == [tree["runs"] / "t__r1"]

    def test_the_attempt_flag_comes_from_the_root_not_the_name(self, tree, tmp_path):
        tagged = {d.name: a for d, a in ot.discover([tree["runs"]], [tree["attempts"]])}
        assert tagged == {"t__baseline": False, "t__r1": False, "t__r1__rep2": False,
                          "t__r1__attempt1": True, "t__r5__attempt1": True}
        # An archived attempt found under a root with no telling name is still one.
        other = tmp_path / "archive"
        _run(other, "t__baseline__x", arm="baseline", trace=[_plan()])
        assert ot.discover([tree["runs"]], [other])[-1] == (other / "t__baseline__x", True)

    def test_a_directory_under_both_kinds_of_root_is_one_attempt(self, tree):
        both = ot.discover([tree["attempts"]], [tree["attempts"]])
        assert [a for _, a in both] == [True, True]

    def test_task_filter(self, tree):
        _run(tree["runs"], "other__r1", arm="r1", trace=[_plan()])
        names = [d.name for d, _ in ot.discover([tree["runs"]], [tree["attempts"]], task="t")]
        assert "other__r1" not in names and "t__r1" in names and "t__r5__attempt1" in names


class TestRefusals:
    def test_each_kind_is_a_plain_count_with_its_rule(self, tree):
        s = ot.aggregate(_rows(tree))
        assert s["runs"] == 5
        assert s["egress_attempts"] == 3 + 3 + 2 + 1 + 0
        assert s["refused_attempts"] == 1
        r = s["refusals"]
        assert r["monitor"] == {"count": 1, "reasons": {"RAW_CONTEXT_CONTAINMENT": 1}}
        assert r["reintegrator"] == {"count": 1, "reasons": {"INVENTED_FACT": 1}}
        assert r["leak_gate_aborts"] == {"count": 1, "reasons": {"OntologyLeak (PERSON)": 1}}
        assert r["transport_failures"]["count"] == 1
        assert r["transport_failures"]["reasons"] == {"CloudError": 1}

    def test_run_level_k_of_n_counts_runs_not_refusals(self, tree):
        s = ot.aggregate(_rows(tree))
        # r1 (reintegrator), r1 rep2 (monitor), the aborted attempt; not the
        # baseline, whose only failure is a transport error.
        assert s["runs_with_any_refusal"] == 3

    def test_a_traceback_counts_one_abort_and_never_the_entity(self, tree):
        rows = _rows(tree)
        abort = next(r for r in rows if r["run"] == "t__r5__attempt1")
        assert abort["leak_gate_aborts"] == ["OntologyLeak (PERSON)"]
        assert abort["egress_attempts"] == 0 and abort["has_manifest"] is False
        assert PRIVATE_NAME not in json.dumps(rows, ensure_ascii=False)

    def test_leak_gate_drops_are_summed_from_the_manifest_and_are_not_refusals(
            self, tmp_path):
        """Since 2026-09-27 the W2 gate drops a leaking relation and the run goes
        on; the count is read from manifest.extraction. A manifest without the
        counter is unrecorded, not zero."""
        rows = [ot.observe_run(_run(tmp_path, "d__r1", arm="r1", trace=[_plan()],
                                    extraction={"relations_dropped_leak": 2,
                                                "documents_all_relations_dropped": 1})),
                ot.observe_run(_run(tmp_path, "d__r5", arm="r5", trace=[_plan()],
                                    extraction={"relations_dropped_leak": 0})),
                ot.observe_run(_run(tmp_path, "d__baseline", arm="baseline", trace=[_plan()]))]
        assert [r["relations_dropped_leak"] for r in rows] == [2, 0, None]
        assert not any(r["refused_any"] for r in rows)
        s = ot.aggregate(rows)
        assert {k: v for k, v in s["leak_gate_drops"].items() if k != "note"} == {
            "relations": 2, "runs_with_drops": 1, "runs_recorded": 2}
        assert s["refusals"]["leak_gate_aborts"]["count"] == 0
        assert "leak-gate drops: 2 relation(s) in 1 run(s), recorded in 2/3" in ot._table(s)

    def test_manifest_and_trace_disagreeing_is_reported(self, tmp_path):
        d = _run(tmp_path, "x", arm="r5", trace=[_plan()],
                 egress={"attempts": 2, "allowed": 2, "refused": 0})
        assert ot.observe_run(d)["discrepancies"] == [
            "manifest egress.attempts=2 but the trace has 1 lines"]

    def test_an_archived_audit_log_is_read_and_its_absence_is_visible(self, tree):
        d = tree["runs"] / "t__r1"
        assert ot.observe_run(d)["audit"] is None
        (d / ot.AUDIT_FILE).write_text("\n".join(json.dumps(r) for r in [
            {"verdict": "allowed"}, {"verdict": "refused", "reason": "SECRET_PATTERN: 1 match"},
        ]) + "\n", encoding="utf-8")
        assert ot.observe_run(d)["audit"] == {
            "records": 2, "verdicts": {"allowed": 1, "refused": 1},
            "refusal_reasons": {"SECRET_PATTERN": 1}}

    def test_a_forwarded_request_is_one_attempt_and_an_orphan_forward_is_visible(self, tree):
        """The monitor writes a pre-forward and an outcome record per forwarded
        request; a pre-forward record with no outcome may have reached C."""
        d = tree["runs"] / "t__r1"
        (d / ot.AUDIT_FILE).write_text("\n".join(json.dumps(r) for r in [
            {"verdict": "forwarding", "request_id": "a"},
            {"verdict": "allowed", "request_id": "a", "upstream_status": 200},
            {"verdict": "refused", "request_id": "b", "reason": "CANARY_TRIPPED: 1"},
            {"verdict": "forwarding", "request_id": "c"},
            {"verdict": "forwarding", "request_id": "d"},
            {"verdict": "upstream_error", "request_id": "d", "reason": "ReadTimeout"},
        ]) + "\n", encoding="utf-8")
        assert ot.observe_run(d)["audit"] == {
            "records": 4,
            "verdicts": {"allowed": 1, "refused": 1, "forwarding": 1, "upstream_error": 1},
            "refusal_reasons": {"CANARY_TRIPPED": 1}}


class TestWhatCrosses:
    def test_slots_relations_and_the_constant_example_id(self, tree):
        row = ot.observe_run(tree["runs"] / "t__r1")
        assert row["slots_advertised"] == {"PERSON": 1, "PROJECT": 2}
        assert row["slots_advertised_total"] == 3
        # Only PROJECT_11111111 is in any message; the drafter's example id sits
        # in its system prompt, a code constant, and is not a slot on the wire.
        assert row["slots_on_wire"] == 3
        assert row["relations"] == 2

    def test_fact_references_are_counted_in_replies_only(self, tree):
        row = ot.observe_run(tree["runs"] / "t__r1")
        # Three in the s1 reply, two distinct; the fact-shaped hint in the
        # request ("<ATTR>") is not one, and is not a reply either.
        assert row["fact_refs_returned"] == 3 and row["fact_refs_returned_distinct"] == 2
        assert row["sentences_pruned"] == 2

    def test_bytes_are_the_compact_sent_and_received_fields(self, tree):
        d = tree["runs"] / "t__baseline"
        trace = [json.loads(ln) for ln in (d / "egress_trace.jsonl").read_text("utf-8").split("\n")
                 if ln]
        row = ot.observe_run(d)

        def size(o):
            return len(json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode())
        assert row["request_bytes"] == sum(
            size({"system": e["system"], "messages": e["messages"], "tools": e["tools"]})
            for e in trace)
        assert row["response_bytes"] == sum(
            size({"response_text": e["response_text"], "structured": e["structured"]})
            for e in trace)


class TestCost:
    def test_full_cost_uses_the_driver_prices(self, tree):
        row = ot.observe_run(tree["runs"] / "t__r1")
        assert row["usage"]["plan"] == {"input_tokens": 1000, "output_tokens": 200}
        assert row["usage"]["draft"] == {"input_tokens": 4000, "output_tokens": 1000}
        assert row["usage"]["adversary"] == {"input_tokens": 16_000, "output_tokens": 700}
        assert row["usd"]["plan"] == pytest.approx(1000 * R.USD_IN + 200 * R.USD_OUT)
        assert row["usd"]["oracle"] == pytest.approx(
            500 * R.USD_IN + 3000 * R.USD_OUT + 9000 * R.USD_CACHE_READ
            + 4000 * R.USD_CACHE_WRITE)
        assert row["usd_total"] == pytest.approx(sum(row["usd"].values()))
        assert row["cost_complete"] is True and row["cost_missing"] == []

    def test_a_pre_ins4_run_is_a_floor_and_says_so(self, tree):
        row = ot.observe_run(tree["runs"] / "t__r1__rep2")
        assert row["usage"]["adversary"] is None
        assert row["cost_complete"] is False and row["cost_missing"] == ["adversary"]

    def test_a_refused_draft_costs_nothing(self, tree):
        row = ot.observe_run(tree["runs"] / "t__r1__rep2")
        assert row["usage"]["draft"] == {"input_tokens": 2000, "output_tokens": 500}


class TestSystemSlots:
    def test_the_constant_is_what_the_drafter_sends(self):
        from privdeep.tier2_cloud import section_drafter as sd
        assert ot.SYSTEM_EXAMPLE_SLOT in sd._SYSTEM
        assert ot.SYSTEM_EXAMPLE_SLOT in sd._SYSTEM_FACTS

    def test_any_other_system_slot_is_counted_and_flagged(self, tmp_path, capsys):
        sneaky = SYSTEM_DRAFT + " Also ⟦SLOT:PERSON_99999999⟧."
        d = _run(tmp_path / "runs", "t__r1", arm="r1",
                 trace=[_plan(), _draft("s1", "x", system=sneaky)])
        row = ot.observe_run(d)
        assert row["system_slots"] == 1
        assert row["slots_on_wire"] == 4
        ot.main([str(tmp_path / "runs")])
        assert "WARNING: system prompts carry up to 1 slot id(s)" in capsys.readouterr().out

    def test_the_constant_alone_is_not_flagged(self, tree):
        assert ot.observe_run(tree["runs"] / "t__r1")["system_slots"] == 0


class TestPerArmAndOutput:
    def test_per_arm_columns_are_over_frozen_runs_only(self, tree):
        s = ot.aggregate(_rows(tree))
        assert s["frozen_runs"] == 3 and s["archived_attempts"] == 2
        r1 = s["by_arm"]["r1"]
        # The archived r1 attempt (plan call only) is not in the arm's means...
        assert r1["runs"] == ["t__r1", "t__r1__rep2"]
        assert r1["egress_attempts"] == 6
        assert r1["slots_advertised_by_category"]["PROJECT"]["per_run"] == [2, 2]
        assert r1["request_bytes"]["per_run"] == [
            ot.observe_run(tree["runs"] / n)["request_bytes"] for n in ("t__r1", "t__r1__rep2")]
        assert r1["tokens"]["adversary"]["input_tokens"]["per_run"] == [16_000, 0]
        assert r1["adversary_tokens_recorded"] == 1 and r1["cost_complete_runs"] == 1
        # ...and an arm seen only in attempts has no per-arm column at all.
        assert set(s["by_arm"]) == {"r1", "baseline"}

    def test_attempts_count_in_k_of_n_and_their_spend_is_apart(self, tree):
        s = ot.aggregate(_rows(tree))
        # Both attempts are in the run and attempt counts and in k/N: the leak-gate
        # abort is one of the three runs with a refusal.
        assert s["runs"] == 5 and s["egress_attempts"] == 9
        assert s["runs_with_any_refusal"] == 3
        assert s["refusals"]["leak_gate_aborts"]["count"] == 1
        at = s["attempts"]
        assert at["runs"] == ["t__r1__attempt1", "t__r5__attempt1"]
        # The aborted attempt wrote no manifest; its directory name gives the arm.
        assert at["by_arm"]["r5"]["runs"] == ["t__r5__attempt1"]
        assert at["by_arm"]["r1"]["usd_total"] == pytest.approx(1000 * R.USD_IN + 200 * R.USD_OUT)
        assert at["usd_total"] == pytest.approx(at["by_arm"]["r1"]["usd_total"])
        assert at["cost_complete_runs"] == 0

    def test_main_prints_and_writes_json_with_nothing_private(self, tree, tmp_path, capsys):
        out = tmp_path / "obs.json"
        rep = ot.main([str(tree["runs"]), "--attempts", str(tree["attempts"]),
                       "--out", str(out)])
        printed = capsys.readouterr().out
        assert "runs 5 (3 frozen, 2 archived attempts)" in printed
        assert "monitor refusals 1/9 attempts" in printed
        assert "runs with any refusal 3/5" in printed
        assert "archived attempts, not in the per-arm columns: 2 run(s)" in printed
        assert rep["attempt_roots"] == [str(tree["attempts"])]
        on_disk = json.loads(out.read_text("utf-8"))
        assert on_disk == json.loads(json.dumps(rep, ensure_ascii=False))
        text = out.read_text("utf-8")
        assert PRIVATE_NAME not in text and "spent ⟦FACT" not in text

    def test_no_runs_is_an_error_not_an_empty_table(self, tmp_path):
        with pytest.raises(SystemExit, match="no run directories"):
            ot.main([str(tmp_path)])

    def test_an_attempts_root_given_as_frozen_is_refused(self, tree):
        with pytest.raises(SystemExit, match="pass them with --attempts"):
            ot.main([str(tree["runs"]), str(tree["attempts"])])
        with pytest.raises(SystemExit, match="pass them with --attempts"):
            ot.main([str(tree["attempts"] / "t__r1__attempt1")])
