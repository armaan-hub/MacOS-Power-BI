"""Task 87 (table-filter-77): a table used as a CALCULATE filter argument filters the other tables by its expanded table, row by row
(relationships.py), and an unrestricted one-side table keeps the filter it already has (measures.py).

The cases are literal (model, expression, Power BI answer) tuples: the 11 spec items that were wrong before this change (7 on ZS,
2 on ZM, 2 on ZJ) plus 30 items that already matched (10 per model). ZJ is loaded from its model file; ZM and ZS come from
tests.critic3_models. Answers compare exactly through tests.critic3_models.ours_for."""

import importlib.util
import pathlib

import pytest

from tests import critic3_models as m

_MODEL_FILE = pathlib.Path(__file__).resolve().parents[1] / "docs" / "plans" / "2026-11-08-rankx-sets-75-model.py"
_spec = importlib.util.spec_from_file_location("rankx_sets_75_model", _MODEL_FILE)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

CASES = [
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Cal[Year],"v",CALCULATE(SUM(ZS_Fact[Qty]),ZS_Fact2)),ZS_Cal[Year]&"="&[v],";",ZS_Cal[Year])', '2024=2'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Cal[Year],TREATAS({2024},ZS_Cal[Year]),"v",CALCULATE(SUM(ZS_Fact[Qty]),ZS_Fact2)),ZS_Cal[Year]&"="&[v],";",ZS_Cal[Year])', '2024=2'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],TREATAS({"S1"},ZS_Sup[Sup]),"v",CALCULATE(SUM(ZS_Fact[Qty]),ZS_Fact2)),ZS_Dim[Cat]&"="&[v],";",ZS_Dim[Cat])', 'A=2'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Reg[Zone],"v",CALCULATE(SUM(ZS_Fact[Qty]),ZS_Fact2)),ZS_Reg[Zone]&"="&[v],";",ZS_Reg[Zone])', 'Z1=2'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Sup[Sup],"v",CALCULATE(SUM(ZS_Fact[Qty]),ZS_Fact2)),ZS_Sup[Sup]&"="&[v],";",ZS_Sup[Sup])', 'S1=2'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Sup[Sup],TREATAS({"S1"},ZS_Sup[Sup]),"v",CALCULATE(SUM(ZS_Fact[Qty]),ZS_Fact2)),ZS_Sup[Sup]&"="&[v],";",ZS_Sup[Sup])', 'S1=2'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Sup[Sup],TREATAS({2024},ZS_Cal[Year]),"v",CALCULATE(SUM(ZS_Fact[Qty]),ZS_Fact2)),ZS_Sup[Sup]&"="&[v],";",ZS_Sup[Sup])', 'S1=2'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],"v",CALCULATE(SUM(ZM_F2[Amt]),ZM_F)),ZM_U[X]&"="&[v],";",ZM_U[X])', 'x1=100;x2=500;x4=400'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],TREATAS({"n1","n5"},ZM_B[N]),"v",CALCULATE(SUM(ZM_F2[Amt]),ZM_F)),ZM_U[X]&"="&[v],";",ZM_U[X])', 'x1=100;x2=500;x4=400'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",CALCULATE(SUM(ZJ_F2[Amt]),ZJ_F)),ZJ_U[X]&"="&[v],";",ZJ_U[X])', 'x2=67;x4=25'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"n1","n6"},ZJ_B[N]),"v",CALCULATE(SUM(ZJ_F2[Amt]),ZJ_F)),ZJ_U[X]&"="&[v],";",ZJ_U[X])', 'x2=67;x4=25'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Cal[Year],"v",CALCULATE(COUNTROWS(ZS_Cal),CROSSFILTER(ZS_Fact[Dt],ZS_Cal[Date],BOTH))),ZS_Cal[Year]&"="&[v],";",ZS_Cal[Year])', '2023=365;2024=366'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Cal[Year],TREATAS({"S1"},ZS_Sup[Sup]),"v",INT(ISCROSSFILTERED(ZS_Fact2[Amt]))),ZS_Cal[Year]&"="&[v],";",ZS_Cal[Year])', '2023=1;2024=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Cal[Year],TREATAS({2024},ZS_Cal[Year]),"v",INT(ISFILTERED(ZS_Dim[Prod]))),ZS_Cal[Year]&"="&[v],";",ZS_Cal[Year])', '2024=0'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],TREATAS({"S1"},ZS_Sup[Sup]),"v",CALCULATE(SUM(ZS_Fact2[Amt]),REMOVEFILTERS(ZS_Sup))),ZS_Dim[Cat]&"="&[v],";",ZS_Dim[Cat])', 'A=7;B=16;C=8'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],TREATAS({2024},ZS_Cal[Year]),"v",INT(ISFILTERED(ZS_Cal[Year]))),ZS_Dim[Cat]&"="&[v],";",ZS_Dim[Cat])', 'A=1;B=1;C=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({"S1"},ZS_Sup[Sup]),"v",CALCULATE(SUM(ZS_Fact2[Amt]),CROSSFILTER(ZS_Fact2[Prod],ZS_Dim[Prod],NONE))),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=31;P2=31;P3=31;P4=31;P5=31'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({2024},ZS_Cal[Year]),"v",INT(ISCROSSFILTERED(ZS_Dim))),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=1;P2=1;P3=1;P4=1;P5=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Reg[Zone],TREATAS({"S1"},ZS_Sup[Sup]),"v",CALCULATE(SUM(ZS_Fact[Amt]),CROSSFILTER(ZS_Fact[Prod],ZS_Dim[Prod],BOTH))),ZS_Reg[Zone]&"="&[v],";",ZS_Reg[Zone])', 'Z1=295'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Reg[Zone],TREATAS({2024},ZS_Cal[Year]),"v",INT(ISCROSSFILTERED(ZS_Fact[Amt]))),ZS_Reg[Zone]&"="&[v],";",ZS_Reg[Zone])', 'Z1=1;Z2=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Sup[Sup],TREATAS({"S1"},ZS_Sup[Sup]),"v",CALCULATE(DISTINCTCOUNT(ZS_Fact[Prod]),ALLEXCEPT(ZS_Dim,ZS_Dim[Cat]))),ZS_Sup[Sup]&"="&[v],";",ZS_Sup[Sup])', 'S1=5'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],"v",CALCULATE(SUM(ZM_A[V]),CROSSFILTER(ZM_A[K],ZM_B[K],NONE))),ZM_B[N]&"="&[v],";",ZM_B[N])', 'n1=210;n1b=210;n2=210;n5=210'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],"v",INT(ISCROSSFILTERED(ZM_W))),ZM_B[N]&"="&[v],";",ZM_B[N])', 'n1=0;n1b=0;n2=0;n5=0'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],TREATAS({"k1","k2"},ZM_U[K]),"v",INT(ISCROSSFILTERED(ZM_U))),ZM_B[N]&"="&[v],";",ZM_B[N])', 'n1=1;n1b=1;n2=1;n5=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],TREATAS({"n1","n5"},ZM_B[N]),"v",INT(ISCROSSFILTERED(ZM_F))),ZM_B[N]&"="&[v],";",ZM_B[N])', 'n1=0;n5=0'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],"v",INT(ISCROSSFILTERED(ZM_F))),ZM_U[X]&"="&[v],";",ZM_U[X])', '=1;x1=1;x2=1;x3=1;x4=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],TREATAS({"k1","k2"},ZM_U[K]),"v",INT(ISCROSSFILTERED(ZM_A[K]))),ZM_U[X]&"="&[v],";",ZM_U[X])', 'x1=0;x2=0'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],TREATAS({"n1","n5"},ZM_B[N]),"v",INT(ISCROSSFILTERED(ZM_A[K]))),ZM_U[X]&"="&[v],";",ZM_U[X])', '=1;x1=1;x2=1;x3=1;x4=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],"v",COUNTROWS(CALCULATETABLE(VALUES(ZM_W[Y]),ZM_F))),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=1;y1=1;y2=1;y3=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"k1","k2"},ZM_U[K]),"v",CALCULATE(SUM(ZM_F[Amt]),REMOVEFILTERS(ZM_W))),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=63;y1=63;y2=63;y3=63;y5=63'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"n1","n5"},ZM_B[N]),"v",CALCULATE(SUM(ZM_F2[Amt]),ZM_F)),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=400;y1=100;y2=500'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],"v",CALCULATE(SUM(ZJ_A[V]),CROSSFILTER(ZJ_A[K],ZJ_B[K],NONE))),ZJ_B[N]&"="&[v],";",ZJ_B[N])', 'n1=158;n2=158;n3=158;n6=158'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],"v",INT(ISCROSSFILTERED(ZJ_W))),ZJ_B[N]&"="&[v],";",ZJ_B[N])', 'n1=0;n2=0;n3=0;n6=0'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],TREATAS({"j2","j3"},ZJ_U[K]),"v",INT(ISCROSSFILTERED(ZJ_U))),ZJ_B[N]&"="&[v],";",ZJ_B[N])', 'n1=1;n2=1;n3=1;n6=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],TREATAS({"n1","n6"},ZJ_B[N]),"v",INT(ISCROSSFILTERED(ZJ_F))),ZJ_B[N]&"="&[v],";",ZJ_B[N])', 'n1=0;n6=0'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",INT(ISCROSSFILTERED(ZJ_F))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=1;x1=1;x2=1;x3=1;x4=1;x5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"j2","j3"},ZJ_U[K]),"v",INT(ISCROSSFILTERED(ZJ_A[K]))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', 'x2=0;x3=0'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"n1","n6"},ZJ_B[N]),"v",INT(ISCROSSFILTERED(ZJ_A[K]))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=1;x1=1;x2=1;x3=1;x4=1;x5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],"v",COUNTROWS(CALCULATETABLE(VALUES(ZJ_W[Y]),ZJ_F))),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=1;y2=1;y5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],TREATAS({"j2","j3"},ZJ_U[K]),"v",CALCULATE(SUM(ZJ_F[Amt]),REMOVEFILTERS(ZJ_W))),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=255;y2=255;y3=255;y5=255;y7=255'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],TREATAS({"n1","n6"},ZJ_B[N]),"v",CALCULATE(SUM(ZJ_F2[Amt]),ZJ_F)),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=25;y2=67'),
    # Task 87 fix pass: items that were wrong on main and now match (blank member of a one-to-one partner under a table filter, FILTER(F, ..) blank group)
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],"v",COUNTROWS(CALCULATETABLE(VALUES(ZM_W[Y]),ZM_F))),ZM_U[X]&"="&[v],";",ZM_U[X])', '=1;x1=1;x2=1;x3=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],TREATAS({"n1","n5"},ZM_B[N]),"v",COUNTROWS(CALCULATETABLE(VALUES(ZM_W[Y]),ZM_F))),ZM_U[X]&"="&[v],";",ZM_U[X])', '=1;x1=1;x2=1;x3=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",COUNTROWS(CALCULATETABLE(VALUES(ZJ_W[Y]),ZJ_F))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=1;x2=1;x5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"n1","n6"},ZJ_B[N]),"v",COUNTROWS(CALCULATETABLE(VALUES(ZJ_W[Y]),ZJ_F))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=1;x2=1;x5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",CALCULATE(COUNTROWS(ZJ_U),FILTER(ZJ_F,ZJ_F[Amt]>10))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', 'x1=1;x2=1;x4=1;x5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",COUNTROWS(CALCULATETABLE(VALUES(ZJ_U[X]),FILTER(ZJ_F,ZJ_F[Amt]>10)))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=1;x1=1;x2=1;x4=1;x5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",COUNTROWS(CALCULATETABLE(VALUES(ZJ_U[X]),ZJ_F))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=1;x1=1;x2=1;x4=1;x5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",COUNTROWS(CALCULATETABLE(VALUES(ZJ_W[Y]),FILTER(ZJ_F,ZJ_F[Amt]>10)))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=1;x2=1;x5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",COUNTROWS(CALCULATETABLE(VALUES(ZJ_W[Y]),ZJ_A))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=2;x2=1;x3=1;x5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",COUNTROWS(CALCULATETABLE(VALUES(ZJ_W[Y]),ZJ_F2))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', 'x2=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",COUNTROWS(CALCULATETABLE(VALUES(ZJ_W[Y]),ZJ_U))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', 'x2=1;x3=1;x5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],"v",COUNTROWS(CALCULATETABLE(VALUES(ZJ_U[X]),ZJ_A))),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=3;y2=1;y3=1;y5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],TREATAS({"y2","y7"},ZJ_W[Y]),"v",COUNTROWS(CALCULATETABLE(VALUES(ZJ_U[X]),ZJ_A))),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', 'y2=1'),
]

REFUSED = [
    # table filter on one end of a one-to-one pair, partner filtered by a TREATAS argument alone: y7 survives in Power BI in a way not modelled
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],TREATAS({"y2","y7"},ZJ_W[Y]),"v",CALCULATE(COUNTROWS(ZJ_W),ZJ_U)),ZJ_B[N]&"="&[v],";",ZJ_B[N])'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],TREATAS({"y2","y7"},ZJ_W[Y]),"v",COUNTROWS(CALCULATETABLE(VALUES(ZJ_W[Y]),ZJ_U))),ZJ_B[N]&"="&[v],";",ZJ_B[N])'),
]


@pytest.mark.parametrize("model, expression, expected", CASES, ids=[f"case{n:02d}-{model}" for n, (model, _e, _p) in enumerate(CASES)])
def test_table_filter_matches_power_bi(model, expression, expected):
    assert m.ours_for(model, expression) == expected


@pytest.mark.parametrize("model, expression", REFUSED, ids=[f"refused{n:02d}-{model}" for n, (model, _e) in enumerate(REFUSED)])
def test_unmodelled_table_filter_is_refused(model, expression):
    assert m.ours_for(model, expression).startswith("LOCAL-REJECT")
