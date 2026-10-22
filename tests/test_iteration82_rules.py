"""Unknown member, many-to-many direction and the date-key wipe (iteration 82).

Expected values are live Power BI Desktop 2.157.879.0 answers: the unknown-member probes of RE-C on the ZO model (fact rows with
orphan / blank keys), RE-D's date-key wipe probes on the CB model and its many-to-one / many-to-many / one-to-one probes on ZM.
The fixtures hold a sample (every 4th / 5th) of the cases the engine reproduces; the rest are tracked in the work log.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.critic3_models import ours_for
from tests.test_allselected_critic2 import ours as cb_ours
from tools.parity_check import status

HERE = Path(__file__).parent


def _answer(model: str, expression: str) -> str:
    return cb_ours(expression) if model == "CB" else ours_for(model, expression)


def _replay(name: str) -> tuple[list[tuple[str, str, str, str]], int]:
    items = json.loads((HERE / f"fixtures_iter82_{name}.json").read_text())["items"]
    failures = []
    for item in items:
        answer = _answer(item["model"], item["expr"])
        if status(item["powerbi"], answer) != "match":
            failures.append((item["model"], item["expr"], item["powerbi"], answer))
    return failures, len(items)


class UnknownMemberTests(unittest.TestCase):
    def check(self, cases: dict[str, str]) -> None:
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.assertEqual(expected, ours_for("ZO", expression).removesuffix(".0"))

    def test_base_table_references_never_see_the_unknown_member(self) -> None:
        self.check({
            "COUNTROWS(ZO_Dim)": "5",
            "COUNTX(ZO_Dim,1)": "5",
            "COUNTROWS(DISTINCT(ZO_Dim))": "5",
            "COUNTROWS(ZO_Cal)": "731",
            "DISTINCTCOUNT(ZO_Dim[Cat])": "3",
        })

    def test_values_and_all_list_it_while_it_is_visible(self) -> None:
        self.check({
            "COUNTROWS(VALUES(ZO_Dim))": "6",
            "COUNTROWS(VALUES(ZO_Dim[Cat]))": "4",
            "COUNTROWS(ALL(ZO_Dim[Cat]))": "4",
            "COUNTROWS(ALLNOBLANKROW(ZO_Dim[Cat]))": "3",
            "COUNTROWS(SUMMARIZECOLUMNS(ZO_Dim[Cat]))": "4",
            'CALCULATE(COUNTROWS(VALUES(ZO_Dim[Cat])),ZO_Dim[Cat]="A")': "1",
        })

    def test_an_orphan_fact_row_transitions_to_the_unknown_member(self) -> None:
        self.check({
            "SUMX(ZO_Fact,CALCULATE(COUNTROWS(ZO_Dim)))": "10",
            "SUMX(ZO_Fact,CALCULATE(COUNTROWS(VALUES(ZO_Dim))))": "13",
            "SUMX(VALUES(ZO_Dim),CALCULATE(SUM(ZO_Fact[Amt])))": "375",
            "SUMX(ZO_Dim,CALCULATE(SUM(ZO_Fact[Amt])))": "300",
        })

    def test_filters_select_it_by_blank_semantics(self) -> None:
        self.check({
            'CALCULATE(SUM(ZO_Fact[Amt]),ZO_Dim[Cat]<>"A")': "235",
            'CALCULATE(SUM(ZO_Fact[Amt]),ZO_Dim[Cat]="A")': "140",
            "CALCULATE(SUM(ZO_Fact[Amt]),ZO_Dim[Cat]=BLANK())": "75",
            'CALCULATE(SUM(ZO_Fact[Amt]),ZO_Dim[Cat]<="B")': "370",
            "CALCULATE(SUM(ZO_Fact[Amt]),ZO_Cal[Year]<=2023)": "170",
            "CALCULATE(SUM(ZO_Fact[Amt]),ZO_Cal[Year] IN {0})": "BLANK",
            'CALCULATE(SUM(ZO_Fact[Amt]),TREATAS({"A",BLANK()},ZO_Dim[Cat]))': "215",
            'CALCULATE(SUM(ZO_Fact[Amt]),FILTER(VALUES(ZO_Dim),ZO_Dim[Cat]<>"A"))': "235",
            'CALCULATE(SUM(ZO_Fact[Amt]),FILTER(ZO_Dim,ZO_Dim[Cat]<>"A"))': "160",
            "CALCULATE(SUM(ZO_Fact[Amt]),ALLNOBLANKROW(ZO_Dim))": "300",
            "CALCULATE(SUM(ZO_Fact[Amt]),ALL(ZO_Dim))": "375",
        })

    def test_saved_power_bi_answers(self) -> None:
        failures, total = _replay("um")
        self.assertEqual([], failures[:6], f"{len(failures)} of {total} differ from Power BI")
        self.assertGreater(total, 600)


class DateKeyWipeTests(unittest.TestCase):
    def test_replacing_a_date_key_wipes_the_other_filters_of_its_table(self) -> None:
        for expression, expected in {
            "CALCULATE(CALCULATE(COUNTROWS(CB_Cal),CB_Cal[Date]<=DATE(2023,6,30)),CB_Cal[Year]=2024)": "181",
            "CALCULATE(CALCULATE(COUNTROWS(CB_Cal),CB_Cal[Date]<=DATE(2023,6,30)),CB_Cal[MonthNo]=2)": "181",
            'CALCULATE(CALCULATE(SUM(CB_Fact[Amt]),CB_Cal[Date]<=DATE(2023,6,30)),CB_Dim[Cat]="A")': "60",
            "SUMX(CB_Cal,CALCULATE(COUNTROWS(CB_Cal),CB_Cal[Date]<=DATE(2023,6,30)))": "132311",
            "CALCULATE(SUMX(ALL(CB_Cal[Date]),CALCULATE(COUNTROWS(CB_Cal))),CB_Cal[Year]=2024)": "731",
            "CALCULATE(CALCULATE(COUNTROWS(CB_Cal),DATESYTD(CB_Cal[Date])),CB_Cal[MonthNo]=2)": "60",
            "CALCULATE(CALCULATE(COUNTROWS(CB_Cal),PREVIOUSYEAR(CB_Cal[Date])),CB_Cal[Year]=2024)": "365",
        }.items():
            with self.subTest(expression=expression):
                self.assertEqual(expected, cb_ours(expression).removesuffix(".0"))

    def test_keepfilters_and_other_columns_do_not_wipe(self) -> None:
        for expression in (
            "CALCULATE(CALCULATE(COUNTROWS(CB_Cal),KEEPFILTERS(CB_Cal[Date]<=DATE(2023,6,30))),CB_Cal[Year]=2024)",
            "CALCULATE(CALCULATE(COUNTROWS(CB_Cal),CB_Cal[Year]=2023),CB_Cal[Year]=2024)",
        ):
            with self.subTest(expression=expression):
                self.assertIn(cb_ours(expression), {"BLANK", "365"})

    def test_saved_power_bi_answers(self) -> None:
        failures, total = _replay("r10")
        self.assertEqual([], failures[:6], f"{len(failures)} of {total} differ from Power BI")
        self.assertGreater(total, 400)


class ManyToManyAndOneToOneTests(unittest.TestCase):
    def test_single_direction_many_to_many_filters_from_by_to(self) -> None:
        for expression, expected in {
            'CALCULATE(SUM(ZM_A[V]),ZM_B[K]="k1")': "30",
            'CALCULATE(COUNTROWS(ZM_B),ZM_A[K]="k1")': "4",
            'CALCULATE(COUNTROWS(ZM_A),ZM_B[K]="k1")': "2",
        }.items():
            with self.subTest(expression=expression):
                self.assertEqual(expected, ours_for("ZM", expression).removesuffix(".0"))

    def test_a_one_to_one_filter_does_not_come_back_to_drop_a_partnerless_row(self) -> None:
        self.assertEqual("1", ours_for("ZM", 'CALCULATE(COUNTROWS(ZM_U),ZM_U[K]="k4")'))

    def test_saved_power_bi_answers(self) -> None:
        failures, total = _replay("mm")
        self.assertEqual([], failures[:6], f"{len(failures)} of {total} differ from Power BI")
        self.assertGreater(total, 500)


if __name__ == "__main__":
    unittest.main()
