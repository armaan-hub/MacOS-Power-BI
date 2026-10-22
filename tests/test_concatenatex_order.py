"""CONCATENATEX (and every table iteration) walks the table in dictionary order, not source-row order.

Every expected value below is a live Power BI Desktop 2.157.879.0 answer (tools/parity/dax_battery_concatenatex_order.json,
re-asked independently of the research that found the rule). The rule: the engine iterates the distinct combinations of
the columns the expression reads; inside a column BLANK comes first, numbers ascending, text by first appearance in the
source rows (ASCII case-insensitive); with several columns the LATER table column is the major key. A double plus another
column, or a wide numeric range, comes out in plain source order instead.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from analytics_studio.measures import evaluate_measures
from analytics_studio.power_query_values import model_text_normalizer
from tools.dax_oracle_diff import local

FIXTURE = json.loads((Path(__file__).parent / "fixtures_concatenatex_order.json").read_text())


def on_table(table: str, expression: str) -> str:
    spec = FIXTURE["tables"][table]
    normalizers = {header: model_text_normalizer() for header in spec["headers"]}  # the controller does this when it loads a table
    rows = [{h: normalizers[h](v) if spec["types"][h] == "text" else v for h, v in row.items()} for row in spec["rows"]]
    spec = {**spec, "rows": rows}
    value = evaluate_measures(
        [{"name": "P__", "expression": expression}], spec["rows"], spec["headers"], table, measure_names=["P__"],
        table_context=[{"id": table.lower(), "name": table, "headers": spec["headers"], "rows": spec["rows"], "column_types": spec["types"]}],
        active_table_id=table.lower(),
    )["P__"]
    return "BLANK" if value is None else str(value)

CASES = {
    "one column: numbers ascending": [
        ('CONCATENATEX(Facts,Facts[Quantity],",")', "0,1,2,3,4,5"),
        ('CONCATENATEX(Facts,Facts[Sales],",")', ",-1.5,0,2.5,10.5,20"),
        ('CONCATENATEX(Facts,Facts[Quantity]*-1,",")', "0,-1,-2,-3,-4,-5"),
    ],
    "one column: text in first-appearance order, repeats merged next to each other": [
        ('CONCATENATEX(Facts,Facts[Region],",")', "East,East,East,West,West,North"),
        ('CONCATENATEX(Facts,Facts[Note],",")', ",,Paid,Paid,Paid,Late"),
        ('CONCATENATEX(Facts,UPPER(Facts[Region]),",")', "EAST,EAST,EAST,WEST,WEST,NORTH"),
    ],
    "booleans: FALSE before TRUE": [
        ('CONCATENATEX(Facts,Facts[Quantity]>2,",")', "FALSE,FALSE,FALSE,TRUE,TRUE,TRUE"),
        ('CONCATENATEX(Facts,NOT(Facts[Quantity]>2),",")', "TRUE,TRUE,TRUE,FALSE,FALSE,FALSE"),
        ('CONCATENATEX(Facts,ISBLANK(Facts[Sales]),",")', "TRUE,FALSE,FALSE,FALSE,FALSE,FALSE"),
    ],
    "several columns: the later table column is the major key": [
        ('CONCATENATEX(Facts,Facts[Region]&"-"&Facts[Quantity],"|")', "East-1|East-2|East-5|West-0|West-3|North-4"),
        ('CONCATENATEX(Facts,Facts[Quantity]&"-"&Facts[Region],"|")', "1-East|2-East|5-East|0-West|3-West|4-North"),
        ('CONCATENATEX(Facts,Facts[Region]&"-"&Facts[Note],"|")', "East-|West-|East-Paid|East-Paid|West-Paid|North-Late"),
        ('CONCATENATEX(Facts,Facts[Note]&"-"&Facts[Region],"|")', "-East|-West|Paid-East|Paid-East|Paid-West|Late-North"),
    ],
    "a double together with another column stays in source order": [
        ('CONCATENATEX(Facts,Facts[Sales]&"-"&Facts[Quantity],"|")', "10.5-2|20-3|-1.5-1|-4|0-0|2.5-5"),
        ('CONCATENATEX(Facts,Facts[Quantity]&"-"&Facts[Sales],"|")', "2-10.5|3-20|1--1.5|4-|0-0|5-2.5"),
    ],
    "no column read: nothing to order by": [
        ('CONCATENATEX(Facts,"a",",")', "a,a,a,a,a,a"),
    ],
    "ORDER BY: the key columns join the combination, ties keep that order": [
        ('CONCATENATEX(Facts,Facts[Quantity],",",Facts[Note])', "3,5,4,0,1,2"),
        ('CONCATENATEX(Facts,Facts[Quantity],",",Facts[Note],DESC)', "0,1,2,4,3,5"),
        ('CONCATENATEX(Facts,Facts[Quantity],",",Facts[Region])', "1,2,5,4,0,3"),
        ('CONCATENATEX(Facts,Facts[Quantity],",",Facts[Region],DESC)', "0,3,4,1,2,5"),
        ('CONCATENATEX(Facts,Facts[Quantity],",",Facts[Sales])', "1,4,0,5,2,3"),
        ('CONCATENATEX(Facts,Facts[Quantity],",",ISBLANK(Facts[Sales]))', "2,3,1,0,5,4"),
        ('CONCATENATEX(Facts,Facts[Quantity],",",Facts[Quantity]>2,DESC)', "3,4,5,0,1,2"),
    ],
    "FILTER: columns only in the predicate are not part of the combination": [
        ('CONCATENATEX(FILTER(Facts,Facts[Quantity]>0),Facts[Quantity],",")', "1,2,3,4,5"),
        ('CONCATENATEX(FILTER(Facts,Facts[Quantity]>0),Facts[Sales],",")', ",-1.5,2.5,10.5,20"),
        ('CONCATENATEX(FILTER(Facts,Facts[Region]<>"East"),Facts[Region],",")', "West,West,North"),
        ('CONCATENATEX(FILTER(Facts,Facts[Quantity]>=2),Facts[Region]&"-"&Facts[Quantity],",")', "East-2,East-5,West-3,North-4"),
    ],
    "CROSSJOIN: the first table varies fastest": [
        ('CONCATENATEX(CROSSJOIN(VALUES(Facts[Region]),VALUES(Facts[Quantity])),Facts[Region]&Facts[Quantity],",")',
         "East0,West0,North0,East1,West1,North1,East2,West2,North2,East3,West3,North3,East4,West4,North4,East5,West5,North5"),
        ('CONCATENATEX(CROSSJOIN(VALUES(Facts[Region]),VALUES(Facts[Note])),Facts[Region]&"/"&Facts[Note],",")',
         "East/,West/,North/,East/Paid,West/Paid,North/Paid,East/Late,West/Late,North/Late"),
    ],
    "UNION keeps the order it was built in": [
        ('CONCATENATEX(UNION(VALUES(Facts[Region]),VALUES(Facts[Region])),Facts[Region],",")', "East,West,North,East,West,North"),
    ],
    "SUMMARIZE / ALL(c1,c2) walk every column of the table, not only the ones read": [
        ('CONCATENATEX(SUMMARIZE(Facts,Facts[Region],Facts[Note]),Facts[Region],",")', "East,West,East,West,North"),
        ('CONCATENATEX(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Quantity],",")', "1,2,5,0,3,4"),
        ('CONCATENATEX(SUMMARIZE(Facts,Facts[Region],Facts[Sales]),Facts[Sales],",")', "-1.5,2.5,10.5,0,20,"),
        ('CONCATENATEX(ALL(Facts[Note],Facts[Region]),Facts[Region],",")', "East,West,East,West,North"),
    ],
    "DISTINCT of a whole table keeps source order": [
        ('CONCATENATEX(DISTINCT(Facts),Facts[Quantity],",")', "2,3,1,4,0,5"),
    ],
    "ADDCOLUMNS: its added columns pull their source columns into the combination": [
        ('CONCATENATEX(ADDCOLUMNS(Facts,"d",Facts[Quantity]*2),[d],",")', "0,2,4,6,8,10"),
        ('CONCATENATEX(ADDCOLUMNS(Facts,"d",Facts[Quantity]*2),Facts[Sales],",")', "10.5,20,-1.5,,0,2.5"),
        ('CONCATENATEX(ADDCOLUMNS(Facts,"d",Facts[Quantity]*2),[d]&"-"&Facts[Note],",")', "6-,10-,0-Paid,2-Paid,4-Paid,8-Late"),
        ('CONCATENATEX(ADDCOLUMNS(Facts,"d",7),[d]&Facts[Region],",")', "7East,7East,7East,7West,7West,7North"),
    ],
    "SELECTCOLUMNS: only the columns that are read count, resolved to the table it selects from": [
        ('CONCATENATEX(SELECTCOLUMNS(Facts,"q",Facts[Quantity]),[q],",")', "0,1,2,3,4,5"),
        ('CONCATENATEX(SELECTCOLUMNS(Facts,"x",-Facts[Quantity]),[x],",")', "0,-1,-2,-3,-4,-5"),
        ('CONCATENATEX(SELECTCOLUMNS(Facts,"x",Facts[Region]&"z"),[x],",")', "Eastz,Eastz,Eastz,Westz,Westz,Northz"),
        ('CONCATENATEX(SELECTCOLUMNS(Facts,"v",IF(Facts[Quantity]>2,7,"x")),[v]&"","|")', "x|x|x|7|7|7"),
        ('CONCATENATEX(SELECTCOLUMNS(Facts,"a",Facts[Region],"b",Facts[Note]),[a],",")', "East,East,East,West,West,North"),
        ('CONCATENATEX(SELECTCOLUMNS(Facts,"a",Facts[Region],"b",Facts[Note]),[b],",")', ",,Paid,Paid,Paid,Late"),
        ('CONCATENATEX(SELECTCOLUMNS(Facts,"a",Facts[Region],"b",Facts[Note]),[a]&[b],",")', "East,West,EastPaid,EastPaid,WestPaid,NorthLate"),
        ('CONCATENATEX(SELECTCOLUMNS(Facts,"r",Facts[Region],"q",Facts[Quantity]),[r]&[q],",")', "East1,East2,East5,West0,West3,North4"),
        ('CONCATENATEX(SELECTCOLUMNS(Facts,"s",Facts[Sales]),[s],",")', ",-1.5,0,2.5,10.5,20"),
    ],
    "TOPN: the rows come out as the array of a heap built over the walk order": [
        ('CONCATENATEX(TOPN(1,Facts,Facts[Quantity]),Facts[Quantity],",")', "5"),
        ('CONCATENATEX(TOPN(2,Facts,Facts[Quantity]),Facts[Quantity],",")', "4,5"),
        ('CONCATENATEX(TOPN(3,Facts,Facts[Quantity]),Facts[Quantity],",")', "3,5,4"),
        ('CONCATENATEX(TOPN(4,Facts,Facts[Quantity]),Facts[Quantity],",")', "2,3,5,4"),
        ('CONCATENATEX(TOPN(5,Facts,Facts[Quantity]),Facts[Quantity],",")', "1,3,2,5,4"),
        ('CONCATENATEX(TOPN(6,Facts,Facts[Quantity]),Facts[Quantity],",")', "0,1,2,3,4,5"),
        ('CONCATENATEX(TOPN(100,Facts,Facts[Quantity]),Facts[Quantity],",")', "0,1,2,3,4,5"),
        ('CONCATENATEX(TOPN(2,Facts,Facts[Quantity],ASC),Facts[Quantity],",")', "1,0"),
        ('CONCATENATEX(TOPN(3,Facts,Facts[Quantity],ASC),Facts[Quantity],",")', "2,0,1"),
        ('CONCATENATEX(TOPN(4,Facts,Facts[Quantity],ASC),Facts[Quantity],",")', "3,2,1,0"),
        ('CONCATENATEX(TOPN(3,Facts,Facts[Quantity]),Facts[Region]&"-"&Facts[Quantity],",")', "West-3,North-4,East-5"),
        ('CONCATENATEX(TOPN(3,Facts,Facts[Quantity]),Facts[Note],",")', ",,Late"),
        ('CONCATENATEX(TOPN(3,Facts,Facts[Sales]),Facts[Quantity],",")', "5,3,2"),
        ('CONCATENATEX(TOPN(4,Facts,Facts[Sales]),Facts[Sales],",")', "0,2.5,20,10.5"),
        ('CONCATENATEX(TOPN(3,VALUES(Facts[Quantity]),Facts[Quantity]),Facts[Quantity],",")', "3,5,4"),
        ('CONCATENATEX(TOPN(2,VALUES(Facts[Region]),Facts[Region]),Facts[Region],",")', "North,West"),
    ],
    "VALUES / DISTINCT / ALL of one column": [
        ('CONCATENATEX(VALUES(Facts[Quantity]),Facts[Quantity],",")', "0,1,2,3,4,5"),
        ('CONCATENATEX(DISTINCT(Facts[Region]),Facts[Region],",")', "East,West,North"),
        ('CONCATENATEX(ALL(Facts[Quantity]),Facts[Quantity],",")', "0,1,2,3,4,5"),
    ],
}


class ConcatenatexOrderTests(unittest.TestCase):
    def test_every_case_matches_power_bi(self) -> None:
        for title, cases in CASES.items():
            for expression, expected in cases:
                with self.subTest(title=title, expression=expression):
                    self.assertEqual(local(expression), expected)

    def test_other_table_shapes_match_power_bi(self) -> None:
        """Power BI answers on 51 other table shapes: dates, wide ints, doubles, text, booleans, 20 to 70 rows."""
        for probe in FIXTURE["probes"]:
            with self.subTest(table=probe["table"], expression=probe["expr"]):
                self.assertEqual(on_table(probe["table"], probe["expr"]), probe["powerbi"])


if __name__ == "__main__":
    unittest.main()
