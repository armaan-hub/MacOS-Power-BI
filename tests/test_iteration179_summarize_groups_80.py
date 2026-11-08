"""Iteration 179 (Task 90, summarize-groups-80): SUMMARIZE / GROUPBY over a fact table grouped by related columns.

Part A: the blank group of SUMMARIZE over a fact grouped through a one-to-one table is the fact rows of the one-side rows with no
partner (ZM U k4, ZJ U j4); an unreachable column in SUMMARIZE is an error at plan time (ZM: ERR). Part B: GROUPBY over a column
of a table on the one side of the grouped table groups the rows by that related value (the unknown member is BLANK).
Expected values are live Power BI answers (never saved to the parity files). Scratch models: ZM in tests/critic3_models.py,
ZJ in docs/plans/2026-11-08-rankx-sets-75-model.py. Compare numerically ("147.0" equals "147"); an "ERR" answer must be a refusal."""
import importlib.util
from pathlib import Path

import pytest

from tests import critic3_models as m

_MODEL_FILE = Path(__file__).resolve().parent.parent / "docs" / "plans" / "2026-11-08-rankx-sets-75-model.py"
_spec = importlib.util.spec_from_file_location("summarize_groups_80_model", _MODEL_FILE)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

FIXED = [
    ('ZM', 'CONCATENATEX(GROUPBY(ZM_F2,ZM_W[Y]),ZM_W[Y],",",ZM_W[Y])', ',y1,y2'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],"v",CONCATENATEX(GROUPBY(ZM_F2,ZM_W[Y]),ZM_W[Y],",",ZM_W[Y])),ZM_B[N]&"="&[v],";",ZM_B[N])', 'n1=,y1,y2;n1b=,y1,y2;n2=,y1,y2;n5=,y1,y2'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],"v",COUNTROWS(GROUPBY(ZM_F,ZM_U[X]))),ZM_B[N]&"="&[v],";",ZM_B[N])', 'n1=5;n1b=5;n2=5;n5=5'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],"v",SUMX(GROUPBY(ZM_F,ZM_W[Y],"s",SUMX(CURRENTGROUP(),ZM_F[Amt])),[s])),ZM_B[N]&"="&[v],";",ZM_B[N])', 'n1=63;n1b=63;n2=63;n5=63'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],"v",SUMX(SUMMARIZE(ZM_F2,ZM_W[Y],"s",SUM(ZM_F[Amt])),[s])),ZM_B[N]&"="&[v],";",ZM_B[N])', 'n1=23;n1b=23;n2=23;n5=23'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],TREATAS({"m1"},ZM_U[K]),"v",CONCATENATEX(GROUPBY(ZM_F2,ZM_W[Y]),ZM_W[Y],",",ZM_W[Y])),ZM_B[N]&"="&[v],";",ZM_B[N])', 'BLANK'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],TREATAS({"m1"},ZM_U[K]),"v",COUNTROWS(GROUPBY(ZM_F,ZM_U[X]))),ZM_B[N]&"="&[v],";",ZM_B[N])', 'BLANK'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],TREATAS({"m1"},ZM_U[K]),"v",SUMX(GROUPBY(ZM_F,ZM_W[Y],"s",SUMX(CURRENTGROUP(),ZM_F[Amt])),[s])),ZM_B[N]&"="&[v],";",ZM_B[N])', 'BLANK'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],"v",CONCATENATEX(GROUPBY(ZM_F2,ZM_W[Y]),ZM_W[Y],",",ZM_W[Y])),ZM_U[X]&"="&[v],";",ZM_U[X])', 'x1=y1;x2=y2;x4='),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],"v",COUNTROWS(GROUPBY(ZM_F,ZM_U[X]))),ZM_U[X]&"="&[v],";",ZM_U[X])', '=1;x1=1;x2=1;x3=1;x4=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],"v",SUMX(GROUPBY(ZM_F,ZM_W[Y],"s",SUMX(CURRENTGROUP(),ZM_F[Amt])),[s])),ZM_U[X]&"="&[v],";",ZM_U[X])', '=32;x1=3;x2=4;x3=8;x4=16'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],TREATAS({"m1"},ZM_U[K]),"v",COUNTROWS(SUMMARIZE(ZM_A,ZM_B[N]))),ZM_U[X]&"="&[v],";",ZM_U[X])', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 95) The column \'N\' specified in the \'SUMMARIZE\' function was not found in the input table."'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],"v",CONCATENATEX(GROUPBY(ZM_F2,ZM_W[Y]),ZM_W[Y],",",ZM_W[Y])),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=;y1=y1;y2=y2'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],"v",COUNTROWS(GROUPBY(ZM_F,ZM_U[X]))),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=2;y1=1;y2=1;y3=1'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],"v",SUMX(GROUPBY(ZM_F,ZM_W[Y],"s",SUMX(CURRENTGROUP(),ZM_F[Amt])),[s])),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=48;y1=3;y2=4;y3=8'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],"v",SUMX(SUMMARIZE(ZM_F2,ZM_W[Y],"s",SUM(ZM_F[Amt])),[s])),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=16;y1=3;y2=4'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"m1"},ZM_U[K]),"v",CONCATENATEX(GROUPBY(ZM_F2,ZM_W[Y]),ZM_W[Y],",",ZM_W[Y])),ZM_W[Y]&"="&[v],";",ZM_W[Y])', 'BLANK'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"m1"},ZM_U[K]),"v",COUNTROWS(GROUPBY(ZM_F,ZM_U[X]))),ZM_W[Y]&"="&[v],";",ZM_W[Y])', 'BLANK'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"m1"},ZM_U[K]),"v",SUMX(GROUPBY(ZM_F,ZM_W[Y],"s",SUMX(CURRENTGROUP(),ZM_F[Amt])),[s])),ZM_W[Y]&"="&[v],";",ZM_W[Y])', 'BLANK'),
    ('ZM', 'COUNTROWS(GROUPBY(ZM_F,ZM_U[X]))', '5'),
    ('ZM', 'SUMX(GROUPBY(ZM_F,ZM_W[Y],"s",SUMX(CURRENTGROUP(),ZM_F[Amt])),[s])', '63'),
    ('ZM', 'SUMX(SUMMARIZE(ZM_F2,ZM_W[Y],"s",SUM(ZM_F[Amt])),[s])', '23'),
    ('ZJ', 'CONCATENATEX(GROUPBY(ZJ_F2,ZJ_W[Y]),ZJ_W[Y],",",ZJ_W[Y])', ',y2'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],"v",CONCATENATEX(GROUPBY(ZJ_F2,ZJ_W[Y]),ZJ_W[Y],",",ZJ_W[Y])),ZJ_B[N]&"="&[v],";",ZJ_B[N])', 'n1=,y2;n2=,y2;n3=,y2;n6=,y2'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],"v",COUNTROWS(GROUPBY(ZJ_F,ZJ_U[X]))),ZJ_B[N]&"="&[v],";",ZJ_B[N])', 'n1=5;n2=5;n3=5;n6=5'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],"v",SUMX(GROUPBY(ZJ_F,ZJ_W[Y],"s",SUMX(CURRENTGROUP(),ZJ_F[Amt])),[s])),ZJ_B[N]&"="&[v],";",ZJ_B[N])', 'n1=255;n2=255;n3=255;n6=255'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],"v",SUMX(SUMMARIZE(ZJ_F2,ZJ_W[Y],"s",SUM(ZJ_F[Amt])),[s])),ZJ_B[N]&"="&[v],";",ZJ_B[N])', 'n1=107;n2=107;n3=107;n6=107'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],TREATAS({"j1"},ZJ_U[K]),"v",CONCATENATEX(GROUPBY(ZJ_F2,ZJ_W[Y]),ZJ_W[Y],",",ZJ_W[Y])),ZJ_B[N]&"="&[v],";",ZJ_B[N])', 'BLANK'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],TREATAS({"j1"},ZJ_U[K]),"v",COUNTROWS(GROUPBY(ZJ_F,ZJ_U[X]))),ZJ_B[N]&"="&[v],";",ZJ_B[N])', 'n1=1;n2=1;n3=1;n6=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],TREATAS({"j1"},ZJ_U[K]),"v",SUMX(GROUPBY(ZJ_F,ZJ_W[Y],"s",SUMX(CURRENTGROUP(),ZJ_F[Amt])),[s])),ZJ_B[N]&"="&[v],";",ZJ_B[N])', 'n1=47;n2=47;n3=47;n6=47'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",CONCATENATEX(GROUPBY(ZJ_F2,ZJ_W[Y]),ZJ_W[Y],",",ZJ_W[Y])),ZJ_U[X]&"="&[v],";",ZJ_U[X])', 'x2=y2;x4='),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",COUNTROWS(GROUPBY(ZJ_F,ZJ_U[X]))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=1;x1=1;x2=1;x4=1;x5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",SUMX(GROUPBY(ZJ_F,ZJ_W[Y],"s",SUMX(CURRENTGROUP(),ZJ_F[Amt])),[s])),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=34;x1=47;x2=46;x4=61;x5=67'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"j1"},ZJ_U[K]),"v",CONCATENATEX(GROUPBY(ZJ_F2,ZJ_W[Y]),ZJ_W[Y],",",ZJ_W[Y])),ZJ_U[X]&"="&[v],";",ZJ_U[X])', 'BLANK'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"j1"},ZJ_U[K]),"v",COUNTROWS(GROUPBY(ZJ_F,ZJ_U[X]))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', 'x1=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"j1"},ZJ_U[K]),"v",SUMX(GROUPBY(ZJ_F,ZJ_W[Y],"s",SUMX(CURRENTGROUP(),ZJ_F[Amt])),[s])),ZJ_U[X]&"="&[v],";",ZJ_U[X])', 'x1=47'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],"v",CONCATENATEX(GROUPBY(ZJ_F2,ZJ_W[Y]),ZJ_W[Y],",",ZJ_W[Y])),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=;y2=y2'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],"v",COUNTROWS(GROUPBY(ZJ_F,ZJ_U[X]))),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=3;y2=1;y5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],"v",SUMX(GROUPBY(ZJ_F,ZJ_W[Y],"s",SUMX(CURRENTGROUP(),ZJ_F[Amt])),[s])),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=142;y2=46;y5=67'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],"v",SUMX(SUMMARIZE(ZJ_F2,ZJ_W[Y],"s",SUM(ZJ_F[Amt])),[s])),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=61;y2=46'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],TREATAS({"j1"},ZJ_U[K]),"v",CONCATENATEX(GROUPBY(ZJ_F2,ZJ_W[Y]),ZJ_W[Y],",",ZJ_W[Y])),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', 'BLANK'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],TREATAS({"j1"},ZJ_U[K]),"v",COUNTROWS(GROUPBY(ZJ_F,ZJ_U[X]))),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],TREATAS({"j1"},ZJ_U[K]),"v",SUMX(GROUPBY(ZJ_F,ZJ_W[Y],"s",SUMX(CURRENTGROUP(),ZJ_F[Amt])),[s])),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=47'),
    ('ZJ', 'COUNTROWS(GROUPBY(ZJ_F,ZJ_U[X]))', '5'),
    ('ZJ', 'SUMX(GROUPBY(ZJ_F,ZJ_W[Y],"s",SUMX(CURRENTGROUP(),ZJ_F[Amt])),[s])', '255'),
    ('ZJ', 'SUMX(SUMMARIZE(ZJ_F2,ZJ_W[Y],"s",SUM(ZJ_F[Amt])),[s])', '107'),
]

ALREADY_MATCHING = [
    ('ZM', 'CONCATENATEX(SUMMARIZE(ZM_F,ZM_U[X]),ZM_U[X],",",ZM_U[X])', ',x1,x2,x3,x4'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],"v",COUNTROWS(SUMMARIZE(ZM_F,ZM_U[X],ZM_W[Y]))),ZM_B[N]&"="&[v],";",ZM_B[N])', 'n1=5;n1b=5;n2=5;n5=5'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_B[N],TREATAS({"m1"},ZM_U[K]),"v",COUNTROWS(SUMMARIZE(ZM_F,ROLLUP(ZM_U[X],ZM_W[Y])))),ZM_B[N]&"="&[v],";",ZM_B[N])', 'BLANK'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],"v",CONCATENATEX(SUMMARIZE(ZM_F,ZM_U[X]),ZM_U[X],",",ZM_U[X])),ZM_U[X]&"="&[v],";",ZM_U[X])', '=;x1=x1;x2=x2;x3=x3;x4=x4'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],"v",SUMX(SUMMARIZE(ZM_F,ROLLUP(ZM_U[X]),"s",SUM(ZM_F[Amt])),[s])),ZM_U[X]&"="&[v],";",ZM_U[X])', '=64;x1=6;x2=8;x3=16;x4=32'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],TREATAS({"m1"},ZM_U[K]),"v",COUNTROWS(GROUPBY(ZM_F,ZM_U[X]))),ZM_U[X]&"="&[v],";",ZM_U[X])', 'BLANK'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_U[X],TREATAS({"m1"},ZM_U[K]),"v",SUMX(SUMMARIZE(ZM_F,ROLLUP(ZM_U[X]),"s",SUM(ZM_F[Amt])),[s])),ZM_U[X]&"="&[v],";",ZM_U[X])', 'BLANK'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],"v",COUNTROWS(SUMMARIZE(ZM_F,ROLLUP(ZM_U[X],ZM_W[Y])))),ZM_W[Y]&"="&[v],";",ZM_W[Y])', '=3;y1=3;y2=3;y3=3'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"m1"},ZM_U[K]),"v",COUNTROWS(SUMMARIZE(ZM_A,ZM_B[N]))),ZM_W[Y]&"="&[v],";",ZM_W[Y])', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 95) The column \'N\' specified in the \'SUMMARIZE\' function was not found in the input table."'),
    ('ZM', 'CONCATENATEX(SUMMARIZECOLUMNS(ZM_W[Y],TREATAS({"m1"},ZM_U[K]),"v",SUMX(SUMMARIZE(ZM_F2,ZM_W[Y],"s",SUM(ZM_F[Amt])),[s])),ZM_W[Y]&"="&[v],";",ZM_W[Y])', 'BLANK'),
    ('ZM', 'SUMX(SUMMARIZE(ZM_F,ROLLUP(ZM_U[X]),"s",SUM(ZM_F[Amt])),[s])', '126'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],"v",COUNTROWS(SUMMARIZE(ZJ_F,ROLLUP(ZJ_U[X],ZJ_W[Y])))),ZJ_B[N]&"="&[v],";",ZJ_B[N])', 'n1=3;n2=3;n3=3;n6=3'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],TREATAS({"j1"},ZJ_U[K]),"v",COUNTROWS(SUMMARIZE(ZJ_A,ZJ_B[N]))),ZJ_B[N]&"="&[v],";",ZJ_B[N])', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 95) The column \'N\' specified in the \'SUMMARIZE\' function was not found in the input table."'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_B[N],TREATAS({"j1"},ZJ_U[K]),"v",SUMX(SUMMARIZE(ZJ_F2,ZJ_W[Y],"s",SUM(ZJ_F[Amt])),[s])),ZJ_B[N]&"="&[v],";",ZJ_B[N])', 'BLANK'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],"v",COUNTROWS(SUMMARIZE(ZJ_F,ZJ_U[X],ZJ_W[Y]))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', '=1;x1=1;x2=1;x4=1;x5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"j1"},ZJ_U[K]),"v",COUNTROWS(SUMMARIZE(ZJ_A,ZJ_B[N]))),ZJ_U[X]&"="&[v],";",ZJ_U[X])', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 95) The column \'N\' specified in the \'SUMMARIZE\' function was not found in the input table."'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_U[X],TREATAS({"j1"},ZJ_U[K]),"v",SUMX(SUMMARIZE(ZJ_F2,ZJ_W[Y],"s",SUM(ZJ_F[Amt])),[s])),ZJ_U[X]&"="&[v],";",ZJ_U[X])', 'BLANK'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],"v",COUNTROWS(SUMMARIZE(ZJ_F,ZJ_U[X],ZJ_W[Y]))),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=3;y2=1;y5=1'),
    ('ZJ', 'CONCATENATEX(SUMMARIZECOLUMNS(ZJ_W[Y],TREATAS({"j1"},ZJ_U[K]),"v",COUNTROWS(SUMMARIZE(ZJ_F,ROLLUP(ZJ_U[X],ZJ_W[Y])))),ZJ_W[Y]&"="&[v],";",ZJ_W[Y])', '=3'),
    ('ZJ', 'COUNTROWS(SUMMARIZE(ZJ_A,ZJ_B[N]))', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 29) The column \'N\' specified in the \'SUMMARIZE\' function was not found in the input table."'),
]


def _same(ours, expected):
    """Numeric-tolerant compare: "147.0" equals "147"; name=value lists compare key by key."""
    ours, expected = ours.strip(), expected.strip()
    if ours == expected:
        return True
    try:
        return float(ours) == float(expected)
    except ValueError:
        pass
    if ";" in ours and ";" in expected:
        a = dict(p.split("=", 1) for p in ours.split(";") if "=" in p)
        b = dict(p.split("=", 1) for p in expected.split(";") if "=" in p)
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    return False


def _check(model, expression, expected):
    ours = m.ours_for(model, expression)
    if expected.startswith("ERR"):
        assert ours.startswith("LOCAL-REJECT"), ours  # Power BI raised an error: ours must refuse, never a value
        return
    assert not ours.startswith("LOCAL-"), ours
    assert _same(ours, expected), (ours, expected)


@pytest.mark.parametrize("model, expression, expected", FIXED)
def test_fixed_item_matches_power_bi(model, expression, expected):
    _check(model, expression, expected)


@pytest.mark.parametrize("model, expression, expected", ALREADY_MATCHING)
def test_already_matching_item_still_matches(model, expression, expected):
    _check(model, expression, expected)
