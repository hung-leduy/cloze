"""Turn the abstract payload into a report outline, using the cloud as a planner.

What the cloud sees: the research goal (user-authored, crosses in the clear,
stated as such in the threat model), the concept relations, and the slot ids
with their categories. What it does not see: any value. It is asked for a
plan via a forced tool call so the reply is a JSON object the core can
validate rather than prose the core would have to parse.

Validation happens here, not in the prompt. The model is untrusted input: a
section that cites a slot id the core never issued has invented an entity and
that reference is dropped and counted; budgets are clamped; the section count
is capped. A plan with no usable sections raises, because there is nothing to
execute and pretending otherwise would push the failure into the drafter.

The request body must itself pass the reference monitor. It contains only
abstract types, slot ids and the goal, so it does; if it ever fails, the
monitor's refusal propagates as EgressRefused and nothing is retried.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from privdeep.models.outline import Outline, Section
from privdeep.tier2_cloud.abstract_payload import CHARS_QUANTUM, AbstractPayload
from privdeep.tier2_cloud.cloud_client import REPORT_EFFORT, CloudClient, CloudReply

log = logging.getLogger(__name__)

__all__ = ["MacroPlanner", "PlanResult", "PlannerError"]


class PlannerError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PlanResult:
    outline: Outline
    resolved_model: str
    input_tokens: int
    output_tokens: int
    dropped_unknown_slots: int
    dropped_sections: int
    clamped_budgets: int
    # Slot references the planner returned in the sections that were kept,
    # before any was resolved or dropped. `dropped_unknown_slots` over this is
    # the drop rate the run's health gate reads; the drop count alone cannot
    # tell one bad reference in eighty from one in one.
    refs_returned: int = 0


_TOOL = {
    "name": "plan_outline",
    "description": "Return the report outline as structured sections.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "objective": {"type": "string",
                                      "description": "one sentence, abstract, no entity names"},
                        "word_budget": {"type": "integer"},
                        "slot_ids": {"type": "array", "items": {"type": "string"},
                                     "description": "slot ids this section should refer to"},
                    },
                    "required": ["title", "objective", "word_budget", "slot_ids"],
                },
            }
        },
        "required": ["sections"],
    },
}

_SYSTEM = (
    "You are planning a structured research report for an analyst. You are given the "
    "analyst's goal, an abstract description of a private document as concept relations "
    "over types, and a list of typed placeholders (slot ids). You never see the underlying "
    "values and must never invent names, figures, dates, or places. Refer to entities ONLY "
    "by their exact slot id, copied verbatim. Plan a sequence of sections that together "
    "achieve the goal; each section gets a one-sentence objective phrased abstractly and a "
    "word budget. Use the plan_outline tool for your answer."
)


# The only content a slot reference has: a category and eight hex digits. The
# look-arounds stop it matching inside a longer identifier.
_SLOT_CORE = re.compile(r"(?<![A-Za-z0-9_])([A-Z]+)_([0-9a-f]{8})(?![A-Za-z0-9])")
# What may surround that core without changing which slot is meant: brackets,
# quotes, whitespace and one optional `SLOT:` prefix. Anything else -- a word,
# a second id -- makes the reference ambiguous, and it is dropped.
_SLOT_NOISE = re.compile(r"[\s⟦⟧\[\]\"'`]*(?:SLOT\s*:)?[\s⟦⟧\[\]\"'`]*", re.IGNORECASE)


def _canonical_slot(ref: str, known: set[str]) -> str | None:
    """Resolve a planner's slot reference to the id the core actually issued.

    The prompt lists placeholders in their full delimited form,
    ``⟦SLOT:PROJECT_389a0ca5⟧``, because that is what the drafter must write
    into prose for the reintegrator to find. Asked for the same ids inside a
    JSON array, the model drops some or all of the delimiters, and *which* it
    drops varies from run to run. Three live runs, three outcomes:

    * first run: 78 of 78 came back bare, ``PROJECT_389a0ca5``;
    * the R5 arm: 47 of 47 bare;
    * the baseline arm: 83 of 83 as ``SLOT:ORG_3a8f4003`` -- prefix kept,
      brackets gone.

    This function used to accept exactly two spellings, so the third dropped
    every reference, every section was offered no slots, the drafter wrote
    14,000 characters with no value in them, and the run exited 0. It is the
    same silent failure the bare spelling caused, arriving through a spelling
    nobody enumerated. Enumerating a fourth would repeat the mistake.

    So the reference is reduced to its only content, ``CATEGORY_hex8``, provided
    everything around it is delimiter noise, and then it must still be an id the
    core issued. Membership is what keeps this sound: a slot the core never
    issued is the invented-reference case the reintegrator refuses on, and no
    amount of normalising turns it into a valid one.
    """
    if ref in known:
        return ref
    cores = list(_SLOT_CORE.finditer(ref))
    if len(cores) != 1:
        return None
    m = cores[0]
    if not _SLOT_NOISE.fullmatch(ref[: m.start()] + ref[m.end():]):
        return None
    wrapped = f"⟦SLOT:{m.group(1)}_{m.group(2)}⟧"
    return wrapped if wrapped in known else None


class MacroPlanner:
    def __init__(
        self,
        client: CloudClient,
        *,
        max_sections: int = 8,
        min_budget: int = 150,
        max_budget: int = 1500,
        max_tokens: int = 8192,
        effort: str = REPORT_EFFORT,   # the oracle plans at the same; see cloud_client.py
    ) -> None:
        self.client = client
        self.max_sections = max_sections
        self.min_budget = min_budget
        self.max_budget = max_budget
        self.max_tokens = max_tokens
        self.effort = effort

    async def plan(self, payload: AbstractPayload, goal: str) -> PlanResult:
        reply = await self.client.messages(
            [{"role": "user", "content": self._user_prompt(payload, goal)}],
            system=_SYSTEM,
            max_tokens=self.max_tokens,
            effort=self.effort,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "plan_outline"},
        )
        return self._to_result(reply, payload, goal)

    @staticmethod
    def _user_prompt(payload: AbstractPayload, goal: str) -> str:
        rel_lines = "\n".join(
            f"- ({s}) --{p}--> ({o})" for s, p, o in payload.relations
        ) or "- (none)"
        slot_lines = "\n".join(f"- {sid}  [{cat}]" for sid, cat in payload.slots) or "- (none)"
        attrs = ""
        if payload.attribute_schema:
            # Constants only: the categories and codes are the same for every
            # corpus, so this line discloses nothing about this one.
            cats = ", ".join(c for c, _ in payload.attribute_schema)
            codes = ", ".join(payload.attribute_schema[0][1])
            attrs = (f"ATTRIBUTES every placeholder of category {cats} may have: {codes}. "
                     "Values are resolved locally; assign the placeholders whose attributes "
                     "a section discusses.\n\n")
        # From wire_stats, never the fields: the exact character count is a G2
        # channel and crosses only rounded (see abstract_payload.py).
        stats = payload.wire_stats()
        return (
            f"GOAL:\n{goal.strip()}\n\n"
            f"DOCUMENT SHAPE (abstract concept relations):\n{rel_lines}\n\n"
            f"AVAILABLE PLACEHOLDERS (slot id, category):\n{slot_lines}\n\n"
            f"{attrs}"
            f"DOCUMENT STATS: {stats['cells']} cells, {stats['blocks']} blocks, "
            f"about {stats['chars']} characters (to the nearest {CHARS_QUANTUM}).\n\n"
            "Produce the outline now."
        )

    def _to_result(self, reply: CloudReply, payload: AbstractPayload, goal: str) -> PlanResult:
        if not reply.structured or not isinstance(reply.structured.get("sections"), list):
            raise PlannerError(
                f"planner returned no structured plan (stop_reason={reply.stop_reason!r})"
            )
        known = {sid for sid, _ in payload.slots}
        sections: list[Section] = []
        dropped_sections = clamped = unknown = 0
        returned = 0
        slots_seen: list[str] = []
        for i, item in enumerate(reply.structured["sections"]):
            if not isinstance(item, dict):
                dropped_sections += 1
                continue
            title = str(item.get("title", "")).strip()
            objective = str(item.get("objective", "")).strip()
            if not title or not objective:
                dropped_sections += 1
                continue
            try:
                budget = int(item.get("word_budget", 0))
            except (TypeError, ValueError, OverflowError):  # OverflowError: 1e400 is inf
                budget = 0
            b = min(max(budget, self.min_budget), self.max_budget)
            if b != budget:
                clamped += 1
            raw_slots = item.get("slot_ids") or []
            if isinstance(raw_slots, (int, float)):
                raw_slots = [raw_slots]          # a number (or true) for the array
            slots = tuple(s for s in raw_slots if isinstance(s, str))
            # An element that is not a string names no issued id and is never
            # resolved. Until 2026-10-27 it was dropped uncounted, so a plan made
            # only of such elements was drafted with no placeholders, and a
            # number given for the whole array raised a TypeError after the
            # request had crossed. Both now count as dropped references, so the
            # share of drops can only rise and such a plan fails closed below.
            other = [s for s in raw_slots if not isinstance(s, str)]
            slots_seen.extend((slots or tuple(str(s) for s in other))[:1])
            resolved = tuple(_canonical_slot(s, known) for s in slots)
            keep = tuple(s for s in resolved if s is not None)
            unknown += len(slots) - len(keep) + len(other)
            returned += len(slots) + len(other)
            sections.append(Section(f"s{len(sections) + 1}", title, objective, b, keep))
            if len(sections) >= self.max_sections:
                dropped_sections += max(0, len(reply.structured["sections"]) - i - 1)
                break
        if not sections:
            raise PlannerError("planner produced no usable sections")
        if returned and unknown == returned:
            # Fail closed. Every reference dropped means every section is
            # drafted with no placeholders, and the report carries none of the
            # values the system exists to carry -- while exiting 0. That has
            # happened twice through two different spellings; a log line did
            # not stop either.
            raise PlannerError(
                f"planner returned {returned} slot reference(s) and none matched an "
                f"issued id (first: {slots_seen[0]!r}); refusing to draft sections "
                "with no placeholders")
        outline = Outline(goal=goal, sections=tuple(sections))
        problems = outline.validate(known)
        if problems:  # pragma: no cover - by construction none should remain
            raise PlannerError("; ".join(problems))
        log.info("planned %d section(s), %d words; dropped %d unknown slot ref(s)",
                 len(sections), outline.total_words, unknown)
        return PlanResult(
            outline=outline,
            resolved_model=reply.model,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            dropped_unknown_slots=unknown,
            dropped_sections=dropped_sections,
            clamped_budgets=clamped,
            refs_returned=returned,
        )
