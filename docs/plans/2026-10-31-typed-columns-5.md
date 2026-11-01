# Task 15: typed-columns-5 (a True/False BLANK in table columns, types of added columns, Currency and dates in the statistical iterators, leftovers of FILTER and VAR tables)

**Branch:** `antigravity/typed-columns-5`  **Written by:** Claude, 2026-10-31  **Status:** see `HANDOFF.md`
**Start condition:** Task 14 is DONE (locked, committed, merged, pushed) and `HANDOFF.md` says Active agent: Antigravity. Branch from `main`.

Read first: `AGENTS.md` ("Compute, never look up"), `HANDOFF.md` (open items), and the "Review outcome" of `docs/plans/2026-10-31-logic-tables-4.md`.
That review is the reason for Rules 3 to 6 below: the Task 14 build reported 794 of 817 spec items matching and 0 DIFF, then 24,925 fresh Power BI probes found 627 wrong answers and 65 crashes, and the full test suite failed although the entry did not say so. Three of the causes: a helper that tested for the literal text `"Nowhere"` (a word of two spec items), a new value class `_EmptyLogicalText` for what is a plain BLANK, and a column typed by its **name** instead of its table.

## Goal
All 1,836 items: Power BI answers, the app refuses ("pending"). Power BI's answers are saved in `tools/parity/task15_typed_columns_spec.json` (fields `part`, `battery`, `expr`, `powerbi`, `app_refusal`). Every one is in a replayed battery, so no `--freeze` is needed. No new function is added. The spec file is a copy for reading; it is **not** a replay battery and must not be read at run time.

## Part A: a BLANK typed True/False in a table column
The rule of Task 14: an empty text on the right of `&&`, `||`, AND, OR with an undecided left is a plain BLANK at run time with the static type True/False (see `typed_true_false`, `logical_operator`, `refuse_logical_blank_in_a_column`).
- **A1 (813 items).** In a column it stays True/False: `COUNTROWS(ADDCOLUMNS(Facts,"q",2.5&&""))` is 6, `COUNTAX({1&&""},[Value])` is 1, `SUMX({OR("false","")},IF([Value],1,2))` is 2, `COUNTROWS(FILTER({1&&LEFT("a",0)},[Value]))` is BLANK, while `MAXX(ADDCOLUMNS(Facts,"q",2.5&&""),[q])` is an error ("cannot work with values of type Boolean") and `COUNTAX(ADDCOLUMNS(Facts,"q",OR(0,UPPER(""))),[q])` is BLANK. COUNTAX of a constructor counts it, COUNTAX of ADDCOLUMNS does not: find what separates them before writing a rule.
- **A2 (198 items).** `ISLOGICAL` of the operator: `ISLOGICAL(2.5&&"")` is True, `ISLOGICAL(LEFT("a",0)||VAR y="" RETURN y)` is False, `ISLOGICAL("0"||LEFT("a",0))` is False, `ISLOGICAL(AND("-1",""))` is True. It depends on the operands. If you cannot state the rule on their types, keep the refusal and say so.

## Part B: statistical iterators
- **B1 (136 items).** A Currency in a conditional inside PRODUCTX, MEDIANX, GEOMEANX, STDEVX, VARX, PERCENTILEX. Start from the Currency rules of Task 14 (`static_type_of`, `currency_typed`, `dax_math.to_currency`). Results such as 6.09924039791019E-320 and 728.999999999995 mean a Currency meets an integer scale somewhere: refuse anything you cannot derive, do not chase digits.
- **B2 (157 items).** A date in VARX / STDEVX: `VARX.P(Facts,DATE(2020,1,1)+Facts[Quantity])` shows 2.88888907432556, the days as numbers give 2.88888888888889: the sums are in single precision or the dates are scaled. Find which. If the result depends on the walk of the rows, refuse it (Rule 5). Zero variance items (`VARX.P(..,DATE(2020,1,1))` is 0) need no such rule.

## Part C: types of added columns (156 items)
`ISINT64`, `ISDOUBLE`, `ISDECIMAL`, `ISCURRENCY` of a body reading an added column: `ISDOUBLE(MAXX(ADDCOLUMNS(Facts,"Intercept",1.5),[Intercept]))` is True, `ISINT64(MAXX(ADDCOLUMNS(Facts,"DegreesOfFreedom",CURRENCY(1)),[DegreesOfFreedom]))` is False, `ISDOUBLE(MAXX(ADDCOLUMNS(LINESTX(Facts,Facts[Quantity],Facts[Sales]),"z",[Slope1]),[z]))` is True. The type comes from the expression of the column, **never from its name**. Also `ISCURRENCY(CURRENCY(10.00005)+BLANK())` is True: a BLANK operand takes the type of the other side in `_static_numeric_type`. Check `SELECTCOLUMNS` too.

## Part D: leftovers
- **D1 (165 items).** `FILTER` over no rows with a predicate that is a table or text: `COUNTROWS(FILTER(FILTER(Facts,1=0),ALL(Facts[Region])))` is BLANK, `COUNTROWS(FILTER(CALCULATETABLE(Facts,LEN(Facts[Region])>100),"a"))` is BLANK. Extend `filter_scan_ran` and `plan_finds_no_rows`, which hold the rule of Task 14: a scan that ran, a plan that knows. Do not go back to testing how the table looks. Also `ISERROR("a"&&VAR y="b" RETURN y)` is True and `IFERROR(AND(MAX(Facts[Region]),VAR y="b" RETURN y),7)` is 7.
- **D2 (88 items).** Table variables and constructors still refused: `COUNTROWS(DISTINCT(VAR r="West" RETURN FILTER(VALUES(Facts[Region]),Facts[Region]<>r)))` is 2, `CALCULATE(COUNTROWS(Facts),VAR t=FILTER(Facts,Facts[Quantity]>2) RETURN t)` is 3, `COUNTROWS(FILTER(FILTER(Facts,FALSE()),{1,2}))` is BLANK.
- **D3 (123 items).** `COALESCE` whose earlier argument can fail, in an iterator: `MAXX(Facts,COALESCE(AVERAGEX(Facts,DATE(2020,1,1)+Facts[Quantity]),"a"))` is 43833.5; `COUNTX` of an IFERROR whose first value fails without a row: `COUNTX(DISTINCT(Facts),IFERROR(FORMAT(1,"0"),NOT(TRUE())))` is BLANK.

## Rules
1. Tests first (`tests/test_iteration104_typed_columns_5.py`). Compute every answer from DAX semantics, never from the saved answers or the spec file.
2. Check each new rule on the standard Facts table **and** on tables A and B of `tests/fixtures_misc3_alt.json`, all three tables of `tests/fixtures_variant2_review_alt.json`, all three of `tests/fixtures_typed3_review_alt.json` and table B of `tests/fixtures_logic4_review_alt.json`. A rule that holds on one table only is fitted, not understood.
3. **Do not turn a refusal into a value unless you know the rule for every shape it now lets through.** For each refusal you remove or narrow, write down in `HANDOFF.md` which shapes it lets through and how you know they are right. If you do not know, keep the refusal and report the item: 900 items honestly refused is a good result, 900 fitted rules is not.
4. **No rule keyed to how an expression looks or to a word in it.** No literal text from the spec in the code, no test on a column's name, no list of function names standing in for a type. Write the rule on types, scans and rows.
5. Keep rows, scans and walks in mind. A result that depends on the order the engine walks the rows cannot be derived here: refuse it.
6. **No new kind of value in the evaluator.** If Power BI shows a BLANK with a type, it is `None` plus a static type. A new class has to be handled by every function, and the ones that do not know it crash: Task 14 had 65 crashes this way.
7. Do not widen a refusal to cover a problem without running the replay (`PYTHONPATH=. python tools/parity_check.py`, about 2 minutes, no pytest): a refusal on a locked item is a regression. Run it after every Part.
8. Every saved value in the spec must match or be refused with a true reason; nothing may become `DIFF` or `CRASH`; no locked item may change.
9. **Finish with the full gate and paste its last lines.** `PYTHONPATH=. python tools/parity_check.py --tests` stops at the first failing test: if it fails, also run `QT_QPA_PLATFORM=offscreen python -m pytest -q` and report **every** failing test in `HANDOFF.md`, not only the ones you expected. The Task 14 entry gave the replay and the smoke test and left the failed suite out. Never write "gate passed" unless that exact command printed `PARITY GATE PASSED`.
10. Before you stop, write and run your own fresh probes against the app (the local engine alone is enough): call each thing you changed with values the spec does not use, wrapped in `+1`, `&"z"`, `ISBLANK`, `IFERROR`, a comparison, a VAR, and as a column of `ADDCOLUMNS`. A Python exception (`LOCAL-CRASH`) anywhere is a bug in your change.
11. Branch `antigravity/typed-columns-5` from `main`. No `--freeze`, `--accept`, commit, merge; no Power BI VM; no global `str.replace` on `measures.py`; no edits to existing tests (list them in `HANDOFF.md` for Claude).
12. Write what you did and refused in `HANDOFF.md`, set Task 15 READY FOR REVIEW and "Active agent: Claude". "Working tree clean" means no uncommitted change: say no if there is one.

## Not in Task 15 (parked, reasons in `HANDOFF.md`)
Non-ASCII collation and composed / decomposed text (1,657), engine row orders (TOCSV, CONCATENATEX, SUMMARIZE, TABLEOF, about 665), LINEST rank-deficient or perfect fits (701), SUBSTITUTEWITHINDEX (857), NaN beside other numbers in a Variant MAXX / MINX (117), `SIN` of a large number or of TRUE() printed in CONCATENATEX (last digits, 7), GEOMEANX of mixed signs, `date*BLANK()` inside arithmetic, `SELECTCOLUMNS` column lineage.

## Review outcome (Claude, 2026-11-01)
Tested against Power BI Desktop on the iPad guest (queried headless, project never saved) and in the real Analytics Studio offscreen. The user was away; Claude approved the lock under the authority they delegated on 2026-11-01.

**The build.** An honest entry: 1,364 new matches, 0 DIFF, its one failing test named, the failed gate pasted. That is the standard. It still let wrong answers through, because every new rule had been checked on the spec shapes only.

**Method that worked.** Generate far more shapes than needed (44,875 here), answer them with `main` and with the build, and ask Power BI only about the answers that changed. An answer that did not change cannot be a new error. Then give the diff to a fresh reviewer without your conclusions: it found what the probes missed.

**Rules Power BI showed, now in `measures.py`:**
- A logical operator's BLANK in a constructor is False beside logical values and numbers, and alone (`COUNTAX({1&&""},[Value])` is 1); it stays a BLANK beside a BLANK. Beside a text or a date no rule could be stated (FORMAT fails, COALESCE gives BLANK, a date shows 12:00:00 AM), so it is refused.
- Through a VAR block or a CALCULATE the same operator gives a plain BLANK, but the column is still True/False (`true_false_column`).
- A table filter is a table: `VAR m=MAX(Facts[Quantity])>1 RETURN m` stays an error. A VAR holding a CALCULATE is evaluated once, before the FILTER; put into the FILTER it would run per row, so that shape is refused.
- A constructor of several columns as a scalar fails at compile time, one of several rows at run time. A text constructor is known by its static type.
- A BLANK operand: `+` and `-` take the other side's type, `*` and `/` read it as an Integer, so `CURRENCY(1)*BLANK()` is a Currency.
- A table variable is a named table of the type walk (`_TABLE_VARIABLE`, `_static_let_scope`), so a column's type comes from its table on every path, never from a stored column of the same name.
- One repeated date has no spread. A refusal raises `MeasureError` (`dax_typed.refusal`), which IFERROR does not catch.

**Still refused (521 of 1,836).** A2 ISLOGICAL (198): the rule on the operand types was not found. B1 Currency in a conditional (136), B2 varying dates in VARX / STDEVX (117), D1 (34), D3 (36).
