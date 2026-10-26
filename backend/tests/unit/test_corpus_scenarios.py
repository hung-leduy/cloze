"""The scenario corpora (plan task EXP1), pinned before and after the refactor.

Scenario A is the corpus every pilot run was made on, so its documents are a
fixed point: the digests below were computed from ``scripts/make_smoke_corpus.py``
as it stood at b06ed46, into a scratch directory, before the generator was
split into scenario modules. They are also the digests of the user mount
``corpus/`` that the nine pilot runs read. ``content_doc_id`` is a SHA-256 over
file bytes and every run manifest records it, so a refactor that changed one
byte would silently rename every document the pilot measured.

The key is pinned separately and to a later commit: INS1 changed the key's mask
patterns (and so its bytes) without touching a document, and the blind
labelling sheets in ``eval/calibration/blind/`` were exported against the INS1
key, whose sha256 their README quotes.

B, C and D have no pin yet: their keys are provisional until the author audits
them. What is checked instead is that each scenario is internally complete
(every numeral and every cell it writes is a surface, and every numeral is in
its key), that the committed copies under ``eval/corpora/`` are what the
generator writes, and the structural-fact counts R1's route gets from each,
against the facts each corpus's tables state (H4-D's premise, for D).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "scripts"))

import corpora  # noqa: E402
import make_smoke_corpus as M  # noqa: E402
from corpora import offlex_d, portfolio_b, prose_c, smoke_q3  # noqa: E402
from corpora import writers as W  # noqa: E402
from privdeep.eval.faithfulness import FABRICATED, load_key, score  # noqa: E402
from privdeep.ingest import SUFFIXES, load  # noqa: E402
from privdeep.tier1_local.fact_store import build_fact_store  # noqa: E402
from privdeep.tier1_local.header_lexicon import attribute_for_header  # noqa: E402
from privdeep.tier1_local.slot_masker import SLOT_RE, Entity, LocalMappingTable  # noqa: E402

COMMITTED = _REPO / "eval" / "corpora"
SCENARIOS = list(corpora.SCENARIOS.values())
_IDS = [m.ID for m in SCENARIOS]
PROVISIONAL = [m for m in SCENARIOS if corpora.is_provisional(m)]

# sha256 of each scenario-A document as the b06ed46 generator writes it.
A_DOCUMENT_SHA256 = {
    "board-minutes.docx": "3ce9713b72f4225d7e804f3be4362d398955e714d5fb195e801e69ba684dff30",
    "budget.xlsx": "ea67494b39c02d45b272f11de515407144d24972dcd0134bb49fd6385e0b6ab1",
    "quarterly-review.pdf": "08dcf85ad1218a0ef108333588ca321692c4fff709e96521dcd2d2aefb69c290",
    "steering-memo.md": "cfcbe635c6f3becfba660e36dbff3c030a80b55d6be51bc814c7b3ec2997b342",
}
# sha256 of scenario A's gold key as the generator writes it after EXP2's one-time
# fix of the RBA attribute lexicon (eval/calibration/EXP2.md); the pre-fix key
# (dc1ff408..., INS1, ecae9dd) is kept in eval/calibration/prefix_keys/smoke-q3.json.
A_KEY_SHA256 = "dcda133acba9478d5f9059761340fc3bdcf0e9e734a870080d3fab4840663780"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def wrapper_out(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("smoke-wrapper")
    M.main(["--out", str(out)])
    return out


@pytest.fixture(scope="module")
def generated(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("scenarios")
    corpora.main(["--scenario", "all", "--out", str(out)])
    return out


class TestScenarioAIsByteIdentical:
    @pytest.mark.parametrize("name", sorted(A_DOCUMENT_SHA256))
    def test_the_wrapper_reproduces_every_document(self, wrapper_out, name):
        assert _sha(wrapper_out / name) == A_DOCUMENT_SHA256[name], name

    def test_the_wrapper_writes_the_ins1_key(self, wrapper_out):
        assert _sha(wrapper_out / "smoke_fact_key.json") == A_KEY_SHA256

    def test_the_scenario_module_writes_the_same_bytes(self, generated):
        out = generated / smoke_q3.ID
        for name, digest in A_DOCUMENT_SHA256.items():
            assert _sha(out / name) == digest, name
        assert _sha(out / W.FACT_KEY_NAME) == A_KEY_SHA256

    def test_the_wrapper_keeps_the_names_its_callers_import(self):
        """calibrate_faithfulness.py and three test modules import these from
        make_smoke_corpus, two of them by file path rather than by name."""
        for name in ("fact_key", "write_fact_key", "write_xlsx", "write_docx",
                     "write_markdown", "write_pdf", "PDF_PAGES", "PROJECT", "LEAD",
                     "CONTRACT", "SITE2", "ORG", "SITE", "ATTRIBUTES", "MASK_PATTERNS"):
            assert hasattr(M, name), name
        assert M.fact_key() == smoke_q3.fact_key()


# --------------------------------------------------------------- all three

def _docs(corpus: Path) -> list:
    return [load(p) for p in sorted(corpus.iterdir()) if p.suffix.lower() in SUFFIXES]


# Loader-added structure ("## sheet: Budget", "## table: 1"), not document text.
_MARKER = re.compile(r"^## (?:sheet|table): .*$", re.MULTILINE)


def _text(corpus: Path) -> str:
    return _MARKER.sub("", "\n\n".join(d.text for d in _docs(corpus)))


@pytest.mark.parametrize("mod", SCENARIOS, ids=_IDS)
class TestEveryScenario:
    def test_regenerating_produces_identical_bytes(self, mod, generated, tmp_path):
        """`content_doc_id` is a SHA-256 over file bytes, recorded in every
        manifest; a second generation must not rename anything."""
        again = tmp_path / mod.ID
        corpora.generate(mod, again)
        for p in sorted((generated / mod.ID).iterdir()):
            assert p.read_bytes() == (again / p.name).read_bytes(), p.name

    def test_the_committed_corpus_is_what_the_generator_writes(self, mod, generated):
        """eval/corpora/<id>/ is tracked so a run names its corpus by commit; it
        must not drift from the constants its key is authored beside."""
        fresh = sorted(p.name for p in (generated / mod.ID).iterdir())
        assert sorted(p.name for p in (COMMITTED / mod.ID).iterdir()) == fresh
        for name in fresh:
            assert _sha(COMMITTED / mod.ID / name) == _sha(generated / mod.ID / name), name

    def test_every_format_loads_and_the_key_is_not_a_document(self, mod, generated):
        corpus = generated / mod.ID
        assert {d.kind.name for d in _docs(corpus)} == {"XLSX", "MARKDOWN", "DOCX", "PDF"}
        assert set(mod.DOCUMENTS) == {p.name for p in corpus.iterdir()
                                      if p.suffix.lower() in SUFFIXES}
        assert Path(W.FACT_KEY_NAME).suffix not in SUFFIXES
        assert Path(W.SURFACES_NAME).suffix not in SUFFIXES

    def test_the_corpus_directory_holds_its_surfaces(self, mod, generated):
        """X4(a) scans from a run's recorded corpus path, so the surfaces sit
        beside the documents rather than only behind an import of scripts/."""
        written = json.loads((generated / mod.ID / W.SURFACES_NAME).read_text(encoding="utf-8"))
        assert written["scenario"] == mod.ID
        assert written["groups"] == mod.surface_groups()
        assert written["surfaces"] == mod.surfaces()

    def test_the_key_loads_and_every_numeric_value_names_one_fact(self, mod, generated):
        key = load_key(generated / mod.ID / W.FACT_KEY_NAME)
        key.lexicon_regex()     # raises if two attributes claim one phrase
        for value in key.by_value:
            facts = {f["fact_id"] for f in key.facts
                     if f["match"] == "numeric" and round(float(f["value"]), 2) == value}
            assert len(facts) == 1, (value, facts)

    def test_no_referent_surface_is_three_characters_or_shorter(self, mod):
        """A short name matches inside ordinary words, in the RBA referent
        binding and in the surface scan alike."""
        assert not [s for v in mod.REFERENTS.values() for s in v if len(s) <= 3]

    def test_the_goal_contains_no_generator_surface(self, mod):
        """The goal crosses the boundary verbatim, as the user's own words."""
        low = mod.GOAL.casefold()
        assert not [s for s in mod.surfaces()
                    if re.search(r"(?<!\w)" + re.escape(s.casefold()) + r"(?!\w)", low)]

    def test_every_written_surface_occurs_in_the_documents(self, mod, generated):
        text = _text(generated / mod.ID)
        groups = mod.surface_groups()
        for group in ("referents", "people", "sites", "identifiers", "quantities",
                      "percentages", "risk_text", "labels"):
            for s in groups[group]:
                assert s in text, (group, s)

    def test_every_cell_value_is_a_surface(self, mod, generated):
        """Completeness for tables: every non-header cell, in the workbook and
        in any docx table, is something surfaces() lists."""
        surfaces = set(mod.surfaces())
        for doc in _docs(generated / mod.ID):
            for c in doc.cells:
                if c.row > 1:
                    assert c.value in surfaces, (doc.source_path, c.sheet, c.row, c.col)

    def test_every_numeral_in_the_documents_lies_inside_a_surface(self, mod, generated):
        """Completeness for prose: no digit is written that the surface scan
        would not know about. Quarter labels are the one exception, because
        A's goal says Q3."""
        text = re.sub(r"\bQ[1-4]\b", "  ", _text(generated / mod.ID))
        covered = [False] * len(text)
        for s in mod.surfaces():
            for m in re.finditer(re.escape(s), text):
                covered[m.start():m.end()] = [True] * (m.end() - m.start())
        assert not [m.group(0) for m in re.finditer(r"\d+", text)
                    if not all(covered[m.start():m.end()])]

    def test_every_numeral_the_documents_write_is_in_the_key(self, mod, generated):
        """The metric itself, run on the corpus: a numeral that no key fact
        owns and no mask covers would be charged to every report repeating it,
        and every fact the key calls stated is found stated."""
        key = load_key(generated / mod.ID / W.FACT_KEY_NAME)
        res = score(_text(generated / mod.ID), key)
        assert not [o.surface for o in res.occurrences if o.verdict == FABRICATED]
        assert res.coverage_stated == 1.0


# ------------------------------------------------------------ B, C and D

def _stated(value: float, text: str) -> bool:
    return any(re.search(r"(?<![\d.,])" + re.escape(s) + r"(?![\d]|[.,]\d)", text)
               for s in W.money_surfaces(float(value)))


@pytest.mark.parametrize("mod", PROVISIONAL, ids=[m.ID for m in PROVISIONAL])
class TestProvisionalKeys:
    def test_derived_means_no_document_states_it(self, mod, generated):
        """coverage_stated reads `derived` as "not stated"; in B, C and D that is
        exactly what it is. (A marks Zephyr's stated balance derived; frozen.)"""
        text = _text(generated / mod.ID)
        for f in mod.fact_key()["facts"]:
            if f["match"] == "numeric":
                assert _stated(f["value"], text) is (not f["derived"]), f["fact_id"]

    def test_the_key_is_marked_provisional(self, mod):
        assert corpora.is_provisional(mod)
        assert not corpora.is_provisional(smoke_q3)
        assert PROVISIONAL == [portfolio_b, prose_c, offlex_d]

    def test_the_audit_sheet_logs_the_current_key_sha(self, mod, generated):
        """KEY_AUDIT.md is what the author audits; a key that changed since it
        was written must fail here rather than be audited stale."""
        audit = (COMMITTED / "KEY_AUDIT.md").read_text(encoding="utf-8")
        assert _sha(generated / mod.ID / W.FACT_KEY_NAME) in audit
        assert f"## {mod.ID} " in audit and f"## {smoke_q3.ID} " not in audit
        for f in [*mod.fact_key()["facts"], *mod.fact_key()["string_facts"]]:
            assert f"| {f['fact_id']}" in audit, f["fact_id"]

    def test_the_audit_sheet_is_what_the_generator_writes(self, mod, generated):
        """Up to the Audited column, which is the author's to fill."""
        from corpora.audit import audit_markdown, strip_marks

        fresh = audit_markdown(PROVISIONAL, generated)
        committed = (COMMITTED / "KEY_AUDIT.md").read_text(encoding="utf-8")
        assert strip_marks(committed) == fresh


@pytest.fixture(scope="module")
def fresh(generated) -> str:
    """KEY_AUDIT.md as the generator writes it, every Audited cell blank."""
    from corpora.audit import audit_markdown

    return audit_markdown(PROVISIONAL, generated)


class TestAuditMarks:
    """The author's verdicts survive regeneration; the generator's rows do not
    need them to match."""

    @staticmethod
    def _mark_every_row(text: str) -> str:
        from corpora.audit import _rows

        lines = text.split("\n")
        for i, _, head, _ in _rows(text):
            lines[i] = f"{head} ok, LDH |"
        return "\n".join(lines)

    def test_the_generator_leaves_every_mark_blank(self, fresh):
        from corpora.audit import _rows, strip_marks

        rows = list(_rows(fresh))
        assert len(rows) > 50 and not any(mark for *_, mark in rows)
        assert strip_marks(fresh) == fresh

    def test_only_the_audited_column_is_stripped(self, fresh):
        from corpora.audit import strip_marks

        marked = self._mark_every_row(fresh)
        assert marked != fresh and strip_marks(marked) == fresh
        # The document-digest tables have no Audited column and keep their SHAs.
        for line in fresh.split("\n"):
            if re.fullmatch(r"\| `[\w.-]+` \| `[0-9a-f]{64}` \|", line):
                assert line in marked

    def test_regenerating_keeps_the_marks_of_unchanged_rows(self, fresh):
        from corpora.audit import carry_marks

        marked = self._mark_every_row(fresh)
        assert carry_marks(fresh, marked) == (marked, [])

    def test_a_changed_row_loses_its_mark_and_says_so(self, fresh):
        from corpora.audit import carry_marks

        marked = self._mark_every_row(fresh)
        changed = fresh.replace("| HALCYON.SPENT | 296418.2 |", "| HALCYON.SPENT | 296418.3 |")
        assert changed != fresh
        merged, dropped = carry_marks(changed, marked)
        assert "| HALCYON.SPENT | 296418.3 |" in merged
        assert all(line.endswith("| |") for line in merged.split("\n")
                   if line.startswith("| HALCYON.SPENT | 296418.3 |"))
        assert dropped and all("HALCYON.SPENT | 296418.2" in d for d in dropped)
        assert merged.count("ok, LDH") == marked.count("ok, LDH") - len(dropped)

    def test_audit_refuses_a_subset_of_the_provisional_scenarios(self, tmp_path, capsys):
        """A partial --audit would drop the other sections and their marks."""
        for scenario in corpora.SCENARIOS:
            with pytest.raises(SystemExit) as exc:
                corpora.main(["--scenario", scenario, "--out", str(tmp_path), "--audit"])
            assert exc.value.code == 2
        assert "--scenario all" in capsys.readouterr().err
        assert not list(tmp_path.iterdir())

    def test_audit_all_carries_the_committed_marks(self, tmp_path, fresh):
        (tmp_path / "KEY_AUDIT.md").write_text(self._mark_every_row(fresh), encoding="utf-8")
        corpora.main(["--scenario", "all", "--out", str(tmp_path), "--audit"])
        assert (tmp_path / "KEY_AUDIT.md").read_text(encoding="utf-8") \
            == self._mark_every_row(fresh)

    def test_adding_d_keeps_the_marks_of_b_and_c(self, generated, fresh):
        """D's section was added to a sheet the author may already have marked
        for B and C; every one of those marks must carry over, and D's rows
        start blank."""
        from corpora.audit import _rows, audit_markdown, carry_marks

        before = self._mark_every_row(audit_markdown([portfolio_b, prose_c], generated))
        merged, dropped = carry_marks(fresh, before)
        assert dropped == []
        assert merged.count("ok, LDH") == before.count("ok, LDH") > 50
        for _, (section, *_), _, mark in _rows(merged):
            assert bool(mark) is (not section.startswith(f"## {offlex_d.ID} ")), section


# ------------------------------------------------- R1's structural route

def _store(mod, docs):
    table = LocalMappingTable(b"corpus-scenarios-salt")
    for k, surfaces in mod.REFERENTS.items():
        if k not in ("VENDOR", "ORG"):
            table.slot_for(Entity(surfaces[0], "PROJECT"))
    return build_fact_store(docs, table), table


def _get(store_table, mod, subject, code):
    store, table = store_table
    sid = table.slot_for(Entity(mod.REFERENTS[subject][0], "PROJECT"))
    fact = store.get(SLOT_RE.fullmatch(sid).group("hex"), code)
    return None if fact is None else float(fact.value_key)


def _column_attribute(mod, header: str) -> str:
    """What a table column states: D's authored code for its budget columns,
    else the header_lexicon code, else the header itself (a risk-register
    column, which no scenario's lexicon maps)."""
    return (getattr(mod, "TABLE_ATTRIBUTES", {}).get(header)
            or attribute_for_header(header) or f"header:{header.casefold()}")


def _table_facts(mod, docs) -> set[tuple[str, str]]:
    """Total table facts: the distinct (referent, attribute) pairs stated by a
    non-empty, non-key cell in a row keyed by a referent, over every table in
    the corpus. Distinct pairs, as ``facts_structural`` counts them, so a value
    restated in the minutes' table is one fact, whatever its header there."""
    subject = {s: k for k, v in mod.REFERENTS.items() for s in v}
    out: set[tuple[str, str]] = set()
    for doc in docs:
        grid = {(c.sheet, c.row, c.col): c.value for c in doc.cells}
        for (sheet, row, col), value in grid.items():
            key = subject.get(grid.get((sheet, row, 1), "").strip())
            if row > 1 and col > 1 and value.strip() and key is not None:
                out.add((key, _column_attribute(mod, grid[(sheet, 1, col)])))
    return out


def _structural(mod, store, table) -> set[tuple[str, str]]:
    subject = {table.slot_for(Entity(v[0], "PROJECT")): k for k, v in mod.REFERENTS.items()
               if k not in ("VENDOR", "ORG")}
    return {(subject[f.referent], f.attribute) for f in store.facts() if not f.derived}


class TestStructuralFacts:
    """facts_structural per corpus, from the real header_lexicon and fact_store.
    X1 reports it against total table facts; these are the pre-freeze counts.

    Counts given a perfect extraction: ``_store`` registers every referent as a
    PROJECT entity before building the store, so B's 24 is what the route yields
    when the extractor finds all four projects. A live run's count also depends
    on the extractor recognising them, and is not to be quoted as this one."""

    def test_b_headers_are_lexicon_synonyms_other_than_as(self):
        codes = [attribute_for_header(h) for h in portfolio_b.BUDGET_HEADER[1:]]
        assert None not in codes and len(set(codes)) == len(codes) == 6
        assert portfolio_b.BUDGET_HEADER[0] == "Project"
        a_header = smoke_q3.xlsx_sheets()[0][1][0]
        assert set(portfolio_b.BUDGET_HEADER) & set(a_header) == {"Project"}
        assert codes != [attribute_for_header(h) for h in a_header[1:]]   # reordered
        table = next(b for b in portfolio_b.docx_blocks() if b[0] == "table")
        assert [attribute_for_header(h) for h in table[1][1:]] == ["AUTHAMT", "SPENTAMT"]
        assert not any("committed" in h.casefold()
                       for h in [*portfolio_b.BUDGET_HEADER, *table[1]])

    def test_b_workbook_yields_every_budget_cell_as_a_fact(self, generated):
        docs = [d for d in _docs(generated / portfolio_b.ID) if d.kind.name == "XLSX"]
        store, _ = _store(portfolio_b, docs)
        assert store.counters["facts_structural"] == len(portfolio_b.BUDGET_ROWS) * 6 == 24
        assert store.counters["fact_conflicts"] == 0
        assert store.counters["fact_dropped_no_referent"] == 0
        # The risk register's four non-key headers map to nothing, as A's do.
        assert store.counters["fact_dropped_unknown_header"] == 4

    def test_b_minutes_table_agrees_with_the_workbook(self, generated):
        store, _ = _store(portfolio_b, _docs(generated / portfolio_b.ID))
        assert store.counters["facts_structural"] == 24
        assert store.counters["fact_conflicts"] == 0

    def test_a_count_for_comparison(self, generated):
        docs = [d for d in _docs(generated / smoke_q3.ID) if d.kind.name == "XLSX"]
        assert _store(smoke_q3, docs)[0].counters["facts_structural"] == 18

    def test_c_has_no_structural_route(self, generated):
        """H2's premise, checked rather than assumed: every C figure is prose."""
        store, _ = _store(prose_c, _docs(generated / prose_c.ID))
        assert store.counters["facts_structural"] == 0
        assert len(store) == 0

    @pytest.mark.parametrize("mod", [smoke_q3, portfolio_b], ids=["smoke-q3", "portfolio-b"])
    def test_the_key_arithmetic_is_the_stores_arithmetic(self, mod, generated):
        """The key's authorities, spends, balances and percentages equal what
        R1's store reads and derives from the same cells, so a correct r1 report
        cannot be scored wrong by a rounding disagreement between the two."""
        st = _store(mod, _docs(generated / mod.ID))
        codes = {"AUTHORISED": "AUTHAMT", "SPENT": "SPENTAMT", "UNSPENT": "UNSPNTAM",
                 "OVERRUN": "OVRRUNAM", "PCT_SPENT": "PCTSPENT"}
        checked = [f for f in mod.fact_key()["facts"] if f["attribute"] in codes]
        for f in checked:
            assert _get(st, mod, f["subject"], codes[f["attribute"]]) == f["value"], f["fact_id"]
        assert len(checked) == 4 * (len(mod.REFERENTS) - 2)

    # ------------------------------------------------------------------ D

    _CODES = {"AUTHAMT", "SPENTAMT", "OWNERREF", "SITEREF", "REFCODE", "DATESTRT"}
    _NUMERIC = {"AUTHAMT", "SPENTAMT", "DATESTRT"}

    def test_d_headers_are_half_off_the_lexicon(self):
        """Every budget column's header either maps to the code the column
        carries or maps to nothing; each sheet maps three of its six; the
        numeric columns split four and four; and every code is stated under
        a mapped header and under an unmapped one."""
        sheets = {name: rows[0] for name, rows in offlex_d.xlsx_sheets()}
        table = next(b for b in offlex_d.docx_blocks() if b[0] == "table")
        budget = [sheets["Capital works"], sheets["Harbour services"], list(table[1])]
        assert budget[:2] == [offlex_d.CAPITAL_HEADER, offlex_d.SERVICES_HEADER]
        assert tuple(budget[2]) == offlex_d.MINUTES_HEADER
        mapped: dict[str, int] = {}
        unmapped: dict[str, int] = {}
        for header in budget:
            assert header[0] == "Project"
            on = [h for h in header[1:] if attribute_for_header(h) is not None]
            for h in header[1:]:
                code = offlex_d.TABLE_ATTRIBUTES[h]
                assert attribute_for_header(h) in (code, None), h
                side = mapped if h in on else unmapped
                side[code] = side.get(code, 0) + 1
            if header is not budget[2]:
                assert len(on) == 3 and len(header) == 7, header
        assert set(mapped) == set(unmapped) == self._CODES
        assert sum(mapped[c] for c in self._NUMERIC) == sum(unmapped[c] for c in self._NUMERIC) == 4
        assert not any("committed" in h.casefold() for header in budget for h in header)
        # The risk register maps nothing, as in every scenario.
        assert [attribute_for_header(h) for h in sheets["Risk register"][1:]] == [None] * 4

    def test_d_store_holds_the_mapped_cells_and_nothing_else(self, generated):
        """The structural route on D, with the real lexicon and store: the
        capital projects' authority, site and contract; the services projects'
        spend, owner and start, and their authority from the minutes. Both
        amounts only for the services projects, so only they derive."""
        store, table = _store(offlex_d, _docs(generated / offlex_d.ID))
        capital, services = ("SALTMARSH", "WEIRGATE"), ("FALLOWBECK", "LODESTAR")
        assert _structural(offlex_d, store, table) == {
            *((s, c) for s in capital for c in ("AUTHAMT", "SITEREF", "REFCODE")),
            *((s, c) for s in services for c in ("AUTHAMT", "SPENTAMT", "OWNERREF", "DATESTRT")),
        }
        assert store.counters["facts_structural"] == 14
        assert store.counters["facts_derived"] == 4
        assert store.counters["fact_conflicts"] == 0
        assert store.counters["fact_dropped_no_referent"] == 0
        # Three unmapped columns per budget sheet, one in the minutes, four risk.
        assert store.counters["fact_dropped_unknown_header"] == 11
        # What the store holds equals the key; what it lacks is exactly the
        # capital projects' spend and everything derived from it.
        codes = {"AUTHORISED": "AUTHAMT", "SPENT": "SPENTAMT", "UNSPENT": "UNSPNTAM",
                 "OVERRUN": "OVRRUNAM", "PCT_SPENT": "PCTSPENT"}
        missing = []
        for f in offlex_d.fact_key()["facts"]:
            if f["attribute"] in codes:
                got = _get((store, table), offlex_d, f["subject"], codes[f["attribute"]])
                if got is None:
                    missing.append(f["fact_id"])
                else:
                    assert got == f["value"], f["fact_id"]
        assert sorted(missing) == sorted(f"{s}.{a}" for s in capital
                                         for a in ("SPENT", "UNSPENT", "PCT_SPENT"))

    def test_facts_structural_against_total_table_facts(self, generated):
        """H4-D's premise: on D the structural route reaches a smaller share of
        what the tables state than on A and B. Pinned per corpus as
        (facts_structural, total table facts), perfect extraction as above:
        A 18/30, B 24/40, C 0/12, D 14/40. The denominators count the risk
        registers' cells, which no scenario's lexicon maps; without them A and
        B are 18/18 and 24/24 and D is 14/24."""
        pinned = {smoke_q3: (18, 30), portfolio_b: (24, 40), prose_c: (0, 12),
                  offlex_d: (14, 40)}
        ratio = {}
        for mod, counts in pinned.items():
            docs = _docs(generated / mod.ID)
            store, table = _store(mod, docs)
            facts = _table_facts(mod, docs)
            assert _structural(mod, store, table) <= facts, mod.ID
            assert (store.counters["facts_structural"], len(facts)) == counts, mod.ID
            ratio[mod.ID] = counts[0] / counts[1]
        assert ratio[offlex_d.ID] < ratio[portfolio_b.ID]
        assert ratio[offlex_d.ID] < ratio[smoke_q3.ID]
