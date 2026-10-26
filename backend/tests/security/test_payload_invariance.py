"""G2: the core-built payload and prompts do not depend on which referent holds which value.

Plan task EXP4, experiment X4. The question G2 asks of the wire is whether an
observer of what crosses can tell *which* project holds *which* amount, site
or row. This test answers it for what the core builds, and only that:

* **Built by the real code path.** ``run_pipeline``, per arm, on corpus A
  loaded by the real loaders, reusing the pilot's saved extraction (the fixture is a byte copy of
  ``eval/pilot/runs-before-paper-freeze-20261007133005/smoke-q3__r1/extractions.json``, not of
  the frozen batch's; the corpus is synthetic, so it carries nothing private). The payload is caught
  as ``MacroPlanner.plan`` receives it and the fact store as the pipeline
  builds it; the planner and drafter requests are the bodies the scripted
  monitor receives. The analysis salt and the monitor salt are fixed.
* **The cloud's replies are fixed.** The planner stub is a deterministic
  function of the request it is sent (referent slots to one section, value
  slots to another, the first listed slot of each category to a third) and
  the drafter stub returns one constant text. Equal requests up to renaming
  therefore get equal replies up to the same renaming.
* **Permutations, in memory.** The documents are rewritten and re-masked;
  nothing is re-extracted. The extraction is held fixed: its relations byte
  for byte, and its entity strings mapped by the same substitution as the
  documents, which is what an extractor that responds to a value and not to
  its holder would return. Without that, an entity the substitution moved
  into a document whose list never had it would go unmasked, a failure of the
  test's own extractor model rather than of the core. Three cases on A:
  ``amounts``, every project's authorised and spent amounts moved one project
  along (Zephyr takes Aurora's, Aurora Kestrel's, Kestrel Zephyr's), every
  spelling kept in its style; ``rows``, Project Zephyr's and Project Aurora's
  names swapped everywhere, which swaps every row either holds; ``site``,
  Manchester and Bristol swapped everywhere. Each is applied consistently to
  every document, so the permuted corpus describes one world, not two.
* **Canonical renaming, order-insensitive.** A permutation can change which
  strings are referents (``Manchester site`` becomes ``Bristol site``), and so
  their HMAC ids, and payload slots are sorted by id. So issued ids are
  renamed by what they do, not by their hex: each id's signature is how often
  it occurs in each compared artifact, ids are numbered per category in
  signature order, and every run of consecutive lines naming an id (the slot
  listings, whose order is a sort on a salted hash) is sorted. Ids with equal
  signatures occur only in the same listings, so which of them gets which
  number cannot change the result. The FACT stem's hex follows its slot.
* **Byte equality** of three channels per arm: the payload JSON, the planner
  request and the drafter requests.

What it shows, and what it does not
-----------------------------------
For BASELINE and R5 the test is close to tautological, and the paper says so:
their payload is the extraction's relations, slot ids keyed on entity strings
the permutation only relabels, and three document statistics. What it pins is
that nothing else enters: no value, no position, no per-referent order. For
R1 the local fact store does hold the permuted values (checked below, so the
permutations are not vacuous), and the test shows none of that reaches the
wire. Every result is conditional on the extraction: the claim is "the
core-built payload and prompts, given the extraction". Whether the SLM would
write different predicates for a permuted document is not measured here.

Measured result: all three channels are byte-equal under all three cases in
every arm (27 of 27), with the character count quantised to 1,000.

History, because it is the reason for the quantum. At 432de29 the drafter
requests were invariant everywhere and the payload and planner request under
``rows``, but under ``amounts`` and ``site`` those two differed in one channel,
the exact character count (``DOCUMENT STATS: ... N characters`` in the
planner prompt, ``stats.chars`` in the payload). A value's spelling has a
length, and the documents mention the projects unequally often, so moving
values between projects moved the corpus's length: 3479 characters became 3482
under ``amounts`` and 3476 under ``site``. Twelve strict xfails named that
channel. The author decided the fix on 2026-09-27: the count crosses rounded to
the nearest 1,000 (``coarse_chars`` in abstract_payload.py, read by the payload
JSON and the planner prompt through ``AbstractPayload.wire_stats``). All three
values round to 3000, so the xfails are now passing assertions of byte
equality. The exact count still moves locally (pinned below, so the equality is
the quantum's doing and not a permutation that stopped moving it); the cell and
block counts move under no tested case (60 and 15 on A throughout).

What crosses now, then: the relations, the slot listing up to renaming, the
cell and block counts, and the character count to the nearest 1,000. The claim
is "invariant under the tested permutations, with the character count
quantised to 1,000; a change across a quantum boundary remains visible". The
second clause is not hypothetical and is constructed below: corpus A padded by
18 characters sits at 3497, ``amounts`` takes it to 3500, and the wire says
3000 before and 4000 after. Corpus A is the weakest of the four corpora: at
3479 it is 21 characters below the 3500 boundary (B 3576 is 76 above it, C 3014
is 486 below 3500, D 3693 is 193 above 3500; pinned below). The renaming is
exercised, not idle: under ``site`` in every arm, and under ``amounts`` in
BASELINE (whose ids key on spellings), the issued ids change and the raw
drafter requests differ; their canonical forms do not.
"""

from __future__ import annotations

import asyncio
import functools
import json
import re
from collections import Counter
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from privdeep import pipeline as P
from privdeep.ingest import SUFFIXES, load
from privdeep.models.document import Cell, Document, Span
from privdeep.tier1_local.extraction_io import dump_extractions, load_extractions
from privdeep.tier1_local.fact_store import LocalFactStore
from privdeep.tier1_local.ontology_extractor import Extraction
from privdeep.tier1_local.slm_client import AsyncSLMClient
from privdeep.tier1_local.slot_masker import SLOT_RE, Entity
from privdeep.tier2_cloud.abstract_payload import coarse_chars
from privdeep.tier2_cloud.cloud_client import CloudClient
from privdeep.tier3_reconcile.evidence_bank import EvidenceBank

from shared.shingle_filter import ShingleFilter

pytestmark = pytest.mark.security

REPO = Path(__file__).resolve().parents[3]
CORPUS = REPO / "eval" / "corpora" / "smoke-q3"
FIXTURE = Path(__file__).parent / "fixtures" / "smoke-q3_extractions.json"
SALT = b"payload-invariance-analysis-salt"
GW_SALT = b"unit-gw-salt"
GW = "http://reference-monitor:5050"
GOAL = "Assess the current position and risks."
ARMS = ("baseline", "r5", "r1")
CHANNELS = ("payload_json", "planner_request", "drafter_requests")
REFERENT_CATEGORIES = ("PERSON", "ORG", "PROJECT", "LOCATION")


# --------------------------------------------------------------------- corpus A


@functools.cache
def _docs() -> tuple[Document, ...]:
    """Corpus A in the order `pipeline._main` loads it."""
    return tuple(load(p) for p in sorted(CORPUS.iterdir()) if p.suffix.lower() in SUFFIXES)


@functools.cache
def _extractions() -> tuple[Extraction, ...]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return tuple(load_extractions(data, list(_docs()), canary_prefix="CANARY_PRIVDEEP_"))


# --------------------------------------------------------------------- permutations
#
# A substitution is a function from text to non-overlapping (start, end, new)
# edits. The same function rewrites the documents and the entity strings.

Edits = list[tuple[int, int, str]]


def _names(mapping: dict[str, str]) -> Callable[[str], Edits]:
    rx = re.compile(r"(?<![0-9A-Za-z])(?:" + "|".join(
        re.escape(k) for k in sorted(mapping, key=len, reverse=True)) + r")(?![0-9A-Za-z])")
    return lambda text: [(m.start(), m.end(), mapping[m.group(0)]) for m in rx.finditer(text)]


_NUMBER = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\w]|[.,]\d)")


def _render(value: Decimal, comma: bool, places: int) -> str:
    exp = value.normalize().as_tuple().exponent
    places = max(places, -exp if isinstance(exp, int) and exp < 0 else 0)
    return f"{value:,.{places}f}" if comma else f"{value:.{places}f}"


def _amounts(mapping: dict[Decimal, Decimal]) -> Callable[[str], Edits]:
    """Every spelling of a mapped amount, rewritten in its own style."""
    def edits(text: str) -> Edits:
        out = []
        for m in _NUMBER.finditer(text):
            v = Decimal(m.group(1).replace(",", "") + (f".{m.group(2)}" if m.group(2) else ""))
            if v in mapping:
                out.append((m.start(), m.end(),
                            _render(mapping[v], "," in m.group(1), len(m.group(2) or ""))))
        return out
    return edits


def _key_amounts() -> dict[Decimal, Decimal]:
    """Authorised and spent amounts, each project's moved one project along."""
    key = json.loads((CORPUS / "smoke_fact_key.json").read_text(encoding="utf-8"))
    val = {f["fact_id"]: Decimal(str(f["value"])) for f in key["facts"]
           if f["attribute"] in ("AUTHORISED", "SPENT")}
    order = ("ZEPHYR", "AURORA", "KESTREL")
    out = {}
    for attr in ("AUTHORISED", "SPENT"):
        for i, p in enumerate(order):
            out[val[f"{p}.{attr}"]] = val[f"{order[(i + 1) % 3]}.{attr}"]
    return out


CASES: dict[str, Callable[[], Callable[[str], Edits]]] = {
    "amounts": lambda: _amounts(_key_amounts()),
    "rows": lambda: _names({"Project Zephyr": "Project Aurora", "Project Aurora": "Project Zephyr",
                            "Zephyr": "Aurora", "Aurora": "Zephyr"}),
    "site": lambda: _names({"Manchester": "Bristol", "Bristol": "Manchester"}),
}


def _apply(text: str, edits: Edits) -> tuple[str, Callable[[int], int]]:
    pieces, cursor, shifts = [], 0, []
    for a, b, new in edits:
        pieces += [text[cursor:a], new]
        cursor = b
        shifts.append((a, b, len(new) - (b - a)))
    pieces.append(text[cursor:])

    def moved(pos: int) -> int:
        assert not any(a < pos < b for a, b, _ in shifts), "a boundary inside a rewritten span"
        return pos + sum(d for _, b, d in shifts if b <= pos)
    return "".join(pieces), moved


def _relabel(doc: Document, sub: Callable[[str], Edits]) -> Document:
    """The document with `sub` applied, every cell and block span moved with it."""
    text, moved = _apply(doc.text, sub(doc.text))
    cells = [Cell(c.sheet, c.row, c.col, text[moved(c.span.start):moved(c.span.end)],
                  Span(moved(c.span.start), moved(c.span.end))) for c in doc.cells]
    blocks = [(label, Span(moved(s.start), moved(s.end))) for label, s in doc.blocks]
    return Document(doc.doc_id, doc.kind, doc.source_path, text, cells, blocks,
                    dict(doc.metadata))


def _pad(doc: Document, n: int) -> Document:
    """`n` spaces appended to the text; every span lies before them and stays put."""
    return Document(doc.doc_id, doc.kind, doc.source_path, doc.text + " " * n, list(doc.cells),
                    list(doc.blocks), dict(doc.metadata))


def _corpus(case: str, pad: int = 0) -> tuple[list[Document], dict[str, Any]]:
    """Documents and the saved-extraction dict the pipeline reuses, for one case.

    `pad` appends that many spaces to the last document, before the case is
    applied; only the boundary test uses it."""
    docs, exs = list(_docs()), list(_extractions())
    if pad:
        docs[-1] = _pad(docs[-1], pad)
    if case != "original":
        sub = CASES[case]()
        docs = [_relabel(d, sub) for d in docs]
        exs = [Extraction(entities=[Entity(_apply(e.text, sub(e.text))[0], e.category)
                                    for e in ex.entities],
                          relations=list(ex.relations),
                          **{k: getattr(ex, k) for k in ("dropped_not_in_text",
                                                         "dropped_bad_category",
                                                         "dropped_malformed",
                                                         "dropped_category_conflict", "chunks")})
               for ex in exs]
    return docs, dump_extractions(docs, exs)


# --------------------------------------------------------------------- the scripted cloud

_LISTED = re.compile(r"^- (⟦SLOT:([A-Z]+)_[0-9a-f]{8}⟧)  \[", re.M)
DRAFT = "The position is summarised here without any figure."


class Cloud:
    """Monitor and cloud, scripted. Replies depend only on the request."""

    def __init__(self) -> None:
        self.plan: dict | None = None
        self.drafts: list[dict] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.url.path == "/canaries":
            return httpx.Response(200, json={"registered": 5, "active": 5})
        if req.url.path == "/containment/seal":
            g = ShingleFilter.from_wire(req.content, salt=GW_SALT)
            return httpx.Response(200, json={"sealed": True, "n_added": g.bloom.n_added,
                                             "m_bits": g.bloom.m_bits, "k": g.bloom.k,
                                             "n_min": g.n_min, "n_max": g.n_max,
                                             "hit_threshold": g.hit_threshold})
        body = json.loads(req.content)
        usage = {"input_tokens": 10, "output_tokens": 5}
        if body.get("tool_choice"):
            self.plan = body
            listed = _LISTED.findall(body["messages"][0]["content"])
            firsts = list({c: s for s, c in reversed(listed)}.values())
            sections = [
                ("Parties and places", [s for s, c in listed if c in REFERENT_CATEGORIES]),
                ("Figures and dates", [s for s, c in listed if c not in REFERENT_CATEGORIES]),
                ("Outlook", sorted(firsts, key=[s for s, _ in listed].index)),
            ]
            return httpx.Response(200, json={
                "id": "m", "type": "message", "role": "assistant", "model": "claude-sonnet-5",
                "stop_reason": "tool_use", "usage": usage,
                "content": [{"type": "tool_use", "id": "t", "name": "plan_outline", "input": {
                    "sections": [{"title": t, "objective": f"Cover the {t.lower()}.",
                                  "word_budget": 300, "slot_ids": ids}
                                 for t, ids in sections]}}]})
        self.drafts.append(body)
        return httpx.Response(200, json={
            "id": "m", "type": "message", "role": "assistant", "model": "claude-sonnet-5",
            "stop_reason": "end_turn", "usage": usage,
            "content": [{"type": "text", "text": DRAFT}]})


def _slm(req: httpx.Request) -> httpx.Response:   # never asked: the extraction is reused
    raise AssertionError("the extractor was called; the extraction must be held fixed")


@functools.cache
def build(case: str, arm: str, pad: int = 0) -> dict[str, Any]:
    """One pipeline run; what it sent, the payload it built and the store it held."""
    docs, reuse = _corpus(case, pad)
    cloud = Cloud()
    seen: dict[str, Any] = {}

    class Planner(P.MacroPlanner):
        async def plan(self, payload, goal):  # type: ignore[no-untyped-def]
            seen["payload"] = payload
            return await super().plan(payload, goal)

    def store(docs_, table):  # type: ignore[no-untyped-def]
        seen["store"] = real_store(docs_, table)
        return seen["store"]

    real_store = P.build_fact_store
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("SHINGLE_HMAC_SALT", GW_SALT.decode())
        mp.setattr(P, "MacroPlanner", Planner)
        mp.setattr(P, "build_fact_store", store)
        res = asyncio.run(P.run_pipeline(
            docs, GOAL,
            slm=AsyncSLMClient("http://local-slm:11434", model="qwen3:14b",
                               transport=httpx.MockTransport(_slm)),
            cloud=CloudClient(GW, transport=httpx.MockTransport(cloud)),
            gateway_url=GW, evidence=EvidenceBank(),
            gw_client=httpx.Client(transport=httpx.MockTransport(cloud)),
            session_salt=SALT, run_id=f"g2-{case}-{arm}", arm=arm, reuse_extraction=reuse))
    assert res.sections_ok == 3 and res.sections_refused == 0
    assert cloud.plan is not None and len(cloud.drafts) == 3
    return {"docs": docs, "payload": seen["payload"], "store": seen.get("store"),
            "plan": cloud.plan, "drafts": cloud.drafts}


# --------------------------------------------------------------------- canonical form


def canonical(artifacts: dict[str, Any], issued: list[str]) -> dict[str, str]:
    """Rename issued ids by what they do, and sort the listings their hex ordered.

    `artifacts` maps a channel to a string (payload JSON) or to a request body
    or a list of them. Only issued ids are renamed: the drafter's constant
    example ids are not the corpus's and stay as they are.
    """
    def texts(obj: Any) -> list[str]:
        if isinstance(obj, str):
            return [obj]
        if isinstance(obj, list):
            return [t for o in obj for t in texts(o)]
        return [json.dumps(obj, ensure_ascii=False, sort_keys=True)]

    units = [t for ch in CHANNELS for t in texts(artifacts[ch])]
    hexes = {sid: SLOT_RE.fullmatch(sid).group("hex") for sid in issued}
    sig = {sid: tuple(u.count(sid) + u.count(f"⟦FACT:{hexes[sid]}.") for u in units)
           for sid in issued}
    names: dict[str, str] = {}
    for cat in sorted({SLOT_RE.fullmatch(s).group("category") for s in issued}):
        ids = sorted((s for s in issued if SLOT_RE.fullmatch(s).group("category") == cat),
                     key=lambda s: sig[s])
        names.update({s: f"{cat}#{i}" for i, s in enumerate(ids)})

    def rename(text: str) -> str:
        for sid, name in names.items():
            text = text.replace(sid, f"⟦SLOT:{name}⟧").replace(f"⟦FACT:{hexes[sid]}.",
                                                               f"⟦FACT:{name}.")
        lines, out, run = text.split("\n"), [], []
        for ln in lines:
            if re.search(r"⟦SLOT:[A-Z]+#\d+⟧", ln):
                run.append(ln)
                continue
            out += sorted(run) + [ln]
            run = []
        return "\n".join(out + sorted(run))

    def body(b: dict) -> str:
        b = json.loads(json.dumps(b))
        b["system"] = rename(b["system"]) if isinstance(b.get("system"), str) else b.get("system")
        for m in b["messages"]:
            m["content"] = rename(m["content"])
        return json.dumps(b, ensure_ascii=False, sort_keys=True, indent=1)

    payload = json.loads(artifacts["payload_json"])
    payload["slots"] = sorted(({"id": rename(s["id"]), "category": s["category"]}
                               for s in payload["slots"]), key=lambda s: s["id"])
    return {"payload_json": json.dumps(payload, ensure_ascii=False, indent=2),
            "planner_request": body(artifacts["planner_request"]),
            "drafter_requests": "\n".join(body(b) for b in artifacts["drafter_requests"])}


def channels(case: str, arm: str, pad: int = 0) -> dict[str, str]:
    b = build(case, arm, pad)
    return canonical({"payload_json": b["payload"].to_json(), "planner_request": b["plan"],
                      "drafter_requests": b["drafts"]},
                     [sid for sid, _ in b["payload"].slots])


# --------------------------------------------------------------------- G2

# Until 2026-09-27 twelve of these were strict xfails naming the exact character
# count (amounts and site; payload JSON and planner request; every arm). The count
# now crosses rounded to 1,000 and they pass; see the module docstring.
@pytest.mark.parametrize(("case", "arm", "channel"),
                         [pytest.param(case, arm, ch, id=f"{case}-{arm}-{ch}")
                          for case in CASES for arm in ARMS for ch in CHANNELS])
def test_the_core_built_payload_and_prompts_are_invariant(case, arm, channel):
    assert channels(case, arm)[channel] == channels("original", arm)[channel]


def _without_chars(text: str) -> str:
    text = re.sub(r"about \d+ characters", "about N characters", text)
    return re.sub(r'"chars": \d+', '"chars": N', text)


@pytest.mark.parametrize("arm", ARMS)
@pytest.mark.parametrize("case", ["amounts", "site"])
def test_the_exact_count_still_moves_and_only_the_coarse_one_crosses(case, arm):
    """Not vacuous: the local exact count differs under these two cases, so the
    equality above is the quantum's doing. The wire carries 3000, never the exact."""
    before, after = (build(c, arm)["payload"] for c in ("original", case))
    assert (before.n_chars, after.n_chars) == (3479, {"amounts": 3482, "site": 3476}[case])
    ours = channels(case, arm)
    assert '"chars": 3000' in ours["payload_json"]
    assert "about 3000 characters (to the nearest 1000)." in ours["planner_request"]
    for ch in CHANNELS:
        assert not re.search(r"\b34(79|82|76)\b", ours[ch]), ch


@pytest.mark.parametrize("case", list(CASES))
def test_no_tested_permutation_moves_the_cell_or_block_count(case):
    for arm in ARMS:
        before, after = (build(c, arm)["payload"] for c in ("original", case))
        assert (after.n_cells, after.n_blocks) == (before.n_cells, before.n_blocks) == (60, 15)


# Corpus A plus this many spaces is 3497; `amounts` adds three and reaches 3500.
PAD = 18


@pytest.mark.parametrize("arm", ARMS)
def test_a_change_across_a_quantum_boundary_remains_visible(arm):
    """The stated limit, constructed. Quantisation is not invariance: the same
    `amounts` permutation, on a corpus 3 characters below the 3500 boundary, moves
    the wire value from 3000 to 4000, and that is the only thing it moves."""
    before, after = (build(c, arm, PAD)["payload"].n_chars for c in ("original", "amounts"))
    assert (before, after) == (3497, 3500)
    ours, base = channels("amounts", arm, PAD), channels("original", arm, PAD)
    assert '"chars": 3000' in base["payload_json"] and '"chars": 4000' in ours["payload_json"]
    assert "about 3000 characters" in base["planner_request"]
    assert "about 4000 characters" in ours["planner_request"]
    assert ours["payload_json"] != base["payload_json"]
    assert ours["planner_request"] != base["planner_request"]
    for ch in CHANNELS:
        assert _without_chars(ours[ch]) == _without_chars(base[ch]), ch


# Measured 2026-09-27 (C on 2026-09-30), as the pipeline counts: sum of len(d.text) over
# the loaded documents. The distance to the nearest rounding boundary (x500) is how many
# characters a permutation must add or remove to change what crosses.
CORPUS_CHARS = {"smoke-q3": (3479, 3000, 21), "portfolio-b": (3576, 4000, 76),
                "prose-c": (3014, 3000, 486), "offlex-d": (3693, 4000, 193)}


@pytest.mark.parametrize("corpus", list(CORPUS_CHARS))
def test_each_corpus_size_and_its_distance_to_a_quantum_boundary(corpus):
    d = REPO / "eval" / "corpora" / corpus
    n = sum(len(load(p).text) for p in sorted(d.iterdir()) if p.suffix.lower() in SUFFIXES)
    exact, wire, distance = CORPUS_CHARS[corpus]
    assert (n, coarse_chars(n)) == (exact, wire)
    assert min(abs(n - b) for b in range(500, 10_000, 1000)) == distance


@pytest.mark.parametrize("arm", ARMS)
def test_the_renaming_is_exercised(arm):
    """Under the site swap the issued ids change, so the raw requests differ and only
    the canonical forms agree; equality is not an accident of an unchanged salt."""
    site, base = build("site", arm), build("original", arm)
    assert {s for s, _ in site["payload"].slots} != {s for s, _ in base["payload"].slots}
    assert json.dumps(site["drafts"]) != json.dumps(base["drafts"])
    assert channels("site", arm)["drafter_requests"] == channels("original", arm)[
        "drafter_requests"]


def test_the_document_ids_are_on_no_request():
    """doc_id is a hash of the file bytes and a permuted file would change it; it is
    in the payload JSON only, which no request carries."""
    for arm in ARMS:
        b = build("original", arm)
        sent = json.dumps([b["plan"], *b["drafts"]], ensure_ascii=False)
        assert all(d.doc_id not in sent for d in b["docs"])


# --------------------------------------------------------------------- not vacuous


def _facts(store: LocalFactStore) -> dict[tuple[str, str], str]:
    return {(f.referent, f.attribute): f.value_key for f in store.facts()}


@pytest.mark.parametrize(("case", "attrs"), [("amounts", {"AUTHAMT", "SPENTAMT"}),
                                             ("rows", {"AUTHAMT", "OWNERREF", "SITEREF"}),
                                             ("site", {"SITEREF"})])
def test_each_permutation_moves_values_between_referents(case, attrs):
    """The local store holds the permuted binding, so equality above is not for want
    of a change: a referent's value for these attributes differs."""
    before, after = (_facts(build(c, "r1")["store"]) for c in ("original", case))
    changed = {a for (r, a), v in before.items() if after.get((r, a)) not in (None, v)}
    assert attrs <= changed
    assert [d.text for d in build(case, "r1")["docs"]] != [d.text for d in _docs()]


def test_the_permuted_documents_keep_their_structure():
    for case in CASES:
        for d0, d1 in zip(_docs(), build(case, "r5")["docs"], strict=True):
            assert (len(d0.cells), len(d0.blocks)) == (len(d1.cells), len(d1.blocks))
            assert all(c.span.slice(d1.text) == c.value for c in d1.cells)


def test_the_amount_permutation_is_a_bijection_on_what_the_documents_spell():
    sub = CASES["amounts"]()
    spelled = Counter(m.group(0) for d in _docs() for m in _NUMBER.finditer(d.text))
    images = {s: _apply(s, sub(s))[0] for s in spelled}
    moved = {s: t for s, t in images.items() if s != t}
    assert len(moved) >= 8
    assert len(set(images.values())) == len(images)


class TestCanonicalForm:
    """The renaming must not hide a difference: controls on synthetic listings."""

    A, B, C = ("⟦SLOT:PROJECT_11111111⟧", "⟦SLOT:PROJECT_22222222⟧", "⟦SLOT:PERSON_33333333⟧")

    def form(self, plan: str, drafts: list[str], ids: list[str]) -> dict[str, str]:
        payload = json.dumps({"slots": [{"id": s, "category": s[7:].split("_")[0]}
                                        for s in sorted(ids)]})
        req = lambda t: {"system": "S", "messages": [{"role": "user", "content": t}]}  # noqa: E731
        return canonical({"payload_json": payload, "planner_request": req(plan),
                          "drafter_requests": [req(t) for t in drafts]}, ids)

    def test_relabelled_and_reordered_is_equal(self):
        x = self.form(f"- {self.A}  [PROJECT]\n- {self.B}  [PROJECT]", [f"- {self.A}  [PROJECT]"],
                      [self.A, self.B])
        y = self.form(f"- {self.B}  [PROJECT]\n- {self.A}  [PROJECT]", [f"- {self.B}  [PROJECT]"],
                      [self.A, self.B])
        assert x == y

    def test_a_different_incidence_is_not_equal(self):
        x = self.form(f"- {self.A}  [PROJECT]\n- {self.B}  [PROJECT]", [f"- {self.A}  [PROJECT]"],
                      [self.A, self.B])
        y = self.form(f"- {self.A}  [PROJECT]\n- {self.B}  [PROJECT]",
                      [f"- {self.A}  [PROJECT]\n- {self.B}  [PROJECT]"], [self.A, self.B])
        assert x != y

    def test_a_different_category_is_not_equal(self):
        x = self.form(f"- {self.A}  [PROJECT]", [f"- {self.A}  [PROJECT]"], [self.A])
        y = self.form(f"- {self.C}  [PERSON]", [f"- {self.C}  [PERSON]"], [self.C])
        assert x != y

    def test_a_fact_stem_follows_its_slot(self):
        x = self.form(f"- {self.A}  [PROJECT]", [f"- {self.A} facts: ⟦FACT:11111111.<ATTR>⟧"],
                      [self.A])
        assert "⟦FACT:PROJECT#0.<ATTR>⟧" in x["drafter_requests"]
