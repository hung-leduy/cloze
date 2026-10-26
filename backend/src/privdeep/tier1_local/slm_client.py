"""Async client for the local SLM, confined to privdeep-internal.

Design facts, all measured inside the partition on 2026-09-06 and recorded in
PRIVDEEP_ICCIT_SCOPE.md section 2:

* The model is ``qwen3:14b`` served by Ollama. It is a *thinking* model. Through
  the OpenAI-compatible ``/v1`` endpoint, a short ``max_tokens`` budget is spent
  entirely inside the ``<think>`` block and the visible reply comes back empty;
  the ``/no_think`` soft switch does not change that through ``/v1``. The native
  ``/api/chat`` endpoint with ``think: false`` returns a real reply. This client
  therefore speaks ``/api/chat`` and never ``/v1``.
* Ollama defaults qwen3 to a 32768-token context, at which the model spills to
  CPU (22%/78%) and runs at ~16 tok/s. At ``num_ctx=8192`` it sits fully on the
  GPU at ~65 tok/s. 8192 is the spec's ``MAX_CONTEXT_LEN`` and is the default
  here; callers that need more must ask for it explicitly and accept the cost.

Thinking is off by default because every call this tier makes (ontology
extraction, slot masking, canary registration) is a structured transformation
where a deterministic, fast answer is worth more than deliberation. A caller
that genuinely wants reasoning passes ``think=True`` and a larger token budget.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger(__name__)

__all__ = ["AsyncSLMClient", "SLMError", "SLMReply"]


class SLMError(RuntimeError):
    """Raised when the SLM cannot be reached or returns a malformed reply."""


@dataclass(frozen=True)
class SLMReply:
    content: str
    prompt_tokens: int
    completion_tokens: int
    generation_seconds: float
    load_seconds: float

    @property
    def tokens_per_second(self) -> float:
        return self.completion_tokens / self.generation_seconds if self.generation_seconds else 0.0


class AsyncSLMClient:
    """Thin, retrying wrapper over Ollama's native chat API."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        *,
        num_ctx: int = 8192,
        timeout: float = 300.0,
        retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        raw = base_url or os.environ.get("LOCAL_SLM_URL", "http://local-slm:11434/v1")
        # Accept either form from the environment; strip a trailing /v1 because
        # this client deliberately uses the native API (see module docstring).
        self.base_url = raw.rstrip("/").removesuffix("/v1")
        self.model = model or os.environ.get("LOCAL_SLM_MODEL", "qwen3:14b")
        self.num_ctx = num_ctx
        self.retries = max(1, retries)
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncSLMClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def list_models(self) -> list[str]:
        r = await self._client.get(f"{self.base_url}/api/tags")
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        think: bool = False,
        max_tokens: int = 1024,
        temperature: float = 0.1,
        num_ctx: int | None = None,
        extra_options: dict[str, Any] | None = None,
    ) -> SLMReply:
        """One non-streaming chat turn. Retries on transport errors with backoff."""
        options: dict[str, Any] = {
            "num_predict": max_tokens,
            "num_ctx": num_ctx or self.num_ctx,
            "temperature": temperature,
        }
        if extra_options:
            options.update(extra_options)
        payload = {
            "model": self.model,
            "messages": messages,
            "think": think,
            "stream": False,
            "options": options,
        }

        last_exc: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                r = await self._client.post(f"{self.base_url}/api/chat", json=payload)
                r.raise_for_status()
                return self._parse(r.json())
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt == self.retries:
                    break
                delay = 0.5 * (2 ** (attempt - 1))
                log.warning("SLM call failed (attempt %d/%d): %s; retrying in %.1fs",
                            attempt, self.retries, exc, delay)
                await asyncio.sleep(delay)
        raise SLMError(f"SLM unreachable after {self.retries} attempts: {last_exc}") from last_exc

    @staticmethod
    def _parse(j: dict[str, Any]) -> SLMReply:
        try:
            content = j["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise SLMError(f"malformed SLM reply: {j!r}") from exc
        return SLMReply(
            content=content,
            prompt_tokens=int(j.get("prompt_eval_count", 0)),
            completion_tokens=int(j.get("eval_count", 0)),
            generation_seconds=j.get("eval_duration", 0) / 1e9,
            load_seconds=j.get("load_duration", 0) / 1e9,
        )


async def _smoke() -> None:
    """`python -m privdeep.tier1_local.slm_client`: one live call from inside the partition."""
    async with AsyncSLMClient() as c:
        models = await c.list_models()
        print(f"models: {len(models)}  target {'present' if c.model in models else 'MISSING'}")
        r = await c.chat([{"role": "user", "content": "Reply with the single word: ok"}],
                         max_tokens=16)
        print(f"reply: {r.content!r}  {r.completion_tokens} tok @ {r.tokens_per_second:.1f} tok/s"
              f"  (load {r.load_seconds:.1f}s)")


if __name__ == "__main__":
    asyncio.run(_smoke())
