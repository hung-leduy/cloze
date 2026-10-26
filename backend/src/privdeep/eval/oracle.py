"""The unconstrained-cloud oracle: the arm that leaks, on purpose.

Scope item T5 requires reporting the oracle's own accuracy beside PrivDeep's,
because "we retain 92% of cloud quality" is uninterpretable when the cloud is
itself near the floor. This module produces the oracle's report: the same
goal, the same plan-then-draft shape, the same section budgets, but the raw
document text in every prompt and no placeholders anywhere.

It runs OUTSIDE the partition, from the host, with a direct client, since
sending the raw document to the cloud is the thing the partition exists to
prevent. That is stated in the run record it writes, and the record carries
no document text either: what leaked is the point, not something to store
twice.

Comparability is the design constraint. The planner tool schema and the private
drafter's register and word-budget rules are reused verbatim; its citation rule is
too, less the sentence limiting figures to tagged evidence, since this arm reads the corpus.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from privdeep.ingest import SUFFIXES, load
from privdeep.models.document import Document
from privdeep.models.outline import Outline, Section
from privdeep.tier2_cloud.cloud_client import REPORT_EFFORT, CloudClient
from privdeep.tier2_cloud.macro_planner import _TOOL as PLAN_TOOL
from privdeep.tier3_reconcile.evidence_bank import EvidenceBank

__all__ = ["OracleResult", "run_oracle"]

# Both arms must plan and draft at the same effort or the utility comparison
# measures the setting instead of the method. The comment here used to say
# these were imported from the private arm while both were literals repeated
# in three files; all three now read REPORT_EFFORT, and a parity test pins it.
PLAN_EFFORT = REPORT_EFFORT
DRAFT_EFFORT = REPORT_EFFORT

_PLAN_SYSTEM = (
    "You are planning a structured research report for an analyst. You are given the "
    "analyst's goal and the full text of the source documents. Plan a sequence of sections "
    "that together achieve the goal; each section gets a one-sentence objective and a word "
    "budget. Use the plan_outline tool for your answer. Leave slot_ids empty."
)

_DRAFT_SYSTEM = (
    "You are drafting one section of a structured research report for an analyst. You are "
    "given the section's objective, the report outline, the full text of the source "
    "documents, and summaries of public evidence with tags. Rules:\n"
    "1. Cite public evidence by its tag in square brackets, e.g. [W2], immediately after the "
    "claim it supports.\n"
    "2. Write in a measured scholarly register. No preamble, no headings, no closing remarks; "
    "output the section body only.\n"
    "3. Aim for the word budget."
)


@dataclass(slots=True)
class OracleResult:
    report_markdown: str
    resolved_models: list[str]
    sections: list[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # Characters of corpus the cap dropped. Non-zero means this arm read less
    # than the private arm did, and the comparison is not like-for-like.
    truncated_chars: int = 0
    max_doc_chars: int = 0
    direct: bool = True
    arm: str = "oracle-unconstrained"

    def record_json(self) -> str:
        d = asdict(self)
        d.pop("report_markdown")           # the record carries counts, not the report
        return json.dumps(d, ensure_ascii=False, indent=2)


def _docs_block(docs: list[Document], max_chars: int) -> tuple[str, int]:
    """The raw corpus as one block, plus how many characters were dropped.

    The count is returned rather than swallowed because this arm is the
    baseline the whole utility claim is measured against, and truncation here
    is not symmetric with the private arm. PrivDeep abstracts the *whole*
    corpus locally — `OntologyExtractor` chunks every document and iterates all
    chunks — so a corpus larger than `max_chars` leaves the oracle reading a
    prefix while PrivDeep read everything. Any gap measured under those
    conditions is partly the cap, not the method, and scope §7 requires the
    oracle's own accuracy to be interpretable. A run that truncates has to say
    so next to its number.
    """
    parts = [f"--- DOCUMENT {d.doc_id} ({d.kind}) ---\n{d.text}" for d in docs]
    text = "\n\n".join(parts)
    if len(text) <= max_chars:
        return text, 0
    return text[:max_chars] + "\n[documents truncated]", len(text) - max_chars


def _cached(stable: str, varying: str) -> list[dict[str, object]]:
    """Two content blocks with the cache breakpoint between them.

    The corpus goes in every one of this arm's calls — the plan, then one per
    section — and it is the same corpus every time. Caching is a prefix match,
    so the stable text has to come first and the per-section text last; the
    original prompt had the documents at the end, after the section objective,
    which is the one arrangement under which nothing can ever be reused.

    Measured at the 60k-character cap this is about 45% of the evaluation's
    total API bill, paid nine times over for one document set.
    """
    return [
        {"type": "text", "text": stable, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": varying},
    ]


async def run_oracle(docs: list[Document], goal: str, cloud: CloudClient, *,
                     evidence: EvidenceBank | None = None, max_doc_chars: int = 60_000,
                     min_budget: int = 150, max_budget: int = 1500,
                     max_sections: int = 8) -> OracleResult:
    if not cloud.direct:
        raise ValueError("the oracle arm must use a direct client; it is defined by bypassing "
                         "the monitor")
    evidence = evidence or EvidenceBank()
    ev_lines = "\n".join(f"[{u.tag}] {u.summary_claim}" for u in evidence) or "(none)"
    docs_block, truncated_chars = _docs_block(docs, max_doc_chars)
    if truncated_chars:
        print(f"warning: oracle corpus truncated by {truncated_chars} chars at the "
              f"{max_doc_chars}-char cap; the private arm reads the whole corpus, so the "
              f"utility comparison is not like-for-like", file=sys.stderr)

    # Everything the whole arm shares, in one cacheable prefix.
    stable = (f"GOAL:\n{goal}\n\nSOURCE DOCUMENTS:\n{docs_block}\n\n"
              f"PUBLIC EVIDENCE:\n{ev_lines}")

    plan = await cloud.messages(
        [{"role": "user", "content": _cached(stable, "Produce the outline now.")}],
        system=_PLAN_SYSTEM, max_tokens=8192, effort=PLAN_EFFORT, tools=[PLAN_TOOL],
        tool_choice={"type": "tool", "name": "plan_outline"},
    )
    models = [plan.model]
    in_tok, out_tok = plan.input_tokens, plan.output_tokens
    cr_tok, cw_tok = plan.cache_read_tokens, plan.cache_write_tokens
    raw = (plan.structured or {}).get("sections", [])
    sections: list[Section] = []
    for item in raw[:max_sections]:
        if not isinstance(item, dict):
            continue
        title, obj = str(item.get("title", "")).strip(), str(item.get("objective", "")).strip()
        if not title or not obj:
            continue
        try:
            b = int(item.get("word_budget", 0))
        except (TypeError, ValueError):
            b = 0
        sections.append(Section(f"s{len(sections) + 1}", title, obj,
                                min(max(b, min_budget), max_budget)))
    if not sections:
        raise RuntimeError("oracle planner produced no usable sections")
    outline = Outline(goal, tuple(sections))

    outline_lines = "\n".join(f"{s.id}: {s.title}" for s in outline.sections)

    parts: list[str] = []
    recs: list[dict] = []
    for sec in outline.sections:
        # The outline is stable across sections, so it joins the cached prefix;
        # only which section is being written varies. Marking the current
        # section inside the outline would put a per-section byte in the
        # prefix and defeat the cache for every call after the first.
        varying = (f"THIS SECTION: {sec.id} {sec.title}\nOBJECTIVE: {sec.objective}\n"
                   f"WORD BUDGET: {sec.word_budget}\n\nWrite the section body now.")
        reply = await cloud.messages(
            [{"role": "user", "content": _cached(stable + "\n\nOUTLINE:\n" + outline_lines,
                                                 varying)}],
            system=_DRAFT_SYSTEM, max_tokens=8192, effort=DRAFT_EFFORT)
        if reply.model not in models:
            models.append(reply.model)
        in_tok += reply.input_tokens
        out_tok += reply.output_tokens
        cr_tok += reply.cache_read_tokens
        cw_tok += reply.cache_write_tokens
        wc = len(reply.text.split())
        recs.append({"section_id": sec.id, "title": sec.title, "word_budget": sec.word_budget,
                     "word_count": wc, "resolved_model": reply.model})
        parts.append(f"## {sec.title}\n\n{reply.text.strip()}\n")

    report = f"# {goal.strip()}\n\n" + "\n".join(parts)
    return OracleResult(report, models, recs, in_tok, out_tok, cr_tok, cw_tok,
                        truncated_chars, max_doc_chars)


async def _main(corpus: Path, goal: str, out_dir: Path) -> int:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key or "PLACEHOLDER" in key:
        print("ANTHROPIC_API_KEY is not set to a real key; the oracle arm cannot run",
              file=sys.stderr)
        return 2
    docs = [load(p) for p in sorted(corpus.iterdir()) if p.suffix.lower() in SUFFIXES]
    base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    t0 = time.time()
    async with CloudClient(base, api_key=key) as cloud:
        res = await run_oracle(docs, goal, cloud)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "oracle_report.md").write_text(res.report_markdown, encoding="utf-8")
    (out_dir / "oracle_record.json").write_text(res.record_json(), encoding="utf-8")
    print(f"oracle: {len(res.sections)} sections, {res.input_tokens}+{res.output_tokens} tokens, "
          f"{time.time() - t0:.1f}s -> {out_dir}")
    return 0


if __name__ == "__main__":
    corpus_arg = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("corpus")
    goal_arg = sys.argv[2] if len(sys.argv) > 2 else "Assess the current position and risks."
    out_arg = (Path(sys.argv[3]) if len(sys.argv) > 3
               else Path("eval_runs") / time.strftime("%Y%m%d-%H%M%S"))
    sys.exit(asyncio.run(_main(corpus_arg, goal_arg, out_arg)))
