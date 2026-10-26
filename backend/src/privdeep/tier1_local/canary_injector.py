"""Per-session canary tokens: the core half of the Fail-Closed Canary Invariant.

Why canaries exist
------------------
The other two egress linters each cover one leak class and nothing else. The
shingle filter (``shared/shingle_filter.py``) catches verbatim spans
of C_user; the entropy screen catches encoded blobs. Neither can tell whether
the local SLM's *prompt context* has leaked: the ontology and the slot table
are abstractions of C_user, shingle-free by construction and low-entropy
English, so an injected instruction that persuades a model to echo its context
back out crosses both checks unexamined. A canary is a string planted where
only the SLM can see it. Its appearance anywhere on the wire is proof, not
inference, that prompt context escaped, and the gateway refuses on sight
(``gateway/linters/canary_matcher.py``). That refusal is the invariant.

Where the canaries live, and where they do not
----------------------------------------------
Canaries go into the PROMPT CONTEXT handed to the SLM (``context_block``) and
nowhere else. They are never written into ``Document.text``. The document model
makes ``text`` the single source of truth for every character offset, and both
the shingle index and the slot masker consume it; inserting a token would shift
every offset after it, add a foreign shingle to the containment filter, and
hand the masker something that is not user data to classify. Keeping them in
the system context gives up nothing the canary was buying: the SLM reads the
document text and the system context in one window, so a prompt-echo leak
carries the canary either way.

Token format
------------
``<prefix><32 hex chars>``, 128 bits from ``secrets.token_hex(16)``, five per
session (the harness spec's N=5). Its Shannon entropy averages about 4.45
bits/char over the whole token and cannot exceed 4.71, the value for a
perfectly uniform draw over this fixed prefix and alphabet. Both are under the
entropy screen's 4.85 threshold, and the ceiling is what matters: no draw of
this format can ever trip that screen, so the Aho-Corasick matcher is the only
mechanism that catches a canary. (The scope document's "about 4.68" is a
99.99th-percentile tail value, not the typical one.) The prefix exists for a person
reading a refusal log, not for the matcher, which matches whole tokens.

Limits, stated as limits
------------------------
* A canary in the system context fires when the model echoes its context.
  Verbatim copying of document text alone does not carry it; that is the
  shingle filter's job, and the two mechanisms are complementary, not
  redundant.
* Matching on the gateway is exact. A canary the model re-cases, splits with
  whitespace or encodes before emitting is not matched (base64 falls to the
  entropy screen; the other two fall to nothing).
* A compliant SLM never emits a canary. A non-compliant one causes a refusal
  at the gateway, which is the intended outcome and the only cost.
* Registration is one synchronous POST at session start. If the gateway does
  not confirm every token the session must not proceed, so ``register`` raises
  rather than returning quietly.
"""

from __future__ import annotations

import secrets
from typing import Any

import httpx

__all__ = ["CanaryInjector", "CanaryRegistrationError"]


class CanaryRegistrationError(RuntimeError):
    """The gateway did not confirm every canary. The session must not start."""


class CanaryInjector:
    """Generates one session's canary tokens and registers them with the gateway."""

    def __init__(
        self,
        prefix: str = "CANARY_PRIVDEEP_",
        n: int = 5,
        *,
        timeout: float = 10.0,
    ) -> None:
        if n < 1:
            raise ValueError("n must be >= 1; an injector with no tokens cannot trip anything")
        self.prefix = prefix
        self.timeout = timeout
        # Generated once, at construction. A second draw would leave the gateway
        # holding tokens the SLM never sees and the SLM holding tokens the
        # gateway never matches.
        self.tokens: tuple[str, ...] = tuple(prefix + secrets.token_hex(16) for _ in range(n))

    def register(self, gateway_url: str, client: httpx.Client | None = None) -> None:
        """POST the tokens to ``{gateway_url}/canaries``. Raises unless every one is confirmed."""
        url = f"{gateway_url.rstrip('/')}/canaries"
        body = {"tokens": list(self.tokens)}
        try:
            if client is None:
                with httpx.Client(timeout=self.timeout) as own:
                    r = own.post(url, json=body)
            else:
                r = client.post(url, json=body)
        except httpx.HTTPError as exc:
            raise CanaryRegistrationError(f"gateway unreachable at {url}: {exc}") from exc
        if not r.is_success:
            raise CanaryRegistrationError(
                f"gateway refused canary registration at {url}: HTTP {r.status_code}"
            )
        self._confirm(r)

    def _confirm(self, r: httpx.Response) -> None:
        """A 2xx is not a confirmation; the gateway's own count of what it now holds is."""
        try:
            registered: Any = r.json().get("registered")
        except (ValueError, AttributeError) as exc:
            raise CanaryRegistrationError(f"gateway reply is not the expected JSON: {exc}") from exc
        if registered != len(self.tokens):
            raise CanaryRegistrationError(
                f"gateway confirmed {registered!r} canary token(s), expected {len(self.tokens)}"
            )

    def context_block(self) -> str:
        """The block to append to the SLM's system context. Never goes into Document.text."""
        return "Internal reference tokens (never output): " + ", ".join(self.tokens)
