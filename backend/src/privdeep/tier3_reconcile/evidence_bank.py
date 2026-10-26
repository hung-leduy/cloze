"""Content-addressed store for public evidence the cloud may cite.

Every unit is identified by the SHA-256 of its raw snippet, so the same
passage retrieved twice is one unit and a citation resolves to the exact
bytes that were seen, not to a URL that may have changed since. The `W<n>`
tag the drafter cites is assigned in insertion order and never reused.

In-memory by scope decision D1 (single session). The harness spec's LanceDB
vector table with 384-d embeddings is not needed to make citations
verifiable; it is needed to *retrieve* evidence by similarity, which is a
later concern and a separate module if it arrives.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

__all__ = ["EvidenceBank", "EvidenceUnit"]


@dataclass(frozen=True, slots=True)
class EvidenceUnit:
    evidence_id: str        # EV-<TYPE>-<sha256[:8]>
    tag: str                # W1, W2, ...
    source_url: str
    content_hash: str       # full sha256 hex of raw_snippet
    summary_claim: str
    raw_snippet: str
    trust_level: str = "LOW"
    kind: str = "WEB"


@dataclass
class EvidenceBank:
    _by_hash: dict[str, EvidenceUnit] = field(default_factory=dict)
    _by_tag: dict[str, EvidenceUnit] = field(default_factory=dict)
    _by_id: dict[str, EvidenceUnit] = field(default_factory=dict)

    def add(self, source_url: str, raw_snippet: str, summary_claim: str,
            *, trust_level: str = "LOW", kind: str = "WEB") -> EvidenceUnit:
        h = hashlib.sha256(raw_snippet.encode("utf-8")).hexdigest()
        if h in self._by_hash:
            return self._by_hash[h]
        tag = f"W{len(self._by_tag) + 1}"
        unit = EvidenceUnit(
            evidence_id=f"EV-{kind}-{h[:8]}", tag=tag, source_url=source_url,
            content_hash=h, summary_claim=summary_claim.strip(), raw_snippet=raw_snippet,
            trust_level=trust_level, kind=kind,
        )
        self._by_hash[h] = unit
        self._by_tag[tag] = unit
        self._by_id[unit.evidence_id] = unit
        return unit

    def by_tag(self, tag: str) -> EvidenceUnit | None:
        return self._by_tag.get(tag)

    def by_id(self, evidence_id: str) -> EvidenceUnit | None:
        return self._by_id.get(evidence_id)

    def __len__(self) -> int:
        return len(self._by_hash)

    def __iter__(self):
        return iter(self._by_tag.values())

    def verify(self, unit: EvidenceUnit) -> bool:
        """Recompute the hash from the stored snippet; a mismatch means tampering."""
        return hashlib.sha256(unit.raw_snippet.encode("utf-8")).hexdigest() == unit.content_hash

    def manifest(self) -> list[dict[str, str]]:
        """What the audit manifest records: ids, tags, hashes, sources. Never snippets."""
        return [{"evidence_id": u.evidence_id, "tag": u.tag, "content_hash": u.content_hash,
                 "source_url": u.source_url} for u in self]
