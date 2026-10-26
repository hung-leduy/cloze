"""The manifest is built to be published; the test is that it cannot carry content."""

from __future__ import annotations

import json

import pytest
from privdeep.audit.manifest import RunManifest, SectionRecord, git_commit, tree_dirty, tree_sha


def test_git_commit_prefers_env_then_git_then_unknown(monkeypatch):
    monkeypatch.setenv("PRIVDEEP_GIT_COMMIT", "abc123")
    assert git_commit() == "abc123"
    monkeypatch.delenv("PRIVDEEP_GIT_COMMIT")
    v = git_commit()
    assert v == "unknown" or len(v) == 40


def test_manifest_round_trips_and_aggregates():
    m = RunManifest(run_id="r1", local_model="qwen3:14b", cloud_model_requested="claude-sonnet-5")
    m.note_resolved_model("claude-sonnet-5-20260901")
    m.note_resolved_model("claude-sonnet-5-20260901")
    m.record_egress(allowed=True, bytes_out=115, bytes_in=106)
    m.record_egress(allowed=False, bytes_out=90)
    m.sections.append(SectionRecord("s1", "Context", 300, 280, 2, 2, 0, 0, 0, 1, 0, 0,
                                    "claude-sonnet-5-20260901", 50, 80))
    m.evidence.append({"evidence_id": "EV-WEB-deadbeef", "tag": "W1",
                       "content_hash": "d" * 64, "source_url": "https://example.invalid"})
    m.finish()
    d = json.loads(m.to_json())
    assert d["cloud_models_resolved"] == ["claude-sonnet-5-20260901"]
    assert d["egress"] == {"attempts": 2, "allowed": 1, "refused": 1, "bytes_out": 205,
                           "bytes_in": 106}
    assert d["sections"][0]["citations_valid"] == 1 and d["finished_at"] >= d["started_at"]
    assert "_FORBIDDEN_KEYS" not in d


def test_content_shaped_keys_are_refused():
    m = RunManifest(run_id="r2")
    m.containment = {"shingles": 330, "sample_text": "Project Zephyr"}   # someone slipped
    with pytest.raises(ValueError, match="looks like content"):
        m.to_json()


def test_content_shaped_key_with_a_counter_is_allowed():
    m = RunManifest(run_id="r2b")
    m.extraction = {"dropped_not_in_text": 3, "entities": 23}
    assert '"dropped_not_in_text": 3' in m.to_json()


def test_manifest_never_contains_private_strings():
    m = RunManifest(run_id="r3")
    m.documents.append({"doc_id": "c0b0b70cd98c49d1", "kind": "xlsx", "chars": 476, "cells": 36})
    m.containment = {"shingles": 330, "m_bits": 11072, "k": 23, "fp_est": 9.7e-8}
    blob = m.to_json()
    for private in ("Project Zephyr", "Nguyễn", "Hanoi", "⟦SLOT:"):
        assert private not in blob


def test_tree_provenance_comes_from_the_driver(monkeypatch):
    """The container has no .git; the host hashes the tree and passes it in."""
    monkeypatch.setenv("PRIVDEEP_GIT_COMMIT", "a" * 40)
    monkeypatch.setenv("PRIVDEEP_TREE_SHA", "b" * 64)
    monkeypatch.setenv("PRIVDEEP_TREE_DIRTY", "true")
    d = json.loads(RunManifest(run_id="p1").to_json())
    assert (d["git_commit"], d["tree_sha256"], d["tree_dirty"]) == ("a" * 40, "b" * 64, True)
    monkeypatch.setenv("PRIVDEEP_TREE_DIRTY", "false")
    assert RunManifest(run_id="p2").tree_dirty is False


def test_an_unchecked_tree_is_unknown_not_clean(monkeypatch):
    """A run launched without the driver was never checked; False would read as clean."""
    monkeypatch.delenv("PRIVDEEP_TREE_SHA", raising=False)
    for v in (None, "", "unknown"):
        if v is None:
            monkeypatch.delenv("PRIVDEEP_TREE_DIRTY", raising=False)
        else:
            monkeypatch.setenv("PRIVDEEP_TREE_DIRTY", v)
        assert tree_dirty() is None
    assert tree_sha() == "unknown"


def test_planner_counters_are_structured_fields():
    m = RunManifest(run_id="p3")
    assert m.planner_refs_returned is None and m.planner_refs_dropped is None
    m.planner_refs_returned, m.planner_refs_dropped = 12, 1
    d = json.loads(m.to_json())
    assert (d["planner_refs_returned"], d["planner_refs_dropped"]) == (12, 1)


def test_runtime_facts_are_held_to_the_same_publishability_rule():
    m = RunManifest(run_id="p4")
    m.runtime = {"local_model": {"digest": "sha256:" + "c" * 64,
                                 "placement": {"processor": "100% GPU"}}}
    assert json.loads(m.to_json())["runtime"]["local_model"]["placement"]["processor"] == \
        "100% GPU"
    m.runtime = {"sample_text": "Project Zephyr"}
    with pytest.raises(ValueError, match="looks like content"):
        m.to_json()
