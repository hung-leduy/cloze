"""Markdown loader: verbatim text, ATX-heading sections located by character offset.

Why the text is verbatim
------------------------
The `Document` contract makes `text` the single canonical string that every
downstream stage indexes into: the shingle filter hashes it, the slot masker
rewrites it, the reintegrator binds slots to spans of it. A Markdown file is
already text, so the loader has no serialisation decision to make and no
reason to touch the bytes. It performs exactly one transformation: every line
ending (``\\r\\n`` and lone ``\\r``) becomes ``\\n``. Nothing else is altered: no
Unicode normalisation (precomposed and decomposed Vietnamese diacritics survive
as written), no whitespace trimming, no BOM stripping, no entity decoding.
Normalising line endings is required because the parser reasons in lines and a
``\\r`` left in the text would make "start of line N" ambiguous between the two
components; it is the one place the loader is lossy, and `metadata["line_endings"]`
records what the source actually used so the audit trail can say so.

How sections are located
------------------------
``markdown-it`` (CommonMark preset) is used only to *decide which lines are
headings*: it is the reference implementation of the rules that say a ``#``
inside a fenced or indented code block, an HTML block, or after seven hashes is
not a heading. Every ``heading_open`` token carries ``map = [first_line, last_line)``.
The loader takes ``first_line`` and converts it to a character offset itself, by
scanning the normalised text for newlines. No offset produced by the parser is
trusted; the only offsets in the returned `Document` are ones computed from the
returned `text`, and a heading whose line does not in fact begin with the
expected ``#`` run is treated as a loader bug and raised, not silently emitted.

Each ATX heading (``#`` to ``######``) yields one block ``("h<level>: <text>", Span)``
whose span runs from the start of the heading line to the start of the next
heading of the same or higher level, or to the end of the text. Content before
the first heading, if any, is a ``("preamble", Span)`` block. Because a section
runs *through* its subsections, the spans nest: an ``h1`` span contains the
``h2`` spans under it. Any two blocks are therefore either disjoint or one
contains the other, and the outermost blocks together with the preamble cover
the text exactly, in document order, with no gap. A character offset thus lies
in a unique innermost block, and every block enclosing it is an ancestor.

Limits, stated as limits
------------------------
* Setext headings (a line underlined with ``===`` or ``---``) are not sectioned.
  The brief scopes this loader to ATX headings, and a setext heading's extent
  is a two-line construct whose "heading line" is ambiguous.
* Headings nested inside a block quote or a list item are ignored. They are
  headings to CommonMark, but they are not document structure: letting a quoted
  ``# Re: your mail`` close the enclosing section would misplace every slot
  after it.
* The heading text in the label is the raw inline source (``*emph*`` stays
  ``*emph*``, ``\\#`` stays ``\\#``), with the leading and optional closing ``#``
  runs and surrounding whitespace removed as CommonMark specifies.
* The file is decoded as strict UTF-8. A file that is not UTF-8 raises
  `UnicodeDecodeError`; guessing an encoding would be a second, undeclared
  transformation.
"""

from __future__ import annotations

from pathlib import Path

from markdown_it import MarkdownIt

from privdeep.models.document import Document, DocumentKind, Span

__all__ = ["load_markdown"]

_MAX_ATX_INDENT = 3  # CommonMark: up to three spaces of indentation before the '#' run


def _normalise_newlines(raw: str) -> tuple[str, str]:
    """Return (text with every line ending as '\\n', label describing what the source used)."""
    n_crlf = raw.count("\r\n")
    n_cr = raw.count("\r") - n_crlf
    n_lf = raw.count("\n") - n_crlf
    kinds = [name for name, n in (("crlf", n_crlf), ("lf", n_lf), ("cr", n_cr)) if n]
    label = "none" if not kinds else kinds[0] if len(kinds) == 1 else "mixed"
    return raw.replace("\r\n", "\n").replace("\r", "\n"), label


def _line_starts(text: str) -> list[int]:
    """Character offset at which each line begins; line i spans [starts[i], starts[i+1])."""
    starts = [0]
    i = text.find("\n")
    while i != -1:
        starts.append(i + 1)
        i = text.find("\n", i + 1)
    return starts


def _check_heading_line(text: str, start: int, level: int, line_no: int) -> None:
    """Fail loudly if the line the parser called a level-N ATX heading does not look like one."""
    end = text.find("\n", start)
    line = text[start:] if end == -1 else text[start:end]
    body = line.lstrip(" ")
    indent = len(line) - len(body)
    hashes = "#" * level
    ok = (
        indent <= _MAX_ATX_INDENT
        and body.startswith(hashes)
        and (len(body) == level or body[level] in " \t")
    )
    if not ok:
        raise ValueError(
            f"parser reported an h{level} ATX heading at line {line_no} but the text there "
            f"is {line!r}; offsets would be wrong"
        )


def load_markdown(path: Path, doc_id: str | None = None) -> Document:
    """Load a Markdown file as a `Document` with one block per top-level ATX heading.

    `text` is the file content with line endings normalised to ``\\n`` and no other
    change. See the module docstring for what a block is and what is not one.
    """
    path = Path(path)
    # newline="" disables Python's universal-newline translation so the loader
    # sees the source's real line endings and can record them before normalising.
    with path.open(encoding="utf-8", newline="") as fh:
        raw = fh.read()
    text, endings = _normalise_newlines(raw)

    starts = _line_starts(text)
    n = len(text)

    # (level, start_offset, label) for each top-level ATX heading, in document order.
    headings: list[tuple[int, int, str]] = []
    tokens = MarkdownIt("commonmark").parse(text)
    for idx, tok in enumerate(tokens):
        if tok.type != "heading_open" or tok.level != 0 or not tok.markup.startswith("#"):
            continue
        if tok.map is None:
            raise ValueError("heading token without a line map; cannot locate it in the text")
        line_no = tok.map[0]
        if line_no >= len(starts):
            raise ValueError(f"heading reported at line {line_no} but text has {len(starts)} lines")
        level = int(tok.tag[1:])
        start = starts[line_no]
        _check_heading_line(text, start, level, line_no)
        # heading_open is always followed by its inline token; the guard is belt and braces.
        inline = tokens[idx + 1] if idx + 1 < len(tokens) else None
        title = inline.content if inline is not None and inline.type == "inline" else ""
        headings.append((level, start, f"{tok.tag}: {title}"))

    blocks: list[tuple[str, Span]] = []
    first_start = headings[0][1] if headings else n
    if first_start > 0:
        blocks.append(("preamble", Span(0, first_start)))
    for i, (level, start, label) in enumerate(headings):
        end = n
        for later_level, later_start, _ in headings[i + 1 :]:
            if later_level <= level:
                end = later_start
                break
        blocks.append((label, Span(start, end)))

    return Document(
        doc_id=doc_id if doc_id is not None else path.stem,
        kind=DocumentKind.MARKDOWN,
        source_path=path,
        text=text,
        blocks=blocks,
        metadata={"line_endings": endings},
    )
