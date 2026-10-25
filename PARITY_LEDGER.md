# Parity ledger: Analytics Studio vs Power BI Desktop

Generated 2026-10-25 by `tools/parity_check.py`. Power BI answers were saved from Power BI Desktop 2.157.879.0 (26.08)+da30fe74eb0b8a8786ab7326b69c400a0e951831; the gate replays them against the app on every run.

Rule: a slice is finished only when it is compared with Power BI, its items are locked here (`--accept`) and the gate passes.  Locked items are never re-investigated, only guarded.

| Group | Locked and matching | Match (not yet locked) | Pending (app refuses) | Differs | Crash |
|---|---|---|---|---|---|
| dax_battery | 93 | 0 | 0 | 0 | 0 |
| dax_battery_review | 25 | 0 | 0 | 0 | 0 |
| dax_battery_blank_logic | 139 | 0 | 0 | 0 | 0 |
| dax_battery_filter_tables | 33 | 0 | 0 | 0 | 0 |
| dax_battery_typed | 933 | 0 | 0 | 0 | 0 |
| dax_battery_math | 188 | 0 | 0 | 0 | 0 |
| dax_battery_tables | 344 | 0 | 0 | 0 | 0 |
| dax_battery_tables2 | 434 | 0 | 0 | 0 | 0 |
| dax_battery_stats | 2645 | 0 | 0 | 0 | 0 |
| dax_battery_misc | 2438 | 0 | 0 | 0 | 0 |
| dax_battery_adversarial | 2764 | 0 | 0 | 0 | 0 |
| dax_battery_finance | 436 | 0 | 0 | 0 | 0 |
| dax_battery_bonds | 2280 | 0 | 0 | 0 | 0 |
| dax_battery_filter_shapes | 23 | 0 | 0 | 0 | 0 |
| dax_battery_filter_shapes2 | 246 | 0 | 0 | 0 | 0 |
| dax_battery_filter_shapes3 | 255 | 0 | 0 | 0 | 0 |
| dax_battery_filter_shapes4 | 476 | 0 | 0 | 0 | 0 |
| dax_battery_allselected | 110 | 0 | 0 | 0 | 0 |
| dax_battery_var_tables | 209 | 0 | 0 | 0 | 0 |
| dax_battery_earlier_arith | 238 | 0 | 0 | 0 | 0 |
| dax_battery_boolean_scalar_rhs | 508 | 0 | 9 | 0 | 0 |
| dax_battery_filter_transition | 575 | 0 | 0 | 0 | 0 |
| dax_battery_boolean_filter_functions | 202 | 0 | 6 | 0 | 0 |
| dax_battery_sdet_filters | 635 | 0 | 25 | 0 | 0 |
| dax_battery_comments_booleans | 432 | 0 | 0 | 0 | 0 |
| dax_battery_round2_scope | 136 | 0 | 3 | 0 | 0 |
| dax_battery_round2 | 2347 | 0 | 83 | 0 | 0 |
| dax_battery_critic_shapes | 92 | 0 | 3 | 0 | 0 |
| dax_battery_round3 | 2346 | 0 | 18 | 0 | 0 |
| dax_battery_round4 | 8148 | 0 | 30 | 0 | 0 |
| dax_battery_round5 | 1208 | 0 | 13 | 0 | 0 |
| dax_battery_diff_groups | 484 | 0 | 0 | 0 | 0 |
| dax_battery_iferror_hard_errors | 165 | 0 | 0 | 0 | 0 |
| dax_battery_concatenatex_order | 189 | 0 | 0 | 0 | 0 |
| dax_battery_not_operator | 30 | 0 | 4 | 0 | 0 |
| dax_battery_promoted_pending | 632 | 0 | 0 | 0 | 0 |
| dax_battery_utf16_text | 244 | 0 | 0 | 0 | 0 |
| dax_battery_evaluation_order | 2215 | 0 | 0 | 0 | 0 |
| dax_battery_allselected_shadow | 2430 | 0 | 0 | 0 | 0 |
| dax_battery_allselected_critic2 | 7420 | 0 | 0 | 0 | 0 |
| table VAT | 575 | 0 | 0 | 0 | 0 |

## Pending work (194): Power BI answers, the app refuses

- `CALCULATE(CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))),Facts[Region]="East")` (Power BI: `2`) [dax_battery_boolean_scalar_rhs]
- `CALCULATE(CALCULATE(COUNTROWS(Facts),Facts[Quantity]>MAXX(CALCULATETABLE(VALUES(Facts[Quantity]),Facts[Region]="East"),Facts[Quantity])),Facts[Region]="East")` (Power BI: `BLANK`) [dax_battery_boolean_scalar_rhs]
- `CALCULATE(CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,ALL(Facts[Quantity])))),Facts[Region]="East")` (Power BI: `1`) [dax_battery_boolean_scalar_rhs]
- `CALCULATE(CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(VALUES(Facts[Quantity]),Facts[Region]="West"))),Facts[Region]="East")` (Power BI: `3`) [dax_battery_boolean_scalar_rhs]
- `CALCULATE(CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Quantity]>2))),Facts[Region]="East")` (Power BI: `2`) [dax_battery_boolean_scalar_rhs]
- `SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))))` (Power BI: `6`) [dax_battery_boolean_scalar_rhs]
- `SUMX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))))` (Power BI: `4`) [dax_battery_boolean_scalar_rhs]
- `SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),Facts[Quantity]>MAXX(CALCULATETABLE(VALUES(Facts[Quantity]),Facts[Region]="East"),Facts[Quantity])))` (Power BI: `BLANK`) [dax_battery_boolean_scalar_rhs]
- `SUMX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>MAXX(CALCULATETABLE(VALUES(Facts[Quantity]),Facts[Region]="East"),Facts[Quantity])))` (Power BI: `2`) [dax_battery_boolean_scalar_rhs]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>SUMX(KEEPFILTERS(VALUES(Facts[Region])),1))` (Power BI: `2`) [dax_battery_boolean_filter_functions]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>MAXX(KEEPFILTERS(VALUES(Facts[Region])),1))` (Power BI: `4`) [dax_battery_boolean_filter_functions]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTX(KEEPFILTERS(VALUES(Facts[Region])),1))` (Power BI: `2`) [dax_battery_boolean_filter_functions]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>SUMX(ADDMISSINGITEMS(Facts[Region],VALUES(Facts[Region]),Facts[Region]),1))` (Power BI: `2`) [dax_battery_boolean_filter_functions]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>MAXX(ADDMISSINGITEMS(Facts[Region],VALUES(Facts[Region]),Facts[Region]),1))` (Power BI: `4`) [dax_battery_boolean_filter_functions]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTX(ADDMISSINGITEMS(Facts[Region],VALUES(Facts[Region]),Facts[Region]),1))` (Power BI: `2`) [dax_battery_boolean_filter_functions]
- `SUMX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))))` (Power BI: `4`) [dax_battery_sdet_filters]
- `MAXX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="West"))))` (Power BI: `1`) [dax_battery_sdet_filters]
- `SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Quantity]>1))))` (Power BI: `3`) [dax_battery_sdet_filters]
- `SUMX(VALUES(Facts[Region]),CALCULATE(SUM(Facts[Quantity]),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))))` (Power BI: `27`) [dax_battery_sdet_filters]
- `SUMX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>MAXX(CALCULATETABLE(Facts,Facts[Region]="West"),Facts[Quantity])))` (Power BI: `4`) [dax_battery_sdet_filters]
- `SUMX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]<MAXX(CALCULATETABLE(Facts,Facts[Region]="West"),Facts[Quantity])))` (Power BI: `BLANK`) [dax_battery_sdet_filters]
- `SUMX(ADDCOLUMNS(Facts,"c",CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East")))),[c])` (Power BI: `4`) [dax_battery_sdet_filters]
- `COUNTROWS(FILTER(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East")))>0))` (Power BI: `4`) [dax_battery_sdet_filters]
- `CALCULATE(COUNTROWS(Facts),FILTER(Facts,Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]=EARLIER(Facts[Region])))))` (Power BI: `4`) [dax_battery_sdet_filters]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]<FIRSTNONBLANKVALUE(Facts[Quantity],MAX(Facts[Quantity])))` (Power BI: `BLANK`) [dax_battery_sdet_filters]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]<IF(ISEMPTY(CALCULATETABLE(Facts,Facts[Region]="East")),1,4))` (Power BI: `4`) [dax_battery_sdet_filters]
- `SUMX(ADDCOLUMNS(Facts,"q2",Facts[Quantity]*2),COUNTROWS(FILTER(Facts,Facts[Quantity]>EARLIER([q2]))))` (Power BI: `9`) [dax_battery_sdet_filters]
- `SUMX(ADDCOLUMNS(Facts,"q2",Facts[Quantity]*2),COUNTROWS(FILTER(Facts,Facts[Quantity]*2>EARLIER([q2])*2)))` (Power BI: `9`) [dax_battery_sdet_filters]
- `SUMX(SELECTCOLUMNS(Facts,"q",Facts[Quantity]),COUNTROWS(FILTER(Facts,Facts[Quantity]>EARLIER([q])*2)))` (Power BI: `9`) [dax_battery_sdet_filters]
- `SUMX(SELECTCOLUMNS(Facts,"q",Facts[Quantity],"r",Facts[Region]),COUNTROWS(FILTER(Facts,Facts[Region]=EARLIER([r]))))` (Power BI: `14`) [dax_battery_sdet_filters]
- `CALCULATE(CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))),Facts[Region]="East")` (Power BI: `2`) [dax_battery_sdet_filters]
- `CALCULATE(CALCULATE(COUNTROWS(Facts),Facts[Quantity]<MAXX(CALCULATETABLE(Facts,Facts[Region]="East"),Facts[Quantity])),Facts[Region]="West")` (Power BI: `2`) [dax_battery_sdet_filters]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>VAR x=COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East")) RETURN x-1)` (Power BI: `3`) [dax_battery_sdet_filters]
- `SUMX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]+COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))>5))` (Power BI: `1`) [dax_battery_sdet_filters]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]<COUNTROWS(CALCULATETABLE(Facts,KEEPFILTERS(Facts[Region]="East"))))` (Power BI: `BLANK`) [dax_battery_sdet_filters]
- `SUMX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]<COUNTROWS(CALCULATETABLE(Facts))))` (Power BI: `1`) [dax_battery_sdet_filters]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]<COUNTROWS(CALCULATETABLE(Facts,KEEPFILTERS(Facts[Region]="East"),Facts[Note]="Paid")))` (Power BI: `2`) [dax_battery_sdet_filters]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]<COUNTROWS(CALCULATETABLE(CALCULATETABLE(Facts,Facts[Region]="East"))))` (Power BI: `3`) [dax_battery_sdet_filters]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]<COUNTROWS(CALCULATETABLE(CALCULATETABLE(Facts),Facts[Region]="East")))` (Power BI: `3`) [dax_battery_sdet_filters]
- `SUMX(Facts,COUNTROWS(CALCULATETABLE(Facts,Facts[Quantity]>EARLIER(Facts[Quantity]))))` (Power BI: `BLANK`) [dax_battery_sdet_filters]
- `{{1}}` (Power BI: `1`) [dax_battery_round2_scope]
- `COUNTROWS({{1,2},{3,4}})` (Power BI: `2`) [dax_battery_round2_scope]
- `SUM(Facts/*c*/[Quantity])` (Power BI: `15`) [dax_battery_round2_scope]
- `CALCULATE(STDEV.S(Facts[Sales]),Facts[Sales]=BLANK())` (Power BI: `NaN`) [dax_battery_round2]
- `CALCULATE(STDEV.S(Facts[Quantity]),Facts[Region]="North")` (Power BI: `NaN`) [dax_battery_round2]
- `CALCULATE(VAR.S(Facts[Sales]),Facts[Sales]=BLANK())` (Power BI: `NaN`) [dax_battery_round2]
- `CALCULATE(VAR.S(Facts[Quantity]),Facts[Region]="North")` (Power BI: `NaN`) [dax_battery_round2]
- `AVERAGEA(Facts[Note])` (Power BI: `0`) [dax_battery_round2]
- `CALCULATE(AVERAGEA(Facts[Note]),Facts[Region]="North")` (Power BI: `0`) [dax_battery_round2]
- `CALCULATE(AVERAGEA(Facts[Note]),Facts[Region]="Nope")` (Power BI: `BLANK`) [dax_battery_round2]
- `CALCULATE(AVERAGEA(Facts[Note]),Facts[Note]=BLANK())` (Power BI: `BLANK`) [dax_battery_round2]
- `AVERAGEA(Facts[Region])` (Power BI: `0`) [dax_battery_round2]
- `CALCULATE(AVERAGEA(Facts[Region]),Facts[Region]="North")` (Power BI: `0`) [dax_battery_round2]
- `CALCULATE(AVERAGEA(Facts[Region]),Facts[Region]="Nope")` (Power BI: `BLANK`) [dax_battery_round2]
- `CALCULATE(AVERAGEA(Facts[Region]),Facts[Note]=BLANK())` (Power BI: `0`) [dax_battery_round2]
- `MAXA(Facts[Note])` (Power BI: `0`) [dax_battery_round2]
- `CALCULATE(MAXA(Facts[Note]),Facts[Region]="North")` (Power BI: `0`) [dax_battery_round2]
- `CALCULATE(MAXA(Facts[Note]),Facts[Region]="Nope")` (Power BI: `BLANK`) [dax_battery_round2]
- `CALCULATE(MAXA(Facts[Note]),Facts[Note]=BLANK())` (Power BI: `BLANK`) [dax_battery_round2]
- `MAXA(Facts[Region])` (Power BI: `0`) [dax_battery_round2]
- `CALCULATE(MAXA(Facts[Region]),Facts[Region]="North")` (Power BI: `0`) [dax_battery_round2]
- `CALCULATE(MAXA(Facts[Region]),Facts[Region]="Nope")` (Power BI: `BLANK`) [dax_battery_round2]
- `CALCULATE(MAXA(Facts[Region]),Facts[Note]=BLANK())` (Power BI: `0`) [dax_battery_round2]
- `MINA(Facts[Note])` (Power BI: `0`) [dax_battery_round2]
- `CALCULATE(MINA(Facts[Note]),Facts[Region]="North")` (Power BI: `0`) [dax_battery_round2]
- `CALCULATE(MINA(Facts[Note]),Facts[Region]="Nope")` (Power BI: `BLANK`) [dax_battery_round2]
- `CALCULATE(MINA(Facts[Note]),Facts[Note]=BLANK())` (Power BI: `BLANK`) [dax_battery_round2]
- `MINA(Facts[Region])` (Power BI: `0`) [dax_battery_round2]
- `CALCULATE(MINA(Facts[Region]),Facts[Region]="North")` (Power BI: `0`) [dax_battery_round2]
- `CALCULATE(MINA(Facts[Region]),Facts[Region]="Nope")` (Power BI: `BLANK`) [dax_battery_round2]
- `CALCULATE(MINA(Facts[Region]),Facts[Note]=BLANK())` (Power BI: `0`) [dax_battery_round2]
- `PERCENTILE.INC(Facts[Quantity],BLANK())` (Power BI: `0`) [dax_battery_round2]
- `PERCENTILE.INC(Facts[Sales],BLANK())` (Power BI: `-1.5`) [dax_battery_round2]
- `VARX.S(FILTER(Facts,Facts[Region]="North"),Facts[Quantity])` (Power BI: `NaN`) [dax_battery_round2]
- `SUM(Facts/**/ [Quantity])` (Power BI: `15`) [dax_battery_round2]
- `SUM('Facts'/*c*/[Quantity])` (Power BI: `15`) [dax_battery_round2]
- `SUM(Facts/*c*/[Quantity])` (Power BI: `15`) [dax_battery_round2]
- `BLANK( //c
)` (Power BI: `BLANK`) [dax_battery_round2]
- `COUNTROWS({{1,2},{3,4}})` (Power BI: `2`) [dax_battery_round2]
- `HOUR("13:45")` (Power BI: `13`) [dax_battery_round2]
- `HOUR("1:45 PM")` (Power BI: `13`) [dax_battery_round2]
- `MINUTE("13:45:30")` (Power BI: `45`) [dax_battery_round2]
- `COUNTROWS(FILTER(Facts,COUNTROWS(CALCULATETABLE(Facts,Facts[Region]=EARLIER(Facts[Region])))>2))` (Power BI: `BLANK`) [dax_battery_round2]
- `COUNTROWS(FILTER(Facts,COUNTROWS(CALCULATETABLE(Facts,Facts[Region]=EARLIER(Facts[Region])))>2 && Facts[Quantity]>1))` (Power BI: `BLANK`) [dax_battery_round2]
- `COUNTROWS(FILTER(Facts,COUNTROWS(CALCULATETABLE(Facts,Facts[Region]=EARLIER(Facts[Region])))>=COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))))` (Power BI: `6`) [dax_battery_round2]
- `COUNTROWS(FILTER(Facts,NOT(ISEMPTY(CALCULATETABLE(Facts,Facts[Region]=EARLIER(Facts[Region]),Facts[Quantity]>3)))))` (Power BI: `2`) [dax_battery_round2]
- `COUNTROWS(FILTER(Facts,Facts[Quantity] IN CALCULATETABLE(VALUES(Facts[Quantity]),Facts[Region]=EARLIER(Facts[Region]))))` (Power BI: `6`) [dax_battery_round2]
- `TRUE()==TRUE()` (Power BI: `True`) [dax_battery_round2]
- `IF("TRUE",2,3)` (Power BI: `2`) [dax_battery_round2]
- `AND("TRUE",TRUE())` (Power BI: `True`) [dax_battery_round2]
- `DIVIDE(1,0,"x")` (Power BI: `x`) [dax_battery_round2]
- `DIVIDE(1,0,TRUE())` (Power BI: `True`) [dax_battery_round2]
- `LN(BLANK())` (Power BI: `-Infinity`) [dax_battery_round2]
- `TRUNC(1234.567,1.9)` (Power BI: `1234.56`) [dax_battery_round2]
- `ISO.CEILING(2.1,-2)` (Power BI: `4`) [dax_battery_round2]
- `CALCULATETABLE(ROW("c",1),Facts[Quantity]>COUNTROWS(VALUES(Facts[Region])))` (Power BI: `1`) [dax_battery_round2]
- `CALCULATETABLE(ROW("c",1),Facts[Quantity]>COUNTROWS(ALL(Facts[Region])))` (Power BI: `1`) [dax_battery_round2]
- `CALCULATETABLE(ROW("c",1),Facts[Quantity]>COUNTROWS(DISTINCT(Facts[Region])))` (Power BI: `1`) [dax_battery_round2]
- `CALCULATETABLE(ROW("c",1),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts)))` (Power BI: `1`) [dax_battery_round2]
- `CALCULATETABLE(ROW("c",1),Facts[Quantity]>COUNTROWS(UNION(VALUES(Facts[Region]),VALUES(Facts[Region]))))` (Power BI: `1`) [dax_battery_round2]
- `CALCULATETABLE(ROW("c",1),Facts[Quantity]>COUNTROWS(CROSSJOIN(VALUES(Facts[Region]),VALUES(Facts[Note]))))` (Power BI: `1`) [dax_battery_round2]
- `CALCULATETABLE(ROW("c",1),Facts[Quantity]>COUNTROWS(GENERATESERIES(1,3)))` (Power BI: `1`) [dax_battery_round2]
- `CALCULATETABLE(ROW("c",1),Facts[Quantity]>COUNTROWS(DATATABLE("a",INTEGER,{{1},{2}})))` (Power BI: `1`) [dax_battery_round2]
- `CALCULATETABLE(ROW("c",1),Facts[Quantity]>COUNTROWS(CALENDAR(DATE(2020,1,1),DATE(2020,1,3))))` (Power BI: `1`) [dax_battery_round2]
- `CALCULATETABLE(ROW("c",COUNTROWS(Facts)),Facts[Quantity]>COUNTROWS(VALUES(Facts[Region])))` (Power BI: `2`) [dax_battery_round2]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(VALUES(Facts[Region]),FILTER(Facts,Facts[Quantity]>1))))` (Power BI: `2`) [dax_battery_round2]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(VALUES(Facts[Region]),ALLSELECTED())))` (Power BI: `2`) [dax_battery_round2]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(VALUES(Facts[Region]),ALLSELECTED(Facts[Region]))))` (Power BI: `4`) [dax_battery_round2]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(VALUES(Facts[Region]),VAR x="East" RETURN Facts[Region]=x)))` (Power BI: `4`) [dax_battery_round2]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,KEEPFILTERS(Facts[Region]="East"))))` (Power BI: `4`) [dax_battery_round2]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>EVALUATEANDLOG(3))` (Power BI: `2`) [dax_battery_round2]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(INFO.TABLES()))` (Power BI: `BLANK`) [dax_battery_round2]
- `VAR x=1 RETURN VAR x=2 RETURN x` (Power BI: `2`) [dax_battery_round2]
- `VAR x=1 RETURN x+VAR y=2 RETURN y` (Power BI: `3`) [dax_battery_round2]
- `VAR t=Facts RETURN COUNTROWS(t)` (Power BI: `6`) [dax_battery_round2]
- `LEN(TOCSV(Facts))` (Power BI: `147`) [dax_battery_round2]
- `TOCSV(ROW("a",1))` (Power BI: `[a]`) [dax_battery_round2]
- `TOCSV(ROW("a",1,"b","x"),0)` (Power BI: `[a],[b]`) [dax_battery_round2]
- `TOCSV(ROW("a",1),5,",")` (Power BI: `[a]`) [dax_battery_round2]
- `TOJSON(ROW("a",1))` (Power BI: `{`) [dax_battery_round2]
- `TOJSON(ROW("a",1,"b","x"))` (Power BI: `{`) [dax_battery_round2]
- `LEN(TOJSON(Facts))` (Power BI: `289`) [dax_battery_round2]
- `TOCSV(DATATABLE("a",INTEGER,"b",STRING,{{1,"x"},{2,"y,z"}}),5,";")` (Power BI: `[a];[b]`) [dax_battery_round2]
- `CONCATENATEX(ADDCOLUMNS(ALL(Facts[Quantity]),"n",INDEX(1,ALL(Facts[Quantity]),ORDERBY(Facts[Quantity]))),[n],",",Facts[Quantity])` (Power BI: `0,0,0,0,0,0`) [dax_battery_round2]
- `ROW("a",1)` (Power BI: `1`) [dax_battery_round2]
- `DATATABLE("a",INTEGER,{{1}})` (Power BI: `1`) [dax_battery_round2]
- `SUMX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>MAXX(CALCULATETABLE(Facts,Facts[Region]="West"),Facts[Quantity])))` (Power BI: `4`) [dax_battery_critic_shapes]
- `CALCULATE(CALCULATE(COUNTROWS(Facts),Facts[Quantity]>MAXX(CALCULATETABLE(Facts,Facts[Region]="West"),Facts[Quantity])),Facts[Region]="West")` (Power BI: `BLANK`) [dax_battery_critic_shapes]
- `CALCULATE(CALCULATE(COUNTROWS(Facts),Facts[Quantity]>MAXX(CALCULATETABLE(Facts,Facts[Region]="West"),Facts[Quantity])),Facts[Region]="East")` (Power BI: `1`) [dax_battery_critic_shapes]
- `SUM(Facts/**/[Quantity])` (Power BI: `15`) [dax_battery_round3]
- `SUM('Facts' /**/ [Quantity])` (Power BI: `15`) [dax_battery_round3]
- `SUM(Facts /* c */ [Quantity])` (Power BI: `15`) [dax_battery_round3]
- `SUM(Facts//c
[Quantity])` (Power BI: `15`) [dax_battery_round3]
- `SUM(Facts--c
[Quantity])` (Power BI: `15`) [dax_battery_round3]
- `VAR a = 1 // xRETURN a` (Power BI: `1`) [dax_battery_round3]
- `VAR a = 1 -- xRETURN a` (Power BI: `1`) [dax_battery_round3]
- `1 == 1` (Power BI: `True`) [dax_battery_round3]
- `CALCULATE(COUNTROWS(Facts),VAR t = Facts[Quantity] RETURN t>2)` (Power BI: `3`) [dax_battery_round3]
- `CALCULATE(COUNTROWS(Facts),VAR t = 2 RETURN Facts[Quantity]>t)` (Power BI: `3`) [dax_battery_round3]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]+CONCATENATEX(Facts,Facts[Quantity])>3)` (Power BI: `6`) [dax_battery_round3]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region]))-1)` (Power BI: `3`) [dax_battery_round3]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]+COUNTROWS(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region]))>5)` (Power BI: `3`) [dax_battery_round3]
- `CALCULATE(COUNTROWS(Facts),COUNTROWS(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region]))>0)` (Power BI: `6`) [dax_battery_round3]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(INFO.TABLES())-1)` (Power BI: `BLANK`) [dax_battery_round3]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]+COUNTROWS(INFO.TABLES())>5)` (Power BI: `6`) [dax_battery_round3]
- `CALCULATE(COUNTROWS(Facts),Facts[Region]=IF(TRUE(),1,"a"))` (Power BI: `BLANK`) [dax_battery_round3]
- `CALCULATE(COUNTROWS(Facts),Facts[Region]>IF(TRUE(),1,"a"))` (Power BI: `6`) [dax_battery_round3]
- `SUMX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>SUMX(OFFSET(1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity])))` (Power BI: `1`) [dax_battery_round4]
- `SUMX(Facts,CALCULATE(COUNTROWS(Facts),KEEPFILTERS(Facts[Quantity]>SUMX(OFFSET(1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity]))))` (Power BI: `1`) [dax_battery_round4]
- `COUNTROWS(FILTER(ALL(Facts),Facts[Quantity]>SUMX(OFFSET(1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity])))` (Power BI: `1`) [dax_battery_round4]
- `CONCATENATEX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>SUMX(OFFSET(1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity])),"|",Facts[Quantity])` (Power BI: `|||1||`) [dax_battery_round4]
- `MAXX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]=SUMX(OFFSET(1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity])))` (Power BI: `1`) [dax_battery_round4]
- `AVERAGEX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>SUMX(OFFSET(1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity])))` (Power BI: `1`) [dax_battery_round4]
- `COUNTX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>SUMX(OFFSET(1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity])))` (Power BI: `1`) [dax_battery_round4]
- `COUNTAX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>SUMX(OFFSET(1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity])))` (Power BI: `1`) [dax_battery_round4]
- `CALCULATE(COUNTROWS(Facts),FILTER(ALL(Facts),Facts[Quantity]>SUMX(OFFSET(1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity])))` (Power BI: `1`) [dax_battery_round4]
- `SUMX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>SUMX(INDEX(2,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity])))` (Power BI: `BLANK`) [dax_battery_round4]
- `SUMX(Facts,CALCULATE(COUNTROWS(Facts),KEEPFILTERS(Facts[Quantity]>SUMX(INDEX(2,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity]))))` (Power BI: `BLANK`) [dax_battery_round4]
- `COUNTROWS(FILTER(ALL(Facts),Facts[Quantity]>SUMX(INDEX(2,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity])))` (Power BI: `BLANK`) [dax_battery_round4]
- `CONCATENATEX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>SUMX(INDEX(2,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity])),"|",Facts[Quantity])` (Power BI: `|||||`) [dax_battery_round4]
- `MAXX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]=SUMX(INDEX(2,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity])))` (Power BI: `1`) [dax_battery_round4]
- `AVERAGEX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>SUMX(INDEX(2,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity])))` (Power BI: `BLANK`) [dax_battery_round4]
- `COUNTX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>SUMX(INDEX(2,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity])))` (Power BI: `BLANK`) [dax_battery_round4]
- `COUNTAX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>SUMX(INDEX(2,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity])))` (Power BI: `BLANK`) [dax_battery_round4]
- `CALCULATE(COUNTROWS(Facts),FILTER(ALL(Facts),Facts[Quantity]>SUMX(INDEX(2,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity])))` (Power BI: `BLANK`) [dax_battery_round4]
- `SUMX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>RANKX(ALL(Facts[Quantity]),Facts[Quantity])))` (Power BI: `2`) [dax_battery_round4]
- `CONCATENATEX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>RANKX(ALL(Facts[Quantity]),Facts[Quantity])),"|",Facts[Quantity])` (Power BI: `||||1|1`) [dax_battery_round4]
- `SUMX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>RANKX(ALL(Facts),Facts[Quantity],,DESC,Dense)))` (Power BI: `2`) [dax_battery_round4]
- `CONCATENATEX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>RANKX(ALL(Facts),Facts[Quantity],,DESC,Dense)),"|",Facts[Quantity])` (Power BI: `||||1|1`) [dax_battery_round4]
- `CONCATENATEX(Facts,SUMX(ROW("a",1),IF(IF(Facts[Quantity]>2,TRUE()),1,2)),"|",Facts[Quantity])` (Power BI: `2|2|2|1|1|1`) [dax_battery_round4]
- `CONCATENATEX(Facts,SUMX(ROW("a",1),IF(IF(Facts[Quantity]>2,1),1,2)),"|",Facts[Quantity])` (Power BI: `2|2|2|1|1|1`) [dax_battery_round4]
- `CONCATENATEX(Facts,SUMX(ROW("a",1),IF(SWITCH(Facts[Quantity],1,TRUE()),1,2)),"|",Facts[Quantity])` (Power BI: `2|1|2|2|2|2`) [dax_battery_round4]
- `CONCATENATEX(Facts,SUMX(ROW("a",1),IF(SWITCH(Facts[Quantity],1,1),1,2)),"|",Facts[Quantity])` (Power BI: `2|1|2|2|2|2`) [dax_battery_round4]
- `CONCATENATEX(Facts,SUMX(ROW("a",1),IF(COALESCE(IF(Facts[Quantity]>2,TRUE()),FALSE()),1,2)),"|",Facts[Quantity])` (Power BI: `2|2|2|1|1|1`) [dax_battery_round4]
- `CONCATENATEX(Facts,SUMX(ROW("a",1),IF(IFERROR(IF(Facts[Quantity]>2,TRUE()),BLANK()),1,2)),"|",Facts[Quantity])` (Power BI: `2|2|2|1|1|1`) [dax_battery_round4]
- `MAXX(Facts,SWITCH(Facts[Region]="East",TRUE(),Facts[Quantity]>2,FALSE(),BLANK()))` (Power BI: `BLANK`) [dax_battery_round4]
- `SUMX(Facts,SWITCH(Facts[Region]="East",TRUE(),Facts[Quantity]>2,FALSE(),BLANK()))` (Power BI: `BLANK`) [dax_battery_round4]
- `IF(1>2,TRUE())==FALSE()` (Power BI: `True`) [dax_battery_round5]
- `IF(1>2,TRUE())==BLANK()` (Power BI: `False`) [dax_battery_round5]
- `IF(1>2,TRUE(),BLANK())==FALSE()` (Power BI: `True`) [dax_battery_round5]
- `IF(1>2,TRUE(),BLANK())==BLANK()` (Power BI: `False`) [dax_battery_round5]
- `SWITCH(7,1,TRUE())==FALSE()` (Power BI: `True`) [dax_battery_round5]
- `SWITCH(7,1,TRUE(),2,FALSE())==FALSE()` (Power BI: `True`) [dax_battery_round5]
- `IF(1>2,1)==0` (Power BI: `False`) [dax_battery_round5]
- `IF(1>2,1)==BLANK()` (Power BI: `True`) [dax_battery_round5]
- `IFERROR(BLANK(),TRUE())==BLANK()` (Power BI: `False`) [dax_battery_round5]
- `COUNTX(ADDCOLUMNS(Facts,"b",Facts[Quantity]>2,"c",Facts[Sales]>1),IFERROR(1/0,IF([b],[c])))` (Power BI: `BLANK`) [dax_battery_round5]
- `ISBLANK(IFERROR(INT("x")>1,BLANK()))` (Power BI: `False`) [dax_battery_round5]
- `ISBLANK(IFERROR(("x"+1)>1,BLANK()))` (Power BI: `False`) [dax_battery_round5]
- `COUNTAX(Facts,COALESCE(SWITCH(Facts[Quantity],2,DATE(2020,1,1),4,CALCULATE(COUNTROWS(Facts)>3)),FALSE()))` (Power BI: `6`) [dax_battery_round5]
- `NOT 1=2` (Power BI: `True`) [dax_battery_not_operator]
- `NOT 1=1` (Power BI: `False`) [dax_battery_not_operator]
- `NOT 1=2 && 1=1` (Power BI: `True`) [dax_battery_not_operator]
- `NOT 1=2 || 1=2` (Power BI: `True`) [dax_battery_not_operator]

## Known deviations from Power BI (14): imprecise or unspecified in Power BI, each explained

- `T.INV(0.95,1e10)`: Power BI 1.6448533237763, app 1.6448536271 (Power BI's solver is inexact here (asked twice, same answer); the app returns the mathematically correct value)
- `T.INV(0.95,2147483647)`: Power BI 1.6448536460143, app 1.6448536277 (Power BI's solver is inexact here (asked twice, same answer); the app returns the mathematically correct value)
- `T.INV(0.35,50000000)`: Power BI -0.385320474583522, app -0.385320468620 (Power BI's solver is inexact here (asked twice, same answer); the app returns the mathematically correct value)
- `T.INV(0.65,50000000)`: Power BI 0.385320474583522, app 0.385320468620 (Power BI's solver is inexact here (asked twice, same answer); the app returns the mathematically correct value)
- `T.INV.2T(0.2,1e10)`: Power BI 1.28155184241157, app 1.28155156563 (Power BI's solver is inexact here (asked twice, same answer); the app returns the mathematically correct value)
- `T.INV.2T(0.3,50000000)`: Power BI 1.03643340367666, app 1.03643340024 (Power BI's solver is inexact here (asked twice, same answer); the app returns the mathematically correct value)
- `T.INV.2T(0.8,50000000)`: Power BI 0.253347108743936, app 0.253347104484 (Power BI's solver is inexact here (asked twice, same answer); the app returns the mathematically correct value)
- `T.INV.2T(1.2,50000000)`: Power BI -0.253347108743936, app -0.253347104484 (Power BI's solver is inexact here (asked twice, same answer); the app returns the mathematically correct value)
- `CHISQ.INV.RT(1e-12,1)`: Power BI 50.8441713324492, app 50.8441279 (Power BI's solver is inexact here (asked twice, same answer); the app returns the mathematically correct value)
- `CHISQ.INV.RT(1e-15,1)`: Power BI 64.4320389693635, app 64.4304635 (Power BI's solver is inexact here (asked twice, same answer); the app returns the mathematically correct value)
- `BETA.INV(1e-300,50,3)`: Power BI 7.4e-14, app 8.66e-7 (Power BI's solver is inexact here (asked twice, same answer); the app returns the mathematically correct value)
- `BETA.INV(1e-300,1e5,3)`: Power BI 4.3e-6, app 0.99299 (Power BI's solver is inexact here (asked twice, same answer); the app returns the mathematically correct value)
- `CONCATENATEX(SELECTCOLUMNS(Facts,Facts[Region]),[Region],",")`: Power BI East,East,East,West,West,North, app East,West,East,North,West,East (DAX defines no row order here (no ORDER BY): Power BI iterates in storage order (the dictionary order of the columns the expression reads, so equal values come together), the app iterates in row order; both are valid results)
- `CALCULATE(COUNTROWS(Facts),TOPN(2,SUMMARIZE(Facts,Facts[Region],Facts[Note])))`: Power BI 2, app 3 (DAX defines no row order here (no ORDER BY): Power BI iterates in storage order (the dictionary order of the columns the expression reads, so equal values come together), the app iterates in row order; both are valid results)

## Notes

- DSI: workbook /Users/armaan/Downloads/DSI.xlsx is missing, its saved Power BI answers were not replayed

## Not yet compared with Power BI (no saved answers)

UI screens side by side, text/Boolean results, VAR/RETURN, VALUES/SELECTEDVALUE, Infinity/NaN, other visuals, Power Query live sources, service features.
