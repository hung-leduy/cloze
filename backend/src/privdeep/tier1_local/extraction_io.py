"""Save one run's local extraction and reuse it in another, without lying.

Why this exists
---------------
The BASELINE and R5 arms differ in one thing: how a slot id is keyed. Each arm
used to run its own extraction, and the extractor is ``qwen3:14b`` at
``temperature=0.1`` with no seed. Two arms would therefore mask *different
entity sets*, and a difference in role-binding accuracy could come from
extraction variance rather than from R5 -- the one change the comparison exists
to isolate. Reusing a single extraction makes Tier 1's input identical across
arms. It does not make the cloud deterministic (Sonnet 5 rejects sampling
parameters), so an N=1 difference is still a difference and not an effect.

What reuse must refuse
----------------------
A reused extraction is input the current run did not produce, so three checks
stand between it and the masker. Each guards a way a run could otherwise pass
while being wrong:

* **A different corpus.** Entities from other documents are simply not found by
  the masker; they land in ``unmatched`` and the run carries on with fewer
  slots. The file records a SHA-256 of every ``Document.text`` and loading
  refuses any mismatch, in either direction.
* **Canary tokens.** Canaries are planted in the *extractor* prompt and are
  fresh per run. An extraction reused from an earlier run can carry that run's
  tokens, which this run's monitor was never told about, so the canary screen
  would pass them. Any string containing the canary prefix is refused.
* **Entities not in the text.** The extractor already drops these; a file that
  still has them has been edited or belongs elsewhere.
* **A relation carrying an entity string.** The writers drop and count a
  relation that fails the corpus-wide W2 gate (`drop_leaking_relations` per
  document, then `drop_corpus_leaking_relations` over every document), so a
  file they write never holds one. Reused relations would bypass that unless
  the gate runs again here, and relations are what cross the boundary. Here it
  is the strict corpus-wide form, `assert_no_corpus_leak`, over every loaded
  document at once: a relation of any document that contains an entity string
  of any document raises `OntologyLeak` and ends the run. A leaking saved
  relation means a file written before the gate dropped (2026-09-27) or before
  it was corpus-wide, or one altered since, and a refused file is safer than a
  silently repaired one.

The drop count (`relations_dropped_leak`) is saved with the other counters, so
every arm that reuses an extraction reports the drops its extraction made. A
file written before the counter existed loads it as 0, which is true of it:
the extractor of that date aborted instead of dropping.

Raw SLM replies are not saved. They are not needed to mask, and they are a copy
of private text with no reason to exist twice.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from privdeep.models.document import Document
from privdeep.tier1_local.ontology_extractor import (
    ConceptRelation,
    Extraction,
    assert_no_corpus_leak,
)
from privdeep.tier1_local.slot_masker import Entity

__all__ = ["ExtractionReuseError", "dump_extractions", "load_extractions", "text_sha256"]

FORMAT = "privdeep.extractions/1"
_COUNTERS = ("dropped_not_in_text", "dropped_bad_category", "dropped_malformed",
             "dropped_category_conflict", "relations_dropped_leak", "chunks")


class ExtractionReuseError(ValueError):
    """A saved extraction cannot be used for this run."""


def text_sha256(doc: Document) -> str:
    return hashlib.sha256(doc.text.encode("utf-8")).hexdigest()


def dump_extractions(docs: Sequence[Document], extractions: Sequence[Extraction]) -> dict[str, Any]:
    if len(docs) != len(extractions):
        raise ValueError("one extraction per document")
    return {
        "format": FORMAT,
        "documents": [
            {
                "doc_id": d.doc_id,
                "text_sha256": text_sha256(d),
                "entities": [{"text": e.text, "category": e.category} for e in ex.entities],
                "relations": [list(r.fields()) for r in ex.relations],
                **{k: getattr(ex, k) for k in _COUNTERS},
            }
            for d, ex in zip(docs, extractions, strict=True)
        ],
    }


def load_extractions(data: dict[str, Any], docs: Sequence[Document], *,
                     canary_prefix: str) -> list[Extraction]:
    """Rebuild extractions for `docs`, in `docs` order, or refuse.

    Refusals are `ExtractionReuseError`, except a saved relation that carries
    an entity string of any saved document, which raises `OntologyLeak` from
    the strict corpus-wide W2 gate (`assert_no_corpus_leak`, run once over all
    rows after the per-row checks; it subsumes the per-document check this
    function used to run, and its message names the category only). That one
    is not dropped here as the writers would drop it: they never save such a
    relation, so its presence means an older or altered file.
    """
    if data.get("format") != FORMAT:
        raise ExtractionReuseError(f"not a {FORMAT} file (format={data.get('format')!r})")
    if not canary_prefix:
        raise ExtractionReuseError("a canary prefix is required to screen a reused extraction")

    saved = {row["text_sha256"]: row for row in data["documents"]}
    here = {text_sha256(d): d for d in docs}
    if set(saved) != set(here) or len(data["documents"]) != len(docs):
        missing = len(set(here) - set(saved))
        extra = len(set(saved) - set(here))
        raise ExtractionReuseError(
            f"corpus mismatch: {missing} document(s) of this run have no saved "
            f"extraction and {extra} saved extraction(s) match no document here")

    out: list[Extraction] = []
    for d in docs:
        row = saved[text_sha256(d)]
        strings = [e["text"] for e in row["entities"]] + [x for r in row["relations"] for x in r]
        if any(canary_prefix in s for s in strings):
            raise ExtractionReuseError(
                f"{d.doc_id}: saved extraction carries a canary-prefixed string; an earlier "
                "run's canaries are unknown to this run's monitor and would pass its screen")
        entities = [Entity(e["text"], e["category"]) for e in row["entities"]]
        absent = sum(1 for e in entities if e.text not in d.text)
        if absent:
            raise ExtractionReuseError(
                f"{d.doc_id}: {absent} saved entit(y/ies) do not occur in the document text")
        relations = [ConceptRelation(*r) for r in row["relations"]]
        out.append(Extraction(entities=entities, relations=relations,
                              **{k: int(row.get(k, 0 if k != "chunks" else 1)) for k in _COUNTERS}))
    # Strict, unlike the writers: refuse the file, do not repair it. Over every
    # row at once, since the payload merges every document's relations.
    assert_no_corpus_leak(out)
    return out
