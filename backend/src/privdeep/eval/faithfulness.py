"""Role-Binding Accuracy: does the report attach the right value to the right thing?

The first live run produced a report with no private value in the trace and the
user's own figures in the wrong roles — Zephyr's unspent balance called a
"shortfall", money correct in 2 placements of 19. The judge could not see any of
it, because the judge never reads the corpus and scores coherence, which a
confidently wrong report has in abundance. Invariant 4 could not see it either:
mechanical grounding checks that a number is *backed*, not what it is attached
to. This module is the instrument for the thing neither of them measures.

It is local, deterministic, and reads only rendered Markdown, which all four
arms produce. No judge, no cloud, no cost.

What it does not do, and why
----------------------------
It does not score at sentence level. The design document measured that on the
archived pilot report (untracked; no test pins the count): 13 of 18 gold-value
occurrences sit in sentences hitting more than one attribute lexicon. And for

    "Of the 250,000.00 USD authorised for Project Zephyr, 187,432.55 USD had
     been committed, leaving 62,567.45 USD uncommitted"

a sentence-scoped rule assigns every numeral the same three candidate
attributes and returns **byte-identical output when the three values are
permuted**. Permutation inside one sentence is precisely the failure the metric
exists to catch, so a rule blind to it is not a candidate.

Nearest-lexicon-term scoped to the *sentence* does not survive either, for a
reason visible by hand on the corpus's own modal sentence: in the line above,
``187,432.55`` sits 2 characters after "authorised" and 14 before "committed",
so the nearest term binds a correct sentence to the wrong attribute.

So the scopes are split, and asymmetrically, because the two bindings are
different linguistic objects:

* **attributes are predicate-level** and bind within the *clause*. Clause
  scoping recovers all three values in the sentence above, and still differs
  under permutation.
* **referents are discourse-level** and bind within the *sentence*, falling
  back to the last referent named earlier in the paragraph. Antecedents cross
  clauses freely; attributes do not.

Both are proxies for syntax, and neither is a parser. The residual error is not
hidden: every occurrence records the scope that resolved it, so disagreement
with the hand labelling is measurable rather than assumed. `scripts/calibrate_faithfulness.py`
reports that agreement, and the paper cites the instrument with it.

Populations, which must not be conflated
----------------------------------------
This module counts **occurrences of a gold value in the report**. The hand
score quoted elsewhere ("50/75 placements wrong") counts **entity-string
placements**, a different and larger population over the same text. A paper
sentence may cite either; it may not mix them.

No pool, no number
------------------
Every rate is ``None`` when its pool is empty, and `FaithfulnessResult.to_json`
writes that as JSON ``null``. A 0.0 there would read as "every binding wrong"
when the report made no binding at all: a report whose sentences state figures
without naming the project they belong to (the modal shape on this corpus), or
one that says nothing checkable, would score the worst possible RBA and pull an
arm mean down with a number that measured nothing. Consumers exclude nulls and
print the n they averaged over.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from privdeep.tier3_reconcile.citation_grounder import _NUM_RE, _SENT_SPLIT, _YEAR_RE

__all__ = [
    "FactKey", "Occurrence", "FaithfulnessResult",
    "CORRECT", "MISBOUND", "PARTIAL", "UNBOUND", "AMBIGUOUS", "FABRICATED",
    "MATCH", "MISMATCH", "UNRESOLVED", "MAX_BIND_DISTANCE",
    "de_escape", "load_key", "score",
]

CORRECT = "CORRECT"
MISBOUND = "MISBOUND"
PARTIAL = "PARTIAL"
UNBOUND = "UNBOUND"
AMBIGUOUS = "AMBIGUOUS"
FABRICATED = "FABRICATED"

# Per-axis outcomes. The two bindings are scored separately because they fail
# separately and, on this corpus, at very different rates: the design document
# counted 14 of 18 gold-value occurrences in the archived pilot report naming no
# referent (a count on an untracked file, pinned by no test), so one combined
# verdict reports mostly on how often the prose names a project. Attribute
# accuracy is where the power is; RBA, the conjunction, keeps its own denominator.
MATCH = "MATCH"
MISMATCH = "MISMATCH"
UNRESOLVED = "UNRESOLVED"

# Largest character gap between a numeral and a lexicon term that may bind it.
# Without a cap the sentence-level fallback reaches across a whole sentence:
# measured on the archived report, it bound "45000 has been flagged as falling
# against plan" to AUTHORISED via a "budget" ~130 characters away in a later
# clause. `scripts/calibrate_faithfulness.py` sweeps this.
MAX_BIND_DISTANCE = 80

# The verdicts that share a denominator. AMBIGUOUS is reported beside RBA and
# never folded into it: an occurrence the rule declines to resolve is not
# evidence either way, and counting it as a failure would let a report improve
# its score by naming fewer projects per sentence.
_SCORED = (CORRECT, MISBOUND, PARTIAL, UNBOUND)
_RESOLVED = (MATCH, MISMATCH)

_MD_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
_TAG = re.compile(r"<[^>]+>")
_PARA_SPLIT = re.compile(r"\n\s*\n")
# A comma that ends a clause is followed by whitespace; a comma inside
# "250,000" is followed by a digit. That distinction is the whole guard.
_CLAUSE_SPLIT = re.compile(r"(?<=[,;:])\s+|\s+[\u2014\u2013-]{1,2}\s+")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def _surface_regex(surface: str) -> re.Pattern[str]:
    """A surface fact's spelling, bounded by lookarounds rather than ``\\b``.

    ``\\b`` after ``%`` needs a word character to follow, so ``\\b12%\\b``
    matched "12%" only when a letter followed it and missed it before a space or
    full stop. The miss was silent: the numeral scan then read the same "12%" as
    12.0 and filed the revenue fall, bound right or wrong, as a numeral outside
    the key. The guards mirror the numeral scan's: no word character on either
    side, and no decimal separator joining a longer number ("0.12%").
    """
    return re.compile(r"(?<!\w)(?<!\d[.,])" + re.escape(surface) + r"(?!\w)(?![.,]\d)",
                      re.IGNORECASE)


def de_escape(markdown: str) -> str:
    """Strip Markdown backslash escapes, for every arm alike.

    The reintegrator escapes private values so they cannot restructure the
    page; the oracle's report is never escaped. Measured on the first live run:
    ``187,432.55`` occurs 0 times in the archived report raw and twice after
    de-escaping, so a metric that skips this step reads the private arm as
    having said nothing. Applying it to one arm only would be worse than
    skipping it, which is why it lives here rather than in a driver.
    """
    return _MD_ESCAPE.sub(r"\1", markdown)


def _norm_number(raw: str) -> float | None:
    t = raw.strip().rstrip("%").replace(",", "").replace("\u2212", "-")
    try:
        return round(float(t), 2)
    except ValueError:
        return None


@dataclass(frozen=True)
class FactKey:
    """The authored gold key, as emitted beside the corpus."""

    referents: dict[str, list[str]]
    attributes: dict[str, list[str]]
    facts: list[dict[str, Any]]
    string_facts: list[dict[str, Any]]
    mask_patterns: list[str]

    # -- derived indexes ---------------------------------------------------
    @property
    def by_value(self) -> dict[float, list[tuple[str, str]]]:
        out: dict[float, list[tuple[str, str]]] = {}
        for f in self.facts:
            if f.get("match") != "numeric":
                continue
            v = round(float(f["value"]), 2)
            for subj in f["subjects"]:
                out.setdefault(v, []).append((subj, f["attribute"]))
        return out

    def referent_regex(self) -> re.Pattern[str]:
        surfaces = sorted(
            {s for v in self.referents.values() for s in v},
            key=lambda s: (-len(s), s))
        return re.compile(r"\b(?:" + "|".join(re.escape(s) for s in surfaces) + r")\b")

    def referent_of(self, surface: str) -> str | None:
        low = surface.casefold()
        for key, surfaces in self.referents.items():
            if any(s.casefold() == low for s in surfaces):
                return key
        return None

    def lexicon_regex(self) -> tuple[re.Pattern[str], dict[str, str]]:
        """One alternation, longest phrase first, so it is a longest match.

        Python alternation is first-match-wins at a position and `finditer` is
        non-overlapping left to right, so sorting by descending length makes
        "exceeds budget by" consume the "budget" that AUTHORISED would
        otherwise claim, and "authorised spend" consume SPENT's "spend".
        """
        table: dict[str, str] = {}
        for attr, phrases in self.attributes.items():
            for p in phrases:
                low = p.casefold()
                if low in table and table[low] != attr:
                    raise ValueError(
                        f"lexicon phrase {p!r} claimed by both "
                        f"{table[low]} and {attr}; attribute binding would be "
                        "order-dependent")
                table[low] = attr
        phrases = sorted(table, key=lambda s: (-len(s), s))
        rx = re.compile(r"\b(?:" + "|".join(re.escape(p) for p in phrases) + r")\b",
                        re.IGNORECASE)
        return rx, table


def load_key(path: str | Path) -> FactKey:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return FactKey(
        referents=raw["referents"],
        attributes={k: v["lexicon"] for k, v in raw["attributes"].items()},
        facts=raw["facts"],
        string_facts=raw.get("string_facts", []),
        mask_patterns=raw.get("mask_patterns", []),
    )


@dataclass
class Occurrence:
    """One appearance of a gold-shaped value, and what the report bound it to."""

    surface: str
    value: float | None
    verdict: str
    referent_verdict: str = UNRESOLVED
    attribute_verdict: str = UNRESOLVED
    referent: str | None = None
    attribute: str | None = None
    belongs_to: list[str] = field(default_factory=list)
    attribute_scope: str = "none"     # clause | sentence | table | none
    referent_scope: str = "none"      # sentence | paragraph | table | none
    tied: bool = False
    context: str = ""
    # Where `surface` starts inside `context`, so a labelling sheet can mark
    # which of two equal numerals in one sentence a row is about.
    offset: int = -1

    def to_json(self) -> dict[str, Any]:
        return {
            "surface": self.surface, "value": self.value, "verdict": self.verdict,
            "referent_verdict": self.referent_verdict,
            "attribute_verdict": self.attribute_verdict,
            "referent": self.referent, "attribute": self.attribute,
            "belongs_to": self.belongs_to, "attribute_scope": self.attribute_scope,
            "referent_scope": self.referent_scope, "tied": self.tied,
            "context": self.context, "offset": self.offset,
        }


@dataclass
class FaithfulnessResult:
    """Every rate is None when its pool is empty; see "No pool, no number".

    `numerals_outside_key` was `fabrication_rate` and was renamed because the
    old name claimed more than the rate measures. It is the share of scanned
    numerals that match no gold value after masking: on a private arm it flags
    invented figures, but it also counts any true figure the key does not hold
    (the percentages before PCT_SPENT existed, a sum across projects), and on
    the oracle, which reads the whole corpus and is free to compute, it is not a
    fabrication rate at all. It is reported for the private arms only.

    `f1` and `f1_attribute` are **not for the paper**. They fold coverage and
    binding accuracy, two populations with different denominators, into one
    number that neither denominator describes, and a report can raise the
    harmonic mean by stating more figures however it binds them, because
    coverage credits a figure for being said. They stay in the output so
    older measurements remain comparable; the paper quotes RBA, attribute
    accuracy and coverage_correct, each with its n.
    """

    occurrences: list[Occurrence]
    counts: dict[str, int]
    denominators: dict[str, int]
    rba: float | None
    attribute_accuracy: float | None
    referent_accuracy: float | None
    resolution_rate: float | None
    misbinding_rate: float | None
    unbound_rate: float | None
    numerals_outside_key: float | None
    coverage: float | None
    coverage_stated: float | None
    coverage_correct: float | None
    f1: float | None
    f1_attribute: float | None

    def to_json(self) -> dict[str, Any]:
        """Aggregate numbers only.

        `occurrences` carries verbatim report sentences, which for the private
        arm means private values. It is written to the run directory and never
        into an aggregate, on the same rule as the judge rationales and the
        adversary output.
        """
        return {
            "counts": dict(self.counts), "denominators": dict(self.denominators),
            "rba": self.rba,
            "attribute_accuracy": self.attribute_accuracy,
            "referent_accuracy": self.referent_accuracy,
            "resolution_rate": self.resolution_rate,
            "misbinding_rate": self.misbinding_rate,
            "unbound_rate": self.unbound_rate,
            "numerals_outside_key": self.numerals_outside_key,
            "coverage": self.coverage, "coverage_stated": self.coverage_stated,
            "coverage_correct": self.coverage_correct,
            "faithfulness_f1": self.f1, "faithfulness_f1_attribute": self.f1_attribute,
        }

    def detail_json(self) -> dict[str, Any]:
        return {**self.to_json(), "occurrences": [o.to_json() for o in self.occurrences]}


# --------------------------------------------------------------------- spans

def _mask(text: str, patterns: list[str]) -> str:
    """Blank identifier- and date-shaped runs, preserving every offset.

    Measured on the archived report: 57 numerals, 18 gold-matching and 39 not,
    and the 39 are dominated by the tails of contract ids (0917, 1044, 1187)
    and of dates (00, 06, 20). Reusing the grounder's year exemption alone
    leaves those in, and `numerals_outside_key` then measures the identifier
    scheme rather than the report.
    """
    out = list(text)
    for p in patterns:
        for m in re.finditer(p, text):
            for i in range(m.start(), m.end()):
                out[i] = " "
    return "".join(out)


def _spans(rx: re.Pattern[str], text: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group(0)) for m in rx.finditer(text)]


def _ranges(text: str, rx: re.Pattern[str]) -> list[tuple[int, int]]:
    """Split `text` by `rx`, returning the offsets of the pieces between hits."""
    out: list[tuple[int, int]] = []
    pos = 0
    for m in rx.finditer(text):
        if m.start() > pos:
            out.append((pos, m.start()))
        pos = m.end()
    if pos < len(text):
        out.append((pos, len(text)))
    return out or [(0, len(text))]


def _enclosing(ranges: list[tuple[int, int]], at: int) -> tuple[int, int]:
    for lo, hi in ranges:
        if lo <= at < hi:
            return lo, hi
    return ranges[-1]


def _distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    if a[1] <= b[0]:
        return b[0] - a[1]
    if b[1] <= a[0]:
        return a[0] - b[1]
    return 0


# -------------------------------------------------------------------- scoring

def _bind_attribute(
    num: tuple[int, int],
    lex: list[tuple[int, int, str]],
    table: dict[str, str],
    clause: tuple[int, int],
    sentence: tuple[int, int],
    cap: int = MAX_BIND_DISTANCE,
) -> tuple[str | None, str, bool]:
    """Nearest lexicon term in the clause; the sentence only if unambiguous.

    The fallback exists for appositives: "Where unspent balances remain, such
    as 45,000.00 USD, these do not indicate headroom" strands the numeral in a
    clause with no term, while the term it plainly belongs to sits ~25
    characters away in the previous one. `cap` is what keeps that from becoming
    a licence to reach across the whole sentence.
    """
    def nearest(lo: int, hi: int) -> tuple[str | None, bool]:
        here = sorted(((_distance(num, (s, e)), s, table[t.casefold()])
                       for s, e, t in lex if lo <= s < hi and _distance(num, (s, e)) <= cap),
                      key=lambda r: (r[0], r[1]))
        if not here:
            return None, False
        best = here[0]
        tied = any(d == best[0] and a != best[2] for d, _, a in here[1:])
        return best[2], tied

    attr, tied = nearest(*clause)
    if attr is not None:
        return attr, "clause", tied
    attr, tied = nearest(*sentence)
    if attr is not None:
        return attr, "sentence", tied
    return None, "none", False


def _verdict(
    value: float | None,
    referent: str | None,
    attribute: str | None,
    ambiguous: bool,
    by_value: dict[float, list[tuple[str, str]]],
    fact_id: str | None,
) -> tuple[str, str, str, list[str]]:
    """Score the referent and the attribute independently, then combine.

    The combination rule that matters: a resolved MISMATCH on *either* axis is
    a finding and outranks both AMBIGUOUS and UNRESOLVED on the other. A report
    that says "187,432.55 is the unspent balance" without naming a project has
    still made a checkable claim and got it wrong, and the earlier single-axis
    rule filed exactly that sentence — the run's headline inversion — under
    "could not tell".
    """
    if fact_id is not None:
        subj, attr = fact_id.split(".", 1)
        owners: list[tuple[str, str]] = [(subj, attr)]
    elif value is None or value not in by_value:
        return FABRICATED, UNRESOLVED, UNRESOLVED, []
    else:
        owners = by_value[value]
    belongs = [f"{s}.{a}" for s, a in owners]
    subjects = {s for s, _ in owners}
    attributes = {a for _, a in owners}

    ref_v = (AMBIGUOUS if ambiguous
             else UNRESOLVED if referent is None
             else MATCH if referent in subjects
             else MISMATCH)
    att_v = (UNRESOLVED if attribute is None
             else MATCH if attribute in attributes
             else MISMATCH)

    if ref_v == MATCH and att_v == MATCH:
        return CORRECT, ref_v, att_v, belongs
    if MISMATCH in (ref_v, att_v):
        return MISBOUND, ref_v, att_v, belongs
    if ref_v == AMBIGUOUS:
        return AMBIGUOUS, ref_v, att_v, belongs
    if ref_v == UNRESOLVED and att_v == UNRESOLVED:
        return UNBOUND, ref_v, att_v, belongs
    return PARTIAL, ref_v, att_v, belongs


def _table_blocks(para: str) -> tuple[list[str], list[str]] | None:
    """A GFM table: header cells and body rows, or None if this is prose."""
    lines = [ln for ln in para.splitlines() if ln.strip()]
    if len(lines) < 3 or not all(_TABLE_ROW.match(ln) for ln in lines):
        return None
    if not _TABLE_RULE.match(lines[1]):
        return None
    header = [c.strip() for c in lines[0].strip().strip("|").split("|")]
    return header, lines[2:]


def score(report_markdown: str, key: FactKey, *,
          cap: int = MAX_BIND_DISTANCE) -> FaithfulnessResult:
    """Classify every gold-shaped value in a report against the authored key."""
    text = _TAG.sub(" ", de_escape(unicodedata.normalize("NFKC", report_markdown)))
    lex_rx, lex_table = key.lexicon_regex()
    ref_rx = key.referent_regex()
    by_value = key.by_value

    occurrences: list[Occurrence] = []
    seen_facts: set[str] = set()

    for para in _PARA_SPLIT.split(text):
        if not para.strip():
            continue
        tbl = _table_blocks(para)
        if tbl is not None:
            occurrences += _score_table(*tbl, key, lex_rx, lex_table, ref_rx,
                                        by_value, seen_facts)
        else:
            occurrences += _score_prose(para, key, lex_rx, lex_table, ref_rx,
                                        by_value, seen_facts, cap)

    counts = {v: 0 for v in (CORRECT, MISBOUND, PARTIAL, UNBOUND, AMBIGUOUS,
                             FABRICATED)}
    for o in occurrences:
        counts[o.verdict] += 1

    # Each rate gets the denominator it is actually about, and every
    # denominator is published. RBA needs both axes resolved, which on prose
    # that names no project is a small set; quoting it without its n would be
    # the same error as quoting a single judge draw.
    full = [o for o in occurrences
            if o.referent_verdict in _RESOLVED and o.attribute_verdict in _RESOLVED]
    attr_res = [o for o in occurrences if o.attribute_verdict in _RESOLVED]
    ref_res = [o for o in occurrences if o.referent_verdict in _RESOLVED]
    gold_shaped = [o for o in occurrences if o.verdict != FABRICATED]

    def rate(hits: int, pool: list | set) -> float | None:
        return (hits / len(pool)) if pool else None

    rba = rate(sum(o.verdict == CORRECT for o in full), full)
    attr_acc = rate(sum(o.attribute_verdict == MATCH for o in attr_res), attr_res)
    ref_acc = rate(sum(o.referent_verdict == MATCH for o in ref_res), ref_res)

    # Intersect before dividing. `belongs` names every subject that owns a
    # value, including alias subjects like AURORA.UNITS_SHORT that exist so
    # either spelling of the vendor shortfall scores CORRECT — those are not
    # gold facts and must not pad the numerator. Without the intersection the
    # archived report scored coverage 1.0 against the first calibration's key of
    # eleven facts (it now has fourteen, with PCT_SPENT), holding eleven strings while
    # missing AURORA.UNSPENT, which no document states. A coverage of 1.0 that is
    # really 10/11 is the same failure as "0 refused, exit 0" over an empty report.
    gold_ids = {f["fact_id"] for f in key.facts}
    stated_ids = {f["fact_id"] for f in key.facts if not f.get("derived")}
    covered = seen_facts & gold_ids
    coverage = rate(len(covered), gold_ids)
    cov_stated = rate(len(covered & stated_ids), stated_ids)
    # `coverage` credits a fact for being *said*, bound right or not, so a
    # report that permutes every figure scores full coverage. coverage_correct
    # credits a fact only when some occurrence of it is CORRECT with the fact's
    # own subject and attribute: a MISBOUND-only report scores 0.
    cov_correct = rate(len(_correctly_bound(occurrences, key.facts) & gold_ids), gold_ids)

    def harm(a: float | None, b: float | None) -> float | None:
        if a is None or b is None:
            return None
        return (2 * a * b / (a + b)) if (a + b) else 0.0

    return FaithfulnessResult(
        occurrences=occurrences, counts=counts,
        denominators={"full": len(full), "attribute": len(attr_res),
                      "referent": len(ref_res), "gold_shaped": len(gold_shaped),
                      "scanned": len(occurrences)},
        rba=rba, attribute_accuracy=attr_acc, referent_accuracy=ref_acc,
        resolution_rate=rate(len(full), gold_shaped),
        misbinding_rate=rate(counts[MISBOUND], gold_shaped),
        unbound_rate=rate(counts[UNBOUND], gold_shaped),
        numerals_outside_key=rate(counts[FABRICATED], occurrences),
        coverage=coverage, coverage_stated=cov_stated, coverage_correct=cov_correct,
        f1=harm(coverage, rba), f1_attribute=harm(coverage, attr_acc),
    )


def _correctly_bound(occurrences: list[Occurrence],
                     facts: list[dict[str, Any]]) -> set[str]:
    """The fact ids some CORRECT occurrence states with the fact's own binding.

    Resolved back to the fact rather than read off `belongs_to`, because an
    alias subject (AURORA for the vendor shortfall) is in `belongs_to` but is
    not a fact id, and a correct binding to it is still a correct statement of
    VENDOR.UNITS_SHORT.
    """
    out: set[str] = set()
    for o in occurrences:
        if o.verdict != CORRECT:
            continue
        for f in facts:
            if f["attribute"] != o.attribute or o.referent not in f["subjects"]:
                continue
            if f.get("match") == "surface":
                same = o.value is None and f["fact_id"] in o.belongs_to
            else:
                same = o.value is not None and round(float(f["value"]), 2) == o.value
            if same:
                out.add(f["fact_id"])
    return out


def _score_prose(para, key, lex_rx, lex_table, ref_rx, by_value, seen_facts,
                 cap=MAX_BIND_DISTANCE):
    out: list[Occurrence] = []
    sentences = _ranges(para, _SENT_SPLIT)
    lex = _spans(lex_rx, para)
    refs = _spans(ref_rx, para)

    # Surface facts first ("twelve percent"), and their spans are blanked so a
    # spelling like "12%" is not then rescanned as an unexplained numeral.
    masked = _mask(para, key.mask_patterns)
    candidates: list[tuple[int, int, str, float | None, str | None]] = []
    for f in key.facts:
        if f.get("match") != "surface":
            continue
        for surf in f["surfaces"]:
            for m in _surface_regex(surf).finditer(para):
                candidates.append((m.start(), m.end(), m.group(0), None, f["fact_id"]))
                masked = masked[:m.start()] + " " * len(m.group(0)) + masked[m.end():]

    for m in _NUM_RE.finditer(masked):
        raw = m.group(0)
        if _YEAR_RE.match(raw.replace(",", "")):
            continue
        candidates.append((m.start(), m.end(), raw, _norm_number(raw), None))

    for start, end, surface, value, fact_id in sorted(candidates):
        num = (start, end)
        s_lo, s_hi = _enclosing(sentences, start)
        sentence = para[s_lo:s_hi]
        clause = _enclosing(_ranges(sentence, _CLAUSE_SPLIT), start - s_lo)
        clause = (clause[0] + s_lo, clause[1] + s_lo)

        attr, a_scope, tied = _bind_attribute(num, lex, lex_table, clause,
                                              (s_lo, s_hi), cap)

        here = [(s, e, t) for s, e, t in refs if s_lo <= s < s_hi]
        names = {key.referent_of(t) for _, _, t in here} - {None}
        ambiguous = len(names) > 1
        if len(names) == 1:
            referent, r_scope = names.pop(), "sentence"
        else:
            earlier = [(s, e, t) for s, e, t in refs if e <= s_lo]
            referent = key.referent_of(earlier[-1][2]) if earlier else None
            r_scope = "paragraph" if referent else "none"
        if ambiguous:
            referent, r_scope = None, "none"

        verdict, ref_v, att_v, belongs = _verdict(value, referent, attr, ambiguous,
                                                  by_value, fact_id)
        if verdict != FABRICATED:
            seen_facts.update(belongs if fact_id is None else [fact_id])
        out.append(Occurrence(
            surface=surface, value=value, verdict=verdict,
            referent_verdict=ref_v, attribute_verdict=att_v, referent=referent,
            attribute=attr, belongs_to=belongs, attribute_scope=a_scope,
            referent_scope=r_scope, tied=tied,
            context=sentence.strip(),
            offset=start - s_lo - (len(sentence) - len(sentence.lstrip()))))
    return out


def _score_table(header, rows, key, lex_rx, lex_table, ref_rx, by_value, seen_facts):
    """A table names its attribute in the header, not in the cell.

    Without this the values in a "Project | Authorised | Spent" table are
    UNBOUND, which reads as the report having failed to say what it said
    plainly. The column is the clause.
    """
    col_attr: list[str | None] = []
    for cell in header:
        hits = {lex_table[t.casefold()] for _, _, t in _spans(lex_rx, cell)}
        col_attr.append(hits.pop() if len(hits) == 1 else None)

    out: list[Occurrence] = []
    for line in rows:
        row = line.strip()
        pieces = row.strip("|").split("|")
        cells = [c.strip() for c in pieces]
        # Offset of each stripped cell inside the stripped row, for `offset`.
        starts, pos = [], len(row) - len(row.lstrip("|"))
        for piece in pieces:
            starts.append(pos + len(piece) - len(piece.lstrip()))
            pos += len(piece) + 1
        names = {key.referent_of(t) for c in cells for _, _, t in _spans(ref_rx, c)}
        names -= {None}
        ambiguous = len(names) > 1
        referent = names.pop() if len(names) == 1 else None

        for i, cell in enumerate(cells):
            masked = _mask(cell, key.mask_patterns)
            for m in _NUM_RE.finditer(masked):
                raw = m.group(0)
                if _YEAR_RE.match(raw.replace(",", "")):
                    continue
                value = _norm_number(raw)
                attr = col_attr[i] if i < len(col_attr) else None
                verdict, ref_v, att_v, belongs = _verdict(value, referent, attr,
                                                          ambiguous, by_value, None)
                if verdict != FABRICATED:
                    seen_facts.update(belongs)
                out.append(Occurrence(
                    surface=raw, value=value, verdict=verdict,
                    referent_verdict=ref_v, attribute_verdict=att_v, referent=referent,
                    attribute=attr, belongs_to=belongs,
                    attribute_scope="table" if attr else "none",
                    referent_scope="table" if referent else "none",
                    context=row, offset=starts[i] + m.start()))
    return out
