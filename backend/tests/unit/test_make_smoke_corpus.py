"""The synthetic corpus, checked for the properties a live run depends on.

A corpus generator is easy to get subtly wrong in ways that only surface three
minutes into a run that costs money: a file the loaders cannot read, an entity
set with nothing to mask, or documents so disjoint that cross-document slot
reuse is never exercised. All of that is cheap to pin here.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import make_smoke_corpus as M  # noqa: E402
from privdeep.ingest import SUFFIXES, content_doc_id, load  # noqa: E402
from privdeep.models.document import SLOT_CATEGORIES, DocumentKind  # noqa: E402

EXPECTED = {
    "budget.xlsx": DocumentKind.XLSX,
    "steering-memo.md": DocumentKind.MARKDOWN,
    "board-minutes.docx": DocumentKind.DOCX,
    "quarterly-review.pdf": DocumentKind.PDF,
}


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("corpus")
    M.main(["--out", str(out)])
    return out


def test_every_supported_format_is_present_and_loads(corpus):
    """D5 makes ingestion first-class, so the sample has to cover all four."""
    produced = {p.name for p in corpus.iterdir() if p.suffix.lower() in SUFFIXES}
    assert produced == set(EXPECTED)
    for name, kind in EXPECTED.items():
        doc = load(corpus / name)
        assert doc.kind is kind
        assert doc.text.strip(), f"{name} produced no extractable text"


def test_the_pdf_has_more_than_one_page(corpus):
    """One block per page is the PDF loader's contract; a single-page fixture
    would let a regression that collapses pages pass unnoticed."""
    doc = load(corpus / "quarterly-review.pdf")
    assert len(doc.blocks) == 2
    assert all(span.slice(doc.text).strip() for _label, span in doc.blocks)


def test_the_spreadsheet_spans_two_sheets_and_has_cells(corpus):
    doc = load(corpus / "budget.xlsx")
    assert len(doc.cells) > 20
    sheets = {c.sheet for c in doc.cells}
    assert len(sheets) == 2, f"expected two sheets, got {sheets}"


def test_the_docx_carries_a_table_as_cells(corpus):
    doc = load(corpus / "board-minutes.docx")
    assert doc.cells, "the minutes table should surface as cells"
    assert doc.blocks, "headings and paragraphs should surface as blocks"


def test_entities_are_shared_across_documents(corpus):
    """Slot ids are HMAC(salt, category + text), so the same entity in two
    documents must resolve to one id and the session table is what merges them.
    A corpus of disjoint documents never exercises that path."""
    texts = {name: load(corpus / name).text for name in EXPECTED}
    for value in (M.PROJECT, M.LEAD, M.CONTRACT, M.SITE2):
        hits = [n for n, t in texts.items() if value in t]
        assert len(hits) >= 2, f"{value!r} appears in only {hits}; no cross-document reuse"


def test_there_is_something_for_every_slot_category(corpus):
    """Not a claim about what the extractor will find — that is a model's job —
    but a floor: if the corpus contains no money, no date and no identifier,
    a run cannot demonstrate masking those categories at all."""
    joined = " ".join(load(corpus / n).text for n in EXPECTED)
    probes = {
        "PERSON": M.LEAD, "ORG": M.ORG, "PROJECT": M.PROJECT, "LOCATION": M.SITE,
        "DATE": "30 September 2026", "MONEY": "62,567.45", "QUANTITY": "340",
        "IDENTIFIER": M.CONTRACT,
    }
    assert set(probes) == set(SLOT_CATEGORIES), "probe list has drifted from the taxonomy"
    for category, probe in probes.items():
        assert probe in joined, f"nothing in the corpus for {category} ({probe!r})"


def test_regenerating_produces_identical_bytes(tmp_path):
    """`content_doc_id` is a SHA-256 over the file bytes and is what the run
    manifest records, so a generator that embeds a timestamp renames every
    document on every regeneration and two runs over identical content look
    like runs over different corpora. openpyxl and python-docx both do that
    until the container is normalised."""
    a, b = tmp_path / "a", tmp_path / "b"
    M.main(["--out", str(a)])
    M.main(["--out", str(b)])
    for name in EXPECTED:
        da, db = (a / name).read_bytes(), (b / name).read_bytes()
        assert hashlib.sha256(da).digest() == hashlib.sha256(db).digest(), name
        assert content_doc_id(a / name) == content_doc_id(b / name), name


def test_the_written_key_carries_the_mask_patterns(corpus):
    """The masks reach the metric only through the key file, so the file the
    driver loads, not just the module constant, must carry them (INS1)."""
    key = json.loads((corpus / "smoke_fact_key.json").read_text(encoding="utf-8"))
    assert key == json.loads(json.dumps(M.fact_key()))
    patterns = key["mask_patterns"]
    for text in ("30 September", "4th August", "20-28 August", "20–28 August",
                 "(3)"):
        assert any(re.fullmatch(p, text) for p in patterns), text
    for text in ("340", "(51,237.75)", "12%"):
        assert not any(re.search(p, text) for p in patterns), text


def test_the_corpus_is_small_enough_not_to_truncate_the_oracle(corpus):
    """The oracle arm is capped at 60,000 characters while the private arm
    abstracts the whole corpus, so a sample over the cap would make the very
    first comparison not like-for-like."""
    total = sum(len(load(corpus / n).text) for n in EXPECTED)
    assert total < 60_000, f"{total} chars would truncate the oracle baseline"
