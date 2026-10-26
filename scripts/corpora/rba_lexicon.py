"""The RBA key's attribute lexicon and mask patterns, shared by every scenario.

This is the *faithfulness key's* lexicon: the phrases that bind a numeral in a
report to an attribute when Role-Binding Accuracy scores it. It is not
``backend/src/privdeep/tier1_local/header_lexicon.py``, which maps column
headers to R1's attribute codes inside the pipeline. The plan's EXP2 lexicon
fix changes this one; corpus B's headers are drawn from the other.

Every scenario's key takes the money attributes from here, so one fix reaches
all three corpora and a cross-corpus comparison is made with one instrument.
Scenario-specific narrative attributes (a unit shortfall, a revenue fall) are
added by the scenario beside its own constants.
"""

from __future__ import annotations

__all__ = ["DATE_MASKS", "MONEY_ATTRIBUTES", "UNITS_SHORT", "REVENUE_FALL_PCT"]

# EXP2 (2026-10-06, by the AI assistant): the one-time fix the author's 63 blind
# development labels confirmed (eval/calibration/EXP2.md). Each entry marked "EXP2"
# repairs an attribute-axis disagreement in which the label agreed with the key and
# the metric did not, and whose cause was a missing phrase: share spent, consumption
# rate and "% of authorised funds" (PCT_SPENT, the expected PCT_SPENT->AUTHORISED
# case), "has been drawn" (SPENT), "headroom" (UNSPENT), "exceeded authorised budget
# by" (OVERRUN), "revenue shortfall" (REVENUE_FALL_PCT). Disagreements caused by the
# nearest-term rule or by an ambiguous phrase are not fixed here: that would change
# the scorer, not the lexicon. The pre-fix keys are kept in eval/calibration/prefix_keys/.
#
# Attribute lexicons. Matching is longest-phrase-first and non-overlapping, so
# a multi-word entry consumes the words a shorter entry would otherwise claim:
# "exceeds budget by" takes OVERRUN's side of "budget", and "authorised spend"
# takes AUTHORISED's side of "spend". Order within a list does not matter;
# length does.
MONEY_ATTRIBUTES: dict[str, tuple[str, list[str]]] = {
    "AUTHORISED": ("authorised budget", [
        "authorised budget", "authorized budget", "budget authority",
        "authorised spend", "authorized spend", "authority of", "an authority of",
        "authorised", "authorized", "authority", "budget", "allocation",
        "allocated", "approved",
    ]),
    "SPENT": ("amount spent", [
        "had been spent", "has been spent", "was committed", "were committed",
        "has spent", "have spent", "spent", "spend", "committed",
        "expenditure", "outlay", "disbursed",
        "has been drawn", "drawn",                                  # EXP2
    ]),
    "UNSPENT": ("unspent balance", [
        "unspent balance", "remaining balance", "is unspent", "held against",
        "uncommitted", "unspent", "unused", "undrawn", "remaining",
        "headroom",                                                 # EXP2
    ]),
    "OVERRUN": ("overspend against authority", [
        "exceeds budget by", "exceeds the budget by", "over budget by",
        "an overrun of", "overrun", "overspend", "exceeds", "in excess of",
        "exceeded authorised budget by",                            # EXP2
    ]),
    # Added after the first R1 run wrote three correct percentages (75.0%, 81.8%,
    # 113.9%) that the key did not contain, so the metric scored true values as
    # fabrication. Derivable from stated figures by the same arithmetic as the
    # derived balances; no document states them.
    "PCT_SPENT": ("share of authority spent", [
        "share of authority spent", "share of authority utilised", "share of authority used",
        "percentage of authority", "share of authority", "percentage spent", "percent spent",
        "spend share", "utilised",
        "share spent", "consumption rate", "of authorised funds",   # EXP2
    ]),
}

# The two narrative attributes scenario A introduced. B and C reuse them with
# their own values, so the lexicon a report is scored with does not vary with
# the corpus beyond what the corpus states.
UNITS_SHORT: tuple[str, list[str]] = ("units short of the commitment", [
    "units fewer than", "units short of", "units fewer", "units short",
    "units against", "units",
])
REVENUE_FALL_PCT: tuple[str, list[str]] = ("revenue decline", [
    "revenue for the quarter fell", "revenue fell", "revenue declined",
    "fell", "declined", "decline",
    "revenue shortfall",                                            # EXP2
])

# Masks for text a report may legitimately write that carries no gold value.
# A scenario prepends its own identifier pattern. The last three were added
# after the nine pilot runs (INS1): the oracle reports write "by 28 August" and
# "20-28 August" without a year and number their lists "(1) ... (4)", and each
# of those digits was counted as a numeral outside the key.
_MONTH = (r"(?:January|February|March|April|May|June|July|August|September"
          r"|October|November|December)")
DATE_MASKS: list[str] = [
    r"\d{4}-\d{2}-\d{2}(?:[T ][\d:]+)?",                 # ISO dates from xlsx cells
    r"\b\d{1,2}\s+" + _MONTH + r"\s+\d{4}\b",            # 20 August 2026
    r"\b" + _MONTH + r"\s+\d{4}\b",                      # August 2026
    r"\bQ[1-4]\b",
    r"\b\d{1,2}\s*(?:[-\u2013\u2014]|to)\s*\d{1,2}\s+" + _MONTH + r"\b",  # 20-28 August
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+" + _MONTH + r"\b",    # 20 August, 20th August
    r"\(\d{1,2}\)",                                     # (1) (2) enumerations
]
