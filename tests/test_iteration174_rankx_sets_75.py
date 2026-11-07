"""Task 85 (rankx-sets-75): guard for RANKX ranking sets over multi-table models (ZM, ZJ, ZS).

Part A (blank member of one-to-one tables in ranking sets) and Part B (ALLSELECTED of a dimension under a filter on another table)
are still wrong in the local engine, so no spec item was fixed in this iteration. This file locks 30 spec items that already match
Power BI on the same models, so later changes cannot break them. Literal (model, expression, Power BI answer) tuples; ZJ is loaded
from its model file. Answers compare through tests.critic3_models.ours_for."""

import importlib.util
import pathlib

import pytest

from tests import critic3_models as m

_MODEL_FILE = pathlib.Path(__file__).resolve().parents[1] / "docs" / "plans" / "2026-11-08-rankx-sets-75-model.py"
_spec = importlib.util.spec_from_file_location("rankx_sets_75_model", _MODEL_FILE)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

CASES = [
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],"v",RANKX(ALL(ZM_U),CALCULATE(SUM(ZM_F2[Amt])))),ZM_B[N]&"="&[v],";",ZM_B[N])', 'n1=1;n1b=1;n2=1;n5=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],"v",RANKX(VALUES(ZM_W[Y]),CALCULATE(SUM(ZM_F2[Amt])),,ASC,Dense)),ZM_B[N]&"="&[v],";",ZM_B[N])', 'n1=5;n1b=5;n2=5;n5=5'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],TREATAS({"k1","k2"},ZM_U[K]),"v",RANKX(VALUES(ZM_U[X]),CALCULATE(SUM(ZM_F2[Amt])),,ASC)),ZM_B[N]&"="&[v],";",ZM_B[N])', 'n1=3;n1b=3;n2=3;n5=3'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],TREATAS({"n1","n5"},ZM_B[N]),"v",RANKX(ALLSELECTED(ZM_U[X]),CALCULATE(SUM(ZM_F2[Amt])),,DESC,Dense)),ZM_B[N]&"="&[v],";",ZM_B[N])', 'n1=1;n5=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],"v",RANKX(ALLSELECTED(ZM_U[X]),CALCULATE(SUM(ZM_F[Amt])),,DESC,Dense)),ZM_U[X]&"="&[v],";",ZM_U[X])', '=1;x1=5;x2=4;x3=3;x4=2'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],TREATAS({"k1","k2"},ZM_U[K]),"v",RANKX(ALLSELECTED(ZM_U[X]),CALCULATE(SUM(ZM_F[Amt])))),ZM_U[X]&"="&[v],";",ZM_U[X])', 'x1=2;x2=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],TREATAS({"n1","n5"},ZM_B[N]),"v",RANKX(ALL(ZM_U),CALCULATE(SUM(ZM_F[Amt])),,ASC)),ZM_U[X]&"="&[v],";",ZM_U[X])', '=5;x1=1;x2=2;x3=3;x4=4'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],TREATAS({"n1","n5"},ZM_B[N]),"v",RANKX(ALLSELECTED(ZM_W[Y]),CALCULATE(SUM(ZM_F[Amt])),,DESC,Dense)),ZM_U[X]&"="&[v],";",ZM_U[X])', '=1;x1=1;x2=1;x3=1;x4=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],"v",RANKX(VALUES(ZM_W[Y]),CALCULATE(COUNTROWS(ZM_F)),,DESC,Dense)),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=1;y1=1;y2=1;y3=1;y5=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"n1","n5"},ZM_B[N]),"v",RANKX(ALL(ZM_W),CALCULATE(SUM(ZM_F2[Amt])),,DESC,Dense)),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=2;y1=2;y2=1;y3=3;y5=3'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],"v",RANKX(ALL(ZJ_U),CALCULATE(COUNTROWS(ZJ_F)))),ZJ_B[N]&"="&[v],";",ZJ_B[N])', 'n1=1;n2=1;n3=1;n6=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],"v",RANKX(ALLSELECTED(ZJ_W),CALCULATE(SUM(ZJ_F[Amt])),,DESC)),ZJ_B[N]&"="&[v],";",ZJ_B[N])', 'n1=1;n2=1;n3=1;n6=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],TREATAS({"j2","j3"},ZJ_U[K]),"v",RANKX(ALL(ZJ_W[Y]),CALCULATE(COUNTROWS(ZJ_F)))),ZJ_B[N]&"="&[v],";",ZJ_B[N])', 'n1=1;n2=1;n3=1;n6=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],TREATAS({"n1","n6"},ZJ_B[N]),"v",RANKX(ALL(ZJ_U[X]),CALCULATE(SUM(ZJ_F[Amt])),,DESC,Dense)),ZJ_B[N]&"="&[v],";",ZJ_B[N])', 'n1=1;n6=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",RANKX(ALLSELECTED(ZJ_U[X]),CALCULATE(SUM(ZJ_F[Amt])),,ASC)),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=2;x1=4;x2=3;x3=1;x4=5;x5=6'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"j2","j3"},ZJ_U[K]),"v",RANKX(ALL(ZJ_U[X]),CALCULATE(COUNTROWS(ZJ_F)))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', 'x2=1;x3=2'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"j2","j3"},ZJ_U[K]),"v",RANKX(VALUES(ZJ_W[Y]),CALCULATE(SUM(ZJ_F2[Amt])),,DESC)),ZJ_U[X]&"="&[v],";",ZJ_U[X])', 'x2=1;x3=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"n1","n6"},ZJ_B[N]),"v",RANKX(VALUES(ZJ_U[X]),CALCULATE(SUM(ZJ_F2[Amt])),,DESC)),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=1;x1=1;x2=1;x3=1;x4=1;x5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],TREATAS({"j2","j3"},ZJ_U[K]),"v",RANKX(ALL(ZJ_W[Y]),CALCULATE(SUM(ZJ_F2[Amt])))),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=2;y2=1;y3=2;y5=2;y7=2'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],TREATAS({"n1","n6"},ZJ_B[N]),"v",RANKX(ALL(ZJ_U[X]),CALCULATE(SUM(ZJ_F2[Amt])),,ASC,Dense)),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=2;y2=2;y3=1;y5=1;y7=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],"v",RANKX(ALL(ZS_Dim),CALCULATE(COUNTROWS(ZS_Fact)),,DESC)),ZS_Dim[Cat]&"="&[v],";",ZS_Dim[Cat])', 'A=1;B=1;C=5'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],"v",RANKX(ALLSELECTED(ZS_Dim[Prod]),CALCULATE(SUM(ZS_Fact2[Amt])))),ZS_Dim[Cat]&"="&[v],";",ZS_Dim[Cat])', 'A=1;B=1;C=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],TREATAS({"S1"},ZS_Sup[Sup]),"v",RANKX(ALL(ZS_Dim[Cat]),CALCULATE(SUM(ZS_Fact2[Amt])),,DESC,Dense)),ZS_Dim[Cat]&"="&[v],";",ZS_Dim[Cat])', 'A=2;B=1;C=3'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],TREATAS({"S1"},ZS_Sup[Sup]),"v",RANKX(VALUES(ZS_Dim[Prod]),CALCULATE(SUM(ZS_Fact[Amt])),,ASC,Dense)),ZS_Dim[Cat]&"="&[v],";",ZS_Dim[Cat])', 'A=3;B=3;C=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Cat],TREATAS({2024},ZS_Cal[Year]),"v",RANKX(VALUES(ZS_Dim[Cat]),CALCULATE(SUM(ZS_Fact2[Amt])))),ZS_Dim[Cat]&"="&[v],";",ZS_Dim[Cat])', 'A=1;B=1;C=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],"v",RANKX(ALLSELECTED(ZS_Sup),CALCULATE(COUNTROWS(ZS_Fact)),,ASC)),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=3;P2=3;P3=3;P4=3;P5=3'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({"S1"},ZS_Sup[Sup]),"v",RANKX(ALL(ZS_Sup[Sup]),CALCULATE(SUM(ZS_Fact[Amt])),,DESC)),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=1;P2=1;P3=1;P4=1;P5=2'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({2024},ZS_Cal[Year]),"v",RANKX(ALLSELECTED(ZS_Dim[Cat]),CALCULATE(COUNTROWS(ZS_Fact)),,DESC)),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=1;P2=1;P3=1;P4=1;P5=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Sup[Sup],"v",RANKX(ALLSELECTED(ZS_Dim),CALCULATE(SUM(ZS_Fact[Amt])),,DESC,Dense)),ZS_Sup[Sup]&"="&[v],";",ZS_Sup[Sup])', 'S1=1;S2=4'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Sup[Sup],TREATAS({"S1"},ZS_Sup[Sup]),"v",RANKX(ALLSELECTED(ZS_Dim),CALCULATE(COUNTROWS(ZS_Fact)),,ASC,Dense)),ZS_Sup[Sup]&"="&[v],";",ZS_Sup[Sup])', 'S1=3'),
]


@pytest.mark.parametrize("model, expression, powerbi", CASES)
def test_matching_ranking_set_answer(model: str, expression: str, powerbi: str) -> None:
    assert m.ours_for(model, expression) == powerbi


# Spec items that were wrong before the fix (blank member of one-to-one tables in ranking sets, SUMMARIZECOLUMNS TREATAS and ALLSELECTED,
# deterministic order of blank-member propagation); Power BI answers from the Task 85 spec.
FIXED_CASES = [
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],"v",RANKX(ALLSELECTED(ZM_W),CALCULATE(SUM(ZM_F[Amt])),,ASC,Dense)),ZM_B[N]&"="&[v],";",ZM_B[N])', 'n1=6;n1b=6;n2=6;n5=6'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],TREATAS({"k1","k2"},ZM_U[K]),"v",RANKX(ALL(ZM_W),CALCULATE(SUM(ZM_F[Amt])),,DESC)),ZM_B[N]&"="&[v],";",ZM_B[N])', 'n1=3;n1b=3;n2=3;n5=3'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],TREATAS({"k1","k2"},ZM_U[K]),"v",RANKX(ALL(ZM_W),CALCULATE(SUM(ZM_F[Amt])),,DESC,Dense)),ZM_B[N]&"="&[v],";",ZM_B[N])', 'n1=3;n1b=3;n2=3;n5=3'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],"v",RANKX(ALLSELECTED(ZM_W),CALCULATE(SUM(ZM_F[Amt])),,ASC)),ZM_U[X]&"="&[v],";",ZM_U[X])', '=5;x1=2;x2=3;x3=4;x4=5'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],"v",RANKX(ALLSELECTED(ZM_W[Y]),CALCULATE(COUNTROWS(ZM_F)),,ASC)),ZM_U[X]&"="&[v],";",ZM_U[X])', '=5;x1=5;x2=5;x3=5;x4=5'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],"v",RANKX(ALLSELECTED(ZM_W[Y]),CALCULATE(SUM(ZM_F[Amt])),,ASC)),ZM_U[X]&"="&[v],";",ZM_U[X])', '=5;x1=5;x2=5;x3=5;x4=5'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],TREATAS({"k1","k2"},ZM_U[K]),"v",RANKX(ALL(ZM_W),CALCULATE(SUM(ZM_F[Amt])))),ZM_U[X]&"="&[v],";",ZM_U[X])', 'x1=4;x2=3'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],TREATAS({"n1","n5"},ZM_B[N]),"v",RANKX(ALL(ZM_W),CALCULATE(SUM(ZM_F[Amt])),,DESC)),ZM_U[X]&"="&[v],";",ZM_U[X])', '=1;x1=4;x2=3;x3=2;x4=2'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],TREATAS({"n1","n5"},ZM_B[N]),"v",RANKX(ALLSELECTED(ZM_W),CALCULATE(SUM(ZM_F[Amt])),,DESC)),ZM_U[X]&"="&[v],";",ZM_U[X])', '=1;x1=4;x2=3;x3=2;x4=2'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],TREATAS({"n1","n5"},ZM_B[N]),"v",RANKX(ALLSELECTED(ZM_W[Y]),CALCULATE(SUM(ZM_F[Amt])),,ASC)),ZM_U[X]&"="&[v],";",ZM_U[X])', '=5;x1=5;x2=5;x3=5;x4=5'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],"v",RANKX(ALLSELECTED(ZM_U[X]),CALCULATE(COUNTROWS(ZM_F)))),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=1;y1=1;y2=1;y3=1;y5=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],"v",RANKX(ALLSELECTED(ZM_U[X]),CALCULATE(COUNTROWS(ZM_F)),,DESC,Dense)),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=1;y1=1;y2=1;y3=1;y5=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],"v",RANKX(ALLSELECTED(ZM_U[X]),CALCULATE(SUM(ZM_F[Amt])),,DESC,Dense)),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=1;y1=1;y2=1;y3=1;y5=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],"v",RANKX(ALLSELECTED(ZM_W),CALCULATE(SUM(ZM_F[Amt])),,ASC,Dense)),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=6;y1=2;y2=3;y3=4;y5=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],"v",RANKX(VALUES(ZM_U[X]),CALCULATE(COUNTROWS(ZM_F)),,DESC,Dense)),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=1;y1=1;y2=1;y3=1;y5=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],"v",RANKX(VALUES(ZM_U[X]),CALCULATE(SUM(ZM_F[Amt])))),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=1;y1=1;y2=1;y3=1;y5=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"n1","n5"},ZM_B[N]),"v",RANKX(ALL(ZM_U[X]),CALCULATE(COUNTROWS(ZM_F)),,DESC,Dense)),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=1;y1=1;y2=1;y3=1;y5=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"n1","n5"},ZM_B[N]),"v",RANKX(ALLSELECTED(ZM_U[X]),CALCULATE(COUNTROWS(ZM_F)))),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=1;y1=1;y2=1;y3=1;y5=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"n1","n5"},ZM_B[N]),"v",RANKX(ALLSELECTED(ZM_U[X]),CALCULATE(SUM(ZM_F[Amt])),,DESC,Dense)),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=1;y1=1;y2=1;y3=1;y5=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"n1","n5"},ZM_B[N]),"v",RANKX(ALLSELECTED(ZM_W),CALCULATE(SUM(ZM_F[Amt])),,ASC)),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=6;y1=2;y2=3;y3=4;y5=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"n1","n5"},ZM_B[N]),"v",RANKX(ALLSELECTED(ZM_W),CALCULATE(SUM(ZM_F[Amt])),,DESC)),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=1;y1=4;y2=3;y3=2;y5=5'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"n1","n5"},ZM_B[N]),"v",RANKX(ALLSELECTED(ZM_W),CALCULATE(SUM(ZM_F[Amt])),,DESC,Dense)),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=1;y1=4;y2=3;y3=2;y5=5'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"n1","n5"},ZM_B[N]),"v",RANKX(VALUES(ZM_U[X]),CALCULATE(COUNTROWS(ZM_F)),,DESC,Dense)),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=1;y1=1;y2=1;y3=1;y5=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"n1","n5"},ZM_B[N]),"v",RANKX(VALUES(ZM_U[X]),CALCULATE(SUM(ZM_F2[Amt])),,ASC,Dense)),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=2;y1=1;y2=1;y3=1;y5=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"n1","n5"},ZM_B[N]),"v",RANKX(VALUES(ZM_U[X]),CALCULATE(SUM(ZM_F[Amt])),,ASC,Dense)),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=3;y1=1;y2=1;y3=1;y5=1'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Dim[Prod],TREATAS({2024},ZS_Cal[Year]),"v",RANKX(ALLSELECTED(ZS_Dim[Prod]),CALCULATE(SUM(ZS_Fact[Amt])),,DESC)),ZS_Dim[Prod]&"="&[v],";",ZS_Dim[Prod])', 'P1=3;P2=2;P3=1;P4=5;P5=4'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Sup[Sup],TREATAS({"S1"},ZS_Sup[Sup]),"v",RANKX(ALLSELECTED(ZS_Dim[Prod]),CALCULATE(COUNTROWS(ZS_Fact)),,ASC)),ZS_Sup[Sup]&"="&[v],";",ZS_Sup[Sup])', 'S1=6'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Sup[Sup],TREATAS({2024},ZS_Cal[Year]),"v",RANKX(ALLSELECTED(ZS_Dim),CALCULATE(SUM(ZS_Fact[Amt])),,ASC)),ZS_Sup[Sup]&"="&[v],";",ZS_Sup[Sup])', 'S1=6;S2=2'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Sup[Sup],TREATAS({2024},ZS_Cal[Year]),"v",RANKX(ALLSELECTED(ZS_Dim[Cat]),CALCULATE(COUNTROWS(ZS_Fact)),,ASC,Dense)),ZS_Sup[Sup]&"="&[v],";",ZS_Sup[Sup])', 'S1=4;S2=2'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Sup[Sup],TREATAS({2024},ZS_Cal[Year]),"v",RANKX(ALLSELECTED(ZS_Dim[Cat]),CALCULATE(SUM(ZS_Fact[Amt])),,ASC)),ZS_Sup[Sup]&"="&[v],";",ZS_Sup[Sup])', 'S1=4;S2=3'),
    ('ZS', 'CONCATENATEX(SUMMARIZECOLUMNS(ZS_Sup[Sup],TREATAS({2024},ZS_Cal[Year]),"v",RANKX(ALLSELECTED(ZS_Dim[Prod]),CALCULATE(SUM(ZS_Fact[Amt])),,ASC)),ZS_Sup[Sup]&"="&[v],";",ZS_Sup[Sup])', 'S1=6;S2=5'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],"v",RANKX(ALL(ZJ_W),CALCULATE(SUM(ZJ_F[Amt])),,ASC,Dense)),ZJ_B[N]&"="&[v],";",ZJ_B[N])', 'n1=5;n2=5;n3=5;n6=5'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",RANKX(ALL(ZJ_W),CALCULATE(SUM(ZJ_F[Amt])))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=3;x1=2;x2=2;x3=4;x4=2;x5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",RANKX(ALL(ZJ_W),CALCULATE(SUM(ZJ_F[Amt])),,ASC,Dense)),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=2;x1=4;x2=3;x3=1;x4=4;x5=4'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",RANKX(ALL(ZJ_W),CALCULATE(SUM(ZJ_F[Amt])),,DESC,Dense)),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=3;x1=2;x2=2;x3=4;x4=2;x5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",RANKX(ALL(ZJ_W[Y]),CALCULATE(SUM(ZJ_F[Amt])),,ASC)),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=5;x1=5;x2=5;x3=1;x4=5;x5=5'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",RANKX(ALLSELECTED(ZJ_W),CALCULATE(SUM(ZJ_F[Amt])),,ASC)),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=3;x1=5;x2=4;x3=1;x4=5;x5=5'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"j2","j3"},ZJ_U[K]),"v",RANKX(ALL(ZJ_W),CALCULATE(COUNTROWS(ZJ_F)))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', 'x2=1;x3=4'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"j2","j3"},ZJ_U[K]),"v",RANKX(ALL(ZJ_W),CALCULATE(SUM(ZJ_F[Amt])),,DESC)),ZJ_U[X]&"="&[v],";",ZJ_U[X])', 'x2=2;x3=4'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"j2","j3"},ZJ_U[K]),"v",RANKX(ALLSELECTED(ZJ_W[Y]),CALCULATE(SUM(ZJ_F[Amt])),,ASC)),ZJ_U[X]&"="&[v],";",ZJ_U[X])', 'x2=5;x3=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"n1","n6"},ZJ_B[N]),"v",RANKX(ALL(ZJ_W),CALCULATE(COUNTROWS(ZJ_F)))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=3;x1=1;x2=1;x3=4;x4=1;x5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"n1","n6"},ZJ_B[N]),"v",RANKX(ALL(ZJ_W),CALCULATE(SUM(ZJ_F[Amt])),,ASC)),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=3;x1=5;x2=4;x3=1;x4=5;x5=5'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"n1","n6"},ZJ_B[N]),"v",RANKX(ALLSELECTED(ZJ_W),CALCULATE(COUNTROWS(ZJ_F)))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=3;x1=1;x2=1;x3=4;x4=1;x5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"n1","n6"},ZJ_B[N]),"v",RANKX(ALLSELECTED(ZJ_W),CALCULATE(SUM(ZJ_F[Amt])),,ASC)),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=3;x1=5;x2=4;x3=1;x4=5;x5=5'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"n1","n6"},ZJ_B[N]),"v",RANKX(ALLSELECTED(ZJ_W),CALCULATE(SUM(ZJ_F[Amt])),,DESC)),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=3;x1=2;x2=2;x3=4;x4=2;x5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"n1","n6"},ZJ_B[N]),"v",RANKX(ALLSELECTED(ZJ_W[Y]),CALCULATE(COUNTROWS(ZJ_F)),,ASC)),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=5;x1=5;x2=5;x3=1;x4=5;x5=5'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"n1","n6"},ZJ_B[N]),"v",RANKX(VALUES(ZJ_W[Y]),CALCULATE(SUM(ZJ_F[Amt])),,ASC,Dense)),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=2;x1=1;x2=1;x3=1;x4=1;x5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],"v",RANKX(ALL(ZJ_W),CALCULATE(SUM(ZJ_F[Amt])),,DESC)),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=1;y2=2;y3=4;y5=1;y7=4'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],"v",RANKX(ALL(ZJ_W),CALCULATE(SUM(ZJ_F[Amt])),,DESC,Dense)),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=1;y2=2;y3=4;y5=1;y7=4'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],"v",RANKX(ALLSELECTED(ZJ_W),CALCULATE(COUNTROWS(ZJ_F)),,ASC,Dense)),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=4;y2=3;y3=1;y5=3;y7=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],"v",RANKX(ALLSELECTED(ZJ_W),CALCULATE(COUNTROWS(ZJ_F)),,DESC,Dense)),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=1;y2=1;y3=3;y5=1;y7=3'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],"v",RANKX(ALLSELECTED(ZJ_W),CALCULATE(SUM(ZJ_F[Amt])),,DESC,Dense)),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=1;y2=2;y3=4;y5=1;y7=4'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],"v",RANKX(VALUES(ZJ_U[X]),CALCULATE(COUNTROWS(ZJ_F)),,DESC,Dense)),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=1;y2=1;y3=1;y5=1;y7=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],TREATAS({"j2","j3"},ZJ_U[K]),"v",RANKX(ALL(ZJ_W),CALCULATE(COUNTROWS(ZJ_F)),,ASC,Dense)),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=1;y2=3;y3=1;y5=1;y7=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],TREATAS({"j2","j3"},ZJ_U[K]),"v",RANKX(ALL(ZJ_W),CALCULATE(SUM(ZJ_F[Amt])),,ASC,Dense)),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=1;y2=3;y3=1;y5=1;y7=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],TREATAS({"n1","n6"},ZJ_B[N]),"v",RANKX(ALL(ZJ_U[X]),CALCULATE(COUNTROWS(ZJ_F)))),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=1;y2=1;y3=1;y5=1;y7=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],TREATAS({"n1","n6"},ZJ_B[N]),"v",RANKX(ALL(ZJ_W),CALCULATE(COUNTROWS(ZJ_F)),,DESC)),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=1;y2=1;y3=4;y5=1;y7=4'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],TREATAS({"n1","n6"},ZJ_B[N]),"v",RANKX(ALLSELECTED(ZJ_W),CALCULATE(COUNTROWS(ZJ_F)),,DESC)),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=1;y2=1;y3=4;y5=1;y7=4'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],TREATAS({"n1","n6"},ZJ_B[N]),"v",RANKX(ALLSELECTED(ZJ_W),CALCULATE(SUM(ZJ_F[Amt])),,DESC,Dense)),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=1;y2=2;y3=4;y5=1;y7=4'),
]


@pytest.mark.parametrize("model, expression, powerbi", FIXED_CASES)
def test_fixed_ranking_set_answer(model: str, expression: str, powerbi: str) -> None:
    assert m.ours_for(model, expression) == powerbi
