from datetime import date
from decimal import Decimal
import unittest

from analytics_studio.measures import MeasureError, evaluate_measures, normalize_measure

class ContextTransitionTests(unittest.TestCase):
    def test_sumx_measure_calculates_with_context_transition(self) -> None:
        rows = [
            {"Category": "A", "Amount": "10"},
            {"Category": "B", "Amount": "20"},
            {"Category": "A", "Amount": "30"},
        ]
        headers = ["Category", "Amount"]

        # Base measure is SUM(Amount), which is 60 overall.
        # But when called in SUMX for each row, context transition filters to that row.
        # So for row 1: Category A, Amount 10 -> filters to this row exactly => SUM is 10.
        # But wait! If we do SUM(Amount) it will return 10 for row 1, 20 for row 2, 30 for row 3.
        # SUMX over these is 10+20+30 = 60.
        
        # Let's do something more interesting:
        # A measure that computes MAX(Amount).
        # Inside SUMX, for row 1 (A, 10), is 10.
        
        values = evaluate_measures(
            [
                {"name": "Base", "expression": "SUM([Amount])"},
                {"name": "SumxMeasure", "expression": "SUMX('Table', [Base] * 2)"}
            ],
            rows, headers, "Table",
            table_context=[{
                "id": "t1", "name": "Table", "headers": headers, "rows": rows, "column_types": {"Amount": "whole_number"}
            }], active_table_id="t1"
        )
        # Row 1: [Base] evaluated under Context Transition (filters Table to Category=A, Amount=10) -> SUM is 10. * 2 = 20
        # Row 2: (B, 20) -> base=20 -> 40
        # Row 3: (A, 30) -> base=30 -> 60
        # Total: 20 + 40 + 60 = 120
        self.assertEqual(values["SumxMeasure"], Decimal(120))


    def test_context_transition_with_calculate(self) -> None:
        rows = [
            {"Category": "A", "Amount": "10"},
            {"Category": "B", "Amount": "20"},
            {"Category": "A", "Amount": "30"},
        ]
        headers = ["Category", "Amount"]

        # CALCULATE inside SUMX.
        values = evaluate_measures(
            [
                {"name": "CalcMeasure", "expression": """
                SUMX(
                    'Table',
                    CALCULATE(SUM([Amount]), 'Table'[Category] = "A")
                )
                """}
            ],
            rows, headers, "Table",
            table_context=[{
                "id": "t1", "name": "Table", "headers": headers, "rows": rows, "column_types": {"Amount": "whole_number"}
            }], active_table_id="t1"
        )
        # Row 1: Context transition: C=A, Amt=10. CALCULATE overrides C=A. So effective filter is C=A, Amt=10. SUM is 10.
        # Row 2: Context transition: C=B, Amt=20. CALCULATE overrides C=A. So effective filter is C=A, Amt=20. No rows match! SUM is 0.
        # Row 3: Context transition: C=A, Amt=30. CALCULATE overrides C=A. effective: C=A, Amt=30. SUM is 30.
        # Total: 10 + 0 + 30 = 40.
        self.assertEqual(values["CalcMeasure"], Decimal(40))

