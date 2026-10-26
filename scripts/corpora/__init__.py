"""Synthetic private corpora, one module per scenario (plan task EXP1).

Synthetic on purpose (scope decision D5): no real person's data enters the
repo, the container, or — since the oracle arm exists to leak — a cloud
provider's request logs. The content is shaped like what the deployment will
see, and every slot category in ``SLOT_CATEGORIES`` has at least one instance
so the ontology extractor and the slot masker both have real work to do.

Scenarios
---------
* ``smoke_q3``    A, ``eval/corpora/smoke-q3``: the pilot corpus, byte-identical
                  to what ``scripts/make_smoke_corpus.py`` has always written.
* ``portfolio_b`` B, ``eval/corpora/portfolio-b``: the same budget-report
                  family for another organisation, four projects, columns
                  reordered and headers drawn from ``header_lexicon.py``'s
                  synonyms. The out-of-sample test of R1's structural route.
* ``prose_c``     C, ``eval/corpora/prose-c``: the figures live in prose and
                  the spreadsheet is only a risk register. The pre-registered
                  test of R1's limit, which has no prose route.
* ``offlex_d``    D, ``eval/corpora/offlex-d``: the budget-report family again,
                  with about half of the budget columns under natural finance
                  headers that ``header_lexicon.py`` does not map. The test of
                  how much of R1's gain depends on that lexicon (H4-D).

A scenario module holds constants, the documents written from them, the gold
key authored beside them (``fact_key()``), and ``surfaces()``: every constant
string it writes into any document, which the generator-surface scan reads.
``generate`` writes the key and the surfaces (``surfaces.json``, grouped and
flat) beside the documents, so a corpus directory is self-describing.
The writers and the OOXML normalisation are shared (``writers.py``), as is the
RBA key's attribute lexicon (``rba_lexicon.py``).

The keys of B, C and D are provisional until the author audits them against the
rendered documents; ``eval/corpora/KEY_AUDIT.md`` lists every key fact with the
sentence or cell it comes from, and logs the provisional key SHAs.

English, and what that hides
----------------------------
The samples are English. The deployment corpus is Vietnamese, and two things
about it do not show up here:

* **Diacritics and normal form.** ``ingest.md`` preserves whichever normal form
  a file was saved in, and the containment tokeniser folds NFD to NFC. Neither
  is exercised by ASCII text. `gateway/tests/test_monitor_bypasses.py` covers
  it instead.
* **The PDF writer could not produce Vietnamese.** See ``writers.py``.

Deterministic: same bytes on every run, so a corpus hash in a manifest means
something and re-running does not invalidate a measurement.

Usage::

    python scripts/corpora --scenario all --out eval/corpora --audit
"""

from __future__ import annotations

import argparse
from pathlib import Path
from types import ModuleType

from corpora import offlex_d, portfolio_b, prose_c, smoke_q3
from corpora import writers as W

__all__ = ["DEFAULT_OUT", "SCENARIOS", "generate", "is_provisional", "main"]

SCENARIOS: dict[str, ModuleType] = {
    "smoke_q3": smoke_q3,
    "portfolio_b": portfolio_b,
    "prose_c": prose_c,
    "offlex_d": offlex_d,
}
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "eval" / "corpora"


def is_provisional(scenario: ModuleType) -> bool:
    """B, C and D mark their keys provisional until the author has audited them."""
    return "provisional" in scenario.fact_key()


def generate(scenario: ModuleType, out: Path) -> list[Path]:
    """Write one scenario's documents, gold key and surfaces list into `out`.

    The answer key and the surfaces list go beside the corpus, not into it: the
    loaders skip .json, so neither becomes a Document or can reach an arm.
    """
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, write in scenario.DOCUMENTS.items():
        write(out / name)
        written.append(out / name)
    key = out / W.FACT_KEY_NAME
    key.write_text(W.dump_key(scenario.fact_key()), encoding="utf-8")
    written.append(key)
    surfaces = out / W.SURFACES_NAME
    surfaces.write_text(W.dump_surfaces(scenario.ID, scenario.surface_groups()),
                        encoding="utf-8")
    written.append(surfaces)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write the synthetic scenario corpora.")
    ap.add_argument("--scenario", required=True, choices=[*SCENARIOS, "all"])
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="parent directory; each scenario is written to <out>/<id>/ "
                         "(default: eval/corpora)")
    ap.add_argument("--audit", action="store_true",
                    help="also write <out>/KEY_AUDIT.md for every provisional key, "
                         "keeping the Audited marks of rows that did not change "
                         "(needs --scenario all)")
    args = ap.parse_args(argv)
    parent = Path(args.out).expanduser().resolve()
    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    provisional = [n for n in SCENARIOS if is_provisional(SCENARIOS[n])]
    if args.audit and not set(provisional) <= set(names):
        # The sheet covers every provisional key; rewriting it from a subset
        # would drop the other sections, and the author's marks with them.
        ap.error(f"--audit rewrites the sheet for every provisional key "
                 f"({', '.join(provisional)}); use --scenario all")
    for name in names:
        mod = SCENARIOS[name]
        out = parent / mod.ID
        generate(mod, out)
        total = W.readback(out)
        if total is None:
            print(f"wrote {out}; skipped the read-back check (backend not importable)")
        else:
            print(f"wrote {out}  ({total} chars total)")
    if args.audit:
        from corpora.audit import audit_markdown, carry_marks

        path = parent / "KEY_AUDIT.md"
        text = audit_markdown([SCENARIOS[n] for n in provisional], parent)
        dropped: list[str] = []
        if path.exists():
            text, dropped = carry_marks(text, path.read_text(encoding="utf-8"))
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")
        for row in dropped:
            print(f"  audit mark dropped, its row changed or is gone: {row}")
    return 0
