"""Four ways the reference monitor was got past, each now a regression test.

Every case here was reproduced against the shipped code before it was fixed,
by driving the real chain with a real sealed filter. They are grouped in one
file because they share a cause: the monitor was deciding what to look at, and
each decision left a place to put the corpus.

* **Position in the body.** `_string_leaves` walked `dict.values()` only, on
  the reasoning that "keys are schema, not content". A private sentence used
  as an object key gave an inspected text of `'string'` and passed all four
  screens. The Messages API has attacker-choosable key positions in every
  request that carries a tool definition, and the planner sends one.
* **Split across requests.** Shingles are contiguous, so a filter shown one
  request at a time cannot see a run spread over several. A 26-token passage
  in seven 4-token requests crossed 7/7. The pipeline already issues one
  request per section, so this is the ordinary traffic shape.
* **Spelling.** The tokeniser casefolded and nothing else, so NFD Vietnamese,
  one Cyrillic homoglyph, fullwidth Latin, or a zero-width space inside a word
  each produced tokens that missed the index while reading identically.
* **The seal itself.** `hit_threshold` came off the wire unvalidated. A wire
  with `10**9` sealed cleanly, left `n_added` intact so the core's own
  confirmation passed, reported `sealed` on `/health`, and admitted everything.

The last one is the one to keep in mind when reading the others: it is not a
parsing bug, it is a reference monitor taking its policy from the party it
monitors.
"""

from __future__ import annotations

import json
import unicodedata

import httpx
import main
import pytest
from fastapi.testclient import TestClient

from shared.shingle_filter import ShingleFilter, tokenize

SALT = b"bypass-test-salt"
PRIVATE = ("Project Zephyr's Q3 revenue fell twelve percent after the Hanoi pilot was "
           "cancelled. The board approved a further eight hundred thousand dollars of "
           "contingency funding.")
VIETNAMESE = "Nguyễn Thị Lan phụ trách dự án Hà Nội"


def upstream(req: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"id": "m", "content": [{"type": "text", "text": "ok"}]},
                          headers={"content-type": "application/json"})


def _client(monkeypatch, tmp_path, document: str) -> TestClient:
    monkeypatch.setattr(main, "SHINGLE_HMAC_SALT", SALT)
    monkeypatch.setattr(main, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(main, "ANTHROPIC_BASE_URL", "https://api.anthropic.invalid")
    monkeypatch.setattr(main, "AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(main, "_shingle", None)
    monkeypatch.setattr(main, "_carry", {})
    monkeypatch.setattr(main, "_carry_last", {})
    monkeypatch.setattr(main, "_canaries", type(main._canaries)())
    monkeypatch.setattr(main, "_EXTRA_SCREENS", [])
    monkeypatch.setattr(main, "_upstream",
                        httpx.AsyncClient(transport=httpx.MockTransport(upstream)))
    c = TestClient(main.app)
    f = ShingleFilter(salt=SALT, n_min=main.SHINGLE_N_MIN, n_max=main.SHINGLE_N_MAX)
    f.index_document(document)
    f.seal()
    assert c.post("/containment/seal", content=f.to_wire()).json()["sealed"]
    return c


@pytest.fixture
def gw(monkeypatch, tmp_path):
    return _client(monkeypatch, tmp_path, PRIVATE)


def body(text: str) -> dict:
    """A realistic Messages body. The extra string values matter: `model` and
    `role` are what broke a single-stream carry, because their tokens landed
    between the chunks and ended the run at every join."""
    return {"model": "claude-sonnet-5", "max_tokens": 64,
            "messages": [{"role": "user", "content": text}]}


def refused(r: httpx.Response) -> bool:
    return r.status_code == 403 and "RAW_CONTEXT_CONTAINMENT" in r.json().get("reason", "")


class TestPositionInTheBody:
    def test_private_text_as_a_json_object_key_is_refused(self, gw):
        payload = {"model": "claude-sonnet-5", "max_tokens": 64, "messages": [],
                   "tools": [{"name": "t", "input_schema": {"properties": {PRIVATE: {}}}}]}
        assert refused(gw.post("/v1/messages", json=payload))

    def test_private_text_as_a_deeply_nested_key_is_refused(self, gw):
        assert refused(gw.post("/v1/messages", json={"a": {"b": [{PRIVATE: 1}]}}))

    def test_key_and_value_are_separate_streams(self, gw):
        """A key must not be able to complete a run started in a value, or the
        schema noise between content fields comes back as a false refusal."""
        toks = tokenize(PRIVATE)
        payload = {"messages": [{"content": " ".join(toks[:3])}],
                   " ".join(toks[3:6]): "x"}
        assert gw.post("/v1/messages", json=payload).status_code == 200


class TestSplitAcrossRequests:
    @pytest.mark.parametrize("chunk", [4, 2, 1])
    def test_a_passage_split_over_requests_is_refused_at_n_min(self, gw, chunk):
        toks = tokenize(PRIVATE)
        chunks = [" ".join(toks[i:i + chunk]) for i in range(0, len(toks), chunk)]
        verdicts = [gw.post("/v1/messages", json=body(c)) for c in chunks]
        assert any(refused(v) for v in verdicts), "the whole passage crossed one chunk at a time"
        # The run becomes visible exactly when the n_min'th token arrives, and
        # not before: an earlier refusal would mean sub-n_min spans are being
        # blocked, which is a false-positive rate the paper measured as zero.
        first = next(i for i, v in enumerate(verdicts) if refused(v))
        assert (first + 1) * chunk >= main.SHINGLE_N_MIN
        assert first * chunk < main.SHINGLE_N_MIN

    def test_unrelated_turns_do_not_accumulate_into_a_refusal(self, gw):
        """The carry must join content, not manufacture it."""
        turns = ["Summarise the market outlook for renewable energy across the region.",
                 "Now add a paragraph on grid interconnection costs and delivery timelines.",
                 "Finally list three risks to the deployment schedule for the coming year."]
        assert all(gw.post("/v1/messages", json=body(t)).status_code == 200 for t in turns)

    def test_inspect_is_a_dry_run_and_does_not_move_the_carry(self, gw):
        """`/inspect` must not be able to prime or poison the live path."""
        toks = tokenize(PRIVATE)
        for _ in range(3):
            gw.post("/inspect", json=body(" ".join(toks[:4])))
        assert gw.post("/v1/messages", json=body(" ".join(toks[4:8]))).status_code == 200

    def test_sealing_starts_a_new_session_and_clears_the_carry(self, gw):
        toks = tokenize(PRIVATE)
        assert gw.post("/v1/messages", json=body(" ".join(toks[:4]))).status_code == 200
        f = ShingleFilter(salt=SALT, n_min=main.SHINGLE_N_MIN, n_max=main.SHINGLE_N_MAX)
        f.index_document(PRIVATE)
        f.seal()
        assert gw.post("/containment/seal", content=f.to_wire()).json()["sealed"]
        assert gw.post("/v1/messages", json=body(" ".join(toks[4:8]))).status_code == 200


class TestSpelling:
    """Each of these reads identically to the indexed text and used to cross."""

    def test_decomposed_vietnamese_is_refused(self, monkeypatch, tmp_path):
        gw = _client(monkeypatch, tmp_path, unicodedata.normalize("NFC", VIETNAMESE))
        sent = unicodedata.normalize("NFD", VIETNAMESE)
        assert sent != unicodedata.normalize("NFC", VIETNAMESE)
        assert refused(gw.post("/v1/messages", json=body(sent)))

    @pytest.mark.parametrize("mangle, label", [
        (lambda s: s.replace("e", "е"), "cyrillic homoglyph"),
        (lambda s: "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in s),
         "fullwidth latin"),
        (lambda s: " ".join(w[:2] + "​" + w[2:] for w in s.split()), "zero-width space"),
        (lambda s: " ".join(w[:2] + "­" + w[2:] for w in s.split()), "soft hyphen"),
    ])
    def test_visually_identical_rewrites_are_refused(self, gw, mangle, label):
        sent = mangle(PRIVATE)
        assert sent != PRIVATE, label
        assert refused(gw.post("/v1/messages", json=body(sent))), label


class TestTheSealItself:
    def _wire(self, **header_overrides) -> bytes:
        f = ShingleFilter(salt=SALT, n_min=main.SHINGLE_N_MIN, n_max=main.SHINGLE_N_MAX)
        f.index_document(PRIVATE)
        f.seal()
        head, rest = f.to_wire().split(b"\n", 1)
        h = json.loads(head)
        h.update(header_overrides)
        return json.dumps(h).encode() + b"\n" + rest

    def test_a_wire_supplied_threshold_does_not_become_policy(self, gw):
        r = gw.post("/containment/seal", content=self._wire(hit_threshold=10**9))
        assert r.json()["sealed"]
        assert r.json()["hit_threshold"] == main.SHINGLE_HIT_THRESHOLD
        assert refused(gw.post("/v1/messages", json=body(PRIVATE)))

    def test_shingle_lengths_that_disagree_with_policy_are_refused(self, gw):
        r = gw.post("/containment/seal", content=self._wire(n_min=2, n_max=3))
        assert r.status_code == 422 and "BAD_WIRE" in r.json()["reason"]

    def test_an_empty_filter_does_not_seal(self, gw):
        f = ShingleFilter(salt=SALT, n_min=main.SHINGLE_N_MIN, n_max=main.SHINGLE_N_MAX)
        f.seal()
        r = gw.post("/containment/seal", content=f.to_wire())
        assert r.status_code == 422

    def test_a_refused_seal_leaves_the_previous_filter_in_force(self, gw):
        gw.post("/containment/seal", content=self._wire(n_min=2, n_max=3))
        assert refused(gw.post("/v1/messages", json=body(PRIVATE)))

    @pytest.mark.parametrize("bad", [0, -1])
    def test_the_constructor_refuses_a_threshold_below_one(self, bad):
        with pytest.raises(ValueError, match="hit_threshold"):
            ShingleFilter(salt=SALT, hit_threshold=bad)


class TestWhatIsStillNotCaught:
    """Pinned as misses, so the claim cannot silently strengthen or weaken.

    Both are encodings: the bytes no longer contain the words, so no
    word-shingle filter can see them. THREAT_MODEL.md says so under what is
    not protected. If either ever starts being caught, this file goes red and
    the document is what has to change.
    """

    @pytest.mark.xfail(strict=True, reason="per-character integers carry no words to shingle")
    def test_private_text_as_an_array_of_codepoints(self, gw):
        payload = {"messages": [{"content": "see below"}], "x": [ord(c) for c in PRIVATE]}
        assert refused(gw.post("/v1/messages", json=payload))

    @pytest.mark.xfail(strict=True, reason="hex is an encoding; entropy screen cannot reach it")
    def test_private_text_hex_encoded(self, gw):
        assert refused(gw.post("/v1/messages", json=body(PRIVATE.encode().hex())))


class TestScatteredAcrossFields:
    """A per-path carry is a stream the sender names, so per-path alone is a
    regression: it chains across requests but stops chaining across fields. The
    whole-body content stream is what covers this, and it is the check the
    pre-carry monitor already had."""

    def test_a_span_split_across_invented_top_level_keys_is_refused(self, gw):
        toks = tokenize(PRIVATE)
        payload = {"model": "claude-sonnet-5", "max_tokens": 1}
        for i in range(0, len(toks), 4):
            payload[f"field_{i:02d}"] = " ".join(toks[i:i + 4])
        assert refused(gw.post("/v1/messages", json=payload))

    def test_a_span_split_across_system_and_messages_is_refused(self, gw):
        toks = tokenize(PRIVATE)
        payload = {"model": "claude-sonnet-5", "system": " ".join(toks[:4]),
                   "messages": [{"role": "user", "content": " ".join(toks[4:9])}]}
        assert refused(gw.post("/v1/messages", json=payload))

    def test_a_span_split_across_two_messages_is_refused(self, gw):
        toks = tokenize(PRIVATE)
        payload = {"model": "claude-sonnet-5", "messages": [
            {"role": "user", "content": " ".join(toks[:3])},
            {"role": "assistant", "content": " ".join(toks[3:8])}]}
        assert refused(gw.post("/v1/messages", json=payload))


class TestSchemaConstantsDoNotAccumulate:
    """The carry must join content, never manufacture it. Chaining a path to a
    value identical to the one already in its carry built a five-token run out
    of `"role": "user"` repeated across requests, and because a refusal freezes
    the carry, the session then refused everything forever."""

    def test_a_repeated_constant_does_not_build_a_run(self, monkeypatch, tmp_path):
        gw = _client(monkeypatch, tmp_path, "user user user user user assistant")
        for i in range(6):
            r = gw.post("/v1/messages", json=body(f"Section {i} please."))
            assert r.status_code == 200, f"request {i} refused on a repeated schema constant"


class TestInvisibleCharacterCoverage:
    """The first ignorable set enumerated the obvious ranges and missed four
    whole classes. One of them inside every word moved the corpus across."""

    @pytest.mark.parametrize("cp, name", [
        ("­", "SOFT HYPHEN"),
        ("͏", "COMBINING GRAPHEME JOINER"),
        ("؜", "ARABIC LETTER MARK"),
        ("᠋", "MONGOLIAN FREE VARIATION SELECTOR ONE"),
        ("​", "ZERO WIDTH SPACE"),
        ("⁠", "WORD JOINER"),
        ("️", "VARIATION SELECTOR-16"),
        ("﻿", "ZERO WIDTH NO-BREAK SPACE"),
        ("\U000e0101", "VARIATION SELECTOR-18"),
    ])
    def test_an_invisible_inside_every_word_is_still_refused(self, gw, cp, name):
        sent = " ".join(w[:1] + cp + w[1:] for w in PRIVATE.split())
        assert sent != PRIVATE
        assert refused(gw.post("/v1/messages", json=body(sent))), name
