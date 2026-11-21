"""Task 246: DAX expressions where Power BI answers an error (or another value) and the local engine used to answer, plus the nested-builder shapes that stay refused.

Every expected answer is a live Power BI answer on the Facts table of tools.dax_oracle_diff (table 1: 6 rows: Sales, Quantity, Region, Note), a second table (SECOND_ROWS), a third
(THIRD_ROWS) or a fourth (FOURTH_ROWS, with twin rows).  An "ERR" answer is a Power BI error (the engine must refuse, never answer).

The measured rules, in plain words:
  * FORMAT(value, format) is an error in Power BI when the value is, or reads, a text column added to the iterated table (ADDCOLUMNS / SUMMARIZE / SUMMARIZECOLUMNS / SELECTCOLUMNS,
    also held in a VAR): every format string, every reader (CONCATENATEX, MAXX, SUMX, COUNTROWS(FILTER)); FORMAT of a stored text column is not an error.
  * SUMX / AVERAGEX / PRODUCTX / MAXX / MINX over a text column added by SUMMARIZECOLUMNS inside ISLOGICAL / ISNONTEXT / ISNUMERIC ... is an error even in a branch that is never taken.
  * CONCATENATEX over VALUES(column) inside a column added by SUMMARIZE / ADDCOLUMNS / SUMMARIZECOLUMNS without an order: the order of VALUES is not decided by a measured rule, so it is refused.
  * Columns added by SUMMARIZE / ADDCOLUMNS / SUMMARIZECOLUMNS that read ALLSELECTED, an iterator over VALUES(column), CALCULATETABLE or a nested CALCULATE in the shapes of
    _MEASURED_WRONG_GROUP_SHAPES (measured wrong on the engine) are refused; the other shapes stay answered and are right (FIXED_TO_RIGHT_ROWS, ANSWERED_ROWS).
"""
from __future__ import annotations

import pytest

from analytics_studio import measures
from tools import dax_oracle_diff
from tools.dax_oracle_diff import HEADERS, local, same

SECOND_ROWS = [("0.5", "7", "East", "Paid"), ("0.25", "9", "West", "Late"), ("", "0", "East", ""), ("-2", "30", "North", "Paid")]
THIRD_ROWS = [("1", "2", "East", "Paid"), ("2", "3", "West", ""), ("30", "4", "North", ""), ("4", "5", "West", ""), ("", "6", "East", "Late")]
FOURTH_ROWS = [("5", "1", "East", "Paid"), ("5", "2", "East", "Paid"), ("5", "2", "East", "Paid"), ("7", "3", "West", "Paid"), ("7", "3", "West", "Paid"), ("8", "4", "North", ""), ("2", "5", "East", "Late"), ("2", "5", "West", "Late")]
TABLE_ROWS = {2: SECOND_ROWS, 3: THIRD_ROWS, 4: FOURTH_ROWS}


def _use_table(monkeypatch: pytest.MonkeyPatch, table: int) -> None:
    if table in TABLE_ROWS:
        rows = [{header: (value if value != "" else None) for header, value in zip(HEADERS, row)} for row in TABLE_ROWS[table]]
        monkeypatch.setattr(dax_oracle_diff, "LOCAL_ROWS", rows)


# (table, expression, what Power BI says): Power BI raises an error; the engine used to answer
ERROR_ROWS = [
    (1, 'CALCULATE(ISNONTEXT(SWITCH(TRUE(),FALSE(),SUMX(SUMMARIZECOLUMNS(Facts[Quantity],"v",COALESCE(MAX(Facts[Note]),"-")&"!"),[v]),0.5)),Facts[Region]="East")', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 139) The function SUMX cannot work with values of type String."'),
    (1, 'CALCULATE(ISNUMERIC(IF(FALSE(),SUMX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(SUM(Facts[Quantity])>3,MAX(Facts[Note]),"z")),[v]),7)),Facts[Region]="East")', 'ERR:Exception calling "Execute'),
    (1, 'CALCULATE(ISTEXT(IF(TRUE(),7,SUMX(SUMMARIZECOLUMNS(Facts[Quantity],Facts[Region],"v",IF(SUM(Facts[Quantity])>3,MAX(Facts[Note]),"z")),[v]))),Facts[Region]="East")', 'ERR:Exception calling "Execute'),
    (1, 'ISSTRING(IF(FALSE(),SUMX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(SUM(Facts[Quantity])>3,"big","small")),[v]),7))', 'ERR:Exception calling "Execute'),
    (2, 'CALCULATE(ISNUMERIC(IF(FALSE(),SUMX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(SUM(Facts[Quantity])>3,MAX(Facts[Note]),"z")),[v]),7)),Facts[Region]="East")', 'ERR:Exception calling "Execute'),
    (2, 'CALCULATE(ISTEXT(IF(TRUE(),7,SUMX(SUMMARIZECOLUMNS(Facts[Quantity],Facts[Region],"v",IF(SUM(Facts[Quantity])>3,MAX(Facts[Note]),"z")),[v]))),Facts[Region]="East")', 'ERR:Exception calling "Execute'),
    (4, 'CALCULATE(ISNUMERIC(IF(FALSE(),GEOMEANX(SUMMARIZECOLUMNS(Facts[Quantity],Facts[Region],"v",SWITCH(TRUE(),SUM(Facts[Quantity])>3,"a","b")),[v]),7)),Facts[Region]="East")', 'ERR:Exception calling "Execute'),
    (4, 'CALCULATE(ISSTRING(IF(FALSE(),PRODUCTX(SUMMARIZECOLUMNS(Facts[Region],"v",SWITCH(TRUE(),SUM(Facts[Quantity])>3,"a","b")),[v]),7)),Facts[Region]="East")', 'ERR:Exception calling "Execute'),
    (1, 'CONCATENATEX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Note]),"s",COALESCE(MAX(Facts[Note]),"-")),FORMAT([s],"0.##"),",")', 'ERR:Exception calling "Read" w'),
    (1, 'CONCATENATEX(SUMMARIZECOLUMNS(Facts[Region],"s",COALESCE(MAX(Facts[Note]),"-")),[s],",",LEN(FORMAT([s],"0.##")),ASC)', 'ERR:Exception calling "Execute'),
    (1, 'MAXX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Note]),"s",SWITCH(TRUE(),SUM(Facts[Quantity])>3,"a","b")),FORMAT([s],"0"))', 'ERR:Exception calling "Execute'),
    (1, 'MAXX(SUMMARIZECOLUMNS(Facts[Region],"s","ab"),FORMAT([s],"@"))', 'ERR:Exception calling "Execute'),
    (2, 'CONCATENATEX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Note]),"s",MIN(Facts[Note])&"x"),FORMAT([s],"0.##"),",")', 'ERR:Exception calling "Read" w'),
    (2, 'CONCATENATEX(SUMMARIZECOLUMNS(Facts[Region],"s",COALESCE(MAX(Facts[Note]),"-")),[s],",",LEN(FORMAT([s],"0.##")),ASC)', 'ERR:Exception calling "Execute'),
    (2, 'MAXX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Note]),"s",IF(SUM(Facts[Quantity])>3,"big","small")),FORMAT([s],"0.##"))', 'ERR:Exception calling "Execute'),
    (2, 'MAXX(SUMMARIZE(Facts,Facts[Region],"s",MAX(Facts[Region])),FORMAT(IF(TRUE(),[s],"z"),"0"))', 'ERR:Exception calling "Execute'),
    (2, 'SUMX(SELECTCOLUMNS(VALUES(Facts[Region]),"s",COALESCE(MAX(Facts[Note]),"-")),LEN(FORMAT(IF(TRUE(),[s],"z"),"0")))', 'ERR:Exception calling "Execute'),
    (3, 'MAXX(ADDCOLUMNS(VALUES(Facts[Quantity]),"s",MIN(Facts[Note])&"x"),FORMAT([s],"0.##"))', 'ERR:Exception calling "Execute'),
    (4, 'CONCATENATEX(SELECTCOLUMNS(VALUES(Facts[Region]),"s",COALESCE(MAX(Facts[Note]),"-")),LEN(FORMAT([s],"0.##")),",")', 'ERR:Exception calling "Read" w'),
    (4, 'COUNTROWS(FILTER(ADDCOLUMNS(VALUES(Facts[Quantity]),"s",MIN(Facts[Note])&"x"),FORMAT([s],"0.##")="x"))', 'ERR:Exception calling "Execute'),
    (4, 'MAXX(SELECTCOLUMNS(VALUES(Facts[Region]),"s",COALESCE(MAX(Facts[Note]),"-")),FORMAT([s],"0"))', 'ERR:Exception calling "Execute'),
    (4, 'MAXX(SUMMARIZECOLUMNS(Facts[Region],"s",SWITCH(TRUE(),SUM(Facts[Quantity])>3,"a","b")),LEN(FORMAT([s],"0.##")))', 'ERR:Exception calling "Execute'),
    (1, 'CALCULATE(CONCATENATEX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Note],Facts[Quantity]),"s",CONCATENATEX(VALUES(Facts[Note]),CALCULATE(COUNTROWS(Facts)),"-",CALCULATE(COUNTROWS(Facts)),ASC)),FORMAT([s],"0.##"),",",FORMAT([s],"0.##"),DESC),Facts[Sales]>1,Facts[Quantity]<5)', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "The following system error occurred: Type mismatch. "'),
    (1, 'CONCATENATEX(ADDCOLUMNS(VALUES(Facts[Quantity]),"s",CONCATENATEX(VALUES(Facts[Region]),Facts[Region],"-")),[s],",",FORMAT([s],"@"),ASC)', 'ERR:Exception calling "Execute'),
    (1, 'COUNTROWS(FILTER(SUMMARIZE(Facts,Facts[Region],"s",CONCATENATEX(VALUES(Facts[Quantity]),Facts[Quantity],"-",Facts[Quantity],ASC)),FORMAT([s],"@")="x"))', 'ERR:Exception calling "Execute'),
    (2, 'CONCATENATEX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Note]),"s",CONCATENATEX(VALUES(Facts[Region]),Facts[Region],"-")),FORMAT(COALESCE([s],"q"),"0.##"),",")', 'ERR:Exception calling "Read" w'),
    (2, 'CONCATENATEX(SUMMARIZECOLUMNS(Facts[Region],"s",CONCATENATEX(VALUES(Facts[Region]),Facts[Region],"-")),LEN(FORMAT([s],"0.##")),",")', 'ERR:Exception calling "Read" w'),
    (2, 'MAXX(ADDCOLUMNS(VALUES(Facts[Quantity]),"s",CONCATENATEX(VALUES(Facts[Quantity]),Facts[Quantity],"-",Facts[Quantity],ASC)),FORMAT([s],"@"))', 'ERR:Exception calling "Execute'),
    (4, 'CONCATENATEX(ADDCOLUMNS(VALUES(Facts[Quantity]),"s",CONCATENATEX(VALUES(Facts[Region]),Facts[Region],"-")),[s],",",FORMAT([s],"@"),ASC)', 'ERR:Exception calling "Execute'),
    (4, 'COUNTROWS(FILTER(SUMMARIZE(Facts,Facts[Region],"s",CONCATENATEX(VALUES(Facts[Quantity]),Facts[Quantity],"-",Facts[Quantity],ASC)),FORMAT([s],"@")="x"))', 'ERR:Exception calling "Execute'),
]

# Power BI's answer differs from what the engine used to say; now refused, or answered equal to Power BI
REFUSED_OR_RIGHT_ROWS = [
    (1, 'CALCULATE(AVERAGEX(SUMMARIZE(Facts,Facts[Region],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),FILTER(ALL(Facts[Quantity]),Facts[Quantity]>1))),[s]),Facts[Quantity]>1)', '1.33333333333333'),
    (1, 'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Region],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),VALUES(Facts[Quantity]))),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Region],ASC),Facts[Quantity]>1)', '1|1|2'),
    (1, 'CALCULATE(SUMX(SUMMARIZE(Facts,Facts[Quantity],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),VALUES(Facts[Quantity]))),[s]),Facts[Region]="East")', '3'),
    (2, 'CALCULATE(AVERAGEX(SUMMARIZE(Facts,Facts[Region],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),REMOVEFILTERS(Facts[Sales],Facts[Region]))),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '1.5'),
    (2, 'CALCULATE(SUMX(SUMMARIZE(Facts,Facts[Region],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),FILTER(VALUES(Facts[Region]),Facts[Region]<>"West"))),[s]),ALL(Facts[Quantity]))', '4'),
    (3, 'CALCULATE(SUMX(SUMMARIZE(Facts,Facts[Quantity],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),VALUES(Facts[Quantity]))),[s]),Facts[Region]="East")', '2'),
    (4, 'CALCULATE(MAXX(SUMMARIZE(Facts,Facts[Region],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),Facts[Region]="East")),[s]),ALL(Facts[Quantity]))', '2'),
    (1, 'CALCULATE(AVERAGEX(SUMMARIZE(Facts,Facts[Note],"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts[Note])))),[s]),ALL(Facts[Quantity]))', '3.66666666666667'),
    (1, 'CALCULATE(SUMX(SUMMARIZE(Facts,Facts[Note],"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts)))),[s]*2),KEEPFILTERS(Facts[Region]<>"North"))', '40'),
    (1, 'MAXX(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],Facts[Note],"s",SUMX(VALUES(Facts[Note]),CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Quantity],Facts[Region])))),[s])', '22.5'),
    (3, 'CALCULATE(AVERAGEX(SUMMARIZE(Facts,Facts[Note],"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts[Note])))),[s]),ALL(Facts[Quantity]))', '2.33333333333333'),
    (3, 'CALCULATE(SUMX(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts[Quantity]))),"t",COUNTROWS(Facts)),[s]),Facts[Quantity]>1)', '9'),
    (4, 'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Sales],"s",SUMX(VALUES(Facts[Note]),CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Sales])))),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Sales],ASC),Facts[Sales]>1,Facts[Quantity]<5)', '8|29|29'),
    (4, 'CALCULATE(SUMX(SUMMARIZE(Facts,Facts[Quantity],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),VALUES(Facts[Quantity]))),[s]),Facts[Sales]>1,Facts[Quantity]<5)', '4'),
    (1, 'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Note],"s",CONCATENATEX(VALUES(Facts[Quantity]),Facts[Quantity],",")),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Note],ASC),Facts[Region]="East")', '2,1|5'),
    (1, 'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",CONCATENATEX(VALUES(Facts[Quantity]),Facts[Quantity],",")),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Region],ASC),Facts[Region]="East")', '2,1|5'),
    (1, 'CONCATENATEX(SUMMARIZE(Facts,Facts[Note],"s",CONCATENATEX(VALUES(Facts[Quantity]),Facts[Quantity],",")),IF(ISBLANK([s]),"b",[s]),"|",Facts[Note],ASC)', '3,5|4|2,1,0'),
    (1, 'CONCATENATEX(SUMMARIZE(Facts,Facts[Note],"s",CONCATENATEX(VALUES(Facts[Quantity]),Facts[Quantity],",")),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Note],ASC)', '2,1,0|3,5|4'),
    (4, 'CALCULATE(CONCATENATEX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],"t",SUM(Facts[Sales])),"s",COUNTROWS(CALCULATETABLE(Facts,FILTER(VALUES(Facts[Region]),Facts[Region]<>"West")))),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Quantity],ASC),KEEPFILTERS(Facts[Region]<>"North"))', 'b|1|1|1|2'),
    (4, 'SUMX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"s",SUMX(CALCULATETABLE(Facts,FILTER(VALUES(Facts[Region]),Facts[Region]<>"West")),Facts[Sales])),[s]*2)', '54'),
    (1, 'CALCULATE(AVERAGEX(SUMMARIZE(Facts,Facts[Region],"t",SUM(Facts[Quantity]),"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),ALLSELECTED(Facts[Sales]))),[s]),Facts[Sales]>1,Facts[Quantity]<5)', '1'),
    (1, 'CALCULATE(CONCATENATEX(SUMMARIZE(TOPN(3,Facts,Facts[Sales],DESC),Facts[Region],Facts[Quantity],"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts[Quantity])))),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Quantity],ASC),Facts[Region]="East")', '3|3|3'),
    (1, 'CALCULATE(SUMX(SUMMARIZE(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),Facts[Region],"s",CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts[Quantity],Facts[Region]))),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '10'),
    (1, 'CALCULATE(SUMX(SUMMARIZE(Facts,Facts[Region],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),FILTER(VALUES(Facts[Region]),Facts[Region]<>"West"))),[s]),ALL(Facts[Quantity]))', '5'),
    (1, 'CONCATENATEX(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],"s",SUMX(VALUES(Facts[Sales]),CALCULATE(COUNTROWS(Facts),ALL(Facts[Quantity])))),IF(ISBLANK([s]),"b",[s]),"|",Facts[Region],ASC,Facts[Quantity],ASC)', '2|2|1|1|1|1'),
    (2, 'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Quantity],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),ALLSELECTED(Facts[Note]))),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Quantity],ASC),KEEPFILTERS(Facts[Region]<>"North"))', '1|1|1'),
    (2, 'MAXX(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],Facts[Note],"s",SUMX(VALUES(Facts[Note]),CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Quantity],Facts[Region])))),[s])', '0.25'),
    (3, 'CALCULATE(MAXX(SUMMARIZE(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),Facts[Quantity],"s",SUMX(VALUES(Facts[Note]),CALCULATE(SUM(Facts[Sales]),Facts[Quantity]>1))),[s]),Facts[Quantity]>1)', '30'),
    (3, 'CALCULATE(SUMX(SUMMARIZE(FILTER(Facts,Facts[Quantity]>1),Facts[Region],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),ALLEXCEPT(Facts,Facts[Note]))),[s]),Facts[Quantity]>1)', '4'),
    (3, 'CALCULATE(SUMX(SUMMARIZE(TOPN(3,Facts,Facts[Sales],DESC),Facts[Region],Facts[Quantity],"s",SUMX(VALUES(Facts[Note]),CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Quantity],Facts[Region])))),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '13'),
    (4, 'CALCULATE(CONCATENATEX(SUMMARIZE(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),Facts[Region],"s",CALCULATE(COUNTROWS(Facts),Facts[Region]="East")),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Region],ASC),Facts[Note]="Paid")', 'b|3'),
    (4, 'CALCULATE(MAXX(ADDCOLUMNS(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),Facts[Region]<>"North"),ALLSELECTED(Facts[Quantity]))),[s]),Facts[Region]="East")', '19'),
    (4, 'CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],Facts[Note]),Facts[Region],"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts)))),[s]),Facts[Quantity]>1)', '4'),
    (4, 'CALCULATE(SUMX(SUMMARIZE(CALCULATETABLE(Facts,Facts[Region]="East"),Facts[Region],Facts[Quantity],"s",SUMX(VALUES(Facts[Note]),CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Quantity])))),[s]*2),ALL(Facts[Quantity]))', '64'),
    (4, 'CALCULATE(SUMX(SUMMARIZE(Facts,Facts[Region],"s",SUMX(VALUES(Facts[Note]),CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Quantity],Facts[Region])))),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '66'),
    (4, 'MAXX(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],Facts[Note],"s",SUMX(VALUES(Facts[Note]),CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Quantity],Facts[Region])))),[s])', '29'),
]

# measured wrong before, now answered right
FIXED_TO_RIGHT_ROWS = [
    (1, 'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Region],"s",COUNTROWS(ALLSELECTED(Facts[Note]))),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Region],ASC),Facts[Quantity]>1)', '1|1|2'),
    (1, 'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",COUNTROWS(ALLSELECTED(Facts[Note]))),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Region],ASC),Facts[Quantity]>1)', '1|1|2|2'),
    (1, 'CALCULATE(COUNTROWS(FILTER(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",COUNTROWS(ALLSELECTED(Facts[Note]))),[s]>1)),Facts[Quantity]>1)', '2'),
    (1, 'CALCULATE(COUNTROWS(FILTER(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",COUNTROWS(ALLSELECTED(Facts[Note]))),[s]>1)),Facts[Sales]>1,Facts[Quantity]<5)', 'BLANK'),
    (1, 'CALCULATE(ISDECIMAL(AVERAGEX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Quantity])>2,CURRENCY(3),7)),[v])),KEEPFILTERS(Facts[Region]<>"West"))', 'True'),
    (1, 'CALCULATE(SUMX(SUMMARIZE(FILTER(Facts,Facts[Quantity]>1),Facts[Region],"s",COUNTROWS(ALLSELECTED(Facts[Note]))),[s]),Facts[Quantity]>1)', '4'),
    (1, 'CALCULATE(SUMX(SUMMARIZE(Facts,Facts[Region],"s",COUNTROWS(ALLSELECTED(Facts[Note]))),[s]),Facts[Quantity]>1)', '4'),
    (1, 'CALCULATE(SUMX(SUMMARIZE(Facts,Facts[Region],"t",SUM(Facts[Quantity]),"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),ALLSELECTED(Facts[Sales]))),[s]),Facts[Quantity]>1)', '4'),
    (1, 'CALCULATE(SUMX(SUMMARIZE(Facts,Facts[Region],"t",SUM(Facts[Quantity]),"s",COUNTROWS(ALLSELECTED(Facts[Note]))),[s]),Facts[Quantity]>1)', '4'),
    (1, 'CALCULATE(SUMX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",COUNTROWS(ALLSELECTED(Facts[Note]))),[s]),Facts[Quantity]>1)', '6'),
    (1, 'SUMX(SUMMARIZE(FILTER(Facts,Facts[Quantity]>1),Facts[Region],"s",COUNTROWS(ALLSELECTED(Facts[Note]))),[s])', '4'),
    (2, 'CALCULATE(ISDECIMAL(AVERAGEX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Quantity])>2,CURRENCY(3),7)),[v])),KEEPFILTERS(Facts[Region]<>"West"))', 'True'),
]

# refused before, now answered and equal to Power BI
ANSWERED_ROWS = [
    (1, 'CALCULATE(ISCURRENCY(COALESCE(SUM(Facts[Sales]),SUMX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Quantity])>2,CURRENCY(3),7)),[v]*2))),Facts[Region]="East")', 'False'),
    (1, 'CALCULATE(ISCURRENCY(MAXX(SUMMARIZECOLUMNS(Facts[Region],"v",IFERROR(1/SUM(Facts[Quantity]),"d0")),[v])),Facts[Note]="Paid")', 'False'),
    (1, 'CALCULATE(ISCURRENCY(SUMX(SUMMARIZECOLUMNS(Facts[Region],"v",IFERROR(1/SUM(Facts[Quantity]),"d0")),[v])),Facts[Region]="East")', 'False'),
    (1, 'CALCULATE(ISDECIMAL(MAXX(SUMMARIZECOLUMNS(Facts[Region],"v",IFERROR(1/MIN(Facts[Quantity]),0)),[v]+0)),KEEPFILTERS(Facts[Region]<>"West"))', 'False'),
    (1, 'CALCULATE(ISDOUBLE(COALESCE(MINX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Quantity])>2,CURRENCY(3),7)),[v]),1/3)),ALL(Facts))', 'True'),
    (1, 'CALCULATE(ISDOUBLE(MINX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Quantity])>2,CURRENCY(3),7)),[v])),ALL(Facts))', 'False'),
    (1, 'CALCULATE(ISINT64(IF(MAX(Facts[Sales])>50,MAXX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MIN(Facts[Quantity])=0,0.5,MIN(Facts[Quantity]))),[v]+0),0.5)),Facts[Note]="Paid")', 'False'),
    (1, 'CALCULATE(ISINT64(MINX(SUMMARIZECOLUMNS(Facts[Region],"v",COALESCE(MIN(Facts[Note]),"none")),[v])),Facts[Note]="Paid")', 'False'),
    (1, 'CALCULATE(ISINTEGER(COALESCE(COUNTROWS(Facts),MAXX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Sales])>15,MAX(Facts[Sales]),0)),-[v]))),REMOVEFILTERS(Facts[Region]))', 'False'),
    (1, 'CALCULATE(ISINTEGER(IFERROR(SUM(Facts[Sales]),MINX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Quantity])>2,CURRENCY(3),7)),[v]))),KEEPFILTERS(Facts[Region]<>"West"))', 'False'),
    (1, 'CALCULATE(ISINTEGER(MINX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Quantity])>2,CURRENCY(3),7)),[v])),Facts[Quantity]>1)', 'False'),
    (1, 'CALCULATE(ISINTEGER(SWITCH(TRUE(),HASONEVALUE(Facts[Region]),0.5,MAXX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Sales])>15,MAX(Facts[Sales]),0)),[v]))),ALL(Facts))', 'False'),
    (1, 'ISDECIMAL(SWITCH(TRUE(),COUNTROWS(Facts)>2,MAXX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Sales])>15,MAX(Facts[Sales]),0)),[v]+0),COUNTROWS(Facts)))', 'False'),
    (1, 'ISINTEGER(SUMX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Sales])>15,MAX(Facts[Sales]),0)),[v]*2))', 'False'),
    (2, 'CALCULATE(ISCURRENCY(MAXX(SUMMARIZECOLUMNS(Facts[Region],"v",IFERROR(1/MIN(Facts[Quantity]),0)),-[v])),Facts[Note]="Paid")', 'False'),
    (2, 'CALCULATE(ISCURRENCY(SUMX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Sales])>15,MAX(Facts[Sales]),0)),[v])),ALL(Facts))', 'False'),
    (2, 'CALCULATE(ISDECIMAL(MAXX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Sales])>15,MAX(Facts[Sales]),0)),-[v])),KEEPFILTERS(Facts[Region]<>"West"))', 'False'),
    (2, 'CALCULATE(ISDECIMAL(SWITCH(TRUE(),ISFILTERED(Facts[Region]),5,MINX(SUMMARIZECOLUMNS(Facts[Region],"v",IFERROR(1/MIN(Facts[Quantity]),0)),[v]))),ALL(Facts))', 'False'),
    (2, 'CALCULATE(ISDOUBLE(MAXX(SUMMARIZECOLUMNS(Facts[Region],"v",IFERROR(MAX(Facts[Sales])/MIN(Facts[Quantity]),"e")),[v])),ALL(Facts))', 'True'),
    (2, 'CALCULATE(ISINT64(IF(FALSE(),1/3,MAXX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MIN(Facts[Quantity])=0,0.5,MIN(Facts[Quantity]))),[v]))),Facts[Quantity]>1)', 'False'),
    (2, 'CALCULATE(ISINT64(MAXX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MIN(Facts[Quantity])=0,0.5,MIN(Facts[Quantity]))),[v])),Facts[Quantity]>1)', 'False'),
    (2, 'CALCULATE(ISINT64(SUMX(SUMMARIZECOLUMNS(Facts[Region],"v",IFERROR(1/SUM(Facts[Quantity]),"d0")),[v]*2)),Facts[Quantity]>1)', 'False'),
    (2, 'CALCULATE(ISINTEGER(IFERROR(DATE(2020,1,1),MAXX(SUMMARIZECOLUMNS(Facts[Region],"v",COALESCE(MIN(Facts[Note]),"none")),[v]+0))),Facts[Note]="Paid")', 'False'),
    (2, 'CALCULATE(ISINTEGER(MAXX(SUMMARIZECOLUMNS(Facts[Region],"v",IFERROR(MAX(Facts[Sales])/MIN(Facts[Quantity]),"e")),-[v])),Facts[Quantity]>1)', 'False'),
    (2, 'CALCULATE(ISINTEGER(SUMX(SUMMARIZECOLUMNS(Facts[Region],"v",IFERROR(MAX(Facts[Sales])/MIN(Facts[Quantity]),"e")),[v])),Facts[Region]="East")', 'False'),
    (2, 'ISDECIMAL(SWITCH(TRUE(),COUNTROWS(Facts)>2,0.5,MAXX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Quantity])>2,CURRENCY(3),7)),[v]+0)))', 'False'),
    (2, 'ISINTEGER(SUMX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Sales])>15,MAX(Facts[Sales]),0)),[v]))', 'False'),
    (3, 'CALCULATE(ISDECIMAL(COALESCE(MAXX(SUMMARIZECOLUMNS(Facts[Region],"v",IFERROR(1/MIN(Facts[Quantity]),0)),[v]+0),DATE(2020,1,1))),KEEPFILTERS(Facts[Region]<>"West"))', 'False'),
    (3, 'CALCULATE(ISDOUBLE(IFERROR(AVERAGE(Facts[Sales]),SUMX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Sales])>15,MAX(Facts[Sales]),0)),[v]))),KEEPFILTERS(Facts[Region]<>"West"))', 'True'),
    (3, 'CALCULATE(ISINT64(IFERROR(MINX(SUMMARIZECOLUMNS(Facts[Region],"v",COALESCE(MIN(Facts[Note]),"none")),[v]),MAX(Facts[Note]))),Facts[Note]="Paid")', 'False'),
    (3, 'CALCULATE(ISINTEGER(IFERROR(MAXX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MIN(Facts[Quantity])=0,0.5,MIN(Facts[Quantity]))),-[v]),1/3)),Facts[Note]="Paid")', 'False'),
    (3, 'ISINTEGER(COALESCE(5,SUMX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Quantity])>2,CURRENCY(3),7)),[v])))', 'False'),
    (4, 'CALCULATE(ISDECIMAL(IF(ISBLANK(MAX(Facts[Note])),0.5,MAXX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Sales])>15,MAX(Facts[Sales]),0)),-[v]))),KEEPFILTERS(Facts[Region]<>"West"))', 'False'),
    (4, 'CALCULATE(ISDOUBLE(SWITCH(TRUE(),TRUE(),SUMX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Sales])>15,MAX(Facts[Sales]),0)),[v]*2),COUNTROWS(Facts))),ALL(Facts))', 'True'),
    (4, 'CALCULATE(ISINTEGER(COALESCE(COUNTROWS(Facts),MAXX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Sales])>15,MAX(Facts[Sales]),0)),-[v]))),REMOVEFILTERS(Facts[Region]))', 'False'),
    (4, 'CALCULATE(ISINTEGER(IFERROR(SUM(Facts[Sales]),MINX(SUMMARIZECOLUMNS(Facts[Region],"v",IF(MAX(Facts[Quantity])>2,CURRENCY(3),7)),[v]))),KEEPFILTERS(Facts[Region]<>"West"))', 'False'),
]


@pytest.mark.parametrize("table, expression, powerbi", ERROR_ROWS)
def test_power_bi_error_is_not_answered(monkeypatch: pytest.MonkeyPatch, table: int, expression: str, powerbi: str) -> None:
    assert powerbi.startswith("ERR")
    _use_table(monkeypatch, table)
    assert local(expression).startswith("LOCAL-")


@pytest.mark.parametrize("table, expression, powerbi", REFUSED_OR_RIGHT_ROWS)
def test_measured_wrong_shape_is_refused_or_right(monkeypatch: pytest.MonkeyPatch, table: int, expression: str, powerbi: str) -> None:
    _use_table(monkeypatch, table)
    result = local(expression)
    assert result.startswith("LOCAL-") or same(powerbi, result)


@pytest.mark.parametrize("table, expression, powerbi", FIXED_TO_RIGHT_ROWS + ANSWERED_ROWS)
def test_answer_equals_power_bi(monkeypatch: pytest.MonkeyPatch, table: int, expression: str, powerbi: str) -> None:
    _use_table(monkeypatch, table)
    assert same(powerbi, local(expression))


def test_group_shape_rules_are_well_formed() -> None:
    rules = measures._MEASURED_WRONG_GROUP_SHAPES
    assert len(rules) == 80
    assert all(len(rule) == 4 and isinstance(rule[3], frozenset) for rule in rules)


def test_this_file_holds_enough_rows() -> None:
    assert len(ERROR_ROWS) == 30
    assert len(REFUSED_OR_RIGHT_ROWS) == 36
    assert len(FIXED_TO_RIGHT_ROWS) == 12
    assert len(ANSWERED_ROWS) == 36
    assert {table for table, *_ in ERROR_ROWS + REFUSED_OR_RIGHT_ROWS + ANSWERED_ROWS} == {1, 2, 3, 4}
