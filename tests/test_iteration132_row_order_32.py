"""Iteration 132: Task 42 row-order-32 (the row order of tables).

Covers:
- Part A: SUBSTITUTEWITHINDEX with tied order values over unmodelled index tables
  (multi-column SUMMARIZE, base table Facts, TOPN, multi-column ALL, SUMMARIZECOLUMNS, SAMPLE)
  cleanly stays refused per standing rules and existing tests (test_iteration122_swi_order_22).
- Part B: TOJSON of VAR table expressions (materialized in forward order), while unmodelled
  orders (TOCSV of VAR, multi-column tables) stay refused.
- Part C: CONCATENATEX over TABLEOF(column) and TOPN(..., TABLEOF(column), ...) using VertiPaq dictionary walk order.
  Unmodelled combinations (UNION/DISTINCT over TABLEOF) stay refused.
"""
from __future__ import annotations

import unittest

from tools import dax_oracle_diff as dax
from tools.parity_check import status


class TestIteration132RowOrder32(unittest.TestCase):
    def test_part_a_substitutewithindex_unmodelled_ties_stay_refused(self) -> None:
        refused_cases = [
            'CONCATENATEX(SUBSTITUTEWITHINDEX(FILTER(VALUES(Facts[Region]),Facts[Region]<>"West"),"i",TOPN(2,VALUES(Facts[Region]),Facts[Region]),BLANK()),[i],"|",[i])',
            'SUMX(SUBSTITUTEWITHINDEX(Facts,"i",TOPN(2,VALUES(Facts[Region]),Facts[Region]),IF(Facts[Region]="East",1,2),ASC),[i])',
            'SUMX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",SAMPLE(3,VALUES(Facts[Region]),Facts[Region]),LEN(Facts[Region])),[i])',
        ]
        for expr in refused_cases:
            with self.subTest(expr=expr):
                actual = str(dax.local(expr))
                self.assertTrue(actual.startswith("LOCAL-REJECT:"), f"Expected refusal for {expr}, got: {actual}")
        # Task 49 (2026-11-05): answered now; live Power BI answers
        self.assertEqual(dax.local('MAXX(SUBSTITUTEWITHINDEX(Facts,"i",SUMMARIZE(Facts,Facts[Region],Facts[Note]),CALCULATE(COUNTROWS(Facts)),ASC),[i])'), "4")
        self.assertEqual(dax.local('SUMX(SUBSTITUTEWITHINDEX(Facts,"i",ALL(Facts[Region],Facts[Note]),Facts[Region],0),[i]*[i])'), "46")
        # Task 59 (2026-11-05): answered now; live Power BI answer
        self.assertEqual(dax.local('MAXX(SUBSTITUTEWITHINDEX(VALUES(Facts[Quantity]),"i",Facts,IF(Facts[Region]="East",1,2),ASC),[i])'), "5")  # dax_battery_swi_extra.json
        self.assertEqual(dax.local('MINX(SUBSTITUTEWITHINDEX(Facts,"i",Facts,Facts[Region],DESC),[i])'), "0")  # dax_battery_swi_extra.json
        self.assertEqual(dax.local('MAXX(SUBSTITUTEWITHINDEX(Facts,"i",Facts,Facts[Region],TRUE()),[i])'), "5")  # dax_battery_swi_extra.json
        self.assertEqual(dax.local('SUMX(SUBSTITUTEWITHINDEX(VALUES(Facts[Quantity]),"i",FILTER(ALL(Facts),Facts[Quantity]>1),Facts[Region],1),[i]*[i])'), "14")  # dax_battery_swi_extra.json
        self.assertEqual(dax.local('MINX(SUBSTITUTEWITHINDEX(Facts,"i",FILTER(ALL(Facts),Facts[Quantity]>1),Facts[Region],TRUE()),[i])'), "0")  # dax_battery_swi_extra.json
        self.assertEqual(dax.local('SUMX(SUBSTITUTEWITHINDEX(Facts,"i",FILTER(ALL(Facts),Facts[Quantity]>1),Facts[Region],TRUE()),[i])'), "6")  # dax_battery_swi_extra.json
        self.assertEqual(dax.local('COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),"i",FILTER(ALL(Facts),Facts[Quantity]>1),Facts[Region]&"x",ASC))'), "4")  # dax_battery_swi_extra.json

    def test_part_b_tocsv_tojson(self) -> None:
        cases = [
            # VAR table in TOJSON
            ('LEN(TOJSON(VAR t=FILTER(Facts,Facts[Quantity]>2) RETURN t))', '203'),
            ('LEN(TOJSON(VAR t=Facts RETURN t))', '289'),
            ('LEN(TOJSON(VAR t=ALL(Facts) RETURN t))', '289'),
            ('LEN(TOJSON(VAR a=1 VAR t=FILTER(Facts,Facts[Quantity]>a) RETURN t))', '232'),
            ('LEN(TOJSON(VAR t=FILTER(Facts,Facts[Quantity]>2) VAR u=t RETURN u))', '203'),
            ('LEN(TOJSON(VAR t=FILTER(Facts,Facts[Quantity]>2) RETURN FILTER(t,Facts[Region]<>"West")))', '176'),
            ('LEN(TOJSON(VAR t=Facts RETURN CALCULATETABLE(t,Facts[Region]="West")))', '289'),
            ('LEN(TOJSON(VAR a=2 RETURN FILTER(Facts,Facts[Quantity]>a)))', '203'),
            ('LEN(TOJSON(VAR t=CALCULATETABLE(Facts,Facts[Region]="West") RETURN t))', '175'),
            ('LEN(TOJSON(VAR t=VALUES(Facts[Region]) RETURN t))', '101'),
            ('LEN(TOJSON(VAR t=SUMMARIZE(Facts,Facts[Region]) RETURN t))', '101'),
            ('LEN(TOJSON(VAR t=DISTINCT(Facts[Quantity]) RETURN t))', '108'),
            ('LEN(TOJSON(VAR t=ALL(Facts[Region]) RETURN t))', '101'),
            ('LEN(TOJSON(VAR r="West" RETURN FILTER(VALUES(Facts[Region]),Facts[Region]<>r)))', '89'),
            # Negative cases stay refused
            ('TOCSV(VAR t=FILTER(Facts,Facts[Quantity]>2) RETURN t)', 'LOCAL-REJECT'),
            ('TOCSV(LINEST(Facts[Quantity],Facts[Sales]))', 'LOCAL-REJECT'),
            ('TOCSV(ADDMISSINGITEMS(Facts[Quantity],Facts,Facts[Quantity],Facts[Region],CALCULATETABLE(Facts,Facts[Quantity]>1)))', 'LOCAL-REJECT'),
        ]
        for expr, expected in cases:
            with self.subTest(expr=expr):
                actual = str(dax.local(expr))
                if expected == "LOCAL-REJECT":
                    self.assertTrue(actual.startswith("LOCAL-REJECT"), f"Expected refusal for {expr}, got: {actual}")
                else:
                    self.assertEqual(status(expected, actual), "match", f"Mismatch for {expr}: expected {expected}, got {actual}")

    def test_part_c_concatenatex_tableof(self) -> None:
        cases = [
            # TABLEOF dictionary order
            ('CONCATENATEX(TOPN(3,TABLEOF(Facts[Quantity]),Facts[Quantity],ASC),Facts[Quantity],",")', '2,0,1'),
            ('CONCATENATEX(TOPN(3,TABLEOF(Facts[Region]),Facts[Region],ASC),Facts[Region],",")', 'East,East,East'),
            ('CONCATENATEX(TOPN(3,TABLEOF(Facts[Quantity]),Facts[Quantity],DESC),Facts[Quantity],",")', '3,5,4'),
            ('CONCATENATEX(TOPN(3,TABLEOF(Facts[Sales]),Facts[Sales],DESC),Facts[Sales],",")', '2.5,20,10.5'),
            ('CONCATENATEX(FILTER(TABLEOF(Facts[Quantity]),Facts[Quantity]>2),Facts[Quantity],",")', '3,4,5'),
            ('CONCATENATEX(CALCULATETABLE(TABLEOF(Facts[Region]),Facts[Region]<>"West"),Facts[Region],",")', 'East,East,East,North'),
            # Negative: UNION / DISTINCT / TOCSV over TABLEOF stay refused
            ('CONCATENATEX(UNION(TABLEOF(Facts[Region]),TABLEOF(Facts[Region])),Facts[Region],",")', 'LOCAL-REJECT'),
            ('CONCATENATEX(DISTINCT(TABLEOF(Facts[Region])),Facts[Region],",")', 'LOCAL-REJECT'),
            ('TOCSV(TABLEOF(Facts[Region]),100)', 'LOCAL-REJECT'),
        ]
        for expr, expected in cases:
            with self.subTest(expr=expr):
                actual = str(dax.local(expr))
                if expected == "LOCAL-REJECT":
                    self.assertTrue(actual.startswith("LOCAL-REJECT"), f"Expected refusal for {expr}, got: {actual}")
                else:
                    self.assertEqual(status(expected, actual), "match", f"Mismatch for {expr}: expected {expected}, got {actual}")


    def test_var_held_table_keeps_its_own_row_order_or_is_refused(self) -> None:
        for expr in [
            'TOJSON(VAR t=SELECTCOLUMNS(Facts,"r",Facts[Region]) RETURN t)',
            'TOJSON(VAR t=SELECTCOLUMNS(Facts,"r",Facts[Region]) VAR u=t RETURN u,3)',
            'TOJSON(VAR t=TOPN(3,Facts,Facts[Sales]) RETURN t)',
            'TOJSON(VAR t=TOPN(3,Facts,Facts[Sales]) RETURN FILTER(t,TRUE()),3)',
            'TOJSON(VAR n=1 RETURN SELECTCOLUMNS(Facts,"r",Facts[Region]),10)',
        ]:
            with self.subTest(expr=expr):
                self.assertTrue(str(dax.local(expr)).startswith("LOCAL-REJECT"), expr)

    def test_concatenatex_without_order_by_around_tableof_is_refused(self) -> None:
        for expr in [
            'CONCATENATEX(FILTER(TOPN(4,TABLEOF(Facts[Sales]),Facts[Sales]),Facts[Sales]>0),Facts[Sales],",")',
            'CONCATENATEX(ADDCOLUMNS(FILTER(TABLEOF(Facts[Sales]),Facts[Sales]>0),"k",Facts[Quantity]),Facts[Sales],",")',
            'CONCATENATEX(TOPN(3,TABLEOF(Facts[Sales]),Facts[Quantity]),Facts[Sales],",")',
        ]:
            with self.subTest(expr=expr):
                self.assertTrue(str(dax.local(expr)).startswith("LOCAL-REJECT"), expr)


if __name__ == "__main__":
    unittest.main()
