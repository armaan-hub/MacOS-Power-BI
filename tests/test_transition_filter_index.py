"""Tests for indexed context transition in transition_filters.

Before (main):
  - 20,000 rows QUADRATIC: projected ~1,488s (timed out >300s)
After (antigravity/transition-index-a5):
  - 20,000 rows QUADRATIC: 59.474s (peak MB 55.1)
"""

from decimal import Decimal
import time
import pytest

from analytics_studio.measures import evaluate_measures, MeasureError
from analytics_studio.power_query_values import PowerQueryCellError


def test_transition_filter_duplicates_blanks_case_expected():
    """SUMX(Facts, CALCULATE(SUM(Facts[Sales]))) and COUNTROWS on duplicate rows, BLANK cells, mixed-case text."""
    rows = [
        {"Sales": Decimal(10), "Region": "East", "Note": "Paid"},
        {"Sales": Decimal(10), "Region": "East", "Note": "Paid"},
        {"Sales": Decimal(20), "Region": "east", "Note": "Paid"},
        {"Sales": Decimal(30), "Region": "West", "Note": None},
        {"Sales": Decimal(40), "Region": "West", "Note": None},
        {"Sales": None, "Region": "North", "Note": "Late"},
        {"Sales": Decimal(50), "Region": "North", "Note": "Late"},
    ]
    # Hand calculation for transition:
    # In DAX, context transition for a row transforms the row into column equality filters on all columns of the table.
    # Note: string equality in cell_key is case-insensitive ("East" == "east").
    # Row 0: Sales=10, Region="East", Note="Paid".
    #   Matches: Row 0 (10, East, Paid), Row 1 (10, East, Paid). Row 2 has Sales=20 so it does not match Sales=10.
    #   CALCULATE(SUM(Sales)) = 10 + 10 = 20.
    #   CALCULATE(COUNTROWS) = 2.
    # Row 1: same as Row 0 -> SUM=20, COUNTROWS=2.
    # Row 2: Sales=20, Region="east", Note="Paid".
    #   Matches: Row 2 only.
    #   CALCULATE(SUM(Sales)) = 20.
    #   CALCULATE(COUNTROWS) = 1.
    # Row 3: Sales=30, Region="West", Note=None.
    #   Matches: Row 3 only (Row 4 has Sales=40).
    #   CALCULATE(SUM(Sales)) = 30.
    #   CALCULATE(COUNTROWS) = 1.
    # Row 4: Sales=40, Region="West", Note=None.
    #   Matches: Row 4 only.
    #   CALCULATE(SUM(Sales)) = 40.
    #   CALCULATE(COUNTROWS) = 1.
    # Row 5: Sales=None, Region="North", Note="Late".
    #   Matches: Row 5 only (Row 6 has Sales=50).
    #   CALCULATE(SUM(Sales)) = None / 0. In DAX SUM of BLANK is None (or Decimal(0) in SUMX accumulator).
    #   CALCULATE(COUNTROWS) = 1.
    # Row 6: Sales=50, Region="North", Note="Late".
    #   Matches: Row 6 only.
    #   CALCULATE(SUM(Sales)) = 50.
    #   CALCULATE(COUNTROWS) = 1.
    # Total SUMX(CALCULATE(SUM(Sales))):
    #   20 + 20 + 20 + 30 + 40 + 0 + 50 = 180.
    # Total SUMX(CALCULATE(COUNTROWS)):
    #   2 + 2 + 1 + 1 + 1 + 1 + 1 = 9.

    headers = ["Sales", "Region", "Note"]
    types = {"Sales": "decimal_number", "Region": "text", "Note": "text"}
    context = [{"id": "facts", "name": "Facts", "headers": headers, "rows": rows, "column_types": types}]

    res_sum = evaluate_measures(
        [{"name": "P", "expression": "SUMX(Facts, CALCULATE(SUM(Facts[Sales])))"}],
        rows, headers, "Facts", measure_names=["P"], table_context=context, active_table_id="facts"
    )["P"]
    assert res_sum == Decimal(180)

    res_cnt = evaluate_measures(
        [{"name": "P", "expression": "SUMX(Facts, CALCULATE(COUNTROWS(Facts)))"}],
        rows, headers, "Facts", measure_names=["P"], table_context=context, active_table_id="facts"
    )["P"]
    assert res_cnt == Decimal(9)


def test_transition_filter_allexcept_keeps_other_columns_filtered():
    """ALLEXCEPT / ALL(column) inside transition still keeps the other columns filtered."""
    rows = [
        {"Sales": Decimal(10), "Region": "East", "Category": "A"},
        {"Sales": Decimal(10), "Region": "East", "Category": "B"},
        {"Sales": Decimal(20), "Region": "West", "Category": "A"},
        {"Sales": Decimal(20), "Region": "West", "Category": "B"},
    ]
    # In CALCULATE(SUM(Facts[Sales]), ALL(Facts[Category])):
    # For row 0 (Sales=10, East, A): transition filters Sales=10, Region=East, Category=A.
    # ALL(Facts[Category]) clears the Category filter, keeping Sales=10 and Region=East.
    # Matching rows in Facts: row 0 and row 1.
    # CALCULATE(SUM(Sales)) = 10 + 10 = 20.
    # For row 1 (Sales=10, East, B): clears Category -> Sales=10, Region=East -> rows 0 and 1 -> SUM = 20.
    # For row 2 (Sales=20, West, A): clears Category -> Sales=20, Region=West -> rows 2 and 3 -> SUM = 20 + 20 = 40.
    # For row 3 (Sales=20, West, B): clears Category -> Sales=20, Region=West -> rows 2 and 3 -> SUM = 40.
    # Total SUMX = 20 + 20 + 40 + 40 = 120.
    headers = ["Sales", "Region", "Category"]
    types = {"Sales": "decimal_number", "Region": "text", "Category": "text"}
    context = [{"id": "facts", "name": "Facts", "headers": headers, "rows": rows, "column_types": types}]

    res = evaluate_measures(
        [{"name": "P", "expression": "SUMX(Facts, CALCULATE(SUM(Facts[Sales]), ALL(Facts[Category])))"}],
        rows, headers, "Facts", measure_names=["P"], table_context=context, active_table_id="facts"
    )["P"]
    assert res == Decimal(120)


def test_transition_filter_power_query_error_cell():
    """A Power Query error cell in the table still raises the same MeasureError message as on main."""
    rows = [
        {"Sales": Decimal(10), "ErrorCol": PowerQueryCellError("Expression.Error", "custom error message")}
    ]
    headers = ["Sales", "ErrorCol"]
    types = {"Sales": "decimal_number", "ErrorCol": "text"}
    context = [{"id": "facts", "name": "Facts", "headers": headers, "rows": rows, "column_types": types}]

    with pytest.raises(MeasureError) as exc_info:
        evaluate_measures(
            [{"name": "P", "expression": "SUMX(Facts, CALCULATE(SUM(Facts[Sales])))"}],
            rows, headers, "Facts", measure_names=["P"], table_context=context, active_table_id="facts"
        )
    assert str(exc_info.value) == (
        "Column 'ErrorCol' contains a Power Query cell error at row 1: custom error message. "
        "Remove or replace the error before evaluating this DAX expression."
    )


def test_transition_filter_derived_table_row_and_low_cardinality():
    """A row that is not in the table (iterated row from a derived/other table) and a table of 30+ rows with only 3 distinct values per column."""
    # Table Facts has 36 rows with 3 distinct values per column
    regions = ["East", "West", "North"]
    categories = ["Cat1", "Cat2", "Cat3"]
    rows = []
    for i in range(36):
        rows.append({
            "Sales": Decimal((i % 3 + 1) * 10),
            "Region": regions[i % 3],
            "Category": categories[(i // 3) % 3],
        })
    headers = ["Sales", "Region", "Category"]
    types = {"Sales": "decimal_number", "Region": "text", "Category": "text"}
    context = [
        {"id": "facts", "name": "Facts", "headers": headers, "rows": rows, "column_types": types},
    ]
    # Iterated derived table with lineage to Facts[Region]: TREATAS({"South"}, Facts[Region])
    # "South" is not present in Facts[Region].
    # Context transition applies Region="South" filter to Facts, yielding empty rows.
    # CALCULATE(COUNTROWS(Facts)) is BLANK / None, so SUMX is None.
    res = evaluate_measures(
        [{"name": "P", "expression": 'SUMX(TREATAS({"South"}, Facts[Region]), CALCULATE(COUNTROWS(Facts)))'}],
        rows, headers, "Facts", measure_names=["P"], table_context=context, active_table_id="facts"
    )["P"]
    assert res is None


def test_transition_filter_speed_20000_rows():
    """Speed: SUMX(Facts, CALCULATE(SUM(Facts[Sales]))) on 20,000 generated rows finishes in under 120s."""
    import random
    rng = random.Random(1)
    regions = ["East", "West", "North", "South"]
    notes = ["Paid", "Late", None]
    rows = [
        {
            "Sales": round(Decimal(str(round(rng.random() * 100, 2))), 2),
            "Quantity": rng.randint(0, 50),
            "Region": rng.choice(regions),
            "Note": rng.choice(notes),
        }
        for _ in range(20000)
    ]
    headers = ["Sales", "Quantity", "Region", "Note"]
    types = {"Sales": "decimal_number", "Quantity": "whole_number", "Region": "text", "Note": "text"}
    context = [{"id": "facts", "name": "Facts", "headers": headers, "rows": rows, "column_types": types}]

    started = time.perf_counter()
    ans = evaluate_measures(
        [{"name": "P", "expression": "SUMX(Facts, CALCULATE(SUM(Facts[Sales])))"}],
        rows, headers, "Facts", measure_names=["P"], table_context=context, active_table_id="facts"
    )["P"]
    elapsed = time.perf_counter() - started
    assert elapsed < 120.0
    assert ans is not None
