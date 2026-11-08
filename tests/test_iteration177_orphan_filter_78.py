"""Iteration 177 (Task 88, orphan-filter-78): a fact table filter whose rows include orphans keeps the fact rows of the blank member
of its one-side table (CALCULATE(COUNTROWS(F), F2) with F2 orphans). Scratch model ZH is defined in docs/plans/2026-11-08-orphan-filter-78-model.py;
the expected values are the live Power BI answers (never saved to the parity files)."""
import importlib.util
from pathlib import Path

import pytest

from tests import critic3_models as m

_MODEL_FILE = Path(__file__).resolve().parent.parent / "docs" / "plans" / "2026-11-08-orphan-filter-78-model.py"
_spec = importlib.util.spec_from_file_location("orphan_filter_78_model", _MODEL_FILE)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

CASES = [
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(COUNTROWS(ZH_F),ZH_F2)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=9;m2=9;m2b=9;m4=9;m7=9'),  # fixed
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(SUM(ZH_F[Amt]),ZH_F2)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=176;m2=176;m2b=176;m4=176;m7=176'),  # fixed
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],TREATAS({"m2","m4"},ZH_B[N]),"v",CALCULATE(COUNTROWS(ZH_F),ZH_F2)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm2=9;m4=9'),  # fixed
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(COUNTROWS(ZH_F),ZH_F2)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=4;y1=2;y3=1;y6=2'),  # fixed
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],TREATAS({"m2","m4"},ZH_B[N]),"v",CALCULATE(SUM(ZH_F[Amt]),ZH_F2)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=113;y1=18;y3=9;y6=36'),  # fixed
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(COUNTROWS(ZH_F),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=9;m2=9;m2b=9;m4=9;m7=9'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",COUNTROWS(CALCULATETABLE(VALUES(ZH_B[N]),ZH_F2))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=1;m2=1;m2b=1;m4=1;m7=1'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],TREATAS({"m2","m4"},ZH_B[N]),"v",CALCULATE(SUM(ZH_F[Amt]),ZH_F)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm2=268;m4=268'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(SUM(ZH_A[V]),ZH_U)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=243;x1=243;x2=243;x3=243;x4=243;x6=243;x8=243'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],TREATAS({"m2","m4"},ZH_B[N]),"v",CALCULATE(COUNTROWS(ZH_U),ZH_A)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     'x1=1;x2=1;x3=1;x4=1;x6=1;x8=1'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],TREATAS({"m2","m4"},ZH_B[N]),"v",COUNTROWS(CALCULATETABLE(VALUES(ZH_B[N]),ZH_W))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=2;x1=2;x2=2;x3=2;x4=2;x6=2;x8=2'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(SUM(ZH_F2[Amt]),ZH_A)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=69;y1=24;y3=32;y6=22'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],TREATAS({"m2","m4"},ZH_B[N]),"v",CALCULATE(SUM(ZH_A[V]),ZH_F2)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=86;y1=86;y10=86;y3=86;y6=86;y9=86'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",INT(ISCROSSFILTERED(ZH_A[K]))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=1;m2=1;m2b=1;m4=1;m7=1'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],TREATAS({"h1","h3"},ZH_U[K]),"v",INT(ISCROSSFILTERED(ZH_U))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=1;m2=1;m2b=1;m4=1;m7=1'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(SUM(ZH_F[Amt]),REMOVEFILTERS(ZH_U[X]))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=268;x1=268;x2=268;x3=268;x4=268;x6=268;x8=268'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],TREATAS({"h1","h3"},ZH_U[K]),"v",INT(ISCROSSFILTERED(ZH_B[N]))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     'x1=0;x3=0'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],TREATAS({"m2","m4"},ZH_B[N]),"v",SUMX(TOPN(2,ALL(ZH_U),CALCULATE(SUM(ZH_F[Amt]))),CALCULATE(SUM(ZH_F[Amt])))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=179;x1=179;x2=179;x3=179;x4=179;x6=179;x8=179'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],TREATAS({"h1","h3"},ZH_U[K]),"v",COUNTROWS(RELATEDTABLE(ZH_F))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     'y1=2;y3=1'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],TREATAS({"m2","m4"},ZH_B[N]),"v",INT(ISCROSSFILTERED(ZH_U))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=1;y1=1;y10=1;y3=1;y6=1;y9=1'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],TREATAS({"h1","h3"},ZH_U[K]),"v",SUMX(ALLSELECTED(ZH_W[Y]),CALCULATE(SUM(ZH_F[Amt])))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=27;m2=27;m2b=27;m4=27;m7=27'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],TREATAS({"y1","y9"},ZH_W[Y]),"v",RANKX(ALLSELECTED(ZH_U),CALCULATE(SUM(ZH_F2[Amt])),,ASC,Dense)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=1;m2=1;m2b=1;m4=1;m7=1'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],TREATAS({"h1","h3"},ZH_U[K]),"v",RANKX(ALLSELECTED(ZH_W),CALCULATE(COUNTROWS(ZH_F)),,DESC,Dense)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     'x1=1;x3=2'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],TREATAS({"m2","m4"},ZH_B[N]),"v",RANKX(ALLSELECTED(ZH_U[X]),CALCULATE(SUM(ZH_F2[Amt])),,ASC,Dense)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=5;x1=3;x2=1;x3=4;x4=1;x6=2;x8=1'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],TREATAS({"y1","y9"},ZH_W[Y]),"v",RANKX(ALLSELECTED(ZH_W),CALCULATE(SUM(ZH_F2[Amt])),,ASC)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=1;x1=2;x2=1;x3=1;x4=1;x6=1;x8=1'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],TREATAS({"h1","h3"},ZH_U[K]),"v",RANKX(ALLSELECTED(ZH_W),CALCULATE(COUNTROWS(ZH_F)),,ASC,Dense)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=1;y1=2;y10=1;y3=1;y6=1;y9=1'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],TREATAS({"m2","m4"},ZH_B[N]),"v",RANKX(ALLSELECTED(ZH_U[X]),CALCULATE(COUNTROWS(ZH_F)),,ASC,Dense)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=5;y1=2;y10=1;y3=2;y6=2;y9=1'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],TREATAS({"y1","y9"},ZH_W[Y]),"v",RANKX(ALLSELECTED(ZH_U),CALCULATE(SUM(ZH_F2[Amt])),,ASC,Dense)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     'y1=1;y9=1'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",RANKX(ALLSELECTED(ZH_U),CALCULATE(SUM(ZH_F2[Amt])),,ASC,Dense)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=6;m2=6;m2b=6;m4=6;m7=6'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],TREATAS({"m2","m4"},ZH_B[N]),"v",RANKX(ALLSELECTED(ZH_U),CALCULATE(COUNTROWS(ZH_F)),,DESC)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm2=1;m4=1'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],TREATAS({"y1","y9"},ZH_W[Y]),"v",RANKX(ALLSELECTED(ZH_W),CALCULATE(SUM(ZH_A[V])),,DESC,Dense)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=1;m2=1;m2b=1;m4=1;m7=1'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],TREATAS({"h1","h3"},ZH_U[K]),"v",RANKX(ALL(ZH_U[X]),CALCULATE(SUM(ZH_A[V])))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     'x1=1;x3=1'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],TREATAS({"m2","m4"},ZH_B[N]),"v",RANKX(VALUES(ZH_W[Y]),CALCULATE(SUM(ZH_A[V])),,DESC)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=1;x1=1;x2=1;x3=1;x4=1;x6=1;x8=1'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",RANKX(VALUES(ZH_U[X]),CALCULATE(SUM(ZH_F2[Amt])),,ASC)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=4;y1=1;y10=1;y3=1;y6=1;y9=1'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],TREATAS({"m2","m4"},ZH_B[N]),"v",RANKX(ALL(ZH_W[Y]),CALCULATE(SUM(ZH_A[V])),,ASC,Dense)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=1;y1=1;y10=1;y3=1;y6=1;y9=1'),  # matching
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(COUNTROWS(ZH_U),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=4;m2=4;m2b=4;m4=4;m7=4'),  # fixed (Task 88 part B, spec item 5)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(COUNTROWS(ZH_U),ZH_F)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=5;m2=5;m2b=5;m4=5;m7=5'),  # fixed (Task 88 part B, spec item 7)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",COUNTROWS(CALCULATETABLE(VALUES(ZH_U[X]),FILTER(ZH_F,ZH_F[Amt]>10)))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=5;m2=5;m2b=5;m4=5;m7=5'),  # fixed (Task 88 part B, spec item 34)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",COUNTROWS(CALCULATETABLE(VALUES(ZH_U[X]),ZH_F))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=6;m2=6;m2b=6;m4=6;m7=6'),  # fixed (Task 88 part B, spec item 35)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",COUNTROWS(CALCULATETABLE(VALUES(ZH_U[X]),ZH_F2))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=4;m2=4;m2b=4;m4=4;m7=4'),  # fixed (Task 88 part B, spec item 36)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],TREATAS({"m2","m4"},ZH_B[N]),"v",CALCULATE(COUNTROWS(ZH_U),ZH_F)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm2=5;m4=5'),  # fixed (Task 88 part B, spec item 47)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],TREATAS({"m2","m4"},ZH_B[N]),"v",CALCULATE(COUNTROWS(ZH_U),ZH_F2)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm2=3;m4=3'),  # fixed (Task 88 part B, spec item 48)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],TREATAS({"m2","m4"},ZH_B[N]),"v",COUNTROWS(CALCULATETABLE(VALUES(ZH_U[X]),FILTER(ZH_F,ZH_F[Amt]>10)))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm2=5;m4=5'),  # fixed (Task 88 part B, spec item 71)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],TREATAS({"m2","m4"},ZH_B[N]),"v",COUNTROWS(CALCULATETABLE(VALUES(ZH_U[X]),ZH_F2))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm2=4;m4=4'),  # fixed (Task 88 part B, spec item 72)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(COUNTROWS(ZH_U),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=2;y1=1;y6=1'),  # fixed (Task 88 part B, spec item 167)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(COUNTROWS(ZH_U),ZH_F)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=2;y1=1;y3=1;y6=1'),  # fixed (Task 88 part B, spec item 169)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",COUNTROWS(CALCULATETABLE(VALUES(ZH_U[X]),ZH_F))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=3;y1=1;y3=1;y6=1'),  # fixed (Task 88 part B, spec item 195)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",COUNTROWS(CALCULATETABLE(VALUES(ZH_U[X]),ZH_F2))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=1;y1=1;y3=1;y6=1'),  # fixed (Task 88 part B, spec item 196)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],TREATAS({"m2","m4"},ZH_B[N]),"v",CALCULATE(COUNTROWS(ZH_U),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=2;y1=1;y6=1'),  # fixed (Task 88 part B, spec item 206)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],TREATAS({"m2","m4"},ZH_B[N]),"v",CALCULATE(COUNTROWS(ZH_U),ZH_F)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=2;y1=1;y3=1;y6=1'),  # fixed (Task 88 part B, spec item 207)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],TREATAS({"m2","m4"},ZH_B[N]),"v",CALCULATE(COUNTROWS(ZH_U),ZH_F2)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     'y1=1;y3=1;y6=1'),  # fixed (Task 88 part B, spec item 208)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],TREATAS({"m2","m4"},ZH_B[N]),"v",COUNTROWS(CALCULATETABLE(VALUES(ZH_U[X]),FILTER(ZH_F,ZH_F[Amt]>10)))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=3;y1=1;y6=1'),  # fixed (Task 88 part B, spec item 231)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],TREATAS({"m2","m4"},ZH_B[N]),"v",COUNTROWS(CALCULATETABLE(VALUES(ZH_U[X]),ZH_F))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=3;y1=1;y3=1;y6=1'),  # fixed (Task 88 part B, spec item 232)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],TREATAS({"m2","m4"},ZH_B[N]),"v",COUNTROWS(CALCULATETABLE(VALUES(ZH_U[X]),ZH_F2))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=1;y1=1;y3=1;y6=1'),  # fixed (Task 88 part B, spec item 233)
]


@pytest.mark.parametrize(("expression", "expected"), CASES)
def test_orphan_filter_78_matches_power_bi(expression, expected):
    assert m.ours_for("ZH", expression) == expected


SPEC3_CASES = [  # Task 88 (nested clears, spec3): CALCULATE(CALCULATE(inner, clear), table filter); expected = live Power BI
    ('CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALL(ZH_U)),ZH_F)',
     '7'),  # restored (right on main, wrong before this step) (spec3 item 0)
    ('CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALL(ZH_W)),ZH_F2)',
     '7'),  # restored (right on main, wrong before this step) (spec3 item 1)
    ('CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALLSELECTED(ZH_U)),FILTER(ZH_F,ZH_F[Amt]>10))',
     '5'),  # fixed vs main (spec3 item 5)
    ('CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALLSELECTED(ZH_U)),ZH_F)',
     '6'),  # fixed vs main (spec3 item 6)
    ('CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALLSELECTED(ZH_U)),ZH_F2)',
     '4'),  # fixed vs main (spec3 item 7)
    ('CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),REMOVEFILTERS(ZH_U[X])),ZH_F2)',
     '4'),  # fixed vs main (spec3 item 10)
    ('CALCULATE(CALCULATE(COUNTROWS(ZH_F),ALL(ZH_F)),ZH_F2)',
     '12'),  # restored (right on main, wrong before this step) (spec3 item 20)
    ('CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_U)),FILTER(ZH_F,ZH_F[Amt]>10))',
     '6'),  # restored (right on main, wrong before this step) (spec3 item 24)
    ('CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_U)),FILTER(ZH_F2,ZH_F2[Amt]>10))',
     '6'),  # restored (right on main, wrong before this step) (spec3 item 25)
    ('CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_U)),ZH_F)',
     '6'),  # restored (right on main, wrong before this step) (spec3 item 26)
    ('CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_W)),ZH_F)',
     '6'),  # restored (right on main, wrong before this step) (spec3 item 27)
    ('CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALLSELECTED(ZH_U)),FILTER(ZH_F2,ZH_F2[Amt]>10))',
     '3'),  # fixed vs main (spec3 item 30)
    ('CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALLSELECTED(ZH_U)),ZH_F)',
     '5'),  # fixed vs main (spec3 item 31)
    ('CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALLSELECTED(ZH_U)),ZH_F2)',
     '3'),  # fixed vs main (spec3 item 32)
    ('CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),ALL(ZH_F)),FILTER(ZH_F2,ZH_F2[Amt]>10))',
     '6'),  # restored (right on main, wrong before this step) (spec3 item 43)
    ('CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),ALL(ZH_W)),ZH_F)',
     '6'),  # restored (right on main, wrong before this step) (spec3 item 45)
    ('CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),ALLSELECTED(ZH_U)),FILTER(ZH_F,ZH_F[Amt]>10))',
     '4'),  # fixed vs main (spec3 item 46)
    ('CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),ALLSELECTED(ZH_U)),FILTER(ZH_F2,ZH_F2[Amt]>10))',
     '3'),  # fixed vs main (spec3 item 47)
    ('CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),REMOVEFILTERS(ZH_U[X])),FILTER(ZH_F,ZH_F[Amt]>10))',
     '4'),  # fixed vs main (spec3 item 49)
    ('CALCULATE(CALCULATE(SUM(ZH_F[Amt]),ALLSELECTED(ZH_U)),ZH_F2)',
     '176'),  # fixed vs main (spec3 item 62)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALL(ZH_F)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=7;m2=7;m2b=7;m4=7;m7=7'),  # restored (right on main, wrong before this step) (spec3 item 65)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALL(ZH_U)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=7;m2=7;m2b=7;m4=7;m7=7'),  # restored (right on main, wrong before this step) (spec3 item 66)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALL(ZH_U)),ZH_F2)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=7;m2=7;m2b=7;m4=7;m7=7'),  # restored (right on main, wrong before this step) (spec3 item 67)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALL(ZH_W)),ZH_F)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=7;m2=7;m2b=7;m4=7;m7=7'),  # restored (right on main, wrong before this step) (spec3 item 68)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_F),ALLSELECTED(ZH_U)),ZH_F2)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=9;m2=9;m2b=9;m4=9;m7=9'),  # fixed vs main (spec3 item 83)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_U)),ZH_F)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=6;m2=6;m2b=6;m4=6;m7=6'),  # restored (right on main, wrong before this step) (spec3 item 86)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_U)),ZH_F2)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=6;m2=6;m2b=6;m4=6;m7=6'),  # restored (right on main, wrong before this step) (spec3 item 87)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_W)),ZH_F)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=6;m2=6;m2b=6;m4=6;m7=6'),  # restored (right on main, wrong before this step) (spec3 item 88)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_W)),ZH_F2)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=6;m2=6;m2b=6;m4=6;m7=6'),  # restored (right on main, wrong before this step) (spec3 item 89)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALLSELECTED(ZH_U)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=3;m2=3;m2b=3;m4=3;m7=3'),  # fixed vs main (spec3 item 92)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALLSELECTED(ZH_U)),ZH_F2)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=3;m2=3;m2b=3;m4=3;m7=3'),  # fixed vs main (spec3 item 93)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),REMOVEFILTERS(ZH_U[X])),ZH_F)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=5;m2=5;m2b=5;m4=5;m7=5'),  # fixed vs main (spec3 item 95)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),ALL(ZH_U)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=6;m2=6;m2b=6;m4=6;m7=6'),  # restored (right on main, wrong before this step) (spec3 item 104)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),ALL(ZH_U)),ZH_F2)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=6;m2=6;m2b=6;m4=6;m7=6'),  # restored (right on main, wrong before this step) (spec3 item 105)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),ALL(ZH_W)),ZH_F)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=6;m2=6;m2b=6;m4=6;m7=6'),  # restored (right on main, wrong before this step) (spec3 item 106)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),ALLSELECTED(ZH_U)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=3;m2=3;m2b=3;m4=3;m7=3'),  # fixed vs main (spec3 item 108)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),ALLSELECTED(ZH_U)),ZH_F2)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=3;m2=3;m2b=3;m4=3;m7=3'),  # fixed vs main (spec3 item 109)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(SUM(ZH_F[Amt]),ALLSELECTED(ZH_U)),ZH_F2)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=176;m2=176;m2b=176;m4=176;m7=176'),  # fixed vs main (spec3 item 126)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALL(ZH_F)),ZH_F2)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=7;x1=7;x2=7;x3=7;x4=7;x6=7;x8=7'),  # restored (right on main, wrong before this step) (spec3 item 127)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALL(ZH_U)),ZH_F)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=7;x1=7;x2=7;x3=7;x4=7;x6=7;x8=7'),  # restored (right on main, wrong before this step) (spec3 item 128)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALL(ZH_U)),ZH_F2)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=7;x1=7;x2=7;x3=7;x4=7;x6=7;x8=7'),  # restored (right on main, wrong before this step) (spec3 item 129)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALL(ZH_W)),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=7;x1=7;x2=7;x3=7;x4=7;x6=7;x8=7'),  # restored (right on main, wrong before this step) (spec3 item 130)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALLSELECTED(ZH_U)),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=1;x1=1;x2=1;x4=1;x6=1'),  # fixed vs main (spec3 item 132)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALLSELECTED(ZH_U)),ZH_F2)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=1;x1=1;x3=1;x6=1'),  # fixed vs main (spec3 item 133)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_F),ALL(ZH_F)),ZH_F2)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=12;x1=12;x2=12;x3=12;x4=12;x6=12;x8=12'),  # restored (right on main, wrong before this step) (spec3 item 142)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_F)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=6;x1=6;x2=6;x3=6;x4=6;x6=6;x8=6'),  # restored (right on main, wrong before this step) (spec3 item 149)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_U)),ZH_F)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=6;x1=6;x2=6;x3=6;x4=6;x6=6;x8=6'),  # restored (right on main, wrong before this step) (spec3 item 150)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_U)),ZH_F2)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=6;x1=6;x2=6;x3=6;x4=6;x6=6;x8=6'),  # restored (right on main, wrong before this step) (spec3 item 151)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_W)),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=6;x1=6;x2=6;x3=6;x4=6;x6=6;x8=6'),  # restored (right on main, wrong before this step) (spec3 item 152)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_W)),ZH_F)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=6;x1=6;x2=6;x3=6;x4=6;x6=6;x8=6'),  # restored (right on main, wrong before this step) (spec3 item 153)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_W)),ZH_F2)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=6;x1=6;x2=6;x3=6;x4=6;x6=6;x8=6'),  # restored (right on main, wrong before this step) (spec3 item 154)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALLSELECTED(ZH_U)),ZH_F)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     'x1=1;x2=1;x3=1;x4=1;x6=1'),  # fixed vs main (spec3 item 158)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),REMOVEFILTERS(ZH_U[X])),ZH_F)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     'x1=1;x2=1;x3=1;x4=1;x6=1'),  # fixed vs main (spec3 item 159)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),REMOVEFILTERS(ZH_U[X])),ZH_F2)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     'x1=1;x3=1;x6=1'),  # fixed vs main (spec3 item 160)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),ALL(ZH_F)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=6;x1=6;x2=6;x3=6;x4=6;x6=6;x8=6'),  # restored (right on main, wrong before this step) (spec3 item 174)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),ALL(ZH_F)),ZH_F2)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=6;x1=6;x2=6;x3=6;x4=6;x6=6;x8=6'),  # restored (right on main, wrong before this step) (spec3 item 176)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),ALL(ZH_U)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=6;x1=6;x2=6;x3=6;x4=6;x6=6;x8=6'),  # restored (right on main, wrong before this step) (spec3 item 177)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),REMOVEFILTERS(ZH_U[X])),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     'x1=1;x3=1;x6=1'),  # fixed vs main (spec3 item 179)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),REMOVEFILTERS(ZH_U[X])),ZH_F2)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     'x1=1;x3=1;x6=1'),  # fixed vs main (spec3 item 180)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(SUM(ZH_F2[Amt]),ALL(ZH_W)),ZH_F)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=147;x1=147;x2=147;x3=147;x4=147;x6=147;x8=147'),  # restored (right on main, wrong before this step) (spec3 item 183)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(SUM(ZH_F[Amt]),ALLSELECTED(ZH_U)),ZH_F2)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=113;x1=18;x3=9;x6=36'),  # fixed vs main (spec3 item 188)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALL(ZH_U)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=7;y1=7;y10=7;y3=7;y6=7;y9=7'),  # restored (right on main, wrong before this step) (spec3 item 191)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALL(ZH_U)),ZH_F)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=7;y1=7;y10=7;y3=7;y6=7;y9=7'),  # restored (right on main, wrong before this step) (spec3 item 192)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALL(ZH_W)),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=7;y1=7;y10=7;y3=7;y6=7;y9=7'),  # restored (right on main, wrong before this step) (spec3 item 193)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALL(ZH_W)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=7;y1=7;y10=7;y3=7;y6=7;y9=7'),  # restored (right on main, wrong before this step) (spec3 item 194)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALLSELECTED(ZH_U)),ZH_F)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=3;y1=1;y3=1;y6=1'),  # fixed vs main (spec3 item 197)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),REMOVEFILTERS(ZH_U[X])),ZH_F2)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=1;y1=1;y3=1;y6=1'),  # fixed vs main (spec3 item 198)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_F),ALL(ZH_F)),ZH_F2)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=12;y1=12;y10=12;y3=12;y6=12;y9=12'),  # restored (right on main, wrong before this step) (spec3 item 211)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_F),ALL(ZH_U)),ZH_F2)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=12;y1=12;y10=12;y3=12;y6=12;y9=12'),  # restored (right on main, wrong before this step) (spec3 item 214)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_F),ALLSELECTED(ZH_U)),ZH_F2)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=4;y1=2;y3=1;y6=2'),  # fixed vs main (spec3 item 217)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_F)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=6;y1=6;y10=6;y3=6;y6=6;y9=6'),  # restored (right on main, wrong before this step) (spec3 item 219)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_U)),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=6;y1=6;y10=6;y3=6;y6=6;y9=6'),  # restored (right on main, wrong before this step) (spec3 item 221)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_U)),ZH_F)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=6;y1=6;y10=6;y3=6;y6=6;y9=6'),  # restored (right on main, wrong before this step) (spec3 item 222)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_W)),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=6;y1=6;y10=6;y3=6;y6=6;y9=6'),  # restored (right on main, wrong before this step) (spec3 item 223)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALLSELECTED(ZH_U)),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=2;y1=1;y6=1'),  # fixed vs main (spec3 item 227)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),ALL(ZH_F)),ZH_F2)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=6;y1=6;y10=6;y3=6;y6=6;y9=6'),  # restored (right on main, wrong before this step) (spec3 item 239)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),ALL(ZH_U)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=6;y1=6;y10=6;y3=6;y6=6;y9=6'),  # restored (right on main, wrong before this step) (spec3 item 240)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),ALL(ZH_W)),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=6;y1=6;y10=6;y3=6;y6=6;y9=6'),  # restored (right on main, wrong before this step) (spec3 item 241)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),ALL(ZH_W)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=6;y1=6;y10=6;y3=6;y6=6;y9=6'),  # restored (right on main, wrong before this step) (spec3 item 242)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),ALL(ZH_W)),ZH_F2)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=6;y1=6;y10=6;y3=6;y6=6;y9=6'),  # restored (right on main, wrong before this step) (spec3 item 243)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(DISTINCTCOUNT(ZH_U[K]),ALLSELECTED(ZH_U)),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=2;y1=1;y6=1'),  # fixed vs main (spec3 item 244)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(SUM(ZH_F2[Amt]),ALLNOBLANKROW(ZH_U)),ZH_F)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=78;y1=78;y10=78;y3=78;y6=78;y9=78'),  # restored (right on main, wrong before this step) (spec3 item 248)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(SUM(ZH_F[Amt]),ALL(ZH_F)),ZH_F2)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=268;y1=268;y10=268;y3=268;y6=268;y9=268'),  # restored (right on main, wrong before this step) (spec3 item 256)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(SUM(ZH_F[Amt]),ALL(ZH_W)),ZH_F2)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=268;y1=268;y10=268;y3=268;y6=268;y9=268'),  # restored (right on main, wrong before this step) (spec3 item 258)
]


def _same_answer(ours, expected):
    if ours == expected:
        return True
    try:
        return float(ours) == float(expected)
    except ValueError:
        return False


@pytest.mark.parametrize(("expression", "expected"), SPEC3_CASES)
def test_nested_clear_under_table_filter_matches_power_bi(expression, expected):
    assert _same_answer(m.ours_for("ZH", expression), expected)

