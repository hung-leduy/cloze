"""Loader dispatch and the one rule every loader shares: identity by content.

`load(path)` picks the loader by suffix and hands it an explicit `doc_id`
derived from the file bytes, so the same document under two filenames is one
document and a rename never breaks a reference. Individual loaders keep their
own `doc_id=None` defaults for interactive use; the pipeline never relies on
them, which is how the four loaders' differing defaults were neutralised
rather than reconciled by hand.

Hash the FILE BYTES, not `Document.text`: the markdown and PDF loaders
normalise line endings, so a text hash would not match the source artifact
that the audit manifest must name.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from privdeep.models.document import Document, DocumentKind

from .docx import load_docx
from .md import load_markdown
from .pdf import load_pdf
from .xlsx import load_xlsx

__all__ = [
    "SUFFIXES", "content_doc_id", "load",
    "load_docx", "load_markdown", "load_pdf", "load_xlsx",
]

SUFFIXES: dict[str, DocumentKind] = {
    ".xlsx": DocumentKind.XLSX,
    ".pdf": DocumentKind.PDF,
    ".md": DocumentKind.MARKDOWN,
    ".markdown": DocumentKind.MARKDOWN,
    ".docx": DocumentKind.DOCX,
}


def content_doc_id(path: Path, *, length: int = 16) -> str:
    """First `length` hex digits of SHA-256 over the file bytes."""
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:length]


def load(path: Path | str, doc_id: str | None = None) -> Document:
    """Load any supported file into a Document with a content-addressed id."""
    p = Path(path)
    kind = SUFFIXES.get(p.suffix.lower())
    if kind is None:
        raise ValueError(f"unsupported document type {p.suffix!r}; supported: {sorted(SUFFIXES)}")
    did = doc_id or content_doc_id(p)
    if kind is DocumentKind.XLSX:
        doc = load_xlsx(p, doc_id=did)
    elif kind is DocumentKind.PDF:
        doc = load_pdf(p, doc_id=did)
    elif kind is DocumentKind.MARKDOWN:
        doc = load_markdown(p, doc_id=did)
    else:
        doc = load_docx(p, doc_id=did)
    doc.metadata.setdefault("stem", p.stem)
    doc.metadata.setdefault("content_sha256_16", did if doc_id is None else content_doc_id(p))
    return doc
