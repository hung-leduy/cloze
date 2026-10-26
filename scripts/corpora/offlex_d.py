"""Scenario D, offlex-d: the budget-report family, headers partly off the lexicon.

All organisation and person names in this scenario are fictitious.

What D tests, and how
---------------------
D is the only test of whether R1's gain depends on the fixed English header
lexicon (H4-D, scope §8.7; decision 4). R1's fact store reads a table cell as a
fact only when ``tier1_local/header_lexicon.py`` maps the cell's column header
to an attribute code; any other header is dropped and counted. A and B use
mapped headers throughout, so on them the structural route reaches every
budget cell. D keeps A's and B's shape, a budget workbook with a risk sheet, a
memo, minutes with a spend table and a two-page review, and changes one thing
that matters: about half of the budget columns carry natural finance headers
the lexicon does not map ('Envelope', 'Outlay to date', 'Responsible officer',
'Depot', 'Kick-off', 'Order ref'; ``attribute_for_header`` returns None for
each). Each is a synonym of the attribute its column carries, not a different
role: the capital sheet's owner column is headed 'Responsible officer', not
'Sponsor', because a sponsor is not the project's owner (the reason
``header_lexicon.py`` refuses to map 'raised by' to OWNERREF), and that column
is the only document source for the capital projects' OWNER in the key.

The split is by column *and* by row, so that no attribute is all-or-nothing:

* The workbook holds two budget sheets from two teams' templates. 'Capital
  works' (Saltmarsh, Weirgate) and 'Harbour services' (Fallowbeck, Lodestar)
  each have three mapped and three unmapped non-key columns, and every one of the
  six header_lexicon codes is mapped on one sheet and unmapped on the other.
* The minutes' table restates every project's authority under a mapped header
  (Approved) and every spend under an unmapped one (Outlay to date).

So the store gets both amounts for the services projects, and the derived
balance, overrun and share with them; for the capital projects it gets the
authority but not the spend, and derives nothing. ``TABLE_ATTRIBUTES`` records
the code each budget column carries whether or not the lexicon maps its
header; the suite counts total table facts from it.

The unmapped-header facts are stated in the tables, where a reader finds them.
They are not moved into prose, which would confound H4-D with H2 (C's test).
The prose restates figures in the proportion B's does. Its attribute wording
is drawn from ``rba_lexicon.py`` ('allocation', 'spent', 'undrawn', 'unspent',
'an overrun of', 'exceeds'), which is frozen at EXP2 and is not edited here.

As in B: a different organisation, people, sites and identifier scheme; four
projects, a deep underspend (Project Saltmarsh, 40.9% of allocation) and an
overrun (Pilot Lodestar, 109.5%); the key (Project) column first in every
table, because ``fact_store`` takes the first column as the row key; 'committed'
avoided; no referent surface of three characters or fewer. The services
scheme is 'Fallowbeck', an invented word, so that the cloud model has no prior
to draw on for it. It replaced 'Juniper', which is also a well-known
network-equipment company; a web search for "Fallowbeck" on 2026-09-27
returned no organisation, product or place of that name.

The key is PROVISIONAL until the author audits it (``eval/corpora/KEY_AUDIT.md``).
``derived`` means exactly "no document states this value", as in B and C.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from corpora import rba_lexicon as L
from corpora import writers as W

ID = "offlex-d"
GOAL = "Review the programme's spending against its budget and the risks to delivery."
GENERATED_BY = "scripts/corpora/offlex_d.py"

SALTMARSH, WEIRGATE, FALLOWBECK, LODESTAR = (
    "Project Saltmarsh", "Project Weirgate", "Scheme Fallowbeck", "Pilot Lodestar")
S_LEAD, W_LEAD, F_LEAD, L_LEAD = (
    "Ottilie Farquhar", "Bastian Greenhalgh", "Leonie Radcliffe", "Caspar Wetherby")
ORG, VENDOR = "Wrenfield Harbour Board", "Tarrant Marine Supplies"
S_SITE, W_SITE, F_SITE, L_SITE = "Whitby", "Falmouth", "Grimsby", "Harwich"
S_CONTRACT, W_CONTRACT, F_CONTRACT, L_CONTRACT = (
    "WHB-0418-26", "WHB-0562-26", "WHB-0691-26", "WHB-0837-26")

S_AUTH, S_SPENT = Decimal("460000"), Decimal("187946.50")
W_AUTH, W_SPENT = Decimal("125000"), Decimal("98340.75")
F_AUTH, F_SPENT = Decimal("238500"), Decimal("229871.40")
L_AUTH, L_SPENT = Decimal("58000"), Decimal("63512.80")
S_UNSPENT, W_UNSPENT, F_UNSPENT = S_AUTH - S_SPENT, W_AUTH - W_SPENT, F_AUTH - F_SPENT
L_OVERRUN = L_SPENT - L_AUTH
UNITS_MISSED = 164

STARTS = (date(2026, 4, 13), date(2026, 6, 1), date(2026, 5, 18), date(2026, 7, 27))
RISK_ROWS = (   # (project, severity, risk, raised by, date)
    (SALTMARSH, "Low",
     f"Dredging consent delayed; {S_UNSPENT:,.2f} USD of the allocation is undrawn",
     S_LEAD, date(2026, 8, 19)),
    (WEIRGATE, "High",
     f"Berthing revenue fell seven percent after the {F_SITE} quay closure",
     W_LEAD, date(2026, 8, 27)),
    (FALLOWBECK, "Medium",
     f"{VENDOR} delivered {UNITS_MISSED} units short of the August commitment",
     F_LEAD, date(2026, 9, 2)),
    (LODESTAR, "High",
     f"Spend exceeds allocation by {L_OVERRUN:,.2f} USD",
     L_LEAD, date(2026, 9, 10)),
)
PROSE_DATES = ("16 September 2026", "9 September 2026", "14 September 2026",
               "18 September 2026", "20 October 2026")


def _c2(v: Decimal) -> str:
    return f"{v:,.2f}"


# ----------------------------------------------------------------- fact key

REFERENTS: dict[str, list[str]] = {
    "SALTMARSH": [SALTMARSH, "Saltmarsh"],
    "WEIRGATE": [WEIRGATE, "Weirgate"],
    "FALLOWBECK": [FALLOWBECK, "Fallowbeck"],
    "LODESTAR": [LODESTAR, "Lodestar"],
    "VENDOR": [VENDOR, "Tarrant"],
    "ORG": [ORG, "Wrenfield"],
}

ATTRIBUTES: dict[str, tuple[str, list[str]]] = {
    **L.MONEY_ATTRIBUTES,
    "UNITS_SHORT": L.UNITS_SHORT,
    "REVENUE_FALL_PCT": L.REVENUE_FALL_PCT,
}

# (subject, attribute, value, derived, also_subjects). derived = no document
# states the value.
NUMERIC_FACTS: list[tuple[str, str, float, bool, list[str]]] = [
    ("SALTMARSH", "AUTHORISED", float(S_AUTH), False, []),
    ("SALTMARSH", "SPENT", float(S_SPENT), False, []),
    ("SALTMARSH", "UNSPENT", float(S_UNSPENT), False, []),   # risk cell, memo
    ("WEIRGATE", "AUTHORISED", float(W_AUTH), False, []),
    ("WEIRGATE", "SPENT", float(W_SPENT), False, []),
    ("WEIRGATE", "UNSPENT", float(W_UNSPENT), False, []),    # memo
    ("FALLOWBECK", "AUTHORISED", float(F_AUTH), False, []),
    ("FALLOWBECK", "SPENT", float(F_SPENT), False, []),
    ("FALLOWBECK", "UNSPENT", float(F_UNSPENT), False, []),  # minutes
    ("LODESTAR", "AUTHORISED", float(L_AUTH), False, []),
    ("LODESTAR", "SPENT", float(L_SPENT), False, []),
    ("LODESTAR", "OVERRUN", float(L_OVERRUN), False, []),    # risk cell, review
    ("SALTMARSH", "PCT_SPENT", float(W.pct(S_SPENT, S_AUTH)), True, []),   # 40.9
    ("WEIRGATE", "PCT_SPENT", float(W.pct(W_SPENT, W_AUTH)), True, []),    # 78.7
    ("FALLOWBECK", "PCT_SPENT", float(W.pct(F_SPENT, F_AUTH)), True, []),  # 96.4
    ("LODESTAR", "PCT_SPENT", float(W.pct(L_SPENT, L_AUTH)), True, []),    # 109.5
    # As in A and B, stated with two subjects: the vendor delivered short, the
    # lead booked the shortfall against Fallowbeck. Either scores CORRECT.
    ("VENDOR", "UNITS_SHORT", UNITS_MISSED, False, ["FALLOWBECK"]),
]

SURFACE_FACTS: list[tuple[str, str, str, list[str]]] = [
    ("WEIRGATE", "REVENUE_FALL_PCT", "7 percent",
     ["seven percent", "7 percent", "7%", "7 per cent"]),
]

STRING_FACTS: list[tuple[str, str, str]] = [
    (s, a, v)
    for s, lead, site, contract in (
        ("SALTMARSH", S_LEAD, S_SITE, S_CONTRACT), ("WEIRGATE", W_LEAD, W_SITE, W_CONTRACT),
        ("FALLOWBECK", F_LEAD, F_SITE, F_CONTRACT), ("LODESTAR", L_LEAD, L_SITE, L_CONTRACT))
    for a, v in (("OWNER", lead), ("SITE", site), ("CONTRACT", contract))
]

MASK_PATTERNS: list[str] = [r"WHB-\d{4}-\d{2}", *L.DATE_MASKS]   # contract identifiers


def fact_key() -> dict:
    return W.build_key(
        generated_by=GENERATED_BY, scenario=ID, referents=REFERENTS,
        attributes=ATTRIBUTES, numeric_facts=NUMERIC_FACTS,
        surface_facts=SURFACE_FACTS, string_facts=STRING_FACTS,
        mask_patterns=MASK_PATTERNS,
        extra={"provisional": "audited under scope §11 (two AI passes); "
                              "see eval/corpora/KEY_AUDIT.md"})


# ---------------------------------------------------------------- documents

# Key column first in every table. Each budget column's header_lexicon code,
# whether or not the lexicon maps its header: ``attribute_for_header`` returns
# the code for the mapped headers and None for the others ('Responsible
# officer', 'Outlay to date (USD)', 'Kick-off', 'Envelope (USD)', 'Depot',
# 'Order ref').
# Each sheet maps three of its six non-key columns, and each code is mapped on
# one sheet and unmapped on the other. The risk register's headers map to
# nothing, as in every scenario.
TABLE_ATTRIBUTES: dict[str, str] = {
    "Responsible officer": "OWNERREF", "Authority (USD)": "AUTHAMT",
    "Outlay to date (USD)": "SPENTAMT", "Location": "SITEREF",
    "Kick-off": "DATESTRT", "Contract": "REFCODE",
    "Envelope (USD)": "AUTHAMT", "Owner": "OWNERREF", "Depot": "SITEREF",
    "Actual spend (USD)": "SPENTAMT", "Order ref": "REFCODE", "Start date": "DATESTRT",
    "Approved (USD)": "AUTHAMT",
}
CAPITAL_HEADER = ["Project", "Responsible officer", "Authority (USD)",
                  "Outlay to date (USD)", "Location", "Kick-off", "Contract"]
CAPITAL_ROWS = [
    [SALTMARSH, S_LEAD, int(S_AUTH), float(S_SPENT), S_SITE, STARTS[0], S_CONTRACT],
    [WEIRGATE, W_LEAD, int(W_AUTH), float(W_SPENT), W_SITE, STARTS[1], W_CONTRACT],
]
SERVICES_HEADER = ["Project", "Envelope (USD)", "Owner", "Depot",
                   "Actual spend (USD)", "Order ref", "Start date"]
SERVICES_ROWS = [
    [FALLOWBECK, int(F_AUTH), F_LEAD, F_SITE, float(F_SPENT), F_CONTRACT, STARTS[2]],
    [LODESTAR, int(L_AUTH), L_LEAD, L_SITE, float(L_SPENT), L_CONTRACT, STARTS[3]],
]
MINUTES_HEADER = ("Project", "Approved (USD)", "Outlay to date (USD)")


def xlsx_sheets() -> list[W.Sheet]:
    return [
        ("Capital works", [CAPITAL_HEADER, *CAPITAL_ROWS]),
        ("Harbour services", [SERVICES_HEADER, *SERVICES_ROWS]),
        ("Risk register", [
            ["Project", "Severity", "Risk", "Raised by", "Date"],
            *(list(r) for r in RISK_ROWS),
        ]),
    ]


MEMO = f"""# Programme memo, 16 September 2026

{WEIRGATE}'s berthing revenue fell seven percent after the {F_SITE} quay
closed for repairs. The programme board attributed the fall to the diverted
sailings, not to the {W_SITE} works themselves, which remain on programme.

## Position

{ORG} holds contract {S_CONTRACT} for the {S_SITE} dredging works. Of the
{S_AUTH:,.0f} USD allocated to {SALTMARSH}, {_c2(S_SPENT)} USD had been spent by
9 September 2026; {_c2(S_UNSPENT)} USD remains undrawn while the dredging consent
is outstanding.

{WEIRGATE} has spent {_c2(W_SPENT)} USD of its {W_AUTH:,.0f} USD allocation, and
{_c2(W_UNSPENT)} USD is unspent for the final quay phase at {W_SITE}.

## Decision

{L_LEAD} will present a recovery plan for {LODESTAR} before the board meets
on 20 October 2026. {S_LEAD} asked that the {SALTMARSH} balance not be
reallocated until then.
"""


def docx_blocks() -> list[W.Block]:
    return [
        ("h", "Programme board minutes", 1),
        ("p", f"Meeting of 14 September 2026, held at the {F_SITE} office of {ORG}."),
        ("h", "Attendance", 2),
        ("p", f"{S_LEAD} (chair), {W_LEAD}, {F_LEAD}, {L_LEAD}."),
        ("h", "Delivery", 2),
        ("p", f"{F_LEAD} reported that {VENDOR} delivered {UNITS_MISSED} units short "
              f"of the August commitment and that she has recorded the shortfall "
              f"against {FALLOWBECK}. Order {F_CONTRACT} is unchanged, and "
              f"{_c2(F_UNSPENT)} USD of the {FALLOWBECK} allocation is unspent."),
        ("p", f"{L_LEAD} confirmed that {LODESTAR} has run over its allocation and that "
              f"order {L_CONTRACT} does not provide for the excess."),
        ("h", "Approved against outlay", 2),
        ("table", MINUTES_HEADER, [
            (LODESTAR, _c2(L_AUTH), _c2(L_SPENT)),
            (SALTMARSH, _c2(S_AUTH), _c2(S_SPENT)),
            (FALLOWBECK, _c2(F_AUTH), _c2(F_SPENT)),
            (WEIRGATE, _c2(W_AUTH), _c2(W_SPENT)),
        ]),
        ("h", "Actions", 2),
        ("p", f"{S_LEAD} will circulate the revised forecast by 18 September 2026."),
    ]


PDF_PAGES = [
    [
        f"Programme review - {ORG}",
        "",
        f"Prepared by {W_LEAD} for the programme board, 16 September 2026.",
        "",
        f"{SALTMARSH} ({S_SITE}, contract {S_CONTRACT}) has an allocation of",
        f"{_c2(S_AUTH)} USD and has spent {_c2(S_SPENT)} USD.",
        "",
        f"{WEIRGATE} ({W_SITE}, contract {W_CONTRACT}) has spent {_c2(W_SPENT)} USD",
        f"against an allocation of {_c2(W_AUTH)} USD.",
        f"Berthing revenue fell seven percent after the {F_SITE} quay closure.",
    ],
    [
        "Programme review - services and suppliers",
        "",
        f"{LODESTAR} ({L_SITE}, order {L_CONTRACT}) has spent {_c2(L_SPENT)} USD",
        f"against an allocation of {_c2(L_AUTH)} USD, an overrun of {_c2(L_OVERRUN)} USD.",
        "",
        f"{FALLOWBECK} ({F_SITE}, order {F_CONTRACT}) has spent {_c2(F_SPENT)} USD of",
        f"{_c2(F_AUTH)} USD. {VENDOR} remains its principal supplier.",
    ],
]


def write_xlsx(path: Path) -> None:
    W.write_xlsx(path, xlsx_sheets())


DOCUMENTS = {
    "programme.xlsx": write_xlsx,
    "programme-memo.md": lambda p: W.write_markdown(p, MEMO),
    "board-minutes.docx": lambda p: W.write_docx(p, docx_blocks()),
    "programme-review.pdf": lambda p: W.write_pdf(p, PDF_PAGES),
}


# ----------------------------------------------------------------- surfaces

def surface_groups() -> dict[str, list[str]]:
    """Every constant this scenario writes into a document, by kind; see
    ``smoke_q3.surface_groups`` for what is left out and why. The derived
    percentages are left out: no document writes them."""
    amounts = (S_AUTH, S_SPENT, S_UNSPENT, W_AUTH, W_SPENT, W_UNSPENT,
               F_AUTH, F_SPENT, F_UNSPENT, L_AUTH, L_SPENT, L_OVERRUN)
    return {
        "referents": [s for v in REFERENTS.values() for s in v],
        "people": [S_LEAD, W_LEAD, F_LEAD, L_LEAD],
        "sites": [S_SITE, W_SITE, F_SITE, L_SITE],
        "identifiers": [S_CONTRACT, W_CONTRACT, F_CONTRACT, L_CONTRACT],
        "amounts": sorted({s for v in amounts for s in W.money_surfaces(float(v))}),
        "quantities": [str(UNITS_MISSED), f"{UNITS_MISSED} units"],
        "percentages": ["seven percent"],
        "dates": sorted({*PROSE_DATES, *(s for d in (*STARTS, *(r[4] for r in RISK_ROWS))
                                          for s in W.date_surfaces(d))}),
        "risk_text": [r[2] for r in RISK_ROWS],
        "labels": sorted({r[1] for r in RISK_ROWS}),
    }


def surfaces() -> list[str]:
    return W.flatten_surfaces(surface_groups())
