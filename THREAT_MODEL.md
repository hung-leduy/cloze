<!--
src comments give the file and lines, in this repository's code as of 2026-10-27, that back each
factual statement about the code. backend/tests/security/test_threat_model_claims.py pins the
load-bearing ones.
-->
# PrivDeep Threat Model

**Status:** scope-doc Fix 3. The harness specification (`PRIVDEEP_ENGINEERING_HARNESS.md`, which the
public release does not include) asserts four invariants across 409 lines without once stating who
the adversary is, what they observe, or what they are assumed unable to do. This document supplies
that, and is the section a security reviewer reads first.

**Revised for R1 (plan task REC2, 2026-09-27).** The first version described the baseline and R5
arms only. The R1 arm, which the paper headlines, puts a fixed attribute schema and per-referent
fact stems on the wire and rewrites cloud prose locally; §3 and §4 now say so. P2's scope, P4, P6,
P7 and P8 are regraded to what the code does, P9 is added, and §3.1 states the wire as templates.

**Revised for P8 (plan task P8, 2026-09-27).** The monitor now writes its audit record before it
forwards and refuses to forward when it cannot; P8 states what that guarantees and what it does not.

**Revised for the public release (2026-10-27, written by the AI assistant at the author's
request).** P2's measured figures cite the frozen `eval/fp_report.json` and `eval/observation.json`
instead of script docstrings and the pilot runs; G1, §3 item 2 and §5 state what the probe measured
at the freeze (`eval/probe/*.json`) instead of deferring it, and §3 no longer rests the masked
document's locality on a live refusal but states what the probe's filter did with it. The W2 gate's
cost and the evaluation-only egress (§5), and the harness spec's acceptance criterion (§7), state
what the frozen A-D batch and track L measured. P8 and §5 say that a refused planner request left
the run's egress trace empty until the pipeline was fixed that day, and §5 that an unusable planner
reply or a failed planner call, which until the same day ended the run before anything was written,
now ends it as a refusal does, and what M's audit log shows after a failed call; and every src
comment cites the code as of that day.

Everything here is either enforced by code in this repository, with the enforcing module named, or
explicitly listed as out of scope. Where a claim is weaker than the harness spec's wording, the
weaker claim is the true one and the spec is wrong.

---

## 1. Parties

| Party | Trust | Holds |
|---|---|---|
| **Local tier T** | Trusted | The corpus $C_{user}$, the on-prem SLM (`qwen3:14b` via Ollama), the `LocalMappingTable`, the egress trace, the run manifest. Runs on `privdeep-internal`, which Docker gives no default route. Also the per-session slot salt, which is drawn fresh for every run and never persisted, and under R1 the `LocalFactStore`, which has no serialisation method. T's run directories (`report.md`, `entities.json`, the extractions) are on the named volume `privdeep-data`, which only T mounts <!-- src: backend/src/privdeep/pipeline.py:208, :369-371; backend/src/privdeep/tier1_local/fact_store.py:3-5; docker-compose.yml:29-40, :79-80 --> |
| **Reference monitor M** | Trusted to enforce, but treated as the exposed surface | The sealed containment filter (salted-HMAC Bloom bits), **the shingle salt `SHINGLE_HMAC_SALT`**, the active canary set, the audit log. The **only** dual-homed service. Because M holds both the bits and the salt, a compromised M is a membership oracle over guessed shingles: it cannot enumerate the corpus from the filter, but it can confirm any five-to-eight-word run an attacker guesses. M writes its audit log to its own named volume, `privdeep-audit`, and mounts none of T's data; `backend/tests/security/test_volume_partition.py` fails if the two sides share a named volume <!-- src: gateway/main.py:115, :121, :502-511; docker-compose.yml:101-116, :128, :130; shared/shingle_filter.py:40-53; backend/tests/security/test_volume_partition.py:102-138 --> |
| **Cloud provider C** | Honest-but-curious | Every prompt PrivDeep sends and every reply it returns |
| **Reader R** | Trusted by assumption | The finished report, which carries real values and is meant to |

**Trust base.** The local host, the container runtime, the on-prem SLM and the Docker network
implementation. If the host is compromised, nothing here helps. No TEE, no attestation, and no
claim resting on either.

## 2. Adversary

**A = C**, the cloud provider, together with anyone with read access to C's request logs.

A answers faithfully, because the system's utility depends on it, and retains and analyses
everything it observes. A knows the PrivDeep algorithm, the prompt templates, the slot format, the
containment filter's parameters, and this document. For the empirical evaluation A is realised as a
frontier model prompted to reconstruct the corpus from the egress trace
(`privdeep.eval.reconstruction`). That adversary is zero-shot and is reached directly, with the
evaluation's own client, not through the monitor; scope decision D3 asked for a few-shot
adversary, and the deviation is recorded in the scope amendment (`PRIVDEEP_ICCIT_SCOPE.md` §8.2).
<!-- src: backend/src/privdeep/eval/reconstruction.py:3-14, :61-69; scripts/run_evaluation.py:880, :2503-2504 -->

**A second threat source, which the evaluated system does not have.** An injected or active
drafter: C, or content C has been induced to follow, writing Markdown built to carry a private
value into a fetching position once the core reintegrates it (the attack path of scope-doc
Fix 2). Every reported run is evidence-free, because nothing retrieves (§6), so no injected
content reaches the drafter, and an honest-but-curious C has no reason to write such markup.
The pipeline-level adversarial-drafter test MX6 (`backend/tests/security/test_pipeline_exfil.py`)
runs this source through `run_pipeline` on the r1 arm: fourteen drafts that must each refuse their
section, with no private value in the report; six pairs that differ only in whether the referenced
attribute is recorded and must get the same verdict; and drafts that are written, not refused, whose
text must put no value in a URL and fetch no image. It exercises P5 and P9 against this source, and
`backend/tests/security/test_threat_model_claims.py` pins P6 through the same scripted pipeline.
MX6 is defence in depth, not a claim about the evaluated runs.
<!-- src: backend/src/privdeep/pipeline.py:25-29, :161, :369-371; backend/tests/security/test_pipeline_exfil.py:88-95, :218-275 -->

**Goals, increasing in strength.**

- **G1 membership and linkage** — is document $d$, or cell $c$, in the corpus; and which corpus, or
  which of two traces, a payload came from. **No protection is claimed against either.** The
  payload discloses the corpus's structure by construction: the DOCUMENT STATS line (the cell and
  block counts, and the character count to the nearest 1,000), the number of slots in each
  category and the relations are on the wire in every run, and they differ between corpora. The
  relations cross as a set, not a multiset: the pipeline merges the per-document payloads and
  drops a relation that repeats an earlier one, in any document, keeping the first appearance.
  How often a relation recurs is therefore not sent, but the order of first appearance, which
  follows document and extraction order, is. `scripts/tier1_probe.py` lists, per arm, which of
  these fields differ between corpora (its G1 inventory; its `relation_multiset` field hashes the
  sorted distinct relations, so it compares the set and not the order). At the freeze commit (plan
  task EXP7) the probe built the inventory from the extraction each corpus's runs shared, with no
  stub (the `g1` block of `eval/probe/<corpus>.json`): in every arm, no two of the four evaluation
  corpora had the same DOCUMENT STATS line, matching slot counts in all categories or the same
  relation set, while the document count (four, on no request), and under r1 the attribute schema,
  were the same for all four.
  <!-- src: backend/src/privdeep/pipeline.py:103-121; backend/src/privdeep/tier2_cloud/macro_planner.py:170-192; backend/src/privdeep/tier2_cloud/section_drafter.py:176-183; scripts/tier1_probe.py:604-752; eval/probe/*.json (provenance, g1; A smoke-q3, B portfolio-b, C prose-c, D offlex-d) -->
- **G2 attribute inference** — the value behind a given slot id; under R1, also which referent
  holds which attribute value. Given a fixed local extraction and fixed salts, the planner and
  drafter requests the core builds are equal under the tested permutations of values and of which
  referent holds which value (amounts moved between projects, two projects' rows swapped, two
  sites swapped), in every arm, with the character count quantised to 1,000, **up to a renaming of
  the slot ids and the order of the listing lines, which the ids sort**. They are not
  byte-identical: a permutation can change which strings are referents and so their salted ids,
  and the test compares canonical forms in which each issued id is renamed by where it occurs and
  each run of id-listing lines is re-sorted; under the site swap the raw drafter requests differ in
  every arm. The payload JSON is compared the same way, and additionally keeps each document's
  `doc_id`, because the test rewrites documents in memory; a real permuted file would get a new
  content-hash `doc_id`, which is in the payload JSON but on no request. Quantisation is not
  invariance: a permutation that carries the exact count across a rounding boundary still changes
  the value on the wire, and the test constructs one such case. Corpus A is the nearest of the four evaluation corpora to
  a boundary, 21 characters below 3,500. This is a construction property of the core-built
  payload, pinned by `backend/tests/security/test_payload_invariance.py` with the cloud's replies
  held fixed. Whether the SLM-written relation fields vary under such permutations is not
  measured. <!-- src: backend/src/privdeep/tier2_cloud/abstract_payload.py:20-52, :84-95, :123-130; backend/tests/security/test_payload_invariance.py:32-42, :217-224, :344-393, :408-412, :445-459, :465-475, :478-495 -->
- **G3 reconstruction** — recover a planted secret verbatim or in paraphrase.

## 3. Observation set, stated exhaustively

A observes, per run: the planner request, then, section by section in outline order, one drafter
request per planned section, and the reply to each. Two qualifications to that count and order.
`CloudClient` sends a request again after a 429, 500, 502, 503 or 529 from the upstream and after
any non-refusal error from the monitor (a 502 or 503, or no connection), up to three attempts in
all, so C can receive the same request more than once (including after the monitor has already
forwarded it, P8). And a request the monitor refuses
never reaches C: a refused planner request ends the run, and a refused drafter request removes
that section's exchange. Neither changes what any one request contains. Every field and labelled
block of those requests, and every field of the payload they are rendered from, is named below,
and §3.1 gives each request's user message as a template.
`backend/tests/security/test_threat_model_claims.py` renders the templates in-process for every
arm and requires the requests the pipeline actually builds to equal them byte for byte (§3.1
says over what). <!-- src: backend/src/privdeep/pipeline.py:252-280, :304-348; backend/src/privdeep/tier2_cloud/cloud_client.py:39, :92, :160-210; gateway/main.py:577-581 -->

1. **The research goal**, user-authored, crossing in the clear: `GOAL` in the planner prompt and
   `REPORT GOAL` in every drafter prompt. It is not protected and is not claimed to be.
   <!-- src: backend/src/privdeep/tier2_cloud/macro_planner.py:187; backend/src/privdeep/tier2_cloud/section_drafter.py:190 -->
2. **The abstract payload**, built by `tier2_cloud.abstract_payload`. Its fields are `doc_id`,
   `relations`, `slots`, `stats` and, under R1 only, `attribute_schema` and `fact_ref_format`. The
   pipeline does not send the payload object; it renders its fields into the planner and drafter
   prompts:
   - `relations`, the concept relations over abstract types, as `DOCUMENT SHAPE` in the planner
     prompt and in every drafter prompt;
   - `slots`, the slot ids `⟦SLOT:<CATEGORY>_<hex8>⟧` with their categories, as
     `AVAILABLE PLACEHOLDERS` in the planner prompt and, for the section's own slots, as
     `PLACEHOLDERS YOU MAY USE` in each drafter prompt;
   - `stats`, as the planner's `DOCUMENT STATS` line: the cell count, the block count, and the
     character count rounded to the nearest 1,000, half up and never below 1,000. The exact count
     stays on the local object; the payload's `stats` and the planner prompt both read the rounded
     one. Drafter prompts carry no statistics;
   - `doc_id`, the documents' content-hash ids, is on no request.

   <!-- src: backend/src/privdeep/tier2_cloud/abstract_payload.py:84-95, :116-117, :123-152; backend/src/privdeep/tier2_cloud/macro_planner.py:168-194; backend/src/privdeep/tier2_cloud/section_drafter.py:167-199; backend/tests/security/test_payload_invariance.py:489-495 -->

   **The relation channel is free text.** All three fields of a relation (subject type, predicate,
   object type) are written by the local SLM. The prompt asks for abstract types and a verb phrase;
   nothing in code bounds their length or vocabulary. The one check in code is the W2 gate, and
   it runs over the whole corpus: no entity string of two or more characters extracted from any
   document may occur, case-insensitively, in any field of any document's relations. The extractor
   applies it to each document's own entities; once every document is extracted, the pipeline
   applies it again against the union of every document's entity strings, because the payload
   merges every document's relations. A relation with such a hit is dropped before anything is
   masked, saved or sent, and counted in its own document's `relations_dropped_leak` (summed in
   the manifest's extraction counters), so it is on no request, and the run continues. A saved
   extraction that another arm reuses is held to the same corpus-wide rule strictly: a leaking
   relation in it means an older or altered file, and the run is refused with `OntologyLeak`.
   Until 2026-09-27 the gate ran per document only, and an entity extracted only from document B,
   written into a relation of document A, crossed in the merged payload. Relations are sent in
   the planner prompt and in every drafter prompt. At the freeze commit (plan task EXP7),
   `scripts/tier1_probe.py` measured the predicate field, not the two type fields, in the
   extraction each corpus's runs shared (corpus C's lacks one of its four documents, lost to an
   unparsable extractor reply) and in three further extractions the probe made
   (`eval/probe/<corpus>.json`, `per_extraction[*].predicates`). A predicate echoes when it holds a
   run of two to four words, as the filter tokenises them (§4.1), that occurs within a single
   corpus document. The 168 predicates of the four shared extractions (one per relation the
   extraction holds, repeats included) were one to five words long; the share that echoed ran from
   17.6% (6/34, corpus C) to 41.5% (17/41, corpus B), against 1.3% to 4.8% for windows of the same
   lengths cut from the false-positive harness's clean English prose. Over all 16 extractions the
   share ran from 10.6% to 47.7%, and no predicate of five words occurred whole in a corpus
   document. A relation field that reproduces five or more corpus words verbatim falls under P2; a
   shorter echo is the gap named in §5.
   <!-- src: backend/src/privdeep/tier1_local/ontology_extractor.py:166-183, :220-286, :289-358, :383-429; backend/src/privdeep/tier1_local/extraction_io.py:125-142; backend/src/privdeep/pipeline.py:103-121, :187-203, :225-230; backend/tests/security/test_leak_gate_drop.py:135-160; backend/tests/security/test_leak_gate_corpus.py:113-165; backend/src/privdeep/tier2_cloud/macro_planner.py:170-172; backend/src/privdeep/tier2_cloud/section_drafter.py:182-183; scripts/tier1_probe.py:47-57, :198, :433-483; eval/probe/*.json (per_extraction[*].predicates, predicate_control.per_length weighted by per_extraction[0].predicates.length_tokens) -->

   **Under R1** (`--arm r1`) the payload changes in two ways.
   - It advertises no MONEY, QUANTITY, DATE or IDENTIFIER slot. Only PERSON, ORG, PROJECT and
     LOCATION referents are listed, and `assert_closed_vocabulary` refuses any payload that
     advertises a value-category slot alongside the schema. <!-- src: backend/src/privdeep/tier2_cloud/abstract_payload.py:166-167, :176-195; backend/src/privdeep/models/facts.py:59 -->
   - It adds the attribute schema (`attribute_schema`): thirteen closed attribute codes
     (`ATTRIBUTE_SCHEMA`), the same codes for every referent category. The codes were read off this
     document family in advance and are a module constant, so the schema is byte-identical for
     every corpus. It tells A what family the system was built for; it does not tell A which
     referent has which attribute. The planner receives the codes on one line, `ATTRIBUTES`. Each
     drafter call receives the codes with their fixed meanings and the fact-reference format
     (`fact_ref_format`, the text `⟦FACT:<referent hex8>.<ATTR>⟧`) in its `ATTRIBUTES` block, and
     each placeholder listed for the section with its fact stem `⟦FACT:<hex8>.<ATTR>⟧`, whose hex
     is the slot id's own. The stem contains `<ATTR>` literally and is not itself a fact
     reference. <!-- src: backend/src/privdeep/tier2_cloud/abstract_payload.py:97-102; backend/src/privdeep/models/facts.py:10-16, :51-55, :78-79, :83-94; backend/src/privdeep/tier2_cloud/macro_planner.py:174-182; backend/src/privdeep/tier2_cloud/section_drafter.py:171-178, :242-250 -->
3. **The rest of every planner and drafter request.**
   - The request envelope: `model`, `max_tokens`, `stream`, `output_config` (the effort, one
     constant for both roles and every arm), `messages` and `system`, and for the planner also
     `tools` (the `plan_outline` schema) and `tool_choice`. The system prompts and the tool schema
     are constants.
   - In each drafter prompt, what the planner wrote: the `OUTLINE` of section titles, and the
     section's `THIS SECTION` title, `OBJECTIVE` and `WORD BUDGET` (clamped by the core). The
     titles and the objective are relayed verbatim: the core neither scrubs nor checks them. Also
     `PUBLIC EVIDENCE`, the tagged public-evidence summaries; in every reported run this is the
     fixed line saying none was supplied, because nothing retrieves (§6).
   - Two constant example tokens in the drafter's system prompts: the slot example
     `⟦SLOT:PROJECT_a1b2c3d4⟧` in every arm, and under R1 the fact example
     `⟦FACT:a1b2c3d4.AUTHAMT⟧`. Their hex is fixed in the source, not derived from any referent.
     The fact example is the only complete fact reference the core itself writes, and a draft that
     copies it is scrubbed as invented unless that hex was issued (P6). It is not the only one the
     core can send: a fact reference, or any other text, that C wrote into a section title or
     objective is sent back to C in the drafter prompts, and so is anything in the user's goal.

   <!-- src: backend/src/privdeep/tier2_cloud/cloud_client.py:48, :145-158; backend/src/privdeep/tier2_cloud/macro_planner.py:55-89, :157-166, :206-238; backend/src/privdeep/tier2_cloud/section_drafter.py:47-79, :107-121, :138-149, :184-198; backend/src/privdeep/pipeline.py:161, :301 -->
4. **Every reply** C itself produced. Under R1 a drafter reply may carry fact references
   `⟦FACT:<hex8>.<ATTR>⟧` where a value would stand. **Nothing about their resolution flows back
   to C**: which references resolved, which rendered `not recorded`, and which sentences the core
   pruned stay local, because each drafter prompt is built from the goal, the outline, the
   section's objective, the payload and the evidence, never from an earlier section's reintegrated
   text. <!-- src: backend/src/privdeep/tier2_cloud/section_drafter.py:131-143, :167-199; backend/src/privdeep/pipeline.py:304-348 -->
5. **Message counts, byte lengths and wall-clock spacing.** Disclosed below, not modelled.
6. **The refusal indicator**: whether a section is present in the final report at all. Visible to
   anyone holding two reports over the same corpus.

A does **not** observe: raw document text, the masked document (it is a local artifact, which no
request carries), the mapping table, the egress trace, the run manifest, local SLM traffic, the
reintegrated report, or the exact character count. Nor, under R1, the fact store or any value in
it. The evaluation-only egress of §5 is the exception, and it never runs in a deployment: there C
is also sent the raw documents (the oracle), the reintegrated report (the judge) and the rendered
egress trace, in which a request the monitor refused appears only as a marker naming its stage and
refusal rule (the adversary).

The masked document is kept local by construction, not by the containment filter. (The design note
of `abstract_payload.py` records that the filter refused the masked document in an earlier live run,
which is why it was made a local artifact.) At the freeze commit (plan task EXP7),
`scripts/tier1_probe.py` masked each corpus's documents as R5 masks them, with each of four
extractions per corpus (the one each corpus's runs shared and three of the probe's own), and ran a
filter with the monitor's deployed shingle lengths and hit threshold over them. It refused 63 of the
64 masked documents, among them a corpus C document in which nothing is masked, because the
extraction its runs shared lost that document to an unparsable reply. The one it passed, a corpus D
document masked with the extraction its runs shared, kept no run of five corpus words after masking,
so passing it is what P2 specifies (`eval/probe/<corpus>.json`,
`per_extraction[*].masked_exposure`). <!-- src: backend/src/privdeep/tier2_cloud/abstract_payload.py:1-18, :155-165; backend/src/privdeep/pipeline.py:223-229; scripts/tier1_probe.py:194-197, :525-573; docker-compose.yml:125-127; gateway/main.py:110-112, :489-494, :505-511; eval/probe/*.json (per_extraction[*].masked_exposure: refused_documents, documents[*].shingle_hits_5_8) -->

**Collusion.** A may collude with a web-search provider, since search queries are egress. A may
collude with readers of *other* reports, so aggregates released for other tasks are auxiliary
knowledge. A does **not** collude with R, the reader of the report under analysis: R is handed
exact values by design, and no property of this system survives that case. Stating the boundary is
part of the claim.

### 3.1 Wire inventory

This subsection is the checked form of the list above. The two tables name every request field and
every payload field, as a JSON path; the two templates give the planner's and the drafter's user
message line by line. `test_threat_model_claims.py` runs `run_pipeline` in-process with a scripted
monitor, planner and drafter, in every arm, on the four evaluation corpora (corpus A with the
pilot's saved extraction, B to D with an extraction built from their surface lists) and on corpus A
again with two public-evidence units in the bank. For each run it requires that every request
field and payload field it observes has a row below, that every row is observed in some run, that
the `tools` and `tool_choice` fields and the system prompts are the module constants, and that
each user message equals the template rendered from values the test computes itself: the goal, the
per-document relations with repeats dropped, the issued slots, the cell, block and rounded
character counts summed over the documents, the scripted outline, the evidence, and the fixed
attribute vocabulary. A new line, a new field, or new content inside an existing line (a
per-referent annotation, an exact count) makes it fail. It does not bound the values themselves:
the SLM-written relation fields, the goal and what the planner wrote are checked to be the values
the run produced, not checked for what they contain.

| Request field | Sent on | What it carries |
|---|---|---|
| `model` | every request | the configured cloud model id |
| `max_tokens` | every request | 8192 |
| `stream` | every request | `false` |
| `output_config.effort` | every request | `REPORT_EFFORT`, one constant for both roles and every arm |
| `messages[].role` | every request | `user`; each request carries one message |
| `messages[].content` | every request | the user message, templates below |
| `system` | every request | a module constant: the planner's, the drafter's, or under R1 the drafter's R1 variant |
| `tools` | planner | the constant `plan_outline` tool schema |
| `tool_choice` | planner | the constant forcing `plan_outline` |

| Payload field | Crosses as |
|---|---|
| `relations[].subject_type` | `<subject type>` in both templates |
| `relations[].predicate` | `<predicate>` in both templates |
| `relations[].object_type` | `<object type>` in both templates |
| `slots[].id` | `<slot id>` in both templates, and its hex as `<hex8>` under R1 |
| `slots[].category` | `<category>` in both templates |
| `stats.cells` | `<cells>` in the planner template |
| `stats.blocks` | `<blocks>` in the planner template |
| `stats.chars` | `<chars>` in the planner template, already rounded to 1,000 |
| `attribute_schema.<category>[]` | R1 only: the constant categories and codes of both `ATTRIBUTES` lines |
| `fact_ref_format` | R1 only: `<fact ref format>` in the drafter template |
| `doc_id` | nothing: it is in the payload JSON, which no request carries |

The system prompts are constants of `macro_planner` and `section_drafter`; the only bracketed tokens
in them are the two examples of §3 item 3, `⟦SLOT:PROJECT_a1b2c3d4⟧` and, under R1,
`⟦FACT:a1b2c3d4.AUTHAMT⟧`.

Template notation: each line is `flags | text`. `each` repeats the line once per item of the list
its fields come from, in the order sent; `none` is present only when the list of the `each` line
above it is empty; `R1` lines are sent only under R1 and `~R1` lines only in the other arms. A
field in angle brackets and lower case is filled by the core; `<ATTR>` in capitals is sent
literally. `<mark>` is `>` for the section being drafted and a space otherwise.

```wire:planner
        | GOAL:
        | <goal>
        |
        | DOCUMENT SHAPE (abstract concept relations):
each    | - (<subject type>) --<predicate>--> (<object type>)
none    | - (none)
        |
        | AVAILABLE PLACEHOLDERS (slot id, category):
each    | - <slot id>  [<category>]
none    | - (none)
        |
R1      | ATTRIBUTES every placeholder of category <referent categories> may have: <attribute codes>. Values are resolved locally; assign the placeholders whose attributes a section discusses.
R1      |
        | DOCUMENT STATS: <cells> cells, <blocks> blocks, about <chars> characters (to the nearest 1000).
        |
        | Produce the outline now.
```

```wire:drafter
        | REPORT GOAL:
        | <goal>
        |
        | OUTLINE (this section marked with >):
each    | <mark> <outline id>: <outline title>
        |
        | THIS SECTION: <section title>
        | OBJECTIVE: <objective>
        | WORD BUDGET: <word budget>
        |
        | DOCUMENT SHAPE (abstract concept relations):
each    | - (<subject type>) --<predicate>--> (<object type>)
none    | - (none)
        |
        | PLACEHOLDERS YOU MAY USE (exact slot id, category):
~R1 each| - <slot id>  [<category>]
R1 each | - <slot id>  [<category>]  facts: ⟦FACT:<hex8>.<ATTR>⟧
none    | - (none for this section)
        |
R1      | ATTRIBUTES (any placeholder of category <referent categories> may have these; format <fact ref format>):
R1 each | - <attribute code>: <attribute meaning>
R1      |
        | PUBLIC EVIDENCE:
each    | [<evidence tag>] <evidence summary>
none    | (no public evidence supplied; make no numeric claims)
        |
        | Write the section body now.
```

<!-- src: backend/src/privdeep/tier2_cloud/cloud_client.py:145-158; backend/src/privdeep/tier2_cloud/macro_planner.py:55-89, :157-194; backend/src/privdeep/tier2_cloud/section_drafter.py:55-79, :107-121, :131-143, :167-199, :242-250; backend/src/privdeep/tier2_cloud/abstract_payload.py:123-152; backend/src/privdeep/pipeline.py:103-121 -->

## 4. What is enforced, and by what

| # | Property | Mechanism | Strength |
|---|---|---|---|
| P1 | Nothing on `privdeep-internal` can reach the internet | Docker `internal: true`; exactly one dual-homed service | **Structural.** Verified empirically by `scripts/verify_partition.sh` with raw-IP probes, so a DNS failure is never mistaken for isolation, and it fails if a second service is ever dual-homed |
| P2 | No contiguous run of five or more words of $C_{user}$ leaves **within any one of three inspected streams**: the concatenated string values of one request's body; one JSON path, chained across requests except where a value repeats that path's previous value byte for byte; and the keys | `shared/shingle_filter.py`: salted-HMAC word shingles (n=5..8) in a Bloom filter the monitor holds, over NFKC-normalised, casefolded, confusable-folded tokens; `gateway/main.py` inspects decoded JSON strings, builds the three streams, and carries the tail of each path to the next request on that path, for at most 64 paths | **Deterministic for verbatim spans inside one stream**, under the definition of "verbatim" in §4.1, which also lists every shape that falls outside the streams. Measured false-positive rate 0/500 on clean payloads, Wilson 95% [0, 0.0076], with a 33/33 positive control. That 0/500 is a Bloom-collision rate on generated text that shares no 5-gram with the index by construction, not an operational false-refusal rate. Through the deployed decode-then-inspect chain, in both carry modes, the same 500 payloads gave 122 refusals and none by containment: 100/100 compact abstract JSON carried inside one message string (entropy screen) and 22/100 code snippets (3 entropy, 19 secret-pattern), with none in the prose and shipped-JSON strata; the positive control was caught 33/33 there too. All these figures are in `eval/fp_report.json`, the deployed ones in its `deployed_chain` block, written at the freeze commit (plan task EXP7). In the frozen A-D batch, M refused 0 of the pipeline's 313 egress attempts over 36 runs (`eval/observation.json`); the runs are not in the repository <!-- src: gateway/main.py:133-137, :197-220, :252-356; scripts/measure_false_positives.py:15-26, :98-122; eval/fp_report.json (git, deployed_chain); eval/observation.json (summary); gateway/tests/test_shingle_filter.py:44-77; gateway/tests/test_monitor_bypasses.py:90-165, :223-247 --> |
| P3 | A request carrying a planted canary is refused and not forwarded | `linters.canary_matcher`, Aho-Corasick with a straddle buffer | **Deterministic**, for the exact token <!-- src: gateway/tests/test_canary_matcher.py:42-171, :228-240; gateway/tests/test_proxy.py:94-100 --> |
| P4 | Egress is refused until the containment filter is sealed | `gateway/main.py`: with no sealed filter the chain refuses (`CONTAINMENT_FILTER_UNSEALED`) while `STRICT_FAIL_CLOSED` is true, which is its default and the compose setting | **Fail-closed default, pinned by test.** It is a runtime flag, not a structure: with `STRICT_FAIL_CLOSED=false` an unsealed monitor admits egress <!-- src: gateway/main.py:109, :403-406; docker-compose.yml:129; gateway/tests/test_proxy.py:114-118 --> |
| P5 | No private value is reconstituted into a position from which the viewer would fetch or navigate | `tier3_reconcile.slot_reintegrator`: a source-level position check, then a render of the output with an inert sentinel in each slot; a sentinel reaching any attribute outside a short safe list, or a script or style body, refuses the section. Values are Markdown-escaped for the inline-active characters (backslash, backtick, `*`, `_`, square brackets, parentheses, angle brackets); the escape set is deliberately narrow, so a value that begins a line with `.`, `-`, `+` or `#` can still change block layout (a list item, a heading), which is layout and not a transport position. Both checks run on the draft as the cloud wrote it, before R1's sentence pruning, with a sentinel for every fact reference whether or not its attribute is recorded, so whether a section is refused, and why, does not depend on which attributes the store holds | **Structural for what the renderer produces.** The renderer is the decision procedure, not merely the test oracle. Asking about the sentinel rather than the value is what makes it exact: markdown-it percent-encodes destinations and escapes entities, so comparing the value itself both missed real leaks and refused legitimate sections <!-- src: backend/src/privdeep/tier3_reconcile/slot_reintegrator.py:68-84, :156-160, :423-466, :506-557; backend/tests/unit/test_slot_reintegrator.py:135-207; backend/tests/security/test_pipeline_exfil.py:218-228 --> |
| P6 | A placeholder or fact reference the core never issued is never resolved | `tier2_cloud.section_drafter` replaces every well-formed slot id outside the payload's slots, and every fact reference that names a referent the payload does not list or a code outside the vocabulary, with the fixed literal `[unresolved reference]`, and counts it (`invented_slots` in the manifest). A malformed token, not in the issued shape, is neither replaced nor counted, and is never resolved (pre-submission check of 2026-10-26). `tier3_reconcile.slot_reintegrator` then refuses the section (`INVENTED_SLOT`, `INVENTED_FACT`) on any that reach it; that refusal is defence in depth. Inclusion is checked against the set issued for the session, not per section and not per outline node | **Deterministic: scrub and count.** The section is not refused when `invented_slots` > 0; the pipeline scrubs, counts and continues <!-- src: backend/src/privdeep/tier2_cloud/section_drafter.py:11-16, :45, :144-149, :201-234; backend/src/privdeep/tier3_reconcile/slot_reintegrator.py:328-333, :397-421; backend/src/privdeep/pipeline.py:325, :331; backend/tests/security/test_threat_model_claims.py:520-574 --> |
| P7 | Every citation resolves to hashed evidence | `tier3_reconcile.citation_grounder` over a content-addressed bank | **Built, not exercised in any reported run.** The pipeline runs the grounder with `strict=False`, and the evidence bank is empty in every run because nothing retrieves (§6). The evidence path is cut from this submission (scope §8.6), so P7 stays in this grade for the paper <!-- src: backend/src/privdeep/pipeline.py:161, :300, :369-371; backend/src/privdeep/tier3_reconcile/citation_grounder.py:61-64, :102-103; backend/tests/unit/test_citation_grounder.py:44-76 --> |
| P8 | No request reaches the upstream unless its audit record was written first; every request the monitor answers leaves an audit line, with the exceptions named here | `gateway/main.py`: a refused request is audited before the refusal is returned and is never forwarded. A request that passes the chain gets a content-free pre-forward record (`verdict: "forwarding"`, the existing fields plus a random `request_id`) before the upstream is called; if that write fails the core gets 503 `AUDIT_UNAVAILABLE` and the upstream is not called. After the reply, or a transport error or exception, an outcome record under the same `request_id` gives the upstream status, bytes and duration (`allowed`) or the exception's type name (`upstream_error`, `proxy_error`); if the `allowed` record cannot be written the reply is withheld (503 `AUDIT_UNAVAILABLE`). An exception before forwarding is recorded as a refusal (`PROXY_ERROR: <type>`) | **Deterministic for "no audit line, no delivery"**, pinned by `gateway/tests/test_proxy.py` with a stubbed upstream asserted never called when the pre-forward write fails. "Written" means the append was closed without an `OSError`; it is not fsynced and the log is not tamper-evident (§6). Not every forwarded request has an outcome record: if the outcome write fails, or the process dies or the call is cancelled in flight, the pre-forward record stands alone, and it shows that C may hold the request, not that C does. A withheld reply's 503 is a gateway error to `CloudClient`, which sends again, so C can receive the request again, each time under a new pre-forward record. An exception after the upstream call is audited as `proxy_error`, but the core still gets 403 `PROXY_ERROR` and raises it as `EgressRefused`: the trace records a delivered request as refused, and `observation_table.py`, which reads refusals from the trace, counts it as a monitor refusal (for a planner request only since 2026-10-27: before, the refusal path left the run's trace empty, §5); the audit log, where archived, shows the `proxy_error`. An `upstream_error` outcome does not show that nothing was delivered. A refused request whose record cannot be written leaves no line, and was not forwarded. No other property rests on P8 <!-- src: gateway/main.py:54-79, :428-441, :544-637; gateway/tests/test_proxy.py:203-307; backend/src/privdeep/tier2_cloud/cloud_client.py:162-210; backend/src/privdeep/tier2_cloud/tracing.py:69-85; scripts/observation_table.py:313-331, :356; backend/src/privdeep/pipeline.py:252-280 --> |
| P9 | Under R1 a fact reference is resolved only locally, only to a value the core holds, and an absent value is written and counted, never guessed | `tier1_local.fact_store` builds facts from table cells only, through the fixed English header lexicon; no model reads a cell or a header, but a row binds only if its key is a surface of a referent the SLM extracted, so which facts exist depends on extractor recall; the derived codes come from a fixed rule table the cloud cannot parameterise. `tier3_reconcile.slot_reintegrator`: a known reference to an advertised but absent attribute renders the fixed plain words `not recorded` (`facts_unavailable`), which open no Markdown structure, and the module refuses to import if they ever could; a sentence in which every fact reference is absent is deleted (`sentences_pruned`). Both counts go to the manifest; neither goes to C. In strict mode a pruning that would itself move a token into a transport position is not applied, and the unpruned draft, which passed both checks, is written | **Deterministic** given the extraction: resolution and the header binding are model-free, the set of referents is not <!-- src: backend/src/privdeep/tier1_local/fact_store.py:7-21, :33-42, :165-255; backend/src/privdeep/models/facts.py:70-73, :96-107; backend/src/privdeep/tier3_reconcile/slot_reintegrator.py:169-173, :338-395, :435-466, :591-593; backend/src/privdeep/pipeline.py:340-341; backend/tests/unit/test_fact_store.py:82-189; backend/tests/unit/test_r1_facts.py:71-156, :246-389 --> |

Unicode escaping is not an evasion: the monitor decodes JSON and inspects string leaves. Measured
before the fix, a private string escaped as `\uXXXX` passed a filter reading raw bytes.

### 4.1 What "verbatim" means in P2

An exact-match filter is worth exactly its notion of sameness, and the naive one is far narrower
than a reader's. Each of the seven ways of sending the corpus unchanged in the table below was
measured crossing an earlier version of this monitor, and each is now closed and pinned by a test in
`gateway/tests/test_monitor_bypasses.py`:

| Sent as | Why it crossed | Closed by |
|---|---|---|
| A JSON object **key** | The leaf walker read `dict.values()` only, on the reasoning that keys are schema; a private sentence in a key gave an inspected text of `'string'` | Keys are walked and checked as their own stream |
| **Split across requests**, four tokens each | Shingles are contiguous and the monitor was stateless; a 26-token passage crossed 7/7 | A per-JSON-path tail joined to the next payload on the same path, so `messages[].content` is one stream across a session |
| **Scattered across fields** in one request | A first attempt at the fix keyed streams by JSON path only. That is a stream the sender names: the same passage across twenty invented top-level keys crossed in a single request, which the stateless monitor would have caught | The whole body's values, concatenated in document order, are inspected as a stream of their own alongside the per-path streams |
| **NFD** instead of NFC | Combining diacritics are non-word characters, so `Nguyễn` tokenised as `nguye` + `n` | NFKC before tokenising |
| One **Cyrillic homoglyph** | `е` U+0435 is not `e` | Confusable folding, Cyrillic/Greek/Armenian |
| **Fullwidth** Latin | Distinct code points | NFKC |
| An **invisible character** inside a word | Zero-width space, soft hyphen, combining grapheme joiner, variation selectors and Mongolian selectors are all non-word characters that split the token; Hangul fillers are the reverse, word characters that insert a phantom letter | The full Default_Ignorable_Code_Point set is removed before tokenising |

The sealed filter itself is also defended: the monitor takes the hit threshold and the shingle
lengths from its own configuration, not from the wire, refuses an empty filter, and keeps the
previous filter in force when a seal is refused. <!-- src: gateway/main.py:477-524; gateway/tests/test_monitor_bypasses.py:168-201 -->

"Verbatim" therefore means: a contiguous run of five or more words in reading order, compared
after Unicode normalisation, casefolding, confusable folding and invisible-character removal. It
does not mean byte-identical, and it does not cover reordering or interleaving, which are listed
below.

Where the run may sit is a second question, and the answer is not "anywhere". The monitor builds
three streams: the concatenated string values of the body, per request and with no carry; one per
JSON path, chained to earlier requests on that same path; and the keys. A run is caught if it lies
inside any one of them. So a run scattered across fields is caught within a request, and a run
spread over requests is caught while it stays on one path. <!-- src: gateway/main.py:310-346 -->

These shapes are not caught, and each is named here rather than left to be discovered:

- **A run that straddles the key/value boundary.** Keys are a stream of their own, so a run begun
  in a value and finished in a key is in neither stream. Pinned as passing by
  `test_key_and_value_are_separate_streams`. <!-- src: gateway/tests/test_monitor_bypasses.py:99-105 -->
- **A run that both moves between paths and spans requests**, including one that floods more than
  64 distinct paths to evict the path in use (the path map keeps 64 and evicts oldest-first).
  Documented in `_containment`; not pinned by a test. <!-- src: gateway/main.py:137, :287-295, :334-337 -->
- **Repeated identical chunks at one path.** The per-path stream does not join a value to the
  path's carry when the value repeats that path's previous value byte for byte, so a run that
  crosses the join between two such requests is not seen on that path. The rule exists because
  `"role": "user"`, repeated on every request, once chained to itself into a phantom five-token run
  and refused the whole session; `test_a_repeated_constant_does_not_build_a_run` pins that a
  corpus run made only of repeats of one value passes. <!-- src: gateway/main.py:134-136, :325-331; gateway/tests/test_monitor_bypasses.py:250-260 -->
- **Confusables outside the folded set**, and **reordered or interleaved text** (§5).
- **Two encodings**, per-character integer arrays and hex, pinned as strict xfails (§5).
- **Any private text shorter than five words**, including relation fields and fact stems (§5).
- **A value under a repeated JSON key.** M parses each body with `json.loads`, which keeps only the
  last of repeated keys, and forwards the raw bytes, so a value under an earlier repeat of a key is in
  none of M's streams, nor in the canary, entropy and regex screens. The core's client posts a
  dictionary and cannot emit one; not pinned by a test. Named on 2026-10-26 by the pre-submission
  check (AI assistant). <!-- src: gateway/main.py:197-220, :587-589; backend/src/privdeep/tier2_cloud/cloud_client.py:145-164 -->

The first three, and the repeated key, need the sender to choose the request structure or its
repeated contents, which is the core, and a core that is choosing how to evade is a compromised local tier, already out of
scope in §6.

## 5. What is NOT protected

Every item here is a real gap, named so a referee does not have to find it.

- **Paraphrase, summary and arithmetic derivation.** P2 is deterministic for verbatim spans and
  best-effort for everything else. The harness spec's absolute wording ("must NEVER") is wrong; the
  honest claim is the one in the table. Pinned by tests that fail if paraphrase ever starts being
  caught, so the claim cannot silently strengthen.
- **Any encoding of the corpus.** Hex, base64, or per-character integers in a JSON array carry no
  words for a word-shingle filter to match, and the entropy screen is alphabet-bound (below). Two
  of these are strict xfails in `gateway/tests/test_monitor_bypasses.py`, so if either ever starts
  being caught, the test file goes red and this paragraph is what has to change. This is the
  boundary of P2: it is a check on text the cloud can read as text, and an encoded payload is
  something the *core* would have to have produced, which puts it outside the honest-but-curious
  adversary and inside a compromised local tier, already out of scope in §6.
- **Reordering and interleaving.** A span sent with its words reordered, or with an innocuous word
  inserted after every fourth, is not paraphrase and is not caught. P2 covers contiguous runs in
  reading order.
- **A run placed to straddle the monitor's stream boundaries.** §4.1 gives the three streams and
  the shapes that fall between them: a run split across the key/value boundary, a run that both
  changes JSON path and spans requests (including eviction past 64 carried paths), and a run across
  byte-identical repeated values at one path. Closing these would require the monitor to treat the
  whole session as one undifferentiated token stream, which reintroduces the schema-noise
  false-refusal problem the streams exist to avoid. All need a sender choosing the request
  structure or its contents — the core, i.e. a compromised local tier, out of scope in §6.
- **Confusables outside the folded set.** The fold covers the Cyrillic, Greek and Armenian
  homoglyphs reachable from a keyboard, not the full UTS #39 table, and there is no mixed-script
  detection. At `hit_threshold=1` an evader must break *every* five-word window, since one
  untouched window still refuses; the gap is therefore narrower than the table's coverage
  suggests, but it is a gap.
- **Private text shorter than five words.** P2 cannot see it. Entity strings the extractor listed
  are masked, and the W2 gate keeps every document's entity strings of two or more characters out of
  every document's relation fields, though a listed string that also occurs in a constant the core
  sends, such as R1's attribute meanings, still crosses in that constant (see "Short Vietnamese
  given names cost relations" below); an entity string the extractor listed for no document, or any
  other short private phrase, is protected by nothing but extractor recall. At the freeze commit
  (plan task EXP7) `scripts/tier1_probe.py` measured that recall over four extractions per corpus,
  the one each corpus's evaluation runs shared among them (corpus C's without one of its four
  documents, §3 item 2; `eval/probe/<corpus>.json`, `per_extraction[*].recall`). In all 16, every
  gold-key referent (5 or 6 per corpus, by one of its surfaces) and every string fact (9 to 12) was
  the whole text of an entity extracted from some document of the corpus, while 0 to 8 of the 49 to
  71 generator surface strings that occur in each corpus lay inside no entity's text
  (`generator_surfaces.missed`). The corpora are synthetic and their keys generator-written, so
  these figures do not carry to other text. <!-- src: backend/src/privdeep/tier1_local/ontology_extractor.py:220-262, :299-329, :426-428; backend/src/privdeep/tier1_local/extraction_io.py:142; scripts/tier1_probe.py:40-46, :372-427; eval/probe/*.json (per_extraction[*].recall) -->
- **The relation channel.** Relation fields are open-vocabulary text written by the local SLM with
  no length or vocabulary control in code (§3 item 2). A field that echoes fewer than five corpus
  words is not caught. At the freeze commit, predicates in each of the four evaluation corpora
  echoed runs of two to four corpus words, more often than clean prose of the same lengths (§3
  item 2); the two type fields were not measured for echo.
- **The abstract payload itself.** The relational skeleton and the slot ids preserve entity
  cardinality, co-occurrence and document shape by construction. This is **pseudonymisation, not
  anonymisation**, and "non-invertible" in the harness spec is an overclaim. It also makes corpora
  linkable (G1, §2), and no protection is claimed against that.
- **The research goal**, user-authored and in the clear.
- **The refusal indicator.** Whether a section is blanked is an un-randomised function of the
  corpus, visible in every released report, growing with the number of reports. Not randomised,
  because one-sided randomised response would corrupt the grounding contract; no theorem is
  manufactured for it.
- **Local rewriting of cloud prose under R1.** The reintegrator deletes each sentence in which every
  fact reference is absent, and writes `not recorded` for any other absent one. Pruning is a
  model-free local rewrite by a regex sentence splitter; table rows, headings and fenced code are
  never pruned. It is counted per section in the manifest, and it changes the report R reads,
  not what C sees. When strict mode declines a pruning because it would move a token into a
  transport position (P9), the reintegrator counts it (`prune_reverted`), but the pipeline does not
  copy that count into the manifest. <!-- src: backend/src/privdeep/tier3_reconcile/slot_reintegrator.py:293-305, :338-383, :459-465; backend/src/privdeep/pipeline.py:338-341; backend/src/privdeep/audit/manifest.py:73-97 -->
- **A refusal lever.** The render check substitutes a fixed-format sentinel, `PDXSENTINELX0000X`
  and upward, for each token in order of first appearance. C can write that literal string into a
  URL anywhere in a section that also carries a live token, and the section is then refused
  although no value was ever placed in the URL. This lets C choose which sections are refused; it
  does not move a value. <!-- src: backend/src/privdeep/tier3_reconcile/slot_reintegrator.py:175-181, :539-556, :574-578 -->
- **Images the reintegrator does not strip.** Inline Markdown images with a remote URL,
  `![alt](https://...)`, are replaced by their alt text. A reference-style image is resolved by its
  label text, so if the substituted output still renders any image to a remote source, every image
  opener in the section is escaped and counted; local images in that section are disabled with it.
  A raw `<img>` tag is left in place: a private value inside it still refuses the section under P5,
  but a cloud-written remote `<img>` with no private value in it survives into the report.
  <!-- src: backend/src/privdeep/tier3_reconcile/slot_reintegrator.py:264-290, :471-484, :630-639 -->
- **Per-section slot binding.** Slot ids and fact references are checked against the set issued
  for the session, not against the outline node they were assigned to, so a slot the planner gave
  to one section may legally appear in another. Per-outline-node binding is cut (scope §8.6); P6
  is scrub-and-count against the session set. <!-- src: backend/src/privdeep/pipeline.py:329-331; backend/src/privdeep/tier2_cloud/section_drafter.py:144-149; backend/src/privdeep/tier3_reconcile/slot_reintegrator.py:410-413 -->
- **A compromised monitor.** M holds the salt as well as the filter (§1), so it can confirm any
  guessed run of five to eight words. A keyed design that denies M that ability is not built.
- **Timing, message count, byte length.** Data-dependent observables, not modelled.
- **Group privacy.** A secret repeated across many documents is not protected by any mechanism here.
- **Prompt injection by paraphrase.** The injection guard catches 12 of 60 adversarial payloads;
  the 48 misses are strict xfails in `gateway/tests/test_injection_redteam.py`. The guard is
  defence in depth. P1, P2 and P5 bound the damage without recognising an attack's phrasing.
  The guard is not on any live path in the reported runs (§6).
- **The entropy screen is alphabet-bound.** Maximum entropy is $\log_2|\Sigma|$, so a 4.85
  bits/char threshold sits above hex's ceiling of 4.0: hex exfiltration can never trip it, at any
  payload size, and a space every twenty characters defeats it even for base64. It is retained for
  the one encoding it does catch and is not described as enforcing P2.
- **The renderer, as a component rather than as an output.** P5 constrains the Markdown the
  reintegrator emits, decided against markdown-it's rendering of it. It does not constrain the
  program that finally displays the report: that program is not in this repository, and the second
  layer the scope document asks for — serving it under a CSP that forbids third-party subresource
  loads — **is not built**. A viewer that renders with a different parser, enables linkify so bare
  URLs become links, or permits remote subresources is outside what P5 was decided against. The
  party table above lists T, M, C and R; the renderer sits between the reintegrator and R and is
  currently trusted by omission. Naming it is the honest state; extending the boundary properly
  means building the viewer.
- **The authorised reader.** R receives exact values and verbatim quotes. The guarantee is
  asymmetric and two-recipient; if R is untrusted, nothing here helps.
- **Short Vietnamese given names cost relations.** The W2 gate matches any entity of two or more
  characters extracted from any document of the corpus as a case-insensitive substring of every
  field of every document's relations, and drops each relation it matches, counted as
  `relations_dropped_leak`. A two- or three-letter given name such as "An" or "Lan" is a substring
  of common English words ("plan", "language", "organisation"), so on a Vietnamese corpus the gate
  drops every relation of every document that contains such a word, not only of the document that
  names the person; the gate has been corpus-wide since 2026-09-27. The run completes, but the
  observation set (§3) loses those relations: the planner and the drafters see less of the
  documents' shape, and a document can be left with none (`documents_all_relations_dropped`). The
  same bluntness applies on English corpora when the extractor types a common word or phrase as an
  entity, as in the two cases of the EXP3 pilot that the unit tests pin: "recovery plan" typed as a
  PROJECT on corpus D, and "authority" typed as an ORG in one document of corpus C, which drops the
  relation "has authority" of another. In the extraction that corpus C's frozen runs shared,
  "authority" was again typed as an ORG. The word is also in R1's fixed attribute meanings, so that
  extracted-entity string crossed in core-sent content in each r1 run on corpus C
  (`crossings.b_extracted_entities` in the aggregate `eval/evaluation.json`): the core sends it
  inside a module constant, which neither the masker nor the W2 gate touches. The gate dropped one
  relation on corpus C (which entity string it matched is not recorded) and none on A, B or D, and
  it emptied no document of its relations (each corpus's r5 repeat-1 manifest,
  `extraction.relations_dropped_leak` and `documents_all_relations_dropped`, and
  `eval/runs/prose-c__r5/extractions.json`; the aggregate and the runs are not in the repository).
  Until 2026-09-27 the gate aborted the run instead. The Vietnamese corpus is cut (scope §8.6), so
  what the gate would cost it is not measured. <!-- src: backend/src/privdeep/tier1_local/ontology_extractor.py:160-162, :220-262, :299-329, :426-428; backend/src/privdeep/pipeline.py:196-203; backend/src/privdeep/models/facts.py:83-88; backend/tests/unit/test_ontology_extractor.py:182-188, :190-197, :303-336, :338-344 -->
- **Evaluation-only egress.** The oracle arm sends raw documents to C by definition, and a frontier
  judge reached directly sees the private arm's reintegrated report. Both are evaluation
  instruments, run outside the partition, and are disclosed as leaks rather than counted as system
  behaviour. Neither runs in a deployment. The reconstruction adversary is also reached directly,
  with the same client, and is sent the rendered egress trace. None of the three passes through the
  monitor. The egress trace keeps an exchange the monitor refused together with its request, as the
  local record (a refused planner request only since 2026-10-27; see below), but the rendering the
  adversary is sent replaces that exchange with one line naming its stage and the refusal rule, with
  no request content and no reply, so a request the monitor blocked (a verbatim corpus run, a
  canary, or whatever else it caught) does not reach C through the adversary call; the crossing
  scans of the same driver treat that request content as not sent, by the same test. This matters
  because a run in which the monitor refused drafter requests but which still delivers a section
  exits zero and is attacked by the adversary like any other run; the health gate counts a monitor
  refusal as an outcome, not a failure, so the refusal does not keep the run out of the pooled
  figures. A run that delivers no section, as when the monitor refuses the planner request, exits
  non-zero and is kept only as an attempt (a run directory archived under `eval/attempts/` or
  `eval/real/attempts/`, not a result), which no adversary is shown. Until 2026-10-27 a planner
  refusal left the attempt's egress trace empty, because the pipeline's refusal path returned
  without the tracer's entries, and the refused request was recorded only in the manifest's egress
  count, in its note "planning refused by monitor: <reason>" and in M's audit log; that path now
  returns the trace and the masked entities too. Until the same day a planner reply the core cannot
  use (no structured plan, no usable section, or slot references none of which it issued:
  `PlannerError`), or a planner call that fails in transport or upstream (`CloudError`,
  `GatewayError`), ended the run before the pipeline wrote anything, although the request had
  crossed or may have, and so did a reply that gave a non-zero number (or true) for a section's
  references, a 200 reply the client could not parse, or an upstream error answer whose "error" is
  not an object or that is nested too deep to decode, which raised untyped errors. Such a value, and
  an element of the array that is not a string, which was dropped uncounted, now count as references
  the core did not issue and are never resolved (a plan with no other reference is a
  `PlannerError`), and such a reply or error answer is now a `CloudError`. Each of these errors now
  ends the run as a refusal does, with the manifest, the masked entities and the extractions
  written; the manifest's note "planning failed: <error class>" leaves out the error's message,
  since a `PlannerError`'s can quote the reply, and the pipeline's output (`attempt_output.txt` in
  the attempt) holds it. The trace holds a `PlannerError`'s exchange, request and reply, and the
  manifest counts it as allowed. A failed call, at the planner as at a drafter, leaves no line,
  because the tracer records only an exchange that succeeded or that the monitor refused, so no
  local record holds its request; M's audit log, content-free, shows whether M forwarded it (P8). A
  `CloudError` is an upstream answer M passed back, so M forwarded the request. A `GatewayError`
  follows a forwarded request when M could not reach the upstream (`UPSTREAM_UNREACHABLE`) or
  withheld the reply (`AUDIT_UNAVAILABLE` after forwarding), and one M did not forward when it had
  no credential (`NO_API_KEY`) or could not write its pre-forward record or a refusal's record
  (`AUDIT_UNAVAILABLE` before forwarding: a chain, credential or streaming refusal M cannot record
  reaches the core as this `GatewayError`, not as `EgressRefused`, and leaves no line in M's log);
  when the core cannot reach M, or loses M's answer, M's log holds a forwarding record only if M
  forwarded the request. Of track L's six test collections (scope §12; public court judgments
  standing in for private documents), four had their first run, r5 repeat 1, refused at the planner
  request. Each is kept as an attempt, its trace empty (they ran before the fix), and no further run
  was made on those collections: every other run, r5's repeat 2 included, reuses the repeat-1 run's
  extraction, and the batch finds none to reuse where that run is only an attempt (scope §12.13);
  none of this is in the repository. Because the oracle and the judge send real values to C, they
  can run only on corpora that are not private, and they ran only on A-D, which are synthetic; track
  L, whose judgments are public, runs neither by design (scope §12.5), so there only the system's
  own egress, the adversary's rendering of it and the adversary's no-trace control, which holds the
  goal alone, reach C. No private corpus, the deployment corpus among them, can be measured with the
  oracle and the judge. <!-- src: scripts/run_evaluation.py:34-43, :689-691, :759-782, :852-862, :880, :996-1006, :1016-1022, :1217-1255, :1354-1356, :2503-2517; backend/src/privdeep/pipeline.py:89-91, :252-280, :372-387, :390; backend/tests/unit/test_pipeline.py:157-176, :202-226, :229-308; backend/src/privdeep/tier2_cloud/macro_planner.py:196-257; backend/src/privdeep/tier2_cloud/cloud_client.py:162-210; gateway/main.py:432-441, :566-581, :583-613; scripts/real_l.py:12-13, :1039-1047, :1075-1097, :1292-1317; backend/src/privdeep/tier2_cloud/tracing.py:69-85; backend/src/privdeep/eval/reconstruction.py:188-222, :233-257; backend/src/privdeep/eval/oracle.py:9-13 -->

## 6. Explicitly out of scope

- A compromised local host, container escape, or a malicious container runtime.
- A malicious cloud provider that returns adversarial content designed to exploit the *core* rather
  than to extract data. The sanitizer (`gateway/sanitizer/`) is not on any live path: nothing
  retrieves, nothing outside its own module and tests calls `evidence_ingest`, and the core
  container does not mount the gateway package. No confinement claim is made for injected content.
  The evidence path (M2) is cut from this submission (scope §8.6), so this holds for every reported
  run. <!-- src: backend/src/privdeep/tier3_reconcile/evidence_ingest.py:17-18, :37-48; backend/src/privdeep/pipeline.py:25-29; docker-compose.yml:79-83 -->
- A malicious task author.
- Denial of service against any component.
- Side channels in the local SLM (memorisation across sessions, cache timing).
- Multi-user isolation, persistence, key management and tamper-evident audit logging. Deferred to
  the VGU deployment by scope decision D1 and named in the paper's limitations.

## 7. What the empirical claim is, and is not

`privdeep.eval.reconstruction` measures entity recovery, per-category recovery and 5-gram recovery
by a frontier adversary over the egress trace, scored locally against the true documents.

**One adversary yields a lower bound on what is recoverable, never a worst case.** The reported
number is "at least this much leaks", not "at most", once matches that a guess would make are set
aside. The harness spec's framing of Task 4.2 as a "worst-case" measurement with an "Empirical
Mutual Information Bound" is inverted. Its acceptance criterion, under 1.5% entity recovery against
over 78% for "Baseline A (Raw transmission)", was taken here to be close to guaranteed by
construction, because the chosen metrics measure surface-string recovery, which pseudonymisation
suppresses by design (Baseline A is raw transmission, not this evaluation's baseline arm, which
pseudonymises too). The frozen A-D batch did not bear that out for every arm. Each run is scored
against the distinct entities of the extraction its corpus's runs shared (58, 73, 39 and 73 on
corpora A-D), so an arm's twelve runs give 729 scorings, and an entity matched in several repeats
counts once per repeat. The adversary matched 5, 10 and 13 of the 729 under the baseline, R1 and R5
arms respectively (0.7%, 1.4% and 1.8%), so R5's pooled rate is over the criterion; in every arm at
least one run was over it, the highest at 2.7%, 2.7% and 8.6% (the aggregate `eval/evaluation.json`,
`reconstruction.by_arm`; it and the runs are not in the repository). Recomputed from each run's
adversary output with the scorer's own whole-token test (the output stays in the run directory), the
28 matches are rating words the extractor typed as QUANTITY ("High", "Medium" and "Low", 18, ten of
them R5's), month names ("July" and "August", 4), "authority" (3, one in each R1 run on corpus C),
"Project Meridian" (2) and "Manchester" (1). Rating words and month names are the "severity labels"
and "bare month names" that the scorer's docstring names as inflating recovery, and "authority" is
in R1's fixed attribute meanings, which the core itself sends (§5). A-D ran no no-trace control, so
on A-D a match is not separated from a guess, and the reported number is not shown to be that lower
bound. The adversary evaluated is zero-shot and reads the trace directly, which makes the bound
weaker still. The rendered trace is capped at 120,000 characters, and each result records the
rendered length before the cap (`trace_chars`) and whether it was cut (`trace_truncated`). The
adversary reads the system prompt, messages and reply of each exchange the trace records as crossed,
and of an exchange the monitor refused only a marker line naming its stage and refusal rule (§5);
each result records how many exchanges were rendered so (`refused_exchanges`). It is therefore shown
no request or reply content that C did not receive, in a run with a refusal or without one; the
marker adds only that an exchange was refused and under which rule, where C observes at most that a
request it would have received did not arrive (§3, items 5 and 6). It can be shown less content than
C received: a request `CloudClient` sent more than once is rendered once, the planner's constant
tool schema is not rendered, a forwarded request whose upstream call then failed is not traced, and
a request delivered before a later monitor exception is traced, and rendered, as refused (P8; a
planner request so refused ends the run, which no adversary is shown, §5). Showing less keeps the
recovery a lower bound on what the crossing disclosed.
<!-- src: backend/src/privdeep/eval/reconstruction.py:35-37, :85-94, :147-162, :179-185, :188-222, :233-261; backend/src/privdeep/tier2_cloud/tracing.py:69-85; backend/src/privdeep/tier2_cloud/cloud_client.py:162-210 -->

No epsilon is claimed. No differential-privacy guarantee is claimed. The chaffing mechanism that
the harness spec labels a "DP budget parameter K" is cut from this build (its anonymity set
collapses to one, because only the real query's results are crawled), and nothing replaces that
label.
