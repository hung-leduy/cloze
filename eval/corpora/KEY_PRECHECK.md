# Key pre-check (AI), 2026-09-28

An independent re-derivation of every gold-key fact from the rendered documents, read through the
project's loaders, by AI agents that did not start from the generator constants. **It is an aid for
the author's audit in `KEY_AUDIT.md`, not a substitute: it marks nothing there.** Rows that agree need
only a glance; rows marked *ambiguous*, *disagrees* or *not-found* need the author's decision.

| corpus | facts checked | agrees | derived, arithmetic ok | ambiguous | disagrees / not found |
|---|---|---|---|---|---|
| A `smoke-q3` | 14 | 9 | 6 | 0 | 0 |
| B `portfolio-b` | 30 | 25 | 4 | 1 | 0 |
| C `prose-c` | 23 | 16 | 3 | 4 | 0 |
| D `offlex-d` | 30 | 26 | 4 | 0 | 0 |

## A — `smoke-q3`

I rederived all 14 numeric facts from the four documents, loaded with privdeep.ingest.load. I also checked the raw docx and xlsx XML and pdftotext output for text the loader drops, and found none. No value in the key disagrees with the documents. The 8 stated facts agree, and each is stated in 2 to 4 documents with identical values. All 6 derived facts are arithmetically correct. The 3 PCT_SPENT values are rounded to 1 dp (74.973 -> 75.0, 81.842 -> 81.8, 113.862 -> 113.9), and there are no ties, so half-even and half-up agree. Three derived facts are also stated verbatim: ZEPHYR.UNSPENT in 3 documents and KESTREL.OVERRUN in 2. AURORA.UNSPENT and the three PCT_SPENT values appear in no document.

Issues for the author's audit:
(1) The PCT_SPENT surfaces pad the 1-dp value to 2 dp ('75.00', '81.80', '113.90'). Those are not the true 2-dp values, which are 74.97, 81.84 and 113.86. '75.0' is also missing from ZEPHYR's surfaces. After the fact I looked at the generator: the key's surfaces come from money_surfaces() in scripts/corpora/writers.py, fed the 1-dp value from pct(), which explains the padding. This only matters if surface matching is used for PCT; the facts are match=numeric.
(2) REVENUE_FALL_PCT is only ever written as 'twelve percent'. The PDF binds it to Zephyr only through the section title, and the PDF says 'against plan' while the memo gives no baseline.
(3) Binding hazards, all resolvable in context:
- the docx sentence '62,567.45 USD of the authorised budget is unspent' puts an AUTHORISED cue next to the UNSPENT figure;
- the xlsx cell 'Spend exceeds budget by 6,237.75 USD' carries SPENT and AUTHORISED cues before the OVERRUN figure;
- the PDF phrase 'Authorised spend stands at 250,000.00 USD' contains the SPENT cue 'spend';
- the memo's 'rather than against the pilot' could pull 340 toward Pilot Kestrel;
- prose names Leeds and Bristol only in Zephyr contexts, although they are Aurora's and Kestrel's sites in the Budget sheet.
I found no numeric figure missing from the key. The only uncovered items are dates, which mask_patterns cover, risk severities, and the ORG to contract link. I modified no repository file and did not touch KEY_AUDIT.md. My only scratch output is texts.txt, in a scratch directory outside the repository.

**Stated in the documents but not in the key** (most are dates or labels the key leaves out by design):

- No numeric money, percent or unit figure stated in the documents is missing from the key. I checked every number in the four texts: 250,000, 187,432.55, 62,567.45, 120,000, 98,210, 45,000, 51,237.75, 6,237.75, 340 and twelve percent.
- Not in the key, probably by design because mask_patterns cover dates: project start dates in xlsx Budget!D2:D4 (ZEPHYR 2026-06-01, AURORA 2026-07-15, KESTREL 2026-08-03); risk dates in xlsx Risks!D2:D4 (ZEPHYR 2026-08-20, AURORA 2026-08-04, KESTREL 2026-08-28); the as-of date for ZEPHYR spend, 20 August 2026 (memo, pdf); the review or revised-plan date, 30 September 2026 (memo, pdf, docx).
- Not in string_facts: risk severity in xlsx Risks!E2:E4 (ZEPHYR High, AURORA Medium, KESTREL High) and 'Raised by' in Risks!C2:C4, which duplicates the owners. The ORG to contract link ('Northbridge Analytics holds contract NB-2026-0917', memo) has no fact, and the ORG referent has no facts at all.

<details><summary>All rows</summary>

| fact | key value | verdict | where found |
|---|---|---|---|
| ZEPHYR.AUTHORISED | 250000.0 | agrees | memo: 'Of the 250,000 USD authorised, 187,432.55 USD had been spent by 20 August 2026'; pdf: 'Authorised spend stands at 250,000.00 USD'; docx table 'Spend against authority', row Project Zephyr, col 'Authorised (USD)' = 250,000.00; xlsx Budget!E2 'Budget (USD)' = 250000 |
| ZEPHYR.SPENT | 187432.55 | agrees | memo: '187,432.55 USD had been spent by 20 August 2026'; pdf: 'of which 187,432.55 USD was committed by 20 August 2026'; docx table row Project Zephyr, 'Spent (USD)' = 187,432.55; xlsx Budget!F2 'Spent' = 187432.55 |
| ZEPHYR.UNSPENT | 62567.45 | derived-ok | recomputed 250,000.00 - 187,432.55 = 62,567.45; also stated in memo: 'leaving 62,567.45 USD held against the remaining milestones'; pdf: 'The unspent balance of 62,567.45 USD is held against the remaining milestones'; docx: 'that 62,567.45 USD of the authorised budget is unspent' |
| AURORA.AUTHORISED | 120000.0 | agrees | docx table row Project Aurora, 'Authorised (USD)' = 120,000.00; xlsx Budget!E3 = 120000 |
| AURORA.SPENT | 98210.0 | agrees | docx table row Project Aurora, 'Spent (USD)' = 98,210.00; xlsx Budget!F3 = 98210 |
| AURORA.UNSPENT | 21790.0 | derived-ok | recomputed 120,000.00 - 98,210.00 = 21,790.00; not stated in any document |
| KESTREL.AUTHORISED | 45000.0 | agrees | pdf: 'Pilot Kestrel has spent 51,237.75 USD against an authority of 45,000.00 USD'; docx table row Pilot Kestrel, 'Authorised (USD)' = 45,000.00; xlsx Budget!E4 = 45000 |
| KESTREL.SPENT | 51237.75 | agrees | pdf: 'Pilot Kestrel has spent 51,237.75 USD'; docx table row Pilot Kestrel, 'Spent (USD)' = 51,237.75; xlsx Budget!F4 = 51237.75 |
| KESTREL.OVERRUN | 6237.75 | derived-ok | recomputed 51,237.75 - 45,000.00 = 6,237.75; also stated in pdf: 'an overrun of 6,237.75 USD'; xlsx Risks!B4 (row Pilot Kestrel): 'Spend exceeds budget by 6,237.75 USD' |
| ZEPHYR.PCT_SPENT | 75.0 | derived-ok | recomputed 187,432.55 / 250,000 x 100 = 74.97302 -> 75.0 (1 dp); no document states it |
| AURORA.PCT_SPENT | 81.8 | derived-ok | recomputed 98,210 / 120,000 x 100 = 81.841667 -> 81.8 (1 dp); no document states it |
| KESTREL.PCT_SPENT | 113.9 | derived-ok | recomputed 51,237.75 / 45,000 x 100 = 113.861667 -> 113.9 (1 dp); no document states it |
| VENDOR.UNITS_SHORT | 340 | agrees | memo: 'Calder Logistics delivered 340 units fewer than the July commitment, and Daniel Okoye recorded the shortfall against Project Aurora rather than against the pilot.'; pdf: 'Calder Logistics delivered 340 units fewer than the July commitment. Daniel Okoye recorded the shortfall against Project A |
| ZEPHYR.REVENUE_FALL_PCT | 12 percent | agrees | memo: "Project Zephyr's Q3 revenue fell twelve percent after the Leeds pilot was cancelled in August."; pdf (section titled 'Quarterly review - Project Zephyr'): 'Revenue for the quarter fell twelve percent against plan.'; xlsx Risks!B2 (row Project Zephyr): 'Leeds pilot cancelled; revenue fell twel |
| string_facts (OWNER/SITE/CONTRACT x3) | Whitfield/Manchester/NB-2026-0917; Okoye/Leeds/NB-2026-1044; Ramanathan/Bristol/NB-2026-1187 | agrees | xlsx Budget rows 2-4, cols B (Owner), C (Site), G (Contract); corroborated in prose: pdf 'Contract NB-2026-0917 covers the Manchester site'; docx 'Project Aurora ... contract NB-2026-1044' |

</details>

## B — `portfolio-b`

I checked all 18 numeric and 12 string facts against the text from the project's own loaders, without opening the generator. None disagrees. Of the 11 stated numeric facts, 10 agree outright and the eleventh (HALCYON.REVENUE_FALL_PCT) is correct but flagged ambiguous. The 4 derived PCT_SPENT values recompute correctly: 78.0048 -> 78.0, 41.5403 -> 41.5, 96.7233 -> 96.7, 111.6474 -> 111.6, none near a rounding boundary. The 3 UNSPENT values and the Osprey OVERRUN are stated in the text and equal authorised minus spent exactly (83,581.80; 87,689.60; 6,881.10; 8,444.35). The keyed surfaces cover every rendered form: memo '380,000' and '296,418.20', pdf/docx '380,000.00', xlsx '380000' and '296418.2', and 'nine percent'. Five points for the author's audit: (1) HALCYON.REVENUE_FALL_PCT: in the pdf, 'Ridership revenue fell nine percent after the Exeter depot closure.' has no subject, sits between the Halcyon and Meridian sentences, and names Exeter, Meridian's site; only the memo and the xlsx Risk register bind it explicitly to Halcyon. (2) HALCYON.UNSPENT is stated only once, in the memo, with 'leaving 83,581.80 USD', and 'leaving' is not in the UNSPENT lexicon. (3) The docx table column 'Actuals (USD)' is not in the SPENT lexicon. (4) In the pdf, Tamarind's authority appears only as 'of 210,000.00 USD' with no allocation word. (5) Place-name distractors: 'Exeter depot' appears in Halcyon's sentences, and 'Norwich office of Veltmoor Civic Works' binds Norwich to ORG. The key has no missing numeric facts. Unkeyed items are commencement dates, severities, the vendor-supplier relation and ORG, all non-numeric or masked. No repository file was modified.

**Needs the author's decision:**

- **HALCYON.REVENUE_FALL_PCT** = `9 percent` — *ambiguous*. Found: memo: "Project Halcyon's ridership revenue fell nine percent after the Exeter depot closed for resurfacing."; pdf p1: 'Ridership revenue fell nine percent after the Exeter depot closure.'; xlsx Risk register row Project Halcyon: 'Ridership revenue fell nine percent after the Exeter depot closure'. The value is correct and the memo and xlsx bind it explicitly to Halcyon. But in the pdf the sentence has no subject: it sits between the Halcyon sentence and the Meridian sentence and names Exeter, which is Meridian's site (pdf 'Project Meridian (Exeter, ...)', memo 'procurement stalled in Exeter'). All three documents use the rendered form 'nine percent', which is in the surfaces. The '9 per cent' / '9 percent' / '9%' surfaces never occur.

**Stated in the documents but not in the key** (most are dates or labels the key leaves out by design):

- No numeric figure the documents state for a keyed referent and attribute is missing from the key. Every amount, the 215 units and the nine percent are keyed.
- Not keyed, and arguably out of scope: the xlsx 'Commenced' dates per project (Halcyon 2026-05-11, Meridian 2026-06-22, Tamarind 2026-07-06, Osprey 2026-08-17) and the Risk register 'Severity' (High/Low/Medium/High), 'Raised by' and 'Date' cells. The dates are covered by mask_patterns, but no string fact records them.
- Not keyed: the memo 'as of' date for Halcyon SPENT ('by 4 September 2026') and the board date '15 October 2026'. Both are dates and are covered by the mask patterns.
- Not keyed as a string fact: the ORG referent 'Veltmoor Civic Works' is the holder of agreement VC-2026-0311 (memo), and the docx places its office in Norwich. ORG has referent aliases but no facts.
- Not keyed as a string fact: VENDOR 'Brantley Fabrication' is Tamarind's principal supplier (pdf p2: 'Brantley Fabrication remains its principal supplier.').

<details><summary>All rows</summary>

| fact | key value | verdict | where found |
|---|---|---|---|
| HALCYON.AUTHORISED | 380000.0 | agrees | memo: 'Of the 380,000 USD allocated to Project Halcyon, ...'; pdf p1: 'Project Halcyon (Carlisle, agreement VC-2026-0311) has an allocation of 380,000.00 USD'; xlsx Portfolio row Project Halcyon, Allocation (USD) = 380000; docx table 1 row Project Halcyon, Approved (USD) = 380,000.00 |
| HALCYON.SPENT | 296418.2 | agrees | memo: '296,418.20 USD had been spent by 4 September 2026'; pdf p1: 'has spent 296,418.20 USD'; xlsx Portfolio Expenditure (USD) = 296418.2; docx table 1 Actuals (USD) = 296,418.20 |
| HALCYON.UNSPENT | 83581.8 | agrees | memo only: '..., leaving 83,581.80 USD for the final resurfacing phase.' |
| MERIDIAN.AUTHORISED | 150000.0 | agrees | memo: 'of its 150,000 USD allocation'; pdf p1: 'against an allocation of 150,000.00 USD'; xlsx Allocation (USD) = 150000; docx table 1 Approved (USD) = 150,000.00 |
| MERIDIAN.SPENT | 62310.4 | agrees | memo: 'Project Meridian has spent only 62,310.40 USD'; pdf p1: 'Project Meridian (Exeter, agreement VC-2026-0486) has spent 62,310.40 USD'; xlsx Expenditure (USD) = 62310.4; docx table 1 Actuals (USD) = 62,310.40 |
| MERIDIAN.UNSPENT | 87689.6 | agrees | memo: '87,689.60 USD remains undrawn'; xlsx Risk register row Project Meridian: 'Procurement stalled; 87,689.60 USD of the allocation is undrawn' |
| TAMARIND.AUTHORISED | 210000.0 | agrees | pdf p2: 'has spent 203,118.90 USD of 210,000.00 USD'; xlsx Allocation (USD) = 210000; docx table 1 Approved (USD) = 210,000.00 |
| TAMARIND.SPENT | 203118.9 | agrees | pdf p2: 'Project Tamarind (Norwich, agreement VC-2026-0529) has spent 203,118.90 USD'; xlsx Expenditure (USD) = 203118.9; docx table 1 Actuals (USD) = 203,118.90 |
| TAMARIND.UNSPENT | 6881.1 | agrees | docx Delivery: '... and 6,881.10 USD of the Project Tamarind allocation is unspent.' |
| OSPREY.AUTHORISED | 72500.0 | agrees | pdf p2: 'against an allocation of 72,500.00 USD'; xlsx Allocation (USD) = 72500; docx table 1 Approved (USD) = 72,500.00 |
| OSPREY.SPENT | 80944.35 | agrees | pdf p2: 'Trial Osprey (Swindon, agreement VC-2026-0774) has spent 80,944.35 USD'; xlsx Expenditure (USD) = 80944.35; docx table 1 Actuals (USD) = 80,944.35 |
| OSPREY.OVERRUN | 8444.35 | agrees | pdf p2: '..., an overrun of 8,444.35 USD.'; xlsx Risk register row Trial Osprey: 'Expenditure exceeds allocation by 8,444.35 USD' |
| HALCYON.PCT_SPENT | 78.0 | derived-ok | not stated in any document; derived from SPENT 296,418.20 / AUTHORISED 380,000 |
| MERIDIAN.PCT_SPENT | 41.5 | derived-ok | not stated; derived from 62,310.40 / 150,000 |
| TAMARIND.PCT_SPENT | 96.7 | derived-ok | not stated; derived from 203,118.90 / 210,000 |
| OSPREY.PCT_SPENT | 111.6 | derived-ok | not stated; derived from 80,944.35 / 72,500 |
| VENDOR.UNITS_SHORT | 215 | agrees | docx Delivery: 'Brantley Fabrication delivered 215 units short of the September commitment and that she has recorded the shortfall against Project Tamarind.'; xlsx Risk register row Project Tamarind: 'Brantley Fabrication delivered 215 units short of the September commitment' |
| HALCYON.REVENUE_FALL_PCT | 9 percent | ambiguous | memo: "Project Halcyon's ridership revenue fell nine percent after the Exeter depot closed for resurfacing."; pdf p1: 'Ridership revenue fell nine percent after the Exeter depot closure.'; xlsx Risk register row Project Halcyon: 'Ridership revenue fell nine percent after the Exeter depot closure' |
| HALCYON.OWNER | Imogen Castellane | agrees | xlsx Portfolio row Project Halcyon, Lead = Imogen Castellane |
| HALCYON.SITE | Carlisle | agrees | pdf p1: 'Project Halcyon (Carlisle, ...)'; xlsx Location = Carlisle; memo: 'the Carlisle works' |
| HALCYON.CONTRACT | VC-2026-0311 | agrees | pdf p1: 'agreement VC-2026-0311'; xlsx Agreement; memo: 'Veltmoor Civic Works holds agreement VC-2026-0311 for the Carlisle works.' |
| MERIDIAN.OWNER | Tobias Fairweather | agrees | xlsx Portfolio Lead = Tobias Fairweather; memo: 'Tobias Fairweather expects to return part of it' (the Meridian balance) |
| MERIDIAN.SITE | Exeter | agrees | pdf p1: 'Project Meridian (Exeter, agreement VC-2026-0486)'; xlsx Location = Exeter; memo: 'procurement stalled in Exeter' |
| MERIDIAN.CONTRACT | VC-2026-0486 | agrees | pdf p1: 'agreement VC-2026-0486'; xlsx Agreement column |
| TAMARIND.OWNER | Nadia Brennock | agrees | xlsx Portfolio Lead = Nadia Brennock |
| TAMARIND.SITE | Norwich | agrees | pdf p2: 'Project Tamarind (Norwich, agreement VC-2026-0529)'; xlsx Location = Norwich |
| TAMARIND.CONTRACT | VC-2026-0529 | agrees | pdf p2: 'agreement VC-2026-0529'; xlsx Agreement; docx: 'Agreement VC-2026-0529 is unchanged' |
| OSPREY.OWNER | Rhys Pemberton | agrees | xlsx Portfolio Lead = Rhys Pemberton |
| OSPREY.SITE | Swindon | agrees | pdf p2: 'Trial Osprey (Swindon, agreement VC-2026-0774)'; xlsx Location = Swindon |
| OSPREY.CONTRACT | VC-2026-0774 | agrees | pdf p2: 'agreement VC-2026-0774'; xlsx Agreement; docx: 'agreement VC-2026-0774 does not provide for the excess' |

</details>

## C — `prose-c`

I loaded the four documents through privdeep.ingest.load and cross-checked the text against the raw container contents: the docx XML, the xlsx sheet1.xml (one sheet, no hidden content) and pdftotext of the PDF. The loader text matches the raw content, and I found no hidden text.

All 9 stated numeric facts agree with the documents, including rendered forms, USD and decimals. Every amount is rendered as 'N,NNN.00 USD' except Cobalt's authority in the memo, which is '96,000 USD'; the surfaces cover both forms. The balances marked derived:false are stated in the documents and are also arithmetically consistent: 540,000.00 - 412,905.30 = 127,094.70; 96,000 - 88,410 = 7,590; 39,102.60 - 33,750 = 5,352.60. COBALT.UNSPENT appears only in the trustee minutes.

The three derived PCT_SPENT facts recompute correctly to 1 dp: 76.46394 -> 76.5, 92.09375 -> 92.1 and 115.85956 -> 115.9, with no rounding-mode sensitivity. However, the 2-dp surfaces '76.50', '92.10' and '115.90' are not the true 2-dp values (76.46, 92.09, 115.86). A 2-dp answer would therefore fail a surface match and depends on the numeric tolerance.

The main ambiguity is LARKSPUR.REVENUE_FALL_PCT. The memo and register bind 'fifteen percent' to Larkspur explicitly. In the PDF, the sentence 'Tariff revenue fell fifteen percent after the Hereford intake failure.' names no subject and sits between the Larkspur and Cobalt sentences, and every document attributes the cause to Hereford, which is Cobalt's site. A plausible reading therefore binds the fall to Cobalt.

VENDOR.UNITS_SHORT = 128 is bound to Cobalt explicitly in the PDF and register, and only anaphorically in the memo. Among the string facts, SITE and CONTRACT agree (the memo binds Larkspur's Truro and PW-2026-0452 only by adjacency; the PDF is explicit). The three OWNER facts are inferred from the register's 'Raised by' column and from reporting roles; no document states ownership.

Missing from the key: the unmasked 'three weeks' tanker duration tied to the Larkspur event, plus several masked dates and severity labels. No monetary or percentage figure is missing. I did not open the generator constants in scripts/corpora/, because nothing disagreed and there was nothing to explain. I modified no repository files and did not touch KEY_AUDIT.md; scratch files are in a scratch directory outside the repository.

**Needs the author's decision:**

- **LARKSPUR.REVENUE_FALL_PCT** = `15 percent (surface match)` — *ambiguous*. Found: finance-memo.md: "Project Larkspur's tariff revenue fell fifteen percent after the Hereford intake failed in August 2026"; risk-register.xlsx Register!B2 (row A2='Project Larkspur'): 'Hereford intake failure; tariff revenue fell fifteen percent'; quarterly-statement.pdf p1: 'Tariff revenue fell fifteen percent after the Hereford intake failure.' (no subject named); trustee-minutes.docx: 'the fall in tariff revenue is confined to the Hereford customers' (no figure). Two documents bind the value to Larkspur explicitly (memo and register), and it is rendered only as 'fifteen percent', which is in the surfaces. In the PDF, though, the sentence names no subject and comes straight after the Larkspur sentence and straight before 'Project Cobalt (Hereford, ...)'. Every document places the cause at Hereford, which is Cobalt's site (memo: 'Project Cobalt, under contract PW-2026-0619 at Hereford'; PDF: 'Project Cobalt (Hereford, ...)'), while Larkspur is at Truro. A reader or model could plausibly bind the 15% fall to COBALT. The key value is right as the text is written, but the binding is only semi-explicit and may be a deliberate trap. The author's audit should confirm it is intended.
- **LARKSPUR.OWNER** = `Miriam Achterberg` — *ambiguous*. Found: risk-register.xlsx Register!C2 'Raised by' = 'Miriam Achterberg' for Project Larkspur; trustee-minutes.docx: 'Miriam Achterberg reported that Project Larkspur has 127,094.70 USD unspent'. No document calls anyone an 'owner'. The name comes only from the 'Raised by' column and from who reported the item. She is also minuted as chair, so she may have reported in that role rather than as owner.
- **COBALT.OWNER** = `Declan Oyelaran` — *ambiguous*. Found: risk-register.xlsx Register!C3 'Raised by' = 'Declan Oyelaran' for Project Cobalt; finance-memo.md: 'Declan Oyelaran has booked the shortfall against Project Cobalt'; trustee-minutes.docx: 'Declan Oyelaran confirmed that Project Cobalt has 7,590.00 USD remaining'. Ownership is not stated; it is inferred from roles. He also prepared the whole quarterly statement ('Prepared by Declan Oyelaran for the trustees'), which is an organisation-wide role.
- **FENWICK.OWNER** = `Harriet Quennell` — *ambiguous*. Found: risk-register.xlsx Register!C4 'Raised by' = 'Harriet Quennell' for Scheme Fenwick; finance-memo.md: 'Harriet Quennell will bring a revised scope for Scheme Fenwick'; trustee-minutes.docx: 'Harriet Quennell reported that Scheme Fenwick has spent 39,102.60 USD'. Ownership is not stated, but this is the strongest of the three owner links: the memo and the minutes give her responsibility for the revised scope.

**Stated in the documents but not in the key** (most are dates or labels the key leaves out by design):

- LARKSPUR (finance-memo.md): 'customers were supplied from tankers for three weeks'. This duration is stated in words and belongs to the Larkspur revenue-fall event. It is in neither the key nor surfaces.json, and no mask pattern covers it, so an unmasked numeric-like surface of the source would go unchecked.
- LARKSPUR as-of date for SPENT (finance-memo.md): 'by 10 September 2026 it had spent 412,905.30 USD'. This is a date and is masked by the date patterns; noted only for completeness.
- FENWICK revised-scope deadline (finance-memo.md and trustee-minutes.docx): '22 October 2026'. A masked date with no key fact.
- Per-project risk-register attributes (risk-register.xlsx): Severity High/Medium/High and raised dates 2026-08-12, 2026-08-24, 2026-09-03 for Larkspur, Cobalt and Fenwick. These are labels and masked dates, not numeric facts, and are absent from the key.
- No monetary, percentage or unit figure appears in the documents without a matching key fact. Every amount in the four documents (540,000.00; 412,905.30; 127,094.70; 96,000 and 96,000.00; 88,410.00; 7,590.00; 33,750.00; 39,102.60; 5,352.60), plus 'fifteen percent' and '128', maps to a key fact.

<details><summary>All rows</summary>

| fact | key value | verdict | where found |
|---|---|---|---|
| LARKSPUR.AUTHORISED | 540000.0 | agrees | finance-memo.md: 'The trustees authorised 540,000.00 USD for Project Larkspur'; quarterly-statement.pdf p1: 'Project Larkspur (Truro, contract PW-2026-0452) holds an authority of 540,000.00 USD'; trustee-minutes.docx: 'Project Larkspur has 127,094.70 USD unspent of its 540,000.00 USD authority' |
| LARKSPUR.SPENT | 412905.3 | agrees | finance-memo.md: 'by 10 September 2026 it had spent 412,905.30 USD'; quarterly-statement.pdf p1: 'of which 412,905.30 USD has been spent' |
| LARKSPUR.UNSPENT | 127094.7 | agrees | finance-memo.md: 'and 127,094.70 USD remains for commissioning'; trustee-minutes.docx: 'Project Larkspur has 127,094.70 USD unspent of its 540,000.00 USD authority' |
| COBALT.AUTHORISED | 96000.0 | agrees | finance-memo.md: 'Project Cobalt, under contract PW-2026-0619 at Hereford, has an authority of 96,000 USD'; quarterly-statement.pdf p1: 'has spent 88,410.00 USD of its 96,000.00 USD authority' |
| COBALT.SPENT | 88410.0 | agrees | finance-memo.md: 'and has spent 88,410.00 USD'; quarterly-statement.pdf p1: 'Project Cobalt (Hereford, contract PW-2026-0619) has spent 88,410.00 USD' |
| COBALT.UNSPENT | 7590.0 | agrees | trustee-minutes.docx only: 'Declan Oyelaran confirmed that Project Cobalt has 7,590.00 USD remaining under contract PW-2026-0619' |
| FENWICK.AUTHORISED | 33750.0 | agrees | finance-memo.md: 'Scheme Fenwick at Lincoln was authorised 33,750.00 USD'; quarterly-statement.pdf p2: 'against an authority of 33,750.00 USD'; trustee-minutes.docx: 'which exceeds its authority of 33,750.00 USD' |
| FENWICK.SPENT | 39102.6 | agrees | finance-memo.md: 'and has spent 39,102.60 USD'; quarterly-statement.pdf p2: 'Scheme Fenwick (Lincoln, contract PW-2026-0833) has spent 39,102.60 USD'; trustee-minutes.docx: 'Scheme Fenwick has spent 39,102.60 USD' |
| FENWICK.OVERRUN | 5352.6 | agrees | finance-memo.md: 'an overrun of 5,352.60 USD'; quarterly-statement.pdf p2: 'an overrun of 5,352.60 USD' |
| LARKSPUR.PCT_SPENT | 76.5 | derived-ok | Not stated in any document; computed from SPENT 412,905.30 / AUTHORISED 540,000.00 |
| COBALT.PCT_SPENT | 92.1 | derived-ok | Not stated in any document; computed from SPENT 88,410.00 / AUTHORISED 96,000.00 |
| FENWICK.PCT_SPENT | 115.9 | derived-ok | Not stated in any document; computed from SPENT 39,102.60 / AUTHORISED 33,750.00 |
| VENDOR.UNITS_SHORT | 128 | agrees | finance-memo.md: 'Holloway Pumpworks delivered 128 units short of the August order, and Declan Oyelaran has booked the shortfall against Project Cobalt.'; quarterly-statement.pdf p2: 'Holloway Pumpworks delivered 128 units fewer than the August order for Project Cobalt.'; risk-register.xlsx Register |
| LARKSPUR.REVENUE_FALL_PCT | 15 percent (surface match) | ambiguous | finance-memo.md: "Project Larkspur's tariff revenue fell fifteen percent after the Hereford intake failed in August 2026"; risk-register.xlsx Register!B2 (row A2='Project Larkspur'): 'Hereford intake failure; tariff revenue fell fifteen percent'; quarterly-statement.pdf p1: 'Tariff revenue fell fift |
| LARKSPUR.OWNER | Miriam Achterberg | ambiguous | risk-register.xlsx Register!C2 'Raised by' = 'Miriam Achterberg' for Project Larkspur; trustee-minutes.docx: 'Miriam Achterberg reported that Project Larkspur has 127,094.70 USD unspent' |
| LARKSPUR.SITE | Truro | agrees | quarterly-statement.pdf p1: 'Project Larkspur (Truro, contract PW-2026-0452)'; finance-memo.md: 'holds contract PW-2026-0452 for the Truro treatment works' (sentence before the Larkspur sentence) |
| LARKSPUR.CONTRACT | PW-2026-0452 | agrees | quarterly-statement.pdf p1: 'Project Larkspur (Truro, contract PW-2026-0452)'; finance-memo.md: 'Pellingham Water Trust holds contract PW-2026-0452 for the Truro treatment works.' |
| COBALT.OWNER | Declan Oyelaran | ambiguous | risk-register.xlsx Register!C3 'Raised by' = 'Declan Oyelaran' for Project Cobalt; finance-memo.md: 'Declan Oyelaran has booked the shortfall against Project Cobalt'; trustee-minutes.docx: 'Declan Oyelaran confirmed that Project Cobalt has 7,590.00 USD remaining' |
| COBALT.SITE | Hereford | agrees | finance-memo.md: 'Project Cobalt, under contract PW-2026-0619 at Hereford'; quarterly-statement.pdf p1: 'Project Cobalt (Hereford, contract PW-2026-0619)' |
| COBALT.CONTRACT | PW-2026-0619 | agrees | finance-memo.md: 'Project Cobalt, under contract PW-2026-0619'; quarterly-statement.pdf p1: 'Project Cobalt (Hereford, contract PW-2026-0619)'; trustee-minutes.docx: 'Project Cobalt has 7,590.00 USD remaining under contract PW-2026-0619' |
| FENWICK.OWNER | Harriet Quennell | ambiguous | risk-register.xlsx Register!C4 'Raised by' = 'Harriet Quennell' for Scheme Fenwick; finance-memo.md: 'Harriet Quennell will bring a revised scope for Scheme Fenwick'; trustee-minutes.docx: 'Harriet Quennell reported that Scheme Fenwick has spent 39,102.60 USD' |
| FENWICK.SITE | Lincoln | agrees | finance-memo.md: 'Scheme Fenwick at Lincoln'; quarterly-statement.pdf p2: 'Scheme Fenwick (Lincoln, contract PW-2026-0833)' |
| FENWICK.CONTRACT | PW-2026-0833 | agrees | quarterly-statement.pdf p2: 'Scheme Fenwick (Lincoln, contract PW-2026-0833)'; trustee-minutes.docx: 'and that contract PW-2026-0833 does not cover the excess' (in the Fenwick sentence) |

</details>

### Addendum, 2026-09-30: the owners are stated in prose

*Written by the AI assistant for the author's review. The pre-check above is left as it was
written on 2026-09-28, against the earlier documents.*

The author decided on 2026-09-30 to state C's project owners in prose. `scripts/corpora/prose_c.py`
now writes each owner-project binding into two of the four documents, and C was regenerated. As the
loaders read them, with each PDF line break shown as a space, the new sentences are:

- quarterly-statement.pdf p1: 'Project Larkspur (Truro, contract PW-2026-0452, owner Miriam Achterberg) holds an authority of 540,000.00 USD, of which 412,905.30 USD has been spent.'
- quarterly-statement.pdf p1: 'Project Cobalt (Hereford, contract PW-2026-0619, owner Declan Oyelaran) has spent 88,410.00 USD of its 96,000.00 USD authority.'
- quarterly-statement.pdf p2: 'Scheme Fenwick (Lincoln, contract PW-2026-0833, owner Harriet Quennell) has spent 39,102.60 USD against an authority of 33,750.00 USD, an overrun of 5,352.60 USD.'
- trustee-minutes.docx para 4, under 'Present': 'Miriam Achterberg (chair; owner of Project Larkspur), Declan Oyelaran (owner of Project Cobalt), Harriet Quennell (owner of Scheme Fenwick).'

The statement names each owner in the same parenthetical as the site and contract, and the minutes
keep Miriam Achterberg as chair. The reason given above for the three *ambiguous* OWNER verdicts
(no document states ownership) therefore no longer holds; the verdicts themselves are the author's
to revise in `KEY_AUDIT.md`, which now lists these sentences as OWNER rows. The key's values are
unchanged, and so is its sha256 (`6430b96c…`). The finance memo and the risk register are
byte-identical to the earlier ones, and the register's 'Raised by' column still maps to no
`header_lexicon` code. The rows above that quote the statement's parentheticals (the SITE and
CONTRACT rows, for example 'Project Larkspur (Truro, contract PW-2026-0452)') now read with the
owner before the closing parenthesis; their values are unchanged.

Untouched, and still for the author:

- **LARKSPUR.REVENUE_FALL_PCT**, the binding question above. The statement's sentence 'Tariff revenue fell fifteen percent after the Hereford intake failure.' is unchanged in wording and in position: it follows the Larkspur sentence and precedes the Cobalt one. The Larkspur lines were re-wrapped to fit the longer parenthetical with the sentence's line break kept where it was, so the loader text around the sentence is as before: one line ends '... has been spent. Tariff revenue', and the next, 'fell fifteen percent after the Hereford intake failure.', is directly followed by the Cobalt line. On the rendered page a blank line separates the Larkspur paragraph from the Cobalt one; the loader text has no blank line there, in the earlier documents as in these, so the sentence belongs to the Larkspur paragraph only on the rendered page.
- **'three weeks'** in the finance memo, which is in neither the key nor surfaces.json and which no mask pattern covers.

The pilot's C runs (plan task EXP3) read the earlier documents.

## D — `offlex-d`

I loaded all four documents through privdeep.ingest.load and cross-checked them against raw extraction (docx XML, pdftotext, openpyxl). The loader text matches the raw content, and I found no hidden sheets or cells. All 18 numeric/surface facts and 12 string facts in the key agree with the documents. The 12 stated numeric facts appear with the rendered surfaces the key lists: comma plus 2 dp in the pdf, docx and memo, and bare numbers in the xlsx. The one exception is REVENUE_FALL_PCT: only the surface 'seven percent' occurs, and the alternates '7 per cent', '7 percent' and '7%' do not appear anywhere. UNSPENT and OVERRUN are stated outright, so derived:false is right for them, and they match the arithmetic: 460000-187946.5=272053.5, 125000-98340.75=26659.25, 238500-229871.4=8628.6, 63512.8-58000=5512.8. I recomputed the four derived PCT_SPENT values with Decimal: 40.857934->40.9, 78.6726->78.7, 96.382138->96.4 and 109.504828->109.5. None sits on a rounding knife-edge. There were no disagreements, so I did not open the generator constants. Points worth the author's attention: (1) WEIRGATE.REVENUE_FALL_PCT. The pdf sentence has no subject and is bound to Weirgate only by position. All three mentions say 'Grimsby quay', and Grimsby is Fallowbeck's site, not Weirgate's (Falmouth). The memo and xlsx bind it to Weirgate explicitly, so the value is correct. (2) VENDOR.UNITS_SHORT=164. The grammatical subject is Tarrant, but the figure is recorded against Fallowbeck and the xlsx row is keyed to Fallowbeck. The key's dual subjects cover this; confirm that is intended. (3) Lexicon gaps and cue collisions, not key-value errors. The xlsx header 'Envelope (USD)' (Fallowbeck and Lodestar AUTHORISED) is not in the AUTHORISED lexicon. The pdf 'has spent 229,871.40 USD of 238,500.00 USD' has no AUTHORISED cue. The xlsx 'Spend exceeds allocation by 5,512.80' and the docx '8,628.60 USD of the ... allocation is unspent' put SPENT and AUTHORISED cue words next to OVERRUN and UNSPENT figures. (4) WEIRGATE.UNSPENT and FALLOWBECK.UNSPENT each have a single source (memo and docx respectively). The only stated figures missing from the key are dates, which the mask_patterns cover. I made no repository changes and wrote no scratch files beyond docs.txt, the loader output dump, in a scratch directory outside the repository.

**Stated in the documents but not in the key** (most are dates or labels the key leaves out by design):

- No numeric money/percent/unit figure stated in the four documents is absent from the key; every stated amount maps to a key fact.
- Dates per referent not in key (all matched by mask_patterns, so presumably intentional): xlsx kick-off/start dates Saltmarsh 2026-04-13, Weirgate 2026-06-01, Fallowbeck 2026-05-18, Lodestar 2026-07-27; xlsx risk-register dates Saltmarsh 2026-08-19, Weirgate 2026-08-27, Fallowbeck 2026-09-02, Lodestar 2026-09-10; memo 'spent by 9 September 2026' (Saltmarsh as-of date).
- Non-numeric relations not in key (informational): Tarrant Marine Supplies is Fallowbeck's 'principal supplier' (pdf p2); risk severities per project (xlsx: Saltmarsh Low, Weirgate High, Fallowbeck Medium, Lodestar High).

<details><summary>All rows</summary>

| fact | key value | verdict | where found |
|---|---|---|---|
| SALTMARSH.AUTHORISED | 460000.0 | agrees | memo: 'Of the 460,000 USD allocated to Project Saltmarsh'; pdf p1: 'Project Saltmarsh (Whitby, contract WHB-0418-26) has an allocation of 460,000.00 USD'; docx table row 'Project Saltmarsh / 460,000.00' (col 'Approved (USD)'); xlsx Capital works 'Authority (USD)' = 460000 |
| SALTMARSH.SPENT | 187946.5 | agrees | memo: '187,946.50 USD had been spent by 9 September 2026'; pdf p1: 'has spent 187,946.50 USD'; docx table 'Outlay to date (USD)' = 187,946.50; xlsx Capital works 'Outlay to date (USD)' = 187946.5 |
| SALTMARSH.UNSPENT | 272053.5 | agrees | memo: '272,053.50 USD remains undrawn while the dredging consent is outstanding'; xlsx Risk register (Project Saltmarsh): 'Dredging consent delayed; 272,053.50 USD of the allocation is undrawn' |
| WEIRGATE.AUTHORISED | 125000.0 | agrees | memo: 'Project Weirgate has spent 98,340.75 USD of its 125,000 USD allocation'; pdf p1: 'against an allocation of 125,000.00 USD'; docx table = 125,000.00; xlsx Capital works 'Authority (USD)' = 125000 |
| WEIRGATE.SPENT | 98340.75 | agrees | memo: 'Project Weirgate has spent 98,340.75 USD'; pdf p1: 'Project Weirgate (Falmouth, contract WHB-0562-26) has spent 98,340.75 USD'; docx table = 98,340.75; xlsx 'Outlay to date (USD)' = 98340.75 |
| WEIRGATE.UNSPENT | 26659.25 | agrees | memo only: '26,659.25 USD is unspent for the final quay phase at Falmouth.' |
| FALLOWBECK.AUTHORISED | 238500.0 | agrees | pdf p2: 'Scheme Fallowbeck (Grimsby, order WHB-0691-26) has spent 229,871.40 USD of 238,500.00 USD.'; docx table = 238,500.00; xlsx Harbour services 'Envelope (USD)' = 238500 |
| FALLOWBECK.SPENT | 229871.4 | agrees | pdf p2: 'has spent 229,871.40 USD of 238,500.00 USD'; docx table 'Outlay to date (USD)' = 229,871.40; xlsx Harbour services 'Actual spend (USD)' = 229871.4 |
| FALLOWBECK.UNSPENT | 8628.6 | agrees | docx Delivery para: 'Order WHB-0691-26 is unchanged, and 8,628.60 USD of the Scheme Fallowbeck allocation is unspent.' |
| LODESTAR.AUTHORISED | 58000.0 | agrees | pdf p2: 'against an allocation of 58,000.00 USD'; docx table row 'Pilot Lodestar / 58,000.00'; xlsx Harbour services 'Envelope (USD)' = 58000 |
| LODESTAR.SPENT | 63512.8 | agrees | pdf p2: 'Pilot Lodestar (Harwich, order WHB-0837-26) has spent 63,512.80 USD'; docx table = 63,512.80; xlsx 'Actual spend (USD)' = 63512.8 |
| LODESTAR.OVERRUN | 5512.8 | agrees | pdf p2: '..., an overrun of 5,512.80 USD.'; xlsx Risk register (Pilot Lodestar): 'Spend exceeds allocation by 5,512.80 USD' |
| SALTMARSH.PCT_SPENT | 40.9 | derived-ok | not stated in any document; derived from 187,946.50 / 460,000 |
| WEIRGATE.PCT_SPENT | 78.7 | derived-ok | not stated; derived from 98,340.75 / 125,000 |
| FALLOWBECK.PCT_SPENT | 96.4 | derived-ok | not stated; derived from 229,871.40 / 238,500 |
| LODESTAR.PCT_SPENT | 109.5 | derived-ok | not stated; derived from 63,512.80 / 58,000 |
| VENDOR.UNITS_SHORT | 164 | agrees | docx Delivery para: 'Tarrant Marine Supplies delivered 164 units short of the August commitment and that she has recorded the shortfall against Scheme Fallowbeck.'; xlsx Risk register row 'Scheme Fallowbeck': 'Tarrant Marine Supplies delivered 164 units short of the August commitment' |
| WEIRGATE.REVENUE_FALL_PCT | 7 percent (surface match) | agrees | memo: "Project Weirgate's berthing revenue fell seven percent after the Grimsby quay closed for repairs."; xlsx Risk register row 'Project Weirgate': 'Berthing revenue fell seven percent after the Grimsby quay closure'; pdf p1: 'Berthing revenue fell seven percent after the Grimsby quay closure.' |
| SALTMARSH.OWNER | Ottilie Farquhar | agrees | xlsx Capital works 'Responsible officer'; memo 'Ottilie Farquhar asked that the Project Saltmarsh balance not be reallocated' |
| SALTMARSH.SITE | Whitby | agrees | pdf p1 'Project Saltmarsh (Whitby, ...)'; xlsx 'Location' = Whitby; memo 'Whitby dredging works' |
| SALTMARSH.CONTRACT | WHB-0418-26 | agrees | pdf p1 'contract WHB-0418-26'; xlsx 'Contract'; memo 'Wrenfield Harbour Board holds contract WHB-0418-26 for the Whitby dredging works' |
| WEIRGATE.OWNER | Bastian Greenhalgh | agrees | xlsx Capital works 'Responsible officer'; xlsx Risk register 'Raised by' |
| WEIRGATE.SITE | Falmouth | agrees | pdf p1 'Project Weirgate (Falmouth, ...)'; xlsx 'Location'; memo 'final quay phase at Falmouth' and 'the Falmouth works' |
| WEIRGATE.CONTRACT | WHB-0562-26 | agrees | pdf p1 'contract WHB-0562-26'; xlsx 'Contract' |
| FALLOWBECK.OWNER | Leonie Radcliffe | agrees | xlsx Harbour services 'Owner'; docx 'Leonie Radcliffe reported ... recorded the shortfall against Scheme Fallowbeck' |
| FALLOWBECK.SITE | Grimsby | agrees | pdf p2 'Scheme Fallowbeck (Grimsby, ...)'; xlsx 'Depot' = Grimsby |
| FALLOWBECK.CONTRACT | WHB-0691-26 | agrees | pdf p2 'order WHB-0691-26'; xlsx 'Order ref'; docx 'Order WHB-0691-26 is unchanged' |
| LODESTAR.OWNER | Caspar Wetherby | agrees | xlsx Harbour services 'Owner'; docx 'Caspar Wetherby confirmed that Pilot Lodestar ...'; memo 'Caspar Wetherby will present a recovery plan for Pilot Lodestar' |
| LODESTAR.SITE | Harwich | agrees | pdf p2 'Pilot Lodestar (Harwich, ...)'; xlsx 'Depot' = Harwich |
| LODESTAR.CONTRACT | WHB-0837-26 | agrees | pdf p2 'order WHB-0837-26'; xlsx 'Order ref'; docx 'order WHB-0837-26 does not provide for the excess' |

</details>

*Edited by the AI assistant on 2026-10-27 at the author's request: the three scratch paths the passes reported, under the machine's temporary directory, now read "a scratch directory outside the repository". No verdict or other text changed.*
