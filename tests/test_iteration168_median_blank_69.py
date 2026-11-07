"""Iteration 168: Task 79 MEDIANX / PERCENTILEX with BLANK results among the values (median-blank-69).

Covers (live Power BI evidence: grid t79e on datasets d8, d12, d16 and the standard grid t72a):
- Part A: a BLANK result counts as zero in the sort, and the median is BLANK when it lands on a BLANK.  The average of two middle values is BLANK
  only when both are BLANK; a BLANK beside a number counts as zero (BLANK + x is x).  Measured on d8 (Region <> "East": a BLANK, BLANK, 10, BLANK
  body gives BLANK, where the old code gave 0), d16 (Quantity < 5: BLANK, -5, 24, -4, 67 gives BLANK).
- Part B: over a column reference, a BLANK and a real 0 tied on the pick: the BLANK sorts first (standard grid t72a: 0 for MEDIANX(Facts,Sales)
  under Quantity <> 3, and 0 for PERCENTILEX.INC(Facts,Sales,0.25) on Facts).
- Part C: over an expression body, a BLANK and a real 0 tied on the pick is refused (live Power BI on d12 gave BLANK where the other order would
  give 0; the order is not settled, so the answer is refused, as it was before).
"""
from __future__ import annotations

import unittest

from decimal import Decimal

from analytics_studio import dax_math
from tools import dax_oracle_diff as dax

# Row sets of the t79e grid (ds.py datasets d8, d12, d16), in storage order
ROWS_D8 = [
    ('', '1', 'West', ''),
    ('5', '1', 'East', ''),
    ('9', '1', 'East', 'Late'),
    ('9', '8', 'East', 'Late'),
    ('', '6', 'West', 'Paid'),
    ('10', '2', 'South', 'Paid'),
    ('', '7', 'East', ''),
    ('6', '6', 'East', 'Late'),
    ('11', '7', 'East', ''),
    ('10', '10', 'East', 'Paid'),
    ('4', '1', 'East', 'Late'),
    ('6', '6', 'East', 'Paid'),
    ('10', '0', 'East', 'Paid'),
    ('-3', '7', 'East', 'Late'),
    ('', '2', 'West', 'Late'),
]

ROWS_D12 = [
    ('-2', '8', 'North', 'Late'),
    ('', '9', 'North', 'Late'),
    ('10', '4', 'South', 'Late'),
    ('32', '8', 'West', 'Paid'),
    ('36', '15', 'North', 'Late'),
    ('34', '13', 'North', 'Late'),
    ('37', '14', 'North', ''),
    ('32', '2', 'West', ''),
    ('39', '1', 'South', 'Paid'),
    ('47', '11', 'South', 'Late'),
    ('0', '15', 'South', 'Paid'),
]

ROWS_D16 = [
    ('', '7', 'South', 'Paid'),
    ('', '9', 'South', 'Paid'),
    ('', '4', 'North', 'Late'),
    ('41', '9', 'South', ''),
    ('-3', '5', 'North', 'Paid'),
    ('-5', '3', 'West', ''),
    ('15', '6', 'West', 'Late'),
    ('24', '0', 'East', ''),
    ('-4', '4', 'North', 'Late'),
    ('3', '7', 'North', 'Paid'),
    ('67', '1', 'East', 'Paid'),
    ('50', '5', 'East', ''),
    ('34', '9', 'East', 'Late'),
]

# d38 and d40: eleven values under Region <> "East", a BLANK and real zeros tied on the pick; Power BI gives BLANK, no order of the tie is known
ROWS_D38 = [
    ('21', '2', 'West', 'Paid'), ('', '5', 'West', 'Late'), ('47', '3', 'South', ''), ('0', '0', 'West', ''), ('0', '6', 'West', 'Paid'),
    ('0', '0', 'South', 'Late'), ('37', '1', 'North', ''), ('33', '3', 'South', 'Paid'), ('0', '7', 'South', ''), ('35', '3', 'East', 'Paid'),
    ('0', '7', 'North', 'Paid'), ('29', '2', 'South', 'Paid'),
]

ROWS_D40 = [
    ('9', '4', 'North', 'Paid'), ('24', '9', 'South', 'Paid'), ('', '4', 'West', ''), ('7', '3', 'North', 'Paid'), ('0', '0', 'West', 'Paid'),
    ('18', '8', 'East', ''), ('', '9', 'South', ''), ('', '4', 'North', 'Paid'), ('', '8', 'East', ''), ('30', '3', 'East', ''),
    ('28', '7', 'West', ''), ('', '10', 'West', 'Late'), ('', '5', 'South', 'Late'), ('15', '2', 'West', 'Late'),
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


class TestIteration168MedianBlank69(unittest.TestCase):
    def test_blank_pick_is_blank_and_pair_with_a_blank_counts_it_as_zero(self) -> None:
        values = [Decimal("0"), Decimal("10")]
        self.assertEqual(dax_math.statistic("MEDIANX", values, None, blanks=[True, False]), Decimal("5"))  # (BLANK + 10) / 2
        self.assertIsNone(dax_math.statistic("MEDIANX", [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("10")], None, blanks=[True, True, True, False], blank_first=True))
        # five values, the middle one (sorted: -5, -4, BLANK, 24, 67) is a BLANK
        five = [Decimal("-5"), Decimal("0"), Decimal("24"), Decimal("-4"), Decimal("67")]
        self.assertIsNone(dax_math.statistic("MEDIANX", five, None, blanks=[False, True, False, False, False]))
        self.assertIsNone(dax_math.statistic("PERCENTILEX.INC", five, Decimal("0.5"), blanks=[False, True, False, False, False]))

    def test_percentile_between_a_blank_and_a_number_counts_the_blank_as_zero(self) -> None:
        values = [Decimal("0"), Decimal("20"), Decimal("4")]
        self.assertEqual(
            dax_math.statistic("PERCENTILEX.INC", values, Decimal("0.5"), blanks=[True, False, False], blank_first=True),
            Decimal("4"))  # sorted: BLANK, 4, 20; the position 0.5 x 2 = 1 lands on 4
        self.assertEqual(
            dax_math.statistic("PERCENTILEX.INC", values, Decimal("0.25"), blanks=[True, False, False], blank_first=True),
            Decimal("2"))  # position 0.5 between BLANK (0) and 4: 0 + 4 x 0.5

    def test_blank_and_real_zero_on_the_pick_is_refused_over_an_expression_body(self) -> None:
        with self.assertRaises(Exception) as caught:
            dax_math.statistic("MEDIANX", [Decimal("32"), Decimal("0"), Decimal("0")], None, blanks=[False, True, False])
        self.assertIn("both a BLANK and a number", str(caught.exception))

    def test_one_blank_and_one_real_zero_run_gives_the_second_as_zero(self) -> None:
        # live Power BI (t72a, d46): MEDIANX(Facts,Facts[Sales]) under Quantity <> 3 over -1.5, BLANK, 0, 2.5, 10.5 is 0; the run of one BLANK and one real
        # zero is the only mixed run measured the same every time
        values = [Decimal("10.5"), Decimal("-1.5"), Decimal("0"), Decimal("0"), Decimal("2.5")]
        self.assertEqual(dax_math.statistic("MEDIANX", values, None, blanks=[False, False, True, False, False], blank_first=True), Decimal("0"))
        # the first of the two, the BLANK, was not measured: refused
        with self.assertRaises(Exception) as caught:
            dax_math.statistic("MEDIANX", [Decimal("-3"), Decimal("-2"), Decimal("0"), Decimal("0"), Decimal("9")], None, blanks=[False, False, True, False, False], blank_first=True)
        self.assertIn("both a BLANK and a number", str(caught.exception))

    def test_larger_mixed_runs_are_refused_for_a_column_reference_too(self) -> None:
        # d38 and d40 give BLANK, d37 and d39 give the zero, for runs of 6, 4 and 5: the order is not known
        values = [Decimal(x) for x in ("0", "0", "0", "0", "0", "0", "21", "29", "33", "37", "47")]
        with self.assertRaises(Exception) as caught:
            dax_math.statistic("MEDIANX", values, None, blanks=[True, False, False, False, False, False] + [False] * 5, blank_first=True)
        self.assertIn("both a BLANK and a number", str(caught.exception))

    def test_d8_reference_body_blank_results_are_blank_where_power_bi_says_so(self) -> None:
        cases = [
            ('CALCULATE(MEDIANX(ALLSELECTED(Facts),Facts[Sales]),Facts[Region]<>"East")', "BLANK"),
            ('CALCULATE(PERCENTILEX.INC(ALLSELECTED(Facts),Facts[Sales],0.5),Facts[Region]<>"East")', "BLANK"),
            ('CALCULATE(PERCENTILEX.EXC(ALLSELECTED(Facts),Facts[Sales],0.5),Facts[Region]<>"East")', "BLANK"),
            ('MEDIANX(ALLSELECTED(Facts),Facts[Sales])', "6"),
            ('CALCULATE(MEDIANX(ALLSELECTED(Facts),Facts[Sales]),Facts[Note]="Paid")', "10"),
        ]
        self.assertEqual(_answers(ROWS_D8, [expression for expression, _expected in cases]), [expected for _expression, expected in cases])

    def test_d16_reference_body_median_landing_on_a_blank_is_blank(self) -> None:
        pairs = [
            ('CALCULATE(MEDIANX(ALLSELECTED(Facts),Facts[Sales]),Facts[Quantity]<5)', "BLANK"),
            ('CALCULATE(MEDIANX(ALLSELECTED(Facts),Facts[Sales]),Facts[Quantity]>=2)', "BLANK"),  # sorted -5, -4, -3, BLANK x3, 3, ...: the middle is a BLANK
        ]
        self.assertEqual(_answers(ROWS_D16, [expression for expression, _expected in pairs]), [expected for _expression, expected in pairs])

    def test_d12_expression_body_blank_and_zero_tie_is_refused(self) -> None:
        answer = _answers(ROWS_D12, ['CALCULATE(MEDIANX(Facts,IF(Facts[Quantity]>3,Facts[Sales])),Facts[Note]="Paid")'])[0]
        self.assertTrue(answer.startswith("LOCAL-REJECT"), answer)

    def test_standard_facts_ties_match_power_bi(self) -> None:
        pairs = [
            ('CALCULATE(MEDIANX(Facts,Facts[Sales]),Facts[Quantity]<>3)', "0"),
            ('CALCULATE(PERCENTILEX.INC(ALLSELECTED(Facts),Facts[Sales],0.25),Facts[Region]<>"East")', "0"),
            ('PERCENTILEX.INC(Facts,Facts[Sales],0.25)', "0"),
        ]
        self.assertEqual([str(dax.local(expression)) for expression, _expected in pairs], [expected for _expression, expected in pairs])

    def test_d38_d40_blank_and_zero_tie_over_eleven_values_is_refused(self) -> None:
        expressions = [
            'CALCULATE(MEDIANX(Facts,Facts[Sales]),Facts[Region]<>"East")',
            'CALCULATE(PERCENTILEX.INC(ALLSELECTED(Facts),Facts[Sales],0.5),Facts[Region]<>"East")',
            'CALCULATE(PERCENTILEX.EXC(Facts,Facts[Sales],0.5),Facts[Region]<>"East")',
        ]
        for rows in (ROWS_D38, ROWS_D40):
            for answer in _answers(rows, expressions):
                self.assertTrue(answer.startswith("LOCAL-REJECT"), answer)

    def test_single_pick_in_a_run_with_a_blank_and_a_real_zero_is_refused_at_any_size(self) -> None:
        for count in (5, 9, 11, 15):
            values = [Decimal(0)] * 4 + [Decimal(10 + i) for i in range(count - 4)]
            flags = [True, False, False, False] + [False] * (count - 4)
            if count % 2 == 0:
                continue
            values = [Decimal(-1) * (i + 1) for i in range(count // 2 - 1)] + values
            flags = [False] * (count // 2 - 1) + flags
            with self.assertRaises(Exception, msg=str(count)) as caught:
                dax_math.statistic("MEDIANX", values[:count] if len(values) > count else values, None, blanks=flags[:count] if len(flags) > count else flags, blank_first=True)
            self.assertIn("both a BLANK and a number", str(caught.exception))

    def test_average_of_two_picks_is_refused_only_when_both_can_be_blank(self) -> None:
        # run of zeros: one BLANK and one real zero; both middle values in it: BLANK + 0 is 0 whichever order the run has
        self.assertEqual(dax_math.statistic("MEDIANX", [Decimal(x) for x in ("-1.5", "0", "0", "2.5")], None, blanks=[False, True, False, False]), Decimal("0"))
        # one middle value in the run, the other a number: the BLANK counts as zero beside it
        self.assertEqual(dax_math.statistic("MEDIANX", [Decimal(x) for x in ("0", "0", "4", "9")], None, blanks=[True, False, False, False]), Decimal("2"))
        # two BLANKs and a real zero, both middle values in the run: BLANK + BLANK is BLANK, BLANK + 0 is 0
        with self.assertRaises(Exception) as caught:
            dax_math.statistic("MEDIANX", [Decimal(x) for x in ("-5", "0", "0", "0", "7")] + [Decimal("8")], None, blanks=[False, True, True, False, False, False])
        self.assertIn("both a BLANK and a number", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
