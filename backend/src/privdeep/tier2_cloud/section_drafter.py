"""Draft one section with the cloud, over slot ids and public evidence only.

The cloud writes prose. It refers to entities by slot id, copied verbatim,
because a slot id is the only handle it has; the reintegrator fills them in
locally later (Fix 2 in the scope doc governs how). It cites public evidence
by tag, `[W3]`, from the summaries it is given; the citation grounder checks
those tags against the evidence store afterwards.

Two things this module does with the reply before anyone else sees it:

* **Invented slot ids** (a placeholder the core never issued) are replaced by
  the literal `[unresolved reference]` and counted. Leaving them in would
  hand the reintegrator a token it cannot resolve; the reintegrator fails
  closed on exactly that, which is correct, but it should fail on drift, not
  on a case the drafter can already see. So the drafter cleans what it can
  see and reports what it cleaned.
* **Word budget** is reported, not enforced. A model that overshoots by a
  third has not done anything unsafe; the count goes into the run record and
  the pipeline decides.

Numbers are not checked here. A figure the cloud states without an evidence
tag is the citation grounder's problem (W5), and the system prompt tells the
model not to state figures it cannot tag. That instruction is a request, the
grounder is the mechanism.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass

from privdeep.models.facts import ATTRIBUTE_CODES, ATTRIBUTE_MEANINGS, FACT_RE
from privdeep.models.outline import Outline, Section
from privdeep.tier1_local.slot_masker import SLOT_RE
from privdeep.tier2_cloud.abstract_payload import AbstractPayload
from privdeep.tier2_cloud.cloud_client import REPORT_EFFORT, CloudClient

log = logging.getLogger(__name__)

__all__ = ["DraftResult", "Evidence", "SectionDrafter"]

_WORD_RE = re.compile(r"\S+")
_UNRESOLVED = "[unresolved reference]"

# The one complete fact reference the core itself writes: a constant example in
# the system prompt. A concrete example is what gets a model to spell references
# correctly. Its hex is fixed here, not derived from any referent, and a draft
# that copies it is scrubbed as invented unless that hex was actually issued.
FACT_EXAMPLE = "⟦FACT:a1b2c3d4.AUTHAMT⟧"

# R1. Used only when the payload carries an attribute schema, so the BASELINE and
# R5 arms send the system prompt they always sent.
_SYSTEM_FACTS = (
    "You are drafting one section of a structured research report for an analyst. You are "
    "given the section's objective, the report outline for context, an abstract description "
    "of a private document as concept relations, a list of typed placeholders (slot ids), the "
    "attributes each placeholder may have, and summaries of public evidence with tags. Rules, "
    "all of them strict:\n"
    "1. Refer to any person, organisation, project or place ONLY by its exact slot id, copied "
    "verbatim, e.g. ⟦SLOT:PROJECT_a1b2c3d4⟧. Never invent a name or place.\n"
    "2. Refer to any amount, date, quantity or reference code ONLY by a fact reference built "
    "from the stem listed with its placeholder, replacing <ATTR> with one listed attribute "
    f"code, e.g. {FACT_EXAMPLE}. Never write such a value yourself. Amounts are "
    "written with their currency, so do not add one.\n"
    "3. Reference only the attributes this section's objective needs; never list or "
    "enumerate attributes. Not every placeholder has every attribute, so write each sentence "
    "to read correctly even if a referenced value is missing. Never refer to these rules, to "
    "placeholders, or to missing values in the text itself.\n"
    "4. Put a space or a word between two references; never write them back to back.\n"
    "5. Use only the placeholders listed for this section. Do not create new ones.\n"
    "6. Cite public evidence by its tag in square brackets, e.g. [W2], immediately after the "
    "claim it supports. Do not state a numeric figure unless it is a fact reference or quoted "
    "from a tagged evidence summary.\n"
    "7. Write in a measured scholarly register. No preamble, no headings, no closing remarks; "
    "output the section body only.\n"
    "8. Aim for the word budget."
)


@dataclass(frozen=True, slots=True)
class Evidence:
    tag: str          # e.g. "W1"
    summary: str      # public text; never from C_user
    source_url: str = ""


@dataclass(frozen=True, slots=True)
class DraftResult:
    section_id: str
    text: str
    resolved_model: str
    input_tokens: int
    output_tokens: int
    word_count: int
    word_budget: int
    slots_used: tuple[str, ...]
    invented_slots: int
    citations_used: tuple[str, ...]

    @property
    def over_budget_ratio(self) -> float:
        return self.word_count / self.word_budget if self.word_budget else 0.0


_SYSTEM = (
    "You are drafting one section of a structured research report for an analyst. You are "
    "given the section's objective, the report outline for context, an abstract description "
    "of a private document as concept relations, a list of typed placeholders (slot ids), and "
    "summaries of public evidence with tags. Rules, all of them strict:\n"
    "1. Refer to any entity from the private document ONLY by its exact slot id, copied "
    "verbatim, e.g. ⟦SLOT:PROJECT_a1b2c3d4⟧. Never invent a name, place, date, or amount.\n"
    "2. Use only the slot ids listed for this section. Do not create new ones.\n"
    "3. Cite public evidence by its tag in square brackets, e.g. [W2], immediately after the "
    "claim it supports. Do not state a numeric figure unless it is quoted from a tagged "
    "evidence summary.\n"
    "4. Write in a measured scholarly register. No preamble, no headings, no closing remarks; "
    "output the section body only.\n"
    "5. Aim for the word budget."
)


class SectionDrafter:
    def __init__(self, client: CloudClient, *, max_tokens: int = 8192,
                 effort: str = REPORT_EFFORT) -> None:
        self.client = client
        self.max_tokens = max_tokens
        self.effort = effort

    async def draft(
        self,
        section: Section,
        outline: Outline,
        payload: AbstractPayload,
        evidence: Sequence[Evidence] = (),
    ) -> DraftResult:
        reply = await self.client.messages(
            [{"role": "user", "content": self._user_prompt(section, outline, payload, evidence)}],
            system=_SYSTEM_FACTS if payload.attribute_schema else _SYSTEM,
            max_tokens=self.max_tokens,
            effort=self.effort,
        )
        allowed = set(section.slot_ids)
        known = {sid for sid, _ in payload.slots}
        text, invented, used = self._scrub_slots(reply.text, allowed | known)
        if payload.attribute_schema:
            text, invented_facts, _facts = self._scrub_facts(text, allowed | known)
            invented += invented_facts
        cites = tuple(sorted(set(re.findall(r"\[(W\d+)\]", text))))
        wc = len(_WORD_RE.findall(text))
        if invented:
            log.warning("section %s: %d invented slot id(s) replaced", section.id, invented)
        return DraftResult(
            section_id=section.id,
            text=text,
            resolved_model=reply.model,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            word_count=wc,
            word_budget=section.word_budget,
            slots_used=used,
            invented_slots=invented,
            citations_used=cites,
        )

    @staticmethod
    def _user_prompt(section: Section, outline: Outline, payload: AbstractPayload,
                     evidence: Sequence[Evidence]) -> str:
        cat = dict(payload.slots)
        if payload.attribute_schema:
            # The stem is spelt out per referent so the model never has to cut
            # the hex out of a slot id -- the kind of spelling freedom that has
            # already dropped every reference twice. `<ATTR>` keeps the stem from
            # matching FACT_RE: the core puts no real fact reference on the wire.
            slot_lines = "\n".join(
                f"- {sid}  [{cat.get(sid, '?')}]  facts: ⟦FACT:{_hex(sid)}.<ATTR>⟧"
                for sid in section.slot_ids) or "- (none for this section)"
        else:
            slot_lines = "\n".join(f"- {sid}  [{cat.get(sid, '?')}]"
                                   for sid in section.slot_ids) or "- (none for this section)"
        rel_lines = "\n".join(f"- ({s}) --{p}--> ({o})" for s, p, o in payload.relations) \
            or "- (none)"
        ev_lines = "\n".join(f"[{e.tag}] {e.summary.strip()}" for e in evidence) \
            or "(no public evidence supplied; make no numeric claims)"
        outline_lines = "\n".join(
            f"{'>' if s.id == section.id else ' '} {s.id}: {s.title}" for s in outline.sections
        )
        return (
            f"REPORT GOAL:\n{outline.goal.strip()}\n\n"
            f"OUTLINE (this section marked with >):\n{outline_lines}\n\n"
            f"THIS SECTION: {section.title}\nOBJECTIVE: {section.objective}\n"
            f"WORD BUDGET: {section.word_budget}\n\n"
            f"DOCUMENT SHAPE (abstract concept relations):\n{rel_lines}\n\n"
            f"PLACEHOLDERS YOU MAY USE (exact slot id, category):\n{slot_lines}\n\n"
            f"{_attribute_block(payload)}"
            f"PUBLIC EVIDENCE:\n{ev_lines}\n\n"
            "Write the section body now."
        )

    @staticmethod
    def _scrub_facts(text: str, permitted_slots: set[str]) -> tuple[str, int, tuple[str, ...]]:
        """Replace fact references to unlisted referents or unknown codes."""
        hexes = {_hex(s) for s in permitted_slots}
        invented = 0
        used: list[str] = []

        def repl(m: re.Match[str]) -> str:
            nonlocal invented
            if m.group("hex") in hexes and m.group("attr") in ATTRIBUTE_CODES:
                if m.group(0) not in used:
                    used.append(m.group(0))
                return m.group(0)
            invented += 1
            return _UNRESOLVED

        return FACT_RE.sub(repl, text), invented, tuple(used)

    @staticmethod
    def _scrub_slots(text: str, permitted: set[str]) -> tuple[str, int, tuple[str, ...]]:
        invented = 0
        used: list[str] = []

        def repl(m: re.Match[str]) -> str:
            nonlocal invented
            sid = m.group(0)
            if sid in permitted:
                if sid not in used:
                    used.append(sid)
                return sid
            invented += 1
            return _UNRESOLVED

        return SLOT_RE.sub(repl, text), invented, tuple(used)


def _hex(slot_id: str) -> str:
    m = SLOT_RE.fullmatch(slot_id)
    return m.group("hex") if m else ""


def _attribute_block(payload: AbstractPayload) -> str:
    """The same text for every corpus: codes and meanings are constants."""
    if not payload.attribute_schema:
        return ""
    cats = ", ".join(c for c, _ in payload.attribute_schema)
    ordered = dict.fromkeys(a for _, attrs in payload.attribute_schema for a in attrs)
    codes = "\n".join(f"- {c}: {ATTRIBUTE_MEANINGS[c]}" for c in ordered)
    return (f"ATTRIBUTES (any placeholder of category {cats} may have these; "
            f"format {payload.fact_ref_format}):\n{codes}\n\n")
