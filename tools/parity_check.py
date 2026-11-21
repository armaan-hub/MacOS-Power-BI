"""Parity gate: everything already compared with Power BI Desktop is replayed against the app on every run.

    PYTHONPATH=. python tools/parity_check.py            # offline replay of the saved Power BI answers (no VM needed)
    PYTHONPATH=. python tools/parity_check.py --tests    # ... plus the pytest suite and the real-app run (tools/app_smoke.py)
    PYTHONPATH=. python tools/parity_check.py --accept   # lock every item that matches now (do this after a verified slice)
    PYTHONPATH=. python tools/parity_check.py --freeze   # re-ask Power BI (VM + Power BI Desktop open) for the DAX batteries
    PYTHONPATH=. python tools/parity_check.py --sample 20 [--seed 1]   # quick task gate: 20 answers per battery file, read-only
    PYTHONPATH=. python tools/parity_check.py --only NAME [--sample N] # full replay of the named battery files, others sampled, read-only

A sampled or --only run is read-only: it writes neither PARITY_LEDGER.md nor baseline.json, and it cannot be combined with
--accept or --freeze.  Its last line is PARITY GATE (SAMPLE) PASSED or FAILED.

Exit code 1 when a locked item stopped matching, any item differs from Power BI, the app crashed on an expression or the
imported VAT table changed.  Items Power BI answers but the app still refuses are listed as pending work (gap-reject),
they do not fail the gate.  Items where Power BI gives an error and the app refuses are counted on their own as
error-vs-refusal: they do not fail the gate either, and --accept locks them with the matches.  A DIFF listed in
tools/parity/known_diffs.json (made by tools/make_known_diffs.py) whose app answer is still the recorded one is a known-diff:
counted on its own, not failing, never locked; any other DIFF, or a listed row whose answer changed, fails.  Hunt batteries
(dax_battery_hunt_*.json) carry a Facts table per item.  The result is written to PARITY_LEDGER.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import subprocess
import tempfile
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analytics_studio.controller import _model_candidate_with_format_errors_as_blank  # noqa: E402
from analytics_studio.file_import import parse_file  # noqa: E402
from analytics_studio.transformations import infer_column_types  # noqa: E402
from tools import dax_oracle_diff as dax  # noqa: E402
from tools.table_oracle_diff import local_value  # noqa: E402

PARITY = ROOT / "tools" / "parity"
BASELINE = PARITY / "baseline.json"
LEDGER = ROOT / "PARITY_LEDGER.md"
DAX_BATTERIES = ["dax_battery", "dax_battery_review", "dax_battery_blank_logic", "dax_battery_filter_tables", "dax_battery_typed", "dax_battery_math", "dax_battery_tables", "dax_battery_tables2", "dax_battery_stats",
                "dax_battery_misc", "dax_battery_adversarial", "dax_battery_finance", "dax_battery_bonds", "dax_battery_filter_shapes", "dax_battery_filter_shapes2",
                "dax_battery_filter_shapes3", "dax_battery_filter_shapes4", "dax_battery_allselected", "dax_battery_var_tables", "dax_battery_earlier_arith",
    "dax_battery_boolean_scalar_rhs", "dax_battery_filter_transition", "dax_battery_boolean_filter_functions",
    "dax_battery_sdet_filters", "dax_battery_comments_booleans",
    "dax_battery_round2_scope", "dax_battery_round2", "dax_battery_critic_shapes",
    "dax_battery_round3", "dax_battery_round4", "dax_battery_round5", "dax_battery_diff_groups", "dax_battery_iferror_hard_errors", "dax_battery_concatenatex_order", "dax_battery_not_operator", "dax_battery_promoted_pending", "dax_battery_utf16_text", "dax_battery_evaluation_order", "dax_battery_allselected_shadow", "dax_battery_allselected_critic2",
    "dax_battery_xnpv", "dax_battery_scalar_misc2", "dax_battery_type_tests", "dax_battery_tocsv_tojson", "dax_battery_tocsv_tojson_extra", "dax_battery_tocsv_tojson_extra2", "dax_battery_linest", "dax_battery_linest_extra", "dax_battery_linest_extra2", "dax_battery_linest_extra3", "dax_battery_swi_extra", "dax_battery_swi_extra2", "dax_battery_swi_extra3", "dax_battery_ami_extra", "dax_battery_ami_extra2", "dax_battery_rollup_extra", "dax_battery_rollup_extra2", "dax_battery_rollup_extra3", "dax_battery_table_fns2", "dax_battery_var_scoping", "dax_battery_pending_extra", "dax_battery_pending_extra2", "dax_battery_misc3_extra", "dax_battery_misc3_extra2", "dax_battery_xnpv2", "dax_battery_gaps2", "dax_battery_gaps2_extra", "dax_battery_gaps2_extra2", "dax_battery_variant2_extra", "dax_battery_typed3_extra", "dax_battery_logic4_extra", "dax_battery_typed5_extra", "dax_battery_strict6_extra", "dax_battery_blank8_extra", "dax_battery_convert9_extra", "dax_battery_never10_extra", "dax_battery_currency11_extra", "dax_battery_double12_extra", "dax_battery_big13_extra", "dax_battery_topn14_extra", "dax_battery_trig15_extra", "dax_battery_logical17_extra", "dax_battery_collation18_extra", "dax_battery_textnum19_extra", "dax_battery_types20_extra", "dax_battery_linest21_extra", "dax_battery_swi22_extra", "dax_battery_xirr23_extra", "dax_battery_colstats24_extra", "dax_battery_info25_extra", "dax_battery_info26_extra", "dax_battery_blanktext27_extra", "dax_battery_bigorder28_extra", "dax_battery_naninf29_extra", "dax_battery_datestats30_extra", "dax_battery_typeerr31_extra", "dax_battery_roworder32_extra", "dax_battery_mixed33_extra", "dax_battery_counttext34_extra", "dax_battery_xnpvblank35_extra", "dax_battery_biground36_extra", "dax_battery_datevar37_extra", "dax_battery_oldtimes38_extra", "dax_battery_swiorder39_extra", "dax_battery_typeerr40_extra", "dax_battery_roworder41_extra", "dax_battery_mainfix43_extra", "dax_battery_xirr44_extra", "dax_battery_biground45_extra", "dax_battery_productx46_extra", "dax_battery_failtype47_extra", "dax_battery_missingfns48_extra", "dax_battery_swities49_extra", "dax_battery_typecols50_extra", "dax_battery_varxdates51_extra", "dax_battery_varxtopn52_extra", "dax_battery_maxxnan53_extra", "dax_battery_typeerr54_extra", "dax_battery_orderfree55_extra", "dax_battery_orderaudit56_extra", "dax_battery_orderaudit57_extra", "dax_battery_orderaudit58_extra", "dax_battery_orderaudit59_extra", "dax_battery_rankx60_extra", "dax_battery_rank61_extra", "dax_battery_stats62_extra", "dax_battery_text63_extra", "dax_battery_convert64_extra", "dax_battery_filter65_extra", "dax_battery_clean66_extra", "dax_battery_topndata67_extra",
    "dax_battery_scalar_misc2_extra", "dax_battery_scalar_misc2_extra2",
    "dax_battery_type_tests_extra", "dax_battery_type_tests_extra2"]
# Measured rows of the hunt, frozen once from the saved probe folders; each item may name its own Facts table ("facts").
HUNT_BATTERIES = sorted(path.stem for path in PARITY.glob("dax_battery_hunt_*.json"))
DAX_BATTERIES += HUNT_BATTERIES
# Real workbooks: the Power BI answers saved by tools/table_oracle_diff.py are replayed against the app's own import.
TABLES = {
    "VAT": {"path": ROOT / "tests/Data/Vat File -Aug 2026.xlsx", "header_row": 12, "sheet_name": "VAT 5%",
            "report": ROOT / "tools/table_oracle_report_VAT.json"},
    "DSI": {"path": Path.home() / "Downloads/DSI.xlsx", "header_row": 6, "sheet_name": None,
            "report": ROOT / "tools/table_oracle_report.json"},
}


def freeze() -> None:
    """Ask the live Power BI Desktop once per DAX battery and save its answers next to the repo."""
    PARITY.mkdir(exist_ok=True)
    port = dax.port()
    version = dax.guest("(Get-Item (Get-Process PBIDesktop | Select-Object -First 1).Path).VersionInfo.ProductVersion").strip().splitlines()[-1]
    dax.ensure_facts(port)
    try:
        for name in DAX_BATTERIES:
            if name in HUNT_BATTERIES:  # frozen once; its rows need their own Facts tables, so they are not re-asked here
                continue
            expressions = json.loads((ROOT / "tools" / f"{name}.json").read_text())
            answers = dax.power_bi(expressions, port)
            assert len(answers) == len(expressions), (name, len(answers), len(expressions))
            (PARITY / f"{name}.json").write_text(json.dumps({
                "powerbi_version": version, "frozen": date.today().isoformat(),
                "items": [{"expr": e, "powerbi": a} for e, a in zip(expressions, answers)]}, indent=1))
            print(f"froze {name}: {len(answers)} answers from Power BI {version}")
    finally:
        dax.drop_facts(port)


def status(powerbi: str, ours: str) -> str:
    """match, error-vs-refusal (Power BI errors and the app refuses: the same outcome by a different path, shown on its own),
    gap-reject (Power BI answers, the app refuses), DIFF, or CRASH."""
    if ours.startswith("LOCAL-CRASH"):
        return "CRASH"
    if powerbi.startswith("ERR") and ours.startswith("LOCAL-REJECT"):
        return "error-vs-refusal"
    if dax.same(powerbi, ours):
        return "match"
    return "gap-reject" if ours.startswith("LOCAL-REJECT") and not powerbi.startswith("ERR") else "DIFF"


def load_known_diffs() -> dict[str, dict]:
    """Rows measured wrong on purpose and listed with the app's current wrong answer (tools/parity/known_diffs.json), by lock id."""
    file = PARITY / "known_diffs.json"
    return {entry["id"]: entry for entry in json.loads(file.read_text())} if file.exists() else {}


def classify(row_id: str, powerbi: str, ours: str, known: dict[str, dict]) -> str:
    """status(), except that a DIFF listed in known_diffs whose app answer is still the recorded one is known-diff (it does not fail the
    gate); a listed row whose answer moved to another wrong value stays DIFF, and one that now matches is reported by the caller."""
    result = status(powerbi, ours)
    if result == "DIFF" and row_id in known and known[row_id]["app"] == ours:
        return "known-diff"
    return result


def _pick(name: str, items: list[dict], sample: int | None, seed: int) -> list[dict]:
    """A seeded sample of `sample` items, in file order; the whole list when it is None or not larger than the sample."""
    if sample is None or len(items) <= sample:
        return items
    chosen = sorted(random.Random(f"{name}:{seed}").sample(range(len(items)), sample))
    return [items[i] for i in chosen]


def saved_total() -> int:
    """How many saved Power BI answers exist (DAX batteries plus table reports), sampled or not."""
    total = 0
    for name in DAX_BATTERIES:
        file = PARITY / f"{name}.json"
        if file.exists():
            total += len(json.loads(file.read_text())["items"])
    for spec in TABLES.values():
        if spec["report"].exists():
            total += len(json.loads(spec["report"].read_text())["measures"])
    return total


def replay_dax(sample: int | None = None, seed: int = 0, only: list[str] | None = None) -> list[dict]:
    rows = []
    full = set(only or [])
    for name in DAX_BATTERIES:
        file = PARITY / f"{name}.json"
        if not file.exists():
            rows.append({"group": name, "expr": "", "powerbi": "", "ours": "", "status": "NOT-FROZEN", "id": name})
            continue
        battery = json.loads(file.read_text())
        tables = battery.get("facts_tables", {})
        known = load_known_diffs()
        for item in _pick(name, battery["items"], None if name in full else sample, seed):
            table = item.get("facts")
            ours = dax.local(item["expr"], tables[table] if table is not None else None)
            # an item on its own Facts table is locked under an id that names the table, so one expression can sit on several tables
            row_id = f"{name}:{table}|{item['expr']}" if table is not None else f"{name}:{item['expr']}"
            rows.append({"group": name, "expr": item["expr"], "powerbi": item["powerbi"], "ours": ours,
                         "status": classify(row_id, item["powerbi"], ours, known), "id": row_id})
    return rows


def import_digest(rows: list[dict], headers: list[str]) -> str:
    text = json.dumps([[repr(row[h]) for h in headers] for row in rows], ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


def replay_tables() -> tuple[list[dict], dict[str, str], list[str]]:
    rows, digests, notes = [], {}, []
    for name, spec in TABLES.items():
        if not spec["path"].exists():
            notes.append(f"{name}: workbook {spec['path']} is missing, its saved Power BI answers were not replayed")
            continue
        options = {"header_row": spec["header_row"], **({"sheet_name": spec["sheet_name"]} if spec["sheet_name"] else {})}
        candidate = parse_file(spec["path"], options)
        types = infer_column_types(candidate.headers, candidate.rows)
        table = [dict(r) for r in _model_candidate_with_format_errors_as_blank(candidate).rows]
        digests[name] = import_digest(table, candidate.headers)
        for item in json.loads(spec["report"].read_text())["measures"]:
            ours = local_value(item["expr"], name, candidate.headers, types, table)
            rows.append({"group": f"table {name}", "expr": item["expr"], "powerbi": item["powerbi"], "ours": ours,
                         "status": status(item["powerbi"], ours), "id": f"table {name}:{item['expr']}"})
    return rows, digests, notes


def write_ledger(results: list[dict], baseline: dict, failures: list[str], notes: list[str]) -> None:
    groups: dict[str, dict[str, int]] = {}
    for r in results:
        groups.setdefault(r["group"], {}).setdefault(r["status"], 0)
        groups[r["group"]][r["status"]] += 1
    lines = [
        "# Parity ledger: Analytics Studio vs Power BI Desktop", "",
        f"Generated {date.today().isoformat()} by `tools/parity_check.py`. Power BI answers were saved from "
        f"Power BI Desktop {baseline.get('powerbi_version', '?')}; the gate replays them against the app on every run.", "",
        "Rule: a slice is finished only when it is compared with Power BI, its items are locked here "
        "(`--accept`) and the gate passes.  Locked items are never re-investigated, only guarded.", "",
        "| Group | Locked and matching | Match (not yet locked) | Error vs refusal | Pending (app refuses) | Known diff | Differs | Crash |",
        "|---|---|---|---|---|---|---|---|",
    ]
    locked = set(baseline.get("locked", []))
    for group, counts in groups.items():
        match_locked = sum(1 for r in results if r["group"] == group and r["status"] == "match" and r["id"] in locked)
        match_all = counts.get("match", 0)
        lines.append(f"| {group} | {match_locked} | {match_all - match_locked} | {counts.get('error-vs-refusal', 0)} | {counts.get('gap-reject', 0)} | "
                     f"{counts.get('known-diff', 0)} | {counts.get('DIFF', 0)} | {counts.get('CRASH', 0)} |")
    pending = [r for r in results if r["status"] == "gap-reject"]
    lines += ["", f"## Pending work ({len(pending)}): Power BI answers, the app refuses", ""]
    lines += [f"- `{r['expr']}` (Power BI: `{r['powerbi'][:60]}`) [{r['group']}]" for r in pending] or ["- none"]
    known_rows = [r for r in results if r["status"] == "known-diff"]
    if known_rows:
        known = load_known_diffs()
        lines += ["", f"## Known wrong ({len(known_rows)}): Power BI answers, the app answers differently, listed in tools/parity/known_diffs.json", ""]
        lines += [f"- `{r['expr'][:150]}` (Power BI: `{r['powerbi'][:40]}`, app: `{r['ours'][:40]}`) [{r['group']}; {known[r['id']]['cause_group']}]"
                  for r in known_rows]
    if failures:
        lines += ["", "## Failing", ""] + [f"- {f}" for f in failures]
    deviations = PARITY / "known_deviations.json"
    if deviations.exists():
        known = json.loads(deviations.read_text())
        lines += ["", f"## Known deviations from Power BI ({len(known)}): imprecise or unspecified in Power BI, each explained", ""]
        lines += [f"- `{k['expr']}`: Power BI {k['powerbi']}, app {k['app']} ({k['why']})" for k in known]
    if notes:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in notes]
    lines += ["", "## Not yet compared with Power BI (no saved answers)", "",
              "UI screens side by side, text/Boolean results, VAR/RETURN, VALUES/SELECTEDVALUE, Infinity/NaN, "
              "other visuals, Power Query live sources, service features."]
    LEDGER.write_text("\n".join(lines) + "\n")


def _start_pytest(env: dict) -> subprocess.Popen:
    """Run the whole suite without stopping at the first failure, spread over CPU cores when pytest-xdist is installed."""
    import importlib.util
    import os
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rfE"]
    if importlib.util.find_spec("xdist"):
        workers = int(os.environ.get("PARITY_WORKERS", max(1, min(12, (os.cpu_count() or 2) - 4))))
        command += ["-n", str(workers)]
    log = tempfile.TemporaryFile(mode="w+")  # a file, not a pipe: a full pipe would stall the suite while the answers replay
    process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, text=True)
    process.log = log
    return process


def _output(process: subprocess.Popen) -> str:
    process.wait()
    process.log.seek(0)
    return process.log.read()


def _failed_test_ids(output: str) -> list[str]:
    """Test node ids from FAILED / ERROR / SUBFAILED summary lines (a subtest's parameters may hold spaces)."""
    ids = []
    for line in output.splitlines():
        if not line.startswith(("FAILED ", "ERROR ", "SUBFAILED")):
            continue
        found = re.search(r"(tests/[^\s:]+\.py::[^\s]+)", line)
        if found and found.group(1) not in ids:
            ids.append(found.group(1))
    return ids


def _finish_pytest(suite: subprocess.Popen, env: dict) -> list[str]:
    """Wait for the suite; a test that failed only in the parallel run is re-run alone before it counts as a failure."""
    output = _output(suite)
    print("pytest:", (output.strip().splitlines() or ["no output"])[-1])
    if suite.returncode == 0:
        return []
    failed = _failed_test_ids(output)
    if not failed:
        return ["pytest suite failed (no test ids found in its output)"]
    rerun = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rfE", *failed], cwd=ROOT, env=env,
                           capture_output=True, text=True)
    still = _failed_test_ids(rerun.stdout) if rerun.returncode else []
    flaky = [t for t in failed if t not in still]
    if flaky:
        print(f"pytest: {len(flaky)} test(s) failed only beside other tests and passed when re-run alone:", ", ".join(flaky))
    if rerun.returncode and not still:
        return ["pytest re-run failed: " + ((rerun.stdout.strip().splitlines() or ["no output"])[-1])]
    return [f"pytest failed: {t}" for t in still]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true", help="re-ask the live Power BI for the DAX batteries")
    parser.add_argument("--accept", action="store_true", help="lock every item that matches now")
    parser.add_argument("--tests", action="store_true", help="also run pytest and tools/app_smoke.py")
    parser.add_argument("--sample", type=int, default=None, metavar="N", help="replay only N seeded answers per battery file (read-only)")
    parser.add_argument("--seed", type=int, default=0, help="seed for --sample")
    parser.add_argument("--only", action="append", default=[], metavar="NAME", help="replay this battery file in full (repeatable; read-only)")
    args = parser.parse_args()
    partial = args.sample is not None or bool(args.only)
    if partial and (args.accept or args.freeze):
        print("error: --accept and --freeze need the full replay; they cannot be combined with --sample or --only", file=sys.stderr)
        return 2
    if args.sample is not None and args.sample < 1:
        print("error: --sample needs N >= 1", file=sys.stderr)
        return 2
    unknown = [n for n in args.only if n not in DAX_BATTERIES]
    if unknown:
        print("error: unknown battery name(s) for --only:", ", ".join(unknown), file=sys.stderr)
        return 2
    if args.freeze:
        freeze()
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else {"locked": [], "import_digests": {}}
    try:
        first = next(PARITY.glob("dax_battery*.json"))
        baseline["powerbi_version"] = json.loads(first.read_text())["powerbi_version"]
    except StopIteration:
        pass

    # --tests: start the pytest suite and the real-app run in the background now, so they run while the answers replay
    env = {"QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": ".", **{k: v for k, v in __import__("os").environ.items()}}
    suite = smoke = None
    if args.tests:
        suite = _start_pytest(env)
        if TABLES["VAT"]["path"].exists():
            log = tempfile.TemporaryFile(mode="w+")
            smoke = subprocess.Popen([sys.executable, "tools/app_smoke.py", str(ROOT / "tools/parity/_smoke")], cwd=ROOT, env=env,
                                     stdout=log, stderr=subprocess.DEVNULL, text=True)
            smoke.log = log

    dax_rows = replay_dax(args.sample, args.seed, args.only)
    table_rows, digests, notes = replay_tables()
    results = dax_rows + table_rows

    failures = []
    locked = set(baseline.get("locked", []))
    for r in results:
        if r["status"] == "NOT-FROZEN":
            failures.append(f"{r['group']}: no saved Power BI answers (run --freeze)")
        elif r["status"] in ("DIFF", "CRASH"):
            failures.append(f"{r['status']} {r['id']}: Power BI {r['powerbi'][:50]} vs app {r['ours'][:80]}")
        elif r["id"] in locked and r["status"] not in ("match", "error-vs-refusal"):
            failures.append(f"REGRESSION (was locked) {r['id']}: Power BI {r['powerbi'][:50]} vs app {r['ours'][:80]}")
    known = load_known_diffs()
    seen_ids = {r["id"] for r in results}
    for r in results:
        if r["id"] in known and r["status"] not in ("known-diff", "DIFF", "CRASH"):
            notes.append(f"fixed, remove from known_diffs.json: {r['id'][:160]} (now {r['status']})")
    if not partial:
        notes += [f"known_diffs.json lists a row that no battery holds any more: {i[:160]}" for i in known if i not in seen_ids]
    for name, digest in digests.items():
        old = baseline.get("import_digests", {}).get(name)
        if old and old != digest:
            failures.append(f"table {name}: imported data changed since it was locked (digest {digest[:12]} vs {old[:12]})")

    if args.accept and not failures and not partial:
        baseline["locked"] = sorted(locked | {r["id"] for r in results if r["status"] in ("match", "error-vs-refusal")})
        baseline["import_digests"] = {**baseline.get("import_digests", {}), **digests}
        PARITY.mkdir(exist_ok=True)
        BASELINE.write_text(json.dumps(baseline, indent=1))
        locked = set(baseline["locked"])
        print(f"locked {len(locked)} items")
    elif args.accept:
        print("not locking: the gate has failures")

    if args.tests:
        failures += _finish_pytest(suite, env)
        if smoke is not None:
            out = _output(smoke)
            line = next((l for l in out.splitlines() if l.startswith("MEASURES THROUGH THE APP")), "no result line")
            print("real app:", line)
            if smoke.returncode or "0 different" not in line or "reopen: True" not in out:
                failures.append(f"real-app run failed: {line}")

    counts = {s: sum(1 for r in results if r["status"] == s) for s in ("match", "error-vs-refusal", "known-diff", "gap-reject", "DIFF", "CRASH")}
    if partial:
        # read-only: no PARITY_LEDGER.md, no baseline.json
        print(f"replayed {len(results)} Power BI answers: {counts}; locked {len(locked)}")
        for n in notes:
            print("note:", n)
        for f in failures:
            print("FAIL:", f)
        print(f"sampled {len(results)} of {saved_total()} saved answers")
        print("PARITY GATE (SAMPLE)", "FAILED" if failures else "PASSED")
        return 1 if failures else 0

    write_ledger(results, baseline, failures, notes)
    print(f"replayed {len(results)} Power BI answers: {counts}; locked {len(locked)}")
    for n in notes:
        print("note:", n)
    for f in failures:
        print("FAIL:", f)
    print("PARITY GATE", "FAILED" if failures else "PASSED", "-> PARITY_LEDGER.md")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
