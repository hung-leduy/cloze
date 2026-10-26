"""Tests for the regex secret/identifier screen.

Three things gate the architectural claims and are pinned here: every default
rule fires on a synthetic value of its shape; the slot placeholder, the only
identifier-shaped token that legitimately leaves, never fires in any position;
and a clean megabyte of prose has zero hits and scans well under 100 ms. The
known false positives are asserted as behaviour, not hidden: a test that
documents `1.2.3.4` firing is what keeps the docstring honest.
"""

from __future__ import annotations

import dataclasses
import random
import re
import time

import pytest
from linters.regex_rules import (
    DEFAULT_RULES,
    SEVERITIES,
    RegexRule,
    RegexScreen,
    RegexVerdict,
)

SCREEN = RegexScreen()

SLOTS = (
    "⟦SLOT:PERSON_a1b2c3d4⟧",
    "⟦SLOT:ORG_0a1b2c3d⟧",
    "⟦SLOT:MONEY_00000000⟧",
    "⟦SLOT:DATE_ffffffff⟧",
    "⟦SLOT:PROJECT_deadbeef⟧",
)


def names(text: str) -> tuple[str, ...]:
    return SCREEN.scan(text).rule_names


def clean_prose(n_bytes: int = 1_000_000, seed: int = 20260906) -> str:
    """Deterministic English-ish prose with the punctuation and numbers real
    reports carry (years, percentages, times, dates, version strings, figure
    refs) and nothing that has the shape of a secret or an identifier."""
    rng = random.Random(seed)  # noqa: S311 - fixture prose, not key material
    words = (
        "the reference monitor mediates every outbound request from the trusted zone and "
        "privacy-preserving research agents evaluate retrieval-grounded synthesis over "
        "abstract payloads while a deterministic linter chain refuses any egress whose shape "
        "identifies it as a credential or an identifier of a person organisation project "
        "or account e.g. Fig. Table Section"
    ).split()
    fillers = [
        "2026", "1999", "12.5%", "$1,234.56", "12:30", "2026-09-06", "v2.1.0", "[12]",
        "3.2.1", "Q3", "(2024)", "Python 3.12.3", "16:9", "12:30:45", "2026-09-06T12:30:45Z",
    ]
    out: list[str] = []
    size = 0
    while size < n_bytes:
        k = rng.randint(6, 18)
        ws = [rng.choice(words) for _ in range(k)]
        if rng.random() < 0.3:
            ws.insert(rng.randrange(k), rng.choice(fillers))
        s = " ".join(ws).capitalize() + rng.choice([". ", ". ", ", ", "; ", ".\n"])
        out.append(s)
        size += len(s)
    return "".join(out)


# One synthetic, obviously fake value per default rule. Values are assembled
# so that no real credential shape is reproduced beyond the prefix.
POSITIVES: list[tuple[str, str]] = [
    ("anthropic_api_key", "sk-ant-api03-" + "FAKE" * 10 + "-FAKEAA"),
    ("openai_api_key", "sk-" + "F0" * 24),
    ("openai_api_key", "sk-proj-" + "FAKE" * 6 + "_FAKE-0000"),
    ("aws_access_key_id", "AKIAFAKEFAKEFAKEFAKE"),
    ("aws_access_key_id", "ASIAFAKEFAKEFAKEFAKE"),
    ("github_token", "ghp_" + "F0" * 18),
    ("github_token", "gho_" + "a1" * 18),
    ("github_fine_grained_pat", "github_pat_" + "F0" * 41),
    ("google_api_key", "AIza" + "F0" * 17 + "F"),
    ("slack_token", "xoxb-" + "0" * 12 + "-" + "0" * 13 + "-" + "FAKE" * 6),
    ("private_key_pem", "-----BEGIN RSA PRIVATE KEY-----"),
    ("private_key_pem", "-----BEGIN PRIVATE KEY-----"),
    ("private_key_pem", "-----BEGIN OPENSSH PRIVATE KEY-----"),
    ("private_key_pem", "-----BEGIN PGP PRIVATE KEY BLOCK-----"),
    ("jwt", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0." + "FAKE" * 6),
    ("uuid", "123e4567-e89b-42d3-a456-426614174000"),
    ("uuid", "123E4567-E89B-12D3-A456-426614174000"),
    ("uuid", "0192a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"),
    ("ipv4", "192.168.1.10"),
    ("ipv4", "10.0.0.1."),
    ("ipv4", "10.0.0.0/8"),
    ("ipv6", "2001:0db8:85a3:0000:0000:8a2e:0370:7334"),
    ("ipv6", "2001:db8::1"),
    ("ipv6", "[::1]:8080"),
    ("ipv6", "fe80::"),
    ("email", "user.name+tag@example.invalid"),
    ("email", "git@example.invalid:org/repo.git"),
    ("vn_mobile", "0912345678"),
    ("vn_mobile", "+84912345678"),
    ("vn_mobile", "+84 912 345 678"),
    ("vn_mobile", "0912 345 678"),
    ("vn_mobile", "091.234.5678"),
    ("vn_mobile", "0321234567"),
    ("vn_national_id", "079123456789"),
    ("vn_national_id", "001099012345"),
    ("vn_tax_code", "0101234567"),
    ("vn_tax_code", "0101234567-001"),
    ("vn_tax_code", "0101234567001"),
]


class TestPositives:
    @pytest.mark.parametrize(("rule", "value"), POSITIVES)
    def test_fires_in_context(self, rule: str, value: str):
        v = SCREEN.scan(f"Please summarise: {value} for the board.")
        assert v.blocked
        assert rule in v.rule_names
        assert v.total_hits >= 1

    @pytest.mark.parametrize(("rule", "value"), POSITIVES)
    def test_fires_at_string_edges(self, rule: str, value: str):
        assert rule in names(value)
        assert rule in names(f"{value}\n")
        assert rule in names(f"\n{value}")

    def test_every_default_rule_has_a_positive(self):
        covered = {rule for rule, _ in POSITIVES}
        assert {r.name for r in DEFAULT_RULES} <= covered

    def test_anthropic_key_is_not_also_an_openai_key(self):
        v = SCREEN.scan("sk-ant-api03-" + "FAKE" * 10 + "-FAKEAA")
        assert v.rule_names == ("anthropic_api_key",)
        assert v.total_hits == 1

    def test_hits_are_counted_per_occurrence(self):
        v = SCREEN.scan("AKIAFAKEFAKEFAKEFAKE and AKIAFAKEFAKEFAKEFAK2")
        assert v.total_hits == 2
        assert v.rule_names == ("aws_access_key_id",)

    def test_rule_names_follow_rule_order_and_are_unique(self):
        v = SCREEN.scan("0912345678 AKIAFAKEFAKEFAKEFAKE 0912345679")
        assert v.rule_names == ("aws_access_key_id", "vn_mobile", "vn_tax_code")
        assert v.total_hits == 5  # each mobile number also satisfies the tax-code grammar

    def test_json_payload(self):
        payload = (
            '{"model": "x", "messages": [{"role": "user", "content": '
            '"contact 001099012345 at user@example.invalid"}]}'
        )
        assert set(names(payload)) == {"vn_national_id", "email"}


class TestSlotPlaceholderNeverFires:
    @pytest.mark.parametrize("slot", SLOTS)
    def test_alone(self, slot: str):
        assert not SCREEN.scan(slot).blocked

    @pytest.mark.parametrize("slot", SLOTS)
    def test_positions(self, slot: str):
        for text in (
            f"{slot} resigned in March.",
            f"Revenue at {slot} fell.",
            f"the audit named {slot}",
            f"x{slot}y",
            f"{slot}'s phone was cut off",
            f"({slot}), [{slot}], \"{slot}\", '{slot}'",
            f"{slot}{slot}",
            f"{slot}\n{slot}\t{slot}",
            f'{{"text": "{slot} is owed money by {slot}."}}',
        ):
            v = SCREEN.scan(text)
            assert not v.blocked, (text, v.rule_names)
            assert v.reason == "OK"

    def test_abstract_payload_with_many_slots_and_stats(self):
        text = (
            "⟦SLOT:ORG_1a2b3c4d⟧ -> cancelled ⟦SLOT:PROJECT_5e6f7a8b⟧ after "
            "⟦SLOT:PERSON_9c0d1e2f⟧ left on ⟦SLOT:DATE_3a4b5c6d⟧; revenue -12% "
            "(⟦SLOT:MONEY_7e8f9a0b⟧), 3 of 14 rows, v2.1.0, Q3 2026."
        )
        assert not SCREEN.scan(text).blocked

    def test_a_rule_that_would_match_slots_is_refused_at_construction(self):
        hex8 = RegexRule("hex8", re.compile(r"[0-9a-f]{8}"), "low")
        with pytest.raises(ValueError, match="hex8"):
            RegexScreen(rules=[*DEFAULT_RULES, hex8])

    def test_a_custom_term_that_would_match_slots_is_refused_at_construction(self):
        with pytest.raises(ValueError, match="custom_term"):
            RegexScreen(custom_terms=["slot"])
        # A category name as a term is fine: the underscore glues it to the hex.
        RegexScreen(custom_terms=["person", "money"])


class TestHashesAndVersionsDoNotFire:
    @pytest.mark.parametrize(
        "digest",
        [
            "da39a3ee5e6b4b0d3255bfef95601890afd80709",  # sha1, 40 hex
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",  # sha256
            "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855",
            "123e4567e89b42d3a456426614174000",  # a UUID without hyphens is not a UUID here
        ],
    )
    def test_hex_digests(self, digest: str):
        for text in (digest, f"sha: {digest}", f"{digest}\n", f"commit {digest} fixed it"):
            assert names(text) == (), text

    @pytest.mark.parametrize(
        "version",
        ["v1.2.3.4", "1.2.3", "2.1.0-rc1", "1.2.3.4.5", "Python 3.12.3", "trafilatura 2.0.0"],
    )
    def test_version_strings(self, version: str):
        assert names(f"requires {version} or later") == ()

    @pytest.mark.parametrize(
        "text",
        [
            "999.1.1.1", "192.168.1.256", "01.02.03.04", "12:30:45", "2026-09-06",
            "2026-09-06T12:30:45Z", "12.5%", "$1,234.56", "in 2026 and 1999", "16:9 and 3:2",
            "std::vector", "Note:: not an address", "00:1A:2B:3C:4D:5E", "see 3.2.1 and Fig. 4",
            "@handle and @dataclass", "email me @ the office.example", "task-runner-privacy",
            "deadbeef cafe babe", "09123456789", "091234567", "123456789012", "097123456789",
            "3.0101234567", "01012345678", "01012345670012", "",
        ],
    )
    def test_ordinary_numbers_and_punctuation(self, text: str):
        v = SCREEN.scan(text)
        assert not v.blocked, (text, v.rule_names)


class TestKnownFalsePositivesAreAsserted:
    """These document the stated false positives. If one stops firing, update the docstring."""

    def test_bare_dotted_quad_fires_as_ipv4(self):
        assert names("1.2.3.4") == ("ipv4",)

    def test_ten_digit_number_fires_as_tax_code(self):
        assert names("0112345678") == ("vn_tax_code",)  # not a mobile prefix
        assert "vn_mobile" not in names("0112345678")
        assert names("1725580800") == ("vn_tax_code",)  # epoch seconds

    def test_thirteen_digit_run_fires_as_tax_code(self):
        assert names("1725580800000") == ("vn_tax_code",)  # epoch milliseconds

    def test_mobile_number_is_also_a_tax_code(self):
        v = SCREEN.scan("0912345678")
        assert v.rule_names == ("vn_mobile", "vn_tax_code")
        assert v.total_hits == 2

    def test_hex_words_around_double_colon_fire_as_ipv6(self):
        assert names("de::ad") == ("ipv6",)


class TestCleanMegabyte:
    def test_zero_hits_and_timed(self):
        text = clean_prose()
        assert len(text) >= 1_000_000
        best = float("inf")
        for _ in range(3):
            t0 = time.perf_counter()
            v = SCREEN.scan(text)
            best = min(best, time.perf_counter() - t0)
        assert not v.blocked, v.rule_names
        assert v.total_hits == 0
        assert best < 0.1, f"1 MB scan took {best * 1000:.1f} ms"

    def test_custom_terms_do_not_change_the_bound(self):
        screen = RegexScreen(custom_terms=["Zephyr", "Project Nightjar", "Bình Dương", "zeta"])
        text = clean_prose()
        t0 = time.perf_counter()
        v = screen.scan(text)
        elapsed = time.perf_counter() - t0
        assert not v.blocked
        assert elapsed < 0.1, f"1 MB scan with custom terms took {elapsed * 1000:.1f} ms"

    def test_one_secret_in_a_megabyte_is_found(self):
        text = clean_prose()
        mid = len(text) // 2
        spiked = text[:mid] + " AKIAFAKEFAKEFAKEFAKE " + text[mid:]
        v = SCREEN.scan(spiked)
        assert v.rule_names == ("aws_access_key_id",)
        assert v.total_hits == 1


class TestCustomTerms:
    def test_whole_word_case_insensitive(self):
        s = RegexScreen(custom_terms=["Zephyr"])
        for text in ("zephyr", "ZEPHYR", "Project Zephyr.", "zephyr's budget", "(Zephyr)"):
            v = s.scan(text)
            assert v.blocked and v.rule_names == ("custom_term",), text

    def test_not_substrings(self):
        s = RegexScreen(custom_terms=["Zephyr"])
        for text in ("Zephyrs", "subzephyr", "zephyr_1", "xzephyrx", "zephyr2"):
            assert not s.scan(text).blocked, text

    def test_multi_word_term_matches_across_whitespace_runs(self):
        s = RegexScreen(custom_terms=["Project Nightjar"])
        assert s.scan("the project   nightjar review").blocked
        assert s.scan("the project\nnightjar review").blocked
        assert not s.scan("project nightjars").blocked
        assert not s.scan("projectnightjar").blocked

    def test_non_ascii_term(self):
        s = RegexScreen(custom_terms=["Bình Dương"])
        assert s.scan("Đại học BÌNH DƯƠNG").blocked
        assert not s.scan("Bình Dươngx").blocked

    def test_terms_sharing_a_first_letter_and_prefixes(self):
        s = RegexScreen(custom_terms=["zephyr", "zeta", "zephyr project"])
        assert s.scan("zeta").total_hits == 1
        assert s.scan("zephyr").total_hits == 1
        assert s.scan("zephyr project").total_hits == 1  # longest wins, counted once
        assert s.scan("zeta and zephyr").total_hits == 2

    def test_counts_every_occurrence(self):
        s = RegexScreen(custom_terms=["zephyr"])
        assert s.scan("zephyr, Zephyr; ZEPHYR").total_hits == 3

    def test_custom_and_default_rules_combine(self):
        s = RegexScreen(custom_terms=["zephyr"])
        v = s.scan("zephyr owes 0101234567")
        assert v.rule_names == ("vn_tax_code", "custom_term")
        assert v.total_hits == 2

    def test_duplicates_are_folded_and_count_is_exposed(self):
        s = RegexScreen(custom_terms=["Zephyr", "zephyr", "  ZEPHYR ", "zeta"])
        assert s.custom_term_count == 2

    def test_empty_dictionary_is_fine(self):
        assert RegexScreen(custom_terms=[]).custom_term_count == 0
        assert RegexScreen(custom_terms=()).scan("zephyr").blocked is False

    def test_bad_terms_are_refused(self):
        with pytest.raises(ValueError):
            RegexScreen(custom_terms=[""])
        with pytest.raises(ValueError):
            RegexScreen(custom_terms=["   "])
        with pytest.raises(TypeError):
            RegexScreen(custom_terms=[b"zephyr"])  # type: ignore[list-item]

    def test_regex_metacharacters_in_terms_are_literal(self):
        s = RegexScreen(custom_terms=["a.b (c)"])
        assert s.scan("A.B (C)").blocked
        assert not s.scan("axb (c)").blocked


class TestVerdictAndRule:
    def test_reason_carries_counts_and_names_only(self):
        value = "AKIAFAKEFAKEFAKEFAKE"
        v = SCREEN.scan(f"key {value} and user@example.invalid")
        assert v.reason == "SECRET_PATTERN: 2 hit(s) across rules aws_access_key_id, email"
        assert value not in v.reason
        assert "example.invalid" not in v.reason

    def test_ok_reason(self):
        v = SCREEN.scan("nothing here")
        assert v == RegexVerdict(blocked=False, rule_names=(), total_hits=0)
        assert v.reason == "OK"

    def test_verdict_is_frozen(self):
        v = SCREEN.scan("x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            v.blocked = True  # type: ignore[misc]

    def test_rule_is_frozen_and_validated(self):
        r = RegexRule("x", re.compile("x"), "low")
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.name = "y"  # type: ignore[misc]
        with pytest.raises(ValueError):
            RegexRule("Bad Name", re.compile("x"), "low")
        with pytest.raises(ValueError):
            RegexRule("x", re.compile("x"), "urgent")
        with pytest.raises(TypeError):
            RegexRule("x", "x", "low")  # type: ignore[arg-type]

    def test_default_rules_are_well_formed(self):
        assert len({r.name for r in DEFAULT_RULES}) == len(DEFAULT_RULES)
        assert all(r.severity in SEVERITIES for r in DEFAULT_RULES)
        assert "custom_term" not in {r.name for r in DEFAULT_RULES}

    def test_duplicate_or_reserved_rule_names_are_refused(self):
        with pytest.raises(ValueError):
            RegexScreen(rules=[DEFAULT_RULES[0], DEFAULT_RULES[0]])
        with pytest.raises(ValueError):
            RegexScreen(rules=[RegexRule("custom_term", re.compile("zzz"), "low")])

    def test_screen_exposes_its_rules(self):
        assert SCREEN.rules == DEFAULT_RULES
        assert RegexScreen(rules=DEFAULT_RULES[:3]).rules == DEFAULT_RULES[:3]

    def test_scan_fits_the_gateway_extra_screen_protocol(self):
        v = SCREEN.scan("AKIAFAKEFAKEFAKEFAKE")
        assert isinstance(v.blocked, bool) and isinstance(v.reason, str)


FACTS = ["⟦FACT:0a1b2c3d.AUTHAMT⟧", "⟦FACT:ffffffff.SPENTAMT⟧", "⟦FACT:deadbeef.OWNERREF⟧",
         "⟦FACT:12345678.PCTSPENT⟧"]


class TestFactReferenceNeverFires:
    """R1's fact references cross the boundary like slot ids and get the same
    guarantees, in the same positions."""

    @pytest.mark.parametrize("fact", FACTS)
    def test_positions(self, fact: str):
        for text in (fact, f"Spend reached {fact} by August.", f"x{fact}y", f"{fact}'s share",
                     f"({fact}), [{fact}], \"{fact}\"", f"{fact}{fact}", f"{fact}\n{fact}",
                     f'{{"text": "{fact} against {fact}"}}'):
            v = SCREEN.scan(text)
            assert not v.blocked, (text, v.rule_names)

    def test_a_rule_that_would_match_fact_references_is_refused_at_construction(self):
        """This rule constructed cleanly before the fact probe existed, and then
        refused every FACT payload."""
        hex8dot = RegexRule("hex8dot", re.compile(r"[0-9a-f]{8}\.[A-Z]+"), "low")
        with pytest.raises(ValueError, match="fact reference"):
            RegexScreen(rules=[*DEFAULT_RULES, hex8dot])

    @pytest.mark.parametrize("term", ["fact", "authamt", "ownerref", "statnote", "commqty"])
    def test_an_attribute_code_cannot_be_added_as_a_custom_term(self, term):
        with pytest.raises(ValueError):
            RegexScreen(custom_terms=[term])
