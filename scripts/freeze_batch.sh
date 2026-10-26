#!/usr/bin/env bash
# The frozen batch (plan tasks EXP6 and EXP7), at the tag paper-freeze.
#
#   scripts/freeze_batch.sh --dry-run            # pre-flight and cost estimates; spends nothing
#   scripts/freeze_batch.sh --yes                # the batch; BILLABLE (decision 7b)
#   scripts/freeze_batch.sh --yes --archive-pilot
#
# What it runs, in order, each step stopping the batch on failure:
#   1. pre-flight: HEAD is the tag paper-freeze and the tree is clean; the SLM
#      container sees the GPU (NVML); eval/runs holds no earlier run (the
#      pilot's smoke-q3 runs share corpus A's run names, so they are moved to
#      eval/pilot/ with --archive-pilot rather than silently skipped);
#   2. phase one: r5 repeat 1 on every corpus with --recreate (the one fresh
#      extraction per corpus), then r5 repeats 2-3 and baseline and r1 repeats
#      1-3 reusing it (scope §8.7: one shared extraction per corpus, three
#      repeats per arm);
#   3. phase two: measure every arm and repeat with three judge repeats;
#   4. aggregate into eval/evaluation.json;
#   5. the local measurements (EXP7, no cloud call): three extra extractions
#      per corpus and the Tier-1 probe over them and the batch's (its G1
#      inventory built from every corpus's batch r5 extraction), the
#      false-positive measurement through the deployed chain, and the
#      observation table over every run and attempt.
#
# The GPU is checked before every phase-one step: snapd's automatic refresh
# runs `systemctl daemon-reload`, which drops the container's NVML access and
# puts the SLM on the CPU (seen twice on 2026-09-27). Hold refreshes first:
# `sudo snap refresh --hold=72h`. The API key is read from the .env file into
# the environment and never printed.
set -euo pipefail

TAG=paper-freeze
REPS=3
JUDGE_REPEATS=3
TASKS=eval/tasks.json
RUNS=eval/runs
CORPORA=(smoke-q3 portfolio-b prose-c offlex-d)
# Both paths are relative to the checkout root, which the script cds to before using them.
ENV_FILE=.env
PY=${PY:-.venv/bin/python}

YES=0; DRY=0; ARCHIVE_PILOT=0
for a in "$@"; do
  case "$a" in
    --yes) YES=1 ;;
    --dry-run) DRY=1 ;;
    --archive-pilot) ARCHIVE_PILOT=1 ;;
    *) echo "unknown argument: $a" >&2; exit 2 ;;
  esac
done
if [ "$YES" = 1 ] && [ "$DRY" = 1 ]; then echo "--yes and --dry-run exclude each other" >&2; exit 2; fi
if [ "$YES" = 0 ] && [ "$DRY" = 0 ]; then echo "pass --dry-run, or --yes to spend" >&2; exit 2; fi

cd "$(git rev-parse --show-toplevel)"
export COMPOSE_PROJECT_NAME=privdeep COMPOSE_ENV_FILES="$ENV_FILE"
set +x
set -a; . "$ENV_FILE"; set +a

say() { echo "== $(date -Is) $*"; }
gpu() {
  docker exec privdeep-local-slm nvidia-smi --query-gpu=name --format=csv,noheader >/dev/null 2>&1 \
    || { say "ABORT: the SLM container cannot see the GPU (NVML); docker restart privdeep-local-slm"; exit 3; }
}
drv() { "$PY" scripts/run_evaluation.py "$@" --tasks "$TASKS" --runs "$RUNS"; }
spend() { if [ "$YES" = 1 ]; then drv "$@" --yes; else drv "$@" || true; fi; }

# 1. pre-flight --------------------------------------------------------------
say "pre-flight"
head_tag=$(git describe --tags --exact-match HEAD 2>/dev/null || true)
if [ "$head_tag" != "$TAG" ]; then
  if [ "$YES" = 1 ]; then say "ABORT: HEAD is not the tag $TAG (git describe: '${head_tag:-none}')"; exit 3; fi
  say "WARNING (dry run): HEAD is not the tag $TAG"
fi
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  say "ABORT: tracked files differ from HEAD"; git status --short --untracked-files=no; exit 3
fi
gpu
if command -v snap >/dev/null && ! snap refresh --time 2>/dev/null | grep -q '^hold:'; then
  say "WARNING: snap refreshes are not held; run: sudo snap refresh --hold=72h"
fi
if [ -d "$RUNS" ] && [ -n "$(ls -A "$RUNS" 2>/dev/null)" ]; then
  if [ "$ARCHIVE_PILOT" = 1 ] && [ "$YES" = 1 ]; then
    dest="eval/pilot/runs-before-$TAG-$(date +%Y%m%d%H%M%S)"
    mkdir -p "$dest"; mv "$RUNS"/* "$dest"/; say "moved the earlier runs to $dest"
  elif [ "$YES" = 1 ]; then
    say "ABORT: $RUNS is not empty; rerun with --archive-pilot to move its runs to eval/pilot/"; exit 3
  else
    say "WARNING (dry run): $RUNS is not empty; the batch needs --archive-pilot"
  fi
fi

# 2. phase one ---------------------------------------------------------------
gpu; say "phase one: r5 repeat 1, fresh extraction per corpus, monitor and core recreated"
spend private --arm r5 --rep 1 --recreate
for rep in $(seq 2 "$REPS"); do
  gpu; say "phase one: r5 repeat $rep (reusing repeat 1's extraction)"
  spend private --arm r5 --rep "$rep" --reuse-extraction-from r5
done
for arm in baseline r1; do
  for rep in $(seq 1 "$REPS"); do
    gpu; say "phase one: $arm repeat $rep (reusing r5's extraction)"
    spend private --arm "$arm" --rep "$rep" --reuse-extraction-from r5
  done
done

# 3. phase two ---------------------------------------------------------------
for arm in r5 baseline r1; do
  for rep in $(seq 1 "$REPS"); do
    say "phase two: $arm repeat $rep"
    spend measure --arm "$arm" --rep "$rep" --judge-repeats "$JUDGE_REPEATS"
  done
done
if [ "$DRY" = 1 ]; then say "dry run ends before aggregate and the local measurements"; exit 0; fi

# 4. aggregate ----------------------------------------------------------------
say "aggregate"
drv aggregate --out eval/evaluation.json

# 5. local measurements (EXP7) ------------------------------------------------
# Every extraction first, then every analysis: an analysis rewrites the tracked
# eval/probe/<corpus>.json, and an extraction refuses a dirty tree. Interleaved, as
# the batch of 2026-10-07 ran them, the second extraction stopped the batch
# (eval/BATCH_A-D.md).
for c in "${CORPORA[@]}"; do
  gpu; say "probe: three extra extractions of $c"
  "$PY" scripts/tier1_probe.py extract "eval/corpora/$c" --k 3
done
for c in "${CORPORA[@]}"; do
  # The batch's extraction first: the probe builds this corpus's G1 row from the
  # first one listed. Every other corpus's G1 row is built from its own batch
  # extraction (CORPUS=FILE), not the stub; make_paper_tables.py refuses a
  # stub-based G1. extraction_*.json leaves out extract_manifest.json.
  say "probe: analysis of $c"
  "$PY" scripts/tier1_probe.py analyse "eval/corpora/$c" \
    --extractions "$RUNS/${c}__r5/extractions.json" "eval/probe/extractions/$c"/extraction_*.json \
    --g1 $(for o in "${CORPORA[@]}"; do [ "$o" != "$c" ] && echo "eval/corpora/$o=$RUNS/${o}__r5/extractions.json"; done) \
    --out "eval/probe/$c.json"
done
say "false positives through the deployed chain"
"$PY" scripts/measure_false_positives.py --out eval/fp_report.json
say "observation table"
"$PY" scripts/observation_table.py "$RUNS" --attempts eval/attempts --out eval/observation.json
say "done"
