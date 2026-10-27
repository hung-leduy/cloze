"""One run, end to end, inside the partition.

    load -> extract -> mask -> register canaries + seal containment
         -> abstract payload -> plan -> per section: draft -> reintegrate -> ground
         -> report + manifest

Every component is injected so the whole chain runs offline under scripted
transports in the test suite, and runs live with the real clients from
`python -m privdeep.pipeline`. The pipeline owns three things the components
do not:

* **One mapping table per session.** `SlotMasker.mask` returns a fresh table
  per document; slot ids are HMAC(salt, category + text), so the same entity
  in two documents already gets the same id, and the session table is built
  by asking `slot_for` for every entity seen. A collision (two entities, one
  id) is refused by the table; the pipeline re-salts once and otherwise
  fails, because a silently re-mapped slot is a wrong value in the report.
* **Per-section failure isolation.** A monitor or reintegrator refusal, or a
  cloud or gateway error, marks that section refused in the manifest and the
  run continues; the grounder runs with strict=False, so it counts and never
  refuses. A report with a missing section is a result; a dead run is not.
* **The manifest.** Counters from every stage land in one publishable
  artifact; content never does.

What the pipeline does not do yet, and says so: retrieve web evidence. The
scope doc's sanitizer is on no live path, because nothing retrieves. The
caller supplies an `EvidenceBank`; empty is allowed and the drafter is then
told to make no numeric claims. This gap is named in the paper's scope
section rather than papered over here.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import secrets
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from privdeep.audit.manifest import RunManifest, SectionRecord
from privdeep.ingest import SUFFIXES, load
from privdeep.models.document import Document
from privdeep.tier1_local.canary_injector import CanaryInjector
from privdeep.tier1_local.containment import build_filter, seal_gateway
from privdeep.tier1_local.extraction_io import dump_extractions, load_extractions
from privdeep.tier1_local.fact_store import LocalFactStore, build_fact_store
from privdeep.tier1_local.ontology_extractor import (
    Extraction,
    OntologyExtractor,
    assert_no_corpus_leak,
    drop_corpus_leaking_relations,
)
from privdeep.tier1_local.slm_client import AsyncSLMClient
from privdeep.tier1_local.slot_masker import (
    Entity,
    LocalMappingTable,
    SlotCollisionError,
    SlotMasker,
)
from privdeep.tier2_cloud.abstract_payload import AbstractPayload, build_abstract_payload
from privdeep.tier2_cloud.cloud_client import CloudClient, CloudError, EgressRefused, GatewayError
from privdeep.tier2_cloud.macro_planner import MacroPlanner
from privdeep.tier2_cloud.section_drafter import Evidence, SectionDrafter
from privdeep.tier2_cloud.tracing import TracingCloudClient
from privdeep.tier3_reconcile.citation_grounder import _NUM_RE, CitationGrounder
from privdeep.tier3_reconcile.evidence_bank import EvidenceBank
from privdeep.tier3_reconcile.slot_reintegrator import ReintegrationRefused, SlotReintegrator

log = logging.getLogger(__name__)

__all__ = ["PipelineResult", "run_pipeline"]


@dataclass(slots=True)
class PipelineResult:
    report_markdown: str
    manifest: RunManifest
    sections_ok: int
    sections_refused: int
    outline_titles: list[str] = field(default_factory=list)
    # Everything sent to and received from the cloud, in order. Stays inside
    # the partition; it is the reconstruction adversary's input.
    trace: list[dict] = field(default_factory=list)
    # The entities this run actually masked. Returned so the adversary can be
    # scored against the run it is attacking: re-extracting them afterwards
    # runs a probabilistic model a second time and may yield a different set,
    # which would score recovery against entities the run never issued a slot
    # for. Private data, and stays inside the partition with the trace.
    entities: list[Entity] = field(default_factory=list)
    # Per-document extractions, saved so another arm can reuse them. See
    # tier1_local/extraction_io.py for why and for what reuse refuses.
    extractions: list[Extraction] = field(default_factory=list)


def _merge_payloads(payloads: list[AbstractPayload]) -> AbstractPayload:
    rels: list[tuple[str, str, str]] = []
    slots: dict[str, str] = {}
    for p in payloads:
        rels.extend(p.relations)
        slots.update(dict(p.slots))
    schemas = {(p.attribute_schema, p.fact_ref_format) for p in payloads}
    if len(schemas) > 1:
        raise ValueError("payloads built with and without facts cannot be merged")
    schema, fmt = schemas.pop() if schemas else ((), "")
    return AbstractPayload(
        doc_id="+".join(p.doc_id for p in payloads),
        relations=tuple(dict.fromkeys(rels)),
        slots=tuple(sorted(slots.items())),
        n_cells=sum(p.n_cells for p in payloads),
        n_blocks=sum(p.n_blocks for p in payloads),
        n_chars=sum(p.n_chars for p in payloads),
        attribute_schema=schema, fact_ref_format=fmt,
    )


def _session_table(salt: bytes, entities: Iterable[Entity], *,
                   normalise: bool = True) -> LocalMappingTable:
    """The one table that has seen every spelling, and so the one that renders.

    Built before masking, from the extractor's entity list, so its surface
    counts are per *listing* rather than per occurrence in the text. That is
    what `LocalMappingTable.original` weighs when it picks the spelling the
    report prints. Measured on a three-document corpus spelling one amount
    three ways, it makes no difference -- every surface is listed once and
    the longest-then-first-seen tie-break decides -- but it would if a terse
    spelling were ever listed more often than an explicit one.

    It must be this table and not a per-document one: a document's own table
    has only seen its own spellings, so the spreadsheet's occurrences would
    render as "250000" while the memo's render as "250,000".
    """
    table = LocalMappingTable(salt, normalise=normalise)
    for e in entities:
        table.slot_for(e)
    return table


async def run_pipeline(
    docs: list[Document],
    goal: str,
    *,
    slm: AsyncSLMClient,
    cloud: CloudClient,
    gateway_url: str,
    evidence: EvidenceBank | None = None,
    gw_client: httpx.Client | None = None,
    session_salt: bytes | None = None,
    run_id: str | None = None,
    arm: str = "r5",
    reuse_extraction: dict | None = None,
    extraction_source: str = "",
) -> PipelineResult:
    evidence = evidence or EvidenceBank()
    manifest = RunManifest(
        run_id=run_id or secrets.token_hex(6),
        local_model=slm.model,
        cloud_model_requested=cloud.model,
    )
    for d in docs:
        manifest.documents.append({"doc_id": d.doc_id, "kind": str(d.kind),
                                   "chars": len(d.text), "cells": len(d.cells)})

    # ---- Canaries first: they have to be in the prompt to be worth anything -
    # Registration must precede extraction, not follow it. The canary invariant
    # says a planted token on the wire proves prompt context escaped; if the
    # tokens are minted after the only prompts that would carry them, nothing
    # is planted and the gateway's matcher guards an empty set.
    canaries = CanaryInjector()
    canaries.register(gateway_url, client=gw_client)
    manifest.canaries_registered = len(canaries.tokens)

    # ---- Tier 1: extract, mask, session table -------------------------------
    extractor = OntologyExtractor(slm, canary_context=canaries.context_block())
    if reuse_extraction is not None:
        # Screened against *this* run's canary prefix and corpus before the
        # masker sees any of it; a refusal here raises and ends the run.
        reused = load_extractions(reuse_extraction, docs, canary_prefix=canaries.prefix)
        manifest.extraction_source = extraction_source or "reused"
    extractions: list[Extraction] = []
    for i, d in enumerate(docs):
        ex = reused[i] if reuse_extraction is not None else await extractor.extract(d)
        extractions.append(ex)
    # The W2 gate again, corpus-wide (ontology_extractor): `extract` checked a
    # document's relations against its own entities only, and the payload
    # merges every document's relations. Before anything is masked, saved or
    # sent. A reused extraction passed the strict form in load_extractions, so
    # on that path this drops nothing.
    drop_corpus_leaking_relations(extractions)
    assert_no_corpus_leak(extractions)  # postcondition; cannot fire
    for ex in extractions:
        # Counts only, into the publishable manifest. They include the W2
        # gate's drops, per-document and corpus-wide: a document the gate left
        # with no relation still contributes its slots and stats, and is counted.
        for k, n in ex.counters().items():
            manifest.extraction[k] = manifest.extraction.get(k, 0) + n

    all_entities: list[Entity] = [e for ex in extractions for e in ex.entities]
    normalise = arm != "baseline"
    facts = arm == "r1"
    salt = session_salt or secrets.token_bytes(32)
    store: LocalFactStore | None = None
    for attempt in (1, 2):
        try:
            table = _session_table(salt, all_entities, normalise=normalise)
            # Inside the loop: FACT tokens carry hex without category, so a
            # cross-category hex clash is a collision exactly like a slot one and
            # takes the same re-salt.
            store = build_fact_store(docs, table) if facts else None
            break
        except SlotCollisionError as exc:
            if attempt == 2:
                raise
            log.warning("slot id collision (%s); re-salting once", exc)
            salt = secrets.token_bytes(32)
    masker = SlotMasker(salt, normalise=normalise)
    payloads: list[AbstractPayload] = []
    for d, ex in zip(docs, extractions, strict=True):
        m = masker.mask(d, ex.entities)
        payloads.append(build_abstract_payload(d.doc_id, ex, m, n_cells=len(d.cells),
                                               n_blocks=len(d.blocks), n_chars=len(d.text),
                                               facts=facts))
    payload = _merge_payloads(payloads)
    manifest.arm = arm
    manifest.slots_issued = len(table)
    manifest.surface_forms = len(set(all_entities))
    manifest.fragmentation = table.fragmentation()
    if store is not None:
        manifest.facts = {**dict(store.counters), "facts_total": len(store)}

    # ---- Boundary setup: containment ----------------------------------------
    f = build_filter(docs, salt=os.environ.get("SHINGLE_HMAC_SALT", "").encode() or None)
    seal = seal_gateway(f, gateway_url, client=gw_client)
    manifest.containment = {"shingles": seal.get("n_added"), "m_bits": seal.get("m_bits"),
                            "k": seal.get("k"), "n_min": seal.get("n_min"),
                            "n_max": seal.get("n_max"),
                            "fp_est": f.bloom.estimated_fp_rate()}
    manifest.evidence = evidence.manifest()

    # ---- Tier 2: plan -------------------------------------------------------
    # Every cloud exchange is recorded on the trusted side; see tracing.py.
    tracer = TracingCloudClient(cloud)
    tracer.label("plan")
    planner = MacroPlanner(tracer)
    try:
        plan = await planner.plan(payload, goal)
    except EgressRefused as exc:
        manifest.record_egress(allowed=False)
        manifest.notes.append(f"planning refused by monitor: {exc.reason}")
        manifest.finish()
        # The extractions stay with the result so that _main can write
        # extractions.json and another arm can reuse them (scope §12.13, after the
        # track-L pilot, whose planner request the monitor refused: nothing that
        # crosses changes). So do the trace, which holds the refused request as
        # the local record, and the masked entities: until 2026-10-27 this path
        # dropped both, and a refused run's egress_trace.jsonl was empty.
        return PipelineResult("", manifest, 0, 0,
                              trace=[e.to_dict() for e in tracer.entries],
                              entities=all_entities, extractions=extractions)
    manifest.record_egress(allowed=True)
    manifest.note_resolved_model(plan.resolved_model)
    # Structured, not only in the note below: the health gate divides one by
    # the other, and parsing a free-text note is how a reworded sentence turns
    # into a gate that silently passes.
    manifest.planner_refs_returned = plan.refs_returned
    manifest.planner_refs_dropped = plan.dropped_unknown_slots
    manifest.notes.append(
        f"plan: {len(plan.outline.sections)} sections, {plan.dropped_unknown_slots} unknown "
        f"slot refs dropped, {plan.clamped_budgets} budgets clamped")
    outline = plan.outline

    # ---- Tier 2/3 per section: draft, reintegrate, ground -------------------
    drafter = SectionDrafter(tracer)
    reintegrator = SlotReintegrator(table, strict=True, facts=store)
    # Numerals the core itself wrote from resolved facts are not unbacked claims
    # by the cloud; they are exempted here and counted per section instead.
    fact_numerals = ({n for f in store.facts() for n in _NUM_RE.findall(f.rendering())}
                     if store is not None else set())
    grounder = CitationGrounder(evidence, strict=False, extra_exempt=fact_numerals)
    ev_list = [Evidence(u.tag, u.summary_claim, u.source_url) for u in evidence]
    parts: list[str] = []
    ok = refused = 0
    for sec in outline.sections:
        rec = SectionRecord(sec.id, sec.title, sec.word_budget, 0, len(sec.slot_ids), 0, 0, 0, 0,
                            0, 0, 0, "", 0, 0)
        tracer.label(f"draft:{sec.id}")
        try:
            draft = await drafter.draft(sec, outline, payload, ev_list)
        except EgressRefused as exc:
            manifest.record_egress(allowed=False)
            rec.refused = f"draft: {exc.reason}"
            manifest.sections.append(rec)
            refused += 1
            continue
        except (CloudError, GatewayError) as exc:
            rec.refused = f"draft: {type(exc).__name__}: {exc}"
            manifest.sections.append(rec)
            refused += 1
            continue
        manifest.record_egress(allowed=True)
        manifest.note_resolved_model(draft.resolved_model)
        rec.resolved_model = draft.resolved_model
        rec.input_tokens, rec.output_tokens = draft.input_tokens, draft.output_tokens
        rec.word_count, rec.invented_slots = draft.word_count, draft.invented_slots
        rec.slots_used = len(draft.slots_used)

        try:
            # Any slot the core issued may appear (the planner may spread them);
            # invented ones are already scrubbed by the drafter and refused here.
            ri = reintegrator.reintegrate(draft.text, issued=[sid for sid, _ in payload.slots])
        except ReintegrationRefused as exc:
            rec.refused = f"reintegrate: {exc}"
            rec.unsafe_positions = exc.unsafe
            manifest.sections.append(rec)
            refused += 1
            continue
        rec.unsafe_positions = ri.unsafe_positions
        rec.remote_images_removed = ri.remote_images_removed
        rec.facts_resolved, rec.facts_unavailable = ri.facts_resolved, ri.facts_unavailable
        rec.sentences_pruned = ri.sentences_pruned

        g = grounder.check(ri.text)
        rec.citations_valid, rec.citations_invalid = len(g.valid_tags), len(g.invalid_tags)
        rec.unbacked_numbers = len(g.unbacked_numbers)
        manifest.sections.append(rec)
        parts.append(f"## {sec.title}\n\n{ri.text.strip()}\n")
        ok += 1

    manifest.finish()
    report = f"# {goal.strip()}\n\n" + "\n".join(parts)
    return PipelineResult(report, manifest, ok, refused, [s.title for s in outline.sections],
                          trace=[e.to_dict() for e in tracer.entries], entities=all_entities,
                          extractions=extractions)


async def _main(corpus: Path, goal: str, out_dir: Path, *, arm: str = "r5",
                reuse_extraction: Path | None = None) -> int:
    files = sorted(p for p in corpus.iterdir() if p.suffix.lower() in SUFFIXES)
    docs = [load(p) for p in files]
    if not docs:
        print(f"no supported documents in {corpus}", file=sys.stderr)
        return 2
    gw = os.environ.get("GATEWAY_URL", "http://reference-monitor:5050")
    t0 = time.time()
    async with AsyncSLMClient() as slm, CloudClient(gw) as cloud:
        reuse = (json.loads(reuse_extraction.read_text(encoding="utf-8"))
                 if reuse_extraction else None)
        res = await run_pipeline(docs, goal, slm=slm, cloud=cloud, gateway_url=gw, arm=arm,
                                 reuse_extraction=reuse,
                                 extraction_source=str(reuse_extraction or ""))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(res.report_markdown, encoding="utf-8")
    (out_dir / "manifest.json").write_text(res.manifest.to_json(), encoding="utf-8")
    with (out_dir / "egress_trace.jsonl").open("w", encoding="utf-8") as fh:
        for e in res.trace:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    # The entity set this run masked, for the reconstruction adversary to be
    # scored against. Private, and it sits beside the report, which already
    # carries every real value.
    (out_dir / "entities.json").write_text(
        json.dumps([{"text": e.text, "category": e.category} for e in res.entities],
                   ensure_ascii=False, indent=2), encoding="utf-8")
    # Written on every run, so any run can be the source another arm reuses.
    (out_dir / "extractions.json").write_text(
        json.dumps(dump_extractions(docs, res.extractions), ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"sections ok={res.sections_ok} refused={res.sections_refused}  "
          f"{time.time() - t0:.1f}s  -> {out_dir}")
    return 0 if res.sections_ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="privdeep.pipeline")
    ap.add_argument("corpus", nargs="?", default=Path("/corpus"), type=Path)
    ap.add_argument("goal", nargs="?", default="Assess the current position and risks.")
    ap.add_argument("out_dir", nargs="?", type=Path,
                    default=Path("/data/runs") / time.strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--arm", choices=("r5", "baseline", "r1"), default="r5",
                    help="baseline keys slots on the raw surface text, as before R5; "
                         "r5 keys on the canonical form; r1 adds the local fact store, "
                         "so values cross only as fact references. Recorded in the "
                         "manifest.")
    ap.add_argument("--reuse-extraction", type=Path, default=None,
                    help="extractions.json from another run over the same corpus. The "
                         "extractor is nondeterministic, so arms compared on their own "
                         "extractions differ in more than the arm.")
    _a = ap.parse_args()
    sys.exit(asyncio.run(_main(_a.corpus, _a.goal, _a.out_dir, arm=_a.arm,
                               reuse_extraction=_a.reuse_extraction)))
