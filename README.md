# Cloze

Code and data for the paper **"Cloze: A Reference Monitor and Local Role Binding for Private
Deep Research"** (Hung Le Duy and Tam Tran Huu, ICCIT 2026).

Cloze is a deep-research agent over private documents. A trusted local tier holds the corpus, a
local small language model (SLM) and the core that builds every request. The system's own
requests reach the cloud model only through the reference monitor **M** (`gateway/`), which
refuses a request that holds a run of 5 or more corpus words within one inspected stream. R1, the
local fact store, binds the values the cloud's drafts refer to back to their roles locally. The
evaluation's oracle, judge and adversary are not part of the system: they call the cloud from the
host and do not pass through M (`THREAT_MODEL.md` §5).

The working name of the system was PrivDeep, so the Python package (`privdeep`), the container
names and the networks (`privdeep-*`) keep it.

## Layout

| Path | What it holds |
|---|---|
| `gateway/` | The reference monitor M: the egress proxy, its containment filter and audit log |
| `backend/src/privdeep/` | The local tier: extraction with the SLM, masking, R1, the core, drafting and restoration; under `eval/`, the evaluation's oracle, judge and adversary clients, which bypass M |
| `shared/` | Code both tiers use |
| `backend/tests/`, `gateway/tests/` | The test suite; `-m security` runs the invariant tests that pin the threat model's properties |
| `THREAT_MODEL.md` | Parties, adversary, observation set, and what is and is not protected (properties P1-P9) |
| `PRIVDEEP_ICCIT_SCOPE.md` | The pre-registration of 2026-09-27 (hypotheses H1-H3, H4-D, H4-D′, the H2 floor rule) and its dated amendments, including track L's HL1 |
| `scripts/corpora/` | The generator of the synthetic corpora A-D (byte-deterministic) and the RBA attribute lexicon |
| `eval/corpora/` | Corpora A-D (`smoke-q3`, `portfolio-b`, `prose-c`, `offlex-d`), their gold keys and the key audit |
| `eval/calibration/` | The reports the RBA rule was calibrated and checked on, and their labels |
| `eval/real/` | Track L's task and manifest files (TAB document ids and file hashes, no judgment text) |
| `eval/probe/`, `eval/fp_report.json`, `eval/observation.json`, `eval/BATCH_A-D.md` | The extraction probes, the false-positive report, the observation-set test and the record of the frozen batch |
| `scripts/run_evaluation.py` | The evaluation driver: `private` and `measure` call the cloud (billable), `aggregate` and `rescore` are offline |
| `scripts/make_paper_tables.py` | Computes the paper's numbers, tables and figures from the runs (see below for what it needs) |

## Running

Host prerequisites: Docker with Compose, an NVIDIA GPU with the NVIDIA Container Toolkit, Ollama
on the host with the SLM already pulled (`ollama pull qwen3:14b`; the SLM container mounts the
host's model store read-only, `OLLAMA_MODELS_HOST`, and has no route out to pull it), and
Python 3.12.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt -r gateway/requirements.txt pytest ruff
make test            # the suite; no network, no cost
make test-security   # the invariant tests only
cp .env.example .env # then set ANTHROPIC_API_KEY and SHINGLE_HMAC_SALT
make up              # the partitioned stack: local tier, SLM, monitor
make verify-partition
```

Status: the suite passes (`make test`; the manuscript-build tests are deselected, below) and
`ruff` is clean. `make typecheck` does not pass: mypy reports 316 errors in 22 files.

Regenerate the corpora (the output is byte-identical to `eval/corpora/`):

```bash
.venv/bin/python scripts/corpora --scenario all --out eval/corpora --audit
```

**Cost.** `make eval-private` and `make eval-measure` pass `--yes` to `scripts/run_evaluation.py`,
so they spend as soon as the estimate is printed; run the script without `--yes` to see the
estimate only. They run one arm and one repeat (r5, repeat 1); the paper's batch ran three arms
(baseline, r5, r1) three times each. `measure` reads `ANTHROPIC_API_KEY` from the environment,
not from `.env`. `make eval-aggregate` is free and offline. `scripts/freeze_batch.sh` and
`scripts/freeze_batch_real.sh` are the drivers the authors ran the batches with; they are kept as
the record of what ran, with the authors' absolute paths to `.env` and the interpreters made
relative to the checkout root, and they need the git tags of the private repository.

**Track L** needs the Text Anonymization Benchmark (TAB,
https://github.com/NorskRegnesentral/text-anonymization-benchmark), which this repository does
not redistribute. Put `echr_dev.json` and `echr_test.json` under `data/tab/` with a
`SHA256SUMS` file for them; `scripts/real_corpora/tab.py` checks both against the hashes it pins
(TAB as downloaded on 2026-10-05), rebuilds the collections by rule and, with `--check`, compares
them with `eval/real/manifest_l.json`. The Presidio reference (`scripts/presidio_residual.py`)
needs a separate environment with `presidio-analyzer` and the spaCy model `en_core_web_lg`.

## Relation to the paper's runs

The frozen batch on corpora A-D ran on 2026-10-07 from the authors' commit `0d5e86b` (tag
`paper-freeze` of 2026-10-06 in their repository, whose history is not public), which pinned the
gold keys, both lexicons and the tasks by sha256. The files in this release have the same hashes:

```
dcda133acba9478d5f9059761340fc3bdcf0e9e734a870080d3fab4840663780  eval/corpora/smoke-q3/smoke_fact_key.json
998d6ee0e07dbb54c082ad032e36a898a34d3f946b7fd156f3e4bbe5cc77d4ad  eval/corpora/portfolio-b/smoke_fact_key.json
7a5a9a3465e99d3fb96b00f5140ea03a3037e86d8b4c6779faf3021caaacbe1c  eval/corpora/prose-c/smoke_fact_key.json
e54c0f00c3780532bf36501aeed0ecf8471e8f8d4566f912af69d2e5ec7d6daf  eval/corpora/offlex-d/smoke_fact_key.json
48044470871fce8e5c5c5e1b2bfec58921687eaf461cb3dc566bcf81655417ee  scripts/corpora/rba_lexicon.py
ad7f13ceb0acda75efb2825342ae290ab964a929c659d94870d93412227dbbe0  backend/src/privdeep/tier1_local/header_lexicon.py
4d36b9cecd46e9cbfd68d8097ad90a9b65d8a28449e7b501cd189612db7ed9a5  eval/tasks.json
```

This release is the code at the paper's submission. It differs from the batch's code in four
runtime changes, none of which changes a verdict of M:

1. `backend/src/privdeep/pipeline.py`: when M refuses the planner request, the pipeline keeps the
   extractions so they are saved. Track L (2026-10-15) ran with this patch, signed by the first
   author; it runs after M's verdict.
2. `gateway/main.py`: the audit record names the request's model only when it is the model id the
   client sends, so a refused request's record cannot carry its text. This came on 2026-10-18,
   after both the A-D batch and track L.
3. `backend/src/privdeep/pipeline.py`: when M refuses the planner request, the pipeline also keeps
   the egress trace and the masked entities, so the refused request stays in the run's local
   record (`egress_trace.jsonl`), as a refused drafter request already did. This came on
   2026-10-27, after both batches, so the track L attempts refused at the planner (the r5 repeat-1
   runs of four collections, each kept as an attempt) have empty traces. `scripts/real_l.py` lists
   an attempt whose every traced exchange was refused as not scanned, as it did those empty
   traces.
4. `backend/src/privdeep/pipeline.py`: a planner reply the pipeline cannot use (`PlannerError`)
   or a planner call that fails upstream or at the monitor (`CloudError`, `GatewayError`) now
   ends the run as a refusal does, with the manifest, the masked entities and the extractions
   written and the error's class in the manifest's note; until 2026-10-27 the error ended the
   run before anything was written. The egress trace keeps an unusable reply's exchange, request
   and reply, which the manifest counts as allowed; a failed call leaves no trace line, at the
   planner as at a drafter. With it, `tier2_cloud/macro_planner.py` counts a non-zero number (or
   true) given for a section's slot references, and each element of the array that is not a
   string, as a reference it did not issue and never resolves them, so a plan of only such
   references fails closed; it treats a word budget that parses as infinity (`1e400`) as
   missing, so it is clamped to the minimum, and `eval/oracle.py` reads that budget the same
   way; and `tier2_cloud/cloud_client.py` raises a 200 reply it cannot parse, or an upstream
   error whose "error" field is not an object or whose body is nested too deep to decode, as a
   `CloudError`, which at a drafter fails that section rather than the run. Before, the element
   was dropped uncounted and each of the others raised an untyped error. No run of either batch
   ended in any of these ways, and no plan reply in them gave a reference other than a string in
   an array.

The runs (`eval/runs/`, with their manifests) and track L's outputs are not in this repository;
the runs will be released upon acceptance. The exceptions are the reports the calibration labels
refer to (`eval/calibration/`, including two reports of a pilot run of 2026-09-14) and one pilot
extraction kept as a test fixture (`backend/tests/security/fixtures/`), all on synthetic
corpora. The SLM is unseeded, the cloud model an undated alias and its sampling cannot be set,
so the runs reproduce the analysis, not the outputs.

The manuscript's build (the Word skeleton, the drafts and the figure sources) is not included,
and its tests are deselected in `pyproject.toml`. `scripts/make_paper_tables.py` writes its
tables onto a Word document's styles, so pass `--skeleton` any `.docx` (the paper used the ICCIT
2026 Word template); it also needs the runs and track L's outputs.

## Licence

MIT (`LICENSE`). TAB's annotations are under the MIT licence; the European Court of Human Rights'
judgments are not redistributed here.
