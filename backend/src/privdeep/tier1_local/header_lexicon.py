"""Column headers to attribute codes, locally, once.

A header is read here as a key and goes no further: what crosses the boundary is
the code, never the header text. A header that matches no code, or more than one,
is dropped and counted -- never passed through as a name.

Two departures from the design document, both about false facts:

* ``raised by`` is **not** ``OWNERREF``. The person who raised a risk is not the
  owner of the project. On the smoke corpus they happen to be the same people,
  which is exactly why the mapping looks harmless there; in general it would
  write a manufactured ownership into a report.
* ``date`` alone maps to nothing. The Risks sheet's ``Date`` is when a risk was
  raised, not when anything started.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["attribute_for_header", "unit_for_header"]

_LEXICON: dict[str, tuple[str, ...]] = {
    "AUTHAMT": ("budget", "authorised", "authorized", "approved", "allocation", "authority"),
    "SPENTAMT": ("spent", "committed", "expenditure", "actual", "actuals"),
    "OWNERREF": ("owner", "lead"),
    "SITEREF": ("site", "location", "facility"),
    "REFCODE": ("contract", "agreement", "po"),
    "DATESTRT": ("start", "commenced"),
}
_WORD = re.compile(r"[a-z]+")
_UNIT = re.compile(r"\(\s*([A-Z]{3})\s*\)")


def attribute_for_header(header: str) -> str | None:
    words = set(_WORD.findall(unicodedata.normalize("NFKC", header).casefold()))
    hits = {code for code, terms in _LEXICON.items() if words & set(terms)}
    return hits.pop() if len(hits) == 1 else None


def unit_for_header(header: str) -> str | None:
    m = _UNIT.search(unicodedata.normalize("NFKC", header))
    return m.group(1) if m else None
