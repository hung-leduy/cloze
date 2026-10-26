"""Shannon-entropy screen for encoded blobs leaving the trusted zone.

Scope note, which matters for how the paper describes this component. This
linter detects *encoded* exfiltration: base64, hex dumps, ciphertext, anything
whose per-character distribution is close to uniform. It does **not** detect raw
private prose, and the harness spec was wrong to imply it contributes to the
Zero-Raw-Context Egress Invariant. English text sits around 4.0-4.3 bits/char,
comfortably under any threshold that does not also refuse ordinary JSON.

`shared.shingle_filter` is what enforces that invariant. This module
covers the disjoint case of a payload that has been encoded to evade it.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

__all__ = ["EntropyVerdict", "calculate_shannon_entropy", "scan_payload"]

# Whitespace-delimited runs. A payload that splits a blob with spaces defeats
# this tokenisation, which is one more reason the entropy screen cannot be the
# invariant's enforcement mechanism.
_TOKEN_RE = re.compile(r"\S+")


def calculate_shannon_entropy(text: str) -> float:
    """Shannon entropy in bits per character. Empty string is 0.0."""
    if not text:
        return 0.0
    counts = Counter(text)
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


@dataclass(frozen=True)
class EntropyVerdict:
    blocked: bool
    worst_token: str
    worst_entropy: float
    threshold: float
    min_length: int

    @property
    def reason(self) -> str:
        if not self.blocked:
            return "OK"
        return (
            f"COVERT_CHANNEL_DETECTED: token of length {len(self.worst_token)} "
            f"has H={self.worst_entropy:.2f} > {self.threshold}"
        )


def scan_payload(payload: str, threshold: float = 4.85, min_length: int = 24) -> EntropyVerdict:
    """Flag any whitespace token longer than `min_length` whose entropy exceeds `threshold`."""
    worst_tok, worst_h = "", 0.0
    for m in _TOKEN_RE.finditer(payload):
        tok = m.group(0)
        if len(tok) <= min_length:
            continue
        h = calculate_shannon_entropy(tok)
        if h > worst_h:
            worst_tok, worst_h = tok, h
    return EntropyVerdict(
        blocked=worst_h > threshold,
        worst_token=worst_tok,
        worst_entropy=worst_h,
        threshold=threshold,
        min_length=min_length,
    )
