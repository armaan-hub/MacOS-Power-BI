"""Iteration 167: Task 78 walk order on other row sets (walk-data-68).

Covers (live Power BI evidence: grid t78e on datasets d2 to d24, the fit sets; datasets d25 to d36 were not used):
- Part B: CONCATENATEX of RANKX(ALL / ALLSELECTED / the table, expression) over the 4-column Facts table walks the two columns the rank expression reads
  in dictionary order while the product of their value-range sizes is at most 341, and in storage order from 432 (measured on the 23 row sets).
  Between those points the walk is refused. A fractional column counts its range in units of its smallest decimal place and has its own points: dictionary
  order at 212 (dataset d23), storage order from 544 (datasets d19, d2, d21, d24), refused between.
- Part C: CONCATENATEX of DISTINCT(ALL(Facts)) / DISTINCT(Facts) walks the distinct rows in dictionary order of all four columns while the product of
  their value-range sizes is at most 1,485, and in storage order from 2,520. Between those points the walk is refused. A fractional column keeps storage order.
- Part A (CONCATENATEX with two ORDER BY keys, rows that tie on both): no walk, scan order or sort algorithm fitted the 16 datasets of 9 rows or more; in the 7
  datasets of 8 rows or fewer the walk order with a stable sort matched every tied case. Over a table of more than 8 rows the text is refused when the
  order of the tied rows can change it.
"""
from __future__ import annotations

import unittest

from decimal import Decimal

from analytics_studio import dax_iteration_order as dio
from tools import dax_oracle_diff as dax

# Row sets of the t78e grid (ds.py datasets d2, d3, d4, d7, d15, d19, d20, d23), in storage order
ROWS_D2 = [
    ('5', '7', 'North', 'Late'), ('', '2', 'East', ''), ('5', '3', 'West', 'Paid'), ('-2', '7', 'East', 'Paid'), ('8', '1', 'North', ''),
    ('1.5', '2', 'West', 'Late'), ('8', '9', 'East', 'Paid'), ('0', '3', 'North', 'Paid'), ('3', '5', 'West', ''),
]

ROWS_D3 = [
    ('4', '1', 'West', ''), ('2', '6', 'North', 'Paid'), ('9', '4', 'East', 'Late'), ('', '2', 'West', 'Paid'),
    ('7', '8', 'North', 'Late'), ('1', '3', 'East', ''), ('6', '5', 'West', 'Late'), ('3', '7', 'North', 'Paid'),
]

ROWS_D4 = [
    ('500', '40', 'West', ''), ('12', '3', 'North', 'Paid'), ('999', '77', 'East', 'Late'), ('', '12', 'West', 'Paid'), ('7', '81', 'North', 'Late'),
    ('250', '5', 'East', ''), ('61', '60', 'West', 'Late'), ('3', '22', 'North', 'Paid'), ('800', '9', 'East', 'Paid'), ('45', '33', 'West', ''),
    ('130', '18', 'North', 'Late'), ('2', '70', 'East', 'Paid'),
]

ROWS_D7 = [
    ('11', '1', 'West', 'Paid'), ('2', '3', 'West', 'Paid'), ('30', '5', 'East', 'Late'), ('-4', '3', 'West', 'Paid'),
    ('27', '3', 'West', 'Late'), ('', '0', 'North', ''), ('25', '1', 'West', 'Paid'), ('0', '1', 'South', ''),
]

ROWS_D15 = [
    ('19', '12', 'East', 'Paid'), ('14', '3', 'East', ''), ('', '2', 'West', 'Late'), ('-1', '12', 'West', 'Late'), ('5', '3', 'North', ''),
    ('6', '10', 'East', 'Paid'), ('27', '8', 'West', 'Paid'), ('-2', '6', 'East', 'Late'), ('28', '9', 'West', 'Paid'), ('', '7', 'South', ''),
]

ROWS_D19 = [
    ('9', '2', 'South', ''), ('', '5', 'South', 'Paid'), ('-1.5', '2', 'South', 'Late'), ('3', '5', 'South', 'Paid'), ('5.5', '3', 'South', ''),
    ('0.5', '3', 'South', ''), ('', '3', 'South', ''), ('12', '5', 'East', 'Paid'),
]

ROWS_D23 = [
    ('6', '2', 'South', 'Paid'), ('-3', '0', 'North', 'Paid'), ('', '0', 'East', 'Late'), ('0.5', '2', 'South', ''), ('1.5', '2', 'West', 'Late'),
    ('-4.5', '0', 'South', 'Paid'), ('0.5', '0', 'East', ''),
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
        fractional = lambda whole: [dio.Profile([Decimal("0.5"), Decimal("11")]), _sized(whole)]  # the fractional range 0.5 .. 11 counts 106 tenths
        self.assertIs(dio.rankx_walk_order(7, fractional(2)), True)  # 106 x 2 = 212: dictionary order (dataset d23)
        self.assertIsNone(dio.rankx_walk_order(7, fractional(3)))  # 318: between the measured points
        self.assertIs(dio.rankx_walk_order(8, fractional(6)), False)  # 636 >= 544: storage order

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

    def test_part_b_fractional_rankx_walks_by_the_scaled_range(self) -> None:
        sum_shape = 'CONCATENATEX(Facts,RANKX(ALL(Facts),Facts[Sales]+Facts[Quantity]),",")'
        self.assertEqual(_answers(ROWS_D23, [sum_shape]), ["5,7,6,4,3,2,1"])  # d23: 106 tenths x 2 = 212, dictionary order
        self.assertEqual(_answers(ROWS_D19, [sum_shape]), ["2,5,8,4,3,6,7,1"])  # d19: 544, storage order

    def test_part_a_tied_order_keys_over_a_larger_table_are_refused(self) -> None:
        tied = 'CONCATENATEX(Facts,Facts[Quantity]&"/"&Facts[Note],",",Facts[Note],ASC,Facts[Region],ASC)'
        self.assertIn("tie on every ORDER BY key", _answers(ROWS_D4, [tied])[0])  # 12 rows: West and no Note hold 40/ and 33/
        untied = 'CONCATENATEX(Facts,Facts[Quantity]&"/"&Facts[Note],",",Facts[Quantity],ASC,Facts[Region],ASC)'
        self.assertEqual(_answers(ROWS_D4, [untied]), ["3/Paid,5/,9/Paid,12/Paid,18/Late,22/Paid,33/,40/,60/Late,70/Paid,77/Late,81/Late"])  # no two rows tie
        same_text = 'CONCATENATEX(Facts,Facts[Region],",",Facts[Region],ASC,Facts[Note],ASC)'
        self.assertNotIn("LOCAL-REJECT", _answers(ROWS_D4, [same_text])[0])  # tied rows give the same text: the order cannot show

    def test_part_a_tied_order_keys_over_a_table_of_8_rows_are_answered(self) -> None:
        tied = 'CONCATENATEX(Facts,Facts[Quantity]&"/"&Facts[Note],",",Facts[Note],ASC,Facts[Region],ASC)'
        self.assertEqual(_answers(ROWS_D3, [tied]), ["3/,1/,4/Late,8/Late,5/Late,6/Paid,7/Paid,2/Paid"])  # d3: measured

    def test_part_c_fractional_distinct_keeps_storage_order(self) -> None:
        self.assertEqual(
            _answers(ROWS_D2, ['CONCATENATEX(DISTINCT(Facts),Facts[Sales],",")']), ["5,,5,-2,8,1.5,8,0,3"])


if __name__ == "__main__":
    unittest.main()
