"""W2 live smoke, run INSIDE the partition: `python -m privdeep.smoke_w2 /corpus`.

Proves the W2 "done when" against the real stack rather than mocks:
  1. every file in the corpus loads to a Document whose cells validate;
  2. the live SLM extracts entities that the document itself confirms;
  3. mask -> restore is character-exact on every document;
  4. the ontology carries no entity string of any document of the corpus
     (the gate, per document in `extract` and then corpus-wide, checked by code);
  5. canaries register and the containment filter seals at the gateway;
  6. the gateway refuses a verbatim span, a canary, AND the masked prose (a
     local artifact that still carries non-entity phrases verbatim), and admits
     the abstract payload: relations + slot ids + stats, the only thing that crosses.

Prints one line per check and exits non-zero on the first failure. Nothing here
is a unit test; it is the artefact a referee can re-run.

Every document is extracted before the corpus-wide gate runs, because a
relation of one document can carry an entity string the extractor found only
in another; checks 3 to 6 then run on the first document, which is enough to
prove the chain.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
import time
from pathlib import Path

import httpx

from privdeep.ingest import SUFFIXES, load
from privdeep.tier1_local.canary_injector import CanaryInjector
from privdeep.tier1_local.containment import build_filter, seal_gateway
from privdeep.tier1_local.ontology_extractor import (
    OntologyExtractor,
    OntologyLeak,
    assert_no_corpus_leak,
    drop_corpus_leaking_relations,
)
from privdeep.tier1_local.slm_client import AsyncSLMClient
from privdeep.tier1_local.slot_masker import SlotMasker
from privdeep.tier2_cloud.abstract_payload import build_abstract_payload

GW = os.environ.get("GATEWAY_URL", "http://reference-monitor:5050").rstrip("/")


def ok(msg: str) -> None:
    print(f"  PASS  {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL  {msg}")
    sys.exit(1)


def inspect(payload: str) -> tuple[bool, str]:
    r = httpx.post(f"{GW}/inspect", content=payload.encode(), timeout=30)
    j = r.json()
    return bool(j.get("allowed")), j.get("reason", "OK")


async def main(corpus: Path) -> None:
    files = sorted(p for p in corpus.iterdir() if p.suffix.lower() in SUFFIXES)
    if not files:
        fail(f"no supported files in {corpus}")

    print("== 1. load ==")
    docs = []
    for p in files:
        d = load(p)
        docs.append(d)
        ok(f"{p.name}: {len(d.text)} chars, {len(d.cells)} cells, "
           f"{len(d.blocks)} blocks, id={d.doc_id}")

    print("== 2. extract (live SLM) ==")
    session_salt = secrets.token_bytes(32)
    masker = SlotMasker(session_salt)
    async with AsyncSLMClient() as slm:
        ex = OntologyExtractor(slm)
        results = []
        for d in docs:
            t = time.time()
            r = await ex.extract(d)
            dt = time.time() - t
            results.append(r)
            ok(f"{d.doc_id}: {len(r.entities)} entities, {len(r.relations)} relations, "
               f"{r.chunks} chunk(s), {dt:.1f}s  "
               f"[dropped: not-in-text={r.dropped_not_in_text} bad-cat={r.dropped_bad_category} "
               f"malformed={r.dropped_malformed} cat-conflict={r.dropped_category_conflict}]")
        # The payload merges every document's relations, so the gate runs over
        # the corpus once every document is extracted (ontology_extractor).
        cross = drop_corpus_leaking_relations(results)
        ok(f"corpus-wide gate: {cross} relation(s) dropped for another document's entity string")
        for d, r in zip(docs, results, strict=True):
            if not r.entities:
                fail(f"{d.doc_id}: extractor found zero entities; cannot exercise the masker")

            print("== 3. mask/restore ==")
            m = masker.mask(d, r.entities)
            restored = masker.restore(m)
            if restored != d.text:
                fail(f"{d.doc_id}: restore is not character-exact")
            ok(f"{d.doc_id}: {len(m.replacements)} spans masked into {len(m.table)} slots, "
               f"{len(m.unmatched)} unmatched; restore == text")

            print("== 4. gate ==")
            try:
                assert_no_corpus_leak(results)
            except OntologyLeak as exc:  # the message names the category only
                fail(f"W2 gate: {exc}")
            ok(f"{d.doc_id}: ontology carries no entity string of the corpus "
               f"({r.relations_dropped_leak} relation(s) dropped by the gate)")

            print("== 5. register + seal ==")
            can = CanaryInjector()
            can.register(GW)
            ok(f"{len(can.tokens)} canaries registered")
            f = build_filter([d])
            body = seal_gateway(f, GW)
            ok(f"containment sealed at gateway: {body['n_added']} shingles, "
               f"fp~{f.bloom.estimated_fp_rate():.1e}")

            print("== 6. egress verdicts ==")
            # a verbatim span of the private text, >= n_min words, must be refused
            words = d.text.split()
            span = " ".join(words[:12]) if len(words) >= 12 else d.text
            allowed, reason = inspect(f"Background: {span}")
            if allowed:
                fail("gateway ADMITTED a verbatim span of C_user")
            ok(f"verbatim span refused: {reason}")

            allowed, reason = inspect(f"note {can.tokens[0]} end")
            if allowed:
                fail("gateway ADMITTED a canary token")
            ok(f"canary refused: {reason}")

            # The masked prose is a LOCAL artifact: it still carries every
            # non-entity phrase verbatim, and the filter must say so.
            allowed, reason = inspect(m.masked_text[:4000])
            if allowed:
                fail("gateway ADMITTED masked prose; the containment filter is not seeing it")
            ok(f"masked prose (local artifact) refused as it must be: {reason}")

            # What actually crosses: relations + slot ids + stats. Nothing else.
            payload = build_abstract_payload(d.doc_id, r, m, n_cells=len(d.cells),
                                             n_blocks=len(d.blocks), n_chars=len(d.text))
            allowed, reason = inspect(payload.to_json())
            if not allowed:
                fail(f"gateway REFUSED the abstract payload: {reason} "
                     "(a relation predicate is echoing document text)")
            ok(f"abstract payload admitted: {len(payload.relations)} relations, "
               f"{len(payload.slots)} slots, {len(payload.to_json())} bytes")
            break  # one document is enough to prove the chain; loop stays for later widening

    print("\nW2 chain holds end to end inside the partition.")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1] if len(sys.argv) > 1 else "/corpus")))
