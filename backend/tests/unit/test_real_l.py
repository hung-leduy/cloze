"""scripts/real_l.py and scripts/freeze_batch_real.sh, offline (scope §12, track L).

Every run directory here is synthetic, built in tmp_path to mirror what the
pipeline writes (egress_trace.jsonl, entities.json, extractions.json,
manifest.json, report.md), and every identifier string is invented: no TAB
text is read. What is pinned is what decides HL1 and what reaches the
output: which side of a trace counts as crossing, when HL1 holds, fails or
is not testable, that the output carries counts and never a string, that the
adversary spends nothing without --yes and that its control is subtracted, and
that the batch refuses before it reads the .env or touches docker.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from privdeep.tier1_local.extraction_io import text_sha256
from privdeep.tier2_cloud.cloud_client import CloudReply

from scripts import real_l as L
from scripts import run_evaluation as R

REPO = Path(__file__).resolve().parents[3]
BATCH = REPO / "scripts" / "freeze_batch_real.sh"
# Resolved once, as the scripts resolve git and docker: a full path, not a PATH lookup.
GIT, BASH = shutil.which("git"), shutil.which("bash")
GOAL = ("Compare the applicants' situations, their complaints and the domestic proceedings "
        "described in these case files.")

# Invented identifiers, typed as TAB types them.
STRINGS = [
    {"text": "Alder Quint", "identifier_type": "DIRECT", "entity_types": ["PERSON"],
     "label": False},
    {"text": "47123/98", "identifier_type": "DIRECT", "entity_types": ["CODE"], "label": False},
    {"text": "Fenwick Lane", "identifier_type": "QUASI", "entity_types": ["LOC"],
     "label": False},
    {"text": "14 March 1999", "identifier_type": "QUASI", "entity_types": ["DATETIME"],
     "label": False},
    {"text": "Harlow Borough Council", "identifier_type": "QUASI", "entity_types": ["ORG"],
     "label": False},
    {"text": "four thousand pounds", "identifier_type": "QUASI", "entity_types": ["QUANTITY"],
     "label": False},
    {"text": "UK", "identifier_type": "QUASI", "entity_types": ["LOC"], "label": True},
    {"text": "Mr", "identifier_type": "DIRECT", "entity_types": ["PERSON"], "label": True},
]
NON_LABEL = [s["text"] for s in STRINGS if not s["label"]]
DOC = ("Mr Alder Quint (application no. 47123/98) lived at Fenwick Lane in the UK. On "
       "14 March 1999 Harlow Borough Council fined him four thousand pounds.")
PAYLOAD = "DOCUMENT STATS: 1 document\n- [[PERSON_1]] (PERSON) filed [[CODE_1]]"


# ------------------------------------------------------------------ fixtures


def _exchange(stage: str, sent: str = "", *, reply: str = "", structured: dict | None = None,
              refused: str | None = None) -> dict:
    return {"stage": stage, "system": "You are a planner.",
            "messages": [{"role": "user", "content": sent}], "tools": None,
            "response_text": reply, "structured": structured, "refused": refused}


def _clean_trace(goal: str = GOAL) -> list[dict]:
    return [_exchange("plan", f"GOAL: {goal}\n{PAYLOAD}",
                      structured={"sections": [{"title": "Overview", "objective": "o"}]}),
            _exchange("draft:s1", f"OBJECTIVE: o\n{PAYLOAD}", reply="[[PERSON_1]] complained.")]


def _manifest(**over) -> dict:
    m = {"arm": "r5", "evidence": [], "facts": {}, "slots_issued": 2,
         "notes": ["plan: 1 sections, 0 unknown slot refs dropped, 0 budgets clamped"],
         "planner_refs_returned": 2, "planner_refs_dropped": 0,
         "sections": [{"section_id": "s1", "slots_offered": 2, "refused": None,
                       "sentences_pruned": 0, "facts_unavailable": 0}]}
    m.update(over)
    return m


def _collection(root: Path, cid: str, strings: list[dict] = STRINGS) -> Path:
    d = root / "corpora" / cid
    d.mkdir(parents=True)
    (d / "doc1.md").write_text(DOC, encoding="utf-8")
    (d / "identifiers.json").write_text(json.dumps({"collection": cid, "strings": strings}),
                                        encoding="utf-8")
    return d


def _tasks(root: Path, ids: list[str], goal: str = GOAL,
           strings: list[dict] = STRINGS) -> tuple[list[R.Task], Path]:
    for cid in ids:
        if not (root / "corpora" / cid).exists():
            _collection(root, cid, strings)
    p = root / "tasks.json"
    p.write_text(json.dumps([{"id": cid, "corpus": str(root / "corpora" / cid), "goal": goal}
                             for cid in ids]), encoding="utf-8")
    return R.load_tasks(p), p


def _run(runs: Path, cid: str, arm: str, rep: int = 1, *, trace: list[dict] | None = None,
         manifest: dict | None = None, report: str = "# g\n",
         entities: tuple[tuple[str, str], ...] = (),
         relations: tuple[tuple[str, str, str], ...] = (), extractions: bool = True,
         write_trace: bool = True) -> Path:
    d = R.run_dir_for(runs, cid, arm, rep)
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps(manifest or _manifest(arm=arm)),
                                     encoding="utf-8")
    (d / "report.md").write_text(report, encoding="utf-8")
    if write_trace:
        (d / "egress_trace.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in (_clean_trace() if trace is None else trace)),
            encoding="utf-8")
    ents = [{"text": surface, "category": kind} for surface, kind in entities]
    (d / "entities.json").write_text(json.dumps(ents), encoding="utf-8")
    if extractions:
        (d / "extractions.json").write_text(json.dumps({
            "format": "privdeep.extractions/1",
            "documents": [{"doc_id": "doc1", "text_sha256": "0" * 64, "entities": ents,
                           "relations": [list(r) for r in relations]}]}), encoding="utf-8")
    return d


def _full(runs: Path, cid: str, reps: int = 2) -> None:
    """A valid run of every arm and repeat, with nothing crossing."""
    for arm in R.ARMS:
        for rep in range(1, reps + 1):
            _run(runs, cid, arm, rep)


# ------------------------------------------------------------------ crossings


class TestCrossing:
    def test_a_direct_string_the_core_sent_crosses(self, tmp_path):
        tasks, _ = _tasks(tmp_path, ["tab-L1"])
        runs = tmp_path / "runs"
        _run(runs, "tab-L1", "r5", trace=[_exchange("plan", f"{GOAL}\nAlder Quint filed")])
        res = L.scan(tasks, runs, registered=["tab-L1"])
        c = res["collections"]["tab-L1"]["runs"]["tab-L1__r5"]["crossing"]
        assert (c["DIRECT"]["k"], c["DIRECT"]["n"]) == (1, 2)
        assert c["DIRECT"]["by_entity_type"]["PERSON"] == {"k": 1, "n": 1, "rate": 1.0}
        # The rule-of-three bound belongs to HL1's DIRECT blocks only (§12.7).
        assert "rule_of_three" not in c["DIRECT"] and "rule_of_three" not in c["QUASI"]
        assert (c["QUASI"]["k"], c["QUASI"]["n"]) == (0, 4)
        assert c["routes"] == [{"identifier_type": "DIRECT", "entity_type": "PERSON",
                                "stage": "plan", "field": "messages", "strings": 1,
                                "occurrences": 1}]

    @pytest.mark.parametrize("side", ["user-goal", "cloud-reply", "cloud-echo", "not-sent"])
    def test_a_string_on_an_excluded_side_does_not_cross(self, tmp_path, side):
        goal = GOAL
        trace = _clean_trace()
        if side == "user-goal":
            goal = "Compare what happened to Alder Quint and the others."
            trace = [_exchange("plan", f"GOAL: {goal}\n{PAYLOAD}")]
        elif side == "cloud-reply":
            trace[1]["response_text"] = "Alder Quint complained."
        elif side == "cloud-echo":
            trace = [_exchange("plan", PAYLOAD, reply="Alder Quint filed the complaint."),
                     _exchange("draft:s1", "Earlier: Alder Quint filed the complaint.")]
        else:
            trace.append(_exchange("draft:s2", "Alder Quint", refused="SHINGLE_HIT: 1 shingle"))
        tasks, _ = _tasks(tmp_path, ["tab-L1"], goal=goal)
        runs = tmp_path / "runs"
        _run(runs, "tab-L1", "r5", trace=trace)
        c = L.scan(tasks, runs)["collections"]["tab-L1"]["runs"]["tab-L1__r5"]["crossing"]
        assert c["DIRECT"]["k"] == 0
        assert c["excluded_occurrences"][side] >= 1

    def test_strings_inside_or_overlapping_another_are_each_found(self, tmp_path):
        """token_hits consumes a matched run, so one call over every string finds
        only one of two overlapping strings; the scan groups them apart."""
        strings = [{"text": "Alder Quint", "identifier_type": "DIRECT",
                    "entity_types": ["PERSON"], "label": False},
                   {"text": "Quint Street", "identifier_type": "QUASI",
                    "entity_types": ["LOC"], "label": False},
                   {"text": "Quint", "identifier_type": "DIRECT",
                    "entity_types": ["PERSON"], "label": False}]
        trace = [_exchange("plan", "seen at Alder Quint Street")]
        together = {h["needle"] for h in R.scan_trace(trace, [s["text"] for s in strings])
                    if h["side"] == "core-sent"}
        assert len(together) == 1
        tasks, _ = _tasks(tmp_path, ["tab-L1"], strings=strings)
        runs = tmp_path / "runs"
        _run(runs, "tab-L1", "r5", trace=trace)
        res = L.scan(tasks, runs)
        c = res["collections"]["tab-L1"]["runs"]["tab-L1__r5"]["crossing"]
        assert c["all"]["k"] == 3
        # The one-call reading, reported beside it, is the consuming one: the
        # longer 'Quint Street' takes both tokens, and neither DIRECT string is seen.
        assert c["one_call"] == {"all": 1, "DIRECT": 0, "QUASI": 1}
        assert res["HL1"]["direct"]["k"] == 2 and res["HL1"]["direct_one_call"]["k"] == 0

    def test_labels_are_reported_apart_and_decide_nothing(self, tmp_path):
        tasks, _ = _tasks(tmp_path, ["tab-L1"])
        runs = tmp_path / "runs"
        _full(runs, "tab-L1")
        (R.run_dir_for(runs, "tab-L1", "r1") / "egress_trace.jsonl").write_text(
            json.dumps(_exchange("plan", f"{PAYLOAD}\nMr Jones of the UK")) + "\n",
            encoding="utf-8")
        res = L.scan(tasks, runs, registered=["tab-L1"])
        c = res["collections"]["tab-L1"]["runs"]["tab-L1__r1"]["crossing"]
        assert c["labels"]["DIRECT"]["k"] == 1 and c["labels"]["QUASI"]["k"] == 1
        assert c["DIRECT"]["k"] == 0
        assert res["HL1"]["outcome"] == L.HOLDS
        assert res["HL1"]["direct_labels_crossed"]["k"] == 1

    def test_the_output_names_no_string_and_the_run_file_does(self, tmp_path):
        tasks, _ = _tasks(tmp_path, ["tab-L1"])
        runs = tmp_path / "runs"
        d = _run(runs, "tab-L1", "r5", trace=[_exchange("plan", "Alder Quint at Fenwick Lane")],
                 entities=(("Alder Quint", "PERSON"),), report="On 14 March 1999 it ended.",
                 relations=(("PERSON", "fined by Harlow Borough Council", "ORG"),))
        res = L.scan(tasks, runs, registered=["tab-L1"])
        dumped = json.dumps(res, ensure_ascii=False)
        assert not [s for s in NON_LABEL if s in dumped]
        kept = json.loads((d / L.CROSSINGS_NAME).read_text(encoding="utf-8"))
        assert sorted(c["text"] for c in kept["crossed"]) == ["Alder Quint", "Fenwick Lane"]

    def test_a_missing_identifier_list_is_refused(self, tmp_path):
        tasks, _ = _tasks(tmp_path, ["tab-L1"])
        (tasks[0].corpus / L.IDENTIFIERS_NAME).unlink()
        with pytest.raises(SystemExit, match="no identifiers.json"):
            L.scan(tasks, tmp_path / "runs")

    def test_another_collections_identifier_list_is_refused(self, tmp_path):
        tasks, _ = _tasks(tmp_path, ["tab-L1"])
        (tasks[0].corpus / L.IDENTIFIERS_NAME).write_text(
            json.dumps({"collection": "tab-L2", "strings": STRINGS}), encoding="utf-8")
        with pytest.raises(SystemExit, match="tab-L2"):
            L.scan(tasks, tmp_path / "runs")


# ------------------------------------------------------------------------ HL1


class TestHL1:
    IDS = ["tab-L1", "tab-L2"]

    def _scan(self, tmp_path: Path, setup=None) -> dict:
        tasks, _ = _tasks(tmp_path, self.IDS)
        runs = tmp_path / "runs"
        for cid in self.IDS:
            _full(runs, cid)
        if setup:
            setup(runs)
        return L.scan(tasks, runs, registered=self.IDS)["HL1"]

    def test_holds_with_the_rule_of_three_bound(self, tmp_path):
        h = self._scan(tmp_path)
        assert h["outcome"] == L.HOLDS and h["reason"] is None
        assert (h["direct"]["k"], h["direct"]["n"], h["direct"]["rule_of_three"]) == (0, 4, 0.75)
        assert (h["direct_run_pairs"]["k"], h["direct_run_pairs"]["n"]) == (0, 24)
        assert h["direct_run_pairs"]["rule_of_three"] == 3 / 24
        assert h["runs_scanned"] == h["runs"] == 12

    def test_fails_on_one_direct_crossing_in_any_run(self, tmp_path):
        def cross(runs: Path) -> None:
            for rep in (1, 2):
                (R.run_dir_for(runs, "tab-L2", "baseline", rep) / "egress_trace.jsonl").write_text(
                    json.dumps(_exchange("draft:s3", "re 47123/98")) + "\n", encoding="utf-8")
        h = self._scan(tmp_path, cross)
        assert h["outcome"] == L.FAILS
        assert (h["direct"]["k"], h["direct"]["rule_of_three"]) == (1, None)
        assert h["direct_run_pairs"]["k"] == 2
        assert h["direct"]["by_entity_type"]["CODE"]["k"] == 1
        assert h["routes"] == [{"identifier_type": "DIRECT", "entity_type": "CODE",
                                "stage": "draft", "field": "messages", "strings": 2,
                                "occurrences": 2}]

    def test_a_crossing_fails_even_where_another_cell_is_missing(self, tmp_path):
        def cross_and_drop(runs: Path) -> None:
            (R.run_dir_for(runs, "tab-L1", "r5") / "egress_trace.jsonl").write_text(
                json.dumps(_exchange("plan", "Alder Quint")) + "\n", encoding="utf-8")
            for rep in (1, 2):
                for f in R.run_dir_for(runs, "tab-L2", "r1", rep).iterdir():
                    f.unlink()
                R.run_dir_for(runs, "tab-L2", "r1", rep).rmdir()
        assert self._scan(tmp_path, cross_and_drop)["outcome"] == L.FAILS

    def test_a_transport_failure_makes_it_not_testable(self, tmp_path):
        def fail(runs: Path) -> None:
            m = _manifest(arm="r1", sections=[
                {"section_id": "s1", "slots_offered": 2, "sentences_pruned": 0,
                 "facts_unavailable": 0, "refused": "draft: CloudError: HTTP 529: overloaded"}])
            (R.run_dir_for(runs, "tab-L1", "r1", 2) / "manifest.json").write_text(
                json.dumps(m), encoding="utf-8")
        h = self._scan(tmp_path, fail)
        assert h["outcome"] == L.NOT_TESTABLE
        assert list(h["runs_incomplete"]) == ["tab-L1__r1__rep2"]
        assert "tab-L1__r1__rep2" in h["reason"]

    def test_an_empty_or_missing_trace_makes_it_not_testable(self, tmp_path):
        def gut(runs: Path) -> None:
            (R.run_dir_for(runs, "tab-L1", "r5") / "egress_trace.jsonl").write_text(
                "", encoding="utf-8")
            (R.run_dir_for(runs, "tab-L2", "r5", 2) / "egress_trace.jsonl").unlink()
        h = self._scan(tmp_path, gut)
        assert h["outcome"] == L.NOT_TESTABLE
        assert set(h["runs_incomplete"]) == {"tab-L1__r5", "tab-L2__r5__rep2"}

    def test_a_collection_without_a_valid_run_of_an_arm_is_not_testable(self, tmp_path):
        def invalidate(runs: Path) -> None:
            for rep in (1, 2):
                m = _manifest(arm="baseline", planner_refs_returned=10, planner_refs_dropped=5)
                (R.run_dir_for(runs, "tab-L2", "baseline", rep) / "manifest.json").write_text(
                    json.dumps(m), encoding="utf-8")
        h = self._scan(tmp_path, invalidate)
        assert h["outcome"] == L.NOT_TESTABLE
        assert h["cells_uncovered"] == ["tab-L2: no baseline run that passes the health gate"]
        assert h["runs_incomplete"] == {}

    def test_one_valid_repeat_of_an_arm_covers_it(self, tmp_path):
        def invalidate_one(runs: Path) -> None:
            m = _manifest(arm="baseline", planner_refs_returned=10, planner_refs_dropped=5)
            (R.run_dir_for(runs, "tab-L2", "baseline", 2) / "manifest.json").write_text(
                json.dumps(m), encoding="utf-8")
        assert self._scan(tmp_path, invalidate_one)["outcome"] == L.HOLDS

    def test_tasks_other_than_the_registered_collections_are_not_testable(self, tmp_path):
        tasks, _ = _tasks(tmp_path, ["tab-L0"])
        runs = tmp_path / "runs"
        _full(runs, "tab-L0", reps=1)
        h = L.scan(tasks, runs)["HL1"]
        assert h["outcome"] == L.NOT_TESTABLE and "tab-L1" in h["reason"]
        assert h["outcome_over_these_tasks"] == L.HOLDS

    @staticmethod
    def _attempt(runs: Path, name: str, record: dict, trace: list[dict] | None) -> Path:
        a = runs.parent / "attempts" / name
        a.mkdir(parents=True)
        (a / "attempt.json").write_text(json.dumps(record), encoding="utf-8")
        if trace is not None:
            (a / "egress_trace.jsonl").write_text(
                "".join(json.dumps(e) + "\n" for e in trace), encoding="utf-8")
        return a

    def test_archived_phase_one_attempts_are_scanned_and_copies_skipped(self, tmp_path):
        def attempt(runs: Path) -> None:
            self._attempt(runs, "tab-L1__r5__attempt1", {"phase": "private"}, None)
            self._attempt(runs, "tab-L1__r1__rep2__attempt1",
                          {"phase": "private", "egress_trace_is_copy": False}, _clean_trace())
            # An adversary re-attack's copy, and a control's: neither is a phase-one run.
            self._attempt(runs, "tab-L1__r5__attempt2", {"egress_trace_is_copy": True},
                          [_exchange("plan", "Alder Quint")])
            self._attempt(runs, "tab-L1__control__attempt1", {"egress_trace_is_copy": True},
                          [_exchange("plan", "Alder Quint")])
        h = self._scan(tmp_path, attempt)
        assert h["outcome"] == L.HOLDS
        assert h["attempts_not_scanned"] == ["tab-L1__r5__attempt1"]
        assert h["attempts"]["scanned"] == ["tab-L1__r1__rep2__attempt1"]
        assert (h["attempts"]["direct"]["k"], h["attempts"]["direct"]["n"]) == (0, 2)

    def test_a_direct_crossing_in_an_archived_attempt_fails(self, tmp_path):
        """A transport failure the batch re-ran with --force is moved to the
        attempts directory; what it sent reached C, so it decides HL1 too."""
        made: list[Path] = []

        def attempt(runs: Path) -> None:
            made.append(self._attempt(
                runs, "tab-L2__baseline__rep2__attempt1",
                {"phase": "private", "reason": "replaced under --force",
                 "egress_trace_is_copy": False}, [_exchange("draft:s1", "re 47123/98")]))
        h = self._scan(tmp_path, attempt)
        assert h["outcome"] == L.FAILS
        assert (h["direct"]["k"], h["direct_run_pairs"]["k"]) == (1, 0)
        assert h["attempts"]["direct"]["k"] == 1
        assert h["attempts"]["routes"] == [{"identifier_type": "DIRECT", "entity_type": "CODE",
                                            "stage": "draft", "field": "messages",
                                            "strings": 1, "occurrences": 1}]
        kept = json.loads((made[0] / L.CROSSINGS_NAME).read_text(encoding="utf-8"))
        assert [c["text"] for c in kept["crossed"]] == ["47123/98"]

    def test_the_digest_check_gates_hl1(self, tmp_path):
        """§12.8: an L run whose SLM or cloud model differs from the A-D batch's,
        or is unrecorded, leaves HL1 not testable; a crossing still fails."""
        ref = tmp_path / "ad_runs"
        (ref / "smoke-q3__r5").mkdir(parents=True)
        (ref / "smoke-q3__r5" / "manifest.json").write_text(json.dumps(TestIntegrity._rt()),
                                                             encoding="utf-8")
        tasks, _ = _tasks(tmp_path, self.IDS)
        runs = tmp_path / "runs"
        for cid in self.IDS:
            for arm in R.ARMS:
                for rep in (1, 2):
                    _run(runs, cid, arm, rep, manifest=_manifest(arm=arm, **TestIntegrity._rt()))
        assert L.scan(tasks, runs, registered=self.IDS,
                      reference_runs=ref)["HL1"]["outcome"] == L.HOLDS
        (R.run_dir_for(runs, "tab-L2", "r1", 2) / "manifest.json").write_text(
            json.dumps(_manifest(arm="r1", **TestIntegrity._rt("sha256:other"))),
            encoding="utf-8")
        h = L.scan(tasks, runs, registered=self.IDS, reference_runs=ref)["HL1"]
        assert h["outcome"] == L.NOT_TESTABLE and "slm_model_digest differs" in h["reason"]
        assert h["integrity"] == {"checked": True, "all_equal": False}
        assert L.scan(tasks, runs, registered=self.IDS)["HL1"]["integrity"] is None
        (R.run_dir_for(runs, "tab-L1", "r5") / "egress_trace.jsonl").write_text(
            json.dumps(_exchange("plan", "Alder Quint")) + "\n", encoding="utf-8")
        assert L.scan(tasks, runs, registered=self.IDS,
                      reference_runs=ref)["HL1"]["outcome"] == L.FAILS

    def test_short_repeats_are_named(self, tmp_path):
        tasks, _ = _tasks(tmp_path, ["tab-L1"])
        runs = tmp_path / "runs"
        _full(runs, "tab-L1", reps=1)
        res = L.scan(tasks, runs, registered=["tab-L1"])
        assert res["collections"]["tab-L1"]["short_of_registered_repeats"] == {
            "r5": 1, "baseline": 1, "r1": 1}

    def test_rule_of_three(self):
        assert L.rule_of_three(0, 30) == pytest.approx(0.1)
        assert L.rule_of_three(1, 30) is None
        assert L.rule_of_three(0, 0) is None


# ------------------------------------------------- recall, echo and utility


class TestLocalMeasures:
    def _one(self, tmp_path: Path, **kw) -> dict:
        tasks, _ = _tasks(tmp_path, ["tab-L1"])
        runs = tmp_path / "runs"
        _run(runs, "tab-L1", "r5", **kw)
        return L.scan(tasks, runs)["collections"]["tab-L1"]["runs"]["tab-L1__r5"]

    def test_recall_is_token_equality_with_a_masked_entity(self, tmp_path):
        r = self._one(tmp_path, entities=(("alder  QUINT", "PERSON"), ("Fenwick", "LOCATION"),
                                          ("47123/98", "IDENTIFIER")))["extractor_recall"]
        assert r["source"] == "entities.json"
        assert (r["DIRECT"]["k"], r["DIRECT"]["n"]) == (2, 2)
        assert (r["QUASI"]["k"], r["QUASI"]["n"]) == (0, 4)
        assert (r["all"]["k"], r["all"]["n"]) == (2, 6)
        # 'Fenwick' is inside the gold 'Fenwick Lane', not around it: not covered.
        assert r["covered"]["all"]["k"] == 2

    def test_a_string_inside_a_longer_masked_entity_is_covered_not_exact(self, tmp_path):
        r = self._one(tmp_path, entities=(("the Harlow Borough Council offices", "ORG"),
                                          ("on 14 March 1999 at noon", "DATE")))
        rec = r["extractor_recall"]
        assert (rec["all"]["k"], rec["covered"]["all"]["k"]) == (0, 2)
        assert rec["covered"]["QUASI"]["by_entity_type"]["ORG"]["k"] == 1

    def test_predicate_echo_reads_every_relation_field(self, tmp_path):
        e = self._one(tmp_path, relations=(("PERSON", "fined by Harlow Borough Council", "ORG"),
                                           ("PERSON", "lives at", "LOCATION")))["predicate_echo"]
        assert e["relations"] == 2
        assert (e["all"]["k"], e["all"]["n"]) == (1, 6)
        assert e["QUASI"]["by_entity_type"]["ORG"]["k"] == 1

    def test_without_extractions_echo_is_absent_and_recall_reads_entities(self, tmp_path):
        r = self._one(tmp_path, entities=(("Alder Quint", "PERSON"),), extractions=False)
        assert r["predicate_echo"]["source"] is None
        assert r["extractor_recall"]["DIRECT"]["k"] == 1

    def test_utility_counts_sections_and_report_strings(self, tmp_path):
        m = _manifest(notes=["plan: 2 sections, 0 unknown slot refs dropped"], sections=[
            {"section_id": "s1", "slots_offered": 2, "refused": None, "sentences_pruned": 0,
             "facts_unavailable": 0},
            {"section_id": "s2", "slots_offered": 2, "refused": "draft: SHINGLE_HIT: 1",
             "sentences_pruned": 0, "facts_unavailable": 0},
            {"section_id": "s3", "slots_offered": 2, "refused": "draft: CloudError: HTTP 529",
             "sentences_pruned": 0, "facts_unavailable": 0}])
        report = "# g\n\nOn 14 March 1999 the Harlow Borough Council\\. ruled."
        u = self._one(tmp_path, manifest=m, report=report)["utility"]
        assert (u["sections_planned"], u["sections_delivered"], u["sections_refused"]) == (2, 1, 1)
        # A transport failure is not a refusal: nothing decided against it.
        assert u["sections_transport_failed"] == 1
        rs = u["report_strings"]
        assert rs["DATETIME"]["k"] == rs["ORG"]["k"] == 1
        assert (rs["QUANTITY"]["k"], rs["any"]["k"], rs["any"]["n"]) == (0, 2, 3)


# ------------------------------------------------------------------ adversary


class FakeAdversary:
    """Writes one guess from the goal alone and two from a real trace."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def messages(self, messages: list[dict], **kw) -> CloudReply:
        prompt = messages[0]["content"]
        self.prompts.append(prompt)
        text = ("Perhaps Alder Quint." if "DOCUMENT STATS" not in prompt
                else "Alder Quint lived at Fenwick Lane.")
        return CloudReply(text=text, stop_reason="end_turn", model="fake-adversary",
                          input_tokens=1000, output_tokens=100)


class TestAdversary:
    def _setup(self, tmp_path: Path) -> tuple[list[R.Task], Path, Path]:
        tasks, tf = _tasks(tmp_path, ["tab-L1"])
        runs = tmp_path / "runs"
        _full(runs, "tab-L1")
        return tasks, tf, runs

    def test_without_yes_it_makes_no_call_and_needs_no_key(self, tmp_path, monkeypatch, capsys):
        _tasks_, tf, runs = self._setup(tmp_path)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        def boom(*a, **k):
            raise AssertionError("no client may be built without --yes")

        monkeypatch.setattr(L, "CloudClient", boom)
        monkeypatch.setattr(L, "reconstruct", boom)
        rc = L.main(["adversary", "--tasks", str(tf), "--runs", str(runs)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "refusing to spend without --yes" in out and "TOTAL" in out
        assert "tab-L1__control" in out
        assert not list(runs.rglob("reconstruction.json"))
        assert not (runs / "tab-L1__control").exists()

    def test_max_usd_refuses_before_any_call(self, tmp_path, monkeypatch, capsys):
        _tasks_, tf, runs = self._setup(tmp_path)
        monkeypatch.setattr(L, "reconstruct", lambda *a, **k: pytest.fail("called"))
        rc = L.main(["adversary", "--tasks", str(tf), "--runs", str(runs), "--yes",
                     "--max-usd", "0.01"])
        assert rc == 1 and "exceeds --max-usd" in capsys.readouterr().out

    def test_the_control_is_subtracted(self, tmp_path):
        tasks, _tf, runs = self._setup(tmp_path)
        fake = FakeAdversary()
        items = L.plan_adversary(tasks, runs)
        asyncio.run(L.run_adversary(items, runs, fake))
        assert len(fake.prompts) == 4
        control = [p for p in fake.prompts if "DOCUMENT STATS" not in p]
        assert len(control) == 1 and GOAL in control[0]
        ctrl = runs / "tab-L1__control"
        assert json.loads((ctrl / "egress_trace.jsonl").read_text("utf-8"))["messages"] == [
            {"role": "user", "content": GOAL}]
        for d in (R.run_dir_for(runs, "tab-L1", a) for a in R.ARMS):
            assert (d / "adversary_output.txt").exists() and (d / "reconstruction.json").exists()
        assert not (R.run_dir_for(runs, "tab-L1", "r5", 2) / "adversary_output.txt").exists()

        res = L.scan(tasks, runs, registered=["tab-L1"])
        g3 = res["collections"]["tab-L1"]["g3"]
        assert g3["control"]["recovered"]["all"]["k"] == 1
        r5 = g3["arms"]["r5"]
        assert (r5["gross"]["all"]["k"], r5["net"]["all"]["k"]) == (2, 1)
        assert r5["net"]["DIRECT"]["k"] == 0 and r5["net"]["QUASI"]["k"] == 1
        assert res["by_arm"]["baseline"]["g3"]["net"]["all"] == {"k": 1, "n": 6, "rate": 1 / 6}
        dumped = json.dumps(res)
        assert "Fenwick Lane" not in dumped and "lived at" not in dumped

    def test_without_a_control_output_net_is_not_computed(self, tmp_path):
        tasks, _tf, runs = self._setup(tmp_path)
        items = [i for i in L.plan_adversary(tasks, runs, arms=["r5"]) if i.kind == "trace"]
        asyncio.run(L.run_adversary(items, runs, FakeAdversary()))
        r5 = L.scan(tasks, runs)["collections"]["tab-L1"]["g3"]["arms"]["r5"]
        assert r5["net"] is None and "control" in r5["net_reason"]

    def test_attacked_runs_are_skipped_and_a_run_without_trace_is_named(self, tmp_path):
        tasks, _tf, runs = self._setup(tmp_path)
        (R.run_dir_for(runs, "tab-L1", "r1") / "egress_trace.jsonl").unlink()
        fake = FakeAdversary()
        asyncio.run(L.run_adversary(L.plan_adversary(tasks, runs), runs, fake))
        assert len(fake.prompts) == 3
        again = L.plan_adversary(tasks, runs)
        assert {i.name: i.skip for i in again} == {
            "tab-L1__r5": "already attacked (--force to redo)",
            "tab-L1__baseline": "already attacked (--force to redo)",
            "tab-L1__r1": "no egress_trace.jsonl: phase one has not run",
            "tab-L1__control": "already attacked (--force to redo)"}

    def test_force_keeps_the_earlier_attempt(self, tmp_path):
        tasks, _tf, runs = self._setup(tmp_path)
        asyncio.run(L.run_adversary(L.plan_adversary(tasks, runs, arms=["r5"]), runs,
                                    FakeAdversary()))
        asyncio.run(L.run_adversary(L.plan_adversary(tasks, runs, arms=["r5"], force=True), runs,
                                    FakeAdversary()))
        kept = runs.parent / "attempts" / "tab-L1__r5__attempt1"
        assert (kept / "adversary_output.txt").exists()
        assert json.loads((kept / "attempt.json").read_text("utf-8"))["egress_trace_is_copy"]

    def test_the_estimate_is_capped_and_the_control_is_cheap(self):
        at_cap = L.adversary_usd(None)
        assert at_cap == pytest.approx(
            (len(L.ADVERSARY_SYSTEM) + len(L._PROMPT_PREFIX) + L.TRACE_MAX_CHARS
             + len(L._TRUNCATION_MARK)) / 3.5 * R.USD_IN + 8192 * R.USD_OUT)
        assert L.adversary_usd([_exchange("plan", "x" * 500_000)]) == pytest.approx(at_cap)
        assert L.adversary_usd(L.control_trace(GOAL)) < at_cap


# ---------------------------------------------------------- estimate, health


class TestEstimate:
    def test_everything_is_priced_until_it_is_on_disk(self, tmp_path):
        tasks, _ = _tasks(tmp_path, ["tab-L1"])
        runs = tmp_path / "runs"
        row = L.estimate(tasks, runs)[0]
        per = R.estimate_private_cost(tasks)["tab-L1"]
        assert len(row["private"]) == 6 and sum(row["private"].values()) == pytest.approx(6 * per)
        assert sorted(row["adversary"]) == ["tab-L1__baseline", "tab-L1__control",
                                            "tab-L1__r1", "tab-L1__r5"]
        _run(runs, "tab-L1", "r5")
        assert len(L.estimate(tasks, runs)[0]["private"]) == 5
        assert len(L.estimate(tasks, runs, fresh=True)[0]["private"]) == 6

    def test_whole_collections_are_admitted_in_order(self):
        rows = [{"id": "a", "total": 2.0}, {"id": "b", "total": 2.0}, {"id": "c", "total": 0.5}]
        assert L.admit(rows, 3.0) == (["a"], ["b", "c"])
        assert L.admit(rows, 10.0) == (["a", "b", "c"], [])

    def test_the_cli_writes_the_admitted_tasks_and_says_what_is_left_out(self, tmp_path, capsys):
        _tasks_, tf = _tasks(tmp_path, ["tab-L1", "tab-L2"])
        runs, out = tmp_path / "runs", tmp_path / "out" / "admitted.json"
        one = L.estimate(_tasks_[:1], runs)[0]["total"]
        rc = L.main(["estimate", "--tasks", str(tf), "--runs", str(runs), "--cap",
                     f"{one + 0.5:.4f}", "--spent", "0.25", "--admit-out", str(out)])
        printed = capsys.readouterr().out
        assert rc == 4
        assert [t["id"] for t in json.loads(out.read_text("utf-8"))] == ["tab-L1"]
        assert "left out whole, over the cap: tab-L2" in printed
        assert L.main(["estimate", "--tasks", str(tf), "--runs", str(runs), "--cap", "0.01"]) == 5
        capsys.readouterr()
        assert L.main(["estimate", "--tasks", str(tf), "--runs", str(runs),
                       "--total-only"]) == 0
        assert float(capsys.readouterr().out) == pytest.approx(2 * one)


class TestHealthLines:
    def test_each_expected_run_gets_one_status(self, tmp_path):
        tasks, _ = _tasks(tmp_path, ["tab-L1"])
        runs = tmp_path / "runs"
        _run(runs, "tab-L1", "r5")
        _run(runs, "tab-L1", "baseline", manifest=_manifest(arm="baseline", sections=[
            {"section_id": "s1", "slots_offered": 2, "refused": "draft: GatewayError: down",
             "sentences_pruned": 0, "facts_unavailable": 0}]))
        _run(runs, "tab-L1", "r1", manifest=_manifest(arm="r1", planner_refs_returned=2,
                                                      planner_refs_dropped=2))
        assert L.health_lines(tasks, runs, reps=1) == [
            ("tab-L1", "r5", 1, "valid"), ("tab-L1", "baseline", 1, "transport-failure"),
            ("tab-L1", "r1", 1, "invalid")]
        assert ("tab-L1", "r5", 2, "missing") in L.health_lines(tasks, runs)

    def test_a_transport_failure_is_re_run_once_only(self, tmp_path):
        """After its one re-run (the failed run moved to the attempts directory),
        a run that fails in transport again is not offered for another."""
        tasks, _ = _tasks(tmp_path, ["tab-L1"])
        runs = tmp_path / "runs"
        failing = _manifest(arm="baseline", sections=[
            {"section_id": "s1", "slots_offered": 2, "refused": "draft: CloudError: 529",
             "sentences_pruned": 0, "facts_unavailable": 0}])
        _run(runs, "tab-L1", "baseline", manifest=failing)
        assert L.health_lines(tasks, runs, arms=["baseline"], reps=1) == [
            ("tab-L1", "baseline", 1, "transport-failure")]
        R.archive_attempt(R.run_dir_for(runs, "tab-L1", "baseline"), runs)
        _run(runs, "tab-L1", "baseline", manifest=failing)
        assert L.health_lines(tasks, runs, arms=["baseline"], reps=1) == [
            ("tab-L1", "baseline", 1, L.RERUN_USED)]


class TestPending:
    def test_only_runs_never_attempted_and_with_their_extraction_are_pending(self, tmp_path,
                                                                             capsys):
        tasks, tf = _tasks(tmp_path, ["tab-L1", "tab-L2", "tab-L3"])
        runs = tmp_path / "runs"
        _run(runs, "tab-L1", "r5")                      # on disk: left to run_evaluation
        a = runs.parent / "attempts" / "tab-L2__r5__attempt1"
        a.mkdir(parents=True)                           # exited non-zero: not run again
        (a / "attempt.json").write_text(json.dumps({"phase": "private", "exit_code": 1,
                                                    "egress_trace_is_copy": False}), "utf-8")
        keep, left = L.pending(tasks, runs, "r5", 1)
        assert [t.id for t in keep] == ["tab-L3"]
        assert left == ["tab-L2 r5 1: attempted before and not on disk; not run again "
                        "(§12.9: one re-run, and only for a transport failure)"]
        keep, left = L.pending(tasks, runs, "baseline", 1, reuse_from="r5")
        assert [t.id for t in keep] == ["tab-L1"]
        assert len(left) == 2 and all("no r5 repeat-1 extraction" in x for x in left)
        out = tmp_path / "pending.json"
        assert L.main(["pending", "--tasks", str(tf), "--runs", str(runs), "--arm", "r5",
                       "--rep", "1", "--out", str(out)]) == 0
        assert [t["id"] for t in json.loads(out.read_text("utf-8"))] == ["tab-L3"]
        assert "left out: tab-L2 r5 1" in capsys.readouterr().out


class TestBudget:
    def test_recorded_spend_counts_traces_attempts_and_adversary_calls(self, tmp_path, capsys):
        runs = tmp_path / "runs"
        trace = [{**_exchange("plan", "x"), "input_tokens": 1_000_000, "output_tokens": 100_000}]
        d = _run(runs, "tab-L1", "r5", trace=trace)
        (d / L.ADVERSARY_RUN_NAME).write_text(json.dumps({"usd": 0.5}), "utf-8")
        R.archive_attempt(d, runs, copy=True)           # a duplicate trace: not counted again
        # The re-attack the copy was made for overwrites the run's own record.
        (d / L.ADVERSARY_RUN_NAME).write_text(json.dumps({"usd": 0.25}), "utf-8")
        moved = _run(runs, "tab-L1", "r1", trace=trace)
        R.archive_attempt(moved, runs)                  # a replaced run: it was billed
        one = 1_000_000 * R.USD_IN + 100_000 * R.USD_OUT
        capsys.readouterr()
        rec = L.recorded_spend(runs)
        assert rec["private"] == pytest.approx(2 * one)
        assert rec["adversary"] == pytest.approx(0.75)  # both attacks, each once
        argv = ["budget", "--runs", str(runs), "--cap", "15", "--spent", "1"]
        assert L.main([*argv, "--remaining-only"]) == 0
        assert float(capsys.readouterr().out) == pytest.approx(15 - 1 - 2 * one - 0.75)
        assert L.main([*argv, "--need-reruns", "2"]) == 0
        need = int((15 - 1 - 2 * one - 0.75) / L.PRIVATE_RUN_USD) + 1
        assert L.main([*argv, "--need-reruns", str(need)]) == 6


class TestAdversaryGuard:
    def test_runs_inside_the_repository_other_than_track_l_are_refused(self, tmp_path):
        tasks, _ = _tasks(tmp_path, ["tab-L1"])
        problems = L.adversary_guard(tasks, REPO / "eval" / "runs", tmp_path / "none.json")
        assert any("--runs" in p and "eval/real/runs" in p for p in problems)
        assert any("not a track-L collection" in p for p in problems)

    def test_with_yes_a_collection_without_its_manifest_is_refused_before_any_key(
            self, tmp_path, monkeypatch, capsys):
        _tasks_, tf = _tasks(tmp_path, ["tab-L1"])
        runs = tmp_path / "runs"
        _full(runs, "tab-L1")

        def boom(*a, **k):
            raise AssertionError("nothing may be read or built before the guard")

        for name in ("host_provenance", "_require_key"):
            monkeypatch.setattr(R, name, boom)
        monkeypatch.setattr(L, "CloudClient", boom)
        rc = L.main(["adversary", "--tasks", str(tf), "--runs", str(runs), "--yes",
                     "--manifest", str(tmp_path / "manifest_l.json")])
        out = capsys.readouterr().out
        assert rc == 1 and "no MANIFEST.json" in out and "no call was made" in out


class TestExtraction:
    @staticmethod
    def _extraction(corpus: Path, ents: list[tuple[str, str]], rels: list[list[str]]) -> dict:
        docs = L._docs(corpus)
        return {"format": "privdeep.extractions/1", "documents": [
            {"doc_id": d.doc_id, "text_sha256": text_sha256(d),
             "entities": [{"text": surface, "category": kind} for surface, kind in ents],
             "relations": rels} for d in docs]}

    def test_the_free_fallback_uses_the_scans_rules_and_writes_counts(self, tmp_path):
        tasks, tf = _tasks(tmp_path, ["tab-L1"])
        root = tmp_path / "extractions" / "tab-L1"
        root.mkdir(parents=True)
        ex = self._extraction(tasks[0].corpus, [("Alder Quint", "PERSON"),
                                                ("Harlow Borough Council offices", "ORG")],
                              [["PERSON", "lived at Fenwick Lane", "LOCATION"]])
        for name in ("extraction_1.json", "extraction_2.json"):   # one extraction, twice
            (root / name).write_text(json.dumps(ex), "utf-8")
        (root / "extract_manifest.json").write_text("{}", "utf-8")
        out = tmp_path / "out.json"
        assert L.main(["extraction", "--tasks", str(tf), "--extractions",
                       str(tmp_path / "extractions"), "--out", str(out)]) == 0
        rep = json.loads(out.read_text("utf-8"))
        assert rep["distinct_extractions"] == 1
        rec = rep["extractor_recall"]
        assert (rec["all"]["k"], rec["covered"]["all"]["k"], rec["all"]["n"]) == (1, 2, 6)
        assert rep["predicate_echo"]["all"]["k"] == 1
        assert not [x for x in NON_LABEL if x in out.read_text("utf-8")]

    def test_an_extraction_of_other_documents_is_refused(self, tmp_path):
        tasks, _tf = _tasks(tmp_path, ["tab-L1"])
        root = tmp_path / "extractions" / "tab-L1"
        root.mkdir(parents=True)
        ex = self._extraction(tasks[0].corpus, [], [])
        ex["documents"][0]["text_sha256"] = "0" * 64
        (root / "extraction_1.json").write_text(json.dumps(ex), "utf-8")
        with pytest.raises(SystemExit, match="not an extraction of this collection"):
            L.extraction_scan(tasks, tmp_path / "extractions")

    def test_the_scan_measures_each_distinct_extraction_once(self, tmp_path):
        tasks, _ = _tasks(tmp_path, ["tab-L1"])
        runs = tmp_path / "runs"
        for arm in R.ARMS:
            _run(runs, "tab-L1", arm, entities=(("Alder Quint", "PERSON"),))
        res = L.scan(tasks, runs)
        [only] = res["collections"]["tab-L1"]["extractions"]
        assert sorted(only["runs"]) == ["tab-L1__baseline", "tab-L1__r1", "tab-L1__r5"]
        assert res["extraction"]["distinct_extractions"] == 1
        assert res["extraction"]["extractor_recall"]["all"] == {"k": 1, "n": 6, "rate": 1 / 6}


# ---------------------------------------------------------------- verify


class TestVerify:
    def _built(self, tmp_path: Path) -> tuple[list[R.Task], Path, Path]:
        tasks, _ = _tasks(tmp_path, ["tab-L1"])
        d = tasks[0].corpus
        for name in L.COLLECTION_FILES:
            if name not in (L.COLLECTION_MANIFEST, L.IDENTIFIERS_NAME, "doc1.md"):
                (d / name).write_text(f"{name}\n", encoding="utf-8")
        files = {n: hashlib.sha256((d / n).read_bytes()).hexdigest()
                 for n in L.COLLECTION_FILES if n != L.COLLECTION_MANIFEST}
        man = {"collection": "tab-L1", "split": "test", "doc_ids": ["001-1", "001-2"],
               "source_sha256": "a" * 64, "files": files}
        (d / L.COLLECTION_MANIFEST).write_text(json.dumps(man), encoding="utf-8")
        summary = tmp_path / "manifest_l.json"
        summary.write_text(json.dumps({"collections": {"tab-L1": man}}), encoding="utf-8")
        return tasks, d, summary

    def test_a_faithful_rebuild_verifies(self, tmp_path):
        tasks, _d, summary = self._built(tmp_path)
        assert L.verify(tasks, summary) == []

    def test_an_edited_document_an_extra_file_and_a_stale_summary_are_named(self, tmp_path):
        tasks, d, summary = self._built(tmp_path)
        (d / "doc2.md").write_text("edited\n", encoding="utf-8")
        (d / "notes.md").write_text("stray\n", encoding="utf-8")
        s = json.loads(summary.read_text("utf-8"))
        s["collections"]["tab-L1"]["doc_ids"] = ["001-9"]
        summary.write_text(json.dumps(s), encoding="utf-8")
        problems = L.verify(tasks, summary)
        assert any("doc2.md does not match" in p for p in problems)
        assert any("notes.md" in p for p in problems)
        assert any("doc_ids differs" in p for p in problems)


# --------------------------------------------------------- §12.8 integrity


class TestIntegrity:
    @staticmethod
    def _rt(digest: str = "sha256:m1", model: str = "claude-sonnet-5-x") -> dict:
        return {"cloud_models_resolved": [model], "runtime": {
            "ollama_image": {"id": "sha256:img", "repo_digests": ["ollama@sha256:d1"]},
            "local_model": {"name": "qwen3:14b", "digest": digest}}}

    def test_equal_differs_and_unrecorded(self, tmp_path):
        ref = tmp_path / "ad"
        for name in ("smoke-q3__r5", "prose-c__r1"):
            (ref / name).mkdir(parents=True)
            (ref / name / "manifest.json").write_text(json.dumps(self._rt()), encoding="utf-8")
        dirs = []
        for name, m in (("tab-L1__r5", self._rt()), ("tab-L1__r1", self._rt("sha256:m2")),
                        ("tab-L1__baseline", {"cloud_models_resolved": []})):
            (tmp_path / "l" / name).mkdir(parents=True)
            (tmp_path / "l" / name / "manifest.json").write_text(json.dumps(m), "utf-8")
            dirs.append(tmp_path / "l" / name)
        out = L.integrity(dirs, ref)
        assert set(out["per_run"]["tab-L1__r5"].values()) == {"equal"}
        assert out["per_run"]["tab-L1__r1"]["slm_model_digest"] == "differs"
        assert out["per_run"]["tab-L1__baseline"]["cloud_models_resolved"] == "unrecorded"
        assert out["all_equal"] is False
        assert L.integrity(dirs[:1], ref)["all_equal"] is True


# ------------------------------------------------------------ scope wording


def _scope_items(start: str, end: str) -> list[str]:
    text = (REPO / "PRIVDEEP_ICCIT_SCOPE.md").read_text(encoding="utf-8")
    i = text.index(start)
    section = text[i:text.index(end, i)]
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


def test_hl1_is_its_scope_bullet():
    """The decision rule is the scope's text, whole: a sentence changed on either
    side fails here, so the scan cannot drift from what the author signs."""
    items = _scope_items("**12.7 Decision rule and claim restriction.**", "**12.8 Integrity.**")
    found = [i for i in items if i.startswith("HL1 holds when")]
    assert found == [f"{L.HL1['wording']} {L.HL1['reporting']} {L.HL1['if_fails']}"]


# ------------------------------------------------------------- the batch


def _git(repo: Path, *args: str) -> None:
    assert GIT
    subprocess.run([GIT, "-c", "user.name=t", "-c", "user.email=t@example.invalid",  # noqa: S603
                    "-c", "commit.gpgsign=false", "-c", "tag.gpgSign=false", *args],
                   cwd=repo, check=True, capture_output=True, env=_git_env())


def _git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_INDEX_FILE",
                                                             "GIT_WORK_TREE")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return env


UNSIGNED = "## 12. Amendment\n\nSigned: ______________ (author), date ______________.\n"
SIGNED = "## 12. Amendment\n\nSigned: A. Author (author), date 2026-10-07.\n"
# What the batch needs git to ignore, as the repository's .gitignore has it.
GITIGNORE = ("data/\neval/runs/\neval/attempts/\neval/pilot/\neval/real/corpora/\n"
             "eval/real/runs/\neval/real/attempts/\neval/real/out/\n")


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    """A throwaway repository, a docker that only records being called, and a
    marker .env whose sourcing leaves a mark: the refusals must come before
    either. PRIVDEEP_BATCH_TEST stops --yes where the .env would be read, and
    under it the script's .env is the marker, never the real one."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    (r / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    _git(r, "add", ".gitignore")
    _git(r, "commit", "-q", "-m", "ignore")
    marks = tmp_path / "marks"
    marks.mkdir()
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker = fakebin / "docker"
    docker.write_text(f'#!/bin/sh\necho "$@" >> "{marks}/docker"\nexit 1\n', encoding="utf-8")
    docker.chmod(0o755)
    env_file = tmp_path / "dot.env"
    env_file.write_text(f'touch "{marks}/env_sourced"\n', encoding="utf-8")
    env = {**_git_env(), "PATH": f"{fakebin}:{os.environ['PATH']}",
           "PRIVDEEP_BATCH_TEST": "1", "PRIVDEEP_ENV_FILE": str(env_file), "PY": "/bin/false",
           "PRESIDIO_PY": "/bin/false"}
    return r, env, marks


def _commit_scope(r: Path, text: str) -> None:
    (r / "PRIVDEEP_ICCIT_SCOPE.md").write_text(text, encoding="utf-8")
    _git(r, "add", "PRIVDEEP_ICCIT_SCOPE.md")
    _git(r, "commit", "-q", "-m", "scope")


def _commit(r: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text(text, encoding="utf-8")
        _git(r, "add", rel)
    _git(r, "commit", "-q", "-m", "change")


def _ready(r: Path, scope: str = SIGNED) -> None:
    """Everything the main batch's pre-flight asks of git and the disk: the
    three tags at HEAD, a signed §12, a track-L file and container code, and
    an A-D batch manifest on disk."""
    _commit_scope(r, scope)
    _commit(r, {"scripts/real_l.py": "x = 1\n", "backend/src/m.py": "y = 1\n",
                "gateway/app.py": "z = 1\n", "gateway/tests/test_app.py": "t = 1\n"})
    for t in ("paper-freeze", "real-prereg", "real-freeze"):
        _git(r, "tag", t)
    ad = r / "eval" / "runs" / "smoke-q3__r5"
    ad.mkdir(parents=True)
    (ad / "manifest.json").write_text("{}", encoding="utf-8")


def _retag(r: Path) -> None:
    _git(r, "tag", "-f", "real-freeze")


def _batch(r: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    assert BASH
    return subprocess.run([BASH, str(BATCH), *args], cwd=r, env=env,  # noqa: S603
                          capture_output=True, text=True, timeout=60, check=False)


TEST_MODE_STOP = "ABORT: test mode (PRIVDEEP_BATCH_TEST): the pre-flight passed"


@pytest.mark.skipif(GIT is None or BASH is None, reason="needs git and bash")
class TestBatchScript:
    def test_it_parses(self):
        assert subprocess.run([BASH, "-n", str(BATCH)], check=False).returncode == 0  # noqa: S603

    def test_it_needs_dry_run_or_yes(self, repo):
        r, env, _marks = repo
        assert _batch(r, env).returncode == 2
        assert _batch(r, env, "--yes", "--dry-run").returncode == 2

    def test_the_env_file_is_not_overridable_outside_the_tests_switch(self):
        text = BATCH.read_text(encoding="utf-8")
        assert "\nENV_FILE=.env\n" in text
        assert ('if [ -n "$TEST_MODE" ]; then ENV_FILE=${PRIVDEEP_ENV_FILE:-/dev/null}; fi'
                in text)
        assert text.count("PRIVDEEP_ENV_FILE") == 1

    def test_a_passing_pre_flight_stops_at_the_test_switch_before_env_and_docker(self, repo):
        r, env, marks = repo
        _ready(r)
        p = _batch(r, env, "--yes", "--spent", "0.65")
        assert p.returncode == 3 and TEST_MODE_STOP in p.stdout, p.stdout + p.stderr
        assert not list(marks.iterdir()), "nothing may read the .env or call docker first"

    def test_it_refuses_when_head_is_not_the_real_freeze_tag(self, repo):
        r, env, marks = repo
        _commit_scope(r, SIGNED)
        _git(r, "tag", "real-prereg")
        p = _batch(r, env, "--yes")
        assert p.returncode == 3
        assert "ABORT: HEAD is not the tag real-freeze" in p.stdout
        assert not list(marks.iterdir()), "nothing may read the .env or call docker first"

    def test_it_refuses_an_unsigned_scope_at_the_tag(self, repo):
        r, env, marks = repo
        _commit_scope(r, UNSIGNED)
        _git(r, "tag", "real-freeze")
        p = _batch(r, env, "--yes")
        assert p.returncode == 3 and "scope §12 is not signed: a blank is left" in p.stdout
        assert not list(marks.iterdir())

    @pytest.mark.parametrize("scope,why", [
        ("## 12. Amendment\n\nThe rule.\n", "no signature line with a date"),
        ("## 12. Amendment\n\nSigned: pending\n", "no signature line with a date"),
        ("## 12. Amendment\n\nSigned: A. Author (author), date soon.\n",
         "no signature line with a date"),
        ("## 12. Amendment\n\n**Status: DRAFT, not in force.**\n\n"
         "Signed: A. Author (author), date 2026-10-07.\n", "it still says 'Status: DRAFT'"),
        ("## 12. Amendment\n\n**12.11** Law 91/2025/QH15: ______________.\n\n"
         "Signed: A. Author (author), date 2026-10-07.\n", "a blank is left"),
    ])
    def test_the_signature_check_fails_closed(self, repo, scope, why):
        r, env, marks = repo
        _ready(r, scope)
        p = _batch(r, env, "--yes", "--spent", "0")
        assert p.returncode == 3 and f"scope §12 is not signed: {why}" in p.stdout, p.stdout
        assert not list(marks.iterdir())

    def test_the_authors_own_signature_form_and_a_later_section_pass(self, repo):
        r, env, _marks = repo
        _ready(r, "## 12. Amendment\n\nSigned by the author on 2026-10-07, in the session.\n\n"
                  "## 13. Later\n\nSigned: ______________\n")
        p = _batch(r, env, "--yes", "--spent", "0")
        assert TEST_MODE_STOP in p.stdout, p.stdout

    def test_the_pilot_skips_the_tags_but_not_the_signature(self, repo):
        r, env, marks = repo
        _commit_scope(r, UNSIGNED)
        p = _batch(r, env, "--pilot", "--yes")
        assert p.returncode == 3 and "scope §12 is not signed" in p.stdout
        assert "real-freeze" not in p.stdout
        assert not list(marks.iterdir())

    def test_a_missing_prereg_tag_is_refused(self, repo):
        r, env, marks = repo
        _commit_scope(r, SIGNED)
        _git(r, "tag", "real-freeze")
        p = _batch(r, env, "--yes")
        assert p.returncode == 3 and "the tag real-prereg does not exist" in p.stdout
        assert not list(marks.iterdir())

    def test_a_track_l_change_after_real_prereg_is_refused(self, repo):
        r, env, marks = repo
        _ready(r)
        _commit(r, {"scripts/real_l.py": "x = 2\n"})
        _retag(r)
        p = _batch(r, env, "--yes", "--spent", "0")
        assert p.returncode == 3, p.stdout
        assert "the track-L paths differ between real-prereg and HEAD" in p.stdout
        assert not list(marks.iterdir())

    def test_a_change_to_scope_12_after_real_prereg_is_refused(self, repo):
        r, env, _marks = repo
        _ready(r)
        _commit_scope(r, SIGNED.replace("Amendment", "Amendment, reworded"))
        _retag(r)
        p = _batch(r, env, "--yes", "--spent", "0")
        assert p.returncode == 3 and "scope §12 differs between real-prereg and HEAD" in p.stdout

    def test_container_code_changed_since_paper_freeze_is_refused_but_its_tests_are_not(
            self, repo):
        r, env, _marks = repo
        _ready(r)
        _commit(r, {"gateway/tests/test_app.py": "t = 2\n"})
        _retag(r)
        assert TEST_MODE_STOP in _batch(r, env, "--yes", "--spent", "0").stdout
        _commit(r, {"gateway/app.py": "z = 2\n"})
        _retag(r)
        p = _batch(r, env, "--yes", "--spent", "0")
        assert p.returncode == 3
        assert "the code the containers run differs between paper-freeze and HEAD" in p.stdout

    def test_a_dirty_tracked_tree_is_refused(self, repo):
        r, env, marks = repo
        _ready(r)
        (r / "backend" / "src" / "m.py").write_text("y = 3\n", encoding="utf-8")
        p = _batch(r, env, "--yes", "--spent", "0")
        assert p.returncode == 3 and "ABORT: tracked files differ from HEAD" in p.stdout
        assert not list(marks.iterdir())

    def test_a_missing_ignore_line_is_refused(self, repo):
        r, env, _marks = repo
        _ready(r)
        _commit(r, {".gitignore": GITIGNORE.replace("eval/real/corpora/\n", "")})
        _retag(r)
        p = _batch(r, env, "--yes", "--spent", "0")
        assert p.returncode == 3
        assert "git does not ignore eval/real/corpora/tab-L1/doc1.md" in p.stdout

    def test_attempts_left_over_are_refused_unless_resuming(self, repo):
        r, env, _marks = repo
        _ready(r)
        (r / "eval" / "real" / "attempts" / "tab-L1__r5__attempt1").mkdir(parents=True)
        p = _batch(r, env, "--yes", "--spent", "0")
        assert p.returncode == 3 and "eval/real/attempts is not empty" in p.stdout
        assert TEST_MODE_STOP in _batch(r, env, "--yes", "--spent", "0", "--resume").stdout

    def test_the_a_d_batch_must_be_on_disk(self, repo):
        r, env, _marks = repo
        _ready(r)
        (r / "eval" / "runs" / "smoke-q3__r5" / "manifest.json").unlink()
        p = _batch(r, env, "--yes", "--spent", "0")
        assert p.returncode == 3 and "no A-D batch manifest under eval/runs" in p.stdout

    def test_the_spend_before_the_batch_must_be_known(self, repo):
        r, env, _marks = repo
        _ready(r)
        p = _batch(r, env, "--yes")
        assert p.returncode == 3 and "pass --spent USD" in p.stdout

    def test_a_dry_run_never_reads_the_env(self, repo):
        """A dry run warns where --yes refuses, reaches the GPU check (the fake
        docker fails it) and never sources the .env."""
        r, env, marks = repo
        _commit_scope(r, UNSIGNED)
        p = _batch(r, env, "--dry-run")
        assert p.returncode == 3, p.stdout + p.stderr
        assert "WARNING (dry run): HEAD is not the tag real-freeze" in p.stdout
        assert "cannot see the GPU" in p.stdout
        assert (marks / "docker").exists() and not (marks / "env_sourced").exists()


def _container_diff_sha(r: Path) -> str:
    """The sha256 of the container-code diff against paper-freeze, computed as
    freeze_batch_real.sh computes it (its CONTAINER_PATHS)."""
    assert GIT
    out = subprocess.run(  # noqa: S603
        [GIT, "diff", "paper-freeze", "HEAD", "--", "backend/src", "gateway",
         ":(exclude)gateway/tests", "shared", "docker-compose.yml",
         "scripts/run_evaluation.py", "scripts/corpora", "scripts/tier1_probe.py",
         "scripts/observation_table.py", "scripts/measure_false_positives.py",
         "pyproject.toml"], cwd=r, capture_output=True, check=True).stdout
    return hashlib.sha256(out).hexdigest()


def test_the_one_signed_container_patch_is_accepted_by_its_diff_hash(repo):
    """§12.13: a container-code change is accepted only when §12 records the
    sha256 of exactly that diff; another change, or a stale hash, still refuses."""
    r, env, _marks = repo
    _ready(r)
    _commit(r, {"gateway/app.py": "z = 2\n"})
    signed = ("## 12. Amendment\n\nSigned: A. Author (author), date 2026-10-07.\n\n"
              f"**12.13 Changelog.** container-code diff sha256 {_container_diff_sha(r)}, "
              "accepted in place of an empty diff.\n")
    _commit_scope(r, signed)
    for t in ("real-prereg", "real-freeze"):
        _git(r, "tag", "-f", t)
    p = _batch(r, env, "--yes", "--spent", "0")
    assert "differs from paper-freeze by the patch §12.13 signs" in p.stdout, p.stdout
    assert TEST_MODE_STOP in p.stdout
    # A further change to the container code is not covered by the signed hash.
    _commit(r, {"backend/src/m.py": "y = 2\n"})
    for t in ("real-prereg", "real-freeze"):
        _git(r, "tag", "-f", t)
    p = _batch(r, env, "--yes", "--spent", "0")
    assert p.returncode == 3
    assert "not by the patch §12.13 signs" in p.stdout, p.stdout
