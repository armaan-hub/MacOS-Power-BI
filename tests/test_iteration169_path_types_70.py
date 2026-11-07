"""Task 80 (path-types-70): PATH values inside iterator comparisons over the parent-child models ZP and ZQ.

The expected Power BI Desktop answers are copied literally from the live-answer spec; this file never reads that spec.
An item passes when ours equals the Power BI answer (numbers compare float-equal), or when Power BI raised an error
and the local engine refuses the expression.
"""
from __future__ import annotations

import unittest

from tests.critic3_models import ours_for

ITEMS = [
    ('ZP', 'CONCATENATEX(ZP_Emp,PATH(ZP_Emp[Id],ZP_Emp[Parent]),";",ZP_Emp[Id])', '1;1|2;1|3;1|2|4;1|2|5;1|2|4|6;1|2|4|6|7;8;8|9;1|3|10'),
    ('ZP', 'SUMX(ZP_Emp,PATHLENGTH(PATH(ZP_Emp[Id],ZP_Emp[Parent])))', '26'),
    ('ZP', 'MAXX(ZP_Emp,PATHLENGTH(PATH(ZP_Emp[Id],ZP_Emp[Parent])))', '5'),
    ('ZP', 'CONCATENATEX(ZP_Emp,PATHITEM(PATH(ZP_Emp[Id],ZP_Emp[Parent]),2),";",ZP_Emp[Id])', ';2;3;2;2;2;2;;9;3'),
    ('ZP', 'CONCATENATEX(ZP_Emp,PATHITEM(PATH(ZP_Emp[Id],ZP_Emp[Parent]),2,INTEGER)+0,";",ZP_Emp[Id])', '0;2;3;2;2;2;2;0;9;3'),
    ('ZP', 'CONCATENATEX(ZP_Emp,PATHITEM(PATH(ZP_Emp[Id],ZP_Emp[Parent]),1,1),";",ZP_Emp[Id])', '1;1;1;1;1;1;1;8;8;1'),
    ('ZP', 'CONCATENATEX(ZP_Emp,PATHITEMREVERSE(PATH(ZP_Emp[Id],ZP_Emp[Parent]),2),";",ZP_Emp[Id])', ';1;1;2;2;4;6;;8;3'),
    ('ZP', 'CONCATENATEX(ZP_Emp,PATHITEM(PATH(ZP_Emp[Id],ZP_Emp[Parent]),-1),";",ZP_Emp[Id])', ';;;;;;;;;'),
    ('ZP', 'CONCATENATEX(ZP_Emp,PATHITEM(PATH(ZP_Emp[Id],ZP_Emp[Parent]),0),";",ZP_Emp[Id])', ';;;;;;;;;'),
    ('ZP', 'CONCATENATEX(ZP_Emp,PATHITEM(PATH(ZP_Emp[Id],ZP_Emp[Parent]),9),";",ZP_Emp[Id])', ';;;;;;;;;'),
    ('ZP', 'COUNTROWS(FILTER(ZP_Emp,PATHCONTAINS(PATH(ZP_Emp[Id],ZP_Emp[Parent]),2)))', '5'),
    ('ZP', 'COUNTROWS(FILTER(ZP_Emp,PATHCONTAINS(PATH(ZP_Emp[Id],ZP_Emp[Parent]),"4")))', '3'),
    ('ZP', 'SUMX(FILTER(ZP_Emp,PATHCONTAINS(PATH(ZP_Emp[Id],ZP_Emp[Parent]),1)),ZP_Emp[Amt])', '186.5'),
    ('ZP', 'CONCATENATEX(ZP_Emp,ZP_Emp[Name]&"/"&LOOKUPVALUE(ZP_Emp[Name],ZP_Emp[Id],PATHITEM(PATH(ZP_Emp[Id],ZP_Emp[Parent]),1,INTEGER)),";",ZP_Emp[Id])', 'Ann/Ann;Bob/Ann;Cid/Ann;Dee/Ann;Eve/Ann;Fay/Ann;Gus/Ann;Hal/Hal;Ivy/Hal;Jo/Ann'),
    ('ZP', 'CONCATENATEX(ZP_Emp,PATHITEMREVERSE(PATH(ZP_Emp[Id],ZP_Emp[Parent]),1,INTEGER)*2,";",ZP_Emp[Id])', '2;4;6;8;10;12;14;16;18;20'),
    ('ZP', 'PATHLENGTH("1|2|3")', '3'),
    ('ZP', 'PATHITEM("1|2|3",2)', '2'),
    ('ZP', 'PATHITEM("1|2|3",5)', 'BLANK'),
    ('ZP', 'PATHITEMREVERSE("1|2|3",3)', '1'),
    ('ZP', 'PATHCONTAINS("1|2|3","2")', 'True'),
    ('ZP', 'PATHCONTAINS("1|2|3",2)', 'True'),
    ('ZP', 'PATHCONTAINS("10|20","1")', 'False'),
    ('ZP', 'PATHLENGTH("")', '1'),
    ('ZP', 'PATHITEM("",1)', ''),
    ('ZP', 'PATHITEM("a||b",2)', ''),
    ('ZP', 'PATHLENGTH("a||b")', '3'),
    ('ZP', 'PATHITEM(" 7|8",1,INTEGER)', '7'),
    ('ZP', 'PATHITEM("1.5|2",1,INTEGER)', '2'),
    ('ZP', 'PATHITEM("x|2",1,INTEGER)', 'ERR:Exception calling "Read" with "0" argument(s): "The following system error occurred: Type mismatch. "'),
    ('ZP', 'PATHITEMREVERSE("1|2|3",0)', 'BLANK'),
    ('ZP', 'PATHLENGTH(BLANK())', 'BLANK'),
    ('ZP', 'PATHCONTAINS(BLANK(),"")', 'False'),
    ('ZP', 'PATHITEM("1|2",2.7)', 'BLANK'),
    ('ZP', 'PATHITEM("1|2","2")', '2'),
    ('ZP', 'MAXX(ZP_Emp,LEN(PATH(ZP_Emp[Id],ZP_Emp[Parent])))', '9'),
    ('ZP', 'COUNTROWS(FILTER(ZP_Emp,PATHLENGTH(PATH(ZP_Emp[Id],ZP_Emp[Parent]))=3))', '3'),
    ('ZP', 'CONCATENATEX(FILTER(ZP_Emp,ISBLANK(ZP_Emp[Parent])),ZP_Emp[Name],",",ZP_Emp[Name])', 'Ann,Hal'),
    ('ZQ', 'CONCATENATEX(ZQ_Org,PATH(ZQ_Org[Code],ZQ_Org[Boss]),";",ZQ_Org[Code])', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 39) The value \'\' in \'ZQ_Org\'[Boss] must also exist in \'ZQ_Org\'[Code]. Please add the missing data and try again."'),
    ('ZQ', 'SUMX(ZQ_Org,PATHLENGTH(PATH(ZQ_Org[Code],ZQ_Org[Boss])))', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 42) The value \'\' in \'ZQ_Org\'[Boss] must also exist in \'ZQ_Org\'[Code]. Please add the missing data and try again."'),
    ('ZQ', 'CONCATENATEX(ZQ_Org,PATHITEM(PATH(ZQ_Org[Code],ZQ_Org[Boss]),2),";",ZQ_Org[Code])', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 48) The value \'\' in \'ZQ_Org\'[Boss] must also exist in \'ZQ_Org\'[Code]. Please add the missing data and try again."'),
    ('ZQ', 'CONCATENATEX(ZQ_Org,PATHITEMREVERSE(PATH(ZQ_Org[Code],ZQ_Org[Boss]),2),";",ZQ_Org[Code])', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 55) The value \'\' in \'ZQ_Org\'[Boss] must also exist in \'ZQ_Org\'[Code]. Please add the missing data and try again."'),
    ('ZQ', 'COUNTROWS(FILTER(ZQ_Org,PATHCONTAINS(PATH(ZQ_Org[Code],ZQ_Org[Boss]),"b")))', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 56) The value \'\' in \'ZQ_Org\'[Boss] must also exist in \'ZQ_Org\'[Code]. Please add the missing data and try again."'),
    ('ZQ', 'SUMX(FILTER(ZQ_Org,PATHCONTAINS(PATH(ZQ_Org[Code],ZQ_Org[Boss]),"a")),ZQ_Org[Amt])', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 51) The value \'\' in \'ZQ_Org\'[Boss] must also exist in \'ZQ_Org\'[Code]. Please add the missing data and try again."'),
    ('ZQ', 'CONCATENATEX(ZQ_Org,PATHITEM(PATH(ZQ_Org[Code],ZQ_Org[Boss]),1,INTEGER),";",ZQ_Org[Code])', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 48) The value \'\' in \'ZQ_Org\'[Boss] must also exist in \'ZQ_Org\'[Code]. Please add the missing data and try again."'),
    ('ZQ', 'CALCULATE(CONCATENATEX(ZQ_Org,PATH(ZQ_Org[Code],ZQ_Org[Boss]),";",ZQ_Org[Code]),ZQ_Org[Grp]="Y")', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 49) The value \'\' in \'ZQ_Org\'[Boss] must also exist in \'ZQ_Org\'[Code]. Please add the missing data and try again."'),
    ('ZQ', 'COUNTROWS(FILTER(ZQ_Org,PATHCONTAINS(PATH(ZQ_Org[Code],ZQ_Org[Boss]),"")))', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 56) The value \'\' in \'ZQ_Org\'[Boss] must also exist in \'ZQ_Org\'[Code]. Please add the missing data and try again."'),
    ('ZP', 'MINX(ZP_Emp,PATHITEM(PATH(ZP_Emp[Id],ZP_Emp[Parent]),1,INTEGER))', '1'),
    ('ZP', 'SUMX(ZP_Emp,PATHITEM(PATH(ZP_Emp[Id],ZP_Emp[Parent]),2,INTEGER))', '25'),
    ('ZP', 'AVERAGEX(ZP_Emp,PATHLENGTH(PATH(ZP_Emp[Id],ZP_Emp[Parent])))', '2.6'),
    ('ZP', 'COUNTROWS(FILTER(ZP_Emp,PATHITEM(PATH(ZP_Emp[Id],ZP_Emp[Parent]),2,INTEGER)=2))', '5'),
    ('ZP', 'COUNTROWS(FILTER(ZP_Emp,PATHITEM(PATH(ZP_Emp[Id],ZP_Emp[Parent]),2)="2"))', '5'),
    ('ZP', 'COUNTROWS(FILTER(ZP_Emp,LEN(PATH(ZP_Emp[Id],ZP_Emp[Parent]))>3))', '5'),
    ('ZP', 'MAXX(ZP_Emp,PATH(ZP_Emp[Id],ZP_Emp[Parent]))', '8|9'),
    ('ZP', 'MINX(ZP_Emp,PATH(ZP_Emp[Id],ZP_Emp[Parent]))', '1'),
    ('ZP', 'CONCATENATEX(TOPN(3,ZP_Emp,PATHLENGTH(PATH(ZP_Emp[Id],ZP_Emp[Parent])),DESC,ZP_Emp[Id],ASC),ZP_Emp[Name],",")', 'Dee,Fay,Gus'),
    ('ZP', 'SUMX(ZP_Emp,IF(PATHCONTAINS(PATH(ZP_Emp[Id],ZP_Emp[Parent]),2),ZP_Emp[Amt]))', '175'),
    ('ZP', 'CONCATENATEX(ZP_Emp,ZP_Emp[Id]&":"&SUMX(FILTER(ALL(ZP_Emp),PATHCONTAINS(PATH(ZP_Emp[Id],ZP_Emp[Parent]),EARLIER(ZP_Emp[Id]))),ZP_Emp[Amt]),";",ZP_Emp[Id])', '1:186.5;2:175;3:1.5;4:105;5:50;6:65;7:5;8:16;9:9;10:1.5'),
    ('ZP', 'CONCATENATEX(VALUES(ZP_Emp[Parent]),ZP_Emp[Parent],",",ZP_Emp[Parent])', ',1,2,3,4,6,8'),
    ('ZP', 'COUNTROWS(ADDCOLUMNS(ZP_Emp,"p",PATH(ZP_Emp[Id],ZP_Emp[Parent])))', '10'),
    ('ZP', 'CONCATENATEX(ADDCOLUMNS(ZP_Emp,"L1",PATHITEM(PATH(ZP_Emp[Id],ZP_Emp[Parent]),1,INTEGER)),[Name]&"="&[L1],",",ZP_Emp[Id])', 'Ann=1,Bob=1,Cid=1,Dee=1,Eve=1,Fay=1,Gus=1,Hal=8,Ivy=8,Jo=1'),
    ('ZP', 'CONCATENATEX(GROUPBY(ADDCOLUMNS(ZP_Emp,"L",PATHLENGTH(PATH(ZP_Emp[Id],ZP_Emp[Parent]))),[L],"n",COUNTX(CURRENTGROUP(),1)),[L]&":"&[n],",",[L])', '1:2,2:3,3:3,4:1,5:1'),
    ('ZP', 'MAXX(ZP_Emp,PATHLENGTH(PATH(ZP_Emp[Id],ZP_Emp[Parent]))*2)', '10'),
    ('ZP', 'SUMX(ZP_Emp,PATHLENGTH(PATH(ZP_Emp[Id],ZP_Emp[Parent]))+ZP_Emp[Amt])', '228.5'),
    ('ZP', 'RANKX(ZP_Emp,PATHLENGTH(PATH(ZP_Emp[Id],ZP_Emp[Parent])))', 'ERR:Exception calling "Read" with "0" argument(s): "Query (1, 48) A table of multiple values was supplied where a single value was expected."'),
    ('ZP', 'CALCULATE(MAXX(ZP_Emp,PATHLENGTH(PATH(ZP_Emp[Id],ZP_Emp[Parent]))),ZP_Emp[Name]="Gus")', '5'),
    ('ZP', 'CONCATENATEX(ZP_Emp,PATHITEM(PATH(ZP_Emp[Id],ZP_Emp[Parent]),PATHLENGTH(PATH(ZP_Emp[Id],ZP_Emp[Parent]))-1,INTEGER),";",ZP_Emp[Id])', ';1;1;2;2;4;6;;8;3'),
    ('ZP', 'CONCATENATEX(ZP_Emp,FORMAT(PATHLENGTH(PATH(ZP_Emp[Id],ZP_Emp[Parent])),"00"),";",ZP_Emp[Id])', '01;02;02;03;03;04;05;01;02;03'),
    ('ZP', 'CONCATENATEX(ZP_Emp,PATHITEMREVERSE(PATH(ZP_Emp[Id],ZP_Emp[Parent]),1,TEXT),";",ZP_Emp[Id])', '1;2;3;4;5;6;7;8;9;10'),
    ('ZP', 'MAXX(ZP_Emp,PATHITEMREVERSE(PATH(ZP_Emp[Id],ZP_Emp[Parent]),2,INTEGER))', '8'),
    ('ZP', 'COUNTROWS(FILTER(ZP_Emp,ISBLANK(PATHITEM(PATH(ZP_Emp[Id],ZP_Emp[Parent]),3))))', '5'),
]


def _same(ours: str, powerbi: str) -> bool:
    if ours == powerbi:
        return True
    try:
        return float(ours) == float(powerbi)
    except ValueError:
        return False


class PathTypesIteratorTest(unittest.TestCase):
    def test_every_item_matches_power_bi(self) -> None:
        for model, expression, powerbi in ITEMS:
            with self.subTest(model=model, expression=expression):
                ours = ours_for(model, expression)
                if powerbi.startswith("ERR"):
                    self.assertTrue(ours.startswith("LOCAL-REJECT"), ours)
                else:
                    self.assertFalse(ours.startswith("LOCAL-"), ours)
                    self.assertTrue(_same(ours, powerbi), (ours, powerbi))


if __name__ == "__main__":
    unittest.main()
