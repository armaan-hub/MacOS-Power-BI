"""FILTER as the table argument of COUNTROWS and the X iterators.

Every expected value was read from Power BI Desktop 2.157.879.0 with ``tools/dax_oracle_diff.py`` and
``tools/dax_battery_filter_tables.json`` against the same six-row Facts table.
"""

from __future__ import annotations

from decimal import Decimal
import unittest

from analytics_studio.measures import MeasureError, evaluate_measures, normalize_measure

HEADERS = ["Sales", "Quantity", "Region", "Note"]
ROWS = [
    {"Sales": "10.5", "Quantity": "2", "Region": "East", "Note": "Paid"},
    {"Sales": "20", "Quantity": "3", "Region": "West", "Note": None},
    {"Sales": "-1.5", "Quantity": "1", "Region": "East", "Note": "Paid"},
    {"Sales": None, "Quantity": "4", "Region": "North", "Note": "Late"},
    {"Sales": "0", "Quantity": "0", "Region": "West", "Note": "Paid"},
    {"Sales": "2.5", "Quantity": "5", "Region": "East", "Note": None},
]
CONTEXT = [{
    "id": "facts", "name": "Facts", "headers": HEADERS, "rows": ROWS,
    "column_types": {"Sales": "decimal_number", "Quantity": "whole_number", "Region": "text", "Note": "text"},
}]


def measure(expression: str) -> Decimal | None:
    return evaluate_measures(
        [{"name": "M", "expression": expression}], ROWS, HEADERS, "Facts",
        measure_names=["M"], table_context=CONTEXT, active_table_id="facts",
    )["M"]


class FilterTableIteratorTests(unittest.TestCase):
    def test_countrows_over_filter(self) -> None:
        for expression, expected in (
            ('COUNTROWS(FILTER(Facts,Facts[Region]="East"))', 3),
            ('COUNTROWS(FILTER(Facts,Facts[Region]="east"))', 3),
            ('COUNTROWS(FILTER(Facts,Facts[Region]="East "))', None),
            ("COUNTROWS(FILTER(Facts,Facts[Quantity]>2))", 3),
            ('COUNTROWS(FILTER(Facts,Facts[Quantity]>=3 && Facts[Region]="East"))', 1),
            ('COUNTROWS(FILTER(Facts,Facts[Region]="East" || Facts[Region]="West"))', 5),
            ('COUNTROWS(FILTER(Facts,NOT(Facts[Region]="East")))', 3),
            ('COUNTROWS(FILTER(Facts,AND(Facts[Quantity]>1,Facts[Region]<>"East")))', 2),
            ("COUNTROWS(FILTER(Facts,Facts[Quantity]>100))", None),
            ("COUNTROWS(FILTER(Facts,Facts[Quantity]>100))+1", 1),
            ("COUNTROWS(FILTER(ALL(Facts),Facts[Quantity]>2))", 3),
        ):
            with self.subTest(expression=expression):
                self.assertEqual(measure(expression), None if expected is None else Decimal(expected))

    def test_blank_comparisons_follow_dax(self) -> None:
        # A blank number equals 0 and a blank text equals "" inside FILTER predicates.
        self.assertEqual(measure("COUNTROWS(FILTER(Facts,Facts[Sales]=0))"), 2)
        self.assertEqual(measure("COUNTROWS(FILTER(Facts,Facts[Sales]>0))"), 3)
        self.assertEqual(measure('COUNTROWS(FILTER(Facts,Facts[Note]=""))'), 2)
        self.assertEqual(measure("COUNTROWS(FILTER(Facts,Facts[Note]=BLANK()))"), 2)

    def test_x_iterators_over_filter(self) -> None:
        for expression, expected in (
            ('SUMX(FILTER(Facts,Facts[Region]="East"),Facts[Sales])', Decimal("11.5")),
            ("SUMX(FILTER(Facts,Facts[Quantity]>1),Facts[Sales]*Facts[Quantity])", Decimal("93.5")),
            ("SUMX(FILTER(Facts,Facts[Quantity]>100),Facts[Sales])", None),
            ('MAXX(FILTER(Facts,Facts[Region]<>"East"),Facts[Quantity])', Decimal(4)),
            ("MINX(FILTER(Facts,Facts[Quantity]>0),Facts[Sales])", Decimal("-1.5")),
            ("COUNTX(FILTER(Facts,Facts[Quantity]>1),Facts[Sales])", Decimal(3)),
            ("COUNTAX(FILTER(Facts,Facts[Quantity]>1),Facts[Note])", Decimal(2)),
            ('SUMX(FILTER(ALL(Facts),Facts[Region]="East"),Facts[Sales])', Decimal("11.5")),
        ):
            with self.subTest(expression=expression):
                self.assertEqual(measure(expression), expected)
        average = measure('AVERAGEX(FILTER(Facts,Facts[Region]="East"),Facts[Sales])')
        self.assertAlmostEqual(float(average), 3.83333333333333, places=12)

    def test_filter_table_respects_the_calculate_context(self) -> None:
        self.assertEqual(
            measure('CALCULATE(COUNTROWS(FILTER(Facts,Facts[Quantity]>1)),Facts[Region]="East")'), 2
        )
        # ALL removes the Region filter before FILTER runs.
        self.assertEqual(
            measure('CALCULATE(COUNTROWS(FILTER(ALL(Facts),Facts[Quantity]>1)),Facts[Region]="East")'), 4
        )

    def test_filter_all_base_is_a_calculate_filter(self) -> None:
        # Power BI answers 11.5 for this on the Facts table (tools/parity/dax_battery_tables2.json)
        normalize_measure("M", 'CALCULATE(SUM(Facts[Sales]),FILTER(ALL(Facts),Facts[Region]="East"))')


if __name__ == "__main__":
    unittest.main()
