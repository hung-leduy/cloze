"""The core's only path to a frontier model: through the reference monitor.

There is no direct route. The core sits on privdeep-internal with no default
route, so the base URL here is the gateway, and the gateway forwards to the
Anthropic Messages API after inspection. This client therefore speaks the
Messages API shape (so the gateway can forward bytes unchanged) but its
failure modes are the gateway's, and they are typed:

* `EgressRefused`  the monitor said no (403, or 400 for a streaming request).
  This is the signal the pipeline must handle, and it is NEVER retried:
  retrying a refusal is how a block becomes a probe.
* `CloudError`     the upstream answered with an error (401, 429, 529, ...) or
  a 200 whose body the client cannot parse. Retried with backoff only for 429,
  500, 502, 503 and 529, honouring Retry-After, up to `max_retries` attempts.
* `GatewayError`   the monitor itself failed (502/503, transport). Retried up
  to `max_retries` attempts too, a restart mid-request being the common cause.

Two facts recorded for the audit manifest (D4): every reply carries the
model id the upstream actually resolved, and every call is non-streaming,
because the monitor inspects whole responses only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger(__name__)

__all__ = ["REPORT_EFFORT", "CloudClient", "CloudError", "CloudReply", "EgressRefused",
           "GatewayError"]

_TRANSIENT = {429, 500, 502, 503, 529}

# The effort at which a report is planned and drafted, by the private arm
# (MacroPlanner, SectionDrafter) and by the oracle alike. One constant, because
# the utility comparison is only about the method while both arms think
# equally hard: the oracle imported its own copy and the private modules
# hard-coded theirs, so the two could drift apart with nothing to notice (INS2).
# It lives here, the module both sides already import, because eval/oracle.py
# imports the planner and the planner cannot import it back.
REPORT_EFFORT = "medium"


class EgressRefused(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class CloudError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


class GatewayError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CloudReply:
    text: str
    stop_reason: str | None
    model: str                 # the id the upstream resolved, not the one we asked for
    input_tokens: int
    output_tokens: int
    # Cache accounting. Reads bill at a fraction of the input rate and writes at
    # a small premium, so these are what say whether a cache breakpoint is
    # actually working: a read count stuck at zero across repeated calls with
    # the same prefix means something volatile crept into it.
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    structured: dict[str, Any] | None = None   # tool_use input, when a tool was forced
    raw: dict[str, Any] = field(default_factory=dict)


class CloudClient:
    def __init__(
        self,
        gateway_url: str | None = None,
        model: str | None = None,
        *,
        timeout: float = 300.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
        api_key: str | None = None,
    ) -> None:
        self.gateway_url = (gateway_url or os.environ.get("GATEWAY_URL", "http://reference-monitor:5050")).rstrip("/")
        self.model = model or os.environ.get("CLOUD_MODEL", "claude-sonnet-5")
        self.max_retries = max(1, max_retries)
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)
        # Direct mode, for the evaluation's oracle arm only: the client sends
        # the credential itself and talks to the upstream with no monitor in
        # between. In the partition the key is absent and the monitor adds it.
        self._headers = (
            {"x-api-key": api_key, "anthropic-version": os.environ.get("ANTHROPIC_VERSION",
                                                                         "2023-06-01")}
            if api_key else {}
        )
        self.direct = bool(api_key)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> CloudClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def messages(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        max_tokens: int = 8192,
        effort: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> CloudReply:
        """One non-streaming call.

        **No `temperature`.** Sonnet 5 removed the sampling parameters: sending
        `temperature`, `top_p` or `top_k` is rejected with a 400, so every
        cloud call in this system would have failed on the first live run. The
        replacement lever is `effort`, which trades thinking depth against
        spend but is not a randomness control — sampling is simply not
        configurable on this model. What that costs the evaluation is written
        down in `eval/judge.py`, which is the caller that wanted determinism.

        `max_tokens` covers thinking as well as the visible reply, because
        Sonnet 5 thinks adaptively whenever `thinking` is omitted. A budget
        sized for the prose alone gets spent on reasoning and the section comes
        back truncated, so the default here is deliberately generous.
        """
        body: dict[str, Any] = {
            "model": model or self.model,
            "max_tokens": max_tokens,
            "messages": messages,
            "stream": False,
        }
        if effort:
            body["output_config"] = {"effort": effort}
        if system:
            body["system"] = system
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice

        url = f"{self.gateway_url}/v1/messages"
        last: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                r = await self._client.post(url, json=body, headers=self._headers)
            except httpx.TransportError as exc:
                last = GatewayError(f"gateway unreachable: {exc}")
                if attempt < self.max_retries:
                    await asyncio.sleep(0.5 * attempt)
                    continue
                raise last from exc

            if r.status_code == 200:
                try:
                    return self._parse(r.json())
                except (ValueError, TypeError, AttributeError, OverflowError,
                        RecursionError) as exc:
                    # Not JSON, not an object, a field of the wrong type, a
                    # count of 1e400 (inf) or nesting too deep to decode; an
                    # object with no content still parses, as an empty reply.
                    # It raised from here untyped until 2026-10-27, so a
                    # drafter's ended the run; the message names the class
                    # only, since the body is the upstream's and can quote the
                    # request.
                    raise CloudError(200, f"unparseable reply ({type(exc).__name__})") from exc

            payload = self._json(r)
            # The monitor's own refusals carry {"allowed": false, "reason": ...}.
            if payload.get("allowed") is False:
                reason = str(payload.get("reason", "refused"))
                if r.status_code in (403, 400):
                    raise EgressRefused(reason)               # never retried
                last = GatewayError(reason)                   # 502/503 from the monitor
            else:
                # Upstream error passed through: Anthropic's error envelope, whose
                # "error" a malformed answer may give as something other than an
                # object (an untyped AttributeError until 2026-10-27).
                err = payload.get("error")
                msg = str(err.get("message", r.text[:200]) if isinstance(err, dict)
                          else r.text[:200])
                if r.status_code not in _TRANSIENT:
                    raise CloudError(r.status_code, msg)
                last = CloudError(r.status_code, msg)

            if attempt < self.max_retries:
                delay = self._retry_after(r) or 0.5 * (2 ** (attempt - 1))
                log.warning("cloud call attempt %d/%d failed (%s); retrying in %.1fs",
                            attempt, self.max_retries, last, delay)
                await asyncio.sleep(delay)
        assert last is not None
        raise last

    @staticmethod
    def _json(r: httpx.Response) -> dict[str, Any]:
        try:
            j = r.json()
            return j if isinstance(j, dict) else {}
        except (ValueError, RecursionError):
            return {}

    @staticmethod
    def _retry_after(r: httpx.Response) -> float | None:
        v = r.headers.get("retry-after")
        try:
            return min(float(v), 60.0) if v else None
        except ValueError:
            return None

    @staticmethod
    def _unwrap_tool_input(inp: Any) -> dict[str, Any] | None:
        """Tool arguments, with a JSON-encoded field decoded back to structure.

        A forced tool call does not guarantee the argument *shapes* the schema
        asks for. Observed live on the first real planner call: the schema
        declares ``sections`` as an array, and what came back was

            {"sections": "{\\"sections\\": [{\\"title\\": ...}]}"}

        — the whole object, JSON-encoded, as a string, nested under its own
        key. The planner's ``isinstance(..., list)`` check then failed and the
        run died after Tier 1 had already done all the local work.

        Two shapes are repaired here, both cheap to recognise and impossible to
        confuse with a legitimate string: a field whose value is a JSON-encoded
        array or object, and that same field re-wrapping the whole payload
        under its own name. Anything that does not parse is left exactly as it
        arrived, so a genuine string argument is untouched.

        Not a workaround to be embarrassed about: `strict: true` constrains the
        schema, not the model's habit of serialising twice, and a decoder that
        assumes well-formed arguments is a decoder that loses a paid run.
        """
        if not isinstance(inp, dict):
            return None
        out: dict[str, Any] = {}
        for key, value in inp.items():
            if isinstance(value, str) and value.lstrip()[:1] in ("[", "{"):
                try:
                    decoded = json.loads(value)
                except (ValueError, RecursionError):  # too deep is not parsed either
                    out[key] = value
                    continue
                if isinstance(decoded, dict) and set(decoded) == {key}:
                    decoded = decoded[key]
                out[key] = decoded
            else:
                out[key] = value
        return out

    @staticmethod
    def _parse(j: dict[str, Any]) -> CloudReply:
        text_parts: list[str] = []
        structured: dict[str, Any] | None = None
        for block in j.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use" and structured is None:
                structured = CloudClient._unwrap_tool_input(block.get("input"))
        usage = j.get("usage", {})
        return CloudReply(
            text="".join(text_parts),
            stop_reason=j.get("stop_reason"),
            model=str(j.get("model", "")),
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            cache_read_tokens=int(usage.get("cache_read_input_tokens", 0)),
            cache_write_tokens=int(usage.get("cache_creation_input_tokens", 0)),
            structured=structured,
            raw=j,
        )
