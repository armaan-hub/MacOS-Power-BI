"""Two Boolean filters that select the same rows are still two filters: ALLSELECTED tells the outer filter from an inner one by identity."""
from __future__ import annotations

import pytest

from analytics_studio.measures import evaluate_measures

ROWS = [{"Chan": c, "Pay": p, "Amt": a} for c, p, a in [
    ("web", "card", 1), ("web", "card", 2), ("web", "cash", 4), ("shop", "card", 8), ("shop", "cash", 16), ("web", "card", 32)]]
TABLES = [{"id": "s", "name": "Sales", "headers": ["Chan", "Pay", "Amt"], "rows": ROWS,
           "column_types": {"Chan": "text", "Pay": "text", "Amt": "decimal_number"}}]
B = 'Sales[Chan]="web" && Sales[Pay]="card"'

CASES = [
    (f'CALCULATE(SUMX(SUMMARIZE(Sales, Sales[Chan], Sales[Pay]), CALCULATE(COUNTROWS(ALLSELECTED(Sales)), {B})), {B})', "3"),
    (f'CALCULATE(SUMX(VALUES(Sales[Chan]), CALCULATE(COUNTROWS(ALLSELECTED(Sales[Chan])), {B})), {B})', "1"),
    ('CALCULATE(SUMX(SUMMARIZE(Sales, Sales[Chan], Sales[Pay]), CALCULATE(COUNTROWS(ALLSELECTED(Sales)), '
     'Sales[Chan]="web" && Sales[Pay]="card")), Sales[Chan]="web" && Sales[Pay]<>"cash")', "3"),
]


@pytest.mark.parametrize("expression,expected", CASES)
def test_same_rows_from_two_predicates_keep_the_outer_filter(expression, expected):
    value = evaluate_measures([{"name": "P", "expression": expression}], ROWS, TABLES[0]["headers"], "Sales",
                              measure_names=["P"], table_context=TABLES, relationships=[], active_table_id="s")["P"]
    assert str(value) == expected
