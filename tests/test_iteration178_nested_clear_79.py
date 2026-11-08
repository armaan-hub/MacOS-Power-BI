"""Iteration 178 (Task 89, nested-clear-79): ALLNOBLANKROW(T) / ALLNOBLANKROW(T[c]) inside a CALCULATE under a table filter with orphan keys.
ALLNOBLANKROW removes the blank member a one-to-one partner of T takes from T (not listed); the partner rows stay for the facts.
Scratch model ZH is defined in docs/plans/2026-11-08-orphan-filter-78-model.py; expected values are the live Power BI answers
(never saved to the parity files). Compare numerically ("147.0" equals "147")."""
import importlib.util
from pathlib import Path

import pytest

from tests import critic3_models as m

_MODEL_FILE = Path(__file__).resolve().parent.parent / "docs" / "plans" / "2026-11-08-orphan-filter-78-model.py"
_spec = importlib.util.spec_from_file_location("nested_clear_79_model", _MODEL_FILE)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)


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


CASES = [
    ('CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[K])),ALLNOBLANKROW(ZH_U)),ZH_F2)',
     '3'),  # fixed (Task 89, spec89 item 14)
    ('CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[K])),ALLNOBLANKROW(ZH_U[X])),FILTER(ZH_F,ZH_F[Amt]>10))',
     '2'),  # fixed (Task 89, spec89 item 15)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[K])),ALLNOBLANKROW(ZH_U)),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=3;m2=3;m2b=3;m4=3;m7=3'),  # fixed (Task 89, spec89 item 88)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[K])),ALLNOBLANKROW(ZH_U)),ZH_F2)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=3;m2=3;m2b=3;m4=3;m7=3'),  # fixed (Task 89, spec89 item 89)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[Y])),ALLNOBLANKROW(ZH_U)),ZH_F)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=3;m2=3;m2b=3;m4=3;m7=3'),  # fixed (Task 89, spec89 item 97)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[K])),ALLNOBLANKROW(ZH_W)),ZH_F2)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=3;x1=3;x2=3;x3=3;x4=3;x6=3;x8=3'),  # fixed (Task 89, spec89 item 149)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[Y])),ALLNOBLANKROW(ZH_U[X])),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     'x1=1;x3=1;x6=1'),  # fixed (Task 89, spec89 item 168)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[Y])),ALLNOBLANKROW(ZH_U[X])),ZH_F)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     'x1=1;x3=1;x6=1'),  # fixed (Task 89, spec89 item 169)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[K])),ALLNOBLANKROW(ZH_U)),ZH_F2)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=3;y1=3;y10=3;y3=3;y6=3;y9=3'),  # fixed (Task 89, spec89 item 243)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[K])),ALLNOBLANKROW(ZH_U[X])),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     'y1=1;y6=1'),  # fixed (Task 89, spec89 item 244)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[K])),ALLNOBLANKROW(ZH_U[X])),ZH_F2)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     'y1=1;y3=1;y6=1'),  # fixed (Task 89, spec89 item 245)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[Y])),ALLNOBLANKROW(ZH_U[X])),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     'y1=1;y3=1;y6=1'),  # fixed (Task 89, spec89 item 253)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[Y])),ALLNOBLANKROW(ZH_U[X])),ZH_F)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     'y1=1;y3=1;y6=1'),  # fixed (Task 89, spec89 item 254)
    ('CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[Y])),ALLNOBLANKROW(ZH_U)),FILTER(ZH_F2,ZH_F2[Amt]>10))',
     '3'),  # fixed (Task 89, spec3 item 14)
    ('CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[Y])),ALLNOBLANKROW(ZH_U)),ZH_F2)',
     '3'),  # fixed (Task 89, spec3 item 15)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[Y])),ALLNOBLANKROW(ZH_U)),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=3;m2=3;m2b=3;m4=3;m7=3'),  # fixed (Task 89, spec3 item 78)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[Y])),ALLNOBLANKROW(ZH_U)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=3;y1=3;y10=3;y3=3;y6=3;y9=3'),  # fixed (Task 89, spec3 item 203)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[Y])),ALLNOBLANKROW(ZH_U)),ZH_F2)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=3;y1=3;y10=3;y3=3;y6=3;y9=3'),  # fixed (Task 89, spec3 item 204)
    ('CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[K])),ALL(ZH_U[X])),FILTER(ZH_F2,ZH_F2[Amt]>10))',
     '4'),  # matching (spec item 0)
    ('CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),REMOVEFILTERS(ZH_U[X])),FILTER(ZH_F,ZH_F[Amt]>10))',
     '5'),  # matching (spec item 10)
    ('CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[Y])),ALLNOBLANKROW(ZH_W)),ZH_F2)',
     '5'),  # matching (spec item 21)
    ('CALCULATE(CALCULATE(COUNTROWS(ZH_F),ALLSELECTED(ZH_W)),ZH_F)',
     '12'),  # matching (spec item 31)
    ('CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALLSELECTED(ZH_U[X])),FILTER(ZH_F2,ZH_F2[Amt]>10))',
     '3'),  # matching (spec item 39)
    ('CALCULATE(CALCULATE(COUNTROWS(ZH_W),ALLSELECTED(ZH_U)),FILTER(ZH_F2,ZH_F2[Amt]>10))',
     '3'),  # matching (spec item 48)
    ('CALCULATE(CALCULATE(SUM(ZH_F2[Amt]),ALLNOBLANKROW(ZH_U[X])),ZH_F2)',
     '78'),  # matching (spec item 57)
    ('CALCULATE(CALCULATE(SUM(ZH_F[Amt]),ALLSELECTED(ZH_U[X])),FILTER(ZH_F,ZH_F[Amt]>10))',
     '251'),  # matching (spec item 66)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALL(ZH_U[K])),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=4;m2=4;m2b=4;m4=4;m7=4'),  # matching (spec item 79)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[K])),REMOVEFILTERS(ZH_W[Y])),ZH_F2)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=4;m2=4;m2b=4;m4=4;m7=4'),  # matching (spec item 93)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_F),ALLNOBLANKROW(ZH_U)),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=5;m2=5;m2b=5;m4=5;m7=5'),  # matching (spec item 103)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_U[K])),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=4;m2=4;m2b=4;m4=4;m7=4'),  # matching (spec item 111)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_W),ALL(ZH_U[K])),ZH_F)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=3;m2=3;m2b=3;m4=3;m7=3'),  # matching (spec item 120)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(SUM(ZH_F2[Amt]),ALL(ZH_U[K])),ZH_F2)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=147;m2=147;m2b=147;m4=147;m7=147'),  # matching (spec item 129)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(SUM(ZH_F2[Amt]),ALLSELECTED(ZH_W)),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=115;m2=115;m2b=115;m4=115;m7=115'),  # matching (spec item 137)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[K])),ALLNOBLANKROW(ZH_U)),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=6;x1=6;x2=6;x3=6;x4=6;x6=6;x8=6'),  # matching (spec item 148)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),REMOVEFILTERS(ZH_U[X])),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=1;x1=1;x3=1;x6=1'),  # matching (spec item 159)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[K])),REMOVEFILTERS(ZH_W[Y])),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=1;x1=1;x3=1;x6=1'),  # matching (spec item 167)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_F),ALLNOBLANKROW(ZH_U)),ZH_F)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     'x1=2;x2=1;x3=1;x4=2;x6=2'),  # matching (spec item 178)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALLNOBLANKROW(ZH_U)),ZH_F)),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=6;x1=6;x2=6;x3=6;x4=6;x6=6;x8=6'),  # matching (spec item 189)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_W),ALL(ZH_U[X])),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     'x1=1;x3=1;x6=1'),  # matching (spec item 199)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(SUM(ZH_F2[Amt]),ALL(ZH_U[X])),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=69;x1=15;x3=29;x6=22'),  # matching (spec item 207)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(SUM(ZH_F2[Amt]),ALLSELECTED(ZH_W)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=69;x1=15;x3=29;x6=22'),  # matching (spec item 216)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(SUM(ZH_F[Amt]),ALLNOBLANKROW(ZH_W)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=63;x1=63;x2=63;x3=63;x4=63;x6=63;x8=63'),  # matching (spec item 225)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[K])),REMOVEFILTERS(ZH_U[X])),ZH_F2)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=1;y1=1;y3=1;y6=1'),  # matching (spec item 234)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[K])),ALLSELECTED(ZH_U)),ZH_F)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=1;y1=1;y3=1;y6=1'),  # matching (spec item 247)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_W[Y])),ALLSELECTED(ZH_W)),ZH_F)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=1;y1=1;y3=1;y6=1'),  # matching (spec item 258)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALL(ZH_U[X])),ZH_F)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=2;y1=1;y3=1;y6=1'),  # matching (spec item 269)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_W),ALL(ZH_U[X])),ZH_F2)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     'y1=1;y3=1;y6=1'),  # matching (spec item 279)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(SUM(ZH_F2[Amt]),ALLSELECTED(ZH_U)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=69;y1=15;y3=29;y6=22'),  # matching (spec item 288)
    ('CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[K])),ALLNOBLANKROW(ZH_U[X])),FILTER(ZH_F,ZH_F[Amt]>10))',
     '5'),  # fixed (Task 89 part 2, spec89 item 1)
    ('CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALLNOBLANKROW(ZH_W)),FILTER(ZH_F,ZH_F[Amt]>10))',
     '3'),  # fixed (Task 89 part 2, spec89 item 7)
    ('CALCULATE(CALCULATE(COUNTROWS(ZH_F),ALL(ZH_U[K])),FILTER(ZH_F2,ZH_F2[Amt]>10))',
     '9'),  # fixed (Task 89 part 2, spec89 item 27)
    ('CALCULATE(CALCULATE(SUM(ZH_F[Amt]),ALL(ZH_U[K])),FILTER(ZH_F2,ZH_F2[Amt]>10))',
     '176'),  # fixed (Task 89 part 2, spec89 item 64)
    ('CALCULATE(CALCULATE(SUM(ZH_F[Amt]),REMOVEFILTERS(ZH_U[X])),FILTER(ZH_F2,ZH_F2[Amt]>10))',
     '176'),  # fixed (Task 89 part 2, spec89 item 68)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[K])),ALLNOBLANKROW(ZH_U[X])),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=5;m2=5;m2b=5;m4=5;m7=5'),  # fixed (Task 89 part 2, spec89 item 73)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[K])),ALLNOBLANKROW(ZH_U[X])),ZH_F2)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=4;m2=4;m2b=4;m4=4;m7=4'),  # fixed (Task 89 part 2, spec89 item 74)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[K])),ALLNOBLANKROW(ZH_W)),ZH_F2)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=3;m2=3;m2b=3;m4=3;m7=3'),  # fixed (Task 89 part 2, spec89 item 75)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALLNOBLANKROW(ZH_U[X])),FILTER(ZH_F,ZH_F[Amt]>10))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=5;m2=5;m2b=5;m4=5;m7=5'),  # fixed (Task 89 part 2, spec89 item 81)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALLNOBLANKROW(ZH_W)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=3;m2=3;m2b=3;m4=3;m7=3'),  # fixed (Task 89 part 2, spec89 item 82)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALLNOBLANKROW(ZH_W)),ZH_F2)),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=3;m2=3;m2b=3;m4=3;m7=3'),  # fixed (Task 89 part 2, spec89 item 83)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(SUM(ZH_F[Amt]),ALLSELECTED(ZH_U[X])),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=176;m2=176;m2b=176;m4=176;m7=176'),  # fixed (Task 89 part 2, spec89 item 142)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(SUM(ZH_F[Amt]),ALLSELECTED(ZH_W)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=176;m2=176;m2b=176;m4=176;m7=176'),  # fixed (Task 89 part 2, spec89 item 143)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALLNOBLANKROW(ZH_U[X])),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=1;x1=1;x3=1;x6=1'),  # fixed (Task 89 part 2, spec89 item 156)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_F),ALLSELECTED(ZH_W)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=4;x1=2;x3=1;x6=2'),  # fixed (Task 89 part 2, spec89 item 182)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_F),REMOVEFILTERS(ZH_U[X])),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=4;x1=2;x3=1;x6=2'),  # fixed (Task 89 part 2, spec89 item 184)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALLNOBLANKROW(ZH_U[X])),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     'x1=1;x3=1;x6=1'),  # fixed (Task 89 part 2, spec89 item 190)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[K])),ALLNOBLANKROW(ZH_W)),ZH_F2)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=3;y1=3;y10=3;y3=3;y6=3;y9=3'),  # fixed (Task 89 part 2, spec89 item 231)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(VALUES(ZH_U[X])),ALLNOBLANKROW(ZH_W)),ZH_F)),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=3;y1=3;y10=3;y3=3;y6=3;y9=3'),  # fixed (Task 89 part 2, spec89 item 237)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_F),ALLNOBLANKROW(ZH_U[X])),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     'y1=2;y3=1;y6=2'),  # fixed (Task 89 part 2, spec89 item 261)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_F),ALLSELECTED(ZH_U[X])),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=4;y1=2;y3=1;y6=2'),  # fixed (Task 89 part 2, spec89 item 265)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_F),ALLSELECTED(ZH_W)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=4;y1=2;y3=1;y6=2'),  # fixed (Task 89 part 2, spec89 item 266)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_U),ALLNOBLANKROW(ZH_U[X])),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     'y1=1;y3=1;y6=1'),  # fixed (Task 89 part 2, spec89 item 272)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(SUM(ZH_F[Amt]),ALLNOBLANKROW(ZH_U[X])),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     'y1=18;y3=9;y6=36'),  # fixed (Task 89 part 2, spec89 item 294)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(SUM(ZH_F[Amt]),ALLSELECTED(ZH_U)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=113;y1=18;y3=9;y6=36'),  # fixed (Task 89 part 2, spec89 item 296)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_W[Y],"v",CALCULATE(CALCULATE(SUM(ZH_F[Amt]),REMOVEFILTERS(ZH_U[X])),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_W[Y]&"="&[v],";",ZH_W[Y])',
     '=113;y1=18;y3=9;y6=36'),  # fixed (Task 89 part 2, spec89 item 298)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(CALCULATE(SUM(ZH_F[Amt]),ALLSELECTED(ZH_U)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_B[N]&"="&[v],";",ZH_B[N])',
     'm1=176;m2=176;m2b=176;m4=176;m7=176'),  # fixed (Task 89 part 2, spec3 item 124)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_F),ALLSELECTED(ZH_U)),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=4;x1=2;x3=1;x6=2'),  # fixed (Task 89 part 2, spec3 item 147)
    ('CONCATENATEX(SUMMARIZECOLUMNS(ZH_U[X],"v",CALCULATE(CALCULATE(COUNTROWS(ZH_F),REMOVEFILTERS(ZH_U[X])),FILTER(ZH_F2,ZH_F2[Amt]>10))),ZH_U[X]&"="&[v],";",ZH_U[X])',
     '=4;x1=2;x3=1;x6=2'),  # fixed (Task 89 part 2, spec3 item 148)
]


@pytest.mark.parametrize(("expression", "expected"), CASES)
def test_nested_clear_79_matches_power_bi(expression, expected):
    assert _same(m.ours_for("ZH", expression), expected)
