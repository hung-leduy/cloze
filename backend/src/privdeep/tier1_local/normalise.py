"""Canonical keys for entity surface forms: R5, one slot per referent.

The first live run masked 19 MONEY slots for 8 actual figures, because the slot
id is ``HMAC(salt, category ‖ NUL ‖ text)`` and ``250,000``, ``250,000.00`` and
``250000`` are three different texts. The cloud received three unrelated
placeholders for one amount and, having no way to know they were the same
amount, wrote all 15 of the report's self-contradictions. This module supplies
the key that collapses them.

Deterministic, model-free, no network. It runs inside the partition and its
output is HMAC'd, so nothing it computes leaves the trusted zone.

The rule that is *not* here
---------------------------
The design specified one join rule: "two decimals are the same referent if
either is the six-significant-figure rounding of the other", justified as
undoing exactly what ``ingest/xlsx.py`` split (``187433``↔``187,432.55``).
That justification expired with commit ``fae743f``, which fixed the loader to
use ``repr(v)``: those truncated forms no longer enter ``Document.text`` at all.

Re-measured on the post-fix corpus, the rule would join **0 pairs**. It is not
merely unjustified now, it is inert — and inert is the best case. The bad case
is a corpus holding a genuine ``187433`` alongside a genuine ``187432.55``,
where the rule merges two real amounts into one referent and ``restore`` writes
the wrong number into the report. A wrong merge is worse than the fragmentation
it repairs, so the rule is omitted and `test_normalise.py` pins its absence.

No alias merging, and why that is not timidity
-----------------------------------------------
``Zephyr`` and ``Project Zephyr`` keep different keys. So do acronyms, initials
and any other substring relation. The asymmetry is deliberate: failing to merge
two spellings of one referent costs fragmentation, which is counted and
reported; merging two different referents writes a false value into a report
the user will act on. Only the first is recoverable. A test fails if alias
merging is ever added.

Known limitation, stated rather than hidden
--------------------------------------------
Currency markers are stripped, not compared, so ``250,000 USD`` and
``250,000 EUR`` receive the same key and would merge. The corpus is
single-currency and does not exercise it; a multi-currency deployment must add
a conflict check before trusting MONEY merges. `test_normalise.py` pins this as
a known-wrong case so it cannot be discovered by surprise.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

__all__ = ["canonical_key", "canonical_rendering"]

# Currency words and symbols are removed before parsing. See the limitation in
# the module docstring: removed, not compared.
_CURRENCY = re.compile(
    r"(?:\b(?:usd|eur|gbp|vnd|dong|đồng|dollars?|euros?|pounds?)\b|[$€£¥₫])",
    re.IGNORECASE)
_THOUSANDS = re.compile(r"(?<=\d)[,   ](?=\d{3}\b)")
_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")

_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"), start=1)}
# The separator and zone letters are matched in both cases on purpose. Every
# caller here folds first, and `str.casefold` lowercases the `T` in
# "2026-06-01T00:00:00" and the trailing `Z` -- so an uppercase-only pattern
# fails on exactly the form `ingest/xlsx.py` produces for a date cell,
# splitting every spreadsheet date from its prose spelling. That is the
# fragmentation R5 exists to remove, reintroduced by the normaliser itself.
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[Tt ][\d:.]+)?[Zz]?$")
_D_MON_Y = re.compile(r"^(\d{1,2})\s+([a-z]+)\s+(\d{4})$")
_MON_D_Y = re.compile(r"^([a-z]+)\s+(\d{1,2}),?\s+(\d{4})$")
_MON_Y = re.compile(r"^([a-z]+)\s+(\d{4})$")

_SEPARATORS = re.compile(r"[\s\-_./\\]+")
_POSSESSIVE = re.compile(r"['’]s$")
_ARTICLE = re.compile(r"^(?:the|a|an)\s+")
_WS = re.compile(r"\s+")

_NUMERIC_CATEGORIES = ("MONEY", "QUANTITY")


def _fold(text: str) -> str:
    """NFKC, casefold, collapse whitespace. The floor every category stands on."""
    return _WS.sub(" ", unicodedata.normalize("NFKC", text).casefold()).strip()


def _numeric(text: str) -> str | None:
    """``250,000.00`` / ``250000`` / ``$250,000`` -> a single canonical decimal.

    Returns None when the text is not a lone number, so a QUANTITY like
    "340 units" or a whole risk sentence the extractor mistyped falls back to
    text normalisation instead of being silently reduced to its first numeral.
    That fallback matters: the extractor types whole cells as QUANTITY, and
    keying two different sentences by a digit they share would merge them.
    """
    t = _THOUSANDS.sub("", _CURRENCY.sub(" ", _fold(text))).strip()
    t = t.replace("−", "-")
    if not _NUMBER.fullmatch(t):
        return None
    try:
        d = Decimal(t)
    except InvalidOperation:
        return None
    # Normalise scale without going exponential: 250000.00 and 250000 agree,
    # and `normalize()`'s 2.5E+5 spelling never reaches the key.
    d = d.normalize()
    if d == d.to_integral_value():
        d = d.quantize(Decimal(1))
    return format(d, "f")


def _date(text: str) -> str | None:
    """ISO where unambiguous, so an xlsx cell and its prose spelling agree.

    Purely numeric forms like ``01/06/2026`` are left alone: day-first and
    month-first are both plausible and guessing would merge two different days.
    """
    t = _fold(text)
    m = _ISO.match(t)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    for rx, order in ((_D_MON_Y, "dmy"), (_MON_D_Y, "mdy")):
        m = rx.match(t)
        if m:
            day, mon, year = ((m.group(1), m.group(2), m.group(3)) if order == "dmy"
                              else (m.group(2), m.group(1), m.group(3)))
            if mon in _MONTHS:
                return f"{int(year):04d}-{_MONTHS[mon]:02d}-{int(day):02d}"
    m = _MON_Y.match(t)
    if m and m.group(1) in _MONTHS:
        return f"{int(m.group(2)):04d}-{_MONTHS[m.group(1)]:02d}"
    return None


def _identifier(text: str) -> str:
    """Casefold and drop separators: ``NB-2026-0917`` and ``nb 2026 0917`` agree."""
    return _SEPARATORS.sub("", _fold(text))


def _name(text: str) -> str:
    """Names, organisations, projects, places.

    Strips a trailing possessive and a leading article, which are grammar rather
    than identity. Nothing else — no alias, acronym or substring merging.
    """
    return _POSSESSIVE.sub("", _ARTICLE.sub("", _fold(text))).strip()


def canonical_key(category: str, text: str) -> str:
    """The key two surface forms must share to be one referent.

    Never raises. An input this module cannot parse falls back to `_fold`, which
    is still deterministic and still collapses the whitespace and Unicode-form
    differences that produced duplicate slots in the first place. Failing closed
    here would mean a document the extractor mistyped could abort a run.
    """
    if category in _NUMERIC_CATEGORIES:
        return _numeric(text) or _name(text)
    if category == "DATE":
        return _date(text) or _name(text)
    if category == "IDENTIFIER":
        return _identifier(text)
    return _name(text)


def canonical_rendering(surfaces: Mapping[str, int]) -> str:
    """Which observed spelling reintegration should write into the report.

    `surfaces` maps surface form to occurrence count, in first-seen order.

    The choice is restricted to spellings that actually occur in C_user. A
    formatter that rendered the canonical *key* back into prose could emit a
    string the user's documents never contained — ``250000.00`` where every
    document says ``250,000.00`` — which is a fabrication path opened by the
    component whose job is fidelity. Most frequent wins; ties go to the longest
    (``250,000.00`` over ``250000``, the more explicit of two equals) and then
    to first-seen, which is document order.
    """
    if not surfaces:
        raise ValueError("a referent with no observed surface form has nothing to render")
    order = {s: i for i, s in enumerate(surfaces)}
    return max(surfaces, key=lambda s: (surfaces[s], len(s), -order[s]))
