"""Review of Task 15 (typed-columns-5): shapes the fresh Power BI probes found wrong in the build.

Every expected value below is Power BI's answer on the review probes (three tables), checked one by one against DAX semantics.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

ROOT = Path(__file__).resolve().parents[1]


class TypedBlankInAConstructorTest(unittest.TestCase):
    def test_alone_or_beside_logical_and_numbers_it_is_false(self) -> None:
        self.assertEqual("1", dax.local('COUNTAX({2.5&&""},[Value])'))
        self.assertEqual("FALSEz", dax.local('CONCATENATEX({2.5&&""},[Value]&"z","|")'))
        self.assertEqual("n|n", dax.local('CONCATENATEX({OR(0,""),TRUE()},IF(ISBLANK([Value]),"b","n"),"|")'))

    def test_beside_a_blank_it_stays_a_blank(self) -> None:
        self.assertEqual("2", dax.local('SUMX({2.5&&"",BLANK()},IF(ISBLANK([Value]),1,2))'))
        self.assertEqual("BLANK", dax.local('COUNTAX({AND("-1",""),BLANK()},[Value])'))
        self.assertEqual("b|b", dax.local('CONCATENATEX({OR(0,""),BLANK()},IF(ISBLANK([Value]),"b","n"),"|")'))

    def test_beside_a_text_it_stays_refused(self) -> None:
        for expression in ('MINX({"0"||LEFT("a",0),"a"},[Value])', 'COUNTAX({2.5&&"","a"},[Value])', 'MAXX({OR(0,""),"a"},COALESCE([Value],5))'):
            self.assertIn("not modelled", dax.local(expression), expression)


class OnlyATableIsATableFilterTest(unittest.TestCase):
    def test_a_true_false_var_with_an_aggregate_stays_an_error(self) -> None:
        for expression in (
            'CALCULATE(COUNTROWS(Facts),VAR m=MAX(Facts[Quantity])>1 RETURN m)',
            'CALCULATE(COUNTROWS(Facts),KEEPFILTERS(VAR b=SUM(Facts[Quantity])>1 RETURN b))',
            'COUNTROWS(CALCULATETABLE(Facts,VAR m=MAX(Facts[Quantity])>1 RETURN m))',
        ):
            self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), expression)

    def test_a_var_holding_a_table_is_one(self) -> None:
        self.assertEqual("3", dax.local('CALCULATE(COUNTROWS(Facts),VAR t=FILTER(Facts,Facts[Quantity]>2) RETURN t)'))
        self.assertEqual("3", dax.local('CALCULATE(COUNTROWS(Facts),VAR t=FILTER(Facts,Facts[Quantity]>2) VAR u=t RETURN u)'))


class ConstructorAsAScalarTest(unittest.TestCase):
    def test_several_columns_fail_at_compile_time(self) -> None:
        for expression in ('IFERROR({(1,2)},7)', 'ISERROR({(1,2)})', 'SUMX(FILTER(Facts,FALSE()),{(1,2)})', 'COUNTROWS(FILTER(FILTER(Facts,FALSE()),{(1,2)}))'):
            self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), expression)

    def test_several_rows_fail_at_run_time(self) -> None:
        self.assertEqual("7", dax.local('IFERROR({1,2},7)'))
        self.assertEqual("7", dax.local('IFERROR({"a","b"},7)'))
        self.assertEqual("BLANK", dax.local('SUMX(FILTER(Facts,FALSE()),{1,2})'))

    def test_a_text_constructor_is_a_text_body(self) -> None:
        self.assertTrue(dax.local('SUMX(FILTER(Facts,FALSE()),{"a","b"})').startswith("LOCAL-REJECT"))


class BlankOperandTypeTest(unittest.TestCase):
    def test_times_blank_keeps_a_currency(self) -> None:
        self.assertEqual("True", dax.local('ISCURRENCY(MAXX(ADDCOLUMNS(Facts,"z",CURRENCY(1)*BLANK()),[z]+1))'))

    def test_plus_blank_keeps_a_currency(self) -> None:
        self.assertEqual("True", dax.local('ISCURRENCY(CURRENCY(10.00005)+BLANK())'))


class OneRepeatedDateHasNoSpreadTest(unittest.TestCase):
    def test_a_repeated_date_with_a_fraction_is_zero(self) -> None:
        self.assertEqual("0", dax.local('IFERROR(VARX.P(Facts,DATE(2020,1,1)+0.5),7)'))
        self.assertEqual("0", dax.local('STDEVX.S(FILTER(Facts,Facts[Quantity]>1),DATE(2020,1,1)+0.5)'))

    def test_a_refusal_is_not_an_error_for_iferror(self) -> None:
        self.assertTrue(dax.local('IFERROR(VARX.P(Facts,0.5),7)').startswith("LOCAL-REJECT"))


class TypesComeFromTheTableTest(unittest.TestCase):
    """A column named like a stored one has the type of its own expression, through DISTINCT, table variables, IF and a sign."""

    def test_a_table_variable(self) -> None:
        self.assertEqual("False", dax.local('VAR t=SELECTCOLUMNS(Facts,"Quantity",CURRENCY(1)) RETURN ISINT64(MAXX(t,[Quantity]))'))
        self.assertEqual("True", dax.local('VAR t=SELECTCOLUMNS(Facts,"Quantity",CURRENCY(1)) RETURN ISCURRENCY(MAXX(t,[Quantity]))'))
        self.assertEqual("True", dax.local('ISDOUBLE(VAR t=SELECTCOLUMNS(Facts,"Quantity",1.5) RETURN IF(TRUE(),MAXX(t,[Quantity])))'))
        self.assertEqual("True", dax.local('ISDOUBLE(VAR t=SELECTCOLUMNS(Facts,"Quantity",Facts[Sales]) RETURN -MAXX(t,[Quantity]))'))

    def test_distinct_of_a_table(self) -> None:
        self.assertEqual("True", dax.local('ISCURRENCY(MAXX(DISTINCT(SELECTCOLUMNS(Facts,"Quantity",CURRENCY(1))),[Quantity]))'))

    def test_rand_is_a_double(self) -> None:
        self.assertEqual("True", dax.local('ISDOUBLE(MAXX(SELECTCOLUMNS(Facts,"Quantity",RAND()),[Quantity]))'))


class VariableOfATableFilterTest(unittest.TestCase):
    def test_a_transition_in_a_variable_is_evaluated_once(self) -> None:
        self.assertEqual("1", dax.local('CALCULATE(COUNTROWS(Facts),VAR m=CALCULATE(MAX(Facts[Quantity])) RETURN FILTER(Facts,Facts[Quantity]=m))'))
        self.assertEqual("6", dax.local('CALCULATE(COUNTROWS(Facts),VAR c=CALCULATE(COUNTROWS(Facts)) RETURN FILTER(Facts,Facts[Quantity]<c))'))

    def test_a_variable_without_one_is_read_once(self) -> None:
        self.assertEqual("1", dax.local('CALCULATE(COUNTROWS(Facts),VAR m=MAX(Facts[Quantity]) RETURN FILTER(Facts,Facts[Quantity]=m))'))


class FiltersInAnyOrderTest(unittest.TestCase):
    def test_a_variable_among_several_filters(self) -> None:
        one = 'COUNTROWS(FILTER(CALCULATETABLE(Facts,VAR r="West" RETURN Facts[Region]=r,LEN(Facts[Region])>100),"a"))'
        other = 'COUNTROWS(FILTER(CALCULATETABLE(Facts,LEN(Facts[Region])>100,VAR r="West" RETURN Facts[Region]=r),"a"))'
        self.assertEqual(dax.local(one), dax.local(other))


class TextByTypeTest(unittest.TestCase):
    def test_a_computed_text_constructor(self) -> None:
        for expression in ('AVERAGEX(FILTER(Facts,FALSE()),{UPPER("a"),UPPER("b")})', 'PRODUCTX(FILTER(Facts,FALSE()),{"a"&"b","c"&"d"})', 'GEOMEANX(FILTER(Facts,FALSE()),{1,UPPER("a")})'):
            self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), expression)


class TypedBlankThroughABlockTest(unittest.TestCase):
    def test_a_var_block_and_calculate_keep_the_type(self) -> None:
        for expression in ('MAXX(ADDCOLUMNS(Facts,"q",VAR y=2.5&&"" RETURN y),[q])', 'MAXX({VAR y=2.5&&"" RETURN y},[Value])', 'MAXX(ADDCOLUMNS(Facts,"q",CALCULATE(2.5&&"")),[q])'):
            self.assertIn("Boolean", dax.local(expression), expression)

    def test_beside_a_date_it_stays_refused(self) -> None:
        self.assertIn("not modelled", dax.local('CONCATENATEX({OR(0,""),DATE(2020,1,1)},[Value],"|")'))

    def test_beside_a_number_it_is_a_number_column(self) -> None:
        self.assertEqual("3", dax.local('SUMX({2.5&&"",3},[Value])'))


class FreshProbesTest(unittest.TestCase):
    def test_fresh_probes_on_another_table_match_or_are_refused(self) -> None:
        fixture = json.loads((ROOT / "tests" / "fixtures_typed5_review_alt.json").read_text())
        saved = (dax.ROWS, dax.LOCAL_ROWS)
        try:
            for dataset in fixture["datasets"].values():
                dax.ROWS = [tuple(row) for row in dataset["rows"]]
                dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, row)} for row in dax.ROWS]
                wrong = [(item["expr"], item["powerbi"][:60]) for item in dataset["items"] if status(item["powerbi"], dax.local(item["expr"])) not in {"match", "gap-reject"}]
                self.assertEqual([], wrong[:10])
        finally:
            dax.ROWS, dax.LOCAL_ROWS = saved


if __name__ == "__main__":
    unittest.main()
