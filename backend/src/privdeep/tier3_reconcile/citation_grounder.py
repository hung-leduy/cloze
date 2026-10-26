"""Check that every citation resolves and every figure has one.

Two checks, both mechanical, both on the reintegrated section text:

* **Citations.** Every `[W<n>]` must resolve to a unit in the evidence bank
  whose stored hash still matches its snippet. A tag that does not resolve is
  a fabricated citation and, in strict mode, refuses the section.
* **Numbers.** Invariant 4 in the harness spec ("every quantitative claim
  backed by a local computation or citation") is honoured here at the level
  this build can actually support: a numeral must share a sentence with a
  resolving citation tag. A numeral in an uncited sentence is reported as
  unbacked. This is a sentence-level co-occurrence rule, not a proof that the
  number appears in the cited snippet; that stronger check is stated as future
  work, not claimed.

Exemptions, because they are not claims: four-digit years (19xx/20xx),
section numbers at line start, list markers, and anything inside a slot id
or a citation tag. Everything else that looks like a number is a number.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from privdeep.tier1_local.slot_masker import SLOT_RE
from privdeep.tier3_reconcile.evidence_bank import EvidenceBank

__all__ = ["CitationGrounder", "GroundingRefused", "GroundingResult"]

_TAG_RE = re.compile(r"\[(W\d+)\]")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n{2,}")
_NUM_RE = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?%?(?![\w])")
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
_LINE_MARK = re.compile(r"^\s*(?:\d+[.)]|[-*+])\s")


@dataclass(frozen=True, slots=True)
class GroundingResult:
    valid_tags: tuple[str, ...]
    invalid_tags: tuple[str, ...]
    unbacked_numbers: tuple[str, ...]     # the numeral strings, in order
    sentences_checked: int

    @property
    def ok(self) -> bool:
        return not self.invalid_tags and not self.unbacked_numbers


class GroundingRefused(RuntimeError):
    def __init__(self, result: GroundingResult) -> None:
        super().__init__(
            f"GROUNDING: {len(result.invalid_tags)} invalid citation(s), "
            f"{len(result.unbacked_numbers)} unbacked number(s)"
        )
        self.result = result


class CitationGrounder:
    def __init__(self, bank: EvidenceBank, *, strict: bool = True,
                 extra_exempt: Iterable[str] = ()) -> None:
        self.bank = bank
        self.strict = strict
        self._exempt = set(extra_exempt)

    def check(self, text: str) -> GroundingResult:
        # Slot ids and tags are not numbers; blank them before numeral scanning.
        scrubbed = SLOT_RE.sub(" ", text)
        valid: list[str] = []
        invalid: list[str] = []
        for tag in dict.fromkeys(_TAG_RE.findall(scrubbed)):
            unit = self.bank.by_tag(tag)
            if unit is None or not self.bank.verify(unit):
                invalid.append(tag)
            else:
                valid.append(tag)
        valid_set = set(valid)

        unbacked: list[str] = []
        # Strip list markers line by line BEFORE sentence splitting: "1. Intro"
        # would otherwise split at "1." and the marker would read as a claim.
        lines = []
        for ln in scrubbed.splitlines():
            prev = None
            while prev != ln:
                prev, ln = ln, _LINE_MARK.sub("", ln, count=1)
            lines.append(ln)
        unmarked = "\n".join(lines)
        sentences = [s for s in _SENT_SPLIT.split(unmarked) if s.strip()]
        for sent in sentences:
            body = sent
            cited = any(t in valid_set for t in _TAG_RE.findall(body))
            body_wo_tags = _TAG_RE.sub(" ", body)
            for m in _NUM_RE.finditer(body_wo_tags):
                n = m.group(0)
                if _YEAR_RE.match(n) or n in self._exempt:
                    continue
                if not cited:
                    unbacked.append(n)
        result = GroundingResult(tuple(valid), tuple(invalid), tuple(unbacked), len(sentences))
        if self.strict and not result.ok:
            raise GroundingRefused(result)
        return result
