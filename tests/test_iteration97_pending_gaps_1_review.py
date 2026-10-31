"""Iteration 97 review: VAR scoping and scalar subqueries in filters against live Power BI Desktop (2.157.879.0).

Two review batteries (3,033 and 3,005 shapes that are not in the saved batteries) and 2,400 more asked on two other Facts tables
(rows in another order) never differ from Power BI. What the first round of fresh shapes showed:
  - a text (or True/False) value beside a VAR block compares by the static type of the block's RETURN expression: "a"<>VAR y=BLANK() RETURN y
    is an error (Text beside Integer) although the value is BLANK; the first build answered True / False;
  - the "a BLANK variable is a number" rule of CALCULATE filters must not leak into a FILTER row: FILTER(Facts,VAR t=BLANK() RETURN Facts[Region]=t)
    is a value in Power BI (the first build refused 23 such shapes that main answered);
  - a TOPN held in a variable and walked by CONCATENATEX is listed in an order that depends on the rows read, so it is refused.
Open (logged in HANDOFF.md, older than this task): the walk order of DISTINCT(table) when every row is distinct, TOPN with tied sort values,
and a text column compared with COUNTROWS of an empty CALCULATETABLE / FILTER (BLANK here, an error in Power BI).
Refused on purpose: a VAR block on the right of ||, && or ^; CALCULATE filter variables holding an expression (1+1, a measure, SUM ...).
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


class PendingGaps1ReviewTest(unittest.TestCase):
    def test_review_batteries_never_differ_from_power_bi(self) -> None:
        for name, floor in (("dax_battery_pending_extra", 2600), ("dax_battery_pending_extra2", 2800)):
            matched, bad = _replay(name)
            self.assertEqual([], bad, name)
            self.assertGreaterEqual(matched, floor, name)

    def test_other_facts_tables_never_differ_from_power_bi(self) -> None:
        fixture = json.loads((ROOT / "tests" / "fixtures_pending_alt.json").read_text())
        for key, dataset in fixture["datasets"].items():
            rows = [tuple(row) for row in dataset["rows"]]
            bad = [
                (item["expr"], item["powerbi"])
                for item in dataset["items"]
                if status(item["powerbi"], _local_on(rows, item["expr"])) == "DIFF"
            ]
            self.assertEqual([], bad, key)
            self.assertGreaterEqual(len(dataset["items"]), 1000)

    def test_a_text_beside_a_var_block_compares_by_the_type_of_its_return_expression(self) -> None:
        errors = [  # Power BI: DAX comparison operations do not support comparing values of type Text with values of type Integer
            '"a"<>VAR y=BLANK() RETURN y',
            '"a">VAR y=BLANK() RETURN y',
            '"a"<VAR y=BLANK() RETURN y',
            '"a"=VAR y=BLANK() RETURN LEN(y)',
            '"x">=VAR y=BLANK() RETURN LEN(y)',
            '"a"=(VAR y=BLANK() RETURN y)',
            '""=VAR y=BLANK() RETURN y',
            '"a"<>VAR y=BLANK() RETURN BLANK()',
            '"a"<>VAR y=BLANK() RETURN 0',
            'TRUE()=VAR y=BLANK() RETURN y',
        ]
        for expression in errors:
            outcome = dax.local(expression)
            self.assertTrue(outcome.startswith(("LOCAL-REJECT", "ERR:")), f"{expression} -> {outcome}")
        values = {  # Power BI answers
            'VAR y=BLANK() RETURN "a"<y': "False",
            'VAR y=BLANK() RETURN "a"<>y': "True",
            '"a"<>VAR y=BLANK() RETURN y&""': "True",
            '"a"<>VAR y=BLANK() RETURN ""': "True",
            '1<VAR y=BLANK() RETURN y': "False",
            '"a"=VAR y="" RETURN y': "False",
            'BLANK()=VAR y="" RETURN y': "True",
        }
        for expression, want in values.items():
            self.assertEqual(want, dax.local(expression), expression)

    def test_a_blank_variable_in_a_filter_row_is_not_a_number(self) -> None:
        for expression, want in {  # Power BI answers (standard Facts)
            'COUNTROWS(FILTER(Facts,VAR t = BLANK() RETURN Facts[Region]=t))': "BLANK",
            'COUNTROWS(FILTER(Facts,VAR t = Facts[Note] RETURN Facts[Note]=t))': "6",
            'CALCULATE(COUNTROWS(Facts),NOT(VAR t = BLANK() RETURN Facts[Region]=t))': "6",
        }.items():
            self.assertEqual(want, dax.local(expression), expression)

    def test_a_topn_held_in_a_variable_is_refused_when_concatenated(self) -> None:
        for expression in (
            'VAR t=TOPN(3,Facts,Facts[Quantity]) RETURN CONCATENATEX(t,Facts[Region],"|")',
            'VAR t=TOPN(3,Facts,Facts[Quantity]) VAR u=t RETURN CONCATENATEX(u,Facts[Region],"|")',
        ):
            self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), expression)
        self.assertEqual("12", dax.local("VAR t=TOPN(3,Facts,Facts[Quantity]) RETURN SUMX(t,Facts[Quantity])"))
        self.assertEqual("West|North|East", dax.local('CONCATENATEX(TOPN(3,Facts,Facts[Quantity]),Facts[Region],"|")'))

    def test_a_var_block_on_the_right_of_a_logical_operator_or_power(self) -> None:  # refused until Task 12
        self.assertEqual("True", dax.local("3||VAR y=TRUE() RETURN y||FALSE()"))
        self.assertEqual("27", dax.local("3^VAR y=2 RETURN y+1"))

    def test_valid_shapes_stay_refused(self) -> None:
        for expression in (
            "VAR t=Facts RETURN SUMX(t,1)",
        ):
            self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), expression)


if __name__ == "__main__":
    unittest.main()
