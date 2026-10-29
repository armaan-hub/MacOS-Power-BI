"""Parity gate: everything already compared with Power BI Desktop is replayed against the app on every run.

    PYTHONPATH=. python tools/parity_check.py            # offline replay of the saved Power BI answers (no VM needed)
    PYTHONPATH=. python tools/parity_check.py --tests    # ... plus the pytest suite and the real-app run (tools/app_smoke.py)
    PYTHONPATH=. python tools/parity_check.py --accept   # lock every item that matches now (do this after a verified slice)
    PYTHONPATH=. python tools/parity_check.py --freeze   # re-ask Power BI (VM + Power BI Desktop open) for the DAX batteries

Exit code 1 when a locked item stopped matching, any item differs from Power BI, the app crashed on an expression or the
imported VAT table changed.  Items Power BI answers but the app still refuses are listed as pending work (gap-reject),
they do not fail the gate.  The result is written to PARITY_LEDGER.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
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
    "dax_battery_xnpv", "dax_battery_scalar_misc2", "dax_battery_type_tests", "dax_battery_tocsv_tojson", "dax_battery_tocsv_tojson_extra", "dax_battery_tocsv_tojson_extra2", "dax_battery_linest", "dax_battery_linest_extra", "dax_battery_linest_extra2", "dax_battery_linest_extra3", "dax_battery_swi_extra", "dax_battery_swi_extra2", "dax_battery_swi_extra3", "dax_battery_ami_extra", "dax_battery_ami_extra2", "dax_battery_rollup_extra", "dax_battery_rollup_extra2", "dax_battery_rollup_extra3", "dax_battery_table_fns2", "dax_battery_var_scoping", "dax_battery_xnpv2",
    "dax_battery_scalar_misc2_extra", "dax_battery_scalar_misc2_extra2",
    "dax_battery_type_tests_extra", "dax_battery_type_tests_extra2"]
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
    if ours.startswith("LOCAL-CRASH"):
        return "CRASH"
    if dax.same(powerbi, ours) or (powerbi.startswith("ERR") and ours.startswith("LOCAL-REJECT")):
        return "match"
    return "gap-reject" if ours.startswith("LOCAL-REJECT") and not powerbi.startswith("ERR") else "DIFF"


def replay_dax() -> list[dict]:
    rows = []
    for name in DAX_BATTERIES:
        file = PARITY / f"{name}.json"
        if not file.exists():
            rows.append({"group": name, "expr": "", "powerbi": "", "ours": "", "status": "NOT-FROZEN", "id": name})
            continue
        for item in json.loads(file.read_text())["items"]:
            ours = dax.local(item["expr"])
            rows.append({"group": name, "expr": item["expr"], "powerbi": item["powerbi"], "ours": ours,
                         "status": status(item["powerbi"], ours), "id": f"{name}:{item['expr']}"})
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
        "| Group | Locked and matching | Match (not yet locked) | Pending (app refuses) | Differs | Crash |",
        "|---|---|---|---|---|---|",
    ]
    locked = set(baseline.get("locked", []))
    for group, counts in groups.items():
        match_locked = sum(1 for r in results if r["group"] == group and r["status"] == "match" and r["id"] in locked)
        match_all = counts.get("match", 0)
        lines.append(f"| {group} | {match_locked} | {match_all - match_locked} | {counts.get('gap-reject', 0)} | "
                     f"{counts.get('DIFF', 0)} | {counts.get('CRASH', 0)} |")
    pending = [r for r in results if r["status"] == "gap-reject"]
    lines += ["", f"## Pending work ({len(pending)}): Power BI answers, the app refuses", ""]
    lines += [f"- `{r['expr']}` (Power BI: `{r['powerbi'][:60]}`) [{r['group']}]" for r in pending] or ["- none"]
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true", help="re-ask the live Power BI for the DAX batteries")
    parser.add_argument("--accept", action="store_true", help="lock every item that matches now")
    parser.add_argument("--tests", action="store_true", help="also run pytest and tools/app_smoke.py")
    args = parser.parse_args()
    if args.freeze:
        freeze()
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else {"locked": [], "import_digests": {}}
    try:
        first = next(PARITY.glob("dax_battery*.json"))
        baseline["powerbi_version"] = json.loads(first.read_text())["powerbi_version"]
    except StopIteration:
        pass

    dax_rows = replay_dax()
    table_rows, digests, notes = replay_tables()
    results = dax_rows + table_rows

    failures = []
    locked = set(baseline.get("locked", []))
    for r in results:
        if r["status"] == "NOT-FROZEN":
            failures.append(f"{r['group']}: no saved Power BI answers (run --freeze)")
        elif r["status"] in ("DIFF", "CRASH"):
            failures.append(f"{r['status']} {r['id']}: Power BI {r['powerbi'][:50]} vs app {r['ours'][:80]}")
        elif r["id"] in locked and r["status"] != "match":
            failures.append(f"REGRESSION (was locked) {r['id']}: Power BI {r['powerbi'][:50]} vs app {r['ours'][:80]}")
    for name, digest in digests.items():
        old = baseline.get("import_digests", {}).get(name)
        if old and old != digest:
            failures.append(f"table {name}: imported data changed since it was locked (digest {digest[:12]} vs {old[:12]})")

    if args.accept and not failures:
        baseline["locked"] = sorted(locked | {r["id"] for r in results if r["status"] == "match"})
        baseline["import_digests"] = {**baseline.get("import_digests", {}), **digests}
        PARITY.mkdir(exist_ok=True)
        BASELINE.write_text(json.dumps(baseline, indent=1))
        locked = set(baseline["locked"])
        print(f"locked {len(locked)} items")
    elif args.accept:
        print("not locking: the gate has failures")

    if args.tests:
        env = {"QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": ".", **{k: v for k, v in __import__("os").environ.items()}}
        suite = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x"], cwd=ROOT, env=env, capture_output=True, text=True)
        print("pytest:", (suite.stdout.strip().splitlines() or ["no output"])[-1])
        if suite.returncode:
            failures.append("pytest suite failed")
        if TABLES["VAT"]["path"].exists():
            smoke = subprocess.run([sys.executable, "tools/app_smoke.py", str(ROOT / "tools/parity/_smoke")], cwd=ROOT, env=env,
                                   capture_output=True, text=True)
            line = next((l for l in smoke.stdout.splitlines() if l.startswith("MEASURES THROUGH THE APP")), "no result line")
            print("real app:", line)
            if smoke.returncode or "0 different" not in line or "reopen: True" not in smoke.stdout:
                failures.append(f"real-app run failed: {line}")

    write_ledger(results, baseline, failures, notes)
    counts = {s: sum(1 for r in results if r["status"] == s) for s in ("match", "gap-reject", "DIFF", "CRASH")}
    print(f"replayed {len(results)} Power BI answers: {counts}; locked {len(locked)}")
    for n in notes:
        print("note:", n)
    for f in failures:
        print("FAIL:", f)
    print("PARITY GATE", "FAILED" if failures else "PASSED", "-> PARITY_LEDGER.md")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
