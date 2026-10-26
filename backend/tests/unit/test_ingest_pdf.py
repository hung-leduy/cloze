"""Unit tests for the PDF loader.

pypdf can copy and write PDFs but has no API for drawing text into a content
stream, so the fixture is a PDF written by hand: catalog, pages tree, one page
object and one content stream per page, a shared Helvetica resource, and an
xref table whose offsets are computed, not guessed. pypdf tolerates a wrong
xref by rebuilding it; ``test_fixture_parses_strictly`` proves the fixture does
not lean on that tolerance, so the other tests exercise the loader and not
pypdf's repair path. Nothing binary is committed; every input is built inside
``tmp_path``.
"""

from __future__ import annotations

import io
from dataclasses import asdict
from itertools import pairwise
from pathlib import Path

import pypdf
import pytest
from privdeep.ingest.pdf import PAGE_SEPARATOR, load_pdf
from privdeep.models.document import Document, DocumentKind, Span

# --------------------------------------------------------------------------
# fixture builder
# --------------------------------------------------------------------------


def _escape(s: str) -> str:
    """PDF literal-string escaping for the three characters that need it."""
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(pages: list[str | None]) -> bytes:
    """A minimal PDF-1.4 file with one page per entry.

    ``None`` produces a page with an empty content stream, i.e. a page that
    exists but carries no text. Object numbering: 1 catalog, 2 pages tree,
    3 font, then (page, contents) pairs from 4 upward.
    """
    n = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, sentence in enumerate(pages):
        page_obj = 4 + 2 * i
        contents_obj = page_obj + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {contents_obj} 0 R >>".encode()
        )
        if sentence is None:
            stream = b""
        else:
            stream = f"BT /F1 12 Tf 72 720 Td ({_escape(sentence)}) Tj ET".encode("latin-1")
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(out)
    size = len(objects) + 1
    out += f"xref\n0 {size}\n".encode()
    out += b"0000000000 65535 f \n"  # exactly 20 bytes per entry, as the spec requires
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


PAGE_ONE = "Hello page one"
PAGE_TWO = "Hello page two"


@pytest.fixture
def two_page_pdf(tmp_path: Path) -> Path:
    p = tmp_path / "two.pdf"
    p.write_bytes(build_pdf([PAGE_ONE, PAGE_TWO]))
    return p


# --------------------------------------------------------------------------
# the fixture itself
# --------------------------------------------------------------------------


def test_fixture_parses_strictly():
    """The xref must be right, so failures below are the loader's, not the fixture's."""
    reader = pypdf.PdfReader(io.BytesIO(build_pdf([PAGE_ONE, PAGE_TWO])), strict=True)
    assert len(reader.pages) == 2
    assert reader.pages[0].extract_text() == PAGE_ONE


# --------------------------------------------------------------------------
# loader
# --------------------------------------------------------------------------


class TestBlocksAndText:
    def test_two_pages_yield_two_blocks_that_slice_to_their_sentences(self, two_page_pdf):
        doc = load_pdf(two_page_pdf)
        assert doc.kind is DocumentKind.PDF
        assert doc.source_path == two_page_pdf
        assert [label for label, _ in doc.blocks] == ["page 1", "page 2"]
        (_, one), (_, two) = doc.blocks
        assert PAGE_ONE in one.slice(doc.text)
        assert PAGE_TWO in two.slice(doc.text)
        assert PAGE_TWO not in one.slice(doc.text)
        assert PAGE_ONE not in two.slice(doc.text)

    def test_text_is_in_page_order(self, two_page_pdf):
        doc = load_pdf(two_page_pdf)
        assert doc.text.index(PAGE_ONE) < doc.text.index(PAGE_TWO)
        (_, one), (_, two) = doc.blocks
        assert one.end <= two.start

    def test_text_is_pages_joined_by_the_separator(self, two_page_pdf):
        """The invariant the module docstring promises: text rebuilds from blocks."""
        doc = load_pdf(two_page_pdf)
        assert doc.text == PAGE_SEPARATOR.join(sp.slice(doc.text) for _, sp in doc.blocks)
        assert PAGE_SEPARATOR == "\n\n"

    def test_find_all_lands_inside_the_right_block(self, two_page_pdf):
        doc = load_pdf(two_page_pdf)
        (hit,) = doc.find_all("page two")
        _, two = doc.blocks[1]
        assert two.start <= hit.start and hit.end <= two.end

    def test_empty_page_yields_empty_block_not_missing_block(self, tmp_path):
        p = tmp_path / "gap.pdf"
        p.write_bytes(build_pdf([PAGE_ONE, None, "Hello page three"]))
        doc = load_pdf(p)
        assert [label for label, _ in doc.blocks] == ["page 1", "page 2", "page 3"]
        _, middle = doc.blocks[1]
        assert middle.length == 0
        assert middle.slice(doc.text) == ""
        assert doc.text == PAGE_SEPARATOR.join(sp.slice(doc.text) for _, sp in doc.blocks)
        assert "Hello page three" in doc.blocks[2][1].slice(doc.text)

    def test_blocks_are_ascending_and_disjoint(self, tmp_path):
        p = tmp_path / "five.pdf"
        p.write_bytes(build_pdf([f"Sentence on page {i}" for i in range(1, 6)]))
        doc = load_pdf(p)
        spans = [sp for _, sp in doc.blocks]
        assert len(spans) == 5
        for a, b in pairwise(spans):
            assert a.end <= b.start
            assert not a.overlaps(b)


class TestContract:
    def test_document_round_trips_contract_validation(self, two_page_pdf):
        """Re-running __post_init__ on the loader's own fields must not raise."""
        doc = load_pdf(two_page_pdf)
        fields = asdict(doc)
        fields["blocks"] = [(label, Span(**sp)) for label, sp in fields["blocks"]]
        again = Document(**fields)
        assert again.text == doc.text
        assert again.blocks == doc.blocks
        for _, sp in again.blocks:
            assert sp.end <= len(again.text)

    def test_doc_id_defaults_to_content_hash_and_can_be_overridden(self, two_page_pdf, tmp_path):
        doc = load_pdf(two_page_pdf)
        assert len(doc.doc_id) == 16
        assert doc.metadata["sha256"].startswith(doc.doc_id)
        # Same bytes under another name: same id. Renaming must not fork identity.
        copy = tmp_path / "renamed.pdf"
        copy.write_bytes(two_page_pdf.read_bytes())
        assert load_pdf(copy).doc_id == doc.doc_id
        assert load_pdf(two_page_pdf, doc_id="explicit").doc_id == "explicit"

    def test_metadata_records_page_count_and_extractor(self, two_page_pdf):
        doc = load_pdf(two_page_pdf)
        assert doc.metadata["pages"] == "2"
        assert doc.metadata["extractor"] == f"pypdf {pypdf.__version__}"
        assert doc.cells == []


class TestNormalisation:
    def test_line_endings_normalised_before_offsets(self, two_page_pdf, monkeypatch):
        """pypdf itself never emits CR; simulate a source that does and check offsets hold."""
        raw = ["first\r\nline\rmore", "second\r\n"]
        calls = iter(raw)
        monkeypatch.setattr(pypdf.PageObject, "extract_text", lambda self: next(calls))
        doc = load_pdf(two_page_pdf)
        assert "\r" not in doc.text
        (_, one), (_, two) = doc.blocks
        assert one.slice(doc.text) == "first\nline\nmore"
        assert two.slice(doc.text) == "second\n"
        assert doc.text == PAGE_SEPARATOR.join(sp.slice(doc.text) for _, sp in doc.blocks)

    def test_none_from_extract_text_is_treated_as_empty(self, two_page_pdf, monkeypatch):
        monkeypatch.setattr(pypdf.PageObject, "extract_text", lambda self: None)
        doc = load_pdf(two_page_pdf)
        assert doc.text == PAGE_SEPARATOR
        assert all(sp.length == 0 for _, sp in doc.blocks)


class TestRefusals:
    # The passwords below lock a PDF that is written to tmp_path and discarded;
    # they protect nothing, so the hardcoded-password rule is suppressed here.

    def test_password_protected_pdf_is_refused_not_emptied(self, two_page_pdf, tmp_path):
        writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(two_page_pdf))
        writer.encrypt(user_password="secret", owner_password="owner")  # noqa: S106
        locked = tmp_path / "locked.pdf"
        with locked.open("wb") as fh:
            writer.write(fh)
        with pytest.raises(pypdf.errors.FileNotDecryptedError):
            load_pdf(locked)

    def test_empty_user_password_opens_transparently(self, two_page_pdf, tmp_path):
        writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(two_page_pdf))
        writer.encrypt(user_password="", owner_password="owner")  # noqa: S106
        open_pdf = tmp_path / "open.pdf"
        with open_pdf.open("wb") as fh:
            writer.write(fh)
        doc = load_pdf(open_pdf)
        assert PAGE_ONE in doc.blocks[0][1].slice(doc.text)
