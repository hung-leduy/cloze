"""R1 fact references against the real reference monitor's screens.

Each claim here was measured before it was written down, and two of the design
document's claims did not survive: the glued-pair entropy and the with-category
headroom. What is pinned is what the linters actually do.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT, ROOT / "gateway"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from privdeep.models.document import SLOT_CATEGORIES  # noqa: E402
from privdeep.models.facts import ATTRIBUTE_CODES, FACT_RE  # noqa: E402

from gateway.linters import regex_rules  # noqa: E402
from gateway.linters.entropy_linter import scan_payload  # noqa: E402
from gateway.sanitizer import injection_guard  # noqa: E402
from shared.shingle_filter import ShingleFilter, tokenize  # noqa: E402

pytestmark = pytest.mark.security
THRESHOLD = 4.85


def _hex(rnd: random.Random) -> str:
    return "".join(rnd.choice("0123456789abcdef") for _ in range(8))


def _worst(make, context: str, n: int = 3000, seed: int = 20260914) -> float:
    rnd = random.Random(seed)  # noqa: S311 - seeded on purpose: pinned figures must reproduce
    worst = 0.0
    for _ in range(n):
        t, u = make(rnd), make(rnd)
        worst = max(worst, scan_payload(context.format(t=t, u=u)).worst_entropy)
    return worst


def fact(rnd):
    return f"⟦FACT:{_hex(rnd)}.{rnd.choice(ATTRIBUTE_CODES)}⟧"


def slot(rnd):
    return f"⟦SLOT:{rnd.choice(SLOT_CATEGORIES)}_{_hex(rnd)}⟧"


class TestEntropy:
    def test_the_bare_fact_token_is_never_scored(self):
        assert _worst(fact, "{t}") == 0.0

    @pytest.mark.parametrize("context", ['"{t}",', "{t}'s", "({t})", "{t}:", "- {t}\n"])
    def test_punctuated_fact_tokens_pass_on_margin(self, context):
        """On margin, not structure: these tokens are scored, and pass."""
        assert _worst(fact, context) < THRESHOLD

    def test_two_fact_tokens_glued_together_are_refused(self):
        """Measured 4.954. The design document reported 4.62 for this context.
        Inbound this is only flagged; anything the core writes outbound must
        separate fact tokens with whitespace, and step 3 pins that."""
        assert _worst(fact, "{t}{u}") > THRESHOLD

    def test_a_category_in_the_token_would_be_refused_in_ordinary_json(self):
        """Why the token carries no category. Measured over 30,000 draws in a
        quoted-JSON context: about 0.5% of with-category tokens are refused
        (worst 4.911), against 0 of 30,000 without it. A false-refusal class,
        not a certainty -- with the attribute fixed at AUTHAMT the worst of
        3,000 draws is 4.696 and nothing is refused."""
        def refused(make, n=3000):
            rnd = random.Random(20260914)  # noqa: S311 - seeded on purpose: pinned figures must reproduce
            return sum(scan_payload(f'"{make(rnd)}",').worst_entropy > THRESHOLD
                       for _ in range(n))

        def with_category(r):
            return f"⟦FACT:{r.choice(SLOT_CATEGORIES)}_{_hex(r)}.{r.choice(ATTRIBUTE_CODES)}⟧"

        assert refused(with_category) > 0
        assert refused(fact) == 0

    @pytest.mark.parametrize("context", ['"{t}",', "- {t}\n"])
    def test_slot_tokens_in_the_shipped_forms_still_pass(self, context):
        assert _worst(slot, context) < THRESHOLD


class TestDriftBetweenGatewayAndBackend:
    def test_the_injection_guard_uses_the_backends_fact_pattern(self):
        assert injection_guard._FACT_RE.pattern == FACT_RE.pattern

    def test_the_fact_probe_names_every_attribute_code(self):
        """A code missing from the probe could be added as a custom term and
        would then refuse every payload referencing that attribute."""
        probe = regex_rules._FACT_PROBE
        assert {m.group("attr") for m in FACT_RE.finditer(probe)} == set(ATTRIBUTE_CODES)


class TestContainment:
    CORPUS = ("Of the 250,000 USD authorised, 187,432.55 USD had been spent by 20 August "
              "2026, leaving 62,567.45 USD held against the remaining milestones. "
              "Calder Logistics delivered 340 units fewer than the July commitment.")

    def _filter(self) -> ShingleFilter:
        f = ShingleFilter(salt=b"fact-containment-test", n_min=5, n_max=8, hit_threshold=1)
        f.index_document(self.CORPUS)
        f.seal()
        return f

    def test_fact_tokens_tokenise_to_nothing_the_corpus_contains(self):
        assert tokenize("⟦FACT:389a0ca5.AUTHAMT⟧") == ["fact", "389a0ca5", "authamt"]

    def test_a_prompt_full_of_fact_references_does_not_hit(self):
        """Compatibility, not a safety property: breaking runs is what defeats a
        word-shingle filter, and THREAT_MODEL section 5 lists interleaving as
        unprotected."""
        rnd = random.Random(1)  # noqa: S311 - seeded on purpose: pinned figures must reproduce
        payload = " ".join(f"the {c.lower()} for this initiative is {fact(rnd)}"
                           for c in ATTRIBUTE_CODES)
        assert not self._filter().inspect(payload).blocked

    def test_positive_control_a_copied_corpus_phrase_does_hit(self):
        assert self._filter().inspect(
            "Calder Logistics delivered 340 units fewer than the July commitment").blocked
