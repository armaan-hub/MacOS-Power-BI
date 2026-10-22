"""RELATED returns a value of the target column's type (text, date, Boolean, number) along any chain of many-to-one / one-to-one links.

Expected values are live Power BI Desktop 2.157.879.0 answers (X4, 2026-10-23, tests/fixtures_related_values.json) on the
CB_Dim / CB_Fact / CB_Cal, ZO (orphan keys), ZS (snowflake), ZM (one-to-one, many-to-many) models and on the XB model, which the
fixture file describes: Fact -> Dim -> Reg -> Zone (three hops), Dim <-> One (one-to-one), Fact -> Cal, Fact -> Dx, an inactive
Fact[Alt] -> Dim link, text/date/Boolean/decimal/currency columns with blanks and a fact table with an orphan key and a blank key.

What the answers establish (each is pinned below and swept by test_saved_power_bi_answers):
  * RELATED(T[c]) is BLANK when a link of the chain finds no row (orphan key, blank key, an orphan at a later hop);
  * it follows the single shortest chain of active links from the many side to the one side, and a one-to-one link either way;
  * from the one side towards the many side, towards an unrelated table, outside a row context, on a column of the same
    table, over a column table (VALUES/DISTINCT of one column) or SELECTCOLUMNS/SUMMARIZE rows it is an error;
  * USERELATIONSHIP selects the link it follows, CROSSFILTER(..., NONE) switches it off;
  * ADDCOLUMNS / GENERATE / CROSSJOIN / FILTER / TOPN rows keep the fact row, so RELATED works on them.
"""
from __future__ import annotations

import datetime
import json
import unittest
from pathlib import Path

from analytics_studio import dax_dates
from analytics_studio.measures import MeasureError, evaluate_measures
from analytics_studio.power_query_values import model_text_normalizer
from tests.critic3_models import ours_for
from tests.test_allselected_critic2 import ours as ours_cb
from tools.dax_oracle_diff import HEADERS, LOCAL_ROWS
from tools.parity_check import status

FIXTURE = json.loads((Path(__file__).parent / "fixtures_related_values.json").read_text())
_TYPES = {"string": "text", "int64": "whole_number", "double": "decimal_number", "decimal": "fixed_decimal", "boolean": "boolean", "dateTime": "date"}
_FACTS = {"id": "facts", "name": "Facts", "headers": HEADERS, "rows": LOCAL_ROWS,
          "column_types": {"Sales": "decimal_number", "Quantity": "whole_number", "Region": "text", "Note": "text"}}


def _xb_model() -> tuple[list[dict], list[dict]]:
    spec = FIXTURE["models"]["XB"]
    tables = [_FACTS]
    for table in spec["tables"]:
        name = table["name"]
        if table.get("calendar"):
            rows, day = [], datetime.date(2023, 1, 1)
            while day <= datetime.date(2024, 12, 31):
                rows.append({"Date": day.isoformat(), "Year": str(day.year), "MonthNo": str(day.month), "Day": str(day.day)})
                day += datetime.timedelta(days=1)
            tables.append({"id": name.lower(), "name": name, "date_column": "Date", "headers": ["Date", "Year", "MonthNo", "Day"], "rows": rows,
                           "column_types": {"Date": "date", "Year": "whole_number", "MonthNo": "whole_number", "Day": "whole_number"}})
            continue
        columns = table["columns"]
        normalisers = {column: model_text_normalizer() for column, kind in columns if kind == "string"}
        rows = []
        for values in table["rows"]:
            cells = {}
            for (column, kind), value in zip(columns, values):
                if value is None:
                    cells[column] = None
                elif kind == "dateTime":
                    cells[column] = "%04d-%02d-%02d" % tuple(value[:3]) + ("T%02d:%02d:%02d" % tuple(value[3:]) if len(value) > 3 else "")
                elif kind == "boolean":
                    cells[column] = bool(value)
                elif kind == "string":
                    cells[column] = normalisers[column](value)
                else:
                    cells[column] = str(value)
            rows.append(cells)
        tables.append({"id": name.lower(), "name": name, "headers": [column for column, _k in columns], "rows": rows,
                       "column_types": {column: _TYPES[kind] for column, kind in columns}})
    relationships = []
    for link in spec["relationships"]:
        cardinality = {("many", "one"): "many_to_one", ("one", "one"): "one_to_one"}[(link["from_card"], link["to_card"])]
        relationships.append({
            "relationship_version": 1, "id": link["name"], "from": link["from_column"], "to": link["to_column"],
            "from_table_id": link["from_table"].lower(), "from_column": link["from_column"], "to_table_id": link["to_table"].lower(),
            "to_column": link["to_column"], "cardinality": cardinality, "is_active": link["active"],
            "cross_filter_direction": "both" if link["both"] or cardinality == "one_to_one" else "single",
        })
    return tables, relationships


_XB = _xb_model()


def ours(model: str, expression: str) -> str:
    """The local answer as the text the comparison harness shows for Power BI's."""
    if model == "CB":
        return ours_cb(expression)
    if model != "XB":
        return ours_for(model, expression)
    tables, relationships = _XB
    try:
        value = evaluate_measures([{"name": "P__", "expression": expression, "home_table_id": "facts"}], LOCAL_ROWS, HEADERS, "Facts",
                                  measure_names=["P__"], table_context=tables, relationships=relationships, active_table_id="facts")["P__"]
    except MeasureError as error:
        return f"LOCAL-REJECT:{error}"
    if isinstance(value, dax_dates.DaxDateTime):
        return dax_dates.oracle_text(value)
    return "BLANK" if value is None else str(value)


class RelatedValueTests(unittest.TestCase):
    def check(self, model: str, cases: dict[str, str]) -> None:
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                answer = ours(model, expression)
                self.assertEqual("match", status(expected, answer), f"Power BI {expected!r}, local {answer!r}")

    def test_text_boolean_and_date_values_of_the_related_row(self) -> None:
        self.check("XB", {
            'CONCATENATEX(XB_Fact,RELATED(XB_Dim[Name]),",",XB_Fact[Id],ASC)': "alpha,alpha,Beta,,delta,Epsilon,zeta,,,Beta",
            'CONCATENATEX(XB_Fact,(RELATED(XB_Dim[Flag]))&"",",",XB_Fact[Id],ASC)': "TRUE,TRUE,FALSE,TRUE,FALSE,FALSE,TRUE,,,FALSE",
            'CONCATENATEX(XB_Fact,(RELATED(XB_Dim[Born]))&"",",",XB_Fact[Id],ASC)': "2/29/2020,2/29/2020,5/5/2021,,12/31/2022,1/1/2023,6/30/2023,,,5/5/2021",
            'COUNTROWS(FILTER(XB_Fact,RELATED(XB_Dim[Name])="alpha"))': "2",
            'COUNTROWS(FILTER(XB_Fact,RELATED(XB_Dim[Name])="ALPHA"))': "2",
            "COUNTROWS(FILTER(XB_Fact,RELATED(XB_Dim[Flag])))": "4",
            "COUNTROWS(FILTER(XB_Fact,RELATED(XB_Dim[Born])>DATE(2021,1,1)))": "5",
            'SUMX(XB_Fact,IF(RELATED(XB_Dim[Name])="alpha",1,0))': "2",
            'CONCATENATEX(XB_Fact,(LEN(RELATED(XB_Dim[Name])))&"",",",XB_Fact[Id],ASC)': "5,5,4,,5,7,4,,,4",
            'CONCATENATEX(XB_Fact,(UPPER(RELATED(XB_Dim[Name])))&"",",",XB_Fact[Id],ASC)': "ALPHA,ALPHA,BETA,,DELTA,EPSILON,ZETA,,,BETA",
            "MAXX(XB_Fact,RELATED(XB_Cal[Date]))": "03/15/2024 00:00:00",
            "MINX(XB_Fact,RELATED(XB_Dim[Born]))": "02/29/2020 00:00:00",
            "COUNTX(XB_Fact,RELATED(XB_Dim[Name]))": "7",
            "COUNTAX(XB_Fact,RELATED(XB_Dim[Flag]))": "8",
        })

    def test_maxx_minx_of_text_and_dates(self) -> None:
        self.check("XB", {
            "MAXX(XB_Fact,RELATED(XB_Dim[Name]))": "zeta",
            "MINX(XB_Fact,RELATED(XB_Dim[Name]))": "alpha",
            'MAXX(XB_Fact,RELATED(XB_Dim[Name])&"")': "zeta",
            "COUNTROWS(FILTER(XB_Fact,RELATED(XB_Cal[Date])=MAXX(XB_Fact,RELATED(XB_Cal[Date]))))": "2",
        })
        self.check("CB", {"MAXX(CB_Fact,RELATED(CB_Dim[Cat]))": "B", "MINX(CB_Fact,RELATED(CB_Dim[Prod]))": "P1"})

    def test_a_chain_of_many_to_one_links_and_a_one_to_one_link(self) -> None:
        self.check("XB", {
            'CONCATENATEX(XB_Fact,RELATED(XB_Zone[ZName])&"",",",XB_Fact[Id],ASC)': "North zone,North zone,North zone,North zone,,,,,,North zone",
            'CONCATENATEX(XB_Fact,RELATED(XB_Reg[Zone])&"",",",XB_Fact[Id],ASC)': "Z1,Z1,Z1,Z1,,,,,,Z1",
            'CONCATENATEX(XB_Fact,RELATED(XB_One[Tag])&"",",",XB_Fact[Id],ASC)': "t1,t1,t2,,,,,,,t2",
        })
        self.check("ZM", {'CONCATENATEX(ZM_F,RELATED(ZM_W[Y]),",",ZM_F[Id],ASC)': "y1,y1,y2,y3,,"})
        self.check("ZS", {
            'CONCATENATEX(ZS_Fact,RELATED(ZS_Reg[Zone]),",",ZS_Fact[Id],ASC)': "Z1,Z1,Z1,Z1,Z1,Z1,Z1,Z1,Z1,Z2",
            'CONCATENATEX(ZS_Dim,RELATED(ZS_Reg[Zone]),",",ZS_Dim[Prod],ASC)': "Z1,Z1,Z1,Z1,Z2",
            'CONCATENATEX(ZS_Sup,RELATED(ZS_Reg[Zone]),",",ZS_Sup[Cat],ASC)': "Z1,Z1,Z2",
        })

    def test_a_key_without_a_match_gives_blank(self) -> None:
        self.check("XB", {
            "SUMX(XB_Fact,IF(ISBLANK(RELATED(XB_Dim[Name])),1,0))": "3",  # D3 has no name, Q9 is an orphan, one key is blank
            "SUMX(XB_Fact,IF(ISBLANK(RELATED(XB_Reg[RK])),1,0))": "4",  # D5 has a blank region key, D6 an orphan one, plus two fact orphans
            "SUMX(XB_Fact,IF(ISBLANK(RELATED(XB_Cal[Date])),1,0))": "2",  # a date outside the calendar and a blank date
            'CONCATENATEX(XB_Fact,COALESCE(RELATED(XB_Dim[Name]),"none"),",",XB_Fact[Id],ASC)': "alpha,alpha,Beta,none,delta,Epsilon,zeta,none,none,Beta",
        })
        self.check("ZO", {"SUMX(ZO_Fact,IF(ISBLANK(RELATED(ZO_Dim[Cat])),1,0))": "3", "SUMX(ZO_Fact,IF(ISBLANK(RELATED(ZO_Cal[Year])),1,0))": "2"})

    def test_relationship_selection(self) -> None:
        self.check("XB", {
            'CALCULATE(CONCATENATEX(XB_Fact,RELATED(XB_Dim[Name]),",",XB_Fact[Id],ASC),USERELATIONSHIP(XB_Fact[Alt],XB_Dim[DK]))': "Beta,alpha,Beta,,alpha,Beta,zeta,delta,Epsilon,",
            "CALCULATE(SUMX(XB_Fact,RELATED(XB_Dim[Wt])),USERELATIONSHIP(XB_Fact[Alt],XB_Dim[DK]))": "24.5",
            "CALCULATE(SUMX(XB_Fact,RELATED(XB_Dim[Wt])),CROSSFILTER(XB_Fact[DK],XB_Dim[DK],NONE))": "ERROR",
        })

    def test_relationship_and_row_context_errors(self) -> None:
        for expression in (
            "SUMX(XB_Dim,RELATED(XB_Fact[Amt]))",  # towards the many side
            "SUMX(XB_Zone,RELATED(XB_Cal[Year]))",  # no relationship
            "SUMX(XB_Fact,RELATED(XB_Fact[Amt]))",  # the same table
            "RELATED(XB_Dim[Wt])",  # outside a row context
            "SUM(XB_Fact[Amt])+RELATED(XB_Dim[Wt])",
            "SUMX(XB_Fact,CALCULATE(RELATED(XB_Dim[Wt])))",  # a context transition ends the row context
            'CONCATENATEX(VALUES(XB_Fact[DK]),RELATED(XB_Dim[Name]),",",XB_Fact[DK])',  # a column of the table has no relationships
            'CONCATENATEX(DISTINCT(XB_Fact[DK]),RELATED(XB_Dim[Name]),",",XB_Fact[DK])',
            'CONCATENATEX(SELECTCOLUMNS(XB_Fact,"k",XB_Fact[DK]),RELATED(XB_Dim[Name]),",",[k])',
            'CONCATENATEX(SUMMARIZE(XB_Fact,XB_Fact[DK]),RELATED(XB_Dim[Name]),",",XB_Fact[DK])',
            "SUMX(XB_Fact,RELATED(XB_Dim))",
            "SUMX(XB_Fact,RELATED(XB_Dim[Wt]+1))",
            "SUMX(XB_Fact,RELATED(XB_Dim[Nope]))",
        ):
            with self.subTest(expression=expression):
                self.assertTrue(ours("XB", expression).startswith("LOCAL-REJECT"), expression)

    def test_derived_tables_that_keep_the_fact_row(self) -> None:
        self.check("XB", {
            'SUMX(ADDCOLUMNS(XB_Fact,"x",1),RELATED(XB_Dim[Wt]))': "22.5",
            'COUNTROWS(FILTER(ADDCOLUMNS(XB_Fact,"x",1),RELATED(XB_Dim[Name])="alpha"))': "2",
            'SUMX(GENERATE(XB_Fact,FILTER(XB_Reg,XB_Reg[RK]="R1")),RELATED(XB_Dim[Wt]))': "22.5",
            'MAXX(ADDCOLUMNS(XB_Fact,"b",RELATED(XB_Dim[Born])),[b])': "06/30/2023 00:00:00",
            'SUMX(TOPN(4,ADDCOLUMNS(XB_Fact,"x",XB_Fact[Amt]),[x],DESC,XB_Fact[Id],ASC),RELATED(XB_Dim[Wt]))': "8",
            'SUMX(SELECTCOLUMNS(XB_Fact,"y",RELATED(XB_Dim[Wt])),[y])': "22.5",
        })

    def test_a_scalar_hoisted_out_of_a_calculate_filter_reads_the_enclosing_row(self) -> None:
        self.check("CB", {
            "SUMX(CB_Fact,CALCULATE(COUNTROWS(CB_Fact),CB_Dim[Cat]=RELATED(CB_Dim[Cat])))": "13",
            "SUMX(CB_Fact,CALCULATE(COUNTROWS(CB_Fact),ALL(CB_Fact),CB_Cal[Year]=RELATED(CB_Cal[Year])))": "89",
            "SUMX(CB_Fact,CALCULATE(COUNTROWS(CB_Fact),ALL(CB_Fact),CB_Fact[Dt]=RELATED(CB_Cal[Date])))": "25",
        })

    def test_sum_of_dates_is_a_date(self) -> None:
        self.check("CB", {"SUMX(CB_Fact,RELATED(CB_Cal[Date])-DATE(2024,1,5))": "10/31/1897 00:00:00"})

    def test_saved_power_bi_answers(self) -> None:
        failures = []
        for item in FIXTURE["items"]:
            answer = ours(item["model"], item["expr"])
            if status(item["powerbi"], answer) != "match":
                failures.append((item["model"], item["expr"], item["powerbi"], answer))
        self.assertEqual([], failures[:6], f"{len(failures)} of {len(FIXTURE['items'])} differ from Power BI")


if __name__ == "__main__":
    unittest.main()
