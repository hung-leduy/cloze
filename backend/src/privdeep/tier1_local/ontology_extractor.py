"""Abstract the private document into typed entities and concept relations.

What this stage produces, and what it does not claim
----------------------------------------------------
Two outputs from one local SLM pass over C_user:

* **Entities**: verbatim strings with a category from `SLOT_CATEGORIES`. These
  feed the slot masker, which replaces every occurrence with a typed slot.
* **Relations**: `(subject_type, predicate, object_type)` triples over abstract
  concept types, meant to carry the document's *shape* to the cloud planner
  without carrying its surface content.

The harness spec called this output "non-invertible". It is not, and the paper
must not say so. The relational skeleton preserves structure by construction,
and typed slots preserve entity cardinality and co-occurrence. What this stage
actually delivers is pseudonymisation plus abstraction, with one mechanical
guarantee attached: **no entity string extracted from any document of the
corpus appears anywhere in any document's relations**. That guarantee is the W2
gate ("zero named entities in the ontology") and it is checked by code, not by
prompt.

The W2 gate drops and counts
----------------------------
`extract` drops every relation any of whose three fields contains,
case-insensitively, an entity string of two or more characters extracted from
the same document, and counts it in `relations_dropped_leak`. The relation is
never returned, so it is never masked, saved or sent; the run continues. The
rule is the substring match `assert_no_entity_leak` has always used, so it is
blunt on purpose: on corpus D (EXP3 pilot, 2026-09-27) qwen3 typed the common
phrase "recovery plan" as a PROJECT entity, and the relation
("PERSON", "will present a recovery plan", "PROJECT") matched it. Until that
date the gate raised `OntologyLeak` instead, and one such relation ended the
whole run; every arm reuses one extraction per corpus, so it lost the corpus.
A false positive now costs one relation, which was the design intent.

The gate is corpus-wide
-----------------------
`extract` sees one document, so it can only check that document's relations
against that document's entities. The payload that crosses merges every
document's relations, and a relation of document A can carry a string the
extractor found only in document B: in the EXP3 pilot on corpus C (2026-09-27)
the predicate "has authority" crossed while "authority" had been extracted, as
an ORG, from another document. So once every document has been extracted, the
caller runs `drop_corpus_leaking_relations` over all of them: the same rule
against the union of every document's entity strings. It subsumes the
per-document pass (a document's own strings are in the union); the
per-document pass stays in `extract` so that `extract` alone never returns a
relation carrying its own document's strings. A relation the corpus pass drops
is counted in its own document's `relations_dropped_leak`, so the counters stay
per document and a relation is counted once. `run_pipeline` and
`probe_extract.extract_corpus` run it before anything is masked, saved or sent.

A document all of whose relations are dropped contributes no relation to the
payload. It still contributes its slots and its statistics, and the planner
prompt reads "- (none)" if no document has a relation left. That is not an
error: the drop count is in the manifest (`extraction.relations_dropped_leak`,
and `extraction.documents_all_relations_dropped`), and
`scripts/run_evaluation.py` and `scripts/observation_table.py` report it per
run as an outcome, never as a health failure.

The strict forms still raise. `assert_no_entity_leak` (one document) runs as a
postcondition at the end of `extract`, where it cannot fire.
`assert_no_corpus_leak` (the corpus) runs on the reuse path
(`extraction_io.load_extractions`), where a saved relation that carries any
document's entity string means the file predates the rule or was altered, and
the run is refused rather than repaired; `run_pipeline` also runs it as a
postcondition of the corpus pass.

Two lessons from a sibling project, applied here
------------------------------------------------
1. Never trust model-reported offsets. The SLM returns entity *strings*; every
   one is re-located in the document by exact match (`Document.find_all`), and
   a string that does not occur verbatim is dropped and counted. The masker
   then operates only on spans the document itself confirmed.
2. The model is untrusted input. A category outside the taxonomy, malformed
   JSON, or a relation that smuggles a name through are all handled as data
   quality events with counters, never as exceptions that take the pipeline
   down. That now includes the leak check on fresh output (above): the
   offending relation is dropped and counted, never sent.

Context budget
--------------
`num_ctx=8192` on the local model (see slm_client). Documents are chunked by
characters with overlap; entities are merged by (text, category) and relations
concatenated. Chunking can split an entity across a boundary; the overlap makes
that rare, not impossible, and the miss is on the recall side. A missed entity
gets no slot; if the SLM writes it into a relation field the W2 gate cannot see
it, and the shingle filter only within five or more corpus words (THREAT_MODEL §5).
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field

from privdeep.models.document import SLOT_CATEGORIES, Document
from privdeep.tier1_local.slm_client import AsyncSLMClient
from privdeep.tier1_local.slot_masker import Entity

log = logging.getLogger(__name__)

__all__ = [
    "ConceptRelation",
    "Extraction",
    "OntologyExtractor",
    "OntologyLeak",
    "assert_no_corpus_leak",
    "assert_no_entity_leak",
    "drop_corpus_leaking_relations",
    "drop_leaking_relations",
]


class OntologyLeak(RuntimeError):
    """A relation contains an entity string. Raised by the strict gate, which
    now guards the reuse path; fresh output is filtered instead."""


@dataclass(frozen=True, slots=True)
class ConceptRelation:
    subject_type: str
    predicate: str
    object_type: str

    def fields(self) -> tuple[str, str, str]:
        return (self.subject_type, self.predicate, self.object_type)


@dataclass(slots=True)
class Extraction:
    entities: list[Entity]
    relations: list[ConceptRelation]
    # Data-quality counters. Reported in the audit manifest, never hidden.
    dropped_not_in_text: int = 0
    dropped_bad_category: int = 0
    dropped_malformed: int = 0
    dropped_category_conflict: int = 0
    # Relations of this document the W2 gate dropped because a field contained
    # an entity string extracted from this document (in `extract`) or from any
    # document of the corpus (in `drop_corpus_leaking_relations`). A count
    # only: neither the entity nor the relation is kept anywhere.
    relations_dropped_leak: int = 0
    chunks: int = 1
    raw_replies: list[str] = field(default_factory=list)

    def counters(self) -> dict[str, int]:
        """What the run manifest sums per document: counts, never content."""
        return {
            "dropped_not_in_text": self.dropped_not_in_text,
            "dropped_bad_category": self.dropped_bad_category,
            "dropped_malformed": self.dropped_malformed,
            "dropped_category_conflict": self.dropped_category_conflict,
            "relations_dropped_leak": self.relations_dropped_leak,
            "entities": len(self.entities),
            "relations": len(self.relations),
            # A document the W2 gate left with no relation at all.
            "documents_all_relations_dropped":
                int(self.relations_dropped_leak > 0 and not self.relations),
        }


_SYSTEM = (
    "You are a strict information-extraction component inside a privacy system. "
    "You will be given a private document. Return ONLY a JSON object, no prose, "
    "no markdown fences, with exactly two keys:\n"
    '  "entities": a list of {"text": <exact verbatim substring>, "category": <one of '
    + ", ".join(SLOT_CATEGORIES)
    + ">}\n"
    '  "relations": a list of {"subject_type": <ABSTRACT_TYPE>, "predicate": <verb phrase>, '
    '"object_type": <ABSTRACT_TYPE>}\n'
    "Rules:\n"
    "- entity.text must be copied character-for-character from the document.\n"
    "- relations describe the document's structure using abstract concept types only "
    "(for example ORGANISATION, INITIATIVE, FINANCIAL_METRIC, TIME_PERIOD, DECISION). "
    "A relation must NEVER contain a person's name, an organisation's name, a place, a "
    "date, an amount, or any other entity text. Use the type, never the instance.\n"
    "- If unsure whether a string is an entity, include it as an entity; recall matters "
    "more than precision here."
)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def _strip_fence(s: str) -> str:
    m = _FENCE_RE.match(s)
    return m.group(1) if m else s.strip()


def _chunks(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]
    out, i = [], 0
    step = max(1, size - overlap)
    while i < len(text):
        out.append(text[i : i + size])
        if i + size >= len(text):
            break
        i += step
    return out


def _locate(doc: Document, text: str) -> str | None:
    """Return the surface form that actually occurs in doc.text, or None.

    The model may emit NFC where the file holds NFD (Vietnamese diacritics are
    the common case) or the reverse. Offsets are code points, so the two forms
    are different strings to find_all. Try the text as given, then both
    normal forms; return whichever the document confirms.
    """
    for cand in (text, unicodedata.normalize("NFC", text), unicodedata.normalize("NFD", text)):
        if doc.find_all(cand):
            return cand
    return None


_FIELD_NAMES = ("subject_type", "predicate", "object_type")


def _needles(entities: Sequence[Entity]) -> list[tuple[str, Entity]]:
    return [(e.text.casefold(), e) for e in entities if len(e.text) >= 2]


def _leak(needles: Sequence[tuple[str, Entity]], r: ConceptRelation
          ) -> tuple[str, Entity] | None:
    """The first (field name, entity) whose casefolded text is a substring of
    that casefolded field, or None. The one matching rule of the W2 gate."""
    for name, fld in zip(_FIELD_NAMES, r.fields(), strict=True):
        f = fld.casefold()
        for needle, e in needles:
            if needle in f:
                return name, e
    return None


def drop_leaking_relations(entities: Sequence[Entity], relations: Sequence[ConceptRelation]
                           ) -> tuple[list[ConceptRelation], int]:
    """The W2 gate on fresh output: the relations that pass, and how many did not.

    Same rule as `assert_no_entity_leak`: a relation is dropped when any of its
    fields contains, case-insensitively, an entity string of two or more
    characters. `entities` is one document's here, which is what `extract`
    passes; `drop_corpus_leaking_relations` applies the same rule against the
    whole corpus's entities and must run after it. Each drop is logged
    with the entity's category and the field name only; the entity and the
    relation text are not logged, returned or counted by content.
    """
    needles = _needles(entities)
    kept: list[ConceptRelation] = []
    dropped = 0
    for r in relations:
        hit = _leak(needles, r)
        if hit is None:
            kept.append(r)
            continue
        dropped += 1
        log.warning("W2 gate: relation dropped, its %s field contains an extracted %s entity",
                    hit[0], hit[1].category)
    return kept, dropped


def assert_no_entity_leak(entities: Sequence[Entity], relations: Sequence[ConceptRelation]) -> None:
    """The strict W2 gate. Case-insensitive substring check of every entity against every field.

    Raises OntologyLeak naming the first offending pair; the message quotes the
    entity and the relation, so a caller that records it keeps only the
    trailing "(CATEGORY)". Nothing in `run_pipeline` catches it, so a raise
    ends the run before any prompt reaches the cloud. It guards the reuse path
    (`extraction_io.load_extractions`): the extractor drops a leaking relation
    (`drop_leaking_relations`) and never saves one, so a saved relation that
    fails here comes from an older or altered file and is refused, not
    repaired. `extract` also runs it on its own kept relations as a
    postcondition. The reuse path now runs `assert_no_corpus_leak`, which
    subsumes this check over the whole corpus.
    """
    needles = _needles(entities)
    for r in relations:
        hit = _leak(needles, r)
        if hit is not None:
            e = hit[1]
            raise OntologyLeak(
                f"relation {r.fields()!r} contains entity {e.text!r} ({e.category})"
            )


def _corpus_needles(extractions: Sequence[Extraction]) -> list[tuple[str, Entity]]:
    """The union of every document's needles, one per casefolded string (the
    first document's entity names the category a hit is reported under)."""
    seen: dict[str, Entity] = {}
    for ex in extractions:
        for needle, e in _needles(ex.entities):
            seen.setdefault(needle, e)
    return list(seen.items())


def drop_corpus_leaking_relations(extractions: Sequence[Extraction]) -> int:
    """The W2 gate over the whole corpus, on fresh output. Returns how many it dropped.

    Run once every document has been extracted, over all of them. A relation
    of any document is dropped when any of its fields contains,
    case-insensitively, an entity string of two or more characters extracted
    from *any* document: `drop_leaking_relations`'s rule against the union of
    the corpus's entities. That subsumes the per-document pass in `extract`,
    which is kept so that `extract` alone is safe for its own document; after
    it, this pass drops only relations that carry another document's string.
    Each extraction is changed in place: its relations are filtered and its
    `relations_dropped_leak` grows by its own drops, so the counters and
    `documents_all_relations_dropped` stay per document and a relation is
    counted once. Each drop is logged with the field name and the category
    only.
    """
    needles = _corpus_needles(extractions)
    total = 0
    for ex in extractions:
        kept: list[ConceptRelation] = []
        for r in ex.relations:
            hit = _leak(needles, r)
            if hit is None:
                kept.append(r)
                continue
            ex.relations_dropped_leak += 1
            total += 1
            log.warning("W2 gate (corpus): relation dropped, its %s field contains an "
                        "extracted %s entity", hit[0], hit[1].category)
        ex.relations = kept
    return total


def assert_no_corpus_leak(extractions: Sequence[Extraction]) -> None:
    """The strict W2 gate over the whole corpus. Raises OntologyLeak on the first hit.

    Same rule as `drop_corpus_leaking_relations`: no field of any document's
    relation may contain, case-insensitively, an entity string of two or more
    characters extracted from any document. It subsumes `assert_no_entity_leak`
    applied to each document. The message names the document by its position,
    the field, whether the entity came from the same or another document, and
    the category; unlike `assert_no_entity_leak` it quotes neither the entity
    nor the relation, and it ends in "(CATEGORY)" as that one does. Guards the
    reuse path (`extraction_io.load_extractions`) and is `run_pipeline`'s
    postcondition of the corpus pass.
    """
    needles = _corpus_needles(extractions)
    for i, ex in enumerate(extractions):
        own = {needle: e.category for needle, e in _needles(ex.entities)}
        for r in ex.relations:
            hit = _leak(needles, r)
            if hit is not None:
                name, e = hit
                needle = e.text.casefold()
                where = "the same" if needle in own else "another"
                raise OntologyLeak(
                    f"document {i + 1} of {len(extractions)}: a relation's {name} field "
                    f"contains an entity string extracted from {where} document "
                    f"({own.get(needle, e.category)})"
                )


class OntologyExtractor:
    def __init__(
        self,
        client: AsyncSLMClient,
        *,
        chunk_chars: int = 12_000,   # ~3k tokens of prose; leaves room for the reply in 8192
        overlap_chars: int = 600,
        max_reply_tokens: int = 2048,
        canary_context: str = "",
    ) -> None:
        self.client = client
        self.chunk_chars = chunk_chars
        self.overlap_chars = overlap_chars
        self.max_reply_tokens = max_reply_tokens
        # `CanaryInjector.context_block()`. This is the only place the tokens
        # are planted: the invariant is that a canary on the wire proves prompt
        # context escaped, and that proof needs the tokens to be in a prompt.
        # An empty string means no canary is planted and the gateway's matcher
        # has nothing to find, which is a silently weaker system, so callers
        # that hold an injector should pass its block.
        self.canary_context = canary_context

    async def extract(self, doc: Document) -> Extraction:
        chunks = _chunks(doc.text, self.chunk_chars, self.overlap_chars)
        ex = Extraction(entities=[], relations=[], chunks=len(chunks))
        seen_text: set[str] = set()

        for idx, chunk in enumerate(chunks):
            payload = await self._ask(chunk, idx)
            ex.raw_replies.append(payload.raw)
            if payload.parsed is None:
                ex.dropped_malformed += 1
                continue
            ents, rels = payload.parsed
            for item in ents:
                text = str(item.get("text", "")).strip()
                cat = str(item.get("category", "")).strip().upper()
                if not text:
                    continue
                if cat not in SLOT_CATEGORIES:
                    ex.dropped_bad_category += 1
                    continue
                located = _locate(doc, text)
                if located is None:
                    ex.dropped_not_in_text += 1
                    continue
                if located in seen_text:
                    # Same surface text under a second category: first wins,
                    # because the masker can bind one span to one slot only.
                    ex.dropped_category_conflict += 1
                    continue
                seen_text.add(located)
                ex.entities.append(Entity(text=located, category=cat))
            for item in rels:
                try:
                    ex.relations.append(
                        ConceptRelation(
                            subject_type=str(item["subject_type"]).strip(),
                            predicate=str(item["predicate"]).strip(),
                            object_type=str(item["object_type"]).strip(),
                        )
                    )
                except (KeyError, TypeError):
                    ex.dropped_malformed += 1

        ex.relations, ex.relations_dropped_leak = drop_leaking_relations(
            ex.entities, ex.relations)
        assert_no_entity_leak(ex.entities, ex.relations)  # postcondition; cannot fire
        return ex

    @dataclass(slots=True)
    class _Reply:
        raw: str
        parsed: tuple[list[dict], list[dict]] | None

    async def _ask(self, chunk: str, idx: int) -> _Reply:
        system = _SYSTEM
        if self.canary_context:
            system = f"{system}\n\n{self.canary_context}"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"DOCUMENT (part {idx + 1}):\n\n{chunk}"},
        ]
        reply = await self.client.chat(messages, think=False, max_tokens=self.max_reply_tokens)
        parsed = self._parse(reply.content)
        if parsed is None:
            # One nudge. The model is fast; a second call is cheaper than a lost chunk.
            messages.append({"role": "assistant", "content": reply.content})
            messages.append(
                {"role": "user", "content": "That was not valid JSON. Return ONLY the JSON object."}
            )
            reply = await self.client.chat(messages, think=False, max_tokens=self.max_reply_tokens)
            parsed = self._parse(reply.content)
        return self._Reply(raw=reply.content, parsed=parsed)

    @staticmethod
    def _parse(raw: str) -> tuple[list[dict], list[dict]] | None:
        try:
            obj = json.loads(_strip_fence(raw))
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict):
            return None
        ents = obj.get("entities", [])
        rels = obj.get("relations", [])
        if not isinstance(ents, list) or not isinstance(rels, list):
            return None
        return ([e for e in ents if isinstance(e, dict)], [r for r in rels if isinstance(r, dict)])
