"""Iteration 167: Task 78 walk order on other row sets (walk-data-68).

Covers (live Power BI evidence: grid t78e on datasets d2 to d24, the fit sets; datasets d25 to d36 were not used):
- Part B: CONCATENATEX of RANKX(ALL / ALLSELECTED / the table, expression) over the 4-column Facts table walks the two columns the rank expression reads
  in dictionary order while the product of their value-range sizes is at most 341, and in storage order from 432 (measured on the 23 row sets).
  Between those points the walk is refused. A fractional column keeps storage order.
- Part C: CONCATENATEX of DISTINCT(ALL(Facts)) / DISTINCT(Facts) walks the distinct rows in dictionary order of all four columns while the product of
  their value-range sizes is at most 1,485, and in storage order from 2,520. Between those points the walk is refused. A fractional column keeps storage order.
- Part A (ORDER BY ties) is not changed: no rule fitted every dataset (see the report of this iteration).
"""
from __future__ import annotations

import unittest

from decimal import Decimal

from analytics_studio import dax_iteration_order as dio
from tools import dax_oracle_diff as dax

# Row sets of the t78e grid (ds.py datasets d2, d3, d7, d15, d20), in storage order
ROWS_D2 = [
    ('5', '7', 'North', 'Late'), ('', '2', 'East', ''), ('5', '3', 'West', 'Paid'), ('-2', '7', 'East', 'Paid'), ('8', '1', 'North', ''),
    ('1.5', '2', 'West', 'Late'), ('8', '9', 'East', 'Paid'), ('0', '3', 'North', 'Paid'), ('3', '5', 'West', ''),
]

ROWS_D3 = [
    ('4', '1', 'West', ''), ('2', '6', 'North', 'Paid'), ('9', '4', 'East', 'Late'), ('', '2', 'West', 'Paid'),
    ('7', '8', 'North', 'Late'), ('1', '3', 'East', ''), ('6', '5', 'West', 'Late'), ('3', '7', 'North', 'Paid'),
]

ROWS_D7 = [
    ('11', '1', 'West', 'Paid'), ('2', '3', 'West', 'Paid'), ('30', '5', 'East', 'Late'), ('-4', '3', 'West', 'Paid'),
    ('27', '3', 'West', 'Late'), ('', '0', 'North', ''), ('25', '1', 'West', 'Paid'), ('0', '1', 'South', ''),
]

ROWS_D15 = [
    ('19', '12', 'East', 'Paid'), ('14', '3', 'East', ''), ('', '2', 'West', 'Late'), ('-1', '12', 'West', 'Late'), ('5', '3', 'North', ''),
    ('6', '10', 'East', 'Paid'), ('27', '8', 'West', 'Paid'), ('-2', '6', 'East', 'Late'), ('28', '9', 'West', 'Paid'), ('', '7', 'South', ''),
]

ROWS_D20 = [
    ('40', '0', 'North', 'Late'), ('14', '0', 'North', ''), ('8', '4', 'South', ''), ('-5', '8', 'North', 'Paid'), ('34', '7', 'North', 'Paid'),
    ('42', '1', 'South', 'Late'), ('26', '8', 'West', 'Paid'), ('35', '7', 'North', 'Paid'), ('6', '4', 'South', 'Late'), ('32', '0', 'West', ''),
    ('23', '1', 'West', 'Paid'),
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


def _sized(count: int) -> dio.Profile:
    """A whole-number column whose value range has `count` steps (size = count)."""
    return dio.Profile([Decimal(v) for v in range(1, count + 1)])


class TestIteration167WalkData68(unittest.TestCase):
    def test_part_b_rankx_rule_uses_the_measured_points(self) -> None:
        self.assertIs(dio.rankx_walk_order(10, [_sized(9), _sized(37)]), True)  # 333 <= 341
        self.assertIs(dio.rankx_walk_order(10, [_sized(15), _sized(11)]), True)  # 165: dictionary (dataset d8)
        self.assertIsNone(dio.rankx_walk_order(10, [_sized(9), _sized(38)]))  # 342: between the measured points
        self.assertIsNone(dio.rankx_walk_order(10, [_sized(12), _sized(35)]))  # 420: between the measured points
        self.assertIs(dio.rankx_walk_order(11, [_sized(48), _sized(9)]), False)  # 432: storage order (dataset d20)
        fractional = [dio.Profile([Decimal("1.5"), Decimal("2")]), _sized(2)]
        self.assertIs(dio.rankx_walk_order(7, fractional), False)  # a fractional column keeps storage order

    def test_part_c_distinct_rule_uses_the_measured_points(self) -> None:
        self.assertIs(dio.distinct_walk_order(8, [_sized(15), _sized(11), _sized(3), _sized(3)]), True)  # 1,485 (dataset d8)
        self.assertIsNone(dio.distinct_walk_order(8, [_sized(15), _sized(12), _sized(3), _sized(3)]))  # 1,620: between the points
        self.assertIs(dio.distinct_walk_order(8, [_sized(28), _sized(30), _sized(3), _sized(3)]), False)  # 7,560 >= 2,520: storage
        fractional = [dio.Profile([Decimal("1.5"), Decimal("2")]), _sized(2), _sized(3), _sized(3)]
        self.assertIs(dio.distinct_walk_order(8, fractional), False)

    def test_part_b_rankx_over_the_whole_table_walks_the_two_columns_it_reads(self) -> None:
        pairs = [
            ('CONCATENATEX(Facts,RANKX(ALL(Facts),Facts[Quantity]*2-Facts[Sales]),",")', "10,5,3,1,6,10,4,7,2,9,7"),  # d20: 432, storage
            ('CONCATENATEX(Facts,RANKX(ALL(Facts),Facts[Quantity]*2-Facts[Sales],,ASC),",")', "5,4,3,7,7,1,2,7,10,6"),  # d15: 341, dictionary
        ]
        self.assertEqual(_answers(ROWS_D20, [pairs[0][0]]), [pairs[0][1]])
        self.assertEqual(_answers(ROWS_D15, [pairs[1][0]]), [pairs[1][1]])

    def test_part_b_sum_shape_walks_by_its_two_columns(self) -> None:
        expression = 'CONCATENATEX(Facts,RANKX(ALL(Facts),Facts[Sales]+Facts[Quantity]),",")'
        self.assertEqual(_answers(ROWS_D7, [expression]), ["7,6,4,3,8,5,2,1"])  # d7: 35 x 6 = 210, dictionary order
        self.assertEqual(_answers(ROWS_D15, [expression]), ["10,7,4,9,8,2,1,5,6,3"])  # d15: 31 x 11 = 341, dictionary order

    def test_part_c_distinct_of_all_columns_walks_in_dictionary_order(self) -> None:
        pairs = [
            ('CONCATENATEX(DISTINCT(ALL(Facts)),Facts[Note],",")', ",,Paid,Paid,Paid,Late,Late,Late"),
            ('CONCATENATEX(DISTINCT(ALL(Facts)),Facts[Quantity],",")', "1,3,2,6,7,5,8,4"),
            ('CONCATENATEX(DISTINCT(Facts),Facts[Quantity],",")', "1,3,2,6,7,5,8,4"),
        ]
        self.assertEqual(_answers(ROWS_D3, [expression for expression, _expected in pairs]), [expected for _expression, expected in pairs])

    def test_part_c_filtered_distinct_walks_the_whole_dictionary_under_the_filter(self) -> None:
        pairs = [
            ('CALCULATE(CONCATENATEX(DISTINCT(Facts),Facts[Note],","),Facts[Quantity]<>3)', ",Paid,Paid,Paid,Late,Late,Late"),
            ('CALCULATE(CONCATENATEX(DISTINCT(Facts),Facts[Quantity],","),Facts[Quantity]<>3)', "1,2,6,7,5,8,4"),
        ]
        self.assertEqual(_answers(ROWS_D3, [expression for expression, _expected in pairs]), [expected for _expression, expected in pairs])

    def test_part_c_fractional_distinct_keeps_storage_order(self) -> None:
        self.assertEqual(
            _answers(ROWS_D2, ['CONCATENATEX(DISTINCT(Facts),Facts[Sales],",")']), ["5,,5,-2,8,1.5,8,0,3"])


if __name__ == "__main__":
    unittest.main()
