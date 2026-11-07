"""Iteration 166: Task 77 TOPN / VALUES walk order on other row sets (topn-data-67).

Covers (live Power BI evidence: grid t77e on datasets d2 to d18, grid t77d on d4, d9 and d14):
- Part A: CONCATENATEX(TOPN(n, Facts, key, dir), body) walks the two columns it reads in dictionary order while (space of the two columns) x (rows)
  is at most 3,410, and in storage order from 3,796 (measured on the 17 row sets). Between those points the walk is refused. Fractional columns keep
  the older grouped rule (dataset d2 is left as it was).
- Part B: VALUES / DISTINCT / UNION(VALUES) of one whole-number column walk in value order up to a space of 14,970 (dataset d4, range 998 over 12 rows);
  a TOPN read of the same column keeps the storage order at that size.
"""
from __future__ import annotations

import unittest

from decimal import Decimal

from analytics_studio import dax_iteration_order as dio
from tools import dax_oracle_diff as dax

# Row sets of the t77e grid (ds.py datasets d4, d9, d14, d18), in storage order
ROWS_D4 = [
    ('500', '40', 'West', ''),
    ('12', '3', 'North', 'Paid'),
    ('999', '77', 'East', 'Late'),
    ('', '12', 'West', 'Paid'),
    ('7', '81', 'North', 'Late'),
    ('250', '5', 'East', ''),
    ('61', '60', 'West', 'Late'),
    ('3', '22', 'North', 'Paid'),
    ('800', '9', 'East', 'Paid'),
    ('45', '33', 'West', ''),
    ('130', '18', 'North', 'Late'),
    ('2', '70', 'East', 'Paid'),
]

ROWS_D9 = [
    ('48', '5', 'West', 'Paid'),
    ('', '3', 'West', ''),
    ('123', '24', 'South', 'Late'),
    ('124', '38', 'East', 'Late'),
    ('154', '18', 'North', 'Late'),
    ('111', '12', 'East', ''),
    ('', '2', 'East', ''),
    ('', '5', 'East', ''),
    ('47', '5', 'South', 'Paid'),
    ('22', '24', 'North', 'Late'),
]

ROWS_D14 = [
    ('29', '9', 'South', 'Paid'),
    ('81', '10', 'North', 'Paid'),
    ('0', '22', 'West', ''),
    ('94', '7', 'South', 'Late'),
    ('2', '12', 'East', 'Late'),
    ('42', '9', 'West', 'Paid'),
    ('28', '12', 'South', ''),
    ('4', '3', 'West', 'Late'),
    ('24', '8', 'West', ''),
    ('', '5', 'West', ''),
    ('73', '21', 'East', 'Paid'),
    ('29', '8', 'North', ''),
    ('23', '14', 'East', 'Paid'),
    ('76', '4', 'North', 'Late'),
]

ROWS_D18 = [
    ('16', '5', 'North', ''),
    ('8', '24', 'East', ''),
    ('-4', '28', 'South', 'Paid'),
    ('14', '16', 'South', 'Paid'),
    ('21', '12', 'South', 'Paid'),
    ('18', '8', 'North', 'Paid'),
    ('', '23', 'North', 'Late'),
    ('16', '30', 'South', ''),
    ('', '8', 'West', 'Late'),
    ('', '25', 'South', 'Paid'),
    ('-3', '19', 'North', 'Paid'),
    ('6', '6', 'South', ''),
    ('11', '23', 'North', 'Late'),
    ('11', '26', 'East', 'Late'),
    ('31', '22', 'West', 'Paid'),
    ('', '13', 'West', 'Paid'),
]


def _answers(rows: list, expressions: list[str]) -> list[str]:
    """Answers of the expressions with `rows` as the Facts table; the grid's rows are restored afterwards."""
    saved = (dax.ROWS, dax.LOCAL_ROWS, dax.FACTS_DAX)
    try:
        dax.ROWS = rows
        dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, r)} for r in rows]
        dax.FACTS_DAX = "UNION(" + ",".join(dax._dax_row(r) for r in rows) + ")"
        return [str(dax.local(expression)) for expression in expressions]
    finally:
        dax.ROWS, dax.LOCAL_ROWS, dax.FACTS_DAX = saved


class TestIteration166TopnData67(unittest.TestCase):
    def test_pair_rule_uses_the_measured_points(self) -> None:
        profiles = [dio.Profile([Decimal(v) for v in (1, 2, 3)]), dio.Profile([Decimal(v) for v in (1, 2, 3, 4)])]  # value ranges 3 and 4, space 12
        self.assertTrue(dio.topn_pair_applies(profiles))
        self.assertIs(dio.topn_pair_order(10, profiles), True)  # 12 x 10 = 120
        self.assertIs(dio.topn_pair_order(283, profiles), True)  # 12 x 283 = 3,396 <= 3,410
        self.assertIsNone(dio.topn_pair_order(300, profiles))  # 3,600 lies between the measured points: refused
        self.assertIs(dio.topn_pair_order(317, profiles), False)  # 12 x 317 = 3,804 >= 3,796: storage order
        fractional = [dio.Profile([Decimal("1"), Decimal("2.5"), Decimal("3")]), dio.Profile([Decimal(v) for v in (1, 2, 3, 4)])]
        self.assertFalse(dio.topn_pair_applies(fractional))

    def test_part_a_two_column_topn_walk_matches_power_bi(self) -> None:
        cases = {
            "d9": (ROWS_D9, [
                ('CONCATENATEX(TOPN(3,Facts,Facts[Note],ASC),Facts[Sales],",")', ",,111,"),
                ('CALCULATE(CONCATENATEX(TOPN(3,Facts,Facts[Note],ASC),Facts[Sales],","),Facts[Quantity]<>3)', "111,,"),
            ]),
            "d14": (ROWS_D14, [
                ('CONCATENATEX(TOPN(3,Facts,Facts[Note],ASC),Facts[Sales],",")', "28,24,0,,29"),
            ]),
            "d18": (ROWS_D18, [
                ('CONCATENATEX(TOPN(3,Facts,Facts[Quantity],ASC),Facts[Sales],",")', ",6,18,16"),
            ]),
        }
        for name, (rows, pairs) in cases.items():
            expressions = [expression for expression, _expected in pairs]
            with self.subTest(dataset=name):
                self.assertEqual(_answers(rows, expressions), [expected for _expression, expected in pairs])

    def test_part_b_values_of_a_large_whole_number_column_walk_in_value_order(self) -> None:
        pairs = [
            ('CONCATENATEX(VALUES(Facts[Sales]),Facts[Sales],",")', ",2,3,7,12,45,61,130,250,500,800,999"),
            ('CALCULATE(CONCATENATEX(VALUES(Facts[Sales]),Facts[Sales],","),Facts[Note]="Paid")', ",2,3,12,800"),
            ('CONCATENATEX(UNION(VALUES(Facts[Sales]),VALUES(Facts[Sales])),Facts[Sales],",")',
             ",2,3,7,12,45,61,130,250,500,800,999,,2,3,7,12,45,61,130,250,500,800,999"),
        ]
        self.assertEqual(_answers(ROWS_D4, [expression for expression, _expected in pairs]), [expected for _expression, expected in pairs])

    def test_part_b_topn_of_the_same_column_keeps_storage_order(self) -> None:
        self.assertEqual(_answers(ROWS_D4, ['CONCATENATEX(TOPN(3,Facts,Facts[Sales],ASC),Facts[Sales],",")']), ["3,2,"])
