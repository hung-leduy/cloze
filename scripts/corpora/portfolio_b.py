"""Scenario B, portfolio-b: the budget-report family, another organisation.

All organisation and person names in this scenario are fictitious.

What changes from A, and why
----------------------------
B is the out-of-sample corpus for H1 (every r1 run above every baseline run).
It keeps A's shape, a budget workbook with a risk sheet, a memo, minutes with a
spend table and a two-page review, so a difference between A and B is not a
difference of document family. Everything a lexicon or a model could have
fitted to on A is changed:

* a different organisation, vendor, people, sites and identifier scheme;
* four projects rather than three, one of them a trial like A's pilot;
* a different overrun (Trial Osprey, 111.6% of authority) and a deep
  underspend (Project Meridian, 41.5%), where A has one overrun and none;
* the budget sheet's non-key columns reordered, the key (Project) column still
  first, because ``fact_store`` takes the first column as the row key;
* every budget header a *different* synonym from ``tier1_local/header_lexicon.py``
  than A uses (Allocation, Expenditure, Lead, Location, Agreement, Commenced;
  the minutes' table uses Approved and Actuals). 'committed' is avoided: it is
  both a SPENTAMT header synonym there and an RBA lexicon phrase here.

No referent surface is three characters or shorter: a short name matches
inside ordinary words and would make the referent binding and the surface scan
count text the corpus never wrote.

The key is PROVISIONAL until the author audits it against the rendered
documents (``eval/corpora/KEY_AUDIT.md``). Here, unlike A, ``derived`` means
exactly "no document states this value", which is what ``coverage_stated``
takes it to mean; ``test_corpus_scenarios.py`` checks that against the
documents.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from corpora import rba_lexicon as L
from corpora import writers as W

ID = "portfolio-b"
GOAL = "Assess the portfolio's budget position and the main risks to delivery."
GENERATED_BY = "scripts/corpora/portfolio_b.py"

HALCYON, MERIDIAN, TAMARIND, OSPREY = (
    "Project Halcyon", "Project Meridian", "Project Tamarind", "Trial Osprey")
H_LEAD, M_LEAD, T_LEAD, O_LEAD = (
    "Imogen Castellane", "Tobias Fairweather", "Nadia Brennock", "Rhys Pemberton")
ORG, VENDOR = "Veltmoor Civic Works", "Brantley Fabrication"
H_SITE, M_SITE, T_SITE, O_SITE = "Carlisle", "Exeter", "Norwich", "Swindon"
H_CONTRACT, M_CONTRACT, T_CONTRACT, O_CONTRACT = (
    "VC-2026-0311", "VC-2026-0486", "VC-2026-0529", "VC-2026-0774")

H_AUTH, H_SPENT = Decimal("380000"), Decimal("296418.20")
M_AUTH, M_SPENT = Decimal("150000"), Decimal("62310.40")
T_AUTH, T_SPENT = Decimal("210000"), Decimal("203118.90")
O_AUTH, O_SPENT = Decimal("72500"), Decimal("80944.35")
H_UNSPENT, M_UNSPENT, T_UNSPENT = H_AUTH - H_SPENT, M_AUTH - M_SPENT, T_AUTH - T_SPENT
O_OVERRUN = O_SPENT - O_AUTH
UNITS_MISSED = 215

STARTS = (date(2026, 5, 11), date(2026, 6, 22), date(2026, 7, 6), date(2026, 8, 17))
RISK_ROWS = (   # (project, severity, risk, raised by, date)
    (HALCYON, "High",
     f"Ridership revenue fell nine percent after the {M_SITE} depot closure",
     H_LEAD, date(2026, 8, 18)),
    (MERIDIAN, "Low",
     f"Procurement stalled; {M_UNSPENT:,.2f} USD of the allocation is undrawn",
     M_LEAD, date(2026, 8, 26)),
    (TAMARIND, "Medium",
     f"{VENDOR} delivered {UNITS_MISSED} units short of the September commitment",
     T_LEAD, date(2026, 9, 2)),
    (OSPREY, "High",
     f"Expenditure exceeds allocation by {O_OVERRUN:,.2f} USD",
     O_LEAD, date(2026, 9, 9)),
)
PROSE_DATES = ("11 September 2026", "4 September 2026", "9 September 2026",
               "14 September 2026", "15 October 2026")


def _c2(v: Decimal) -> str:
    return f"{v:,.2f}"


# ----------------------------------------------------------------- fact key

REFERENTS: dict[str, list[str]] = {
    "HALCYON": [HALCYON, "Halcyon"],
    "MERIDIAN": [MERIDIAN, "Meridian"],
    "TAMARIND": [TAMARIND, "Tamarind"],
    "OSPREY": [OSPREY, "Osprey"],
    "VENDOR": [VENDOR, "Brantley"],
    "ORG": [ORG, "Veltmoor"],
}

ATTRIBUTES: dict[str, tuple[str, list[str]]] = {
    **L.MONEY_ATTRIBUTES,
    "UNITS_SHORT": L.UNITS_SHORT,
    "REVENUE_FALL_PCT": L.REVENUE_FALL_PCT,
}

# (subject, attribute, value, derived, also_subjects). derived = no document
# states the value.
NUMERIC_FACTS: list[tuple[str, str, float, bool, list[str]]] = [
    ("HALCYON", "AUTHORISED", float(H_AUTH), False, []),
    ("HALCYON", "SPENT", float(H_SPENT), False, []),
    ("HALCYON", "UNSPENT", float(H_UNSPENT), False, []),     # memo
    ("MERIDIAN", "AUTHORISED", float(M_AUTH), False, []),
    ("MERIDIAN", "SPENT", float(M_SPENT), False, []),
    ("MERIDIAN", "UNSPENT", float(M_UNSPENT), False, []),    # risk cell, memo
    ("TAMARIND", "AUTHORISED", float(T_AUTH), False, []),
    ("TAMARIND", "SPENT", float(T_SPENT), False, []),
    ("TAMARIND", "UNSPENT", float(T_UNSPENT), False, []),    # minutes
    ("OSPREY", "AUTHORISED", float(O_AUTH), False, []),
    ("OSPREY", "SPENT", float(O_SPENT), False, []),
    ("OSPREY", "OVERRUN", float(O_OVERRUN), False, []),      # risk cell, review
    ("HALCYON", "PCT_SPENT", float(W.pct(H_SPENT, H_AUTH)), True, []),     # 78.0
    ("MERIDIAN", "PCT_SPENT", float(W.pct(M_SPENT, M_AUTH)), True, []),    # 41.5
    ("TAMARIND", "PCT_SPENT", float(W.pct(T_SPENT, T_AUTH)), True, []),    # 96.7
    ("OSPREY", "PCT_SPENT", float(W.pct(O_SPENT, O_AUTH)), True, []),      # 111.6
    # As in A, stated with two subjects: the vendor delivered short, the lead
    # booked the shortfall against Tamarind. Either scores CORRECT.
    ("VENDOR", "UNITS_SHORT", UNITS_MISSED, False, ["TAMARIND"]),
]

SURFACE_FACTS: list[tuple[str, str, str, list[str]]] = [
    ("HALCYON", "REVENUE_FALL_PCT", "9 percent",
     ["nine percent", "9 percent", "9%", "9 per cent"]),
]

STRING_FACTS: list[tuple[str, str, str]] = [
    (s, a, v)
    for s, lead, site, contract in (
        ("HALCYON", H_LEAD, H_SITE, H_CONTRACT), ("MERIDIAN", M_LEAD, M_SITE, M_CONTRACT),
        ("TAMARIND", T_LEAD, T_SITE, T_CONTRACT), ("OSPREY", O_LEAD, O_SITE, O_CONTRACT))
    for a, v in (("OWNER", lead), ("SITE", site), ("CONTRACT", contract))
]

MASK_PATTERNS: list[str] = [r"VC-\d{4}-\d{4}", *L.DATE_MASKS]   # contract identifiers


def fact_key() -> dict:
    return W.build_key(
        generated_by=GENERATED_BY, scenario=ID, referents=REFERENTS,
        attributes=ATTRIBUTES, numeric_facts=NUMERIC_FACTS,
        surface_facts=SURFACE_FACTS, string_facts=STRING_FACTS,
        mask_patterns=MASK_PATTERNS,
        extra={"provisional": "audited under scope §11 (two AI passes); "
                              "see eval/corpora/KEY_AUDIT.md"})


# ---------------------------------------------------------------- documents

# Key column first, the rest reordered against A's Owner, Site, Start, Budget,
# Spent, Contract. Each header maps to exactly one header_lexicon code.
BUDGET_HEADER = ["Project", "Agreement", "Allocation (USD)", "Lead",
                 "Expenditure (USD)", "Commenced", "Location"]
# The (project, code) cells the budget sheet states; facts_structural on the
# workbook alone should equal len(BUDGET_ROWS) * 6.
BUDGET_ROWS = [
    [HALCYON, H_CONTRACT, int(H_AUTH), H_LEAD, float(H_SPENT), STARTS[0], H_SITE],
    [MERIDIAN, M_CONTRACT, int(M_AUTH), M_LEAD, float(M_SPENT), STARTS[1], M_SITE],
    [TAMARIND, T_CONTRACT, int(T_AUTH), T_LEAD, float(T_SPENT), STARTS[2], T_SITE],
    [OSPREY, O_CONTRACT, int(O_AUTH), O_LEAD, float(O_SPENT), STARTS[3], O_SITE],
]


def xlsx_sheets() -> list[W.Sheet]:
    return [
        ("Portfolio", [BUDGET_HEADER, *BUDGET_ROWS]),
        ("Risk register", [
            ["Project", "Severity", "Risk", "Raised by", "Date"],
            *(list(r) for r in RISK_ROWS),
        ]),
    ]


MEMO = f"""# Portfolio memo, 11 September 2026

{HALCYON}'s ridership revenue fell nine percent after the {M_SITE} depot
closed for resurfacing. The portfolio board attributed the fall to the diverted
routes, not to the {H_SITE} works themselves, which remain on programme.

## Position

{ORG} holds agreement {H_CONTRACT} for the {H_SITE} works. Of the {H_AUTH:,.0f} USD
allocated to {HALCYON}, {_c2(H_SPENT)} USD had been spent by 4 September 2026,
leaving {_c2(H_UNSPENT)} USD for the final resurfacing phase.

{MERIDIAN} has spent only {_c2(M_SPENT)} USD of its {M_AUTH:,.0f} USD allocation
because procurement stalled in {M_SITE}; {_c2(M_UNSPENT)} USD remains undrawn and
{M_LEAD} expects to return part of it.

## Decision

{O_LEAD} will present a recovery plan for {OSPREY} before the board meets
on 15 October 2026. {H_LEAD} asked that the {MERIDIAN} balance not be
reallocated until then.
"""


def docx_blocks() -> list[W.Block]:
    return [
        ("h", "Steering group minutes", 1),
        ("p", f"Meeting of 9 September 2026, held at the {T_SITE} office of {ORG}."),
        ("h", "Attendance", 2),
        ("p", f"{H_LEAD} (chair), {M_LEAD}, {T_LEAD}, {O_LEAD}."),
        ("h", "Delivery", 2),
        ("p", f"{T_LEAD} reported that {VENDOR} delivered {UNITS_MISSED} units short "
              f"of the September commitment and that she has recorded the shortfall "
              f"against {TAMARIND}. Agreement {T_CONTRACT} is unchanged, and "
              f"{_c2(T_UNSPENT)} USD of the {TAMARIND} allocation is unspent."),
        ("p", f"{O_LEAD} confirmed that {OSPREY} has run over its allocation and that "
              f"agreement {O_CONTRACT} does not provide for the excess."),
        ("h", "Approved against actuals", 2),
        ("table", ("Project", "Approved (USD)", "Actuals (USD)"), [
            (OSPREY, _c2(O_AUTH), _c2(O_SPENT)),
            (HALCYON, _c2(H_AUTH), _c2(H_SPENT)),
            (TAMARIND, _c2(T_AUTH), _c2(T_SPENT)),
            (MERIDIAN, _c2(M_AUTH), _c2(M_SPENT)),
        ]),
        ("h", "Actions", 2),
        ("p", f"{H_LEAD} will circulate the revised forecast by 14 September 2026."),
    ]


PDF_PAGES = [
    [
        f"Portfolio review - {ORG}",
        "",
        f"Prepared by {M_LEAD} for the portfolio board, 11 September 2026.",
        "",
        f"{HALCYON} ({H_SITE}, agreement {H_CONTRACT}) has an allocation of",
        f"{_c2(H_AUTH)} USD and has spent {_c2(H_SPENT)} USD. Ridership revenue fell",
        f"nine percent after the {M_SITE} depot closure.",
        "",
        f"{MERIDIAN} ({M_SITE}, agreement {M_CONTRACT}) has spent {_c2(M_SPENT)} USD",
        f"against an allocation of {_c2(M_AUTH)} USD.",
    ],
    [
        "Portfolio review - trials and suppliers",
        "",
        f"{OSPREY} ({O_SITE}, agreement {O_CONTRACT}) has spent {_c2(O_SPENT)} USD",
        f"against an allocation of {_c2(O_AUTH)} USD, an overrun of {_c2(O_OVERRUN)} USD.",
        "",
        f"{TAMARIND} ({T_SITE}, agreement {T_CONTRACT}) has spent {_c2(T_SPENT)} USD of",
        f"{_c2(T_AUTH)} USD. {VENDOR} remains its principal supplier.",
    ],
]


def write_xlsx(path: Path) -> None:
    W.write_xlsx(path, xlsx_sheets())


DOCUMENTS = {
    "portfolio.xlsx": write_xlsx,
    "portfolio-memo.md": lambda p: W.write_markdown(p, MEMO),
    "steering-minutes.docx": lambda p: W.write_docx(p, docx_blocks()),
    "portfolio-review.pdf": lambda p: W.write_pdf(p, PDF_PAGES),
}


# ----------------------------------------------------------------- surfaces

def surface_groups() -> dict[str, list[str]]:
    """Every constant this scenario writes into a document, by kind; see
    ``smoke_q3.surface_groups`` for what is left out and why. The derived
    percentages are left out: no document writes them."""
    amounts = (H_AUTH, H_SPENT, H_UNSPENT, M_AUTH, M_SPENT, M_UNSPENT,
               T_AUTH, T_SPENT, T_UNSPENT, O_AUTH, O_SPENT, O_OVERRUN)
    return {
        "referents": [s for v in REFERENTS.values() for s in v],
        "people": [H_LEAD, M_LEAD, T_LEAD, O_LEAD],
        "sites": [H_SITE, M_SITE, T_SITE, O_SITE],
        "identifiers": [H_CONTRACT, M_CONTRACT, T_CONTRACT, O_CONTRACT],
        "amounts": sorted({s for v in amounts for s in W.money_surfaces(float(v))}),
        "quantities": [str(UNITS_MISSED), f"{UNITS_MISSED} units"],
        "percentages": ["nine percent"],
        "dates": sorted({*PROSE_DATES, *(s for d in (*STARTS, *(r[4] for r in RISK_ROWS))
                                          for s in W.date_surfaces(d))}),
        "risk_text": [r[2] for r in RISK_ROWS],
        "labels": sorted({r[1] for r in RISK_ROWS}),
    }


def surfaces() -> list[str]:
    return W.flatten_surfaces(surface_groups())
