"""Task 238: type tests that Power BI answers but the engine still refused (four rules).

R1  Currency + - * of literals that overflow the Currency range: Power BI answers the type test by the static type (a division of it is an error).
R2  DIVIDE with a text literal inline in ISINTEGER / ISINT64 / ISNONTEXT / ISBOOLEAN / ISLOGICAL / ISDATETIME / ISDECIMAL / ISCURRENCY / ISTEXT / ISSTRING
    (ISNUMBER / ISNUMERIC / ISDOUBLE of it are errors in Power BI and stay refused; so does a text alternate result).
R3  a power of a column aggregate plus or minus a number literal: answered by the static type (double); the product with a number stays refused.
R4  ISDOUBLE of a whole-number aggregate plus or minus a text literal: True; with * or / Power BI raises.
Every answer below is a live Power BI answer on the Facts table (6 rows: Sales, Quantity, Region, Note); ERRORS lists expressions Power BI raised for,
which the engine must keep refusing.
"""

from __future__ import annotations

import pytest

from tools.dax_oracle_diff import local

REQUESTED = [
    ('ISINTEGER(DIVIDE(1,"zz"))', 'False'),
    ('ISNONTEXT(DIVIDE(1,"zz"))', 'True'),
    ('ISBOOLEAN(DIVIDE(1,"zz"))', 'False'),
    ('ISNUMERIC(CURRENCY(1E15)*3)', 'True'),
    ('ISDATETIME(CURRENCY(1E15)*3)', 'False'),
    ('ISNONTEXT(CURRENCY(1E15)*3)', 'True'),
    ('ISDATETIME(ABS(DIVIDE("zz",2)))', 'False'),
    ('ISLOGICAL(ABS(DIVIDE("zz",2)))', 'False'),
    ('ISNONTEXT(ABS(DIVIDE("zz",2)))', 'True'),
    ('ISNUMBER(CURRENCY(1E15)*3)', 'True'),
    ('ISCURRENCY(CURRENCY(1E15)*3)', 'True'),
    ('ISLOGICAL(CURRENCY(1E15)*3)', 'False'),
    ('ISDOUBLE(CURRENCY(2E15)*2)', 'False'),
    ('ISDECIMAL(CURRENCY(2E15)*2)', 'True'),
    ('ISBOOLEAN(CURRENCY(2E15)*2)', 'False'),
    ('ISCURRENCY(CURRENCY(1E15)+CURRENCY(1E15)*2)', 'True'),
    ('ISNONTEXT(CURRENCY(1E15)+CURRENCY(1E15)*2)', 'True'),
    ('ISNUMBER(CURRENCY(1E15)+CURRENCY(1E15)*2)', 'True'),
    ('ISTEXT(CURRENCY(1E15)*CURRENCY(1E15))', 'False'),
    ('ISBOOLEAN(CURRENCY(1E15)*CURRENCY(1E15))', 'False'),
    ('ISINT64(CURRENCY(1E15)*CURRENCY(1E15))', 'False'),
    ('ISNONTEXT(2*CURRENCY(1E15)*2)', 'True'),
    ('ISDATETIME(2*CURRENCY(1E15)*2)', 'False'),
    ('ISCURRENCY(2*CURRENCY(1E15)*2)', 'True'),
    ('ISLOGICAL(CURRENCY(1E16)+1)', 'False'),
    ('ISNUMBER(CURRENCY(1E16)+1)', 'True'),
    ('ISDECIMAL(CURRENCY(1E16)+1)', 'True'),
    ('ISNUMBER(MIN(Facts[Sales])^0.5+1)', 'True'),
    ('ISDOUBLE(MIN(Facts[Sales])^0.5+1)', 'True'),
    ('ISNUMBER(MIN(Facts[Sales])^0.5-1)', 'True'),
    ('ISNUMBER(1+MIN(Facts[Sales])^0.5)', 'True'),
    ('ISDOUBLE(MAX(Facts[Quantity])-"abc")', 'True'),
    ('ISDOUBLE(MIN(Facts[Quantity])-"abc")', 'True'),
    ('ISDOUBLE(MAX(Facts[Quantity])+"abc")', 'True'),
    ('ISDOUBLE(MAX(Facts[Quantity])-"xyz")', 'True'),
    ('ISNUMBER(CURRENCY(1E15)*2+"a")', 'True'),
]

FURTHER = [
    ('ISBOOLEAN(2-MIN(Facts[Sales])^0.5)', 'False'),
    ('ISBOOLEAN(ABS(DIVIDE("qq",3)))', 'False'),
    ('ISBOOLEAN(CURRENCY(1E16)+2)', 'False'),
    ('ISBOOLEAN(CURRENCY(4E15)-CURRENCY(-4E15)*2)', 'False'),
    ('ISBOOLEAN(DIVIDE("qq",3))', 'False'),
    ('ISBOOLEAN(MIN(Facts[Sales])^0.5+1)', 'False'),
    ('ISCURRENCY(3*CURRENCY(2E15)*4)', 'True'),
    ('ISCURRENCY(ABS(DIVIDE(2,"qq")))', 'False'),
    ('ISCURRENCY(CURRENCY(1E16)-1)', 'True'),
    ('ISCURRENCY(CURRENCY(4E15)-CURRENCY(-4E15)*2)', 'True'),
    ('ISCURRENCY(DIVIDE("qq",3))', 'False'),
    ('ISCURRENCY(MIN(Facts[Sales])^0.5+1)', 'False'),
    ('ISDATETIME(3*CURRENCY(2E15)*4)', 'False'),
    ('ISDATETIME(ABS(DIVIDE(2,"qq")))', 'False'),
    ('ISDATETIME(CURRENCY(1E16)-1)', 'False'),
    ('ISDATETIME(CURRENCY(5E15)+CURRENCY(5E15)*2)', 'False'),
    ('ISDATETIME(DIVIDE(2,"qq"))', 'False'),
    ('ISDATETIME(MIN(Facts[Sales])^0.5+1.5)', 'False'),
    ('ISDECIMAL(3+MIN(Facts[Sales])^0.25)', 'False'),
    ('ISDECIMAL(CURRENCY(-3E15)*4)', 'True'),
    ('ISDECIMAL(CURRENCY(3E15)*3)', 'True'),
    ('ISDECIMAL(DIVIDE("qq","pp"))', 'False'),
    ('ISDECIMAL(DIVIDE(2,"qq",5))', 'False'),
    ('ISDOUBLE("q"-MAX(Facts[Quantity]))', 'True'),
    ('ISDOUBLE(2-MIN(Facts[Sales])^0.5)', 'True'),
    ('ISDOUBLE(CURRENCY(-3E15)*4)', 'False'),
    ('ISDOUBLE(CURRENCY(3E15)*3)', 'False'),
    ('ISDOUBLE(MAX(Facts[Quantity])+"k9")', 'True'),
    ('ISDOUBLE(MIN(Facts[Quantity])-"k9")', 'True'),
    ('ISDOUBLE(SUM(Facts[Quantity])+"k9")', 'True'),
    ('ISINT64(3*CURRENCY(2E15)*4)', 'False'),
    ('ISINT64(ABS(DIVIDE(2,"qq")))', 'False'),
    ('ISINT64(CURRENCY(1E16)-1)', 'False'),
    ('ISINT64(CURRENCY(5E15)+CURRENCY(5E15)*2)', 'False'),
    ('ISINT64(DIVIDE(2,"qq"))', 'False'),
    ('ISINT64(MIN(Facts[Sales])^0.5+1.5)', 'False'),
    ('ISINTEGER(3+MIN(Facts[Sales])^0.25)', 'False'),
    ('ISINTEGER(CURRENCY(-3E15)*4)', 'False'),
    ('ISINTEGER(CURRENCY(3E15)*3)', 'False'),
    ('ISINTEGER(DIVIDE("qq","pp"))', 'False'),
    ('ISINTEGER(DIVIDE(2,"qq",5))', 'False'),
    ('ISLOGICAL(2-MIN(Facts[Sales])^0.5)', 'False'),
    ('ISLOGICAL(ABS(DIVIDE("qq",3)))', 'False'),
    ('ISLOGICAL(CURRENCY(1E16)+2)', 'False'),
    ('ISLOGICAL(CURRENCY(4E15)-CURRENCY(-4E15)*2)', 'False'),
    ('ISLOGICAL(DIVIDE("qq",3))', 'False'),
    ('ISLOGICAL(MIN(Facts[Sales])^0.5+1)', 'False'),
    ('ISNONTEXT(3*CURRENCY(2E15)*4)', 'True'),
    ('ISNONTEXT(ABS(DIVIDE(2,"qq")))', 'True'),
    ('ISNONTEXT(CURRENCY(1E16)-1)', 'True'),
    ('ISNONTEXT(CURRENCY(5E15)+CURRENCY(5E15)*2)', 'True'),
    ('ISNONTEXT(DIVIDE(2,"qq"))', 'True'),
    ('ISNONTEXT(MIN(Facts[Sales])^0.5+1.5)', 'True'),
    ('ISNUMBER(3+MIN(Facts[Sales])^0.25)', 'True'),
    ('ISNUMBER(CURRENCY(1E16)+2)', 'True'),
    ('ISNUMBER(CURRENCY(3E15)*3)', 'True'),
    ('ISNUMBER(CURRENCY(5E15)+CURRENCY(5E15)*2)', 'True'),
    ('ISNUMERIC(2-MIN(Facts[Sales])^0.5)', 'True'),
    ('ISNUMERIC(CURRENCY(-3E15)*4)', 'True'),
    ('ISNUMERIC(CURRENCY(3E15)*3)', 'True'),
    ('ISNUMERIC(MIN(Facts[Sales])^0.5+1)', 'True'),
    ('ISSTRING(3*CURRENCY(2E15)*4)', 'False'),
    ('ISSTRING(ABS(DIVIDE(2,"qq")))', 'False'),
    ('ISSTRING(CURRENCY(1E16)-1)', 'False'),
    ('ISSTRING(CURRENCY(5E15)+CURRENCY(5E15)*2)', 'False'),
    ('ISSTRING(DIVIDE(2,"qq"))', 'False'),
    ('ISSTRING(MIN(Facts[Sales])^0.5+1.5)', 'False'),
    ('ISTEXT(3+MIN(Facts[Sales])^0.25)', 'False'),
    ('ISTEXT(CURRENCY(-3E15)*4)', 'False'),
    ('ISTEXT(CURRENCY(3E15)*3&"x")', 'True'),
    ('ISTEXT(CURRENCY(5E15)+CURRENCY(5E15)*2)', 'False'),
    ('ISTEXT(DIVIDE(2,"qq"))', 'False'),
]

ERRORS = [
    'ISBOOLEAN(MIN(Facts[Sales])^0.5/2)',
    'ISCURRENCY(CURRENCY(3E15)*3/2)',
    'ISCURRENCY(MIN(Facts[Quantity])/"k9")',
    'ISCURRENCY(SUM(Facts[Quantity])/"k9")',
    'ISDATETIME(MIN(Facts[Sales])^0.5/2)',
    'ISDECIMAL(MIN(Facts[Quantity])/"k9")',
    'ISDOUBLE(-DIVIDE("qq",3))',
    'ISDOUBLE(AVERAGE(Facts[Quantity])*"k9")',
    'ISDOUBLE(DIVIDE("qq","pp"))',
    'ISDOUBLE(DIVIDE("ww",9))',
    'ISDOUBLE(DIVIDE(4,"ww"))',
    'ISDOUBLE(MAX(Facts[Quantity])*"k9")',
    'ISDOUBLE(MAX(Facts[Sales])/"abc")',
    'ISDOUBLE(MIN(Facts[Quantity])*"k9")',
    'ISDOUBLE(MIN(Facts[Quantity])/"k9")',
    'ISDOUBLE(MIN(Facts[Sales])^0.5/2)',
    'ISDOUBLE(SUM(Facts[Quantity])*"abc")',
    'ISINT64(AVERAGE(Facts[Quantity])/"k9")',
    'ISINT64(MIN(Facts[Quantity])/"k9")',
    'ISINTEGER(AVERAGE(Facts[Quantity])/"k9")',
    'ISINTEGER(MIN(Facts[Sales])^0.5+1/2)',
    'ISLOGICAL(DIVIDE("zz",3,"q"))',
    'ISNONTEXT(AVERAGE(Facts[Quantity])/"k9")',
    'ISNONTEXT(MIN(Facts[Sales])^0.5+1/2)',
    'ISNUMBER(-DIVIDE("qq",3))',
    'ISNUMBER(2/0+0.0^0.0)',
    'ISNUMBER(ABS(DIVIDE(2,"qq")))',
    'ISNUMBER(CURRENCY(1E15)/2)',
    'ISNUMBER(CURRENCY(3E15)*3/2)',
    'ISNUMBER(DIVIDE("qq",3))',
    'ISNUMBER(DIVIDE("zz",3,"q"))',
    'ISNUMBER(DIVIDE(DIVIDE("zz",1),2))',
    'ISNUMBER(MAX(Facts[Quantity])/"k9")',
    'ISNUMBER(MIN(Facts[Sales])^0.5)',
    'ISNUMBER(MIN(Facts[Sales])^0.5+MIN(Facts[Sales]))',
    'ISNUMBER(SUM(Facts[Quantity])/"k9")',
    'ISNUMERIC(-DIVIDE("qq",3))',
    'ISNUMERIC(AVERAGE(Facts[Quantity])*"k9")',
    'ISNUMERIC(DIVIDE("qq",3))',
    'ISNUMERIC(DIVIDE("ww",9))',
    'ISNUMERIC(DIVIDE(4,"ww"))',
    'ISNUMERIC(VAR v=DIVIDE("zz",2) RETURN v)',
]


@pytest.mark.parametrize("expression, powerbi", REQUESTED)
def test_requested_shape_answers_like_power_bi(expression: str, powerbi: str) -> None:
    assert local(expression) == powerbi


@pytest.mark.parametrize("expression, powerbi", FURTHER)
def test_further_measured_shape_answers_like_power_bi(expression: str, powerbi: str) -> None:
    assert local(expression) == powerbi


@pytest.mark.parametrize("expression", ERRORS)
def test_shape_power_bi_raises_for_stays_refused(expression: str) -> None:
    assert local(expression).startswith("LOCAL-")


def test_this_file_holds_enough_shapes() -> None:
    assert len(REQUESTED) == 36
    assert len(FURTHER) >= 40
    assert len(ERRORS) >= 30
