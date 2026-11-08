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
]


@pytest.mark.parametrize(("expression", "expected"), CASES)
def test_orphan_filter_78_matches_power_bi(expression, expected):
    assert m.ours_for("ZH", expression) == expected
