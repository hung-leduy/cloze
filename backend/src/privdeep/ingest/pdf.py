"""PDF loader: pypdf text extraction into the Document contract.

What this produces
------------------
One ``Document`` whose canonical ``text`` is the pages' ``extract_text()``
output joined by a blank line (``PAGE_SEPARATOR``), and one block per page,
labelled ``"page N"`` with N starting at 1, whose ``Span`` covers exactly that
page's extracted text. The invariant a consumer may rely on is::

    doc.text == PAGE_SEPARATOR.join(span.slice(doc.text) for _, span in doc.blocks)

A page with no extractable text yields an *empty* block, not a missing one, so
``len(doc.blocks)`` is always the page count and the label index is always
the physical page number. Downstream code that wants "which page did this
slot come from" can bisect the block spans without special-casing gaps.

What is lossy, stated as limits
-------------------------------
pypdf is the only PDF library in the environment, and text extraction from PDF
is reconstruction, not reading: a PDF stores positioned glyph runs, not text.
Consequences the rest of the pipeline must not forget:

* **Layout is flattened.** Multi-column pages come out in content-stream order,
  which is usually but not always reading order. Tables lose their grid.
* **Glyphs are mapped, not decoded.** Ligatures (``fi``, ``fl``), fonts with
  missing or custom encodings, and hyphenation at line ends survive in whatever
  form the font's ToUnicode map gives them. Scanned pages have no text at all.
* **Offsets index the extracted text, not the PDF bytes.** A ``Span`` here is a
  code-point range in ``doc.text``; it says nothing about where on the page, or
  where in the file, those characters came from. Nothing downstream re-parses
  the PDF, so this is sufficient for masking and reintegration, and it is all
  that is promised.

Line endings are normalised to ``"\\n"`` before offsets are computed. pypdf 5.1
itself emits only ``"\\n"``, so this is defensive: it guards against a CR glyph
in the source text shifting offsets between this loader and any consumer that
canonicalises newlines on its own.

Plain extraction mode is used rather than pypdf's layout mode. Layout mode pads
with whitespace to mimic the page geometry, which inflates the text with runs
of spaces that mean nothing to the shingle filter or the slot masker and would
make offsets depend on a rendering heuristic rather than on content.

Encrypted files: pypdf opens a PDF whose user password is empty without being
asked; one with a real user password raises ``pypdf.errors.FileNotDecryptedError``
on first page access. This loader takes no password because the scope's
``C_user`` is documents the user chose to upload; a locked file is refused,
not guessed at.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pypdf
from pypdf import PdfReader

from privdeep.models.document import Document, DocumentKind, Span

__all__ = ["PAGE_SEPARATOR", "load_pdf"]

# Blank line between pages. Two newlines rather than a form feed because every
# consumer (shingle tokeniser, slot masker, SLM prompt) treats "\n\n" as a
# paragraph break already; a control character would need special-casing.
PAGE_SEPARATOR = "\n\n"


def _normalise_newlines(s: str) -> str:
    """CRLF and lone CR become LF. Applied per page, before any offset is taken."""
    return s.replace("\r\n", "\n").replace("\r", "\n")


def load_pdf(path: Path, doc_id: str | None = None) -> Document:
    """Load one PDF into a ``Document`` of kind ``PDF``.

    ``doc_id`` defaults to the first 16 hex digits of the file's SHA-256, so
    the same bytes always get the same id regardless of filename; the full
    digest is kept in ``metadata["sha256"]`` for the audit manifest.

    Raises whatever pypdf raises for a file it cannot parse or decrypt; the
    loader does not mask a broken input as an empty document.
    """
    path = Path(path)
    data = path.read_bytes()
    reader = PdfReader(BytesIO(data))

    page_texts = [_normalise_newlines(page.extract_text() or "") for page in reader.pages]

    blocks: list[tuple[str, Span]] = []
    cursor = 0
    for number, page_text in enumerate(page_texts, start=1):
        if number > 1:
            cursor += len(PAGE_SEPARATOR)
        blocks.append((f"page {number}", Span(cursor, cursor + len(page_text))))
        cursor += len(page_text)
    text = PAGE_SEPARATOR.join(page_texts)

    digest = hashlib.sha256(data).hexdigest()
    return Document(
        doc_id=doc_id or digest[:16],
        kind=DocumentKind.PDF,
        source_path=path,
        text=text,
        blocks=blocks,
        metadata={
            "pages": str(len(page_texts)),
            "sha256": digest,
            "extractor": f"pypdf {pypdf.__version__}",
        },
    )
