"""Differential test tool comparing two DAX evaluation paths on generated data.

Run formulas through two evaluation paths on the same data and compare the answers.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import sys
from typing import Callable

from analytics_studio import dax_dates
from analytics_studio.measures import MeasureError, evaluate_measures
from tools.dax_oracle_diff import same

HEADERS = ["Sales", "Quantity", "Region", "Note", "OrderDate"]
COLUMN_TYPES = {
    "Sales": "decimal_number",
    "Quantity": "whole_number",
    "Region": "text",
    "Note": "text",
    "OrderDate": "date",
}

SALES_SPECIAL = [None, 0.0, 1e-9, -1e-9, 1e15, -1e15]
QUANTITY_SPECIAL = [None, 0, 1, -1]
REGIONS = ["East", "east", "EAST", "West", "west", "WEST", "North", "north", "South", "south", None]
NOTES = ["Paid", "Late", "Pending", "Cancelled", None]
ORDER_DATES = [
    "2020-01-15", "2020-07-20", "2021-03-10", "2021-11-25",
    "2022-05-04", "2022-12-31", "2023-02-28", "2023-08-14",
    "2024-02-29", "2024-10-10", "2025-01-01", "2025-06-15", None,
]

DEFAULT_FORMULAS = [
    # SUM/MIN/MAX/AVERAGE/COUNT/COUNTA/COUNTROWS/COUNTBLANK/DISTINCTCOUNT
    ("SUM_Sales", "SUM(Facts[Sales])"),
    ("SUM_Quantity", "SUM(Facts[Quantity])"),
    ("MIN_Sales", "MIN(Facts[Sales])"),
    ("MIN_Quantity", "MIN(Facts[Quantity])"),
    ("MIN_OrderDate", "MIN(Facts[OrderDate])"),
    ("MAX_Sales", "MAX(Facts[Sales])"),
    ("MAX_Quantity", "MAX(Facts[Quantity])"),
    ("MAX_OrderDate", "MAX(Facts[OrderDate])"),
    ("AVERAGE_Sales", "AVERAGE(Facts[Sales])"),
    ("AVERAGE_Quantity", "AVERAGE(Facts[Quantity])"),
    ("COUNT_Sales", "COUNT(Facts[Sales])"),
    ("COUNT_Quantity", "COUNT(Facts[Quantity])"),
    ("COUNT_OrderDate", "COUNT(Facts[OrderDate])"),
    ("COUNTA_Region", "COUNTA(Facts[Region])"),
    ("COUNTA_Note", "COUNTA(Facts[Note])"),
    ("COUNTROWS_Facts", "COUNTROWS(Facts)"),
    ("COUNTBLANK_Sales", "COUNTBLANK(Facts[Sales])"),
    ("COUNTBLANK_Quantity", "COUNTBLANK(Facts[Quantity])"),
    ("COUNTBLANK_Region", "COUNTBLANK(Facts[Region])"),
    ("COUNTBLANK_Note", "COUNTBLANK(Facts[Note])"),
    ("COUNTBLANK_OrderDate", "COUNTBLANK(Facts[OrderDate])"),
    ("DISTINCTCOUNT_Region", "DISTINCTCOUNT(Facts[Region])"),
    ("DISTINCTCOUNT_Note", "DISTINCTCOUNT(Facts[Note])"),
    ("DISTINCTCOUNT_Quantity", "DISTINCTCOUNT(Facts[Quantity])"),
    # Iterators: SUMX, AVERAGEX
    ("SUMX_Sales_Quantity", "SUMX(Facts, Facts[Sales] * Facts[Quantity])"),
    ("AVERAGEX_Sales", "AVERAGEX(Facts, Facts[Sales])"),
    ("AVERAGEX_Quantity", "AVERAGEX(Facts, Facts[Quantity])"),
    # CALCULATE with column predicates, ALL, REMOVEFILTERS, ALLEXCEPT, KEEPFILTERS
    ("CALCULATE_pred", 'CALCULATE(SUM(Facts[Sales]), Facts[Region] = "East")'),
    ("CALCULATE_pred_num", "CALCULATE(SUM(Facts[Sales]), Facts[Quantity] > 10)"),
    ("CALCULATE_ALL", "CALCULATE(SUM(Facts[Sales]), ALL(Facts[Region]))"),
    ("CALCULATE_REMOVEFILTERS", "CALCULATE(SUM(Facts[Sales]), REMOVEFILTERS(Facts[Region]))"),
    ("CALCULATE_ALLEXCEPT", "CALCULATE(SUM(Facts[Sales]), ALLEXCEPT(Facts, Facts[Region]))"),
    ("CALCULATE_KEEPFILTERS", 'CALCULATE(SUM(Facts[Sales]), KEEPFILTERS(Facts[Region] = "East"))'),
    # VALUES, DISTINCT, FILTER
    ("COUNTROWS_VALUES_Region", "COUNTROWS(VALUES(Facts[Region]))"),
    ("COUNTROWS_DISTINCT_Region", "COUNTROWS(DISTINCT(Facts[Region]))"),
    ("SUMX_FILTER", "SUMX(FILTER(Facts, Facts[Sales] > 0), Facts[Sales])"),
    ("COUNTROWS_FILTER", 'COUNTROWS(FILTER(Facts, Facts[Region] = "West"))'),
    # RANKX
    ("RANKX_Region", "RANKX(ALL(Facts[Region]), CALCULATE(SUM(Facts[Sales])))"),
    # CONCATENATEX with ORDER BY
    ("CONCATENATEX_Region", 'CONCATENATEX(VALUES(Facts[Region]), Facts[Region], ", ", Facts[Region], ASC)'),
    # YEAR/MAX on OrderDate
    ("YEAR_MAX_OrderDate", "YEAR(MAX(Facts[OrderDate]))"),
    ("YEAR_MIN_OrderDate", "YEAR(MIN(Facts[OrderDate]))"),
    # DIVIDE
    ("DIVIDE_Sales_Quantity", "DIVIDE(SUM(Facts[Sales]), SUM(Facts[Quantity]))"),
    ("DIVIDE_with_alt", "DIVIDE(SUM(Facts[Sales]), 0, -1)"),
    # IF/SWITCH on aggregates
    ("IF_agg", 'IF(SUM(Facts[Sales]) > 0, "Positive", "Non-positive")'),
    ("SWITCH_agg", 'SWITCH(TRUE(), SUM(Facts[Quantity]) > 100, "High", SUM(Facts[Quantity]) > 0, "Low", "None")'),
]


def generate_table(row_count: int, seed: int = 1) -> dict:
    """Generate a seeded Facts table with typed columns."""
    rng = random.Random(seed)
    rows: list[dict] = []
    for _ in range(row_count):
        if rng.random() < 0.2:
            sales = rng.choice(SALES_SPECIAL)
        else:
            sales = round(rng.uniform(-10000, 10000), 2)

        if rng.random() < 0.2:
            quantity = rng.choice(QUANTITY_SPECIAL)
        else:
            quantity = rng.randint(-100, 100)

        rows.append({
            "Sales": sales,
            "Quantity": quantity,
            "Region": rng.choice(REGIONS),
            "Note": rng.choice(NOTES),
            "OrderDate": rng.choice(ORDER_DATES),
        })
    return {
        "name": "Facts",
        "headers": list(HEADERS),
        "rows": rows,
        "column_types": dict(COLUMN_TYPES),
    }


def reference_path(expression: str, table: dict) -> str:
    """Evaluation path using analytics_studio.measures.evaluate_measures."""
    facts_rows = table["rows"]
    headers = table["headers"]
    column_types = table.get("column_types", COLUMN_TYPES)
    name = table.get("name", "Facts")
    active_id = table.get("id", name.lower())
    table_context = [{
        "id": active_id,
        "name": name,
        "headers": headers,
        "rows": facts_rows,
        "column_types": column_types,
    }]
    try:
        value = evaluate_measures(
            [{"name": "Probe__", "expression": expression}],
            facts_rows,
            headers,
            name,
            measure_names=["Probe__"],
            table_context=table_context,
            active_table_id=active_id,
        )["Probe__"]
    except MeasureError as error:
        return f"LOCAL-REJECT:{error}"
    except Exception as error:
        return f"LOCAL-CRASH:{type(error).__name__}:{error}"
    if isinstance(value, dax_dates.DaxDateTime):
        try:
            return dax_dates.oracle_text(value)
        except MeasureError as error:
            return f"LOCAL-REJECT:{error}"
    return "BLANK" if value is None else str(value)


PATHS: dict[str, Callable[[str, dict], str]] = {
    "reference": reference_path,
}


def load_formulas(path: str | Path) -> list[tuple[str, str]]:
    """Load formulas from a JSON file (list of strings or list of objects with name and expr)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    formulas: list[tuple[str, str]] = []
    for index, item in enumerate(data):
        if isinstance(item, str):
            formulas.append((f"F{index + 1}", item))
        elif isinstance(item, dict):
            name = item.get("name", f"F{index + 1}")
            expr = item.get("expr", item.get("expression", ""))
            formulas.append((name, expr))
    return formulas


def classify_result(left_res: str, right_res: str) -> str:
    """Classify the comparison between left and right results."""
    if left_res.startswith("LOCAL-CRASH:") or right_res.startswith("LOCAL-CRASH:"):
        return "CRASH"
    if left_res.startswith("LOCAL-REJECT:") and right_res.startswith("LOCAL-REJECT:"):
        return "both-reject"
    if left_res.startswith("LOCAL-REJECT:") or right_res.startswith("LOCAL-REJECT:"):
        return "DIFF"
    if same(left_res, right_res):
        return "same"
    return "DIFF"


def render_table(rows: list[dict]) -> str:
    """Format comparison rows as a text table."""
    headers = ["name", "status", "left", "right"]
    col_widths = {
        "name": max(4, max((len(r["name"]) for r in rows), default=4)),
        "status": max(6, max((len(r["status"]) for r in rows), default=6)),
        "left": 40,
        "right": 40,
    }
    header_line = (
        f"{headers[0].ljust(col_widths['name'])}  "
        f"{headers[1].ljust(col_widths['status'])}  "
        f"{headers[2].ljust(col_widths['left'])}  "
        f"{headers[3].ljust(col_widths['right'])}"
    )
    lines = [header_line]
    for r in rows:
        left_disp = (r["left"][:37] + "...") if len(r["left"]) > 40 else r["left"]
        right_disp = (r["right"][:37] + "...") if len(r["right"]) > 40 else r["right"]
        line = (
            f"{r['name'].ljust(col_widths['name'])}  "
            f"{r['status'].ljust(col_widths['status'])}  "
            f"{left_disp.ljust(col_widths['left'])}  "
            f"{right_disp.ljust(col_widths['right'])}"
        )
        lines.append(line)
    return "\n".join(lines)


def run_diff(
    left_name: str = "reference",
    right_name: str = "reference",
    row_count: int = 2000,
    seed: int = 1,
    formulas: list[tuple[str, str]] | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """Run formulas through left and right paths on generated data."""
    if left_name not in PATHS:
        raise ValueError(f"Unknown left path {left_name!r}; known: {', '.join(PATHS)}")
    if right_name not in PATHS:
        raise ValueError(f"Unknown right path {right_name!r}; known: {', '.join(PATHS)}")

    left_fn = PATHS[left_name]
    right_fn = PATHS[right_name]
    table = generate_table(row_count, seed)
    formula_list = formulas if formulas is not None else DEFAULT_FORMULAS

    rows: list[dict] = []
    counts = {"same": 0, "both-reject": 0, "DIFF": 0, "CRASH": 0}

    for name, expr in formula_list:
        left_res = left_fn(expr, table)
        right_res = right_fn(expr, table)
        status = classify_result(left_res, right_res)
        counts[status] = counts.get(status, 0) + 1
        rows.append({
            "name": name,
            "expr": expr,
            "status": status,
            "left": left_res,
            "right": right_res,
        })

    return rows, counts


def main(argv: list[str] | None = None) -> int:
    """Parse command line, run differential test, print summary table and counts."""
    parser = argparse.ArgumentParser(description="Differential test tool comparing two DAX evaluation paths.")
    parser.add_argument("--left", default="reference", help="left path name (default: reference)")
    parser.add_argument("--right", default="reference", help="right path name (default: reference)")
    parser.add_argument("--rows", type=int, default=2000, help="row count for generated table (default: 2000)")
    parser.add_argument("--seed", type=int, default=1, help="random seed (default: 1)")
    parser.add_argument("--formulas", default=None, metavar="FILE", help="path to JSON file with formulas")
    parser.add_argument("--json", dest="json_out", default=None, metavar="OUT", help="write rows as JSON")

    args = parser.parse_args(argv)

    formulas = load_formulas(args.formulas) if args.formulas else None
    rows, counts = run_diff(
        left_name=args.left,
        right_name=args.right,
        row_count=args.rows,
        seed=args.seed,
        formulas=formulas,
    )

    print(render_table(rows))
    print(f"\nTotals: {len(rows)} formulas | same: {counts.get('same', 0)} | both-reject: {counts.get('both-reject', 0)} | DIFF: {counts.get('DIFF', 0)} | CRASH: {counts.get('CRASH', 0)}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return 1 if (counts.get("DIFF", 0) > 0 or counts.get("CRASH", 0) > 0) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
