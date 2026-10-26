#!/usr/bin/env python3
"""The Tier-1 probe: what the local extractor finds, echoes and leaves behind.

Why this exists
---------------
Plan task EXP4, experiment X2. Every arm masks from one saved extraction, so
the local extractor is the floor under all of them and nothing measured so far
says how good that floor is. Four reviewer questions are answered here from
saved extractions, offline, with no cloud call and no model: how much does the
extractor vary on identical input, what does it miss, what does the free-text
predicate channel echo from the corpus, and why not simply redact entities and
send the document. A fifth, what the payload discloses about which corpus it
came from (G1), is answered by building payloads for several corpora.

Two modes
---------
``analyse`` reads a corpus directory and one or more ``extractions.json`` files
and writes one JSON (default ``eval/probe/<corpus-id>.json``). Pure: no Docker,
no network, no SLM.

``extract`` produces the k extra extractions EXP7 needs. The SLM publishes no
port on the host, so it drives ``privdeep.tier1_local.probe_extract`` inside
``privdeep-core`` through ``docker compose``, with the helper style of
``run_evaluation.py`` (``_compose``, the corpus bind-mounted at ``/corpus`` by
``PRIVDEEP_CORPUS_DIR``, the code provenance checked before and recorded
after), and copies each file out. It is free (local GPU only) but it restarts
the core with the probe's corpus mounted. It is tested with a faked
``_compose`` only.

What ``analyse`` computes, per distinct extraction
--------------------------------------------------
Files are deduplicated by content first: the nine pilot runs share one
extraction, and nine copies of it are one extraction, not 36 pairs at 1.0.

(a) **Variance.** Pairwise Jaccard of the pooled entity set ``(text,
    category)`` and of the pooled relation set ``(subject, predicate,
    object)``, plus the per-document entity Jaccard. This is noise on
    identical input. It does not discharge "given a fixed extraction", which
    every downstream claim is conditional on.
(b) **Recall** of every gold-key referent and string fact: an item is found
    when some extracted entity equals one of its surfaces (``exact``) or
    contains one at token boundaries (``covered``). Beyond the brief, the same
    is reported for every generator surface in ``surfaces.json`` that occurs
    in the corpus, which is what (e) splits on. Also every generator surface
    found inside a relation field, matched case-insensitively on whole tokens,
    with the ``labels`` group (ordinary words such as "High") reported apart.
(c) **Predicate echo.** Tokens are the containment filter's own
    (``shared.shingle_filter.tokenize``: casefolded ``[^\\W_]+`` runs, so
    ``has_owner`` is two tokens). A predicate *echoes* when it contains a
    corpus 2-, 3- or 4-gram; it is a *whole* match when its full token
    sequence occurs in the corpus. The control is the ``english_prose``
    stratum of ``measure_false_positives.py``: every window of the stratum's
    text of each length a predicate has, and the share of those windows that
    would echo or match whole. The expected control share is that per-length
    share averaged over the predicates' own lengths, so the comparison is at
    matched length. The word-length distribution is reported too; nothing in
    code caps it.
(d) **R5 residue.** Referents whose canonical key is a proper substring of
    another key in the same category: the aliases R5 refuses to merge.
    Substring and not token matching, because IDENTIFIER keys are stripped of
    separators (``contract NB-2026-0917`` keys as ``contractnb20260917``).
    LOCATION keys keep single spaces, so for them a substring hit can also be
    a longer place name that merely starts with a shorter one, and a DATE key
    for a month (``2026-08``) is a prefix of every day in it. The pairs are
    listed so each can be read off.
(e) **Masked-document exposure.** Each document is masked with the pipeline's
    own ``SlotMasker`` (r5 keying, an analysis salt) and inspected by a sealed
    ``ShingleFilter`` built offline with ``containment.build_filter`` over the
    same documents and the deployed parameters (5-8 grams, threshold 1). This
    is the filter, not the monitor's ``/inspect``, and its verdict is a
    construction fact under P2, not an observation of the running system.
    Reported: the share of the masked text's 5-grams that are corpus 5-grams,
    the share of the corpus's distinct 5-grams that survive masking, and
    refused yes/no. Then a policy-independent figure: the generator surfaces
    left standing in the masked text (placeholders removed first, whole-token,
    longest first), listing separately those that (b) says the extractor
    missed altogether. A missed surface that a shorter entity cut in two
    (``22 August 2026`` with ``August`` masked) no longer stands, and is not
    counted as surviving; it stays a miss in (b).
(f) **G1 inventory**, when ``--g1`` names other corpora: which payload fields
    differ between corpora, per arm, from payloads built with the pipeline's
    own masking and ``build_abstract_payload``: the DOCUMENT STATS line, the
    per-category slot counts, the relation multiset, and the constant
    attribute schema. Each corpus is built from a real extraction, marked
    ``saved``: the primary from its first distinct extraction (so list the
    batch's first), every other from the file given as ``CORPUS=FILE``, read
    through ``load_extractions`` as the pipeline reads it. The stub is an
    explicit fallback: only under ``--g1-stub`` is every corpus also built
    from a stub extraction, marked ``stub``, and a corpus given without a
    file then appears under the stub alone (without the flag it is refused).
    The stub is built from ``surfaces.json`` (every generator surface that
    occurs in a document, typed by its group, and no relations), so its slot
    counts are the generator's and its relation multiset is empty. Every
    comparison names its stub rows in ``stub_corpora``.

What the output carries
-----------------------
Corpus strings: generator surfaces, canonical keys and predicates. The corpora
here are synthetic and tracked, so that is fine for them. For a real corpus
the output is private and stays in the partition with the run directories.

Measured, the pilot (corpus A, the one extraction all nine runs share)
----------------------------------------------------------------------
(a) No variance figure: nine files, one extraction. EXP7 supplies the k=3.
(b) Referents 5/5, string facts 9/9, generator surfaces 57/58 (the memo's
    heading date ``22 August 2026`` is missed); no generator surface in any
    relation field.
(c) 18/43 predicates echo a corpus 2-4-gram and 16/43 match whole; lengths in
    tokens 1:4, 2:23, 3:14, 4:2, maximum 4. The english_prose control at
    matched length: 5.4% would echo, 5.6% would match whole.
(d) 7 of 47 referents carry residue: IDENTIFIER 2 (``contract NB-...``),
    LOCATION 2 (``Manchester site``, ``Bristol fulfilment centre``), QUANTITY 2
    (risk sentences typed QUANTITY that contain ``340 units`` and ``twelve
    percent``), DATE 1 (``2026-08``, a month, prefixes five days).
(e) All four masked documents are refused by the filter. 16.5% of the masked
    text's 5-grams are corpus 5-grams, and 18.5% of the corpus's distinct
    5-grams survive masking. Four generator surfaces survive, none an
    extractor miss: each was extracted from another document but not listed
    for the one it survives in (``62,567.45``, which a line break splits from
    its ``USD`` in the memo, both contract codes, ``twelve percent``).
(f) Under the stub extraction A, B and C differ, in every arm, in the DOCUMENT
    STATS line and the per-category slot counts; the attribute schema is a
    constant and the stub has no relations. Against A's saved extraction the
    relation multiset differs as well (43 relations against none). Under the
    saved extractions of A and of the pilot's ``prose-c__r5`` and
    ``offlex-d__r5`` runs (A, C, D), the DOCUMENT STATS line, the slot counts
    and the relation set (43, 27 and 43 relations) differ in every arm; the
    document count (4) and r1's attribute schema are the same.

Usage
-----
    python scripts/tier1_probe.py analyse eval/corpora/smoke-q3 \\
        --extractions eval/runs/smoke-q3__r5/extractions.json \\
        --g1 eval/corpora/portfolio-b=eval/runs/portfolio-b__r5/extractions.json \\
             eval/corpora/prose-c=eval/runs/prose-c__r5/extractions.json
    python scripts/tier1_probe.py extract eval/corpora/smoke-q3 --k 3
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import re
import sys
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "backend" / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from privdeep.ingest import SUFFIXES, load  # noqa: E402
from privdeep.models.document import Document  # noqa: E402
from privdeep.pipeline import _merge_payloads  # noqa: E402
from privdeep.tier1_local.containment import build_filter  # noqa: E402
from privdeep.tier1_local.extraction_io import (  # noqa: E402
    ExtractionReuseError,
    dump_extractions,
    load_extractions,
    text_sha256,
)
from privdeep.tier1_local.normalise import canonical_key  # noqa: E402
from privdeep.tier1_local.ontology_extractor import Extraction, OntologyLeak  # noqa: E402
from privdeep.tier1_local.slot_masker import SLOT_RE, Entity, SlotMasker  # noqa: E402
from privdeep.tier2_cloud.abstract_payload import (  # noqa: E402
    AbstractPayload,
    build_abstract_payload,
)
from privdeep.tier2_cloud.macro_planner import MacroPlanner  # noqa: E402

from scripts import run_evaluation as R  # noqa: E402
from shared.shingle_filter import tokenize  # noqa: E402

__all__ = ["ARMS", "G1_MIXED", "G1_SAVED", "G1_STUB", "G1Entry", "analyse", "extract",
           "g1_entries", "g1_inventory", "main", "masked_exposure", "parse_g1",
           "predicate_control", "predicate_echo", "r5_residue", "recall", "stub_extraction",
           "variance"]

ARMS = R.ARMS
DEFAULT_OUT_DIR = _REPO / "eval" / "probe"
# The canary prefix `load_extractions` screens with; the deployed injector's.
CANARY_PREFIX = "CANARY_PRIVDEEP_"
# Instrument salts. Not secrets: slot ids and the filter built here protect
# nothing, and fixed salts make every figure reproducible from the inputs.
ANALYSIS_SALT = b"privdeep-tier1-probe"
FILTER_SALT = b"privdeep-tier1-probe-filter"
# The deployed containment parameters (docker-compose.yml defaults), passed
# explicitly so the environment cannot move them.
SHINGLE_N_MIN, SHINGLE_N_MAX, SHINGLE_HIT_THRESHOLD = 5, 8, 1
ECHO_N = (2, 4)
GOAL = "Assess the current position and risks."   # the pipeline's default goal

# surfaces.json group -> slot category, for the stub extraction. `labels` and
# `risk_text` are left out: the generator writes them as cell text, and typing
# them is the extractor's guess (the pilot's was QUANTITY), not a fact.
_STUB_CATEGORY = {"people": "PERSON", "sites": "LOCATION", "identifiers": "IDENTIFIER",
                  "amounts": "MONEY", "dates": "DATE", "quantities": "QUANTITY",
                  "percentages": "QUANTITY"}
_ORG_REFERENTS = ("ORG", "VENDOR")


# ----------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class Corpus:
    id: str
    path: Path
    docs: list[Document]
    key: dict[str, Any] | None
    surfaces: dict[str, Any] | None

    def text(self) -> str:
        return "\n".join(d.text for d in self.docs)


def _rel(p: Path) -> str:
    """Repository-relative, so the output names no checkout. A run directory read
    from another worktree is named from its ``eval/`` component on."""
    p = p.resolve()
    try:
        return str(p.relative_to(_REPO))
    except ValueError:
        parts = p.parts
        return str(Path(*parts[parts.index("eval"):])) if "eval" in parts else str(p)


def load_corpus(path: Path) -> Corpus:
    files = sorted(p for p in path.iterdir() if p.suffix.lower() in SUFFIXES)
    if not files:
        raise SystemExit(f"no supported documents in {path}")
    key_p, surf_p = path / R.FACT_KEY_NAME, path / "surfaces.json"
    key = json.loads(key_p.read_text(encoding="utf-8")) if key_p.exists() else None
    surfaces = json.loads(surf_p.read_text(encoding="utf-8")) if surf_p.exists() else None
    cid = (surfaces or {}).get("scenario") or (key or {}).get("scenario") or path.name
    return Corpus(cid, path, [load(p) for p in files], key, surfaces)


def _content_sha(data: dict[str, Any]) -> str:
    """Identity of an extraction by what it says, not by its file bytes."""
    rows = sorted(({"sha": r["text_sha256"], "entities": r["entities"],
                    "relations": r["relations"]} for r in data.get("documents", [])),
                  key=lambda r: r["sha"])
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


@dataclass
class LoadedExtraction:
    files: list[str]
    sha: str
    extractions: list[Extraction]     # in corpus document order

    @property
    def entities(self) -> list[Entity]:
        return [e for ex in self.extractions for e in ex.entities]

    @property
    def relations(self) -> list[tuple[str, str, str]]:
        return [r.fields() for ex in self.extractions for r in ex.relations]


def read_extractions(paths: Sequence[Path], corpus: Corpus
                     ) -> tuple[list[LoadedExtraction], list[dict[str, Any]]]:
    """Distinct usable extractions, and the files refused with their reason.

    Loaded through ``load_extractions``, so a file the pipeline would refuse
    (another corpus, canary strings, an entity not in the text, a relation
    carrying an entity) is refused here too and reported rather than
    measured. A leak-gate refusal names the class and category only: the
    exception's message may quote the entity (the strict per-document gate's
    did; the corpus-wide gate's names only the category). A file carrying
    ``stub_extraction``'s 'stub' mark is refused with reason 'stub': a stub is
    never read back as a saved extraction.
    """
    by_sha: dict[str, LoadedExtraction] = {}
    refused: list[dict[str, Any]] = []
    for p in paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("stub"):
            refused.append({"file": _rel(p), "reason": "stub"})
            continue
        aborted = (data.get("probe") or {}).get("aborted") or []
        try:
            exs = load_extractions(data, corpus.docs, canary_prefix=CANARY_PREFIX)
        except ExtractionReuseError as exc:
            refused.append({"file": _rel(p), "reason": "ExtractionReuseError",
                            "detail": str(exc), "leak_gate_aborts": aborted})
            continue
        except OntologyLeak as exc:
            m = re.search(r"\(([A-Z]+)\)\s*$", str(exc))
            refused.append({"file": _rel(p), "reason": "OntologyLeak",
                            "category": m.group(1) if m else "unknown"})
            continue
        sha = _content_sha(data)
        if sha in by_sha:
            by_sha[sha].files.append(_rel(p))
        else:
            by_sha[sha] = LoadedExtraction([_rel(p)], sha, exs)
    return list(by_sha.values()), refused


# ----------------------------------------------------------------------- helpers


def _token_rx(surface: str, *, ignore_case: bool = False) -> re.Pattern[str]:
    """Whole-token match: no letter or digit may touch either end."""
    return re.compile(rf"(?<![0-9A-Za-z]){re.escape(surface)}(?![0-9A-Za-z])",
                      re.IGNORECASE if ignore_case else 0)


def _grams(tokens: Sequence[str], lo: int, hi: int) -> set[tuple[str, ...]]:
    return {tuple(tokens[i:i + n]) for n in range(lo, hi + 1)
            for i in range(len(tokens) - n + 1)}


def jaccard(a: set[Any], b: set[Any]) -> float | None:
    return len(a & b) / len(a | b) if a | b else None


def _surface_groups(corpus: Corpus) -> dict[str, list[str]]:
    return dict((corpus.surfaces or {}).get("groups") or {})


def _group_of(corpus: Corpus) -> dict[str, str]:
    out: dict[str, str] = {}
    for g, items in _surface_groups(corpus).items():
        for s in items:
            out.setdefault(s, g)
    return out


# ----------------------------------------------------------------------- (a)


def variance(exs: Sequence[LoadedExtraction]) -> dict[str, Any]:
    ent = [{(e.text, e.category) for e in x.entities} for x in exs]
    rel = [set(x.relations) for x in exs]
    pairs = []
    for i, j in itertools.combinations(range(len(exs)), 2):
        per_doc = [jaccard({(e.text, e.category) for e in a.entities},
                           {(e.text, e.category) for e in b.entities})
                   for a, b in zip(exs[i].extractions, exs[j].extractions, strict=True)]
        per_doc_vals = [v for v in per_doc if v is not None]
        pairs.append({"a": i, "b": j, "entity_jaccard": jaccard(ent[i], ent[j]),
                      "relation_jaccard": jaccard(rel[i], rel[j]),
                      "per_document_entity_jaccard_mean":
                          sum(per_doc_vals) / len(per_doc_vals) if per_doc_vals else None})

    def summary(k: str) -> dict[str, Any] | None:
        v = [p[k] for p in pairs if p[k] is not None]
        return {"min": min(v), "mean": sum(v) / len(v), "max": max(v)} if v else None

    return {"distinct_extractions": len(exs), "pairs": pairs,
            "entity_jaccard": summary("entity_jaccard"),
            "relation_jaccard": summary("relation_jaccard"),
            "note": None if pairs else "fewer than two distinct extractions: no pair to "
                                       "compare, so no variance figure"}


# ----------------------------------------------------------------------- (b)


def _covered(surface: str, entity_texts: Iterable[str]) -> tuple[bool, bool]:
    texts = list(entity_texts)
    exact = surface in texts
    rx = _token_rx(surface)
    return exact, exact or any(rx.search(t) for t in texts)


def recall(corpus: Corpus, ex: LoadedExtraction) -> dict[str, Any]:
    texts = {e.text for e in ex.entities}
    corpus_text = corpus.text()
    out: dict[str, Any] = {}
    key = corpus.key or {}

    def item(name: str, surfaces: Sequence[str]) -> dict[str, Any]:
        present = [s for s in surfaces if _token_rx(s).search(corpus_text)]
        hits = {s: _covered(s, texts) for s in present}
        return {"item": name, "surfaces_in_corpus": present,
                "exact": any(e for e, _ in hits.values()),
                "covered": any(c for _, c in hits.values()),
                "surfaces_covered": [s for s, (_, c) in hits.items() if c]}

    refs = [item(k, v) for k, v in sorted((key.get("referents") or {}).items())]
    strs = [item(f["fact_id"], [f["value"]]) for f in key.get("string_facts") or []]
    for name, rows in (("referents", refs), ("string_facts", strs)):
        rows = [r for r in rows if r["surfaces_in_corpus"]]
        out[name] = {"n": len(rows), "exact": sum(r["exact"] for r in rows),
                     "covered": sum(r["covered"] for r in rows),
                     "missed": [r["item"] for r in rows if not r["covered"]],
                     "items": rows}

    groups = _group_of(corpus)
    rows = []
    for s in (corpus.surfaces or {}).get("surfaces", []):
        if not _token_rx(s).search(corpus_text):
            continue
        exact, cov = _covered(s, texts)
        rows.append({"surface": s, "group": groups.get(s), "exact": exact, "covered": cov})
    out["generator_surfaces"] = {
        "n": len(rows), "covered": sum(r["covered"] for r in rows),
        "by_group": {g: {"n": sum(r["group"] == g for r in rows),
                         "covered": sum(r["covered"] for r in rows if r["group"] == g)}
                     for g in sorted({r["group"] for r in rows if r["group"]})},
        "missed": [r["surface"] for r in rows if not r["covered"]]}

    in_rel = []
    flat = [s for s in (corpus.surfaces or {}).get("surfaces", []) if len(s) >= 2]
    for s, p, o in ex.relations:
        for fld_name, fld in (("subject_type", s), ("predicate", p), ("object_type", o)):
            for surf in flat:
                if _token_rx(surf, ignore_case=True).search(fld):
                    in_rel.append({"field": fld_name, "value": fld, "surface": surf,
                                   "group": groups.get(surf)})
    out["surfaces_in_relations"] = {
        "hits": [h for h in in_rel if h["group"] != "labels"],
        "labels_group_hits": [h for h in in_rel if h["group"] == "labels"]}
    return out


# ----------------------------------------------------------------------- (c)


def predicate_echo(corpus: Corpus, ex: LoadedExtraction) -> dict[str, Any]:
    preds = [p for _, p, _ in ex.relations]
    toks = [tokenize(p) for p in preds]
    longest = max((len(t) for t in toks), default=0)
    cgrams: set[tuple[str, ...]] = set()
    for d in corpus.docs:
        cgrams |= _grams(tokenize(d.text), 1, max(longest, ECHO_N[1]))
    echo = [bool(_grams(t, *ECHO_N) & cgrams) for t in toks]
    whole = [bool(t) and tuple(t) in cgrams for t in toks]
    return {
        "n_predicates": len(preds),
        "echo_2_4gram": sum(echo),
        "echo_share": sum(echo) / len(preds) if preds else None,
        "whole_match": sum(whole),
        "whole_match_share": sum(whole) / len(preds) if preds else None,
        "echoing": [p for p, e in zip(preds, echo, strict=True) if e],
        "whole_matches": [p for p, w in zip(preds, whole, strict=True) if w],
        "length_tokens": dict(sorted(Counter(len(t) for t in toks).items())),
        "length_whitespace_words": dict(sorted(Counter(len(p.split()) for p in preds).items())),
        "max_tokens": longest,
    }


def predicate_control(corpus: Corpus, lengths: Sequence[int]) -> dict[str, Any]:
    """The same two tests on the FP harness's clean English, at matched length."""
    from scripts.measure_false_positives import DEFAULT_SEED, N_PER_STRATUM, build_corpus

    texts = [p.text for p in build_corpus(DEFAULT_SEED, N_PER_STRATUM)
             if p.stratum == "english_prose"]
    top = max([*lengths, ECHO_N[1]])
    cgrams: set[tuple[str, ...]] = set()
    for d in corpus.docs:
        cgrams |= _grams(tokenize(d.text), 1, top)
    per_len: dict[int, dict[str, Any]] = {}
    for n in sorted(set(lengths)):
        wins = [tuple(t[i:i + n]) for t in map(tokenize, texts) for i in range(len(t) - n + 1)]
        e = sum(bool(_grams(w, *ECHO_N) & cgrams) for w in wins)
        w = sum(win in cgrams for win in wins)
        per_len[n] = {"windows": len(wins), "echo_share": e / len(wins) if wins else None,
                      "whole_share": w / len(wins) if wins else None}

    def expected(k: str) -> float | None:
        v = [per_len[n][k] for n in lengths if per_len[n][k] is not None]
        return sum(v) / len(v) if v else None

    return {"stratum": "english_prose", "seed": DEFAULT_SEED, "payloads": len(texts),
            "per_length": {str(k): v for k, v in per_len.items()},
            "expected_echo_share": expected("echo_share"),
            "expected_whole_share": expected("whole_share"),
            "note": "windows of the stratum's text at each predicate length; the expected "
                    "shares average the per-length shares over the predicates' own lengths"}


# ----------------------------------------------------------------------- (d)


def r5_residue(ex: LoadedExtraction) -> dict[str, Any]:
    keys: dict[str, set[str]] = {}
    for e in ex.entities:
        keys.setdefault(e.category, set()).add(canonical_key(e.category, e.text))
    pairs: dict[str, list[list[str]]] = {}
    for cat, ks in sorted(keys.items()):
        found = sorted([a, b] for a in ks for b in ks if a != b and a in b)
        if found:
            pairs[cat] = found
    shorter = {(c, a) for c, ps in pairs.items() for a, _ in ps}
    return {"referents_total": sum(len(k) for k in keys.values()),
            "referents_with_residue": len(shorter),
            "by_category": {c: len({a for a, _ in ps}) for c, ps in pairs.items()},
            "pairs": pairs}


# ----------------------------------------------------------------------- (e)


def _strip_slots(text: str) -> str:
    return SLOT_RE.sub(" ⟦⟧ ", text)


def _surviving(text: str, surfaces: Sequence[str]) -> Counter[str]:
    """Generator surfaces standing in `text`, longest first, spans claimed once."""
    claimed: list[tuple[int, int]] = []
    out: Counter[str] = Counter()
    for s in sorted(surfaces, key=lambda s: (-len(s), s)):
        for m in _token_rx(s).finditer(text):
            if any(m.start() < b and a < m.end() for a, b in claimed):
                continue
            claimed.append(m.span())
            out[s] += 1
    return out


def masked_exposure(corpus: Corpus, ex: LoadedExtraction,
                    extractor_misses: Iterable[str]) -> dict[str, Any]:
    f = build_filter(corpus.docs, salt=FILTER_SALT, n_min=SHINGLE_N_MIN,
                     n_max=SHINGLE_N_MAX, hit_threshold=SHINGLE_HIT_THRESHOLD)
    masker = SlotMasker(ANALYSIS_SALT, normalise=True)
    corpus5: set[str] = set()
    for d in corpus.docs:
        t = tokenize(d.text)
        corpus5 |= {" ".join(t[i:i + 5]) for i in range(len(t) - 4)}
    surfaces = list((corpus.surfaces or {}).get("surfaces", []))
    groups = _group_of(corpus)
    misses = set(extractor_misses)
    rows, hit5_all, total5 = [], set(), 0
    survived: Counter[str] = Counter()
    for d, dex in zip(corpus.docs, ex.extractions, strict=True):
        m = masker.mask(d, dex.entities)
        verdict = f.inspect(m.masked_text)
        t = tokenize(m.masked_text)
        grams5 = [" ".join(t[i:i + 5]) for i in range(len(t) - 4)]
        hit5 = [g for g in grams5 if g.encode("utf-8") in f.bloom]
        hit5_all |= set(hit5)
        total5 += len(grams5)
        s = _surviving(_strip_slots(m.masked_text), surfaces)
        survived.update(s)
        rows.append({"doc_id": d.doc_id, "refused": verdict.blocked,
                     "shingle_hits_5_8": verdict.hit_count if verdict.blocked else 0,
                     "masked_5grams": len(grams5), "masked_5grams_hit": len(hit5),
                     "placeholders": len(m.replacements), "unmatched_entities": len(m.unmatched),
                     "surfaces_surviving": sum(s.values())})
    hit_total = sum(r["masked_5grams_hit"] for r in rows)
    return {
        "filter": {"n_min": SHINGLE_N_MIN, "n_max": SHINGLE_N_MAX,
                   "hit_threshold": SHINGLE_HIT_THRESHOLD, "salt": "fixed analysis salt",
                   "fp_est": f.bloom.estimated_fp_rate(), "keying": "r5"},
        "refused_any": any(r["refused"] for r in rows),
        "refused_documents": sum(r["refused"] for r in rows),
        "masked_5gram_hit_share": hit_total / total5 if total5 else None,
        "corpus_5grams_distinct": len(corpus5),
        "corpus_5grams_surviving_share": len(hit5_all & corpus5) / len(corpus5)
        if corpus5 else None,
        "documents": rows,
        "generator_surfaces_surviving": {
            "distinct": len(survived), "occurrences": sum(survived.values()),
            "surfaces": [{"surface": s, "group": groups.get(s), "occurrences": n,
                          "extractor_miss": s in misses} for s, n in sorted(survived.items())],
            "extractor_misses": sorted(s for s in survived if s in misses),
            "extracted_elsewhere": sorted(s for s in survived if s not in misses),
            "labels_group": sorted(s for s in survived if groups.get(s) == "labels")},
    }


# ----------------------------------------------------------------------- (f)


def stub_extraction(corpus: Corpus) -> dict[str, Any]:
    """A deterministic stand-in for an extraction, from the generator's own surfaces.

    Not an extractor: every generator surface that occurs in a document, typed
    by its group, longest first so a name is listed before its fragment, and no
    relations. Labels and risk-cell text are left out (see ``_STUB_CATEGORY``).
    """
    groups = _surface_groups(corpus)
    cat: dict[str, str] = {}
    for g, c in _STUB_CATEGORY.items():
        for s in groups.get(g, []):
            cat.setdefault(s, c)
    for name, surfaces in ((corpus.key or {}).get("referents") or {}).items():
        for s in surfaces:
            cat.setdefault(s, "ORG" if name in _ORG_REFERENTS else "PROJECT")
    exs = []
    for d in corpus.docs:
        ents = [Entity(s, c) for s, c in sorted(cat.items(), key=lambda kv: (-len(kv[0]), kv[0]))
                if d.find_all(s)]
        exs.append(Extraction(entities=ents, relations=[]))
    data = dump_extractions(corpus.docs, exs)
    data["stub"] = True
    return data


def build_payload(docs: Sequence[Document], extractions: Sequence[Extraction], arm: str,
                  salt: bytes = ANALYSIS_SALT) -> AbstractPayload:
    """The merged payload exactly as ``run_pipeline`` builds it for `arm`."""
    masker = SlotMasker(salt, normalise=arm != "baseline")
    return _merge_payloads([
        build_abstract_payload(d.doc_id, ex, masker.mask(d, ex.entities), n_cells=len(d.cells),
                               n_blocks=len(d.blocks), n_chars=len(d.text), facts=arm == "r1")
        for d, ex in zip(docs, extractions, strict=True)])


def _fields(p: AbstractPayload) -> dict[str, Any]:
    stats = re.search(r"^DOCUMENT STATS: .*$", MacroPlanner._user_prompt(p, GOAL), re.M)
    rels = sorted(Counter(p.relations).items())
    return {
        "document_stats": stats.group(0) if stats else None,
        "slot_counts": dict(sorted(Counter(c for _, c in p.slots).items())),
        "relation_multiset": {"n": sum(n for _, n in rels), "distinct": len(rels),
                              "sha256": hashlib.sha256(json.dumps(rels).encode()).hexdigest()},
        "attribute_schema": hashlib.sha256(p.schema_json().encode()).hexdigest()
        if p.attribute_schema else None,
        "documents": len(p.doc_id.split("+")),
    }


# Where each field is disclosed. `documents` (the count of content-hash ids in
# `doc_id`) is in the payload JSON only; no prompt carries doc_id.
_WHERE = {"document_stats": "planner prompt",
          "slot_counts": "planner prompt and drafter prompts",
          "relation_multiset": "planner prompt and drafter prompts",
          "attribute_schema": "planner and drafter prompts (r1 only)",
          "documents": "payload JSON only"}


# The comparisons the inventory writes; make_paper_tables.py reads the first two
# by name and takes only a one-rule comparison (every corpus under the same kind
# of extraction), the saved one first.
G1_SAVED = "all corpora under their saved extractions"
G1_STUB = "all corpora under the stub extraction"
G1_MIXED = "saved extraction where given, the stub otherwise"


@dataclass(frozen=True)
class G1Entry:
    label: str                        # "<corpus id>:saved" or "<corpus id>:stub"
    corpus: Corpus
    extractions: list[Extraction]     # in corpus document order
    kind: str                         # "saved" or "stub"
    source: str                       # the file read, or what the stub was built from


def g1_inventory(entries: Sequence[G1Entry]) -> dict[str, Any]:
    """Per arm, the disclosed fields of each corpus's payload and which differ."""
    rows = []
    for e in entries:
        rows.append({"label": e.label, "corpus": e.corpus.id, "extraction": e.kind,
                     "source": e.source,
                     "arms": {arm: _fields(build_payload(e.corpus.docs, e.extractions, arm))
                              for arm in ARMS}})

    def compare(name: str, labels: Sequence[str]) -> dict[str, Any]:
        sel = [r for r in rows if r["label"] in labels]
        out: dict[str, Any] = {}
        for arm in ARMS:
            per_field = {}
            for fld in _WHERE:
                vals = [json.dumps(r["arms"][arm][fld], sort_keys=True) for r in sel]
                per_field[fld] = len(set(vals)) > 1
            out[arm] = {"differs": [f for f, d in per_field.items() if d],
                        "same": [f for f, d in per_field.items() if not d]}
        kinds = {r["extraction"] for r in sel}
        return {"name": name, "extraction": kinds.pop() if len(kinds) == 1 else "mixed",
                "stub_corpora": [r["label"] for r in sel if r["extraction"] == "stub"],
                "corpora": list(labels), "by_arm": out}

    saved = [r["label"] for r in rows if r["extraction"] == "saved"]
    stubs = [r["label"] for r in rows if r["extraction"] == "stub"]
    comparisons = []
    if len(saved) >= 2:
        comparisons.append(compare(G1_SAVED, saved))
    if len(stubs) >= 2:
        comparisons.append(compare(G1_STUB, stubs))
    with_saved = {r["corpus"] for r in rows if r["extraction"] == "saved"}
    fallback = [r["label"] for r in rows
                if r["extraction"] == "stub" and r["corpus"] not in with_saved]
    if saved and fallback:
        comparisons.append(compare(G1_MIXED, saved + fallback))
    return {"where_disclosed": _WHERE, "corpora": rows, "comparisons": comparisons,
            "stub_corpora": sorted({r["corpus"] for r in rows if r["extraction"] == "stub"}),
            "note": "A row marked 'saved' is built from an extraction file read through "
                    "load_extractions (its 'source'), as the pipeline builds the payload from "
                    "it. A row marked 'stub' uses a deterministic stub extraction built from "
                    "the corpus's surfaces.json, not an extractor run: its slot counts are the "
                    "generator's and its relation multiset is empty. Stub rows exist only "
                    "under --g1-stub; a comparison that includes one names it in "
                    "'stub_corpora'."}


def parse_g1(spec: str | Path | tuple[Path, Path | None]) -> tuple[Path, Path | None]:
    """``CORPUS`` or ``CORPUS=EXTRACTIONS.json`` into (corpus dir, extraction file)."""
    if isinstance(spec, tuple):
        return spec
    if isinstance(spec, Path):
        return spec, None
    corpus, sep, ex = spec.partition("=")
    if not corpus or (sep and not ex):
        raise SystemExit(f"--g1 {spec!r}: expected CORPUS or CORPUS=EXTRACTIONS.json")
    return Path(corpus), Path(ex) if sep else None


def g1_entries(corpus: Corpus, exs: Sequence[LoadedExtraction],
               g1: Sequence[str | Path | tuple[Path, Path | None]], *,
               stub: bool = False) -> list[G1Entry]:
    """The G1 rows: the primary corpus under its first distinct extraction, every
    other corpus under the extraction file given for it, and, only when `stub`,
    every corpus under the stub extraction as well. A corpus given without an
    extraction is refused unless `stub`, and then appears under the stub only.
    An extraction file the pipeline would refuse for its corpus is refused here."""
    out: list[G1Entry] = []
    if exs:
        out.append(G1Entry(f"{corpus.id}:saved", corpus, exs[0].extractions, "saved",
                           exs[0].files[0]))
    corpora = [corpus]
    for spec in g1:
        d, path = parse_g1(spec)
        c = load_corpus(d)
        if c.id in {x.id for x in corpora}:
            raise SystemExit(f"--g1 {d}: corpus {c.id} is already in the inventory")
        corpora.append(c)
        if path is None:
            if not stub:
                raise SystemExit(
                    f"--g1 {d}: no extraction for corpus {c.id}; pass "
                    f"{d}=EXTRACTIONS.json (the batch's eval/runs/{c.id}__r5/extractions.json), "
                    "or --g1-stub to fall back to the stub extraction, labelled 'stub'")
            continue
        if not path.is_file():
            raise SystemExit(f"--g1 {spec}: no extraction file {path} for corpus {c.id}")
        loaded, refused = read_extractions([path], c)
        if refused or not loaded:
            raise SystemExit(f"--g1 {spec}: the extraction for corpus {c.id} is refused: "
                             + json.dumps(refused))
        out.append(G1Entry(f"{c.id}:saved", c, loaded[0].extractions, "saved", _rel(path)))
    if stub:
        for c in corpora:
            out.append(G1Entry(f"{c.id}:stub", c,
                               load_extractions(stub_extraction(c), c.docs,
                                                canary_prefix=CANARY_PREFIX),
                               "stub", f"stub from {_rel(c.path)}/surfaces.json"))
    return out


# ----------------------------------------------------------------------- analyse


def analyse(corpus_dir: Path, extraction_paths: Sequence[Path],
            g1: Sequence[str | Path | tuple[Path, Path | None]] = (), *,
            g1_stub: bool = False) -> dict[str, Any]:
    corpus = load_corpus(corpus_dir)
    exs, refused = read_extractions(extraction_paths, corpus)
    if g1 and extraction_paths and not (exs and _rel(extraction_paths[0]) in exs[0].files):
        # The primary's G1 row is built from the first file listed (the batch's);
        # refuse rather than build it silently from a later one.
        raise SystemExit(f"--g1: the first extraction {_rel(extraction_paths[0])} for corpus "
                         f"{corpus.id} is refused, so its G1 row has no source: "
                         + json.dumps(refused))
    report: dict[str, Any] = {
        "instrument": "scripts/tier1_probe.py", "mode": "analyse",
        "provenance": R.host_provenance().to_json(),
        "corpus": {"id": corpus.id, "path": _rel(corpus.path), "gold_key": corpus.key is not None,
                   "surfaces": corpus.surfaces is not None,
                   "documents": [{"doc_id": d.doc_id, "kind": str(d.kind), "chars": len(d.text),
                                  "text_sha256": text_sha256(d)} for d in corpus.docs]},
        "extraction_files": len(extraction_paths),
        "extractions": [{"index": i, "sha256": x.sha, "files": x.files}
                        for i, x in enumerate(exs)],
        "refused_files": refused,
        "variance": variance(exs),
    }
    per = []
    all_lengths: list[int] = []
    for i, x in enumerate(exs):
        rec = recall(corpus, x)
        echo = predicate_echo(corpus, x)
        all_lengths += [len(tokenize(p)) for _, p, _ in x.relations]
        per.append({"index": i, "entities": len(x.entities), "relations": len(x.relations),
                    "recall": rec, "predicates": echo, "r5_residue": r5_residue(x),
                    "masked_exposure": masked_exposure(
                        corpus, x, rec["generator_surfaces"]["missed"])})
    report["per_extraction"] = per
    report["predicate_control"] = predicate_control(corpus, all_lengths) if all_lengths else None
    if g1:
        report["g1"] = g1_inventory(g1_entries(corpus, exs, g1, stub=g1_stub))
    return report


def _summary(report: dict[str, Any]) -> str:
    lines = [f"corpus {report['corpus']['id']}: {report['extraction_files']} file(s), "
             f"{len(report['extractions'])} distinct extraction(s), "
             f"{len(report['refused_files'])} refused"]
    v = report["variance"]
    if v["entity_jaccard"]:
        lines.append(f"  (a) entity Jaccard mean {v['entity_jaccard']['mean']:.3f}, "
                     f"relation Jaccard mean {v['relation_jaccard']['mean']:.3f}")
    else:
        lines.append(f"  (a) {v['note']}")
    for x in report["per_extraction"]:
        r, p, d, e = x["recall"], x["predicates"], x["r5_residue"], x["masked_exposure"]
        lines += [
            f"  [{x['index']}] (b) referents {r['referents']['covered']}/{r['referents']['n']}, "
            f"string facts {r['string_facts']['covered']}/{r['string_facts']['n']}, generator "
            f"surfaces {r['generator_surfaces']['covered']}/{r['generator_surfaces']['n']}; "
            f"surfaces in relations {len(r['surfaces_in_relations']['hits'])} "
            f"(+{len(r['surfaces_in_relations']['labels_group_hits'])} labels)",
            f"      (c) echo {p['echo_2_4gram']}/{p['n_predicates']}, whole "
            f"{p['whole_match']}/{p['n_predicates']}, max {p['max_tokens']} tokens, "
            f"lengths {p['length_tokens']}",
            f"      (d) R5 residue {d['referents_with_residue']} referent(s) {d['by_category']}",
            f"      (e) masked: refused={e['refused_any']} "
            f"({e['refused_documents']}/{len(e['documents'])} docs), "
            f"{e['masked_5gram_hit_share']:.1%} of masked 5-grams hit, "
            f"{e['corpus_5grams_surviving_share']:.1%} of corpus 5-grams survive, "
            f"{e['generator_surfaces_surviving']['distinct']} generator surface(s) survive "
            f"({len(e['generator_surfaces_surviving']['extractor_misses'])} extractor misses)"]
    c = report.get("predicate_control")
    if c:
        lines.append(f"  (c) control english_prose: expected echo "
                     f"{c['expected_echo_share']:.1%}, whole {c['expected_whole_share']:.1%}")
    for comp in (report.get("g1") or {}).get("comparisons", []):
        stubbed = comp.get("stub_corpora") or []
        lines.append(f"  (f) {comp['name']}" + (f" (stub: {', '.join(stubbed)})" if stubbed
                                                  else "") + ": " + "; ".join(
            f"{arm} differs in {v['differs']}" for arm, v in comp["by_arm"].items()))
    return "\n".join(lines)


# ----------------------------------------------------------------------- extract

CONTAINER_PROBE_ROOT = "/data/probe"
EXTRACT_MODULE = "privdeep.tier1_local.probe_extract"


def _compose(*args: str, env: dict[str, str] | None = None) -> Any:
    """``run_evaluation._compose``, through one name the tests can fake."""
    return R._compose(*args, env=env)


def extract(corpus_dir: Path, k: int, out_dir: Path, *, force: bool = False,
            allow_dirty: bool = False) -> list[Path]:
    """k fresh extractions of one corpus, run inside ``privdeep-core``, copied out.

    Free (local GPU only) and no cloud call, but it (re)starts the core with
    this corpus mounted at ``/corpus``, as a phase-one run does. Existing files
    are kept unless ``force``, and even then moved aside, never deleted.
    """
    if k < 1:
        raise SystemExit("k must be at least 1")
    corpus_dir = corpus_dir.resolve()
    cid = load_corpus(corpus_dir).id
    prov = R.host_provenance()
    if R._refuse_unclean(prov, allow_dirty):
        raise SystemExit(1)
    env = {**os.environ, "PRIVDEEP_CORPUS_DIR": str(corpus_dir)}
    up = _compose("up", "-d", R.CORE, env=env)
    if up.returncode != 0:
        raise SystemExit(f"could not start {R.CORE}:\n{up.stderr}")
    container_dir = f"{CONTAINER_PROBE_ROOT}/{cid}"
    mk = _compose("exec", "-T", R.CORE, "mkdir", "-p", container_dir, env=env)
    if mk.returncode != 0:
        raise SystemExit(f"could not create {container_dir} in {R.CORE}:\n{mk.stderr}")
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    records = []
    for i in range(1, k + 1):
        host = out_dir / f"extraction_{i}.json"
        if host.exists():
            if not force:
                print(f"  {host} exists, skipping (--force moves it aside)")
                continue
            n = 1
            while (aside := host.with_name(f"{host.stem}.attempt{n}.json")).exists():
                n += 1
            host.rename(aside)
        container = f"{container_dir}/extraction_{i}.json"
        t0 = time.time()
        proc = _compose("exec", "-T", *prov.env_args(), R.CORE, "python", "-m", EXTRACT_MODULE,
                        "/corpus", container, env=env)
        if proc.returncode != 0:
            raise SystemExit(f"extraction {i} failed (exit {proc.returncode}):\n"
                             f"{proc.stdout}\n{proc.stderr}")
        cp = _compose("cp", f"{R.CORE}:{container}", str(host), env=env)
        if cp.returncode != 0:
            raise SystemExit(f"could not copy {container} out of {R.CORE}:\n{cp.stderr}")
        tail = (proc.stdout or "").strip().splitlines()
        print("   ", tail[-1] if tail else "(no output)")
        records.append({"file": host.name, "seconds": round(time.time() - t0, 1)})
        written.append(host)
    after = R.host_provenance()
    manifest = {"instrument": "scripts/tier1_probe.py", "mode": "extract", "corpus": cid,
                "corpus_path": _rel(corpus_dir), "k": k, "runs": records,
                "provenance": prov.to_json(), "provenance_after": after.to_json(),
                "changed_during": R._changed_since(prov, after)}
    (out_dir / "extract_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if manifest["changed_during"]:
        raise SystemExit(f"the code changed during extraction: {manifest['changed_during']}")
    return written


# ----------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> dict[str, Any] | list[Path]:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    a = sub.add_parser("analyse", help="offline analysis of saved extractions")
    a.add_argument("corpus", type=Path)
    a.add_argument("--extractions", nargs="+", type=Path, required=True, metavar="FILE",
                   help="extractions.json files over this corpus (duplicates are merged)")
    a.add_argument("--g1", nargs="*", default=[], metavar="CORPUS[=EXTRACTIONS]",
                   help="other corpora for the G1 inventory, each with the extractions.json "
                        "its payload is built from (the batch's r5 one)")
    a.add_argument("--g1-stub", action="store_true",
                   help="also build every G1 corpus under the stub extraction (labelled "
                        "'stub'), and let a --g1 corpus without an extraction appear there only")
    a.add_argument("--out", type=Path, default=None,
                   help="output JSON (default eval/probe/<corpus-id>.json)")
    e = sub.add_parser("extract", help="k extractions inside privdeep-core (local GPU, "
                                       "no cloud call)")
    e.add_argument("corpus", type=Path)
    e.add_argument("--k", type=int, default=3)
    e.add_argument("--out-dir", type=Path, default=None,
                   help="default eval/probe/extractions/<corpus-id>/")
    e.add_argument("--force", action="store_true", help="move existing files aside and redo")
    e.add_argument("--allow-dirty", action="store_true")
    args = ap.parse_args(argv)
    if args.mode == "extract":
        out_dir = args.out_dir or DEFAULT_OUT_DIR / "extractions" / load_corpus(args.corpus).id
        return extract(args.corpus, args.k, out_dir, force=args.force,
                       allow_dirty=args.allow_dirty)
    report = analyse(args.corpus, args.extractions, args.g1, g1_stub=args.g1_stub)
    out = args.out or DEFAULT_OUT_DIR / f"{report['corpus']['id']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(_summary(report))
    print(f"\nwrote {out}")
    return report


if __name__ == "__main__":
    main()
