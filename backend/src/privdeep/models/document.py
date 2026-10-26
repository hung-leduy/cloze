"""The document model every loader produces and every Tier-1 stage consumes.

One rule holds everything together: a `Document` has exactly one canonical
`text`, and every structural element (a spreadsheet cell, a PDF page, a Word
paragraph) records its **character offsets into that text**. Nothing downstream
ever re-parses the source file. The shingle filter indexes `text`; the slot
masker rewrites `text`; the reintegrator binds a slot to a `Span` in `text`.
If two components ever disagree about where something is, the offsets are the
tie-breaker, and the loader that produced them is the bug.

For tabular sources the canonical text is a deterministic serialisation, one
row per line, cells joined by a tab, sheets separated by a header line. That
serialisation is what the local SLM reads and what the cloud never sees; it is
chosen for offset stability, not for prettiness.

Offsets are Python string indices (code points), half-open `[start, end)`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

__all__ = ["Cell", "Document", "DocumentKind", "SLOT_CATEGORIES", "Span"]


class DocumentKind(StrEnum):
    XLSX = "xlsx"
    PDF = "pdf"
    MARKDOWN = "md"
    DOCX = "docx"


# The slot taxonomy (scope decision, W2). Chosen because qwen3:14b classifies
# these eight stably and they cover both spreadsheet cells and prose. A category
# not in this tuple is a bug in the extractor, not a new category.
SLOT_CATEGORIES: tuple[str, ...] = (
    "PERSON",
    "ORG",
    "PROJECT",
    "LOCATION",
    "DATE",
    "MONEY",
    "QUANTITY",
    "IDENTIFIER",
)


@dataclass(frozen=True, slots=True)
class Span:
    """A half-open character range in a Document's canonical text."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"invalid span [{self.start}, {self.end})")

    @property
    def length(self) -> int:
        return self.end - self.start

    def slice(self, text: str) -> str:
        return text[self.start : self.end]

    def overlaps(self, other: Span) -> bool:
        return self.start < other.end and other.start < self.end


@dataclass(frozen=True, slots=True)
class Cell:
    """One spreadsheet cell, located in the canonical text.

    `value` is the cell's rendered string exactly as it appears in `text` at
    `span`, so `span.slice(doc.text) == value` always holds. Numbers are
    rendered by the loader with a fixed rule so the same workbook always yields
    the same text.
    """

    sheet: str
    row: int  # 1-based, as in the spreadsheet
    col: int  # 1-based
    value: str
    span: Span


@dataclass(slots=True)
class Document:
    doc_id: str
    kind: DocumentKind
    source_path: Path
    text: str
    cells: list[Cell] = field(default_factory=list)
    # Coarse structure for prose sources: page or paragraph boundaries. Each
    # entry is (label, span), e.g. ("page 3", Span(...)) or ("para 12", Span).
    blocks: list[tuple[str, Span]] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        n = len(self.text)
        for c in self.cells:
            if c.span.end > n:
                raise ValueError(f"cell span {c.span} exceeds text length {n}")
            if c.span.slice(self.text) != c.value:
                raise ValueError(
                    f"cell at {c.sheet}!R{c.row}C{c.col} claims {c.value!r} "
                    f"but text has {c.span.slice(self.text)!r}"
                )
        for label, sp in self.blocks:
            if sp.end > n:
                raise ValueError(f"block {label!r} span {sp} exceeds text length {n}")

    def find_all(self, needle: str) -> list[Span]:
        """Every non-overlapping occurrence of `needle` in the canonical text."""
        if not needle:
            return []
        out: list[Span] = []
        i = self.text.find(needle)
        while i != -1:
            out.append(Span(i, i + len(needle)))
            i = self.text.find(needle, i + len(needle))
        return out
