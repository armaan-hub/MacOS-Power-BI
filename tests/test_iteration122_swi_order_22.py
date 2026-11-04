"""Iteration 122: tests for Task 32 swi-order-22 (SUBSTITUTEWITHINDEX row order & shared column names)."""

import unittest
from tools import dax_oracle_diff as dax


class TestIteration122SwiOrder22(unittest.TestCase):
    def test_part_a_tied_order_known_tables(self) -> None:
        # Example from Task 32 plan: EXCEPT as index table with tie-breaking row order
        self.assertEqual(
            dax.local('CONCATENATEX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",EXCEPT(VALUES(Facts[Region]),ROW("Region","Zed")),LEN(Facts[Region])),[s]&":"&[i],"|",[s])'),
            "3:2|4:0|8:1",
        )
        self.assertEqual(
            dax.local('CONCATENATEX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",EXCEPT(VALUES(Facts[Region]),ROW("Region","Zed")),LEN(Facts[Region]),ASC),[s]&":"&[i],"|",[s])'),
            "3:1|4:2|8:0",
        )
        # Single-column SUMMARIZE as index table with ties
        self.assertEqual(
            dax.local('COUNTROWS(SUBSTITUTEWITHINDEX(Facts,"i",SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),CALCULATE(COUNTROWS(Facts)),ASC))'),
            "6",
        )
        # FILTER over single-column table as index table with ties
        self.assertEqual(
            dax.local('SUMX(SUBSTITUTEWITHINDEX(VALUES(Facts[Quantity]),"i",FILTER(VALUES(Facts[Quantity]),Facts[Quantity]>1),Facts[Quantity],1),[i]*[i])'),
            "14",
        )
        # Single-column ALL as index table
        self.assertEqual(
            dax.local('COUNTROWS(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",ALL(Facts[Region]),0))'),
            "3",
        )

    def test_part_a_unmodelled_index_tables_refuse(self) -> None:
        # Task 49 (2026-11-05): answered now; live Power BI answer
        self.assertEqual(dax.local('MAXX(SUBSTITUTEWITHINDEX(Facts,"i",SUMMARIZE(Facts,Facts[Region],Facts[Note]),CALCULATE(COUNTROWS(Facts)),ASC),[i])'), "4")
        # Base table Facts with ties remains refused
        self.assertTrue(
            dax.local('MAXX(SUBSTITUTEWITHINDEX(VALUES(Facts[Quantity]),"i",Facts,IF(Facts[Region]="East",1,2),ASC),[i])').startswith("LOCAL-REJECT:")
        )
        # TOPN with ties in index table order remains refused
        self.assertTrue(
            dax.local('COUNTROWS(SUBSTITUTEWITHINDEX(FILTER(VALUES(Facts[Region]),Facts[Region]<>"West"),"i",TOPN(2,VALUES(Facts[Region]),Facts[Region]),BLANK()))').startswith("LOCAL-REJECT:")
        )
        # Task 49 (2026-11-05): answered now; live Power BI answer
        self.assertEqual(dax.local('SUMX(SUBSTITUTEWITHINDEX(Facts,"i",ALL(Facts[Region],Facts[Note]),Facts[Region],0),[i]*[i])'), "46")
        # SUMMARIZECOLUMNS with ties remains refused
        self.assertTrue(
            dax.local('CONCATENATEX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",SUMMARIZECOLUMNS(Facts[Region],"t",SUM(Facts[Quantity])),0),[s]&":"&[i],"|",[s])').startswith("LOCAL-REJECT:")
        )
        # SAMPLE with ties remains refused
        self.assertTrue(
            dax.local('CONCATENATEX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",SAMPLE(3,VALUES(Facts[Region]),Facts[Region]),0),[s]&":"&[i],"|",[s])').startswith("LOCAL-REJECT:")
        )

    def test_part_b_shared_column_names_matching_types(self) -> None:
        # Same name and same type, matching values: joins on both columns and matches
        self.assertEqual(
            dax.local('COUNTROWS(SUBSTITUTEWITHINDEX(ADDCOLUMNS(VALUES(Facts[Region]),"k",1),"i",ADDCOLUMNS(VALUES(Facts[Region]),"k",1),ISBLANK(Facts[Region]),ASC))'),
            "3",
        )
        self.assertEqual(
            dax.local('SUMX(SUBSTITUTEWITHINDEX(ADDCOLUMNS(VALUES(Facts[Region]),"k",1),"i",ADDCOLUMNS(VALUES(Facts[Region]),"k",1),ISBLANK(Facts[Region]),ASC),[i])'),
            "3",
        )
        # Same name and same type, differing values: join produces no matching rows -> BLANK
        self.assertEqual(
            dax.local('COUNTROWS(SUBSTITUTEWITHINDEX(ADDCOLUMNS(VALUES(Facts[Region]),"k",1),"i",ADDCOLUMNS(VALUES(Facts[Region]),"k",2),Facts[Region]))'),
            "BLANK",
        )
        self.assertEqual(
            dax.local('SUMX(SUBSTITUTEWITHINDEX(ADDCOLUMNS(VALUES(Facts[Region]),"k",1),"i",ADDCOLUMNS(VALUES(Facts[Region]),"k",2),Facts[Region]),[i])'),
            "BLANK",
        )
        # Case-insensitive name match: "k" vs "K"
        self.assertEqual(
            dax.local('COUNTROWS(SUBSTITUTEWITHINDEX(ADDCOLUMNS(VALUES(Facts[Region]),"k",CALCULATE(SUM(Facts[Quantity]))),"i",ADDCOLUMNS(VALUES(Facts[Region]),"K",1),Facts[Region]))'),
            "BLANK",
        )

    def test_part_b_shared_column_names_different_types(self) -> None:
        # Different data types (int64 vs text): column does not join, only Region joins
        self.assertEqual(
            dax.local('COUNTROWS(SUBSTITUTEWITHINDEX(ADDCOLUMNS(VALUES(Facts[Region]),"k",CALCULATE(SUM(Facts[Quantity]))),"i",ADDCOLUMNS(VALUES(Facts[Region]),"k","1"),Facts[Region]))'),
            "3",
        )
        # Different data types (int64 Quantity vs double Sales in SUMMARIZE): column "s" does not join
        self.assertEqual(
            dax.local('COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Sales])),Facts[Region]))'),
            "3",
        )
        self.assertEqual(
            dax.local('COUNTROWS(SUBSTITUTEWITHINDEX(GROUPBY(Facts,Facts[Region],"s",SUMX(CURRENTGROUP(),Facts[Quantity])),"i",SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Sales])),Facts[Region]))'),
            "3",
        )


if __name__ == "__main__":
    unittest.main()
