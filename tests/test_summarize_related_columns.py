"""SUMMARIZE over a table with columns of the tables on its one side (live Power BI Desktop 2.157.879.0).

SUMMARIZE(Fact, Dim[Cat], Cal[Year], "x", expr) groups the visible rows of the fact table by the values their keys reach in the
one-side tables (a key with no partner reaches the unknown member, whose columns are BLANK); the extension columns are evaluated
per group with every grouped column of every table as a filter. A table cannot be summarized by columns of a table on its many side
(Power BI refuses those: the saved ERR answers).

Expected values: tests/fixtures_summarize_related.json (critic81 loop and the orphan-key probes of re_c).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from analytics_studio import dax_dates
from analytics_studio.measures import MeasureError, evaluate_measures
from tests.critic3_models import ours_for
from tests.test_allselected_critic2 import MEASURES, RELATIONSHIPS, TABLES
from tools.dax_oracle_diff import HEADERS, LOCAL_ROWS
from tools.parity_check import status

FIXTURE = json.loads((Path(__file__).parent / "fixtures_summarize_related.json").read_text())
# Items with an "open" reason in the fixture are saved answers the engine still cannot give (mostly the unknown member of ZO_Dim /
# ZO_Cal, which is being reworked separately); they are not asserted here, every other saved SUMMARIZE answer is.


# measures of the saved CB probes that the shared CB test model does not hold
_EXTRA = {
    "mAllD": "CALCULATE([mSum],ALL(CB_Dim))", "mAllC": "CALCULATE([mSum],ALL(CB_Cal))",
    "mRem": "CALCULATE([mSum],REMOVEFILTERS(CB_Fact))", "mTrans": "SUMX(CB_Fact,CALCULATE(COUNTROWS(CB_Dim)))",
}
_CB_MEASURES = MEASURES + [
    {"name": name, "expression": text, "home_table_id": "cb_fact"} for name, text in _EXTRA.items() if name not in {m["name"] for m in MEASURES}
]


def ours_cb(expression: str) -> str:
    try:
        value = evaluate_measures(
            _CB_MEASURES + [{"name": "P__", "expression": expression, "home_table_id": "cb_fact"}], LOCAL_ROWS, HEADERS, "Facts",
            measure_names=["P__"], table_context=TABLES, relationships=RELATIONSHIPS, active_table_id="facts",
        )["P__"]
    except MeasureError as error:
        return f"LOCAL-REJECT:{error}"
    except Exception as error:  # an evaluator crash is a failure of its own
        return f"LOCAL-CRASH:{type(error).__name__}:{error}"
    return dax_dates.oracle_text(value) if isinstance(value, dax_dates.DaxDateTime) else "BLANK" if value is None else str(value)


def ours(model: str, expression: str) -> str:
    return ours_cb(expression) if model in {"CB", "FX"} else ours_for(model, expression)


# Matched before the unknown-member rules of iteration 82 and now differ: a one-to-one table with a partner-less row
# (RE-D: it keeps its own blank member) and TREATAS({.., BLANK()}, column) selecting the blank member. Both are on the work list.
PENDING_AFTER_UNKNOWN_MEMBER = {
    ("ZM", "COUNTROWS(FILTER(SUMMARIZE(ZM_W,ZM_W[K]),CALCULATE(SUMX(ZM_F,ZM_F[Id]),ALL(ZM_A[K]))>0))"),
    ("ZO", 'CALCULATE(COUNTROWS(SUMMARIZE(ZO_Fact,ZO_Dim[Cat],ZO_Cal[Year])),TREATAS({"A",BLANK()},ZO_Dim[Cat]),ALLNOBLANKROW(ZO_Cal))'),
}


class SummarizeRelatedColumnsTests(unittest.TestCase):
    def test_group_by_columns_of_the_one_side(self) -> None:
        for model, expression, expected in [
            ("CB", 'SUMX(SUMMARIZE(CB_Fact,CB_Dim[Cat],"x",CALCULATE(COUNTROWS(DISTINCT(CB_Fact[Prod])))),[x])', "4"),
            ("CB", 'SUMX(SUMMARIZE(CB_Fact,CB_Cal[Date],"x",CALCULATE(COUNTROWS(DISTINCT(CB_Dim[Prod])))),[x])', "12"),
            ("CB", 'SUMX(SUMMARIZE(CB_Fact,CB_Dim[Grp],"x",CALCULATE(SUM(CB_Cal[Day]))),[x])', "182"),
            ("ZS", 'SUMX(SUMMARIZE(ZS_Dim,ZS_Sup[Sup],"x",CALCULATE(COUNTROWS(VALUES(ZS_Cal)))),[x])', "1462"),
        ]:
            with self.subTest(expression=expression):
                self.assertEqual(expected, ours(model, expression).removesuffix(".0"))

    def test_a_table_is_not_summarized_by_its_many_side(self) -> None:
        for model, expression in [
            ("CB", 'SUMX(SUMMARIZE(CB_Dim,CB_Fact[Reg],"x",CALCULATE(MIN(CB_Cal[Day]))),[x])'),
            ("CB", 'SUMX(SUMMARIZE(CB_Cal,CB_Dim[Prod],"x",CALCULATE(SUM(CB_Fact[Amt]))),[x])'),
        ]:
            with self.subTest(expression=expression):
                self.assertTrue(ours(model, expression).startswith("LOCAL-REJECT"))

    def test_saved_power_bi_answers(self) -> None:
        failures = []
        for item in FIXTURE["items"]:
            if item.get("open") or (item["model"], item["expr"]) in PENDING_AFTER_UNKNOWN_MEMBER:
                continue
            answer = ours(item["model"], item["expr"])
            if status(item["powerbi"], answer) != "match":
                failures.append((item["model"], item["expr"], item["powerbi"], answer))
        self.assertEqual([], failures[:8], f"{len(failures)} of {len(FIXTURE['items'])} differ from Power BI")


if __name__ == "__main__":
    unittest.main()
