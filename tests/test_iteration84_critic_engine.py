"""Iteration 84, Critic findings that are not date probes: a measure sharing its name with a column of its own table.

Live Power BI Desktop 2.157.879.0 (measure Qty added to ZO_Fact, which has the column Qty): SUMX(ZO_Fact,[Qty]) is 39, the sum of the
column, and a bare [Qty] is an error.  The local engine refuses the ambiguous reference instead of reading the measure."""
from __future__ import annotations

import unittest

from analytics_studio.measures import MeasureError, evaluate_measures


class MeasureShadowingAColumn(unittest.TestCase):
    TABLE = {"id": "facts", "name": "Facts", "headers": ["Quantity", "Region"],
             "rows": [{"Quantity": "1", "Region": "A"}, {"Quantity": "2", "Region": "B"}, {"Quantity": "3", "Region": "A"}],
             "column_types": {"Quantity": "whole_number", "Region": "text"}}

    def evaluate(self, expression: str) -> object:
        measures = [{"name": "Quantity", "expression": "1", "home_table_id": "facts"},
                    {"name": "Probe", "expression": expression, "home_table_id": "facts"}]
        return evaluate_measures(measures, self.TABLE["rows"], self.TABLE["headers"], "Facts", measure_names=["Probe"],
                                 table_context=[self.TABLE], active_table_id="facts")["Probe"]

    def test_reading_the_shared_name_is_refused(self) -> None:
        for expression in ("SUMX(Facts,[Quantity])", "[Quantity]", "[Quantity]+1"):
            with self.subTest(expression=expression), self.assertRaises(MeasureError):
                self.evaluate(expression)

    def test_other_names_still_evaluate(self) -> None:
        self.assertEqual(6, self.evaluate("SUM(Facts[Quantity])"))
        self.assertEqual(3, self.evaluate("COUNTROWS(Facts)"))


if __name__ == "__main__":
    unittest.main()
