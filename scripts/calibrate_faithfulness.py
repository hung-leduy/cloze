#!/usr/bin/env python3
"""Measure the faithfulness metric against an independent hand labelling.

The metric is an instrument, so it gets an error bar. This script computes that
error bar the only way it can mean anything: against labels written by reading
the report, recorded before the scoring rule was last changed, and stored in
`eval/calibration/`.

It exists because the design document arrived with a pre-computed calibration
("correct=1, misbound=3, unbound=12, ambiguous=2") produced by running the
proposed rule and reading off its output. A rule scoring itself agrees with
itself perfectly and reports nothing. Any number this project publishes about
faithfulness has to survive the comparison below instead.

The cap sweep is here for the same reason. `MAX_BIND_DISTANCE` is the one free
parameter in the rule, and a free parameter tuned on the calibration set is how
an instrument gets quietly fitted to its own reference. The sweep prints
agreement across the whole range so the choice is visible and its sensitivity
is publishable, rather than a constant someone picked.

Blind sheets (INS1)
-------------------
The first label set was written by the metric's builder, in the same commit as
the rule it calibrates. It is kept, and reported as in-sample and non-blind.
New labels come from a sheet this script exports with ``--export-sheet``: one
row per scored occurrence, with the sentence and the numeral and nothing of
what the metric decided. The labeller writes what the report binds each
numeral to, by name (ZEPHYR, SPENT, NONE, ...), not a verdict; the verdict is
derived here from the key by the metric's own comparison, so the labeller never
has to look up a gold value and cannot be led by one.

A filled sheet is read back by passing it as ``--labels`` (a ``.csv``). Several
``--report``/``--labels`` pairs pool into one agreement table. Only the
attribute axis is quoted in the paper (plan X5), with Cohen's kappa beside it,
because raw agreement does not discount the agreement two readers reach by
both using the commonest label. Both are headlined over gold-valued
occurrences (INS1b): a numeral outside the key is UNRESOLVED on both sides
whatever anyone wrote, so including it adds agreement nobody earned. The
all-rows figures are printed beside them, labelled.

The paper's calibration sentence in §5 (PAP5a, ``make_paper_tables.py
--calibration``; a sentence, not a table, since plan Part D AD32) reads these
headline figures as JSON, which this script does not write: EXP8 records them in
the shape ``{"rows": [{"id", "labeller", "blind", "in_sample", "occurrences",
"agreement": {"k", "n"}, "kappa"}]}``, one row per labelled report, copied from
the attribute-axis, gold-valued block printed here. ``id`` is one of
``insample_A_baseline``, ``dev_A_r1``, ``dev_A_oracle`` and ``heldout_B_r1``, and
fixes the labeller, blind and in_sample the sentence states for that row
(make_paper_tables.py CAL_ROWS; its docstring, ``--calibration``).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from make_smoke_corpus import fact_key  # noqa: E402
from privdeep.eval.faithfulness import (  # noqa: E402
    FABRICATED,
    MATCH,
    MAX_BIND_DISTANCE,
    FactKey,
    Occurrence,
    _verdict,
    de_escape,
    load_key,
    score,
)

DEFAULT_LABELS = ROOT / "eval" / "calibration" / "smoke-q3_hand_labels.json"
DEFAULT_REPORT = ROOT / "eval" / "runs" / "smoke-q3" / "report.md"

# The sheet's columns. There is deliberately no verdict, referent, attribute or
# scope column: anything the metric decided would anchor the labeller.
SHEET_COLUMNS = ("id", "section", "before", "sentence", "numeral",
                 "referent_label", "attribute_label", "note")
# Labels beyond the key's own referent and attribute names.
NONE, UNCLEAR, OTHER = "NONE", "UNCLEAR", "OTHER"
_MARK = ("[[", "]]")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
_TAG = re.compile(r"<[^>]+>")
_BEFORE_CHARS = 400


def _key(path: str | None = None) -> FactKey:
    if path:
        return load_key(path)
    raw = fact_key()
    return FactKey(
        referents=raw["referents"],
        attributes={k: v["lexicon"] for k, v in raw["attributes"].items()},
        facts=raw["facts"], string_facts=raw["string_facts"],
        mask_patterns=raw["mask_patterns"],
    )


def _key_sha(path: str | None) -> str:
    if path:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    body = json.dumps(fact_key(), indent=2, sort_keys=True) + "\n"
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _align(occurrences, labels):
    """Occurrences and labels are both in document order, so they zip.

    Zipping rather than fuzzy-matching on context is deliberate: two
    occurrences of 51,237.75 sit in one sentence and share a context string, so
    any content-based match would have to guess between them. If a rule change
    alters the number of occurrences the alignment breaks loudly, which is the
    correct outcome — the hand labels no longer describe that output and have
    to be re-done, not silently re-matched.
    """
    if len(occurrences) != len(labels):
        raise SystemExit(
            f"alignment failed: {len(occurrences)} occurrences vs "
            f"{len(labels)} hand labels. The rule changed what it finds; "
            "re-label before quoting any agreement number.")
    for i, (o, lab) in enumerate(zip(occurrences, labels, strict=True), 1):
        if o.surface.rstrip(",").strip() != lab["surface"]:
            raise SystemExit(
                f"alignment failed at {i}: metric saw {o.surface!r}, "
                f"labels say {lab['surface']!r}")
    return list(zip(occurrences, labels, strict=True))


# ---------------------------------------------------------------- the sheet

def _normalised(report_markdown: str) -> str:
    """The text `score` reads, so contexts can be found in it again."""
    return _TAG.sub(" ", de_escape(unicodedata.normalize("NFKC", report_markdown)))


def _context_starts(text: str, occurrences: list[Occurrence]) -> list[int]:
    """Where each occurrence's sentence or table row starts in `text`; -1 if absent.

    A plain `text.find(o.context)` returns the first copy of a sentence, so when
    a report repeats a sentence or a table row verbatim (an executive summary
    restating a finding, say) every later copy's row would carry the first
    copy's section and paragraph. Occurrences come in document order, so each
    numeral must sit strictly after the previous one: the search for a context
    starts where that holds, and two numerals in one sentence still resolve to
    the same copy of it.
    """
    starts: list[int] = []
    last = -1                       # position of the previous numeral in `text`
    for o in occurrences:
        offset = max(o.offset, 0)
        at = text.find(o.context, max(last - offset + 1, 0))
        starts.append(at)
        if at >= 0:
            last = at + offset
    return starts


def _surroundings(text: str, o: Occurrence, at: int) -> tuple[str, str]:
    """The nearest heading above an occurrence, and what precedes it.

    `at` is where the occurrence's sentence or table row starts in `text`
    (from `_context_starts`). `before` is the paragraph up to the sentence (the
    metric lets a referent named earlier in the paragraph carry forward, so
    the labeller must see it too). For a table row it is the table's header
    row, which is where the column says what its numbers are.
    """
    if at < 0:
        return "", ""
    head = ""
    for line in text[:at].splitlines():
        m = _HEADING.match(line)
        if m:
            head = m.group(1).strip()
    if o.context.startswith("|"):
        lines = text[:at].splitlines()
        rows = []
        for line in reversed(lines):
            if not line.strip().startswith("|"):
                break
            rows.append(line.strip())
        return head, rows[-1] if rows else ""
    para_start = text.rfind("\n\n", 0, at)
    before = " ".join(text[para_start + 2 if para_start >= 0 else 0:at].split())
    if len(before) > _BEFORE_CHARS:
        before = "..." + before[-_BEFORE_CHARS:]
    return head, before


def _marked(o: Occurrence) -> str:
    if o.offset < 0 or o.context[o.offset:o.offset + len(o.surface)] != o.surface:
        return o.context
    end = o.offset + len(o.surface)
    return o.context[:o.offset] + _MARK[0] + o.surface + _MARK[1] + o.context[end:]


def export_sheet(report_path: Path, key: FactKey, out: Path) -> int:
    """Write a blind labelling sheet: every scored occurrence, no verdicts."""
    markdown = report_path.read_text(encoding="utf-8")
    text = _normalised(markdown)
    res = score(markdown, key)
    out.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so a spreadsheet opens the dashes and quotes correctly.
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=SHEET_COLUMNS)
        w.writeheader()
        starts = _context_starts(text, res.occurrences)
        for i, (o, at) in enumerate(zip(res.occurrences, starts, strict=True), 1):
            section, before = _surroundings(text, o, at)
            w.writerow({"id": i, "section": section, "before": before,
                        "sentence": _marked(o), "numeral": o.surface,
                        "referent_label": "", "attribute_label": "", "note": ""})
    return len(res.occurrences)


def _sheet_labels(path: Path, occurrences: list[Occurrence], key: FactKey) -> list[dict]:
    """Read a filled sheet back as per-axis verdicts, derived from the key.

    The labeller named a referent and an attribute; `_verdict` turns those into
    MATCH/MISMATCH/UNRESOLVED/AMBIGUOUS exactly as it does for the metric's own
    binding, against the same gold owners, so the two sides differ only in who
    read the sentence. OTHER is a binding the key has no name for ("variance",
    "the Leeds pilot") and is a checkable wrong binding, so it maps to MISMATCH.
    """
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if len(rows) != len(occurrences):
        raise SystemExit(
            f"{path}: {len(rows)} rows vs {len(occurrences)} occurrences. The rule "
            "changed what it finds since the sheet was exported; re-export it.")
    referents = set(key.referents) | {NONE, UNCLEAR, OTHER}
    attributes = set(key.attributes) | {NONE, OTHER}
    bad = []
    for row in rows:
        ref = row["referent_label"].strip().upper()
        att = row["attribute_label"].strip().upper()
        if ref not in referents or att not in attributes:
            bad.append(f"  id {row['id']}: referent {ref or '(blank)'!r}, "
                       f"attribute {att or '(blank)'!r}")
    if bad:
        raise SystemExit(
            f"{path}: {len(bad)} row(s) unfilled or with a label outside "
            f"referent {sorted(referents)} / attribute {sorted(attributes)}:\n"
            + "\n".join(bad))

    by_value = key.by_value
    out = []
    for o, row in zip(occurrences, rows, strict=True):
        # The marked sentence is the alignment check; whitespace is normalised
        # because a spreadsheet may rewrite line breaks inside a cell. The bare
        # numeral column is not compared, since a spreadsheet may reformat
        # "250,000.00" as a number.
        if " ".join(row["sentence"].split()) != " ".join(_marked(o).split()):
            raise SystemExit(
                f"{path}: row {row['id']} is about {row['numeral']!r} in a sentence "
                f"the metric no longer produces as {o.surface!r}; re-export.")
        ref = row["referent_label"].strip().upper()
        att = row["attribute_label"].strip().upper()
        fact_id = o.belongs_to[0] if (o.value is None and o.belongs_to) else None
        overall, ref_v, att_v, _ = _verdict(
            o.value, None if ref in (NONE, UNCLEAR) else ref,
            None if att == NONE else att, ref == UNCLEAR, by_value, fact_id)
        out.append({"id": row["id"], "surface": o.surface.rstrip(",").strip(),
                    "referent": ref_v, "attribute": att_v, "overall": overall,
                    "referent_label": ref, "attribute_label": att,
                    "note": row.get("note", "")})
    return out


def _labels(path: Path, occurrences: list[Occurrence], key: FactKey) -> list[dict]:
    if path.suffix.lower() == ".csv":
        return _sheet_labels(path, occurrences, key)
    return json.loads(path.read_text(encoding="utf-8"))["labels"]


# --------------------------------------------------------------- statistics

def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    """Cohen's kappa for two raters over the same items; None if undefined.

    Undefined when chance agreement is 1, i.e. both raters used one and the
    same category for every item: there is nothing to be better than chance at.
    """
    n = len(a)
    if n == 0 or n != len(b):
        return None
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in set(a) | set(b))
    return None if pe == 1 else (po - pe) / (1 - pe)


def _axis_table(pairs) -> dict[str, tuple[int, int]]:
    n = len(pairs)
    gold = [(o, lab) for o, lab in pairs if o.verdict != FABRICATED]
    return {
        "overall": (sum(o.verdict == lab["overall"] for o, lab in pairs), n),
        "referent": (sum(o.referent_verdict == lab["referent"] for o, lab in pairs), n),
        "attribute": (sum(o.attribute_verdict == lab["attribute"] for o, lab in pairs), n),
        "attribute_gold": (sum(o.attribute_verdict == lab["attribute"] for o, lab in gold),
                           len(gold)),
    }


def _attribute_kappas(pairs) -> dict[str, float | None]:
    """Attribute-axis kappa on gold-valued occurrences, and over every row.

    A numeral outside the key has no owner, so `_verdict` forces its attribute
    to UNRESOLVED on both sides whatever either reader wrote: those rows agree
    by construction. Counting them adds certain agreement to the observed rate
    and to the UNRESOLVED marginal, which inflates kappa without measuring any
    reading. The gold-valued figure is the headline; the all-rows one is kept
    beside it so the earlier numbers (21/24 on smoke-q3) still reproduce.
    """
    gold = [(o, lab) for o, lab in pairs if o.verdict != FABRICATED]
    return {
        "attribute_gold": cohen_kappa([lab["attribute"] for _, lab in gold],
                                      [o.attribute_verdict for o, _ in gold]),
        "attribute": cohen_kappa([lab["attribute"] for _, lab in pairs],
                                 [o.attribute_verdict for o, _ in pairs]),
    }


def _print_agreement(pairs, indent: str = "  ") -> None:
    t = _axis_table(pairs)
    kappa = _attribute_kappas(pairs)
    outside = t["attribute"][1] - t["attribute_gold"][1]

    def pct(k: int, n: int) -> str:
        return f"{k}/{n}  ({k / n:.0%})" if n else "0/0"

    def kap(k: float | None) -> str:
        return "undefined" if k is None else f"{k:.3f}"
    print(f"{indent}overall verdict agreement    {pct(*t['overall'])}")
    print(f"{indent}referent axis agreement      {pct(*t['referent'])}")
    print(f"{indent}attribute axis, gold-valued occurrences (headline)")
    print(f"{indent}  agreement                  {pct(*t['attribute_gold'])}")
    print(f"{indent}  Cohen kappa                {kap(kappa['attribute_gold'])}")
    print(f"{indent}attribute axis, all rows (includes {outside} outside the key, "
          "where agreement is trivial)")
    print(f"{indent}  agreement                  {pct(*t['attribute'])}")
    print(f"{indent}  Cohen kappa                {kap(kappa['attribute'])}")


def _print_attribute_disagreements(pairs, where: str = "") -> None:
    for i, (o, lab) in enumerate(pairs, 1):
        if o.attribute_verdict == lab["attribute"]:
            continue
        rid = lab.get("id", i)
        named = f" (labelled {lab['attribute_label']})" if "attribute_label" in lab else ""
        print(f"[{where}{rid}] {o.surface!r}  metric={o.attribute_verdict}/{o.attribute} "
              f"({o.attribute_scope})  hand={lab['attribute']}{named}")
        print(f"     {o.context[:160]}")
        if lab.get("note"):
            print(f"     note: {lab['note']}")


# ---------------------------------------------------------------------- cli

def _one_report(report_path: str, labels_path: str, key: FactKey):
    report = Path(report_path).read_text(encoding="utf-8")
    res = score(report, key)
    labels = _labels(Path(labels_path), res.occurrences, key)
    return report, res, _align(res.occurrences, labels), labels


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--report", action="append",
                    help="report to score; repeat, paired in order with --labels")
    ap.add_argument("--labels", action="append",
                    help="hand labels: the JSON label file, or a filled blind sheet (.csv)")
    ap.add_argument("--key", default=None,
                    help="gold key JSON (default: the key make_smoke_corpus.py generates)")
    ap.add_argument("--sweep", default="20,40,60,80,100,120,160,10000")
    ap.add_argument("--export-sheet", metavar="REPORT", default=None,
                    help="write a blind labelling sheet for REPORT to --out and exit")
    ap.add_argument("--out", default=None, help="where --export-sheet writes the CSV")
    args = ap.parse_args(argv)

    if args.export_sheet:
        if not (args.key and args.out):
            ap.error("--export-sheet needs --key and --out")
        n = export_sheet(Path(args.export_sheet), _key(args.key), Path(args.out))
        print(f"wrote {args.out}: {n} occurrence(s) from {args.export_sheet}")
        print(f"key {args.key} sha256 {_key_sha(args.key)}")
        return 0

    reports = args.report or [str(DEFAULT_REPORT)]
    label_files = args.labels or [str(DEFAULT_LABELS)]
    if len(reports) != len(label_files):
        ap.error("give one --labels per --report, in the same order")

    key = _key(args.key)
    print(f"key     {args.key or 'make_smoke_corpus.fact_key()'}  "
          f"sha256 {_key_sha(args.key)[:16]}\n")
    runs = [(r, lf, *_one_report(r, lf, key)) for r, lf in zip(reports, label_files,
                                                                   strict=True)]

    for report_path, labels_path, _report, res, pairs, labels in runs:
        n = len(pairs)
        print(f"report  {report_path}")
        print(f"labels  {labels_path}  ({n} occurrences)\n")
        print(f"cap = {MAX_BIND_DISTANCE}")
        _print_agreement(pairs)

        print("\n--- metric output ---")
        for k, v in res.to_json().items():
            print(f"  {k:<28} {v}")

        hand: dict[str, int] = {}
        for lab in labels:
            hand[lab["overall"]] = hand.get(lab["overall"], 0) + 1
        print("\n--- hand labelling, for comparison ---")
        print(f"  counts                       {hand}")
        h_attr = [lab for lab in labels if lab["attribute"] != "UNRESOLVED"]
        h_ref = [lab for lab in labels if lab["referent"] in (MATCH, "MISMATCH")]
        if h_attr:
            print(f"  attribute_accuracy           "
                  f"{sum(x['attribute'] == MATCH for x in h_attr) / len(h_attr):.3f}"
                  f"  (n={len(h_attr)})")
        if h_ref:
            print(f"  referent_accuracy            "
                  f"{sum(x['referent'] == MATCH for x in h_ref) / len(h_ref):.3f}"
                  f"  (n={len(h_ref)})")

        print("\n--- disagreements ---")
        for i, (o, lab) in enumerate(pairs, 1):
            if o.verdict == lab["overall"]:
                continue
            print(f"[{i:2}] {o.surface!r}  metric={o.verdict:<10} hand={lab['overall']}")
            print(f"     axes metric ref={o.referent_verdict}/{o.referent} "
                  f"attr={o.attribute_verdict}/{o.attribute} "
                  f"({o.referent_scope}/{o.attribute_scope})")
            print(f"     axes hand   ref={lab['referent']} attr={lab['attribute']}")
            if lab.get("note"):
                print(f"     {lab['note']}")

        print("\n--- attribute-axis disagreements ---")
        _print_attribute_disagreements(pairs)
        print()

    pooled = [p for run in runs for p in run[4]]
    if len(runs) > 1:
        print(f"=== pooled over {len(runs)} reports ({len(pooled)} occurrences) ===")
        _print_agreement(pooled)
        print()

    print("--- sensitivity to MAX_BIND_DISTANCE ---")
    print(f"  {'cap':>6}  {'overall':>9}  {'attr gold':>9}  {'attr all':>9}  "
          f"{'attr acc':>9}  {'n(attr)':>8}")
    total = len(pooled)
    for cap in [int(c) for c in args.sweep.split(",")]:
        agree = att = att_gold = n_gold = hits = pool = 0
        comparable = True
        for _rp, _lp, report, _res, _pairs, labels in runs:
            r = score(report, key, cap=cap)
            try:
                ps = _align(r.occurrences, labels)
            except SystemExit:
                comparable = False
                break
            agree += sum(o.verdict == lab["overall"] for o, lab in ps)
            att += sum(o.attribute_verdict == lab["attribute"] for o, lab in ps)
            gold = [(o, lab) for o, lab in ps if o.verdict != FABRICATED]
            att_gold += sum(o.attribute_verdict == lab["attribute"] for o, lab in gold)
            n_gold += len(gold)
            pool += r.denominators["attribute"]
            hits += sum(o.attribute_verdict == MATCH for o in r.occurrences)
        if not comparable:
            print(f"  {cap:>6}  (occurrence count changed; not comparable)")
            continue
        acc = f"{hits / pool:>9.3f}" if pool else f"{'n/a':>9}"
        print(f"  {cap:>6}  {agree:>4}/{total:<4}  {att_gold:>4}/{n_gold:<4}  "
              f"{att:>4}/{total:<4}  {acc}  {pool:>8}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
