"""Measure the false-refusal rate of every deterministic egress linter on clean payloads.

Why this exists
---------------
The containment check (Fix 1 in the ICCIT scope) and the entropy screen are
deterministic, which is the property the paper leans on. Determinism cuts both
ways: a linter that refuses a legitimate payload does so every time, so its
false-positive rate is an operating cost the paper must state as a number with
an interval, not as "low". The W3 exit criterion is exactly that number,
measured on payloads that are clean by construction. This module is the
instrument that produces it. It is not a unit test; it is run once per seed and
its output, ``eval/fp_report.json``, is the artifact the paper cites.

What "clean by construction" means here
---------------------------------------
Every payload is generated from a seeded template grammar, never copied from a
document, and the private document the shingle filter is built from is
generated so that every window of ``n_min`` consecutive tokens contains at
least one token that occurs nowhere in the clean corpus. A shared 5-gram is
therefore impossible, and the harness confirms it by brute force before it
reports anything. That isolates what is being measured: any refusal by the
shingle filter on this corpus is a Bloom-filter hash collision, not a
linguistic coincidence. The linguistic-coincidence rate, a clean payload that
legitimately reproduces five consecutive words of the corpus, is a property of
real traffic against a real corpus and is NOT measured here; the paper must not
cite this number as if it were.

Strata
------
* ``english_prose``: technical and business English paragraphs from a template
  grammar with vocabulary wide enough that 5-grams are diverse.
* ``abstract_json``: payloads shaped like ``AbstractPayload.to_json()``, with
  ``indent=2`` as the builder ships them, random abstract types and random
  slot placeholders ``⟦SLOT:<CATEGORY>_<hex8>⟧``. Slot placeholders are the one
  legitimate egress token that looks like an identifier; no linter may refuse
  them, and this stratum is where that shows.
* ``abstract_json_compact``: the same payloads serialised without whitespace.
  Added beyond the brief because the measurement is stark: a compact
  serialisation is one whitespace token of ~900 characters at about 5.2
  bits/char, and the entropy screen refuses it. The builder's ``indent=2`` is
  therefore load-bearing, and this stratum is what will catch a change to it.
* ``code_snippet``: python, JSON and YAML with content hashes, version strings
  and UUID-shaped test ids. Hosts are ``*.invalid`` throughout.
* ``vietnamese_prose``: Vietnamese with full diacritics from a template grammar.

What is reported, and what it can and cannot resolve
----------------------------------------------------
Per linter: refusals / N, the Wilson 95% interval, and the same per stratum.
For the shingle filter the Bloom filter's ``estimated_fp_rate()`` (per shingle
lookup, from bit occupancy) is reported alongside, with the per-payload rate it
implies given how many shingles each payload actually has. With N in the
hundreds, zero refusals bounds the per-payload rate at about 0.8% at 95%; the
Bloom estimate is three or four orders of magnitude below that. The empirical
measurement therefore cannot confirm the estimate, only fail to refute it, and
the report says so by carrying both numbers.

A positive control runs each sentence of the private document through the
shingle filter; the catch rate must be 1.0, and the harness refuses to write a
report otherwise. A report whose control failed must not exist.

Through the deployed chain, in two carry modes (plan task EXP5, experiment X3)
-----------------------------------------------------------------------------
The per-linter columns above call each linter standalone on the raw payload
text. That is not what runs. The live handler, ``gateway/main.py``
``proxy_messages``, receives a Messages request body, decodes it
(``_decoded_text``: parse the JSON, inspect every decoded string, keys
included) and runs ``_inspect_text`` with ``advance_carry=True``: canaries,
entropy, the extra screens, then containment over the whole-body stream, the
per-path streams chained to earlier requests, and the key stream. The
standalone entropy column is the clearest case of the difference: it scores
the payload's serialisation, while the deployed chain scores decoded strings.

So every payload is also wrapped as the core's ``CloudClient`` wraps a user
turn (``model``, ``max_tokens``, ``messages``, ``stream``), serialised as
httpx 0.28 serialises ``json=`` (``ensure_ascii=False``, compact separators),
and passed through those two functions of the imported gateway module,
in-process, against a filter installed through the gateway's own
``/containment/seal`` route and with five session canaries registered through
``/canaries``, as a pipeline run does. Nothing is mocked inside the chain; the
gateway's configured thresholds, its regex screen and its hit threshold are
the ones in force, and the report records them.

The per-path carry makes the verdict on one payload depend on the payloads
before it, so the chain is run twice and the modes are reported separately:

* ``reset_per_payload``: the carry is cleared before each payload, as a fresh
  seal clears it. Payloads are independent, and a Wilson interval applies.
* ``session_per_stratum``: the carry is cleared once per stratum and then
  accumulates over its 100 payloads in index order, as one simulated session
  would. A refused payload does not join the carry, exactly as live. Payloads
  in one session are not independent, so no interval is reported for this mode.

The positive control is repeated through the deployed chain (carry reset per
sentence) and must also be 1.0 before a report is written. The gateway
module's globals are restored afterwards, so the instrument leaves no seal,
carry or canary behind in a process that imports it.

Measured, seed 20260906, 500 payloads (100 per stratum)
--------------------------------------------------------
* Shingle filter: 0/500 refused, Wilson 95% [0, 0.0076]. Bloom occupancy gives
  8.0e-8 per shingle lookup, 2.5e-5 per payload at a mean of 309 shingles per
  payload, so 0.012 refusals were expected on this corpus and none occurred.
  The 5-gram disjointness held with zero rejected template fills, and the
  positive control caught 33/33 private sentences.
* Entropy screen: 103/500 refused, all in two places. 100/100 compact JSON
  payloads (one token of 180-700 characters at 4.97-5.25 bits/char), and 3/100
  code snippets, each a YAML image reference of the form
  ``registry.example.invalid/<name>@sha256:<64 hex>`` measuring 4.86-4.88
  bits/char against the 4.85 threshold. The prose and shipped-JSON strata had
  no refusals. The threshold therefore sits within 0.03 bits of an ordinary
  digest-pinned image reference, and any payload that carries one has a real
  chance of refusal; that is a fact about the screen's design (whitespace
  tokens over 24 characters, one threshold), not about this corpus.
* Deployed chain, same seed, when this section was added: 122/500 refused,
  with the same counts in both carry modes. That is 100/100 compact JSON
  (entropy, ``COVERT_CHANNEL_DETECTED``) and 22/100 code snippets (the 3
  entropy refusals above plus 19 regex ``SECRET_PATTERN``), and 0 elsewhere.
  The chain stops at its first refusal, so on this corpus it is the union of
  the standalone screens. The per-path carry accumulated over a stratum added
  no refusal. Decoding does not rescue the compact stratum here, because the
  payload travels as one message string and is still one long token once
  decoded. The deployed positive control caught 33/33, all by containment.

Registry
--------
``REGISTRY`` is a list of ``(name, factory)``. A factory takes the run fixture
and returns the linter's scan callable, ``str -> verdict`` with ``.blocked``.
The indirection exists because the shingle filter is stateful and must be built
from the private document first; a stateless linter ignores the fixture. The
regex screen, written concurrently, is added by the orchestrator in one line::

    REGISTRY.append(("regex", lambda _fx: RegexScreen().scan))

Nothing private reaches the report: payload text, the private document and
matched shingles never leave the process. The report carries counts, the names
of the rules that fired, and a SHA-256 fingerprint of the corpus so a re-run
under the same seed can be checked for identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "gateway"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from linters.entropy_linter import scan_payload  # noqa: E402
from linters.regex_rules import RegexScreen  # noqa: E402

from shared.shingle_filter import ShingleFilter  # noqa: E402
from shared.shingle_filter import tokenize as _filter_tokenize  # noqa: E402

__all__ = [
    "CARRY_MODES",
    "REGISTRY",
    "DEFAULT_SEED",
    "N_PER_STRATUM",
    "Payload",
    "RunFixture",
    "build_corpus",
    "build_fixture",
    "deployed_chain",
    "envelope",
    "generate_private_document",
    "main",
    "ngrams",
    "positive_control",
    "run_registry",
    "shared_ngrams",
    "tokenize",
    "wilson_interval",
]

DEFAULT_SEED = 20260906
N_PER_STRATUM = 100
# Same defaults as gateway/main.py reads from the environment. Fixed here rather
# than read from the environment so that a run is reproducible from the seed
# alone; the values are recorded in the report.
SHINGLE_N_MIN = 5
SHINGLE_N_MAX = 8
SHINGLE_HIT_THRESHOLD = 1
SHINGLE_TARGET_FP = 1e-7
ENTROPY_THRESHOLD = 4.85
PRIVATE_DOC_WORDS = 600
# Instrument salt. Not a secret: the filter built here protects nothing, and a
# fixed salt is what makes the bit occupancy, and so the Bloom estimate,
# reproducible from the seed.
SALT = b"privdeep-fp-harness"

# Mirrors privdeep.models.document.SLOT_CATEGORIES. Pinned here so the
# instrument runs standalone; the test asserts the two stay equal.
SLOT_CATEGORIES: tuple[str, ...] = (
    "PERSON", "ORG", "PROJECT", "LOCATION", "DATE", "MONEY", "QUANTITY", "IDENTIFIER",
)

# The filter's own tokenisation, imported rather than reimplemented, so the
# "no shared 5-gram" guarantee is stated in the filter's terms and cannot drift
# from it. A copy here was correct while both were `casefold` over `\w+`; it
# would now silently disagree about Unicode normalisation and confusables, and
# the disagreement would show up as a false-positive rate measured against a
# tokeniser the gateway does not use.
tokenize = _filter_tokenize


def ngrams(tokens: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


class Verdict(Protocol):
    @property
    def blocked(self) -> bool: ...


Linter = Callable[[str], Verdict]
LinterFactory = Callable[["RunFixture"], Linter]


@dataclass(frozen=True, slots=True)
class Payload:
    stratum: str
    index: int
    text: str


@dataclass(frozen=True, slots=True)
class RunFixture:
    """Everything a linter factory may need. Never serialised."""

    seed: int
    private_doc: str
    private_sentences: tuple[str, ...]
    shingle: ShingleFilter
    n_min: int
    n_max: int
    hit_threshold: int
    entropy_threshold: float


# --------------------------------------------------------------------------- clean corpus
#
# Vocabulary rules that make the private document's anchors possible: no month
# names, no person, place or organisation names, no four-digit years and no
# numbers above 99 anywhere in the clean grammars. Everything else is fair game.

_EN_SUBJECTS = (
    "the procurement team", "the audit committee", "the platform engineering group",
    "the reference monitor", "the ingestion pipeline", "the steering board",
    "the compliance function", "the vendor assessment", "the quarterly forecast",
    "the migration plan", "the incident review", "the containment check",
    "the retrieval layer", "the evaluation harness", "the deployment schedule",
    "the risk register", "the training programme", "the support desk",
    "the retention policy", "the release checklist", "the finance workstream",
    "the observability stack", "the onboarding guide", "the capacity model",
    "the change advisory board", "the sandbox environment", "the billing reconciliation",
    "the localisation effort", "the security review", "the reporting cadence",
)
_EN_VERBS = (
    "reduced", "increased", "documented", "reviewed", "consolidated", "postponed",
    "prioritised", "measured", "flagged", "streamlined", "validated", "approved",
    "rejected", "extended", "renegotiated", "absorbed", "clarified", "tracked",
    "simplified", "constrained", "re-baselined", "escalated", "deferred", "summarised",
    "benchmarked", "isolated", "reconciled", "instrumented",
)
_EN_OBJECTS = (
    "the onboarding backlog", "latency at the ninety-fifth percentile", "the licensing overhead",
    "the monthly reconciliation", "the fallback procedure", "the vendor shortlist",
    "the throughput target", "the failover drill", "the sandbox rollout",
    "the observability budget", "the approval workflow", "the retry policy",
    "the cache invalidation rules", "the error budget", "the handover notes",
    "the access review", "the cost allocation model", "the schema migration",
    "the acceptance criteria", "the rollback plan", "the audit trail format",
    "the alert thresholds", "the dependency inventory", "the test coverage gap",
    "the queue depth", "the storage quota", "the translation glossary",
    "the escalation matrix", "the sprint capacity", "the service catalogue",
)
_EN_MODIFIERS = (
    "during the pilot phase", "after the second review", "ahead of the renewal",
    "under the revised policy", "across both regions", "before the freeze",
    "without additional headcount", "within the agreed tolerance", "over the last cycle",
    "despite the schedule pressure", "in the staging tier", "per the runbook",
    "at the request of the board", "with no customer impact", "pending sign-off",
    "as a temporary measure", "once the dashboards were live", "by the end of the sprint",
    "against the baseline figures", "alongside the vendor audit",
)
_EN_CONNECTIVES = (
    "Consequently", "In parallel", "As a result", "By contrast", "Meanwhile",
    "Nevertheless", "In practice", "For the same reason", "On balance", "Separately",
)
_EN_TEMPLATES = (
    "{S} {V} {O} {M}.",
    "{C}, {S} {V} {O}.",
    "{S} {V} {O}, and {S2} {V2} {O2}.",
    "Although {S} {V} {O}, {S2} {V2} {O2} {M}.",
    "{S} {V} {O} because {S2} {V2} {O2}.",
    "{M}, {S} {V} {O}.",
    "{C}, {S} {V} {O} while {S2} {V2} {O2}.",
)


def _cap(s: str) -> str:
    return s[0].upper() + s[1:] if s else s


def gen_english_prose(rng: random.Random) -> str:
    sentences = []
    for _ in range(rng.randint(3, 6)):
        t = rng.choice(_EN_TEMPLATES)
        s = t.format(
            S=rng.choice(_EN_SUBJECTS), V=rng.choice(_EN_VERBS), O=rng.choice(_EN_OBJECTS),
            S2=rng.choice(_EN_SUBJECTS), V2=rng.choice(_EN_VERBS), O2=rng.choice(_EN_OBJECTS),
            M=rng.choice(_EN_MODIFIERS), C=rng.choice(_EN_CONNECTIVES),
        )
        sentences.append(_cap(s))
    return " ".join(sentences)


_ABSTRACT_TYPES = (
    "INITIATIVE", "STAKEHOLDER", "FINANCIAL_METRIC", "REGION", "MILESTONE", "VENDOR",
    "RISK", "DELIVERABLE", "CONTRACT", "TIMEFRAME", "HEADCOUNT", "FACILITY", "BUDGET_LINE",
    "OUTCOME", "POLICY", "DATASET",
)
_ABSTRACT_PREDICATES = (
    "led by", "reported decline in", "depends on", "located in", "scheduled for",
    "funded by", "mitigated by", "delivers", "supersedes", "blocked by", "owned by",
    "measured against", "renewed under", "escalated to", "constrains", "precedes",
)


def _hex8(rng: random.Random) -> str:
    return f"{rng.getrandbits(32):08x}"


def _slot(rng: random.Random, category: str | None = None) -> str:
    return f"⟦SLOT:{category or rng.choice(SLOT_CATEGORIES)}_{_hex8(rng)}⟧"


def _abstract_payload_obj(rng: random.Random) -> dict[str, Any]:
    n_rel, n_slots = rng.randint(3, 10), rng.randint(2, 10)
    return {
        "doc_id": f"doc-{rng.getrandbits(16):04x}",
        "relations": [
            {
                "subject_type": rng.choice(_ABSTRACT_TYPES),
                "predicate": rng.choice(_ABSTRACT_PREDICATES),
                "object_type": rng.choice(_ABSTRACT_TYPES),
            }
            for _ in range(n_rel)
        ],
        "slots": [
            {"id": _slot(rng, c), "category": c}
            for c in (rng.choice(SLOT_CATEGORIES) for _ in range(n_slots))
        ],
        "stats": {
            "cells": rng.randint(0, 99), "blocks": rng.randint(0, 40), "chars": rng.randint(0, 99),
        },
    }


def gen_abstract_json(rng: random.Random) -> str:
    """As AbstractPayload.to_json() serialises: ensure_ascii=False, indent=2."""
    return json.dumps(_abstract_payload_obj(rng), ensure_ascii=False, indent=2)


def gen_abstract_json_compact(rng: random.Random) -> str:
    return json.dumps(_abstract_payload_obj(rng), ensure_ascii=False, separators=(",", ":"))


def _hexstr(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(n))


def _uuid(rng: random.Random) -> str:
    return "-".join(_hexstr(rng, w) for w in (8, 4, 4, 4, 12))


def _semver(rng: random.Random) -> str:
    return f"{rng.randint(0, 9)}.{rng.randint(0, 30)}.{rng.randint(0, 20)}"


_CODE_NAMES = (
    "report-builder", "evidence-store", "outline-planner", "slot-reintegrator", "citation-grounder",
    "ingest-worker", "audit-writer", "purifier", "drafter", "scheduler",
)
_CODE_FUNCS = ("verify", "check_digest", "validate_artifact", "assert_pinned", "confirm")


def _gen_python(rng: random.Random) -> str:
    fn, ver, digest, tid = rng.choice(_CODE_FUNCS), _semver(rng), _hexstr(rng, 64), _uuid(rng)
    name = rng.choice(_CODE_NAMES).replace("-", "_")
    return (
        f'"""Verify the pinned {name} artifact before unpacking."""\n'
        "import hashlib\n\n"
        f'EXPECTED_SHA256 = "{digest}"\n'
        f'RELEASE_VERSION = "{ver}"\n'
        f'TEST_ID = "{tid}"\n'
        f"RETRIES = {rng.randint(1, 9)}\n\n\n"
        f"def {fn}(path: str) -> bool:\n"
        '    with open(path, "rb") as fh:\n'
        "        digest = hashlib.sha256(fh.read()).hexdigest()\n"
        "    return digest == EXPECTED_SHA256\n"
    )


def _gen_json_config(rng: random.Random) -> str:
    obj = {
        "service": rng.choice(_CODE_NAMES),
        "version": _semver(rng),
        "build": {"commit": _hexstr(rng, 40), "image_digest": f"sha256:{_hexstr(rng, 64)}"},
        "test_ids": [_uuid(rng) for _ in range(rng.randint(1, 4))],
        "endpoints": [
            f"https://api.example.invalid/v{rng.randint(1, 4)}/{rng.choice(_CODE_NAMES)}"
        ],
        "retries": rng.randint(0, 9),
        "timeout_seconds": rng.randint(1, 90),
    }
    return json.dumps(obj, indent=2)


def _gen_yaml(rng: random.Random) -> str:
    svc = rng.choice(_CODE_NAMES)
    return (
        "apiVersion: v1\n"
        "kind: ConfigMap\n"
        "metadata:\n"
        f"  name: {svc}-config\n"
        "  labels:\n"
        f"    release: \"{_semver(rng)}\"\n"
        "data:\n"
        f"  image: registry.example.invalid/{svc}@sha256:{_hexstr(rng, 64)}\n"
        f"  commit: {_hexstr(rng, 40)}\n"
        f"  test_id: {_uuid(rng)}\n"
        f"  replicas: \"{rng.randint(1, 9)}\"\n"
        f"  upstream: https://{rng.choice(_CODE_NAMES)}.example.invalid\n"
    )


def gen_code_snippet(rng: random.Random) -> str:
    return rng.choice((_gen_python, _gen_json_config, _gen_yaml))(rng)


_VI_SUBJECTS = (
    "hệ thống", "nhóm nghiên cứu", "bộ phận kỹ thuật", "phòng kế toán", "ban điều hành",
    "quy trình kiểm duyệt", "mô hình ngôn ngữ", "tầng truy xuất", "công cụ đánh giá",
    "kế hoạch triển khai", "chính sách lưu trữ", "đội vận hành", "bộ lọc nội dung",
    "cổng kiểm soát", "lớp bảo mật", "nhóm sản phẩm",
)
_VI_VERBS = (
    "đã cải thiện", "đã triển khai", "đang đánh giá", "sẽ mở rộng", "đã hoàn thành",
    "đề xuất", "đang xem xét", "đã ghi nhận", "đã rút gọn", "sẽ điều chỉnh", "đã xác nhận",
    "đã tạm hoãn", "đang đo lường", "đã chuẩn hóa", "sẽ bàn giao",
)
_VI_OBJECTS = (
    "quy trình xử lý dữ liệu", "hiệu suất của mô hình", "chi phí vận hành", "kế hoạch bảo trì",
    "tài liệu hướng dẫn", "khả năng mở rộng", "cơ chế bảo mật", "chính sách lưu trữ",
    "ngưỡng cảnh báo", "danh sách phụ thuộc", "tiêu chí nghiệm thu", "phương án khôi phục",
    "định dạng nhật ký kiểm toán", "độ trễ ở phân vị chín mươi lăm", "ngân sách quan sát",
    "quy tắc vô hiệu hóa bộ đệm",
)
_VI_MODIFIERS = (
    "trong giai đoạn thử nghiệm", "sau đợt kiểm tra thứ hai", "theo chính sách mới",
    "với ngân sách hiện có", "trước thời hạn đã thống nhất", "mà không cần thêm nhân sự",
    "trên cả hai khu vực", "trong phạm vi sai số cho phép", "dưới áp lực tiến độ",
    "theo yêu cầu của ban điều hành", "khi bảng điều khiển đã hoạt động",
)
_VI_CONNECTIVES = ("Do đó", "Bên cạnh đó", "Tuy nhiên", "Đồng thời", "Ngoài ra", "Trên thực tế")
_VI_TEMPLATES = (
    "{S} {V} {O} {M}.",
    "{C}, {S} {V} {O}.",
    "{S} {V} {O}, và {S2} {V2} {O2}.",
    "Mặc dù {S} {V} {O}, {S2} {V2} {O2} {M}.",
    "{S} {V} {O} vì {S2} {V2} {O2}.",
    "{M}, {S} {V} {O}.",
)


def gen_vietnamese_prose(rng: random.Random) -> str:
    sentences = []
    for _ in range(rng.randint(3, 6)):
        s = rng.choice(_VI_TEMPLATES).format(
            S=rng.choice(_VI_SUBJECTS), V=rng.choice(_VI_VERBS), O=rng.choice(_VI_OBJECTS),
            S2=rng.choice(_VI_SUBJECTS), V2=rng.choice(_VI_VERBS), O2=rng.choice(_VI_OBJECTS),
            M=rng.choice(_VI_MODIFIERS), C=rng.choice(_VI_CONNECTIVES),
        )
        sentences.append(_cap(s))
    return " ".join(sentences)


STRATA: dict[str, Callable[[random.Random], str]] = {
    "english_prose": gen_english_prose,
    "abstract_json": gen_abstract_json,
    "abstract_json_compact": gen_abstract_json_compact,
    "code_snippet": gen_code_snippet,
    "vietnamese_prose": gen_vietnamese_prose,
}


def _rng(seed: int, label: str) -> random.Random:
    # One generator per stratum, derived from the seed and the stratum name, so
    # adding a stratum leaves the others' payloads unchanged. Reproducibility,
    # not unpredictability, is the requirement here.
    return random.Random(f"{seed}:{label}")  # noqa: S311


def build_corpus(
    seed: int = DEFAULT_SEED, n_per_stratum: int = N_PER_STRATUM
) -> tuple[Payload, ...]:
    out: list[Payload] = []
    for name, gen in STRATA.items():
        rng = _rng(seed, name)
        out.extend(Payload(name, i, gen(rng)) for i in range(n_per_stratum))
    return tuple(out)


def corpus_fingerprint(corpus: Iterable[Payload]) -> str:
    h = hashlib.sha256()
    for p in corpus:
        h.update(f"{p.stratum}\x1f{p.index}\x1f".encode())
        h.update(p.text.encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()


# --------------------------------------------------------------------------- private document
#
# Synthetic. Names, places and figures are invented or generic; the document is
# the only input to the shingle filter and never leaves the process. Each
# template places an anchor (name, place, organisation, codename, figure) at
# most four tokens from the previous one, and every fill is checked so that
# every n_min-window of the finished document holds a token absent from the
# clean corpus. That is the construction that makes a shared 5-gram impossible.

_PERSONS = (
    "Phạm Quốc Bảo", "Đặng Mỹ Linh", "Hoàng Tuấn Kiệt", "Vũ Ngọc Hà", "Lâm Gia Huy",
    "Bùi Thanh Trúc", "Đỗ Minh Khôi", "Trịnh Kim Oanh", "Ingrid Halvorsen", "Tomasz Wieczorek",
    "Adaeze Okonkwo", "Rafael Ibarra", "Mei-Ling Tsai", "Kwame Boateng", "Sigrún Þórsdóttir",
)
_ORGS = (
    "Halvorsen Logistics", "Ibarra Freight", "Okonkwo Analytics", "Wieczorek Foundry",
    "Tsai Semiconductor", "Boateng Holdings", "Trúc Lâm Textiles", "Kiệt Bảo Engineering",
)
_PLACES = (
    "Hải Phòng", "Cần Thơ", "Biên Hòa", "Đà Lạt", "Vũng Tàu", "Quy Nhơn", "Bắc Ninh",
    "Tromsø", "Gdańsk", "Kumasi", "Oaxaca", "Kaohsiung",
)
_CODENAMES = ("Marigold", "Saffron", "Cobalt", "Juniper", "Tamarind", "Obsidian", "Verdigris")
_MONTHS = (
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
)
_PRIVATE_TEMPLATES = (
    "{P} of {O} approved {MONEY} for the {PL} site on {DATE}.",
    "On {DATE}, {P} reported that {CN} shipped {QTY} units from {PL}.",
    "{O} invoiced {MONEY} under contract {CT}, which {P} countersigned in {PL}.",
    "The {PL} warehouse run by {P} lost {MONEY} when {CN} slipped to {DATE}.",
    "{P} and {P2} met in {PL} on {DATE} to renegotiate {CT} with {O}.",
    "{CN} margins fell {PCT} percent after {O} withdrew from {PL} in {MONTH}.",
    "{P} holds {QTY} shares of {O}, valued at {MONEY} on {DATE}.",
    "Contract {CT} assigns {P} to the {PL} rollout of {CN} until {DATE}.",
    "{O} paid {P} {MONEY} in {MONTH} for the {CN} audit at {PL}.",
    "{P2} warned {P} that {CN} would overrun {MONEY} unless {O} left {PL}.",
)


def _fill_private_template(rng: random.Random) -> str:
    year = rng.randint(2019, 2031)
    return rng.choice(_PRIVATE_TEMPLATES).format(
        P=rng.choice(_PERSONS), P2=rng.choice(_PERSONS), O=rng.choice(_ORGS),
        PL=rng.choice(_PLACES), CN=rng.choice(_CODENAMES), MONTH=rng.choice(_MONTHS),
        DATE=f"{rng.randint(1, 28)} {rng.choice(_MONTHS)} {year}",
        MONEY=f"{rng.randint(100, 999)},{rng.randint(100, 999)} USD",
        QTY=f"{rng.randint(1000, 99999)}", PCT=f"{rng.randint(3, 47)}",
        CT=f"VN-{year}-{rng.randint(1000, 9999)}",
    )


def _windows_anchored(tokens: list[str], clean_vocab: set[str], n: int) -> bool:
    """True iff every n-window of `tokens` holds at least one token outside clean_vocab."""
    if len(tokens) < n:
        return True
    return all(
        any(t not in clean_vocab for t in tokens[i : i + n]) for i in range(len(tokens) - n + 1)
    )


@dataclass(frozen=True, slots=True)
class PrivateDocument:
    text: str = field(repr=False)
    sentences: tuple[str, ...] = field(repr=False)
    n_words: int
    rejected_fills: int


def generate_private_document(
    seed: int,
    clean_vocab: set[str],
    *,
    n_min: int = SHINGLE_N_MIN,
    target_words: int = PRIVATE_DOC_WORDS,
) -> PrivateDocument:
    rng = _rng(seed, "private")
    sentences: list[str] = []
    tokens: list[str] = []
    rejected = 0
    while len(tokens) < target_words:
        for _attempt in range(200):
            s = _fill_private_template(rng)
            cand = tokenize(s)
            # The check spans the join with the previous sentence: shingles
            # ignore sentence boundaries, so must the guarantee.
            if _windows_anchored(tokens[-(n_min - 1) :] + cand, clean_vocab, n_min):
                break
            rejected += 1
        else:
            raise RuntimeError("private-document grammar cannot satisfy the anchor property")
        sentences.append(s)
        tokens.extend(cand)
    text = " ".join(sentences)
    if not _windows_anchored(tokenize(text), clean_vocab, n_min):
        raise RuntimeError("anchor property violated after assembly")  # unreachable by design
    return PrivateDocument(text, tuple(sentences), len(tokens), rejected)


def shared_ngrams(private_doc: str, corpus: Iterable[Payload], n: int) -> int:
    """Brute force: number of n-grams the private document shares with any clean payload."""
    private = ngrams(tokenize(private_doc), n)
    clean: set[tuple[str, ...]] = set()
    for p in corpus:
        clean |= ngrams(tokenize(p.text), n)
    return len(private & clean)


# --------------------------------------------------------------------------- fixture and registry


def build_fixture(
    seed: int,
    corpus: tuple[Payload, ...],
    *,
    n_min: int = SHINGLE_N_MIN,
    n_max: int = SHINGLE_N_MAX,
    hit_threshold: int = SHINGLE_HIT_THRESHOLD,
    entropy_threshold: float = ENTROPY_THRESHOLD,
) -> tuple[RunFixture, PrivateDocument]:
    clean_vocab: set[str] = set()
    for p in corpus:
        clean_vocab.update(tokenize(p.text))
    doc = generate_private_document(seed, clean_vocab, n_min=n_min)
    f = ShingleFilter(
        salt=SALT, n_min=n_min, n_max=n_max, hit_threshold=hit_threshold,
        target_fp_rate=SHINGLE_TARGET_FP,
    )
    f.index_document(doc.text)
    f.seal()
    fx = RunFixture(
        seed, doc.text, doc.sentences, f, n_min, n_max, hit_threshold, entropy_threshold
    )
    return fx, doc


def _entropy_factory(fx: RunFixture) -> Linter:
    return lambda text: scan_payload(text, threshold=fx.entropy_threshold)


def _shingle_factory(fx: RunFixture) -> Linter:
    return fx.shingle.inspect


REGISTRY: list[tuple[str, LinterFactory]] = [
    ("entropy", _entropy_factory),
    ("shingle", _shingle_factory),
]


# --------------------------------------------------------------------------- statistics


def wilson_interval(refusals: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion. Sane at 0/N, unlike Wald."""
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0 <= refusals <= n:
        raise ValueError("refusals must be in [0, n]")
    p = refusals / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    # At 0/N and N/N the bound is exactly 0 or 1 in exact arithmetic; floating
    # point returns 4e-19 and 0.9999..., which would misreport a hard limit.
    lo = 0.0 if refusals == 0 else max(0.0, centre - half)
    hi = 1.0 if refusals == n else min(1.0, centre + half)
    return lo, hi


@dataclass(frozen=True, slots=True)
class RateReport:
    n: int
    refusals: int

    @property
    def rate(self) -> float:
        return self.refusals / self.n if self.n else 0.0

    def to_dict(self) -> dict[str, Any]:
        lo, hi = wilson_interval(self.refusals, self.n)
        return {"n": self.n, "refusals": self.refusals, "rate": self.rate, "wilson95": [lo, hi]}


@dataclass(frozen=True, slots=True)
class LinterReport:
    name: str
    overall: RateReport
    by_stratum: dict[str, RateReport]
    rules_fired: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            **self.overall.to_dict(),
            "by_stratum": {k: v.to_dict() for k, v in self.by_stratum.items()},
            "rules_fired": dict(self.rules_fired),
        }


def _rule_name(verdict: Any) -> str:
    """The rule that fired: the reason's leading identifier, before any detail.

    Reasons carry no content by house rule, but the entropy reason carries the
    offending token's length and entropy, which is one distinct string per
    payload. The report wants a histogram over rules, not over payloads.
    """
    reason = str(getattr(verdict, "reason", "BLOCKED"))
    return reason.split(":", 1)[0].strip() or "BLOCKED"


def run_registry(
    fx: RunFixture,
    corpus: tuple[Payload, ...],
    registry: list[tuple[str, LinterFactory]] | None = None,
) -> list[LinterReport]:
    reports: list[LinterReport] = []
    for name, factory in registry if registry is not None else REGISTRY:
        linter = factory(fx)
        per: Counter[str] = Counter()
        n_per: Counter[str] = Counter()
        rules: Counter[str] = Counter()
        for p in corpus:
            n_per[p.stratum] += 1
            v = linter(p.text)
            if v.blocked:
                per[p.stratum] += 1
                rules[_rule_name(v)] += 1
        by_stratum = {s: RateReport(n_per[s], per[s]) for s in STRATA if n_per[s]}
        overall = RateReport(len(corpus), sum(per.values()))
        reports.append(LinterReport(name, overall, by_stratum, dict(rules)))
    return reports


def positive_control(fx: RunFixture) -> RateReport:
    """Each private sentence through the sealed filter; every one must be caught."""
    caught = sum(1 for s in fx.private_sentences if fx.shingle.inspect(s).blocked)
    return RateReport(len(fx.private_sentences), caught)


# --------------------------------------------------------------------------- deployed chain

CARRY_MODES: tuple[str, ...] = ("reset_per_payload", "session_per_stratum")
# What CloudClient.messages sends for a user turn with no system prompt or tools.
ENVELOPE_MODEL = "claude-sonnet-5"
ENVELOPE_MAX_TOKENS = 8192
N_CANARIES = 5
CANARY_PREFIX = "CANARY_PRIVDEEP_"


def envelope(text: str) -> bytes:
    """`text` as the user turn of a Messages request body, serialised as the core's
    httpx 0.28 client serialises ``json=``: UTF-8, no ASCII escaping, compact."""
    body = {
        "model": ENVELOPE_MODEL, "max_tokens": ENVELOPE_MAX_TOKENS,
        "messages": [{"role": "user", "content": text}], "stream": False,
    }
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# The gateway globals the instrument touches, restored on exit. `_shingle`,
# `_carry` and `_carry_last` are what a seal replaces; `_canaries` is what
# `/canaries` adds to; the salt is what `/containment/seal` checks for.
_GATEWAY_STATE = ("SHINGLE_HMAC_SALT", "_shingle", "_carry", "_carry_last", "_canaries")


@contextmanager
def _deployed_monitor(fx: RunFixture) -> Iterator[Any]:
    """The imported gateway module with this run's filter sealed and canaries registered.

    Both go through the gateway's own control-plane routes, in-process, so the
    seal applies the gateway's policy (its hit threshold, its n range, its
    refusal of an empty filter) rather than the harness's.
    """
    import main as gw  # gateway/main.py; `gateway/` is on sys.path above
    from fastapi.testclient import TestClient

    saved = {k: getattr(gw, k) for k in _GATEWAY_STATE}
    try:
        gw.SHINGLE_HMAC_SALT = SALT
        gw._canaries = type(gw._canaries)()
        client = TestClient(gw.app)
        rng = _rng(fx.seed, "canaries")
        tokens = [CANARY_PREFIX + f"{rng.getrandbits(128):032x}" for _ in range(N_CANARIES)]
        if client.post("/canaries", json={"tokens": tokens}).status_code != 200:
            raise RuntimeError("the gateway refused the session canaries")
        seal = client.post("/containment/seal", content=fx.shingle.to_wire()).json()
        if not seal.get("sealed"):
            raise RuntimeError(f"the gateway refused the seal: {seal.get('reason')}")
        yield gw
    finally:
        for k, v in saved.items():
            setattr(gw, k, v)


def _screen_name(f: Callable[..., Any]) -> str:
    owner = getattr(f, "__self__", None)          # a bound `.scan` names its class
    return type(owner).__name__ if owner is not None else getattr(f, "__qualname__", repr(f))


def _gateway_config(gw: Any) -> dict[str, Any]:
    s = gw._shingle
    return {
        "entry": "gateway/main.py: _decoded_text -> _inspect_text(advance_carry=True)",
        "entropy_threshold": gw.ENTROPY_THRESHOLD,
        "strict_fail_closed": gw.STRICT_FAIL_CLOSED,
        "extra_screens": [_screen_name(f) for f in gw._EXTRA_SCREENS],
        "canaries_registered": len(gw._canaries),
        "shingle": {"n_min": s.n_min, "n_max": s.n_max, "hit_threshold": s.hit_threshold,
                    "n_added": s.bloom.n_added},
        "carry_max_paths": gw._CARRY_MAX_PATHS,
        "envelope": {"model": ENVELOPE_MODEL, "max_tokens": ENVELOPE_MAX_TOKENS,
                     "fields": ["model", "max_tokens", "messages", "stream"],
                     "serialisation": "ensure_ascii=False, separators=(',', ':')"},
    }


def _reset_carry(gw: Any) -> None:
    # What a seal does to the carry, and nothing else.
    gw._carry = {}
    gw._carry_last = {}


def _through_chain(gw: Any, text: str) -> Any:
    """One payload down the live path: decode, then the chain, advancing the carry."""
    decoded, parsed = gw._decoded_text(envelope(text))
    return gw._inspect_text(decoded, parsed=parsed, advance_carry=True)


def _deployed_mode(gw: Any, corpus: tuple[Payload, ...], mode: str) -> dict[str, Any]:
    if mode not in CARRY_MODES:
        raise ValueError(f"unknown carry mode {mode!r}")
    per: Counter[str] = Counter()
    n_per: Counter[str] = Counter()
    rules: Counter[str] = Counter()
    by_stratum: dict[str, list[Payload]] = {}
    for p in corpus:
        by_stratum.setdefault(p.stratum, []).append(p)
    for stratum, payloads in by_stratum.items():
        _reset_carry(gw)                       # each stratum is its own session
        for p in sorted(payloads, key=lambda q: q.index):
            if mode == "reset_per_payload":
                _reset_carry(gw)
            n_per[stratum] += 1
            refusal = _through_chain(gw, p.text)
            if refusal is not None:
                per[stratum] += 1
                rules[_rule_name(refusal)] += 1
    independent = mode == "reset_per_payload"

    def rate(n: int, k: int) -> dict[str, Any]:
        d = RateReport(n, k).to_dict()
        if not independent:
            d["wilson95"] = None
        return d

    out = {
        "mode": mode,
        **rate(len(corpus), sum(per.values())),
        "by_stratum": {s: rate(n_per[s], per[s]) for s in STRATA if n_per[s]},
        "rules_fired": dict(rules),
    }
    if not independent:
        out["note"] = ("carry accumulated over each stratum as one session; payloads are "
                       "not independent, so no binomial interval is reported")
    return out


def _deployed_positive_control(gw: Any, fx: RunFixture) -> dict[str, Any]:
    caught = 0
    rules: Counter[str] = Counter()
    for s in fx.private_sentences:
        _reset_carry(gw)
        refusal = _through_chain(gw, s)
        if refusal is not None:
            caught += 1
            rules[_rule_name(refusal)] += 1
    n = len(fx.private_sentences)
    return {"n_sentences": n, "caught": caught, "catch_rate": caught / n if n else 0.0,
            "rules_fired": dict(rules)}


def deployed_chain(fx: RunFixture, corpus: tuple[Payload, ...]) -> dict[str, Any]:
    """Every payload, and the positive control, through the gateway's live inspection path."""
    with _deployed_monitor(fx) as gw:
        config = _gateway_config(gw)
        modes = {m: _deployed_mode(gw, corpus, m) for m in CARRY_MODES}
        control = _deployed_positive_control(gw, fx)
    return {"config": config, "modes": modes, "positive_control": control}


def git_provenance() -> dict[str, Any]:
    """The commit the instrument ran at, and whether the tree had uncommitted changes."""
    git = shutil.which("git")
    if not git:
        return {"commit": "unknown", "dirty": None}

    def _git(*args: str) -> str:
        r = subprocess.run([git, "-C", str(_REPO), *args],  # noqa: S603
                           capture_output=True, text=True, check=False)
        return r.stdout.strip() if r.returncode == 0 else ""

    commit = _git("rev-parse", "HEAD") or "unknown"
    status = _git("status", "--porcelain", "--untracked-files=no")
    return {"commit": commit, "dirty": bool(status) if commit != "unknown" else None}


def _shingle_count(text: str, n_min: int, n_max: int) -> int:
    t = len(tokenize(text))
    return sum(max(0, t - n + 1) for n in range(n_min, n_max + 1))


def _bloom_section(fx: RunFixture, corpus: tuple[Payload, ...]) -> dict[str, Any]:
    b = fx.shingle.bloom
    p_shingle = b.estimated_fp_rate()
    counts = [_shingle_count(p.text, fx.n_min, fx.n_max) for p in corpus]
    # Per payload, with hit_threshold=1: P(at least one of S lookups collides).
    implied = [1 - (1 - p_shingle) ** s for s in counts]
    return {
        "n_min": fx.n_min, "n_max": fx.n_max, "hit_threshold": fx.hit_threshold,
        "target_fp_rate": SHINGLE_TARGET_FP,
        "n_added": b.n_added, "m_bits": b.m_bits, "k": b.k, "bits_set": b.bits_set,
        "estimated_fp_rate_per_shingle": p_shingle,
        "mean_shingles_per_payload": sum(counts) / len(counts) if counts else 0.0,
        "implied_fp_rate_per_payload": sum(implied) / len(implied) if implied else 0.0,
        "expected_refusals_on_corpus": sum(implied),
    }


def _corpus_section(corpus: tuple[Payload, ...], n: int) -> dict[str, Any]:
    total = 0
    distinct: set[tuple[str, ...]] = set()
    n_tokens = 0
    for p in corpus:
        toks = tokenize(p.text)
        n_tokens += len(toks)
        total += max(0, len(toks) - n + 1)
        distinct |= ngrams(toks, n)
    return {
        "n_payloads": len(corpus),
        "strata": dict(Counter(p.stratum for p in corpus)),
        "n_tokens": n_tokens,
        f"total_{n}grams": total,
        f"distinct_{n}grams": len(distinct),
        "sha256": corpus_fingerprint(corpus),
    }


# --------------------------------------------------------------------------- main


def _table(report: dict[str, Any]) -> str:
    rows = [
        f"{'linter':<16} {'stratum':<24} {'N':>5} {'refused':>8} {'rate':>8}  {'wilson 95%':<20}"
    ]
    for lr in report["linters"].values():
        lo, hi = lr["wilson95"]
        rows.append(
            f"{lr['name']:<16} {'ALL':<24} {lr['n']:>5} {lr['refusals']:>8} {lr['rate']:>8.4f}"
            f"  [{lo:.4f}, {hi:.4f}]"
        )
        for s, r in lr["by_stratum"].items():
            lo, hi = r["wilson95"]
            rows.append(
                f"{'':<16} {s:<24} {r['n']:>5} {r['refusals']:>8} {r['rate']:>8.4f}"
                f"  [{lo:.4f}, {hi:.4f}]"
            )
    for mode, dr in report["deployed_chain"]["modes"].items():
        label = f"deployed:{'reset' if mode == 'reset_per_payload' else 'session'}"
        for s, r in [("ALL", dr), *dr["by_stratum"].items()]:
            ci = ("[{:.4f}, {:.4f}]".format(*r["wilson95"]) if r["wilson95"]
                  else "n/a (correlated)")
            rows.append(f"{label if s == 'ALL' else '':<16} {s:<24} {r['n']:>5} "
                        f"{r['refusals']:>8} {r['rate']:>8.4f}  {ci}")
        if dr["rules_fired"]:
            rows.append(f"{'':<16} rules fired: {dr['rules_fired']}")
    b = report["shingle_filter"]
    rows.append("")
    rows.append(
        f"shingle bloom: {b['n_added']} shingles, {b['m_bits']} bits, k={b['k']}, "
        f"per-shingle fp~{b['estimated_fp_rate_per_shingle']:.2e}, "
        f"per-payload fp~{b['implied_fp_rate_per_payload']:.2e} "
        f"(expected refusals on this corpus: {b['expected_refusals_on_corpus']:.4f})"
    )
    pc = report["positive_control"]
    rows.append(f"positive control: {pc['caught']}/{pc['n_sentences']} private sentences caught "
                f"(rate {pc['catch_rate']:.3f})")
    dpc = report["deployed_chain"]["positive_control"]
    rows.append(f"positive control, deployed chain: {dpc['caught']}/{dpc['n_sentences']} "
                f"caught, by rule {dpc['rules_fired']}")
    g = report["git"]
    rows.append(f"commit {g['commit']}{' (dirty tree)' if g['dirty'] else ''}")
    rows.append(f"shared {report['disjointness']['n']}-grams private vs clean: "
                f"{report['disjointness']['shared']}")
    return "\n".join(rows)


def main(
    seed: int = DEFAULT_SEED,
    out: Path = Path("eval/fp_report.json"),
    *,
    n_per_stratum: int = N_PER_STRATUM,
    quiet: bool = False,
) -> dict[str, Any]:
    """Build the corpus and fixture, run every registered linter, write and return the report.

    A relative `out` resolves against the repository root, not the working
    directory, so the artifact lands in the same place whoever runs it.
    """
    corpus = build_corpus(seed, n_per_stratum)
    fx, doc = build_fixture(seed, corpus)

    shared = shared_ngrams(doc.text, corpus, fx.n_min)
    if shared:
        raise RuntimeError(
            f"{shared} {fx.n_min}-gram(s) shared between private doc and clean corpus"
        )
    control = positive_control(fx)
    if control.refusals != control.n:
        raise RuntimeError(
            f"positive control failed: {control.refusals}/{control.n} private sentences caught"
        )

    deployed = deployed_chain(fx, corpus)
    dpc = deployed["positive_control"]
    if dpc["caught"] != dpc["n_sentences"]:
        raise RuntimeError(
            f"positive control failed through the deployed chain: "
            f"{dpc['caught']}/{dpc['n_sentences']} private sentences caught"
        )

    reports = run_registry(fx, corpus)
    report: dict[str, Any] = {
        "instrument": "scripts/measure_false_positives.py",
        "git": git_provenance(),
        "seed": seed,
        "n_per_stratum": n_per_stratum,
        "entropy_threshold": fx.entropy_threshold,
        "corpus": _corpus_section(corpus, fx.n_min),
        "private_doc": {
            "n_words": doc.n_words,
            "n_sentences": len(doc.sentences),
            "rejected_fills": doc.rejected_fills,
            "n_shingles_indexed": fx.shingle.bloom.n_added,
        },
        "disjointness": {"n": fx.n_min, "shared": shared},
        "shingle_filter": _bloom_section(fx, corpus),
        # Standalone: each linter called alone on the raw payload text. Kept for
        # comparison with `deployed_chain`, which is what actually runs.
        "linters": {r.name: r.to_dict() for r in reports},
        "deployed_chain": deployed,
        "positive_control": {
            "n_sentences": control.n, "caught": control.refusals, "catch_rate": control.rate,
        },
    }
    out_path = out if out.is_absolute() else _REPO / out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not quiet:
        print(_table(report))
        print(f"\nwrote {out_path}")
    return report



# The regex screen is stateless; registered here so the report covers the full chain.
REGISTRY.append(("regex", lambda _fx: RegexScreen().scan))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", type=Path, default=Path("eval/fp_report.json"))
    ap.add_argument("--n-per-stratum", type=int, default=N_PER_STRATUM)
    args = ap.parse_args()
    main(args.seed, args.out, n_per_stratum=args.n_per_stratum)
