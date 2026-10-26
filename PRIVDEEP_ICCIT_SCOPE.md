# Pre-registration and its amendments (sections 8-13 of the authors' scope document)

This file holds sections 8 to 13 of the authors' scope document for the ICCIT 2026 paper:
the pre-registration of 2026-09-27 (section 8: hypotheses H1-H3 and H4-D in 8.7, H4-D′ and the
H2 floor rule in 8.7a, the freeze rules in 8.8, the claim restriction in 8.10) and its dated
amendments (sections 9-13: corpus C, the H4-D count, the key audit, track L with HL1 in 12.7,
and the post-hoc analyses of 2026-10-26). Sections 1-7, the project's earlier planning, are not
included. File and commit references inside point to the authors' repository, whose history is
not public; the tests in backend/tests pin the code's hypothesis wording to this text.
The text is verbatim, except that two paths on the authors' machine are written as
`~/CLAUDE.md` and `.venv-presidio`.

---

## 8. Amendment of 2026-09-27: R1 on the record, cuts, and pre-registration

**Status:** signed by the author on 2026-09-27. Drafted by the assistant from
`PRIVDEEP_COMPLETION_PLAN.md` (2026-09-27, Part B with the Part D corrections). It records plan
decisions 1, 2, 3, 4 and 9 as the author took them that day. File:line citations refer to commit
`b06ed46` unless a later commit is named.

**Why this section exists.** Construction has moved past this document. The arm the paper
headlines, R1, puts a fixed attribute schema and per-referent fact stems on the wire and rewrites
cloud prose locally, and neither the claim in §7 nor `THREAT_MODEL.md` described it until now. §1
asks that a locked decision be reopened only with a stated reason; the reasons were in commit
messages and memory notes. They are recorded here.

**Ordering rule.** This section is committed before any billable run made after 2026-09-27: the
EXP3 pilot on corpus C and the EXP6 frozen batch. `git log` shows this commit first. The nine
smoke-q3 runs of 2026-09-14 predate it; they are pilot data and are not quoted in the paper.

### 8.1 D7: R1, R5 and RBA

| # | Decision | Consequence |
|---|---|---|
| D7 | Adopt R5 (canonical slots, one slot per referent), R1 (a local fact store; the cloud writes typed fact references instead of values) and RBA (role-binding accuracy, a two-axis faithfulness metric over numeric values). The baseline arm and the unconstrained-cloud oracle are kept. Decided 2026-09-11; R1 confirmed 2026-09-14 after the baseline-vs-R5 measurement. | Three private arms (baseline, r5, r1) share one extraction per corpus. What crosses under R1 is stated in `THREAT_MODEL.md` §3. R1 deletes and counts sentences locally, which is a rewrite of cloud prose and is disclosed as one |

**Reason: a measured role-binding failure.** Synthesis over a type-level abstract payload misbinds
the user's own figures: the cloud receives a MONEY slot and cannot tell an authority from a spend
or a balance. R5 alone did not fix it, measured on 2026-09-14 as baseline against R5 over one shared
extraction (`backend/src/privdeep/models/facts.py:3-8`). R1 moves the binding local. Pilot figures,
smoke-q3, N=3 over one shared extraction, recorded as the reason and not citable: RBA baseline
0.315±0.042, r5 0.178±0.077, r1 0.771±0.016; oracle 0.72-0.90.

**Commits.** RBA: `6906472` (2026-09-13). R5: `72c0929` (2026-09-13). R1: `d95de69..b06ed46`
(2026-09-14), five build steps, then the PCT_SPENT key extension (`9d8d4c6`), the readability fixes
including sentence pruning (`d0ddfce`), and repeats in the driver (`b06ed46`). The range
`6906472^..b06ed46` covers all three, and also carries four driver and extraction commits
(`329d1c2`, `2624088`, `f2f9bdf`, `af4a90c`).

### 8.2 D3 is amended: a zero-shot adversary, reached directly

D3's few-shot frontier adversary is not built. The reconstruction adversary is a
frontier model, zero-shot, reached directly with the evaluation's own client rather than through
the monitor, reading the rendered egress trace (`backend/src/privdeep/eval/reconstruction.py:46-54,
:166-172`; `scripts/run_evaluation.py:411, :735-736`). Reason: G3 is near zero by construction
whatever the prompt, because pseudonymisation suppresses surface strings; G2 is carried by a
construction test and G1 is stated analytically (§8.6), so a stronger prompt buys no claim. The
paper calls the G3 figure a direct-access lower bound from one zero-shot adversary.

### 8.3 The R4 arm is cut

The R4 ablation arm (slot-level triples sent to the cloud), part of the 2026-09-11
decision, is not built and is cut, as an explicit author decision. The oracle is already the
measured upper anchor, and what R4 would disclose, the labelled relational graph, is stated
analytically. The paper gives it one sentence in Design: sending slot-level triples would disclose
the labelled relational graph, and it is not evaluated because the unconstrained oracle bounds
fidelity.

### 8.4 P6 is scrub-and-count

`THREAT_MODEL.md` P6 said that a placeholder the core never issued refuses the section. The
pipeline does not do that. P6 now reads: an unissued placeholder or unknown fact
reference is replaced by the fixed literal `[unresolved reference]` and counted
(`invented_slots` in the manifest), never resolved; the reintegrator's refusal of an invented
token is defence in depth. The code: `backend/src/privdeep/tier2_cloud/section_drafter.py:144-149,
:201-234` scrubs; `backend/src/privdeep/tier3_reconcile/slot_reintegrator.py:337-356` refuses
whatever reaches it. No invented placeholder occurred in any of the nine pilot runs (manifests,
`invented_slots` = 0 in every section).

### 8.5 Fix 2 is set inclusion

§4 asked for the returned slots to equal the issued ones as multisets. The code enforces set
inclusion, which fits free prose, where an entity may be named twice or not at all
(`slot_reintegrator.py:68-71`):

- **Slots.** Every slot token in a draft must be in the mapping table and in the issued set, or
  the section is refused (`INVENTED_SLOT`, `slot_reintegrator.py:337-344`).
- **Fact references (R1).** The referent must be one the session issued and the code must be in
  the closed vocabulary, or the section is refused (`INVENTED_FACT`, `:263-268, :349-356`). A
  known referent lacking the attribute is not refused; it renders `not recorded` (plain words
  since `c8f906d`; it was `[not recorded]`, whose brackets are Markdown-active).
- **The issued set is the session's**, not the section's or the outline node's: the pipeline
  passes every payload slot as issued (`backend/src/privdeep/pipeline.py:289-291`).
- **Omissions and duplicates** are counted (`missing_issued`) and never refused.
- The drafter scrubs invented tokens before the reintegrator sees them (§8.4).

Status of the rest of Fix 2's resolution: the position check is done and is decided by the renderer (P5).
Per-outline-node binding is cut (§8.6). The viewer and its CSP were cut on
8 September (§5). Extending the trust boundary to rendering is stated in `THREAT_MODEL.md` §5 as the
renderer trusted by omission. Done in `25db615` and `c8f906d` (plan task INS5): both transport checks
run on the unpruned draft, so pruning can no longer turn a refusal into an attribute-existence
signal, and the 14-case MX6 test (`backend/tests/security/test_pipeline_exfil.py`) exercises Fix 2
through `run_pipeline`.

### 8.6 Cut list

Each row names the claim the paper gives up. The decision column says which plan decision
approves the row. Decision 1's text enumerates nine items; the rows marked "1*" are on the plan's
cut list (§7) but not in that enumeration; the author's approval of the whole cut list on
2026-09-27 covers them.

| Cut | Claim the paper gives up | Decision |
|---|---|---|
| M2 evidence path (offline snapshot, purifier, guard, bank, citations) and the end-to-end injection ASR | Any injection-resistance claim; citation grounding in a reported run (P7 is "built, not exercised"); any statement that injected content is confined. Every reported run is evidence-free | 1 |
| P1/P2/P5 ablation | A per-property ablation. Each property is instead tied to its enforcing module and pinning test, with MX6 for P5 | 1 |
| R4 slot-level-triples arm | Any measured fidelity or disclosure of slot-level triples (§8.3) | 1 |
| Vietnamese corpus and Vietnamese R5/R1 (header lexicon, normaliser, PDF writer, leak gate) | Any claim that R5, R1 or RBA works on Vietnamese or on the deployment corpus. The monitor alone is measured on Vietnamese (FP stratum, NFD test) | 1 |
| K=9 G1 linkage attacker and its six variant corpora | Any empirical G1 figure. G1 (membership and linkage) is stated analytically as not protected | 1 |
| Empirical role-permuted-corpus extraction | G2 for the SLM-written relation fields. G2 is claimed only for the core-built payload, given a fixed extraction | 1* |
| Live redact-and-send arm; external utility baselines (a Presidio pipeline, local-only drafting) | Any utility comparison with redaction pipelines or local-only drafting. The misbinding claim is scoped to type-level payloads | 1 |
| Masked-document exposure as a hypothesis (the former H4) | Nothing testable: under P2 it cannot fail, so it is reported as a construction fact (§8.7) | 1* |
| Scoring name and place bindings (string facts) in RBA | Any claim about how names and places are bound. RBA covers numeric values only | 1 |
| A "within the oracle's run-to-run range" inference | Any inference that R1 matches the oracle. The oracle's figures sit beside R1's with no inference drawn | 1* |
| Significance tests across corpora, Wilson intervals over correlated egress attempts, N=5 | p-values and confidence intervals. The baseline-vs-R5 difference is stated as not established | 1* |
| Second human-authored gold key and inter-annotator agreement | Inter-annotator agreement. Calibration is single-labeller | 1 |
| Few-shot adversary (D3) and an LLM-based G1/G2 probe | A stronger G3 bound, and any LLM-measured G1 or G2 figure (§8.2) | 2 |
| Symmetric-prompt oracle, a frozen oracle per corpus, a private-vs-private judge pair, any "retains X% of cloud quality" sentence | Any quality-retention percentage, and any judge-based ranking of the private arms. The judge is secondary, per criterion and order, with position bias | 1* |
| Oracle fabrication rate | Any fabrication rate for the oracle. Only the private arms' numerals outside the key are reported | 1* |
| Per-outline-node slot binding; the report viewer with CSP | Per-section binding, and any claim about the renderer. Slot ids are bound per session; the renderer is trusted by omission | 3 (binding); §5 of 8 September (viewer) |
| A persisted session salt, and a keyed monitor that cannot confirm guessed shingles | Any claim that a compromised monitor learns nothing. M holds the salt and is a membership oracle over guessed shingles | 1* |
| SLM seed threading, GPU-placement run refusal, a throughput and latency table, a per-section slots gate | Any tok/s figure, and seeded extraction. Extraction variance is reported as Jaccard; GPU placement is recorded, not gated | 1* |
| CI, mypy cleanup, orchestrator refactors, extra orchestrator tests, raw-draft persistence, sentence-splitter change | Any "CI" or "typecheck clean" statement. The artifact README states the test and typecheck status; the work is scheduled for 1-14 November | 1 |
| Editing the global `~/CLAUDE.md`; re-marking memory notes already marked "Superseded" | None | 1* |

### 8.7 Pre-registration

Committed before the EXP3 pilot and the EXP6 batch. Corpora: A = `eval/corpora/smoke-q3`
(byte-identical to the pilot corpus documents), B = `eval/corpora/portfolio-b`, C =
`eval/corpora/prose-c`, built by plan task EXP1, and D = `eval/corpora/offlex-d`, whose table
headers are partly outside the header lexicon (decision 4, taken 2026-09-27). Arms: baseline, r5, r1, three repeats each over
one shared extraction per corpus, all at the tag `paper-freeze`.

The hypotheses, worded as in the plan's X1:

- **H1:** on each of A and B, every r1 run's RBA and attribute accuracy exceed every baseline run's.
  A is a replication at the tag, because the pilot already shows the outcome; B is out-of-sample.
- **H2:** on C, r1's coverage_stated and coverage_correct are below baseline's, because R1 has no
  prose route. RBA on C is reported with its n and suppressed below the minimum n.
- **H3:** the generator-surface scan finds zero hits in core-sent content of any private-arm trace.

Definitions the hypotheses rely on:

- "Minimum n" is 5 scored occurrences per run: a run with fewer has no RBA (plan task INS1).
- The generator-surface scan (plan X4(a)) searches core-sent request content (system and
  messages) for every constant the scenario modules write. It excludes the user goal, which
  crosses in the clear by design, and any span that repeats text from an earlier response in the
  same run. "Crossed" means request side.
- H1 is tested under the frozen RBA attribute lexicon (§8.8, after its one-time fix). The pre-fix
  figure is reported beside it and is not tested, and corpus A is marked in-sample for the fix.

**Construction fact, reported and not tested:** the entity-masked copy of each corpus contains
corpus 5-grams and the sealed filter refuses it. It is not a hypothesis because under P2 it cannot
fail (`backend/src/privdeep/tier2_cloud/abstract_payload.py:3-8`).

**H4-D** (corpus D is included): on D, facts_structural against total table facts falls below A and B, and
r1's RBA gain over baseline shrinks accordingly. If H4-D fails, the paper reports that the gain on
D did not shrink with lexicon coverage and does not attribute R1's gain to the lexicon on the
evidence of D.

**Claim restriction, fixed now.**

- If H1 fails on a corpus, the R1 sentence names only the corpora where it holds.
- If H2 fails, meaning r1 states prose-only values, that is reported and traced, and the prose
  sentence is withdrawn.
- If H3 fails, the crossing strings are reported and the first bullet of the claim (§8.10) is
  withdrawn.
- Whatever the batch shows, the paper states that the difference between the baseline and R5 arms
  is not established.

### 8.7a Amendment after the C and D pilot, 2026-09-27, before any frozen-batch run

The pre-freeze pilot (plan task EXP3: one run per arm on corpora C and D, at commits
`b799894` and `166718c`, archived under `eval/pilot/` and never quoted) showed that on D the r1
report states few figures but binds the ones it states correctly. The lexicon dependence H4-D is
meant to capture therefore appears in how much r1 can state, not in how accurately it binds what it
states, and RBA, which scores only stated bindings, is the wrong instrument for it. H4-D stays as
registered in §8.7 and its outcome is reported under its own rule. Added, and reported in the paper
as registered after the pilot and before the batch:

- **H4-D′:** on D, every r1 run's coverage_correct is below every r1 run's coverage_correct on A
  and on B.
- If H4-D′ fails, the paper reports that r1's coverage did not fall with lexicon coverage on D and
  does not attribute R1's coverage limits to the header lexicon on the evidence of D.

- **H2 floor rule.** A half of H2 in which the largest r1 value and the smallest baseline value on C
  are both 0 cannot show r1 below baseline, because no value is below 0. Such a half is reported as
  not testable (a floor), not as a failure, and H2 is decided by its other half; if both halves are
  at the floor, H2 is not testable. The restriction "If H2 fails, meaning r1 states prose-only
  values" applies only to a failure of a half that is not at the floor.

The paper states when H4-D′ and the H2 floor rule were added and why. No other hypothesis, key or instrument was changed
in response to the pilot; the changes made after it (the W2 leak gate dropping and counting a
leaking relation, and checking it across the corpus) are pipeline-health fixes the pilot exposed,
recorded in their commits.

### 8.8 Freeze rules

- The SHA of every gold key and of the RBA attribute lexicon (`ATTRIBUTES` in the corpus generator,
  emitted into each key) are written into the message of the tag `paper-freeze`, not into this
  section. `header_lexicon.py`, R1's structural route, is not changed by calibration; the tag commit
  freezes it.
- No instrument, key or lexicon change is made between the tag and the end of the batch.
- Every number in the paper comes from `eval/paper/numbers.json`, generated from the frozen
  artifacts. No pilot or memory figure is quoted.

### 8.9 Schedule, re-dated

Supersedes blocks M2 to P of §6. M2 is cut (§8.6). M3's measurement runs become the frozen batch.
M4's "privacy number" becomes the analytic G1 statement, the G2 construction test and the G3 lower
bound. H is cut to after submission.

| Date (2026) | Freeze or gate |
|---|---|
| Fri 2 Oct | Gate: this section signed and committed; corpus A byte-identical, B and C generated with provisional key SHAs, D specified; decision 4 taken (D included) |
| Fri 9 Oct | **Tag freeze.** `paper-freeze` tagged with `make test` and `pytest -m security` green, key and lexicon SHAs in the message. At the latest Sun 11 Oct |
| Sat-Sun 10-11 Oct | Frozen batch run; backstop Wed 14 Oct |
| Fri 16 Oct | **Experiment freeze.** No billable run and no new experiment after this date |
| Sun 18 Oct | **Numbers freeze.** After this a number changes only through a scripted rescore for a found bug, with a changelog entry |
| Mon 26 Oct | **Upload** to CMT |
| Wed 28 Oct | Content hard stop; re-uploads for defects only |
| Fri 30 Oct | Deadline. 29-30 Oct kept free |

### 8.10 What the paper claims (replaces the claim in §7)

The two paragraphs after the quoted claim in §7 stay in force. The claim itself is replaced by the
following. Bracketed values are pilot figures or pre-registered expectations; at the tag they are
replaced from `eval/paper/numbers.json`.

> PrivDeep partitions a deep-research agent into three tiers:
> - A local tier abstracts the user's documents into typed concept relations, opaque
>   category-tagged placeholder identifiers and coarse document statistics.
> - A cloud model plans and drafts over that abstraction only. Under R1 it also receives per-slot
>   fact stems and a 13-code attribute vocabulary. The vocabulary was fixed in advance from this
>   document family and is identical for every corpus.
> - The local tier then resolves placeholders and fact references into values and computes derived
>   figures. It also deletes, and counts, each sentence whose referenced fact is not recorded.
>
> Every pipeline egress passes through a reference monitor, the only dual-homed service. The
> evaluation-only oracle, judge and adversary calls do not pass through it. The monitor inspects
> three streams: the concatenated decoded string values of the body, each JSON path across
> requests, and the keys. It deterministically refuses any contiguous run of five or more corpus
> words that lies within one of these streams, after Unicode normalisation, case folding and
> confusable folding.
>
> Known gaps:
> - private text encoded as per-character integers or hex (two strict xfails);
> - a run that straddles a key and its value (pinned as passing);
> - a run that changes JSON path across requests, including eviction past 64 carried paths;
> - repeated identical chunks at one path (the per-path stream skips a value that repeats the
>   path's previous value byte for byte);
> - confusables outside the folded set;
> - reordered text;
> - all private text shorter than five words, including relation predicates.
>
> The evaluation uses four synthetic four-format English corpora from one budget-report family:
> 36 private-arm runs at one tagged commit.
> - [No value, name or date that the corpus generator wrote appeared in core-sent egress content.
>   The only extracted-entity strings present in any trace were common words the cloud itself
>   wrote; in the pilot this was 'high', in 'at a high level'.]
> - Synthesis over a type-level abstract payload misbinds the user's own figures:
>   - masked baseline: role-binding accuracy [0.32], attribute accuracy [0.53];
>   - normalised slots (R5): [0.18] and [0.58];
>   - the difference between these two arms is not established at n=3.
> - R1 is a local fact store to which the cloud writes typed fact references instead of values, so
>   no value crosses the boundary. It covers facts held in table cells whose headers the fixed
>   English header lexicon recognises; corpus B's headers were drawn from that lexicon by design, and corpus D's are partly outside
>   it. On
>   those facts R1 raises role-binding accuracy to [0.77] and attribute accuracy to [0.76], at
>   coverage_correct [x], while stating fewer values than the other arms. The unconstrained-cloud
>   oracle scores [0.72-0.90] role-binding accuracy on the same corpus. R1's figures are reported
>   under both the pre-fix and the frozen RBA attribute lexicon, and corpus A is in-sample for the
>   lexicon fix.
> - Role-binding accuracy scores numeric values against referent and attribute. Bindings of names and
>   places are not scored.
> - R1 states none of the facts that appear only in prose (coverage_stated [x] vs [y]), which puts
>   it below both other arms there.
> - LLM-judged report quality stays far below the oracle's. It is reported per criterion; the mean
>   excluding groundedness, which is uninformative without evidence, is [x] vs [y] on a 1-5 scale.
>
> Given a fixed local extraction, the core-built payload and prompts are byte-identical under the
> tested permutations of values and of which referent holds which value (G2). This is a
> construction property pinned by a test that holds the cloud's own replies fixed. Whether the
> SLM-written predicates vary under such permutations is not measured. No membership or linkage
> protection is claimed (G1): the payload discloses the corpus's structure. The design is
> pseudonymisation, not anonymisation. The surface-reconstruction result comes from one
> zero-shot adversary reading the trace directly, so it is a lower bound. Its scorer's pilot
> hits were an adversary guess ('August') matching an over-typed DATE entity, and 'High'.

How the bracketed values change at the tag: if H1 fails on a corpus, the R1 sentence
names only the corpora where it holds; if H3 fails, the crossing strings are reported and the first
bullet is withdrawn; if H2 fails, meaning r1 states prose-only values, that is reported and traced,
and the prose sentence is withdrawn; H4-D's outcome is reported as §8.7 says.

Added to "deliberately not claimed" in §7: no injection resistance and no evidence grounding in
any reported run; no membership or linkage protection; no bypass-class count (the
closed classes of `THREAT_MODEL.md` §4.1 are named, not counted); no "retains X% of cloud quality"
figure.

### 8.11 Corrections to earlier sections, dated 2026-09-27

- **Fix 1's resolution (line 158).** The earlier text said a compromised gateway would learn
  nothing about the corpus. It holds the filter and the salt, so it can confirm guessed shingles.
  Corrected in place; `THREAT_MODEL.md` §1 states it; the monitor's volume is split from the core's
  by plan task REC3, which corrects the same claim in `docker-compose.yml` and
  `shared/shingle_filter.py`.
- **Entropy (line 113).** The earlier text named the standalone aggregate over all five strata as
  entropy's headline. Entropy is now quoted per stratum at its rate through the deployed
  decode-then-inspect chain (plan task EXP5, `9183c59`). Measured on 2026-09-27 on the same 500
  clean payloads: the deployed chain refuses 122/500 in both carry modes, all of it compact abstract
  JSON carried inside one message string (100/100, entropy; decoding the request does not split a
  payload that travels as one string) and code snippets (22/100: 3 entropy, 19 secret-pattern);
  nothing in the prose and shipped-JSON strata. The pipeline's own requests were refused 0 of 78
  times in the pilot, so whether the compact stratum describes traffic the pipeline sends is
  settled in EXP7 before any rate is quoted. Corrected in place.
- **Fix 2's resolution (line 181).** Reworded to the set-inclusion rule the code enforces (§8.5).
- **Typecheck count, like for like.** §6's block H recorded `make typecheck` red at 23 errors in
  source. On 2026-09-27 at b06ed46, `make typecheck` (`mypy backend/src gateway`, the target the
  23 came from) reports 286 errors in 22 files, 28 of them outside `gateway/tests`. `mypy
  backend/src shared` reports 30 errors in 12 files; that is a different target and is not
  comparable with the 23.
- **Test count.** `make test` at b06ed46: 1138 passed, 50 xfailed (strict); at `ef28a71`, after
  the first plan tasks (INS1, EXP1, INS3, INS5, INS4, EXP5): 1388 passed, 50 xfailed. The figure of
  802 in §6's block S is the count on 8 September and is left as it was.
- **G2 wording (§8.10), added 2026-09-27 after the G2 test.** "Byte-identical under the tested
  permutations" is read as `THREAT_MODEL.md` §2 words it: equal up to renaming slot ids and
  reordering listing lines, with the character count on the wire quantised to 1,000 (`a304bd2`); a
  permutation that moves the count across a rounding boundary still changes it.
- **Single labeller (§8.6), added 2026-09-27.** "Calibration is single-labeller" means one human
  labeller, the author, for the blind development and held-out rows. The in-sample baseline label
  set (`eval/calibration/smoke-q3_hand_labels.json`) was written by the AI coding assistant that
  built the RBA rule, in the same commit as the rule, and is reported apart as assistant-written and
  non-blind.

### 8.12 Writing model

The assistant writes the first draft of every prose section of the paper from frozen
sources (`THREAT_MODEL.md`, `eval/paper/numbers.json`, the verified bibliography and the code).
The author edits, checks every claim and owns the text. The paper's AI-use declaration states this,
and states that Claude models serve as drafter, oracle, judge and adversary. The writing fallback
(Fig. 2 as a listing, Table 3 folded into Table 4, related work at 0.5 page, simulated review only)
is decided at the 16 October gate.

---

Signed by the author on 2026-09-27, in the working session with the assistant: decisions 1, 2, 3
and 9 approved as recommended; decision 4, include corpus D; H1 tested under the frozen RBA
attribute lexicon; this section committed as drafted.

## 9. Amendment of 2026-09-30: corpus C states its owners in prose

*Drafted by the AI assistant on 2026-09-30 for the author's review. The signature of 2026-09-27
above does not cover this section; the author signed it on 2026-09-30 (below).*

From 2026-09-30 corpus C's quarterly statement and trustee minutes state each project's owner in
prose, by the author's decision on the AI key pre-check (`eval/corpora/KEY_PRECHECK.md`, C); the
risk register's 'Raised by' column is unchanged and maps to no header-lexicon code, so C still has
no structural fact and H2 is unchanged. The key's values and sha256 are unchanged; C's character
count moves from 2863 to 3014, 3000 on the wire as before. The pilot's C runs (§8.7a) used the
earlier documents.

Signed by the author on 2026-09-30, in the working session with the assistant: this section
committed as drafted.

## 10. Clarification of 2026-10-02: how H4-D counts "total table facts"

*Drafted by the AI assistant on 2026-10-02 for the author's review; the author signed it the same
day (below). It states how a registered quantity is computed and changes no hypothesis, threshold
or quantifier.*

H4-D (§8.7) compares facts_structural "against total table facts". The aggregate computes that
denominator as a corpus's table data cells: the non-empty table cells below the header row and
outside the key column, over every sheet and docx table (`_table_data_cells` in
`scripts/run_evaluation.py`, added in commit b81ecc8 on 2026-09-27, before the pilot runs of that
day). §6 and Table 3 state the computation; §5 keeps the registered wording. On the committed
corpora the plausible readings of "total table facts" stand in the same A:B:D proportion, 3:4:4:
table data cells 36/48/48, the gold key's facts held in a table cell 15/20/20, and distinct
(referent, column) table facts 30/40/40. The rule compares ratios, so H4-D's outcome is the same
under each. Two other counts are not in that proportion and are not the reading adopted: distinct
cell values (32/43/43), which differ only at an exact tie, and the key's stated facts that a table
holds, risk-register text included (17/24/24). The computation is frozen with the rest of the
instrument at `paper-freeze` (§8.8).

Signed by the author on 2026-10-02, in the working session with the assistant: this section
committed as drafted.

## 11. Amendment of 2026-10-03: who audits the gold keys

*Drafted by the AI assistant on 2026-10-03. The author chose this division in the working session
the same day (the choice "AI audit key, bạn gán 63 nhãn"); approved as recorded below.*

The gold keys of corpora B, C and D are audited by two independent passes of the AI assistant, not
by the author alone. Each pass reads every row of `eval/corpora/KEY_AUDIT.md` (every place a
spelling of a key value occurs) against the documents, without the other pass's output and without
the earlier pre-check (`eval/corpora/KEY_PRECHECK.md`), and gives each row a verdict: the place
binds the value to the fact's subject and attribute, only mentions it, binds it to another subject
or attribute, is ambiguous, or (for a derived fact) recomputes correctly or not. A row both passes
judge the same way, as binding, a mention or a correctly derived value, is marked `AI: ...`; every
other row is marked `AI: needs author` and decided by the author, whose mark replaces it. The blind
development and held-out labels of the RBA calibration stay the author's (X5), so the calibration
keeps one human labeller who did not build the rule. The paper states the division (§5 Corpora, §7
Evaluation scope). What this costs: the keys are checked by the assistant that wrote their
generator, and only the rows the passes contest or flag are read by a person.

Approved by the author on 2026-10-03, in the working session with the assistant: this section
committed as drafted.


## 12. Amendment of 2026-10-05: track L, leakage on real court judgments, with a Presidio reference

*Drafted by the AI assistant on 2026-10-05 from the author's choices of the same day in the working
session ("Chỉ L + Presidio"; downloads of the TAB dev and test splits and of the spaCy model
en_core_web_lg approved; track L cap $15). **Status: signed by the author on 2026-10-15** (recorded by the AI assistant at the author's instruction, in the working session; the schedule of §12.9 was amended at signing, and the §12.12 record filled, as the signature block states).*

**12.1 Why.** The author judged synthetic corpora alone unconvincing for the privacy claim. The
evaluation-only oracle and judge send raw text to C (§5 of THREAT_MODEL.md), which excludes real
private data but not public documents standing in for private ones. Track L measures, on real text
whose personal identifiers were labelled by people unrelated to PrivDeep, whether any identifier
reaches C through PrivDeep's own egress. It adds no role-binding measurement: RBA, R1 and H1-H4
stay on A-D, unchanged. A, B, C, D, their keys, both lexicons, `eval/tasks.json`,
`scripts/freeze_batch.sh`, the paper-freeze tag and every §8.9 date are untouched; track L is
reported beside A-D and never pooled with it.

**12.2 Source.** The Text Anonymization Benchmark (TAB; Pilán et al., Computational Linguistics
48(4), 2022, doi:10.1162/coli_a_00458), `echr_dev.json` and `echr_test.json` from
github.com/NorskRegnesentral/text-anonymization-benchmark (branch master), downloaded 2026-10-05
into `data/tab/` (gitignored) with `data/tab/SHA256SUMS`: dev 8c3c7306…93ec, test cd0f0f15…6379.
TAB's annotations are under the MIT licence; the judgment texts are © ECHR-CEDH, reproduced for
information and education with the source acknowledged. No TAB text is committed or redistributed:
the collections are rebuilt from TAB by script, and only identifiers, hashes and the build rule are
committed.

**12.3 Collections (fixed before any test text is read).** A judgment is eligible if it has at
least 4 annotators, at most 8,000 characters of text, and the respondent state `meta.countries ==
"GBR"` (the only state with enough eligible judgments: 41 of 47 eligible in test, 42 of 49 in dev).
- L0, development, never quoted: the first 4 eligible dev judgments in ascending `doc_id`.
- L1-L6, test: the first 24 eligible test judgments in ascending `doc_id`, cut into 6 consecutive
  collections of 4.
Each judgment's `text` is written verbatim as `doc1.md` … `doc4.md` (UTF-8). No `meta` field
(`meta.applicant` names the protected person) and no `task` field is ever written into a document,
a goal or a committed file. Goal, identical for every collection and checked to share no 5-gram
with any TAB judgment: "Compare the applicants' situations, their complaints and the domestic
proceedings described in these case files." Disclosure: while designing this track the assistant
computed aggregate statistics of the test split (counts by country, article and one keyword); no
test judgment's text was read.

**12.4 Gold.** For each annotator, every mention whose `identifier_type` is DIRECT or QUASI. The
unit is an *identifier string*: a mention's `span_text`, normalised by the containment tokenizer,
distinct per collection, typed by `entity_type` and `identifier_type` (a string labelled DIRECT by
any annotator counts as DIRECT). Strings of at most 2 characters, or whose tokens all occur in the
goal or in a fixed English function-word list committed with the builder, form a `labels` group,
reported apart. The groups are written to each collection's `surfaces.json`; the same strings are
`string_facts` of a key with no numeric facts, so `tier1_probe` can read them.

**12.5 Runs.** baseline, r5 and r1, 2 repeats each, on L1-L6: 36 private runs, one fresh extraction
per collection (the first r5 run) reused by the others, as in A-D. No oracle and no judge run on L,
so only PrivDeep's own egress, and the adversary's rendering of it, reaches C. G3: the existing
zero-shot reconstruction adversary on the rendered trace of each arm's first repeat (18 calls), and
per collection one no-trace control given a one-exchange trace holding only the goal (6 calls).
Pilot on L0: one run per arm and one adversary call with its control, under `eval/pilot/real-l/`.

**12.6 Measures.**
- Crossing: an identifier string has crossed when the run's egress trace holds a whole-token hit of
  it (`token_hits`, `scan_trace`) on the side `core-sent`; the goal, cloud echoes, cloud replies and
  refused requests are excluded as in H3. Reported per run, arm and entity type, for DIRECT and for
  QUASI, as k/n.
- Extractor recall and predicate echo (local, free): the share of identifier strings that the
  extraction masked, and the share that occur in relation fields.
- G3: identifier strings recovered in the adversary's output, net of the no-trace control.
- Operational refusals and health, as for A-D.
- Utility proxy: sections delivered and refused per run, and the share of the collection's DATETIME,
  QUANTITY and ORG strings present in the final reintegrated report.
- Presidio reference, offline and free: presidio-analyzer and presidio-anonymizer 2.2.362 in their
  default configuration (spaCy en_core_web_lg 3.8.0, language "en", default recognizers, default
  "replace" operator), run in `.venv-presidio`; the share of DIRECT and QUASI
  identifier strings, by type, with a whole-token hit in the anonymised text. It is what a standard
  redactor would leave in text it sends; PrivDeep sends an abstract payload, not text, so the two
  are reported side by side, never as one ranking.

**12.7 Decision rule and claim restriction.**
- HL1 holds when no DIRECT identifier string crosses in any private-arm run of L1-L6, every run's
  trace was scanned and complete, and every collection has a valid run of every arm. Reported with
  k/n and, when k = 0, the rule-of-three 95% upper bound 3/n on the per-string crossing probability
  (descriptive, not a test). If HL1 fails, the paper reports the entity types, counts and routes of
  the crossings, never the strings.
- QUASI rates are descriptive, with no threshold: private text shorter than five words is a declared
  gap (§8.10), which L measures and cannot close.
- Wording: "public court judgments standing in for private documents"; never "real private data".
  No sentence claims R1 or RBA on L.

**12.8 Integrity.** Tag `real-prereg` on Thu 08/10 commits the builder, `MANIFEST.json` per
collection (doc_ids, source and output hashes), the `surfaces.json` and key hashes, the tasks file
`eval/real/tasks_l.json` and the analysis scripts; their SHAs go in the tag message. After the A-D
batch, tag `real-freeze`: its pre-flight requires an empty diff against `real-prereg` on those
paths (a bug fix only with a changelog entry the author signs) and an empty diff against
`paper-freeze` on the code the containers run: `backend/src`, `gateway` (excluding `gateway/tests`),
`shared`, `docker-compose.yml`, `scripts/run_evaluation.py`, `scripts/corpora`,
`scripts/tier1_probe.py`, `scripts/observation_table.py`, `scripts/measure_false_positives.py` and
`pyproject.toml`. Each L run's SLM image and model digests and resolved cloud model id must equal
those of the A-D batch manifests.

**12.9 Budget, schedule and stop rules.** Cap $15 (author, 2026-10-05) for the pilot, the 36 runs
and the 24 adversary calls; a free estimate is printed first and the run asks before exceeding it.
Schedule (amended at signing, 2026-10-15; the A-D batch of 2026-10-07 is done): signature and L0 pilot 15/10; `real-prereg` and `real-freeze` 15/10, on one commit; the L batch 15-16/10. One re-run only for a transport failure; at the cap no new collection starts, and a collection left out is left out whole and named. If no billable L run can start by 18:00 Thu 16/10, the free measures alone (extractor recall, predicate echo, Presidio) are reported, as an extractor-floor measurement. Experiment freeze 16/10 and numbers freeze 18/10 are unchanged.

**12.10 What this reverses or adds.** It partly reverses §8.6's cut of external baselines (Presidio,
descriptive only) and the plan's "no additional experiment" fallback, and adds a descriptive
rule-of-three bound to a paper whose A-D results carry no intervals. The paper adds TAB, and
Presidio back, to the references; §3, §5 (an ethics paragraph: public judgments whose applicants
consented to publication, private arms only, data minimised, nothing stored beyond the run
directory), §6 and §7 change accordingly; about half a page.

**12.11 Readings fixed before signature.** Drafted by the AI assistant on 2026-10-05 after the
track-L code was built and reviewed; each item states how the code reads a sentence above, so the
signature covers it.
- *Order and length (12.3).* "Ascending doc_id" compares doc_ids as strings (001-106448 sorts
  before 001-57819; numeric order would select other judgments); "8,000 characters" counts the
  code points of `text`. The goal check covers every judgment of the dev and test splits (the train
  split was not downloaded). The collections so built are recorded, by doc_id and hash only, in
  `eval/real/manifest_l.json`.
- *Labels and typing (12.4).* "At most 2 characters" is measured on the tokens joined by one
  separator, so only a single token of 1 or 2 characters is a label by length; a string of two or
  more tokens (initials such as A.B.) never is. A string is DIRECT if any annotator typed it DIRECT;
  its entity types are every type any annotator gave it; a mention one annotator left NO_MASK and
  another marked DIRECT or QUASI is gold; the stored spelling is the first seen (annotators by name,
  then offsets). At this build no DIRECT string is a label; labels number 1 in L0 and 10 in L1-L6.
  `string_facts` hold the non-label strings, one per (string, entity type); `surfaces.json` carries
  the groups only, so `tier1_probe analyse`, whose output lists the strings it finds, is not run on
  test collections.
- *Crossing (12.6).* Each identifier string is read on its own (strings are scanned in groups that
  share no token), so a string inside a longer hit still counts; the single-call reading that H3
  uses is reported beside it, descriptive only. "As in H3" refers to the exclusions only. Presidio's
  survival uses the same per-string rule, with the single-call reading beside it. A string survives
  Presidio when found in the anonymised text of any document of its collection; a string with
  several entity types counts under each type and once in the total.
- *Recall, echo, utility, G3 (12.6).* "Masked" means token-tuple equality with an entity in the run's
  `entities.json` (exact), with "covered" (contiguous inside one masked entity) beside it, reported
  per run, pooled, and once per extraction. Predicate echo is a whole-token hit in any relation
  field. Sections that failed in transport are counted apart from refused ones. G3's net is a
  per-string set difference against the goal-only control; repeat 1 of each arm is attacked as run;
  the rendered trace is capped at 120,000 characters, with truncation reported; the pilot's one
  adversary call is on r5. The judgments are public, so the cloud may know them from pre-training:
  G3 and any crossing traced to text the cloud wrote are read as upper bounds on what PrivDeep's
  egress carried.
- *HL1 (12.7).* Label-group strings, DIRECT or not, are reported apart (`direct_labels_crossed`) and
  do not decide HL1, unlike H3. n is the number of distinct non-label DIRECT strings over L1-L6 (65
  at this build), each counted once however many runs it crossed in; string-by-run pairs are
  reported beside it; the bound 3/n is given for these two DIRECT blocks only. Archived phase-one
  attempts count as private-arm runs: a DIRECT crossing in one fails HL1. HL1 needs one valid run of
  every arm in every collection, and every run present scanned and complete; a missing second repeat
  is named but does not decide it. Over any tasks file other than exactly L1-L6 (the pilot, for one)
  HL1 is "not testable", with the computed value reported apart.
- *Integrity (12.8).* The runtime comparison gates HL1: an L run whose SLM image or model digest or
  resolved cloud model differs from, or is unrecorded against, the A-D batch manifests makes HL1
  "not testable", though a crossing still fails it; this reads `manifest.json` of the A-D runs and
  nothing else there. `real-prereg` commits `eval/real/manifest_l.json`, the two tasks files,
  `scripts/real_corpora/`, `scripts/real_l.py`, `scripts/presidio_residual.py`,
  `scripts/freeze_batch_real.sh` and the three track-L tests; this section's own text is compared
  separately; `git check-ignore` must cover every path that holds TAB text.
- *Runs, cap, fallback (12.9).* One re-run, only for a transport failure, after which the run is not
  offered again; a pipeline that exits non-zero stops the batch and is kept as an attempt; a
  transport failure of r5 repeat 1 is not re-run once other runs reuse its extraction. The cap is
  applied before phase one to the over-estimate, admitting whole collections in order (estimate at
  this build: about $8.2 for the batch, about $0.65 for the pilot); re-runs and the adversary are
  checked against recorded spend; "asks" means the batch aborts. The free fallback runs
  `tier1_probe.py extract` on each collection (local SLM, no cloud call) and `real_l.py extraction`,
  with counts-only output.
- *Signing.* The batch accepts "Signed by the author on YYYY-MM-DD" or a filled
  "Signed: NAME (author), date YYYY-MM-DD", and refuses while the Status line says DRAFT or a blank
  remains, so the Status line is updated when signing.

**12.12 For the author before signing.** Record how sending PrivDeep's egress over these public
judgments to the provider fits Viet Nam's Law 91/2025/QH15 and the ECHR terms: The judgments are public decisions of the European Court of Human Rights, published by the Court and redistributed in TAB for information and education with the source acknowledged; the persons named are parties to public proceedings, and no data of Vietnamese data subjects is involved. What reaches the provider is PrivDeep's abstract payload of these public texts under the same egress monitor as A-D, never the texts, with nothing kept beyond the run directory. The author assesses this as lawful processing of publicly disclosed personal data for scientific research under Law No. 91/2025/QH15, and as within the ECHR's terms for reproduction of its judgments. (Recorded by the AI assistant at the author's instruction, 2026-10-15.)

Signed by the author on 2026-10-15, in the working session with the assistant: this section, with the schedule of §12.9 as amended above and the §12.12 record, is in force.

**12.13 Changelog after signing (2026-10-15, the pilot's finding).** The pilot on L0 (r5, repeat 1)
was refused at its planner request by the monitor (`RAW_CONTEXT_CONTAINMENT: 1 shingle hit(s) >= 1`,
the attempt's manifest and the audit record): the abstract payload built from real judgments carried
a contiguous run of 5-8 corpus words, the free-text relation fields being the probable route (§12.6's
predicate echo measures the sub-5-word case). The pipeline failed closed as P2 specifies, at no
cost, and the frozen core then crashed before writing `extractions.json` (`dump_extractions` on the
refusal path of `backend/src/privdeep/pipeline.py`). Two consequences, chosen by the author in the
working session:
- *Readings (§12.11 Runs, cap, fallback).* A phase-one run that exits non-zero because the monitor
  refused its planner request is kept as an attempt (its manifest notes "planning refused by
  monitor") and the batch continues with the next step; the scan counts it (`l_plans_refused_kn`,
  `l_refused_attempts_kn`, the attempts' crossings), and HL1 is then "not testable" for want of a
  valid run of every arm, with its computed value reported apart, as §12.11 reads. Any other
  non-zero exit still stops the batch. The arms that reuse r5's extraction do not run for a
  collection whose r5 repeat 1 was refused (`pending` finds no run to reuse), and the paper says so.
- *Integrity (§12.8).* One change to `backend/src/privdeep/pipeline.py` is allowed: the refusal path
  returns the extractions, so that `extractions.json` is written as on every other path. It changes
  nothing that crosses, since the request was refused before it. The container-code diff against
  `paper-freeze` (`git diff paper-freeze HEAD -- <container paths> | sha256sum`) must be exactly this
  patch, container-code diff sha256 c5e150a6d81646bdf56fa7a321b4529ca7addec76386fa890e5c1cf19c8bd5be,
  which the batch's pre-flight accepts in place of an empty diff; the paper states that L ran on this
  patched core. The SLM image, model digests and cloud model id are unchanged and still gated by HL1's
  digest check. The schedule of §12.9 is unchanged.

Signed by the author on 2026-10-15, in the working session with the assistant (recorded by the AI
assistant at the author's instruction): §12.13 is in force.

*Addendum (2026-10-15, after the batch's first step).* The first batch run of tab-L1 (r5, repeat 1:
9 requests allowed, none refused, 8 sections delivered) was invalidated by `run_evaluation.py`'s
provenance check (`tree_dirty`) because the AI assistant edited paper files in the worktree while the
batch ran, not because of the pipeline, the monitor or the container code. The author allows this one
run to be re-run once, outside §12.11's transport-only rule; the invalidated attempt is moved from
`eval/real/attempts/` to `eval/real/out/discarded_attempts/`, kept, scanned apart for crossings and
reported beside the batch, and its spend is counted against the cap through `--spent`. No tracked
file is edited while the batch runs. Signed by the author on 2026-10-15, in the working session with
the assistant (recorded by the AI assistant at the author's instruction).

*Bug fix (2026-10-15, after the batch's second step).* `freeze_batch_real.sh`'s `step()` judged every
task of the step instead of the failed ones, so a step with completed runs or unreached tasks beside
a planner refusal (tab-L3) stopped the batch, and it did not call the driver again for the tasks it
had not reached. Fixed: only tasks with an attempt and no run are judged, and the step loops over
`pending` until nothing is left; the rule of §12.13 is unchanged. Signed by the author on 2026-10-15,
in the working session with the assistant (recorded by the AI assistant at the author's instruction).


## 13. Amendment of 2026-10-26: two offline post-hoc analyses after the numbers freeze

*Drafted by the AI assistant on 2026-10-26 from the author's choice of the same day in the working
session ("Chỉ thêm phân tích offline"), after the simulated review of 2026-10-26
(`paper/reviews/simulated_review_2026-10-26.md`, items S6 and S13). **Status: signed by the author
on 2026-10-26** (recorded by the AI assistant at the author's instruction, in the working session:
"Ký như bản soạn"). Nothing below was computed before the signature.*

**13.1 Why.** The reviewers asked (S6) how much corpus text shorter than the 5-word run reaches C,
compared with entity masking, and (S13) for effect sizes between the arms and for the dispersion and
an interval of judged quality. Both can be computed offline, for free, from the frozen artifacts,
with no run, no label and no rescore. §8.9 allows a changed number only through a scripted rescore
for a found bug; it does not provide for new numbers, so this section adds them explicitly.

**13.2 What is computed, fixed here before any value is seen.** One deterministic script,
`scripts/posthoc_2026_10_26.py`, reads the frozen batch's run directories (`eval/runs/`),
`eval/evaluation.json` and the masking probe's outputs (`eval/probe/`), and writes
`eval/paper/posthoc.json`; `scripts/make_paper_tables.py` reads that file into `numbers.json`, with
sources, like every other input.
- (a) S6, short echoes. For each corpus A-D and arm, in each frozen run's core-sent content as H3
  defines it (what the local core writes into a request, excluding the goal and spans repeating a
  cloud reply), the number of distinct word n-grams of two, three and four tokens that also occur in
  the corpus documents, after the monitor's own normalisation and with every n-gram made only of
  stopwords (a fixed list in the script) dropped; and, as the comparator, the same count for the
  entity-masked documents of the masking probe under the shared extraction. Reported per corpus as
  the range over runs and arms, beside the masked documents' count.
- (b) S13, dispersion and effect size. Per arm, the SD and min-max over runs of judged quality
  (the run's mean over the judge's criteria without groundedness, as `judge_mean_exgr_<arm>`), and a
  percentile-bootstrap 95% interval of its mean over runs (10,000 resamples, fixed seed). Per corpus,
  Cliff's delta between r1's and baseline's runs for attribute accuracy and for RBA (the frozen
  rule's scores).
- (c) Presentation only: negative values are printed with the minus sign U+2212; no value changes.

**13.3 Status and use.** Every number of 13.2 is post hoc and exploratory, and is called so wherever
the paper quotes it. None tests, replaces or reinterprets a registered hypothesis or outcome
(§8.7, §8.7a, §12), and no frozen number changes. The script and its keys are committed together; an
error found later is corrected by rerunning the script, with a changelog entry, as §8.9 asks of a
rescore.

**13.4 Not added.** S1 (repeated, seeded extraction with drafting nested in it) and S3 (a judge from
another model family, human raters) need billable runs after the experiment freeze (§8.9); the paper
names them as future work.

Signed by the author on 2026-10-26, in the working session with the assistant, as drafted (recorded
by the AI assistant at the author's instruction).
