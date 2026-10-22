"""ALLSELECTED on a model with relationships, found by the second Critic of iteration 80.

Expected values are live Power BI Desktop 2.157.879.0 answers (tests/fixtures_allselected_critic2.json): Facts plus a
Dim / Fact / Calendar model (Fact->Dim on Prod, Fact.Dt->Cal active, Fact.Ship->Cal inactive) with duplicate rows, a
blank amount and text that differs only in case. The three causes it pins:
  R1  SUMMARIZECOLUMNS: ALLSELECTED still sees the outer filter a group row replaced;
  R2  iterating ALLSELECTED(T) under a filter that is not a prefix of the table: filters are rows of the loaded table;
  R3  SUMMARIZE over a derived copy of a loaded table: group keys are rows of the loaded table.
"""
from __future__ import annotations

import datetime
import json
import unittest
from pathlib import Path

from analytics_studio import dax_dates
from analytics_studio.measures import MeasureError, evaluate_measures
from tools.dax_oracle_diff import HEADERS, LOCAL_ROWS
from tools.parity_check import status

FIXTURE = json.loads((Path(__file__).parent / "fixtures_allselected_critic2.json").read_text())


def _model() -> tuple[list[dict], list[dict], list[dict]]:
    spec = FIXTURE["model"]
    dim_headers = [name for name, _t in spec["dim_cols"]]
    dim_rows = [dict(zip(dim_headers, row)) for row in spec["dim_rows"]]
    fact_headers = [name for name, _t in spec["fact_cols"]]
    fact_rows = []
    for row in spec["fact_rows"]:
        cells = {}
        for (name, kind), value in zip(spec["fact_cols"], row):
            cells[name] = None if value is None else ("%04d-%02d-%02d" % tuple(value) if kind == "dateTime" else str(value))
        fact_rows.append(cells)
    calendar, day = [], datetime.date(2023, 1, 1)
    while day <= datetime.date(2024, 12, 31):
        calendar.append({"Date": day.isoformat(), "Year": str(day.year), "MonthNo": str(day.month), "Day": str(day.day)})
        day += datetime.timedelta(days=1)

    def relationship(identifier, from_table, from_column, to_table, to_column, active=True):
        return {
            "relationship_version": 1, "id": identifier, "from": from_column, "to": to_column, "from_table_id": from_table,
            "from_column": from_column, "to_table_id": to_table, "to_column": to_column, "cardinality": "many_to_one",
            "is_active": active, "cross_filter_direction": "single",
        }

    tables = [
        {"id": "facts", "name": "Facts", "headers": HEADERS, "rows": LOCAL_ROWS,
         "column_types": {"Sales": "decimal_number", "Quantity": "whole_number", "Region": "text", "Note": "text"}},
        {"id": "cb_dim", "name": "CB_Dim", "headers": dim_headers, "rows": dim_rows, "column_types": {h: "text" for h in dim_headers}},
        {"id": "cb_fact", "name": "CB_Fact", "headers": fact_headers, "rows": fact_rows,
         "column_types": {"Id": "whole_number", "Prod": "text", "Dt": "date", "Ship": "date", "Amt": "decimal_number", "Qty": "whole_number", "Reg": "text"}},
        {"id": "cb_dim2", "name": "CB_Dim2", "headers": ["K", "N"], "column_types": {"K": "text", "N": "text"},
         "rows": [{"K": "k1", "N": "n1"}, {"K": "k2", "N": "n2"}, {"K": "k3", "N": "n3"}]},
        {"id": "cb_fact2", "name": "CB_Fact2", "headers": ["K", "V"], "column_types": {"K": "text", "V": "whole_number"},
         "rows": [{"K": "k1", "V": "10"}, {"K": "k1", "V": "20"}, {"K": "k2", "V": "30"}, {"K": "k9", "V": "40"}, {"K": None, "V": "50"}]},
        {"id": "cb_cal", "name": "CB_Cal", "date_column": "Date", "headers": ["Date", "Year", "MonthNo", "Day"], "rows": calendar,
         "column_types": {"Date": "date", "Year": "whole_number", "MonthNo": "whole_number", "Day": "whole_number"}},
    ]
    relationships = [
        relationship("r1", "cb_fact", "Prod", "cb_dim", "Prod"),
        relationship("r2", "cb_fact", "Dt", "cb_cal", "Date"),
        relationship("r3", "cb_fact", "Ship", "cb_cal", "Date", False),
        relationship("r4", "cb_fact2", "K", "cb_dim2", "K"),
    ]
    measures = [{"name": name, "expression": text, "home_table_id": "cb_fact"} for name, text in spec["measures"].items()]
    return tables, relationships, measures


TABLES, RELATIONSHIPS, MEASURES = _model()


def ours(expression: str) -> str:
    try:
        value = evaluate_measures(
            MEASURES + [{"name": "P__", "expression": expression}], LOCAL_ROWS, HEADERS, "Facts", measure_names=["P__"],
            table_context=TABLES, relationships=RELATIONSHIPS, active_table_id="facts",
        )["P__"]
    except MeasureError as error:
        return f"LOCAL-REJECT:{error}"
    except Exception as error:  # an evaluator crash is a failure of its own
        return f"LOCAL-CRASH:{type(error).__name__}:{error}"
    if isinstance(value, dax_dates.DaxDateTime):
        return dax_dates.oracle_text(value)
    return "BLANK" if value is None else str(value)


class AllSelectedCriticTwoTests(unittest.TestCase):
    def test_saved_power_bi_answers(self) -> None:
        failures = []
        for item in FIXTURE["items"]:
            answer = ours(item["expr"])
            if status(item["powerbi"], answer) != "match":
                failures.append((item["expr"], item["powerbi"], answer))
        self.assertEqual([], failures[:5], f"{len(failures)} of {len(FIXTURE['items'])} differ from Power BI")

    def test_named_repros(self) -> None:
        cases = {
            # R1: the outer filter a SUMMARIZECOLUMNS group row replaced stays visible to ALLSELECTED
            'CALCULATE(SUMX(SUMMARIZECOLUMNS(Facts[Region],"m",CALCULATE(SUM(Facts[Sales]),ALLSELECTED())),[m]),Facts[Region]="East")': "11.5",
            # R2: ALLSELECTED(T) iterated under a filter that is not a prefix of the table
            'CALCULATE(COUNTX(ALLSELECTED(Facts),CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts[Region]))),Facts[Region]="East")': "3",
            'CALCULATE(SUMX(ALLSELECTED(CB_Dim),CALCULATE(SUM(CB_Fact[Amt]))),CB_Dim[Grp]="X")': "210",
            # R3: SUMMARIZE over a derived copy of a loaded table
            'CALCULATE(CONCATENATEX(SUMMARIZE(ALLSELECTED(Facts),Facts[Region],"m",SUM(Facts[Sales])),[m],",",Facts[Region],ASC),Facts[Region]="East")': "11.5",
        }
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.assertEqual(expected, ours(expression).removesuffix(".0"))

    def test_fixture_is_not_vacuous(self) -> None:
        self.assertGreater(len(FIXTURE["items"]), 1500)
        answers = {item["powerbi"] for item in FIXTURE["items"]}
        self.assertGreater(len(answers), 20)  # many different Power BI answers, not one constant


if __name__ == "__main__":
    unittest.main()
