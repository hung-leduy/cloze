#!/usr/bin/env python3
"""Track L's collections, rebuilt from the Text Anonymization Benchmark by rule.

Why this exists
---------------
Scope §12 (drafted 2026-10-05) measures whether any personal identifier in a
real document reaches the cloud through PrivDeep's own egress. The documents
are ECHR judgments from TAB (Pilán et al., 2022), whose identifiers were
labelled by annotators unrelated to PrivDeep, so the gold is not ours to bend.
TAB's texts are not ours to redistribute either: ``data/tab/`` is gitignored,
and so is everything this script writes under ``eval/real/corpora/``. What is
committed is the rule (this file and ``function_words.txt``), the two tasks
files and ``eval/real/manifest_l.json``, which holds document ids and hashes
only. Anyone with TAB rebuilds the collections byte for byte and checks them
against that manifest with ``--check``.

The rule (scope §12.3, fixed before any test judgment was read)
---------------------------------------------------------------
A judgment is eligible when it has at least 4 annotators, at most 8,000
characters of text (code points), and ``meta.countries == "GBR"``. Eligible
judgments are taken in ascending ``doc_id`` compared as strings, so
``001-106448`` sorts before ``001-57819``. ``tab-L0`` is the first 4 eligible
judgments of the dev split, the only collection inspected by eye; ``tab-L1`` to
``tab-L6`` are the first 24 of the test split, in 6 consecutive groups of 4.
Only ``text`` is written: ``meta.applicant`` names the protected person and
``task`` repeats the name, so neither field is read past eligibility.

The gold (scope §12.4)
----------------------
Every mention any annotator typed DIRECT or QUASI; NO_MASK mentions are not
identifiers. The unit is the identifier string: two spans are one string when
the containment tokenizer gives them the same tokens. That is the sameness
``token_hits`` scores crossings with, so the gold and the scan cannot disagree
about what a string is. A string any annotator typed DIRECT is DIRECT, and it
keeps every entity type it was typed with. A string goes to the ``labels``
group, reported apart, when its tokens written with one separator between
them hold at most 2 characters (so only a single token of 1 or 2 characters
qualifies), or when every token is a goal token or a function word: a
whole-token hit on ``UK`` or ``the`` says nothing about a judgment. Both tests
read the tokens, not the spelling, so the grouping does not depend on which
annotator's spelling was seen first; and a string of two or more tokens is
never a label by length, so initials such as ``A.B.`` stay identifiers (the
separators were once dropped, which put a DIRECT name of two initials among
the labels and out of HL1).

What a collection directory holds, and nothing else
---------------------------------------------------
``doc1.md`` to ``doc4.md`` (each judgment's ``text`` verbatim, UTF-8, in
``doc_id`` order); ``identifiers.json`` (every string with its identifier
type, entity types and label flag); ``surfaces.json`` (the groups the crossing
scans read: ``direct``, ``quasi_<type>`` and ``labels``); ``smoke_fact_key.json``
(the non-label strings as ``string_facts`` of a key with no numeric facts, one
per string and entity type, which is how ``tier1_probe`` reads recall); and
``MANIFEST.json``. Any other ``.md`` file there would be ingested as a
document, so the builder refuses to write into a directory that holds anything
else.

Refusals
--------
The builder writes nothing when ``data/tab/SHA256SUMS`` does not match the
files or the split files are not the ones scope §12.2 records, when a split has
fewer eligible judgments than the rule takes, when a mention carries a type TAB
does not define, when the goal shares a 5-gram with any judgment of TAB's dev
or test split (the two downloaded; the train split is not), when a collection
directory inside the repository is not gitignored, or when the build differs
from the committed manifest or tasks files (``--update-committed`` rewrites
those deliberately, for review in the diff). Its messages name doc ids, file
names and counts, never a judgment's text or an identifier string.

Usage
-----
    python scripts/real_corpora/tab.py --tab data/tab --out eval/real/corpora
    python scripts/real_corpora/tab.py --tab data/tab --out eval/real/corpora --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from shared.shingle_filter import tokenize  # noqa: E402

__all__ = ["COLLECTION_NAMES", "DATA_NAMES", "DOC_NAMES", "GOAL", "Build", "Collection",
           "IdentifierString", "Refusal", "build", "check", "check_goal", "eligible", "fact_key",
           "git_ignores",
           "identifier_strings", "is_label", "load_function_words", "main", "select",
           "surface_groups", "verify_sums", "write"]

GENERATED_BY = "scripts/real_corpora/tab.py"
# Scope §12.3. Identical for every collection; `check_goal` holds it to the
# scope's claim that it shares no 5-gram with any TAB judgment.
GOAL = ("Compare the applicants' situations, their complaints and the domestic "
        "proceedings described in these case files.")
MIN_ANNOTATORS = 4
MAX_TEXT_CHARS = 8000
RESPONDENT_STATE = "GBR"
DOCS_PER_COLLECTION = 4
TEST_COLLECTIONS = 6
DEV_ID = "tab-L0"
TEST_IDS = tuple(f"tab-L{i}" for i in range(1, TEST_COLLECTIONS + 1))
SPLITS = {"dev": "echr_dev.json", "test": "echr_test.json"}
SUMS_NAME = "SHA256SUMS"
# The download scope §12.2 records. SHA256SUMS sits beside the files it
# describes, so on its own it shows only that they agree with each other; this
# pins them to the download the scope names.
SOURCE_SHA256: dict[str, str] | None = {
    "echr_dev.json": "8c3c7306f46b8d54debeb38ae11d8b0b8bcf4bdccbc3b6f13c12ad7be16893ec",
    "echr_test.json": "cd0f0f15f84a8739654c7cf30c6be8ce27b051ef73974d39d792a0cb8c846379",
}
GOAL_NGRAM = 5          # the containment filter's n_min
LABEL_MAX_CHARS = 2
IDENTIFIER_TYPES = ("DIRECT", "QUASI")
TAB_IDENTIFIER_TYPES = frozenset({*IDENTIFIER_TYPES, "NO_MASK"})
ENTITY_TYPES = ("CODE", "DATETIME", "DEM", "LOC", "MISC", "ORG", "PERSON", "QUANTITY")

DOC_NAMES = tuple(f"doc{i}.md" for i in range(1, DOCS_PER_COLLECTION + 1))
IDENTIFIERS_NAME = "identifiers.json"
SURFACES_NAME = "surfaces.json"           # run_evaluation.SURFACES_NAME
KEY_NAME = "smoke_fact_key.json"          # run_evaluation.FACT_KEY_NAME
MANIFEST_NAME = "MANIFEST.json"
DATA_NAMES = (*DOC_NAMES, IDENTIFIERS_NAME, KEY_NAME, SURFACES_NAME)
COLLECTION_NAMES = frozenset({*DATA_NAMES, MANIFEST_NAME})

FUNCTION_WORDS = Path(__file__).resolve().with_name("function_words.txt")
DEFAULT_TAB = _REPO / "data" / "tab"
DEFAULT_OUT = _REPO / "eval" / "real" / "corpora"
DEFAULT_MANIFEST = _REPO / "eval" / "real" / "manifest_l.json"
DEFAULT_TASKS_DIR = _REPO / "eval" / "real"
TASKS_DEV_NAME, TASKS_TEST_NAME = "tasks_l_dev.json", "tasks_l.json"


class Refusal(Exception):
    """The builder declines to write. The message says why, without TAB text."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dump(obj: Any, *, sort_keys: bool = True) -> bytes:
    """JSON as every file here is written: sorted keys unless the order is the
    content, two-space indent, UTF-8 rather than escapes, a final newline."""
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=sort_keys) + "\n").encode()


def _rel(p: Path) -> str:
    p = p.resolve()
    return p.relative_to(_REPO).as_posix() if p.is_relative_to(_REPO) else str(p)


# ----------------------------------------------------------------------- the source


def verify_sums(tab: Path) -> dict[str, str]:
    """Every file SHA256SUMS lists, hashed and compared, and the split files pinned.

    Any listed file, not only the splits: a README or licence that changed
    means the download is not the one the scope records. Returns name -> sha256.
    """
    sums = tab / SUMS_NAME
    if not sums.is_file():
        raise Refusal(f"{sums} is missing; the TAB download cannot be verified")
    listed: dict[str, str] = {}
    for n, line in enumerate(sums.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise Refusal(f"{SUMS_NAME} line {n} is not a sha256sum line")
        digest, name = parts[0].lower(), parts[1].strip().removeprefix("*")
        if Path(name).name != name:
            raise Refusal(f"{SUMS_NAME} line {n} names a path outside {tab}")
        listed[name] = digest
    for name in SPLITS.values():
        if name not in listed:
            raise Refusal(f"{SUMS_NAME} does not list {name}")
    for name, digest in sorted(listed.items()):
        f = tab / name
        if not f.is_file():
            raise Refusal(f"{name} is listed in {SUMS_NAME} but missing from {tab}")
        if _sha256(f.read_bytes()) != digest:
            raise Refusal(f"{name} does not match its line in {SUMS_NAME}")
    for name, digest in (SOURCE_SHA256 or {}).items():
        if listed[name] != digest:
            raise Refusal(f"{name} is not the download scope §12.2 records "
                          f"(sha256 {listed[name][:12]}..., expected {digest[:12]}...)")
    return listed


def load_split(path: Path) -> list[dict[str, Any]]:
    docs = json.loads(path.read_bytes())
    if not isinstance(docs, list):
        raise Refusal(f"{path.name} is not a list of judgments")
    ids = [d["doc_id"] for d in docs]
    if len(set(ids)) != len(ids):
        raise Refusal(f"{path.name} repeats a doc_id; 'ascending doc_id' would not be an order")
    return docs


def is_eligible(doc: dict[str, Any]) -> bool:
    return (len(doc["annotations"]) >= MIN_ANNOTATORS
            and len(doc["text"]) <= MAX_TEXT_CHARS
            and doc["meta"]["countries"] == RESPONDENT_STATE)


def eligible(docs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The eligible judgments in ascending doc_id, compared as strings."""
    return sorted((d for d in docs if is_eligible(d)), key=lambda d: d["doc_id"])


def select(dev: list[dict[str, Any]], test: list[dict[str, Any]]
           ) -> list[tuple[str, str, list[dict[str, Any]]]]:
    """(collection id, split, judgments) in collection order. Never mixes splits:
    L0 is read by eye, and nothing read by eye may reach a test collection."""
    e_dev, e_test = eligible(dev), eligible(test)
    need = DOCS_PER_COLLECTION * TEST_COLLECTIONS
    if len(e_dev) < DOCS_PER_COLLECTION:
        raise Refusal(f"the dev split has {len(e_dev)} eligible judgments; "
                      f"{DEV_ID} needs {DOCS_PER_COLLECTION}")
    if len(e_test) < need:
        raise Refusal(f"the test split has {len(e_test)} eligible judgments; "
                      f"{TEST_IDS[0]}..{TEST_IDS[-1]} need {need}")
    out = [(DEV_ID, "dev", e_dev[:DOCS_PER_COLLECTION])]
    for i, cid in enumerate(TEST_IDS):
        out.append((cid, "test", e_test[i * DOCS_PER_COLLECTION:(i + 1) * DOCS_PER_COLLECTION]))
    return out


def _grams(tokens: Sequence[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def check_goal(goal: str, judgments: Iterable[dict[str, Any]]) -> None:
    """Refuse a goal that shares a 5-gram with any judgment.

    The goal crosses verbatim by design and the scans cut it out of the trace
    (`scan_trace`'s ``user-goal`` side). A goal holding a run of five judgment
    words would make that cut hide a real crossing, and the monitor would
    refuse the planning request outright.
    """
    mine = _grams(tokenize(goal), GOAL_NGRAM)
    for d in judgments:
        shared = mine & _grams(tokenize(d["text"]), GOAL_NGRAM)
        if shared:
            # The count and the doc id only: a shared 5-gram is judgment text,
            # and the judgment may be a test one.
            raise Refusal(f"the goal shares {len(shared)} {GOAL_NGRAM}-gram(s) with judgment "
                          f"{d['doc_id']}")


# ------------------------------------------------------------------------- the gold


def load_function_words(path: Path = FUNCTION_WORDS) -> frozenset[str]:
    words: set[str] = set()
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        w = line.strip()
        if not w or w.startswith("#"):
            continue
        if tokenize(w) != [w]:
            raise Refusal(f"{path.name} line {n} is not one lowercase token")
        words.add(w)
    return frozenset(words)


@dataclass(frozen=True, slots=True)
class IdentifierString:
    tokens: tuple[str, ...]
    text: str                       # the first-seen spelling
    identifier_type: str            # DIRECT | QUASI
    entity_types: tuple[str, ...]   # sorted
    label: bool

    def to_json(self) -> dict[str, Any]:
        return {"text": self.text, "identifier_type": self.identifier_type,
                "entity_types": list(self.entity_types), "label": self.label}


def is_label(tokens: Sequence[str], goal_tokens: frozenset[str],
             function_words: frozenset[str]) -> bool:
    """Whether a string goes to the labels group.

    The length is that of the tokens joined by one separator, so it depends on
    the tokens and not on the spelling seen first (``(7)`` and ``7`` alike),
    and two tokens, which need a separator between them in any text, are never
    short enough: ``A.B.`` is 3 characters here, as initials are an identifier.
    A string with no tokens at all, which ``token_hits`` can never find, is a
    label.
    """
    return (len(" ".join(tokens)) <= LABEL_MAX_CHARS
            or all(t in goal_tokens or t in function_words for t in tokens))


def _mentions(doc: dict[str, Any]) -> Iterator[tuple[str, int, dict[str, Any]]]:
    """A judgment's mentions in a fixed order: annotators by name, then by
    offsets. The order decides only which spelling a string keeps as its text."""
    for ann in sorted(doc["annotations"]):
        ms = doc["annotations"][ann]["entity_mentions"]
        for i in sorted(range(len(ms)),
                        key=lambda i: (ms[i]["start_offset"], ms[i]["end_offset"], i)):
            yield ann, i, ms[i]


def _order(s: IdentifierString) -> tuple[bool, bool, tuple[str, ...]]:
    return (s.identifier_type != "DIRECT", s.label, s.tokens)


def identifier_strings(docs: Sequence[dict[str, Any]], goal: str = GOAL,
                       function_words: frozenset[str] | None = None) -> list[IdentifierString]:
    """The collection's identifier strings, DIRECT first, then by tokens."""
    fw = load_function_words() if function_words is None else function_words
    goal_tokens = frozenset(tokenize(goal))
    seen: dict[tuple[str, ...], tuple[str, set[str], set[str]]] = {}
    for doc in docs:
        for ann, i, m in _mentions(doc):
            itype, etype = m["identifier_type"], m["entity_type"]
            if itype not in TAB_IDENTIFIER_TYPES or etype not in ENTITY_TYPES:
                raise Refusal(f"judgment {doc['doc_id']}, {ann} mention {i}: identifier or "
                              "entity type is not one TAB defines")
            if itype not in IDENTIFIER_TYPES:
                continue
            toks = tuple(tokenize(m["span_text"]))
            _, itypes, etypes = seen.setdefault(toks, (m["span_text"], set(), set()))
            itypes.add(itype)
            etypes.add(etype)
    strings = [IdentifierString(toks, text, "DIRECT" if "DIRECT" in it else "QUASI",
                                tuple(sorted(et)), is_label(toks, goal_tokens, fw))
               for toks, (text, it, et) in seen.items()]
    return sorted(strings, key=_order)


def surface_groups(strings: Iterable[IdentifierString]) -> dict[str, list[str]]:
    """surfaces.json's groups. Every group is present, empty or not, so the
    collections share one shape; a QUASI string goes in each of its types."""
    groups: dict[str, list[str]] = {"direct": [], "labels": [],
                                    **{f"quasi_{t.lower()}": [] for t in ENTITY_TYPES}}
    for s in strings:
        if s.label:
            groups["labels"].append(s.text)
        elif s.identifier_type == "DIRECT":
            groups["direct"].append(s.text)
        else:
            for t in s.entity_types:
                groups[f"quasi_{t.lower()}"].append(s.text)
    return groups


def fact_key(cid: str, strings: Iterable[IdentifierString]) -> dict[str, Any]:
    """A gold key with no numeric facts, for ``tier1_probe``'s recall.

    One string fact per non-label string and entity type, mirroring the
    surfaces groups; the labels group is left out, as it is reported apart.
    """
    facts: list[dict[str, str]] = []
    for s in strings:
        if s.label:
            continue
        for t in s.entity_types:
            facts.append({"fact_id": f"{cid}.S{len(facts) + 1}", "subject": "TAB",
                          "attribute": f"{s.identifier_type}_{t}", "value": s.text})
    return {"generated_by": GENERATED_BY, "scenario": cid, "referents": {}, "attributes": {},
            "facts": [], "string_facts": facts, "mask_patterns": []}


# ---------------------------------------------------------------------- the build


@dataclass(frozen=True)
class Collection:
    id: str
    split: str
    doc_ids: tuple[str, ...]
    strings: tuple[IdentifierString, ...]
    files: dict[str, bytes]          # every file of the directory, MANIFEST.json included
    manifest: dict[str, Any]


@dataclass(frozen=True)
class Build:
    collections: tuple[Collection, ...]
    summary: bytes                   # eval/real/manifest_l.json
    tasks: dict[str, bytes]          # tasks file name -> bytes


def build_collection(cid: str, split: str, docs: Sequence[dict[str, Any]], source_sha256: str,
                     function_words: frozenset[str]) -> Collection:
    files = {name: d["text"].encode("utf-8") for name, d in zip(DOC_NAMES, docs, strict=True)}
    strings = identifier_strings(docs, GOAL, function_words)
    files[IDENTIFIERS_NAME] = _dump({"collection": cid,
                                     "strings": [s.to_json() for s in strings]})
    files[SURFACES_NAME] = _dump({"groups": surface_groups(strings)})
    files[KEY_NAME] = _dump(fact_key(cid, strings))
    manifest = {"collection": cid, "split": split, "doc_ids": [d["doc_id"] for d in docs],
                "source_sha256": source_sha256,
                "files": {n: _sha256(b) for n, b in sorted(files.items())}}
    files[MANIFEST_NAME] = _dump(manifest)
    return Collection(cid, split, tuple(manifest["doc_ids"]), tuple(strings), files, manifest)


def _tasks(colls: Iterable[Collection], out: Path) -> bytes:
    """A tasks file for run_evaluation.load_tasks. The corpus is repo-relative
    when it is under the repository, as eval/tasks.json's are."""
    rows = [{"id": c.id, "corpus": _rel(out / c.id), "goal": GOAL} for c in colls]
    return _dump(rows, sort_keys=False)


def build(tab: Path, out: Path) -> Build:
    """Everything the rule writes, in memory; nothing is written here."""
    sums = verify_sums(tab)
    splits = {name: load_split(tab / fname) for name, fname in SPLITS.items()}
    check_goal(GOAL, [d for docs in splits.values() for d in docs])
    fw = load_function_words()
    colls = tuple(build_collection(cid, split, docs, sums[SPLITS[split]], fw)
                  for cid, split, docs in select(splits["dev"], splits["test"]))
    summary = {
        "generated_by": GENERATED_BY,
        "rule": {"min_annotators": MIN_ANNOTATORS, "max_text_chars": MAX_TEXT_CHARS,
                 "respondent_state": RESPONDENT_STATE,
                 "order": "ascending doc_id, compared as strings",
                 "docs_per_collection": DOCS_PER_COLLECTION,
                 "dev_collections": [DEV_ID], "test_collections": list(TEST_IDS),
                 "goal": GOAL, "goal_ngram_checked": GOAL_NGRAM,
                 "label_max_chars": LABEL_MAX_CHARS,
                 "label_rule": ("label when the tokens joined by one separator hold at most "
                                "label_max_chars characters, or every token is a goal token or "
                                "a function word"),
                 "function_words_sha256": _sha256(FUNCTION_WORDS.read_bytes())},
        "sources": {split: {"file": fname, "sha256": sums[fname]}
                    for split, fname in SPLITS.items()},
        "collections": {c.id: c.manifest for c in colls},
    }
    tasks = {TASKS_DEV_NAME: _tasks((c for c in colls if c.split == "dev"), out),
             TASKS_TEST_NAME: _tasks((c for c in colls if c.split == "test"), out)}
    return Build(colls, _dump(summary), tasks)


def _committed(b: Build, manifest: Path, tasks_dir: Path) -> dict[Path, bytes]:
    return {manifest: b.summary, **{tasks_dir / n: data for n, data in b.tasks.items()}}


def _difference(old: bytes, new: bytes) -> str:
    """Which entries of a committed JSON file differ, by key only: the summary
    holds ids and hashes, but a message is no place to start quoting files."""
    try:
        a, b = json.loads(old), json.loads(new)
    except ValueError:
        return "not JSON"
    if isinstance(a, dict) and isinstance(b, dict):
        keys = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
        colls_a, colls_b = a.get("collections"), b.get("collections")
        if "collections" in keys and isinstance(colls_a, dict) and isinstance(colls_b, dict):
            ids = sorted(k for k in colls_a.keys() | colls_b.keys()
                         if colls_a.get(k) != colls_b.get(k))
            keys = [k for k in keys if k != "collections"] + [f"collections.{i}" for i in ids]
        return "entries " + ", ".join(keys) if keys else "formatting only"
    return "content"


def git_ignores(path: Path) -> bool | None:
    """Whether git ignores `path`, a file that need not exist yet; None when git
    cannot say. Untracked and ignored: a tracked path is reported as not
    ignored, which is the answer wanted here."""
    git = shutil.which("git")
    if not git:
        return None
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")}
    rel = path.resolve().relative_to(_REPO).as_posix()
    p = subprocess.run([git, "-C", str(_REPO), "check-ignore", "-q", "--", rel],  # noqa: S603
                       env=env, capture_output=True, text=True, check=False)
    return {0: True, 1: False}.get(p.returncode)


def _unignored(out: Path, ids: Iterable[str]) -> list[str]:
    """The collection directories under the repository that git would not
    ignore. Judgment text written there could be staged and committed, which
    scope §12.2 rules out; a directory outside the repository (a test's tmp
    path) is the caller's business."""
    bad = []
    for cid in ids:
        doc = out / cid / DOC_NAMES[0]
        if not doc.resolve().is_relative_to(_REPO):
            continue
        ignored = git_ignores(doc)
        if ignored is not True:
            why = "git cannot tell" if ignored is None else "not ignored"
            bad.append(f"{_rel(out / cid)} ({why})")
    return bad


def _foreign_entries(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir() if p.name not in COLLECTION_NAMES or not p.is_file())


def write(b: Build, out: Path, manifest: Path, tasks_dir: Path, *,
          update_committed: bool = False) -> None:
    """Write the collections, the manifest and the tasks files, or nothing.

    A committed file that the build would change is refused unless asked: after
    the ``real-prereg`` tag the manifest is what the frozen batch is checked
    against, and a rebuild that silently rewrote it would check nothing.
    """
    committed = _committed(b, manifest, tasks_dir)
    stale = [f"{_rel(p)} ({_difference(p.read_bytes(), data)})"
             for p, data in committed.items() if p.is_file() and p.read_bytes() != data]
    if stale and not update_committed:
        raise Refusal("this build differs from " + "; ".join(stale) + ". Pass "
                      "--update-committed to rewrite them deliberately, or --manifest and "
                      "--tasks-dir for a build outside eval/real/")
    if bad := _unignored(out, (c.id for c in b.collections)):
        raise Refusal("judgment text may only be written where git ignores it; "
                      + "; ".join(bad))
    for c in b.collections:
        d = out / c.id
        if d.exists() and not d.is_dir():
            raise Refusal(f"{_rel(d)} exists and is not a directory")
        if d.is_dir() and (foreign := _foreign_entries(d)):
            raise Refusal(f"{_rel(d)} holds entries the rule does not write "
                          f"({', '.join(foreign)}); a stray .md there would be ingested as a "
                          "document. Remove them first")
    for c in b.collections:
        d = out / c.id
        d.mkdir(parents=True, exist_ok=True)
        for name, data in sorted(c.files.items()):
            (d / name).write_bytes(data)
    for p, data in committed.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def check(b: Build, out: Path, manifest: Path, tasks_dir: Path) -> list[str]:
    """What on disk differs from this build; empty when everything matches.
    Reads only: the frozen batch runs this before it spends anything."""
    problems: list[str] = []
    for p, data in _committed(b, manifest, tasks_dir).items():
        if not p.is_file():
            problems.append(f"{_rel(p)} is missing")
        elif p.read_bytes() != data:
            problems.append(f"{_rel(p)} differs from this build "
                            f"({_difference(p.read_bytes(), data)})")
    for c in b.collections:
        d = out / c.id
        if not d.is_dir():
            problems.append(f"{_rel(d)} is missing")
            continue
        names = {p.name for p in d.iterdir()}
        if missing := sorted(COLLECTION_NAMES - names):
            problems.append(f"{c.id} lacks {', '.join(missing)}")
        if foreign := _foreign_entries(d):
            problems.append(f"{c.id} holds entries the rule does not write: {', '.join(foreign)}")
        for name, data in sorted(c.files.items()):
            f = d / name
            if f.is_file() and _sha256(f.read_bytes()) != _sha256(data):
                problems.append(f"{c.id}/{name} differs from this build")
    return problems


def report(b: Build) -> list[str]:
    """Counts and hashes, never strings: the test collections' are not to be read."""
    lines = []
    for c in b.collections:
        live = [s for s in c.strings if not s.label]
        n_direct = sum(1 for s in live if s.identifier_type == "DIRECT")
        lines.append(f"{c.id} {c.split} {','.join(c.doc_ids)}: strings DIRECT {n_direct}, "
                     f"QUASI {len(live) - n_direct}, labels {len(c.strings) - len(live)}; "
                     f"MANIFEST.json {_sha256(c.files[MANIFEST_NAME])}")
    lines.append(f"manifest_l.json {_sha256(b.summary)}")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build track L's collections from TAB (scope §12).")
    ap.add_argument("--tab", type=Path, default=DEFAULT_TAB,
                    help="the TAB download: echr_dev.json, echr_test.json, SHA256SUMS")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help="where the collection directories go (gitignored)")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST,
                    help="the committed summary of every collection's MANIFEST.json")
    ap.add_argument("--tasks-dir", type=Path, default=DEFAULT_TASKS_DIR,
                    help=f"where {TASKS_DEV_NAME} and {TASKS_TEST_NAME} go")
    ap.add_argument("--check", action="store_true",
                    help="rebuild in memory and compare with what is on disk; write nothing")
    ap.add_argument("--update-committed", action="store_true",
                    help="rewrite the manifest and tasks files when this build differs")
    args = ap.parse_args(argv)
    if args.check and args.update_committed:
        ap.error("--check writes nothing; --update-committed cannot apply")
    try:
        b = build(args.tab, args.out)
        if args.check:
            problems = check(b, args.out, args.manifest, args.tasks_dir)
            for line in report(b):
                print(line)
            for p in problems:
                print(f"check: {p}", file=sys.stderr)
            print("check: " + (f"{len(problems)} problem(s)" if problems else
                               f"ok, {len(b.collections)} collections match {_rel(args.manifest)}"))
            return 1 if problems else 0
        write(b, args.out, args.manifest, args.tasks_dir, update_committed=args.update_committed)
    except Refusal as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    for line in report(b):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
