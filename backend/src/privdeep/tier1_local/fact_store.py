"""R1's local fact ledger: (referent, attribute) -> value, built from table cells.

The cloud refers to ``⟦FACT:<referent hex8>.<ATTR>⟧``; this store is what answers.
It lives inside the partition with the same posture as ``LocalMappingTable``: no
serialisation method, and a ``repr`` that prints counts only.

Structural extraction only
--------------------------
Facts come from table cells and no model reads them: the header of a cell is
the cell in the first row of its column, the key of a row is the cell in the
first column. Verified on the post-fix smoke corpus -- ``budget.xlsx`` and the
table in ``board-minutes.docx`` both bind Project Zephyr's authority and spend
this way. Prose-extracted facts are deferred: that route runs the extractor this
repository already knows to be unreliable, and the structural route alone
addresses the measured figure-to-project failure. Consequence, stated: a value
that appears only in prose (a revenue fall, a unit shortfall written inside a
risk description) has no fact and cannot be referred to.

A row binds only if its key is a surface of a referent the session table already
issued. A key the extractor never masked is dropped and counted, never promoted
into a referent here, so which facts exist depends on the SLM's recall.

Agreement, conflict, and why nothing is guessed
-----------------------------------------------
Two sources for one (referent, attribute) agree when their R5 canonical keys are
equal -- ``250000`` in the sheet and ``250,000.00`` in the minutes are one value,
and both spellings are kept for rendering. When the keys differ the fact is
**withheld** and ``fact_conflicts`` counts it. The design proposed a precedence
rule (prefer the source that round-trips through Decimal without loss); its own
example was the xlsx loader's truncated ``187433``, which no longer exists, and a
precedence rule is a way of choosing a number the documents do not agree on.

Derivations
-----------
A fixed rule table, same referent, compatible units, structural operands only:
``UNSPNTAM = AUTHAMT - SPENTAMT`` (when not negative), ``OVRRUNAM = SPENTAMT -
AUTHAMT`` (when positive), ``PCTSPENT = SPENTAMT / AUTHAMT``. The cloud cannot
request one or supply an operand. A derived amount is rendered in the style its
operands were observed in (thousands separator, decimal places), so
``250,000.00 - 187,432.55`` renders ``62,567.45`` -- the figure three documents
state verbatim -- rather than a spelling the store invented. ``120,000.00 -
98,210.00 = 21,790.00`` appears in no document and is marked derived.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from privdeep.models.document import Document
from privdeep.models.facts import REFERENT_CATEGORIES, VALUE_KIND
from privdeep.tier1_local.header_lexicon import attribute_for_header, unit_for_header
from privdeep.tier1_local.normalise import canonical_key, canonical_rendering
from privdeep.tier1_local.slot_masker import SLOT_RE, LocalMappingTable, SlotCollisionError

__all__ = ["Fact", "LocalFactStore", "Provenance", "build_fact_store"]

_KEY_CATEGORY = {"money": "MONEY", "quantity": "QUANTITY", "date": "DATE", "code": "IDENTIFIER",
                 "person": "PERSON", "location": "LOCATION", "note": "PROJECT", "ratio": "QUANTITY"}


@dataclass(frozen=True, slots=True)
class Provenance:
    doc_id: str
    sheet: str
    row: int
    col: int


@dataclass(frozen=True)
class Fact:
    """One resolved value. Values are excluded from ``repr``: a Fact in a log line
    is C_user in a log line."""

    referent: str                      # the referent's slot id
    attribute: str
    value_key: str = field(repr=False)
    surfaces: dict[str, int] = field(repr=False)
    unit: str | None
    provenance: tuple[Provenance, ...] = field(repr=False)
    derived: bool = False

    def rendering(self) -> str:
        return canonical_rendering(self.surfaces)


class LocalFactStore:
    __slots__ = ("_facts", "_hex_to_slot", "counters")

    def __init__(self) -> None:
        self._facts: dict[tuple[str, str], Fact] = {}
        self._hex_to_slot: dict[str, str] = {}
        self.counters: dict[str, int] = defaultdict(int)

    def _bind_hex(self, slot_id: str) -> str:
        """FACT tokens carry the hex without the category, so the hex alone must
        name one referent. Slot ids are HMAC over category and key and the table
        refuses a clash only when category *and* hex coincide; a PERSON and a
        PROJECT sharing hex8 would make one entity's value appear under the
        other's name. Refused here, and the pipeline re-salts."""
        m = SLOT_RE.fullmatch(slot_id)
        assert m is not None
        hx = m.group("hex")
        held = self._hex_to_slot.setdefault(hx, slot_id)
        if held != slot_id:
            raise SlotCollisionError(
                f"referents {held} and {slot_id} share hex {hx}; a FACT token could not "
                "tell them apart. Re-mask under a fresh session salt")
        return hx

    def get(self, referent_hex: str, attribute: str) -> Fact | None:
        slot = self._hex_to_slot.get(referent_hex)
        return None if slot is None else self._facts.get((slot, attribute))

    def referent_for_hex(self, referent_hex: str) -> str | None:
        return self._hex_to_slot.get(referent_hex)

    def facts(self) -> list[Fact]:
        return list(self._facts.values())

    def __len__(self) -> int:
        return len(self._facts)

    def __repr__(self) -> str:
        derived = sum(f.derived for f in self._facts.values())
        return (f"LocalFactStore(facts={len(self._facts)}, derived={derived}, "
                f"referents={len(self._hex_to_slot)})")


def _referent_surfaces(table: LocalMappingTable) -> dict[str, str]:
    out: dict[str, str] = {}
    for sid in table:
        m = SLOT_RE.fullmatch(sid)
        if m and m.group("category") in REFERENT_CATEGORIES:
            for s in table.surfaces(sid):
                out.setdefault(s, sid)
    return out


def _decimal(key: str) -> Decimal | None:
    try:
        return Decimal(key)
    except (InvalidOperation, ValueError):
        return None


def _render_like(value: Decimal, *styles: str) -> str:
    """Render a derived amount in the style its operands were written in.

    Decimal places are the most any operand spelling uses, and never fewer than
    the value itself needs. Taking them from the authority alone rounded
    ``250000 - 187432.55`` to ``62567``: a wrong figure in the report, hidden on
    the smoke corpus only because the minutes also spell ``250,000.00``.
    """
    places = max((len(s.rsplit(".", 1)[1]) for s in styles if "." in s), default=0)
    exponent = value.normalize().as_tuple().exponent
    if isinstance(exponent, int) and exponent < 0:
        places = max(places, -exponent)
    q = value.quantize(Decimal(1).scaleb(-places))
    return f"{q:,.{places}f}" if any("," in s for s in styles) else f"{q:.{places}f}"


def build_fact_store(docs: Sequence[Document], table: LocalMappingTable) -> LocalFactStore:
    store = LocalFactStore()
    keys = _referent_surfaces(table)
    # Every issued referent is bound, not only those that end up with a fact. A
    # reference to a real referent with nothing recorded must resolve as
    # unavailable; if only referents with facts were bound it would be
    # indistinguishable from an invented reference and refuse the section. It
    # also makes the cross-category hex check cover every referent.
    for sid in sorted(set(keys.values())):
        store._bind_hex(sid)
    obs: dict[tuple[str, str], list[tuple[str, str, str | None, Provenance]]] = defaultdict(list)

    for doc in docs:
        sheets: dict[str, dict[tuple[int, int], str]] = defaultdict(dict)
        for c in doc.cells:
            sheets[c.sheet][(c.row, c.col)] = c.value
        for sheet, grid in sheets.items():
            head_row = min(r for r, _ in grid)
            key_col = min(c for _, c in grid)
            headers = {c: v for (r, c), v in grid.items() if r == head_row and c != key_col}
            attrs = {c: attribute_for_header(h) for c, h in headers.items()}
            units = {c: unit_for_header(h) for c, h in headers.items()}
            store.counters["fact_dropped_unknown_header"] += sum(a is None for a in attrs.values())
            for row in sorted({r for r, _ in grid if r != head_row}):
                key = grid.get((row, key_col), "").strip()
                referent = keys.get(key)
                if referent is None:
                    store.counters["fact_dropped_no_referent"] += 1
                    continue
                for col, attr in attrs.items():
                    raw = grid.get((row, col), "").strip()
                    if attr is None or not raw:
                        continue
                    vk = canonical_key(_KEY_CATEGORY[VALUE_KIND[attr]], raw)
                    obs[(referent, attr)].append((vk, raw, units[col],
                                                  Provenance(doc.doc_id, sheet, row, col)))

    for (referent, attr), rows in obs.items():
        value_keys = {vk for vk, *_ in rows}
        explicit_units = {u for *_, u, _p in rows if u}
        if len(value_keys) > 1 or len(explicit_units) > 1:
            store.counters["fact_conflicts"] += 1
            continue
        surfaces: dict[str, int] = {}
        for _vk, raw, _u, _p in rows:
            surfaces[raw] = surfaces.get(raw, 0) + 1
        store._facts[(referent, attr)] = Fact(
            referent, attr, value_keys.pop(), surfaces,
            explicit_units.pop() if explicit_units else None,
            tuple(p for *_, p in rows))
        store.counters["facts_structural"] += 1

    for referent in sorted({r for r, _ in store._facts}):
        _derive(store, referent)
    return store


def _derive(store: LocalFactStore, referent: str) -> None:
    auth = store._facts.get((referent, "AUTHAMT"))
    spent = store._facts.get((referent, "SPENTAMT"))
    if auth is None or spent is None:
        return
    if auth.unit and spent.unit and auth.unit != spent.unit:
        store.counters["derivation_unit_mismatch"] += 1
        return
    a, s = _decimal(auth.value_key), _decimal(spent.value_key)
    if a is None or s is None:
        return
    unit = auth.unit or spent.unit
    prov = auth.provenance + spent.provenance
    styles = (auth.rendering(), spent.rendering())
    candidates: dict[str, tuple[Decimal, str]] = {}
    if a - s >= 0:
        candidates["UNSPNTAM"] = (a - s, _render_like(a - s, *styles))
    if s - a > 0:
        candidates["OVRRUNAM"] = (s - a, _render_like(s - a, *styles))
    if a > 0:
        pct = (s / a * 100).quantize(Decimal("0.1"))
        candidates["PCTSPENT"] = (pct, f"{pct}%")
    for attr, (value, text) in candidates.items():
        if (referent, attr) in store._facts:
            # Never overwrite something a document states; a disagreement with
            # the arithmetic is itself a conflict.
            if _decimal(store._facts[(referent, attr)].value_key) != value.normalize():
                store.counters["fact_conflicts"] += 1
                del store._facts[(referent, attr)]
            continue
        store._facts[(referent, attr)] = Fact(referent, attr, format(value.normalize(), "f"),
                                              {text: 1}, unit if attr != "PCTSPENT" else None,
                                              prov, derived=True)
        store.counters["facts_derived"] += 1
