# Task 14: logic-tables-4 (empty text in logical operators, table variables as iterator tables, FILTER over empty tables, leftovers of typed bodies)

**Branch:** `antigravity/logic-tables-4`  **Written by:** Claude, 2026-10-31  **Status:** see `HANDOFF.md`
**Start condition:** Tasks 12 and 13 are DONE (locked, committed, merged, pushed) and `HANDOFF.md` says Active agent: Antigravity. Branch from `main`. Do not start before that: Tasks 12 and 13 were left uncommitted once and built on top of each other, so neither can be reviewed or undone alone.

Read first: `AGENTS.md` ("Compute, never look up"), `HANDOFF.md` (open items), and the "Review outcome" of `docs/plans/2026-10-30-iterators-typed-3.md`.
That review is the reason for Rules 3 to 5 below: the Task 13 build matched 1,155 of its 1,180 saved items, and fresh Power BI probes then found 556 of 17,632 answers wrong, because rules had been fitted to the saved items.

## Goal
Parts A to D: Power BI answers a value, the app refuses ("pending"). All 812 items have Power BI's answer saved in `tools/parity/task14_logic_tables_spec.json` (fields `part`, `battery`, `expr`, `powerbi`, `app_refusal`). Every one is in a replayed battery, so no `--freeze` is needed.
Part E: 5 expressions the app answers wrongly today. They are in the spec too, with `app_answer`, and are not in a replayed battery.
No new function is added. The spec file is a copy for reading; it is **not** a replay battery and must not be read at run time.

## Part A: empty text in logical operators
- **A1 (310 items).** `AND(2.5,"")` shows BLANK, yet `ISBLANK("1"&&VAR y=IF(TRUE(),"","a") RETURN y)` is False, `IF(FALSE()||LEFT("a",0),1,2)` is 2 and `(2.5&&VAR y=IF(TRUE(),"") RETURN y)&"z"` is z. An empty text on the right of `&&`, `||`, AND, OR with an undecided left gives a value that is **not** BLANK and displays as BLANK. It needs its own representation, not `None` and not `""` alone: go through the 178 BLANK, 44 `2`, 44 `z` and 44 `False` answers before choosing one. Compare the left values: `"0"`, `0`, `2.5`, `"TRUE"`, `"false"`, `BLANK()`, and what happens when the left alone decides.
- **A2 (40 items).** Text on the left that cannot convert: `AND("a",IF(TRUE(),"","a"))` is False, `"a"&&(VAR y="" RETURN y)` is False, `("a"&&VAR y=IF(TRUE(),"") RETURN y)&"z"` is FALSEz, `ISBLANK("TRUE"&&VAR y=MAX(Facts[Region]) RETURN y)` is False. The app raises the conversion error; Power BI does not, here. Find which operand order and which right-hand values keep the error: errors on the same operators are locked and must stay.

## Part B: tables
- **B1 (170 items).** A `VAR` block as the table of an iterator or table function: `MAXX(VAR t=FILTER(Facts,FALSE()) RETURN t,Facts[Note])` is BLANK, likewise SUMX, COUNTAX, PRODUCTX, GEOMEANX, STDEVX.S, CONCATENATEX, `COUNTROWS(ADDCOLUMNS(VAR t=... RETURN t,"q",...))`, `COUNTROWS(FILTER(VAR t=... RETURN t,TRUE()))`. All 170 are over an empty table. A non-empty table variable must work the same way: test `VAR t=FILTER(Facts,Facts[Quantity]>2) RETURN t` with all those functions, and refuse what you cannot show to be right.
- **B2 (44 items).** A text predicate in FILTER over an empty table: `COUNTROWS(FILTER(GENERATESERIES(1,0),"a"))`, `COUNTROWS(FILTER(EXCEPT(Facts,Facts),MAXX(Facts,Facts[Region])))` are BLANK.
- **B3 (23 items).** A many-valued table as the FILTER predicate over a table that is empty by construction: `COUNTROWS(FILTER(EXCEPT(Facts,Facts),VALUES(Facts[Region])))` is BLANK, while over a table with no **data** rows it is an error. `validate_with_ghost_row` keeps this refused with a comment. Removing that refusal alone made DIFFs in the Task 13 review, so the two cases have to be told apart first.

## Part C: bodies that are checked too early
- **C1 (121 items).** The type check of an inner function fails before the iteration: `COUNTX(Facts,IF(Facts[Quantity]>2,INT(DATE(2020,1,1)),1))` is 6, `COUNTX(CALCULATETABLE(Facts,Facts[Region]="West"),MAX("a","b"))` is 2, `MAXX(EXCEPT(Facts,Facts),VAR q=Facts[Quantity] RETURN q*2)` is BLANK, `COUNTAX(FILTER(Facts,FALSE()),ABS(DATEVALUE("2020-01-01")))` is BLANK. Also `ISBLANK(2.5&&VAR y=ERROR("x") RETURN y)` is False, and `VAR z=VAR a=1 RETURN a RETURN z&&VAR y=BLANK() RETURN y<>"a"` is True ("Function VAR is not supported").

## Part D: typing and Currency
- **D1 (56 items).** `ISDOUBLE` / `ISINT64` of a LINEST or LINESTX statistic: `ISDOUBLE(MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales]),[StandardErrorIntercept]))` is True, `ISINT64(MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales]),[DegreesOfFreedom]))` is False. Every LINEST column is a Double, `DegreesOfFreedom` too.
- **D2 (48 items).** XNPV over Currency values computed with arithmetic (66.6667, -7.0122, -1833.3331). The XNPV extremes rules of Task 10 are the starting point; items with a non-finite result may stay refused.

## Part E: wrong answers to fix
- `MAXX(ADDCOLUMNS(EXCEPT(Facts,Facts),"q",ISBLANK(VALUES(Facts[Region]))),[q])` and the same with `Facts[Note]`: a compile error ("The function MAXX cannot work with values of type Boolean"), here BLANK. An added column has a type even over an empty table.
- `MAXX(SUMMARIZE(Facts,Facts[Region]),IF(COUNTROWS(Facts)>3,Facts[Region],Facts[Sales]))`: an error ("A single value for column 'Sales' ... cannot be determined"), here a value. Every branch is compiled, so a column the iterated rows lack is an error even in the untaken branch; `refuse_column_no_row_holds` looks only at the top conditional.
- `-MIN(DATE(1899,12,30),BLANK())`: 0, here BLANK (day zero negated).
- `LEN(GEOMEANX(VALUES(Facts[Region]),LASTNONBLANK(Facts[Sales],"a")))`: 16, here 15 (last digits of a double). Do not chase digits: refuse if the rule is not clear.
Add a saved-answer test for each in `tests/test_iteration102_logic_tables_4.py`.

## Rules
1. Tests first (`tests/test_iteration102_logic_tables_4.py`). Compute every answer from DAX semantics, never from the saved answers or the spec file.
2. Check each new rule on the standard Facts table **and** on tables A and B of `tests/fixtures_misc3_alt.json`, all three tables of `tests/fixtures_variant2_review_alt.json` and all three of `tests/fixtures_typed3_review_alt.json`. A rule that holds on one table only is fitted, not understood.
3. **Do not turn a refusal into a value unless you know the rule for every shape it now lets through.** Removing a refusal changes shapes outside the spec. For each refusal you remove or narrow, write down in `HANDOFF.md` which shapes it let through and how you know they are right. If you do not know, keep the refusal and report the item: 90 items honestly refused is a good result, 90 fitted rules is not.
4. **No rule keyed to how an expression looks.** "When the body calls DATE", "when the argument is a literal" and similar tests are how Task 13 got 556 wrong answers. Write the rule on types, scans and rows: read `_stored_scan`, `conditional_type`, `date_as_typed` and the Task 13 review outcome first, they hold the rules Power BI showed.
5. Keep rows, scans and walks in mind. A result that depends on the order the engine walks the rows cannot be derived here: refuse it.
6. Do not widen a refusal to cover a problem without running the replay: it is quick (`PYTHONPATH=. python tools/parity_check.py`, about 2 minutes, no pytest) and a refusal on a locked item is a regression. Run it after every Part.
7. Every saved value in the spec must match or be refused with a true reason; nothing may become `DIFF` or `CRASH`; no locked item may change. Report **all** failing tests in `HANDOFF.md`, including ones that are not on your list of expected updates.
8. Branch `antigravity/logic-tables-4` from `main`. No `--freeze`, `--accept`, commit, merge; no Power BI VM; no global `str.replace` on `measures.py`; no edits to existing tests (list them in `HANDOFF.md` for Claude).
9. Finish with `PYTHONPATH=. python tools/parity_check.py --tests`, write what you did and refused in `HANDOFF.md`, set Task 14 READY FOR REVIEW and "Active agent: Claude".

## Not in Task 14 (parked, reasons in `HANDOFF.md`)
Non-ASCII collation and composed / decomposed text (1,657), engine row orders (TOCSV, CONCATENATEX, SUMMARIZE, TABLEOF, about 660), LINEST rank-deficient or perfect fits (703), SUBSTITUTEWITHINDEX (857), Currency or dates in a conditional inside the statistical iterators (188), NaN beside other numbers in a Variant MAXX / MINX (117), `date*BLANK()` inside arithmetic, `SELECTCOLUMNS` column lineage, the fold of a constant IF over scans not yet measured.
