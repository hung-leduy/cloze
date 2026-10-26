"""Turn a fetched web page into a citable evidence unit, confined on the way in.

Order matters and is fixed here so no caller can get it wrong:

    HTML -> purify (strip scripts, invisibles, collapse) -> neutralise
         (defang injection patterns, when a guard is supplied) -> bank

The bank hashes the purified, neutralised text, so a citation resolves to
the exact bytes the model could have been shown. The envelope is applied at
prompt time, by `enveloped`, because it carries the unit's id and the id is
the hash of the text; wrapping first would make the id depend on itself.

The summary the drafter sees is provisional: the page title and its opening
sentence(s). It is public text, so showing it to the cloud leaks nothing,
and a later pass may replace it with a model-written claim.

Nothing here fetches. Retrieval is a separate, currently unbuilt concern;
this module is what it will feed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from privdeep.tier3_reconcile.evidence_bank import EvidenceBank, EvidenceUnit

__all__ = ["default_guard", "enveloped", "ingest_page"]

# Sentinel: None means "do not neutralise", which is different from "default".
_DEFAULT = object()

_SENT_END = re.compile(r"(?<=[.!?])\s")


def _purify_and_envelope():
    # Imported lazily: the sanitizer lives in the gateway package, which the
    # core container does not mount, so only the tests reach it (pyproject's
    # pythonpath). No live path calls this module; a miss fails at first use.
    from sanitizer.html_purifier import envelope, purify
    return purify, envelope


def default_guard():
    """The injection guard, as a neutralise callable. Used unless overridden."""
    from sanitizer.injection_guard import InjectionGuard
    return InjectionGuard().neutralise


def ingest_page(
    bank: EvidenceBank,
    url: str,
    html: str | bytes,
    *,
    neutralise: Callable[[str], tuple[str, Any]] | None = _DEFAULT,
    max_chars: int = 20_000,
    summary_chars: int = 300,
) -> tuple[EvidenceUnit, dict[str, Any]]:
    """Purify, optionally neutralise, and bank one page. Returns (unit, provenance)."""
    # Defanging is on by default: a page reaching the bank unneutralised is
    # a page whose injection payloads are intact in a prompt.
    if neutralise is _DEFAULT:
        neutralise = default_guard()
    purify, _ = _purify_and_envelope()
    page = purify(html, url, max_chars=max_chars)
    text = page.text
    prov: dict[str, Any] = {"url": page.url, "title": page.title, "truncated": page.truncated,
                            "stripped": dict(page.stripped), "neutralised": None}
    if neutralise is not None:
        text, verdict = neutralise(text)
        findings = getattr(verdict, "findings", ())
        prov["neutralised"] = {"flagged": bool(getattr(verdict, "flagged", False)),
                               "findings": [(getattr(f, "rule", "?"), getattr(f, "count", 0))
                                            for f in findings]}
    head = _SENT_END.split(text.strip(), maxsplit=2)
    opening = " ".join(head[:2]).strip()
    summary = (f"{page.title}: " if page.title else "") + opening
    summary = summary[:summary_chars].rstrip()
    unit = bank.add(page.url, text, summary or page.title or url, kind="WEB")
    return unit, prov


def enveloped(unit: EvidenceUnit) -> str:
    """The unit's full text wrapped for a prompt, with unforgeable delimiters."""
    from sanitizer.html_purifier import PurifiedPage, envelope
    page = PurifiedPage(text=unit.raw_snippet, title="", url=unit.source_url, truncated=False,
                        stripped={})
    return envelope(page, unit.evidence_id)
