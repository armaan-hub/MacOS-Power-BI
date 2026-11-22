"""Exit-test items (Phase 1.5 A): statistics and averages over a Currency column are Currency, rounded to four decimals.

Power BI answers are read from the saved file for comparison only. The engine never reads them.
No guest VM connection required.
"""
from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path
from statistics import fmean, pstdev

import pytest

from tools import exit_check
from tools import exit_model
from tools.dax_oracle_diff import same

REPO_ROOT = Path(__file__).resolve().parents[1]
SAVED_ANSWERS = REPO_ROOT / "tools" / "parity" / "exit_pbi_answers.json"

CURRENCY_ITEMS = [
    "XT-AG-006",
    "XT-AG-030",
    "XT-ST-009",
    "XT-ST-010",
    "XT-ST-011",
    "XT-ST-012",
    "XT-ST-013",
    "XT-ST-019",
    "XT-ST-024",
]


@pytest.fixture(scope="module")
def xt_data() -> dict:
    return exit_model.generate_data()


@pytest.fixture(scope="module")
def saved_answers() -> dict[str, dict]:
    rows = json.loads(SAVED_ANSWERS.read_text(encoding="utf-8"))
    return {row["id"]: row for row in rows}


@pytest.fixture(scope="module")
def local_results(xt_data: dict, saved_answers: dict[str, dict]) -> dict[str, str]:
    items = [saved_answers[item_id] for item_id in CURRENCY_ITEMS]
    return {row["id"]: row["local"] for row in exit_check.run_local(items, data=xt_data)}


@pytest.mark.parametrize("item_id", CURRENCY_ITEMS)
def test_currency_statistic_matches_power_bi(item_id: str, saved_answers: dict[str, dict], local_results: dict[str, str]) -> None:
    expected = saved_answers[item_id]["powerbi"]
    local = local_results[item_id]
    assert not local.startswith("LOCAL-"), f"{item_id} refused or crashed: {local}"
    assert same(expected, local), f"{item_id} {saved_answers[item_id]['expr']}: Power BI {expected} local {local}"


def test_currency_average_is_rounded_to_four_decimals(local_results: dict[str, str]) -> None:
    value = Decimal(local_results["XT-AG-006"])
    assert value == value.quantize(Decimal("0.0001")), local_results["XT-AG-006"]


def _non_blank(rows: list[dict], column: str) -> list[float]:
    return [float(row[column]) for row in rows if row.get(column) is not None]


def _assert_unrounded(local: str, expected: float) -> None:
    value = Decimal(local)
    assert value != value.quantize(Decimal("0.0001")), f"non-Currency result was rounded to four decimals: {local}"
    assert math.isclose(float(value), expected, rel_tol=1e-9, abs_tol=1e-12), (local, expected)


def test_double_column_average_is_not_rounded(xt_data: dict) -> None:
    items = [{"id": "NC-DBL-AVG", "expr": "AVERAGE(XT_Sales[Discount])"}]
    local = exit_check.run_local(items, data=xt_data)[0]["local"]
    _assert_unrounded(local, fmean(_non_blank(xt_data["XT_Sales"], "Discount")))


def test_double_column_stdev_is_not_rounded(xt_data: dict) -> None:
    items = [{"id": "NC-DBL-STDEV", "expr": "STDEV.P(XT_Sales[Discount])"}]
    local = exit_check.run_local(items, data=xt_data)[0]["local"]
    _assert_unrounded(local, pstdev(_non_blank(xt_data["XT_Sales"], "Discount")))


def test_whole_number_column_average_is_not_rounded(xt_data: dict) -> None:
    items = [{"id": "NC-INT-AVG", "expr": "AVERAGE(XT_Sales[Quantity])"}]
    local = exit_check.run_local(items, data=xt_data)[0]["local"]
    _assert_unrounded(local, fmean(_non_blank(xt_data["XT_Sales"], "Quantity")))


# Phase 1.5 A round 2: the 17 probes that Power BI answered differently from the first round (RP-004 .. RP-079).
ROUNDING_ANSWERS = REPO_ROOT / "tools" / "parity" / "exit_pbi_answers_rounding.json"
ROUNDING_PROBES = [
    "RP-004", "RP-006", "RP-032", "RP-033", "RP-034", "RP-040", "RP-041", "RP-045", "RP-046",
    "RP-053", "RP-057", "RP-058", "RP-059", "RP-060", "RP-064", "RP-077", "RP-079",
]


@pytest.fixture(scope="module")
def rounding_answers() -> dict[str, dict]:
    rows = json.loads(ROUNDING_ANSWERS.read_text(encoding="utf-8"))
    return {row["id"]: row for row in rows}


@pytest.fixture(scope="module")
def rounding_local(xt_data: dict, rounding_answers: dict[str, dict]) -> dict[str, str]:
    items = [rounding_answers[item_id] for item_id in ROUNDING_PROBES]
    return {row["id"]: row["local"] for row in exit_check.run_local(items, data=xt_data)}


@pytest.mark.parametrize("item_id", ROUNDING_PROBES)
def test_rounding_probe_matches_power_bi(item_id: str, rounding_answers: dict[str, dict], rounding_local: dict[str, str]) -> None:
    expected = rounding_answers[item_id]["powerbi"]
    local = rounding_local[item_id]
    if expected.startswith("ERR:"):
        # Power BI raised an error: the local engine must raise the same error (a refusal or a NaN is not a match)
        assert local.startswith("LOCAL-REJECT:") and "division by zero" in local, f"{item_id}: Power BI {expected} local {local}"
        return
    assert not local.startswith("LOCAL-"), f"{item_id} refused or crashed: {local}"
    assert same(expected, local), f"{item_id} {rounding_answers[item_id]['expr']}: Power BI {expected} local {local}"


def test_double_column_average_over_divisor_is_not_rounded(xt_data: dict) -> None:
    items = [{"id": "NC-DBL-AVG-DIV", "expr": "AVERAGE(XT_Sales[Discount]) / 7"}]
    local = exit_check.run_local(items, data=xt_data)[0]["local"]
    _assert_unrounded(local, fmean(_non_blank(xt_data["XT_Sales"], "Discount")) / 7)


def test_double_column_average_times_literal_is_not_rounded(xt_data: dict) -> None:
    items = [{"id": "NC-DBL-AVG-MUL", "expr": "AVERAGE(XT_Sales[Discount]) * 3.7"}]
    local = exit_check.run_local(items, data=xt_data)[0]["local"]
    _assert_unrounded(local, fmean(_non_blank(xt_data["XT_Sales"], "Discount")) * 3.7)


def test_whole_number_column_average_times_literal_is_not_rounded(xt_data: dict) -> None:
    items = [{"id": "NC-INT-AVG-MUL", "expr": "AVERAGE(XT_Sales[Quantity]) * 3.7"}]
    local = exit_check.run_local(items, data=xt_data)[0]["local"]
    _assert_unrounded(local, fmean(_non_blank(xt_data["XT_Sales"], "Quantity")) * 3.7)


def test_double_column_one_row_stdev_stays_nan(xt_data: dict) -> None:
    # measured earlier: STDEV.S of one Double row is NaN (only a Currency row raises the division-by-zero error)
    items = [{"id": "NC-DBL-STDEV1", "expr": "CALCULATE(STDEV.S(XT_Sales[Discount]), XT_Sales[SalesKey] = 17)"}]
    local = exit_check.run_local(items, data=xt_data)[0]["local"]
    assert local == "NaN", local


# Phase 1.5 A round 3: MEDIAN of a Currency column is a Currency (HP-003/007/011 measured); MEDIAN of a Double column stays a Double.
HELDOUT_ANSWERS = REPO_ROOT / "tools" / "parity" / "exit_pbi_answers_heldout.json"
MEDIAN_TYPE_PROBES = ["HP-003", "HP-007", "HP-011"]


@pytest.fixture(scope="module")
def heldout_answers() -> dict[str, dict]:
    rows = json.loads(HELDOUT_ANSWERS.read_text(encoding="utf-8"))
    return {row["id"]: row for row in rows}


@pytest.mark.parametrize("item_id", MEDIAN_TYPE_PROBES)
def test_median_of_currency_column_type_matches_power_bi(item_id: str, heldout_answers: dict[str, dict], xt_data: dict) -> None:
    expected = heldout_answers[item_id]["powerbi"]
    local = exit_check.run_local([heldout_answers[item_id]], data=xt_data)[0]["local"]
    assert not local.startswith("LOCAL-"), f"{item_id} refused or crashed: {local}"
    assert same(expected, local), f"{item_id} {heldout_answers[item_id]['expr']}: Power BI {expected} local {local}"


def test_median_of_double_column_stays_double(xt_data: dict) -> None:
    items = [{"id": "NC-DBL-MED", "expr": "ISDOUBLE(MEDIAN(XT_Sales[Discount]))"}]
    local = exit_check.run_local(items, data=xt_data)[0]["local"]
    assert local == "True", local


def test_median_of_whole_number_column_is_not_currency(xt_data: dict) -> None:
    items = [{"id": "NC-INT-MED", "expr": "ISCURRENCY(MEDIAN(XT_Sales[Quantity]))"}]
    local = exit_check.run_local(items, data=xt_data)[0]["local"]
    assert local == "False", local
