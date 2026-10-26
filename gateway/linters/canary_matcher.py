"""Aho-Corasick canary matcher: the gateway half of the Fail-Closed Canary Invariant.

Why a multi-pattern automaton
-----------------------------
The core registers five random tokens per session (``CanaryInjector``) and the
gateway must decide, for every outbound payload, whether any of them occurs.
One ``str.find`` per token is O(len(text) * k). An Aho-Corasick automaton
answers "does any of these k strings occur, and how often" in one pass,
O(len(text) + matches), with no dependence on k, and pyahocorasick compiles it
once at registration. Five tokens would not need this; the design does,
because the matcher is the one linter whose cost must not grow with the
number of sessions the gateway serves.

Why the verdict carries a count and not the tokens
--------------------------------------------------
The verdict's reason string is written to the gateway log and returned in the
403 body. The token values have no business in either: the log lives on the
only dual-homed container in the system, and a count is all an incident
handler needs. Compare ``ShingleFilter.inspect(collect=False)``.

Streaming, and the straddle the harness spec would have missed
--------------------------------------------------------------
The harness spec (Task 1.4) says "every outgoing packet buffer is scanned
against the automaton". Scanned per packet, a token whose first half closes one
packet and whose second half opens the next is never seen whole, and a leak
that lands on a packet boundary passes. No adversary has to construct that
case; TCP segmentation produces it unasked. ``CanaryStream`` therefore keeps
the last ``longest_token_length - 1`` characters fed so far and prepends them
to the next chunk. That is the minimum tail that can complete any match begun
in an earlier chunk, and the count stays exact: a match is counted at the feed
in which its last character arrives and at no other, so a shorter token that
sits entirely inside a longer token's tail is not counted twice. No
end-of-stream flush is needed, because every character fed has already been
scanned as part of the chunk it arrived in.

Limits, stated as limits
------------------------
* Matching is exact. A re-cased, whitespace-split or encoded canary is not
  matched here.
* The stream works on text. A proxy that decodes bytes per packet and splits a
  multi-byte UTF-8 sequence across packets must reassemble with an incremental
  decoder before feeding; this class does not do that for it.
* An empty matcher blocks nothing. That is correct for this linter (there is
  nothing to trip) and is why it runs alongside, not instead of, the
  fail-closed containment check.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import ahocorasick

__all__ = ["CanaryMatcher", "CanaryStream", "CanaryVerdict"]


@dataclass(frozen=True)
class CanaryVerdict:
    """Outcome of one canary inspection. Carries a count, never the tokens."""

    blocked: bool
    hits: int

    @property
    def reason(self) -> str:
        if not self.blocked:
            return "OK"
        return f"CANARY_TRIPPED: {self.hits} active canary token(s) in egress"


@dataclass(frozen=True)
class _Compiled:
    """One immutable build of the automaton, swapped in as a unit by ``CanaryMatcher.add``."""

    tokens: frozenset[str]
    automaton: ahocorasick.Automaton | None
    longest: int


_EMPTY = _Compiled(tokens=frozenset(), automaton=None, longest=0)


class CanaryMatcher:
    """Exact multi-pattern matcher over the active canary set."""

    def __init__(self) -> None:
        self._compiled = _EMPTY

    def add(self, tokens: Iterable[str]) -> None:
        """Add tokens and rebuild the automaton over the union.

        pyahocorasick cannot extend a compiled automaton, so every add is a
        rebuild; that costs microseconds per token and happens once per
        session. The new build replaces the old in a single reference
        assignment, so a scan running concurrently on another thread sees the
        old build or the new one, never a half-built trie.
        """
        merged = set(self._compiled.tokens)
        for t in tokens:
            if not isinstance(t, str):
                raise TypeError(f"canary token must be str, got {type(t).__name__}")
            if not t:
                raise ValueError("canary token must be non-empty")
            merged.add(t)
        if not merged:
            self._compiled = _EMPTY
            return
        automaton = ahocorasick.Automaton()
        for t in merged:
            automaton.add_word(t, len(t))
        automaton.make_automaton()
        self._compiled = _Compiled(frozenset(merged), automaton, max(len(t) for t in merged))

    def __len__(self) -> int:
        return len(self._compiled.tokens)

    @property
    def longest(self) -> int:
        """Length of the longest active token; 0 when the matcher is empty."""
        return self._compiled.longest

    def scan(self, text: str) -> CanaryVerdict:
        """Count every occurrence of every active token in ``text`` in one pass."""
        hits = self.count_from(text, 0)
        return CanaryVerdict(blocked=hits > 0, hits=hits)

    def count_from(self, text: str, min_end: int) -> int:
        """Occurrences whose last character is at index >= ``min_end``.

        ``scan`` uses 0; ``CanaryStream`` uses the tail length so that a match
        wholly inside the tail, already counted on an earlier feed, is skipped.
        """
        automaton = self._compiled.automaton
        if automaton is None or not text:
            return 0
        return sum(1 for end, _ in automaton.iter(text) if end >= min_end)


class CanaryStream:
    """Straddle-safe canary scanning for one streaming egress connection.

    ``feed`` returns the cumulative verdict. Once a canary has been seen, every
    later verdict on this stream is blocked: a connection that has carried one
    canary is compromised whatever its next chunk contains.
    """

    def __init__(self, matcher: CanaryMatcher) -> None:
        self._matcher = matcher
        self._tail = ""
        self._hits = 0

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def tripped(self) -> bool:
        return self._hits > 0

    def feed(self, chunk: str) -> CanaryVerdict:
        text = self._tail + chunk
        # Only matches ending inside the new chunk are new; one ending inside
        # the tail was whole, and counted, on the feed its last character came in.
        self._hits += self._matcher.count_from(text, min_end=len(self._tail))
        # Keep the minimum that can complete a match begun in this chunk. If
        # the active set grows after this stream began, the kept tail may be
        # short for the new longest token at one boundary; canaries are
        # registered at session start, before any egress, so that window is
        # not exercised.
        keep = self._matcher.longest - 1
        self._tail = text[-keep:] if keep > 0 else ""
        return CanaryVerdict(blocked=self._hits > 0, hits=self._hits)
