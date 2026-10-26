"""The closed attribute vocabulary and the FACT token: R1's wire-level constants.

R5 did not fix role binding (measured 2026-09-14, BASELINE vs R5 on a shared
extraction). Nothing crossing the boundary said *what a value was* -- the cloud
received a MONEY slot and had to guess whether it was an authority, a spend or a
balance -- and both arms misbound most of what they wrote. R1 moves the binding
local: the cloud writes ``⟦FACT:389a0ca5.AUTHAMT⟧`` ("this referent's
authorised amount") and the core, which holds the table, supplies the number.

Why the vocabulary is closed
----------------------------
A corpus-derived attribute set cannot be padded to a constant, because the set
*is* the leak. These thirteen codes are fixed in advance; every referent of a
category advertises all of them whether or not a value exists. The honest scope
of that claim: the codes were read off this corpus family. "0 bits given a
vocabulary fixed in advance", not "0 bits for any corpus".

Why eight characters, and why no category in the token
------------------------------------------------------
Measured against ``gateway/linters/entropy_linter.py`` (threshold 4.85, tokens of
24 characters or fewer are never scored), 30,000 random draws per context:

======================  ==========  ===========  ==========  ==========
form                    bare len    quoted JSON  possessive  two glued
======================  ==========  ===========  ==========  ==========
``⟦FACT:hex8.ATTR⟧``    23-24       4.607        4.624       **4.954**
with category           27-33       4.911        4.923       5.106
======================  ==========  ===========  ==========  ==========

Figures are worst cases. With the category, about 0.5% of tokens in quoted
JSON are refused outright (146 of 30,000; none without it) -- a live
false-refusal class, so the category is dropped. (An earlier commit message
said "blocked in every punctuated context"; that overstated a worst case as a
certainty.) Codes are at most eight characters so the bare token stays at 24
and is skipped entirely. Even the short form blocks when two tokens are glued
with no whitespace between them -- the design document measured "glued pair" and
reported 4.62; the linter says otherwise. FACT tokens are cloud-authored and
arrive inbound, where the monitor flags and does not block, but any FACT token
the core itself places in an outbound prompt must never be glued to another.
"""

from __future__ import annotations

import re

__all__ = [
    "ATTRIBUTE_CODES", "ATTRIBUTE_MEANINGS", "DERIVED_CODES", "FACT_RE",
    "NOT_RECORDED", "REFERENT_CATEGORIES", "VALUE_KIND", "fact_token", "token_union",
]

ATTRIBUTE_CODES: tuple[str, ...] = (
    "AUTHAMT", "SPENTAMT", "UNSPNTAM", "OVRRUNAM", "PCTSPENT",
    "DATESTRT", "DATEREV", "OWNERREF", "SITEREF", "REFCODE",
    "DELIVQTY", "COMMQTY", "STATNOTE",
)

# The categories a fact can hang off. MONEY, QUANTITY, DATE and IDENTIFIER stop
# being things the cloud refers to directly; they are values of these.
REFERENT_CATEGORIES: tuple[str, ...] = ("PERSON", "ORG", "PROJECT", "LOCATION")

# What kind of value each code carries, which decides how it is canonicalised
# and whether it may enter a derivation.
VALUE_KIND: dict[str, str] = {
    "AUTHAMT": "money", "SPENTAMT": "money", "UNSPNTAM": "money", "OVRRUNAM": "money",
    "PCTSPENT": "ratio", "DATESTRT": "date", "DATEREV": "date",
    "OWNERREF": "person", "SITEREF": "location", "REFCODE": "code",
    "DELIVQTY": "quantity", "COMMQTY": "quantity", "STATNOTE": "note",
}

# Computed locally from a fixed rule table. The cloud can neither request a
# derivation nor supply an operand: a channel that computed DIFFERENCE(x, k) for
# a cloud-chosen k would binary-search a private value.
DERIVED_CODES: frozenset[str] = frozenset({"UNSPNTAM", "OVRRUNAM", "PCTSPENT"})

# Any upper-case run is accepted as the attribute, so a cloud-invented
# ``⟦FACT:….SALARY⟧`` is still recognised as fact-shaped and refused, rather
# than passing through as literal text.
FACT_RE: re.Pattern[str] = re.compile(
    r"⟦FACT:(?P<hex>[0-9a-f]{8})\.(?P<attr>[A-Z][A-Z0-9]{1,7})⟧")

# What each code means, for the drafter. A closed constant like the codes: it
# is the same text for every corpus, so it discloses nothing about any of them.
ATTRIBUTE_MEANINGS: dict[str, str] = {
    "AUTHAMT": "amount authorised (budget authority)",
    "SPENTAMT": "amount spent or committed",
    "UNSPNTAM": "authorised amount not yet spent",
    "OVRRUNAM": "amount spent beyond the authority",
    "PCTSPENT": "share of the authority spent",
    "DATESTRT": "start date", "DATEREV": "revised date",
    "OWNERREF": "owner", "SITEREF": "site",
    "REFCODE": "contract or reference code",
    "DELIVQTY": "quantity delivered", "COMMQTY": "quantity committed",
    "STATNOTE": "status note",
}

# What a reference to an advertised but absent attribute resolves to. Absence is
# the expected case under padding, so it is written, not refused.
#
# Plain words, no brackets. It was "[not recorded]", which is Markdown-active:
# the reintegrator's position checks stand an inert sentinel in for every
# reference, so they did not model it, and written after "![" or before
# "(https://...)" the brackets made an image or link that exists only when the
# attribute is absent (INS5 review). Escaping them is not enough, because a
# backslash the draft puts in front of the reference then escapes the escape.
# The reintegrator refuses to import if this ever holds a character that can
# open structure again.
NOT_RECORDED = "not recorded"

if set(ATTRIBUTE_MEANINGS) != set(ATTRIBUTE_CODES):
    raise RuntimeError("every attribute code needs a meaning")
if len(set(ATTRIBUTE_CODES)) != len(ATTRIBUTE_CODES):
    raise RuntimeError("duplicate attribute code")
if any(len(c) > 8 for c in ATTRIBUTE_CODES):
    raise RuntimeError("attribute codes must be at most 8 characters; see the entropy table")
if set(VALUE_KIND) != set(ATTRIBUTE_CODES):
    raise RuntimeError("every attribute code needs a value kind")


def token_union(*patterns: re.Pattern[str]) -> re.Pattern[str]:
    """One alternation over several token patterns.

    SLOT_RE and FACT_RE both name a group ``hex``, so a plain union does not
    compile. Group names are stripped here; callers re-match a found token
    against its own pattern to read its fields.
    """
    bare = [re.sub(r"\(\?P<\w+>", "(", p.pattern) for p in patterns]
    return re.compile("|".join(f"(?:{b})" for b in bare))


def fact_token(referent_hex: str, attribute: str) -> str:
    token = f"⟦FACT:{referent_hex}.{attribute}⟧"
    if not FACT_RE.fullmatch(token) or attribute not in ATTRIBUTE_CODES:
        raise ValueError("not a valid fact reference")
    return token
