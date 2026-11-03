"""Iteration 119: text-number-19 (text-to-number conversions, iterator conditions, COALESCE evaluation order).

Plan: docs/plans/2026-11-03-text-number-19.md
Spec: tools/parity/task29_text_number_spec.json
"""
from __future__ import annotations

import unittest
from tools import dax_oracle_diff as dax


class TextNumber19PartBTest(unittest.TestCase):
    def test_logical_iterator_conditions_with_text_operands(self) -> None:
        """Iterators accept text and logical expressions in logical operators."""
        self.assertEqual("6", dax.local('COUNTAX(Facts,Facts[Region]&&"")'))
        self.assertEqual("BLANK", dax.local('COUNTAX(FILTER(Facts,FALSE()),Facts[Region]&&"")'))
        self.assertEqual("6", dax.local('IFERROR(COUNTAX(Facts,Facts[Region]&&""),"e")'))
        self.assertEqual("6", dax.local('COUNTAX(Facts,IF(TRUE(),Facts[Region]&&""))'))
        self.assertEqual("BLANK", dax.local('MINX({1,2},IF(TRUE(),CONVERT(0||"",STRING)))'))
        self.assertEqual("z", dax.local('MAXX({1},CONVERT(1&&"",DOUBLE)&"z")'))


class TextNumber19PartCTest(unittest.TestCase):
    def test_coalesce_in_iterators_with_safe_aggregates(self) -> None:
        """COALESCE with earlier arguments that do not raise evaluates cleanly in iterators."""
        self.assertEqual("43831", dax.local('MAXX(Facts,COALESCE(BLANK(),MAXX(ROW("a",DATE(2020,1,1)),[a]),1))'))
        self.assertEqual("262986", dax.local('SUMX(Facts,COALESCE(BLANK(),MAXX(ROW("a",DATE(2020,1,1)),[a]),1))'))
        self.assertEqual("01/01/2020 00:00:00", dax.local('MAXX(Facts,COALESCE(MAXX(ROW("a",DATE(2020,1,1)),[a]),"a"))'))
        self.assertEqual("2.916666666666666666666666667", dax.local('MAXX(Facts,COALESCE(VARX.P(Facts,Facts[Quantity]),"a"))'))


class TextNumber19PartDTest(unittest.TestCase):
    def test_text_columns_in_arithmetic_inside_iterators(self) -> None:
        """Text columns in arithmetic within row context produce catchable runtime errors."""
        self.assertEqual("0", dax.local('SUMX(Facts,IF(Facts[Region]&&VAR y=TRUE() RETURN ISBLANK(y),1,0))'))
        self.assertEqual("e|e|e|e|e|e", dax.local('CONCATENATEX(Facts,IFERROR(Facts[Note]*"b","e"),"|",Facts[Quantity],ASC,Facts[Sales],ASC)'))
        self.assertEqual("e|e|e|e|e|e", dax.local('CONCATENATEX(Facts,IFERROR((0)/(Facts[Note]),"e"),"|",Facts[Quantity],ASC,Facts[Sales],ASC)'))
        self.assertEqual("e|e|e||e|", dax.local('CONCATENATEX(Facts,IFERROR(Facts[Note]*"3","e"),"|",Facts[Quantity],ASC,Facts[Sales],ASC)'))
        self.assertEqual("28", dax.local('SUMX(Facts,IFERROR(INT(Facts[Note]),7))'))
        self.assertEqual("42", dax.local('SUMX(Facts,IFERROR(INT(Facts[Region]),7))'))
        self.assertEqual("28", dax.local('SUMX(Facts,IFERROR(ABS(Facts[Note]),7))'))
        self.assertEqual("42", dax.local('SUMX(Facts,IFERROR(ABS(Facts[Region]),7))'))


if __name__ == "__main__":
    unittest.main()
