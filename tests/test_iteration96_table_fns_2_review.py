"""Iteration 96 review (Part A, SUBSTITUTEWITHINDEX) against live Power BI Desktop (2.157.879.0).

The first build joined the two tables on column NAMES, checked a duplicate index key only for the rows the left table used,
and broke ties between equal order values in whatever order the local engine happened to hold the index rows. Power BI joins on
data lineage, rejects a duplicate key anywhere in the index table, and breaks ties in the index table's own row order.
Fixed here and pinned by three review batteries (10,101 + 4,851 + 1,424 fresh shapes); nothing in them may differ.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

PARITY = Path(__file__).resolve().parents[1] / "tools" / "parity"

# Valid DAX whose Power BI answer needs a rule the local engine does not model: it must refuse, never guess.
STAYS_REFUSED = [
    # tied order values over a TOPN index table (Power BI lays the TOPN rows out in its own order)
    'SUMX(SUBSTITUTEWITHINDEX(FILTER(VALUES(Facts[Region]),Facts[Region]<>"West"),"i",TOPN(2,VALUES(Facts[Region]),Facts[Region]),0),[i])',
    # tied order values over SUMMARIZECOLUMNS and SAMPLE
    'CONCATENATEX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",SUMMARIZECOLUMNS(Facts[Region],"t",SUM(Facts[Quantity])),0),[s]&":"&[i],"|",[s])',
    # tied order values over a base table
    "SUMX(SUBSTITUTEWITHINDEX(Facts,\"i\",ALL(Facts[Region],Facts[Note]),Facts[Region],0),[i]*[i])",
    # SELECTCOLUMNS leaves the join no lineage in Power BI
    'COUNTROWS(SUBSTITUTEWITHINDEX(SELECTCOLUMNS(VALUES(Facts[Region]),"Region",Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region]))',
    'VAR t=SELECTCOLUMNS(Facts,"Region",Facts[Region]) RETURN COUNTROWS(SUBSTITUTEWITHINDEX(t,"i",VALUES(Facts[Region]),Facts[Region]))',
    # a table with no lineage (DATATABLE) has no common column with a loaded one, whatever its column is called
    'COUNTROWS(SUBSTITUTEWITHINDEX(DATATABLE("Region",STRING,{{"East"},{"North"}}),"i",VALUES(Facts[Region]),Facts[Region]))',
    # the same computed column name on both sides
    'COUNTROWS(SUBSTITUTEWITHINDEX(ADDCOLUMNS(VALUES(Facts[Region]),"k",1),"i",ADDCOLUMNS(VALUES(Facts[Region]),"k",2),Facts[Region]))',
    # a duplicate key anywhere in the index table, although the left table only uses unique ones
    'COUNTROWS(SUBSTITUTEWITHINDEX(TOPN(2,VALUES(Facts[Region]),Facts[Region]),"i",FILTER(ALL(Facts),Facts[Quantity]>1),Facts[Region]))',
]


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


class SubstituteWithIndexReviewTest(unittest.TestCase):
    def test_review_batteries_never_differ_from_power_bi(self) -> None:
        for name, minimum in (("dax_battery_swi_extra", 9500), ("dax_battery_swi_extra2", 4300), ("dax_battery_swi_extra3", 800)):
            matched, bad = _replay(name)
            self.assertEqual([], bad, name)
            self.assertGreaterEqual(matched, minimum, name)

    def test_stays_refused(self) -> None:
        for expression in STAYS_REFUSED:
            outcome = dax.local(expression)
            self.assertTrue(outcome.startswith("LOCAL-REJECT"), f"{expression} -> {outcome}")

    def test_unique_order_values_and_known_orders_are_still_computed(self) -> None:
        self.assertEqual("3", dax.local('COUNTROWS(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region]))'))
        self.assertEqual("3", dax.local('SUMX(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region],ASC),[i])'))
        # ties over VALUES keep the distinct-values order (live Power BI)
        self.assertEqual("3:1|4:2|8:0", dax.local(
            'CONCATENATEX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),0),[s]&":"&[i],"|",[s])'))


if __name__ == "__main__":
    unittest.main()
