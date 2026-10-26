"""Record every cloud exchange, inside the partition, for the adversary to read later.

The gateway's audit log carries no content by design. But the paper's
privacy number is "how much of the private document can an adversary who
sees everything that crossed reconstruct", and that adversary needs the
actual bytes: every prompt the core sent and every reply it received. So
the core records them itself, on the trusted side, as the egress trace.

The trace is written on the trusted side and is the input to
`privdeep.eval.reconstruction`, which in the evaluation sends it, rendered, to
a frontier model directly, zero-shot, not through the monitor. An exchange the
monitor refused is recorded here with its request, as the local record of
what was attempted: the evaluation's crossing scans mark that content
'not-sent', and the adversary's rendering replaces the exchange with one
marker line naming the stage and the refusal rule, so the adversary is not
shown a request that never crossed (THREAT_MODEL §5).

Composition, not subclassing: the wrapper has the one method the planner
and drafter call, and the `model` attribute the pipeline reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from privdeep.tier2_cloud.cloud_client import CloudClient, CloudReply, EgressRefused

__all__ = ["TraceEntry", "TracingCloudClient"]


@dataclass(slots=True)
class TraceEntry:
    stage: str
    system: str | None
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None
    response_text: str | None
    structured: dict[str, Any] | None
    resolved_model: str | None
    refused: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage, "system": self.system, "messages": self.messages,
            "tools": self.tools, "response_text": self.response_text,
            "structured": self.structured, "resolved_model": self.resolved_model,
            "refused": self.refused, "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


@dataclass
class TracingCloudClient:
    inner: CloudClient
    entries: list[TraceEntry] = field(default_factory=list)
    stage: str = "unlabelled"

    @property
    def model(self) -> str:
        return self.inner.model

    def label(self, stage: str) -> None:
        """Set the stage name recorded on subsequent calls (e.g. 'plan', 'draft:s2')."""
        self.stage = stage

    async def messages(self, messages: list[dict[str, Any]], **kw: Any) -> CloudReply:
        entry = TraceEntry(
            stage=self.stage, system=kw.get("system"), messages=messages,
            tools=kw.get("tools"), response_text=None, structured=None, resolved_model=None,
        )
        try:
            reply = await self.inner.messages(messages, **kw)
        except EgressRefused as exc:
            entry.refused = exc.reason
            self.entries.append(entry)
            raise
        entry.response_text = reply.text
        entry.structured = reply.structured
        entry.resolved_model = reply.model
        entry.input_tokens, entry.output_tokens = reply.input_tokens, reply.output_tokens
        self.entries.append(entry)
        return reply

    async def aclose(self) -> None:
        await self.inner.aclose()

    async def __aenter__(self) -> TracingCloudClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
