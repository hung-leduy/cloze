"""The report plan the cloud produces and the core executes.

Flat by scope decision. The harness spec's DualGraph (an outline graph joined
to a knowledge graph with gap detection) was cut because it earns no page in
ten; what remains is the part the pipeline actually needs, a sequence of
sections each with an objective, a word budget, and the slot ids it should
refer to. Slot ids are the only handle the cloud has on entities: it never
sees a value, so a section that "discusses ⟦SLOT:PROJECT_a1b2c3d4⟧" is a
section the reintegrator will later fill.

`validate` is the boundary check: a plan that names a slot id the core never
issued is a plan that invented an entity, and it is dropped, not repaired.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ["Outline", "Section"]


@dataclass(frozen=True, slots=True)
class Section:
    id: str
    title: str
    objective: str
    word_budget: int
    slot_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Outline:
    goal: str
    sections: tuple[Section, ...]

    @property
    def total_words(self) -> int:
        return sum(s.word_budget for s in self.sections)

    def validate(self, known_slots: Iterable[str]) -> list[str]:
        """Problems, as strings. Empty list means the plan is executable."""
        known = set(known_slots)
        problems: list[str] = []
        if not self.sections:
            problems.append("outline has no sections")
        seen: set[str] = set()
        for s in self.sections:
            if s.id in seen:
                problems.append(f"duplicate section id {s.id!r}")
            seen.add(s.id)
            if not s.title.strip() or not s.objective.strip():
                problems.append(f"section {s.id!r} has an empty title or objective")
            if s.word_budget <= 0:
                problems.append(f"section {s.id!r} has a non-positive word budget")
            for sid in s.slot_ids:
                if sid not in known:
                    problems.append(f"section {s.id!r} references unknown slot {sid!r}")
        return problems

    def without_unknown_slots(self, known_slots: Iterable[str]) -> tuple[Outline, int]:
        """Copy with unknown slot ids removed; returns (outline, number dropped)."""
        known = set(known_slots)
        dropped = 0
        secs = []
        for s in self.sections:
            keep = tuple(x for x in s.slot_ids if x in known)
            dropped += len(s.slot_ids) - len(keep)
            secs.append(Section(s.id, s.title, s.objective, s.word_budget, keep))
        return Outline(self.goal, tuple(secs)), dropped
