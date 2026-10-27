"""One manifest per run: what happened, provable later, with no private content.

Scope item T5 and harness Task 4.4, cut to what a referee needs to re-derive
a table: the code that ran (git commit), the models that answered (the ids
the upstream resolved, not the ones requested), the documents by content
hash, the containment filter's parameters, every egress attempt in bytes
and verdicts, the evidence by hash, and per-section counters from the
drafter, the reintegrator and the grounder.

Never in here: document text, entity values, slot-to-value mappings, evidence
snippets, prompts, or drafts. The manifest is the artifact that leaves the
trusted zone with the paper, so it is built to be safe to publish.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from typing import Any

__all__ = ["RunManifest", "SectionRecord", "git_commit", "tree_dirty", "tree_sha"]


def git_commit() -> str:
    """The commit under test. Env first (containers have no .git), then git, then unknown."""
    v = os.environ.get("PRIVDEEP_GIT_COMMIT")
    if v:
        return v
    git = shutil.which("git")
    if not git:
        return "unknown"
    try:
        out = subprocess.run(  # noqa: S603 - fixed args; executable resolved via shutil.which
            [git, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=False
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def tree_sha() -> str:
    """sha256 over the mounted code as the host hashed it, or unknown.

    Only the host can compute it: backend/src, shared and gateway are
    bind-mounted, so the commit alone does not say what ran when the tree was
    edited mid-batch, which it has been. `scripts/run_evaluation.py` hashes
    them and passes the digest in as PRIVDEEP_TREE_SHA. It is the code this
    process loaded only because the driver hashes again before and after each
    run and keeps a run during which the digest changed out of eval/runs; a
    pipeline started some other way gets no such check.
    """
    return os.environ.get("PRIVDEEP_TREE_SHA") or "unknown"


def tree_dirty() -> bool | None:
    """Whether the host tree had uncommitted changes, or None if nobody said.

    None rather than False: a run launched without the driver has not been
    checked, and an unchecked tree must not read as a clean one.
    """
    v = os.environ.get("PRIVDEEP_TREE_DIRTY", "").strip().lower()
    if v in ("1", "true", "yes"):
        return True
    if v in ("0", "false", "no"):
        return False
    return None


@dataclass(slots=True)
class SectionRecord:
    section_id: str
    title: str
    word_budget: int
    word_count: int
    slots_offered: int
    slots_used: int
    invented_slots: int
    unsafe_positions: int
    remote_images_removed: int
    citations_valid: int
    citations_invalid: int
    unbacked_numbers: int
    resolved_model: str
    input_tokens: int
    output_tokens: int
    refused: str | None = None       # reason, if the section was refused at any stage
    # R1. Resolved fact values are written by the core, so the grounder exempts
    # them from unbacked_numbers; they are counted here instead, as locally
    # attested -- a weaker class than citation-backed, not a stronger one.
    facts_resolved: int = 0
    facts_unavailable: int = 0
    # Local rewriting of cloud prose, counted so it is never silent.
    sentences_pruned: int = 0


@dataclass(slots=True)
class RunManifest:
    run_id: str
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    git_commit: str = field(default_factory=git_commit)
    # The commit says which history; these say which bytes. A commit with a
    # dirty tree is not a reproducible description of the code that ran.
    tree_sha256: str = field(default_factory=tree_sha)
    tree_dirty: bool | None = field(default_factory=tree_dirty)
    # Which arm produced this run. R5 is a behaviour switch, and a behaviour
    # switch that leaves no trace in the artifact is how a run gets compared
    # against itself and reports a difference of zero.
    arm: str = "r5"
    # "extracted" when this run ran the local extractor; otherwise the path of
    # the saved extraction it reused. An arm comparison is only about R5 when
    # both arms masked the same entity set, and this is how a reader checks.
    extraction_source: str = "extracted"
    local_model: str = ""
    cloud_model_requested: str = ""
    cloud_models_resolved: list[str] = field(default_factory=list)
    # each: doc_id, kind, sha256_16, chars, cells
    documents: list[dict[str, Any]] = field(default_factory=list)
    extraction: dict[str, int] = field(default_factory=dict)          # counters from Extraction
    # Under R5 a slot is a referent, not a spelling, so these differ and the
    # pair is the measurement: `surface_forms` distinct spellings collapsed
    # into `slots_issued` referents. Recording only one of them hides what
    # R5 did, which is the number the paper is about.
    slots_issued: int = 0
    surface_forms: int = 0
    fragmentation: dict[str, int] = field(default_factory=dict)
    # R1 fact-store counters (structural, derived, conflicts, drops). Empty for
    # the BASELINE and R5 arms.
    facts: dict[str, int] = field(default_factory=dict)
    # shingles, m_bits, k, fp_est, n_min, n_max
    containment: dict[str, Any] = field(default_factory=dict)
    canaries_registered: int = 0
    # Slot references the planner returned, and how many of them named no
    # issued slot and were dropped. None when no usable plan came back (the
    # planning call was refused or failed, or its reply was unusable; the note
    # says which), which is not the same as a plan with zero references.
    planner_refs_returned: int | None = None
    planner_refs_dropped: int | None = None
    # What the host saw around the run and the container cannot: the Ollama
    # image and model digests, where the model was loaded (GPU or CPU), and
    # when the monitor container last started. Filled by
    # scripts/run_evaluation.py after the run is copied out, so it is empty in
    # a manifest written by the pipeline alone. Recorded, never gated on.
    runtime: dict[str, Any] = field(default_factory=dict)
    egress: dict[str, int] = field(default_factory=lambda: {
        "attempts": 0, "allowed": 0, "refused": 0, "bytes_out": 0, "bytes_in": 0})
    evidence: list[dict[str, str]] = field(default_factory=list)      # EvidenceBank.manifest()
    sections: list[SectionRecord] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    _FORBIDDEN_KEYS = ("text", "draft", "prompt", "snippet", "original", "value", "masked")

    def note_resolved_model(self, model_id: str) -> None:
        if model_id and model_id not in self.cloud_models_resolved:
            self.cloud_models_resolved.append(model_id)

    def record_egress(self, *, allowed: bool, bytes_out: int = 0, bytes_in: int = 0) -> None:
        e = self.egress
        e["attempts"] += 1
        e["allowed" if allowed else "refused"] += 1
        e["bytes_out"] += bytes_out
        e["bytes_in"] += bytes_in

    def finish(self) -> None:
        self.finished_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("_FORBIDDEN_KEYS", None)
        return d

    def to_json(self) -> str:
        d = self.to_dict()
        self._assert_publishable(d)
        return json.dumps(d, ensure_ascii=False, indent=2, sort_keys=True)

    @classmethod
    def _assert_publishable(cls, obj: Any, path: str = "") -> None:
        """Structural guard: a content-shaped key may not hold a string.

        A counter named dropped_not_in_text is a number and is fine; a key
        named sample_text holding a string is exactly the slip this exists to
        catch. So the rule is key shape AND string value, recursively.
        """
        if isinstance(obj, dict):
            for k, v in obj.items():
                if any(bad in k.lower() for bad in cls._FORBIDDEN_KEYS) and cls._holds_str(v):
                    raise ValueError(f"manifest key {path + k!r} looks like content; refusing")
                cls._assert_publishable(v, f"{path}{k}.")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                cls._assert_publishable(v, f"{path}[{i}].")

    @classmethod
    def _holds_str(cls, v: Any) -> bool:
        if isinstance(v, str):
            return True
        if isinstance(v, dict):
            return any(cls._holds_str(x) for x in v.values())
        if isinstance(v, list):
            return any(cls._holds_str(x) for x in v)
        return False
