"""Task 245: table builders nested inside the columns added by SUMMARIZE / ADDCOLUMNS / SUMMARIZECOLUMNS.

Every expected answer is a live Power BI answer on the Facts table of tools.dax_oracle_diff (6 rows: Sales, Quantity, Region, Note), or on a second table (SECOND_ROWS),
a third (THIRD_ROWS) or a fourth (FOURTH_ROWS, with twin rows).

The measured rules, in plain words:
  * SUMMARIZE over a table value (SUMMARIZE(SUMMARIZE(Facts, Region, Quantity), Region, "s", ...)): the group is the set of rows of that table that hold the group key, so the columns
    the inner table holds that are not group-by columns (Quantity here) stay filtered to the values those rows hold, inside the added column (ISFILTERED(Quantity) is TRUE there).
    A CALCULATE filter on the group-by column (Region) therefore keeps the other column's values.  When an added column reads ALLSELECTED of a column (or table) of the inner table
    over a plain inner SUMMARIZE of a table, the groups and answers are those of SUMMARIZE(Facts, outer group columns, ...).
  * Stays refused (unsure => refused): ALLSELECTED read as a table of a column the table value does not hold (COUNTROWS(ALLSELECTED(Note))); ALLSELECTED of a column of a table value that is not a
    plain SUMMARIZE of a table; an iterator over VALUES(column) inside an added column whose two readings (the transition on a group-by column leaving that column unfiltered, or applying it)
    differ; SUMMARIZECOLUMNS with ALLSELECTED of a group-by column (or table) inside a CALCULATE nested under a CALCULATE filter, or a table read of ALLSELECTED(group column) beside a filter on
    another column; ADDCOLUMNS over SUMMARIZE with CALCULATETABLE over ALLSELECTED of a column of the summarized table or FILTER(Facts, ...); and ISBOOLEAN of a SWITCH whose branch is a SUMX
    over a table built with COALESCE(MIN or MAX(column), "text") (Power BI raises an error there).
"""
from __future__ import annotations

import pytest

from tools import dax_oracle_diff
from tools.dax_oracle_diff import HEADERS, local, same

SECOND_ROWS = [("0.5", "7", "East", "Paid"), ("0.25", "9", "West", "Late"), ("", "0", "East", ""), ("-2", "30", "North", "Paid")]
THIRD_ROWS = [("1", "2", "East", "Paid"), ("2", "3", "West", ""), ("30", "4", "North", ""), ("4", "5", "West", ""), ("", "6", "East", "Late")]
FOURTH_ROWS = [("5", "1", "East", "Paid"), ("5", "2", "East", "Paid"), ("5", "2", "East", "Paid"), ("7", "3", "West", "Paid"), ("7", "3", "West", "Paid"), ("8", "4", "North", ""), ("2", "5", "East", "Late"), ("2", "5", "West", "Late")]

ISBOOLEAN_TEXT_ROW = 'CALCULATE(ISBOOLEAN(SWITCH(TRUE(),HASONEVALUE(Facts[Region]),SUMX(SUMMARIZECOLUMNS(Facts[Region],"v",COALESCE(MIN(Facts[Note]),"none")),[v]),0.5)),Facts[Quantity]>1)'

ANSWERED = [
    ('AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(VALUES(Facts[Quantity])),REMOVEFILTERS(Facts[Sales],Facts[Region]))),[s])', '2'),
    ('CALCULATE(AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(AVERAGE(Facts[Sales]),ALLEXCEPT(Facts,Facts[Quantity],Facts[Region]))),[s]),Facts[Sales]>1,Facts[Quantity]<5)', '15.25'),
    ('CALCULATE(AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SELECTEDVALUE(Facts[Quantity],-1),Facts[Note]<>"Paid")),[s]),Facts[Note]="Paid")', '-1'),
    ('CALCULATE(AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SELECTEDVALUE(Facts[Quantity],-1),REMOVEFILTERS(Facts[Sales],Facts[Region]))),[s]),Facts[Sales]>1,Facts[Quantity]<5)', '2.5'),
    ('CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts[Quantity])))),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Region],ASC),Facts[Quantity]>1)', '1|1|1|1'),
    ('CALCULATE(COUNTROWS(FILTER(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"s",CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts[Sales]))),NOT(ISBLANK([s])))),Facts[Quantity]>1)', '4'),
    ('CALCULATE(COUNTROWS(FILTER(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],"t",SUM(Facts[Sales])),"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts)),Facts[Region]<>"North")),NOT(ISBLANK([s])))),KEEPFILTERS(Facts[Region]<>"North"))', '5'),
    ('CALCULATE(COUNTROWS(FILTER(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(MAX(Facts[Note]),ALLEXCEPT(Facts,Facts[Quantity],Facts[Region]))),NOT(ISBLANK([s])))),Facts[Sales]>1,Facts[Quantity]<5)', '1'),
    ('CALCULATE(COUNTROWS(FILTER(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SUMX(Facts,Facts[Sales]*Facts[Quantity]),ALL(Facts[Sales]),Facts[Region]="East")),NOT(ISBLANK([s])))),Facts[Note]="Paid")', '1'),
    ('CALCULATE(COUNTROWS(FILTER(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",SUMX(CALCULATETABLE(Facts,ALL(Facts[Sales]),Facts[Region]="East"),Facts[Sales])),NOT(ISBLANK([s])))),ALL(Facts[Quantity]))', '1'),
    ('CALCULATE(MAXX(ADDCOLUMNS(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),"s",CALCULATE(SELECTEDVALUE(Facts[Quantity],-1),ALLSELECTED(Facts[Quantity],Facts[Region]))),[s]),ALL(Facts[Quantity]))', '-1'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),REMOVEFILTERS(Facts[Note])),Facts[Region]<>"North")),[s]),Facts[Sales]>1,Facts[Quantity]<5)', '20'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(Facts),ALL(Facts[Region]))),[s]),Facts[Quantity]>1)', '2'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(VALUES(Facts[Quantity])),ALLSELECTED(Facts))),[s]),Facts[Sales]>1,Facts[Quantity]<5)', '2'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(DISTINCTCOUNT(Facts[Note]),Facts[Note]<>"Paid")),[s]),Facts[Note]="Paid")', 'BLANK'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(IF(HASONEVALUE(Facts[Region]),1,0),ALLSELECTED(Facts))),[s]),ALL(Facts[Quantity]))', '0'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(IF(HASONEVALUE(Facts[Region]),1,0),ALLSELECTED(Facts))),[s]),Facts[Note]="Paid")', '0'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",IF(ISFILTERED(Facts[Quantity]),1,0)),[s]),Facts[Region]="East")', '1'),
    ('CALCULATE(MAXX(SUMMARIZECOLUMNS(Facts[Note],"s",CALCULATE(AVERAGE(Facts[Sales]),ALLSELECTED(Facts[Note]),Facts[Quantity]>1)),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '11'),
    ('CALCULATE(SUMX(ADDCOLUMNS(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),"s",SUMX(VALUES(Facts[Note]),CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Note])))),[s]*2),ALL(Facts[Quantity]))', '189'),
    ('CALCULATE(SUMX(SUMMARIZE(CALCULATETABLE(Facts,Facts[Region]="East"),Facts[Region],Facts[Quantity],"s",SUMX(VALUES(Facts[Note]),CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Note]),Facts[Quantity]>1))),[s]),Facts[Quantity]>1)', '13'),
    ('CALCULATE(SUMX(SUMMARIZE(Facts,Facts[Sales],"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts[Note]),Facts[Quantity]>1))),[s]),Facts[Region]="East")', '2'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Quantity])),Facts[Region]<>"North")),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '31.5'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),Facts[Region]<>"North"),Facts[Sales]>1)),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '33'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),Facts[Region]<>"North"),TREATAS({"Paid"},Facts[Note]))),[s]),ALL(Facts[Quantity]))', '9'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(DISTINCTCOUNT(Facts[Note]),ALLSELECTED(Facts[Region]))),[s]),ALL(Facts[Quantity]))', '9'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(IF(ISFILTERED(Facts[Quantity]),1,0),ALL(Facts[Sales]))),[s]*2),Facts[Region]="East")', '2'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(MAX(Facts[Quantity]),ALL(Facts[Region]))),[s]),Facts[Quantity]>1)', '12'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(MAX(Facts[Quantity]),REMOVEFILTERS(Facts[Sales],Facts[Region]))),[s]*2),Facts[Quantity]>1)', '24'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SUM(Facts[Sales]),ALL(Facts[Region]))),[s]),ALL(Facts[Quantity]))', '31.5'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Region]))),[s]),ALL(Facts[Quantity]))', '94.5'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SUMX(Facts,Facts[Sales]*Facts[Quantity]),ALLSELECTED(Facts[Region]))),[s]*2),Facts[Sales]>1,Facts[Quantity]<5)', '324'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",COUNTROWS(CALCULATETABLE(Facts,ALL(Facts[Sales]),Facts[Region]="East"))),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '3'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",SUMX(VALUES(Facts[Note]),CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Sales])))),[s]),Facts[Sales]>1,Facts[Quantity]<5)', '30.5'),
    ('MAXX(ADDCOLUMNS(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),"s",COUNTROWS(ALLSELECTED(Facts[Note]))),[s])', '3'),
    ('MAXX(SUMMARIZECOLUMNS(Facts[Region],Facts[Quantity],"s",COUNTROWS(ALLSELECTED(Facts[Note]))),[s])', '3'),
    ('SUMX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"s",SUMX(Facts,CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts)))),[s]*2)', '2268'),
    ('SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",SUMX(CALCULATETABLE(Facts,REMOVEFILTERS(Facts[Sales],Facts[Region])),Facts[Sales])),[s]*2)', '63'),
]

STILL_REFUSED = [
    ('CALCULATE(AVERAGEX(ADDCOLUMNS(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),"s",COUNTROWS(CALCULATETABLE(Facts,ALLSELECTED(Facts)))),[s]),Facts[Sales]>1,Facts[Quantity]<5)', '2'),
    ('CALCULATE(AVERAGEX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],"t",SUM(Facts[Sales])),"s",COUNTROWS(CALCULATETABLE(Facts,ALLSELECTED(Facts[Quantity])))),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '2.6'),
    ('CALCULATE(AVERAGEX(SUMMARIZECOLUMNS(Facts[Note],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),ALL(Facts[Sales]),Facts[Region]="East")),[s]),Facts[Quantity]>1)', '3'),
    ('CALCULATE(CONCATENATEX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],"t",SUM(Facts[Sales])),"s",SUMX(CALCULATETABLE(Facts,FILTER(Facts,Facts[Quantity]>1)),Facts[Sales])),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Quantity],ASC),Facts[Region]="East")', '13|13|13'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),Facts[Quantity] IN {2,3})),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '3'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",COUNTROWS(ALLSELECTED(Facts[Note]))),[s]),Facts[Region]="East")', '3'),
    ('CALCULATE(MAXX(SUMMARIZECOLUMNS(Facts[Region],Facts[Quantity],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Quantity])),Facts[Region]<>"North")),[s]),Facts[Quantity]>1)', '33'),
    ('CALCULATE(SUMX(ADDCOLUMNS(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),"s",SUMX(CALCULATETABLE(Facts,ALLSELECTED(Facts)),Facts[Sales])),[s]*2),KEEPFILTERS(Facts[Region]<>"North"))', '315'),
    ('CALCULATE(SUMX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"s",SUMX(CALCULATETABLE(Facts,ALLSELECTED(Facts)),Facts[Sales])),[s]),Facts[Region]="East")', '34.5'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),FILTER(ALL(Facts[Quantity]),Facts[Quantity]>1))),[s]*2),Facts[Region]="East")', '6'),
    ('CALCULATE(SUMX(SUMMARIZECOLUMNS(Facts[Note],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Note])),Facts[Region]<>"North")),[s]*2),KEEPFILTERS(Facts[Region]<>"North"))', '126'),
    ('CALCULATE(SUMX(SUMMARIZECOLUMNS(Facts[Region],Facts[Quantity],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Quantity],Facts[Region])),Facts[Region]<>"North")),[s]*2),Facts[Note]="Paid")', '54'),
]

ANSWERED_SECOND = [
    ('AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(VALUES(Facts[Quantity])),REMOVEFILTERS(Facts[Sales],Facts[Region]))),[s])', '1.33333333333333'),
    ('CALCULATE(AVERAGEX(ADDCOLUMNS(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),Facts[Region]<>"North"),ALLSELECTED(Facts[Note]))),[s]),Facts[Quantity]>1)', '0.375'),
    ('CALCULATE(AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts[Quantity],Facts[Region]))),[s]),Facts[Quantity]>1)', '3'),
    ('CALCULATE(AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SELECTEDVALUE(Facts[Quantity],-1),ALL(Facts[Region]))),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '4'),
    ('CALCULATE(AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SELECTEDVALUE(Facts[Quantity],-1),Facts[Note]<>"Paid")),[s]),Facts[Note]="Paid")', '-1'),
    ('CALCULATE(AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",SUMX(Facts,CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Quantity],Facts[Region])))),[s]),Facts[Sales]>1,Facts[Quantity]<5)', 'BLANK'),
    ('CALCULATE(AVERAGEX(SUMMARIZECOLUMNS(Facts[Region],Facts[Quantity],"s",CALCULATE(COUNTROWS(VALUES(Facts[Quantity])),ALLSELECTED(Facts[Sales]))),[s]),Facts[Note]="Paid")', '1'),
    ('CALCULATE(CONCATENATEX(ADDCOLUMNS(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),"s",SUMX(Facts,CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Quantity],Facts[Region])))),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Quantity],ASC),Facts[Sales]>1,Facts[Quantity]<5)', 'BLANK'),
    ('CALCULATE(COUNTROWS(FILTER(SUMMARIZE(FILTER(Facts,Facts[Quantity]>1),Facts[Region],"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts)))),NOT(ISBLANK([s])))),ALL(Facts[Quantity]))', '3'),
    ('CALCULATE(COUNTROWS(FILTER(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SUM(Facts[Sales]),Facts[Region]="East")),NOT(ISBLANK([s])))),KEEPFILTERS(Facts[Region]<>"North"))', '1'),
    ('CALCULATE(COUNTROWS(FILTER(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",SUMX(CALCULATETABLE(Facts,ALL(Facts[Sales]),Facts[Region]="East"),Facts[Sales])),NOT(ISBLANK([s])))),ALL(Facts[Quantity]))', '1'),
    ('CALCULATE(MAXX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts[Quantity])))),[s]),Facts[Region]="East")', '1'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(AVERAGE(Facts[Sales]),REMOVEFILTERS(Facts[Sales],Facts[Region]))),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '0.5'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(VALUES(Facts[Quantity])),ALLSELECTED(Facts))),[s]),Facts[Sales]>1,Facts[Quantity]<5)', 'BLANK'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(IF(HASONEVALUE(Facts[Region]),1,0),ALLSELECTED(Facts))),[s]),ALL(Facts[Quantity]))', '0'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(IF(HASONEVALUE(Facts[Region]),1,0),ALLSELECTED(Facts))),[s]),Facts[Note]="Paid")', '0'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts)))),[s]),ALL(Facts[Quantity]))', '2'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(AVERAGE(Facts[Sales]),ALL(Facts[Sales]),Facts[Region]="East")),[s]*2),Facts[Note]="Paid")', '1'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(AVERAGE(Facts[Sales]),ALLSELECTED(Facts[Region]))),[s]),Facts[Note]="Paid")', '-1.5'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),ALL(Facts[Sales],Facts[Note])),Facts[Region]<>"North")),[s]*2),Facts[Note]="Paid")', '1'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),Facts[Note]="Paid"),Facts[Region]<>"North")),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '0.5'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),Facts[Region]<>"North"),ALLSELECTED(Facts[Quantity]))),[s]*2),ALL(Facts[Quantity]))', '1.5'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(VALUES(Facts[Quantity])),ALLSELECTED(Facts))),[s]*2),KEEPFILTERS(Facts[Region]<>"North"))', '12'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(DISTINCTCOUNT(Facts[Note]),ALLSELECTED(Facts[Quantity],Facts[Region]))),[s]*2),KEEPFILTERS(Facts[Region]<>"North"))', '12'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(DISTINCTCOUNT(Facts[Note]),ALLSELECTED(Facts[Region]))),[s]),ALL(Facts[Quantity]))', '9'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(IF(ISFILTERED(Facts[Quantity]),1,0),ALLEXCEPT(Facts,Facts[Quantity],Facts[Region]))),[s]),Facts[Note]="Paid")', '2'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(MAX(Facts[Quantity]),ALL(Facts[Sales]),Facts[Region]="East")),[s]),Facts[Quantity]>1)', '7'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(MAX(Facts[Quantity]),Facts[Note]<>"Paid")),[s]),Facts[Note]="Paid")', 'BLANK'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SUM(Facts[Sales]),REMOVEFILTERS(Facts[Sales],Facts[Region]))),[s]),ALL(Facts[Quantity]))', '-1.25'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SUMX(Facts,Facts[Sales]*Facts[Quantity]),REMOVEFILTERS(Facts[Sales],Facts[Region]))),[s]),ALL(Facts[Quantity]))', '-54.25'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",COUNTROWS(CALCULATETABLE(Facts,ALL(Facts[Sales]),Facts[Region]="East"))),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '2'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",IF(ISFILTERED(Facts[Quantity]),1,0)),[s]),Facts[Region]="East")', '1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(Facts[Note],"s",CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Quantity],Facts[Region]))),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Note],ASC)', '-1.5|0.25'),
    ('MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts)),Facts[Region]<>"North")),[s])', '0.75'),
    ('MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SUMX(Facts,Facts[Sales]*Facts[Quantity]),REMOVEFILTERS(Facts[Sales],Facts[Region]))),[s])', '3.5'),
    ('MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",IF(ISFILTERED(Facts[Quantity]),1,0)),[s])', '1'),
    ('SUMX(ADDCOLUMNS(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),"s",CALCULATE(DISTINCTCOUNT(Facts[Note]),ALLSELECTED(Facts[Note]))),[s])', '4'),
    ('SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",SUMX(CALCULATETABLE(Facts,REMOVEFILTERS(Facts[Sales],Facts[Region])),Facts[Sales])),[s]*2)', '-2.5'),
]

STILL_REFUSED_SECOND = [
    ('CALCULATE(AVERAGEX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],"t",SUM(Facts[Sales])),"s",COUNTROWS(CALCULATETABLE(Facts,ALLSELECTED(Facts[Quantity])))),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '1.66666666666667'),
    ('CALCULATE(CONCATENATEX(ADDCOLUMNS(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),"s",COUNTROWS(CALCULATETABLE(Facts,ALLSELECTED(Facts[Quantity])))),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Quantity],ASC),Facts[Region]="East")', '2|2'),
    ('CALCULATE(CONCATENATEX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],"t",SUM(Facts[Sales])),"s",SUMX(CALCULATETABLE(Facts,FILTER(Facts,Facts[Quantity]>1)),Facts[Sales])),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Quantity],ASC),Facts[Region]="East")', '0.5|0.5'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),Facts[Quantity] IN {2,3})),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '3'),
    ('CALCULATE(MAXX(SUMMARIZECOLUMNS(Facts[Note],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Note])),Facts[Region]<>"North")),[s]),Facts[Quantity]>1)', '0.75'),
    ('CALCULATE(MAXX(SUMMARIZECOLUMNS(Facts[Region],Facts[Quantity],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Quantity])),Facts[Region]<>"North")),[s]),Facts[Quantity]>1)', '0.75'),
    ('CALCULATE(SUMX(ADDCOLUMNS(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),"s",SUMX(CALCULATETABLE(Facts,ALLSELECTED(Facts)),Facts[Sales])),[s]*2),KEEPFILTERS(Facts[Region]<>"North"))', '4.5'),
    ('CALCULATE(SUMX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"s",SUMX(CALCULATETABLE(Facts,ALLSELECTED(Facts)),Facts[Sales])),[s]),Facts[Region]="East")', '1'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),FILTER(ALL(Facts[Quantity]),Facts[Quantity]>1))),[s]*2),Facts[Region]="East")', '6'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",COUNTROWS(ALLSELECTED(Facts[Note]))),[s]),Facts[Quantity]>1)', '9'),
    ('CALCULATE(SUMX(SUMMARIZECOLUMNS(Facts[Note],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),Facts[Sales]>0,Facts[Quantity]<4)),[s]),Facts[Quantity]>1)', '6'),
    ('MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",COUNTROWS(ALLSELECTED(Facts[Note]))),[s])', '3'),
]

ANSWERED_THIRD = [
    ('AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SUM(Facts[Sales]),REMOVEFILTERS(Facts[Sales],Facts[Region]))),[s])', '12.3333333333333'),
    ('CALCULATE(AVERAGEX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],"t",SUM(Facts[Sales])),"s",CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Quantity]))),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '3.5'),
    ('CALCULATE(AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(AVERAGE(Facts[Sales]),ALLSELECTED(Facts))),[s]),ALL(Facts[Quantity]))', '9.25'),
    ('CALCULATE(AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(AVERAGE(Facts[Sales]),ALLSELECTED(Facts[Quantity]))),[s]),Facts[Quantity]>1)', '11.3333333333333'),
    ('CALCULATE(AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(AVERAGE(Facts[Sales]),REMOVEFILTERS(Facts[Sales],Facts[Region]))),[s]),ALL(Facts[Quantity]))', '11.3333333333333'),
    ('CALCULATE(AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),Facts[Region]<>"North"),KEEPFILTERS(Facts[Quantity]>1))),[s]),Facts[Quantity]>1)', '3.5'),
    ('CALCULATE(AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SELECTEDVALUE(Facts[Quantity],-1),Facts[Note]<>"Paid")),[s]),Facts[Note]="Paid")', '-1'),
    ('CALCULATE(AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SELECTEDVALUE(Facts[Quantity],-1),REMOVEFILTERS(Facts[Sales],Facts[Region]))),[s]),Facts[Sales]>1,Facts[Quantity]<5)', '3.5'),
    ('CALCULATE(AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SUMX(Facts,Facts[Sales]*Facts[Quantity]),ALLSELECTED(Facts[Quantity]))),[s]),ALL(Facts[Quantity]))', '49.3333333333333'),
    ('CALCULATE(CONCATENATEX(ADDCOLUMNS(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),"s",CALCULATE(IF(HASONEVALUE(Facts[Region]),1,0),ALLSELECTED(Facts[Quantity],Facts[Region]))),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Quantity],ASC),Facts[Note]="Paid")', '1'),
    ('CALCULATE(COUNTROWS(FILTER(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),ALL(Facts[Sales]),Facts[Region]="East"),Facts[Region]<>"North")),NOT(ISBLANK([s])))),KEEPFILTERS(Facts[Region]<>"North"))', '1'),
    ('CALCULATE(COUNTROWS(FILTER(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),Facts[Region]<>"North"),ALL(Facts[Note]))),NOT(ISBLANK([s])))),ALL(Facts[Quantity]))', '2'),
    ('CALCULATE(COUNTROWS(FILTER(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts))),NOT(ISBLANK([s])))),Facts[Quantity]>1)', '3'),
    ('CALCULATE(COUNTROWS(FILTER(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(Facts),Facts[Region]="East")),NOT(ISBLANK([s])))),ALL(Facts[Quantity]))', '1'),
    ('CALCULATE(COUNTROWS(FILTER(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",SUMX(CALCULATETABLE(Facts,ALL(Facts[Sales]),Facts[Region]="East"),Facts[Sales])),NOT(ISBLANK([s])))),ALL(Facts[Quantity]))', '1'),
    ('CALCULATE(MAXX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],"t",SUM(Facts[Sales])),"s",CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts))),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '4'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(Facts),ALL(Facts[Region]))),[s]),Facts[Quantity]>1)', '2'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(VALUES(Facts[Quantity])),ALLSELECTED(Facts))),[s]),Facts[Sales]>1,Facts[Quantity]<5)', '2'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(IF(HASONEVALUE(Facts[Region]),1,0),ALLSELECTED(Facts))),[s]),ALL(Facts[Quantity]))', '0'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SELECTEDVALUE(Facts[Quantity],-1),ALLSELECTED(Facts[Note]))),[s]),ALL(Facts[Quantity]))', '4'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",IF(ISFILTERED(Facts[Quantity]),1,0)),[s]),Facts[Region]="East")', '1'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts[Quantity])))),[s]),Facts[Region]="East")', '2'),
    ('CALCULATE(MAXX(SUMMARIZECOLUMNS(Facts[Note],"s",CALCULATE(COUNTROWS(VALUES(Facts[Quantity])),ALLSELECTED(Facts[Region]))),[s]),Facts[Quantity]>1)', '3'),
    ('CALCULATE(SUMX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],"t",SUM(Facts[Sales])),"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Note])),Facts[Region]<>"North")),[s]*2),KEEPFILTERS(Facts[Region]<>"North"))', '14'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(VALUES(Facts[Quantity])),ALLSELECTED(Facts))),[s]*2),KEEPFILTERS(Facts[Region]<>"North"))', '16'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(DISTINCTCOUNT(Facts[Note]),ALLSELECTED(Facts[Quantity],Facts[Region]))),[s]*2),KEEPFILTERS(Facts[Region]<>"North"))', '12'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(IF(ISFILTERED(Facts[Quantity]),1,0),ALL(Facts[Sales]))),[s]*2),Facts[Region]="East")', '2'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(IF(ISFILTERED(Facts[Quantity]),1,0),ALLEXCEPT(Facts,Facts[Quantity],Facts[Region]))),[s]),Facts[Note]="Paid")', '1'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(MAX(Facts[Quantity]),Facts[Region]="East")),[s]*2),KEEPFILTERS(Facts[Region]<>"North"))', '12'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(MAX(Facts[Quantity]),REMOVEFILTERS(Facts[Sales],Facts[Region]))),[s]*2),KEEPFILTERS(Facts[Region]<>"North"))', '22'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SUM(Facts[Sales]),ALL(Facts[Region]))),[s]),ALL(Facts[Quantity]))', '37'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SUMX(Facts,Facts[Sales]*Facts[Quantity]),Facts[Region]="East")),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '2'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",COUNTROWS(CALCULATETABLE(Facts,ALL(Facts[Sales]),Facts[Region]="East"))),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '2'),
    ('CONCATENATEX(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],"s",SUMX(VALUES(Facts[Note]),CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Region]))),"t",COUNTROWS(Facts)),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Quantity],ASC)', 'b|1|2|4|30'),
    ('MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),ALL(Facts[Sales])),Facts[Region]<>"North")),[s])', '6'),
    ('MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SUMX(Facts,Facts[Sales]*Facts[Quantity]),REMOVEFILTERS(Facts[Sales],Facts[Region]))),[s])', '120'),
    ('SUMX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],"t",SUM(Facts[Sales])),"s",CALCULATE(IF(ISFILTERED(Facts[Quantity]),1,0),ALLSELECTED(Facts[Note]))),[s]*2)', '10'),
    ('SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",SUMX(CALCULATETABLE(Facts,REMOVEFILTERS(Facts[Sales],Facts[Region])),Facts[Sales])),[s]*2)', '74'),
]

STILL_REFUSED_THIRD = [
    ('CALCULATE(AVERAGEX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],"t",SUM(Facts[Sales])),"s",COUNTROWS(CALCULATETABLE(Facts,ALLSELECTED(Facts[Quantity])))),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '2'),
    ('CALCULATE(AVERAGEX(SUMMARIZECOLUMNS(Facts[Note],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts)),Facts[Region]<>"North")),[s]),Facts[Region]="East")', '7'),
    ('CALCULATE(CONCATENATEX(ADDCOLUMNS(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),"s",SUMX(CALCULATETABLE(Facts,ALLSELECTED(Facts)),Facts[Sales])),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Quantity],ASC),ALL(Facts[Quantity]))', '37|37|37|37|37'),
    ('CALCULATE(CONCATENATEX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],"t",SUM(Facts[Sales])),"s",SUMX(CALCULATETABLE(Facts,FILTER(Facts,Facts[Quantity]>1)),Facts[Sales])),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Quantity],ASC),Facts[Region]="East")', '1|1'),
    ('CALCULATE(MAXX(ADDCOLUMNS(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),"s",COUNTROWS(CALCULATETABLE(Facts,FILTER(Facts,Facts[Quantity]>1)))),[s]),ALL(Facts[Quantity]))', '5'),
    ('CALCULATE(MAXX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],"t",SUM(Facts[Sales])),"s",SUMX(CALCULATETABLE(Facts,FILTER(Facts,Facts[Quantity]>1)),Facts[Sales])),[s]),ALL(Facts[Quantity]))', '37'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),Facts[Quantity] IN {2,3})),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '3'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",COUNTROWS(ALLSELECTED(Facts[Note]))),[s]),Facts[Quantity]>1)', '3'),
    ('CALCULATE(MAXX(SUMMARIZECOLUMNS(Facts[Region],Facts[Quantity],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Quantity])),Facts[Region]<>"North")),[s]),Facts[Quantity]>1)', '7'),
    ('CALCULATE(SUMX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"s",SUMX(CALCULATETABLE(Facts,ALLSELECTED(Facts)),Facts[Sales])),[s]),Facts[Region]="East")', '2'),
    ('CALCULATE(SUMX(SUMMARIZECOLUMNS(Facts[Note],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),Facts[Quantity]>1)),[s]),Facts[Sales]>1,Facts[Quantity]<5)', '3'),
    ('CALCULATE(SUMX(SUMMARIZECOLUMNS(Facts[Region],Facts[Quantity],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts)),Facts[Region]<>"North")),[s]),Facts[Region]="East")', '14'),
]

ANSWERED_FOURTH = [
    ('CALCULATE(AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts))),[s]),Facts[Sales]>1,Facts[Quantity]<5)', '6'),
    ('CALCULATE(AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts[Region]))),[s]),Facts[Sales]>1,Facts[Quantity]<5)', '6'),
    ('CALCULATE(AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(DISTINCTCOUNT(Facts[Note]),REMOVEFILTERS(Facts[Sales],Facts[Region]))),[s]),Facts[Sales]>1,Facts[Quantity]<5)', '1'),
    ('CALCULATE(AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SELECTEDVALUE(Facts[Quantity],-1),Facts[Note]<>"Paid")),[s]),Facts[Note]="Paid")', '-1'),
    ('CALCULATE(AVERAGEX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SELECTEDVALUE(Facts[Quantity],-1),REMOVEFILTERS(Facts[Sales],Facts[Region]))),[s]),Facts[Sales]>1,Facts[Quantity]<5)', '2'),
    ('CALCULATE(AVERAGEX(SUMMARIZECOLUMNS(Facts[Region],Facts[Quantity],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),Facts[Region]<>"North"),ALLSELECTED(Facts[Quantity],Facts[Region]))),[s]),ALL(Facts[Quantity]))', '33'),
    ('CALCULATE(CONCATENATEX(SUMMARIZE(ALL(Facts),Facts[Region],Facts[Quantity],"s",SUMX(VALUES(Facts[Note]),CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Sales])))),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Quantity],ASC),Facts[Region]="East")', '2|2|5|8|10|14'),
    ('CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Note],"s",SUMX(VALUES(Facts[Note]),CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Quantity],Facts[Region])))),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Note],ASC),ALL(Facts[Quantity]))', '4|8|29'),
    ('CALCULATE(CONCATENATEX(SUMMARIZECOLUMNS(Facts[Note],"s",COUNTROWS(CALCULATETABLE(Facts,ALLSELECTED(Facts[Quantity])))),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Note],ASC),ALL(Facts[Quantity]))', '1|2|5'),
    ('CALCULATE(COUNTROWS(FILTER(ADDCOLUMNS(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Region])),Facts[Region]<>"North")),NOT(ISBLANK([s])))),Facts[Sales]>1,Facts[Quantity]<5)', '3'),
    ('CALCULATE(COUNTROWS(FILTER(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",SUMX(CALCULATETABLE(Facts,ALL(Facts[Sales]),Facts[Region]="East"),Facts[Sales])),NOT(ISBLANK([s])))),ALL(Facts[Quantity]))', '2'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(AVERAGE(Facts[Sales]),ALLSELECTED(Facts[Quantity],Facts[Region]))),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '4.71428571428571'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(VALUES(Facts[Quantity])),ALLSELECTED(Facts))),[s]),Facts[Sales]>1,Facts[Quantity]<5)', '4'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(IF(HASONEVALUE(Facts[Region]),1,0),ALLSELECTED(Facts))),[s]),ALL(Facts[Quantity]))', '0'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(IF(HASONEVALUE(Facts[Region]),1,0),ALLSELECTED(Facts))),[s]),Facts[Note]="Paid")', '0'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SUMX(Facts,Facts[Sales]*Facts[Quantity]),ALLSELECTED(Facts[Quantity],Facts[Region]))),[s]),Facts[Note]="Paid")', '67'),
    ('CALCULATE(MAXX(SUMMARIZECOLUMNS(Facts[Region],Facts[Quantity],"s",CALCULATE(IF(ISFILTERED(Facts[Quantity]),1,0),ALLSELECTED(Facts[Quantity]))),[s]),Facts[Quantity]>1)', '1'),
    ('CALCULATE(SUMX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts[Note])))),[s]),ALL(Facts[Quantity]))', '10'),
    ('CALCULATE(SUMX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],"t",SUM(Facts[Sales])),"s",CALCULATE(SELECTEDVALUE(Facts[Quantity],-1),ALLSELECTED(Facts))),[s]),Facts[Note]="Paid")', '-3'),
    ('CALCULATE(SUMX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],"t",SUM(Facts[Sales])),"s",CALCULATE(SUMX(Facts,Facts[Sales]*Facts[Quantity]),ALLSELECTED(Facts[Quantity]))),[s]),Facts[Note]="Paid")', '92'),
    ('CALCULATE(SUMX(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],Facts[Note],"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts[Quantity],Facts[Region])))),[s]),Facts[Quantity]>1)', '7'),
    ('CALCULATE(SUMX(SUMMARIZE(Facts,Facts[Sales],"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts[Note]),Facts[Quantity]>1))),[s]),Facts[Region]="East")', '3'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(AVERAGE(Facts[Sales]),ALLEXCEPT(Facts,Facts[Quantity],Facts[Region]))),[s]*2),Facts[Note]="Paid")', '24'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),Facts[Region]<>"North"),FILTER(VALUES(Facts[Region]),Facts[Region]<>"West"))),[s]*2),Facts[Note]="Paid")', '58'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),Facts[Region]<>"North"),TREATAS({"Paid"},Facts[Note]))),[s]),ALL(Facts[Quantity]))', '29'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),VALUES(Facts[Note])),Facts[Region]<>"North")),[s]),Facts[Note]="Paid")', '29'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(VALUES(Facts[Quantity])),ALLSELECTED(Facts))),[s]*2),KEEPFILTERS(Facts[Region]<>"North"))', '16'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(DISTINCTCOUNT(Facts[Note]),Facts[Region]="East")),[s]*2),Facts[Sales]>1,Facts[Quantity]<5)', '2'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(IF(ISFILTERED(Facts[Quantity]),1,0),ALLEXCEPT(Facts,Facts[Quantity],Facts[Region]))),[s]),Facts[Note]="Paid")', '2'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(MAX(Facts[Quantity]),ALL(Facts[Sales]),Facts[Region]="East")),[s]),ALL(Facts[Quantity]))', '10'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Region]))),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '66'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",COUNTROWS(CALCULATETABLE(Facts,ALL(Facts[Sales]),Facts[Region]="East"))),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '5'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",IF(ISFILTERED(Facts[Quantity]),1,0)),[s]),Facts[Region]="East")', '1'),
    ('CALCULATE(SUMX(SUMMARIZECOLUMNS(Facts[Region],Facts[Quantity],"s",SUMX(CALCULATETABLE(Facts,ALLSELECTED(Facts[Quantity])),Facts[Sales])),[s]),Facts[Quantity]>1)', '64'),
    ('COUNTROWS(FILTER(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),Facts[Region]="East"),Facts[Region]<>"North")),NOT(ISBLANK([s]))))', '2'),
    ('SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(MAX(Facts[Quantity]),ALL(Facts[Region]))),[s]*2)', '28'),
    ('SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",IF(ISFILTERED(Facts[Quantity]),1,0)),[s])', '3'),
    ('SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",SUMX(CALCULATETABLE(Facts,REMOVEFILTERS(Facts[Sales],Facts[Region])),Facts[Sales])),[s]*2)', '90'),
]

STILL_REFUSED_FOURTH = [
    ('CALCULATE(CONCATENATEX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],"t",SUM(Facts[Sales])),"s",COUNTROWS(CALCULATETABLE(Facts,ALLSELECTED(Facts)))),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Quantity],ASC),Facts[Region]="East")', '4|4|4'),
    ('CALCULATE(MAXX(ADDCOLUMNS(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),"s",COUNTROWS(CALCULATETABLE(Facts,FILTER(Facts,Facts[Quantity]>1)))),[s]),ALL(Facts[Quantity]))', '7'),
    ('CALCULATE(MAXX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),Facts[Note]<>"Paid"))),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '2'),
    ('CALCULATE(MAXX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(COUNTROWS(ALLSELECTED(Facts[Note])),Facts[Quantity] IN {2,3})),[s]),KEEPFILTERS(Facts[Region]<>"North"))', '3'),
    ('CALCULATE(SUMX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"s",SUMX(CALCULATETABLE(Facts,ALLSELECTED(Facts)),Facts[Sales])),[s]),Facts[Region]="East")', '51'),
    ('CALCULATE(SUMX(SUMMARIZE(ALL(Facts),Facts[Region],Facts[Quantity],"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),VALUES(Facts[Quantity])))),[s]),Facts[Note]="Paid")', '10'),
    ('CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",COUNTROWS(ALLSELECTED(Facts[Note]))),[s]),Facts[Quantity]>1)', '9'),
    ('CALCULATE(SUMX(SUMMARIZECOLUMNS(Facts[Note],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Note]),Facts[Quantity]>1),Facts[Region]<>"North")),[s]*2),Facts[Region]="East")', '112'),
    ('CALCULATE(SUMX(SUMMARIZECOLUMNS(Facts[Region],Facts[Quantity],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Quantity],Facts[Region])),Facts[Region]<>"North")),[s]*2),Facts[Note]="Paid")', '174'),
    ('SUMX(SUMMARIZE(FILTER(Facts,Facts[Quantity]>1),Facts[Region],"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),KEEPFILTERS(Facts[Quantity]>1)))),[s])', '9'),
    ('SUMX(SUMMARIZE(Facts,Facts[Region],"t",SUM(Facts[Quantity]),"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),ALL(Facts[Note])))),[s]*2)', '20'),
    ('SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts[Quantity])))),[s]*2)', '20'),
]


def _table(monkeypatch: pytest.MonkeyPatch, table_rows: list[tuple[str, ...]]) -> None:
    rows = [{header: (value if value != "" else None) for header, value in zip(HEADERS, row)} for row in table_rows]
    monkeypatch.setattr(dax_oracle_diff, "LOCAL_ROWS", rows)


@pytest.fixture
def second_table(monkeypatch: pytest.MonkeyPatch) -> None:
    _table(monkeypatch, SECOND_ROWS)


@pytest.fixture
def third_table(monkeypatch: pytest.MonkeyPatch) -> None:
    _table(monkeypatch, THIRD_ROWS)


@pytest.fixture
def fourth_table(monkeypatch: pytest.MonkeyPatch) -> None:
    _table(monkeypatch, FOURTH_ROWS)


def _right_or_refused(expression: str, powerbi: str) -> None:
    result = local(expression)
    assert result.startswith("LOCAL-") or same(powerbi, result)


@pytest.mark.parametrize("expression, powerbi", ANSWERED)
def test_answer_equals_power_bi(expression: str, powerbi: str) -> None:
    assert same(powerbi, local(expression))


@pytest.mark.parametrize("expression, powerbi", ANSWERED_SECOND)
def test_answer_on_second_table_equals_power_bi(second_table: None, expression: str, powerbi: str) -> None:
    assert same(powerbi, local(expression))


@pytest.mark.parametrize("expression, powerbi", ANSWERED_THIRD)
def test_answer_on_third_table_equals_power_bi(third_table: None, expression: str, powerbi: str) -> None:
    assert same(powerbi, local(expression))


@pytest.mark.parametrize("expression, powerbi", ANSWERED_FOURTH)
def test_answer_on_fourth_table_equals_power_bi(fourth_table: None, expression: str, powerbi: str) -> None:
    assert same(powerbi, local(expression))


@pytest.mark.parametrize("expression, powerbi", STILL_REFUSED)
def test_shape_not_modelled_is_refused_or_right(expression: str, powerbi: str) -> None:
    _right_or_refused(expression, powerbi)


@pytest.mark.parametrize("expression, powerbi", STILL_REFUSED_SECOND)
def test_second_table_shape_not_modelled_is_refused_or_right(second_table: None, expression: str, powerbi: str) -> None:
    _right_or_refused(expression, powerbi)


@pytest.mark.parametrize("expression, powerbi", STILL_REFUSED_THIRD)
def test_third_table_shape_not_modelled_is_refused_or_right(third_table: None, expression: str, powerbi: str) -> None:
    _right_or_refused(expression, powerbi)


@pytest.mark.parametrize("expression, powerbi", STILL_REFUSED_FOURTH)
def test_fourth_table_shape_not_modelled_is_refused_or_right(fourth_table: None, expression: str, powerbi: str) -> None:
    _right_or_refused(expression, powerbi)


# one measured row per group (Power BI answers): refused (the engine said something else) or answered
GROUP_ROWS = [
    # 1. an iterator over VALUES(group-by column) inside a SUMMARIZE added column (fourth table: Power BI 10, the engine said 8)
    ("fourth", 'SUMX(SUMMARIZE(Facts,Facts[Region],"s",SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts)))),[s])', "10", "refused"),
    # 2. SUMMARIZE of SUMMARIZE: ISFILTERED(Quantity) is TRUE in every group (Power BI 3, the engine said 0); the CALCULATE(Region filter) keeps the Quantity values
    ("first", 'SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",IF(ISFILTERED(Facts[Quantity]),1,0)),[s])', "3", "answered"),
    ("first", 'CALCULATE(SUMX(SUMMARIZE(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),Facts[Region],"s",CALCULATE(SUM(Facts[Sales]),ALL(Facts[Region]))),[s]),ALL(Facts[Quantity]))', "31.5", "answered"),
    # 3. SUMMARIZECOLUMNS with ALLSELECTED nested under a CALCULATE filter (Power BI 33, the engine said 20)
    ("first", 'CALCULATE(MAXX(SUMMARIZECOLUMNS(Facts[Region],Facts[Quantity],"s",CALCULATE(CALCULATE(SUM(Facts[Sales]),ALLSELECTED(Facts[Quantity])),Facts[Region]<>"North")),[s]),Facts[Quantity]>1)', "33", "refused"),
    # 4. ADDCOLUMNS over SUMMARIZE with CALCULATETABLE over ALLSELECTED(Facts) (Power BI 34.5)
    ("first", 'CALCULATE(SUMX(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"s",SUMX(CALCULATETABLE(Facts,ALLSELECTED(Facts)),Facts[Sales])),[s]),Facts[Region]="East")', "34.5", "refused"),
    ("fourth", 'CALCULATE(CONCATENATEX(ADDCOLUMNS(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),"u",1),"s",COUNTROWS(CALCULATETABLE(Facts,ALLSELECTED(Facts[Quantity])))),IF(ISBLANK([s]),"b",[s]),"|",[s],ASC,Facts[Quantity],ASC),Facts[Region]="East")', "4|4|4", "refused"),
]


@pytest.mark.parametrize("table, expression, powerbi, mode", GROUP_ROWS)
def test_group_row(monkeypatch: pytest.MonkeyPatch, table: str, expression: str, powerbi: str, mode: str) -> None:
    if table == "fourth":
        _table(monkeypatch, FOURTH_ROWS)
    result = local(expression)
    if mode == "answered":
        assert same(powerbi, result)
    else:
        assert result.startswith("LOCAL-") or same(powerbi, result)


def test_isboolean_of_switch_over_a_text_column_is_not_answered() -> None:
    # Power BI raises an error (the SUMX over a text column); the engine said False
    assert local(ISBOOLEAN_TEXT_ROW).startswith("LOCAL-")


def test_this_file_holds_enough_shapes() -> None:
    assert len(ANSWERED) == 38
    assert len(ANSWERED_SECOND) == 38
    assert len(ANSWERED_THIRD) == 38
    assert len(ANSWERED_FOURTH) == 38
    assert len(STILL_REFUSED) == 12
    assert len(STILL_REFUSED_SECOND) == 12
    assert len(STILL_REFUSED_THIRD) == 12
    assert len(STILL_REFUSED_FOURTH) == 12
