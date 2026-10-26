"""Tests for the false-positive instrument, scripts/measure_false_positives.py.

These pin the properties that make the report citable: the corpus is a pure
function of the seed; the private document shares no 5-gram with the clean
corpus (checked here by brute force, independently of the harness's own
check); the positive control catches every private sentence; the interval
arithmetic is right; every registered linter appears in the report; slot
placeholders are refused by no linter; and nothing private reaches the report.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from privdeep.models.document import SLOT_CATEGORIES as BACKEND_SLOT_CATEGORIES

from scripts import measure_false_positives as mfp
from shared.shingle_filter import _tokenize as filter_tokenize

SEED = mfp.DEFAULT_SEED


@pytest.fixture(scope="module")
def corpus() -> tuple[mfp.Payload, ...]:
    return mfp.build_corpus(SEED)


@pytest.fixture(scope="module")
def fixture(corpus) -> tuple[mfp.RunFixture, mfp.PrivateDocument]:
    return mfp.build_fixture(SEED, corpus)


@pytest.fixture(scope="module")
def report(tmp_path_factory) -> tuple[dict, Path]:
    out = tmp_path_factory.mktemp("fp") / "fp_report.json"
    return mfp.main(SEED, out, quiet=True), out


class TestCorpus:
    def test_deterministic_under_the_seed(self, corpus):
        again = mfp.build_corpus(SEED)
        assert again == corpus
        assert mfp.corpus_fingerprint(again) == mfp.corpus_fingerprint(corpus)

    def test_different_seed_gives_a_different_corpus(self, corpus):
        other = mfp.build_corpus(SEED + 1)
        assert mfp.corpus_fingerprint(other) != mfp.corpus_fingerprint(corpus)

    def test_size_and_strata(self, corpus):
        assert len(corpus) >= 400
        per = {s: sum(1 for p in corpus if p.stratum == s) for s in mfp.STRATA}
        assert all(n == mfp.N_PER_STRATUM for n in per.values()), per
        assert set(mfp.STRATA) >= {
            "english_prose", "abstract_json", "code_snippet", "vietnamese_prose"
        }

    def test_five_grams_are_diverse(self, corpus):
        """A degenerate grammar would make the shingle measurement meaningless."""
        total, distinct = 0, set()
        for p in corpus:
            toks = mfp.tokenize(p.text)
            total += max(0, len(toks) - 4)
            distinct |= mfp.ngrams(toks, 5)
        assert len(distinct) / total > 0.3, f"{len(distinct)}/{total} distinct 5-grams"

    def test_no_real_hosts_in_payloads(self, corpus):
        for p in corpus:
            assert ".com" not in p.text and ".org" not in p.text and ".vn" not in p.text
            if "://" in p.text:
                assert ".invalid" in p.text

    def test_tokenizer_matches_the_filters(self, corpus):
        """The disjointness guarantee is stated in the filter's own tokens."""
        for p in corpus[::25]:
            assert mfp.tokenize(p.text) == filter_tokenize(p.text)

    def test_slot_categories_match_the_backend(self):
        assert mfp.SLOT_CATEGORIES == BACKEND_SLOT_CATEGORIES


class TestPrivateDocument:
    def test_shape(self, fixture):
        fx, doc = fixture
        assert doc.n_words >= mfp.PRIVATE_DOC_WORDS
        assert len(doc.sentences) >= 20
        assert all(len(mfp.tokenize(s)) >= fx.n_min for s in doc.sentences)
        assert doc.text == " ".join(doc.sentences)

    @pytest.mark.security
    @pytest.mark.parametrize("seed", [SEED, 1, 7, 12345])
    def test_shares_no_five_gram_with_the_clean_corpus(self, seed):
        """Brute force, independent of the harness's own check, over several seeds."""
        corpus = mfp.build_corpus(seed)
        _, doc = mfp.build_fixture(seed, corpus)
        private = set()
        toks = filter_tokenize(doc.text)
        for i in range(len(toks) - 4):
            private.add(tuple(toks[i : i + 5]))
        for p in corpus:
            t = filter_tokenize(p.text)
            for i in range(len(t) - 4):
                assert tuple(t[i : i + 5]) not in private, f"shared 5-gram in {p.stratum}#{p.index}"

    def test_positive_control_catch_rate_is_one(self, fixture):
        fx, _ = fixture
        pc = mfp.positive_control(fx)
        assert pc.n == len(fx.private_sentences)
        assert pc.refusals == pc.n
        assert pc.rate == 1.0

    def test_verbatim_span_from_the_private_doc_is_caught(self, fixture):
        """The filter built here behaves as the gateway's does: a copied span is refused."""
        fx, doc = fixture
        toks = doc.sentences[0].split()
        assert fx.shingle.inspect("Background: " + " ".join(toks[:6]) + ", apparently.").blocked


class TestWilson:
    def test_known_case_zero_of_four_hundred(self):
        lo, hi = mfp.wilson_interval(0, 400)
        assert lo == 0.0
        assert abs(hi - 0.00951) < 1e-4, hi

    def test_symmetry_at_one_half(self):
        lo, hi = mfp.wilson_interval(200, 400)
        assert abs((lo + hi) / 2 - 0.5) < 1e-12
        assert abs(hi - 0.5486) < 1e-3

    def test_all_refused_mirrors_none_refused(self):
        lo0, hi0 = mfp.wilson_interval(0, 400)
        lo1, hi1 = mfp.wilson_interval(400, 400)
        assert hi1 == 1.0 and abs(lo1 - (1 - hi0)) < 1e-12 and lo0 == 0.0

    def test_rejects_bad_inputs(self):
        with pytest.raises(ValueError):
            mfp.wilson_interval(0, 0)
        with pytest.raises(ValueError):
            mfp.wilson_interval(5, 4)


class TestReport:
    def test_has_every_registry_entry(self, report):
        rep, _ = report
        assert list(rep["linters"]) == [name for name, _ in mfp.REGISTRY]
        for name, _ in mfp.REGISTRY:
            entry = rep["linters"][name]
            assert entry["n"] == rep["corpus"]["n_payloads"]
            assert set(entry["by_stratum"]) == set(mfp.STRATA)
            assert 0.0 <= entry["wilson95"][0] <= entry["rate"] <= entry["wilson95"][1] <= 1.0

    def test_registry_append_reaches_the_report_in_one_line(self, monkeypatch, tmp_path):
        class Always:
            blocked = True
            reason = "STUB_RULE: 1 thing"

        extra = ("stub", lambda _fx: lambda _t: Always())
        monkeypatch.setattr(mfp, "REGISTRY", [*mfp.REGISTRY, extra])
        rep = mfp.main(SEED, tmp_path / "r.json", n_per_stratum=10, quiet=True)
        assert "stub" in rep["linters"]
        stub = rep["linters"]["stub"]
        assert stub["refusals"] == stub["n"] == 10 * len(mfp.STRATA)
        assert stub["rate"] == 1.0 and stub["wilson95"][1] == 1.0
        assert stub["rules_fired"] == {"STUB_RULE": stub["n"]}

    def test_written_file_matches_returned_dict(self, report):
        rep, out = report
        assert json.loads(out.read_text(encoding="utf-8")) == rep

    def test_control_and_disjointness_are_recorded(self, report):
        rep, _ = report
        assert rep["positive_control"]["catch_rate"] == 1.0
        assert rep["positive_control"]["caught"] == rep["positive_control"]["n_sentences"]
        assert rep["disjointness"] == {"n": mfp.SHINGLE_N_MIN, "shared": 0}

    def test_bloom_estimate_sits_beside_the_empirical_rate(self, report):
        rep, _ = report
        b = rep["shingle_filter"]
        assert 0.0 < b["estimated_fp_rate_per_shingle"] < 1e-5
        assert b["implied_fp_rate_per_payload"] >= b["estimated_fp_rate_per_shingle"]
        # The empirical bound is coarse; the estimate must lie inside it.
        lo, hi = rep["linters"]["shingle"]["wilson95"]
        assert lo <= b["implied_fp_rate_per_payload"] <= hi

    def test_nothing_private_reaches_the_report(self, report, fixture, corpus):
        rep, out = report
        text = out.read_text(encoding="utf-8")
        _, doc = fixture
        for name in mfp._PERSONS + mfp._ORGS + mfp._PLACES + mfp._CODENAMES:
            assert name not in text
        assert "⟦" not in text
        for sentence in doc.sentences:
            assert sentence not in text
        for p in corpus[::10]:
            assert p.text not in text

    def test_report_is_not_written_when_the_control_fails(self, monkeypatch, tmp_path):
        broken = lambda fx: mfp.RateReport(len(fx.private_sentences), 0)  # noqa: E731
        monkeypatch.setattr(mfp, "positive_control", broken)
        out = tmp_path / "never.json"
        with pytest.raises(RuntimeError, match="positive control"):
            mfp.main(SEED, out, n_per_stratum=5, quiet=True)
        assert not out.exists()


@pytest.mark.security
class TestSlotPlaceholders:
    """The one legitimate egress token that looks like an identifier."""

    def test_no_registered_linter_refuses_a_slot_placeholder(self, fixture):
        fx, _ = fixture
        ids = [f"⟦SLOT:{c}_{i:08x}⟧" for i, c in enumerate(mfp.SLOT_CATEGORIES, start=0xA1B2C3D4)]
        bare = " ".join(ids)
        pairs = zip(ids, mfp.SLOT_CATEGORIES, strict=True)
        shipped = json.dumps(
            {"slots": [{"id": s, "category": c} for s, c in pairs]}, ensure_ascii=False, indent=2
        )
        for name, factory in mfp.REGISTRY:
            linter = factory(fx)
            assert not linter(bare).blocked, f"{name} refused bare slot placeholders"
            assert not linter(shipped).blocked, f"{name} refused the shipped slot form"

    def test_abstract_json_stratum_has_zero_refusals_for_every_linter(self, report):
        rep, _ = report
        for name, entry in rep["linters"].items():
            assert entry["by_stratum"]["abstract_json"]["refusals"] == 0, name


class TestMeasuredFindings:
    """Findings the run surfaced. Pinned so a change in either direction is noticed."""

    def test_entropy_screen_refuses_compact_json(self, report):
        """One whitespace-free token of ~900 chars at ~5.2 bits/char. Not a tuning accident:
        the builder's indent=2 is what keeps the shipped form under the threshold."""
        rep, _ = report
        compact = rep["linters"]["entropy"]["by_stratum"]["abstract_json_compact"]
        assert compact["refusals"] == compact["n"]
        assert rep["linters"]["entropy"]["by_stratum"]["abstract_json"]["refusals"] == 0

    def test_shingle_filter_refuses_nothing_clean(self, report):
        rep, _ = report
        assert rep["linters"]["shingle"]["refusals"] == 0
        assert rep["linters"]["shingle"]["wilson95"][1] < 0.01

    def test_measured_deployed_rates(self, report):
        """On this corpus the deployed chain is the union of the standalone entropy
        and regex refusals, and accumulating the carry over a stratum adds nothing."""
        rep, _ = report
        for mode in mfp.CARRY_MODES:
            by = rep["deployed_chain"]["modes"][mode]["by_stratum"]
            assert by["abstract_json_compact"]["refusals"] == 100
            assert by["code_snippet"]["refusals"] == 22
            for s in ("english_prose", "abstract_json", "vietnamese_prose"):
                assert by[s]["refusals"] == 0, (mode, s)


class TestDeployedChain:
    """EXP5 / X3: the payloads through gateway main's live path, not the linters alone.

    The live handler decodes the request body and runs `_inspect_text` with the
    carry advancing. These pin that the instrument drives that path, that the
    two carry modes are really different experiments, and that it leaves the
    imported gateway module as it found it.
    """

    def test_both_carry_modes_cover_every_stratum(self, report):
        rep, _ = report
        dc = rep["deployed_chain"]
        assert list(dc["modes"]) == list(mfp.CARRY_MODES)
        for mode, entry in dc["modes"].items():
            assert entry["mode"] == mode
            assert entry["n"] == rep["corpus"]["n_payloads"]
            assert set(entry["by_stratum"]) == set(mfp.STRATA)
            assert entry["refusals"] == sum(r["refusals"] for r in entry["by_stratum"].values())

    def test_only_independent_payloads_get_an_interval(self, report):
        rep, _ = report
        reset, session = (rep["deployed_chain"]["modes"][m] for m in mfp.CARRY_MODES)
        lo, hi = reset["wilson95"]
        assert lo <= reset["rate"] <= hi
        assert session["wilson95"] is None and "not independent" in session["note"]
        assert all(r["wilson95"] is None for r in session["by_stratum"].values())

    def test_positive_control_through_the_chain_is_one(self, report):
        rep, _ = report
        dpc = rep["deployed_chain"]["positive_control"]
        assert dpc["caught"] == dpc["n_sentences"] == rep["positive_control"]["n_sentences"]
        assert dpc["catch_rate"] == 1.0

    def test_the_gateway_policy_in_force_is_recorded(self, report):
        rep, _ = report
        cfg = rep["deployed_chain"]["config"]
        assert "_inspect_text" in cfg["entry"] and "_decoded_text" in cfg["entry"]
        assert cfg["canaries_registered"] == mfp.N_CANARIES
        assert cfg["extra_screens"] == ["RegexScreen"]
        assert cfg["shingle"]["n_added"] == rep["private_doc"]["n_shingles_indexed"]

    def test_the_commit_is_recorded(self, report):
        rep, _ = report
        g = rep["git"]
        assert g["commit"] == "unknown" or len(g["commit"]) == 40
        assert g["dirty"] in (True, False, None)

    def test_envelope_is_what_the_gateway_decodes_back_to_the_payload(self):
        import main as gw
        text = "Nguyễn Thị Lan — ⟦SLOT:PERSON_0a1b2c3d⟧"
        raw = mfp.envelope(text)
        assert text.encode("utf-8") in raw, "the core does not ASCII-escape"
        decoded, parsed = gw._decoded_text(raw)
        assert parsed["messages"][0]["content"] == text
        assert text in decoded.split("\n")

    def test_session_carry_catches_what_reset_cannot(self, fixture):
        """A private span split four tokens per payload: invisible one payload at a
        time, refused once the second payload chains to the first on the same path."""
        fx, _ = fixture
        toks = mfp.tokenize(fx.private_sentences[0])
        halves = (" ".join(toks[:4]), " ".join(toks[4:8]))
        split = tuple(mfp.Payload("english_prose", i, h) for i, h in enumerate(halves))
        with mfp._deployed_monitor(fx) as gw:
            reset = mfp._deployed_mode(gw, split, "reset_per_payload")
            session = mfp._deployed_mode(gw, split, "session_per_stratum")
            across = mfp._deployed_mode(
                gw, (mfp.Payload("english_prose", 0, halves[0]),
                     mfp.Payload("vietnamese_prose", 0, halves[1])), "session_per_stratum")
        assert reset["refusals"] == 0
        assert session["refusals"] == 1
        assert session["rules_fired"] == {"RAW_CONTEXT_CONTAINMENT": 1}
        assert across["refusals"] == 0, "each stratum must start its own session"

    def test_the_gateway_module_is_left_as_found(self, fixture, monkeypatch):
        import main as gw
        fx, _ = fixture
        sentinel_carry = {"$.x": ["a"]}
        monkeypatch.setattr(gw, "_shingle", None)
        monkeypatch.setattr(gw, "_carry", sentinel_carry)
        monkeypatch.setattr(gw, "SHINGLE_HMAC_SALT", b"")
        canaries = gw._canaries
        mfp.deployed_chain(fx, mfp.build_corpus(SEED, 2))
        assert gw._shingle is None and gw._carry is sentinel_carry
        assert gw.SHINGLE_HMAC_SALT == b"" and gw._canaries is canaries

    def test_report_is_not_written_when_the_deployed_control_fails(self, monkeypatch, tmp_path):
        def broken(gw, fx):
            return {"n_sentences": len(fx.private_sentences), "caught": 0,
                    "catch_rate": 0.0, "rules_fired": {}}
        monkeypatch.setattr(mfp, "_deployed_positive_control", broken)
        out = tmp_path / "never.json"
        with pytest.raises(RuntimeError, match="deployed chain"):
            mfp.main(SEED, out, n_per_stratum=5, quiet=True)
        assert not out.exists()
