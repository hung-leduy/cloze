"""The local extractor alone, over one corpus, saved for the Tier-1 probe.

Plan task EXP4, experiment X2. Every arm masks from one saved extraction, so
the extractor is the floor under all of them, and its run-to-run variance and
recall are measured by running it again, k times, over the same documents.
The SLM publishes no port on the host, so this runs inside ``privdeep-core``;
``scripts/tier1_probe.py extract`` drives it through ``docker compose exec``
and copies the file out.

What is the same as a pipeline run, and what is not
---------------------------------------------------
* **The prompt.** The extractor is given a canary context block, as
  ``run_pipeline`` gives it, so the system prompt has the same shape and
  length as the one the measured runs used. The tokens are fresh and are not
  registered with the monitor: nothing here egresses, so there is nothing for
  the monitor to match against. A reused file screens them anyway
  (``extraction_io.load_extractions`` refuses any canary-prefixed string).
* **No seed.** The extractor runs at the client's temperature with no seed;
  unseeded variance is the quantity a deployment sees.
* **The leak gate.** Since 2026-09-27 ``extract`` drops a relation that
  carries one of its document's entity strings and counts it
  (``relations_dropped_leak``), exactly as in a pipeline run, so no document
  aborts. Once every document is extracted, ``drop_corpus_leaking_relations``
  drops, and counts in the same per-document counter, a relation that carries
  an entity string of any other document, as ``run_pipeline`` does, so the
  saved file passes the reuse path's corpus-wide check. The per-document count
  is saved with the other counters and the corpus total is in the ``probe``
  block. Files written before that date may
  carry a ``probe.aborted`` list instead (document id and category of each
  abort); ``scripts/tier1_probe.py`` still reads it.

The output is the ``privdeep.extractions/1`` format ``extraction_io`` writes,
plus a ``probe`` block (model, timing, leak-gate drops). Raw SLM replies are
not saved, for the reason ``extraction_io`` gives.

Usage (inside the container)::

    python -m privdeep.tier1_local.probe_extract /corpus /data/probe/<id>/extraction_1.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from privdeep.ingest import SUFFIXES, load
from privdeep.models.document import Document
from privdeep.tier1_local.canary_injector import CanaryInjector
from privdeep.tier1_local.extraction_io import dump_extractions
from privdeep.tier1_local.ontology_extractor import (
    Extraction,
    OntologyExtractor,
    drop_corpus_leaking_relations,
)
from privdeep.tier1_local.slm_client import AsyncSLMClient

__all__ = ["extract_corpus", "main"]

async def extract_corpus(docs: Sequence[Document], slm: AsyncSLMClient
                         ) -> dict[str, Any]:
    """One extraction of every document, as the saved-extraction format plus a probe block."""
    extractor = OntologyExtractor(slm, canary_context=CanaryInjector().context_block())
    kept: list[Extraction] = []
    t0 = time.monotonic()
    for d in docs:
        kept.append(await extractor.extract(d))
    drop_corpus_leaking_relations(kept)  # the payload merges every document's relations
    out = dump_extractions(docs, kept)
    out["probe"] = {"model": slm.model, "canary_context": True,
                    "documents_total": len(docs),
                    "relations_dropped_leak": sum(ex.relations_dropped_leak for ex in kept),
                    "seconds": round(time.monotonic() - t0, 1)}
    return out


async def _run(corpus: Path, out: Path) -> int:
    files = sorted(p for p in corpus.iterdir() if p.suffix.lower() in SUFFIXES)
    docs = [load(p) for p in files]
    if not docs:
        print(f"no supported documents in {corpus}", file=sys.stderr)
        return 2
    async with AsyncSLMClient() as slm:
        data = await extract_corpus(docs, slm)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    probe = data["probe"]
    print(f"extracted {len(data['documents'])}/{probe['documents_total']} document(s), "
          f"{probe['relations_dropped_leak']} relation(s) dropped by the leak gate, "
          f"{probe['seconds']}s -> {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="privdeep.tier1_local.probe_extract",
                                 description=__doc__.split("\n", 1)[0])
    ap.add_argument("corpus", type=Path)
    ap.add_argument("out", type=Path)
    a = ap.parse_args(argv)
    return asyncio.run(_run(a.corpus, a.out))


if __name__ == "__main__":
    sys.exit(main())
