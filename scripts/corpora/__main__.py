"""``python scripts/corpora --scenario {smoke_q3,portfolio_b,prose_c,offlex_d,all} --out DIR``."""

import sys
from pathlib import Path

# Run as a directory, Python puts scripts/corpora itself on the path; the
# modules import each other as the `corpora` package, so its parent is needed.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corpora import main  # noqa: E402

raise SystemExit(main())
