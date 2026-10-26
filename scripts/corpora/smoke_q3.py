"""Scenario A, smoke-q3: the corpus every pilot run was made on.

All organisation and person names in this scenario are fictitious.

Four documents, one scenario
----------------------------
D5 makes ingestion first-class, so the corpus covers all four loaders:

* ``budget.xlsx``           two sheets, so per-cell offsets and the sheet
                            boundary are exercised
* ``steering-memo.md``      headings and prose
* ``board-minutes.docx``    headings, prose and a table
* ``quarterly-review.pdf``  two pages, so the per-page block contract is
                            exercised and page two proves blocks are not
                            collapsed

The same entities appear in more than one document on purpose. Slot ids are
``HMAC(salt, category + text)``, so an entity seen twice must get the *same*
id, and the session table is what merges them; a corpus where every document
had disjoint entities would never test that path.

Frozen. The documents are pinned by sha256 to what the pre-split generator
wrote at b06ed46, and the key to what the INS1 generator wrote (ecae9dd); both
pins are in ``backend/tests/unit/test_corpus_scenarios.py``. An edit here that
changes a byte of either renames every document or key the pilot recorded.
The amounts are named constants so that the documents, the key and
``surfaces()`` are written from one source; the byte pins are what show that
naming them changed nothing.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from corpora import rba_lexicon as L
from corpora import writers as W

ID = "smoke-q3"
# The goal eval/tasks.json has always given this corpus. It names no entity
# and no value, so it may cross the boundary as the user's own words.
GOAL = "Assess the Q3 budget position and the risks to the delivery schedule."
# Kept as the pre-split script's path: it is a field of the pinned key.
GENERATED_BY = "scripts/make_smoke_corpus.py"

PROJECT, PROJECT2, PILOT = "Project Zephyr", "Project Aurora", "Pilot Kestrel"
LEAD, ANALYST, DIRECTOR = "Sarah Whitfield", "Daniel Okoye", "Priya Ramanathan"
ORG, VENDOR = "Northbridge Analytics", "Calder Logistics"
SITE, SITE2, SITE3 = "Manchester", "Leeds", "Bristol"
CONTRACT, CONTRACT2 = "NB-2026-0917", "NB-2026-1044"
CONTRACT3 = "NB-2026-1187"

# Amounts. Authorities are written to the sheet as integers and spends as
# floats, exactly as the pre-split script did, because openpyxl serialises the
# two differently and the xlsx bytes are pinned.
Z_AUTH, Z_SPENT = Decimal("250000"), Decimal("187432.55")
A_AUTH, A_SPENT = Decimal("120000"), Decimal("98210.00")
K_AUTH, K_SPENT = Decimal("45000"), Decimal("51237.75")
Z_UNSPENT, A_UNSPENT, K_OVERRUN = Z_AUTH - Z_SPENT, A_AUTH - A_SPENT, K_SPENT - K_AUTH
UNITS_MISSED = 340

Z_START, A_START, K_START = date(2026, 6, 1), date(2026, 7, 15), date(2026, 8, 3)
RISK_DATES = (date(2026, 8, 20), date(2026, 8, 4), date(2026, 8, 28))
RISK_TEXT = (f"{SITE2} pilot cancelled; revenue fell twelve percent",
             f"{VENDOR} missed {UNITS_MISSED} units against the July commitment",
             f"Spend exceeds budget by {K_OVERRUN:,.2f} USD")
SEVERITIES = ("High", "Medium", "High")
# Every date the prose writes, as it writes it.
PROSE_DATES = ("22 August 2026", "20 August 2026", "30 September 2026",
               "28 August 2026", "25 August 2026", "August 2026", "2027")


def _c2(v: Decimal) -> str:
    return f"{v:,.2f}"


# ----------------------------------------------------------------- fact key
# The gold answer key for the faithfulness metric, authored here beside the
# constants that write the four documents. Two properties follow from the
# location and neither would survive extracting the key from the corpus: it
# cannot drift from what the documents say, and it shares no code path with
# any arm being measured, so no arm can score itself.
#
# `derived` marks a computed value (Zephyr's 62,567.45 is written out three
# times but is still marked derived, as it was when the pilot was scored;
# Aurora's 21,790.00 is only implied by two figures that are). `narrative`
# marks a fact the slot vocabulary cannot express at all. Both belong in the
# key: without the second, ORACLE is charged with fabrication for reporting
# something true.

REFERENTS: dict[str, list[str]] = {
    "ZEPHYR": [PROJECT, "Zephyr"],
    "AURORA": [PROJECT2, "Aurora"],
    "KESTREL": [PILOT, "Kestrel"],
    "VENDOR": [VENDOR, "Calder"],
    "ORG": [ORG, "Northbridge"],
}

ATTRIBUTES: dict[str, tuple[str, list[str]]] = {
    **L.MONEY_ATTRIBUTES,
    "UNITS_SHORT": L.UNITS_SHORT,
    "REVENUE_FALL_PCT": L.REVENUE_FALL_PCT,
}

# (subject, attribute, value, derived, also_subjects)
NUMERIC_FACTS: list[tuple[str, str, float, bool, list[str]]] = [
    ("ZEPHYR", "AUTHORISED", float(Z_AUTH), False, []),
    ("ZEPHYR", "SPENT", float(Z_SPENT), False, []),
    ("ZEPHYR", "UNSPENT", float(Z_UNSPENT), True, []),
    ("AURORA", "AUTHORISED", float(A_AUTH), False, []),
    ("AURORA", "SPENT", float(A_SPENT), False, []),
    ("AURORA", "UNSPENT", float(A_UNSPENT), True, []),
    ("KESTREL", "AUTHORISED", float(K_AUTH), False, []),
    ("KESTREL", "SPENT", float(K_SPENT), False, []),
    ("KESTREL", "OVERRUN", float(K_OVERRUN), True, []),
    ("ZEPHYR", "PCT_SPENT", float(W.pct(Z_SPENT, Z_AUTH)), True, []),    # 75.0
    ("AURORA", "PCT_SPENT", float(W.pct(A_SPENT, A_AUTH)), True, []),    # 81.8
    ("KESTREL", "PCT_SPENT", float(W.pct(K_SPENT, K_AUTH)), True, []),   # 113.9
    # The corpus states this twice with two different subjects — the vendor
    # missed the units, the analyst booked the miss against Aurora — and both
    # spellings are true. Either subject scores CORRECT.
    ("VENDOR", "UNITS_SHORT", UNITS_MISSED, False, ["AURORA"]),
]

# Facts whose gold value is not a numeral. Matched by surface, never by the
# numeric scan, so "twelve percent" and "12%" are the same fact and neither is
# fabrication.
SURFACE_FACTS: list[tuple[str, str, str, list[str]]] = [
    ("ZEPHYR", "REVENUE_FALL_PCT", "12 percent",
     ["twelve percent", "12 percent", "12%", "12 per cent"]),
]

# String-valued facts. They do not enter the numeral scan; they carry coverage
# and, later, prose-name agreement.
STRING_FACTS: list[tuple[str, str, str]] = [
    ("ZEPHYR", "OWNER", LEAD), ("ZEPHYR", "SITE", SITE), ("ZEPHYR", "CONTRACT", CONTRACT),
    ("AURORA", "OWNER", ANALYST), ("AURORA", "SITE", SITE2), ("AURORA", "CONTRACT", CONTRACT2),
    ("KESTREL", "OWNER", DIRECTOR), ("KESTREL", "SITE", SITE3), ("KESTREL", "CONTRACT", CONTRACT3),
]

# Things the report may legitimately say that carry no gold value, and whose
# digits must not be scanned as candidate fabrications. Measured on the first
# archived report: 39 of its 57 numerals are identifier and date fragments, so
# without these the numerals-outside-key rate is noise rather than a
# measurement. They live in the key rather than in faithfulness.py, so a change
# to them changes the key's SHA, which every measurement scored against it
# records.
MASK_PATTERNS: list[str] = [r"NB-\d{4}-\d{4}", *L.DATE_MASKS]   # contract identifiers


def fact_key() -> dict:
    """The gold key as plain data, deterministic across runs."""
    return W.build_key(
        generated_by=GENERATED_BY, scenario=ID, referents=REFERENTS,
        attributes=ATTRIBUTES, numeric_facts=NUMERIC_FACTS,
        surface_facts=SURFACE_FACTS, string_facts=STRING_FACTS,
        mask_patterns=MASK_PATTERNS)


def write_fact_key(path: Path) -> None:
    path.write_text(W.dump_key(fact_key()), encoding="utf-8")


# ---------------------------------------------------------------- documents

def xlsx_sheets() -> list[W.Sheet]:
    return [
        ("Budget", [
            ["Project", "Owner", "Site", "Start", "Budget (USD)", "Spent", "Contract"],
            [PROJECT, LEAD, SITE, Z_START, int(Z_AUTH), float(Z_SPENT), CONTRACT],
            [PROJECT2, ANALYST, SITE2, A_START, int(A_AUTH), float(A_SPENT), CONTRACT2],
            [PILOT, DIRECTOR, SITE3, K_START, int(K_AUTH), float(K_SPENT), CONTRACT3],
        ]),
        ("Risks", [
            ["Project", "Risk", "Raised by", "Date", "Severity"],
            *([name, risk, who, when, sev] for name, risk, who, when, sev in zip(
                (PROJECT, PROJECT2, PILOT), RISK_TEXT, (LEAD, ANALYST, DIRECTOR),
                RISK_DATES, SEVERITIES, strict=True)),
        ]),
    ]


MEMO = f"""# Steering memo, 22 August 2026

{PROJECT}'s Q3 revenue fell twelve percent after the {SITE2} pilot was cancelled
in August. The steering committee attributed the shortfall to the delayed
migration of the {SITE3} fulfilment centre, which had been scheduled for
completion before the quarter closed.

## Position

{ORG} holds contract {CONTRACT} for the {SITE} site. Of the {Z_AUTH:,.0f} USD
authorised, {_c2(Z_SPENT)} USD had been spent by 20 August 2026, leaving {_c2(Z_UNSPENT)}
USD held against the remaining milestones.

{VENDOR} delivered {UNITS_MISSED} units fewer than the July commitment, and {ANALYST}
recorded the shortfall against {PROJECT2} rather than against the pilot.

## Decision

{LEAD} raised the risk in the June review and recommended deferring the launch
until the following year. {DIRECTOR} asked for a revised plan before the
committee meets again on 30 September 2026.
"""


def docx_blocks() -> list[W.Block]:
    return [
        ("h", "Board minutes", 1),
        ("p", f"Meeting of 28 August 2026, held at the {SITE} office of {ORG}."),
        ("h", "Present", 2),
        ("p", f"{LEAD} (chair), {ANALYST}, {DIRECTOR}."),
        ("h", "Matters arising", 2),
        ("p", f"The board reviewed {PROJECT} following the cancellation of the {SITE2} "
              f"pilot. {LEAD} confirmed that contract {CONTRACT} remains in force and "
              f"that {_c2(Z_UNSPENT)} USD of the authorised budget is unspent."),
        ("p", f"{ANALYST} reported that {VENDOR} had missed the July commitment by "
              f"{UNITS_MISSED} units, and that {PROJECT2} would absorb the delay without "
              f"a change to contract {CONTRACT2}."),
        ("h", "Spend against authority", 2),
        ("table", ("Project", "Authorised (USD)", "Spent (USD)"), [
            (PROJECT, _c2(Z_AUTH), _c2(Z_SPENT)),
            (PROJECT2, _c2(A_AUTH), _c2(A_SPENT)),
            (PILOT, _c2(K_AUTH), _c2(K_SPENT)),
        ]),
        ("h", "Resolution", 2),
        ("p", f"{DIRECTOR} moved that the launch be deferred to 2027 and that a revised "
              "plan be tabled on 30 September 2026. Carried unanimously."),
    ]


PDF_PAGES = [
    [
        f"Quarterly review - {PROJECT}",
        "",
        f"Prepared by {LEAD} for the board of {ORG}, 25 August 2026.",
        "",
        f"Revenue for the quarter fell twelve percent against plan. The {SITE2}",
        f"pilot was cancelled in August 2026 and the {SITE3} migration slipped",
        "past the quarter end.",
        "",
        f"Contract {CONTRACT} covers the {SITE} site. Authorised spend stands at",
        f"{_c2(Z_AUTH)} USD, of which {_c2(Z_SPENT)} USD was committed by 20 August 2026.",
        f"The unspent balance of {_c2(Z_UNSPENT)} USD is held against the remaining",
        "milestones and is not released before the review on 30 September 2026.",
    ],
    [
        "Quarterly review - risks and vendors",
        "",
        f"{VENDOR} delivered {UNITS_MISSED} units fewer than the July commitment. {ANALYST}",
        f"recorded the shortfall against {PROJECT2}, which carries contract",
        f"{CONTRACT2} and is unaffected by the {SITE2} decision.",
        "",
        f"{PILOT} has spent {_c2(K_SPENT)} USD against an authority of {_c2(K_AUTH)} USD,",
        f"an overrun of {_c2(K_OVERRUN)} USD. {DIRECTOR} has asked for a revised plan.",
    ],
]


def write_xlsx(path: Path) -> None:
    W.write_xlsx(path, xlsx_sheets())


def write_markdown(path: Path) -> None:
    W.write_markdown(path, MEMO)


def write_docx(path: Path) -> None:
    W.write_docx(path, docx_blocks())


DOCUMENTS = {
    "budget.xlsx": write_xlsx,
    "steering-memo.md": write_markdown,
    "board-minutes.docx": write_docx,
    "quarterly-review.pdf": lambda p: W.write_pdf(p, PDF_PAGES),
}


# ----------------------------------------------------------------- surfaces

def surface_groups() -> dict[str, list[str]]:
    """Every constant this scenario writes into a document, by kind.

    The generator-surface scan (X4(a)) reads this. Headers, headings and the
    template prose around the values are not surfaces: they name no entity and
    carry no value, and some of them ("budget", "Q3") are the user's own goal.
    Two groups are ordinary English words ("High", "Medium", and "Zephyr" is a
    dictionary word too); a consumer that matches case-insensitively or inside
    words will hit them in text the corpus never touched.
    """
    amounts = (Z_AUTH, Z_SPENT, Z_UNSPENT, A_AUTH, A_SPENT, A_UNSPENT,
               K_AUTH, K_SPENT, K_OVERRUN)
    return {
        "referents": [s for v in REFERENTS.values() for s in v],
        "people": [LEAD, ANALYST, DIRECTOR],
        "sites": [SITE, SITE2, SITE3],
        "identifiers": [CONTRACT, CONTRACT2, CONTRACT3],
        # Every amount a document writes, and the derived balance no document
        # writes (A_UNSPENT), in each spelling money_surfaces gives.
        "amounts": sorted({s for v in amounts for s in W.money_surfaces(float(v))}),
        "quantities": [str(UNITS_MISSED), f"{UNITS_MISSED} units"],
        "percentages": ["twelve percent"],
        "dates": sorted({*PROSE_DATES, *(s for d in (Z_START, A_START, K_START, *RISK_DATES)
                                          for s in W.date_surfaces(d))}),
        "risk_text": list(RISK_TEXT),
        "labels": sorted(set(SEVERITIES)),
    }


def surfaces() -> list[str]:
    return W.flatten_surfaces(surface_groups())
