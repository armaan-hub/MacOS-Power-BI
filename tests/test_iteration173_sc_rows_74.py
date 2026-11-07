"""Task 84 (sc-rows-74): SUMMARIZECOLUMNS group rows over filters on other tables, ADDCOLUMNS and SUMMARIZE ISINSCOPE,
FILTERS counting the blank member, and the unknown member last in ALL(table), on model ZV.

The cases are literal (expression, Power BI answer) pairs: every ZV case fixed by the task, the ZS and ZM cases fixed by the task,
and 30 ZV cases that already matched. The model data is written out here as literals (the plans file is not imported).
Answers are compared through tests.critic3_models.ours_for; numbers compare by float value. The two ZM RANKX cases on the
orphan row (still wrong, see the work log) are not listed."""
import math

import pytest

from tests import critic3_models as m

DIM_COLS = [('Item', 'string'), ('Fam', 'string'), ('Tier', 'int64')]

DIM_ROWS = [('I1', 'G1', 1), ('I2', 'G1', 2), ('I3', 'G2', 2), ('I4', 'G2', 2), ('I5', 'G1', 3), ('I6', 'G1', 2)]

FACT_COLS = [('Id', 'int64'), ('Item', 'string'), ('Dt', 'dateTime'), ('Val', 'double'), ('Units', 'int64')]

FACT_ROWS = [(1, 'I4', (2024, 12, 8), None, 0), (2, 'I1', (2023, 1, 8), 2.0, 7), (3, 'I8', (2023, 3, 22), 64.0, 0), (4, None, (2024, 7, 7), 88.0, 1), (5, 'I5', (2024, 1, 26), 64.0, 5), (6, 'I7', (2024, 10, 14), 25.0, 8), (7, 'I2', (2023, 1, 8), 15.0, 5), (8, 'I7', (2024, 2, 6), -9.0, 8), (9, 'I3', (2024, 5, 4), 22.0, 4), (10, 'I5', (2023, 6, 2), 33.0, 0), (11, 'I1', (2024, 1, 14), 1.0, 3), (12, 'I6', (2024, 5, 28), 83.0, 1), (13, 'I7', (2024, 5, 11), None, 5), (14, 'I2', (2024, 4, 12), 69.0, 6), (15, 'I4', (2024, 7, 16), 38.0, 8), (16, 'I3', (2023, 12, 28), -3.0, 2), (17, 'I2', (2023, 8, 6), 30.0, 3), (18, 'I2', (2024, 10, 28), 83.0, 0), (19, 'I3', (2023, 7, 12), 0.0, 8), (20, 'I4', (2024, 7, 8), None, 8), (21, 'I8', (2024, 8, 13), 82.0, 7), (22, None, (2023, 2, 16), 27.0, 0), (23, 'I4', (2024, 6, 23), 58.0, 8), (24, 'I1', (2024, 2, 3), None, 2), (25, 'I7', (2023, 1, 14), None, 4), (26, 'I7', (2023, 3, 20), 45.0, 4)]

RELS = [('ZV_r1', 'ZV_Fact', 'Item', 'ZV_Dim', 'Item', True, False, 'many', 'one'), ('ZV_r2', 'ZV_Fact', 'Dt', 'ZV_Cal', 'Date', True, False, 'many', 'one')]

m.SPEC['ZV'] = {'tables': {'ZV_Dim': (DIM_COLS, DIM_ROWS), 'ZV_Fact': (FACT_COLS, FACT_ROWS), 'ZV_Cal': (m.CAL_COLS, None)}, 'rels': RELS}


CASES_ZV = [
    ('CONCATENATEX(ADDCOLUMNS(VALUES(ZV_Dim[Item]),"v",CALCULATE(ISINSCOPE(ZV_Dim[Item]))+0),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=1;I1=1;I2=1;I3=1;I4=1;I5=1;I6=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZV_Dim[Item],"v",COUNTROWS(FILTERS(ZV_Dim[Item])),"s",COUNTROWS(ZV_Fact)),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=1;I1=1;I2=1;I3=1;I4=1;I5=1;I6=1'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZV_Fact,ZV_Dim[Item]),"v",COUNTROWS(FILTERS(ZV_Dim[Item]))),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=7;I1=7;I2=7;I3=7;I4=7;I5=7;I6=7'),
    ('CONCATENATEX(ADDCOLUMNS(VALUES(ZV_Dim[Item]),"v",COUNTROWS(FILTERS(ZV_Dim[Item]))),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=7;I1=7;I2=7;I3=7;I4=7;I5=7;I6=7'),
    ('CONCATENATEX(ADDCOLUMNS(VALUES(ZV_Dim[Fam]),"v",CALCULATE(ISINSCOPE(ZV_Dim[Fam]))+0),ZV_Dim[Fam]&"="&[v],";",ZV_Dim[Fam])', '=1;G1=1;G2=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZV_Dim[Fam],"v",COUNTROWS(FILTERS(ZV_Dim[Item])),"s",COUNTROWS(ZV_Fact)),ZV_Dim[Fam]&"="&[v],";",ZV_Dim[Fam])', '=7;G1=7;G2=7'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZV_Fact,ZV_Dim[Fam]),"v",COUNTROWS(FILTERS(ZV_Dim[Item]))),ZV_Dim[Fam]&"="&[v],";",ZV_Dim[Fam])', '=7;G1=7;G2=7'),
    ('CONCATENATEX(ADDCOLUMNS(VALUES(ZV_Dim[Fam]),"v",COUNTROWS(FILTERS(ZV_Dim[Item]))),ZV_Dim[Fam]&"="&[v],";",ZV_Dim[Fam])', '=7;G1=7;G2=7'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZV_Dim[Fam],ZV_Dim[Item],"v",COUNTROWS(FILTERS(ZV_Dim[Item])),"s",COUNTROWS(ZV_Fact)),ZV_Dim[Fam]&"|"&ZV_Dim[Item]&"="&[v],";",ZV_Dim[Fam]&"|"&ZV_Dim[Item])', '|=1;G1|I1=1;G1|I2=1;G1|I5=1;G1|I6=1;G2|I3=1;G2|I4=1'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZV_Fact,ZV_Dim[Fam],ZV_Dim[Item]),"v",COUNTROWS(FILTERS(ZV_Dim[Item]))),ZV_Dim[Fam]&"|"&ZV_Dim[Item]&"="&[v],";",ZV_Dim[Fam]&"|"&ZV_Dim[Item])', '|=7;G1|I1=7;G1|I2=7;G1|I5=7;G1|I6=7;G2|I3=7;G2|I4=7'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZV_Dim[Item],ZV_Cal[Year],"v",COUNTROWS(FILTERS(ZV_Dim[Item])),"s",COUNTROWS(ZV_Fact)),ZV_Dim[Item]&"|"&ZV_Cal[Year]&"="&[v],";",ZV_Dim[Item]&"|"&ZV_Cal[Year])', '|2023=1;|2024=1;I1|2023=1;I1|2024=1;I2|2023=1;I2|2024=1;I3|2023=1;I3|2024=1;I4|2023=1;I4|2024=1;I5|2023=1;I5|2024=1;I6|2023=1;I6|2024=1'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZV_Fact,ZV_Dim[Item],ZV_Cal[Year]),"v",COUNTROWS(FILTERS(ZV_Dim[Item]))),ZV_Dim[Item]&"|"&ZV_Cal[Year]&"="&[v],";",ZV_Dim[Item]&"|"&ZV_Cal[Year])', '|2023=7;|2024=7;I1|2023=7;I1|2024=7;I2|2023=7;I2|2024=7;I3|2023=7;I3|2024=7;I4|2024=7;I5|2023=7;I5|2024=7;I6|2024=7'),
    ('CONCATENATEX(ALL(ZV_Dim),ZV_Dim[Item]&"",",")', 'I1,I2,I3,I4,I5,I6,'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZV_Dim[Item],"v",ISINSCOPE(ZV_Dim[Item])+0,"s",COUNTROWS(ZV_Fact)),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=1;I1=1;I2=1;I3=1;I4=1;I5=1;I6=1'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZV_Fact,ZV_Dim[Item]),"v",ISINSCOPE(ZV_Dim[Item])+0),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=0;I1=0;I2=0;I3=0;I4=0;I5=0;I6=0'),
    ('CONCATENATEX(ADDCOLUMNS(VALUES(ZV_Dim[Item]),"v",ISINSCOPE(ZV_Dim[Item])+0),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=0;I1=0;I2=0;I3=0;I4=0;I5=0;I6=0'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZV_Dim[Item],"v",CALCULATE(ISINSCOPE(ZV_Dim[Item]))+0,"s",COUNTROWS(ZV_Fact)),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=1;I1=1;I2=1;I3=1;I4=1;I5=1;I6=1'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZV_Fact,ZV_Dim[Item]),"v",CALCULATE(ISINSCOPE(ZV_Dim[Item]))+0),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=1;I1=1;I2=1;I3=1;I4=1;I5=1;I6=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZV_Dim[Item],"v",CALCULATE(ISINSCOPE(ZV_Dim[Fam]))+0,"s",COUNTROWS(ZV_Fact)),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=0;I1=0;I2=0;I3=0;I4=0;I5=0;I6=0'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZV_Fact,ZV_Dim[Item]),"v",CALCULATE(ISINSCOPE(ZV_Dim[Fam]))+0),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=0;I1=0;I2=0;I3=0;I4=0;I5=0;I6=0'),
    ('CONCATENATEX(ADDCOLUMNS(VALUES(ZV_Dim[Item]),"v",CALCULATE(ISINSCOPE(ZV_Dim[Fam]))+0),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=0;I1=0;I2=0;I3=0;I4=0;I5=0;I6=0'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZV_Dim[Item],"v",HASONEFILTER(ZV_Dim[Item])+0,"s",COUNTROWS(ZV_Fact)),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=1;I1=1;I2=1;I3=1;I4=1;I5=1;I6=1'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZV_Fact,ZV_Dim[Item]),"v",HASONEFILTER(ZV_Dim[Item])+0),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=0;I1=0;I2=0;I3=0;I4=0;I5=0;I6=0'),
    ('CONCATENATEX(ADDCOLUMNS(VALUES(ZV_Dim[Item]),"v",HASONEFILTER(ZV_Dim[Item])+0),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=0;I1=0;I2=0;I3=0;I4=0;I5=0;I6=0'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZV_Dim[Item],"v",HASONEVALUE(ZV_Dim[Fam])+0,"s",COUNTROWS(ZV_Fact)),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=1;I1=1;I2=1;I3=1;I4=1;I5=1;I6=1'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZV_Fact,ZV_Dim[Item]),"v",HASONEVALUE(ZV_Dim[Fam])+0),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=0;I1=0;I2=0;I3=0;I4=0;I5=0;I6=0'),
    ('CONCATENATEX(ADDCOLUMNS(VALUES(ZV_Dim[Item]),"v",HASONEVALUE(ZV_Dim[Fam])+0),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=0;I1=0;I2=0;I3=0;I4=0;I5=0;I6=0'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZV_Dim[Item],"v",SELECTEDVALUE(ZV_Dim[Fam],"m"),"s",COUNTROWS(ZV_Fact)),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=;I1=G1;I2=G1;I3=G2;I4=G2;I5=G1;I6=G1'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZV_Fact,ZV_Dim[Item]),"v",SELECTEDVALUE(ZV_Dim[Fam],"m")),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=m;I1=m;I2=m;I3=m;I4=m;I5=m;I6=m'),
    ('CONCATENATEX(ADDCOLUMNS(VALUES(ZV_Dim[Item]),"v",SELECTEDVALUE(ZV_Dim[Fam],"m")),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=m;I1=m;I2=m;I3=m;I4=m;I5=m;I6=m'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZV_Dim[Item],"v",CONCATENATEX(VALUES(ZV_Dim[Fam]),ZV_Dim[Fam]&"",","),"s",COUNTROWS(ZV_Fact)),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=;I1=G1;I2=G1;I3=G2;I4=G2;I5=G1;I6=G1'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZV_Fact,ZV_Dim[Item]),"v",CONCATENATEX(VALUES(ZV_Dim[Fam]),ZV_Dim[Fam]&"",",")),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=G1,G2,;I1=G1,G2,;I2=G1,G2,;I3=G1,G2,;I4=G1,G2,;I5=G1,G2,;I6=G1,G2,'),
    ('CONCATENATEX(ADDCOLUMNS(VALUES(ZV_Dim[Item]),"v",CONCATENATEX(VALUES(ZV_Dim[Fam]),ZV_Dim[Fam]&"",",")),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=G1,G2,;I1=G1,G2,;I2=G1,G2,;I3=G1,G2,;I4=G1,G2,;I5=G1,G2,;I6=G1,G2,'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZV_Dim[Item],"v",CONCATENATEX(ALL(ZV_Dim[Item]),ZV_Dim[Item]&"","/"),"s",COUNTROWS(ZV_Fact)),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=I1/I2/I3/I4/I5/I6/;I1=I1/I2/I3/I4/I5/I6/;I2=I1/I2/I3/I4/I5/I6/;I3=I1/I2/I3/I4/I5/I6/;I4=I1/I2/I3/I4/I5/I6/;I5=I1/I2/I3/I4/I5/I6/;I6=I1/I2/I3/I4/I5/I6/'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZV_Fact,ZV_Dim[Item]),"v",CONCATENATEX(ALL(ZV_Dim[Item]),ZV_Dim[Item]&"","/")),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=I1/I2/I3/I4/I5/I6/;I1=I1/I2/I3/I4/I5/I6/;I2=I1/I2/I3/I4/I5/I6/;I3=I1/I2/I3/I4/I5/I6/;I4=I1/I2/I3/I4/I5/I6/;I5=I1/I2/I3/I4/I5/I6/;I6=I1/I2/I3/I4/I5/I6/'),
    ('CONCATENATEX(ADDCOLUMNS(VALUES(ZV_Dim[Item]),"v",CONCATENATEX(ALL(ZV_Dim[Item]),ZV_Dim[Item]&"","/")),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=I1/I2/I3/I4/I5/I6/;I1=I1/I2/I3/I4/I5/I6/;I2=I1/I2/I3/I4/I5/I6/;I3=I1/I2/I3/I4/I5/I6/;I4=I1/I2/I3/I4/I5/I6/;I5=I1/I2/I3/I4/I5/I6/;I6=I1/I2/I3/I4/I5/I6/'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZV_Dim[Item],"v",CONCATENATEX(VALUES(ZV_Dim[Item]),ZV_Dim[Item]&"","/"),"s",COUNTROWS(ZV_Fact)),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=;I1=I1;I2=I2;I3=I3;I4=I4;I5=I5;I6=I6'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZV_Fact,ZV_Dim[Item]),"v",CONCATENATEX(VALUES(ZV_Dim[Item]),ZV_Dim[Item]&"","/")),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=I1/I2/I3/I4/I5/I6/;I1=I1/I2/I3/I4/I5/I6/;I2=I1/I2/I3/I4/I5/I6/;I3=I1/I2/I3/I4/I5/I6/;I4=I1/I2/I3/I4/I5/I6/;I5=I1/I2/I3/I4/I5/I6/;I6=I1/I2/I3/I4/I5/I6/'),
    ('CONCATENATEX(ADDCOLUMNS(VALUES(ZV_Dim[Item]),"v",CONCATENATEX(VALUES(ZV_Dim[Item]),ZV_Dim[Item]&"","/")),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=I1/I2/I3/I4/I5/I6/;I1=I1/I2/I3/I4/I5/I6/;I2=I1/I2/I3/I4/I5/I6/;I3=I1/I2/I3/I4/I5/I6/;I4=I1/I2/I3/I4/I5/I6/;I5=I1/I2/I3/I4/I5/I6/;I6=I1/I2/I3/I4/I5/I6/'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZV_Dim[Item],"v",CALCULATE(HASONEFILTER(ZV_Dim[Fam]))+0,"s",COUNTROWS(ZV_Fact)),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=0;I1=0;I2=0;I3=0;I4=0;I5=0;I6=0'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZV_Fact,ZV_Dim[Item]),"v",CALCULATE(HASONEFILTER(ZV_Dim[Fam]))+0),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=0;I1=0;I2=0;I3=0;I4=0;I5=0;I6=0'),
    ('CONCATENATEX(ADDCOLUMNS(VALUES(ZV_Dim[Item]),"v",CALCULATE(HASONEFILTER(ZV_Dim[Fam]))+0),ZV_Dim[Item]&"="&[v],";",ZV_Dim[Item])', '=0;I1=0;I2=0;I3=0;I4=0;I5=0;I6=0'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZV_Dim[Fam],"v",ISINSCOPE(ZV_Dim[Item])+0,"s",COUNTROWS(ZV_Fact)),ZV_Dim[Fam]&"="&[v],";",ZV_Dim[Fam])', '=0;G1=0;G2=0'),
]


CASES_OTHER = [
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({2024},ZS_Cal[Year]),"v",SUM(ZS_Fact[Amt])),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=15;P2=40;P3=110;P5=5'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({2024},ZS_Cal[Year]),"v",SUM(ZS_Fact[Amt])+SUM(ZS_Fact2[Amt])),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=16;P2=42;P3=126;P5=5'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({2024},ZS_Cal[Year]),"v",CALCULATE(SUM(ZS_Fact[Amt]),ALLSELECTED(ZS_Sup))),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=15;P2=40;P3=110;P5=5'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({2024},ZS_Cal[Year]),"v",DIVIDE(SUM(ZS_Fact[Amt]),CALCULATE(SUM(ZS_Fact[Amt]),ALL(ZS_Reg)))),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=1;P2=1;P3=1;P5=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({"S1"},ZS_Sup[Sup]),"v",RANKX(ALLSELECTED(ZS_Dim[Prod]),CALCULATE(SUM(ZS_Fact2[Amt])))),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=3;P2=2;P3=1;P4=4;P5=4'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({2024},ZS_Cal[Year]),"v",RANKX(ALLSELECTED(ZS_Dim[Prod]),CALCULATE(SUM(ZS_Fact2[Amt])))),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=3;P2=2;P3=1;P4=4;P5=4'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({"S1"},ZS_Sup[Sup]),"v",CALCULATE(SUM(ZS_Fact[Amt]),REMOVEFILTERS(ZS_Dim))),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=300;P2=300;P3=300;P4=300;P5=300'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({2024},ZS_Cal[Year]),"v",CALCULATE(SUM(ZS_Fact[Amt]),REMOVEFILTERS(ZS_Dim))),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=170;P2=170;P3=170;P4=170;P5=170'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({2024},ZS_Cal[Year]),"v",DISTINCTCOUNT(ZS_Fact[Prod])),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=1;P2=1;P3=1;P4=1;P5=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({"S1"},ZS_Sup[Sup]),"v",ISINSCOPE(ZS_Dim[Prod])+0),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=1;P2=1;P3=1;P4=1;P5=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({2024},ZS_Cal[Year]),"v",ISINSCOPE(ZS_Dim[Prod])+0),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=1;P2=1;P3=1;P4=1;P5=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({"S1"},ZS_Sup[Sup]),"v",HASONEVALUE(ZS_Sup[Sup])+0),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=1;P2=1;P3=1;P4=1;P5=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({2024},ZS_Cal[Year]),"v",HASONEVALUE(ZS_Sup[Sup])+0),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=0;P2=0;P3=0;P4=0;P5=0'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({"S1"},ZS_Sup[Sup]),"v",SELECTEDVALUE(ZS_Reg[Zone],"many")),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=many;P2=many;P3=many;P4=many;P5=many'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({2024},ZS_Cal[Year]),"v",SELECTEDVALUE(ZS_Reg[Zone],"many")),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=many;P2=many;P3=many;P4=many;P5=many'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({2024},ZS_Cal[Year]),"v",CALCULATE(SUM(ZS_Fact[Amt]),DATESYTD(ZS_Cal[Date]))),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=15;P2=40;P3=110;P5=5'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],ZS_Cal[Year],TREATAS({2024},ZS_Cal[Year]),"v",SUM(ZS_Fact[Amt])),ZS_Dim[Cat]&"|"&ZS_Cal[Year]&"="&[v],";",ZS_Dim[Cat]&"|"&ZS_Cal[Year])', 'A|2024=55;B|2024=110;C|2024=5'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],ZS_Cal[Year],TREATAS({2024},ZS_Cal[Year]),"v",SUM(ZS_Fact[Amt])+SUM(ZS_Fact2[Amt])),ZS_Dim[Cat]&"|"&ZS_Cal[Year]&"="&[v],";",ZS_Dim[Cat]&"|"&ZS_Cal[Year])', 'A|2024=58;B|2024=126;C|2024=5'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],ZS_Cal[Year],TREATAS({2024},ZS_Cal[Year]),"v",CALCULATE(SUM(ZS_Fact[Amt]),ALLSELECTED(ZS_Sup))),ZS_Dim[Cat]&"|"&ZS_Cal[Year]&"="&[v],";",ZS_Dim[Cat]&"|"&ZS_Cal[Year])', 'A|2024=55;B|2024=110;C|2024=5'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],ZS_Cal[Year],TREATAS({2024},ZS_Cal[Year]),"v",DIVIDE(SUM(ZS_Fact[Amt]),CALCULATE(SUM(ZS_Fact[Amt]),ALL(ZS_Reg)))),ZS_Dim[Cat]&"|"&ZS_Cal[Year]&"="&[v],";",ZS_Dim[Cat]&"|"&ZS_Cal[Year])', 'A|2024=1;B|2024=1;C|2024=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],ZS_Cal[Year],TREATAS({"S1"},ZS_Sup[Sup]),"v",RANKX(ALLSELECTED(ZS_Dim[Prod]),CALCULATE(SUM(ZS_Fact2[Amt])))),ZS_Dim[Cat]&"|"&ZS_Cal[Year]&"="&[v],";",ZS_Dim[Cat]&"|"&ZS_Cal[Year])', 'A|2023=1;A|2024=1;B|2023=1;B|2024=1;C|2023=1;C|2024=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],ZS_Cal[Year],TREATAS({2024},ZS_Cal[Year]),"v",RANKX(ALLSELECTED(ZS_Dim[Prod]),CALCULATE(SUM(ZS_Fact2[Amt])))),ZS_Dim[Cat]&"|"&ZS_Cal[Year]&"="&[v],";",ZS_Dim[Cat]&"|"&ZS_Cal[Year])', 'A|2024=1;B|2024=1;C|2024=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],ZS_Cal[Year],TREATAS({"S1"},ZS_Sup[Sup]),"v",CALCULATE(SUM(ZS_Fact[Amt]),REMOVEFILTERS(ZS_Dim))),ZS_Dim[Cat]&"|"&ZS_Cal[Year]&"="&[v],";",ZS_Dim[Cat]&"|"&ZS_Cal[Year])', 'A|2023=130;A|2024=170;B|2023=130;B|2024=170;C|2023=130;C|2024=170'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],ZS_Cal[Year],TREATAS({2024},ZS_Cal[Year]),"v",CALCULATE(SUM(ZS_Fact[Amt]),REMOVEFILTERS(ZS_Dim))),ZS_Dim[Cat]&"|"&ZS_Cal[Year]&"="&[v],";",ZS_Dim[Cat]&"|"&ZS_Cal[Year])', 'A|2024=170;B|2024=170;C|2024=170'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],ZS_Cal[Year],TREATAS({2024},ZS_Cal[Year]),"v",DISTINCTCOUNT(ZS_Fact[Prod])),ZS_Dim[Cat]&"|"&ZS_Cal[Year]&"="&[v],";",ZS_Dim[Cat]&"|"&ZS_Cal[Year])', 'A|2024=2;B|2024=2;C|2024=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],ZS_Cal[Year],TREATAS({"S1"},ZS_Sup[Sup]),"v",ISINSCOPE(ZS_Dim[Prod])+0),ZS_Dim[Cat]&"|"&ZS_Cal[Year]&"="&[v],";",ZS_Dim[Cat]&"|"&ZS_Cal[Year])', 'A|2023=0;A|2024=0;B|2023=0;B|2024=0;C|2023=0;C|2024=0'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],ZS_Cal[Year],TREATAS({2024},ZS_Cal[Year]),"v",ISINSCOPE(ZS_Dim[Prod])+0),ZS_Dim[Cat]&"|"&ZS_Cal[Year]&"="&[v],";",ZS_Dim[Cat]&"|"&ZS_Cal[Year])', 'A|2024=0;B|2024=0;C|2024=0'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],ZS_Cal[Year],TREATAS({"S1"},ZS_Sup[Sup]),"v",HASONEVALUE(ZS_Sup[Sup])+0),ZS_Dim[Cat]&"|"&ZS_Cal[Year]&"="&[v],";",ZS_Dim[Cat]&"|"&ZS_Cal[Year])', 'A|2023=1;A|2024=1;B|2023=1;B|2024=1;C|2023=1;C|2024=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],ZS_Cal[Year],TREATAS({2024},ZS_Cal[Year]),"v",HASONEVALUE(ZS_Sup[Sup])+0),ZS_Dim[Cat]&"|"&ZS_Cal[Year]&"="&[v],";",ZS_Dim[Cat]&"|"&ZS_Cal[Year])', 'A|2024=0;B|2024=0;C|2024=0'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],ZS_Cal[Year],TREATAS({"S1"},ZS_Sup[Sup]),"v",SELECTEDVALUE(ZS_Reg[Zone],"many")),ZS_Dim[Cat]&"|"&ZS_Cal[Year]&"="&[v],";",ZS_Dim[Cat]&"|"&ZS_Cal[Year])', 'A|2023=many;A|2024=many;B|2023=many;B|2024=many;C|2023=many;C|2024=many'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],ZS_Cal[Year],TREATAS({2024},ZS_Cal[Year]),"v",SELECTEDVALUE(ZS_Reg[Zone],"many")),ZS_Dim[Cat]&"|"&ZS_Cal[Year]&"="&[v],";",ZS_Dim[Cat]&"|"&ZS_Cal[Year])', 'A|2024=many;B|2024=many;C|2024=many'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],ZS_Cal[Year],TREATAS({2024},ZS_Cal[Year]),"v",CALCULATE(SUM(ZS_Fact[Amt]),DATESYTD(ZS_Cal[Date]))),ZS_Dim[Cat]&"|"&ZS_Cal[Year]&"="&[v],";",ZS_Dim[Cat]&"|"&ZS_Cal[Year])', 'A|2024=55;B|2024=110;C|2024=5'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"k1","k2"},ZM_U[K]),"v",SUM(ZM_A[V])),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=210;y1=210;y2=210;y3=210;y5=210'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"k1","k2"},ZM_U[K]),"v",COUNTROWS(ZM_B)),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=4;y1=4;y2=4;y3=4;y5=4'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"k1","k2"},ZM_U[K]),"v",CALCULATE(SUM(ZM_F[Amt]),ALLSELECTED(ZM_U))),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=7;y1=7;y2=7;y3=7;y5=7'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"k1","k2"},ZM_U[K]),"v",RANKX(ALLSELECTED(ZM_U[X]),CALCULATE(SUM(ZM_F[Amt])))),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=1;y1=1;y2=1;y3=1;y5=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"k1","k2"},ZM_U[K]),"v",SELECTEDVALUE(ZM_B[K],"m")),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=m;y1=m;y2=m;y3=m;y5=m'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"k1","k2"},ZM_U[K]),"v",CALCULATE(SUM(ZM_A[V]),REMOVEFILTERS(ZM_B))),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=210;y1=210;y2=210;y3=210;y5=210'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_A[K],TREATAS({"n1","n5"},ZM_B[N]),"v",SUM(ZM_F[Amt])),ZM_A[K]&"="&[v],";",ZM_A[K])', 'k1=63;k2=63;k3=63;k4=63'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_A[K],TREATAS({"n1","n5"},ZM_B[N]),"v",SUM(ZM_F2[Amt])),ZM_A[K]&"="&[v],";",ZM_A[K])', 'k1=1000;k2=1000;k3=1000;k4=1000'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_A[K],TREATAS({"n1","n5"},ZM_B[N]),"v",COUNTROWS(ZM_B)),ZM_A[K]&"="&[v],";",ZM_A[K])', 'k1=2;k2=2;k3=2;k4=2'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_A[K],TREATAS({"n1","n5"},ZM_B[N]),"v",COUNTROWS(ZM_W)),ZM_A[K]&"="&[v],";",ZM_A[K])', 'k1=4;k2=4;k3=4;k4=4'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_A[K],TREATAS({"n1","n5"},ZM_B[N]),"v",CALCULATE(SUM(ZM_F[Amt]),ALLSELECTED(ZM_U))),ZM_A[K]&"="&[v],";",ZM_A[K])', 'k1=63;k2=63;k3=63;k4=63'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_A[K],TREATAS({"n1","n5"},ZM_B[N]),"v",RANKX(ALLSELECTED(ZM_U[X]),CALCULATE(SUM(ZM_F[Amt])))),ZM_A[K]&"="&[v],";",ZM_A[K])', 'k1=1;k2=1;k3=1;k4=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_A[K],TREATAS({"n1","n5"},ZM_B[N]),"v",DIVIDE(SUM(ZM_F[Amt]),CALCULATE(SUM(ZM_F[Amt]),ALL(ZM_W)))),ZM_A[K]&"="&[v],";",ZM_A[K])', 'k1=1;k2=1;k3=1;k4=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_A[K],TREATAS({"n1","n5"},ZM_B[N]),"v",SELECTEDVALUE(ZM_B[K],"m")),ZM_A[K]&"="&[v],";",ZM_A[K])', 'k1=m;k2=m;k3=m;k4=m'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_A[K],TREATAS({"n1","n5"},ZM_B[N]),"v",CALCULATE(SUM(ZM_A[V]),REMOVEFILTERS(ZM_B))),ZM_A[K]&"="&[v],";",ZM_A[K])', 'k1=30;k2=30;k3=90;k4=60'),
]


def _same(ours: str, powerbi: str) -> bool:
    if ours == powerbi:
        return True
    try:
        return math.isclose(float(ours), float(powerbi), rel_tol=1e-9, abs_tol=0.0)
    except ValueError:
        return False


@pytest.mark.parametrize("expression, powerbi", [pytest.param(e, p, id=f"zv{i}") for i, (e, p) in enumerate(CASES_ZV)])
def test_sc_rows_and_blank_member_functions_on_model_zv_match_power_bi(expression: str, powerbi: str) -> None:
    assert _same(m.ours_for("ZV", expression), powerbi)


@pytest.mark.parametrize("model, expression, powerbi", [pytest.param(mo, e, p, id=f"other{i}") for i, (mo, e, p) in enumerate(CASES_OTHER)])
def test_sc_rows_over_filters_on_other_tables_match_power_bi(model: str, expression: str, powerbi: str) -> None:
    assert _same(m.ours_for(model, expression), powerbi)
