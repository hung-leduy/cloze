"""Unit tests for the Markdown loader.

Every fixture is built in `tmp_path`; nothing binary is committed. The tests pin
the two properties downstream stages rely on: `text` is the source with only its
line endings changed, and every block span, sliced from that `text`, begins with
the heading line it claims to cover. If either regresses, slot offsets bound to
Markdown sections silently point at the wrong characters.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest
from privdeep.ingest.md import load_markdown
from privdeep.models.document import Document, DocumentKind, Span

# The brief's sample: CRLF endings, a preamble, headings nested #, ##, ##, #, a
# fenced code block whose body has a line starting with "#", and Vietnamese text.
SAMPLE_CRLF = (
    "Đây là phần mở đầu của tài liệu.\r\n"
    "Nó không nằm dưới tiêu đề nào.\r\n"
    "\r\n"
    "# Tổng quan dự án Zephyr\r\n"
    "Doanh thu quý 3 giảm 12% sau khi thí điểm ở Hà Nội bị huỷ.\r\n"
    "\r\n"
    "## Bối cảnh\r\n"
    "Một đoạn văn có dấu: ă â ê ô ơ ư đ.\r\n"
    "\r\n"
    "```python\r\n"
    "# not a heading, this is a comment\r\n"
    "x = 1\r\n"
    "```\r\n"
    "\r\n"
    "## Kết quả\r\n"
    "Bảng số liệu.\r\n"
    "\r\n"
    "# Phụ lục\r\n"
    "Tài liệu tham khảo.\r\n"
)
SAMPLE_LF = SAMPLE_CRLF.replace("\r\n", "\n")


def write(tmp_path: Path, content: str, name: str = "doc.md") -> Path:
    p = tmp_path / name
    # newline="" so the test controls the bytes on disk exactly.
    with p.open("w", encoding="utf-8", newline="") as fh:
        fh.write(content)
    return p


def labels(doc: Document) -> list[str]:
    return [label for label, _ in doc.blocks]


def assert_well_nested(doc: Document) -> None:
    """Spans are pairwise disjoint or nested, and the outermost ones cover the text exactly."""
    spans = [sp for _, sp in doc.blocks]
    if not doc.text:
        assert spans == []
        return
    for i, a in enumerate(spans):
        assert a.length > 0
        for b in spans[i + 1 :]:
            assert b.start > a.start, "blocks must be in document order with distinct starts"
            nested = b.end <= a.end
            disjoint = b.start >= a.end
            assert nested or disjoint, f"{a} and {b} overlap without nesting"
    outer = [
        sp
        for i, sp in enumerate(spans)
        if not any(o.start <= sp.start and sp.end <= o.end for o in spans[:i])
    ]
    assert outer[0].start == 0
    assert outer[-1].end == len(doc.text)
    for a, b in zip(outer, outer[1:], strict=False):
        assert a.end == b.start, f"gap or overlap between outermost blocks {a} and {b}"


class TestVerbatimText:
    def test_text_is_source_with_crlf_normalised_and_nothing_else(self, tmp_path):
        doc = load_markdown(write(tmp_path, SAMPLE_CRLF))
        assert doc.text == SAMPLE_LF
        assert "\r" not in doc.text
        assert doc.metadata["line_endings"] == "crlf"

    def test_lf_source_is_untouched(self, tmp_path):
        doc = load_markdown(write(tmp_path, SAMPLE_LF))
        assert doc.text == SAMPLE_LF
        assert doc.metadata["line_endings"] == "lf"

    def test_lone_cr_is_normalised_too(self, tmp_path):
        doc = load_markdown(write(tmp_path, "# A\rline\r## B\rmore\r"))
        assert doc.text == "# A\nline\n## B\nmore\n"
        assert doc.metadata["line_endings"] == "cr"
        assert labels(doc) == ["h1: A", "h2: B"]

    def test_mixed_endings_are_reported_as_mixed(self, tmp_path):
        doc = load_markdown(write(tmp_path, "# A\r\nb\nc\r"))
        assert doc.text == "# A\nb\nc\n"
        assert doc.metadata["line_endings"] == "mixed"

    def test_no_unicode_normalisation(self, tmp_path):
        # Decomposed diacritics (NFD) must survive verbatim; the loader may not
        # recompose them, or offsets computed by anyone else would drift.
        nfd = unicodedata.normalize("NFD", "# Tiêu đề\nNội dung có dấu.\n")
        assert nfd != unicodedata.normalize("NFC", nfd)
        doc = load_markdown(write(tmp_path, nfd))
        assert doc.text == nfd
        assert doc.blocks[0][1].slice(doc.text) == nfd

    def test_trailing_whitespace_and_blank_lines_are_kept(self, tmp_path):
        src = "# A   \n\n\n  text with spaces   \n\n"
        doc = load_markdown(write(tmp_path, src))
        assert doc.text == src


class TestBlocks:
    def test_kind_and_labels(self, tmp_path):
        doc = load_markdown(write(tmp_path, SAMPLE_CRLF))
        assert doc.kind is DocumentKind.MARKDOWN
        assert labels(doc) == [
            "preamble",
            "h1: Tổng quan dự án Zephyr",
            "h2: Bối cảnh",
            "h2: Kết quả",
            "h1: Phụ lục",
        ]

    def test_each_heading_span_starts_with_its_heading_line(self, tmp_path):
        doc = load_markdown(write(tmp_path, SAMPLE_CRLF))
        for label, sp in doc.blocks:
            if label == "preamble":
                continue
            level, _, title = label.partition(": ")
            expected_line = "#" * int(level[1:]) + " " + title + "\n"
            assert sp.slice(doc.text).startswith(expected_line), label
            # And the span begins at a line start in the text.
            assert sp.start == 0 or doc.text[sp.start - 1] == "\n"

    def test_code_block_hash_line_is_not_a_heading(self, tmp_path):
        doc = load_markdown(write(tmp_path, SAMPLE_CRLF))
        assert not any("not a heading" in label for label in labels(doc))
        # The line still exists in the text, inside the "Bối cảnh" section.
        (boi_canh,) = [sp for label, sp in doc.blocks if label == "h2: Bối cảnh"]
        assert "# not a heading, this is a comment\n" in boi_canh.slice(doc.text)

    def test_nesting_boundaries(self, tmp_path):
        doc = load_markdown(write(tmp_path, SAMPLE_CRLF))
        by_label = dict(doc.blocks)
        h1a = by_label["h1: Tổng quan dự án Zephyr"]
        h2a = by_label["h2: Bối cảnh"]
        h2b = by_label["h2: Kết quả"]
        h1b = by_label["h1: Phụ lục"]
        # The first h1 runs until the next h1, enclosing both h2 sections.
        assert h1a.end == h1b.start
        assert h1a.start < h2a.start < h2a.end == h2b.start < h2b.end == h1b.start
        # Each h2 stops at the next heading of level <= 2.
        assert h2a.end == h2b.start
        assert h2b.end == h1b.start
        # The last section runs to end of text.
        assert h1b.end == len(doc.text)
        # Sections are nested, not overlapping siblings.
        assert h1a.overlaps(h2a) and h1a.overlaps(h2b) and not h1a.overlaps(h1b)
        assert not h2a.overlaps(h2b)

    def test_preamble_is_everything_before_first_heading(self, tmp_path):
        doc = load_markdown(write(tmp_path, SAMPLE_CRLF))
        label, sp = doc.blocks[0]
        assert label == "preamble"
        assert sp.start == 0
        assert sp.slice(doc.text) == (
            "Đây là phần mở đầu của tài liệu.\nNó không nằm dưới tiêu đề nào.\n\n"
        )
        assert doc.text[sp.end :].startswith("# Tổng quan")

    def test_blocks_are_well_nested_and_cover_the_text(self, tmp_path):
        assert_well_nested(load_markdown(write(tmp_path, SAMPLE_CRLF)))

    def test_h2_spans_lie_inside_their_h1(self, tmp_path):
        doc = load_markdown(write(tmp_path, SAMPLE_CRLF))
        by = dict(doc.blocks)
        parent = by["h1: Tổng quan dự án Zephyr"]
        for child in (by["h2: Bối cảnh"], by["h2: Kết quả"]):
            assert parent.start < child.start and child.end <= parent.end

    def test_vietnamese_offsets_are_code_points(self, tmp_path):
        doc = load_markdown(write(tmp_path, SAMPLE_CRLF))
        (hits,) = doc.find_all("Hà Nội")
        (section,) = [sp for label, sp in doc.blocks if label.startswith("h1: Tổng quan")]
        assert section.start <= hits.start and hits.end <= section.end
        assert hits.slice(doc.text) == "Hà Nội"


class TestEdgeShapes:
    def test_no_headings_gives_single_preamble(self, tmp_path):
        doc = load_markdown(write(tmp_path, "just prose\nno headings\n"))
        assert doc.blocks == [("preamble", Span(0, len(doc.text)))]

    def test_empty_file(self, tmp_path):
        doc = load_markdown(write(tmp_path, ""))
        assert doc.text == ""
        assert doc.blocks == []
        assert doc.metadata["line_endings"] == "none"

    def test_file_starting_with_heading_has_no_preamble(self, tmp_path):
        doc = load_markdown(write(tmp_path, "# First\nbody\n"))
        assert labels(doc) == ["h1: First"]
        assert doc.blocks[0][1] == Span(0, len(doc.text))

    def test_no_trailing_newline(self, tmp_path):
        doc = load_markdown(write(tmp_path, "# A\ntext\n## B\nlast line"))
        assert doc.text.endswith("last line")
        assert dict(doc.blocks)["h2: B"] == Span(doc.text.index("## B"), len(doc.text))
        assert_well_nested(doc)

    def test_closing_hashes_and_padding_are_stripped_from_label(self, tmp_path):
        doc = load_markdown(write(tmp_path, "##   Padded  ##  \n###### Six\n"))
        assert labels(doc) == ["h2: Padded", "h6: Six"]
        # But the span still starts at the raw heading line, hashes and all.
        assert doc.blocks[0][1].slice(doc.text).startswith("##   Padded  ##  \n")

    def test_things_that_look_like_headings_but_are_not(self, tmp_path):
        src = (
            "# Real\n"
            "#nospace\n"
            "####### seven\n"
            "    # indented code\n"
            "<div>\n# inside html block\n</div>\n"
            "~~~\n# tilde fence\n~~~\n"
        )
        doc = load_markdown(write(tmp_path, src))
        assert labels(doc) == ["h1: Real"]

    def test_headings_inside_quote_or_list_are_not_document_structure(self, tmp_path):
        src = "# Top\n> # Quoted\n- # Listed\nafter\n# Next\n"
        doc = load_markdown(write(tmp_path, src))
        assert labels(doc) == ["h1: Top", "h1: Next"]
        # "Top" therefore runs straight through the quote and list to "Next".
        top = dict(doc.blocks)["h1: Top"]
        assert top.end == doc.text.index("# Next")
        assert top.slice(doc.text) == "# Top\n> # Quoted\n- # Listed\nafter\n"

    def test_setext_headings_are_a_documented_limit(self, tmp_path):
        doc = load_markdown(write(tmp_path, "Title\n=====\n# Real\n"))
        assert labels(doc) == ["preamble", "h1: Real"]

    def test_heading_interrupting_paragraph(self, tmp_path):
        doc = load_markdown(write(tmp_path, "para\n# H\nmore\n"))
        assert labels(doc) == ["preamble", "h1: H"]
        assert dict(doc.blocks)["h1: H"].slice(doc.text) == "# H\nmore\n"

    def test_empty_heading_text(self, tmp_path):
        doc = load_markdown(write(tmp_path, "#\nbody\n"))
        assert labels(doc) == ["h1: "]

    def test_bom_is_kept_verbatim(self, tmp_path):
        # A BOM is bytes the loader did not write; it stays, and per CommonMark
        # it stops the first line from being a heading.
        src = "﻿# Not a heading\n## Real\n"
        doc = load_markdown(write(tmp_path, src))
        assert doc.text == src
        assert labels(doc) == ["preamble", "h2: Real"]

    def test_deep_nesting_boundaries(self, tmp_path):
        src = "# A\n### C\n## B\n#### D\n# E\n"
        doc = load_markdown(write(tmp_path, src))
        by = dict(doc.blocks)
        assert by["h3: C"].end == doc.text.index("## B")  # closed by a higher level
        assert by["h2: B"].end == doc.text.index("# E")  # runs past the deeper h4
        assert by["h4: D"].end == doc.text.index("# E")
        assert by["h1: A"].end == doc.text.index("# E")
        assert by["h1: E"].end == len(doc.text)


class TestIdentity:
    def test_doc_id_defaults_to_stem_and_can_be_overridden(self, tmp_path):
        p = write(tmp_path, "# x\n", name="report-q3.md")
        assert load_markdown(p).doc_id == "report-q3"
        assert load_markdown(p, doc_id="custom").doc_id == "custom"
        assert load_markdown(p).source_path == p

    def test_accepts_str_path(self, tmp_path):
        p = write(tmp_path, "# x\n")
        assert load_markdown(str(p)).text == "# x\n"  # type: ignore[arg-type]

    def test_non_utf8_raises_rather_than_guessing(self, tmp_path):
        p = tmp_path / "latin1.md"
        p.write_bytes("# Ph\xf9 l\xf9c\n".encode("latin-1"))
        with pytest.raises(UnicodeDecodeError):
            load_markdown(p)
