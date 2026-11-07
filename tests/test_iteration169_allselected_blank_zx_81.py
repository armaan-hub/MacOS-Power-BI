"""Task 81 follow-up (allselected-blank-71, held-out model ZX): ALLSELECTED inside SUMMARIZECOLUMNS with a TREATAS filter on the
dimension itself. The blank (unknown) member is kept only when no filter on a column ALLSELECTED asks for (or that it keeps) fails it:
a TREATAS Fam filter drops the blank row from ALLSELECTED(Fam) and ALLSELECTED(Dim), but not from ALLSELECTED(Item) or ALLSELECTED(Tier).
Literal (expression, Power BI answer) tuples on a literal copy of the guest model; numbers compare by float value."""

import pytest

from tests import critic3_models as m

DIM = [("Item", "string"), ("Fam", "string"), ("Tier", "int64")]
DIMS = [('I1', 'F3', 1), ('I2', 'F3', 2), ('I3', 'F3', 1), ('I4', 'F2', 2), ('I5', 'F1', 1), ('I6', 'F2', 2), ('I7', 'F3', 2)]
FCT = [("Id", "int64"), ("Item", "string"), ("Dt", "dateTime"), ("Val", "double"), ("Units", "int64")]
FACTS = [(1, 'I1', (2023, 1, 20), 61.0, 9), (2, 'I6', (2023, 2, 20), 29.0, 9), (3, 'I4', (2024, 5, 19), 74.0, 4), (4, 'I3', (2023, 11, 27), 24.0, 1), (5, 'I1', (2024, 8, 19), 78.0, 9), (6, 'I1', (2023, 8, 22), 85.0, 9), (7, None, (2023, 8, 25), 7.0, 0), (8, 'I1', (2024, 6, 13), 66.0, 9), (9, 'I5', (2024, 3, 5), 29.0, 0), (10, 'I7', (2024, 4, 14), 7.0, 8), (11, 'I5', (2023, 11, 12), 76.0, 9), (12, 'I1', (2024, 1, 12), 58.0, 0), (13, 'I2', (2024, 3, 9), 5.0, 0), (14, 'I7', (2024, 5, 14), 33.0, 4), (15, 'I3', (2024, 3, 21), 85.0, 7), (16, 'I6', (2023, 1, 17), -6.0, 3), (17, 'I6', (2023, 12, 7), 18.0, 4), (18, 'I6', (2023, 2, 20), 53.0, 6), (19, 'I4', (2023, 3, 7), 78.0, 0), (20, 'I3', (2023, 4, 11), 18.0, 4), (21, 'I3', (2023, 4, 19), 75.0, 5), (22, 'I7', (2024, 5, 26), 38.0, 3)]
m.SPEC["ZX"] = {
    "tables": {"ZX_Dim": (DIM, DIMS), "ZX_Fact": (FCT, FACTS), "ZX_Cal": (m.CAL_COLS, None)},
    "rels": [
        ("ZX_r1", "ZX_Fact", "Item", "ZX_Dim", "Item", True, False, "many", "one"),
        ("ZX_r2", "ZX_Fact", "Dt", "ZX_Cal", "Date", True, False, "many", "one"),
    ],
}

CASES = [
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=1;I2=5;I3=2;I5=3;I7=4'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=1;I2=5;I3=2;I5=3;I7=4'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=1;I2=1;I3=1;I5=1;I7=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=1;I2=1;I3=1;I5=1;I7=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=1;I2=1;I3=1;I5=1;I7=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=5;I2=1;I3=4;I5=2;I7=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=5;I2=1;I3=4;I5=2;I7=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=2;I2=1;I3=2;I5=2;I7=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=2;I2=1;I3=2;I5=2;I7=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=2;I2=1;I3=2;I5=2;I7=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim[Item]))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=8;I2=8;I3=8;I5=8;I7=8'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=5;I2=5;I3=5;I5=5;I7=5'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim[Fam]))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=2;I2=2;I3=2;I5=2;I7=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim[Tier]))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=3;I2=3;I3=3;I5=3;I7=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=3;I2=3;I3=3;I5=3;I7=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=15;I2=15;I3=15;I5=15;I7=15'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=15;I2=15;I3=15;I5=15;I7=15'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=5;I2=1;I3=4;I5=2;I7=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=5;I2=1;I3=4;I5=2;I7=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=5;I2=1;I3=4;I5=2;I7=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=5;I2=5;I3=5;I5=5;I7=5'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=5;I2=5;I3=5;I5=5;I7=5'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=348;I2=5;I3=202;I5=105;I7=78'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=348;I2=5;I3=202;I5=105;I7=78'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=348;I2=5;I3=202;I5=105;I7=78'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=15.4;I2=15.4;I3=15.4;I5=15.4;I7=15.4'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=15.4;I2=15.4;I3=15.4;I5=15.4;I7=15.4'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=36;I2=0;I3=17;I5=9;I7=15'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=36;I2=0;I3=17;I5=9;I7=15'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=36;I2=0;I3=17;I5=9;I7=15'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=1;F3=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=3;F3=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=2;F3=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=1;F3=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=2;F3=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=2;F3=5'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=2;F3=6'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=1;F3=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=2;F3=4'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=1;F3=4'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim[Item]))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=8;F3=8'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=5;F3=5'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim[Fam]))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=2;F3=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim[Tier]))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=3;F3=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=3;F3=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=2;F3=13'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=15;F3=15'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=15;F3=15'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=2;F3=13'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=15;F3=15'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=105;F3=5'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=5;F3=5'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=105;F3=105'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=105;F3=83'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=83;F3=83'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=9;F3=17'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=15.4;F3=15.4'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=38.5;F3=38.5'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=9;F3=34'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=25.6666666666667;F3=25.6666666666667'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=1;1|2024=1;2|2023=1;2|2024=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=1;1|2024=1;2|2023=4;2|2024=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=1;1|2024=1;2|2023=1;2|2024=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=1;1|2024=1;2|2023=2;2|2024=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=1;1|2024=1;2|2023=3;2|2024=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=5;1|2024=4;2|2023=1;2|2024=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=5;1|2024=5;2|2023=1;2|2024=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=3;1|2024=2;2|2023=1;2|2024=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=2;1|2024=3;2|2023=1;2|2024=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=4;1|2024=3;2|2023=1;2|2024=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim[Item]))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=8;1|2024=8;2|2023=8;2|2024=8'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=5;1|2024=5;2|2023=5;2|2024=5'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim[Fam]))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=2;1|2024=2;2|2023=2;2|2024=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim[Tier]))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=3;1|2024=3;2|2023=3;2|2024=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=3;1|2024=3;2|2023=3;2|2024=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=6;1|2024=5;2|2024=4'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=6;1|2024=9;2|2023=6;2|2024=9'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=6;1|2024=5;2|2024=4'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=6;1|2024=9;2|2023=6;2|2024=9'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=6;1|2024=9;2|2023=6;2|2024=9'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=76;1|2024=29;2|2024=5'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=76;1|2024=5;2|2023=76;2|2024=5'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=76;1|2024=29;2|2024=83'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=339;1|2024=83;2|2023=339;2|2024=83'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=76;1|2024=29;2|2023=76;2|2024=29'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=12.3333333333333;1|2024=8.33333333333333;2|2024=7.5'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=12.3333333333333;1|2024=8;2|2023=12.3333333333333;2|2024=8'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=18.5;1|2024=12.5;2|2024=15'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=37;1|2024=20;2|2023=37;2|2024=20'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=18.5;1|2024=13.3333333333333;2|2023=18.5;2|2024=13.3333333333333'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=1;F3|1=1;F3|2=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=3;F3|1=1;F3|2=4'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=2;F3|1=1;F3|2=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=1;F3|1=1;F3|2=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=2;F3|1=1;F3|2=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=2;F3|1=4;F3|2=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=2;F3|1=6;F3|2=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=1;F3|1=2;F3|2=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=2;F3|1=3;F3|2=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",RANKX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Units])),,ASC,DENSE)),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=1;F3|1=3;F3|2=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim[Item]))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=8;F3|1=8;F3|2=8'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=5;F3|1=5;F3|2=5'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim[Fam]))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=2;F3|1=2;F3|2=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim[Tier]))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=3;F3|1=3;F3|2=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",COUNTROWS(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=3;F3|1=3;F3|2=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=2;F3|1=9;F3|2=4'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=15;F3|1=15;F3|2=15'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=11;F3|1=11;F3|2=4'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=2;F3|1=13;F3|2=13'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SUMX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(COUNTROWS(ZX_Fact)))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=15;F3|1=15;F3|2=15'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=105;F3|1=202;F3|2=5'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=5;F3|1=5;F3|2=5'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=105;F3|1=105;F3|2=83'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=105;F3|1=83;F3|2=83'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",MINX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Val])))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=83;F3|1=83;F3|2=83'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=9;F3|1=26.5;F3|2=7.5'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=15.4;F3|1=15.4;F3|2=15.4'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim[Fam]),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=31;F3|1=31;F3|2=15'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=9;F3|1=34;F3|2=34'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Tier],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",AVERAGEX(ALLSELECTED(ZX_Dim[Fam],ZX_Dim[Tier]),CALCULATE(SUM(ZX_Fact[Units])))),ZX_Dim[Fam]&"|"&ZX_Dim[Tier]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Tier])', 'F1|1=25.6666666666667;F3|1=25.6666666666667;F3|2=25.6666666666667'),
]


def _same(ours, expected):
    if ours == expected:
        return True
    try:
        return float(ours) == float(expected)
    except (TypeError, ValueError):
        return False


@pytest.mark.parametrize("expression, expected", CASES, ids=[f"zx{index}" for index in range(len(CASES))])
def test_allselected_blank_under_dimension_filter(expression, expected):
    assert _same(m.ours_for("ZX", expression), expected)
