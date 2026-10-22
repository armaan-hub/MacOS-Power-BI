"""Models of Critic 3 (iteration 81): ZB bidirectional star, ZO orphan and blank keys, ZS snowflake with two facts, ZM one-to-one and
many-to-many, built the way Power BI Desktop holds them (live answers in tests/fixtures_critic3_models.json).

Tables hold text, whole numbers, decimals and dates; text is normalised to its first spelling like the app does."""
from __future__ import annotations

import datetime
from typing import Any

from analytics_studio import dax_dates
from analytics_studio.measures import MeasureError, evaluate_measures
from analytics_studio.power_query_values import model_text_normalizer
from tools.dax_oracle_diff import HEADERS, LOCAL_ROWS

CAL_EXPR='ADDCOLUMNS(CALENDAR(DATE(2023,1,1),DATE(2024,12,31)),"Year",YEAR([Date]),"MonthNo",MONTH([Date]),"Day",DAY([Date]))'
CAL_COLS=[('Date','dateTime'),('Year','int64'),('MonthNo','int64'),('Day','int64')]
DIM_COLS=[('Prod','string'),('Cat','string'),('Grp','string')]
DIM_ROWS=[('P1','A','X'),('P2','A','Y'),('P3','B','X'),('P4','B','Y'),('P5','C','X')]
FACT_COLS=[('Id','int64'),('Prod','string'),('Dt','dateTime'),('Ship','dateTime'),('Amt','double'),('Qty','int64'),('Reg','string')]

# ZO: orphans / blank keys on the many side
ZO_FACT=[
 (1,'P1',(2023,1,15),(2023,1,20),10.0,2,'East'),
 (2,'P1',(2023,2,10),(2023,2,12),20.0,3,'West'),
 (3,'P2',(2023,2,10),(2023,3,1),30.0,1,'West'),
 (4,'P2',(2024,1,5),(2024,1,9),40.0,4,'East'),
 (5,'P3',(2024,2,20),(2024,2,25),50.0,5,'East'),
 (6,'P9',(2024,3,15),(2024,3,20),60.0,2,'North'),   # orphan product
 (7,None,(2024,3,15),(2024,4,1),None,3,'North'),   # blank product
 (8,'P4',(2025,3,1),(2023,1,15),70.0,6,'East'),     # date outside the calendar
 (9,'P1',None,(2024,1,6),15.0,2,'East'),            # blank date
 (10,'P9',(2024,1,5),(2024,1,6),15.0,2,'East'),
 (11,'P5',(2024,2,10),(2024,2,11),5.0,1,'West'),
 (12,'P2',(2023,12,31),(2024,1,2),25.0,7,'East'),
 (13,'P3',(2024,12,31),(2024,12,31),35.0,1,'North'),
]
# ZS: snowflake Fact -> Dim -> Sup -> Reg, Fact2 -> Dim, both facts -> Cal
ZS_REG=([('Region','string'),('Zone','string')],[('R1','Z1'),('R2','Z1'),('R3','Z2')])
ZS_SUP=([('Cat','string'),('Sup','string'),('Region','string')],[('A','S1','R1'),('B','S1','R2'),('C','S2','R3')])
ZS_FACT=([('Id','int64'),('Prod','string'),('Dt','dateTime'),('Amt','double'),('Qty','int64')],[
 (1,'P1',(2023,1,15),10.0,2),(2,'P1',(2023,2,10),20.0,3),(3,'P2',(2023,2,10),30.0,1),(4,'P2',(2024,1,5),40.0,4),
 (5,'P3',(2024,2,20),50.0,5),(6,'P3',(2024,3,15),60.0,2),(7,'P4',(2024,3,15),None,3),(8,'P4',(2023,1,15),70.0,6),
 (9,'P1',(2024,1,5),15.0,2),(10,'P5',(2024,2,10),5.0,1)])
ZS_FACT2=([('Id','int64'),('Prod','string'),('Dt','dateTime'),('Amt','double')],[
 (101,'P1',(2024,1,5),1.0),(102,'P2',(2024,2,5),2.0),(103,'P2',(2023,6,5),4.0),(104,'P5',(2023,6,6),8.0),(105,'P3',(2024,7,1),16.0)])
# ZM: many-to-many, one-to-one, one-to-many oriented from the one side
ZM_A=([('Id','int64'),('K','string'),('V','double')],[(1,'k1',10.0),(2,'k1',20.0),(3,'k2',30.0),(4,'k3',40.0),(5,'k3',50.0),(6,'k4',60.0)])
ZM_B=([('K','string'),('N','string')],[('k1','n1'),('k1','n1b'),('k2','n2'),('k5','n5')])
ZM_U=([('K','string'),('X','string')],[('k1','x1'),('k2','x2'),('k3','x3'),('k4','x4')])
ZM_W=([('K','string'),('Y','string')],[('k1','y1'),('k2','y2'),('k3','y3'),('k5','y5')])
ZM_F=([('Id','int64'),('K','string'),('Amt','double')],[(1,'k1',1.0),(2,'k1',2.0),(3,'k2',4.0),(4,'k3',8.0),(5,'k4',16.0),(6,'k9',32.0)])
ZM_F2=([('Id','int64'),('K','string'),('Amt','double')],[(1,'k1',100.0),(2,'k2',200.0),(3,'k2',300.0),(4,'k4',400.0)])

# relationship tuples: name, from table, from col, to table, to col, active, both, fromCard, toCard
SPEC={
 'ZO':{'tables':{'ZO_Dim':(DIM_COLS,DIM_ROWS),'ZO_Fact':(FACT_COLS,ZO_FACT),'ZO_Cal':(CAL_COLS,None)},
       'rels':[('ZO_r1','ZO_Fact','Prod','ZO_Dim','Prod',True,False,'many','one'),
               ('ZO_r2','ZO_Fact','Dt','ZO_Cal','Date',True,False,'many','one'),
               ('ZO_r3','ZO_Fact','Ship','ZO_Cal','Date',False,False,'many','one')]},
 'ZS':{'tables':{'ZS_Reg':ZS_REG,'ZS_Sup':ZS_SUP,'ZS_Dim':(DIM_COLS,DIM_ROWS),'ZS_Fact':ZS_FACT,'ZS_Fact2':ZS_FACT2,'ZS_Cal':(CAL_COLS,None)},
       'rels':[('ZS_r1','ZS_Fact','Prod','ZS_Dim','Prod',True,False,'many','one'),
               ('ZS_r2','ZS_Dim','Cat','ZS_Sup','Cat',True,False,'many','one'),
               ('ZS_r3','ZS_Sup','Region','ZS_Reg','Region',True,False,'many','one'),
               ('ZS_r4','ZS_Fact2','Prod','ZS_Dim','Prod',True,True,'many','one'),
               ('ZS_r5','ZS_Fact','Dt','ZS_Cal','Date',True,False,'many','one'),
               ('ZS_r6','ZS_Fact2','Dt','ZS_Cal','Date',True,False,'many','one')]},
 'ZM':{'tables':{'ZM_A':ZM_A,'ZM_B':ZM_B,'ZM_U':ZM_U,'ZM_W':ZM_W,'ZM_F':ZM_F,'ZM_F2':ZM_F2},
       'rels':[('ZM_r1','ZM_A','K','ZM_B','K',True,False,'many','many'),
               ('ZM_r2','ZM_U','K','ZM_W','K',True,True,'one','one'),
               ('ZM_r3','ZM_F','K','ZM_U','K',True,False,'many','one'),
               ('ZM_r4','ZM_F2','K','ZM_U','K',True,False,'many','one')]},
}

ZB_FACT=[(i,p,d,sd,a,q,r) for (i,p,d,sd,a,q,r) in [
 (1,'P1',(2023,1,15),(2023,1,20),10.0,2,'East'),(2,'P1',(2023,2,10),(2023,2,12),20.0,3,'West'),(3,'P2',(2023,2,10),(2023,3,1),30.0,1,'West'),
 (4,'P2',(2024,1,5),(2024,1,9),40.0,4,'East'),(5,'P3',(2024,2,20),(2024,2,25),50.0,5,'East'),(6,'P3',(2024,3,15),(2024,3,20),60.0,2,'North'),
 (7,'P4',(2024,3,15),(2024,4,1),None,3,'North'),(8,'P4',(2023,1,15),(2023,1,15),70.0,6,'East'),(9,'P1',(2024,1,5),(2024,1,6),15.0,2,'East'),
 (10,'P5',(2024,2,10),(2024,2,11),5.0,1,'West')]]
ZB_REG=([('Reg','string'),('Zone','string')],[('East','Z1'),('West','Z1'),('North','Z2'),('South','Z2')])
SPEC['ZB']={'tables':{'ZB_Dim':(DIM_COLS,DIM_ROWS),'ZB_Reg':ZB_REG,'ZB_Fact':(FACT_COLS,ZB_FACT),'ZB_Cal':(CAL_COLS,None)},
 'rels':[('ZB_r1','ZB_Fact','Prod','ZB_Dim','Prod',True,True,'many','one'),
         ('ZB_r2','ZB_Fact','Reg','ZB_Reg','Reg',True,True,'many','one'),
         ('ZB_r3','ZB_Fact','Dt','ZB_Cal','Date',True,False,'many','one'),
         ('ZB_r4','ZB_Fact','Ship','ZB_Cal','Date',False,False,'many','one')]}
def cal_rows():
    out=[]; d=datetime.date(2023,1,1)
    while d<=datetime.date(2024,12,31):
        out.append((d.year,d.month,d.day)); d+=datetime.timedelta(days=1)
    return out

SPEC['ZT']={'tables':SPEC['ZS']['tables'],'rels':[(r[0],r[1],r[2],r[3],r[4],r[5],False if r[0]=='ZS_r4' else r[6],r[7],r[8]) for r in SPEC['ZS']['rels']]}


_TYPES = {"string": "text", "int64": "whole_number", "double": "decimal_number", "dateTime": "date"}
_FACTS = {"id": "facts", "name": "Facts", "headers": HEADERS, "rows": LOCAL_ROWS,
          "column_types": {"Sales": "decimal_number", "Quantity": "whole_number", "Region": "text", "Note": "text"}}


def _iso(day: tuple[int, int, int] | None) -> str | None:
    return None if day is None else "%04d-%02d-%02d" % day


def _table(name: str, columns: list[tuple[str, str]], rows: list[tuple[Any, ...]] | None) -> dict[str, Any]:
    headers = [column for column, _kind in columns]
    if rows is None:  # the calendar
        data = [{"Date": "%04d-%02d-%02d" % day, "Year": str(day[0]), "MonthNo": str(day[1]), "Day": str(day[2])} for day in cal_rows()]
        return {"id": name.lower(), "name": name, "date_column": "Date", "headers": headers, "rows": data,
                "column_types": {"Date": "date", "Year": "whole_number", "MonthNo": "whole_number", "Day": "whole_number"}}
    normalisers = {column: model_text_normalizer() for column, kind in columns if kind == "string"}
    data = []
    for row in rows:
        cells = {}
        for (column, kind), value in zip(columns, row):
            value = _iso(value) if kind == "dateTime" else None if value is None else str(value)
            if kind == "string" and value is not None:
                value = normalisers[column](value)
            cells[column] = value
        data.append(cells)
    return {"id": name.lower(), "name": name, "headers": headers, "rows": data, "column_types": {column: _TYPES[kind] for column, kind in columns}}


def _relationship(spec: tuple[Any, ...]) -> dict[str, Any]:
    name, from_table, from_column, to_table, to_column, active, both, from_card, to_card = spec
    cardinality = {("many", "one"): "many_to_one", ("one", "one"): "one_to_one", ("many", "many"): "many_to_many", ("one", "many"): "one_to_many"}[(from_card, to_card)]
    return {"relationship_version": 1, "id": name, "from": from_column, "to": to_column, "from_table_id": from_table.lower(),
            "from_column": from_column, "to_table_id": to_table.lower(), "to_column": to_column, "cardinality": cardinality,
            "is_active": active, "cross_filter_direction": "both" if both or cardinality == "one_to_one" else "single"}


_ROLES = {"ZB": ("ZB_Fact", "ZB_Dim", "ZB_Cal"), "ZO": ("ZO_Fact", "ZO_Dim", "ZO_Cal"), "ZS": ("ZS_Fact", "ZS_Dim", "ZS_Cal"), "ZT": ("ZS_Fact", "ZS_Dim", "ZS_Cal")}
_MEASURES = {
    "mSum": "SUM({F}[Amt])", "mCnt": "COUNTROWS({F})",
    "mShareCat": "DIVIDE([mSum],CALCULATE([mSum],ALLSELECTED({D}[Cat])))", "mShareAll": "DIVIDE([mSum],CALCULATE([mSum],ALLSELECTED()))",
    "mShareDim": "DIVIDE([mSum],CALCULATE([mSum],ALLSELECTED({D})))", "mRank": "RANKX(ALLSELECTED({D}[Prod]),[mSum])",
    "mSel": "CALCULATE([mSum],ALLSELECTED({D}[Prod]))", "mAllF": "CALCULATE([mSum],ALL({F}))", "mAllD": "CALCULATE([mSum],ALL({D}))",
    "mAllC": "CALCULATE([mSum],ALL({C}))", "mExcP": "CALCULATE([mSum],ALLEXCEPT({F},{F}[Prod]))", "mYtd": "TOTALYTD([mSum],{C}[Date])",
    "mDimRows": "COUNTROWS({D})", "mTrans": "SUMX({F},CALCULATE(COUNTROWS({D})))", "mRem": "CALCULATE([mSum],REMOVEFILTERS({F}))",
}
_built: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]] = {}


def build(model: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if model not in _built:
        spec = SPEC[model]
        tables = [_FACTS] + [_table(name, columns, rows) for name, (columns, rows) in spec["tables"].items()]
        roles = _ROLES.get(model)
        measures = [{"name": key, "expression": text.format(F=roles[0], D=roles[1], C=roles[2]), "home_table_id": roles[0].lower()}
                    for key, text in _MEASURES.items()] if roles else []
        _built[model] = (tables, [_relationship(spec_rel) for spec_rel in spec["rels"]], measures)
    return _built[model]


def ours_for(model: str, expression: str) -> str:
    tables, relationships, measures = build(model)
    home = measures[0]["home_table_id"] if measures else "facts"
    try:
        value = evaluate_measures(
            measures + [{"name": "P__", "expression": expression, "home_table_id": home}], LOCAL_ROWS, HEADERS, "Facts",
            measure_names=["P__"], table_context=tables, relationships=relationships, active_table_id="facts",
        )["P__"]
    except MeasureError as error:
        return f"LOCAL-REJECT:{error}"
    except Exception as error:  # an evaluator crash is a failure of its own
        return f"LOCAL-CRASH:{type(error).__name__}:{error}"
    if isinstance(value, dax_dates.DaxDateTime):
        return dax_dates.oracle_text(value)
    return "BLANK" if value is None else str(value)
