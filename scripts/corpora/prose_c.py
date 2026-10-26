"""Scenario C, prose-c: the figures live in prose, the workbook is a risk register.

All organisation and person names in this scenario are fictitious.

C is the pre-registered test of R1's limit (H2). R1's fact store is built from
table cells only; a value written only in a sentence has no fact and cannot be
referred to. So in C every authority, spend and balance is written in the
memo, the minutes (prose, no table) and the review, and the workbook holds a
risk register whose headers (Risk, Raised by, Date, Severity) map to no
``header_lexicon`` code. ``fact_store`` should find zero structural facts here;
``test_corpus_scenarios.py`` checks that with the real code. The risk cells
still carry the two narrative facts, as A's do.

The project owners are stated in prose too: the minutes' list of those present
and the quarterly statement's per-project parenthetical name each project's
owner, as the statement names its site and contract. The register's 'Raised
by' column names the same people and still maps to no code, because the person
who raised a risk is not the project's owner (``header_lexicon``). Until
2026-09-30 no document stated ownership, and the key's OWNER facts rested on
that column and on who reported what (``eval/corpora/KEY_PRECHECK.md``, C).

The key is authored beside the constants, as A's is, and is PROVISIONAL until
the author audits it (``eval/corpora/KEY_AUDIT.md``). ``derived`` means exactly
"no document states this value", as in B.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from corpora import rba_lexicon as L
from corpora import writers as W

ID = "prose-c"
GOAL = "Summarise the quarter's financial position and the risks to the programme."
GENERATED_BY = "scripts/corpora/prose_c.py"

LARKSPUR, COBALT, FENWICK = "Project Larkspur", "Project Cobalt", "Scheme Fenwick"
L_LEAD, C_LEAD, F_LEAD = "Miriam Achterberg", "Declan Oyelaran", "Harriet Quennell"
ORG, VENDOR = "Pellingham Water Trust", "Holloway Pumpworks"
L_SITE, C_SITE, F_SITE = "Truro", "Hereford", "Lincoln"
L_CONTRACT, C_CONTRACT, F_CONTRACT = "PW-2026-0452", "PW-2026-0619", "PW-2026-0833"

L_AUTH, L_SPENT = Decimal("540000"), Decimal("412905.30")
C_AUTH, C_SPENT = Decimal("96000"), Decimal("88410.00")
F_AUTH, F_SPENT = Decimal("33750"), Decimal("39102.60")
L_UNSPENT, C_UNSPENT, F_OVERRUN = L_AUTH - L_SPENT, C_AUTH - C_SPENT, F_SPENT - F_AUTH
UNITS_MISSED = 128

RISK_ROWS = (   # (project, risk, raised by, date, severity)
    (LARKSPUR, f"{C_SITE} intake failure; tariff revenue fell fifteen percent",
     L_LEAD, date(2026, 8, 12), "High"),
    (COBALT, f"{VENDOR} delivered {UNITS_MISSED} units short of the August order",
     C_LEAD, date(2026, 8, 24), "Medium"),
    (FENWICK, "Scheme spend running ahead of its authority",
     F_LEAD, date(2026, 9, 3), "High"),
)
PROSE_DATES = ("17 September 2026", "10 September 2026", "21 September 2026",
               "22 October 2026", "August 2026")


def _c2(v: Decimal) -> str:
    return f"{v:,.2f}"


# ----------------------------------------------------------------- fact key

REFERENTS: dict[str, list[str]] = {
    "LARKSPUR": [LARKSPUR, "Larkspur"],
    "COBALT": [COBALT, "Cobalt"],
    "FENWICK": [FENWICK, "Fenwick"],
    "VENDOR": [VENDOR, "Holloway"],
    "ORG": [ORG, "Pellingham"],
}

ATTRIBUTES: dict[str, tuple[str, list[str]]] = {
    **L.MONEY_ATTRIBUTES,
    "UNITS_SHORT": L.UNITS_SHORT,
    "REVENUE_FALL_PCT": L.REVENUE_FALL_PCT,
}

# (subject, attribute, value, derived, also_subjects). derived = no document
# states the value.
NUMERIC_FACTS: list[tuple[str, str, float, bool, list[str]]] = [
    ("LARKSPUR", "AUTHORISED", float(L_AUTH), False, []),
    ("LARKSPUR", "SPENT", float(L_SPENT), False, []),
    ("LARKSPUR", "UNSPENT", float(L_UNSPENT), False, []),
    ("COBALT", "AUTHORISED", float(C_AUTH), False, []),
    ("COBALT", "SPENT", float(C_SPENT), False, []),
    ("COBALT", "UNSPENT", float(C_UNSPENT), False, []),
    ("FENWICK", "AUTHORISED", float(F_AUTH), False, []),
    ("FENWICK", "SPENT", float(F_SPENT), False, []),
    ("FENWICK", "OVERRUN", float(F_OVERRUN), False, []),
    ("LARKSPUR", "PCT_SPENT", float(W.pct(L_SPENT, L_AUTH)), True, []),    # 76.5
    ("COBALT", "PCT_SPENT", float(W.pct(C_SPENT, C_AUTH)), True, []),      # 92.1
    ("FENWICK", "PCT_SPENT", float(W.pct(F_SPENT, F_AUTH)), True, []),     # 115.9
    ("VENDOR", "UNITS_SHORT", UNITS_MISSED, False, ["COBALT"]),
]

SURFACE_FACTS: list[tuple[str, str, str, list[str]]] = [
    ("LARKSPUR", "REVENUE_FALL_PCT", "15 percent",
     ["fifteen percent", "15 percent", "15%", "15 per cent"]),
]

STRING_FACTS: list[tuple[str, str, str]] = [
    (s, a, v)
    for s, lead, site, contract in (
        ("LARKSPUR", L_LEAD, L_SITE, L_CONTRACT), ("COBALT", C_LEAD, C_SITE, C_CONTRACT),
        ("FENWICK", F_LEAD, F_SITE, F_CONTRACT))
    for a, v in (("OWNER", lead), ("SITE", site), ("CONTRACT", contract))
]

MASK_PATTERNS: list[str] = [r"PW-\d{4}-\d{4}", *L.DATE_MASKS]   # contract identifiers


def fact_key() -> dict:
    return W.build_key(
        generated_by=GENERATED_BY, scenario=ID, referents=REFERENTS,
        attributes=ATTRIBUTES, numeric_facts=NUMERIC_FACTS,
        surface_facts=SURFACE_FACTS, string_facts=STRING_FACTS,
        mask_patterns=MASK_PATTERNS,
        extra={"provisional": "audited under scope §11 (two AI passes); "
                              "see eval/corpora/KEY_AUDIT.md"})


# ---------------------------------------------------------------- documents

def xlsx_sheets() -> list[W.Sheet]:
    return [("Register", [["Project", "Risk", "Raised by", "Date", "Severity"],
                          *(list(r) for r in RISK_ROWS)])]


MEMO = f"""# Finance memo, 17 September 2026

{LARKSPUR}'s tariff revenue fell fifteen percent after the {C_SITE} intake
failed in August 2026 and customers were supplied from tankers for three weeks.

## Position

{ORG} holds contract {L_CONTRACT} for the {L_SITE} treatment works. The trustees
authorised {_c2(L_AUTH)} USD for {LARKSPUR}; by 10 September 2026 it had spent
{_c2(L_SPENT)} USD, and {_c2(L_UNSPENT)} USD remains for commissioning.

{COBALT}, under contract {C_CONTRACT} at {C_SITE}, has an authority of
{C_AUTH:,.0f} USD and has spent {_c2(C_SPENT)} USD. {VENDOR} delivered
{UNITS_MISSED} units short of the August order, and {C_LEAD} has booked the
shortfall against {COBALT}.

{FENWICK} at {F_SITE} was authorised {_c2(F_AUTH)} USD and has spent
{_c2(F_SPENT)} USD, an overrun of {_c2(F_OVERRUN)} USD.

## Decision

{F_LEAD} will bring a revised scope for {FENWICK} to the trustees on
22 October 2026.
"""


def docx_blocks() -> list[W.Block]:
    return [
        ("h", "Trustee minutes", 1),
        ("p", f"Meeting of 21 September 2026, held at the {L_SITE} office of {ORG}."),
        ("h", "Present", 2),
        ("p", f"{L_LEAD} (chair; owner of {LARKSPUR}), {C_LEAD} (owner of {COBALT}), "
              f"{F_LEAD} (owner of {FENWICK})."),
        ("h", "Finance", 2),
        ("p", f"{L_LEAD} reported that {LARKSPUR} has {_c2(L_UNSPENT)} USD unspent "
              f"of its {_c2(L_AUTH)} USD authority, and that the fall in tariff "
              f"revenue is confined to the {C_SITE} customers."),
        ("p", f"{C_LEAD} confirmed that {COBALT} has {_c2(C_UNSPENT)} USD remaining "
              f"under contract {C_CONTRACT}, and that {VENDOR} has been asked to make "
              f"good the missing units before the end of the quarter."),
        ("p", f"{F_LEAD} reported that {FENWICK} has spent {_c2(F_SPENT)} USD, which "
              f"exceeds its authority of {_c2(F_AUTH)} USD, and that contract "
              f"{F_CONTRACT} does not cover the excess."),
        ("h", "Resolution", 2),
        ("p", f"The trustees asked {F_LEAD} for a revised scope by 22 October 2026. "
              "Carried unanimously."),
    ]


PDF_PAGES = [
    [
        f"Quarterly statement - {ORG}",
        "",
        f"Prepared by {C_LEAD} for the trustees, 17 September 2026.",
        "",
        # The line break before 'fell fifteen percent' is where it was before the owners
        # were added: the binding of that sentence is the pre-check's open question (C).
        f"{LARKSPUR} ({L_SITE}, contract {L_CONTRACT}, owner {L_LEAD}) holds an",
        f"authority of {_c2(L_AUTH)} USD, of which {_c2(L_SPENT)} USD has been spent. "
        "Tariff revenue",
        f"fell fifteen percent after the {C_SITE} intake failure.",
        "",
        f"{COBALT} ({C_SITE}, contract {C_CONTRACT}, owner {C_LEAD}) has spent",
        f"{_c2(C_SPENT)} USD of its {_c2(C_AUTH)} USD authority.",
    ],
    [
        "Quarterly statement - schemes and suppliers",
        "",
        f"{FENWICK} ({F_SITE}, contract {F_CONTRACT}, owner {F_LEAD}) has spent",
        f"{_c2(F_SPENT)} USD against an authority of {_c2(F_AUTH)} USD, an overrun of "
        f"{_c2(F_OVERRUN)} USD.",
        "",
        f"{VENDOR} delivered {UNITS_MISSED} units fewer than the August order for {COBALT}.",
    ],
]


def write_xlsx(path: Path) -> None:
    W.write_xlsx(path, xlsx_sheets())


DOCUMENTS = {
    "risk-register.xlsx": write_xlsx,
    "finance-memo.md": lambda p: W.write_markdown(p, MEMO),
    "trustee-minutes.docx": lambda p: W.write_docx(p, docx_blocks()),
    "quarterly-statement.pdf": lambda p: W.write_pdf(p, PDF_PAGES),
}


# ----------------------------------------------------------------- surfaces

def surface_groups() -> dict[str, list[str]]:
    """Every constant this scenario writes into a document, by kind; see
    ``smoke_q3.surface_groups`` for what is left out and why."""
    amounts = (L_AUTH, L_SPENT, L_UNSPENT, C_AUTH, C_SPENT, C_UNSPENT,
               F_AUTH, F_SPENT, F_OVERRUN)
    return {
        "referents": [s for v in REFERENTS.values() for s in v],
        "people": [L_LEAD, C_LEAD, F_LEAD],
        "sites": [L_SITE, C_SITE, F_SITE],
        "identifiers": [L_CONTRACT, C_CONTRACT, F_CONTRACT],
        "amounts": sorted({s for v in amounts for s in W.money_surfaces(float(v))}),
        "quantities": [str(UNITS_MISSED), f"{UNITS_MISSED} units"],
        "percentages": ["fifteen percent"],
        "dates": sorted({*PROSE_DATES, *(s for r in RISK_ROWS
                                          for s in W.date_surfaces(r[3]))}),
        "risk_text": [r[1] for r in RISK_ROWS],
        "labels": sorted({r[4] for r in RISK_ROWS}),
    }


def surfaces() -> list[str]:
    return W.flatten_surfaces(surface_groups())
