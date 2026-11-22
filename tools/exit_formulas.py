"""Exit-test formula list for the XT_ model (Phase 1.2).

Writes tools/parity/exit_formulas.json: a list of {"id", "group", "expr"}.
Every expr is ONE scalar DAX expression (the runner wraps it as EVALUATE ROW("v", <expr>)).
Formulas are written out here as real-world patterns; this file holds NO answers.
A base expression is evaluated under several filter contexts by wrapping it in
CALCULATE(<base>, <filters>); the "all" context means no wrapper.
Run: PYTHONPATH=. python tools/exit_formulas.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "parity" / "exit_formulas.json"

# ---- filter contexts (each key is a list of CALCULATE filter arguments; "a+b" combines) ----
CTX: dict[str, list[str]] = {
    "all": [],
    "y23": ["XT_Date[Year] = 2023"],
    "y24": ["XT_Date[Year] = 2024"],
    "y26": ["XT_Date[Year] = 2026"],
    "m2301": ["XT_Date[Year] = 2023", "XT_Date[MonthNumber] = 1"],
    "m2403": ["XT_Date[Year] = 2024", "XT_Date[MonthNumber] = 3"],
    "q24Q2": ["XT_Date[Year] = 2024", 'XT_Date[Quarter] = "Q2"'],
    "ym": ["XT_Date[YearMonth] = 202403"],
    "d": ["XT_Date[Date] = DATE(2024, 3, 15)"],
    "cat": ['XT_Product[Category] = "Cat_2"'],
    "sub": ['XT_Product[Subcategory] = "Subcat_4"'],
    "p7": ['XT_Product[Product] = "Product_7"'],
    "reg": ['XT_Region[Region] = "North"'],
    "seg": ['XT_Customer[Segment] = "Corporate"'],
    "cust": ['XT_Customer[Customer] = "Customer_10"'],
    "chan": ['XT_Sales[Channel] = "Online"'],
    "none": ['XT_Product[Product] = "No Such Product"'],
}

S = "SUM(XT_Sales[SalesAmount])"
Q = "SUM(XT_Sales[Quantity])"
N = "COUNTROWS(XT_Sales)"
CUS = "DISTINCTCOUNT(XT_Sales[CustomerKey])"
D = "XT_Date[Date]"

ITEMS: list[dict[str, str]] = []
_COUNTS: dict[str, int] = {}


def _filters(key: str) -> list[str]:
    out: list[str] = []
    for part in key.split("+"):
        out += CTX[part]
    return out


def wrap(base: str, key: str) -> str:
    fs = _filters(key)
    return base if not fs else f"CALCULATE({base}, {', '.join(fs)})"


def add(group: str, base: str, keys: list[str]) -> None:
    for key in keys:
        _COUNTS[group] = _COUNTS.get(group, 0) + 1
        ITEMS.append({"id": f"XT-{group}-{_COUNTS[group]:03d}", "group": group, "expr": wrap(base, key)})


def raw(group: str, exprs: list[str]) -> None:
    for e in exprs:
        _COUNTS[group] = _COUNTS.get(group, 0) + 1
        ITEMS.append({"id": f"XT-{group}-{_COUNTS[group]:03d}", "group": group, "expr": e})


def retire(group: str) -> None:
    """Burn the next id in a group without an item, so later ids never renumber."""
    _COUNTS[group] = _COUNTS.get(group, 0) + 1


# =============================================================== AG aggregates
add("AG", S, ["all","y24","none"])
add("AG", Q, ["all","reg"])
add("AG", "AVERAGE(XT_Sales[UnitPrice])", ["all","none"])
add("AG", N, ["all","seg","none"])
add("AG", "COUNT(XT_Sales[CustomerKey])", ["all"])
add("AG", CUS, ["all", "cat", "none"])
add("AG", "DISTINCTCOUNT(XT_Sales[ProductKey])", ["all","none"])
add("AG", "MIN(XT_Sales[OrderDate])", ["reg"])
add("AG", "MAX(XT_Sales[ShipDate])", ["all"])
add("AG", "SUMX(XT_Sales, XT_Sales[Quantity] * XT_Sales[UnitPrice])", ["all", "none"])
add("AG", "SUMX(XT_Sales, XT_Sales[Quantity] * XT_Sales[UnitPrice] * (1 - XT_Sales[Discount]))", ["seg"])
add("AG", "AVERAGEX(XT_Sales, XT_Sales[SalesAmount] / XT_Sales[Quantity])", ["reg"])
add("AG", "MAXX(XT_Sales, XT_Sales[SalesAmount])", ["all", "none"])
add("AG", "MINX(XT_Sales, XT_Sales[Discount])", ["y24"])
add("AG", "COUNTA(XT_Sales[ShipDate])", ["all"])
add("AG", "COUNTBLANK(XT_Sales[ShipDate])", ["cat"])
add("AG", "DISTINCTCOUNTNOBLANK(XT_Sales[CustomerKey])", ["all"])
add("AG", "AVERAGE(XT_Sales[Discount])", ["y24"])
raw("AG", [
    "GEOMEANX(XT_Sales, XT_Sales[UnitPrice])",
    "COUNTX(XT_Sales, XT_Sales[ShipDate])",
    "PRODUCTX(VALUES(XT_Region[RegionKey]), XT_Region[RegionKey])",
])

# =============================================================== CA CALCULATE and filter functions
add("CA", f"CALCULATE({S}, XT_Product[Category] = \"Cat_1\")", ["all","cat","none"])
add("CA", f"CALCULATE({S}, XT_Region[Region] = \"North\", XT_Product[Category] = \"Cat_3\")", ["seg"])
add("CA", f"CALCULATE({S}, XT_Product[Category] IN {{\"Cat_1\", \"Cat_2\"}})", ["all","reg"])
add("CA", f"CALCULATE({S}, XT_Product[Category] = \"Cat_1\" || XT_Product[Category] = \"Cat_2\")", ["y24"])
add("CA", f"CALCULATE({S}, XT_Sales[Quantity] > 10)", ["cat"])
add("CA", f"CALCULATE({S}, FILTER(XT_Sales, XT_Sales[Quantity] > 10 && XT_Sales[Discount] > 0.1))", ["cat"])
add("CA", f"CALCULATE({S}, FILTER(ALL(XT_Sales[Channel]), XT_Sales[Channel] <> \"Store\"))", ["reg"])
add("CA", f"CALCULATE({S}, ALL(XT_Product))", ["reg+y24"])
add("CA", f"CALCULATE({S}, ALL(XT_Date))", ["m2403"])
add("CA", f"CALCULATE({S}, ALLEXCEPT(XT_Date, XT_Date[Year]))", ["m2403+cat"])
add("CA", f"CALCULATE({S}, ALLEXCEPT(XT_Product, XT_Product[Category]))", ["sub", "cat+sub"])
add("CA", f"CALCULATE({S}, REMOVEFILTERS(XT_Region))", ["reg+y24"])
add("CA", f"CALCULATE({S}, REMOVEFILTERS(XT_Product[Category]))", ["cat"])
add("CA", f"CALCULATE({S}, ALLSELECTED(XT_Product))", ["cat"])
add("CA", f"CALCULATE({S}, ALLSELECTED(XT_Date[Year]))", ["y24"])
add("CA", f"CALCULATE({S}, KEEPFILTERS(XT_Product[Category] = \"Cat_1\"))", ["cat"])
add("CA", f"CALCULATE({S}, KEEPFILTERS(XT_Product[Category] IN {{\"Cat_2\", \"Cat_3\"}}))", ["cat"])
raw("CA", [
    f"CALCULATE(CALCULATE({S}, XT_Date[Year] = 2024), XT_Date[Year] = 2023)",
    f"CALCULATE(CALCULATE({S}, XT_Date[Year] = 2024), XT_Date[MonthNumber] = 3)",
])
add("CA", f"CALCULATE({S}, VALUES(XT_Product[Category]))", ["cat"])
add("CA", f"CALCULATE({S}, XT_Product[Category] <> \"Cat_1\")", ["y24"])
add("CA", f"CALCULATE({S}, XT_Sales[Channel] = \"Online\", XT_Sales[Discount] >= 0.2)", ["y24"])
add("CA", f"CALCULATE({N}, XT_Sales[Channel] = \"Online\")", ["reg"])
add("CA", f"CALCULATE({CUS}, XT_Sales[Channel] = \"Online\")", ["y24"])
add("CA", f"CALCULATE({S}, ALL(XT_Customer[Segment]))", ["seg"])
add("CA", f"CALCULATE({S}, ALL(XT_Sales[Channel]))", ["chan"])
raw("CA", [
    f"COUNTROWS(CALCULATETABLE(XT_Sales, XT_Sales[Channel] = \"Partner\", XT_Date[Year] = 2025))",
    f"SUMX(CALCULATETABLE(XT_Sales, XT_Product[Category] = \"Cat_4\"), XT_Sales[SalesAmount])",
    f"CALCULATE({S}, FILTER(ALL(XT_Product[Product]), CONTAINSSTRING(XT_Product[Product], \"_1\")))",
])

# =============================================================== TI time intelligence
add("TI", f"CALCULATE({S}, DATESYTD({D}))", ["y24", "m2403", "m2403+cat"])
add("TI", f"TOTALYTD({S}, {D})", ["y24", "reg+y24"])
add("TI", f"TOTALYTD({S}, {D}, \"6/30\")", ["y24", "m2403"])
add("TI", f"CALCULATE({S}, DATESYTD({D}, \"6/30\"))", ["m2403"])
add("TI", f"CALCULATE({S}, DATESQTD({D}))", ["q24Q2"])
add("TI", f"TOTALQTD({S}, {D})", ["m2403"])
add("TI", f"CALCULATE({S}, DATESMTD({D}))", ["d"])
add("TI", f"TOTALMTD({S}, {D})", ["m2301"])
add("TI", f"CALCULATE({S}, SAMEPERIODLASTYEAR({D}))", ["y24", "m2403", "m2301"])
add("TI", f"CALCULATE({S}, DATEADD({D}, -1, YEAR))", ["m2403"])
add("TI", f"CALCULATE({S}, DATEADD({D}, -1, MONTH))", ["m2403","m2301"])
add("TI", f"CALCULATE({S}, DATEADD({D}, -1, QUARTER))", ["q24Q2"])
add("TI", f"CALCULATE({S}, DATEADD({D}, -1, DAY))", ["d"])
add("TI", f"CALCULATE({S}, DATEADD({D}, 1, YEAR))", ["y23"])
add("TI", f"CALCULATE({S}, PARALLELPERIOD({D}, -1, YEAR))", ["m2403"])
add("TI", f"CALCULATE({S}, PARALLELPERIOD({D}, -12, MONTH))", ["m2403"])
add("TI", f"CALCULATE({S}, PARALLELPERIOD({D}, -3, MONTH))", ["q24Q2"])
add("TI", f"CALCULATE({S}, PREVIOUSMONTH({D}))", ["m2301"])
add("TI", f"CALCULATE({S}, NEXTMONTH({D}))", ["m2403"])
add("TI", f"CALCULATE({S}, PREVIOUSQUARTER({D}))", ["q24Q2"])
add("TI", f"CALCULATE({S}, PREVIOUSYEAR({D}))", ["y23"])
add("TI", f"CALCULATE({S}, NEXTYEAR({D}))", ["y23"])
add("TI", f"CALCULATE({S}, PREVIOUSDAY({D}))", ["d"])
add("TI", f"CALCULATE({S}, NEXTDAY({D}))", ["d"])
add("TI", f"CALCULATE({S}, DATESBETWEEN({D}, DATE(2024, 1, 1), DATE(2024, 6, 30)))", ["all"])
add("TI", f"CALCULATE({S}, DATESBETWEEN({D}, BLANK(), MAX({D})))", ["m2403"])
add("TI", f"CALCULATE({S}, DATESINPERIOD({D}, MAX({D}), -3, MONTH))", ["m2403"])
add("TI", f"CALCULATE({S}, DATESINPERIOD({D}, MAX({D}), -12, MONTH))", ["m2301"])
add("TI", f"CALCULATE({S}, DATESINPERIOD({D}, MAX({D}), -30, DAY))", ["d"])
add("TI", f"CALCULATE({S}, DATESINPERIOD({D}, MIN({D}), 1, YEAR))", ["m2403"])
add("TI", f"DIVIDE(CALCULATE({S}, DATESINPERIOD({D}, MAX({D}), -3, MONTH)), 3)", ["m2301"])
add("TI", f"AVERAGEX(DATESINPERIOD({D}, MAX({D}), -3, MONTH), CALCULATE({S}))", ["m2403"])
add("TI", f"CALCULATE(AVERAGEX(VALUES(XT_Date[YearMonth]), CALCULATE({S})), DATESINPERIOD({D}, MAX({D}), -3, MONTH))", ["m2403"])
add("TI", f"CALCULATE({S}, FILTER(ALL({D}), {D} <= MAX({D})))", ["d", "m2403", "m2403+cat"])
add("TI", f"CALCULATE({S}, FILTER(ALL(XT_Date), XT_Date[Year] = MAX(XT_Date[Year]) && {D} <= MAX({D})))", ["m2403", "d"])
add("TI", f"CALCULATE({S}, FILTER(ALL(XT_Date[YearMonth]), XT_Date[YearMonth] <= MAX(XT_Date[YearMonth])))", ["ym"])
add("TI",
    f"VAR cur = {S} VAR prev = CALCULATE({S}, PREVIOUSMONTH({D})) RETURN DIVIDE(cur - prev, prev)",
    ["m2403","m2301","m2403+cat"])
add("TI", f"VAR cur = {S} VAR prev = CALCULATE({S}, PREVIOUSMONTH({D})) RETURN cur - prev", ["m2301"])
add("TI",
    f"VAR cur = {S} VAR py = CALCULATE({S}, SAMEPERIODLASTYEAR({D})) RETURN DIVIDE(cur - py, py)",
    ["y24","y23","m2403","m2403+cat"])
add("TI", f"VAR cur = {S} VAR py = CALCULATE({S}, SAMEPERIODLASTYEAR({D})) RETURN cur - py", ["y24"])
add("TI",
    f"VAR cur = {S} VAR py = CALCULATE({S}, SAMEPERIODLASTYEAR({D})) RETURN IF(ISBLANK(py), BLANK(), DIVIDE(cur - py, py))",
    ["y23"])
add("TI", f"CALCULATE({S}, SAMEPERIODLASTYEAR(DATESYTD({D})))", ["m2403"])
add("TI", f"CALCULATE(TOTALYTD({S}, {D}), DATEADD({D}, -1, YEAR))", ["m2403"])
add("TI", f"CALCULATE({S}, ENDOFMONTH({D}))", ["m2403"])
add("TI", f"CALCULATE({S}, LASTDATE({D}))", ["y24"])
add("TI", f"CALCULATE({S}, FIRSTDATE({D}))", ["m2403"])
add("TI", f"COUNTROWS(DATESYTD({D}))", ["m2403"])
add("TI", f"DATEDIFF(MIN({D}), MAX({D}), DAY)", ["y24"])
raw("TI", [
    f"CALCULATE(CALCULATE({S}, DATEADD({D}, -1, MONTH)), {D} = DATE(2024, 3, 31))",
    f"CALCULATE(CALCULATE({S}, SAMEPERIODLASTYEAR({D})), {D} = DATE(2024, 2, 29))",
])

# =============================================================== PT percent of total / parent
add("PT", f"DIVIDE({S}, CALCULATE({S}, ALL(XT_Product)))", ["cat", "cat+y24", "none"])
add("PT", f"DIVIDE({S}, CALCULATE({S}, ALL(XT_Region)))", ["reg","reg+cat"])
add("PT", f"DIVIDE({S}, CALCULATE({S}, REMOVEFILTERS()))", ["y24","reg+seg"])
add("PT", f"DIVIDE({S}, CALCULATE({S}, ALL(XT_Customer[Segment])))", ["seg"])
add("PT", f"DIVIDE({S}, CALCULATE({S}, ALL(XT_Sales[Channel])))", ["chan+reg"])
add("PT", f"DIVIDE({S}, CALCULATE({S}, ALLEXCEPT(XT_Product, XT_Product[Category])))", ["sub", "cat+sub"])
add("PT", f"DIVIDE({S}, CALCULATE({S}, REMOVEFILTERS(XT_Date[MonthNumber])))", ["m2403"])
add("PT", f"DIVIDE({S}, CALCULATE({S}, ALLSELECTED(XT_Product)))", ["cat"])
add("PT", f"IF(ISFILTERED(XT_Product[Category]), DIVIDE({S}, CALCULATE({S}, ALL(XT_Product[Category]))), 1)", ["all", "cat"])
add("PT", f"{S} / CALCULATE({S}, ALL(XT_Product))", ["cat", "none"])
add("PT", f"DIVIDE({N}, CALCULATE({N}, ALL(XT_Region)))", ["reg"])
add("PT", f"DIVIDE({CUS}, CALCULATE({CUS}, ALL(XT_Product)))", ["sub"])

# =============================================================== RK ranking, TOPN
add("RK", f"RANKX(ALL(XT_Product[Product]), CALCULATE({S}))", ["p7", "none"])
add("RK", f"RANKX(ALL(XT_Product[Product]), CALCULATE({Q}), , ASC, Dense)", ["p7"])
add("RK", f"RANKX(ALL(XT_Product[Category]), CALCULATE({S}))", ["cat","cat+y24"])
add("RK", f"RANKX(ALL(XT_Product[Category]), CALCULATE({S}), , ASC)", ["cat"])
add("RK", f"RANKX(ALL(XT_Region[Region]), CALCULATE({S}))", ["reg"])
add("RK", f"RANKX(ALL(XT_Region[Region]), CALCULATE({N}), , DESC, Dense)", ["reg"])
add("RK", f"RANKX(ALL(XT_Customer[Customer]), CALCULATE({S}))", ["cust"])
add("RK", f"RANKX(ALL(XT_Customer[Customer]), CALCULATE({N}), , DESC, Dense)", ["cust"])
add("RK", f"RANKX(ALL(XT_Customer[Customer]), CALCULATE({N}), , DESC, Skip)", ["cust"])
add("RK", f"RANKX(ALL(XT_Product[Subcategory]), CALCULATE({Q}))", ["sub"])
add("RK", f"RANKX(ALL(XT_Date[YearMonth]), CALCULATE({S}))", ["ym"])
add("RK", f"RANKX(ALL(XT_Date[MonthNumber]), CALCULATE({S}))", ["m2403"])
add("RK", f"RANKX(ALL(XT_Product[Category]), CALCULATE({S}), CALCULATE({S}))", ["cat"])
add("RK", f"RANKX(ALLSELECTED(XT_Product[Category]), CALCULATE({S}))", ["cat"])
add("RK", f"SUMX(TOPN(5, ALL(XT_Product[Product]), CALCULATE({S})), CALCULATE({S}))", ["all", "cat"])
add("RK", f"SUMX(TOPN(10, ALL(XT_Product[Product]), CALCULATE({S})), CALCULATE({S}))", ["y24"])
add("RK", f"SUMX(TOPN(5, ALL(XT_Product[Product]), CALCULATE({S}), ASC), CALCULATE({S}))", ["all"])
add("RK",
    f"DIVIDE(SUMX(TOPN(10, ALL(XT_Product[Product]), CALCULATE({S})), CALCULATE({S})), CALCULATE({S}, ALL(XT_Product)))",
    ["all","reg"])
add("RK",
    f"DIVIDE(SUMX(TOPN(10, ALL(XT_Customer[Customer]), CALCULATE({S})), CALCULATE({S})), CALCULATE({S}, ALL(XT_Customer)))",
    ["all"])
add("RK", f"COUNTROWS(TOPN(3, ALL(XT_Region[Region]), CALCULATE({S})))", ["all"])
add("RK", f"CONCATENATEX(TOPN(3, ALL(XT_Product[Category]), CALCULATE({S})), XT_Product[Category], \", \", CALCULATE({S}), DESC)", ["all","reg"])
add("RK", f"MAXX(TOPN(1, ALL(XT_Customer[Customer]), CALCULATE({S})), XT_Customer[Customer])", ["all", "cat"])
add("RK", f"COUNTROWS(TOPN(1, ALL(XT_Customer[Customer]), CALCULATE({N})))", ["all"])
add("RK", f"COUNTROWS(TOPN(5, VALUES(XT_Product[Product]), CALCULATE({S})))", ["none"])

# =============================================================== AB ABC classes (cumulative share of sales)
_ABC = (
    "VAR cs = CALCULATE({S}) "
    "VAR cum = SUMX(FILTER(ALL({COL}), CALCULATE({S}) >= cs), CALCULATE({S})) "
    "VAR tot = CALCULATE({S}, ALL({COL})) "
    "VAR pct = DIVIDE(cum, tot) "
    "RETURN IF(ISBLANK(cs), BLANK(), IF(pct <= 0.8, \"A\", IF(pct <= 0.95, \"B\", \"C\")))"
)
_abc_prod = _ABC.format(S=S, COL="XT_Product[Product]")
add("AB", _abc_prod, ["p7"])
raw("AB", [
    f"CALCULATE({_abc_prod}, XT_Product[Product] = \"Product_30\")",
    f"CALCULATE({_abc_prod}, XT_Product[Product] = \"Product_59\")",
    f"CALCULATE({_abc_prod}, XT_Product[Product] = \"Product_7\", XT_Date[Year] = 2024)",
    f"CALCULATE({_ABC.format(S=S, COL='XT_Product[Subcategory]')}, XT_Product[Subcategory] = \"Subcat_4\")",
    f"CALCULATE({_ABC.format(S=S, COL='XT_Region[Region]')}, XT_Region[Region] = \"North\")",
])
retire("AB")  # XT-AB-007 (60x60 ABC) removed; id burned so XT-AB-008 and later keep their numbers
raw("AB", [
    f"CALCULATE(SUMX(ALL(XT_Product[Product]), VAR cs = CALCULATE({S}) VAR cum = SUMX(FILTER(ALL(XT_Product[Product]), CALCULATE({S}) >= cs), CALCULATE({S})) VAR tot = CALCULATE({S}, ALL(XT_Product[Product])) RETURN IF(DIVIDE(cum, tot) <= 0.8, 1, 0)), XT_Date[Year] = 2024)",
    f"CALCULATE({_ABC.format(S=S, COL='XT_Customer[Customer]')}, XT_Customer[Customer] = \"Customer_10\")",
])

# =============================================================== NR new vs returning customers
_MM = "VAR mn = MIN(XT_Date[Date]) VAR mx = MAX(XT_Date[Date]) RETURN "
add("NR", _MM + "COUNTROWS(FILTER(ALL(XT_Customer), XT_Customer[FirstOrderDate] >= mn && XT_Customer[FirstOrderDate] <= mx))",
    ["y24", "m2403", "all"])
add("NR", _MM + f"CALCULATE({CUS}, FILTER(ALL(XT_Customer), XT_Customer[FirstOrderDate] >= mn && XT_Customer[FirstOrderDate] <= mx))",
    ["y24", "m2403", "y24+reg"])
add("NR", _MM + f"{CUS} - CALCULATE({CUS}, FILTER(ALL(XT_Customer), XT_Customer[FirstOrderDate] >= mn && XT_Customer[FirstOrderDate] <= mx))",
    ["y24"])
add("NR", _MM + f"CALCULATE({S}, FILTER(ALL(XT_Customer), XT_Customer[FirstOrderDate] >= mn && XT_Customer[FirstOrderDate] <= mx))",
    ["y24", "m2403"])
add("NR", _MM + f"COUNTROWS(FILTER(VALUES(XT_Sales[CustomerKey]), VAR f = CALCULATE(MIN(XT_Sales[OrderDate]), REMOVEFILTERS(XT_Date)) RETURN f >= mn && f <= mx))",
    ["y24", "m2403", "y24+reg"])
add("NR", _MM + f"COUNTROWS(FILTER(VALUES(XT_Sales[CustomerKey]), VAR f = CALCULATE(MIN(XT_Sales[OrderDate]), REMOVEFILTERS(XT_Date)) RETURN f < mn))",
    ["y24", "m2403"])
add("NR", "COUNTROWS(FILTER(XT_Customer, ISBLANK(XT_Customer[FirstOrderDate])))", ["all"])
add("NR", "COUNTROWS(FILTER(XT_Customer, XT_Customer[FirstOrderDate] >= DATE(2025, 1, 1)))", ["all"])

# =============================================================== BV budget vs actual (no relationship; TREATAS)
_BM = "TREATAS(VALUES(XT_Date[YearMonth]), XT_Budget[YearMonth])"
_BC = "TREATAS(VALUES(XT_Product[Category]), XT_Budget[Category])"
_BUD = f"CALCULATE(SUM(XT_Budget[BudgetAmount]), {_BM})"
_BUDC = f"CALCULATE(SUM(XT_Budget[BudgetAmount]), {_BM}, {_BC})"
add("BV", _BUD, ["y24", "m2403", "q24Q2"])
add("BV", _BUDC, ["y24", "m2403+cat", "cat", "y23", "none"])
add("BV", f"VAR a = {S} VAR b = {_BUDC} RETURN a - b", ["m2403+cat", "cat"])
add("BV", f"VAR a = {S} VAR b = {_BUDC} RETURN DIVIDE(a - b, b)", ["y24", "m2403+cat", "y26"])
add("BV", f"VAR a = {S} VAR b = {_BUDC} RETURN DIVIDE(a, b)", ["y24", "all"])
add("BV", f"CALCULATE(SUM(XT_Budget[BudgetAmount]), TREATAS(CALCULATETABLE(VALUES(XT_Date[YearMonth]), DATESYTD({D})), XT_Budget[YearMonth]))",
    ["m2403"])
add("BV", f"VAR a = CALCULATE({S}, DATESYTD({D})) VAR b = CALCULATE(SUM(XT_Budget[BudgetAmount]), TREATAS(CALCULATETABLE(VALUES(XT_Date[YearMonth]), DATESYTD({D})), XT_Budget[YearMonth])) RETURN DIVIDE(a, b)",
    ["y24"])
add("BV", "SUMX(VALUES(XT_Date[YearMonth]), VAR ym = XT_Date[YearMonth] RETURN CALCULATE(SUM(XT_Budget[BudgetAmount]), XT_Budget[YearMonth] = ym))",
    ["y24", "m2403"])
add("BV", "SUM(XT_Budget[BudgetAmount])", ["y24"])
raw("BV", [
    "LOOKUPVALUE(XT_Budget[BudgetAmount], XT_Budget[YearMonth], 202403, XT_Budget[Category], \"Cat_1\")",
    "CALCULATE(SUM(XT_Budget[BudgetAmount]), XT_Budget[Category] = \"Cat_1\", XT_Budget[YearMonth] >= 202401, XT_Budget[YearMonth] <= 202406)",
    f"SUMX(VALUES(XT_Product[Category]), VAR c = XT_Product[Category] RETURN CALCULATE(SUM(XT_Budget[BudgetAmount]), XT_Budget[Category] = c, {_BM}))",
])

# =============================================================== SA semi-additive (Quantity used as a stock-like measure)
add("SA", f"CALCULATE({Q}, LASTDATE({D}))", ["y24", "m2403", "q24Q2"])
add("SA", f"CALCULATE({Q}, LASTNONBLANK({D}, CALCULATE({N})))", ["y24", "m2403", "m2403+cat"])
add("SA", f"CALCULATE({Q}, LASTNONBLANK({D}, {Q}))", ["m2403"])
add("SA", f"CALCULATE({Q}, FIRSTNONBLANK({D}, CALCULATE({N})))", ["m2403"])
add("SA", f"CLOSINGBALANCEMONTH({Q}, {D})", ["m2403", "q24Q2"])
add("SA", f"CLOSINGBALANCEQUARTER({Q}, {D})", ["q24Q2"])
add("SA", f"CLOSINGBALANCEYEAR({Q}, {D})", ["y24"])
add("SA", f"OPENINGBALANCEMONTH({Q}, {D})", ["m2403"])
add("SA", f"OPENINGBALANCEQUARTER({Q}, {D})", ["q24Q2"])
add("SA", f"OPENINGBALANCEYEAR({Q}, {D})", ["y24"])
add("SA", f"LASTNONBLANKVALUE({D}, {Q})", ["y24", "m2403"])
add("SA", f"CALCULATE({Q}, DATESBETWEEN({D}, BLANK(), MAX({D})))", ["m2403", "d"])
add("SA", f"CALCULATE({CUS}, FILTER(ALL(XT_Date), {D} <= MAX({D})))", ["m2403"])
add("SA", f"AVERAGEX(VALUES({D}), CALCULATE({Q}))", ["m2403"])

# =============================================================== IR inactive relationship (ShipDate)
_UR = "USERELATIONSHIP(XT_Sales[ShipDate], XT_Date[Date])"
add("IR", f"CALCULATE({S}, {_UR})", ["all", "y24", "m2403", "y23", "cat+y24"])
add("IR", f"CALCULATE({N}, {_UR})", ["y24", "m2403"])
add("IR", f"CALCULATE({S}, {_UR}) - {S}", ["m2403"])
add("IR", f"CALCULATE({S}, {_UR}, DATESYTD({D}))", ["m2403"])
add("IR", f"CALCULATE({S}, {_UR}, SAMEPERIODLASTYEAR({D}))", ["m2403"])
add("IR", f"CALCULATE({CUS}, {_UR})", ["y24"])
add("IR", f"{S} - CALCULATE({S}, {_UR})", ["all"])
add("IR", f"CALCULATE({N}, ISBLANK(XT_Sales[ShipDate]))", ["all"])
add("IR", "AVERAGEX(XT_Sales, IF(ISBLANK(XT_Sales[ShipDate]), BLANK(), DATEDIFF(XT_Sales[OrderDate], XT_Sales[ShipDate], DAY)))", ["all", "cat"])
add("IR", "AVERAGEX(XT_Sales, DATEDIFF(XT_Sales[OrderDate], XT_Sales[ShipDate], DAY))", ["all"])
add("IR", f"CALCULATE(SUMX(XT_Sales, RELATED(XT_Date[MonthNumber])), {_UR})", ["y24"])
add("IR", f"CALCULATE({S}, CROSSFILTER(XT_Sales[OrderDate], XT_Date[Date], NONE), {_UR})", ["y24"])

# =============================================================== MM many-to-many bridge
_XF = "CROSSFILTER(XT_CustomerRegion[CustomerKey], XT_Customer[CustomerKey], BOTH)"
_TT = "TREATAS(VALUES(XT_CustomerRegion[CustomerKey]), XT_Sales[CustomerKey])"
add("MM", "COUNTROWS(XT_CustomerRegion)", ["all", "reg", "reg+seg"])
add("MM", "DISTINCTCOUNT(XT_CustomerRegion[CustomerKey])", ["all", "seg"])
add("MM", f"CALCULATE({S}, {_XF})", ["reg", "reg+y24"])
add("MM", f"CALCULATE({S}, {_TT})", ["reg", "all", "reg+y24"])
add("MM", f"CALCULATE({S}, {_TT}, REMOVEFILTERS(XT_Region))", ["reg"])
add("MM", f"CALCULATE({CUS}, {_TT}, REMOVEFILTERS(XT_Region))", ["reg"])
add("MM", "AVERAGEX(VALUES(XT_Region[Region]), CALCULATE(COUNTROWS(XT_CustomerRegion)))", ["all"])
add("MM", "COUNTROWS(FILTER(VALUES(XT_Customer[CustomerKey]), CALCULATE(COUNTROWS(XT_CustomerRegion)) > 1))", ["all", "reg"])
add("MM", "SUMX(XT_Customer, CALCULATE(COUNTROWS(XT_CustomerRegion)))", ["seg"])
add("MM", "COUNTROWS(FILTER(XT_Customer, CALCULATE(COUNTROWS(XT_CustomerRegion), XT_Region[Region] = \"North\") > 0))", ["all"])
add("MM", f"CALCULATE(DISTINCTCOUNT(XT_Customer[CustomerKey]), {_XF})", ["reg"])
add("MM", f"CALCULATE({N}, CROSSFILTER(XT_Sales[RegionKey], XT_Region[RegionKey], NONE))", ["reg"])

# =============================================================== CT context transition, RELATED, RELATEDTABLE
add("CT", f"SUMX(XT_Customer, CALCULATE({S}))", ["all", "y24", "seg", "reg"])
add("CT", f"SUMX(VALUES(XT_Product[Category]), CALCULATE({S}))", ["y24", "reg"])
add("CT", f"MAXX(VALUES(XT_Product[Category]), CALCULATE({S}))", ["all", "reg"])
add("CT", f"AVERAGEX(XT_Customer, CALCULATE({S}))", ["all", "seg"])
add("CT", "SUMX(XT_Sales, RELATED(XT_Product[ListPrice]) * XT_Sales[Quantity])", ["all", "cat", "none"])
add("CT", "SUMX(XT_Sales, IF(RELATED(XT_Product[Category]) = \"Cat_1\", XT_Sales[SalesAmount], 0))", ["y24"])
add("CT", "SUMX(XT_Customer, COUNTROWS(RELATEDTABLE(XT_Sales)))", ["all", "seg"])
add("CT", f"COUNTROWS(FILTER(XT_Customer, CALCULATE({S}) > 5000))", ["all", "y24", "reg"])
add("CT", f"SUMX(XT_Product, CALCULATE({Q}) * XT_Product[ListPrice])", ["all", "cat"])
add("CT", f"AVERAGEX(VALUES({D}), CALCULATE({S}))", ["m2403"])
add("CT", f"SUMX(VALUES(XT_Region[Region]), SUMX(VALUES(XT_Product[Category]), CALCULATE({S})))", ["y24"])
add("CT", "SUMX(XT_Product, COUNTROWS(RELATEDTABLE(XT_Sales)))", ["y24"])
add("CT", f"SUMX(FILTER(XT_Customer, CALCULATE({N}) > 10), CALCULATE({S}))", ["y24"])
add("CT", "COUNTROWS(FILTER(XT_Sales, RELATED(XT_Region[Country]) = \"Canada\"))", ["all"])
raw("CT", [
    "SUMX(XT_Product, SUMX(RELATEDTABLE(XT_Sales), XT_Sales[Quantity]))",
])

# =============================================================== TX text
add("TX", f"FORMAT({S}, \"#,0.00\")", ["y24", "none"])
add("TX", f"FORMAT({S}, \"Currency\")", ["cat"])
add("TX", f"FORMAT(DIVIDE({S}, CALCULATE({S}, ALL(XT_Product))), \"0.0%\")", ["cat"])
add("TX", "FORMAT(MIN(XT_Date[Date]), \"yyyy-MM-dd\")", ["m2403"])
add("TX", "FORMAT(MIN(XT_Date[Date]), \"MMM yyyy\")", ["m2403"])
add("TX", "CONCATENATEX(VALUES(XT_Product[Category]), XT_Product[Category], \", \", XT_Product[Category], ASC)", ["all", "sub"])
add("TX", "CONCATENATEX(VALUES(XT_Region[Region]), XT_Region[Region], \" | \", XT_Region[Region])", ["reg"])
add("TX", "CONCATENATEX(VALUES(XT_Sales[Channel]), XT_Sales[Channel], \", \", XT_Sales[Channel])", ["y24", "none"])
add("TX", f"CONCATENATEX(FILTER(VALUES(XT_Product[Category]), CALCULATE({S}) > 1000000), XT_Product[Category], \", \", XT_Product[Category])", ["y24"])
add("TX", f"SWITCH(TRUE(), {S} > 1000000, \"High\", {S} > 500000, \"Medium\", \"Low\")", ["all", "cat", "none", "m2403"])
add("TX", "SWITCH(SELECTEDVALUE(XT_Product[Category]), \"Cat_1\", \"One\", \"Cat_2\", \"Two\", \"Other\")", ["cat"])
add("TX", "SELECTEDVALUE(XT_Product[Category], \"Multiple\")", ["cat"])
add("TX", "SELECTEDVALUE(XT_Date[Year])", ["y24"])
add("TX", "SELECTEDVALUE(XT_Region[Region], \"All Regions\")", ["all", "reg"])
add("TX", "SELECTEDVALUE(XT_Customer[Segment])", ["all"])
add("TX", "LEFT(SELECTEDVALUE(XT_Product[Category], \"n/a\"), 3)", ["cat"])
add("TX", "UPPER(SELECTEDVALUE(XT_Region[Region], \"ALL\"))", ["reg"])
add("TX", "SUBSTITUTE(SELECTEDVALUE(XT_Product[Category], \"x\"), \"_\", \" \")", ["cat"])
add("TX", f"\"Sales \" & SELECTEDVALUE(XT_Date[Year], \"All Years\") & \" - \" & SELECTEDVALUE(XT_Region[Region], \"All Regions\")", ["all", "y24+reg"])
add("TX", "LEN(CONCATENATEX(VALUES(XT_Product[Category]), XT_Product[Category], \",\"))", ["all"])
add("TX", "IF(HASONEVALUE(XT_Product[Category]), VALUES(XT_Product[Category]), \"Many\")", ["cat"])
raw("TX", [
    'CALCULATE(SELECTEDVALUE(XT_Product[Category], "Multiple"), XT_Product[Category] IN {"Cat_1", "Cat_2"})',
])

# =============================================================== LG logic, BLANK handling, DIVIDE, COALESCE
add("LG", f"IF({S} > 1000000, \"Above\", \"Below\")", ["none"])
add("LG", f"IF(ISBLANK({S}), 0, {S})", ["none", "y26"])
add("LG", f"{S} + 0", ["none"])
add("LG", f"COALESCE({S}, 0)", ["none", "y26"])
add("LG", f"COALESCE({S}, -1)", ["none"])
add("LG", f"DIVIDE({S}, {N}, 0)", ["none", "reg"])
add("LG", f"DIVIDE({S}, {N})", ["none"])
add("LG", f"DIVIDE({Q}, 0, -1)", ["all"])
add("LG", f"IF({S} > 0, {S})", ["none"])
add("LG", f"IF({N} = 0, \"No data\", \"Has data\")", ["none", "y26"])
add("LG", f"IF({S} = BLANK(), \"blank\", \"value\")", ["none"])
add("LG", f"IF(AND({S} > 100000, {N} > 100), 1, 0)", ["cat", "none"])
add("LG", f"IF(OR({S} > 10000000, {N} > 100), 1, 0)", ["m2403"])
add("LG", f"{S} > 0", ["none"])
add("LG", f"ISBLANK({S})", ["none", "all"])
add("LG", f"ISEMPTY(XT_Sales)", ["none"])
add("LG", f"NOT(ISEMPTY(CALCULATETABLE(XT_Sales, XT_Sales[Channel] = \"Online\")))", ["none", "y26"])
raw("LG", [
    "IFERROR(1 / 0, -1)",
    "IFERROR(VALUE(\"abc\"), 0)",
    f"ROUND(DIVIDE({S}, {N}), 2)",
    f"IF(HASONEVALUE(XT_Product[Category]), {S}, BLANK())",
    f"IF(SELECTEDVALUE(XT_Product[Category]) IN {{\"Cat_1\", \"Cat_2\"}}, \"early\", \"late\")",
    "ISCROSSFILTERED(XT_Sales)",
    "HASONEFILTER(XT_Product[Category])",
])

# =============================================================== ST statistics
add("ST", "MEDIAN(XT_Sales[SalesAmount])", ["all", "cat", "none"])
add("ST", "MEDIANX(XT_Sales, XT_Sales[SalesAmount] / XT_Sales[Quantity])", ["y24"])
add("ST", "PERCENTILE.INC(XT_Sales[SalesAmount], 0.9)", ["all", "cat"])
add("ST", "PERCENTILE.EXC(XT_Sales[SalesAmount], 0.25)", ["cat"])
add("ST", "PERCENTILEX.INC(XT_Sales, XT_Sales[Quantity] * XT_Sales[UnitPrice], 0.5)", ["y24"])
add("ST", "STDEV.P(XT_Sales[SalesAmount])", ["all", "cat"])
add("ST", "STDEV.S(XT_Sales[SalesAmount])", ["reg"])
add("ST", "STDEVX.P(XT_Sales, XT_Sales[SalesAmount])", ["all"])
add("ST", "STDEVX.S(XT_Sales, XT_Sales[SalesAmount])", ["all"])
add("ST", "VAR.P(XT_Sales[SalesAmount])", ["y24", "cat"])
add("ST", "VAR.S(XT_Sales[Quantity])", ["reg"])
add("ST", "VARX.P(XT_Sales, XT_Sales[SalesAmount])", ["all"])
add("ST", "VARX.S(XT_Sales, XT_Sales[SalesAmount])", ["all"])
add("ST", "DIVIDE(STDEV.P(XT_Sales[SalesAmount]), AVERAGE(XT_Sales[SalesAmount]))", ["all", "none"])
add("ST", f"MEDIANX(VALUES(XT_Product[Product]), CALCULATE({S}))", ["all", "reg"])
add("ST", f"PERCENTILEX.INC(ALL(XT_Product[Product]), CALCULATE({S}), 0.8)", ["y24"])
add("ST", "AVERAGE(XT_Sales[SalesAmount]) - MEDIAN(XT_Sales[SalesAmount])", ["all"])

# =============================================================== EC edge cases (blank rows, unknown members, scalar edge arithmetic)
add("EC", f"CALCULATE({S}, XT_Sales[ProductKey] = 999)", ["all", "reg"])
add("EC", f"CALCULATE({S}, XT_Product[Category] = BLANK())", ["all"])
add("EC", f"CALCULATE({S}, ISBLANK(XT_Product[Category]))", ["all"])
add("EC", f"{S} - SUMX(VALUES(XT_Product[Category]), CALCULATE({S}))", ["all"])
add("EC", f"{S} - SUMX(DISTINCT(XT_Product[Category]), CALCULATE({S}))", ["y24"])
add("EC", f"{S} - SUMX(ALLNOBLANKROW(XT_Product[Category]), CALCULATE({S}))", ["all"])
add("EC", "COUNTROWS(VALUES(XT_Product[Category]))", ["all"])
add("EC", "COUNTROWS(DISTINCT(XT_Product[Category]))", ["all"])
add("EC", "COUNTROWS(ALL(XT_Product[Category]))", ["all"])
add("EC", "COUNTROWS(ALLNOBLANKROW(XT_Product[Category]))", ["all"])
add("EC", "COUNTROWS(VALUES(XT_Product[Color]))", ["all"])
add("EC", f"CALCULATE({S}, XT_Product[Color] = BLANK())", ["all"])
add("EC", f"CALCULATE({N}, ISBLANK(XT_Sales[CustomerKey]))", ["all"])
add("EC", f"CALCULATE({S}, XT_Customer[Customer] = BLANK())", ["all"])
add("EC", f"CALCULATE({S}, XT_Date[Date] = DATE(2024, 2, 29))", ["all"])
add("EC", f"CALCULATE({S}, XT_Date[IsWeekend] = TRUE())", ["reg"])
add("EC", f"CALCULATE({S}, XT_Date[Month] = \"Feb\", XT_Date[Year] = 2024)", ["all"])
raw("EC", [
    "1 / 0",
    "0 / 0",
    "BLANK() + 1",
    "BLANK() = 0",
    "BLANK() & \"x\"",
    "ROUND(2.5, 0)",
    "ROUND(-2.5, 0)",
    "MOD(-7, 3)",
    "SQRT(-1)",
])

# =============================================================== SH table shaping and set functions
SH_CTX = ["all", "y24", "m2403", "cat"]
add("SH", "COUNTROWS(EXCEPT(VALUES(XT_Sales[CustomerKey]), CALCULATETABLE(VALUES(XT_Sales[CustomerKey]), FILTER(ALL(XT_Date), XT_Date[Date] < MIN(XT_Date[Date])))))", SH_CTX)
add("SH", "COUNTROWS(INTERSECT(VALUES(XT_Sales[CustomerKey]), CALCULATETABLE(VALUES(XT_Sales[CustomerKey]), FILTER(ALL(XT_Date), XT_Date[Date] < MIN(XT_Date[Date])))))", SH_CTX)
add("SH", "COUNTROWS(UNION(VALUES(XT_Region[Region]), VALUES(XT_Region[Region])))", SH_CTX)
add("SH", f'SUMX(ADDCOLUMNS(VALUES(XT_Product[Category]), "s", CALCULATE({S})), [s])', SH_CTX)
add("SH", f'MAXX(SUMMARIZE(XT_Sales, XT_Product[Category], "s", {S}), [s])', SH_CTX)
add("SH", "COUNTROWS(SUMMARIZE(XT_Sales, XT_Sales[CustomerKey], XT_Date[Year]))", SH_CTX)
add("SH", "COUNTROWS(CROSSJOIN(VALUES(XT_Region[Region]), VALUES(XT_Product[Category])))", SH_CTX)
add("SH", "SUMX(GENERATESERIES(1, 10), [Value])", SH_CTX)
add("SH", 'COUNTROWS(SELECTCOLUMNS(XT_Customer, "k", XT_Customer[CustomerKey]))', SH_CTX)
add("SH", 'CONTAINS(VALUES(XT_Product[Category]), XT_Product[Category], "Cat_1")', SH_CTX)
raw("SH", [
    "SUMX(XT_Product, COUNTROWS(FILTER(XT_Product, XT_Product[ListPrice] > EARLIER(XT_Product[ListPrice]))))",
])

# =============================================================== FN scalar functions (one row each, grand-total context)
raw("FN", [
    "YEAR(MAX(XT_Date[Date]))",
    "EOMONTH(MAX(XT_Date[Date]), 0)",
    "EDATE(MAX(XT_Date[Date]), -1)",
    "WEEKDAY(MAX(XT_Date[Date]), 2)",
    "WEEKNUM(MAX(XT_Date[Date]))",
    'FORMAT(MAX(XT_Date[Date]), "dddd")',
    "INT(-2.5)",
    "TRUNC(-2.57, 1)",
    "FLOOR(7.3, 2)",
    "CEILING(7.1, 2)",
    "ROUNDUP(-2.1, 0)",
    "MROUND(7, 5)",
    "ABS(-3)",
    "POWER(2, 0.5)",
    "LN(10)",
    "SIGN(-4)",
    'MID("abcdef", 2, 3)',
    'RIGHT("abc", 5)',
    'LOWER("AbC")',
    'TRIM("  a  b ")',
    'SEARCH("x", "abc", 1, 0)',
    'FIND("b", "abc")',
    'REPLACE("abcdef", 2, 2, "ZZ")',
    "FIXED(1234.567, 1)",
    "CONVERT(2.5, INTEGER)",
    "ISTEXT(SELECTEDVALUE(XT_Region[Region]))",
    "XOR(TRUE(), FALSE())",
])

# =============================================================== WN window functions (year 2024 context)
add("WN", f"CALCULATE(SUMX(OFFSET(-1, ALLSELECTED(XT_Date[YearMonth]), ORDERBY(XT_Date[YearMonth])), CALCULATE({S})))", ["y24"])
raw("WN", [
    f"CALCULATE(SUMX(INDEX(2, ALLSELECTED(XT_Date[YearMonth]), ORDERBY(XT_Date[YearMonth])), CALCULATE({S})))",
])


def main() -> None:
    ids = [it["id"] for it in ITEMS]
    assert len(ids) == len(set(ids)), "duplicate ids"
    OUT.write_text(json.dumps(ITEMS, indent=1) + "\n", encoding="utf-8")
    counts: dict[str, int] = {}
    for it in ITEMS:
        counts[it["group"]] = counts.get(it["group"], 0) + 1
    print(f"wrote {len(ITEMS)} formulas to {OUT}")
    print(counts)


if __name__ == "__main__":
    main()
