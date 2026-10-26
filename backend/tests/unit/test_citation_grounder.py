"""Citations must resolve to hashed evidence; numbers must sit in cited sentences."""

from __future__ import annotations

import pytest
from privdeep.tier3_reconcile.citation_grounder import CitationGrounder, GroundingRefused
from privdeep.tier3_reconcile.evidence_bank import EvidenceBank


@pytest.fixture
def bank():
    b = EvidenceBank()
    b.add("https://example.invalid/a", "Pilot cancellations cut revenue 10-15% in 2026.",
          "Regional pilot cancellations reduced revenue by 10-15%.")
    b.add("https://example.invalid/b", "Migration delays averaged 40 days.",
          "Fulfilment migrations were delayed ~40 days on average.")
    return b


class TestBank:
    def test_content_addressed_and_deduplicated(self, bank):
        u1 = bank.by_tag("W1")
        again = bank.add("https://other.invalid", u1.raw_snippet, "different summary")
        assert again is u1 and len(bank) == 2
        assert u1.evidence_id == f"EV-WEB-{u1.content_hash[:8]}"

    def test_tags_are_sequential_and_stable(self, bank):
        assert [u.tag for u in bank] == ["W1", "W2"]
        assert bank.by_tag("W3") is None

    def test_manifest_has_hashes_not_snippets(self, bank):
        m = bank.manifest()
        assert {"evidence_id", "tag", "content_hash", "source_url"} == set(m[0])
        assert "revenue" not in str(m)

    def test_verify_detects_tampering(self, bank):
        from dataclasses import replace

        u = bank.by_tag("W1")
        tampered = replace(u, raw_snippet=u.raw_snippet + "!")
        assert bank.verify(u) and not bank.verify(tampered)


class TestGrounding:
    def test_valid_tags_and_cited_numbers_pass(self, bank):
        text = ("Cancellations reduced revenue by 12% [W1]. "
                "Migration slipped about 40 days [W2]. In 2026 the plan changed.")
        r = CitationGrounder(bank).check(text)
        assert r.valid_tags == ("W1", "W2") and r.invalid_tags == ()
        assert r.unbacked_numbers == () and r.ok

    def test_unknown_tag_is_invalid_and_refuses_strict(self, bank):
        with pytest.raises(GroundingRefused) as ei:
            CitationGrounder(bank).check("Revenue fell [W9].")
        assert ei.value.result.invalid_tags == ("W9",)

    def test_number_in_uncited_sentence_is_unbacked(self, bank):
        r = CitationGrounder(bank, strict=False).check(
            "Revenue fell 12% last quarter. Costs rose 3.5 million. Delays were 40 days [W2].")
        assert r.unbacked_numbers == ("12%", "3.5")
        assert not r.ok

    def test_years_list_markers_and_slots_are_exempt(self, bank):
        text = ("1. In 2024 and 2026 the site ⟦SLOT:IDENTIFIER_0badf00d⟧ was reviewed.\n"
                "- 2. Second point with no figure.")
        r = CitationGrounder(bank, strict=False).check(text)
        assert r.unbacked_numbers == ()

    def test_invalid_tag_does_not_back_a_number(self, bank):
        r = CitationGrounder(bank, strict=False).check("Revenue fell 12% [W9].")
        assert r.invalid_tags == ("W9",) and r.unbacked_numbers == ("12%",)

    def test_extra_exempt(self, bank):
        g = CitationGrounder(bank, strict=False, extra_exempt={"Q3"})
        r = g.check("Q3 was fine. 7 issues.")
        assert r.unbacked_numbers == ("7",)
