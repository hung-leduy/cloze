"""Unit tests for SlotMasker: the W2 gate is that mask/restore is character-exact.

Every scenario goes through `roundtrip`, which asserts the equality the gate is
named for plus the structural invariants the module docstring argues from:
claimed spans are disjoint, each slices back to its entity's text, the table
holds exactly the placeholders present in the masked text, and nothing in the
table is printable through `repr`.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from privdeep.models.document import SLOT_CATEGORIES, Cell, Document, DocumentKind, Span
from privdeep.tier1_local.slot_masker import (
    SLOT_RE,
    Entity,
    LocalMappingTable,
    MaskResult,
    SlotCollisionError,
    SlotMasker,
)

SALT = b"unit-test-session-salt"
OTHER_SALT = b"a-different-session"

LAN = Entity("Nguyễn Thị Lan", "PERSON")
ZEPHYR = Entity("Zephyr", "PROJECT")
PROJECT_ZEPHYR = Entity("Project Zephyr", "PROJECT")
HANOI = Entity("Hanoi", "LOCATION")
ACME = Entity("Acme Logistics", "ORG")


def make_doc(text: str, kind: DocumentKind = DocumentKind.MARKDOWN, **kw) -> Document:
    return Document(doc_id="t", kind=kind, source_path=Path("/dev/null"), text=text, **kw)


def roundtrip(doc: Document, entities: list[Entity], salt: bytes = SALT) -> MaskResult:
    """Mask, then restore, then check every invariant the gate depends on."""
    masker = SlotMasker(salt)
    res = masker.mask(doc, entities)

    # The gate.
    assert masker.restore(res) == doc.text

    # Replacements are ascending, disjoint, and each slices back to the exact
    # spelling recorded at that occurrence -- `surface`, not `original`: under
    # R5 `original` is the canonical rendering, which may be a different one of
    # the referent's spellings.
    prev_end = 0
    for span, slot, ix in res.replacements:
        assert span.start >= prev_end, "claimed spans overlap or are unsorted"
        assert span.slice(doc.text) == res.table.surface(slot, ix)
        assert SLOT_RE.fullmatch(slot)
        prev_end = span.end

    # The table holds exactly the distinct placeholders in the masked text.
    in_text = {m.group(0) for m in SLOT_RE.finditer(res.masked_text)}
    assert in_text == set(res.table)
    assert len(res.table) == len(in_text)
    assert all(s in res.table for s in in_text)

    # Nothing in the table is printable through repr.
    r = repr(res.table)
    for slot in res.table:
        assert res.table.original(slot) not in r

    # Unmatched entities were never issued a placeholder. (Their text may still
    # be in the table under another category; the slot id is what is checked.)
    for e in res.unmatched:
        assert LocalMappingTable(salt).slot_for(e) not in res.table
    return res


class TestSlotIdFormat:
    def test_slot_re_matches_exact_shape_only(self):
        good = "⟦SLOT:PERSON_1a2b3c4d⟧"
        m = SLOT_RE.fullmatch(good)
        assert m and m.group("category") == "PERSON" and m.group("hex") == "1a2b3c4d"
        for bad in (
            "⟦SLOT:PERSON_1a2b3c4⟧",  # 7 hex
            "⟦SLOT:PERSON_1a2b3c4d5⟧",  # 9 hex
            "⟦SLOT:PERSON_1A2B3C4D⟧",  # uppercase hex
            "⟦SLOT:person_1a2b3c4d⟧",  # lowercase category
            "[SLOT:PERSON_1a2b3c4d]",  # wrong brackets
            "⟦SLOT:PERSON-1a2b3c4d⟧",  # wrong separator
            "⟦SLOT:_1a2b3c4d⟧",  # empty category
        ):
            assert SLOT_RE.search(bad) is None, bad

    def test_id_is_category_plus_eight_hex(self):
        res = SlotMasker(SALT).mask(make_doc("x Hanoi y"), [HANOI])
        (_, slot, _ix), = res.replacements
        m = SLOT_RE.fullmatch(slot)
        assert m and m.group("category") == "LOCATION" and len(m.group("hex")) == 8

    def test_same_entity_under_two_salts_gives_different_ids(self):
        a = LocalMappingTable(SALT).slot_for(HANOI)
        b = LocalMappingTable(OTHER_SALT).slot_for(HANOI)
        assert a != b
        assert a.startswith("⟦SLOT:LOCATION_") and b.startswith("⟦SLOT:LOCATION_")

    def test_same_entity_same_salt_is_deterministic_across_tables_and_calls(self):
        assert LocalMappingTable(SALT).slot_for(LAN) == LocalMappingTable(SALT).slot_for(LAN)
        doc = make_doc("Nguyễn Thị Lan met Nguyễn Thị Lan.")
        m = SlotMasker(SALT)
        assert m.mask(doc, [LAN]).masked_text == m.mask(doc, [LAN]).masked_text

    def test_two_different_entities_never_collide(self):
        t = LocalMappingTable(SALT)
        ids = {t.slot_for(e) for e in (LAN, ZEPHYR, PROJECT_ZEPHYR, HANOI, ACME)}
        assert len(ids) == 5
        # Same text, different category: still distinct, because the category is
        # both in the HMAC input and in the visible prefix.
        assert t.slot_for(Entity("Zephyr", "ORG")) != t.slot_for(ZEPHYR)


class TestConstruction:
    def test_invalid_category_raises(self):
        with pytest.raises(ValueError, match="unknown slot category"):
            Entity("Lan", "NAME")
        with pytest.raises(ValueError):
            Entity("Lan", "person")  # case matters; the taxonomy is uppercase

    def test_every_taxonomy_category_is_accepted(self):
        for c in SLOT_CATEGORIES:
            assert Entity("x", c).category == c

    def test_empty_entity_text_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            Entity("", "PERSON")

    def test_empty_salt_raises(self):
        with pytest.raises(ValueError):
            SlotMasker(b"")
        with pytest.raises(ValueError):
            LocalMappingTable(b"")

    def test_entity_repr_hides_text(self):
        assert "Nguyễn" not in repr(LAN)
        assert "PERSON" in repr(LAN)


class TestMaskingScenarios:
    def test_vietnamese_entity_with_diacritics(self):
        doc = make_doc("Bà Nguyễn Thị Lan phụ trách dự án tại Hà Nội.")
        res = roundtrip(doc, [LAN])
        assert "Nguyễn Thị Lan" not in res.masked_text
        assert res.masked_text.startswith("Bà ⟦SLOT:PERSON_")
        assert res.masked_text.endswith("⟧ phụ trách dự án tại Hà Nội.")
        assert res.unmatched == []

    def test_entity_appearing_three_times_gets_one_slot(self):
        doc = make_doc("Hanoi. Then Hanoi again, and finally Hanoi.")
        res = roundtrip(doc, [HANOI])
        assert len(res.replacements) == 3
        slots = {s for _, s, _ in res.replacements}
        assert len(slots) == 1
        assert len(res.table) == 1
        assert res.masked_text.count(next(iter(slots))) == 3
        assert "Hanoi" not in res.masked_text

    def test_nested_entity_longest_wins_and_short_still_masked_alone(self):
        doc = make_doc("Project Zephyr slipped; Zephyr was cancelled.")
        res = roundtrip(doc, [ZEPHYR, PROJECT_ZEPHYR])  # short one listed first on purpose
        by_slot = {}
        for span, slot, _ix in res.replacements:
            by_slot.setdefault(res.table.original(slot), []).append(span)
        assert by_slot["Project Zephyr"] == [Span(0, 14)]
        assert by_slot["Zephyr"] == [Span(24, 30)]
        assert len(res.table) == 2
        assert res.unmatched == []
        assert "Zephyr" not in res.masked_text

    def test_fully_shadowed_entity_is_unmatched_and_not_in_table(self):
        doc = make_doc("Only Project Zephyr appears here.")
        res = roundtrip(doc, [PROJECT_ZEPHYR, ZEPHYR])
        assert res.unmatched == [ZEPHYR]
        assert len(res.table) == 1
        assert len(res.replacements) == 1

    def test_adjacent_entities_with_no_gap(self):
        doc = make_doc("ZephyrHanoi report")
        res = roundtrip(doc, [ZEPHYR, HANOI])
        assert [sp for sp, _, _ in res.replacements] == [Span(0, 6), Span(6, 11)]
        z = res.table.slot_for(ZEPHYR)
        h = res.table.slot_for(HANOI)
        assert res.masked_text == f"{z}{h} report"

    def test_entity_absent_from_text_lands_in_unmatched(self):
        doc = make_doc("Nothing relevant here.")
        res = roundtrip(doc, [LAN, HANOI])
        assert res.unmatched == [LAN, HANOI]
        assert res.replacements == []
        assert len(res.table) == 0
        assert res.masked_text == doc.text

    def test_case_sensitive_exact_match(self):
        doc = make_doc("hanoi is not Hanoi; HANOI is not either.")
        res = roundtrip(doc, [HANOI])
        assert len(res.replacements) == 1
        assert res.replacements[0][0] == Span(13, 18)

    def test_same_text_two_categories_first_wins_second_unmatched(self):
        doc = make_doc("Zephyr, Zephyr.")
        as_org = Entity("Zephyr", "ORG")
        res = roundtrip(doc, [as_org, ZEPHYR])
        assert res.unmatched == [ZEPHYR]
        assert all(s.startswith("⟦SLOT:ORG_") for _, s, _ in res.replacements)

    def test_duplicate_entities_in_input_are_harmless(self):
        doc = make_doc("Hanoi and Hanoi.")
        res = roundtrip(doc, [HANOI, HANOI, Entity("Hanoi", "LOCATION")])
        assert len(res.replacements) == 2
        assert len(res.table) == 1
        assert res.unmatched == []

    def test_equal_length_overlap_resolved_by_caller_order(self):
        doc = make_doc("Lan Anh Lee")
        first = Entity("Lan Anh", "PERSON")  # 7 chars
        second = Entity("Anh Lee", "PERSON")  # 7 chars, overlapping at "Anh"
        assert len(first.text) == len(second.text)
        res = roundtrip(doc, [first, second])
        assert res.replacements[0][0] == Span(0, 7)
        assert res.unmatched == [second]
        res2 = roundtrip(doc, [second, first])
        assert res2.replacements[0][0] == Span(4, 11)
        assert res2.unmatched == [first]

    def test_replacements_are_in_text_order_regardless_of_entity_order(self):
        doc = make_doc("Hanoi, Zephyr, Acme Logistics, Hanoi")
        res = roundtrip(doc, [ACME, HANOI, ZEPHYR])
        starts = [sp.start for sp, _, _ in res.replacements]
        assert starts == sorted(starts)
        assert len(res.replacements) == 4


class TestXlsxStyleDocument:
    """The tabular serialisation: one row per line, cells joined by a tab."""

    def build(self) -> tuple[Document, list[Entity]]:
        header = "# Sheet: Q3\n"
        rows = [
            ["Owner", "Project", "Site", "Budget"],
            ["Nguyễn Thị Lan", "Project Zephyr", "Hanoi", "1200000"],
            ["Trần Văn Minh", "Zephyr", "Hanoi", "350000"],
        ]
        lines = ["\t".join(r) for r in rows]
        text = header + "\n".join(lines) + "\n"
        cells: list[Cell] = []
        pos = len(header)
        for r_idx, row in enumerate(rows, start=1):
            for c_idx, value in enumerate(row, start=1):
                cells.append(Cell("Q3", r_idx, c_idx, value, Span(pos, pos + len(value))))
                pos += len(value) + 1  # the tab, or the newline after the last cell
        doc = make_doc(text, kind=DocumentKind.XLSX, cells=cells)  # validates cell spans
        ents = [
            LAN,
            Entity("Trần Văn Minh", "PERSON"),
            PROJECT_ZEPHYR,
            ZEPHYR,
            HANOI,
            Entity("1200000", "MONEY"),
            Entity("350000", "MONEY"),
        ]
        return doc, ents

    def test_roundtrip_is_exact_and_structure_survives(self):
        doc, ents = self.build()
        res = roundtrip(doc, ents)
        assert res.unmatched == []
        assert res.masked_text.startswith("# Sheet: Q3\nOwner\tProject\tSite\tBudget\n")
        # Row structure is intact: same number of lines, same number of tabs per line.
        assert res.masked_text.count("\n") == doc.text.count("\n")
        for a, b in zip(doc.text.splitlines(), res.masked_text.splitlines(), strict=True):
            assert a.count("\t") == b.count("\t")
        # Hanoi appears twice, one slot; both money cells masked with distinct slots.
        assert len(res.table) == 7
        assert len(res.replacements) == 8
        assert "Hanoi" not in res.masked_text
        assert "1200000" not in res.masked_text and "350000" not in res.masked_text

    def test_no_word_boundary_is_enforced(self):
        """Documented limit: matching is exact substring, so the extractor is trusted."""
        doc = make_doc("Landau\tLan\n")
        res = roundtrip(doc, [Entity("Lan", "PERSON")])
        assert len(res.replacements) == 2  # inside 'Landau' too


class TestFailClosed:
    def test_restore_with_unknown_slot_raises_key_error(self):
        masker = SlotMasker(SALT)
        res = masker.mask(make_doc("Hanoi."), [HANOI])
        invented = "⟦SLOT:PERSON_00000000⟧"
        assert invented not in res.table
        with pytest.raises(KeyError):
            masker.restore(replace(res, masked_text=res.masked_text + " " + invented))
        # A slot-shaped string with a category outside the taxonomy is still refused.
        with pytest.raises(KeyError):
            masker.restore(replace(res, masked_text="⟦SLOT:PERSONS_1a2b3c4d⟧",
                                   replacements=[]))

    def test_restore_against_a_foreign_table_raises(self):
        doc = make_doc("Hanoi.")
        res = SlotMasker(SALT).mask(doc, [HANOI])
        foreign = SlotMasker(OTHER_SALT).mask(doc, [HANOI]).table
        with pytest.raises(KeyError):
            SlotMasker(SALT).restore(replace(res, table=foreign))

    def test_document_already_containing_a_placeholder_is_refused(self):
        doc = make_doc("see ⟦SLOT:ORG_deadbeef⟧ for details")
        with pytest.raises(ValueError, match="slot-shaped"):
            SlotMasker(SALT).mask(doc, [HANOI])

    def test_marker_fragments_next_to_a_placeholder_cannot_fuse_into_one(self):
        """Rule 2 of the exactness argument: text that is *almost* a placeholder,
        butted right up against a real one, must not change what SLOT_RE sees."""
        doc = make_doc(
            "⟦SLOT:ORG_Hanoi⟧ | ⟦SLOT:ORG_1234abcHanoi | ⟦SLOT:ORG_1234abcdHanoi | Hanoi⟧ | Hanoi_"
        )
        assert SLOT_RE.search(doc.text) is None  # passes the mask-time guard
        res = roundtrip(doc, [HANOI])
        assert len(res.replacements) == 5
        assert len(list(SLOT_RE.finditer(res.masked_text))) == 5

    def test_table_original_unknown_raises_key_error(self):
        with pytest.raises(KeyError):
            LocalMappingTable(SALT).original("⟦SLOT:ORG_deadbeef⟧")

    def test_hex8_collision_is_refused_not_overwritten(self):
        # Found by brute force offline: under this salt, both texts hash to
        # eb630f76 in category PERSON. Pinning a real pair keeps the test
        # deterministic and instant.
        salt = b"collision-search-salt"
        a = Entity("person-60384", "PERSON")
        b = Entity("person-75979", "PERSON")
        t = LocalMappingTable(salt)
        slot_a = t.slot_for(a)
        assert slot_a.endswith("_eb630f76⟧")
        with pytest.raises(SlotCollisionError):
            t.slot_for(b)
        assert t.original(slot_a) == a.text  # the first binding is untouched
        # Through the public API the whole mask call fails, never a wrong table.
        doc = make_doc("person-60384 and person-75979")
        with pytest.raises(SlotCollisionError):
            SlotMasker(salt).mask(doc, [a, b])
        # The remedy the error message names works: a fresh salt.
        assert SlotMasker(SALT).mask(doc, [a, b]).unmatched == []



class TestOneSlotPerReferent:
    """R5: spellings of one referent merge; different referents never do.

    `roundtrip` runs the W2 gate on every case here, so each of these also
    asserts that merging did not cost character-exact restore -- which is the
    whole risk of keying on a canonical form instead of the text.
    """

    def test_three_spellings_of_one_amount_share_a_slot(self):
        doc = make_doc("Budget 250,000.00 USD; authorised 250,000; cell 250000.")
        res = roundtrip(doc, [Entity("250,000.00", "MONEY"), Entity("250,000", "MONEY"),
                              Entity("250000", "MONEY")])
        assert len(res.table) == 1, "one amount must be one referent"
        assert len({s for _, s, _ in res.replacements}) == 1
        assert len(res.replacements) == 3
        assert res.unmatched == []

    def test_each_occurrence_keeps_its_own_spelling(self):
        doc = make_doc("Budget 250,000.00 USD; authorised 250,000; cell 250000.")
        res = roundtrip(doc, [Entity("250,000.00", "MONEY"), Entity("250,000", "MONEY"),
                              Entity("250000", "MONEY")])
        got = [res.table.surface(sid, ix) for _sp, sid, ix in res.replacements]
        assert got == ["250,000.00", "250,000", "250000"]

    def test_the_canonical_rendering_is_an_observed_spelling(self):
        doc = make_doc("Budget 250,000.00 USD; authorised 250,000; cell 250000.")
        res = roundtrip(doc, [Entity("250,000.00", "MONEY"), Entity("250,000", "MONEY"),
                              Entity("250000", "MONEY")])
        (sid,) = set(res.table)
        # Never a re-formatted key: reintegration may only print text the user
        # actually wrote, or the fidelity component becomes a fabrication path.
        assert res.table.original(sid) in res.table.surfaces(sid)
        assert res.table.original(sid) == "250,000.00"

    def test_fragmentation_reports_referents_holding_several_spellings(self):
        doc = make_doc("Budget 250,000.00 and 250000, plus Hanoi.")
        res = roundtrip(doc, [Entity("250,000.00", "MONEY"), Entity("250000", "MONEY"),
                              HANOI])
        assert res.table.fragmentation() == {"MONEY": 1}

    def test_an_xlsx_date_cell_and_its_prose_spelling_share_a_slot(self):
        doc = make_doc("Start 2026-06-01T00:00:00 in the sheet, 1 June 2026 in the memo.")
        res = roundtrip(doc, [Entity("2026-06-01T00:00:00", "DATE"),
                              Entity("1 June 2026", "DATE")])
        assert len(res.table) == 1

    def test_two_different_amounts_are_two_referents(self):
        doc = make_doc("Authorised 250,000.00 against spend of 187,432.55.")
        res = roundtrip(doc, [Entity("250,000.00", "MONEY"), Entity("187,432.55", "MONEY")])
        assert len(res.table) == 2

    def test_a_truncated_figure_is_not_merged_with_the_real_one(self):
        # The six-significant-figure join the design asked for, declined. See
        # tier1_local/normalise.py; keeping it would merge two real amounts.
        doc = make_doc("The sheet said 187433 but the true figure is 187,432.55.")
        res = roundtrip(doc, [Entity("187433", "MONEY"), Entity("187,432.55", "MONEY")])
        assert len(res.table) == 2

    def test_nested_project_names_remain_two_referents(self):
        doc = make_doc("Project Zephyr slipped; Zephyr was cancelled.")
        res = roundtrip(doc, [ZEPHYR, PROJECT_ZEPHYR])
        assert len(res.table) == 2, "alias merging would write the wrong name into a report"

    def test_a_merge_is_not_mistaken_for_a_hash_collision(self):
        """The predicate is the canonical key, not the Entity.

        Entity equality includes its text, so comparing entities would make the
        first successful merge raise. `pipeline.py` re-salts once and then
        raises, so this would abort every run over a document that spells an
        amount two ways -- which is every document.
        """
        t = LocalMappingTable(SALT)
        a = t.slot_for(Entity("250,000.00", "MONEY"))
        b = t.slot_for(Entity("250000", "MONEY"))  # must not raise
        assert a == b and len(t) == 1

    def test_surface_index_out_of_range_fails_closed(self):
        t = LocalMappingTable(SALT)
        sid = t.slot_for(HANOI)
        with pytest.raises(KeyError):
            t.surface(sid, 7)

class TestBaselineArm:
    """`normalise=False` reproduces the pre-R5 behaviour from the same code.

    The BASELINE arm has to come from this switch rather than from an old
    commit: an arm that must be recovered by checking out a different tree is an
    arm nobody re-runs, and comparing two differently-built binaries measures the
    build rather than the change.
    """

    def test_baseline_keys_on_the_raw_text_so_spellings_do_not_merge(self):
        doc = make_doc("Budget 250,000.00 USD; authorised 250,000; cell 250000.")
        ents = [Entity("250,000.00", "MONEY"), Entity("250,000", "MONEY"),
                Entity("250000", "MONEY")]
        base = SlotMasker(SALT, normalise=False).mask(doc, ents)
        assert len(base.table) == 3, "pre-R5 behaviour: one slot per spelling"
        assert len(SlotMasker(SALT).mask(doc, ents).table) == 1

    def test_the_gate_still_holds_under_the_baseline_arm(self):
        doc = make_doc("Budget 250,000.00 USD; authorised 250,000; cell 250000.")
        masker = SlotMasker(SALT, normalise=False)
        res = masker.mask(doc, [Entity("250,000.00", "MONEY"), Entity("250,000", "MONEY"),
                                Entity("250000", "MONEY")])
        assert masker.restore(res) == doc.text

    def test_the_two_arms_issue_different_ids_for_the_same_entity(self):
        e = Entity("250,000.00", "MONEY")
        assert (LocalMappingTable(SALT, normalise=False).slot_for(e)
                != LocalMappingTable(SALT).slot_for(e))


class TestTableHygiene:
    def test_repr_contains_counts_only(self):
        doc = make_doc("Nguyễn Thị Lan, Hanoi, Acme Logistics, Zephyr")
        res = SlotMasker(SALT).mask(doc, [LAN, HANOI, ACME, ZEPHYR])
        r = repr(res.table)
        assert r == "LocalMappingTable(slots=4, PERSON=1, ORG=1, PROJECT=1, LOCATION=1)"
        for e in (LAN, HANOI, ACME, ZEPHYR):
            assert e.text not in r
        assert repr(LocalMappingTable(SALT)) == "LocalMappingTable(slots=0, empty)"

    def test_len_contains_iter(self):
        t = LocalMappingTable(SALT)
        assert len(t) == 0
        s = t.slot_for(HANOI)
        assert len(t) == 1 and s in t and "nope" not in t
        assert list(t) == [s]
        assert t.slot_for(HANOI) == s and len(t) == 1  # idempotent


class TestManyEntitiesRoundTrip:
    def test_large_deterministic_mix(self):
        """Many entities, many occurrences, nesting, adjacency, tabs and newlines."""
        people = [f"Người {i}" for i in range(20)]
        orgs = [f"Công ty {i}" for i in range(15)]
        places = ["Hà Nội", "Đà Nẵng", "TP. Hồ Chí Minh"]
        lines = []
        for i in range(60):
            p = people[i % len(people)]
            o = orgs[i % len(orgs)]
            loc = places[i % len(places)]
            # Prefix nesting: "Người 1" inside "Người 10"..."Người 19".
            lines.append(f"{p}\t{o}\t{loc}\t{p}{loc}\t{o} {loc} {p}")
        text = "\n".join(lines) + "\n"
        doc = make_doc(text, kind=DocumentKind.XLSX)
        ents = (
            [Entity(p, "PERSON") for p in people]
            + [Entity(o, "ORG") for o in orgs]
            + [Entity(loc, "LOCATION") for loc in places]
        )
        res = roundtrip(doc, ents)
        assert res.unmatched == []
        assert len(res.table) == len(ents)
        # Nothing an entity was named survives outside a placeholder.
        stripped = SLOT_RE.sub("", res.masked_text)
        for e in ents:
            assert e.text not in stripped
