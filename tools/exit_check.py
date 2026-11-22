"""Chained Power BI answer-check runner for exit-test model.

Evaluates batches of DAX expressions over the XT_ exit model on Power BI Desktop (guest)
and/or the local evaluator, and compares results.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

from analytics_studio import dax_dates
from analytics_studio.measures import MeasureError, evaluate_measures
from tools import dax_oracle_diff as dax
from tools import exit_model


def _ensure_blocking() -> None:
    for fd in (0, 1, 2):
        try:
            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            if fl & os.O_NONBLOCK:
                fcntl.fcntl(fd, fcntl.F_SETFL, fl & ~os.O_NONBLOCK)
        except Exception:
            pass


def run_power_bi(items: list[dict[str, str]], port_: str, chunk: int = 200) -> list[dict[str, Any]]:
    """Evaluate DAX expressions on guest Power BI in a single session with model installed and dropped."""
    with dax.guest_lock():
        try:
            data = exit_model.generate_data()
            exit_model.install_guest_model(port_, data)
            exprs = [it["expr"] for it in items]
            answers = dax.power_bi(exprs, port_, chunk=chunk)
            results = []
            for it, ans in zip(items, answers):
                results.append({
                    "id": it["id"],
                    "expr": it["expr"],
                    "powerbi": ans,
                })
            return results
        finally:
            exit_model.drop_guest_model(port_)


def run_local(items: list[dict[str, str]], data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Evaluate DAX expressions using local evaluator with exit_model.local_context()."""
    if data is None:
        data = exit_model.generate_data()
    tables, rels = exit_model.local_context(data)
    home_table = "xt_sales"
    table_map = {t["id"]: t for t in tables}
    t_home = table_map[home_table]

    results = []
    for it in items:
        expr = it["expr"]
        t0 = time.perf_counter()
        ans_str: str
        try:
            val = evaluate_measures(
                [{"name": "Probe__", "expression": expr, "home_table_id": home_table}],
                t_home["rows"],
                t_home["headers"],
                "XT_Sales",
                measure_names=["Probe__"],
                table_context=tables,
                relationships=rels,
                active_table_id=home_table,
            )["Probe__"]
            if isinstance(val, dax_dates.DaxDateTime):
                try:
                    ans_str = dax_dates.oracle_text(val)
                except MeasureError as err:
                    ans_str = f"LOCAL-REJECT:{err}"
            elif val is None:
                ans_str = "BLANK"
            else:
                ans_str = str(val)
        except MeasureError as err:
            ans_str = f"LOCAL-REJECT:{err}"
        except Exception as err:
            ans_str = f"LOCAL-CRASH:{type(err).__name__}:{err}"

        duration_ms = (time.perf_counter() - t0) * 1000.0
        results.append({
            "id": it["id"],
            "expr": expr,
            "local": ans_str,
            "time_ms": round(duration_ms, 2),
        })
    return results


def compare_results(path_a: str, path_b: str) -> dict[str, Any]:
    """Compare Power BI answers (or file A) with local answers (file B)."""
    items_a = json.loads(Path(path_a).read_text(encoding="utf-8"))
    items_b = json.loads(Path(path_b).read_text(encoding="utf-8"))

    map_a = {it["id"]: it for it in items_a}
    map_b = {it["id"]: it for it in items_b}

    only_in_a = set(map_a.keys()) - set(map_b.keys())
    only_in_b = set(map_b.keys()) - set(map_a.keys())

    right_count = 0
    wrong_count = 0
    refused_count = 0
    both_error_count = 0
    crash_count = 0

    wrong_items = []
    items_with_time = []

    for item_id, item_b in map_b.items():
        if item_id not in map_a:
            continue
        item_a = map_a[item_id]
        pbi_ans = item_a.get("powerbi", item_a.get("actual", ""))
        loc_ans = item_b.get("local", item_b.get("actual", ""))
        expr = item_b.get("expr", item_a.get("expr", ""))
        time_ms = item_b.get("time_ms", 0.0)
        items_with_time.append({"id": item_id, "expr": expr, "time_ms": time_ms})

        if loc_ans.startswith("LOCAL-CRASH:"):
            crash_count += 1
            wrong_items.append({"id": item_id, "expr": expr, "pbi": pbi_ans, "local": loc_ans, "category": "crash"})
        elif loc_ans.startswith("LOCAL-REJECT:"):
            if pbi_ans.startswith("ERR:"):
                both_error_count += 1
            else:
                refused_count += 1
                wrong_items.append({"id": item_id, "expr": expr, "pbi": pbi_ans, "local": loc_ans, "category": "refused"})
        elif dax.same(pbi_ans, loc_ans):
            right_count += 1
        else:
            wrong_count += 1
            wrong_items.append({"id": item_id, "expr": expr, "pbi": pbi_ans, "local": loc_ans, "category": "mismatch"})

    items_with_time.sort(key=lambda x: x["time_ms"], reverse=True)
    slowest_20 = items_with_time[:20]

    return {
        "right": right_count,
        "wrong": wrong_count,
        "refused": refused_count,
        "both_error": both_error_count,
        "crash": crash_count,
        "slowest_20": slowest_20,
        "wrong_items": wrong_items,
        "only_in_a_count": len(only_in_a),
        "only_in_b_count": len(only_in_b),
        "only_in_a": sorted(only_in_a),
        "only_in_b": sorted(only_in_b),
    }


def print_comparison_report(stats: dict[str, Any]) -> None:
    """Print the comparison summary, slowest 20 items, and wrong items."""
    _ensure_blocking()
    print("\n### Comparison Summary")
    print(f"- **Right:** {stats['right']}")
    print(f"- **Wrong:** {stats['wrong']}")
    print(f"- **Refused:** {stats['refused']}")
    print(f"- **Both error (right):** {stats.get('both_error', 0)}")
    print(f"- **Crash:** {stats['crash']}")
    print(f"- **Only in File A:** {stats.get('only_in_a_count', 0)}")
    print(f"- **Only in File B:** {stats.get('only_in_b_count', 0)}")
    if stats.get('only_in_a'):
        print(f"  - IDs in A only: {stats['only_in_a']}")
    if stats.get('only_in_b'):
        print(f"  - IDs in B only: {stats['only_in_b']}")

    print("\n### 20 Slowest Items")
    print("| ID | Duration (ms) | DAX Expression |")
    print("|---|---|---|")
    for it in stats["slowest_20"]:
        print(f"| {it['id']} | {it['time_ms']:.2f} | `{it['expr']}` |")

    print("\n### Wrong Items")
    if not stats["wrong_items"]:
        print("None! All items matched Power BI.")
    else:
        print("| ID | Category | Power BI | Local | DAX Expression |")
        print("|---|---|---|---|---|")
        for it in stats["wrong_items"]:
            pbi = str(it['pbi']).replace('\n', ' ')
            loc = str(it['local']).replace('\n', ' ')
            print(f"| {it['id']} | {it['category']} | `{pbi}` | `{loc}` | `{it['expr']}` |")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Chained Power BI answer-check runner for exit model.")
    parser.add_argument("input_file", nargs="?", help="JSON input file with list of {'id', 'expr'}")
    parser.add_argument("--power-bi", action="store_true", help="Evaluate items on Power BI guest")
    parser.add_argument("--local", action="store_true", help="Evaluate items locally")
    parser.add_argument("--output", "-o", help="Output JSON path")
    parser.add_argument("--compare", nargs=2, metavar=("A", "B"), help="Compare two result JSON files")

    args = parser.parse_args()

    if args.compare:
        stats = compare_results(args.compare[0], args.compare[1])
        print_comparison_report(stats)
        return

    if not args.input_file:
        parser.print_help()
        sys.exit(1)

    items = json.loads(Path(args.input_file).read_text(encoding="utf-8"))

    if args.power_bi:
        port_ = exit_model.get_guest_port()
        results = run_power_bi(items, port_)
        output_path = args.output or args.input_file.replace(".json", "_pbi.json")
        Path(output_path).write_text(json.dumps(results, indent=2), encoding="utf-8")
        _ensure_blocking()
        print(f"Saved {len(results)} Power BI answers to {output_path}")

    if args.local:
        results = run_local(items)
        output_path = args.output or args.input_file.replace(".json", "_local.json")
        Path(output_path).write_text(json.dumps(results, indent=2), encoding="utf-8")
        _ensure_blocking()
        print(f"Saved {len(results)} local answers to {output_path}")


if __name__ == "__main__":
    main()
