"""Exit-test items (Phase 1.4): four DAX formulas that the local engine refused although Power BI answers them.

XT-CA-009: a table filter on XT_Sales whose rows have blank CustomerKey values (two common one-side tables through the bridge).
XT-TI-057: SAMEPERIODLASTYEAR over a DATESYTD date set.
XT-BV-023: a VAR read from the iterator row compared with a text column.
XT-TX-029: IF(HASONEVALUE(c), VALUES(c), "Many") in a scalar position.

Power BI answers are read from the saved file for comparison only. The engine never reads them.
No guest VM connection required.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import exit_check
from tools import exit_model
from tools.dax_oracle_diff import same

REPO_ROOT = Path(__file__).resolve().parents[1]
SAVED_ANSWERS = REPO_ROOT / "tools" / "parity" / "exit_pbi_answers.json"

FIXED_ITEMS = ["XT-CA-009", "XT-TI-057", "XT-BV-023", "XT-TX-029"]

CONTROLS = {
    # near-miss shapes that must keep their refusal or error (exact text checked where it is stable)
    "XT-CA-009": [
        ("CALCULATE(SUM(XT_Sales[SalesAmount]), XT_Sales[Quantity] > 10 && XT_Product[Category] = \"Cat_2\")",
         "must reference columns of exactly one table"),
    ],
    "XT-TI-057": [
        ("CALCULATE(SUM(XT_Sales[SalesAmount]), SAMEPERIODLASTYEAR(DATESQTD(XT_Date[Date])))",
         "SAMEPERIODLASTYEAR needs one marked date-column reference."),
        ("CALCULATE(SUM(XT_Sales[SalesAmount]), SAMEPERIODLASTYEAR(FILTER(XT_Date, XT_Date[Year] = 2024)))",
         "SAMEPERIODLASTYEAR needs one marked date-column reference."),
    ],
    "XT-BV-023": [
        ("SUMX(VALUES(XT_Product[Category]), VAR c = XT_Product[Category] RETURN CALCULATE(SUM(XT_Budget[BudgetAmount]), XT_Budget[YearMonth] = c))",
         "DAX comparison operations do not support comparing values of type Integer with values of type Text."),
        ("CALCULATE(SUM(XT_Budget[BudgetAmount]), XT_Budget[Category] = 5)",
         "DAX comparison operations do not support comparing values of type Text with values of type Integer."),
    ],
    "XT-TX-029": [
        ("VALUES(XT_Product[Category])", "A table of multiple values was supplied where a single value was expected."),
        ("CALCULATE(IF(HASONEVALUE(XT_Region[RegionKey]), VALUES(XT_Product[Category]), \"Many\"), XT_Product[Category] = \"Cat_2\")",
         "IF cannot return a table in one branch and a single value in another."),
    ],
}


@pytest.fixture(scope="module")
def xt_data() -> dict:
    return exit_model.generate_data()


@pytest.fixture(scope="module")
def saved_answers() -> dict[str, dict]:
    rows = json.loads(SAVED_ANSWERS.read_text(encoding="utf-8"))
    return {row["id"]: row for row in rows}


@pytest.fixture(scope="module")
def local_results(xt_data: dict, saved_answers: dict[str, dict]) -> dict[str, str]:
    items = [saved_answers[item_id] for item_id in FIXED_ITEMS]
    return {row["id"]: row["local"] for row in exit_check.run_local(items, data=xt_data)}


@pytest.mark.parametrize("item_id", FIXED_ITEMS)
def test_fixed_formula_matches_power_bi(item_id: str, local_results: dict[str, str], saved_answers: dict[str, dict]) -> None:
    local = local_results[item_id]
    assert not local.startswith("LOCAL-REJECT"), local
    assert same(saved_answers[item_id]["powerbi"], local), (saved_answers[item_id]["powerbi"], local)


@pytest.mark.parametrize("item_id", FIXED_ITEMS)
def test_near_miss_controls_keep_their_refusal(item_id: str, xt_data: dict) -> None:
    items = [{"id": f"{item_id}-control-{index}", "expr": expr} for index, (expr, _) in enumerate(CONTROLS[item_id])]
    results = exit_check.run_local(items, data=xt_data)
    for (expr, expected), result in zip(CONTROLS[item_id], results):
        local = result["local"]
        assert local.startswith("LOCAL-REJECT"), (expr, local)
        assert expected in local, (expr, local)


def test_xt_ca_009_control_filter_on_two_paths_matches_independent_sum(xt_data: dict) -> None:
    # near miss: an outer Category filter and an inner FILTER(XT_Sales, ...) on another column, computed from the raw rows
    expr = "CALCULATE(SUM(XT_Sales[SalesAmount]), FILTER(XT_Product, XT_Product[Category] = \"Cat_2\"), FILTER(XT_Sales, XT_Sales[Quantity] > 10))"
    local = exit_check.run_local([{"id": "XT-CA-009-control", "expr": expr}], data=xt_data)[0]["local"]
    category = {row["ProductKey"]: row["Category"] for row in xt_data["XT_Product"]}
    expected = sum(
        (row["SalesAmount"] for row in xt_data["XT_Sales"] if row["Quantity"] > 10 and category.get(row["ProductKey"]) == "Cat_2"),
        start=type(xt_data["XT_Sales"][0]["SalesAmount"])("0"),
    )
    assert same(str(expected), local), (str(expected), local)


def _three_common_tables() -> tuple[list[dict], list[dict], list[dict]]:
    """A small fact F with three one-side tables A, B, C and a bridge X many-to-one to all three (three common one-side tables)."""
    def table(name: str, headers: list[str], rows: list[dict], types: dict[str, str]) -> dict:
        return {"id": name.lower(), "name": name, "headers": headers, "rows": rows, "column_types": types}

    tables = [
        table("F", ["Key_A", "Key_B", "Key_C", "Amount"],
              [{"Key_A": "1", "Key_B": "1", "Key_C": "1", "Amount": "10"},
               {"Key_A": None, "Key_B": "1", "Key_C": "1", "Amount": "20"}],
              {"Key_A": "text", "Key_B": "text", "Key_C": "text", "Amount": "whole_number"}),
        table("A", ["Key_A"], [{"Key_A": "1"}], {"Key_A": "text"}),
        table("B", ["Key_B"], [{"Key_B": "1"}], {"Key_B": "text"}),
        table("C", ["Key_C"], [{"Key_C": "1"}], {"Key_C": "text"}),
        table("X", ["Key_A", "Key_B", "Key_C"], [{"Key_A": "1", "Key_B": "1", "Key_C": "1"}],
              {"Key_A": "text", "Key_B": "text", "Key_C": "text"}),
    ]

    def rel(name: str, source: str, column: str, target: str) -> dict:
        return {
            "relationship_version": 1, "id": name, "from": column, "to": column,
            "from_table_id": source, "from_column": column, "to_table_id": target, "to_column": column,
            "cardinality": "many_to_one", "is_active": True, "cross_filter_direction": "single",
        }

    relationships = [
        rel("f_a", "f", "Key_A", "a"), rel("f_b", "f", "Key_B", "b"), rel("f_c", "f", "Key_C", "c"),
        rel("x_a", "x", "Key_A", "a"), rel("x_b", "x", "Key_B", "b"), rel("x_c", "x", "Key_C", "c"),
    ]
    return tables, relationships, tables[0]["rows"]


def test_three_common_one_side_tables_with_blank_key_stay_refused() -> None:
    # XT-CA-009 scope: blank members are allowed with one or two common one-side tables only; three is unverified, so refused
    from analytics_studio.measures import MeasureError, evaluate_measures

    tables, relationships, rows = _three_common_tables()
    with pytest.raises(MeasureError, match="points at a key with no match"):
        evaluate_measures(
            [{"name": "Probe__", "expression": "CALCULATE(SUM(F[Amount]), FILTER(F, F[Amount] > 0))", "home_table_id": "f"}],
            rows, ["Key_A", "Key_B", "Key_C", "Amount"], "F",
            measure_names=["Probe__"], table_context=tables, relationships=relationships, active_table_id="f",
        )
