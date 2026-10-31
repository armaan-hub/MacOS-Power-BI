"""Iteration 87: variant (mixed-type) IF / SWITCH / IFERROR / COALESCE iterator bodies, and the type of IN, Boolean information functions,
statistics and numbers used as conditions inside iterators (compared with Power BI Desktop 2.157.879.0).

fixtures_iter87_saved.json: 164 saved live Power BI answers (tools/parity) that the local engine used to refuse ("Iterator IF comparison branches need
matching local data types", "...unsupported or unverifiable local data type", "Logical iterator conditions need Boolean operands" ...); they must now
match Power BI exactly.

fixtures_iter87_fresh.json: 12,112 fresh live probes (Facts, ZO and ZS models).  Every row must match Power BI or be refused: a wrong answer is worse
than a refusal.

The rule (live probes, 120,000 on the Facts scratch table and the ZO / ZS models; 0 differences):
* An IF / SWITCH / IFERROR / COALESCE whose result branches differ in type is a Variant.  COUNTX, SUMX, AVERAGEX, MAXX and MINX read only the numbers
  (and dates) it returns: text and True/False rows count for nothing, never the number a text spells.  COUNTAX counts every row that is not BLANK.
* Types merge pairwise from the right (SWITCH is nested IFs, COALESCE(a, b, c) is COALESCE(a, COALESCE(b, c))).  A literal BLANK() takes the type of
  the other branch, but an IF / SWITCH whose branches are all blank is itself a number (SWITCH(x, 1, "t", BLANK(), BLANK()) is a Variant).
* Numbers beside dates are one number type: the dates are plain numbers.  Inside a Variant, a date keeps its type unless a number-and-date branch
  nested in it already turned it into a number (refused: which one applies depends on the nesting).
* A COALESCE of mixed types evaluates all its arguments; an error in an argument other than the last is not caught by IFERROR."""
from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path

from tests.critic3_models import ours_for
from tools import dax_oracle_diff as dax
from tools.parity_check import status

HERE = Path(__file__).parent
SAVED = json.loads((HERE / "fixtures_iter87_saved.json").read_text())
FRESH = json.loads((HERE / "fixtures_iter87_fresh.json").read_text())["items"]


def local(expr: str) -> str:
    return dax.local(expr)


class VariantIterators(unittest.TestCase):
    def test_saved_power_bi_answers_now_match(self) -> None:
        wrong = []
        for row in SAVED:
            ours = local(row["expr"])
            if status(row["powerbi"], ours) != "match":
                wrong.append((row["expr"], row["powerbi"][:60], ours[:60]))
        self.assertEqual([], wrong[:5], f"{len(wrong)} of {len(SAVED)} saved answers do not match")

    def test_fresh_probes_match_or_are_refused(self) -> None:
        wrong = []
        for model, expr, powerbi, _old, _state in FRESH:
            ours = local(expr) if model == "Facts" else ours_for(model, expr)
            state = status(powerbi, ours)
            if state not in {"match", "gap-reject"}:
                wrong.append((state, expr[:160], powerbi[:40], ours[:60]))
        self.assertEqual([], wrong[:5], f"{len(wrong)} of {len(FRESH)} fresh probes answered wrongly ({dict(Counter(w[0] for w in wrong))})")

    def test_most_fresh_probes_are_answered(self) -> None:
        answered = sum(1 for model, expr, powerbi, *_ in FRESH if status(powerbi, local(expr) if model == "Facts" else ours_for(model, expr)) == "match")
        self.assertGreater(answered / len(FRESH), 0.88)

    def test_variant_aggregates_read_only_the_numbers(self) -> None:
        """The rows with Quantity > 2 (three of them) return text, the other three return 7."""
        for aggregate, expected in (("COUNTX", "3"), ("COUNTAX", "6"), ("MAXX", "7"), ("MINX", "7"), ("SUMX", "21"), ("AVERAGEX", "7")):
            self.assertEqual(expected, local(f'{aggregate}(Facts,IF(Facts[Quantity]>2,"x",7))'), aggregate)
        self.assertEqual("BLANK", local('COUNTX(Facts,IF(Facts[Quantity]>2,"x",TRUE()))'))  # no number at all
        self.assertEqual("3", local('SUMX(Facts,IF(Facts[Quantity]>2,Facts[Region],Facts[Quantity]))'))  # 1 + 0 + 2: the text rows count for nothing
        self.assertEqual("21", local('SUMX(Facts,IF(Facts[Quantity]>2,"5",7))'))  # "5" is text, it is not the number 5

    def test_coalesce_types_every_argument(self) -> None:
        self.assertEqual("5", local('COUNTX(Facts,COALESCE(Facts[Sales],"x"))'))
        self.assertEqual("2", local('COUNTX(Facts,COALESCE(Facts[Note],7))'))
        self.assertEqual("7", local('MAXX(Facts,COALESCE(Facts[Note],7))'))

    def test_computed_blank_is_a_number(self) -> None:
        self.assertEqual("BLANK", local('COUNTX(Facts,SWITCH(Facts[Quantity],2,"x",3,BLANK(),BLANK()))'))  # a Variant, not text
        self.assertEqual("2", local('COUNTX(Facts,SWITCH(Facts[Quantity],2,"x",3,"x",BLANK()))'))  # text: the literal BLANK() takes its type

    def test_numbers_beside_dates_are_plain_numbers(self) -> None:
        self.assertEqual("43831", local("MAXX(Facts,IF(Facts[Quantity]>2,7,DATE(2020,1,1)))"))
        self.assertEqual("43831", local("MAXX(Facts,COALESCE(Facts[Sales],DATE(2020,1,1)))"))
        self.assertEqual("01/01/2020 00:00:00", local('MAXX(Facts,IF(Facts[Quantity]>2,"x",DATE(2020,1,1)))'))

    def test_nested_number_and_date_branch_inside_a_variant_is_refused(self) -> None:
        self.assertTrue(local('MAXX(Facts,SWITCH(Facts[Quantity],2,"x",3,7,DATE(2020,1,1)))').startswith("LOCAL-REJECT"))
        self.assertTrue(local('SUMX(Facts,SWITCH(Facts[Quantity],2,"x",3,7,DATE(2020,1,1)))').startswith("LOCAL-REJECT"))
        self.assertEqual("5", local('COUNTX(Facts,SWITCH(Facts[Quantity],2,"x",3,7,DATE(2020,1,1)))'))  # counting does not depend on the type of the dates

    def test_failing_coalesce_arguments_are_not_swallowed(self) -> None:
        """IFERROR does not catch the error of an earlier COALESCE argument (live Power BI); the last argument is lazy."""
        self.assertTrue(local("SUMX(Facts,IFERROR(COALESCE(VALUE(Facts[Region]),7),1))").startswith("LOCAL-REJECT"))
        self.assertTrue(local("SUMX(Facts,IFERROR(COALESCE(Facts[Sales],VALUE(Facts[Region]),7),1))").startswith("LOCAL-REJECT"))
        self.assertEqual("32.5", local("SUMX(Facts,IFERROR(COALESCE(Facts[Sales],VALUE(Facts[Region])),1))"))
        self.assertEqual("38.5", local("SUMX(Facts,IFERROR(COALESCE(Facts[Sales],7,VALUE(Facts[Region])),1))"))

    def test_min_of_only_plus_infinity_is_blank(self) -> None:
        self.assertEqual("BLANK", local("MINX(Facts,IF(Facts[Quantity]>3,1/0))"))
        self.assertEqual("BLANK", local("MAXX(Facts,IF(Facts[Quantity]>3,-1/0))"))
        self.assertEqual("Infinity", local("MAXX(Facts,IF(Facts[Quantity]>3,1/0))"))
        self.assertEqual("5", local("MINX(Facts,IF(Facts[Quantity]>3,1/0,5))"))

    def test_sum_of_a_text_typed_body_is_an_error(self) -> None:
        self.assertTrue(local('SUMX(Facts,IF(Facts[Quantity]>2,"5","6"))').startswith("LOCAL-REJECT"))
        self.assertTrue(local("SUMX(Facts,IF(Facts[Quantity]>99,Facts[Region]))").startswith("LOCAL-REJECT"))

    def test_addcolumns_variant_column_is_read_like_the_expression(self) -> None:
        self.assertEqual("22.5", local('SUMX(ADDCOLUMNS(Facts,"v",IF(Facts[Quantity]>2,Facts[Sales],Facts[Region]&"!")),[v])'))
        self.assertEqual("5", local('COUNTAX(ADDCOLUMNS(Facts,"v",IF(Facts[Quantity]>2,Facts[Sales],Facts[Region]&"!")),[v])'))
        self.assertTrue(local('SUMX(ADDCOLUMNS(Facts,"v",IF(Facts[Quantity]>2,Facts[Sales],Facts[Region]&"!")),[v]+1)').startswith("LOCAL-REJECT"))

    def test_conditional_types_inside_iterators(self) -> None:
        """IN, Boolean information functions, statistics and numbers as conditions are typed (live Power BI answers)."""
        self.assertEqual("6", local("COUNTAX(Facts,Facts[Quantity] IN {1,2})"))
        self.assertEqual("6", local('COUNTAX(Facts,IF(Facts[Quantity]>99,CONTAINS(Facts,Facts[Region],"East")))'))
        self.assertEqual("6", local("COUNTAX(Facts,IF(Facts[Quantity]>99,NOT(Facts[Quantity])))"))
        self.assertEqual("6", local("COUNTAX(Facts,IF(Facts[Quantity],1,0))"))
        self.assertEqual("2", local("CALCULATE(COUNTROWS(Facts),Facts[Quantity]<STDEV.S(Facts[Quantity]))"))
        self.assertEqual("3", local("CALCULATE(COUNTROWS(Facts),Facts[Quantity]<AVERAGEA(Facts[Quantity]))"))
        self.assertEqual("6", local("CALCULATE(COUNTROWS(Facts),Facts[Quantity]+COUNTROWS(UNION(Facts,Facts))>7)"))
        self.assertEqual("TRUE|TRUE|FALSE|FALSE|FALSE|FALSE", local('CONCATENATEX(Facts,+(Facts[Quantity]>1)=FALSE(),"|",Facts[Quantity])'))

    def test_contains_in_a_boolean_filter_is_an_error(self) -> None:
        self.assertTrue(local('CALCULATE(COUNTROWS(Facts),Facts[Quantity]>CONTAINS(Facts,Facts[Region],"East")*1)').startswith("LOCAL-REJECT"))

    def test_refusals_kept_on_purpose(self) -> None:
        # a True/False under a condition that tests nothing about the row is counted by COUNTX in Power BI (6), not by a row-dependent one (3)
        self.assertEqual("6", local("COUNTX(Facts,IF(TRUE(),TRUE(),7))"))
        # of two texts that differ only in case Power BI returns one the local engine cannot predict
        self.assertTrue(local('MAXX(Facts,IF(Facts[Quantity]>2,UPPER(Facts[Region]),Facts[Region]))').startswith("LOCAL-REJECT"))
        # a Variant that returns Infinity sums to it (live Power BI, Task 13 review)
        self.assertEqual("Infinity", local('SUMX(Facts,IF(Facts[Quantity]=2,Facts[Quantity]/(Facts[Quantity]-2),"x"))'))


if __name__ == "__main__":
    unittest.main()
