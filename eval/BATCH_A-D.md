# The frozen A-D batch of 2026-10-07

*Recorded by the AI assistant on 2026-10-07. The batch ran under the author's approval of a
$27 cap (plan Part D AD38) after the author held snap refreshes (`sudo snap refresh
--hold=72h`, held until 2026-10-10 13:29).*

All of it ran from the checkout at the tag `paper-freeze` (commit `0d5e86b`, tree clean), as
user systemd services so that it survived the session; every step's log is under `build/batch/`
(gitignored). The results are in `eval/evaluation.json` and `eval/runs/` (never committed); the
EXP7 outputs are `eval/probe/*.json`, `eval/fp_report.json` and `eval/observation.json`.

## What ran

| When (+07) | Step | Outcome |
|---|---|---|
| 13:30 | `scripts/freeze_batch.sh --yes --archive-pilot` | pre-flight passed; the pilot's runs moved to `eval/pilot/runs-before-paper-freeze-20261007133005/` |
| 13:30-14:34 | phase one: r5 repeat 1 with a fresh extraction per corpus, then r5 repeats 2-3, baseline and r1 repeats 1-3 reusing it | 36 runs, no section and no plan refused |
| 14:34-14:39 | phase two, r5 repeat 1 | smoke-q3, portfolio-b and prose-c measured; for offlex-d the oracle's outline call returned no usable section (`RuntimeError: oracle planner produced no usable sections`, `backend/src/privdeep/eval/oracle.py:167`), and the script stopped |
| 16:56-17:54 | resume: phase two with the script's own commands, each `measure` call retried once in a second pass (`build/batch/resume_after_phase_one.sh`) | offlex-d's oracle succeeded on the retry; 36 tasks measured; no failure in either pass |
| 17:54 | `aggregate --out eval/evaluation.json` | health gate 36/36 valid |
| 17:54-17:58 | EXP7 as the script ordered it | smoke-q3's three extra extractions and its analysis ran; the analysis rewrote the tracked `eval/probe/smoke-q3.json`, so portfolio-b's extraction refused the now dirty tree |
| 17:58-18:10 | EXP7 resumed (`build/batch/resume_exp7.sh`): smoke-q3's analysis set aside, the tracked file restored, the three remaining extractions run on the clean tree, then the three analyses, the false-positive measurement and the observation table; smoke-q3's analysis put back | done; 0 monitor refusals over 313 egress attempts |

Rerunning `freeze_batch.sh` was not possible: `--archive-pilot` would have moved the batch's own
runs away. The two resume scripts run the same commands as `freeze_batch.sh`, from the same
checkout, with the tree clean at each start; no instrument, key or lexicon changed. After the
batch, `freeze_batch.sh` runs every extraction before any analysis, so a rerun cannot stop where
this one did.

## Cost

- Phase one: 705,744 input and 261,158 output tokens over the 36 runs' traced exchanges, about
  $4.0 at the list rates (cache reads, cheaper, are counted at the full rate).
- Phase two: $9.42 recorded by the measurements (oracle $1.80, judge $4.30, adversary $3.32).
- Not recorded: the failed oracle outline call for offlex-d.
- Total about $13.4 against the $27 cap and the dry run's over-estimate of about $25.6.

## Afterwards

- EXP8: the held-out sheet `eval/calibration/heldout/portfolio-b__r1.report.csv` (27 rows) was
  exported from corpus B's first r1 run for the author to label blind.
- Track L (scope §12) runs only after the author signs §12, at the tag `real-freeze`, whose
  container code must equal `paper-freeze`'s.
