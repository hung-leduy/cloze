"""Tracing captures every exchange; the adversary is scored locally; rates only."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from privdeep.eval.reconstruction import reconstruct, score
from privdeep.models.document import Document, DocumentKind
from privdeep.pipeline import run_pipeline
from privdeep.tier1_local.slm_client import AsyncSLMClient
from privdeep.tier1_local.slot_masker import Entity
from privdeep.tier2_cloud.cloud_client import CloudClient
from privdeep.tier2_cloud.tracing import TracingCloudClient
from privdeep.tier3_reconcile.evidence_bank import EvidenceBank

from .test_pipeline import ENTS, GW_SALT, SALT, TEXT, GatewayScript, slm_handler

DOC = Document("d1", DocumentKind.MARKDOWN, Path("d1.md"), TEXT)


def run(c):
    return asyncio.run(c)


class TestTracing:
    def test_pipeline_trace_records_every_cloud_exchange_and_no_private_value(self, monkeypatch):
        monkeypatch.setenv("SHINGLE_HMAC_SALT", GW_SALT.decode())
        gw = GatewayScript()
        slm = AsyncSLMClient("http://local-slm:11434", transport=httpx.MockTransport(slm_handler))
        cloud = CloudClient("http://reference-monitor:5050", transport=httpx.MockTransport(gw))
        res = run(run_pipeline([DOC], "Assess Q3.", slm=slm, cloud=cloud,
                               gateway_url="http://reference-monitor:5050",
                               evidence=EvidenceBank(),
                               gw_client=httpx.Client(transport=httpx.MockTransport(gw)),
                               session_salt=SALT))
        stages = [e["stage"] for e in res.trace]
        assert stages == ["plan", "draft:s1", "draft:s2", "draft:s3"]
        assert res.trace[0]["structured"] is not None          # the tool-use plan
        assert res.trace[2]["refused"].startswith("RAW_CONTEXT_CONTAINMENT")
        blob = json.dumps(res.trace, ensure_ascii=False)
        for e in ENTS:
            assert e.text not in blob, "the trace is what crossed; it must carry no value"
        assert "⟦SLOT:" in blob

    def test_wrapper_relabels_and_passes_kwargs_through(self):
        seen = {}

        def h(req):
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json={
                "id": "m", "type": "message", "role": "assistant", "model": "m-x",
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1}})
        t = TracingCloudClient(CloudClient("http://gw", transport=httpx.MockTransport(h)))
        t.label("probe")
        r = run(t.messages([{"role": "user", "content": "x"}], system="S", max_tokens=7))
        assert r.text == "ok" and t.model == "claude-sonnet-5"
        assert seen["body"]["system"] == "S" and seen["body"]["max_tokens"] == 7
        assert t.entries[0].stage == "probe" and t.entries[0].resolved_model == "m-x"


class TestScoring:
    def test_entity_and_fivegram_recovery(self):
        out = ("The document concerned project zephyr in HANOI. Revenue fell twelve percent "
               "after the Hanoi pilot was cancelled in August, it said.")
        r = score([DOC], ENTS, out, "adv")
        assert r.entities_total == 3 and r.entities_recovered == 2       # Zephyr, Hanoi; not Lan
        assert r.entity_recovery == 2 / 3
        assert r.by_category["PERSON"] == {"total": 1, "recovered": 0}
        assert r.by_category["PROJECT"] == {"total": 1, "recovered": 1}
        assert r.fivegrams_recovered >= 5 and 0 < r.fivegram_recovery < 1

    def test_nfd_output_still_matches_nfc_entity(self):
        import unicodedata
        out = unicodedata.normalize("NFD", "Nguyễn Thị Lan was named.")
        r = score([DOC], [Entity("Nguyễn Thị Lan", "PERSON")], out, "adv")
        assert r.entities_recovered == 1

    def test_empty_output_scores_zero(self):
        r = score([DOC], ENTS, "", "adv")
        assert r.entity_recovery == 0.0 and r.fivegram_recovery == 0.0


class TestAdversaryPath:
    def test_adversary_sees_only_the_trace_and_result_carries_rates_only(self):
        seen = {}

        def h(req):
            seen["body"] = json.loads(req.content)
            leak = "I believe the project is called Project Zephyr, based in Hanoi."
            return httpx.Response(200, json={
                "id": "m", "type": "message", "role": "assistant", "model": "adv-1",
                "content": [{"type": "text", "text": leak}],
                "usage": {"input_tokens": 1, "output_tokens": 1}})
        trace = [{"stage": "plan", "system": "S",
                  "messages": [{"role": "user", "content": "⟦SLOT:PROJECT_x⟧"}],
                  "structured": {"sections": []}, "response_text": None, "refused": None}]
        cloud = CloudClient("http://gw", transport=httpx.MockTransport(h))
        r = run(reconstruct([DOC], ENTS, trace, cloud))
        assert "⟦SLOT:PROJECT_x⟧" in seen["body"]["messages"][0]["content"]
        assert TEXT not in seen["body"]["messages"][0]["content"]
        assert r.entities_recovered == 2 and r.adversary_model == "adv-1"
        j = r.to_json()
        assert "Project Zephyr" not in j and "Hanoi" not in j and '"entity_recovery"' in j

    def test_monitor_refusal_scores_zero_and_is_noted(self):
        cloud = CloudClient("http://gw", transport=httpx.MockTransport(
            lambda r: httpx.Response(403, json={"allowed": False, "reason": "CANARY_TRIPPED: 1"})))
        r = run(reconstruct([DOC], ENTS, [], cloud))
        assert r.adversary_refused.startswith("CANARY_TRIPPED") and r.entity_recovery == 0.0
        assert r.notes


class TestTraceCap:
    """INS4. The pilot's r1 traces rendered 62,940-64,634 characters and were
    cut at the old 60,000 cap with nothing recording it, so the r1 lower bound
    was weaker than the others and no artifact said so."""

    @staticmethod
    def _trace(chars: int) -> list[dict]:
        words = " ".join(f"w{i}" for i in range(chars))[:chars]
        return [{"stage": "draft:s1", "system": None,
                 "messages": [{"role": "user", "content": words}],
                 "structured": None, "response_text": "ok", "refused": None}]

    @staticmethod
    def _cloud(seen: dict) -> CloudClient:
        def h(req):
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json={
                "id": "m", "type": "message", "role": "assistant", "model": "adv-1",
                "content": [{"type": "text", "text": "nothing"}],
                "usage": {"input_tokens": 16_500, "output_tokens": 700}})
        return CloudClient("http://direct", api_key="k", transport=httpx.MockTransport(h))

    def test_a_64k_character_trace_renders_untruncated(self):
        from privdeep.eval.reconstruction import TRACE_MAX_CHARS, _render_trace
        trace = self._trace(64_000)
        text = _render_trace(trace)
        assert "[trace truncated]" not in text
        assert trace[0]["messages"][0]["content"] in text
        assert TRACE_MAX_CHARS >= 120_000

    def test_the_adversary_is_shown_all_of_it_and_the_fields_say_so(self):
        seen: dict = {}
        trace = self._trace(64_000)
        r = run(reconstruct([DOC], ENTS, trace, self._cloud(seen)))
        prompt = seen["body"]["messages"][0]["content"]
        assert trace[0]["messages"][0]["content"] in prompt
        assert "[trace truncated]" not in prompt
        assert r.trace_chars > 64_000 and r.trace_truncated is False
        assert (r.adversary_tokens_in, r.adversary_tokens_out) == (16_500, 700)
        j = json.loads(r.to_json())
        assert j["trace_chars"] == r.trace_chars and j["trace_truncated"] is False
        assert j["adversary_tokens_in"] == 16_500 and j["adversary_tokens_out"] == 700

    def test_a_trace_over_the_cap_is_cut_and_recorded_as_cut(self):
        seen: dict = {}
        r = run(reconstruct([DOC], ENTS, self._trace(5_000), self._cloud(seen),
                            max_trace_chars=1_000))
        assert "[trace truncated]" in seen["body"]["messages"][0]["content"]
        assert r.trace_truncated is True and r.trace_chars > 5_000
        assert any("truncated" in n for n in r.notes)

    def test_a_refused_call_still_records_what_it_would_have_shown(self):
        cloud = CloudClient("http://gw", transport=httpx.MockTransport(
            lambda r: httpx.Response(403, json={"allowed": False, "reason": "CANARY_TRIPPED: 1"})))
        r = run(reconstruct([DOC], ENTS, self._trace(2_000), cloud))
        assert r.adversary_refused and r.trace_chars > 2_000
        assert (r.adversary_tokens_in, r.adversary_tokens_out) == (0, 0)


class TestScoringDefinitions:
    """Two definitional corrections the first live run forced.

    On the smoke corpus Tier 1 listed 95 entity entries for 61 distinct
    entities, and the scorer counted entries, so an entity weighed as much as
    the corpus repeated it. And it matched by substring, which credits "340"
    inside "1340"; an over-count is not a lower bound, which is the only thing
    one adversary's recovery figure is allowed to be.
    """

    def test_an_entity_repeated_across_documents_counts_once(self):
        ents = [Entity("Hanoi", "LOCATION")] * 4 + [Entity("Project Zephyr", "PROJECT")]
        r = score([DOC], ents, "Hanoi was named.", "adv")
        assert r.entities_total == 2 and r.entities_recovered == 1
        assert r.by_category["LOCATION"] == {"total": 1, "recovered": 1}

    @pytest.mark.parametrize("entity, output", [
        ("340", "Unit 1340 shipped on time."),
        ("High", "Take the Highway north."),
        ("Lan", "The plan was approved."),
    ])
    def test_a_substring_is_not_a_recovery(self, entity, output):
        r = score([DOC], [Entity(entity, "QUANTITY")], output, "adv")
        assert r.entities_recovered == 0, f"{entity!r} credited inside {output!r}"

    def test_whole_token_runs_still_match_through_case_and_punctuation(self):
        r = score([DOC], [Entity("Project Zephyr", "PROJECT")], "PROJECT ZEPHYR, again.", "adv")
        assert r.entities_recovered == 1

    def test_the_adversary_text_is_carried_but_never_serialised(self):
        """Kept for reading its guesses; never in a JSON artifact, because by
        definition it may contain recovered private text."""
        r = score([DOC], [Entity("Hanoi", "LOCATION")], "Hanoi is recovered here.", "adv")
        assert r.adversary_output == "Hanoi is recovered here."
        j = r.to_json()
        assert "Hanoi is recovered" not in j and "adversary_output" not in j


def _render_before_g3(trace: list[dict]) -> str:
    """`_render_trace_full` as it was at 543f65e, verbatim, before refused
    requests were left out: the reference for what must not have moved."""
    parts: list[str] = []
    for i, e in enumerate(trace):
        parts.append(f"=== EXCHANGE {i + 1} [{e.get('stage')}] ===")
        if e.get("system"):
            parts.append(f"[system]\n{e['system']}")
        for m in e.get("messages", []):
            parts.append(f"[{m.get('role')}]\n{m.get('content')}")
        if e.get("structured") is not None:
            parts.append(f"[model tool output]\n{json.dumps(e['structured'], ensure_ascii=False)}")
        if e.get("response_text"):
            parts.append(f"[model]\n{e['response_text']}")
        if e.get("refused"):
            parts.append(f"[refused by monitor: {e['refused']}]")
    return "\n\n".join(parts)


def _pipeline_trace(monkeypatch) -> list[dict]:
    """The scripted pipeline's trace: plan, s1, s2 refused by containment, s3."""
    monkeypatch.setenv("SHINGLE_HMAC_SALT", GW_SALT.decode())
    gw = GatewayScript()
    slm = AsyncSLMClient("http://local-slm:11434", transport=httpx.MockTransport(slm_handler))
    cloud = CloudClient("http://reference-monitor:5050", transport=httpx.MockTransport(gw))
    res = run(run_pipeline([DOC], "Assess Q3.", slm=slm, cloud=cloud,
                           gateway_url="http://reference-monitor:5050", evidence=EvidenceBank(),
                           gw_client=httpx.Client(transport=httpx.MockTransport(gw)),
                           session_salt=SALT))
    return json.loads(json.dumps(res.trace))       # as egress_trace.jsonl round-trips it


class TestRefusedExchangesAreNotShown:
    """G3. The tracer keeps a refused exchange's request, the local record, and
    the adversary used to be shown it: a request the monitor blocked reached C
    through the adversary call, and the G3 figure bounded what crossed only for
    runs with no refusal. The rendering now carries a marker in its place."""

    PLANTED = "QXZ-PLANTED-7731-NEVER-CROSSED"

    @staticmethod
    def _cloud(seen: dict) -> CloudClient:
        def h(req):
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json={
                "id": "m", "type": "message", "role": "assistant", "model": "adv-1",
                "content": [{"type": "text", "text": "nothing"}],
                "usage": {"input_tokens": 1, "output_tokens": 1}})
        return CloudClient("http://direct", api_key="k", transport=httpx.MockTransport(h))

    def test_a_refused_request_is_a_marker_and_its_content_is_not_sent(self, monkeypatch):
        from privdeep.eval.reconstruction import _render_trace_full
        trace = _pipeline_trace(monkeypatch)
        (k,) = [i for i, e in enumerate(trace) if e["refused"]]
        assert trace[k]["stage"] == "draft:s2"
        assert trace[k]["refused"].startswith("RAW_CONTEXT_CONTAINMENT:")
        trace[k]["system"] += "\n" + self.PLANTED
        trace[k]["messages"][0]["content"] += "\n" + self.PLANTED
        trace[k]["response_text"] = self.PLANTED       # "has no reply", even if one is recorded
        assert self.PLANTED in _render_before_g3(trace)  # what the adversary used to be sent

        seen: dict = {}
        r = run(reconstruct([DOC], ENTS, trace, self._cloud(seen)))
        prompt = seen["body"]["messages"][0]["content"]
        rendered = _render_trace_full(trace)
        assert self.PLANTED not in prompt and self.PLANTED not in rendered
        marker = ("=== EXCHANGE 3 [draft:s2] === "
                  "[request refused by the monitor: RAW_CONTEXT_CONTAINMENT]")
        assert prompt.count(marker) == 1
        assert r.trace_chars == len(rendered) and prompt.endswith(rendered)
        assert r.refused_exchanges == 1 and r.trace_truncated is False
        assert any("refused" in n for n in r.notes)
        assert json.loads(r.to_json())["refused_exchanges"] == 1

        # Every other exchange renders exactly as before, numbering included.
        old = _render_before_g3(trace)
        old_marker = f"[refused by monitor: {trace[k]['refused']}]"
        assert rendered == (_render_before_g3(trace[:k]) + "\n\n" + marker
                            + old.split(old_marker, 1)[1])

    def test_only_the_rule_name_is_kept_from_the_reason(self):
        from privdeep.eval.reconstruction import _render_trace_full
        trace = [{"stage": "plan", "system": "S", "messages": [{"role": "user", "content": "x"}],
                  "structured": None, "response_text": None,
                  "refused": f"SHINGLE_HIT: 3 shingles near {self.PLANTED}"},
                 {"stage": "draft:s1", "system": None, "messages": [], "structured": None,
                  "response_text": None, "refused": ":"}]
        assert _render_trace_full(trace) == (
            "=== EXCHANGE 1 [plan] === [request refused by the monitor: SHINGLE_HIT]\n\n"
            "=== EXCHANGE 2 [draft:s1] === [request refused by the monitor: UNSPECIFIED]")

    def test_a_trace_with_no_refusal_renders_byte_identically(self, monkeypatch):
        from privdeep.eval.reconstruction import _render_trace_full
        crossed = [e for e in _pipeline_trace(monkeypatch) if not e["refused"]]
        fixtures = [
            crossed,
            [{"stage": "plan", "system": "S",
              "messages": [{"role": "user", "content": "⟦SLOT:PROJECT_x⟧"}],
              "structured": {"sections": []}, "response_text": None, "refused": None}],
            TestTraceCap._trace(5_000),
            [],
        ]
        assert len(crossed) == 3
        for t in fixtures:
            assert _render_trace_full(t) == _render_before_g3(t)
        seen: dict = {}
        r = run(reconstruct([DOC], ENTS, crossed, self._cloud(seen)))
        assert seen["body"]["messages"][0]["content"].endswith(_render_before_g3(crossed))
        assert r.refused_exchanges == 0 and r.trace_chars == len(_render_before_g3(crossed))
        assert not any("refused" in n for n in r.notes)
