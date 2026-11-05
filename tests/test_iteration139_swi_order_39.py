"""Iteration 139: Task 49 swi-order-39 (SUBSTITUTEWITHINDEX when the index table's order keys tie).

Covers:
- Ties over an index table of several columns (ALL(c1,c2), SUMMARIZE of several columns) and of one column are broken by the
  index table's dictionary walk order (dax_iteration_order), then the dense index is assigned.
- Index tables whose walk is not modelled keep refusing: TOPN, SAMPLE, SUMMARIZECOLUMNS, DISTINCT of a whole table, a
  loaded table (Facts) and FILTER(ALL(table), ...) with tied keys (live Power BI disagreed with the walk order there).
Expected values are the live Power BI answers saved in tools/parity/task49_swi_order_spec.json.
"""
from __future__ import annotations

import unittest

from tools import dax_oracle_diff as dax
from tools.parity_check import status


# (expression, Power BI answer) pairs measured in Power BI Desktop for the tied-key shapes this iteration models
MODELLED = [
    ('SUMX(SUBSTITUTEWITHINDEX(Facts,"i",ALL(Facts[Region],Facts[Note]),Facts[Region],1),[i]*[i])', "31"),
    ('CONCATENATEX(SUBSTITUTEWITHINDEX(Facts,"i",ALL(Facts[Region],Facts[Note]),Facts[Region],1),[i],"|",[i])', "0|1|1|2|3|4"),
    ('CONCATENATEX(SUBSTITUTEWITHINDEX(Facts,"i",SUMMARIZE(Facts,Facts[Region],Facts[Note]),1),[i],"|",[i])', "0|1|2|2|3|4"),
    ('CONCATENATEX(SUBSTITUTEWITHINDEX(Facts,"i",SUMMARIZE(Facts,Facts[Region],Facts[Note]),IF(Facts[Region]="East",1,2),ASC),[i],"|",[i])', "0|1|1|2|3|4"),
    ('MINX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),"i",ALL(Facts[Region],Facts[Note]),BLANK()),[i])', "0"),
    ('MAXX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),"i",SUMMARIZE(Facts,Facts[Region],Facts[Note]),0),[i])', "4"),
    ('AVERAGEX(SUBSTITUTEWITHINDEX(Facts,"i",SUMMARIZE(Facts,Facts[Region],Facts[Note]),Facts[Region],0),[i])', "2.33333333333333"),
    ('COUNTROWS(FILTER(SUBSTITUTEWITHINDEX(Facts,"i",ALL(Facts[Region],Facts[Note]),Facts[Region],DESC),[i]>0))', "5"),
    ('SUMX(SUBSTITUTEWITHINDEX(Facts,"i",ALL(Facts[Region],Facts[Note]),CALCULATE(COUNTROWS(Facts)),ASC),[i]*[i])', "46"),
]

# index tables whose tie order is not modelled: each must keep refusing with tied order keys
STAYS_REFUSED = [
    'COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",TOPN(2,VALUES(Facts[Region]),Facts[Region],ASC),0))',
    'COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",SAMPLE(3,VALUES(Facts[Region]),Facts[Region]),0))',
    'COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",SUMMARIZECOLUMNS(Facts[Region],"t",SUM(Facts[Quantity])),0))',
]


class TestIteration139SwiOrder39(unittest.TestCase):
    def test_modelled_tie_orders_match_power_bi(self) -> None:
        for expression, powerbi in MODELLED:
            with self.subTest(expression=expression):
                self.assertEqual("match", status(powerbi, dax.local(expression)), dax.local(expression))

    def test_unmodelled_index_tables_keep_refusing(self) -> None:
        for expression in STAYS_REFUSED:
            with self.subTest(expression=expression):
                self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), dax.local(expression))
        # Task 59 (2026-11-05): answered now; live Power BI answer
        self.assertEqual(dax.local('SUMX(SUBSTITUTEWITHINDEX(VALUES(Facts[Quantity]),"i",FILTER(ALL(Facts),Facts[Quantity]>1),Facts[Region],1),[i]*[i])'), "14")  # dax_battery_swi_extra.json
        self.assertEqual(dax.local('MINX(SUBSTITUTEWITHINDEX(Facts,"i",FILTER(ALL(Facts),Facts[Quantity]>1),Facts[Region],TRUE()),[i])'), "0")  # dax_battery_swi_extra.json
        self.assertEqual(dax.local('MAXX(SUBSTITUTEWITHINDEX(VALUES(Facts[Quantity]),"i",Facts,IF(Facts[Region]="East",1,2),ASC),[i])'), "5")  # dax_battery_swi_extra.json
        self.assertEqual(dax.local('MINX(SUBSTITUTEWITHINDEX(Facts,"i",Facts,Facts[Region],DESC),[i])'), "0")  # dax_battery_swi_extra.json
        self.assertEqual(dax.local('COUNTROWS(SUBSTITUTEWITHINDEX(Facts,"i",DISTINCT(Facts),Facts[Region],DESC,Facts[Note],DESC))'), "6")  # dax_battery_swi_extra2.json

    def test_output_row_order_follows_the_left_table_walk(self) -> None:
        # Live Power BI 2026-11-05 (fresh grid): the result of SUBSTITUTEWITHINDEX comes in the walk order of the left table
        # (dictionary order of its join columns), not in its source order; ALL(c1,c2) and a loaded table were out of order before.
        cases = [
            ('CONCATENATEX(SUBSTITUTEWITHINDEX(ALL(Facts[Region],Facts[Note]),"i",ALL(Facts[Note],Facts[Region]),0),[i],",")', "0,1,2,3,4"),
            ('CONCATENATEX(SUBSTITUTEWITHINDEX(ALL(Facts[Region],Facts[Note]),"i",ALL(Facts[Region]),LEN(Facts[Region])),[i],",")', "1,2,1,2,0"),
            ('CONCATENATEX(SUBSTITUTEWITHINDEX(Facts,"i",ALL(Facts[Note]),"x"),[i],",")', "0,0,1,1,1,2"),
            ('CONCATENATEX(SUBSTITUTEWITHINDEX(Facts,"i",ADDCOLUMNS(ALL(Facts[Region]),"k",1),Facts[Region],DESC),[i],",")', "2,2,2,0,0,1"),
        ]
        for expression, powerbi in cases:
            with self.subTest(expression=expression):
                self.assertEqual("match", status(powerbi, dax.local(expression)), dax.local(expression))


if __name__ == "__main__":
    unittest.main()
