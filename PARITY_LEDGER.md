# Parity ledger: Analytics Studio vs Power BI Desktop

Generated 2026-10-26 by `tools/parity_check.py`. Power BI answers were saved from Power BI Desktop 2.157.879.0 (26.08)+da30fe74eb0b8a8786ab7326b69c400a0e951831; the gate replays them against the app on every run.

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
| dax_battery_boolean_scalar_rhs | 517 | 0 | 0 | 0 | 0 |
| dax_battery_filter_transition | 575 | 0 | 0 | 0 | 0 |
| dax_battery_boolean_filter_functions | 202 | 0 | 6 | 0 | 0 |
| dax_battery_sdet_filters | 655 | 0 | 5 | 0 | 0 |
| dax_battery_comments_booleans | 432 | 0 | 0 | 0 | 0 |
| dax_battery_round2_scope | 139 | 0 | 0 | 0 | 0 |
| dax_battery_round2 | 2405 | 0 | 25 | 0 | 0 |
| dax_battery_critic_shapes | 95 | 0 | 0 | 0 | 0 |
| dax_battery_round3 | 2356 | 0 | 8 | 0 | 0 |
| dax_battery_round4 | 8172 | 0 | 6 | 0 | 0 |
| dax_battery_round5 | 1217 | 0 | 4 | 0 | 0 |
| dax_battery_diff_groups | 484 | 0 | 0 | 0 | 0 |
| dax_battery_iferror_hard_errors | 165 | 0 | 0 | 0 | 0 |
| dax_battery_concatenatex_order | 189 | 0 | 0 | 0 | 0 |
| dax_battery_not_operator | 34 | 0 | 0 | 0 | 0 |
| dax_battery_promoted_pending | 632 | 0 | 0 | 0 | 0 |
| dax_battery_utf16_text | 244 | 0 | 0 | 0 | 0 |
| dax_battery_evaluation_order | 2215 | 0 | 0 | 0 | 0 |
| dax_battery_allselected_shadow | 2430 | 0 | 0 | 0 | 0 |
| dax_battery_allselected_critic2 | 7420 | 0 | 0 | 0 | 0 |
| dax_battery_xnpv | 107 | 0 | 0 | 0 | 0 |
| dax_battery_scalar_misc2 | 43 | 0 | 99 | 0 | 0 |
| dax_battery_type_tests | 9 | 0 | 362 | 0 | 0 |
| dax_battery_tocsv_tojson | 23 | 0 | 162 | 0 | 0 |
| dax_battery_linest | 41 | 0 | 178 | 0 | 0 |
| dax_battery_table_fns2 | 42 | 0 | 124 | 0 | 0 |
| dax_battery_var_scoping | 70 | 0 | 20 | 0 | 0 |
| dax_battery_xnpv2 | 221 | 0 | 37 | 0 | 0 |
| table VAT | 575 | 0 | 0 | 0 | 0 |

## Pending work (1036): Power BI answers, the app refuses

- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>SUMX(KEEPFILTERS(VALUES(Facts[Region])),1))` (Power BI: `2`) [dax_battery_boolean_filter_functions]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>MAXX(KEEPFILTERS(VALUES(Facts[Region])),1))` (Power BI: `4`) [dax_battery_boolean_filter_functions]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTX(KEEPFILTERS(VALUES(Facts[Region])),1))` (Power BI: `2`) [dax_battery_boolean_filter_functions]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>SUMX(ADDMISSINGITEMS(Facts[Region],VALUES(Facts[Region]),Facts[Region]),1))` (Power BI: `2`) [dax_battery_boolean_filter_functions]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>MAXX(ADDMISSINGITEMS(Facts[Region],VALUES(Facts[Region]),Facts[Region]),1))` (Power BI: `4`) [dax_battery_boolean_filter_functions]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTX(ADDMISSINGITEMS(Facts[Region],VALUES(Facts[Region]),Facts[Region]),1))` (Power BI: `2`) [dax_battery_boolean_filter_functions]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]<FIRSTNONBLANKVALUE(Facts[Quantity],MAX(Facts[Quantity])))` (Power BI: `BLANK`) [dax_battery_sdet_filters]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]<IF(ISEMPTY(CALCULATETABLE(Facts,Facts[Region]="East")),1,4))` (Power BI: `4`) [dax_battery_sdet_filters]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>VAR x=COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East")) RETURN x-1)` (Power BI: `3`) [dax_battery_sdet_filters]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]<COUNTROWS(CALCULATETABLE(CALCULATETABLE(Facts,Facts[Region]="East"))))` (Power BI: `3`) [dax_battery_sdet_filters]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]<COUNTROWS(CALCULATETABLE(CALCULATETABLE(Facts),Facts[Region]="East")))` (Power BI: `3`) [dax_battery_sdet_filters]
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
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>EVALUATEANDLOG(3))` (Power BI: `2`) [dax_battery_round2]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(INFO.TABLES()))` (Power BI: `BLANK`) [dax_battery_round2]
- `LEN(TOCSV(Facts))` (Power BI: `147`) [dax_battery_round2]
- `TOCSV(ROW("a",1))` (Power BI: `[a]
1`) [dax_battery_round2]
- `TOCSV(ROW("a",1,"b","x"),0)` (Power BI: `[a],[b]
`) [dax_battery_round2]
- `TOCSV(ROW("a",1),5,",")` (Power BI: `[a]
1`) [dax_battery_round2]
- `TOJSON(ROW("a",1))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[1]
	]
}`) [dax_battery_round2]
- `TOJSON(ROW("a",1,"b","x"))` (Power BI: `{
	"header": ["[a]", "[b]"],
	"rowCount": 1,
	"data": [
		[1`) [dax_battery_round2]
- `LEN(TOJSON(Facts))` (Power BI: `289`) [dax_battery_round2]
- `TOCSV(DATATABLE("a",INTEGER,"b",STRING,{{1,"x"},{2,"y,z"}}),5,";")` (Power BI: `[a];[b]
1;x
2;y,z`) [dax_battery_round2]
- `CONCATENATEX(ADDCOLUMNS(ALL(Facts[Quantity]),"n",INDEX(1,ALL(Facts[Quantity]),ORDERBY(Facts[Quantity]))),[n],",",Facts[Quantity])` (Power BI: `0,0,0,0,0,0`) [dax_battery_round2]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]+CONCATENATEX(Facts,Facts[Quantity])>3)` (Power BI: `6`) [dax_battery_round3]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region]))-1)` (Power BI: `3`) [dax_battery_round3]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]+COUNTROWS(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region]))>5)` (Power BI: `3`) [dax_battery_round3]
- `CALCULATE(COUNTROWS(Facts),COUNTROWS(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region]))>0)` (Power BI: `6`) [dax_battery_round3]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(INFO.TABLES())-1)` (Power BI: `BLANK`) [dax_battery_round3]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]+COUNTROWS(INFO.TABLES())>5)` (Power BI: `6`) [dax_battery_round3]
- `CALCULATE(COUNTROWS(Facts),Facts[Region]=IF(TRUE(),1,"a"))` (Power BI: `BLANK`) [dax_battery_round3]
- `CALCULATE(COUNTROWS(Facts),Facts[Region]>IF(TRUE(),1,"a"))` (Power BI: `6`) [dax_battery_round3]
- `SUMX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>RANKX(ALL(Facts[Quantity]),Facts[Quantity])))` (Power BI: `2`) [dax_battery_round4]
- `CONCATENATEX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>RANKX(ALL(Facts[Quantity]),Facts[Quantity])),"|",Facts[Quantity])` (Power BI: `||||1|1`) [dax_battery_round4]
- `SUMX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>RANKX(ALL(Facts),Facts[Quantity],,DESC,Dense)))` (Power BI: `2`) [dax_battery_round4]
- `CONCATENATEX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>RANKX(ALL(Facts),Facts[Quantity],,DESC,Dense)),"|",Facts[Quantity])` (Power BI: `||||1|1`) [dax_battery_round4]
- `MAXX(Facts,SWITCH(Facts[Region]="East",TRUE(),Facts[Quantity]>2,FALSE(),BLANK()))` (Power BI: `BLANK`) [dax_battery_round4]
- `SUMX(Facts,SWITCH(Facts[Region]="East",TRUE(),Facts[Quantity]>2,FALSE(),BLANK()))` (Power BI: `BLANK`) [dax_battery_round4]
- `COUNTX(ADDCOLUMNS(Facts,"b",Facts[Quantity]>2,"c",Facts[Sales]>1),IFERROR(1/0,IF([b],[c])))` (Power BI: `BLANK`) [dax_battery_round5]
- `ISBLANK(IFERROR(INT("x")>1,BLANK()))` (Power BI: `False`) [dax_battery_round5]
- `ISBLANK(IFERROR(("x"+1)>1,BLANK()))` (Power BI: `False`) [dax_battery_round5]
- `COUNTAX(Facts,COALESCE(SWITCH(Facts[Quantity],2,DATE(2020,1,1),4,CALCULATE(COUNTROWS(Facts)>3)),FALSE()))` (Power BI: `6`) [dax_battery_round5]
- `IF.EAGER(TRUE(),1,2)` (Power BI: `1`) [dax_battery_scalar_misc2]
- `IF.EAGER(FALSE(),1,"a")` (Power BI: `a`) [dax_battery_scalar_misc2]
- `IF.EAGER(TRUE(),1/0,2)` (Power BI: `Infinity`) [dax_battery_scalar_misc2]
- `IF.EAGER(FALSE(),1/0,2)` (Power BI: `2`) [dax_battery_scalar_misc2]
- `IF.EAGER(TRUE(),1)` (Power BI: `1`) [dax_battery_scalar_misc2]
- `IF.EAGER(FALSE(),1)` (Power BI: `BLANK`) [dax_battery_scalar_misc2]
- `IF.EAGER(BLANK(),1,2)` (Power BI: `2`) [dax_battery_scalar_misc2]
- `IF.EAGER(1,2,3)` (Power BI: `2`) [dax_battery_scalar_misc2]
- `IF.EAGER(0,1,2)` (Power BI: `2`) [dax_battery_scalar_misc2]
- `IFERROR(ERROR("x"),5)` (Power BI: `5`) [dax_battery_scalar_misc2]
- `IF(TRUE(),1,ERROR("x"))` (Power BI: `1`) [dax_battery_scalar_misc2]
- `ISERROR(ERROR("x"))` (Power BI: `True`) [dax_battery_scalar_misc2]
- `IFERROR(ERROR(""),5)` (Power BI: `5`) [dax_battery_scalar_misc2]
- `CUSTOMDATA()` (Power BI: `BLANK`) [dax_battery_scalar_misc2]
- `NAMEOF(Facts[Sales])` (Power BI: `'Facts'[Sales]`) [dax_battery_scalar_misc2]
- `NAMEOF(Facts)` (Power BI: `'Facts'`) [dax_battery_scalar_misc2]
- `COUNTROWS(TABLEOF(Facts[Sales]))` (Power BI: `6`) [dax_battery_scalar_misc2]
- `ISAFTER(2,1)` (Power BI: `True`) [dax_battery_scalar_misc2]
- `ISAFTER(1,2)` (Power BI: `False`) [dax_battery_scalar_misc2]
- `ISAFTER(1,1)` (Power BI: `False`) [dax_battery_scalar_misc2]
- `ISAFTER(2,1,DESC)` (Power BI: `False`) [dax_battery_scalar_misc2]
- `ISAFTER(1,2,DESC)` (Power BI: `True`) [dax_battery_scalar_misc2]
- `ISAFTER("b","a")` (Power BI: `True`) [dax_battery_scalar_misc2]
- `ISAFTER(BLANK(),1)` (Power BI: `False`) [dax_battery_scalar_misc2]
- `ISAFTER(1,BLANK())` (Power BI: `True`) [dax_battery_scalar_misc2]
- `ISAFTER(1,1,ASC,2,1)` (Power BI: `True`) [dax_battery_scalar_misc2]
- `ISAFTER(1,1,ASC,1,2)` (Power BI: `False`) [dax_battery_scalar_misc2]
- `ISAFTER(1,1,DESC,2,1)` (Power BI: `True`) [dax_battery_scalar_misc2]
- `EVALUATEANDLOG(3)` (Power BI: `3`) [dax_battery_scalar_misc2]
- `EVALUATEANDLOG(1+1,"lbl")` (Power BI: `2`) [dax_battery_scalar_misc2]
- `EVALUATEANDLOG(BLANK())` (Power BI: `BLANK`) [dax_battery_scalar_misc2]
- `EVALUATEANDLOG("a")` (Power BI: `a`) [dax_battery_scalar_misc2]
- `COUNTROWS(EVALUATEANDLOG(Facts))` (Power BI: `6`) [dax_battery_scalar_misc2]
- `SUM(Facts[Quantity])+EVALUATEANDLOG(1)` (Power BI: `16`) [dax_battery_scalar_misc2]
- `EVALUATEANDLOG(1,"a",5)` (Power BI: `1`) [dax_battery_scalar_misc2]
- `EVALUATEANDLOG(1,"a",1000)` (Power BI: `1`) [dax_battery_scalar_misc2]
- `NAMEOF(Facts[Quantity])` (Power BI: `'Facts'[Quantity]`) [dax_battery_scalar_misc2]
- `CALCULATE(COUNTROWS(Facts),ALLCROSSFILTERED(Facts))` (Power BI: `6`) [dax_battery_scalar_misc2]
- `CALCULATE(COUNTROWS(Facts),Facts[Region]="East",ALLCROSSFILTERED(Facts))` (Power BI: `3`) [dax_battery_scalar_misc2]
- `IF.EAGER(TRUE(),1,ERROR("x"))` (Power BI: `1`) [dax_battery_scalar_misc2]
- `IF.EAGER(FALSE(),ERROR("x"),2)` (Power BI: `2`) [dax_battery_scalar_misc2]
- `IF(FALSE(),ERROR("x"),2)` (Power BI: `2`) [dax_battery_scalar_misc2]
- `IF.EAGER(TRUE(),1,1/0)` (Power BI: `1`) [dax_battery_scalar_misc2]
- `IF.EAGER(TRUE(),1,SQRT(-1))` (Power BI: `1`) [dax_battery_scalar_misc2]
- `IF.EAGER(TRUE(),1,VALUE("x"))` (Power BI: `1`) [dax_battery_scalar_misc2]
- `IFERROR(IF.EAGER(TRUE(),1,ERROR("x")),9)` (Power BI: `1`) [dax_battery_scalar_misc2]
- `SUMX(Facts,IF.EAGER(Facts[Quantity]>2,1,0))` (Power BI: `3`) [dax_battery_scalar_misc2]
- `IF.EAGER(TRUE(),"a",1)` (Power BI: `a`) [dax_battery_scalar_misc2]
- `IF.EAGER(FALSE(),"a",1)` (Power BI: `1`) [dax_battery_scalar_misc2]
- `IF.EAGER(TRUE(),1,"a")` (Power BI: `1`) [dax_battery_scalar_misc2]
- `IF.EAGER(TRUE(),BLANK(),1)` (Power BI: `BLANK`) [dax_battery_scalar_misc2]
- `IF.EAGER(NOT TRUE(),1)` (Power BI: `BLANK`) [dax_battery_scalar_misc2]
- `IFERROR(1,ERROR("b"))` (Power BI: `1`) [dax_battery_scalar_misc2]
- `ISERROR(ERROR("a"))` (Power BI: `True`) [dax_battery_scalar_misc2]
- `IFERROR(ERROR("a")+1,0)` (Power BI: `0`) [dax_battery_scalar_misc2]
- `SUMX(Facts,IF(Facts[Quantity]>10,ERROR("big"),1))` (Power BI: `6`) [dax_battery_scalar_misc2]
- `ISBLANK(IFERROR(ERROR("a"),BLANK()))` (Power BI: `True`) [dax_battery_scalar_misc2]
- `CUSTOMDATA()&"x"` (Power BI: `x`) [dax_battery_scalar_misc2]
- `ISBLANK(CUSTOMDATA())` (Power BI: `True`) [dax_battery_scalar_misc2]
- `LEN(CUSTOMDATA())` (Power BI: `BLANK`) [dax_battery_scalar_misc2]
- `IF.EAGER(TRUE(),1,2)+IF.EAGER(FALSE(),1,2)` (Power BI: `3`) [dax_battery_scalar_misc2]
- `ISAFTER(2,1)=TRUE()` (Power BI: `True`) [dax_battery_scalar_misc2]
- `IF(ISAFTER(3,2),"after","not")` (Power BI: `after`) [dax_battery_scalar_misc2]
- `ISAFTER("a","B")` (Power BI: `False`) [dax_battery_scalar_misc2]
- `ISAFTER("B","a")` (Power BI: `True`) [dax_battery_scalar_misc2]
- `ISAFTER(DATE(2020,1,2),DATE(2020,1,1))` (Power BI: `True`) [dax_battery_scalar_misc2]
- `ISAFTER(TRUE(),FALSE())` (Power BI: `True`) [dax_battery_scalar_misc2]
- `ISAFTER(2,1,ASC)` (Power BI: `True`) [dax_battery_scalar_misc2]
- `ISAFTER(1,1,ASC,3,2)` (Power BI: `True`) [dax_battery_scalar_misc2]
- `ISAFTER(1,1,ASC,2,2)` (Power BI: `False`) [dax_battery_scalar_misc2]
- `ISAFTER(1,1,DESC,1,2)` (Power BI: `False`) [dax_battery_scalar_misc2]
- `ISAFTER(BLANK(),BLANK())` (Power BI: `False`) [dax_battery_scalar_misc2]
- `ISAFTER(BLANK(),-1)` (Power BI: `True`) [dax_battery_scalar_misc2]
- `ISAFTER(-1,BLANK())` (Power BI: `False`) [dax_battery_scalar_misc2]
- `ISAFTER(BLANK(),0)` (Power BI: `False`) [dax_battery_scalar_misc2]
- `ISAFTER(0,BLANK())` (Power BI: `True`) [dax_battery_scalar_misc2]
- `ISAFTER(BLANK(),"")` (Power BI: `False`) [dax_battery_scalar_misc2]
- `ISAFTER("",BLANK())` (Power BI: `True`) [dax_battery_scalar_misc2]
- `ISAFTER(1/0,1)` (Power BI: `True`) [dax_battery_scalar_misc2]
- `ISAFTER(1,1/0)` (Power BI: `False`) [dax_battery_scalar_misc2]
- `EVALUATEANDLOG(1)+EVALUATEANDLOG(2)` (Power BI: `3`) [dax_battery_scalar_misc2]
- `SUMX(Facts,EVALUATEANDLOG(Facts[Quantity]))` (Power BI: `15`) [dax_battery_scalar_misc2]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>EVALUATEANDLOG(3))` (Power BI: `2`) [dax_battery_scalar_misc2]
- `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>EVALUATEANDLOG(SUM(Facts[Quantity])/6))` (Power BI: `3`) [dax_battery_scalar_misc2]
- `EVALUATEANDLOG(1/0)` (Power BI: `Infinity`) [dax_battery_scalar_misc2]
- `EVALUATEANDLOG(TRUE())` (Power BI: `True`) [dax_battery_scalar_misc2]
- `EVALUATEANDLOG(DATE(2020,1,1))=DATE(2020,1,1)` (Power BI: `True`) [dax_battery_scalar_misc2]
- `LEN(EVALUATEANDLOG("abc","label"))` (Power BI: `3`) [dax_battery_scalar_misc2]
- `COUNTROWS(EVALUATEANDLOG(VALUES(Facts[Region])))` (Power BI: `3`) [dax_battery_scalar_misc2]
- `COUNTROWS(EVALUATEANDLOG(Facts,"t",2))` (Power BI: `6`) [dax_battery_scalar_misc2]
- `SUMX(EVALUATEANDLOG(Facts),Facts[Quantity])` (Power BI: `15`) [dax_battery_scalar_misc2]
- `NAMEOF(Facts[Region])` (Power BI: `'Facts'[Region]`) [dax_battery_scalar_misc2]
- `NAMEOF(Facts[Sales])&"x"` (Power BI: `'Facts'[Sales]x`) [dax_battery_scalar_misc2]
- `LEN(NAMEOF(Facts))` (Power BI: `7`) [dax_battery_scalar_misc2]
- `NAMEOF(Facts[Note])=NAMEOF(Facts[Note])` (Power BI: `True`) [dax_battery_scalar_misc2]
- `COUNTROWS(TABLEOF(Facts[Region]))` (Power BI: `6`) [dax_battery_scalar_misc2]
- `SUMX(TABLEOF(Facts[Quantity]),Facts[Quantity])` (Power BI: `15`) [dax_battery_scalar_misc2]
- `COUNTROWS(TABLEOF(Facts[Sales]))+1` (Power BI: `7`) [dax_battery_scalar_misc2]
- `COUNTROWS(FILTER(TABLEOF(Facts[Quantity]),Facts[Quantity]>2))` (Power BI: `3`) [dax_battery_scalar_misc2]
- `ISINTEGER(1)` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(1.5)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER("a")` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(TRUE())` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(BLANK())` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(CURRENCY(1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(DATE(2020,1,1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(1/2)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(2/1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(SUM(Facts[Sales]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(SUM(Facts[Quantity]))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(COUNTROWS(Facts))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(AVERAGE(Facts[Quantity]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(INT(2.5))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(ROUND(2.5,0))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(POWER(2,2))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(SQRT(4))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(1000000000000)` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(0.1+0.2)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(1E0)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(MAX(Facts[Quantity]))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(MAX(Facts[Sales]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(MIN(Facts[Quantity]))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(COUNT(Facts[Sales]))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(DISTINCTCOUNT(Facts[Region]))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(AVERAGE(Facts[Sales]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(DIVIDE(1,2))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(DIVIDE(4,2))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(1+1)` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(1+1.5)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(2*3)` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(2*0.5)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(-1)` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(ABS(-1))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(MOD(7,3))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(FLOOR(2.5,1))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(CEILING(2.5,1))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(TRUNC(2.5))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(LEN("abc"))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(YEAR(DATE(2020,1,1)))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(VALUE("5"))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(SUM(Facts[Quantity])+1)` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(SUM(Facts[Quantity])/1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(SUM(Facts[Quantity])*1.0)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(CURRENCY(1)+1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(CURRENCY(1)*2)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(CURRENCY(1)+1.5)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(CURRENCY(1)/2)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(FIXED(1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(ROUND(CURRENCY(1.234),1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(1=1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER("1")` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(1E15)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(9223372036854775807)` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(9223372036854775808)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(-9223372036854775808)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(1E19)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(CALCULATE(SUM(Facts[Quantity]),Facts[Region]="Nope"))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(SUM(Facts[Sales])*CURRENCY(1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(1)` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(1.5)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64("a")` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(TRUE())` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(BLANK())` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(CURRENCY(1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(DATE(2020,1,1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(1/2)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(2/1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(SUM(Facts[Sales]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(SUM(Facts[Quantity]))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(COUNTROWS(Facts))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(AVERAGE(Facts[Quantity]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(INT(2.5))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(ROUND(2.5,0))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(POWER(2,2))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(SQRT(4))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(1000000000000)` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(0.1+0.2)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(1E0)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(MAX(Facts[Quantity]))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(MAX(Facts[Sales]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(MIN(Facts[Quantity]))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(COUNT(Facts[Sales]))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(DISTINCTCOUNT(Facts[Region]))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(AVERAGE(Facts[Sales]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(DIVIDE(1,2))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(DIVIDE(4,2))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(1+1)` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(1+1.5)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(2*3)` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(2*0.5)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(-1)` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(ABS(-1))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(MOD(7,3))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(FLOOR(2.5,1))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(CEILING(2.5,1))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(TRUNC(2.5))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(LEN("abc"))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(YEAR(DATE(2020,1,1)))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(VALUE("5"))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(SUM(Facts[Quantity])+1)` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(SUM(Facts[Quantity])/1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(SUM(Facts[Quantity])*1.0)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(CURRENCY(1)+1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(CURRENCY(1)*2)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(CURRENCY(1)+1.5)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(CURRENCY(1)/2)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(FIXED(1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(ROUND(CURRENCY(1.234),1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(1=1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64("1")` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(1E15)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(9223372036854775807)` (Power BI: `True`) [dax_battery_type_tests]
- `ISINT64(9223372036854775808)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(-9223372036854775808)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(1E19)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(CALCULATE(SUM(Facts[Quantity]),Facts[Region]="Nope"))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINT64(SUM(Facts[Sales])*CURRENCY(1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(1.5)` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE("a")` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(TRUE())` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(BLANK())` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(CURRENCY(1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(DATE(2020,1,1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(1/2)` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(2/1)` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(SUM(Facts[Sales]))` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(SUM(Facts[Quantity]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(COUNTROWS(Facts))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(AVERAGE(Facts[Quantity]))` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(INT(2.5))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(ROUND(2.5,0))` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(POWER(2,2))` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(SQRT(4))` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(1000000000000)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(0.1+0.2)` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(1E0)` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(MAX(Facts[Quantity]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(MAX(Facts[Sales]))` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(MIN(Facts[Quantity]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(COUNT(Facts[Sales]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(DISTINCTCOUNT(Facts[Region]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(AVERAGE(Facts[Sales]))` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(DIVIDE(1,2))` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(DIVIDE(4,2))` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(1+1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(1+1.5)` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(2*3)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(2*0.5)` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(-1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(ABS(-1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(MOD(7,3))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(FLOOR(2.5,1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(CEILING(2.5,1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(TRUNC(2.5))` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(LEN("abc"))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(YEAR(DATE(2020,1,1)))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(VALUE("5"))` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(SUM(Facts[Quantity])+1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(SUM(Facts[Quantity])/1)` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(SUM(Facts[Quantity])*1.0)` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(CURRENCY(1)+1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(CURRENCY(1)*2)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(CURRENCY(1)+1.5)` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(CURRENCY(1)/2)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(FIXED(1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(ROUND(CURRENCY(1.234),1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(1=1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE("1")` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(1E15)` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(9223372036854775807)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(9223372036854775808)` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(-9223372036854775808)` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(1E19)` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(CALCULATE(SUM(Facts[Quantity]),Facts[Region]="Nope"))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDOUBLE(SUM(Facts[Sales])*CURRENCY(1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(1.5)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL("a")` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(TRUE())` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(BLANK())` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(CURRENCY(1))` (Power BI: `True`) [dax_battery_type_tests]
- `ISDECIMAL(DATE(2020,1,1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(1/2)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(2/1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(SUM(Facts[Sales]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(SUM(Facts[Quantity]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(COUNTROWS(Facts))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(AVERAGE(Facts[Quantity]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(INT(2.5))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(ROUND(2.5,0))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(POWER(2,2))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(SQRT(4))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(1000000000000)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(0.1+0.2)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(1E0)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(MAX(Facts[Quantity]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(MAX(Facts[Sales]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(MIN(Facts[Quantity]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(COUNT(Facts[Sales]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(DISTINCTCOUNT(Facts[Region]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(AVERAGE(Facts[Sales]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(DIVIDE(1,2))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(DIVIDE(4,2))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(1+1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(1+1.5)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(2*3)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(2*0.5)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(-1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(ABS(-1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(MOD(7,3))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(FLOOR(2.5,1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(CEILING(2.5,1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(TRUNC(2.5))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(LEN("abc"))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(YEAR(DATE(2020,1,1)))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(VALUE("5"))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(SUM(Facts[Quantity])+1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(SUM(Facts[Quantity])/1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(SUM(Facts[Quantity])*1.0)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(CURRENCY(1)+1)` (Power BI: `True`) [dax_battery_type_tests]
- `ISDECIMAL(CURRENCY(1)*2)` (Power BI: `True`) [dax_battery_type_tests]
- `ISDECIMAL(CURRENCY(1)+1.5)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(CURRENCY(1)/2)` (Power BI: `True`) [dax_battery_type_tests]
- `ISDECIMAL(FIXED(1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(ROUND(CURRENCY(1.234),1))` (Power BI: `True`) [dax_battery_type_tests]
- `ISDECIMAL(1=1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL("1")` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(1E15)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(9223372036854775807)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(9223372036854775808)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(-9223372036854775808)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(1E19)` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(CALCULATE(SUM(Facts[Quantity]),Facts[Region]="Nope"))` (Power BI: `False`) [dax_battery_type_tests]
- `ISDECIMAL(SUM(Facts[Sales])*CURRENCY(1))` (Power BI: `True`) [dax_battery_type_tests]
- `ISCURRENCY(1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(1.5)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY("a")` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(TRUE())` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(BLANK())` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(CURRENCY(1))` (Power BI: `True`) [dax_battery_type_tests]
- `ISCURRENCY(DATE(2020,1,1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(1/2)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(2/1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(SUM(Facts[Sales]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(SUM(Facts[Quantity]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(COUNTROWS(Facts))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(AVERAGE(Facts[Quantity]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(INT(2.5))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(ROUND(2.5,0))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(POWER(2,2))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(SQRT(4))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(1000000000000)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(0.1+0.2)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(1E0)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(MAX(Facts[Quantity]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(MAX(Facts[Sales]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(MIN(Facts[Quantity]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(COUNT(Facts[Sales]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(DISTINCTCOUNT(Facts[Region]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(AVERAGE(Facts[Sales]))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(DIVIDE(1,2))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(DIVIDE(4,2))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(1+1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(1+1.5)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(2*3)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(2*0.5)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(-1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(ABS(-1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(MOD(7,3))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(FLOOR(2.5,1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(CEILING(2.5,1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(TRUNC(2.5))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(LEN("abc"))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(YEAR(DATE(2020,1,1)))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(VALUE("5"))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(SUM(Facts[Quantity])+1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(SUM(Facts[Quantity])/1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(SUM(Facts[Quantity])*1.0)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(CURRENCY(1)+1)` (Power BI: `True`) [dax_battery_type_tests]
- `ISCURRENCY(CURRENCY(1)*2)` (Power BI: `True`) [dax_battery_type_tests]
- `ISCURRENCY(CURRENCY(1)+1.5)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(CURRENCY(1)/2)` (Power BI: `True`) [dax_battery_type_tests]
- `ISCURRENCY(FIXED(1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(ROUND(CURRENCY(1.234),1))` (Power BI: `True`) [dax_battery_type_tests]
- `ISCURRENCY(1=1)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY("1")` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(1E15)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(9223372036854775807)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(9223372036854775808)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(-9223372036854775808)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(1E19)` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(CALCULATE(SUM(Facts[Quantity]),Facts[Region]="Nope"))` (Power BI: `False`) [dax_battery_type_tests]
- `ISCURRENCY(SUM(Facts[Sales])*CURRENCY(1))` (Power BI: `True`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISINTEGER(Facts[Sales]),1,0))` (Power BI: `0`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISINTEGER(Facts[Quantity]),1,0))` (Power BI: `6`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISINTEGER(Facts[Region]),1,0))` (Power BI: `0`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISINTEGER(Facts[Quantity]+1),1,0))` (Power BI: `6`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISINTEGER(Facts[Quantity]*0.5),1,0))` (Power BI: `0`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISDOUBLE(Facts[Sales]),1,0))` (Power BI: `5`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISDOUBLE(Facts[Quantity]),1,0))` (Power BI: `0`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISDOUBLE(Facts[Region]),1,0))` (Power BI: `0`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISDOUBLE(Facts[Quantity]+1),1,0))` (Power BI: `0`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISDOUBLE(Facts[Quantity]*0.5),1,0))` (Power BI: `6`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISDECIMAL(Facts[Sales]),1,0))` (Power BI: `0`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISDECIMAL(Facts[Quantity]),1,0))` (Power BI: `0`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISDECIMAL(Facts[Region]),1,0))` (Power BI: `0`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISDECIMAL(Facts[Quantity]+1),1,0))` (Power BI: `0`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISDECIMAL(Facts[Quantity]*0.5),1,0))` (Power BI: `0`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISCURRENCY(Facts[Sales]),1,0))` (Power BI: `0`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISCURRENCY(Facts[Quantity]),1,0))` (Power BI: `0`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISCURRENCY(Facts[Region]),1,0))` (Power BI: `0`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISCURRENCY(Facts[Quantity]+1),1,0))` (Power BI: `0`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISCURRENCY(Facts[Quantity]*0.5),1,0))` (Power BI: `0`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISINT64(Facts[Sales]),1,0))` (Power BI: `0`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISINT64(Facts[Quantity]),1,0))` (Power BI: `6`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISINT64(Facts[Region]),1,0))` (Power BI: `0`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISINT64(Facts[Quantity]+1),1,0))` (Power BI: `6`) [dax_battery_type_tests]
- `SUMX(Facts,IF(ISINT64(Facts[Quantity]*0.5),1,0))` (Power BI: `0`) [dax_battery_type_tests]
- `ISINTEGER(1)+0` (Power BI: `1`) [dax_battery_type_tests]
- `ISINTEGER(TRUE())+0` (Power BI: `0`) [dax_battery_type_tests]
- `ISINTEGER(BLANK())&"x"` (Power BI: `FALSEx`) [dax_battery_type_tests]
- `IF(ISINTEGER(1),"i","n")` (Power BI: `i`) [dax_battery_type_tests]
- `NOT ISINTEGER(1.5)` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(1) && ISDOUBLE(1.5)` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(ISINTEGER(1))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(LEN("abc")+1)` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(IF(TRUE(),1,2.5))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(IF(FALSE(),1,2.5))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(IF(TRUE(),1))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(SWITCH(1,1,2,3))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(COALESCE(BLANK(),1))` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(COALESCE(BLANK(),1.5))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(MAXX(Facts,Facts[Quantity]))` (Power BI: `True`) [dax_battery_type_tests]
- `ISDOUBLE(SUMX(Facts,Facts[Sales]))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(SUMX(Facts,Facts[Quantity]))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(COUNTROWS(Facts)/2)` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(COUNTROWS(Facts)*2)` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(COUNTROWS(Facts)-1)` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(INT(SUM(Facts[Sales])))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(ROUNDUP(2.1,0))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(ROUNDDOWN(2.9,0))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(SIGN(-3))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(POWER(2,3))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(RANDBETWEEN(1,1))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(DATEDIFF(DATE(2020,1,1),DATE(2020,1,3),DAY))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(MONTH(DATE(2020,5,1)))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(WEEKDAY(DATE(2020,5,1)))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(FIND("a","bca"))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(SEARCH("a","bca"))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(UNICODE("A"))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(EXACT("a","a"))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(GCD(4,6))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(LCM(4,6))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(FACT(3))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(COMBIN(5,2))` (Power BI: `False`) [dax_battery_type_tests]
- `ISINTEGER(QUOTIENT(7,2))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(EVEN(3))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(ODD(2))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(MROUND(7,5))` (Power BI: `True`) [dax_battery_type_tests]
- `ISINTEGER(RANKX(ALL(Facts[Quantity]),1))` (Power BI: `True`) [dax_battery_type_tests]
- `LEN(TOCSV(Facts))` (Power BI: `147`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1))` (Power BI: `[a]
1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1,"b","x"),0)` (Power BI: `[a],[b]
`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),5,",")` (Power BI: `[a]
1`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",1))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[1]
	]
}`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",1,"b","x"))` (Power BI: `{
	"header": ["[a]", "[b]"],
	"rowCount": 1,
	"data": [
		[1`) [dax_battery_tocsv_tojson]
- `LEN(TOJSON(Facts))` (Power BI: `289`) [dax_battery_tocsv_tojson]
- `TOCSV(DATATABLE("a",INTEGER,"b",STRING,{{1,"x"},{2,"y,z"}}),5,";")` (Power BI: `[a];[b]
1;x
2;y,z`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1,"b","x"))` (Power BI: `[a],[b]
1,x`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),5)` (Power BI: `[a]
1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),5,";")` (Power BI: `[a]
1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),5,";",FALSE())` (Power BI: `1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),5,";",TRUE())` (Power BI: `[a]
1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),0)` (Power BI: `[a]
`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),-1)` (Power BI: `[a]
1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),1.5)` (Power BI: `[a]
1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),BLANK())` (Power BI: `[a]
`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),5,BLANK())` (Power BI: `"[a]"
"1"`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),5,"")` (Power BI: `"[a]"
"1"`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1,"b",2),5,"||")` (Power BI: `[a]||[b]
1||2`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1,"b",2),5,"tab")` (Power BI: `[a]tab[b]
1tab2`) [dax_battery_tocsv_tojson]
- `TOCSV(Facts)` (Power BI: `'Facts'[Sales],'Facts'[Quantity],'Facts'[Region],'Facts'[Not`) [dax_battery_tocsv_tojson]
- `TOCSV(Facts,2)` (Power BI: `'Facts'[Sales],'Facts'[Quantity],'Facts'[Region],'Facts'[Not`) [dax_battery_tocsv_tojson]
- `TOCSV(Facts,2,";",FALSE())` (Power BI: `10.5;2;East;Paid
20;3;West;`) [dax_battery_tocsv_tojson]
- `TOCSV(VALUES(Facts[Region]))` (Power BI: `'Facts'[Region]
East
West
North`) [dax_battery_tocsv_tojson]
- `TOCSV(VALUES(Facts[Region]),1)` (Power BI: `'Facts'[Region]
East`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a","x,y","b","say ""hi""","c","l1"&UNICHAR(10)&"l2"))` (Power BI: `[a],[b],[c]
"x,y","say ""hi""","l1
l2"`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",BLANK(),"b",""))` (Power BI: `[a],[b]
,`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",TRUE(),"b",1.5,"c",DATE(2020,1,2),"d",CURRENCY(2.25)))` (Power BI: `[a],[b],[c],[d]
TRUE,1.5,1/2/2020,2.25`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1/3))` (Power BI: `[a]
0.333333333333333`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1000000000000000000))` (Power BI: `[a]
1000000000000000000`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",-0.0))` (Power BI: `[a]
-0`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1E20))` (Power BI: `[a]
1E+20`) [dax_battery_tocsv_tojson]
- `TOCSV(FILTER(Facts,FALSE()))` (Power BI: `'Facts'[Sales],'Facts'[Quantity],'Facts'[Region],'Facts'[Not`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a b",1))` (Power BI: `[a b]
1`) [dax_battery_tocsv_tojson]
- `TOCSV(DATATABLE("a",INTEGER,"b",STRING,{{1,"x"},{2,"y,z"}}))` (Power BI: `[a],[b]
1,x
2,"y,z"`) [dax_battery_tocsv_tojson]
- `TOCSV(SELECTCOLUMNS(Facts,"Region",Facts[Region],"Q",Facts[Quantity]),3)` (Power BI: `[Region],[Q]
East,2
West,3
East,1`) [dax_battery_tocsv_tojson]
- `TOCSV(TOPN(2,Facts,Facts[Quantity]))` (Power BI: `'Facts'[Sales],'Facts'[Quantity],'Facts'[Region],'Facts'[Not`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1))&"|"` (Power BI: `[a]
1|`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",1),0)` (Power BI: `BLANK`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",1),5)` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[1]
	]
}`) [dax_battery_tocsv_tojson]
- `TOJSON(Facts)` (Power BI: `{
	"header": ["'Facts'[Sales]", "'Facts'[Quantity]", "'Facts`) [dax_battery_tocsv_tojson]
- `TOJSON(Facts,2)` (Power BI: `{
	"header": ["'Facts'[Sales]", "'Facts'[Quantity]", "'Facts`) [dax_battery_tocsv_tojson]
- `TOJSON(VALUES(Facts[Region]))` (Power BI: `{
	"header": ["'Facts'[Region]"],
	"rowCount": 3,
	"data": [`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",BLANK(),"b",""))` (Power BI: `{
	"header": ["[a]", "[b]"],
	"rowCount": 1,
	"data": [
		[n`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",TRUE(),"b",1.5,"c",DATE(2020,1,2),"d",CURRENCY(2.25)))` (Power BI: `{
	"header": ["[a]", "[b]", "[c]", "[d]"],
	"rowCount": 1,
	`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",1/3))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[0.3333]
`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a","q""uote","b","new"&UNICHAR(10)&"line","c","\"))` (Power BI: `{
	"header": ["[a]", "[b]", "[c]"],
	"rowCount": 1,
	"data":`) [dax_battery_tocsv_tojson]
- `TOJSON(FILTER(Facts,FALSE()))` (Power BI: `BLANK`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",1000000000000000000))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[10000000`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",1E20))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[10000000`) [dax_battery_tocsv_tojson]
- `LEN(TOJSON(ROW("a",1)))` (Power BI: `59`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),5,";",1)` (Power BI: `[a]
1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),5,";",0)` (Power BI: `1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),5,";",BLANK())` (Power BI: `1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),"2")` (Power BI: `[a]
1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),TRUE())` (Power BI: `[a]
1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),2,TRUE())` (Power BI: `[a]
1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),2,1)` (Power BI: `[a]
"1"`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),2,";;;")` (Power BI: `[a]
1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),5,",",FALSE())` (Power BI: `1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),5,"""")` (Power BI: `[a]
1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1,"b",2),5,"""")` (Power BI: `[a]"[b]
1"2`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a","x""y"),5,"""")` (Power BI: `[a]
"x""y"`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a","x;y"),5,";")` (Power BI: `[a]
"x;y"`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a","x"&UNICHAR(13)&"y"))` (Power BI: `[a]
xy`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a"," x "))` (Power BI: `[a]
 x `) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a","x"&UNICHAR(9)&"y"))` (Power BI: `[a]
x	y`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a","é€😀"))` (Power BI: `[a]
é€😀`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1.10))` (Power BI: `[a]
1.1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",0.1+0.2))` (Power BI: `[a]
0.3`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",100000000000000))` (Power BI: `[a]
100000000000000`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",123456789.123456789))` (Power BI: `[a]
123456789.123457`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",0.000001))` (Power BI: `[a]
0.000001`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",0.0000001))` (Power BI: `[a]
0.0000001`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1E-10))` (Power BI: `[a]
0.0000000001`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",-1.5E300))` (Power BI: `[a]
-1.5E+300`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1/0))` (Power BI: `[a]
inf`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",-1/0))` (Power BI: `[a]
-inf`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",0/0))` (Power BI: `[a]
-nan(ind)`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",DATE(2020,1,2)+TIME(3,4,5)))` (Power BI: `[a]
1/2/2020 3:04:05 AM`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",DATE(2020,12,31)))` (Power BI: `[a]
12/31/2020`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",TIME(3,4,5)))` (Power BI: `[a]
3:04:05 AM`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",CURRENCY(1)))` (Power BI: `[a]
1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",CURRENCY(1.5)))` (Power BI: `[a]
1.5`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",CURRENCY(1234.5678)))` (Power BI: `[a]
1234.5678`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",TRUE(),"b",FALSE()))` (Power BI: `[a],[b]
TRUE,FALSE`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",BLANK(),"b",BLANK()))` (Power BI: `[a],[b]
,`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",""))` (Power BI: `[a]
`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a","","b",""))` (Power BI: `[a],[b]
,`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),2,";",TRUE())` (Power BI: `[a]
1`) [dax_battery_tocsv_tojson]
- `TOCSV({1,2,3})` (Power BI: `[Value]
1
2
3`) [dax_battery_tocsv_tojson]
- `TOCSV({1,2,3},2)` (Power BI: `[Value]
1
2`) [dax_battery_tocsv_tojson]
- `TOCSV({(1,"a"),(2,"b")})` (Power BI: `[Value1],[Value2]
1,a
2,b`) [dax_battery_tocsv_tojson]
- `TOCSV(GENERATESERIES(1,3))` (Power BI: `[Value]
1
2
3`) [dax_battery_tocsv_tojson]
- `TOCSV(GENERATESERIES(1,3,1.5))` (Power BI: `[Value]
1
2.5`) [dax_battery_tocsv_tojson]
- `TOCSV(CALENDAR(DATE(2020,1,1),DATE(2020,1,3)))` (Power BI: `[Date]
1/1/2020
1/2/2020
1/3/2020`) [dax_battery_tocsv_tojson]
- `TOCSV(TOPN(2,VALUES(Facts[Quantity]),Facts[Quantity]))` (Power BI: `'Facts'[Quantity]
4
5`) [dax_battery_tocsv_tojson]
- `TOCSV(DISTINCT(Facts[Region]))` (Power BI: `'Facts'[Region]
East
West
North`) [dax_battery_tocsv_tojson]
- `TOCSV(ALL(Facts[Region]))` (Power BI: `'Facts'[Region]
East
West
North`) [dax_battery_tocsv_tojson]
- `TOCSV(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])))` (Power BI: `'Facts'[Region],[s]
East,8
West,3
North,4`) [dax_battery_tocsv_tojson]
- `TOCSV(ADDCOLUMNS(VALUES(Facts[Region]),"n",COUNTROWS(Facts)))` (Power BI: `'Facts'[Region],[n]
East,6
West,6
North,6`) [dax_battery_tocsv_tojson]
- `TOCSV(SELECTCOLUMNS(Facts,"A",Facts[Sales]))` (Power BI: `[A]
10.5
20
-1.5

0
2.5`) [dax_battery_tocsv_tojson]
- `TOCSV(SELECTCOLUMNS(Facts,"A",Facts[Sales]),0)` (Power BI: `[A]
`) [dax_battery_tocsv_tojson]
- `TOCSV(SELECTCOLUMNS(Facts,"A",Facts[Sales]),100)` (Power BI: `[A]
10.5
20
-1.5

0
2.5`) [dax_battery_tocsv_tojson]
- `TOCSV(SELECTCOLUMNS(Facts,"A",Facts[Sales]),1,"|")` (Power BI: `[A]
10.5`) [dax_battery_tocsv_tojson]
- `TOCSV(CROSSJOIN(VALUES(Facts[Region]),VALUES(Facts[Note])))` (Power BI: `'Facts'[Region],'Facts'[Note]
East,
West,
North,
East,Paid
W`) [dax_battery_tocsv_tojson]
- `TOCSV(UNION(ROW("a",1),ROW("a",2)))` (Power BI: `[a]
1
2`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a",1),2)&TOCSV(ROW("a",2),2)` (Power BI: `[a]
1[a]
2`) [dax_battery_tocsv_tojson]
- `LEN(TOCSV(ROW("a",1)))` (Power BI: `5`) [dax_battery_tocsv_tojson]
- `LEFT(TOCSV(Facts),10)` (Power BI: `'Facts'[Sa`) [dax_battery_tocsv_tojson]
- `SUBSTITUTE(TOCSV(ROW("a",1)),UNICHAR(10),"|")` (Power BI: `[a]|1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("[a]",1))` (Power BI: `[[a]]]
1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("a,b",1))` (Power BI: `"[a,b]"
1`) [dax_battery_tocsv_tojson]
- `TOCSV(ROW("é",1))` (Power BI: `[é]
1`) [dax_battery_tocsv_tojson]
- `TOCSV(Facts,-1)` (Power BI: `'Facts'[Sales],'Facts'[Quantity],'Facts'[Region],'Facts'[Not`) [dax_battery_tocsv_tojson]
- `TOCSV(Facts,1000)` (Power BI: `'Facts'[Sales],'Facts'[Quantity],'Facts'[Region],'Facts'[Not`) [dax_battery_tocsv_tojson]
- `TOCSV(Facts,1E10)` (Power BI: `'Facts'[Sales],'Facts'[Quantity],'Facts'[Region],'Facts'[Not`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",1),1)` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[1]
	]
}`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",1),-1)` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[1]
	]
}`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",1),1.5)` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[1]
	]
}`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",1),BLANK())` (Power BI: `BLANK`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",1),"2")` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[1]
	]
}`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",1),TRUE())` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[1]
	]
}`) [dax_battery_tocsv_tojson]
- `TOJSON({1,2,3})` (Power BI: `{
	"header": ["[Value]"],
	"rowCount": 3,
	"data": [
		[1],
`) [dax_battery_tocsv_tojson]
- `TOJSON({(1,"a"),(2,"b")})` (Power BI: `{
	"header": ["[Value1]", "[Value2]"],
	"rowCount": 2,
	"dat`) [dax_battery_tocsv_tojson]
- `TOJSON(GENERATESERIES(1,3))` (Power BI: `{
	"header": ["[Value]"],
	"rowCount": 3,
	"data": [
		[1],
`) [dax_battery_tocsv_tojson]
- `TOJSON(CALENDAR(DATE(2020,1,1),DATE(2020,1,3)))` (Power BI: `{
	"header": ["[Date]"],
	"rowCount": 3,
	"data": [
		["2020`) [dax_battery_tocsv_tojson]
- `TOJSON(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])))` (Power BI: `{
	"header": ["'Facts'[Region]", "[s]"],
	"rowCount": 3,
	"d`) [dax_battery_tocsv_tojson]
- `TOJSON(SELECTCOLUMNS(Facts,"A",Facts[Sales]))` (Power BI: `{
	"header": ["[A]"],
	"rowCount": 6,
	"data": [
		[10.5],
	`) [dax_battery_tocsv_tojson]
- `TOJSON(SELECTCOLUMNS(Facts,"A",Facts[Sales]),2)` (Power BI: `{
	"header": ["[A]"],
	"rowCount": 6,
	"data": [
		[10.5],
	`) [dax_battery_tocsv_tojson]
- `TOJSON(TOPN(2,Facts,Facts[Quantity]))` (Power BI: `{
	"header": ["'Facts'[Sales]", "'Facts'[Quantity]", "'Facts`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",0.1+0.2))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[0.3]
	]
`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",1.10))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[1.1]
	]
`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",100000000000000))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[10000000`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",123456789.123456789))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[12345678`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",0.000001))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[0.0]
	]
`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",0.0000001))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[0.0]
	]
`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",1E-10))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[0.0]
	]
`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",-1.5E300))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[-1.5e300`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",1/0))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[]
	]
}`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",0/0))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[]
	]
}`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",2/3))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[0.6666]
`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",12345.6789))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[12345.67`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",1234567.891234))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[1234567.`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",CURRENCY(1234.5678)))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[1234.567`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",CURRENCY(1)))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[1.0]
	]
`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",DATE(2020,1,2)+TIME(3,4,5)))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		["2020-01`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",TIME(3,4,5)))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		["1899-12`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",TRUE(),"b",FALSE()))` (Power BI: `{
	"header": ["[a]", "[b]"],
	"rowCount": 1,
	"data": [
		[t`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a",""))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		[""]
	]
}`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a","é€😀"))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		["é€😀"]
	`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a","x"&UNICHAR(9)&"y"))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		["x\ty"]
`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a","x"&UNICHAR(13)&"y"))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		["x\ry"]
`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a","<>&"))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		["<>&"]
	`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a","/"))` (Power BI: `{
	"header": ["[a]"],
	"rowCount": 1,
	"data": [
		["/"]
	]
`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a b",1))` (Power BI: `{
	"header": ["[a b]"],
	"rowCount": 1,
	"data": [
		[1]
	]
`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("a""b",1))` (Power BI: `{
	"header": ["[a\"b]"],
	"rowCount": 1,
	"data": [
		[1]
	]`) [dax_battery_tocsv_tojson]
- `TOJSON(ROW("é",1))` (Power BI: `{
	"header": ["[é]"],
	"rowCount": 1,
	"data": [
		[1]
	]
}`) [dax_battery_tocsv_tojson]
- `TOJSON(Facts,1000)` (Power BI: `{
	"header": ["'Facts'[Sales]", "'Facts'[Quantity]", "'Facts`) [dax_battery_tocsv_tojson]
- `LEN(TOJSON(VALUES(Facts[Region])))` (Power BI: `101`) [dax_battery_tocsv_tojson]
- `LEFT(TOJSON(Facts),12)` (Power BI: `{
	"header":`) [dax_battery_tocsv_tojson]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x]))` (Power BI: `[Slope1],[Intercept],[StandardErrorSlope1],[StandardErrorInt`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x]),[Slope1])` (Power BI: `1.97`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x]),[Intercept])` (Power BI: `0.0899999999999999`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x]),[StandardErrorSlope1])` (Power BI: `0.0550757054728609`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x]),[StandardErrorIntercept])` (Power BI: `0.182665450117603`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x]),[CoefficientOfDetermination])` (Power BI: `0.997660668380463`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x]),[StandardError])` (Power BI: `0.174164673034841`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x]),[FStatistic])` (Power BI: `1279.41758241759`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x]),[DegreesOfFreedom])` (Power BI: `3`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x]),[RegressionSumOfSquares])` (Power BI: `38.809`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x]),[ResidualSumOfSquares])` (Power BI: `0.0909999999999994`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z]))` (Power BI: `[Slope1],[Slope2],[Intercept],[StandardErrorSlope1],[Standar`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z]),[Slope1])` (Power BI: `1.85`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z]),[Slope2])` (Power BI: `0.15`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z]),[Intercept])` (Power BI: `4.44089209850063E-16`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z]),[StandardErrorSlope1])` (Power BI: `0.0372677996249961`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z]),[StandardErrorSlope2])` (Power BI: `0.0372677996249961`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z]),[StandardErrorIntercept])` (Power BI: `0.0774596669241475`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z]),[CoefficientOfDetermination])` (Power BI: `0.99974293059126`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z]),[StandardError])` (Power BI: `0.070710678118654`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z]),[FStatistic])` (Power BI: `3889.00000000008`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z]),[DegreesOfFreedom])` (Power BI: `2`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z]),[RegressionSumOfSquares])` (Power BI: `38.89`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z]),[ResidualSumOfSquares])` (Power BI: `0.0099999999999998`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],FALSE()))` (Power BI: `[Slope1],[StandardErrorSlope1],[CoefficientOfDetermination],`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],FALSE()),[Slope1])` (Power BI: `1.99454545454545`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],FALSE()),[StandardErrorSlope1])` (Power BI: `0.0211449151811145`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],FALSE()),[CoefficientOfDetermination])` (Power BI: `0.999550645790938`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],FALSE()),[StandardError])` (Power BI: `0.156814887975947`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],FALSE()),[FStatistic])` (Power BI: `8897.66358595201`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],FALSE()),[DegreesOfFreedom])` (Power BI: `4`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],FALSE()),[RegressionSumOfSquares])` (Power BI: `218.801636363636`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],FALSE()),[ResidualSumOfSquares])` (Power BI: `0.0983636363636356`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z],FALSE()))` (Power BI: `[Slope1],[Slope2],[StandardErrorSlope1],[StandardErrorSlope2`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z],FALSE()),[Slope1])` (Power BI: `1.85`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z],FALSE()),[Slope2])` (Power BI: `0.149999999999999`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z],FALSE()),[StandardErrorSlope1])` (Power BI: `0.0291335791158374`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z],FALSE()),[StandardErrorSlope2])` (Power BI: `0.0291335791158374`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z],FALSE()),[CoefficientOfDetermination])` (Power BI: `0.999954317039744`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z],FALSE()),[StandardError])` (Power BI: `0.0577350269189622`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z],FALSE()),[FStatistic])` (Power BI: `32833.5000000004`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z],FALSE()),[DegreesOfFreedom])` (Power BI: `3`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z],FALSE()),[RegressionSumOfSquares])` (Power BI: `218.89`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],[z],FALSE()),[ResidualSumOfSquares])` (Power BI: `0.00999999999999989`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],TRUE()))` (Power BI: `[Slope1],[Intercept],[StandardErrorSlope1],[StandardErrorInt`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],TRUE()),[Slope1])` (Power BI: `1.97`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],TRUE()),[Intercept])` (Power BI: `0.0899999999999999`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],TRUE()),[StandardErrorSlope1])` (Power BI: `0.0550757054728609`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],TRUE()),[StandardErrorIntercept])` (Power BI: `0.182665450117603`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],TRUE()),[CoefficientOfDetermination])` (Power BI: `0.997660668380463`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],TRUE()),[StandardError])` (Power BI: `0.174164673034841`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],TRUE()),[FStatistic])` (Power BI: `1279.41758241759`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],TRUE()),[DegreesOfFreedom])` (Power BI: `3`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],TRUE()),[RegressionSumOfSquares])` (Power BI: `38.809`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[y],[x],TRUE()),[ResidualSumOfSquares])` (Power BI: `0.0909999999999994`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x]))` (Power BI: `[Slope1],[Intercept],[StandardErrorSlope1],[StandardErrorInt`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x]),[Slope1])` (Power BI: `2.01428571428571`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x]),[Intercept])` (Power BI: `1.01428571428571`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x]),[StandardErrorSlope1])` (Power BI: `0.0367006645104718`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x]),[StandardErrorIntercept])` (Power BI: `0.164130361329658`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x]),[CoefficientOfDetermination])` (Power BI: `0.998342874359747`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x]),[StandardError])` (Power BI: `0.194201662491045`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x]),[FStatistic])` (Power BI: `3012.27272727273`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x]),[DegreesOfFreedom])` (Power BI: `5`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x]),[RegressionSumOfSquares])` (Power BI: `113.605714285714`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x]),[ResidualSumOfSquares])` (Power BI: `0.188571428571429`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z]))` (Power BI: `[Slope1],[Slope2],[Intercept],[StandardErrorSlope1],[Standar`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z]),[Slope1])` (Power BI: `2.05471698113208`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z]),[Slope2])` (Power BI: `-0.0452830188679243`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z]),[Intercept])` (Power BI: `1.03369272237197`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z]),[StandardErrorSlope1])` (Power BI: `0.0882567212341623`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z]),[StandardErrorSlope2])` (Power BI: `0.0882567212341623`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z]),[StandardErrorIntercept])` (Power BI: `0.181727338206772`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z]),[CoefficientOfDetermination])` (Power BI: `0.99844520115743`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z]),[StandardError])` (Power BI: `0.210313589503672`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z]),[FStatistic])` (Power BI: `1284.34003656307`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z]),[DegreesOfFreedom])` (Power BI: `4`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z]),[RegressionSumOfSquares])` (Power BI: `113.617358490566`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z]),[ResidualSumOfSquares])` (Power BI: `0.176927223719677`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],FALSE()))` (Power BI: `[Slope1],[StandardErrorSlope1],[CoefficientOfDetermination],`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],FALSE()),[Slope1])` (Power BI: `2.21714285714286`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],FALSE()),[StandardErrorSlope1])` (Power BI: `0.044035390838035`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],FALSE()),[CoefficientOfDetermination])` (Power BI: `0.997638755718283`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],FALSE()),[StandardError])` (Power BI: `0.521033770955578`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],FALSE()),[FStatistic])` (Power BI: `2535.03315207859`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],FALSE()),[DegreesOfFreedom])` (Power BI: `6`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],FALSE()),[RegressionSumOfSquares])` (Power BI: `688.201142857143`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],FALSE()),[ResidualSumOfSquares])` (Power BI: `1.62885714285714`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z],FALSE()))` (Power BI: `[Slope1],[Slope2],[StandardErrorSlope1],[StandardErrorSlope2`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z],FALSE()),[Slope1])` (Power BI: `2.15920577617328`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z],FALSE()),[Slope2])` (Power BI: `0.0592057761732855`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z],FALSE()),[StandardErrorSlope1])` (Power BI: `0.232770720620969`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z],FALSE()),[StandardErrorSlope2])` (Power BI: `0.232770720620969`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z],FALSE()),[CoefficientOfDetermination])` (Power BI: `0.997668917644179`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z],FALSE()),[StandardError])` (Power BI: `0.567106787389508`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z],FALSE()),[FStatistic])` (Power BI: `1069.9631816447`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z],FALSE()),[DegreesOfFreedom])` (Power BI: `5`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z],FALSE()),[RegressionSumOfSquares])` (Power BI: `688.221949458484`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z],FALSE()),[ResidualSumOfSquares])` (Power BI: `1.60805054151624`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],TRUE()))` (Power BI: `[Slope1],[Intercept],[StandardErrorSlope1],[StandardErrorInt`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],TRUE()),[Slope1])` (Power BI: `2.01428571428571`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],TRUE()),[Intercept])` (Power BI: `1.01428571428571`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],TRUE()),[StandardErrorSlope1])` (Power BI: `0.0367006645104718`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],TRUE()),[StandardErrorIntercept])` (Power BI: `0.164130361329658`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],TRUE()),[CoefficientOfDetermination])` (Power BI: `0.998342874359747`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],TRUE()),[StandardError])` (Power BI: `0.194201662491045`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],TRUE()),[FStatistic])` (Power BI: `3012.27272727273`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],TRUE()),[DegreesOfFreedom])` (Power BI: `5`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],TRUE()),[RegressionSumOfSquares])` (Power BI: `113.605714285714`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],TRUE()),[ResidualSumOfSquares])` (Power BI: `0.188571428571429`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z],[w]))` (Power BI: `[Slope1],[Slope2],[Slope3],[Intercept],[StandardErrorSlope1]`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z],[w]),[Slope3])` (Power BI: `-0.0553738317757009`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z],[w]),[RegressionSumOfSquares])` (Power BI: `113.650373831776`) [dax_battery_linest]
- `MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,"w",DOUBLE,{{1,3,1,7},{2,5.2,3,1},{3,6.9,2,8},{4,9.1,5,3},{5,11.2,4,9},{6,12.8,7,2},{7,15.3,6,5}}),[y],[x],[z],[w]),[StandardErrorSlope3])` (Power BI: `0.0667474043609174`) [dax_battery_linest]
- `TOCSV(LINEST(Facts[Quantity],Facts[Sales]))` (Power BI: `[Slope1],[Intercept],[StandardErrorSlope1],[StandardErrorInt`) [dax_battery_linest]
- `TOCSV(LINEST(Facts[Quantity],Facts[Sales],Facts[Quantity]))` (Power BI: `[Slope1],[Slope2],[Intercept],[StandardErrorSlope1],[Standar`) [dax_battery_linest]
- `TOCSV(LINEST(Facts[Quantity],Facts[Sales],FALSE()))` (Power BI: `[Slope1],[StandardErrorSlope1],[CoefficientOfDetermination],`) [dax_battery_linest]
- `TOCSV(LINEST(Facts[Quantity],Facts[Quantity]))` (Power BI: `[Slope1],[Intercept],[StandardErrorSlope1],[StandardErrorInt`) [dax_battery_linest]
- `TOCSV(LINEST(Facts[Sales],Facts[Quantity]))` (Power BI: `[Slope1],[Intercept],[StandardErrorSlope1],[StandardErrorInt`) [dax_battery_linest]
- `TOCSV(LINEST(Facts[Quantity],Facts[Sales],TRUE()))` (Power BI: `[Slope1],[Intercept],[StandardErrorSlope1],[StandardErrorInt`) [dax_battery_linest]
- `TOCSV(LINEST(Facts[Quantity],Facts[Sales],Facts[Quantity],FALSE()))` (Power BI: `[Slope1],[Slope2],[StandardErrorSlope1],[StandardErrorSlope2`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Quantity],Facts[Sales]),[Slope1])` (Power BI: `0.0374955783516095`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Sales],Facts[Quantity]),[Slope1])` (Power BI: `0.757142857142857`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Sales],Facts[Quantity],FALSE()),[Slope1])` (Power BI: `1.67272727272727`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Quantity],Facts[Sales]),[Intercept])` (Power BI: `2.30314821365405`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Sales],Facts[Quantity]),[Intercept])` (Power BI: `3.35714285714286`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Quantity],Facts[Sales]),[StandardErrorSlope1])` (Power BI: `0.109677417431646`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Sales],Facts[Quantity]),[StandardErrorSlope1])` (Power BI: `2.21470042199474`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Sales],Facts[Quantity],FALSE()),[StandardErrorSlope1])` (Power BI: `1.15185082826663`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Quantity],Facts[Sales]),[StandardErrorIntercept])` (Power BI: `1.01981323823361`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Sales],Facts[Quantity]),[StandardErrorIntercept])` (Power BI: `6.70533851687223`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Quantity],Facts[Sales]),[CoefficientOfDetermination])` (Power BI: `0.0283895093233614`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Sales],Facts[Quantity]),[CoefficientOfDetermination])` (Power BI: `0.0283895093233617`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Sales],Facts[Quantity],FALSE()),[CoefficientOfDetermination])` (Power BI: `0.29665717415115`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Quantity],Facts[Sales]),[StandardError])` (Power BI: `2.06174583707844`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Sales],Facts[Quantity]),[StandardError])` (Power BI: `9.26475656915573`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Sales],Facts[Quantity],FALSE()),[StandardError])` (Power BI: `8.54235436995084`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Quantity],Facts[Sales]),[FStatistic])` (Power BI: `0.116876092202713`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Sales],Facts[Quantity]),[FStatistic])` (Power BI: `0.116876092202714`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Sales],Facts[Quantity],FALSE()),[FStatistic])` (Power BI: `2.10890879417957`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Quantity],Facts[Sales]),[DegreesOfFreedom])` (Power BI: `4`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Sales],Facts[Quantity]),[DegreesOfFreedom])` (Power BI: `4`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Sales],Facts[Quantity],FALSE()),[DegreesOfFreedom])` (Power BI: `5`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Quantity],Facts[Sales]),[RegressionSumOfSquares])` (Power BI: `0.496816413158825`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Sales],Facts[Quantity]),[RegressionSumOfSquares])` (Power BI: `10.032142857143`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Sales],Facts[Quantity],FALSE()),[RegressionSumOfSquares])` (Power BI: `153.890909090909`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Quantity],Facts[Sales]),[ResidualSumOfSquares])` (Power BI: `17.0031835868412`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Sales],Facts[Quantity]),[ResidualSumOfSquares])` (Power BI: `343.342857142857`) [dax_battery_linest]
- `MAXX(LINEST(Facts[Sales],Facts[Quantity],FALSE()),[ResidualSumOfSquares])` (Power BI: `364.859090909091`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,2},{2,4},{3,6}}),[y],[x]))` (Power BI: `[Slope1],[Intercept],[StandardErrorSlope1],[StandardErrorInt`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,2},{2,4},{3,6}}),[y],[x],FALSE()))` (Power BI: `[Slope1],[StandardErrorSlope1],[CoefficientOfDetermination],`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,2}}),[y],[x]))` (Power BI: `[Slope1],[Intercept],[StandardErrorSlope1],[StandardErrorInt`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,2}}),[y],[x],FALSE()))` (Power BI: `[Slope1],[StandardErrorSlope1],[CoefficientOfDetermination],`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,2},{1,3}}),[y],[x]))` (Power BI: `[Slope1],[Intercept],[StandardErrorSlope1],[StandardErrorInt`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,2},{1,3}}),[y],[x],FALSE()))` (Power BI: `[Slope1],[StandardErrorSlope1],[CoefficientOfDetermination],`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,2},{2,3}}),[y],[x]))` (Power BI: `[Slope1],[Intercept],[StandardErrorSlope1],[StandardErrorInt`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,2},{2,3}}),[y],[x],FALSE()))` (Power BI: `[Slope1],[StandardErrorSlope1],[CoefficientOfDetermination],`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,5},{2,5},{3,5}}),[y],[x]))` (Power BI: `[Slope1],[Intercept],[StandardErrorSlope1],[StandardErrorInt`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,5},{2,5},{3,5}}),[y],[x],FALSE()))` (Power BI: `[Slope1],[StandardErrorSlope1],[CoefficientOfDetermination],`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,2},{2,4},{3,7},{4,8}}),[y],[x]))` (Power BI: `[Slope1],[Intercept],[StandardErrorSlope1],[StandardErrorInt`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,2},{2,4},{3,7},{4,8}}),[y],[x],FALSE()))` (Power BI: `[Slope1],[StandardErrorSlope1],[CoefficientOfDetermination],`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,2},{2,4},{3,6},{4,8.0000001}}),[y],[x]))` (Power BI: `[Slope1],[Intercept],[StandardErrorSlope1],[StandardErrorInt`) [dax_battery_linest]
- `TOCSV(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,2},{2,4},{3,6},{4,8.0000001}}),[y],[x],FALSE()))` (Power BI: `[Slope1],[StandardErrorSlope1],[CoefficientOfDetermination],`) [dax_battery_linest]
- `TOCSV(LINESTX(FILTER(DATATABLE("x",DOUBLE,"y",DOUBLE,"z",DOUBLE,{{1,2,1},{2,4.1,3},{3,5.9,2},{4,8.2,5},{5,9.8,4}}),[x]>10),[y],[x]))` (Power BI: `[Slope1],[Intercept],[StandardErrorSlope1],[StandardErrorInt`) [dax_battery_linest]
- `TOCSV(LINESTX(Facts,Facts[Quantity],Facts[Sales]))` (Power BI: `[Slope1],[Intercept],[StandardErrorSlope1],[StandardErrorInt`) [dax_battery_linest]
- `TOCSV(LINESTX(Facts,Facts[Quantity],Facts[Sales],Facts[Quantity]*2))` (Power BI: `[Slope1],[Slope2],[Intercept],[StandardErrorSlope1],[Standar`) [dax_battery_linest]
- `COUNTROWS(LINESTX(Facts,Facts[Quantity],Facts[Sales]))` (Power BI: `1`) [dax_battery_linest]
- `COUNTROWS(LINEST(Facts[Quantity],Facts[Sales]))` (Power BI: `1`) [dax_battery_linest]
- `COUNTROWS(LINEST(Facts[Quantity],Facts[Sales],FALSE()))` (Power BI: `1`) [dax_battery_linest]
- `TOCSV(LINESTX(Facts,Facts[Quantity],Facts[Sales]),1,";",FALSE())` (Power BI: `3.74955783516095E-02;2.30314821365405;0.109677417431646;1.01`) [dax_battery_linest]
- `LEN(TOCSV(LINESTX(Facts,Facts[Quantity],Facts[Sales])))` (Power BI: `358`) [dax_battery_linest]
- `CALCULATE(MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales]),[Slope1]),Facts[Region]="East")` (Power BI: `0.0178571428571428`) [dax_battery_linest]
- `CALCULATE(MAXX(LINEST(Facts[Quantity],Facts[Sales]),[Slope1]),Facts[Region]="East")` (Power BI: `0.0178571428571428`) [dax_battery_linest]
- `CALCULATE(MAXX(LINEST(Facts[Quantity],Facts[Sales]),[Slope1]),Facts[Quantity]>1)` (Power BI: `-0.09007164790174`) [dax_battery_linest]
- `MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales]),[Slope1]*2)` (Power BI: `0.074991156703219`) [dax_battery_linest]
- `MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales]),[Slope1])+1` (Power BI: `1.03749557835161`) [dax_battery_linest]
- `SUMX(LINESTX(Facts,Facts[Quantity],Facts[Sales]),[DegreesOfFreedom])` (Power BI: `4`) [dax_battery_linest]
- `ROUND(MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales]),[Slope1]),4)` (Power BI: `0.0375`) [dax_battery_linest]
- `TOCSV(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region]))` (Power BI: `[s],[i]
8,2
3,0
4,1`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region]))` (Power BI: `3`) [dax_battery_table_fns2]
- `SUMX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region]),[i])` (Power BI: `3`) [dax_battery_table_fns2]
- `TOCSV(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region],ASC))` (Power BI: `[s],[i]
8,0
3,2
4,1`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region],ASC))` (Power BI: `3`) [dax_battery_table_fns2]
- `SUMX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region],ASC),[i])` (Power BI: `3`) [dax_battery_table_fns2]
- `TOCSV(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region],DESC))` (Power BI: `[s],[i]
8,2
3,0
4,1`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region],DESC))` (Power BI: `3`) [dax_battery_table_fns2]
- `SUMX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region],DESC),[i])` (Power BI: `3`) [dax_battery_table_fns2]
- `TOCSV(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",FILTER(VALUES(Facts[Region]),Facts[Region]<>"East"),Facts[Region]))` (Power BI: `[s],[i]
3,0
4,1`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",FILTER(VALUES(Facts[Region]),Facts[Region]<>"East"),Facts[Region]))` (Power BI: `2`) [dax_battery_table_fns2]
- `SUMX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",FILTER(VALUES(Facts[Region]),Facts[Region]<>"East"),Facts[Region]),[i])` (Power BI: `1`) [dax_battery_table_fns2]
- `TOCSV(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region]))` (Power BI: `[i]
2
0
1`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region]))` (Power BI: `3`) [dax_battery_table_fns2]
- `SUMX(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region]),[i])` (Power BI: `3`) [dax_battery_table_fns2]
- `TOCSV(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region],ASC))` (Power BI: `[i]
0
2
1`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region],ASC))` (Power BI: `3`) [dax_battery_table_fns2]
- `SUMX(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region],ASC),[i])` (Power BI: `3`) [dax_battery_table_fns2]
- `TOCSV(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region],DESC))` (Power BI: `[i]
2
0
1`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region],DESC))` (Power BI: `3`) [dax_battery_table_fns2]
- `SUMX(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region],DESC),[i])` (Power BI: `3`) [dax_battery_table_fns2]
- `TOCSV(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",FILTER(VALUES(Facts[Region]),Facts[Region]<>"East"),Facts[Region]))` (Power BI: `[i]
0
1`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",FILTER(VALUES(Facts[Region]),Facts[Region]<>"East"),Facts[Region]))` (Power BI: `2`) [dax_battery_table_fns2]
- `SUMX(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",FILTER(VALUES(Facts[Region]),Facts[Region]<>"East"),Facts[Region]),[i])` (Power BI: `1`) [dax_battery_table_fns2]
- `TOCSV(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region]))` (Power BI: `'Facts'[Note],[s],[i]
,5,2
,3,0
Paid,3,2
Paid,0,0
Late,4,1`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region]))` (Power BI: `5`) [dax_battery_table_fns2]
- `SUMX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region]),[i])` (Power BI: `5`) [dax_battery_table_fns2]
- `TOCSV(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region],ASC))` (Power BI: `'Facts'[Note],[s],[i]
,5,0
,3,2
Paid,3,0
Paid,0,2
Late,4,1`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region],ASC))` (Power BI: `5`) [dax_battery_table_fns2]
- `SUMX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region],ASC),[i])` (Power BI: `5`) [dax_battery_table_fns2]
- `TOCSV(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region],DESC))` (Power BI: `'Facts'[Note],[s],[i]
,5,2
,3,0
Paid,3,2
Paid,0,0
Late,4,1`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region],DESC))` (Power BI: `5`) [dax_battery_table_fns2]
- `SUMX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region],DESC),[i])` (Power BI: `5`) [dax_battery_table_fns2]
- `TOCSV(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),"i",FILTER(VALUES(Facts[Region]),Facts[Region]<>"East"),Facts[Region]))` (Power BI: `'Facts'[Note],[s],[i]
,3,0
Paid,0,0
Late,4,1`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),"i",FILTER(VALUES(Facts[Region]),Facts[Region]<>"East"),Facts[Region]))` (Power BI: `3`) [dax_battery_table_fns2]
- `SUMX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),"i",FILTER(VALUES(Facts[Region]),Facts[Region]<>"East"),Facts[Region]),[i])` (Power BI: `1`) [dax_battery_table_fns2]
- `TOCSV(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),"i",SUMMARIZE(Facts,Facts[Region],Facts[Note]),Facts[Region],ASC,Facts[Note],DESC))` (Power BI: `[s],[i]
5,1
3,4
3,0
0,3
4,2`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),"i",SUMMARIZE(Facts,Facts[Region],Facts[Note]),Facts[Region],ASC,Facts[Note],DESC))` (Power BI: `5`) [dax_battery_table_fns2]
- `SUMX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),"i",SUMMARIZE(Facts,Facts[Region],Facts[Note]),Facts[Region],ASC,Facts[Note],DESC),[i])` (Power BI: `10`) [dax_battery_table_fns2]
- `SUMX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region]),[s])` (Power BI: `15`) [dax_battery_table_fns2]
- `SUMX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region]),[s]*[i])` (Power BI: `20`) [dax_battery_table_fns2]
- `MAXX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region],DESC),[i])` (Power BI: `2`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),Facts[Region]))` (Power BI: `3`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",ALL(Facts[Region]),Facts[Region]))` (Power BI: `3`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(FILTER(Facts,TRUE()),"i",VALUES(Facts[Region]),Facts[Region]))` (Power BI: `6`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",FILTER(VALUES(Facts[Region]),FALSE()),Facts[Region]))` (Power BI: `BLANK`) [dax_battery_table_fns2]
- `TOCSV(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",FILTER(VALUES(Facts[Region]),FALSE()),Facts[Region]))` (Power BI: `[s],[i]
`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region],1))` (Power BI: `3`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region],TRUE()))` (Power BI: `3`) [dax_battery_table_fns2]
- `CALCULATE(COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region])),Facts[Region]="East")` (Power BI: `1`) [dax_battery_table_fns2]
- `COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",CALCULATETABLE(VALUES(Facts[Region]),Facts[Quantity]>2),Facts[Region]))` (Power BI: `3`) [dax_battery_table_fns2]
- `TOCSV(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region]))` (Power BI: `'Facts'[Region],[s]
East,5
North,4
West,`) [dax_battery_table_fns2]
- `COUNTROWS(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region]))` (Power BI: `3`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region]),[s])` (Power BI: `9`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region]),1)` (Power BI: `3`) [dax_battery_table_fns2]
- `TOCSV(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],"s",SUM(Facts[Sales])),Facts[Region]))` (Power BI: `'Facts'[Region],[s]
East,11.5
West,20
North,`) [dax_battery_table_fns2]
- `COUNTROWS(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],"s",SUM(Facts[Sales])),Facts[Region]))` (Power BI: `3`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],"s",SUM(Facts[Sales])),Facts[Region]),[s])` (Power BI: `31.5`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],"s",SUM(Facts[Sales])),Facts[Region]),1)` (Power BI: `3`) [dax_battery_table_fns2]
- `TOCSV(ADDMISSINGITEMS(Facts[Region],VALUES(Facts[Region]),Facts[Region]))` (Power BI: `'Facts'[Region]
East
West
North`) [dax_battery_table_fns2]
- `COUNTROWS(ADDMISSINGITEMS(Facts[Region],VALUES(Facts[Region]),Facts[Region]))` (Power BI: `3`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Region],VALUES(Facts[Region]),Facts[Region]),1)` (Power BI: `3`) [dax_battery_table_fns2]
- `TOCSV(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>100),"s",SUM(Facts[Quantity])),Facts[Region]))` (Power BI: `'Facts'[Region],[s]
East,
West,
North,`) [dax_battery_table_fns2]
- `COUNTROWS(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>100),"s",SUM(Facts[Quantity])),Facts[Region]))` (Power BI: `3`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>100),"s",SUM(Facts[Quantity])),Facts[Region]),[s])` (Power BI: `BLANK`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>100),"s",SUM(Facts[Quantity])),Facts[Region]),1)` (Power BI: `3`) [dax_battery_table_fns2]
- `TOCSV(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity]),"c",COUNTROWS(Facts)),Facts[Region]))` (Power BI: `'Facts'[Region],[s],[c]
East,5,1
North,4,1
West,,`) [dax_battery_table_fns2]
- `COUNTROWS(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity]),"c",COUNTROWS(Facts)),Facts[Region]))` (Power BI: `3`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity]),"c",COUNTROWS(Facts)),Facts[Region]),[s])` (Power BI: `9`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity]),"c",COUNTROWS(Facts)),Facts[Region]),1)` (Power BI: `3`) [dax_battery_table_fns2]
- `TOCSV(ADDMISSINGITEMS(Facts[Region],Facts[Note],SUMMARIZECOLUMNS(Facts[Region],Facts[Note],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region],Facts[Note]))` (Power BI: `'Facts'[Region],'Facts'[Note],[s]
East,,5
North,Late,4
West,`) [dax_battery_table_fns2]
- `COUNTROWS(ADDMISSINGITEMS(Facts[Region],Facts[Note],SUMMARIZECOLUMNS(Facts[Region],Facts[Note],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region],Facts[Note]))` (Power BI: `5`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Region],Facts[Note],SUMMARIZECOLUMNS(Facts[Region],Facts[Note],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region],Facts[Note]),[s])` (Power BI: `9`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Region],Facts[Note],SUMMARIZECOLUMNS(Facts[Region],Facts[Note],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region],Facts[Note]),1)` (Power BI: `5`) [dax_battery_table_fns2]
- `TOCSV(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],Facts[Note],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region],Facts[Note]))` (Power BI: `'Facts'[Region],'Facts'[Note],[s]
East,,5
North,Late,4
West,`) [dax_battery_table_fns2]
- `COUNTROWS(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],Facts[Note],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region],Facts[Note]))` (Power BI: `3`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],Facts[Note],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region],Facts[Note]),[s])` (Power BI: `9`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],Facts[Note],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region],Facts[Note]),1)` (Power BI: `3`) [dax_battery_table_fns2]
- `TOCSV(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region],Facts[Note]))` (Power BI: `'Facts'[Region],[s]
East,5
North,4
West,`) [dax_battery_table_fns2]
- `COUNTROWS(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region],Facts[Note]))` (Power BI: `3`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region],Facts[Note]),[s])` (Power BI: `9`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region],Facts[Note]),1)` (Power BI: `3`) [dax_battery_table_fns2]
- `TOCSV(ADDMISSINGITEMS(Facts[Quantity],SUMMARIZECOLUMNS(Facts[Quantity],FILTER(ALL(Facts),Facts[Region]="East"),"s",SUM(Facts[Sales])),Facts[Quantity]))` (Power BI: `'Facts'[Quantity],[s]
1,-1.5
2,10.5
5,2.5
0,
3,
4,`) [dax_battery_table_fns2]
- `COUNTROWS(ADDMISSINGITEMS(Facts[Quantity],SUMMARIZECOLUMNS(Facts[Quantity],FILTER(ALL(Facts),Facts[Region]="East"),"s",SUM(Facts[Sales])),Facts[Quantity]))` (Power BI: `6`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Quantity],SUMMARIZECOLUMNS(Facts[Quantity],FILTER(ALL(Facts),Facts[Region]="East"),"s",SUM(Facts[Sales])),Facts[Quantity]),[s])` (Power BI: `11.5`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Quantity],SUMMARIZECOLUMNS(Facts[Quantity],FILTER(ALL(Facts),Facts[Region]="East"),"s",SUM(Facts[Sales])),Facts[Quantity]),1)` (Power BI: `6`) [dax_battery_table_fns2]
- `TOCSV(ADDMISSINGITEMS(Facts[Region],ADDCOLUMNS(VALUES(Facts[Region]),"s",CALCULATE(SUM(Facts[Quantity]))),Facts[Region]))` (Power BI: `'Facts'[Region],[s]
East,8
West,3
North,4`) [dax_battery_table_fns2]
- `COUNTROWS(ADDMISSINGITEMS(Facts[Region],ADDCOLUMNS(VALUES(Facts[Region]),"s",CALCULATE(SUM(Facts[Quantity]))),Facts[Region]))` (Power BI: `3`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Region],ADDCOLUMNS(VALUES(Facts[Region]),"s",CALCULATE(SUM(Facts[Quantity]))),Facts[Region]),[s])` (Power BI: `15`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Region],ADDCOLUMNS(VALUES(Facts[Region]),"s",CALCULATE(SUM(Facts[Quantity]))),Facts[Region]),1)` (Power BI: `3`) [dax_battery_table_fns2]
- `TOCSV(ADDMISSINGITEMS(Facts[Region],SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),Facts[Region]))` (Power BI: `'Facts'[Region],[s]
East,8
West,3
North,4`) [dax_battery_table_fns2]
- `COUNTROWS(ADDMISSINGITEMS(Facts[Region],SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),Facts[Region]))` (Power BI: `3`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Region],SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),Facts[Region]),[s])` (Power BI: `15`) [dax_battery_table_fns2]
- `SUMX(ADDMISSINGITEMS(Facts[Region],SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),Facts[Region]),1)` (Power BI: `3`) [dax_battery_table_fns2]
- `COUNTROWS(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region],FILTER(Facts,Facts[Quantity]>3)))` (Power BI: `2`) [dax_battery_table_fns2]
- `COUNTROWS(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region],ALL(Facts)))` (Power BI: `3`) [dax_battery_table_fns2]
- `COUNTROWS(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region],FILTER(Facts,FALSE())))` (Power BI: `2`) [dax_battery_table_fns2]
- `TOCSV(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region],FILTER(Facts,FALSE())))` (Power BI: `'Facts'[Region],[s]
East,5
North,4`) [dax_battery_table_fns2]
- `COUNTROWS(ADDMISSINGITEMS(SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region]))` (Power BI: `2`) [dax_battery_table_fns2]
- `CALCULATE(COUNTROWS(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region])),Facts[Region]="East")` (Power BI: `2`) [dax_battery_table_fns2]
- `CALCULATE(COUNTROWS(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],"s",SUM(Facts[Quantity])),Facts[Region])),Facts[Quantity]>3)` (Power BI: `2`) [dax_battery_table_fns2]
- `MAXX(ADDMISSINGITEMS(Facts[Region],VALUES(Facts[Region]),Facts[Region]),1)` (Power BI: `1`) [dax_battery_table_fns2]
- `COUNTX(ADDMISSINGITEMS(Facts[Region],VALUES(Facts[Region]),Facts[Region]),1)` (Power BI: `3`) [dax_battery_table_fns2]
- `SUMX(KEEPFILTERS(VALUES(Facts[Region])),1)` (Power BI: `3`) [dax_battery_table_fns2]
- `MAXX(KEEPFILTERS(VALUES(Facts[Region])),1)` (Power BI: `1`) [dax_battery_table_fns2]
- `COUNTX(KEEPFILTERS(VALUES(Facts[Region])),1)` (Power BI: `3`) [dax_battery_table_fns2]
- `TOCSV(SUMMARIZECOLUMNS(ROLLUPADDISSUBTOTAL(Facts[Region],"sub"),"s",SUM(Facts[Quantity])))` (Power BI: `'Facts'[Region],[sub],[s]
East,FALSE,8
West,FALSE,3
North,FA`) [dax_battery_table_fns2]
- `COUNTROWS(SUMMARIZECOLUMNS(ROLLUPADDISSUBTOTAL(Facts[Region],"sub"),"s",SUM(Facts[Quantity])))` (Power BI: `4`) [dax_battery_table_fns2]
- `TOCSV(SUMMARIZECOLUMNS(ROLLUPADDISSUBTOTAL(Facts[Region],"a",Facts[Note],"b"),"s",SUM(Facts[Quantity])))` (Power BI: `'Facts'[Region],'Facts'[Note],[a],[b],[s]
East,,FALSE,FALSE,`) [dax_battery_table_fns2]
- `TOCSV(SUMMARIZE(Facts,ROLLUP(Facts[Region]),"s",SUM(Facts[Quantity])))` (Power BI: `'Facts'[Region],[s]
East,8
West,3
North,4
,15`) [dax_battery_table_fns2]
- `TOCSV(SUMMARIZE(Facts,ROLLUP(Facts[Region],Facts[Note]),"s",SUM(Facts[Quantity])))` (Power BI: `'Facts'[Region],'Facts'[Note],[s]
East,,5
West,,3
East,Paid,`) [dax_battery_table_fns2]
- `TOCSV(SUMMARIZE(Facts,Facts[Region],ROLLUP(Facts[Note]),"s",SUM(Facts[Quantity])))` (Power BI: `'Facts'[Region],'Facts'[Note],[s]
East,,5
West,,3
East,Paid,`) [dax_battery_table_fns2]
- `TOCSV(SUMMARIZE(Facts,ROLLUPGROUP(Facts[Region],Facts[Note]),"s",SUM(Facts[Quantity])))` (Power BI: `'Facts'[Region],'Facts'[Note],[s]
East,,5
West,,3
East,Paid,`) [dax_battery_table_fns2]
- `TOCSV(SUMMARIZE(Facts,ROLLUP(ROLLUPGROUP(Facts[Region],Facts[Note])),"s",SUM(Facts[Quantity])))` (Power BI: `'Facts'[Region],'Facts'[Note],[s]
East,,5
West,,3
East,Paid,`) [dax_battery_table_fns2]
- `TOCSV(SUMMARIZE(Facts,ROLLUP(Facts[Region]),"s",SUM(Facts[Quantity]),"x",ISSUBTOTAL(Facts[Region])))` (Power BI: `'Facts'[Region],[s],[x]
East,8,FALSE
West,3,FALSE
North,4,FA`) [dax_battery_table_fns2]
- `TOCSV(SUMMARIZE(Facts,ROLLUP(Facts[Region],Facts[Note]),"x",ISSUBTOTAL(Facts[Region]),"y",ISSUBTOTAL(Facts[Note])))` (Power BI: `'Facts'[Region],'Facts'[Note],[x],[y]
East,,FALSE,FALSE
West`) [dax_battery_table_fns2]
- `TOCSV(SUMMARIZE(Facts,Facts[Region],ROLLUPGROUP(Facts[Note]),"s",SUM(Facts[Quantity])))` (Power BI: `'Facts'[Region],'Facts'[Note],[s]
East,,5
West,,3
East,Paid,`) [dax_battery_table_fns2]
- `TOCSV(SUMMARIZECOLUMNS(Facts[Region],ROLLUPADDISSUBTOTAL(Facts[Note],"sub"),"s",SUM(Facts[Quantity])))` (Power BI: `'Facts'[Region],'Facts'[Note],[sub],[s]
East,,FALSE,5
West,,`) [dax_battery_table_fns2]
- `TOCSV(SUMMARIZECOLUMNS(ROLLUPADDISSUBTOTAL(ROLLUPGROUP(Facts[Region],Facts[Note]),"sub"),"s",SUM(Facts[Quantity])))` (Power BI: `'Facts'[Region],'Facts'[Note],[sub],[s]
East,,FALSE,5
West,,`) [dax_battery_table_fns2]
- `TOCSV(SUMMARIZECOLUMNS(ROLLUPADDISSUBTOTAL(Facts[Region],"sub"),FILTER(ALL(Facts),Facts[Quantity]>2),"s",SUM(Facts[Quantity])))` (Power BI: `'Facts'[Region],[sub],[s]
East,FALSE,5
West,FALSE,3
North,FA`) [dax_battery_table_fns2]
- `TOCSV(SUMMARIZE(Facts,ROLLUP(Facts[Region]),"s",SUM(Facts[Quantity]),"c",COUNTROWS(Facts)))` (Power BI: `'Facts'[Region],[s],[c]
East,8,3
West,3,2
North,4,1
,15,6`) [dax_battery_table_fns2]
- `TOCSV(SUMMARIZE(Facts,ROLLUP(Facts[Region]),"s",SUM(Facts[Sales])))` (Power BI: `'Facts'[Region],[s]
East,11.5
West,20
North,
,31.5`) [dax_battery_table_fns2]
- `COUNTROWS(SUMMARIZE(Facts,ROLLUP(Facts[Region])))` (Power BI: `2`) [dax_battery_table_fns2]
- `COUNTROWS(SUMMARIZE(Facts,ROLLUP(Facts[Region],Facts[Note])))` (Power BI: `3`) [dax_battery_table_fns2]
- `1>VAR y=2 RETURN y` (Power BI: `False`) [dax_battery_var_scoping]
- `1=VAR y=2 RETURN y` (Power BI: `False`) [dax_battery_var_scoping]
- `"a"&VAR y="b" RETURN y` (Power BI: `ab`) [dax_battery_var_scoping]
- `VAR t=Facts RETURN COUNTROWS(DISTINCT(t))` (Power BI: `6`) [dax_battery_var_scoping]
- `VAR t=Facts RETURN SUMX(t,Facts[Quantity])` (Power BI: `15`) [dax_battery_var_scoping]
- `VAR t=Facts RETURN COUNTROWS(FILTER(t,Facts[Quantity]>2))` (Power BI: `3`) [dax_battery_var_scoping]
- `VAR t=Facts VAR u=t RETURN COUNTROWS(u)` (Power BI: `6`) [dax_battery_var_scoping]
- `CALCULATE(COUNTROWS(Facts),VAR t = Facts[Quantity] RETURN t>2 && Facts[Sales]>1)` (Power BI: `2`) [dax_battery_var_scoping]
- `CALCULATE(COUNTROWS(Facts),VAR u = 2 VAR t = u RETURN Facts[Quantity]>t)` (Power BI: `3`) [dax_battery_var_scoping]
- `CALCULATE(COUNTROWS(Facts),VAR t = "East" RETURN Facts[Region]=t)` (Power BI: `3`) [dax_battery_var_scoping]
- `CALCULATE(COUNTROWS(Facts),VAR t = DATE(2020,1,1) RETURN Facts[Quantity]>t)` (Power BI: `BLANK`) [dax_battery_var_scoping]
- `CALCULATE(COUNTROWS(Facts),VAR t = TRUE() RETURN Facts[Quantity]>2 && t)` (Power BI: `3`) [dax_battery_var_scoping]
- `CALCULATE(COUNTROWS(Facts),VAR t = 2 RETURN VAR u = t RETURN Facts[Quantity]>u)` (Power BI: `3`) [dax_battery_var_scoping]
- `CALCULATE(COUNTROWS(Facts),VAR t = Facts[Quantity] RETURN t>t)` (Power BI: `BLANK`) [dax_battery_var_scoping]
- `CALCULATE(COUNTROWS(Facts),VAR t = Facts[Quantity] RETURN VAR u = Facts[Sales] RETURN t>u)` (Power BI: `3`) [dax_battery_var_scoping]
- `CALCULATETABLE(ROW("c",1),VAR t = 2 RETURN Facts[Quantity]>t)` (Power BI: `1`) [dax_battery_var_scoping]
- `CALCULATE(COUNTROWS(Facts),VAR t = Facts[Quantity] RETURN t)` (Power BI: `5`) [dax_battery_var_scoping]
- `CALCULATE(COUNTROWS(Facts),VAR t = Facts[Quantity] RETURN t IN {1,2})` (Power BI: `2`) [dax_battery_var_scoping]
- `CALCULATE(COUNTROWS(Facts),VAR t = Facts[Quantity] RETURN t+1>3)` (Power BI: `3`) [dax_battery_var_scoping]
- `CALCULATE(COUNTROWS(Facts),VAR t = Facts[Quantity] RETURN ISBLANK(t))` (Power BI: `BLANK`) [dax_battery_var_scoping]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v],[d],DATE(2020,1,1))` (Power BI: `-999.99315547714`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v],[d],ROW("a",0.1))` (Power BI: `-21.0368144252443`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v],[d],1E308)` (Power BI: `-1000`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v],[d],1E200)` (Power BI: `-1000`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v],[d],1/0)` (Power BI: `-1000`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v],[d],0/0)` (Power BI: `NaN`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),IF([n]=365,1/0,[v]),[d],0.1)` (Power BI: `Infinity`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),IF([n]=365,-1/0,[v]),[d],0.1)` (Power BI: `-Infinity`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),IF([n]=365,0/0,[v]),[d],0.1)` (Power BI: `NaN`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v]*1E308*10,[d],0.1)` (Power BI: `NaN`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),CURRENCY(5),[d],0.1)` (Power BI: `17.4343`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v]/0,[d],0.1)` (Power BI: `NaN`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),CURRENCY([v]),[d],0.1)` (Power BI: `-21.0368`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v],[n]*1000000,0.1)` (Power BI: `-1000`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v],1E12,0.1)` (Power BI: `0`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v],1/0,0.1)` (Power BI: `0`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v],-1/0,0.1)` (Power BI: `NaN`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v],0/0,0.1)` (Power BI: `NaN`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v],"2020-01-01",0.1)` (Power BI: `200`) [dax_battery_xnpv2]
- `VAR t=Facts RETURN XNPV(t,Facts[Quantity],DATE(2020,1,1)+Facts[Quantity],0.1)` (Power BI: `14.9856458600632`) [dax_battery_xnpv2]
- `IFERROR(XNPV(Facts,Facts[Quantity],DATE(2020,1,1),-1),7)` (Power BI: `7`) [dax_battery_xnpv2]
- `ISERROR(XNPV(Facts,Facts[Quantity],DATE(2020,1,1),"a"))` (Power BI: `True`) [dax_battery_xnpv2]
- `IFERROR(XNPV(Facts,Facts[Quantity],BLANK(),0.1),7)` (Power BI: `7`) [dax_battery_xnpv2]
- `IF(FALSE(),XNPV(Facts,IF(Facts[Quantity]>2,"a",1),DATE(2020,1,1)+Facts[Quantity],0.1),1)` (Power BI: `1`) [dax_battery_xnpv2]
- `XNPV(DATATABLE("v",DOUBLE,"d",DOUBLE,{{-1000,2958465},{1100,2958830}}),[v],[d],0.1)` (Power BI: `-1.13686837721616E-13`) [dax_battery_xnpv2]
- `XNPV(DATATABLE("v",DOUBLE,"d",DOUBLE,{{-1000,2958466},{1100,2958831}}),[v],[d],0.1)` (Power BI: `0`) [dax_battery_xnpv2]
- `XNPV(DATATABLE("v",DOUBLE,"d",DOUBLE,{{-1000,3000000},{1100,3000365}}),[v],[d],0.1)` (Power BI: `-3.46944695195361E-18`) [dax_battery_xnpv2]
- `XNPV(DATATABLE("v",DOUBLE,"d",DOUBLE,{{-1000,10000000},{1100,10000365}}),[v],[d],0.1)` (Power BI: `0`) [dax_battery_xnpv2]
- `XNPV(DATATABLE("v",DOUBLE,"d",DOUBLE,{{-1000,2958466},{1100,2958466}}),[v],[d],0.1)` (Power BI: `99.973891030956`) [dax_battery_xnpv2]
- `XNPV(DATATABLE("v",DOUBLE,"d",DOUBLE,{{-1000,3000000},{1100,3000000}}),[v],[d],0.1)` (Power BI: `0.00194867421343405`) [dax_battery_xnpv2]
- `XNPV(DATATABLE("v",DOUBLE,"d",DOUBLE,{{-1000,2958100},{1100,2958466}}),[v],[d],0.1)` (Power BI: `-0.26108969043878`) [dax_battery_xnpv2]
- `XNPV(DATATABLE("v",DOUBLE,"d",DOUBLE,{{-1000,2958100},{1100,2958466.0}}),[v],[d],0.1)` (Power BI: `-0.26108969043878`) [dax_battery_xnpv2]
- `XNPV(DATATABLE("v",DOUBLE,"d",DOUBLE,{{-1000,1000000000000.0},{1100,1000000000000.0}}),[v],[d],0.1)` (Power BI: `0`) [dax_battery_xnpv2]
- `XNPV(DATATABLE("v",DOUBLE,"d",DOUBLE,{{-1000,1000000000000000.0},{1100,1000000000000000.0}}),[v],[d],0.1)` (Power BI: `0`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v],2958466,0.1)` (Power BI: `199.947782061912`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v],[n]+2958466,0.1)` (Power BI: `-21.0313219298782`) [dax_battery_xnpv2]
- `XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v],[n]+2958465,0.1)` (Power BI: `-21.0368144252443`) [dax_battery_xnpv2]

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
