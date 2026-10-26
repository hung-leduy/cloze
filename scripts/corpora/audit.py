"""The key-audit sheet: every key fact, and the sentence or cell that states it.

B's and C's keys are authored beside their constants, so they cannot drift from
the documents, but an authored key can still be wrong: a value bound to the
wrong project, a figure the prose states under another role, a "derived" fact
that some sentence does state. The author audits that against the rendered
documents, and this sheet is what makes the audit a reading task rather than a
search: it loads each written document through the real loaders and lists,
for every fact, each place one of its spellings occurs.

Mechanical, and only as good as string matching. A numeric fact is found by
its ``money_surfaces`` spellings with the numeral scan's guards (no digit or
decimal separator joining a longer number), a narrative fact by its surfaces,
case-insensitively, and a string fact by its value. Whether the sentence
*binds* the value to the fact's subject and attribute is the auditor's call;
the "names subject" column only says whether a surface of the subject occurs in
the same sentence or table row.

The sheet is generated, and the author's verdicts live in it: the last column
of every row, "Audited", is the one cell the generator never fills.
``carry_marks`` puts a verdict back on regeneration when its row (scenario,
table, and every other cell) is unchanged, and hands back the verdicts whose
row changed or vanished so they can be re-read. ``strip_marks`` blanks the
column, which is how the suite compares the committed sheet to a fresh one.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from types import ModuleType

from corpora import writers as W

__all__ = ["audit_markdown", "carry_marks", "locations", "strip_marks"]

_MARKER = re.compile(r"^## (?:sheet|table): .*$", re.MULTILINE)
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_DERIVATION = {
    "UNSPENT": "AUTHORISED - SPENT",
    "OVERRUN": "SPENT - AUTHORISED",
    "PCT_SPENT": "SPENT / AUTHORISED x 100, to one decimal place",
}


def _col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _sentences(doc) -> list[tuple[str, str]]:
    """(where, sentence) for the prose of one loaded document, cells excluded."""
    text = list(doc.text)
    for c in doc.cells:
        text[c.span.start:c.span.end] = " " * (c.span.end - c.span.start)
    body = _MARKER.sub(lambda m: " " * len(m.group(0)), "".join(text))
    out: list[tuple[str, str]] = []
    pos = 0
    for para in re.split(r"\n\s*\n", body):
        start = body.index(para, pos)
        pos = start + len(para)
        lines = para.split("\n")
        # A docx paragraph is one line and a heading is its own line; md and
        # pdf paragraphs are hard-wrapped and are joined back.
        groups = [[ln] for ln in lines] if doc.kind.name == "DOCX" else [lines]
        offset = start
        for g in groups:
            chunk = " ".join(ln.strip() for ln in g).strip()
            if chunk.startswith("#"):
                chunk = ""
            where = _block_label(doc, offset)
            offset += sum(len(ln) + 1 for ln in g)
            for s in _SENT.split(chunk):
                if s.strip():
                    out.append((where, s.strip()))
    return out


def _block_label(doc, at: int) -> str:
    inside = [(sp.end - sp.start, label) for label, sp in doc.blocks if sp.start <= at < sp.end]
    return min(inside)[1] if inside else ""


def _numeral_rx(surface: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\d.,])" + re.escape(surface) + r"(?![\d]|[.,]\d)")


def _surface_rx(surface: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)" + re.escape(surface) + r"(?!\w)", re.IGNORECASE)


def locations(docs: list, rxs: list[re.Pattern[str]],
              subject_surfaces: list[str]) -> list[tuple[str, str, bool]]:
    """(document and place, quoted sentence or cell, names the subject)."""
    subj = re.compile(r"\b(?:" + "|".join(re.escape(s) for s in subject_surfaces) + r")\b")
    out: list[tuple[str, str, bool]] = []
    for doc in docs:
        name = Path(doc.source_path).name
        grid = {(c.sheet, c.row, c.col): c.value for c in doc.cells}
        for c in doc.cells:
            if c.row == 1 or not any(rx.search(c.value) for rx in rxs):
                continue
            header = grid.get((c.sheet, 1, c.col), "")
            key = grid.get((c.sheet, c.row, 1), "")
            row = " ".join(v for (s, r, _), v in grid.items() if s == c.sheet and r == c.row)
            out.append((f"{name} {c.sheet}!{_col(c.col)}{c.row} (column '{header}', "
                        f"row '{key}')", c.value, bool(subj.search(row))))
        for where, sentence in _sentences(doc):
            if any(rx.search(sentence) for rx in rxs):
                place = f"{name} {where}".strip()
                out.append((place, sentence, bool(subj.search(sentence))))
    return out


def _esc(s: str) -> str:
    return s.replace("|", "\\|")


def _scenario_section(mod: ModuleType, corpus_dir: Path) -> list[str]:
    W.backend_on_path()
    from privdeep.ingest import SUFFIXES, load

    docs = [load(p) for p in sorted(corpus_dir.iterdir()) if p.suffix.lower() in SUFFIXES]
    key = mod.fact_key()
    key_sha = hashlib.sha256(W.dump_key(key).encode("utf-8")).hexdigest()
    lines = [
        f"## {mod.ID} ({mod.__name__.split('.')[-1]}, `{mod.GENERATED_BY}`)",
        "",
        f"Provisional key: `eval/corpora/{mod.ID}/{W.FACT_KEY_NAME}`, sha256 `{key_sha}`.",
        "",
        "| Document | sha256 |",
        "|---|---|",
    ]
    for p in sorted(corpus_dir.iterdir()):
        if p.suffix.lower() in SUFFIXES:
            lines.append(f"| `{p.name}` | `{hashlib.sha256(p.read_bytes()).hexdigest()}` |")
    lines += ["", f"Task goal: \"{mod.GOAL}\"", ""]

    def subject_surfaces(subjects: list[str]) -> list[str]:
        return [s for k in subjects for s in key["referents"][k]]

    lines += ["### Numeric and narrative facts", "",
              "| Fact | Value | Derived | Where | Sentence or cell | Names subject | Audited |",
              "|---|---|---|---|---|---|---|"]
    for f in key["facts"]:
        if f["match"] == "numeric":
            rxs = [_numeral_rx(s) for s in f["surfaces"]]
        else:
            rxs = [_surface_rx(s) for s in f["surfaces"]]
        hits = locations(docs, rxs, subject_surfaces(f["subjects"]))
        subj = f["fact_id"] if len(f["subjects"]) == 1 else (
            f"{f['fact_id']} (also {', '.join(f['subjects'][1:])})")
        derived = "yes" if f["derived"] else "no"
        if not hits:
            how = _DERIVATION.get(f["attribute"], "")
            lines.append(f"| {subj} | {f['value']} | {derived} | not stated in any "
                         f"document | {('= ' + how) if how else ''} | | |")
        for where, text, names in hits:
            lines.append(f"| {subj} | {f['value']} | {derived} | {_esc(where)} | "
                         f"{_esc(text)} | {'yes' if names else 'no'} | |")
    lines += ["", "### String facts", "",
              "| Fact | Value | Where | Sentence or cell | Names subject | Audited |",
              "|---|---|---|---|---|---|"]
    for f in key["string_facts"]:
        hits = locations(docs, [_surface_rx(f["value"])], subject_surfaces([f["subject"]]))
        for where, text, names in hits:
            lines.append(f"| {f['fact_id']} | {f['value']} | {_esc(where)} | {_esc(text)} | "
                         f"{'yes' if names else 'no'} | |")
    return lines + [""]


_PIPE = re.compile(r"(?<!\\)\|")


def _last_cell(line: str) -> tuple[str, str] | None:
    """(the row up to and including the pipe before its last cell, that cell's
    text), or None for a line that is not a table row."""
    if not (line.startswith("|") and line.endswith("|")):
        return None
    pipes = [m.start() for m in _PIPE.finditer(line)]
    if len(pipes) < 3:
        return None
    return line[:pipes[-2] + 1], line[pipes[-2] + 1:-1].strip()


def _rows(text: str):
    """(line index, identity, head, mark) per data row of a table whose last
    column is "Audited" (the document-digest tables are left alone). The
    identity is the scenario heading, the table heading and every cell but
    the last."""
    section = table = ""
    audited = False
    for i, line in enumerate(text.split("\n")):
        if line.startswith("## "):
            section, table = line, ""
        elif line.startswith("### "):
            table = line
        split = _last_cell(line)
        if split is None:
            audited = False
        elif split[1] == "Audited":
            audited = True
        elif audited and not line.startswith("|---"):
            yield i, (section, table, split[0]), split[0], split[1]


def strip_marks(text: str) -> str:
    """The sheet with every Audited cell blank: what the generator writes."""
    lines = text.split("\n")
    for i, _, head, _ in _rows(text):
        lines[i] = head + " |"
    return "\n".join(lines)


def carry_marks(fresh: str, previous: str) -> tuple[str, list[str]]:
    """`fresh` with each Audited cell of `previous` whose row is unchanged.

    Returns the merged sheet and the rows of `previous` whose mark could not be
    carried because the row changed or is gone; those need auditing again.
    Two identical rows in one table share one mark, which is harmless: they
    quote the same sentence at the same place.
    """
    marks = {ident: mark for _, ident, _, mark in _rows(previous) if mark}
    lines = fresh.split("\n")
    used = set()
    for i, ident, head, _ in _rows(fresh):
        if ident in marks:
            lines[i] = f"{head} {marks[ident]} |"
            used.add(ident)
    dropped = [f"{ident[0][3:]} {ident[2]} {marks[ident]}"
               for ident in marks if ident not in used]
    return "\n".join(lines), dropped


def audit_markdown(mods: list[ModuleType], corpora_dir: Path) -> str:
    head = [
        "# Key audit: corpora B, C and D (provisional)",
        "",
        "Plan task EXP1. Generated by `python scripts/corpora --scenario all --audit`",
        "from the written documents, through the real loaders. The keys of",
        "`portfolio-b`, `prose-c` and `offlex-d` are PROVISIONAL until every row below is",
        "marked in the Audited column.",
        "",
        "The generator never fills the Audited column. Since 2026-10-03",
        "(PRIVDEEP_ICCIT_SCOPE.md §11) two independent passes of the AI assistant fill it,",
        "each mark starting `AI:`; the author decides every row marked `AI: needs author`,",
        "and the author's own mark replaces it.",
        "Regenerating keeps each mark whose row (every other cell) is unchanged and",
        "prints the marks it had to drop; the suite compares this file to a fresh",
        "one with the column blanked, so marking a row does not fail it.",
        "`--audit` refuses anything but `--scenario all`, so it cannot rewrite the",
        "sheet without one of its sections.",
        "",
        "Scenario A (`smoke-q3`) is not listed: its key is the one the pilot was",
        "scored against, pinned by sha256 in `backend/tests/unit/test_corpus_scenarios.py`.",
        "",
        "How to read a row. Each row is one place where a spelling of the fact's",
        "value occurs. A numeric fact is matched by every `money_surfaces` spelling",
        "with the numeral scan's guards; a narrative fact by its surfaces,",
        "ignoring case; a string fact by its value. 'Names subject' says only",
        "whether a surface of the fact's subject occurs in the same sentence or",
        "table row. Whether the sentence binds the value to that subject *and*",
        "attribute is what the audit decides. A fact with `Derived: yes` should",
        "have no row other than 'not stated in any document': in B, C and D",
        "`derived` means exactly that no document states the value, which is how",
        "`coverage_stated` reads it.",
        "",
        "The provisional key SHAs below are the plan's log for EXP1. The frozen",
        "SHAs go into the `paper-freeze` tag message after EXP2's fix to the RBA",
        "attribute lexicon (`scripts/corpora/rba_lexicon.py`, not",
        "`tier1_local/header_lexicon.py`), which changes every key's bytes.",
        "`test_corpus_scenarios.py` fails when a key no longer matches the SHA",
        "logged here, so regenerate this file (and re-audit the rows whose marks",
        "were dropped) whenever a key changes.",
        "",
    ]
    body: list[str] = []
    for mod in mods:
        body += _scenario_section(mod, corpora_dir / mod.ID)
    return "\n".join(head + body)
