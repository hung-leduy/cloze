"""Unit tests for the faithfulness metric.

The gate this file exists for is `TestPermutationSensitivity`. The design
rejected sentence-level co-occurrence by measuring that it emits byte-identical
output when the values in a sentence are permuted, and permutation inside one
sentence is the exact failure the first live run produced. Any future
simplification of the binding rule has to keep failing that permutation, so it
is pinned here rather than left as a paragraph in a design document.

The key under test is the real one, imported from the corpus generator, because
a key written for the tests could drift from the corpus and would prove nothing
about the instrument that is actually run.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from privdeep.eval.faithfulness import (
    AMBIGUOUS,
    CORRECT,
    FABRICATED,
    MATCH,
    MISBOUND,
    MISMATCH,
    PARTIAL,
    UNRESOLVED,
    FactKey,
    de_escape,
    score,
)

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts" / "make_smoke_corpus.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("make_smoke_corpus", _SCRIPTS)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def key() -> FactKey:
    raw = _load_generator().fact_key()
    return FactKey(
        referents=raw["referents"],
        attributes={k: v["lexicon"] for k, v in raw["attributes"].items()},
        facts=raw["facts"], string_facts=raw["string_facts"],
        mask_patterns=raw["mask_patterns"],
    )


def verdicts(text: str, key: FactKey) -> list[tuple[str, str]]:
    return [(o.surface, o.verdict) for o in score(text, key).occurrences]


TRUE = ("Of the 250,000.00 USD authorised for Project Zephyr, 187,432.55 USD had "
        "been committed, leaving 62,567.45 USD uncommitted.")
PERMUTED = ("Of the 62,567.45 USD authorised for Project Zephyr, 250,000.00 USD had "
            "been committed, leaving 187,432.55 USD uncommitted.")


class TestPermutationSensitivity:
    """The property that disqualified sentence-level scoring."""

    def test_true_sentence_is_all_correct(self, key):
        res = score(TRUE, key)
        assert [o.verdict for o in res.occurrences] == [CORRECT, CORRECT, CORRECT]
        assert res.rba == 1.0

    def test_permuting_the_values_is_detected(self, key):
        res = score(PERMUTED, key)
        assert all(o.verdict == MISBOUND for o in res.occurrences)
        assert res.rba == 0.0

    def test_output_is_not_permutation_invariant(self, key):
        assert verdicts(TRUE, key) != verdicts(PERMUTED, key)

    def test_attribute_is_bound_per_clause_not_per_sentence(self, key):
        # The whole reason for clause scoping: 187,432.55 sits 2 characters
        # after "authorised" and 14 before "committed", so a sentence-scoped
        # nearest-term rule binds this correct sentence to AUTHORISED.
        by_surface = {o.surface: o for o in score(TRUE, key).occurrences}
        assert by_surface["187,432.55"].attribute == "SPENT"
        assert by_surface["187,432.55"].attribute_scope == "clause"
        assert by_surface["250,000.00"].attribute == "AUTHORISED"


class TestTwoAxes:
    def test_wrong_attribute_without_a_referent_is_a_finding(self, key):
        # The archived run's headline inversion. Scored UNBOUND by a
        # single-axis rule, which reads as "could not tell" — but the report
        # has made a checkable claim and got it wrong.
        (o,) = score("Of the amounts confirmed, 187,432.55 is identified as "
                     "the unspent balance.", key).occurrences
        assert o.verdict == MISBOUND
        assert o.attribute_verdict == MISMATCH
        assert o.referent_verdict == UNRESOLVED

    def test_right_attribute_without_a_referent_is_partial_not_correct(self, key):
        (o,) = score("Authorised spend to date stands at 250,000.00 USD.",
                     key).occurrences
        assert o.verdict == PARTIAL
        assert (o.attribute_verdict, o.referent_verdict) == (MATCH, UNRESOLVED)

    def test_wrong_referent_outranks_an_unresolved_attribute(self, key):
        (o,) = score("Calder Logistics saw the gap quantified at twelve percent.",
                     key).occurrences
        assert o.referent_verdict == MISMATCH
        assert o.verdict == MISBOUND

    def test_two_referents_in_one_sentence_is_ambiguous_not_correct(self, key):
        res = score("Project Aurora, set against Project Zephyr, reports "
                    "250,000.00 USD.", key)
        assert res.occurrences[0].verdict == AMBIGUOUS
        assert res.counts[CORRECT] == 0

    def test_a_mismatched_attribute_survives_an_ambiguous_referent(self, key):
        # Declining on the referent must not suppress a checkable attribute
        # error, or a report improves its score by naming more projects.
        (o,) = score("Project Aurora and Project Zephyr report 120,000.00 USD "
                     "as the unspent balance.", key).occurrences
        assert o.attribute_verdict == MISMATCH
        assert o.verdict == MISBOUND

    def test_antecedent_carries_across_sentences_in_a_paragraph(self, key):
        res = score("Pilot Kestrel was reviewed. Committed funds of 51,237.75 "
                    "USD were recorded.", key)
        (o,) = res.occurrences
        assert (o.verdict, o.referent, o.referent_scope) == (CORRECT, "KESTREL",
                                                             "paragraph")

    def test_antecedent_does_not_cross_a_paragraph_break(self, key):
        res = score("Pilot Kestrel was reviewed.\n\nCommitted funds of 51,237.75 "
                    "USD were recorded.", key)
        (o,) = res.occurrences
        assert o.referent is None
        assert o.verdict == PARTIAL


class TestFabricationAndMasking:
    def test_a_value_outside_the_key_is_fabrication(self, key):
        (o,) = score("Authorised spend stands at 999,111.22 USD.", key).occurrences
        assert o.verdict == FABRICATED

    def test_the_loader_bug_artefact_is_caught_as_fabrication(self, key):
        # 187433 and 51237.8 are what the six-significant-figure loader bug
        # (fixed in fae743f) put into Document.text. They are not corpus values
        # and a report carrying them is fabricating.
        res = score("An additional figure, 187433, reflects allocated funds.", key)
        assert res.occurrences[0].verdict == FABRICATED

    def test_contract_identifiers_are_not_scanned_as_values(self, key):
        assert score("Contract NB-2026-0917 remains in force.", key).occurrences == []

    def test_dates_are_not_scanned_as_values(self, key):
        for text in ("Spent by 20 August 2026.", "Recorded 2026-06-01 in the sheet.",
                     "Tabled in September 2026."):
            assert score(text, key).occurrences == [], text

    def test_a_bare_year_is_exempt(self, key):
        assert score("The launch was deferred to 2027.", key).occurrences == []

    @pytest.mark.parametrize("text", [
        "The review meets on 30 September.",
        "Spend was recorded by 28 August, before the review.",
        "It was raised on the 4th August.",
        "Delays ran over 20-28 August.",
        "Delays ran over 20\u201328 August.",
        "Delays ran over 20 to 28 August.",
        "The board should (1) defer the launch and (2) table a plan.",
    ])
    def test_yearless_dates_ranges_and_enumerations_are_not_values(self, key, text):
        # Each of these digits was counted as a numeral outside the key in the
        # pilot's oracle reports before INS1.
        assert score(text, key).occurrences == [], text

    def test_the_new_masks_come_from_the_key_not_the_metric(self, key):
        """The masks are key data, so the key's SHA moves when they do. With
        the key's patterns removed the same text is scanned again."""
        bare = FactKey(referents=key.referents, attributes=key.attributes,
                       facts=key.facts, string_facts=key.string_facts, mask_patterns=[])
        found = [o.surface for o in score("Delays ran over 20-28 August; (1) defer.",
                                          bare).occurrences]
        assert found == ["20", "28", "1"]

    def test_masks_leave_a_gold_value_in_parentheses_alone(self, key):
        (o,) = score("Committed funds (51,237.75 USD) exceed the authority.",
                     key).occurrences
        assert o.surface == "51,237.75"


class TestSurfaceFacts:
    """The spelling "12%" was missed by a word-boundary regex, because a boundary
    after "%" needs a word character to follow, and was then scored as the
    numeral 12.0, outside the key."""

    @pytest.mark.parametrize("text", [
        "Zephyr's revenue fell 12% in the quarter.",
        "Zephyr's revenue fell 12%.",
        "Zephyr's revenue fell 12%, after the cancellation.",
        "Zephyr's revenue fell (12%) after the cancellation.",
        "Zephyr's revenue fell twelve percent.",
    ])
    def test_every_spelling_is_the_surface_fact(self, key, text):
        (o,) = score(text, key).occurrences
        assert o.verdict == CORRECT, (text, o)
        assert o.belongs_to == ["ZEPHYR.REVENUE_FALL_PCT"]

    @pytest.mark.parametrize("text", ["Revenue fell 0.12% overall.",
                                      "Revenue fell 112% overall.",
                                      "Revenue fell 12.5% overall."])
    def test_a_longer_number_is_not_the_surface_fact(self, key, text):
        (o,) = score(text, key).occurrences
        assert o.verdict == FABRICATED, (text, o)


class TestCoverage:
    def test_saying_nothing_does_not_score_well(self, key):
        res = score("The programme continues to progress against plan.", key)
        assert res.occurrences == []
        assert res.coverage == 0.0
        assert res.coverage_correct == 0.0
        # No binding was made, so there is no RBA to combine with coverage.
        assert res.f1 is None

    def test_a_misbound_only_report_scores_zero_coverage_correct(self, key):
        """`coverage` credits a fact for being said; a report that permutes
        every figure says all three and binds none of them right."""
        res = score(PERMUTED, key)
        assert {o.verdict for o in res.occurrences} == {MISBOUND}
        assert res.coverage == pytest.approx(3 / len(key.facts))
        assert res.coverage_correct == 0.0

    def test_coverage_correct_counts_correctly_bound_facts(self, key):
        res = score(TRUE, key)
        assert res.coverage_correct == pytest.approx(3 / len(key.facts))

    def test_coverage_correct_resolves_an_alias_subject_to_its_fact(self, key):
        # AURORA is an alias subject of VENDOR.UNITS_SHORT, not a fact id.
        (o,) = score("Project Aurora booked a shortfall of 340 units.", key).occurrences
        assert (o.verdict, o.referent) == (CORRECT, "AURORA")
        res = score("Project Aurora booked a shortfall of 340 units.", key)
        assert res.coverage_correct == pytest.approx(1 / len(key.facts))

    def test_a_correct_binding_of_one_value_does_not_credit_another(self, key):
        # 250,000.00 said right, 187,432.55 said wrong: one fact, not two.
        res = score("Project Zephyr was authorised 250,000.00 USD. Project Zephyr "
                    "holds 187,432.55 USD unspent.", key)
        assert [o.verdict for o in res.occurrences] == [CORRECT, MISBOUND]
        assert res.coverage_correct == pytest.approx(1 / len(key.facts))


class TestEmptyPools:
    """No pool, no number: a rate over nothing is None, never 0.0."""

    RATES = ("rba", "attribute_accuracy", "referent_accuracy", "resolution_rate",
             "misbinding_rate", "unbound_rate", "numerals_outside_key")

    def test_an_empty_report_has_no_rates(self, key):
        res = score("Nothing checkable is said here.", key)
        for name in self.RATES:
            assert getattr(res, name) is None, name

    def test_nulls_reach_the_json(self, key):
        out = json.loads(json.dumps(score("Nothing checkable.", key).to_json()))
        for name in self.RATES:
            assert out[name] is None, name
        assert '"rba": null' in json.dumps(score("Nothing.", key).to_json())

    def test_unresolved_bindings_leave_rba_null_not_zero(self, key):
        # Attribute resolved, referent not: an attribute accuracy exists, an
        # RBA does not. Before INS1 this RBA read 0.0, the worst score.
        res = score("Authorised spend to date stands at 250,000.00 USD.", key)
        assert res.attribute_accuracy == 1.0
        assert res.rba is None
        assert res.denominators["full"] == 0

    def test_only_numerals_outside_the_key(self, key):
        res = score("Authorised spend stands at 999,111.22 USD.", key)
        assert res.numerals_outside_key == 1.0
        assert res.rba is None and res.misbinding_rate is None

    def test_the_old_field_name_is_gone(self, key):
        out = score(TRUE, key).to_json()
        assert "fabrication_rate" not in out
        assert out["numerals_outside_key"] == 0.0
        assert out["coverage_correct"] == pytest.approx(3 / len(key.facts))

    def test_coverage_counts_only_real_gold_facts(self, key):
        # The vendor shortfall carries an alias subject so either spelling
        # scores CORRECT; the alias is not itself a gold fact and must not
        # inflate coverage.
        res = score("Calder Logistics missed its commitment by 340 units.", key)
        assert res.occurrences[0].verdict == CORRECT
        n_gold = len(key.facts)
        assert res.coverage == pytest.approx(1 / n_gold)

    def test_a_derived_fact_no_document_states_is_separated_out(self, key):
        derived = {f["fact_id"] for f in key.facts if f.get("derived")}
        assert "AURORA.UNSPENT" in derived
        stated = {f["fact_id"] for f in key.facts if not f.get("derived")}
        assert "AURORA.UNSPENT" not in stated


class TestDeEscaping:
    def test_escapes_are_stripped(self):
        assert de_escape(r"187,432\.55 on 2026\-06\-01") == "187,432.55 on 2026-06-01"

    def test_an_escaped_report_scores_the_same_as_a_plain_one(self, key):
        plain = "Authorised spend to date stands at 250,000.00 USD."
        escaped = r"Authorised spend to date stands at 250,000\.00 USD\."
        assert verdicts(escaped, key) == verdicts(plain, key)


class TestTables:
    def test_a_table_binds_its_attribute_from_the_header(self, key):
        table = ("| Project | Authorised (USD) | Spent (USD) |\n"
                 "| --- | --- | --- |\n"
                 "| Project Zephyr | 250,000.00 | 187,432.55 |\n")
        res = score(table, key)
        assert [o.verdict for o in res.occurrences] == [CORRECT, CORRECT]
        assert all(o.attribute_scope == "table" for o in res.occurrences)

    def test_offsets_point_at_the_numeral_in_prose_and_tables(self, key):
        text = ("Pilot Kestrel spent 51,237.75 USD, and 51,237.75 USD again.\n\n"
                "| Project | Authorised (USD) | Spent (USD) |\n"
                "| --- | --- | --- |\n"
                "|  Project Zephyr |250,000.00 | 187,432.55 |\n")
        occ = score(text, key).occurrences
        assert len(occ) == 4
        for o in occ:
            assert o.context[o.offset:o.offset + len(o.surface)] == o.surface, o
        assert occ[0].offset != occ[1].offset

    def test_a_table_with_swapped_columns_is_caught(self, key):
        table = ("| Project | Authorised (USD) | Spent (USD) |\n"
                 "| --- | --- | --- |\n"
                 "| Project Zephyr | 187,432.55 | 250,000.00 |\n")
        assert [o.verdict for o in score(table, key).occurrences] == [MISBOUND,
                                                                     MISBOUND]


class TestKeyIntegrity:
    def test_a_phrase_claimed_by_two_attributes_is_refused(self, key):
        # "budget" already belongs to AUTHORISED; claiming it for SPENT too
        # would make the longest-match alternation order-dependent.
        clashing = {**key.attributes,
                    "SPENT": [*key.attributes["SPENT"], "budget"]}
        clash = FactKey(referents=key.referents, attributes=clashing,
                        facts=key.facts, string_facts=key.string_facts,
                        mask_patterns=key.mask_patterns)
        with pytest.raises(ValueError, match="order-dependent"):
            clash.lexicon_regex()

    def test_every_gold_value_has_at_least_one_surface(self, key):
        for f in key.facts:
            assert f["surfaces"], f["fact_id"]
