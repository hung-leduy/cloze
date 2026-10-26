# Blind labelling sheets (plan task INS1, used by X5 / EXP2)

Two sheets to fill in by hand. They are the development set for calibrating
the faithfulness metric (RBA) on an R1-shaped report and on the oracle report
it is compared with.

| Sheet | Report it describes | Rows |
|---|---|---|
| `smoke-q3__r1.report.csv` | `smoke-q3__r1.report.md` (private arm r1, pilot run `eval/runs/smoke-q3__r1/report.md`) | 21 |
| `smoke-q3__r1.oracle_report.csv` | `smoke-q3__r1.oracle_report.md` (oracle arm, same run, `oracle_report.md`) | 42 |

The two `.md` files are byte-for-byte copies of the reports in that run
directory, committed here so the sheets can be checked from a clean checkout
(`eval/runs/` is gitignored). The sheets were exported by
`scripts/calibrate_faithfulness.py --export-sheet` against the gold key that
`scripts/make_smoke_corpus.py` generates on branch `plan/ins1`, sha256
`dc1ff408b1eedd44f9ee27081049519c8017ecb0ac86b887704a0ddd91d94ee0`.

On `plan/ins1b` the export was changed so that a sentence or table row that
appears twice in a report takes its `section` and `before` from its own copy,
not the first one. Neither pilot report repeats a scored sentence or row, so
both sheets re-export byte-for-byte unchanged from that code against the same
key. Their sha256 digests, for checking a copy:

| File | sha256 |
|---|---|
| `smoke-q3__r1.report.csv` | `28935179274ac0edf947172cf72816fd7bb9988f23576ea9fed0948706ed5e7e` |
| `smoke-q3__r1.oracle_report.csv` | `20a75e5125026c0fc922e019d2a4943eafa3ae1efa4a10d0f33ddfbc59667683` |
| `smoke-q3__r1.report.md` | `8fd8e34490a13a789cbf0f14ae3f3d21d3380fa132d985d2a0b6f6e73fe96dc3` |
| `smoke-q3__r1.oracle_report.md` | `00f861fa79835def6298a13023967882ddc6475cf3ac55fcfda637dea882bebf` |

## What is hidden, and why

The metric's own output is deliberately left out. There is no verdict column,
no "metric thinks this belongs to" column, and nothing else the metric decided.
The first calibration set was labelled by the metric's builder, in the same
commit as the rule, so it can only be reported as in-sample and non-blind.
These sheets are meant to give the blind rows. To keep them blind, do not open
`faithfulness_occurrences.json` or the `faithfulness` block of
`measurement.json` for this run, and do not run the calibration command below,
until both sheets are finished.

## One row

Each row is one number the metric found in the report, in document order.

- `id`: row number. Do not reorder, add or delete rows.
- `section`: the nearest heading above the number.
- `before`: the text of the same paragraph before the sentence, cut to about
  400 characters. For a table row, this is the table's header row.
- `sentence`: the sentence, with the number marked `[[like this]]`. If the same
  number appears twice in a sentence, the brackets show which one the row is
  about.
- `numeral`: the number as written.
- `referent_label`, `attribute_label`: **fill these in** (see below).
- `note`: optional free text, e.g. why a row was hard.

Do not edit `sentence`. The script uses it to check that the sheet still matches
the report. You can open the `.md` report next to the sheet if a row needs more
context than the sheet gives.

## What to write

For every row, record **what the report says the number is**. Do not record
what the corpus says is true. You do not need the gold key, and you should not
look up whether the number is right. The script checks your labels against the
key itself, using the same comparison the metric uses.

### `referent_label`: whose number is it, according to the report?

The referent is the project or organisation the report attaches the number to.
Use the sentence, the text before it, and the report if needed. Label what a
careful reader would take the report to mean. The referent may be named in an
earlier sentence ("This project...") or in a heading.

| Label | Use when the report attaches the number to |
|---|---|
| `ZEPHYR` | Project Zephyr |
| `AURORA` | Project Aurora |
| `KESTREL` | Pilot Kestrel |
| `VENDOR` | Calder Logistics |
| `ORG` | Northbridge Analytics, as the owner of the number |
| `NONE` | nobody: the report does not say whose number it is |
| `UNCLEAR` | one of several named candidates, and you cannot tell which |
| `OTHER` | something not listed: a site ("the Leeds pilot"), "the portfolio", a sum across projects |

### `attribute_label`: what kind of amount does the report say it is?

The attribute is the role the report gives the number. Pick the closest label.
Synonyms count, so "drawn", "committed" and "outlay" are all `SPENT`, and
"headroom" is `UNSPENT`.

| Label | The report says the number is |
|---|---|
| `AUTHORISED` | the authorised budget, authority, allocation or ceiling |
| `SPENT` | the amount spent or committed |
| `UNSPENT` | the unspent, remaining or uncommitted balance, or headroom |
| `OVERRUN` | the amount by which spend exceeds the authority |
| `PCT_SPENT` | the share of the authority that has been spent, as a percentage |
| `UNITS_SHORT` | the number of units short of a delivery commitment |
| `REVENUE_FALL_PCT` | the fall in revenue, as a percentage |
| `NONE` | the report does not say what the number is |
| `OTHER` | a role not listed above (for example "a variance", "a baseline figure") |

**When the report calls a number something generic.** First ask whether the
word gives the number a role at all. If it does not ("a figure of", "an amount
of", "funds of", "a sum"), write `NONE`. If it names a kind of amount that is
not in the table ("a variance", "a baseline", "a forecast", "a saving"), write
`OTHER`, unless the report makes clear that the word means one of the listed
roles: "an adverse variance of X against the authority" that is the overspend is
`OVERRUN`, and "the remaining allocation" is `UNSPENT`. `OTHER` is scored as
MISMATCH, because a report that calls the authorised budget "a variance" has
said something checkable and wrong. The first, non-blind label set
(`eval/calibration/smoke-q3_hand_labels.json`) was not consistent here: it
scored 45,000.00, which one sentence presents as "a variance", as a wrong
attribute, but left 250,000 in "variances such as 250,000" UNRESOLVED, on the ground that the metric's word
list has no variance term. Do not follow the second choice. Label what the
report says, not what the metric can see. Where the metric has no word for the
role you read, the disagreement it produces is a limit of the metric, and it is
the thing the calibration is meant to count.

Labels are not case-sensitive. Every row needs both labels. The script refuses
a sheet with a blank label, or a label not listed here, and names the row.

Some numbers are not figures from the corpus at all, for example a total the
report worked out itself. Label them anyway, in the same way. Leaving them out
would tell you which numbers the metric counted as outside the key, and that
would unblind the sheet.

### How the labels are scored (for reference, not needed to fill in)

For each row, `referent_label` and `attribute_label` are compared with the key's
owners of that number. The result is a verdict on each axis: MATCH, MISMATCH,
UNRESOLVED (`NONE`) or AMBIGUOUS (`UNCLEAR`, referent only). `OTHER` counts as
MISMATCH, because it is a checkable claim that the number is something it is
not. These verdicts are then compared with the metric's verdicts.

## After both sheets are filled

Save them as CSV (UTF-8) under the same names, then run:

```bash
.venv/bin/python scripts/calibrate_faithfulness.py \
  --report eval/calibration/blind/smoke-q3__r1.report.md \
  --labels eval/calibration/blind/smoke-q3__r1.report.csv \
  --report eval/calibration/blind/smoke-q3__r1.oracle_report.md \
  --labels eval/calibration/blind/smoke-q3__r1.oracle_report.csv
```

For each report, and pooled over both, the script prints per-axis agreement,
attribute-axis agreement and Cohen's kappa, and every attribute-axis
disagreement with its sentence. Only the attribute axis is quoted in the paper.

The attribute axis is printed twice. The headline is over **gold-valued
occurrences** only, the rows whose number the key owns. The second figure is
over **all rows**, and it is labelled with how many of them are outside the key.
A number outside the key has no owner, so both the metric and the sheet score
its attribute UNRESOLVED whatever was written. Those rows agree by
construction, and counting them raises both the agreement and kappa without
measuring anything either reader did. Quote the gold-valued pair. The all-rows
pair is kept so that earlier figures stay reproducible. On the first, non-blind
set (`eval/runs/smoke-q3/report.md` with `eval/calibration/smoke-q3_hand_labels.json`)
the headline is 19/22 (86%), kappa 0.784, and the all-rows figure is 21/24
(88%), kappa 0.810, where the two numbers outside the key account for the
difference.
