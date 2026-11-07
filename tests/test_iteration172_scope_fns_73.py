"""Task 83 (scope-fns-73): ISINSCOPE, HASONEVALUE and SELECTEDVALUE in SUMMARIZECOLUMNS group rows, on model ZX.

The cases are literal (expression, Power BI answer) pairs on model ZX: every case that was wrong before the fix (28) plus 20 cases that
already matched. The model data is written out here as literals (the plans file is not imported). Answers are compared through
tests.critic3_models.ours_for; numbers compare by float value."""

import math

import pytest

from tests import critic3_models as m

DIM_COLS = [('Item', 'string'), ('Fam', 'string'), ('Tier', 'int64')]

DIM_ROWS = [('I1', 'F3', 1), ('I2', 'F3', 2), ('I3', 'F3', 1), ('I4', 'F2', 2), ('I5', 'F1', 1), ('I6', 'F2', 2), ('I7', 'F3', 2)]

FACT_COLS = [('Id', 'int64'), ('Item', 'string'), ('Dt', 'dateTime'), ('Val', 'double'), ('Units', 'int64')]

FACT_ROWS = [(1, 'I1', (2023, 1, 20), 61.0, 9), (2, 'I6', (2023, 2, 20), 29.0, 9), (3, 'I4', (2024, 5, 19), 74.0, 4), (4, 'I3', (2023, 11, 27), 24.0, 1), (5, 'I1', (2024, 8, 19), 78.0, 9), (6, 'I1', (2023, 8, 22), 85.0, 9), (7, None, (2023, 8, 25), 7.0, 0), (8, 'I1', (2024, 6, 13), 66.0, 9), (9, 'I5', (2024, 3, 5), 29.0, 0), (10, 'I7', (2024, 4, 14), 7.0, 8), (11, 'I5', (2023, 11, 12), 76.0, 9), (12, 'I1', (2024, 1, 12), 58.0, 0), (13, 'I2', (2024, 3, 9), 5.0, 0), (14, 'I7', (2024, 5, 14), 33.0, 4), (15, 'I3', (2024, 3, 21), 85.0, 7), (16, 'I6', (2023, 1, 17), -6.0, 3), (17, 'I6', (2023, 12, 7), 18.0, 4), (18, 'I6', (2023, 2, 20), 53.0, 6), (19, 'I4', (2023, 3, 7), 78.0, 0), (20, 'I3', (2023, 4, 11), 18.0, 4), (21, 'I3', (2023, 4, 19), 75.0, 5), (22, 'I7', (2024, 5, 26), 38.0, 3)]

RELS = [('ZX_r1', 'ZX_Fact', 'Item', 'ZX_Dim', 'Item', True, False, 'many', 'one'), ('ZX_r2', 'ZX_Fact', 'Dt', 'ZX_Cal', 'Date', True, False, 'many', 'one')]

m.SPEC['ZX'] = {'tables': {'ZX_Dim': (DIM_COLS, DIM_ROWS), 'ZX_Fact': (FACT_COLS, FACT_ROWS), 'ZX_Cal': (m.CAL_COLS, None)}, 'rels': RELS}


CASES = [
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],"v",ISINSCOPE(ZX_Dim[Item])+0),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', '=1;I1=1;I2=1;I3=1;I4=1;I5=1;I6=1;I7=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",ISINSCOPE(ZX_Dim[Item])+0),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=1;I2=1;I3=1;I5=1;I7=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({2024},ZX_Cal[Year]),"v",ISINSCOPE(ZX_Dim[Item])+0),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', '=1;I1=1;I2=1;I3=1;I4=1;I5=1;I6=1;I7=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],"v",HASONEVALUE(ZX_Dim[Fam])+0),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', '=1;I1=1;I2=1;I3=1;I4=1;I5=1;I6=1;I7=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",HASONEVALUE(ZX_Dim[Fam])+0),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=1;I2=1;I3=1;I5=1;I7=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({2024},ZX_Cal[Year]),"v",HASONEVALUE(ZX_Dim[Fam])+0),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', '=1;I1=1;I2=1;I3=1;I4=1;I5=1;I6=1;I7=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],"v",SELECTEDVALUE(ZX_Dim[Fam],"m")),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=F3;I2=F3;I3=F3;I4=F2;I5=F1;I6=F2;I7=F3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SELECTEDVALUE(ZX_Dim[Fam],"m")),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=F3;I2=F3;I3=F3;I5=F1;I7=F3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({2024},ZX_Cal[Year]),"v",SELECTEDVALUE(ZX_Dim[Fam],"m")),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=F3;I2=F3;I3=F3;I4=F2;I5=F1;I6=F2;I7=F3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],"v",IF(ISINSCOPE(ZX_Dim[Item]),RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units]))),-1)),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', '=7;I1=1;I2=7;I3=3;I4=6;I5=5;I6=2;I7=4'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",IF(ISINSCOPE(ZX_Dim[Item]),RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units]))),-1)),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', 'I1=1;I2=5;I3=2;I5=4;I7=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Item],TREATAS({2024},ZX_Cal[Year]),"v",IF(ISINSCOPE(ZX_Dim[Item]),RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units]))),-1)),ZX_Dim[Item]&"="&[v],";",ZX_Dim[Item])', '=5;I1=1;I2=5;I3=3;I4=4;I5=5;I6=5;I7=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],"v",ISINSCOPE(ZX_Dim[Item])+0),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', '=0;F1=0;F2=0;F3=0'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",ISINSCOPE(ZX_Dim[Item])+0),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=0;F3=0'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({2024},ZX_Cal[Year]),"v",ISINSCOPE(ZX_Dim[Item])+0),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', '=0;F1=0;F2=0;F3=0'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],"v",HASONEVALUE(ZX_Dim[Fam])+0),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', '=1;F1=1;F2=1;F3=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",HASONEVALUE(ZX_Dim[Fam])+0),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=1;F3=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({2024},ZX_Cal[Year]),"v",HASONEVALUE(ZX_Dim[Fam])+0),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', '=1;F1=1;F2=1;F3=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],"v",SELECTEDVALUE(ZX_Dim[Fam],"m")),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=F1;F2=F2;F3=F3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SELECTEDVALUE(ZX_Dim[Fam],"m")),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=F1;F3=F3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({2024},ZX_Cal[Year]),"v",SELECTEDVALUE(ZX_Dim[Fam],"m")),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=F1;F2=F2;F3=F3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],"v",IF(ISINSCOPE(ZX_Dim[Item]),RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units]))),-1)),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', '=-1;F1=-1;F2=-1;F3=-1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",IF(ISINSCOPE(ZX_Dim[Item]),RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units]))),-1)),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', 'F1=-1;F3=-1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],TREATAS({2024},ZX_Cal[Year]),"v",IF(ISINSCOPE(ZX_Dim[Item]),RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units]))),-1)),ZX_Dim[Fam]&"="&[v],";",ZX_Dim[Fam])', '=-1;F1=-1;F2=-1;F3=-1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Item],"v",ISINSCOPE(ZX_Dim[Item])+0),ZX_Dim[Fam]&"|"&ZX_Dim[Item]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Item])', '|=1;F1|I5=1;F2|I4=1;F2|I6=1;F3|I1=1;F3|I2=1;F3|I3=1;F3|I7=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",ISINSCOPE(ZX_Dim[Item])+0),ZX_Dim[Fam]&"|"&ZX_Dim[Item]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Item])', 'F1|I5=1;F3|I1=1;F3|I2=1;F3|I3=1;F3|I7=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Item],TREATAS({2024},ZX_Cal[Year]),"v",ISINSCOPE(ZX_Dim[Item])+0),ZX_Dim[Fam]&"|"&ZX_Dim[Item]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Item])', '|=1;F1|I5=1;F2|I4=1;F2|I6=1;F3|I1=1;F3|I2=1;F3|I3=1;F3|I7=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Item],"v",HASONEVALUE(ZX_Dim[Fam])+0),ZX_Dim[Fam]&"|"&ZX_Dim[Item]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Item])', '|=1;F1|I5=1;F2|I4=1;F2|I6=1;F3|I1=1;F3|I2=1;F3|I3=1;F3|I7=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",HASONEVALUE(ZX_Dim[Fam])+0),ZX_Dim[Fam]&"|"&ZX_Dim[Item]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Item])', 'F1|I5=1;F3|I1=1;F3|I2=1;F3|I3=1;F3|I7=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Item],TREATAS({2024},ZX_Cal[Year]),"v",HASONEVALUE(ZX_Dim[Fam])+0),ZX_Dim[Fam]&"|"&ZX_Dim[Item]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Item])', '|=1;F1|I5=1;F2|I4=1;F2|I6=1;F3|I1=1;F3|I2=1;F3|I3=1;F3|I7=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Item],"v",SELECTEDVALUE(ZX_Dim[Fam],"m")),ZX_Dim[Fam]&"|"&ZX_Dim[Item]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Item])', 'F1|I5=F1;F2|I4=F2;F2|I6=F2;F3|I1=F3;F3|I2=F3;F3|I3=F3;F3|I7=F3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SELECTEDVALUE(ZX_Dim[Fam],"m")),ZX_Dim[Fam]&"|"&ZX_Dim[Item]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Item])', 'F1|I5=F1;F3|I1=F3;F3|I2=F3;F3|I3=F3;F3|I7=F3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Item],TREATAS({2024},ZX_Cal[Year]),"v",SELECTEDVALUE(ZX_Dim[Fam],"m")),ZX_Dim[Fam]&"|"&ZX_Dim[Item]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Item])', 'F1|I5=F1;F2|I4=F2;F2|I6=F2;F3|I1=F3;F3|I2=F3;F3|I3=F3;F3|I7=F3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Item],"v",IF(ISINSCOPE(ZX_Dim[Item]),RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units]))),-1)),ZX_Dim[Fam]&"|"&ZX_Dim[Item]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Item])', '|=1;F1|I5=1;F2|I4=2;F2|I6=1;F3|I1=1;F3|I2=4;F3|I3=2;F3|I7=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Item],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",IF(ISINSCOPE(ZX_Dim[Item]),RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units]))),-1)),ZX_Dim[Fam]&"|"&ZX_Dim[Item]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Item])', 'F1|I5=1;F3|I1=1;F3|I2=4;F3|I3=2;F3|I7=3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Fam],ZX_Dim[Item],TREATAS({2024},ZX_Cal[Year]),"v",IF(ISINSCOPE(ZX_Dim[Item]),RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units]))),-1)),ZX_Dim[Fam]&"|"&ZX_Dim[Item]&"="&[v],";",ZX_Dim[Fam]&"|"&ZX_Dim[Item])', '|=1;F1|I5=1;F2|I4=1;F2|I6=2;F3|I1=1;F3|I2=4;F3|I3=3;F3|I7=2'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],"v",ISINSCOPE(ZX_Dim[Item])+0),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '|2023=0;|2024=0;1|2023=0;1|2024=0;2|2023=0;2|2024=0'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",ISINSCOPE(ZX_Dim[Item])+0),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=0;1|2024=0;2|2023=0;2|2024=0'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({2024},ZX_Cal[Year]),"v",ISINSCOPE(ZX_Dim[Item])+0),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '|2024=0;1|2024=0;2|2024=0'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],"v",HASONEVALUE(ZX_Dim[Fam])+0),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '|2023=1;|2024=1;1|2023=0;1|2024=0;2|2023=0;2|2024=0'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",HASONEVALUE(ZX_Dim[Fam])+0),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=0;1|2024=0;2|2023=1;2|2024=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({2024},ZX_Cal[Year]),"v",HASONEVALUE(ZX_Dim[Fam])+0),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '|2024=1;1|2024=0;2|2024=0'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],"v",SELECTEDVALUE(ZX_Dim[Fam],"m")),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=m;1|2024=m;2|2023=m;2|2024=m'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",SELECTEDVALUE(ZX_Dim[Fam],"m")),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=m;1|2024=m;2|2023=F3;2|2024=F3'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({2024},ZX_Cal[Year]),"v",SELECTEDVALUE(ZX_Dim[Fam],"m")),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2024=m;2|2024=m'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],"v",IF(ISINSCOPE(ZX_Dim[Item]),RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units]))),-1)),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '|2023=-1;|2024=-1;1|2023=-1;1|2024=-1;2|2023=-1;2|2024=-1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({"F1","F3"},ZX_Dim[Fam]),"v",IF(ISINSCOPE(ZX_Dim[Item]),RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units]))),-1)),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '1|2023=-1;1|2024=-1;2|2023=-1;2|2024=-1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZX_Dim[Tier],ZX_Cal[Year],TREATAS({2024},ZX_Cal[Year]),"v",IF(ISINSCOPE(ZX_Dim[Item]),RANKX(ALLSELECTED(ZX_Dim[Item]),CALCULATE(SUM(ZX_Fact[Units]))),-1)),ZX_Dim[Tier]&"|"&ZX_Cal[Year]&"="&[v],";",ZX_Dim[Tier]&"|"&ZX_Cal[Year])', '|2024=-1;1|2024=-1;2|2024=-1'),
]


def _same(ours: str, powerbi: str) -> bool:
    if ours == powerbi:
        return True
    try:
        return math.isclose(float(ours), float(powerbi), rel_tol=1e-9, abs_tol=0.0)
    except ValueError:
        return False


PARAMS = [pytest.param(expr, pb, id=f"case{index}") for index, (expr, pb) in enumerate(CASES)]


@pytest.mark.parametrize("expression, powerbi", PARAMS)
def test_scope_and_one_value_functions_in_summarizecolumns_match_power_bi(expression: str, powerbi: str) -> None:
    assert _same(m.ours_for("ZX", expression), powerbi)


# Task 83 (live Power BI, model ZO of tests.critic3_models): CALCULATE(ISINSCOPE) in a SUMMARIZE row, HASONEFILTER on the blank group row,
# and the unknown member last in VALUES. Each pair is (expression, Power BI answer).
ZO_CASES = [
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZO_Fact,ZO_Dim[Prod]),"v",CALCULATE(ISINSCOPE(ZO_Dim[Prod]))+0),ZO_Dim[Prod]&"="&[v],";",ZO_Dim[Prod])', '=1;P1=1;P2=1;P3=1;P4=1;P5=1'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZO_Fact,ZO_Dim[Cat],ZO_Dim[Prod]),"v",CALCULATE(ISINSCOPE(ZO_Dim[Prod]))+0),ZO_Dim[Cat]&"|"&ZO_Dim[Prod]&"="&[v],";",ZO_Dim[Cat]&"|"&ZO_Dim[Prod])', '|=1;A|P1=1;A|P2=1;B|P3=1;B|P4=1;C|P5=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZO_Dim[Prod],"v",HASONEFILTER(ZO_Dim[Prod])+0,"s",COUNTROWS(ZO_Fact)),ZO_Dim[Prod]&"="&[v],";",ZO_Dim[Prod])', '=1;P1=1;P2=1;P3=1;P4=1;P5=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZO_Dim[Cat],ZO_Dim[Prod],"v",HASONEFILTER(ZO_Dim[Prod])+0,"s",COUNTROWS(ZO_Fact)),ZO_Dim[Cat]&"|"&ZO_Dim[Prod]&"="&[v],";",ZO_Dim[Cat]&"|"&ZO_Dim[Prod])', '|=1;A|P1=1;A|P2=1;B|P3=1;B|P4=1;C|P5=1'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZO_Fact,ZO_Dim[Prod]),"v",CONCATENATEX(VALUES(ZO_Dim[Cat]),ZO_Dim[Cat]&"",",")),ZO_Dim[Prod]&"="&[v],";",ZO_Dim[Prod])', '=A,B,C,;P1=A,B,C,;P2=A,B,C,;P3=A,B,C,;P4=A,B,C,;P5=A,B,C,'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZO_Fact,ZO_Dim[Cat]),"v",CONCATENATEX(VALUES(ZO_Dim[Cat]),ZO_Dim[Cat]&"",",")),ZO_Dim[Cat]&"="&[v],";",ZO_Dim[Cat])', '=A,B,C,;A=A,B,C,;B=A,B,C,;C=A,B,C,'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZO_Fact,ZO_Dim[Cat],ZO_Dim[Prod]),"v",CONCATENATEX(VALUES(ZO_Dim[Cat]),ZO_Dim[Cat]&"",",")),ZO_Dim[Cat]&"|"&ZO_Dim[Prod]&"="&[v],";",ZO_Dim[Cat]&"|"&ZO_Dim[Prod])', '|=A,B,C,;A|P1=A,B,C,;A|P2=A,B,C,;B|P3=A,B,C,;B|P4=A,B,C,;C|P5=A,B,C,'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZO_Fact,ZO_Dim[Cat],ZO_Cal[Year]),"v",CONCATENATEX(VALUES(ZO_Dim[Cat]),ZO_Dim[Cat]&"",",")),ZO_Dim[Cat]&"|"&ZO_Cal[Year]&"="&[v],";",ZO_Dim[Cat]&"|"&ZO_Cal[Year])', '|2024=A,B,C,;A|=A,B,C,;A|2023=A,B,C,;A|2024=A,B,C,;B|=A,B,C,;B|2024=A,B,C,;C|2024=A,B,C,'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZO_Fact,ZO_Dim[Prod]),"v",ISINSCOPE(ZO_Dim[Prod])+0),ZO_Dim[Prod]&"="&[v],";",ZO_Dim[Prod])', '=0;P1=0;P2=0;P3=0;P4=0;P5=0'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZO_Fact,ZO_Dim[Cat],ZO_Dim[Prod]),"v",ISINSCOPE(ZO_Dim[Prod])+0),ZO_Dim[Cat]&"|"&ZO_Dim[Prod]&"="&[v],";",ZO_Dim[Cat]&"|"&ZO_Dim[Prod])', '|=0;A|P1=0;A|P2=0;B|P3=0;B|P4=0;C|P5=0'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZO_Fact,ZO_Dim[Prod]),"v",HASONEFILTER(ZO_Dim[Prod])+0),ZO_Dim[Prod]&"="&[v],";",ZO_Dim[Prod])', '=0;P1=0;P2=0;P3=0;P4=0;P5=0'),
    ('CONCATENATEX(ADDCOLUMNS(SUMMARIZE(ZO_Fact,ZO_Dim[Cat],ZO_Dim[Prod]),"v",HASONEFILTER(ZO_Dim[Prod])+0),ZO_Dim[Cat]&"|"&ZO_Dim[Prod]&"="&[v],";",ZO_Dim[Cat]&"|"&ZO_Dim[Prod])', '|=0;A|P1=0;A|P2=0;B|P3=0;B|P4=0;C|P5=0'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZO_Dim[Prod],"v",CALCULATE(ISINSCOPE(ZO_Dim[Prod]))+0,"s",COUNTROWS(ZO_Fact)),ZO_Dim[Prod]&"="&[v],";",ZO_Dim[Prod])', '=1;P1=1;P2=1;P3=1;P4=1;P5=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZO_Dim[Cat],ZO_Dim[Prod],"v",CALCULATE(ISINSCOPE(ZO_Dim[Prod]))+0,"s",COUNTROWS(ZO_Fact)),ZO_Dim[Cat]&"|"&ZO_Dim[Prod]&"="&[v],";",ZO_Dim[Cat]&"|"&ZO_Dim[Prod])', '|=1;A|P1=1;A|P2=1;B|P3=1;B|P4=1;C|P5=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZO_Dim[Prod],"v",ISINSCOPE(ZO_Dim[Prod])+0,"s",COUNTROWS(ZO_Fact)),ZO_Dim[Prod]&"="&[v],";",ZO_Dim[Prod])', '=1;P1=1;P2=1;P3=1;P4=1;P5=1'),
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZO_Dim[Cat],"v",HASONEFILTER(ZO_Dim[Prod])+0,"s",COUNTROWS(ZO_Fact)),ZO_Dim[Cat]&"="&[v],";",ZO_Dim[Cat])', '=0;A=0;B=0;C=0'),
]


ZO_PARAMS = [pytest.param(expr, pb, id=f"zo{index}") for index, (expr, pb) in enumerate(ZO_CASES)]


@pytest.mark.parametrize("expression, powerbi", ZO_PARAMS)
def test_scope_functions_and_unknown_member_order_on_model_zo(expression: str, powerbi: str) -> None:
    assert _same(m.ours_for("ZO", expression), powerbi)

@pytest.mark.parametrize("expression, powerbi", [
 ('CONCATENATEX(VALUES(ZO_Dim[Cat]),ZO_Dim[Cat]&"",",")', 'A,B,C,'),
 ('CONCATENATEX(ALL(ZO_Dim[Cat]),ZO_Dim[Cat]&"",",")', 'A,B,C,'),
])
def test_unknown_member_comes_last_in_unordered_values_and_all(expression: str, powerbi: str) -> None:
    assert m.ours_for("ZO", expression) == powerbi
