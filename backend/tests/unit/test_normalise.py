"""Unit tests for R5 canonical keys.

Three of these classes exist to pin *absences*. `TestNoSixSignificantFigureJoin`
and `TestNoAliasMerging` fail if a merge rule the design asked for is ever added
back, and `TestKnownLimitations` records the one case where the shipped rule is
wrong on purpose. An absence that is not pinned is an absence that comes back.
"""

from __future__ import annotations

import pytest
from privdeep.models.document import SLOT_CATEGORIES
from privdeep.tier1_local.normalise import canonical_key, canonical_rendering


def same(category: str, *texts: str) -> bool:
    return len({canonical_key(category, t) for t in texts}) == 1


class TestTheJoinsR5ExistsFor:
    """The 19-slots-for-8-figures failure, by surface family."""

    def test_thousands_separators_and_trailing_zeros_agree(self):
        assert same("MONEY", "250,000", "250,000.00", "250000", "250000.00")
        assert same("MONEY", "187,432.55", "187432.55")
        assert same("MONEY", "98,210.00", "98210", "98,210")
        assert same("MONEY", "51,237.75", "51237.75")

    def test_currency_markers_are_stripped(self):
        assert same("MONEY", "250,000.00 USD", "$250,000.00", "250000")

    def test_quantities_join_the_same_way(self):
        assert same("QUANTITY", "6,237.75", "6237.75")

    def test_the_key_is_never_in_exponential_form(self):
        # Decimal.normalize() spells 250000 as 2.5E+5; a key that varies with
        # magnitude would make large round amounts collide oddly.
        assert canonical_key("MONEY", "250,000.00") == "250000"
        assert "E" not in canonical_key("MONEY", "250000")

    def test_iso_cell_and_prose_date_agree(self):
        assert same("DATE", "2026-06-01", "2026-06-01T00:00:00", "1 June 2026",
                    "June 1, 2026")

    def test_the_iso_separator_survives_casefolding(self):
        """Regression: keys are computed on casefolded text, so the `T` and the
        trailing `Z` arrive lowercase. An uppercase-only pattern failed on
        `2026-06-01T00:00:00`, which is precisely what a date cell becomes in
        `ingest/xlsx.py` -- every spreadsheet date would have split from its
        prose spelling, inside the module written to stop that happening."""
        assert same("DATE", "2026-06-01", "2026-06-01T00:00:00",
                    "2026-06-01t00:00:00", "2026-06-01 00:00:00",
                    "2026-06-01Z", "2026-06-01z")

    def test_month_precision_dates_agree_but_differ_from_a_day(self):
        assert same("DATE", "August 2026", "august 2026")
        assert canonical_key("DATE", "August 2026") != canonical_key("DATE", "1 August 2026")

    def test_identifier_separators_and_case(self):
        assert same("IDENTIFIER", "NB-2026-0917", "nb 2026 0917", "NB.2026.0917")

    def test_names_fold_case_width_and_whitespace(self):
        assert same("PERSON", "Sarah Whitfield", "sarah  whitfield", "Sarah Whitfield")
        assert same("ORG", "Ｎorthbridge Analytics", "Northbridge Analytics")

    def test_possessive_and_article_are_grammar_not_identity(self):
        assert same("PROJECT", "Project Zephyr", "Project Zephyr's", "Project Zephyr’s")
        assert same("ORG", "Calder Logistics", "the Calder Logistics")


class TestNoSixSignificantFigureJoin:
    """The design's one join rule, deliberately not implemented.

    It existed to undo `ingest/xlsx.py`'s `format(v, "g")`. Commit fae743f
    replaced that with `repr(v)`, so the forms it repaired no longer reach
    Document.text, and re-measured on the post-fix corpus the rule joins 0
    pairs. What it can still do is merge two genuinely distinct amounts, and
    then `restore` writes the wrong number into a report.
    """

    def test_a_truncated_form_is_a_different_referent(self):
        assert not same("MONEY", "187433", "187,432.55")
        assert not same("MONEY", "51237.8", "51,237.75")

    def test_two_real_amounts_six_sig_figs_apart_stay_distinct(self):
        # The case the rule would have corrupted.
        assert not same("MONEY", "1234567", "1234570")


class TestNoAliasMerging:
    """Fragmentation is counted; a wrong merge is acted on."""

    def test_substring_names_stay_distinct(self):
        assert not same("PROJECT", "Zephyr", "Project Zephyr")

    def test_acronyms_stay_distinct(self):
        assert not same("ORG", "Northbridge Analytics", "NA")

    def test_initials_stay_distinct(self):
        assert not same("PERSON", "Sarah Whitfield", "S. Whitfield")

    def test_two_people_sharing_a_surname_stay_distinct(self):
        assert not same("PERSON", "Sarah Whitfield", "Daniel Whitfield")


class TestKnownLimitations:
    def test_currencies_are_stripped_not_compared(self):
        """Documented and wrong on purpose: the corpus is single-currency.

        A multi-currency deployment must compare markers before trusting a
        MONEY merge. Pinned here so it is found by reading the tests rather
        than by reading a report.
        """
        assert same("MONEY", "250,000 USD", "250,000 EUR")

    def test_ambiguous_all_numeric_dates_are_not_guessed(self):
        # 01/06/2026 is 1 June or 6 January depending on locale. Guessing would
        # merge two different days.
        assert not same("DATE", "01/06/2026", "2026-06-01")


class TestTotality:
    """It never raises, whatever the extractor hands it."""

    @pytest.mark.parametrize("text", [
        "Spend exceeds budget by 6,237.75 USD", "High", "Medium",
        "  ", "​", "—", "12%", "not a date at all", "NB-", "0",
    ])
    def test_every_category_accepts_every_input(self, text):
        for cat in SLOT_CATEGORIES:
            assert isinstance(canonical_key(cat, text), str)

    def test_a_mistyped_sentence_is_not_reduced_to_its_first_numeral(self):
        # The extractor types whole risk cells as QUANTITY. Keying those by a
        # digit they happen to share would merge two unrelated sentences.
        a = "Spend exceeds budget by 6,237.75 USD"
        b = "Calder Logistics missed 6,237.75 units"
        assert not same("QUANTITY", a, b)

    def test_it_is_deterministic(self):
        assert canonical_key("MONEY", "250,000.00") == canonical_key("MONEY", "250,000.00")

    def test_category_separates_identical_text(self):
        # The masker puts the category in the HMAC input, but the keys for the
        # same string under two categories may legitimately differ too.
        assert canonical_key("IDENTIFIER", "NB-2026-0917") != canonical_key(
            "PROJECT", "NB-2026-0917")


class TestCanonicalRendering:
    def test_most_frequent_surface_wins(self):
        assert canonical_rendering({"250000": 1, "250,000.00": 5}) == "250,000.00"

    def test_ties_go_to_the_longer_more_explicit_spelling(self):
        assert canonical_rendering({"250000": 2, "250,000.00": 2}) == "250,000.00"

    def test_ties_on_length_go_to_first_seen(self):
        assert canonical_rendering({"250,000.01": 1, "250,000.02": 1}) == "250,000.01"

    def test_it_only_ever_returns_an_observed_surface(self):
        surfaces = {"250,000.00": 3, "250000": 1}
        assert canonical_rendering(surfaces) in surfaces

    def test_a_referent_with_no_surface_is_refused(self):
        with pytest.raises(ValueError, match="nothing to render"):
            canonical_rendering({})
