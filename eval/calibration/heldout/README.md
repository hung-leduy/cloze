# Held-out labelling sheet (plan task EXP8)

Labelled blind by the author after the frozen batch, on reports the lexicon fix of EXP2 never
saw: the held-out r1 row of the RBA calibration (EXP8), and, added on 2026-10-10 after the
simulated review (paper/reviews/critical_review_2026-10-10.md, MR1-MR2), the baseline report of
the same corpus and repeat, so the rule's error on a baseline report is measured too. The
baseline row is an exploratory analysis after the batch; no instrument changes.

| Sheet | Report it describes | Rows |
|---|---|---|
| `portfolio-b__r1.report.csv` | `portfolio-b__r1.report.md`, a byte copy of `eval/runs/portfolio-b__r1/report.md` (corpus B, arm r1, repeat 1, frozen batch of 2026-10-07 at the tag paper-freeze) | 27 |
| `portfolio-b__baseline.report.csv` | `portfolio-b__baseline.report.md`, a byte copy of `eval/runs/portfolio-b__baseline/report.md` (corpus B, arm baseline, repeat 1, same batch) | 34 |

Exported on 2026-10-07 by the AI assistant with
`scripts/calibrate_faithfulness.py --export-sheet` against the frozen corpus-B key
(`eval/corpora/portfolio-b/smoke_fact_key.json`, sha256 `998d6ee0…d4ad`). Repeat 1 was chosen
before the sheet was exported, as the first r1 run of corpus B, not by looking at any score.

Fill it in exactly as `../blind/README.md` describes (what the report says each number is, not
what is true; every row needs both labels; do not open `faithfulness_occurrences.json` or the
measurement of this run until the sheet is finished), with corpus B's referent labels:

| Label | Use when the report attaches the number to |
|---|---|
| `HALCYON` | Project Halcyon |
| `MERIDIAN` | Project Meridian |
| `TAMARIND` | Project Tamarind |
| `OSPREY` | Trial Osprey |
| `VENDOR` | Brantley Fabrication |
| `ORG` | Veltmoor Civic Works, as the owner of the number |
| `NONE` | nobody: the report does not say whose number it is |
| `UNCLEAR` | one of several named candidates, and you cannot tell which |
| `OTHER` | something not listed: a site, "the portfolio", a sum across projects |

The attribute labels are the same as for corpus A (`AUTHORISED`, `SPENT`, `UNSPENT`, `OVERRUN`,
`PCT_SPENT`, `UNITS_SHORT`, `REVENUE_FALL_PCT`, `NONE`, `OTHER`).

The author entered the labels on a local labelling page, which this release does not include.
To score them:

```bash
.venv/bin/python scripts/calibrate_faithfulness.py \
  --report eval/calibration/heldout/portfolio-b__r1.report.md \
  --labels eval/calibration/heldout/portfolio-b__r1.report.csv \
  --key eval/corpora/portfolio-b/smoke_fact_key.json
```

## Results at the frozen RBA attribute lexicon

*Recorded by the AI assistant; the labels are the author's (r1 sheet finished on 2026-10-09,
baseline sheet on 2026-10-14).* Attribute axis, gold-valued occurrences; full outputs in
`../exp8_heldout_frozen.txt` and `../exp8_heldout_baseline_frozen.txt`, rows in
`../calibration.json`.

| Sheet | Agreement | Cohen's kappa | Labels MATCH (author / rule) |
|---|---|---|---|
| r1 report (EXP8, registered) | 11/27 | -0.007 | 24/27 / 11/27 |
| baseline report (exploratory, after the batch) | 26/34 | 0.541 | 16/34 / 15/34 |

On the r1 report the rule under-credits: most disagreements are bindings the author labels
correct and the rule scores as misbound. On the baseline report its errors run both ways (4
under-credited, 3 over-credited, 1 unresolved against a label the author scores as a mismatch),
and its share of matches is close to the author's. The referent axis of the baseline sheet
agrees on 1 of 34 rows, 31 of the 33 others because the author's `UNCLEAR` is compared as
ambiguous with the rule's unresolved referent: both say the report does not tell whose figure it
is. In the other 2 the author labels `ORG`, against the key, where the rule resolves no referent. One
report per arm, after the batch: no instrument, key or lexicon changes.
