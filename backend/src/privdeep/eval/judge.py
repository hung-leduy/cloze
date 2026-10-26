"""Pairwise report judge: the same rubric over both arms, with position bias visible.

Two reports about the same goal, one from the private pipeline and one from
the unconstrained oracle, are scored on four criteria, 1 to 5 each, by a
model forced into a tool call. Every pair is judged twice with the order
swapped and the two orderings are reported separately as well as averaged,
because a judge that prefers whatever it read first is a known failure and
hiding it inside a mean would be dishonest.

Which model judges is the caller's choice, and it matters for the paper:

* a frontier judge reached DIRECTLY (host side) sees the private arm's
  reintegrated report, which contains real values. That is evaluation-only
  egress, the same class as the oracle arm, and must be disclosed as such;
* a frontier judge reached through the MONITOR will be refused as soon as
  the report carries five verbatim words of the corpus, which is the monitor
  being right. The refusal propagates; nothing is retried;
* a local judge is private but weaker. The paper can carry it as a
  robustness check beside the disclosed frontier judge.

Criteria are deliberately few and orthogonal. Groundedness here is a
reader's impression; the mechanical grounding numbers come from the
citation grounder and are reported separately.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from privdeep.tier2_cloud.cloud_client import CloudClient

log = logging.getLogger(__name__)

__all__ = ["JudgeResult", "RUBRIC", "judge_pair"]

RUBRIC: tuple[tuple[str, str], ...] = (
    ("goal_coverage", "How completely does the report address the stated goal?"),
    ("coherence", "Is the report well organised, with sections that build on each other?"),
    ("groundedness", "Are claims supported by cited evidence rather than asserted?"),
    ("specificity", "Does the report say concrete, checkable things rather than generalities?"),
)

_SCORES = {"type": "object",
           "properties": {name: {"type": "integer", "minimum": 1, "maximum": 5}
                          for name, _ in RUBRIC},
           "required": [name for name, _ in RUBRIC]}

_TOOL = {
    "name": "score_reports",
    "description": "Score two reports on the rubric.",
    "input_schema": {
        "type": "object",
        "properties": {"A": _SCORES, "B": _SCORES,
                       "rationale": {"type": "string", "description": "two or three sentences"}},
        "required": ["A", "B", "rationale"],
    },
}

_SYSTEM = (
    "You are an impartial evaluator of research reports. You will be shown a goal and two "
    "reports, A and B, that attempt it. Score EACH report on every criterion from 1 (poor) "
    "to 5 (excellent), independently; do not rank them against each other, and do not reward "
    "length. Use the score_reports tool. Criteria:\n"
    + "\n".join(f"- {name}: {desc}" for name, desc in RUBRIC)
)


@dataclass(slots=True)
class JudgeResult:
    criteria: tuple[str, ...]
    a_scores: dict[str, float]                 # averaged over both orderings
    b_scores: dict[str, float]
    a_by_order: list[dict[str, int]] = field(default_factory=list)   # [as-A, as-B-swapped]
    b_by_order: list[dict[str, int]] = field(default_factory=list)
    rationales: list[str] = field(default_factory=list)
    judge_models: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def a_mean(self) -> float:
        return sum(self.a_scores.values()) / len(self.a_scores)

    @property
    def b_mean(self) -> float:
        return sum(self.b_scores.values()) / len(self.b_scores)

    @property
    def position_bias(self) -> float:
        """Mean absolute score shift when the same report moves from slot A to slot B."""
        if len(self.a_by_order) < 2:
            return 0.0
        shifts = [abs(self.a_by_order[0][c] - self.a_by_order[1][c]) for c in self.criteria]
        shifts += [abs(self.b_by_order[0][c] - self.b_by_order[1][c]) for c in self.criteria]
        return sum(shifts) / len(shifts)


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + "\n\n[report truncated for judging]"


async def _one(cloud: CloudClient, goal: str, first: str, second: str, max_chars: int,
               max_tokens: int) -> tuple[dict[str, int], dict[str, int], str, str, int, int]:
    user = (f"GOAL:\n{goal.strip()}\n\n=== REPORT A ===\n{_clip(first, max_chars)}\n\n"
            f"=== REPORT B ===\n{_clip(second, max_chars)}\n\nScore both now.")
    reply = await cloud.messages([{"role": "user", "content": user}], system=_SYSTEM,
                                 max_tokens=max_tokens, effort="low", tools=[_TOOL],
                                 tool_choice={"type": "tool", "name": "score_reports"})
    s = reply.structured or {}
    a = {c: int(s.get("A", {}).get(c, 0)) for c, _ in RUBRIC}
    b = {c: int(s.get("B", {}).get(c, 0)) for c, _ in RUBRIC}
    return a, b, str(s.get("rationale", "")), reply.model, reply.input_tokens, reply.output_tokens


async def judge_pair(goal: str, report_a: str, report_b: str, cloud: CloudClient, *,
                     max_chars: int = 40_000, max_tokens: int = 4096) -> JudgeResult:
    """Score both reports in both orderings.

    This function used to pass `temperature=0.0` and call the result
    deterministic. It cannot: Sonnet 5 rejects the sampling parameters
    outright, so there is no knob that makes a judge call repeatable, and two
    runs over the same pair may disagree. The paper has to say so.

    What survives is the mitigation that was already the point of this
    function: every pair is scored in both orderings and the disagreement is
    reported as position bias rather than averaged away. That measures the
    judge's instability instead of assuming it away, which is the honest
    version of what `temperature=0.0` was pretending to buy. For a rate rather
    than a single reading, run the pair several times and report the spread —
    the effort here is `low` precisely so that is affordable.
    """
    """Score report_a and report_b; each is judged in both slots."""
    a1, b1, r1, m1, i1, o1 = await _one(cloud, goal, report_a, report_b, max_chars, max_tokens)
    b2, a2, r2, m2, i2, o2 = await _one(cloud, goal, report_b, report_a, max_chars, max_tokens)
    crit = tuple(c for c, _ in RUBRIC)
    return JudgeResult(
        criteria=crit,
        a_scores={c: (a1[c] + a2[c]) / 2 for c in crit},
        b_scores={c: (b1[c] + b2[c]) / 2 for c in crit},
        a_by_order=[a1, a2], b_by_order=[b1, b2],
        rationales=[r1, r2],
        judge_models=list(dict.fromkeys([m1, m2])),
        input_tokens=i1 + i2, output_tokens=o1 + o2,
    )
