"""One CALCULATE that mixes relationship modifiers (USERELATIONSHIP, CROSSFILTER) or ALLSELECTED with filter-clearing modifiers
(ALL, ALL(col), ALLEXCEPT, ALLNOBLANKROW, REMOVEFILTERS) and with Boolean / FILTER / TREATAS / KEEPFILTERS filters (X3).

Expected values are live Power BI Desktop 2.157.879.0 answers (Critic 81 loop corpus, tests/fixtures_calculate_modifier_mix.json).
Rules the saved answers fix:
  * every filter argument is evaluated in the original context; the relationship modifiers then apply to the whole CALCULATE;
  * ALL(table) / REMOVEFILTERS(table) / ALLEXCEPT / ALLNOBLANKROW clear the tables reached through the relationships of the
    ENCLOSING context: a USERELATIONSHIP of the same CALCULATE does not widen them (it does when an outer CALCULATE holds it);
  * the clearing runs before the new filters, KEEPFILTERS intersects, and the expression sees the modified relationships.
Models: FB (Fact->Dim, Fact.Dt->Cal inactive), CB (Fact.Dt->Cal active, Fact.Ship->Cal inactive), FX (loose table), and the Z models
of tests/critic3_models.py.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from analytics_studio import dax_dates
from analytics_studio.measures import MeasureError, evaluate_measures
from tests import critic3_models as models
from tools.dax_oracle_diff import HEADERS, LOCAL_ROWS
from tools.parity_check import status

FIXTURE = json.loads((Path(__file__).parent / "fixtures_calculate_modifier_mix.json").read_text())

_CB_FACT = [
    (1, "P1", (2023, 1, 15), (2023, 1, 20), 10.0, 2, "East"), (2, "P1", (2023, 2, 10), (2023, 2, 12), 20.0, 3, "west"),
    (3, "P2", (2023, 2, 10), (2023, 3, 1), 30.0, 1, "West"), (4, "P2", (2024, 1, 5), (2024, 1, 9), 40.0, 4, "East"),
    (5, "P3", (2024, 2, 20), (2024, 2, 25), 50.0, 5, "East"), (6, "P3", (2024, 3, 15), (2024, 3, 20), 60.0, 2, "North"),
    (7, "P4", (2024, 3, 15), (2024, 4, 1), None, 3, "North"), (8, "P4", (2023, 1, 15), (2023, 1, 15), 70.0, 6, "East"),
    (9, "P1", (2024, 1, 5), (2024, 1, 6), 15.0, 2, "East"), (10, "P1", (2024, 1, 5), (2024, 1, 6), 15.0, 2, "East"),
    (11, "P1", (2024, 2, 10), (2024, 2, 11), 5.0, 1, "West"), (12, "P2", (2023, 12, 31), (2024, 1, 2), 25.0, 7, "east"),
    (13, "P3", (2024, 12, 31), (2024, 12, 31), 35.0, 1, "North"),
]
_FACT_FACTS = {"id": "facts", "name": "Facts", "headers": HEADERS, "rows": LOCAL_ROWS,
               "column_types": {"Sales": "decimal_number", "Quantity": "whole_number", "Region": "text", "Note": "text"}}
_BUILT: dict[str, tuple[list, list, list]] = {}


def _build(model: str) -> tuple[list, list, list]:
    if model in _BUILT:
        return _BUILT[model]
    if model in {"FB", "CB"}:
        prefix = model
        tables = [
            models._FACTS,
            models._table(f"{prefix}_Dim", models.DIM_COLS, models.DIM_ROWS),
            models._table(f"{prefix}_Fact", models.FACT_COLS, _CB_FACT),
            models._table(f"{prefix}_Cal", models.CAL_COLS, None),
        ]
        if model == "FB":
            specs = [("FB_r1", "FB_Fact", "Prod", "FB_Dim", "Prod", True, False, "many", "one"),
                     ("FB_r2", "FB_Fact", "Dt", "FB_Cal", "Date", False, False, "many", "one")]
        else:
            specs = [("CB_r1", "CB_Fact", "Prod", "CB_Dim", "Prod", True, False, "many", "one"),
                     ("CB_r2", "CB_Fact", "Dt", "CB_Cal", "Date", True, False, "many", "one"),
                     ("CB_r3", "CB_Fact", "Ship", "CB_Cal", "Date", False, False, "many", "one")]
        measures = [{"name": key, "expression": text.format(F=f"{prefix}_Fact", D=f"{prefix}_Dim", C=f"{prefix}_Cal"),
                     "home_table_id": f"{prefix}_fact".lower()} for key, text in models._MEASURES.items()]
        _BUILT[model] = (tables, [models._relationship(spec) for spec in specs], measures)
    elif model == "FX":
        _BUILT[model] = ([_FACT_FACTS], [], [])
    else:
        _BUILT[model] = models.build(model)
    return _BUILT[model]


def ours(model: str, expression: str) -> str:
    tables, relationships, measures = _build(model)
    home = measures[0]["home_table_id"] if measures else "facts"
    try:
        value = evaluate_measures(
            measures + [{"name": "P__", "expression": expression, "home_table_id": home}], LOCAL_ROWS, HEADERS, "Facts",
            measure_names=["P__"], table_context=tables, relationships=relationships, active_table_id="facts",
        )["P__"]
    except MeasureError as error:
        return f"LOCAL-REJECT:{error}"
    if isinstance(value, dax_dates.DaxDateTime):
        return dax_dates.oracle_text(value)
    return "BLANK" if value is None else str(value)


class RelationshipModifierRulesTests(unittest.TestCase):
    """The ordering rules, pinned on FB (the inactive Fact.Dt -> Cal relationship)."""

    def check(self, cases: dict[str, str]) -> None:
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.assertEqual(expected, ours("FB", expression).removesuffix(".0"))

    def test_same_calculate_userelationship_does_not_widen_all(self) -> None:
        # ALL(Fact) clears Dim only (the relationships of the enclosing context): the Cal filter of the outer CALCULATE survives
        # and, through the activated Dt relationship, still narrows the Fact rows, whatever the argument order
        self.check({
            "CALCULATE(CALCULATE(COUNTROWS(FB_Fact),USERELATIONSHIP(FB_Fact[Dt],FB_Cal[Date]),ALL(FB_Fact)),FB_Cal[Year]=2024)": "8",
            "CALCULATE(CALCULATE(COUNTROWS(FB_Fact),ALL(FB_Fact),USERELATIONSHIP(FB_Fact[Dt],FB_Cal[Date])),FB_Cal[MonthNo]=1)": "5",
            "CALCULATE(CALCULATE(COUNTROWS(FB_Fact),USERELATIONSHIP(FB_Fact[Dt],FB_Cal[Date]),REMOVEFILTERS(FB_Fact)),FB_Cal[Year]=2024)": "8",
            "CALCULATE(CALCULATE(COUNTROWS(FB_Fact),USERELATIONSHIP(FB_Fact[Dt],FB_Cal[Date]),ALLEXCEPT(FB_Fact,FB_Fact[Prod])),FB_Cal[Year]=2024)": "8",
            "CALCULATE(CALCULATE(COUNTROWS(FB_Fact),USERELATIONSHIP(FB_Fact[Dt],FB_Cal[Date]),ALLNOBLANKROW(FB_Fact)),FB_Cal[Year]=2024)": "8",
        })

    def test_outer_userelationship_does_widen_all(self) -> None:
        self.check({
            "CALCULATE(CALCULATE(COUNTROWS(FB_Fact),ALL(FB_Fact)),USERELATIONSHIP(FB_Fact[Dt],FB_Cal[Date]),FB_Cal[Year]=2024)": "13",
        })

    def test_all_of_the_activated_table_clears_it(self) -> None:
        self.check({
            "CALCULATE(CALCULATE(SUM(FB_Fact[Amt]),ALL(FB_Cal),USERELATIONSHIP(FB_Fact[Dt],FB_Cal[Date])),FB_Fact[Qty]>2)": "205",
            "CALCULATE(CALCULATE(COUNTROWS(FB_Fact),ALL(FB_Cal),USERELATIONSHIP(FB_Fact[Dt],FB_Cal[Date])),FB_Fact[Qty]>2)": "6",
            "CALCULATE(SUM(FB_Fact[Amt]),USERELATIONSHIP(FB_Fact[Dt],FB_Cal[Date]),ALL(FB_Cal))": "375",
        })

    def test_the_expression_sees_the_modified_relationship(self) -> None:
        self.check({
            "CALCULATE(COUNTROWS(VALUES(FB_Cal[MonthNo])),USERELATIONSHIP(FB_Fact[Dt],FB_Cal[Date]),ALL(FB_Fact))": "12",
            "CALCULATE(CALCULATE(DISTINCTCOUNT(FB_Cal[Year]),USERELATIONSHIP(FB_Fact[Dt],FB_Cal[Date]),REMOVEFILTERS(FB_Fact)),FB_Fact[Qty]>2)": "2",
        })


class AllSelectedMixTests(unittest.TestCase):
    def test_allselected_beside_userelationship_and_other_filters(self) -> None:
        for expression, expected in {
            "CALCULATE(SUM(FB_Fact[Amt]),ALLSELECTED(FB_Fact),USERELATIONSHIP(FB_Fact[Dt],FB_Cal[Date]))": "375",
            "CALCULATE(CALCULATE(SUM(FB_Fact[Amt]),USERELATIONSHIP(FB_Fact[Dt],FB_Cal[Date]),ALLSELECTED(FB_Fact)),FB_Fact[Qty]>2)": "205",
            "CALCULATE(COUNTROWS(ALL(FB_Cal[Year])),USERELATIONSHIP(FB_Fact[Dt],FB_Cal[Date]),ALLSELECTED(FB_Fact))": "2",
        }.items():
            with self.subTest(expression=expression):
                self.assertEqual(expected, ours("FB", expression).removesuffix(".0"))


class HeldCalculateTableTests(unittest.TestCase):
    """A VAR holding CALCULATETABLE(table, FILTER(..) / TREATAS(..)) used beside a clearing modifier validates."""

    def test_held_calculatetable_filters_beside_a_clear(self) -> None:
        for model, expression, expected in (
            ("CB", 'VAR v=CALCULATETABLE(CB_Fact,FILTER(CB_Dim,CB_Dim[Cat]="A")) RETURN CALCULATE(COUNTROWS(FILTER(CB_Fact,TRUE())),v,ALLSELECTED())', "8"),
            ("CB", 'VAR v=CALCULATETABLE(DISTINCT(CB_Dim[Cat]),TREATAS({2024},CB_Cal[Year])) RETURN CALCULATE(COUNTROWS(VALUES(CB_Fact)),v,ALLSELECTED(CB_Fact[Id]))', "13"),
            ("ZB", 'VAR v=CALCULATETABLE(ZB_Dim,FILTER(ALL(ZB_Fact[Id]),ZB_Fact[Id]<>3)) RETURN CALCULATE(COUNTROWS(FILTER(ZB_Fact,TRUE())),v,ALLSELECTED(ZB_Cal))', "10"),
        ):
            with self.subTest(expression=expression):
                self.assertEqual(expected, ours(model, expression).removesuffix(".0"))


class SavedPowerBIAnswersTests(unittest.TestCase):
    def test_saved_answers(self) -> None:
        failures = []
        for item in FIXTURE["items"]:
            answer = ours(item["model"], item["expr"])
            if status(item["powerbi"], answer) != "match":
                failures.append((item["model"], item["expr"], item["powerbi"], answer))
        self.assertEqual([], failures[:6], f"{len(failures)} of {len(FIXTURE['items'])} differ from Power BI")


if __name__ == "__main__":
    unittest.main()
