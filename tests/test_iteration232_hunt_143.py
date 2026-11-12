"""Iteration 232: Task 143 dax-hunt-143 (wrong DAX answers found by the fresh Power BI hunt, batch 1).

Each family below holds the Power BI answers measured for the hunt (values copied from the hunt spec, one row per expression on the
standard Facts grid). A value must match to 15 significant digits with the same sign, and text exactly. "ERR" means Power BI raises an
error: the local engine must raise it too (a LOCAL-REJECT), so IFERROR cannot turn it into a value. A LOCAL-CRASH never passes.

Families: A TOPNSKIP, B RANK / ROWNUMBER over whole tables, C EARLIER / EARLIEST without an outer row, D CURRENTGROUP outside GROUPBY,
E EDATE / EOMONTH of a BLANK date, F FIXED negative zero, G SUBSTITUTE instance_num.
"""
import unittest
from decimal import Context, Decimal

from tools import dax_oracle_diff as dax

ROUND15 = Context(prec=15)


def _same(expected: str, local: str) -> bool:
    if expected == "ERR":
        return local.startswith("LOCAL-REJECT")
    if local.startswith("LOCAL-"):
        return False
    if expected == local:
        return True
    if expected.lower() in ("true", "false"):
        return expected.lower() == local.lower()
    try:
        want, got = Decimal(expected), Decimal(local)
    except Exception:
        return False
    if not want.is_finite() or not got.is_finite():
        return False
    return ROUND15.plus(want) == ROUND15.plus(got) and want.is_signed() == got.is_signed()


# Family A: TOPNSKIP: exactly n rows after the skip, ties in table order, BLANK lowest, n rounds half up, fractional or text skip gives no rows
FAMILY_A = [
    ('CONCATENATEX(TOPNSKIP("2",1,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', '4,3'),
    ('CONCATENATEX(TOPNSKIP("2",1,Facts,Facts[Region],ASC),Facts[Quantity],",")', '1,5'),
    ('CONCATENATEX(TOPNSKIP("2",1,Facts,Facts[Sales]),Facts[Quantity],",")', '2,5'),
    ('CONCATENATEX(TOPNSKIP(-0.5,1,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', '4,3,2,1,0'),
    ('CONCATENATEX(TOPNSKIP(-0.5,1,Facts,Facts[Region],ASC),Facts[Quantity],",")', '1,5,4,3,0'),
    ('CONCATENATEX(TOPNSKIP(-0.5,1,Facts,Facts[Sales]),Facts[Quantity],",")', '2,5,0,1,4'),
    ('CONCATENATEX(TOPNSKIP(-1,1,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', '4,3,2,1,0'),
    ('CONCATENATEX(TOPNSKIP(-1,1,Facts,Facts[Region],ASC),Facts[Quantity],",")', '1,5,4,3,0'),
    ('CONCATENATEX(TOPNSKIP(-1,1,Facts,Facts[Sales]),Facts[Quantity],",")', '2,5,0,1,4'),
    ('CONCATENATEX(TOPNSKIP(-2,1,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', '4,3,2,1,0'),
    ('CONCATENATEX(TOPNSKIP(-2,1,Facts,Facts[Region],ASC),Facts[Quantity],",")', '1,5,4,3,0'),
    ('CONCATENATEX(TOPNSKIP(-2,1,Facts,Facts[Sales]),Facts[Quantity],",")', '2,5,0,1,4'),
    ('CONCATENATEX(TOPNSKIP(-3,1,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', '4,3,2,1,0'),
    ('CONCATENATEX(TOPNSKIP(-3,1,Facts,Facts[Region],ASC),Facts[Quantity],",")', '1,5,4,3,0'),
    ('CONCATENATEX(TOPNSKIP(-3,1,Facts,Facts[Sales]),Facts[Quantity],",")', '2,5,0,1,4'),
    ('CONCATENATEX(TOPNSKIP(0,1,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(0,1,Facts,Facts[Region],ASC),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(0,1,Facts,Facts[Sales]),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(0.5,1,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', '4'),
    ('CONCATENATEX(TOPNSKIP(0.5,1,Facts,Facts[Region],ASC),Facts[Quantity],",")', '1'),
    ('CONCATENATEX(TOPNSKIP(0.5,1,Facts,Facts[Sales]),Facts[Quantity],",")', '2'),
    ('CONCATENATEX(TOPNSKIP(1.4,1,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', '4'),
    ('CONCATENATEX(TOPNSKIP(1.4,1,Facts,Facts[Region],ASC),Facts[Quantity],",")', '1'),
    ('CONCATENATEX(TOPNSKIP(1.4,1,Facts,Facts[Sales]),Facts[Quantity],",")', '2'),
    ('CONCATENATEX(TOPNSKIP(1.5,1,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', '4,3'),
    ('CONCATENATEX(TOPNSKIP(1.5,1,Facts,Facts[Region],ASC),Facts[Quantity],",")', '1,5'),
    ('CONCATENATEX(TOPNSKIP(1.5,1,Facts,Facts[Sales]),Facts[Quantity],",")', '2,5'),
    ('CONCATENATEX(TOPNSKIP(2,"2",Facts,Facts[Quantity],DESC),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,"2",Facts,Facts[Region],ASC),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,"2",Facts,Facts[Sales]),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,-0.5,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', '5,4'),
    ('CONCATENATEX(TOPNSKIP(2,-0.5,Facts,Facts[Region],ASC),Facts[Quantity],",")', '2,1'),
    ('CONCATENATEX(TOPNSKIP(2,-0.5,Facts,Facts[Sales]),Facts[Quantity],",")', '3,2'),
    ('CONCATENATEX(TOPNSKIP(2,-1,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', '5,4'),
    ('CONCATENATEX(TOPNSKIP(2,-1,Facts,Facts[Region],ASC),Facts[Quantity],",")', '2,1'),
    ('CONCATENATEX(TOPNSKIP(2,-1,Facts,Facts[Sales]),Facts[Quantity],",")', '3,2'),
    ('CONCATENATEX(TOPNSKIP(2,-2,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', '5,4'),
    ('CONCATENATEX(TOPNSKIP(2,-2,Facts,Facts[Region],ASC),Facts[Quantity],",")', '2,1'),
    ('CONCATENATEX(TOPNSKIP(2,-2,Facts,Facts[Sales]),Facts[Quantity],",")', '3,2'),
    ('CONCATENATEX(TOPNSKIP(2,-3,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', '5,4'),
    ('CONCATENATEX(TOPNSKIP(2,-3,Facts,Facts[Region],ASC),Facts[Quantity],",")', '2,1'),
    ('CONCATENATEX(TOPNSKIP(2,-3,Facts,Facts[Sales]),Facts[Quantity],",")', '3,2'),
    ('CONCATENATEX(TOPNSKIP(2,0,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', '5,4'),
    ('CONCATENATEX(TOPNSKIP(2,0,Facts,Facts[Region],ASC),Facts[Quantity],",")', '2,1'),
    ('CONCATENATEX(TOPNSKIP(2,0,Facts,Facts[Sales]),Facts[Quantity],",")', '3,2'),
    ('CONCATENATEX(TOPNSKIP(2,0.5,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,0.5,Facts,Facts[Region],ASC),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,0.5,Facts,Facts[Sales]),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,1.4,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,1.4,Facts,Facts[Region],ASC),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,1.4,Facts,Facts[Sales]),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,1.5,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,1.5,Facts,Facts[Region],ASC),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,1.5,Facts,Facts[Sales]),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,2.5,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,2.5,Facts,Facts[Region],ASC),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,2.5,Facts,Facts[Sales]),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,7,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,7,Facts,Facts[Region],ASC),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,7,Facts,Facts[Sales]),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,BLANK(),Facts,Facts[Quantity],DESC),Facts[Quantity],",")', '5,4'),
    ('CONCATENATEX(TOPNSKIP(2,BLANK(),Facts,Facts[Region],ASC),Facts[Quantity],",")', '2,1'),
    ('CONCATENATEX(TOPNSKIP(2,BLANK(),Facts,Facts[Sales]),Facts[Quantity],",")', '3,2'),
    ('CONCATENATEX(TOPNSKIP(2,TRUE(),Facts,Facts[Quantity],DESC),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,TRUE(),Facts,Facts[Region],ASC),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2,TRUE(),Facts,Facts[Sales]),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(2.5,1,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', '4,3,2'),
    ('CONCATENATEX(TOPNSKIP(2.5,1,Facts,Facts[Region],ASC),Facts[Quantity],",")', '1,5,4'),
    ('CONCATENATEX(TOPNSKIP(2.5,1,Facts,Facts[Sales]),Facts[Quantity],",")', '2,5,0'),
    ('CONCATENATEX(TOPNSKIP(7,1,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', '4,3,2,1,0'),
    ('CONCATENATEX(TOPNSKIP(7,1,Facts,Facts[Region],ASC),Facts[Quantity],",")', '1,5,4,3,0'),
    ('CONCATENATEX(TOPNSKIP(7,1,Facts,Facts[Sales]),Facts[Quantity],",")', '2,5,0,1,4'),
    ('CONCATENATEX(TOPNSKIP(BLANK(),1,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(BLANK(),1,Facts,Facts[Region],ASC),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(BLANK(),1,Facts,Facts[Sales]),Facts[Quantity],",")', 'BLANK'),
    ('CONCATENATEX(TOPNSKIP(TRUE(),1,Facts,Facts[Quantity],DESC),Facts[Quantity],",")', '4'),
    ('CONCATENATEX(TOPNSKIP(TRUE(),1,Facts,Facts[Region],ASC),Facts[Quantity],",")', '1'),
    ('CONCATENATEX(TOPNSKIP(TRUE(),1,Facts,Facts[Sales]),Facts[Quantity],",")', '2'),
    ('COUNTROWS(TOPNSKIP("2",3,Facts,Facts[Quantity],DESC))', '2'),
    ('COUNTROWS(TOPNSKIP("2",3,Facts,Facts[Region],ASC))', '2'),
    ('COUNTROWS(TOPNSKIP("2",3,Facts,Facts[Sales]))', '2'),
    ('COUNTROWS(TOPNSKIP(-0.5,3,Facts,Facts[Quantity],DESC))', '3'),
    ('COUNTROWS(TOPNSKIP(-0.5,3,Facts,Facts[Region],ASC))', '3'),
    ('COUNTROWS(TOPNSKIP(-0.5,3,Facts,Facts[Sales]))', '3'),
    ('COUNTROWS(TOPNSKIP(-1,3,Facts,Facts[Quantity],DESC))', '3'),
    ('COUNTROWS(TOPNSKIP(-1,3,Facts,Facts[Region],ASC))', '3'),
    ('COUNTROWS(TOPNSKIP(-1,3,Facts,Facts[Sales]))', '3'),
    ('COUNTROWS(TOPNSKIP(-2,3,Facts,Facts[Quantity],DESC))', '3'),
    ('COUNTROWS(TOPNSKIP(-2,3,Facts,Facts[Region],ASC))', '3'),
    ('COUNTROWS(TOPNSKIP(-2,3,Facts,Facts[Sales]))', '3'),
    ('COUNTROWS(TOPNSKIP(-3,3,Facts,Facts[Quantity],DESC))', '3'),
    ('COUNTROWS(TOPNSKIP(-3,3,Facts,Facts[Region],ASC))', '3'),
    ('COUNTROWS(TOPNSKIP(-3,3,Facts,Facts[Sales]))', '3'),
    ('COUNTROWS(TOPNSKIP(0,3,Facts,Facts[Quantity],DESC))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(0,3,Facts,Facts[Region],ASC))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(0,3,Facts,Facts[Sales]))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(0.5,3,Facts,Facts[Quantity],DESC))', '1'),
    ('COUNTROWS(TOPNSKIP(0.5,3,Facts,Facts[Region],ASC))', '1'),
    ('COUNTROWS(TOPNSKIP(0.5,3,Facts,Facts[Sales]))', '1'),
    ('COUNTROWS(TOPNSKIP(1.4,3,Facts,Facts[Quantity],DESC))', '1'),
    ('COUNTROWS(TOPNSKIP(1.4,3,Facts,Facts[Region],ASC))', '1'),
    ('COUNTROWS(TOPNSKIP(1.4,3,Facts,Facts[Sales]))', '1'),
    ('COUNTROWS(TOPNSKIP(1.5,3,Facts,Facts[Quantity],DESC))', '2'),
    ('COUNTROWS(TOPNSKIP(1.5,3,Facts,Facts[Region],ASC))', '2'),
    ('COUNTROWS(TOPNSKIP(1.5,3,Facts,Facts[Sales]))', '2'),
    ('COUNTROWS(TOPNSKIP(2.5,3,Facts,Facts[Quantity],DESC))', '3'),
    ('COUNTROWS(TOPNSKIP(2.5,3,Facts,Facts[Region],ASC))', '3'),
    ('COUNTROWS(TOPNSKIP(2.5,3,Facts,Facts[Sales]))', '3'),
    ('COUNTROWS(TOPNSKIP(3,"2",Facts,Facts[Quantity],DESC))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,"2",Facts,Facts[Region],ASC))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,"2",Facts,Facts[Sales]))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,-0.5,Facts,Facts[Quantity],DESC))', '3'),
    ('COUNTROWS(TOPNSKIP(3,-0.5,Facts,Facts[Region],ASC))', '3'),
    ('COUNTROWS(TOPNSKIP(3,-0.5,Facts,Facts[Sales]))', '3'),
    ('COUNTROWS(TOPNSKIP(3,-1,Facts,Facts[Quantity],DESC))', '3'),
    ('COUNTROWS(TOPNSKIP(3,-1,Facts,Facts[Region],ASC))', '3'),
    ('COUNTROWS(TOPNSKIP(3,-1,Facts,Facts[Sales]))', '3'),
    ('COUNTROWS(TOPNSKIP(3,-2,Facts,Facts[Quantity],DESC))', '3'),
    ('COUNTROWS(TOPNSKIP(3,-2,Facts,Facts[Region],ASC))', '3'),
    ('COUNTROWS(TOPNSKIP(3,-2,Facts,Facts[Sales]))', '3'),
    ('COUNTROWS(TOPNSKIP(3,-3,Facts,Facts[Quantity],DESC))', '3'),
    ('COUNTROWS(TOPNSKIP(3,-3,Facts,Facts[Region],ASC))', '3'),
    ('COUNTROWS(TOPNSKIP(3,-3,Facts,Facts[Sales]))', '3'),
    ('COUNTROWS(TOPNSKIP(3,0,Facts,Facts[Quantity],DESC))', '3'),
    ('COUNTROWS(TOPNSKIP(3,0,Facts,Facts[Region],ASC))', '3'),
    ('COUNTROWS(TOPNSKIP(3,0,Facts,Facts[Sales]))', '3'),
    ('COUNTROWS(TOPNSKIP(3,0.5,Facts,Facts[Quantity],DESC))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,0.5,Facts,Facts[Region],ASC))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,0.5,Facts,Facts[Sales]))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,1.4,Facts,Facts[Quantity],DESC))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,1.4,Facts,Facts[Region],ASC))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,1.4,Facts,Facts[Sales]))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,1.5,Facts,Facts[Quantity],DESC))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,1.5,Facts,Facts[Region],ASC))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,1.5,Facts,Facts[Sales]))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,2.5,Facts,Facts[Quantity],DESC))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,2.5,Facts,Facts[Region],ASC))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,2.5,Facts,Facts[Sales]))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,7,Facts,Facts[Quantity],DESC))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,7,Facts,Facts[Region],ASC))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,7,Facts,Facts[Sales]))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,BLANK(),Facts,Facts[Quantity],DESC))', '3'),
    ('COUNTROWS(TOPNSKIP(3,BLANK(),Facts,Facts[Region],ASC))', '3'),
    ('COUNTROWS(TOPNSKIP(3,BLANK(),Facts,Facts[Sales]))', '3'),
    ('COUNTROWS(TOPNSKIP(3,TRUE(),Facts,Facts[Quantity],DESC))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,TRUE(),Facts,Facts[Region],ASC))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(3,TRUE(),Facts,Facts[Sales]))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(7,3,Facts,Facts[Quantity],DESC))', '3'),
    ('COUNTROWS(TOPNSKIP(7,3,Facts,Facts[Region],ASC))', '3'),
    ('COUNTROWS(TOPNSKIP(7,3,Facts,Facts[Sales]))', '3'),
    ('COUNTROWS(TOPNSKIP(BLANK(),3,Facts,Facts[Quantity],DESC))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(BLANK(),3,Facts,Facts[Region],ASC))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(BLANK(),3,Facts,Facts[Sales]))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(TRUE(),3,Facts,Facts[Quantity],DESC))', '1'),
    ('COUNTROWS(TOPNSKIP(TRUE(),3,Facts,Facts[Region],ASC))', '1'),
    ('COUNTROWS(TOPNSKIP(TRUE(),3,Facts,Facts[Sales]))', '1'),
    ('COUNTROWS(TOPNSKIP(2,10,Facts,Facts[Sales]))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(1,-2,Facts,Facts[Sales]))', '1'),
    ('COUNTROWS(TOPNSKIP(0,5,Facts,Facts[Sales]))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(0,1,Facts,Facts[Sales]))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(2,-1,Facts,Facts[Sales]))', '2'),
    ('COUNTROWS(TOPNSKIP(1,-3,Facts,Facts[Sales]))', '1'),
    ('COUNTROWS(TOPNSKIP(5,10,Facts,Facts[Sales]))', 'BLANK'),
    ('COUNTROWS(TOPNSKIP(0.5,-3,Facts,Facts[Sales]))', '1'),
    ('COUNTROWS(TOPNSKIP(10,-1,Facts,Facts[Sales]))', '6'),
    ('COUNTROWS(TOPNSKIP(-3,5,Facts,Facts[Sales]))', '1'),
    ('IFERROR(COUNTROWS(TOPNSKIP(5,0.5,Facts,Facts[Sales])),"E")', 'BLANK'),
]

# Family B: RANK / ROWNUMBER over Facts inside an iterator over FILTER(Facts, ...) and CONCATENATEX over ROWNUMBER(ALL(Facts), ...)
FAMILY_B = [
    ('CONCATENATEX(FILTER(Facts,Facts[Region]<>"West"),RANK(DENSE,Facts,ORDERBY(Facts[Quantity],DESC)),",")', '4,5,2,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Region]<>"West"),RANK(DENSE,Facts,ORDERBY(Facts[Region],ASC,Facts[Quantity],DESC)),",")', '2,3,4,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Region]<>"West"),RANK(DENSE,Facts,ORDERBY(Facts[Sales])),",")', '5,1,2,4'),
    ('CONCATENATEX(FILTER(Facts,Facts[Region]<>"West"),ROWNUMBER(FILTER(Facts,Facts[Region]<>"West"),ORDERBY(Facts[Quantity],DESC)),",")', '3,4,2,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Region]<>"West"),ROWNUMBER(FILTER(Facts,Facts[Region]<>"West"),ORDERBY(Facts[Region],ASC,Facts[Quantity],DESC)),",")', '2,3,4,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Region]<>"West"),ROWNUMBER(FILTER(Facts,Facts[Region]<>"West"),ORDERBY(Facts[Sales])),",")', '4,1,2,3'),
    ('CONCATENATEX(FILTER(Facts,Facts[Region]<>"West"),ROWNUMBER(Facts,ORDERBY(Facts[Quantity],DESC)),",")', '4,5,2,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Region]<>"West"),ROWNUMBER(Facts,ORDERBY(Facts[Region],ASC,Facts[Quantity],DESC)),",")', '2,3,4,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Region]<>"West"),ROWNUMBER(Facts,ORDERBY(Facts[Sales])),",")', '5,1,2,4'),
    ('CONCATENATEX(FILTER(Facts,Facts[Region]="East"),RANK(DENSE,Facts,ORDERBY(Facts[Quantity],DESC)),",")', '4,5,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Region]="East"),RANK(DENSE,Facts,ORDERBY(Facts[Region],ASC,Facts[Quantity],DESC)),",")', '2,3,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Region]="East"),RANK(DENSE,Facts,ORDERBY(Facts[Sales])),",")', '5,1,4'),
    ('CONCATENATEX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(FILTER(Facts,Facts[Region]="East"),ORDERBY(Facts[Quantity],DESC)),",")', '2,3,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(FILTER(Facts,Facts[Region]="East"),ORDERBY(Facts[Region],ASC,Facts[Quantity],DESC)),",")', '2,3,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(FILTER(Facts,Facts[Region]="East"),ORDERBY(Facts[Sales])),",")', '3,1,2'),
    ('CONCATENATEX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(Facts,ORDERBY(Facts[Quantity],DESC)),",")', '4,5,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(Facts,ORDERBY(Facts[Region],ASC,Facts[Quantity],DESC)),",")', '2,3,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(Facts,ORDERBY(Facts[Sales])),",")', '5,1,4'),
    ('CONCATENATEX(FILTER(Facts,Facts[Sales]>0),RANK(DENSE,Facts,ORDERBY(Facts[Quantity],DESC)),",")', '4,3,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Sales]>0),RANK(DENSE,Facts,ORDERBY(Facts[Region],ASC,Facts[Quantity],DESC)),",")', '2,5,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Sales]>0),RANK(DENSE,Facts,ORDERBY(Facts[Sales])),",")', '5,6,4'),
    ('CONCATENATEX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(FILTER(Facts,Facts[Sales]>0),ORDERBY(Facts[Quantity],DESC)),",")', '3,2,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(FILTER(Facts,Facts[Sales]>0),ORDERBY(Facts[Region],ASC,Facts[Quantity],DESC)),",")', '2,3,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(FILTER(Facts,Facts[Sales]>0),ORDERBY(Facts[Sales])),",")', '2,3,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(Facts,ORDERBY(Facts[Quantity],DESC)),",")', '4,3,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(Facts,ORDERBY(Facts[Region],ASC,Facts[Quantity],DESC)),",")', '2,5,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(Facts,ORDERBY(Facts[Sales])),",")', '5,6,4'),
    ('CONCATENATEX(FILTER(Facts,TRUE()),RANK(DENSE,Facts,ORDERBY(Facts[Quantity],DESC)),",")', '4,3,5,2,6,1'),
    ('CONCATENATEX(FILTER(Facts,TRUE()),RANK(DENSE,Facts,ORDERBY(Facts[Region],ASC,Facts[Quantity],DESC)),",")', '2,5,3,4,6,1'),
    ('CONCATENATEX(FILTER(Facts,TRUE()),RANK(DENSE,Facts,ORDERBY(Facts[Sales])),",")', '5,6,1,2,3,4'),
    ('CONCATENATEX(FILTER(Facts,TRUE()),ROWNUMBER(FILTER(Facts,TRUE()),ORDERBY(Facts[Quantity],DESC)),",")', '4,3,5,2,6,1'),
    ('CONCATENATEX(FILTER(Facts,TRUE()),ROWNUMBER(FILTER(Facts,TRUE()),ORDERBY(Facts[Region],ASC,Facts[Quantity],DESC)),",")', '2,5,3,4,6,1'),
    ('CONCATENATEX(FILTER(Facts,TRUE()),ROWNUMBER(FILTER(Facts,TRUE()),ORDERBY(Facts[Sales])),",")', '5,6,1,2,3,4'),
    ('CONCATENATEX(FILTER(Facts,TRUE()),ROWNUMBER(Facts,ORDERBY(Facts[Quantity],DESC)),",")', '4,3,5,2,6,1'),
    ('CONCATENATEX(FILTER(Facts,TRUE()),ROWNUMBER(Facts,ORDERBY(Facts[Region],ASC,Facts[Quantity],DESC)),",")', '2,5,3,4,6,1'),
    ('CONCATENATEX(FILTER(Facts,TRUE()),ROWNUMBER(Facts,ORDERBY(Facts[Sales])),",")', '5,6,1,2,3,4'),
    ('SUMX(VALUES(Facts[Region]),ROWNUMBER(Facts,ORDERBY(Facts[Quantity],DESC)))', '2'),
    ('SUMX(VALUES(Facts[Region]),ROWNUMBER(Facts,ORDERBY(Facts[Region],ASC,Facts[Quantity],DESC)))', '4'),
    ('SUMX(VALUES(Facts[Region]),ROWNUMBER(Facts,ORDERBY(Facts[Sales])))', '2'),
    ('AVERAGEX(FILTER(Facts,Facts[Quantity]>=2),RANK(DENSE,Facts,ORDERBY(Facts[Sales])))', '4.25'),
    ('AVERAGEX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(ALL(Facts),ORDERBY(Facts[Sales])))', '4.25'),
    ('AVERAGEX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(Facts,ORDERBY(Facts[Quantity],DESC)))', '2.5'),
    ('AVERAGEX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(Facts,ORDERBY(Facts[Sales])))', '4.25'),
    ('AVERAGEX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(ORDERBY(Facts[Sales])))', '2.5'),
    ('AVERAGEX(FILTER(Facts,Facts[Region]="East"),RANK(DENSE,Facts,ORDERBY(Facts[Sales])))', '3.33333333333333'),
    ('AVERAGEX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(ALL(Facts),ORDERBY(Facts[Sales])))', '3.33333333333333'),
    ('AVERAGEX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(Facts,ORDERBY(Facts[Quantity],DESC)))', '3.33333333333333'),
    ('AVERAGEX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(Facts,ORDERBY(Facts[Sales])))', '3.33333333333333'),
    ('AVERAGEX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(ORDERBY(Facts[Sales])))', '2'),
    ('AVERAGEX(FILTER(Facts,Facts[Sales]>0),RANK(DENSE,Facts,ORDERBY(Facts[Sales])))', '5'),
    ('AVERAGEX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(ALL(Facts),ORDERBY(Facts[Sales])))', '5'),
    ('AVERAGEX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(Facts,ORDERBY(Facts[Quantity],DESC)))', '2.66666666666667'),
    ('AVERAGEX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(Facts,ORDERBY(Facts[Sales])))', '5'),
    ('AVERAGEX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(ORDERBY(Facts[Sales])))', '2'),
    ('CONCATENATEX(FILTER(Facts,Facts[Quantity]>=2),RANK(DENSE,Facts,ORDERBY(Facts[Sales])),",")', '5,6,2,4'),
    ('CONCATENATEX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(ALL(Facts),ORDERBY(Facts[Sales])),",")', '5,6,2,4'),
    ('CONCATENATEX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(Facts,ORDERBY(Facts[Quantity],DESC)),",")', '4,3,2,1'),
    ('CONCATENATEX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(Facts,ORDERBY(Facts[Sales])),",")', '5,6,2,4'),
    ('CONCATENATEX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(ORDERBY(Facts[Sales])),",")', '2,4,5,6'),
    ('CONCATENATEX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(ALL(Facts),ORDERBY(Facts[Sales])),",")', '5,1,4'),
    ('CONCATENATEX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(ORDERBY(Facts[Sales])),",")', '1,4,5'),
    ('CONCATENATEX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(ALL(Facts),ORDERBY(Facts[Sales])),",")', '5,6,4'),
    ('CONCATENATEX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(ORDERBY(Facts[Sales])),",")', '4,5,6'),
    ('COUNTX(FILTER(Facts,Facts[Quantity]>=2),RANK(DENSE,Facts,ORDERBY(Facts[Sales])))', '4'),
    ('COUNTX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(ALL(Facts),ORDERBY(Facts[Sales])))', '4'),
    ('COUNTX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(Facts,ORDERBY(Facts[Quantity],DESC)))', '4'),
    ('COUNTX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(Facts,ORDERBY(Facts[Sales])))', '4'),
    ('COUNTX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(ORDERBY(Facts[Sales])))', '4'),
    ('COUNTX(FILTER(Facts,Facts[Region]="East"),RANK(DENSE,Facts,ORDERBY(Facts[Sales])))', '3'),
    ('COUNTX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(ALL(Facts),ORDERBY(Facts[Sales])))', '3'),
    ('COUNTX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(Facts,ORDERBY(Facts[Quantity],DESC)))', '3'),
    ('COUNTX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(Facts,ORDERBY(Facts[Sales])))', '3'),
    ('COUNTX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(ORDERBY(Facts[Sales])))', '3'),
    ('COUNTX(FILTER(Facts,Facts[Sales]>0),RANK(DENSE,Facts,ORDERBY(Facts[Sales])))', '3'),
    ('COUNTX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(ALL(Facts),ORDERBY(Facts[Sales])))', '3'),
    ('COUNTX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(Facts,ORDERBY(Facts[Quantity],DESC)))', '3'),
    ('COUNTX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(Facts,ORDERBY(Facts[Sales])))', '3'),
    ('COUNTX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(ORDERBY(Facts[Sales])))', '3'),
    ('MAXX(FILTER(Facts,Facts[Quantity]>=2),RANK(DENSE,Facts,ORDERBY(Facts[Sales])))', '6'),
    ('MAXX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(ALL(Facts),ORDERBY(Facts[Sales])))', '6'),
    ('MAXX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(Facts,ORDERBY(Facts[Quantity],DESC)))', '4'),
    ('MAXX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(Facts,ORDERBY(Facts[Sales])))', '6'),
    ('MAXX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(ORDERBY(Facts[Sales])))', '4'),
    ('MAXX(FILTER(Facts,Facts[Region]="East"),RANK(DENSE,Facts,ORDERBY(Facts[Sales])))', '5'),
    ('MAXX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(ALL(Facts),ORDERBY(Facts[Sales])))', '5'),
    ('MAXX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(Facts,ORDERBY(Facts[Quantity],DESC)))', '5'),
    ('MAXX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(Facts,ORDERBY(Facts[Sales])))', '5'),
    ('MAXX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(ORDERBY(Facts[Sales])))', '3'),
    ('MAXX(FILTER(Facts,Facts[Sales]>0),RANK(DENSE,Facts,ORDERBY(Facts[Sales])))', '6'),
    ('MAXX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(ALL(Facts),ORDERBY(Facts[Sales])))', '6'),
    ('MAXX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(Facts,ORDERBY(Facts[Quantity],DESC)))', '4'),
    ('MAXX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(Facts,ORDERBY(Facts[Sales])))', '6'),
    ('MAXX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(ORDERBY(Facts[Sales])))', '3'),
    ('SUMX(FILTER(Facts,Facts[Quantity]>=2),RANK(DENSE,Facts,ORDERBY(Facts[Sales])))', '17'),
    ('SUMX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(ALL(Facts),ORDERBY(Facts[Sales])))', '17'),
    ('SUMX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(Facts,ORDERBY(Facts[Quantity],DESC)))', '10'),
    ('SUMX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(Facts,ORDERBY(Facts[Sales])))', '17'),
    ('SUMX(FILTER(Facts,Facts[Quantity]>=2),ROWNUMBER(ORDERBY(Facts[Sales])))', '10'),
    ('SUMX(FILTER(Facts,Facts[Region]="East"),RANK(DENSE,Facts,ORDERBY(Facts[Sales])))', '10'),
    ('SUMX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(ALL(Facts),ORDERBY(Facts[Sales])))', '10'),
    ('SUMX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(Facts,ORDERBY(Facts[Quantity],DESC)))', '10'),
    ('SUMX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(Facts,ORDERBY(Facts[Sales])))', '10'),
    ('SUMX(FILTER(Facts,Facts[Region]="East"),ROWNUMBER(ORDERBY(Facts[Sales])))', '6'),
    ('SUMX(FILTER(Facts,Facts[Sales]>0),RANK(DENSE,Facts,ORDERBY(Facts[Sales])))', '15'),
    ('SUMX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(ALL(Facts),ORDERBY(Facts[Sales])))', '15'),
    ('SUMX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(Facts,ORDERBY(Facts[Quantity],DESC)))', '8'),
    ('SUMX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(Facts,ORDERBY(Facts[Sales])))', '15'),
    ('SUMX(FILTER(Facts,Facts[Sales]>0),ROWNUMBER(ORDERBY(Facts[Sales])))', '6'),
    ('IFERROR(SUMX(FILTER(Facts,Facts[Region]="East" && Facts[Sales]>0),ROWNUMBER(Facts,ORDERBY(Facts[Sales]))),"E")', '9'),
    ('SUMX(FILTER(Facts,Facts[Quantity]>SUM(Facts[Quantity])/2),ROWNUMBER(Facts,ORDERBY(Facts[Sales])))', 'BLANK'),
    ('RANK(1)', 'ERR'),
]

# Family C: EARLIER / EARLIEST with no outer row context (SELECTCOLUMNS / ADDCOLUMNS at the top level) is an error
FAMILY_C = [
    ('COUNTROWS(SELECTCOLUMNS(Facts,"a",EARLIER(Facts[Sales])))', 'ERR'),
    ('EARLIER(Facts[Sales])', 'ERR'),
    ('EARLIEST(Facts[Sales])', 'ERR'),
    ('IFERROR(SUMX(Facts,EARLIER(Facts[Sales])),1)', 'ERR'),
    ('SUMX(Facts,EARLIER(Facts[Sales]))', 'ERR'),
    ('SUMX(Facts,EARLIER(Facts[Sales],2))', 'ERR'),
    ('SUMX(Facts,SUMX(Facts,EARLIER(Facts[Sales])))', '189'),
    ('SUMX(Facts,SUMX(Facts,EARLIER(Facts[Sales],2)))', 'ERR'),
    ('SUMX(Facts,SUMX(Facts,EARLIEST(Facts[Sales])))', '189'),
    ('SUMX(Facts,EARLIER(Facts[Sales])+EARLIEST(Facts[Sales]))', 'ERR'),
    ('IFERROR(COUNTROWS(SELECTCOLUMNS(Facts,"a",EARLIER(Facts[Sales]))),"E")', 'ERR'),
    ('SUMX(ADDCOLUMNS(VALUES(Facts[Region]),"v",STDEVX.P(ADDCOLUMNS(Facts,"k",-0.5),EARLIER(Facts[Sales]))),[v])', 'ERR'),
    ('STDEVX.P(ADDCOLUMNS(Facts,"k",PRODUCTX(TOPN(5,Facts,Facts[Sales]),EARLIER(Facts[Sales]))),IF(ISBLANK(Facts[Sales]),0,Facts[Sales]))', '7.6743620798952'),
    ('MAXX(CALCULATETABLE(Facts,Facts[Sales]<>BLANK()),EARLIER(Facts[Sales]))', 'ERR'),
    ('COUNTX(FILTER(Facts,Facts[Region]="East"),EARLIER(Facts[Sales]))', 'ERR'),
    ('VARX.S(TOPN(-1,Facts,Facts[Sales]),EARLIER(Facts[Sales]))', 'ERR'),
    ('PERCENTILEX.EXC(ADDCOLUMNS(Facts,"k",MAX(Facts[Sales])),EARLIER(Facts[Sales]),0.5)', 'ERR'),
    ('RANKX(FILTER(Facts,NOT(Facts[Region]="North")),EARLIER(Facts[Sales]),,ASC)', 'ERR'),
    ('VARX.P(ADDCOLUMNS(Facts,"k","1.5"),EARLIER(Facts[Sales]))', 'ERR'),
    ('RANKX(ALL(Facts),EARLIER(Facts[Sales]))', 'ERR'),
    ('PRODUCTX(ADDCOLUMNS(Facts,"k",DATE(2020,2,29)),EARLIER(Facts[Sales]))', 'ERR'),
    ('COUNTAX(ALL(Facts),EARLIER(Facts[Sales]))', 'ERR'),
    ('GEOMEANX(FILTER(Facts,Facts[Region]=MAX(Facts[Region])),EARLIER(Facts[Sales]))', 'ERR'),
    ('STDEVX.S(ADDCOLUMNS(Facts,"k",SUMX(VALUES(Facts[Region]),CALCULATE(SUM(Facts[Sales])))),EARLIER(Facts[Sales]))', 'ERR'),
    ('PERCENTILEX.INC(Facts,EARLIER(Facts[Sales]),0.9)', 'ERR'),
]

# Family D: CURRENTGROUP() outside GROUPBY is an error, not a crash
FAMILY_D = [
    ('COUNTROWS(CURRENTGROUP())', 'ERR'),
    ('CURRENTGROUP()', 'ERR'),
    ('IFERROR(CURRENTGROUP(),1)', 'ERR'),
    ('SUMX(CURRENTGROUP(),Facts[Sales])', 'ERR'),
    ('IFERROR(CURRENTGROUP(),"E")', 'ERR'),
    ('COUNTROWS(GROUPBY(Facts,Facts[Region],"g",SUMX(CURRENTGROUP(),Facts[Sales])))', '3'),
    ('IFERROR(COUNTROWS(GROUPBY(Facts,Facts[Region],"g",SUMX(CURRENTGROUP(),Facts[Sales]))),"E")', '3'),
    ('SUMX(GROUPBY(Facts,Facts[Region],"g",SUMX(CURRENTGROUP(),Facts[Sales])),[g])', '31.5'),
    ('IFERROR(SUMX(GROUPBY(Facts,Facts[Region],"g",SUMX(CURRENTGROUP(),Facts[Sales])),[g]),"E")', '31.5'),
    ('PERCENTILEX.EXC(ADDCOLUMNS(Facts,"k",SUMX(GROUPBY(Facts,Facts[Region],"g",SUMX(CURRENTGROUP(),Facts[Sales])),[g])),IF(Facts[Sales]>0,Facts[Sales],0),0.25)', '0'),
]

# Family E: EDATE / EOMONTH of a BLANK date beside + or - a number is a date (day zero plus the number)
FAMILY_E = [
    ('EDATE(BLANK(),0)&""', ''),
    ('EDATE(BLANK(),2)+1', '12/31/1899 00:00:00'),
    ('EOMONTH(BLANK(),-3)+2', '01/01/1900 00:00:00'),
    ('EOMONTH(BLANK(),-3)+2.5', '01/01/1900 12:00:00'),
    ('EOMONTH(BLANK(),-3)+BLANK()', 'BLANK'),
    ('EOMONTH(BLANK(),-3)-2', '12/28/1899 00:00:00'),
    ('EOMONTH(BLANK(),0)', 'BLANK'),
    ('EOMONTH(BLANK(),0)+0', '12/30/1899 00:00:00'),
    ('EOMONTH(BLANK(),1)*1', 'BLANK'),
    ('EOMONTH(BLANK(),5)&""', ''),
    ('INT(EOMONTH(BLANK(),-3)+2)', '2'),
    ('ISBLANK(EOMONTH(BLANK(),0))', 'True'),
    ('WEEKDAY(EDATE(BLANK(),-1),1)', 'BLANK'),
    ('"2020-02-29"+(NETWORKDAYS(EDATE(BLANK(),5),DATEVALUE("2021-06-15")+(DATE(2020,2,29))))', '106927'),
    ('EOMONTH(BLANK()+2,0)', '01/31/1900 00:00:00'),
]

# Family F: FIXED never shows a negative zero
FAMILY_F = [
    ('FIXED(-0.0001,2)', '0.00'),
    ('FIXED(-0.004,2,TRUE())', '0.00'),
    ('FIXED(-0.4,0)', '0'),
    ('FIXED(-0.4,0,TRUE())', '0'),
    ('FIXED(-0.5,0)', '-1'),
    ('FIXED(-1E-20,5)', '0.00000'),
    ('FIXED(-2,-1)', '0'),
    ('FIXED(-2,-1,TRUE())', '0'),
    ('FIXED(-4,-1)', '0'),
    ('FIXED(-49,-2,FALSE())', '0'),
    ('IFERROR(FIXED(ISO.CEILING(BLANK(),2),0),"E")', '0'),
    ('FIXED(ROUND((MAX(Facts[Sales]))/(10),-2),10,(1<2))', '0.0000000000'),
    ('IFERROR(FIXED(ROUNDUP(AVERAGE(Facts[Quantity]),10),1),"E")', '2.5'),
    ('FIXED(ROUNDUP(AVERAGE(Facts[Sales]),3),0.5,FALSE())', '6.3'),
    ('FIXED(1E15,-1)', '1,000,000,000,000,000'),
    ('IFERROR(FIXED(5,5,"x"="x"),"E")', '5.00000'),
    ('FIXED(DATE(1899,12,30),-2,ISBLANK(SUM(Facts[Sales])))', '0'),
    ('FIXED(-0.5,1,FALSE())', '-0.5'),
    ('FIXED(SUM(Facts[Sales]),10,0=1)', '31.5000000000'),
    ('FIXED(0,3)', '0.000'),
    ('FIXED(CEILING(CURRENCY(1.23456),0),10,COUNTROWS(Facts)>3)', '0.0000000000'),
    ('FIXED(SUM(Facts[Sales]),10,1)', '31.5000000000'),
    ('IFERROR(FIXED(DATE(9999,12,31),1,SUM(Facts[Sales])>0),"E")', '2958465.0'),
    ('FIXED(FLOOR(CURRENCY(123456789.123),"12"),3)', '123,456,780.000'),
    ('IFERROR(FIXED(ISO.CEILING("1.5"),-2,1),"E")', '0'),
    ('FIXED(-2,-1,COUNTROWS(Facts)>3)', '0'),
    ('FIXED("12",0.5,TRUE())', '12.0'),
    ('FIXED(TRUNC(COUNTROWS(Facts)),-2,0=1)', '0'),
    ('FIXED(TRUNC(MAX(Facts[Sales])),-1)', '20'),
    ('FIXED(TIME(13,5,0),0.5,COUNTROWS(Facts)>3)', '0.5'),
    ('FIXED(TIME(13,5,0),2)', '0.55'),
    ('FIXED(123456789.123,1)', '123,456,789.1'),
    ('IFERROR(FIXED(CURRENCY(DATE(9999,12,31)),5),"E")', '2,958,465.00000'),
    ('IFERROR(FIXED("1.5",-3,"a"),"E")', 'E'),
    ('FIXED(BLANK(),0.5)', '0.0'),
    ('IFERROR(FIXED(TRUNC(2.5),10),"E")', '2.0000000000'),
    ('FIXED(DATE(2020,2,29),-2,1)', '43900'),
    ('IFERROR(FIXED(FLOOR(TRUNC(AVERAGE(Facts[Quantity]),0),3),1),"E")', '0.0'),
    ('FIXED(ODD(MAX(Facts[Sales])),-1)', '20'),
    ('FIXED("12",-2,COUNTROWS(Facts)>3)', '0'),
    ('FIXED(ODD(ISO.CEILING(-3)),10)', '-3.0000000000'),
    ('FIXED(5,10)', '5.0000000000'),
]

# Family G: SUBSTITUTE with instance_num 0, a negative or BLANK() is an error; fractional instances round half up
FAMILY_G = [
    ('IFERROR(SUBSTITUTE("aaa","a","b",0),"E")', 'E'),
    ('SUBSTITUTE("6.00E+00","","12",0)', 'ERR'),
    ('SUBSTITUTE("aaa","","b",0)', 'ERR'),
    ('SUBSTITUTE("aaa","","b",1)', 'aaa'),
    ('SUBSTITUTE("aaa","a","b","2")', 'aba'),
    ('SUBSTITUTE("aaa","a","b",-1)', 'ERR'),
    ('SUBSTITUTE("aaa","a","b",0)', 'ERR'),
    ('SUBSTITUTE("aaa","a","b",0.5)', 'baa'),
    ('SUBSTITUTE("aaa","a","b",1.9)', 'aba'),
    ('SUBSTITUTE("aaa","a","b",4)', 'aaa'),
    ('SUBSTITUTE("aaa","a","b",BLANK())', 'ERR'),
    ('SUBSTITUTE("2020-02-29",FORMAT(DATE(2020,2,29),"yyyy"),CONCATENATEX(Facts,Facts[Region],","))', 'East,East,East,West,West,North-02-29'),
    ('SUBSTITUTE("12","a,b",MIN(Facts[Note]))', '12'),
    ('SUBSTITUTE(MAX(Facts[Region]),TRIM(UPPER("-0.5")),FORMAT(TIME(13,5,0),"0.00"),2)', 'West'),
    ('UNICODE(SUBSTITUTE("Paid",RIGHT(FORMAT(DATE(2020,2,29),"yyyy"),-2),"x"&"y",1))', 'ERR'),
    ('SUBSTITUTE("12",TRIM("East"),FORMAT(DATE(2020,2,29),"yyyy"),3)', '12'),
    ('SUBSTITUTE("Paid"&SEARCH("Paid","1E15"),"1E15",FORMAT(2.5,"Fixed"),2)', 'ERR'),
    ('LOWER(SUBSTITUTE(MIN(Facts[Note]),"East","-0.5",0.5))', 'late'),
    ('SUBSTITUTE(FORMAT(DATE(2020,2,29),"yyyy"),"abc","  pad  ")', '2020'),
    ('SUBSTITUTE(CONCATENATEX(FILTER(Facts,Facts[Sales]>=2.5),Facts[Region],BLANK()),CONCATENATEX(FILTER(Facts,Facts[Sales]>=2.5),Facts[Region],CONCATENATE("2020-02-29","-0.5")),FORMAT(DATE(2020,2,29),"yyyy"))', 'EastEastWest'),
    ('SUBSTITUTE("  pad  ","Ünï",MAX(Facts[Region]),1)', '  pad  '),
    ('IFERROR(SUBSTITUTE(MIN(Facts[Note]),MAX(Facts[Region]),"  pad  ",3),"E")', 'Late'),
    ('SUBSTITUTE(BLANK(),"-0.5"&"abc","x"&"y",1)', 'BLANK'),
    ('SUBSTITUTE(REPLACE(BLANK(),5,2,MID("2020-02-29",0,0.5)),"1.5",CONCATENATEX(Facts,Facts[Region],","),2)', 'ERR'),
    ('SUBSTITUTE("1.5",FORMAT(DATE(1899,12,30),"yyyy-mm-dd"),"-0.5")', '1.5'),
    ('REPLACE(SUBSTITUTE("x"&"y","Ünï","Ünï",10),0,-3,BLANK())', 'ERR'),
    ('SUBSTITUTE(FORMAT(VALUE(123456789.123),"#,##0.00"),CONCATENATEX(Facts,Facts[Region],","),"Ünï")', '123,456,789.12'),
    ('IFERROR(SUBSTITUTE(SUBSTITUTE("Paid","Paid","1E15"),"  pad  ",FORMAT(0,"0.00")),"E")', '1E15'),
    ('SUBSTITUTE("a,b","12","1E15")', 'a,b'),
    ('"a,b"&SUBSTITUTE("","-0.5","1.5"&"1.5",-2)', 'ERR'),
    ('EXACT("East",SUBSTITUTE(LEFT("-0.5",3),"-0.5",FORMAT(COUNTROWS(Facts),"0%")))', 'False'),
    ('SUBSTITUTE(SUBSTITUTE("abc","1E15","x"&"y"),"-0.5","East",0.5)', 'abc'),
    ('SUBSTITUTE(CONCATENATEX(FILTER(Facts,Facts[Sales]>0),Facts[Note],"2020-02-29"),MIN(Facts[Note]),"-0.5")', '2020-02-292020-02-29Paid'),
    ('SUBSTITUTE("1E15","abc",FORMAT(DATE(2020,2,29),"yyyy"))', '1E15'),
    ('SUBSTITUTE("1E15","12",FORMAT(DATE(2020,2,29),"yyyy"))', '1E15'),
    ('UNICODE(SUBSTITUTE("Ünï","12","x"&"y",-2))', 'ERR'),
    ('FORMAT(SEARCH("  pad  ",SUBSTITUTE("","abc",CONCATENATEX(Facts,Facts[Region],","),5),-3,3),"#,##0.00")', 'ERR'),
    ('UNICODE(SUBSTITUTE(FORMAT(COUNTROWS(Facts),"0.00E+00"),"","12",0))', 'ERR'),
]


class HuntBatchOneFamilies(unittest.TestCase):
    def _check_family(self, rows, label):
        failures = []
        for expr, expected in rows:
            local = dax.local(expr)
            if not _same(expected, local):
                failures.append(f"{expr} | power bi {expected} | local {local[:80]}")
        self.assertEqual(failures, [], f"{label}: {len(failures)} of {len(rows)} differ")

    def test_family_a_topnskip(self):
        self._check_family(FAMILY_A, "TOPNSKIP")

    def test_family_b_rank_rownumber_whole_table(self):
        self._check_family(FAMILY_B, "RANK / ROWNUMBER")

    def test_family_c_earlier_without_outer_row(self):
        self._check_family(FAMILY_C, "EARLIER / EARLIEST")

    def test_family_d_currentgroup_outside_groupby(self):
        self._check_family(FAMILY_D, "CURRENTGROUP")

    def test_family_e_blank_date_shift(self):
        self._check_family(FAMILY_E, "EDATE / EOMONTH of BLANK")

    def test_family_f_fixed_negative_zero(self):
        self._check_family(FAMILY_F, "FIXED")

    def test_family_g_substitute_instance(self):
        self._check_family(FAMILY_G, "SUBSTITUTE")

    def test_named_cases(self):
        self.assertEqual(dax.local('CONCATENATEX(TOPNSKIP(2,0,Facts,Facts[Region],ASC),Facts[Quantity],",")'), "2,1")
        self.assertEqual(dax.local("FIXED(-0.4,0)"), "0")
        self.assertEqual(dax.local("FIXED(-0.0001,2)"), "0.00")
        self.assertTrue(dax.local('SUBSTITUTE("aaa","a","b",0)').startswith("LOCAL-REJECT"))
        self.assertTrue(dax.local("CURRENTGROUP()").startswith("LOCAL-REJECT"))


class Task143ReviewFixes(unittest.TestCase):
    """Review fixes (values from the hidden Power BI hold-out set)."""

    def _rejects(self, expr):
        self.assertTrue(dax.local(expr).startswith("LOCAL-REJECT"), expr)

    def test_topnskip_two_order_columns_is_an_error(self):
        for n in ("4", "6", "10", "0.49", "-4", "FALSE()", '"-1"'):
            self._rejects(f"COUNTROWS(TOPNSKIP({n},1,Facts,Facts[Note],DESC,Facts[Quantity],ASC))")
        self.assertEqual(dax.local("COUNTROWS(TOPNSKIP(4,1,Facts,Facts[Quantity],DESC))"), "4")

    def test_earlier_in_addcolumns_without_outer_row(self):
        self._rejects('COUNTROWS(ADDCOLUMNS(Facts,"a",EARLIER(Facts[Quantity])))')
        self._rejects('COUNTROWS(ADDCOLUMNS(Facts,"a",EARLIEST(Facts[Quantity])))')
        self._rejects('COUNTROWS(ADDCOLUMNS(Facts,"a",CALCULATE(COUNTROWS(Facts),Facts[Region]=EARLIER(Facts[Region],2))))')
        self.assertEqual(dax.local('SUMX(ADDCOLUMNS(Facts,"n",CALCULATE(COUNTROWS(Facts),Facts[Region]=EARLIER(Facts[Region]))),[n])'), "6")
        self.assertEqual(dax.local('COUNTROWS(ADDCOLUMNS(Facts,"a",SUMX(Facts,EARLIER(Facts[Quantity]))))'), "6")

    def test_allselected_rank_keeps_the_iterated_rows(self):
        self.assertEqual(dax.local('SUMX(FILTER(Facts,Facts[Note]="Paid"),ROWNUMBER(ALLSELECTED(Facts),ORDERBY(Facts[Sales],DESC)))'), "6")
        self.assertEqual(dax.local('SUMX(FILTER(Facts,Facts[Quantity]<4),ROWNUMBER(ALLSELECTED(Facts),ORDERBY(Facts[Sales],DESC)))'), "10")
        self.assertEqual(dax.local('PRODUCTX(FILTER(Facts,Facts[Region]<>"East"),ROWNUMBER(ALLSELECTED(Facts),ORDERBY(Facts[Sales],DESC)))'), "6")
        self.assertEqual(dax.local('MINX(FILTER(Facts,Facts[Note]="Paid"),ROWNUMBER(ALLSELECTED(Facts),ORDERBY(Facts[Sales],DESC)))'), "1")


class Task143Spec2Ties(unittest.TestCase):
    """Task 143 spec2 (fresh Power BI probe): DESC ties come in reverse table order, ASC ties in table order; an expression ORDER BY,
    a negative count over FILTER, and a text or fractional skip are handled as measured. Values are the Power BI rows."""

    CONCAT = ',Facts[Quantity]&Facts[Note],";")'

    def _pbi(self, call, expected):
        self.assertEqual(dax.local("CONCATENATEX(" + call + ")" + self.CONCAT), expected, call)

    def _rejects(self, expr):
        self.assertTrue(dax.local(expr).startswith("LOCAL-REJECT"), expr)

    def test_desc_ties_come_in_reverse_table_order(self):
        self._pbi('TOPNSKIP("3",1,Facts,Facts[Region],DESC', "3;4Late;5")
        self._pbi('TOPNSKIP("3",3,ALL(Facts),Facts[Region],DESC', "5;1Paid;2Paid")
        self._pbi('TOPNSKIP(1.5,1,ALL(Facts),Facts[Region],DESC', "3;4Late")
        self._pbi('TOPNSKIP(1.5,5,Facts,Facts[Region],DESC', "2Paid")
        self._pbi('TOPNSKIP(1.5,BLANK(),Facts,Facts[Region],DESC', "0Paid;3")
        self._pbi('TOPNSKIP(5,-5,Facts,Facts[Region],DESC', "0Paid;3;4Late;5;1Paid")
        self._pbi('TOPNSKIP(5,2,FILTER(Facts,Facts[Quantity]>0),Facts[Region],DESC', "5;1Paid;2Paid")
        self._pbi('TOPNSKIP(5,BLANK(),ALL(Facts),Facts[Region],DESC', "0Paid;3;4Late;5;1Paid")
        self._pbi('TOPNSKIP(TRUE(),-5,ALL(Facts),Facts[Region],DESC', "0Paid")
        self._pbi('TOPNSKIP(-5,1,ALL(Facts),Facts[Region],DESC', "3;4Late;5;1Paid;2Paid")
        self._pbi('TOPNSKIP(-1,3,Facts,Facts[Region],DESC', "5;1Paid;2Paid")

    def test_asc_ties_keep_table_order(self):
        self._pbi('TOPNSKIP(3,1,ALL(Facts),Facts[Note],ASC', "5;4Late;2Paid")
        self._pbi('TOPNSKIP(0.7,1,Facts,Facts[Note],ASC', "5")
        self._pbi('TOPNSKIP(1.5,BLANK(),Facts,Facts[Note],ASC', "3;5")
        self._pbi('TOPNSKIP(2.5,2,Facts,Facts[Note],ASC', "4Late;2Paid;1Paid")

    def test_expression_order_by_is_refused(self):
        for call in (
            "TOPNSKIP(3,-5,FILTER(Facts,Facts[Quantity]>0),Facts[Sales]*-1)",
            "TOPNSKIP(5,0,ALL(Facts),Facts[Sales]*-1)",
            "TOPNSKIP(-1,0,FILTER(Facts,Facts[Quantity]>0),Facts[Sales]*-1)",
            "TOPNSKIP(0.7,-5,FILTER(Facts,Facts[Quantity]>0),Facts[Sales]*-1)",
            "TOPNSKIP(1,2,FILTER(Facts,Facts[Quantity]>0),Facts[Sales]*-1)",
        ):
            self._rejects("CONCATENATEX(" + call + self.CONCAT)

    def test_negative_count_over_filter_is_refused(self):
        self._rejects('CONCATENATEX(TOPNSKIP(-5,"3",FILTER(Facts,Facts[Quantity]>0),Facts[Region],DESC)' + self.CONCAT)
        self._rejects('CONCATENATEX(TOPNSKIP(-1,-1,FILTER(Facts,Facts[Quantity]>0),Facts[Region],DESC)' + self.CONCAT)
        self._rejects('CONCATENATEX(TOPNSKIP(-5,2.5,FILTER(Facts,Facts[Quantity]>0),Facts[Quantity])' + self.CONCAT)
        self._rejects('CONCATENATEX(TOPNSKIP(-1,-5,FILTER(Facts,Facts[Quantity]>0),Facts[Note],ASC)' + self.CONCAT)


if __name__ == "__main__":
    unittest.main()
