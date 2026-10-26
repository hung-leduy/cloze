"""The one artifact of C_user that is allowed to cross the boundary.

A live run made the boundary concrete. The masked document (entities swapped
for typed slots) still carries every non-entity phrase verbatim: column
headers, connective prose, boilerplate. The containment filter refused it,
correctly, because five consecutive words of the corpus are five consecutive
words of the corpus whether or not a name sits next to them. So the masked
text is a LOCAL artifact for the reintegrator, and what crosses is this:

* the concept relations over abstract types (the document's shape),
* the slot ids with their categories (so the cloud can refer to entities it
  will never see), and
* coarse statistics: the cell count, the block count and the character count
  rounded to the nearest 1,000 (below).

Never the originals, never the masked prose. `to_json` is the wire form; the
test suite proves the containment filter built over the source document does
not fire on it, which is the property the whole tier rests on.

G2: the character count is quantised
------------------------------------
The G2 invariance test (backend/tests/security/test_payload_invariance.py)
found one channel through which the payload and the planner prompt depended on
which referent holds which value: the exact character count. A value's
spelling has a length and the documents mention their projects unequally
often, so moving amounts one project along took corpus A from 3479 characters
to 3482, and swapping its two sites took it to 3476. Cells and blocks did not
move under any tested permutation; they count structure, which a permutation
of values does not touch.

So what crosses is `coarse_chars(n_chars)`: the count rounded to the nearest
1,000, half up, never below 1,000. `wire_stats` is the one place the crossing
statistics are computed; the payload JSON and the planner prompt both read
it. `n_chars` itself stays exact on this object, which is local: merging the
per-document payloads sums exact counts and the corpus total is rounded once,
not each document's count rounded and the roundings added.

The floor. Rounding sends every count under 500 to 0, and "0 characters" is
false for any corpus the pipeline runs on and invites an empty outline. So
every count under 1,500 reports 1,000: the floor merges the lowest two quanta
rather than adding a third, and discloses nothing the quantum does not.

The limit, stated rather than hidden: quantisation is not invariance. A
permutation that carries the exact count across a rounding boundary (3499 to
3500) still changes the value on the wire by 1,000, and the invariance test
constructs one such case. The G2 claim is therefore "invariant under the
tested permutations, with the character count quantised to 1,000; a change
across a quantum boundary remains visible". It is weakest for a corpus near a
boundary. Measured on the four evaluation corpora, as the pipeline counts
(sum of `len(d.text)`): A smoke-q3 3479 -> 3000, 21 below the 3500 boundary;
B portfolio-b 3576 -> 4000, 76 above it; C prose-c 3014 -> 3000, 486 below
3500; D offlex-d 3693 -> 4000, 193 above 3500.

R1: facts instead of value slots
-------------------------------
With `facts=True` the payload stops advertising MONEY, QUANTITY, DATE and
IDENTIFIER slots at all. Those values are reachable only as attributes of a
PERSON, ORG, PROJECT or LOCATION referent, written `⟦FACT:<hex8>.<ATTR>⟧` and
resolved locally. The cloud learns which referents exist, which it already
did, and which attributes *could* exist -- the same thirteen codes for every
referent category, always. `ATTRIBUTE_SCHEMA` is a module constant, so the
schema block is byte-identical for every corpus whatsoever, not merely for
two corpora that differ in values. (The design keyed it by the categories
present; that would add nothing the slot list does not already disclose, but
a constant needs no argument.) Which referent has which attribute is never on
the wire. That is a policy plus a test, not an unrepresentable format: the R4
ablation arm would need a per-referent field, and the paper must say so.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from privdeep.models.facts import ATTRIBUTE_CODES, REFERENT_CATEGORIES
from privdeep.tier1_local.ontology_extractor import Extraction
from privdeep.tier1_local.slot_masker import SLOT_RE, MaskResult

__all__ = ["ATTRIBUTE_SCHEMA", "CHARS_QUANTUM", "FACT_REF_FORMAT", "AbstractPayload",
           "ClosedVocabularyError", "assert_closed_vocabulary", "build_abstract_payload",
           "coarse_chars"]

# The character count crosses only in multiples of this; see the module docstring.
CHARS_QUANTUM = 1000


def coarse_chars(n: int) -> int:
    """`n` rounded to the nearest `CHARS_QUANTUM`, half up, with a floor of one quantum.

    Integer arithmetic, so 3499 -> 3000 and 3500 -> 4000 exactly, with no
    banker's rounding. Every n under 1500, including 0, gives 1000.
    """
    if n < 0:
        raise ValueError(f"a character count cannot be negative: {n}")
    return max(CHARS_QUANTUM, (n + CHARS_QUANTUM // 2) // CHARS_QUANTUM * CHARS_QUANTUM)

ATTRIBUTE_SCHEMA: tuple[tuple[str, tuple[str, ...]], ...] = tuple(
    (category, ATTRIBUTE_CODES) for category in REFERENT_CATEGORIES)
# A description of the format, not a token: `<` and `>` keep it from matching
# FACT_RE. The payload carries no fact reference; the only one the core writes is
# the drafter's constant example, whose hex is fixed, not derived from a referent.
FACT_REF_FORMAT = "⟦FACT:<referent hex8>.<ATTR>⟧"


class ClosedVocabularyError(ValueError):
    """A payload names an attribute or category outside the fixed vocabulary."""


@dataclass(frozen=True, slots=True)
class AbstractPayload:
    doc_id: str
    relations: tuple[tuple[str, str, str], ...]
    slots: tuple[tuple[str, str], ...]        # (slot_id, category); ids only
    n_cells: int
    n_blocks: int
    # Exact, and local: nothing may send it. The wire reads `wire_stats()`.
    n_chars: int
    # Empty unless built with facts=True, and omitted from the wire when empty,
    # so the BASELINE and R5 arms send exactly what they sent before R1.
    attribute_schema: tuple[tuple[str, tuple[str, ...]], ...] = ()
    fact_ref_format: str = ""

    def wire_stats(self) -> dict[str, int]:
        """The document statistics as they cross: the one place they are computed.

        The payload JSON and the planner prompt both read this, so neither can
        send the exact character count.
        """
        return {"cells": self.n_cells, "blocks": self.n_blocks,
                "chars": coarse_chars(self.n_chars)}

    def schema_json(self) -> str:
        return json.dumps({"attribute_schema": {c: list(a) for c, a in self.attribute_schema},
                           "fact_ref_format": self.fact_ref_format},
                          ensure_ascii=False, indent=2)

    def to_json(self) -> str:
        return json.dumps(
            {
                "doc_id": self.doc_id,
                "relations": [
                    {"subject_type": s, "predicate": p, "object_type": o}
                    for s, p, o in self.relations
                ],
                "slots": [{"id": sid, "category": cat} for sid, cat in self.slots],
                "stats": self.wire_stats(),
                **({"attribute_schema": {c: list(a) for c, a in self.attribute_schema},
                    "fact_ref_format": self.fact_ref_format} if self.attribute_schema else {}),
            },
            ensure_ascii=False,
            indent=2,
        )


def build_abstract_payload(
    doc_id: str, extraction: Extraction, mask: MaskResult,
    *, n_cells: int = 0, n_blocks: int = 0, n_chars: int = 0, facts: bool = False,
) -> AbstractPayload:
    # Slot ids come from the mapping table so only slots that were actually
    # placed are advertised; an entity the masker never found has no slot.
    seen: dict[str, str] = {}
    for _span, slot_id, _surface_ix in mask.replacements:
        if slot_id not in seen:
            m = SLOT_RE.fullmatch(slot_id)
            seen[slot_id] = m.group("category") if m else "UNKNOWN"
    if facts:
        seen = {sid: cat for sid, cat in seen.items() if cat in REFERENT_CATEGORIES}
    payload = AbstractPayload(
        doc_id=doc_id,
        relations=tuple(r.fields() for r in extraction.relations),
        slots=tuple(sorted(seen.items())),
        n_cells=n_cells, n_blocks=n_blocks, n_chars=n_chars,
        attribute_schema=ATTRIBUTE_SCHEMA if facts else (),
        fact_ref_format=FACT_REF_FORMAT if facts else "",
    )
    if facts:
        assert_closed_vocabulary(payload)
    return payload


def assert_closed_vocabulary(payload: AbstractPayload) -> None:
    """Membership, not substring: every code in the fixed tuple, every category a
    referent category, and no value-category slot advertised. Fails closed. A
    referee verifies the property by reading a thirteen-element tuple."""
    for category, codes in payload.attribute_schema:
        if category not in REFERENT_CATEGORIES:
            raise ClosedVocabularyError(f"schema names a non-referent category {category!r}")
        extra = [c for c in codes if c not in ATTRIBUTE_CODES]
        if extra:
            raise ClosedVocabularyError(f"schema names {len(extra)} code(s) outside the vocabulary")
    if payload.attribute_schema:
        stray = [cat for _, cat in payload.slots if cat not in REFERENT_CATEGORIES]
        if stray:
            raise ClosedVocabularyError(
                f"{len(stray)} value-category slot(s) advertised alongside facts")
