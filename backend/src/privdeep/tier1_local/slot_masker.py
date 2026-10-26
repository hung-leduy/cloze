"""Typed-placeholder masking of named entities, and its exact inverse.

This is the W2 gate: ``restore(mask(doc, entities)) == doc.text`` character for
character, for every document the loaders produce. Everything below is in
service of that equality and of keeping the mapping inside the partition.

What crosses the boundary and what does not
-------------------------------------------
The cloud tier sees ``masked_text``: the document with every claimed mention of
an entity replaced by a placeholder ``⟦SLOT:<CATEGORY>_<hex8>⟧``. It never sees
the ``LocalMappingTable`` that binds a placeholder back to its value; that table
is session-scoped, in-memory, and its ``repr`` prints counts only so that a log
line or a traceback cannot carry C_user out of the trusted zone.

The placeholder carries the category on purpose. The cloud drafter needs to know
that ``⟦SLOT:PERSON_…⟧`` takes a personal pronoun and ``⟦SLOT:MONEY_…⟧`` takes a
currency verb, or its prose is unusable. This is pseudonymisation, not
anonymisation: the category and the co-reference structure (which mentions are
the same entity) are disclosed by construction. The scope document says so and
the paper must too.

One slot per referent, not per spelling (R5)
---------------------------------------------
``hex8 = HMAC-SHA256(session_salt, category ‖ NUL ‖ canonical_key(category, text))``.

The key, not the text. Keying on the raw surface form produced 19 MONEY slots
for 8 amounts on the first live run, because ``250,000``, ``250,000.00`` and
``250000`` are three different strings; the cloud received three unrelated
placeholders for one figure and wrote all 15 of that report's
self-contradictions. :mod:`privdeep.tier1_local.normalise` supplies the key; it
merges spellings and never merges referents, and the asymmetry is argued there.

A referent therefore has *many* surfaces, and two questions now have two
answers:

* :meth:`LocalMappingTable.surface` — the exact spelling at one occurrence.
  This is what ``restore`` puts back, and why the gate stays character-exact.
* :meth:`LocalMappingTable.original` — the canonical rendering, one spelling
  chosen from those observed. This is what *reintegration* writes into the
  report, so the prose does not alternate spellings drawn from different source
  documents.

Why the id is a keyed hash and not a counter or a UUID
------------------------------------------------------
* *Deterministic within a session.* Every mention of the same referent gets the
  same placeholder, in this document and in the next one the session uploads.
  The cloud can only write "⟦SLOT:PROJECT_…⟧ was cancelled after ⟦SLOT:PROJECT_…⟧
  slipped" coherently if the two placeholders are the same string when the two
  projects are the same project. A counter or UUID assigned at first sight gives
  that within one ``mask`` call but not across calls.
* *Unlinkable across sessions.* The salt is fresh per session, so an adversary
  who captures egress from two sessions cannot tell whether
  ``⟦SLOT:PERSON_1a2b3c4d⟧`` in one is the person behind ``⟦SLOT:PERSON_9f8e7d6c⟧``
  in the other. An unsalted hash would also let the adversary confirm a guess by
  hashing candidate names; the HMAC removes that oracle.

  R5 sharpens what a *repeated* session discloses, and the cost is real rather
  than zero: per-category cardinality stops being "how many spellings happened
  to appear" (noisy, salt-dependent) and becomes "how many distinct referents
  exist" (stable). A stable cardinality vector is a better cross-session
  fingerprint. That is a threat-model entry, not a footnote.

**The collision predicate compares canonical keys, not entities.** Comparing
``Entity`` — whose equality includes its text — would make the first successful
R5 merge look like a collision: ``250,000`` and ``250,000.00`` share an id
because they *are* one referent. ``pipeline.py`` re-salts once and raises on the
second failure, so that mistake would not corrupt a report; it would abort every
run over any document that spells an amount two ways, which is every document.

Eight hex digits is 32 bits. Two different referents in the same category
collide with probability about ``n² / 2³³``: roughly one in ten thousand at
``n = 1000``. A collision would make ``restore`` write the wrong value,
silently, so the table refuses it with :class:`SlotCollisionError` rather than
overwrite. The caller's remedy is a new session salt.

Overlap policy
--------------
Entities are matched exactly and case-sensitively at every occurrence via
:meth:`Document.find_all`; no word boundary is enforced, so this module trusts
the extractor's entity list. Entities are processed longest text first, and a
span that overlaps an already claimed span is skipped. Hence "Project Zephyr"
wins over "Zephyr" where they coincide and "Zephyr" is still masked where it
stands alone. Among equal lengths, caller order decides. Every offset used is an
offset into the original ``doc.text``; the masked string is assembled from the
untouched gaps and the placeholders in one pass, which is the same result as
right-to-left in-place substitution and never has to re-derive an offset.

Why ``restore`` is exact, stated so a referee can check it
----------------------------------------------------------
1. ``mask`` refuses a document that already contains a slot-shaped string, so
   every :data:`SLOT_RE` match in ``masked_text`` is one this module wrote.
2. A placeholder is delimited by ``⟦`` and ``⟧`` and :data:`SLOT_RE` requires
   both, with exactly eight hex digits before the closing bracket, so a match can
   neither start inside a placeholder nor run across its edge into the text.
3. Claimed spans are pairwise disjoint and each was verified by ``find_all`` to
   contain exactly ``entity.text``.
4. Distinct referents get distinct placeholders (or the table raises).
5. ``replacements`` is sorted by span start and ``masked_text`` is assembled in
   that same single left-to-right pass, so the k-th :data:`SLOT_RE` match in
   ``masked_text`` is the k-th entry of ``replacements``. This is what makes a
   per-occurrence surface recoverable at all: under R5 the placeholder names the
   referent, and only the position says which of its spellings stood there.

Together these mean substituting each placeholder with the surface recorded for
its position restores each claimed span to the text it held, and the gaps were
never touched. Because of (5), ``restore`` takes the whole :class:`MaskResult`
rather than a bare string and table — there is nowhere else for the positional
information to live. A placeholder with no table entry raises ``KeyError``; it is
never left in place, because a dangling placeholder in a rendered report is the
Fix 2 failure mode.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from bisect import bisect_right
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from privdeep.models.document import SLOT_CATEGORIES, Document, Span
from privdeep.tier1_local.normalise import canonical_key, canonical_rendering

__all__ = [
    "SLOT_RE",
    "Entity",
    "LocalMappingTable",
    "MaskResult",
    "SlotCollisionError",
    "SlotMasker",
]

# U+27E6 / U+27E7, the mathematical white square brackets. Chosen because they
# do not occur in business prose or spreadsheet cells, which is what makes rule
# 1 of the exactness argument cheap to enforce.
_OPEN = "⟦"
_CLOSE = "⟧"
_PREFIX = f"{_OPEN}SLOT:"
_HEX_LEN = 8

# The category group accepts any uppercase run rather than only the taxonomy, so
# that a cloud-invented placeholder such as ⟦SLOT:PERSONS_1a2b3c4d⟧ is still
# recognised as slot-shaped and fails closed in `restore` and in the
# reintegrator, instead of passing through as literal text. Consumers that need
# a valid category check `m.group("category") in SLOT_CATEGORIES` themselves.
SLOT_RE: re.Pattern[str] = re.compile(
    rf"{_OPEN}SLOT:(?P<category>[A-Z]+)_(?P<hex>[0-9a-f]{{{_HEX_LEN}}}){_CLOSE}"
)


class SlotCollisionError(RuntimeError):
    """Two different referents hashed to the same slot id under this session's salt."""


@dataclass(frozen=True, slots=True)
class Entity:
    """One entity the extractor wants masked: exact surface text plus its category.

    ``text`` is excluded from ``repr`` for the same reason the table's is: an
    ``Entity`` in a log line is C_user in a log line.
    """

    text: str = field(repr=False)
    category: str

    def __post_init__(self) -> None:
        if self.category not in SLOT_CATEGORIES:
            raise ValueError(
                f"unknown slot category {self.category!r}; expected one of {SLOT_CATEGORIES}"
            )
        if not self.text:
            raise ValueError("entity text must be non-empty")


class _Referent:
    """One real-world thing, and every spelling of it this session has seen."""

    __slots__ = ("category", "key", "surfaces")

    def __init__(self, category: str, key: str) -> None:
        self.category = category
        self.key = key
        # Surface -> occurrence count, in first-seen order. Insertion order is
        # load-bearing: `canonical_rendering` breaks its final tie on it.
        self.surfaces: dict[str, int] = {}

    def observe(self, text: str) -> int:
        """Record one occurrence of a spelling; return its stable index."""
        if text not in self.surfaces:
            self.surfaces[text] = 0
        self.surfaces[text] += 1
        return list(self.surfaces).index(text)

    def at(self, index: int) -> str:
        try:
            return list(self.surfaces)[index]
        except IndexError as exc:
            raise KeyError(f"surface index {index} out of range for this referent") from exc


class LocalMappingTable:
    """Session-scoped, in-memory map from slot id to the referent it stands for.

    There is deliberately no serialisation method. The table is the one object
    in the system that holds C_user next to the identifiers the cloud has seen;
    it lives and dies with the session, inside the partition.
    """

    __slots__ = ("_salt", "_by_slot", "_normalise")

    def __init__(self, session_salt: bytes, *, normalise: bool = True) -> None:
        if not session_salt:
            raise ValueError("session_salt must be non-empty; an unsalted id is a guessing oracle")
        self._salt = session_salt
        self._by_slot: dict[str, _Referent] = {}
        # `normalise=False` keys on the raw surface text, which is what the
        # system did before R5. It exists so the BASELINE arm can be produced
        # from the same code path as the R5 arm: an arm that has to be recovered
        # by checking out an old commit is an arm nobody re-runs, and a
        # comparison against a differently-built binary measures the build.
        self._normalise = normalise

    def _slot_id(self, category: str, key: str) -> str:
        msg = f"{category}\x00{key}".encode()
        digest = hmac.new(self._salt, msg, hashlib.sha256).hexdigest()
        return f"{_PREFIX}{category}_{digest[:_HEX_LEN]}{_CLOSE}"

    def register(self, entity: Entity) -> tuple[str, int]:
        """Bind one occurrence: return its slot id and its surface index.

        Raises :class:`SlotCollisionError` if a *different referent* already
        holds this id. The predicate is the canonical key, not the entity: two
        spellings of one amount share an id by design, and treating that as a
        collision would abort every run over a document that writes an amount
        two ways.
        """
        key = canonical_key(entity.category, entity.text) if self._normalise else entity.text
        slot = self._slot_id(entity.category, key)
        held = self._by_slot.get(slot)
        if held is None:
            held = self._by_slot[slot] = _Referent(entity.category, key)
        elif held.category != entity.category or held.key != key:
            raise SlotCollisionError(
                f"slot id {slot} is already bound to a different {held.category} referent; "
                "re-mask under a fresh session salt"
            )
        return slot, held.observe(entity.text)

    def slot_for(self, entity: Entity) -> str:
        """The entity's slot id, registering it on first sight."""
        return self.register(entity)[0]

    def surface(self, slot_id: str, index: int) -> str:
        """The exact spelling recorded at one occurrence. What ``restore`` writes."""
        return self._by_slot[slot_id].at(index)

    def original(self, slot_id: str) -> str:
        """The canonical rendering: one spelling, chosen from those observed.

        What *reintegration* writes into the report, so the prose is internally
        consistent rather than alternating spellings drawn from different source
        documents. ``KeyError`` if the slot is unknown.
        """
        return canonical_rendering(self._by_slot[slot_id].surfaces)

    def surfaces(self, slot_id: str) -> tuple[str, ...]:
        """Every spelling seen for this referent, in first-seen order."""
        return tuple(self._by_slot[slot_id].surfaces)

    def fragmentation(self) -> dict[str, int]:
        """Per-category count of referents holding more than one spelling.

        R5's benefit, and the residue of its refusal to merge aliases, are both
        visible here. Reported rather than assumed.
        """
        out: dict[str, int] = {}
        for r in self._by_slot.values():
            if len(r.surfaces) > 1:
                out[r.category] = out.get(r.category, 0) + 1
        return out

    def __len__(self) -> int:
        return len(self._by_slot)

    def __contains__(self, slot_id: object) -> bool:
        return slot_id in self._by_slot

    def __iter__(self) -> Iterator[str]:
        """Slot ids only, in registration order. Never the values."""
        return iter(self._by_slot)

    def __repr__(self) -> str:
        counts: dict[str, int] = {}
        for r in self._by_slot.values():
            counts[r.category] = counts.get(r.category, 0) + 1
        per_cat = ", ".join(f"{c}={counts[c]}" for c in SLOT_CATEGORIES if c in counts)
        return f"LocalMappingTable(slots={len(self._by_slot)}, {per_cat or 'empty'})"


@dataclass(frozen=True)
class MaskResult:
    """Outcome of one ``mask`` call.

    ``replacements`` lists ``(span in doc.text, slot id, surface index)`` in
    ascending text order, one entry per claimed occurrence. The surface index is
    what makes ``restore`` exact under R5: the placeholder names the referent,
    and only the position records which of that referent's spellings stood
    there. ``unmatched`` lists the entities that claimed no span at all: absent
    from the text, or present only inside a longer entity's span. Neither
    appears in the table.
    """

    masked_text: str
    table: LocalMappingTable
    replacements: list[tuple[Span, str, int]]
    unmatched: list[Entity]


class SlotMasker:
    """Replaces entity mentions with typed placeholders and puts them back."""

    def __init__(self, session_salt: bytes, *, normalise: bool = True) -> None:
        if not session_salt:
            raise ValueError("session_salt must be non-empty")
        self._salt = session_salt
        self._normalise = normalise

    def mask(self, doc: Document, entities: Sequence[Entity]) -> MaskResult:
        pre = SLOT_RE.search(doc.text)
        if pre is not None:
            raise ValueError(
                f"document {doc.doc_id!r} already contains a slot-shaped string at "
                f"offset {pre.start()}; restore could not tell it from a placeholder"
            )

        table = LocalMappingTable(self._salt, normalise=self._normalise)
        # Dedupe on (text, category) but keep first-seen order: it is the
        # tie-break among equal-length entities, and it should be the caller's.
        ordered = sorted(dict.fromkeys(entities), key=lambda e: len(e.text), reverse=True)

        claimed: list[Span] = []  # pairwise disjoint, sorted by start
        starts: list[int] = []  # claimed[i].start, for bisect
        found: list[tuple[Span, Entity]] = []
        unmatched: list[Entity] = []

        for entity in ordered:
            took_any = False
            for span in doc.find_all(entity.text):
                i = bisect_right(starts, span.start)
                if i > 0 and claimed[i - 1].end > span.start:
                    continue  # overlaps the last claimed span starting at or before us
                if i < len(claimed) and claimed[i].start < span.end:
                    continue  # overlaps the first claimed span starting after us
                claimed.insert(i, span)
                starts.insert(i, span.start)
                found.append((span, entity))
                took_any = True
            if not took_any:
                unmatched.append(entity)

        # Register in text order, so a referent's first-seen surface is the one
        # appearing first in the document rather than the one whose entity
        # happened to be longest. `canonical_rendering` breaks its final tie on
        # that order, so this is what makes the chosen spelling reproducible.
        found.sort(key=lambda r: r[0].start)
        replacements: list[tuple[Span, str, int]] = [
            (span, *table.register(entity)) for span, entity in found
        ]

        pieces: list[str] = []
        cursor = 0
        for span, slot, _ix in replacements:
            pieces.append(doc.text[cursor : span.start])
            pieces.append(slot)
            cursor = span.end
        pieces.append(doc.text[cursor:])

        return MaskResult(
            masked_text="".join(pieces),
            table=table,
            replacements=replacements,
            unmatched=unmatched,
        )

    def restore(self, result: MaskResult) -> str:
        """Substitute every placeholder with the exact surface it replaced.

        Takes the whole :class:`MaskResult` because the surface index lives in
        ``replacements`` and nowhere else; see rule 5 of the exactness argument.
        A placeholder beyond what ``mask`` recorded, or one whose id the table
        does not hold, raises ``KeyError`` rather than being left in place.
        """
        out: list[str] = []
        cursor = 0
        recorded = result.replacements
        for k, m in enumerate(SLOT_RE.finditer(result.masked_text)):
            slot = m.group(0)
            if k < len(recorded) and recorded[k][1] == slot:
                text = result.table.surface(slot, recorded[k][2])
            else:
                # Not one this mask call wrote at this position: a tampered or
                # concatenated string. Fail closed through the table.
                text = result.table.original(slot)
            out.append(result.masked_text[cursor : m.start()])
            out.append(text)
            cursor = m.end()
        out.append(result.masked_text[cursor:])
        return "".join(out)
