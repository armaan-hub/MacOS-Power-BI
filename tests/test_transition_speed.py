"""Tests for context transition speed: rows_matching helper and BlankSet cache.

Verifies:
1. Expected values for the 26 design formulas match old baseline.
2. Nested context transitions and filter identity checks (ALLSELECTED, SUMMARIZE, ALL, KEEPFILTERS).
3. rows_matching unit cases: empty dict, list value, out-of-range position, disjoint pair, order preserved.
"""

from decimal import Decimal
import random
import pytest

from analytics_studio.measures import BlankSet, evaluate_measures, rows_matching


def _build_test_data():
    random.seed(42)
    regions = ["East", "east", "West", "North"]
    notes = ["Paid", "Late", "Overdue", None]

    rows = []
    for i in range(400):
        rows.append({
            "ID": i + 1,
            "DimID": (i % 20) + 1,
            "Sales": Decimal(random.randint(10, 100)),
            "Quantity": random.randint(1, 10),
            "Region": random.choice(regions),
            "Note": random.choice(notes),
            "OrderDate": f"2023-01-{(i % 28) + 1:02d}",
        })

    rows.append(dict(rows[0]))
    rows.append(dict(rows[10]))

    dim_rows = [{"DimID": i, "Category": f"Cat_{i % 5}"} for i in range(1, 21)]

    facts_table = {
        "id": "Facts",
        "name": "Facts",
        "columns": ["ID", "DimID", "Sales", "Quantity", "Region", "Note", "OrderDate"],
        "headers": ["ID", "DimID", "Sales", "Quantity", "Region", "Note", "OrderDate"],
        "types": {
            "ID": "whole_number",
            "DimID": "whole_number",
            "Sales": "decimal_number",
            "Quantity": "whole_number",
            "Region": "text",
            "Note": "text",
            "OrderDate": "date",
        },
        "rows": rows,
    }

    dim_table = {
        "id": "Dim",
        "name": "Dim",
        "columns": ["DimID", "Category"],
        "headers": ["DimID", "Category"],
        "types": {"DimID": "whole_number", "Category": "text"},
        "rows": dim_rows,
    }

    relationships = [{
        "from_table": "Facts",
        "from_column": "DimID",
        "to_table": "Dim",
        "to_column": "DimID",
        "cardinality": "many_to_one",
        "cross_filtering": "single",
        "active": True,
    }]

    return facts_table, dim_table, relationships


EXPECTED_26 = {
    "SUMX(Facts, CALCULATE(SUM(Facts[Sales])))": "22601",
    "SUMX(Facts, CALCULATE(SUM(Facts[Sales]), ALL(Facts[Region])))": "22601",
    "SUMX(Facts, CALCULATE(SUM(Facts[Sales]), ALLEXCEPT(Facts, Facts[Region])))": "2254545",
    "SUMX(Facts, CALCULATE(SUM(Facts[Sales]), REMOVEFILTERS(Facts[Quantity])))": "22601",
    "SUMX(Facts, CALCULATE(SUM(Facts[Sales]), KEEPFILTERS(Facts[Region] = \"East\")))": "11477",
    "AVERAGEX(Facts, CALCULATE(AVERAGE(Facts[Quantity])))": "5.7064676616915424034459647373296320438385009765625",
    "SUMX(VALUES(Facts[Region]), CALCULATE(SUM(Facts[Sales])))": "17418",
    "SUMX(FILTER(Facts, Facts[Quantity] > 5), CALCULATE(SUM(Facts[Sales])))": "11612",
    "COUNTROWS(FILTER(Facts, CALCULATE(SUM(Facts[Sales])) > 50))": "ERROR: _HardError: Iterator SUM argument 1 needs a numeric expression.",
    "SUMX(Facts, CALCULATE(COUNTROWS(Facts)))": "406",
    "SUMX(Facts, CALCULATE(MAX(Facts[Sales]), Facts[Quantity] > 5))": "ERROR: MeasureError: Iterator comparisons need matching local data types: DAX comparison operations do not support comparing values of type Text with values of type Integer.",
    "SUMX(Facts, CALCULATE(MIN(Facts[Quantity]), ALL(Facts)))": "402",
    "MAXX(Facts, CALCULATE(SUM(Facts[Sales])))": "ERROR: MeasureRuntimeError: Iterator SUM argument 1 needs a numeric expression.",
    "MINX(Facts, CALCULATE(SUM(Facts[Sales])))": "ERROR: MeasureRuntimeError: Iterator SUM argument 1 needs a numeric expression.",
    "RANKX(ALL(Facts[Region]), CALCULATE(SUM(Facts[Sales])))": "1",
    "SUMX(Facts, CALCULATE(DISTINCTCOUNT(Facts[Region])))": "402",
    "SUMX(Facts, CALCULATE(COUNTBLANK(Facts[Note])))": "97",
    "AVERAGEX(VALUES(Facts[Region]), CALCULATE(SUM(Facts[Sales])))": "5806",
    "SUMX(Facts, CALCULATE(SUM(Facts[Sales]), Facts[Sales] > 50))": "ERROR: MeasureError: Iterator comparisons need matching local data types: DAX comparison operations do not support comparing values of type Text with values of type Integer.",
    "SUMX(Facts, CALCULATE(SUM(Facts[Sales]), Facts[Note] = BLANK()))": "5639",
    "SUMX(Facts, CALCULATE(SUM(Facts[Sales]), ALLSELECTED(Facts[Region])))": "22601",
    "SUMX(Facts, CALCULATE(DIVIDE(SUM(Facts[Sales]), SUM(Facts[Quantity]))))": "6000.715873015873015873015873",
    "CONCATENATEX(VALUES(Facts[Region]), Facts[Region], \", \", CALCULATE(SUM(Facts[Sales])), ASC)": "West, North, East",
    "SUMX(Facts, CALCULATE(SUM(Facts[Sales]), Facts[Region] IN {\"East\", \"West\"}))": "16914",
    "SUMX(Facts, CALCULATE(SUM(Facts[Sales]), NOT(Facts[Region] = \"East\")))": "11124",
    "SUMX(Facts, CALCULATE(COUNTROWS(Dim)))": "8040",
}


@pytest.mark.parametrize("expr,expected", list(EXPECTED_26.items()))
def test_design_section_4_formulas(expr, expected):
    facts_table, dim_table, relationships = _build_test_data()
    try:
        res = evaluate_measures(
            [{"name": "M", "expression": expr}],
            facts_table["rows"],
            facts_table["headers"],
            facts_table["name"],
            table_context=[facts_table, dim_table],
            relationships=relationships,
        )
        actual = str(res.get("M"))
    except Exception as exc:
        actual = f"ERROR: {type(exc).__name__}: {exc}"
    assert actual == expected


def test_nested_identity_and_shadowing():
    regions = ["East", "east", "West", "North"]
    notes = ["Paid", "Late", "Overdue", None]

    rows_60 = []
    for i in range(60):
        rows_60.append({
            "ID": i + 1,
            "Sales": Decimal((i % 10 + 1) * 10),
            "Region": regions[i % 4],
            "Note": notes[i % 4],
        })

    t60 = {
        "id": "Facts",
        "name": "Facts",
        "columns": ["ID", "Sales", "Region", "Note"],
        "headers": ["ID", "Sales", "Region", "Note"],
        "types": {"ID": "whole_number", "Sales": "decimal_number", "Region": "text", "Note": "text"},
        "rows": rows_60,
    }

    nested_expected = {
        "SUMX(Facts, SUMX(Facts, CALCULATE(SUM(Facts[Sales]), ALLSELECTED(Facts[Region]))))": "198000",
        "SUMX(SUMMARIZE(Facts, Facts[Region]), CALCULATE(SUM(Facts[Sales])))": "2400",
        "SUMX(Facts, CALCULATE(SUM(Facts[Sales]), ALL(Facts[Region])))": "3300",
        "SUMX(Facts, CALCULATE(SUM(Facts[Sales]), KEEPFILTERS(Facts[Region] = \"East\")))": "1650",
    }

    for expr, exp_val in nested_expected.items():
        res = evaluate_measures(
            [{"name": "M", "expression": expr}],
            t60["rows"],
            t60["headers"],
            t60["name"],
            table_context=[t60],
        )
        actual = str(res.get("M"))
        assert actual == exp_val, f"Mismatch for {expr}: expected {exp_val}, got {actual}"


def test_rows_matching_unit_cases():
    rows = [{"id": 0}, {"id": 1}, {"id": 2}, {"id": 3}]

    # 1. Empty dict
    assert rows_matching(rows, {}) == rows

    # 2. List value
    res = rows_matching(rows, {"col": [1, 3]})
    assert res == [{"id": 1}, {"id": 3}]

    # 3. Out-of-range position ignored
    res = rows_matching(rows, {"col": frozenset([-2, 1, 99])})
    assert res == [{"id": 1}]

    # 4. Disjoint pair returns empty
    res = rows_matching(rows, {"c1": frozenset([0, 1]), "c2": frozenset([2, 3])})
    assert res == []

    # 5. Order preserved based on row index
    res = rows_matching(rows, {"col": frozenset([3, 0, 2])})
    assert res == [{"id": 0}, {"id": 2}, {"id": 3}]

    # 6. BlankSet preserved
    bs = BlankSet([2, 3], blank=True)
    res = rows_matching(rows, {"col": bs})
    assert res == [{"id": 2}, {"id": 3}]
