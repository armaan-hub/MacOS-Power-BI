"""Review of Task 16 (strict-types-6): rules Power BI showed on fresh probes, not on the spec items.

Every expected value is Power BI's answer. Fresh answers: dax_battery_strict6_extra (the standard table) and tests/fixtures_strict6_review_alt.json (table B).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from analytics_studio import dax_typed
from tools import dax_oracle_diff as dax
from tools.parity_check import status

ROOT = Path(__file__).resolve().parents[1]


class TextOrderTest(unittest.TestCase):
    def test_punctuation_sorts_before_digits_and_letters(self) -> None:
        self.assertEqual("True", dax.local('"|"<"0"'))
        self.assertEqual("0", dax.local('MAX("=","0")'))
        self.assertEqual("1", dax.local('IF("~"<"a",1,2)'))

    def test_the_order_of_ascii_punctuation(self) -> None:
        order = " !\"#$%&()*,./:;?@[\\]^_`{|}~+<=>"
        keys = [dax_typed.text_collation_key(c) for c in order + "05az"]
        self.assertEqual(keys, sorted(keys))

    def test_hyphen_and_apostrophe_only_break_a_tie(self) -> None:
        self.assertEqual("a'b", dax.local('MAXX({"a\'b","ab"},[Value])'))
        self.assertEqual("-1", dax.local('MAXX({"-1","0"},[Value])'))
        self.assertEqual("True", dax.local('"a-bc"<"ab-c"'))
        self.assertEqual("True", dax.local('"a\'b"<"a-b"'))
        self.assertEqual("True", dax.local('"a-b">"aa"'))
        self.assertEqual("True", dax.local('"a-b"<"ac"'))

    def test_equality_does_not_change(self) -> None:
        self.assertEqual("False", dax.local('"a-b"="ab"'))

    def test_every_path_sorts_the_same(self) -> None:
        self.assertEqual("^|0", dax.local('CONCATENATEX({"^","0"},[Value],"|",[Value],ASC)'))
        self.assertEqual("~", dax.local('MAXX(TOPN(1,{"~","a"},[Value],ASC),[Value])'))


class IslogicalTest(unittest.TestCase):
    def test_a_folded_text_keeps_the_type(self) -> None:
        for expression in ('ISLOGICAL(2.5&&"")', 'ISLOGICAL(2.5&&UPPER(""))', 'ISLOGICAL(2.5&&VAR y=LEFT("a",0) RETURN y)', 'ISLOGICAL(AND("-1",""))'):
            self.assertEqual("True", dax.local(expression), expression)

    def test_a_text_read_at_run_time_does_not(self) -> None:
        for expression in ('ISLOGICAL(2.5&&LEFT("a",0))', 'ISLOGICAL("0"||REPT("a",0))', 'ISLOGICAL(2.5&&REPLACE("a",1,1,""))'):
            self.assertEqual("False", dax.local(expression), expression)

    def test_beside_data_there_is_no_rule(self) -> None:
        for expression in ('ISLOGICAL(2.5&&UNICHAR(32))',):
            self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), expression)


class ConditionalOfAnOperatorTest(unittest.TestCase):
    def test_beside_nothing_or_a_blank_it_stays_a_blank(self) -> None:
        for expression in ('ISBLANK(IF(TRUE(),2.5&&""))', 'ISBLANK(IF(TRUE(),2.5&&"",BLANK()))', 'ISBLANK(SWITCH(TRUE(),TRUE(),2.5&&""))', 'ISBLANK(IFERROR(2.5&&"",BLANK()))', 'ISBLANK(IF(TRUE(),IF(TRUE(),2.5&&"")))'):
            self.assertEqual("True", dax.local(expression), expression)

    def test_the_branch_not_taken_is_false(self) -> None:
        self.assertEqual("False", dax.local('ISBLANK(IF(FALSE(),2.5&&""))'))
        self.assertEqual("FALSEz", dax.local('(IF(FALSE(),"0"||LEFT("a",0)))&"z"'))

    def test_the_row_decides(self) -> None:
        self.assertEqual("3", dax.local('COUNTAX(ADDCOLUMNS(Facts,"q",IF(Facts[Quantity]>2,2.5&&"",BLANK())),[q])'))

    def test_beside_another_operator_it_stays_refused(self) -> None:
        self.assertEqual("BLANK", dax.local('LEN(IF(TRUE(),2.5&&"","0"||LEFT("a",0)))'))  # Power BI Desktop 2026-11-03 (Task 27 models it)

    def test_a_locked_shape_is_kept(self) -> None:
        self.assertEqual("BLANK", dax.local('IF(FALSE(),1,2.5&&"")'))
        self.assertEqual("BLANK", dax.local('IF(TRUE(),2.5&&"","a")'))


class TablesOfATypeTest(unittest.TestCase):
    def test_union_joins_its_tables(self) -> None:
        self.assertEqual("False", dax.local('ISINT64(MAXX(UNION(SELECTCOLUMNS(Facts,"z",1),SELECTCOLUMNS(Facts,"z",1.5)),[z]))'))
        self.assertEqual("True", dax.local('ISCURRENCY(MAXX(UNION(SELECTCOLUMNS(Facts,"z",Facts[Quantity]),SELECTCOLUMNS(Facts,"z",CURRENCY(1))),[z]))'))
        self.assertEqual("True", dax.local('ISDOUBLE(MAXX(UNION(SELECTCOLUMNS(Facts,"z",DATE(2020,1,1)),SELECTCOLUMNS(Facts,"z",1.5)),[z]))'))

    def test_a_date_beside_a_number_is_a_double(self) -> None:
        self.assertEqual("True", dax.local('ISDOUBLE(MAXX({1+DATE(2020,1,1),1},[Value]))'))

    def test_a_date_minus_a_date_is_no_double(self) -> None:
        self.assertEqual("False", dax.local('ISDOUBLE(MAXX(ADDCOLUMNS(Facts,"z",DATE(2020,1,1)-DATE(2020,1,2)),[z]))'))

    def test_statistics_keep_a_currency(self) -> None:
        for function in ("GEOMEANX", "STDEVX.P", "STDEVX.S"):
            self.assertEqual("True", dax.local(f"ISCURRENCY({function}(Facts,CURRENCY(1)))"), function)

    def test_a_renamed_column_keeps_its_own_type(self) -> None:
        self.assertEqual("1", dax.local('SUMX(ROW("Region",1),[Region])'))
        self.assertEqual("1", dax.local('COUNTROWS(FILTER(SELECTCOLUMNS(Facts,"Region",Facts[Quantity]),[Region]=1))'))


class StrictEqualTest(unittest.TestCase):
    def test_only_a_literal_blank_fits_every_type(self) -> None:
        for expression in ('TRUE()==(VAR y=BLANK() RETURN y)', '"a"==(VAR y=BLANK() RETURN y)', '(VAR b=BLANK() RETURN b)=="a"', 'IFERROR(FALSE()==(VAR y=BLANK() RETURN y),7)'):
            self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), expression)

    def test_the_type_of_the_column_counts(self) -> None:
        self.assertTrue(dax.local('SUMX(SELECTCOLUMNS(Facts,"Value",Facts[Note]),IF([Value]==CURRENCY(1),1,2))').startswith("LOCAL-REJECT"))
        self.assertTrue(dax.local('SUMX(Facts,SUMX({1},IF([Note]==1,1,2)))').startswith("LOCAL-REJECT"))

    def test_a_var_holding_a_column_is_that_column(self) -> None:
        self.assertEqual("4", dax.local('SUMX({TRUE(),BLANK()},VAR v=[Value] RETURN IF(v==FALSE(),1,2))'))

    def test_selectedvalue_with_an_alternate_is_not_typed_by_its_column(self) -> None:
        self.assertEqual("True", dax.local('SELECTEDVALUE(Facts[Quantity],1)==1'))

    def test_circular_variables_end(self) -> None:
        self.assertEqual("True", dax.local('VAR x=1 RETURN VAR y=x RETURN VAR x=y RETURN x==1'))


class VariableInATableFilterTest(unittest.TestCase):
    def test_it_runs_in_the_row_of_the_caller(self) -> None:
        self.assertEqual("1", dax.local('CALCULATE(COUNTROWS(Facts),VAR m=CALCULATE(MAX(Facts[Quantity])) RETURN FILTER(Facts,Facts[Quantity]=m))'))

    def test_only_if_something_reads_it(self) -> None:
        self.assertEqual("6", dax.local('CALCULATE(COUNTROWS(Facts),VAR m=CALCULATE(ERROR("x")) RETURN FILTER(Facts,TRUE()))'))

    def test_earlier_variables_reach_it(self) -> None:
        self.assertEqual("1", dax.local('CALCULATE(COUNTROWS(Facts),VAR a=2 VAR m=CALCULATE(MAX(Facts[Quantity]))+a-2 RETURN FILTER(Facts,Facts[Quantity]=m))'))

    def test_an_inner_variable_of_the_same_name_wins(self) -> None:
        self.assertEqual("5", dax.local('CALCULATE(COUNTROWS(Facts),VAR m=CALCULATE(MAX(Facts[Quantity])) RETURN FILTER(Facts,VAR m=1 RETURN Facts[Quantity]>=m))'))

    def test_a_nested_block_stays_refused(self) -> None:
        self.assertIn("not modelled", dax.local('CALCULATE(COUNTROWS(Facts),VAR a=1 RETURN VAR m=CALCULATE(MAX(Facts[Quantity])) RETURN FILTER(Facts,Facts[Quantity]=m))'))


class CurrencyDivisionTest(unittest.TestCase):
    def test_through_an_added_column(self) -> None:
        for expression in ('SUMX(ADDCOLUMNS(Facts,"c",CURRENCY(1)),[c]/0)', 'SUMX(ADDCOLUMNS(Facts,"c",CURRENCY(1)),SUMX({1},[c]/0))', 'SUMX(ADDCOLUMNS(Facts,"c",CURRENCY(1)),VAR v=[c] RETURN v/0)', 'SUMX(ADDCOLUMNS(SELECTCOLUMNS(Facts,"Q",CURRENCY(1)),"z",[Q]),[z]/0)'):
            self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), expression)

    def test_a_currency_by_a_currency_is_infinity(self) -> None:
        self.assertEqual("Infinity", dax.local('CURRENCY(1)/CURRENCY(0)'))


class MixedConditionalTest(unittest.TestCase):
    def test_one_branch_of_another_type_makes_a_variant(self) -> None:
        self.assertEqual("1", dax.local('MAXX({IF(FALSE(),2.5&&"",1)},[Value])'))
        self.assertEqual("BLANK", dax.local('SUMX({IFERROR(2.5&&"",1)},[Value])'))


class FreshProbesTest(unittest.TestCase):
    def test_fresh_probes_on_another_table_match_or_are_refused(self) -> None:
        fixture = json.loads((ROOT / "tests" / "fixtures_strict6_review_alt.json").read_text())
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
