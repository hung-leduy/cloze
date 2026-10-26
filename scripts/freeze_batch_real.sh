#!/usr/bin/env bash
# Track L's batch (scope §12): leakage on public court judgments standing in for
# private documents, at the tag real-freeze, after the A-D batch and its backstop.
#
#   scripts/freeze_batch_real.sh --dry-run          # pre-flight and estimates; spends nothing
#   scripts/freeze_batch_real.sh --yes --spent USD  # the batch; BILLABLE, cap $15 (§12.9);
#                                                   # USD: what track L spent before (the pilot)
#   scripts/freeze_batch_real.sh --yes --fit-cap    # run only the whole collections the cap admits
#   scripts/freeze_batch_real.sh --yes --resume     # continue a stopped batch; runs on disk are kept
#   scripts/freeze_batch_real.sh --pilot --dry-run  # tab-L0, one repeat per arm, eval/pilot/real-l/
#   scripts/freeze_batch_real.sh --pilot --yes      # the pilot; BILLABLE, inside the same cap
#
# What it runs, in order, each step stopping the batch on failure:
#   1. pre-flight, all of it before the .env is read or docker is touched:
#      HEAD is the tag real-freeze; tracked files are clean; scope §12 is signed
#      (a filled signature line with a date, no DRAFT status, no blank left in
#      §12, the §12.12 record included: no billable track-L run, the pilot
#      included, starts before that); git ignores every path that holds TAB text;
#      git diff real-prereg..real-freeze is empty on the track-L paths, §12 is
#      unchanged since real-prereg, and git diff paper-freeze..real-freeze is
#      empty on the code the containers run (§12.8; a bug fix there needs a
#      changelog entry the author signs, and is not this script's call). The
#      pilot precedes the tags and checks neither. The runs and attempts
#      directories are empty (--resume keeps them); the A-D batch's manifests
#      exist, for the §12.8 digest check; and what track L spent before is
#      known: the pilot's runs are on disk, or --spent says it.
#   2. the SLM sees the GPU (NVML); the collections are rebuilt from data/tab
#      (the builder checks SHA256SUMS and refuses a build that differs from the
#      committed manifest) and checked again, file by file, against
#      eval/real/manifest_l.json;
#   3. the estimate, itemised per collection, against the cap: whole
#      collections are admitted in order while the over-estimate fits, so at
#      the cap no new collection starts and one left out is left out whole and
#      named; if any is left out the batch asks, by refusing, unless --fit-cap;
#   4. phase one over the admitted collections (run_evaluation.py private),
#      each step over the collections real_l.py pending names: not on disk,
#      never attempted (a pipeline that exited non-zero, every section refused
#      among them, is not run again), and with r5's extraction when it reuses
#      it. r5 repeat 1 with one fresh extraction per collection and the monitor
#      and core recreated once; a transport failure there is re-run once before
#      anything reuses that extraction, unless something already does; then r5
#      repeat 2 and baseline and r1 repeats 1-2 reusing it, and their transport
#      failures re-run once (§12.5, §12.9). A run whose one re-run is spent is
#      not offered again. Each re-run pass is priced against what the runs
#      recorded spending, and refused over the cap. A pipeline that exits
#      non-zero stops the batch, as in freeze_batch.sh, and leaves its attempt
#      under the attempts directory, which the scan reads; except (§12.13) a
#      run the monitor refused at its planner request, which is kept as an
#      attempt and lets the batch continue;
#   5. the G3 adversary on each arm's first repeat and one goal-only control
#      per collection (real_l.py adversary, its --max-usd the cap less what was
#      recorded), the scan over the registered collections, so a collection
#      left out makes HL1 not testable by name (real_l.py scan, with the §12.8
#      digest check against eval/runs, which HL1 is gated on), and the Presidio
#      reference (offline).
#
# The GPU is checked before every phase-one step, as in freeze_batch.sh: snapd's
# automatic refresh drops the container's NVML access. Hold refreshes first:
# `sudo snap refresh --hold=72h`. The API key is read from the one .env file
# below into the environment, never printed, and only under --yes.
# PRIVDEEP_BATCH_TEST=1 (the tests) stops --yes where that .env would be read.
set -euo pipefail

TAG=real-freeze
PREREG=real-prereg
PAPER_TAG=paper-freeze
CAP_USD=15
# The paths are relative to the checkout root, which the script cds to before using them.
ENV_FILE=.env
TEST_MODE=${PRIVDEEP_BATCH_TEST:-}
# Under the tests' switch the path is theirs (a marker file), so even a broken
# guard below could not read the real .env; outside it, nothing overrides it.
if [ -n "$TEST_MODE" ]; then ENV_FILE=${PRIVDEEP_ENV_FILE:-/dev/null}; fi
PY=${PY:-.venv/bin/python}
PRESIDIO_PY=${PRESIDIO_PY:-.venv-presidio/bin/python}
SCOPE=PRIVDEEP_ICCIT_SCOPE.md
MANIFEST=eval/real/manifest_l.json
# §12.8: what real-prereg commits (the builder, the record, the analysis
# scripts and the tests that pin them), and what the containers run. §12 itself
# is compared on its own, since other sections of the scope may move.
TRACK_L_PATHS=(scripts/real_corpora scripts/real_l.py scripts/presidio_residual.py
               scripts/freeze_batch_real.sh eval/real/manifest_l.json eval/real/tasks_l.json
               eval/real/tasks_l_dev.json backend/tests/unit/test_real_tab.py
               backend/tests/unit/test_real_l.py backend/tests/unit/test_presidio_residual.py)
CONTAINER_PATHS=(backend/src gateway ':(exclude)gateway/tests' shared docker-compose.yml
                 scripts/run_evaluation.py scripts/corpora scripts/tier1_probe.py
                 scripts/observation_table.py scripts/measure_false_positives.py pyproject.toml)
# Paths that hold TAB text or what was run on it; git must ignore every one.
IGNORED_PATHS=(eval/real/corpora/tab-L1/doc1.md eval/real/runs/tab-L1__r5/egress_trace.jsonl
               eval/real/attempts/tab-L1__r5__attempt1/egress_trace.jsonl
               eval/real/out/real_l_scan.json eval/pilot/real-l/runs/tab-L0__r5/report.md
               data/tab/echr_test.json)

YES=0; DRY=0; PILOT=0; FIT_CAP=0; RESUME=0; SPENT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) YES=1 ;;
    --dry-run) DRY=1 ;;
    --pilot) PILOT=1 ;;
    --fit-cap) FIT_CAP=1 ;;
    --resume) RESUME=1 ;;
    --spent) shift; SPENT=${1:?--spent needs an amount in USD} ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done
if [ "$YES" = 1 ] && [ "$DRY" = 1 ]; then echo "--yes and --dry-run exclude each other" >&2; exit 2; fi
if [ "$YES" = 0 ] && [ "$DRY" = 0 ]; then echo "pass --dry-run, or --yes to spend" >&2; exit 2; fi

if [ "$PILOT" = 1 ]; then
  TASKS=eval/real/tasks_l_dev.json; RUNS=eval/pilot/real-l/runs; OUT=eval/pilot/real-l/out
  REPS=1; ADV_ARMS=(r5)            # §12.5: one run per arm, one adversary call and its control
else
  TASKS=eval/real/tasks_l.json; RUNS=eval/real/runs; OUT=eval/real/out
  REPS=2; ADV_ARMS=(r5 baseline r1)
fi
ATTEMPTS="$(dirname "$RUNS")/attempts"

cd "$(git rev-parse --show-toplevel)"

say() { echo "== $(date -Is) $*"; }
# A refusal under --yes; a warning in a dry run, which may precede the tags.
refuse() {
  if [ "$YES" = 1 ]; then say "ABORT: $*"; exit 3; fi
  say "WARNING (dry run): $*"
}
# §12 of a scope text, up to the next section heading.
section12() { awk '/^## 12\. /{on=1; print; next} on && /^## /{exit} on'; }

# 1. pre-flight, git and files only ----------------------------------------------
# Outputs are captured before grep reads them: under pipefail, `producer | grep -q`
# fails when grep stops early and the producer takes SIGPIPE, which would turn a
# match into a miss.
say "pre-flight ($([ "$PILOT" = 1 ] && echo "pilot, tab-L0" || echo "batch, tab-L1 to tab-L6"))"
head_tags=$(git tag --points-at HEAD)
if [ "$PILOT" = 0 ] && ! grep -qx "$TAG" <<<"$head_tags"; then
  refuse "HEAD is not the tag $TAG"
fi
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  say "ABORT: tracked files differ from HEAD"; git status --short --untracked-files=no; exit 3
fi
# The signature, failing closed: a filled line in the scope's own forms, and
# nothing of the draft left (its status, a blank, the §12.12 record).
scope_text=$(cat "$SCOPE" 2>/dev/null || true)
sec12=$(section12 <<<"$scope_text")
if [ -z "$sec12" ]; then
  refuse "$SCOPE has no §12; track L is not in the scope"
elif grep -q 'Status: DRAFT' <<<"$sec12"; then
  refuse "scope §12 is not signed: it still says 'Status: DRAFT'; no billable track-L run, the pilot included, starts before the author signs it"
elif grep -q '_\{4,\}' <<<"$sec12"; then
  refuse "scope §12 is not signed: a blank is left (the signature or the §12.12 record); no billable track-L run, the pilot included, starts before it is filled and signed"
elif ! grep -Eq '^(Signed by the author on [0-9]{4}-[0-9]{2}-[0-9]{2}|Signed: [^_[:space:]].*\(author\), date [0-9]{4}-[0-9]{2}-[0-9]{2})' <<<"$sec12"; then
  refuse "scope §12 is not signed: no signature line with a date; no billable track-L run, the pilot included, starts before it"
fi
for p in "${IGNORED_PATHS[@]}"; do
  git check-ignore -q -- "$p" || refuse "git does not ignore $p; TAB text may only be written where it does"
done
if [ "$PILOT" = 0 ]; then
  for t in "$PREREG" "$PAPER_TAG"; do
    git rev-parse -q --verify "refs/tags/$t" >/dev/null || refuse "the tag $t does not exist"
  done
  if git rev-parse -q --verify "refs/tags/$PREREG" >/dev/null; then
    if ! git diff --quiet "$PREREG" HEAD -- "${TRACK_L_PATHS[@]}"; then
      git diff --stat "$PREREG" HEAD -- "${TRACK_L_PATHS[@]}"
      refuse "the track-L paths differ between $PREREG and HEAD (§12.8)"
    fi
    prereg_scope=$(git show "$PREREG:$SCOPE" 2>/dev/null || true)
    if [ "$(section12 <<<"$prereg_scope")" != "$sec12" ]; then
      refuse "scope §12 differs between $PREREG and HEAD (§12.8)"
    fi
  fi
  if git rev-parse -q --verify "refs/tags/$PAPER_TAG" >/dev/null \
     && ! git diff --quiet "$PAPER_TAG" HEAD -- "${CONTAINER_PATHS[@]}"; then
    # §12.13: the one patch the author signed (the refusal path of pipeline.py)
    # is accepted in place of an empty diff, by the sha256 of the diff that the
    # changelog records; any other difference still refuses.
    signed=$({ grep -oE 'container-code diff sha256 [0-9a-f]{64}' <<<"$sec12" || true; } | awk '{print $NF}' | head -1)
    actual=$(git diff "$PAPER_TAG" HEAD -- "${CONTAINER_PATHS[@]}" | sha256sum | awk '{print $1}')
    if [ -n "$signed" ] && [ "$signed" = "$actual" ]; then
      say "the code the containers run differs from $PAPER_TAG by the patch §12.13 signs (diff sha256 $actual)"
    else
      git diff --stat "$PAPER_TAG" HEAD -- "${CONTAINER_PATHS[@]}"
      refuse "the code the containers run differs between $PAPER_TAG and HEAD (§12.8), and not by the patch §12.13 signs"
    fi
  fi
  if ! ls eval/runs/*/manifest.json >/dev/null 2>&1; then
    refuse "no A-D batch manifest under eval/runs; track L runs after the A-D batch, and §12.8 compares digests with it"
  fi
fi
for d in "$RUNS" "$ATTEMPTS"; do
  if [ -d "$d" ] && [ -n "$(ls -A "$d" 2>/dev/null)" ]; then
    if [ "$RESUME" = 1 ]; then say "resuming: what is in $d is kept"
    else refuse "$d is not empty (--resume continues a stopped batch)"; fi
  fi
done
PILOT_RUNS=eval/pilot/real-l/runs
if [ -z "$SPENT" ]; then
  if [ "$PILOT" = 1 ]; then
    SPENT=0
  elif [ -n "$(ls -A "$PILOT_RUNS" 2>/dev/null)" ]; then
    SPENT=pilot
  else
    refuse "the pilot's runs are not in this checkout; pass --spent USD, what track L has spent before, so the cap counts it (§12.9)"
    SPENT=0
  fi
fi

# 2. the stack, the collections -------------------------------------------------
export COMPOSE_PROJECT_NAME=privdeep COMPOSE_ENV_FILES="$ENV_FILE"
if [ "$YES" = 1 ]; then
  if [ -n "$TEST_MODE" ]; then
    say "ABORT: test mode (PRIVDEEP_BATCH_TEST): the pre-flight passed; no .env is read and nothing is spent"
    exit 3
  fi
  set +x
  set -a; . "$ENV_FILE"; set +a
fi
gpu() {
  docker exec privdeep-local-slm nvidia-smi --query-gpu=name --format=csv,noheader >/dev/null 2>&1 \
    || { say "ABORT: the SLM container cannot see the GPU (NVML); docker restart privdeep-local-slm"; exit 3; }
}
gpu
if command -v snap >/dev/null && ! grep -q '^hold:' <<<"$(snap refresh --time 2>/dev/null || true)"; then
  say "WARNING: snap refreshes are not held; run: sudo snap refresh --hold=72h"
fi
say "rebuilding the collections from data/tab"
"$PY" scripts/real_corpora/tab.py --tab data/tab --out eval/real/corpora
"$PY" scripts/real_corpora/tab.py --tab data/tab --out eval/real/corpora --check
"$PY" scripts/real_l.py verify --tasks "$TASKS" --manifest "$MANIFEST"

# 3. estimate and cap -------------------------------------------------------------
mkdir -p "$OUT"
if [ "$SPENT" = pilot ]; then
  # The pilot spends from the same $15 (§12.9); its own over-estimate stands in
  # for what it cost (--spent overrides).
  SPENT=$("$PY" scripts/real_l.py estimate --tasks eval/real/tasks_l_dev.json \
          --runs "$PILOT_RUNS" --reps 1 --adversary-arms r5 --fresh --total-only)
  say "the pilot's runs are on disk; its estimate, \$$SPENT, is taken off the cap (--spent overrides)"
fi
ADMITTED="$OUT/tasks_admitted.json"
set +e
"$PY" scripts/real_l.py estimate --tasks "$TASKS" --runs "$RUNS" --reps "$REPS" \
  --adversary-arms "${ADV_ARMS[@]}" --cap "$CAP_USD" --spent "$SPENT" --admit-out "$ADMITTED"
rc=$?
set -e
case "$rc" in
  0) ;;
  4) if [ "$FIT_CAP" = 1 ]; then say "running only the admitted collections; the rest are left out whole"
     else refuse "the estimate exceeds the cap; --fit-cap runs only the whole collections it admits"; fi ;;
  5) refuse "no collection fits under the cap" ;;
  *) say "ABORT: the estimate failed (exit $rc)"; exit 3 ;;
esac
if [ "$DRY" = 1 ]; then say "dry run ends before phase one"; exit 0; fi

# 4. phase one --------------------------------------------------------------------
priv() { "$PY" scripts/run_evaluation.py private --runs "$RUNS" --yes "$@"; }
count() { "$PY" -c 'import json, sys; print(len(json.load(open(sys.argv[1], encoding="utf-8"))))' "$1"; }
RECREATE=(--recreate)      # the monitor and core, once, before the first run of the batch
# One phase-one step over the collections that may still run it.
step() {   # $1 arm, $2 repeat, then run_evaluation flags
  local arm=$1 rep=$2 f="$OUT/tasks_step.json"
  shift 2
  local -a reuse=()
  if [ "$arm" != r5 ] || [ "$rep" != 1 ]; then reuse=(--reuse-from r5); fi
  # The driver stops at its first failed task, so the step loops: after a
  # planner refusal (§12.13) the refused task is an attempt, `pending` leaves it
  # out, and the driver is called again for the tasks it had not reached.
  while :; do
    "$PY" scripts/real_l.py pending --tasks "$ADMITTED" --runs "$RUNS" --arm "$arm" --rep "$rep" \
      ${reuse[@]+"${reuse[@]}"} --out "$f"
    if [ "$(count "$f")" = 0 ]; then return 0; fi
    gpu; say "phase one: $arm repeat $rep ($(count "$f") task(s))"
    local rc=0
    priv --tasks "$f" --arm "$arm" --rep "$rep" ${RECREATE[@]+"${RECREATE[@]}"} "$@" || rc=$?
    RECREATE=()
    if [ "$rc" = 0 ]; then return 0; fi
    # §12.13: a run the monitor refused at its planner request is an outcome,
    # kept as an attempt, and the batch continues; any other failure stops it.
    # Only the tasks that failed are judged: a task with a run is done, and a
    # task with neither run nor attempt was not reached by the driver.
    if "$PY" - "$f" "$RUNS" "$ATTEMPTS" "$arm" <<'PYEOF'
import json, sys
from pathlib import Path
tasks = json.load(open(sys.argv[1], encoding="utf-8"))
runs = Path(sys.argv[2]); attempts = Path(sys.argv[3]); arm = sys.argv[4]
bad, refused = [], []
for t in tasks:
    tid = t["id"]
    if (runs / f"{tid}__{arm}").is_dir():
        continue
    dirs = sorted(attempts.glob(f"{tid}__{arm}__attempt*"))
    if not dirs:
        continue
    notes = []
    for d in dirs:
        m = d / "manifest.json"
        if m.is_file():
            notes += json.load(open(m, encoding="utf-8")).get("notes", [])
    (refused if any(n.startswith("planning refused by monitor") for n in notes) else bad).append(tid)
if bad or not refused:
    print("not a planner refusal: " + ", ".join(bad or ["(no failed task found)"])); sys.exit(1)
print("planner refused by the monitor: " + ", ".join(refused) + "; kept as attempts, the batch continues (§12.13)")
PYEOF
    then :; else say "ABORT: phase one failed for a reason other than a planner refusal (exit $rc)"; exit 3; fi
  done
}
# One re-run, and only for a transport failure (§12.9), of each run the health
# check names; each through a one-task tasks file so nothing else re-runs. A run
# whose re-run is spent reads transport-failure-rerun-used and is not named. Two
# passes, each run in exactly one: r5 repeat 1 first, before anything reuses its
# extraction (its re-run extracts afresh), then every other run, reusing it.
rerun_transport() {   # $1: first | rest
  local line id arm rep one reuse
  local -a failed=() todo=()
  if [ "$1" = first ]; then
    mapfile -t failed < <("$PY" scripts/real_l.py health --tasks "$ADMITTED" --runs "$RUNS" \
                            --arms r5 --reps 1 --only transport-failure)
  else
    mapfile -t failed < <("$PY" scripts/real_l.py health --tasks "$ADMITTED" --runs "$RUNS" \
                            --reps "$REPS" --only transport-failure)
  fi
  for line in ${failed[@]+"${failed[@]}"}; do
    read -r id arm rep _ <<<"$line"
    if [ "$1" = rest ] && [ "$arm" = r5 ] && [ "$rep" = 1 ]; then continue; fi
    if [ "$1" = first ] && [ -n "$(find "$RUNS" -mindepth 1 -maxdepth 1 -type d \
         -name "${id}__*" ! -name "${id}__r5" -print -quit)" ]; then
      # Under --resume: other runs already reuse this extraction, and a fresh
      # one would leave them on another. Its cell stays a transport failure.
      say "NOT re-running $id r5 repeat 1: other runs of $id already reuse its extraction"
      continue
    fi
    todo+=("$line")
  done
  if [ "${#todo[@]}" = 0 ]; then return 0; fi
  if ! "$PY" scripts/real_l.py budget --runs "$RUNS" --cap "$CAP_USD" --spent "$SPENT" \
       --need-reruns "${#todo[@]}"; then
    say "ABORT: the ${#todo[@]} transport re-run(s) would exceed the cap; nothing was re-run"
    exit 3
  fi
  for line in "${todo[@]}"; do
    read -r id arm rep _ <<<"$line"
    one="$OUT/tasks_rerun_${id}.json"
    "$PY" -c 'import json, sys
ts = [t for t in json.load(open(sys.argv[1], encoding="utf-8")) if t["id"] == sys.argv[2]]
json.dump(ts, open(sys.argv[3], "w", encoding="utf-8"), indent=2)' "$ADMITTED" "$id" "$one"
    reuse=""
    if [ "$arm" != r5 ] || [ "$rep" != 1 ]; then reuse="--reuse-extraction-from r5"; fi
    gpu; say "re-running $id $arm repeat $rep once, after a transport failure"
    # shellcheck disable=SC2086
    priv --tasks "$one" --arm "$arm" --rep "$rep" $reuse --force
  done
}
step r5 1
rerun_transport first
for rep in $(seq 2 "$REPS"); do
  step r5 "$rep" --reuse-extraction-from r5
done
for arm in baseline r1; do
  for rep in $(seq 1 "$REPS"); do
    step "$arm" "$rep" --reuse-extraction-from r5
  done
done
rerun_transport rest

# 5. G3, scan, Presidio -------------------------------------------------------------
"$PY" scripts/real_l.py budget --runs "$RUNS" --cap "$CAP_USD" --spent "$SPENT"
REMAINING=$("$PY" scripts/real_l.py budget --runs "$RUNS" --cap "$CAP_USD" --spent "$SPENT" \
            --remaining-only)
say "G3: the adversary on each arm's first repeat (${ADV_ARMS[*]}) and a goal-only control per collection, within \$$REMAINING"
"$PY" scripts/real_l.py adversary --tasks "$ADMITTED" --runs "$RUNS" --arms "${ADV_ARMS[@]}" \
  --max-usd "$REMAINING" --yes
say "scan"
reference=()
if [ "$PILOT" = 0 ]; then reference=(--reference-runs eval/runs); fi
"$PY" scripts/real_l.py scan --tasks "$TASKS" --runs "$RUNS" --out "$OUT/real_l_scan.json" \
  ${reference[@]+"${reference[@]}"}
say "Presidio reference (offline, free)"
"$PRESIDIO_PY" scripts/presidio_residual.py --tasks "$TASKS" --out "$OUT"
"$PY" scripts/real_l.py budget --runs "$RUNS" --cap "$CAP_USD" --spent "$SPENT"
say "done"
