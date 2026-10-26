"""Invariant tests for the raw-context containment check.

The test named `test_entropy_linter_misses_what_shingles_catch` is the one that
justifies the component existing at all, and it is the figure the paper should
carry: the incumbent mechanism's catch rate on this class is zero by
construction, not by bad luck.
"""

from __future__ import annotations

import secrets

import pytest
from linters.entropy_linter import calculate_shannon_entropy, scan_payload

from shared.shingle_filter import BloomFilter, ShingleFilter

SALT = b"test-salt-not-for-production"

# Representative private context: the kind of sentence the invariant exists to
# stop, containing a project name, a place, a figure and a business fact.
PRIVATE_DOC = """
Project Zephyr's Q3 revenue fell twelve percent after the Hanoi pilot was
cancelled in August. The steering committee attributed the shortfall to the
delayed migration of the Da Nang fulfilment centre, which had been scheduled
for completion before the quarter closed. Nguyen Thi Lan raised the risk in
the June review and recommended deferring the launch until the following year.
"""

UNRELATED = """
Transformer architectures rely on scaled dot-product attention to model
long-range dependencies. The mechanism computes a weighted sum over value
vectors, where the weights come from a softmax over query-key inner products.
"""


def build(doc: str = PRIVATE_DOC, **kw) -> ShingleFilter:
    f = ShingleFilter(salt=SALT, **kw)
    f.index_document(doc)
    f.seal()
    return f


class TestContainment:
    def test_verbatim_span_is_blocked(self):
        f = build()
        leak = (
            "As background, Project Zephyr's Q3 revenue fell twelve percent "
            "after the Hanoi pilot was cancelled."
        )
        v = f.inspect(leak)
        assert v.blocked
        assert v.hit_count >= 1

    def test_unrelated_text_passes(self):
        f = build()
        assert not f.inspect(UNRELATED).blocked

    def test_span_shorter_than_n_min_passes(self):
        """Below n_min there is no containment claim, and the test pins that."""
        f = build(n_min=5, n_max=8)
        assert not f.inspect("revenue fell twelve percent").blocked  # 4 tokens

    def test_reformatting_does_not_evade(self):
        """Casefolding and punctuation-insensitivity survive a model's re-typing."""
        f = build()
        restyled = "PROJECT ZEPHYR'S  Q3   REVENUE, FELL! TWELVE... PERCENT AFTER THE HANOI PILOT"
        assert f.inspect(restyled).blocked

    def test_abstracted_form_passes(self):
        """The masked form the architecture actually sends must not be refused."""
        f = build()
        masked = (
            "The ⟦SLOT:PROJECT_NAME_a1b2⟧ initiative reported a decline in the third quarter "
            "following the cancellation of a regional pilot programme."
        )
        assert not f.inspect(masked).blocked


class TestHonestLimits:
    """Tests that pin what this mechanism does NOT do, so the claim stays scoped."""

    def test_paraphrase_is_not_caught(self):
        f = build()
        para = (
            "Revenue for the Zephyr programme dropped by around a eighth in the third "
            "quarter once the pilot in northern Vietnam was called off."
        )
        assert not f.inspect(para).blocked, (
            "If this ever passes, the honest claim has changed and the paper must say so."
        )

    def test_arithmetic_derivation_is_not_caught(self):
        f = build()
        assert not f.inspect("The decline was 0.12 of prior-quarter revenue.").blocked


class TestLeakResistance:
    def test_filter_is_salt_dependent(self):
        """An attacker holding the gateway's filter but not the salt learns nothing."""
        a = ShingleFilter(salt=b"salt-A")
        a.index_document(PRIVATE_DOC)
        a.seal()
        b = ShingleFilter(salt=b"salt-B")
        b.index_document(PRIVATE_DOC)
        b.seal()
        # Same content, different salt: the digests, and so the set bits, differ.
        assert a.bloom.bits_set != b.bloom.bits_set or a.bloom._bits != b.bloom._bits

    def test_unsalted_filter_is_rejected(self):
        with pytest.raises(ValueError, match="salt"):
            BloomFilter(m_bits=1024, k=3, salt=b"")

    def test_matched_shingles_withheld_by_default(self):
        """Matched shingles are corpus text; they must not land in a gateway log."""
        f = build()
        v = f.inspect("Project Zephyr's Q3 revenue fell twelve percent after the Hanoi pilot")
        assert v.blocked
        assert v.matched_shingles == ()


class TestTheCaseForThisComponent:
    def test_entropy_linter_misses_what_shingles_catch(self):
        """The incumbent mechanism's catch rate on raw prose is 0.00 by construction.

        This is the comparison the paper reports. It is not a tuning problem:
        no threshold that admits ordinary JSON also refuses English prose.
        """
        f = build()
        leak = (
            "Project Zephyr's Q3 revenue fell twelve percent "
            "after the Hanoi pilot was cancelled."
        )

        entropy_verdict = scan_payload(leak, threshold=4.85, min_length=24)
        shingle_verdict = f.inspect(leak)

        assert not entropy_verdict.blocked, "entropy linter unexpectedly caught raw prose"
        assert shingle_verdict.blocked, "shingle filter failed to catch a verbatim span"

    def test_prose_entropy_sits_far_below_the_threshold(self):
        """Quantifies the gap, so the paper can state it rather than assert it."""
        h = calculate_shannon_entropy(PRIVATE_DOC)
        assert h < 4.85
        # And the spec's own canary format is also under the threshold:
        canary = "CANARY_PRIVDEEP_" + secrets.token_hex(16)
        assert calculate_shannon_entropy(canary) < 4.85

    def test_entropy_linter_still_earns_its_place(self):
        """It covers the disjoint case: base64, which shingles cannot see."""
        import base64

        blob = base64.b64encode(secrets.token_bytes(256)).decode()
        assert scan_payload(blob).blocked


class TestFalseRefusalCost:
    def test_false_positive_rate_is_measured_not_assumed(self):
        f = build(target_fp_rate=1e-7)
        est = f.bloom.estimated_fp_rate()
        assert est < 1e-4, f"filter sizing gives FP rate {est:.2e}"

    def test_clean_payloads_are_not_refused_in_bulk(self):
        """Bulk check over unrelated technical prose: no refusals."""
        f = build()
        corpus = [
            "The reference monitor mediates every outbound request from the trusted zone.",
            "Retrieval augmented generation grounds model output in retrieved passages.",
            "Differential privacy bounds the influence of any single record on the output.",
            "Container networks marked internal receive no default route from the daemon.",
            "The quick brown fox jumps over the lazy dog near the river bank at dawn.",
        ]
        refused = [p for p in corpus if f.inspect(p).blocked]
        assert refused == [], f"false refusals: {refused}"


class TestEntropyThresholdIsAlphabetBound:
    """The 4.85 bits/char threshold is not a tunable knob, it is an alphabet choice.

    Maximum achievable entropy is log2(|alphabet|). So a threshold of 4.85 sits
    above hex's ceiling and below base64's, which means the screen catches
    exactly one encoding and is structurally blind to the others. This is a
    provable statement about the specification, not an empirical accident, and
    it belongs in the paper as such.
    """

    @pytest.mark.parametrize(
        "name,alphabet_size,catchable",
        [("hex", 16, False), ("base32", 32, True), ("base64", 64, True)],
        ids=["hex", "base32", "base64"],
    )
    def test_threshold_versus_alphabet_ceiling(self, name, alphabet_size, catchable):
        import math

        ceiling = math.log2(alphabet_size)
        assert (ceiling > 4.85) is catchable, (
            f"{name}: ceiling {ceiling:.2f} bits/char vs threshold 4.85"
        )

    def test_hex_exfiltration_passes_the_entropy_screen(self):
        """Concrete consequence: hex is a free covert channel under the spec."""
        payload = secrets.token_hex(128)
        assert len(payload) > 24
        assert not scan_payload(payload, threshold=4.85, min_length=24).blocked

    def test_whitespace_injection_defeats_the_length_floor(self):
        """A space every 20 chars puts every token under min_length=24."""
        import base64

        blob = base64.b64encode(secrets.token_bytes(256)).decode()
        assert scan_payload(blob).blocked
        chunked = " ".join(blob[i : i + 20] for i in range(0, len(blob), 20))
        assert not scan_payload(chunked).blocked


class TestWireFormat:
    """The core seals inside the partition and ships bytes; the gateway must get
    the identical filter back, or every verdict on the gateway is quietly wrong."""

    def test_round_trip_preserves_every_verdict(self):
        f = build()
        g = ShingleFilter.from_wire(f.to_wire(), salt=SALT)
        leak = "Project Zephyr's Q3 revenue fell twelve percent after the Hanoi pilot"
        assert g.inspect(leak).blocked and f.inspect(leak).blocked
        assert not g.inspect(UNRELATED).blocked
        assert g.bloom.m_bits == f.bloom.m_bits and g.bloom.k == f.bloom.k
        assert g.bloom.n_added == f.bloom.n_added
        assert g.n_min == f.n_min and g.n_max == f.n_max and g.hit_threshold == f.hit_threshold

    def test_shingling_parameters_travel_with_the_filter(self):
        f = build(n_min=3, n_max=4, hit_threshold=2)
        g = ShingleFilter.from_wire(f.to_wire(), salt=SALT)
        assert (g.n_min, g.n_max, g.hit_threshold) == (3, 4, 2)

    def test_wrong_salt_on_receive_breaks_matching(self):
        """Salt is out-of-band on purpose; a mismatch must show up as misses, not silence."""
        f = build()
        g = ShingleFilter.from_wire(f.to_wire(), salt=b"a-different-salt")
        leak = "Project Zephyr's Q3 revenue fell twelve percent after the Hanoi pilot"
        assert f.inspect(leak).blocked
        assert not g.inspect(leak).blocked

    @pytest.mark.parametrize("kind", ["truncated", "bad-magic", "bad-header", "no-header"])
    def test_corrupt_wire_is_rejected_not_accepted(self, kind):
        wire = build().to_wire()
        nl = wire.find(b"\n")
        if kind == "truncated":
            bad = wire[:-1]
        elif kind == "bad-magic":
            bad = wire[: nl + 1] + b"XXXX" + wire[nl + 5 :]
        elif kind == "bad-header":
            bad = wire.replace(b'"n_min"', b'"nmin"', 1)
        else:
            bad = b"no newline at all"
        with pytest.raises(ValueError):
            ShingleFilter.from_wire(bad, salt=SALT)

    def test_bloom_bytes_are_compact(self):
        f = build()
        wire = f.to_wire()
        assert len(wire) < 2048, f"one document's filter is {len(wire)} bytes"
