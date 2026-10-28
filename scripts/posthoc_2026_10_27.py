#!/usr/bin/env python3
"""Track L after the numbers freeze: Presidio on the admitted collections, the
field of the QUASI crossing, and what the refused collections held (scope §14).

Why this exists
---------------
Track L's crossing figures hold on the two collections the monitor admitted;
the frozen Presidio keys pool all six; the one QUASI crossing's field is named
but not what it holds; and what the four refused planner requests held is not
measured. ``PRIVDEEP_ICCIT_SCOPE.md`` §14, signed by the author on 2026-10-27,
fixes what is computed, from frozen artifacts only, with no run, no label, no
rescore and no model or network call. This script computes exactly that and
writes ``eval/paper/posthoc_l.json``, which ``make_paper_tables.py --posthoc-l``
reads into numbers.json. Written by the AI assistant on 2026-10-27 under §14.

Every figure is post hoc and exploratory (§14.4). None tests, replaces or
reinterprets a registered hypothesis or outcome; HL1 stays not testable. The
output holds counts, hashes and routes, never an identifier string (§12.7).

What it computes (§14.2)
------------------------
(a) Presidio's residual on tab-L1 and tab-L2, summed from the frozen
    ``eval/real/out/presidio_tab-L{1,2}.json`` (DIRECT and QUASI totals, DIRECT
    CODE and PERSON), each file tied to the scan's strings by its
    ``identifiers_sha256``.
(b) Whether the system field of every r1 drafter request on tab-L1 and tab-L2
    is byte-identical to the one of corpus A's frozen r1 runs, and that every
    QUASI crossing occurrence lies in such a field.
(c) Only once §14 is signed (the script reads the Status line): on the four
    refused collections, (c1) extractor recall and (c2) predicate echo through
    ``real_l.py extraction``, and (c3) the would-be crossing of the r5 planner
    request rebuilt as ``real_l_refusal_sim.py`` rebuilds it, scanned by
    ``real_l.py``'s ``_crossings`` as a one-exchange trace on the core-sent
    side. The measurement code is imported from a clean tree of commit
    26de996 (the commit ``real_l_scan.json`` and ``refusal_sim.json`` record),
    never from this checkout, because ``real_l.py`` and ``pipeline.py`` changed
    on 2026-10-27. If a rebuilt request does not match ``refusal_sim.json``'s
    r5 entry, or a string (c2) counts is not counted by (c3), (c3) is reported
    for no collection (§14.3's fallback).

Usage (the venv interpreter, which has FastAPI for the in-process monitor)::

    git archive 26de996 | tar -x -C CODE        # a clean tree of that commit
    ln -s "$PWD/eval/real/corpora" CODE/eval/real/corpora
    /home/ldhung/privdeep/.venv/bin/python scripts/posthoc_2026_10_27.py --code-root CODE
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
INSTRUMENT = "scripts/posthoc_2026_10_27.py"
CODE_COMMIT = "26de996ff464a5e3d10bffc79ec91996bcd174e1"
ADMITTED = ("tab-L1", "tab-L2")
REFUSED = ("tab-L3", "tab-L4", "tab-L5", "tab-L6")
R1_L_RUNS = ("tab-L1__r1", "tab-L1__r1__rep2", "tab-L2__r1", "tab-L2__r1__rep2")
R1_A_RUNS = ("smoke-q3__r1", "smoke-q3__r1__rep2", "smoke-q3__r1__rep3")
# §14.2(c), pinned before any value was computed.
EXTRACTIONS = {
    "tab-L3": "21e095606e8cb8362c2792f8afe5c8c42f5f150c1f62246461a7a0efe1ff73be",
    "tab-L4": "ed2b5ed6cf8a53915731b8f3413e74214694e31b612d5cb0870648039aec08b5",
    "tab-L5": "95d1afb33926607409a9e199e76ac1ef16332d135e5f64257d456c2602ee889a",
    "tab-L6": "927a0a5e084976fffad9e3135423f7b7b34665b198cdb7501516d93c1ae97e32",
}
IDENTIFIERS = {
    "tab-L3": "d0324e7cc288a13312028f539fe3ef2a2ab31d83564e2ed2409a836c3c4467db",
    "tab-L4": "542d7c458277830d19878712c4f990f2a11f3e4d366b6ebffdd4ac5adacbbc1c",
    "tab-L5": "80ac90a158a19bcadb13111464d49f234af99178a36ccf9a648348dcb97c7374",
    "tab-L6": "bcfead32d735a7062aed50e53b5b49530ee17579c1ef0f0fe5daee7aa3adb785",
}
VENV_PYTHON = Path("/home/ldhung/privdeep/.venv/bin/python")
COPY_DIR = REPO / "eval" / "real" / "out" / "posthoc_refused_extractions"
EXTRACTION_OUT = REPO / "eval" / "real" / "out" / "posthoc_refused_extraction.json"
# refusal_sim.json's r5 fields a rebuilt request must reproduce (§14.2(c3)).
SIM_FIELDS = (("refused",), ("reason",), ("relations", "distinct"), ("slots", "advertised"),
              ("prompt", "hits"), ("hits", "whole_stream"))


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def kn(k: int, n: int) -> dict[str, Any]:
    return {"k": k, "n": n, "rate": k / n if n else None}


def read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def section_14_signed() -> bool:
    """§14's Status line, as §12.11's batch reads a signature: signed, not DRAFT."""
    text = (REPO / "PRIVDEEP_ICCIT_SCOPE.md").read_text(encoding="utf-8")
    m = re.search(r"^## 14\..*?(?=^## \d|\Z)", text, re.S | re.M)
    if not m:
        return False
    sec = m.group(0)
    return "**Status: signed by the author on 2026-10-27**" in sec and "DRAFT" not in sec


# ------------------------------------------------------------------ (a)

def presidio_admitted(scan: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"per_collection": {}}
    sums = {k: [0, 0] for k in ("direct", "quasi", "direct_CODE", "direct_PERSON")}
    for c in ADMITTED:
        p = REPO / "eval" / "real" / "out" / f"presidio_{c}.json"
        d = read_json(p)
        if d.get("identifiers_sha256") != scan["collections"][c]["identifiers_sha256"]:
            raise SystemExit(f"{p.name}: identifiers differ from real_l_scan.json's {c}")
        bt = d["by_type"]
        got = {"direct": bt["DIRECT"]["total"], "quasi": bt["QUASI"]["total"],
               "direct_CODE": bt["DIRECT"].get("CODE", {"k": 0, "n": 0}),
               "direct_PERSON": bt["DIRECT"].get("PERSON", {"k": 0, "n": 0})}
        out["per_collection"][c] = {"file_sha256": sha256(p),
                                    **{k: kn(v["k"], v["n"]) for k, v in got.items()}}
        for k, v in got.items():
            sums[k][0] += int(v["k"])
            sums[k][1] += int(v["n"])
    out.update({k: kn(*v) for k, v in sums.items()})
    if (sums["direct"][1], sums["quasi"][1]) != (scan["HL1"]["direct"]["n"],
                                                 scan["HL1"]["quasi_descriptive"]["n"]):
        raise SystemExit("Presidio's admitted strings are not the scan's (n differs)")
    return out


# ------------------------------------------------------------------ (b)

def _trace(run: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (run / "egress_trace.jsonl").read_text(
        encoding="utf-8").splitlines() if line.strip()]


def _canon(system: Any) -> str:
    """A system field as one string: itself, or its JSON when it is a list of blocks."""
    return system if isinstance(system, str) else json.dumps(system, sort_keys=True,
                                                              ensure_ascii=False)


def _drafter_systems(run: Path) -> list[str]:
    return [_canon(e.get("system")) for e in _trace(run)
            if str(e.get("stage", "")).startswith("draft")]


def sysfield(scan: dict[str, Any]) -> dict[str, Any]:
    a_systems = {s for r in R1_A_RUNS for s in _drafter_systems(REPO / "eval" / "runs" / r)}
    if len(a_systems) != 1 or "null" in a_systems:
        raise SystemExit(f"corpus A's r1 drafter requests carry {len(a_systems)} system fields")
    (a_sys,) = a_systems
    same = total = 0
    for r in R1_L_RUNS:
        for e in _trace(REPO / "eval" / "real" / "runs" / r):
            if str(e.get("stage", "")).startswith("draft"):
                total += 1
                same += _canon(e.get("system")) == a_sys
    # Every crossing occurrence of every run the scan read, counted as the scan's routes
    # count them (once per entity type), must lie in that field of a drafter request.
    occurrences = in_template = 0
    for c in ADMITTED:
        for name, run_scan in scan["collections"][c]["runs"].items():
            if run_scan.get("crossing") is None:
                continue
            run = REPO / "eval" / "real" / "runs" / name
            cp = run / "real_l_crossings.json"
            if not cp.exists():
                raise SystemExit(f"{cp} is missing for a run the scan read")
            trace = _trace(run)
            for x in read_json(cp)["crossed"]:
                if x.get("label"):
                    continue
                for o in x["occurrences"]:
                    w = int(o["count"]) * len(x["entity_types"])
                    occurrences += w
                    e = trace[o["exchange"]]
                    in_template += w * (o["field"] == "system"
                                        and str(e.get("stage", "")).startswith("draft")
                                        and _canon(e.get("system")) == a_sys)
    hl1 = scan["HL1"]
    routed = sum(int(x["occurrences"]) for x in (hl1.get("routes") or [])
                 + ((hl1.get("attempts") or {}).get("routes") or []))
    if occurrences != routed:
        raise SystemExit(f"{occurrences} crossing occurrences read, the scan's routes hold "
                         f"{routed}")
    if occurrences == 0 or in_template != occurrences:
        raise SystemExit(f"{in_template}/{occurrences} crossing occurrences lie in the r1 drafter "
                         "system field shared with corpus A; §14.2(b) stops")
    return {"a_system_sha256": hashlib.sha256(a_sys.encode("utf-8")).hexdigest(),
            "a_system_chars": len(a_sys), "same_as_A": kn(same, total),
            "crossing_occurrences_in_that_field": kn(in_template, occurrences)}


# ------------------------------------------------------------------ (c)

def _git(*args: str) -> str:
    git = shutil.which("git")
    if not git:
        raise SystemExit("git is needed to check the code tree against its commit")
    return subprocess.run([git, "-C", str(REPO), *args], check=True,  # noqa: S603 - argv list
                          capture_output=True, text=True).stdout


def _verify_tree(code_root: Path) -> int:
    """Every file of the tree is the commit's, byte for byte (git blob ids), and none is
    missing; the corpora link (git-ignored data) and bytecode caches are not code."""
    want = {}
    for line in _git("ls-tree", "-r", CODE_COMMIT).splitlines():
        meta, path = line.split("\t", 1)
        want[path] = meta.split()[2]
    got = {}
    for f in code_root.rglob("*"):
        rel = f.relative_to(code_root).as_posix()
        if rel.startswith("eval/real/corpora") or "__pycache__" in rel or f.is_dir():
            continue
        data = f.read_bytes()
        got[rel] = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # noqa: S324 - git's id
    if got != want:
        diff = sorted(set(got) ^ set(want)) + sorted(k for k in got.keys() & want.keys()
                                                     if got[k] != want[k])
        raise SystemExit(f"{code_root} is not commit {CODE_COMMIT}: {diff[:5]}")
    return len(got)


def _import_code(code_root: Path) -> tuple[Any, Any, Any, dict[str, str]]:
    for p in (code_root / "backend" / "src", code_root):
        sys.path.insert(0, str(p))
    from scripts import real_l as RL  # noqa: E402
    from scripts import real_l_refusal_sim as SIM  # noqa: E402
    from scripts import run_evaluation as R  # noqa: E402
    loaded: dict[str, str] = {}
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None)
        if not f or m.__name__ == "__main__":
            continue
        fp = Path(f).resolve()
        if fp.is_relative_to(REPO):
            raise SystemExit(f"{m.__name__} was imported from this checkout ({fp}), not the tree")
        if fp.is_relative_to(code_root):
            loaded[fp.relative_to(code_root).as_posix()] = sha256(fp)
    for need in ("scripts/real_l.py", "scripts/real_l_refusal_sim.py", "scripts/run_evaluation.py",
                 "backend/src/privdeep/pipeline.py", "shared/shingle_filter.py"):
        if need not in loaded:
            raise SystemExit(f"{need} was not imported from {code_root}")
    return RL, SIM, R, dict(sorted(loaded.items()))


def _get(d: dict[str, Any], path: tuple[str, ...]) -> Any:
    for k in path:
        d = d[k]
    return d


def refused_collections(code_root: Path) -> dict[str, Any]:
    code_root = code_root.resolve()
    tree_files = _verify_tree(code_root)
    RL, SIM, R, code_files = _import_code(code_root)
    corpora_link = code_root / "eval" / "real" / "corpora"
    if corpora_link.resolve() != (REPO / "eval" / "real" / "corpora").resolve():
        raise SystemExit(f"{corpora_link} must link to this checkout's eval/real/corpora")
    tasks = {t.id: t for t in R.load_tasks(code_root / "eval" / "real" / "tasks_l.json")}
    sim = read_json(REPO / "eval" / "real" / "out" / "refusal_sim.json")
    if sim.get("git_commit") != CODE_COMMIT:
        raise SystemExit(f"refusal_sim.json records {sim.get('git_commit')}, not {CODE_COMMIT}")

    # Inputs, pinned: copy exactly the four extractions into a new git-ignored directory.
    _git("check-ignore", "-q", str(COPY_DIR / "x.json"))
    if COPY_DIR.exists():
        shutil.rmtree(COPY_DIR)
    for c in REFUSED:
        src = REPO / "eval" / "real" / "attempts" / f"{c}__r5__attempt1" / "extractions.json"
        if sha256(src) != EXTRACTIONS[c]:
            raise SystemExit(f"{src}: sha256 differs from §14.2(c)")
        if sha256(tasks[c].corpus / "identifiers.json") != IDENTIFIERS[c]:
            raise SystemExit(f"{c}: identifiers.json sha256 differs from §14.2(c)")
        (COPY_DIR / c).mkdir(parents=True)
        shutil.copyfile(src, COPY_DIR / c / "extractions.json")
        if sha256(COPY_DIR / c / "extractions.json") != EXTRACTIONS[c]:
            raise SystemExit(f"copy of {c} differs")

    # (c1), (c2): real_l.py extraction, as §14.2 names it.
    cmd = [sys.executable, "-B", str(code_root / "scripts" / "real_l.py"), "extraction",
           "--tasks", str(code_root / "eval" / "real" / "tasks_l.json"),
           "--extractions", str(COPY_DIR), "--out", str(EXTRACTION_OUT)]
    subprocess.run(cmd, cwd=code_root, check=True,  # noqa: S603 - argv list, no shell
                   stdout=subprocess.DEVNULL)
    ext = read_json(EXTRACTION_OUT)
    for c in ADMITTED:
        if ext["collections"][c]["extractions"]:
            raise SystemExit(f"{EXTRACTION_OUT.name} lists an extraction for {c}")
    if ext["distinct_extractions"] != len(REFUSED):
        raise SystemExit(f"{EXTRACTION_OUT.name}: {ext['distinct_extractions']} extractions")
    # The child records `git rev-parse HEAD` in the tree: "unknown" for an archive.
    if ext.get("git_commit") not in ("unknown", CODE_COMMIT):
        raise SystemExit(f"{EXTRACTION_OUT.name} was written by {ext.get('git_commit')}")
    ext_content = json.dumps({k: v for k, v in ext.items() if k != "git_commit"},
                             sort_keys=True, ensure_ascii=False).encode("utf-8")

    # (c3): the r5 planner request rebuilt from each extraction, scanned as sent.
    per: dict[str, Any] = {}
    c3: dict[str, Any] = {}
    rows: list[tuple[Any, bool]] = []
    one_call_k = {"all": 0, "DIRECT": 0, "QUASI": 0}
    route_agg: dict[tuple[str, str, str, str], list[int]] = {}
    rebuild_ok = True
    for c in REFUSED:
        task = tasks[c]
        docs = SIM.load_docs(task.corpus)
        path = COPY_DIR / c / "extractions.json"
        lx = SIM.load_extraction(path, docs)
        req = SIM.build_planner_request(docs, lx.extractions, "r5", task.goal)
        f = SIM.build_filter(docs, salt=SIM.FILTER_SALT, n_min=SIM.N_MIN, n_max=SIM.N_MAX,
                             hit_threshold=SIM.HIT_THRESHOLD)
        with SIM.monitor_session(f) as (client, _seal):
            rec = SIM.inspect_request(client, f, req, task.goal)
        frozen = sim["collections"][c]["extractions"][0]
        if frozen["sha256"] != EXTRACTIONS[c]:
            raise SystemExit(f"refusal_sim.json's {c} extraction is not the pinned one")
        frozen = frozen["arms"]["r5"]
        mismatched = [".".join(p) for p in SIM_FIELDS if _get(rec, p) != _get(frozen, p)]
        idents = RL.load_identifiers(task)
        by_text = {i.text: i for i in idents}
        groups = RL.needle_groups(by_text)
        nl_groups = RL.needle_groups(i.text for i in idents if not i.label)
        b = json.loads(req.raw)
        trace = [{"stage": "plan", "system": b.get("system"), "messages": b["messages"],
                  "tools": b.get("tools")}]
        crossed, one_call, excluded = RL._crossings(trace, task.goal, idents, groups)
        _block, xrows = RL.extraction_measures(read_json(path), idents, nl_groups)
        echoed = {i.text for i, h in xrows["echo"] if h}
        echo_not_carried = sorted(echoed - set(crossed))
        ok = not mismatched and not echo_not_carried
        rebuild_ok &= ok
        crow = [(i, i.text in crossed) for i in idents]
        rows += crow
        oc = RL._one_call(idents, one_call)
        for k in one_call_k:
            one_call_k[k] += int(oc[k])
        for key, v in RL._routes(crossed, by_text).items():
            a = route_agg.setdefault(key, [0, 0])
            a[0] += v[0]
            a[1] += v[1]
        (x0,) = ext["collections"][c]["extractions"]
        if x0["sha256"] != EXTRACTIONS[c]:
            raise SystemExit(f"{EXTRACTION_OUT.name}: {c} read another extraction")
        per[c] = {"rebuild_matches_refusal_sim": not mismatched, "mismatched_fields": mismatched,
                  "request_bytes": {"this": rec["request_bytes"],
                                    "refusal_sim": frozen["request_bytes"]},
                  "echo_strings_not_carried": len(echo_not_carried),
                  "recall": x0["extractor_recall"], "echo": x0["predicate_echo"]}
        c3[c] = {"would_cross": RL.tally(crow), "one_call": oc,
                 "routes": RL._route_rows(RL._routes(crossed, by_text)),
                 "excluded_occurrences": excluded}
    out = {"code_commit": CODE_COMMIT, "code_tree_files_verified": tree_files,
           "code_files_sha256": code_files,
           "inputs_sha256": {"extractions": EXTRACTIONS, "identifiers": IDENTIFIERS},
           "extraction_output": {"file": str(EXTRACTION_OUT.relative_to(REPO)),
                                 "content_sha256": hashlib.sha256(ext_content).hexdigest()},
           "recall": ext["extractor_recall"], "echo": ext["predicate_echo"],
           "rebuild_ok": rebuild_ok, "per_collection": per}
    # §14.3: when a rebuild fails anywhere, (c3) is reported for no collection.
    if not rebuild_ok:
        out["rebuild_failure"] = sorted(
            {"mismatch" for v in per.values() if v["mismatched_fields"]}
            | {"echo_not_carried" for v in per.values() if v["echo_strings_not_carried"]})
    else:
        for c in REFUSED:
            per[c].update(c3[c])
        out["would_cross"] = RL.tally(rows)
        out["would_cross_one_call"] = one_call_k
        out["would_cross_routes"] = RL._route_rows(route_agg)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--code-root", type=Path, required=True,
                    help="a clean tree of commit 26de996, eval/real/corpora linked to this one's")
    ap.add_argument("--out", type=Path, default=REPO / "eval" / "paper" / "posthoc_l.json")
    args = ap.parse_args(argv)
    if Path(sys.executable).resolve() != VENV_PYTHON.resolve():
        raise SystemExit(f"run under {VENV_PYTHON} (§14.2), not {sys.executable}")
    out_dir = REPO / "eval" / "real" / "out"
    scan_path = out_dir / "real_l_scan.json"
    scan = read_json(scan_path)
    if scan.get("git_commit") != CODE_COMMIT:
        raise SystemExit(f"real_l_scan.json records {scan.get('git_commit')}, not {CODE_COMMIT}")
    signed = section_14_signed()
    rep: dict[str, Any] = {
        "instrument": INSTRUMENT,
        "source": "PRIVDEEP_ICCIT_SCOPE.md §14 (signed by the author on 2026-10-27)",
        "section_14_signed": signed,
        "instrument_sha256": sha256(Path(__file__)),
        "python": sys.executable,
        "inputs": {"real_l_scan.json": sha256(scan_path),
                   "refusal_sim.json": sha256(out_dir / "refusal_sim.json"),
                   **{f"presidio_{c}.json": sha256(out_dir / f"presidio_{c}.json")
                      for c in ADMITTED}},
        "presidio_admitted": presidio_admitted(scan),
        "r1_drafter_system_field": sysfield(scan),
        "reproduced": {"l_direct_strings": str(scan["HL1"]["direct"]["n"]),
                       "l_quasi_strings": str(scan["HL1"]["quasi_descriptive"]["n"])},
    }
    if signed:
        rep["refused"] = refused_collections(args.code_root)
    else:
        print("§14 is not signed: 14.2(c) is not computed", file=sys.stderr)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
