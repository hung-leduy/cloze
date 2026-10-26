# EXP2: development calibration and the one-time fix of the RBA attribute lexicon

*Recorded by the AI assistant on 2026-10-06. The blind labels are the author's (63 rows,
`blind/smoke-q3__r1.report.csv` and `blind/smoke-q3__r1.oracle_report.csv`, finished on
2026-10-06); the fix below is the assistant's, made under plan task EXP2 before the tag.*

This changes the RBA attribute lexicon (`scripts/corpora/rba_lexicon.py`, emitted into every
gold key), the scoring side. `backend/src/privdeep/tier1_local/header_lexicon.py`, R1's
structural route, is not changed by the calibration.

## Rule

An attribute-axis disagreement between the metric and a blind label is fixed when (1) the label
agrees with the key and the metric does not, and (2) the cause is a phrase missing from the
lexicon, so that adding one role-specific phrase repairs it. A disagreement caused by the
nearest-term rule, by clause scoping, or by a phrase that is itself ambiguous is not fixed here:
that would change the scorer, which EXP2 does not do. A fix is kept only if no labelled row that
agreed before disagrees after, on the 63 blind rows and on the 24 in-sample rows.

## The 14 attribute-axis disagreements of the pre-fix lexicon

| Sheet, row | Numeral | Label | Metric (pre-fix) | Decision |
|---|---|---|---|---|
| r1, 8 | 113.9% | PCT_SPENT | AUTHORISED | fixed: PCT_SPENT "of authorised funds" (the expected PCT_SPENT→AUTHORISED case) |
| r1, 12 | 81.8% | PCT_SPENT | UNSPENT | fixed: PCT_SPENT "consumption rate" |
| r1, 14 | 75.0% | PCT_SPENT | SPENT | fixed: PCT_SPENT "share spent" |
| r1, 17 | 120,000.00 | SPENT | AUTHORISED (key) | not fixed: "authorised spend" is ambiguous; the lexicon maps it to AUTHORISED by design |
| r1, 18 | 98,210.00 | SPENT | AUTHORISED | fixed: SPENT "has been drawn", "drawn" |
| oracle, 6 | 98,210.00 | SPENT | AUTHORISED | not fixed: nearest-term rule ("authority (98,210.00 USD spent)") |
| oracle, 8 | 45,000.00 | SPENT | AUTHORISED (key) | not fixed: the label disagrees with the key |
| oracle, 9 | 6,237.75 | OVERRUN | AUTHORISED | not fixed: nearest-term rule ("overspent its … authority by 6,237.75") |
| oracle, 26 | 21,790.00 | UNSPENT | AUTHORISED | fixed: UNSPENT "headroom" (listed as UNSPENT in `blind/README.md`) |
| oracle, 29 | 45,000.00 | AUTHORISED | OVERRUN | not fixed: nearest-term rule ("exceeds its 45,000.00 USD authority") |
| oracle, 31 | twelve percent | PCT_SPENT | unresolved | not fixed: the label disagrees with the key (REVENUE_FALL_PCT) |
| oracle, 33 | 6,237.75 | OVERRUN | AUTHORISED | fixed: OVERRUN "exceeded authorised budget by" (as "exceeds budget by") |
| oracle, 39 | 340 | UNITS_SHORT | unresolved | not fixed: no role-specific phrase ("340-unit … shortfall") |
| oracle, 42 | twelve percent | REVENUE_FALL_PCT | unresolved | fixed: REVENUE_FALL_PCT "revenue shortfall" |

Exactly the seven targeted rows changed; no other row's agreement changed, and the in-sample
output is identical apart from the key hash.

## Agreement on the attribute axis (gold-valued occurrences, the headline)

| Labelled set | Labeller, blind | Pre-fix lexicon | Frozen lexicon |
|---|---|---|---|
| dev, r1 pilot report (21 rows) | author, blind | 16/21, kappa 0.173 | 20/21, kappa 0.644 |
| dev, oracle report (42 rows; 40 gold-valued) | author, blind | 31/40, kappa 0.037 | 34/40, kappa 0.091 |
| dev, pooled | author, blind | 47/61, kappa 0.096 | 54/61, kappa 0.251 |
| in-sample, baseline report (24 rows; 22 gold-valued) | AI assistant, not blind | 19/22, kappa 0.784 | 19/22, kappa 0.784 |

The development rows are in-sample for the fix (it was made on them), so the frozen-lexicon
figures on them are not an out-of-sample estimate; the held-out row (EXP8, an r1 report of corpus
B labelled blind by the author after the batch) is. Full outputs: `exp2_dev_prefix.txt`,
`exp2_dev_frozen.txt`, `exp2_insample_frozen.txt` (the pre-fix in-sample output is the one quoted
in `blind/README.md`).

## Hashes

| Object | Pre-fix | Frozen |
|---|---|---|
| `scripts/corpora/rba_lexicon.py` | `740f5dd5…1df0` | `48044470…17ee` |
| key, smoke-q3 (A) | `dc1ff408…4ee0` | `dcda133a…3780` |
| key, portfolio-b (B) | `352a5dfc…cc4f` | `998d6ee0…d4ad` |
| key, prose-c (C) | `6430b96c…963f` | `7a5a9a34…be1c` |
| key, offlex-d (D) | `bbaa8143…7223` | `e54c0f00…6daf` |
| `header_lexicon.py` (unchanged) | `ad7f13ce…dbbe0` | `ad7f13ce…dbbe0` |

The pre-fix keys are kept, byte for byte, in `prefix_keys/<task_id>.json`, for r1's both-lexicon
rescoring (`run_evaluation.py aggregate --alt-key eval/calibration/prefix_keys`, one key per
corpus). The B, C and D keys also changed their `provisional` note from "not yet audited" to
"audited under scope §11", which the scorer does not read.

## Pilot rescoring

The nine pilot runs (and the in-sample run) were rescored against the frozen keys with
`run_evaluation.py rescore`, and aggregated before and after into `eval/pilot/exp2/`
(gitignored). Pilot figures are never quoted; the frozen batch measures afresh.
