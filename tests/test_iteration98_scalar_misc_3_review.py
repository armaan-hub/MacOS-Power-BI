"""Iteration 98 review (Task 10, scalar-misc-3): fresh shapes against live Power BI Desktop (2.157.879.0).

Two review batteries (shapes that are not in the saved batteries; answers frozen from Power BI) and the same kinds of shapes asked on two
other Facts tables (rows in another order) never differ from Power BI. What the first round of fresh shapes showed about the first build:
  - Part D: letters with no decomposition (ł đ ø ð þ ı ŀ ŉ ſ ...) sort as letters of their own, accents rank acute < grave < dot < circumflex <
    diaeresis < caron < breve < macron < tilde < ring < ogonek < cedilla < double acute (not by code point), an apostrophe or hyphen counts for
    almost nothing, and two accents on one letter are compared as a set; only ASCII letters and digits with one known accent are ordered here;
  - Part C: XNPV is plain IEEE double arithmetic (NaN, Infinity, overflow and underflow of the discount factor), the reference date is never later
    than serial 2958465, and Currency values are rounded to four decimals before XNPV reads them;
  - Part B: EVALUATEANDLOG around REMOVEFILTERS / ALLCROSSFILTERED / an IN predicate is an error, a date beside a number is a number in IF.EAGER
    (also inside an iterator, whichever branch is taken), a literal condition folds the other branch away before the table is walked, TABLEOF
    keeps no order the local engine knows once it sits inside TOPN / UNION.
Open (logged in HANDOFF.md, older than this task): TOPN with tied sort values, IF with a column condition and branches of different types in an
unordered walk, and a date-typed IF / IF.EAGER result with a BLANK branch used in arithmetic (a date in Power BI, a number here).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

ROOT = Path(__file__).resolve().parents[1]
PARITY = ROOT / "tools" / "parity"


def _replay(name: str) -> tuple[int, list[tuple[str, str, str, str]]]:
    saved = json.loads((PARITY / f"{name}.json").read_text())
    matched, bad = 0, []
    for item in saved["items"]:
        actual = dax.local(item["expr"])
        outcome = status(item["powerbi"], actual)
        if outcome == "match":
            matched += 1
        elif outcome != "gap-reject":
            bad.append((item["expr"], item["powerbi"], actual, outcome))
    return matched, bad


def _local_on(rows: list[tuple[str, ...]], expression: str) -> str:
    saved = (dax.ROWS, dax.LOCAL_ROWS)
    dax.ROWS = rows
    dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, row)} for row in rows]
    try:
        return dax.local(expression)
    finally:
        dax.ROWS, dax.LOCAL_ROWS = saved


def _assert_matches(test: unittest.TestCase, cases: list[tuple[str, str]]) -> None:
    for expression, powerbi in cases:
        test.assertEqual("match", status(powerbi, dax.local(expression)), expression)


def _assert_refused(test: unittest.TestCase, expressions: list[str]) -> None:
    for expression in expressions:
        test.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), expression)


class Misc3ReviewTest(unittest.TestCase):
    def test_review_batteries_never_differ_from_power_bi(self) -> None:
        for name, floor in (("dax_battery_misc3_extra", FLOOR_EXTRA), ("dax_battery_misc3_extra2", FLOOR_EXTRA2)):
            matched, bad = _replay(name)
            self.assertEqual([], bad, name)
            self.assertGreaterEqual(matched, floor, name)

    def test_other_facts_tables_never_differ_from_power_bi(self) -> None:
        fixture = json.loads((ROOT / "tests" / "fixtures_misc3_alt.json").read_text())
        for key, dataset in fixture["datasets"].items():
            rows = [tuple(row) for row in dataset["rows"]]
            bad = [
                (item["expr"], item["powerbi"])
                for item in dataset["items"]
                if status(item["powerbi"], _local_on(rows, item["expr"])) == "DIFF"
            ]
            self.assertEqual([], bad, key)
            self.assertGreaterEqual(len(dataset["items"]), 1000)

    def test_text_collation_only_for_ascii_letters_with_one_known_accent(self) -> None:
        _assert_matches(self, [
            ('"ó"<="ò"', "True"),  # acute sorts before grave: code-point order says the opposite
            ('"īote">"ïote"', "True"),  # macron after diaeresis
            ('"ä"<"b"', "True"),
            ('"é"<"e"', "False"),
            ("MAX(\"ä\",\"z\")", "z"),
        ])
        _assert_refused(self, [
            '"ł">"s"',  # a letter with no decomposition sorts as a letter of its own
            '"s"<>"ſ"',  # long s is not s in Power BI
            "MAX(\"a\",\"A\")",  # which of two texts that differ only in case comes back is not modelled
            "\"ñ'ÿòê\"<\"ňű2oä\"",  # an apostrophe counts for almost nothing
            '"ė̊"="e̊̇"',  # two accents on one letter are compared as a set
            '"α"<"β"',
        ])

    def test_xnpv_is_ieee_double_arithmetic(self) -> None:
        table = 'ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{100,0},{200,1},{300,2}}),"d",DATE(2020,1,1)+[n])'
        _assert_matches(self, [
            (f"XNPV({table},[v],IF([n]=1,0/0,[d]),0)", "600"),  # 1 ** NaN is 1
            (f"XNPV({table},[v],IF([n]=1,0/0,[d]),0.1)", "NaN"),
            (f"XNPV({table},[v],IF([n]=0,1/0,[d]),0.1)", "499.921673092868"),
            (f"XNPV({table},[v],IF([n]=0,1/0,[d]),-0.5)", "Infinity"),  # 100 / 0
            (f"XNPV({table},[v],IF([n]=1,-1/0,[d]),0.1)", "NaN"),
            (f"XNPV({table},IF([n]=1,1/0,[v]),[d],1/0)", "NaN"),  # Infinity / Infinity
            ('XNPV(ROW("v",5,"d",DATE(2021,1,1)),[v],[d],0/0)', "5"),  # NaN ** 0 is 1
            ("XNPV(Facts,Facts[Quantity],DATE(2020,1,1)+Facts[Quantity],1E150)", "0.999954635643838"),
            ("XNPV(Facts,Facts[Quantity],Facts[Quantity]*1E10,-0.5)", "Infinity"),
        ])
        _assert_refused(self, [
            # Currency arithmetic rounds each value to four decimals first (Power BI: 1733.3335, exact arithmetic gives 1733.3333)
            f"XNPV({table},CURRENCY([v])/3,[n]-3000000,-0.5)",
            "XNPV({{100,1},{200,400}},[Value1],[Value2],0.1)",  # Power BI: Column 'Value1' cannot be found
        ])

    def test_a_filter_modifier_or_in_predicate_inside_evaluateandlog_is_an_error(self) -> None:
        _assert_refused(self, [
            "CALCULATE(COUNTROWS(Facts),EVALUATEANDLOG(ALLCROSSFILTERED(Facts)))",
            "CALCULATE(COUNTROWS(Facts),EVALUATEANDLOG(REMOVEFILTERS(Facts[Region])))",
            'CALCULATE(COUNTROWS(Facts),EVALUATEANDLOG(Facts[Region] IN {"East","West"}))',
            'EVALUATEANDLOG(ROW("a",1),"a",Facts[Quantity])',
        ])

    def test_if_eager_date_beside_number_is_a_number_and_a_literal_condition_folds(self) -> None:
        _assert_matches(self, [
            ("IF.EAGER(FALSE(),1/0,DATE(2020,1,1))", "43831"),
            ("SUMX(Facts,IF.EAGER(FALSE(),1,DATE(2020,1,1)))", "262986"),
            ("SUMX(Facts,IF.EAGER(TRUE(),DATE(2020,1,1)+0.5,Facts[Quantity]))", "262989"),
            ('CONCATENATEX(Facts,IF.EAGER(TRUE(),Facts[Quantity],Facts[Sales]),"|")', "0|1|2|3|4|5"),
            ('CONCATENATEX(Facts,IF.EAGER(FALSE(),Facts[Sales],Facts[Region]),"|")', "East|East|East|West|West|North"),
        ])
        _assert_refused(self, [
            "IF.EAGER(TRUE(),1,Facts[Quantity])",  # a bare column outside a row context, also in the branch that is not taken
            'FORMAT(IF.EAGER(FALSE(),DATE(2020,1,1)+Facts[Quantity],1),"0.0")',
            'CALCULATE(IF.EAGER(TRUE(),-3,DATE(2021,3,4)+Facts[Quantity]),Facts[Region]="East")',
        ])

    def test_tableof_has_a_known_order_only_straight_under_concatenatex(self) -> None:
        _assert_matches(self, [('CONCATENATEX(TABLEOF(Facts[Region]),Facts[Region],",")', "East,East,East,West,West,North")])
        _assert_refused(self, [
            'CONCATENATEX(TOPN(4,TABLEOF(Facts[Region]),Facts[Region],DESC),Facts[Region],",")',
            'CONCATENATEX(UNION(TABLEOF(Facts[Region]),TABLEOF(Facts[Region])),Facts[Region],",")',
        ])


FLOOR_EXTRA = 5200
FLOOR_EXTRA2 = 19000

if __name__ == "__main__":
    unittest.main()
