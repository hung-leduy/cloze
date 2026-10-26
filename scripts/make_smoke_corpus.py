#!/usr/bin/env python3
"""Write the synthetic smoke corpus (scenario A) for a live run.

A thin wrapper since EXP1: the scenario lives in ``scripts/corpora/smoke_q3.py``
and the writers in ``scripts/corpora/writers.py``; ``python scripts/corpora``
writes all three scenarios. This script keeps its command line (``--out``, a
directory the four documents and the key are written into directly, default
``corpus/``) and its module surface, because ``calibrate_faithfulness.py`` and
the unit tests import ``fact_key``, ``write_fact_key``, the writers and the
scenario constants from here. Its output is byte-identical to what it wrote
before the split; ``backend/tests/unit/test_corpus_scenarios.py`` pins that.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Loaded by path (importlib) as well as by name, so the package's parent is put
# on the path here rather than relied on.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpora import generate  # noqa: E402
from corpora import writers as _W  # noqa: E402
from corpora.smoke_q3 import (  # noqa: E402, F401
    ANALYST,
    ATTRIBUTES,
    CONTRACT,
    CONTRACT2,
    CONTRACT3,
    DIRECTOR,
    LEAD,
    MASK_PATTERNS,
    NUMERIC_FACTS,
    ORG,
    PDF_PAGES,
    PILOT,
    PROJECT,
    PROJECT2,
    REFERENTS,
    SITE,
    SITE2,
    SITE3,
    STRING_FACTS,
    SURFACE_FACTS,
    VENDOR,
    fact_key,
    surfaces,
    write_docx,
    write_fact_key,
    write_markdown,
    write_xlsx,
)
from corpora.writers import write_pdf  # noqa: E402, F401

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "corpus"
_normalise_ooxml = _W.normalise_ooxml
_money_surfaces = _W.money_surfaces


def main(argv: list[str] | None = None) -> int:
    from corpora import smoke_q3

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="corpus directory to write (created if absent)")
    args = ap.parse_args(argv)
    out = Path(args.out).expanduser().resolve()
    generate(smoke_q3, out)
    total = _W.readback(out)
    if total is None:
        print(f"wrote {out}; skipped the read-back check (backend not importable)")
    else:
        print(f"wrote {out}  ({total} chars total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
