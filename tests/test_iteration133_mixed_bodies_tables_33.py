"""Iteration 133: Task 43 mixed-bodies-tables-33.

Tests for iterator bodies mixing Currency/number/text branches, and single-cell table queries:
- Part A: Iterator bodies whose branches have different types (Currency, Double, Integer, text, BLANK)
  and statistical iterators over conditionals with Currency; variant column comparisons in COLUMNSTATISTICS;
  multiplication with BLANK and error expressions.
- Part B: Single-cell table expressions evaluated as the whole query (1x1 scalar value, empty table as BLANK,
  multi-row or multi-column table expressions refused).
"""
import unittest

from tools import dax_oracle_diff as dax


class MixedBodiesTables33Tests(unittest.TestCase):
    def assertRefused(self, expression: str) -> None:
        result = dax.local(expression)
        self.assertTrue(result.startswith("LOCAL-REJECT:"), f"Expected refusal, got: {result}")

    def test_part_a_currency_conditionals_in_statistical_iterators(self) -> None:
        # MEDIANX with Currency in conditional
        self.assertTrue(dax.same("3", dax.local('MEDIANX(Facts,IF(1=1,CURRENCY(3),Facts[Region]))')))
        self.assertTrue(dax.same("2.5", dax.local('MEDIANX(Facts,IF.EAGER(TRUE(),Facts[Quantity],CURRENCY(3)))')))
        self.assertTrue(dax.same("2.5", dax.local('MEDIANX(Facts,IF(TRUE(),Facts[Quantity],CURRENCY(3)))')))
        # MEDIANX where all rows evaluate to text -> BLANK
        self.assertEqual("BLANK", dax.local('MEDIANX(Facts,IF(TRUE(),Facts[Region],CURRENCY(3)))'))

        # STDEVX.P with Currency quantized to 4 decimals
        self.assertTrue(dax.same("0.2852", dax.local('STDEVX.P(Facts,IF.EAGER(ISBLANK(Facts[Sales]),1+1,CURRENCY(1.23456)))')))

        # GEOMEANX valid Currency cases
        self.assertTrue(dax.same("1.2346", dax.local('GEOMEANX(TOPN(2,Facts,Facts[Quantity]),VAR x=Facts[Sales]/0 RETURN IF(1=2,x,CURRENCY(1.23456)))')))
        self.assertTrue(dax.same("3", dax.local('GEOMEANX(TOPN(2,Facts,Facts[Quantity]),IF.EAGER("FALSE",Facts[Sales],CURRENCY(3)))')))

        # GEOMEANX over Currency in variant conditional (corrupted float/integer in Power BI) is refused
        self.assertRefused('GEOMEANX(Facts,IF.EAGER("FALSE",1=1,CURRENCY(1.23456)))')
        self.assertRefused('GEOMEANX(CROSSJOIN(VALUES(Facts[Region]),VALUES(Facts[Note])),COALESCE(CURRENCY(3),UPPER(Facts[Region])))')

    def test_part_a_variant_columns_in_conditions_and_multiplications(self) -> None:
        # SUMX over ADDCOLUMNS variant column used inside condition
        self.assertTrue(dax.same("6", dax.local('SUMX(ADDCOLUMNS(Facts,"q",IFERROR(2.5&&"","")),IF(ISBLANK([q]),1,2))')))

        # ISERROR of BLANK multiplied by MAXX with ERROR
        self.assertEqual("False", dax.local('ISERROR((VAR y=BLANK() RETURN y)*(MAXX(Facts,ERROR("x"))))'))

    def test_part_a_columnstatistics_variant_comparisons(self) -> None:
        # COLUMNSTATISTICS [Min] and [Max] comparisons using Variant ordering
        self.assertTrue(dax.same("1", dax.local('COUNTROWS(FILTER(COLUMNSTATISTICS(),[Min]<0))')))
        self.assertTrue(dax.same("3", dax.local('COUNTROWS(FILTER(COLUMNSTATISTICS(),[Max]>10))')))
        self.assertTrue(dax.same("2", dax.local('COUNTROWS(FILTER(COLUMNSTATISTICS(),[Min]=BLANK()))')))
        self.assertTrue(dax.same("1", dax.local('COUNTROWS(FILTER(COLUMNSTATISTICS(),[Max]=BLANK()))')))

    def test_part_b_table_expression_single_cell_scalar(self) -> None:
        # Single row, single column table returns the single value
        self.assertTrue(dax.same("3", dax.local('CALCULATETABLE(ROW("a",COUNTROWS(Facts)),VAR a=2 VAR t=FILTER(Facts,Facts[Quantity]>a) RETURN t)')))
        self.assertTrue(dax.same("1", dax.local('FILTER(ROW("v",1),ISBLANK(IFERROR((SQRT(-1))*(SELECTEDVALUE(Facts[Quantity])),7)))')))

        # Empty table returns BLANK
        self.assertEqual("BLANK", dax.local('FILTER(ROW("v",1),FALSE())'))
        self.assertEqual("BLANK", dax.local('CALCULATETABLE(SELECTCOLUMNS(FILTER(Facts,FALSE()),"v",Facts[Quantity]))'))

        # Multi-row or multi-column table expression as whole query stays refused
        self.assertRefused('Facts')
        self.assertRefused('ROW("a",1,"b",2)')
        self.assertRefused('CALCULATETABLE(Facts,Facts[Quantity]>2)')


if __name__ == "__main__":
    unittest.main()
