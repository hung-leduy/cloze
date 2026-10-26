#!/usr/bin/env python3
"""What a standard redactor leaves of track L's identifier strings (scope §12.6).

Why this exists
---------------
A reader of track L's crossing counts will ask what an off-the-shelf redactor
would have left in text it sends. This answers it for Microsoft Presidio in its
default configuration, offline and free: each judgment is anonymised by
``AnalyzerEngine`` and ``AnonymizerEngine`` as constructed with no arguments
(spaCy ``en_core_web_lg``, language ``en``, the default recognizers, the default
``replace`` operator). A non-label identifier string *survives* when
``token_hits``, the function that scores PrivDeep's crossings, finds it
whole-token in the anonymised text of any document of the collection.

The two figures are reported side by side, never as one ranking: Presidio's is
what a redactor leaves in text, and PrivDeep sends an abstract payload, not
text.

What is counted
---------------
Per collection and per (identifier type, entity type): ``n`` non-label
identifier strings, ``k`` of them surviving, and ``present``, those found
whole-token in the original documents, which bounds ``k`` in practice. Two
readings of "finds it", because ``token_hits`` consumes the longest needle
first:

* ``k``, ``present``, the primary reading: each string looked for on its own,
  so a string left standing inside a longer one counts as left standing.
  ``scripts/real_l.py`` decides a crossing the same way (its needle groups
  share no token, which gives the same answer as one string at a time), so
  the two figures scope §12.6 sets side by side are counted under one rule.
* ``k_one_call``, ``present_one_call``, descriptive: every non-label string a
  needle of one call, as ``scan_trace`` scores a trace for H3, so a string
  seen only inside a longer one that is also found (a day and month inside
  the full date that holds them) is not counted. On tab-L0, 34 of the 226
  non-label strings occur in the documents only so. real_l.py's ``one_call``
  is built over the same non-label needles.

A string typed with several entity types is counted under each, as
``surfaces.json`` groups it, and once under ``total``. The labels group is
left out, and only its size is recorded.

What it writes
--------------
``eval/real/out/presidio_<id>.json`` (gitignored): counts, the hashes of the
collection's files, Presidio's own result counts per document and entity type,
and the exact package and model versions. No document text, anonymised text or
identifier string is written or printed. The collection is checked against its
``MANIFEST.json`` first, so a result belongs to the build the committed
manifest names, and the installed versions must be the ones the scope pins.

``score`` and ``read_collection`` need neither Presidio nor spaCy; only
``presidio_engine`` imports them, so the scoring is tested in the main venv.

Usage
-----
    .venv-presidio/bin/python scripts/presidio_residual.py \\
        --tasks eval/real/tasks_l_dev.json --out eval/real/out
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "backend" / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.real_corpora import tab as T  # noqa: E402
from scripts.run_evaluation import load_tasks, token_hits  # noqa: E402

__all__ = ["CONFIGURATION", "PINNED", "Collection", "Refusal", "main", "presidio_engine",
           "read_collection", "run", "score"]

GENERATED_BY = "scripts/presidio_residual.py"
DEFAULT_TASKS = _REPO / "eval" / "real" / "tasks_l.json"
DEFAULT_OUT = _REPO / "eval" / "real" / "out"
LANGUAGE = "en"
MODEL = "en_core_web_lg"
# Scope §12.6. A result from other versions is a different redactor.
PINNED = {"presidio-analyzer": "2.2.362", "presidio-anonymizer": "2.2.362",
          "en-core-web-lg": "3.8.0"}
CONFIGURATION = {"analyzer": "AnalyzerEngine() with no arguments: default NLP engine "
                             "and recognizer registry",
                 "anonymizer": "AnonymizerEngine() with no operators: default 'replace'",
                 "language": LANGUAGE, "model": MODEL}

# text -> (anonymised text, Presidio's result count per entity type)
Anonymiser = Callable[[str], tuple[str, dict[str, int]]]


class Refusal(Exception):
    """The script declines to score. The message names files, never their text."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Collection:
    id: str
    documents: tuple[tuple[str, str], ...]    # (file name, text), doc1.md first
    strings: tuple[dict[str, Any], ...]       # identifiers.json's
    files: dict[str, str]                     # name -> sha256, from MANIFEST.json
    manifest_sha256: str


def read_collection(cid: str, corpus: Path, summary: dict[str, Any] | None) -> Collection:
    """The collection as its MANIFEST.json describes it, or a refusal.

    The directory must hold exactly the files the builder writes, each matching
    the hash its MANIFEST.json gives it, and that manifest must be the entry the
    committed summary (``eval/real/manifest_l.json``) holds for it, so the figure
    is about the committed build. ``summary=None`` skips only the last check,
    for a collection built outside the committed record.
    """
    mpath = corpus / T.MANIFEST_NAME
    if not mpath.is_file():
        raise Refusal(f"{cid}: no {T.MANIFEST_NAME}; build it with scripts/real_corpora/tab.py")
    raw = mpath.read_bytes()
    manifest = json.loads(raw)
    if manifest.get("collection") != cid:
        raise Refusal(f"{cid}: {T.MANIFEST_NAME} names another collection")
    if summary is not None and (summary.get("collections") or {}).get(cid) != manifest:
        raise Refusal(f"{cid}: {T.MANIFEST_NAME} is not the committed manifest's entry for it")
    names = {p.name for p in corpus.iterdir()}
    if names != T.COLLECTION_NAMES:
        odd = sorted(names ^ T.COLLECTION_NAMES)
        raise Refusal(f"{cid}: the directory does not hold exactly the builder's files "
                      f"({', '.join(odd)})")
    files = dict(manifest.get("files") or {})
    if set(files) != set(T.DATA_NAMES):
        raise Refusal(f"{cid}: {T.MANIFEST_NAME} does not list the builder's files")
    for name, digest in sorted(files.items()):
        if _sha256((corpus / name).read_bytes()) != digest:
            raise Refusal(f"{cid}: {name} does not match {T.MANIFEST_NAME}")
    ident = json.loads((corpus / T.IDENTIFIERS_NAME).read_text(encoding="utf-8"))
    if ident.get("collection") != cid:
        raise Refusal(f"{cid}: {T.IDENTIFIERS_NAME} names another collection")
    docs = tuple((n, (corpus / n).read_bytes().decode("utf-8")) for n in T.DOC_NAMES)
    return Collection(cid, docs, tuple(ident["strings"]), files, _sha256(raw))


_COUNTS = ("k", "k_one_call", "n", "present", "present_one_call")


def _found(texts: Sequence[str], needles: list[str]) -> tuple[set[str], set[str]]:
    """The needles `token_hits` finds in any of `texts`: each needle in a call of
    its own (the primary reading), and all needles in one call."""
    alone = {n for n in needles if any(token_hits(t, [n]) for t in texts)}
    together = {n for t in texts for n in token_hits(t, needles)}
    return alone, together


def score(strings: Sequence[dict[str, Any]], originals: Sequence[str],
          anonymised: Sequence[str]) -> dict[str, Any]:
    """k survived / n per identifier type and entity type, and how many were present.

    Pure. ``token_hits`` runs per document, since no whole-token run spans two
    documents; see the module docstring for the two readings.
    """
    if len(originals) != len(anonymised):
        raise ValueError("one anonymised text per original")
    live = [s for s in strings if not s["label"]]
    needles = [s["text"] for s in live]
    present, present_one_call = _found(originals, needles)
    survived, survived_one_call = _found(anonymised, needles)
    by_type: dict[str, dict[str, dict[str, int]]] = {
        it: {"total": dict.fromkeys(_COUNTS, 0)} for it in T.IDENTIFIER_TYPES}
    for s in live:
        t = s["text"]
        flags = {"k": t in survived, "k_one_call": t in survived_one_call, "n": True,
                 "present": t in present, "present_one_call": t in present_one_call}
        types = by_type[s["identifier_type"]]
        for key in (*s["entity_types"], "total"):
            row = types.setdefault(key, dict.fromkeys(_COUNTS, 0))
            for c in _COUNTS:
                row[c] += flags[c]
    return {"by_type": {it: dict(sorted(rows.items())) for it, rows in by_type.items()},
            "labels_excluded": len(strings) - len(live)}


def presidio_engine() -> tuple[Anonymiser, dict[str, str]]:
    """Presidio as constructed with no arguments, and the versions it runs.

    Refuses on any version other than the pinned ones, read both from the
    installed distributions and from the spaCy pipeline the analyzer loaded:
    the default NLP engine falls back to whatever model is installed under the
    name it asks for, and that is the version that did the work.
    """
    from importlib import metadata

    versions = {p: metadata.version(p) for p in (*PINNED, "spacy")}
    if wrong := sorted(p for p, v in PINNED.items() if versions[p] != v):
        raise Refusal("installed versions differ from scope §12.6: " + ", ".join(
            f"{p} {versions[p]} (pinned {PINNED[p]})" for p in wrong))
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine

    analyzer, anonymizer = AnalyzerEngine(), AnonymizerEngine()
    nlp = getattr(analyzer.nlp_engine, "nlp", {}).get(LANGUAGE)
    if nlp is None:
        raise Refusal("cannot read which spaCy pipeline the analyzer loaded")
    loaded = f"{nlp.meta['lang']}_{nlp.meta['name']}"
    if loaded != MODEL or nlp.meta["version"] != PINNED["en-core-web-lg"]:
        raise Refusal(f"the analyzer loaded {loaded} {nlp.meta['version']}, "
                      f"not {MODEL} {PINNED['en-core-web-lg']}")
    versions["model_loaded"] = f"{loaded} {nlp.meta['version']}"
    versions["python"] = platform.python_version()

    def anonymise(text: str) -> tuple[str, dict[str, int]]:
        results = analyzer.analyze(text=text, language=LANGUAGE)
        out = anonymizer.anonymize(text=text, analyzer_results=results).text
        return out, dict(Counter(r.entity_type for r in results))

    return anonymise, versions


def run(collections: Sequence[Collection], out: Path, anonymise: Anonymiser,
        versions: dict[str, str]) -> list[dict[str, Any]]:
    """Anonymise and score each collection; write one JSON per collection."""
    records = []
    for c in collections:
        originals, anonymised, docs = [], [], []
        for name, text in c.documents:
            anon, counts = anonymise(text)
            originals.append(text)
            anonymised.append(anon)
            docs.append({"name": name, "sha256": c.files[name],
                         "presidio_results": dict(sorted(counts.items()))})
        rec = {"collection": c.id, "generated_by": GENERATED_BY,
               "configuration": CONFIGURATION, "versions": dict(sorted(versions.items())),
               "manifest_sha256": c.manifest_sha256,
               "identifiers_sha256": c.files[T.IDENTIFIERS_NAME], "documents": docs,
               "rule": "a non-label identifier string survives when token_hits finds it in "
                       "the anonymised text of any document of the collection; k and present "
                       "with each string a needle of its own (primary, as real_l.py decides a "
                       "crossing), k_one_call and present_one_call with every non-label string "
                       "a needle of one call (descriptive)",
               **score(c.strings, originals, anonymised)}
        out.mkdir(parents=True, exist_ok=True)
        (out / f"presidio_{c.id}.json").write_text(
            json.dumps(rec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        records.append(rec)
    return records


def summary_lines(rec: dict[str, Any]) -> list[str]:
    """Counts only."""
    def counts(r: dict[str, int]) -> str:
        return (f"{r['k']}/{r['n']} (present {r['present']}); "
                f"one call {r['k_one_call']}/{r['n']} (present {r['present_one_call']})")

    lines = [f"{rec['collection']}: labels excluded {rec['labels_excluded']}"]
    for it, rows in rec["by_type"].items():
        lines.append(f"  {it} survived {counts(rows['total'])}")
        lines += [f"    {et} {counts(r)}" for et, r in rows.items() if et != "total"]
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Presidio's residue on track L (scope §12.6).")
    ap.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--manifest", type=Path, default=T.DEFAULT_MANIFEST,
                    help="the committed summary each collection must match")
    ap.add_argument("--collection", action="append", default=[],
                    help="only this collection id (repeatable)")
    args = ap.parse_args(argv)
    if not args.manifest.is_file():
        ap.error(f"{args.manifest} is missing")
    summary = json.loads(args.manifest.read_text(encoding="utf-8"))
    tasks = load_tasks(args.tasks)
    if args.collection:
        unknown = sorted(set(args.collection) - {t.id for t in tasks})
        if unknown:
            ap.error(f"not in {args.tasks}: {', '.join(unknown)}")
        tasks = [t for t in tasks if t.id in args.collection]
    try:
        # Every collection is checked before Presidio loads, which takes a while.
        collections = [read_collection(t.id, t.corpus, summary) for t in tasks]
        anonymise, versions = presidio_engine()
        records = run(collections, args.out, anonymise, versions)
    except Refusal as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    for rec in records:
        print("\n".join(summary_lines(rec)))
    print(f"versions: {json.dumps(versions, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
