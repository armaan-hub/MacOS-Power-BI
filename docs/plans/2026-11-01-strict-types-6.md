# Task 16: strict-types-6 (wrong answers from the Task 15 review, types of columns the walk does not know, ISLOGICAL, strict comparison, tables as CALCULATE filters)

**Branch:** `antigravity/strict-types-6`  **Written by:** Claude, 2026-11-01  **Status:** see `HANDOFF.md`
**Start condition:** Task 15 is DONE (locked, merged, pushed) and `HANDOFF.md` says Active agent: Antigravity. Branch from `main`.

Read first: `AGENTS.md` ("Compute, never look up"), `HANDOFF.md` (open items), and the "Review outcome" of `docs/plans/2026-10-31-typed-columns-5.md`.
Your Task 15 report was honest and that made the review faster: keep doing that. It still let wrong answers through, because each rule had been tried on the spec shapes only: a BLANK made False beside a text, any `VAR x RETURN x` taken for a table filter, a column typed by its name on every path but the two you changed. Rule 10 below is new and is the answer to that.

## Goal
836 items. Part A (51): the app gives a value and Power BI another. Parts B to G (785): Power BI answers, the app refuses ("pending"). Answers are saved in `tools/parity/task16_strict_types_spec.json` (fields `part`, `battery`, `expr`, `powerbi`, and `app_answer` or `app_refusal`). Parts B to G are in replayed batteries; Part A is not and has to be tested from your own test file, so no `--freeze` is needed. No new function is added. The spec file is for reading; it must not be read at run time.

## Part A: answers that are wrong today
- **A1 (10).** `SUMX({1,2},IF([Value]==FALSE(),1,2))` gives 4; Power BI: an error, "DAX comparison operations do not support comparing values of type Integer with values of type True/False". Also a text column against True/False, and a True/False column against a number. `1==TRUE()` is already an error here: the column of a constructor or of `ADDCOLUMNS` must reach the same check.
- **A2 (5).** Text ordering ignores hyphens: `MAXX({"-1","0"},[Value])` is -1, `MINX({"-1","0"},[Value])` is 0, `MAXX({"a-b","ab"},[Value])` is a-b, `MAXX({"-1","0","2"},[Value])` is 2. Look at how text is compared in `dax_typed` and what is already done for collation. Keep the existing non-ASCII refusal. Ask yourself which other punctuation behaves the same; if you cannot say, refuse text holding it.
- **A3 (21).** A division by zero over an added Currency column: `SUMX(ADDCOLUMNS(Facts,"c",CURRENCY(1)),[c]/0)` is the error "A division by zero has been encountered", the app gives Infinity. `currency_typed` does not see added columns. Currency division results also keep Currency digits there (`[c]/Facts[Quantity]-Facts[Quantity]` is -44.4999).
- **A4 (15).** A typed BLANK through IF or SWITCH: `ISBLANK(IF(TRUE(),2.5&&""))` is True, `ISLOGICAL(IF(TRUE(),2.5&&""))` is False, `COUNTAX(ADDCOLUMNS(Facts,"q",IF(TRUE(),2.5&&"")),[q])` is BLANK. Compare with the VAR block and CALCULATE case in the Task 15 review outcome.

## Part B: columns of unknown type (223)
`ISINT64(MAXX(SELECTCOLUMNS(Facts,"Quantity",BLANK()-DATE(2020,1,1)),[Quantity]))` is False, `ISDOUBLE` of it True. The walk returns None for `BLANK()+BLANK()`, a date beside a BLANK, and more. Extend `_static_numeric_type` on types. Types come from the expression and the table (`_static_table_columns`, `_TABLE_VARIABLE`), never from a name. Add `SUMMARIZE`, `GROUPBY`, `CROSSJOIN`, `UNION` to `_static_table_columns` where the spec needs them: today a table of unknown shape falls back to stored columns of the same name, which is the older behaviour and wrong when a column is renamed.

## Part C: ISLOGICAL of a logical operator (198)
`ISLOGICAL(2.5&&"")` is True, `ISLOGICAL("0"||LEFT("a",0))` is False, `ISLOGICAL(TRUE()&&VAR y="" RETURN y)` is True, `ISLOGICAL(AND("-1",""))` is True. You left this refused in Task 15, rightly. Look at the operands: which of them convert to True/False at compile time, and which only at run time. If you cannot state the rule on their types, keep the refusal again.

## Part D: a typed BLANK beside a text or a date (144)
`SUMX({2.5&&"","a"},IF(ISBLANK([Value]),1,2))` is 4, `COUNTAX({2.5&&"","a"},[Value])` is 2, yet `MAXX({2.5&&"","a"},FORMAT([Value],"General Number"))` fails with a type mismatch and `MAXX({2.5&&"","a"},COALESCE([Value],5))` is BLANK. It reads as an empty text except where it does not. Claude could not state the rule. Do not fit it: take the cases that follow one rule and keep the others refused by a condition on types.

## Part E: `==` in the local engine (78)
`SUMX({2.5&&"",BLANK()},IF([Value]==FALSE(),1,2))` is 4: a BLANK column. The refusal "== needs operands of a known type" is the other side of A1. Do them together.

## Part F: tables and VARs as CALCULATE filters (102)
`CALCULATE(COUNTROWS(Facts),VAR t=ADDCOLUMNS(Facts,"q",Facts[Quantity]*2) RETURN t)` is 6, `CALCULATE(COUNTROWS(Facts),VAR t=TOPN(2,Facts,..) RETURN t)` is 2. See `_is_table_filter_argument` and `_unwrap_var_filter`: a VAR holding a table is a table; a VAR holding a True/False with an aggregate stays an error; a VAR is evaluated **once, before the FILTER**, so a VAR holding a CALCULATE must not be put inside a FILTER's row (Power BI: `CALCULATE(COUNTROWS(Facts),VAR m=CALCULATE(MAX(Facts[Quantity])) RETURN FILTER(Facts,Facts[Quantity]=m))` is 1). The right fix there is to evaluate it once, not to refuse it; try that.

## Part G: COALESCE whose earlier argument can fail (40)
`MAXX(Facts,COALESCE(BLANK(),SUMX(VALUES(Facts[Region]),DATE(2020,1,1)),1))` is 131493. Beside a text, the type is a Variant: `MAXX(Facts,COALESCE(SUMX(VALUES(Facts[Region]),DATE(2020,1,1)),"a"))` shows a date. `_cannot_raise` is a list of function names that has grown: replace it with what the guard really needs, or leave it.

## Rules
1. Tests first (`tests/test_iteration105_strict_types_6.py`). Compute every answer from DAX semantics, never from the saved answers or the spec file.
2. Check each new rule on the standard Facts table **and** on tables A and B of `tests/fixtures_misc3_alt.json`, all three tables of `tests/fixtures_variant2_review_alt.json`, all three of `tests/fixtures_typed3_review_alt.json`, table B of `tests/fixtures_logic4_review_alt.json` and table B of `tests/fixtures_typed5_review_alt.json`. A rule that holds on one table only is fitted, not understood.
3. **Do not turn a refusal into a value unless you know the rule for every shape it now lets through.** For each refusal you remove or narrow, write down in `HANDOFF.md` which shapes it lets through and how you know they are right. If you do not know, keep the refusal and report the item.
4. **No rule keyed to how an expression looks or to a word in it.** No literal text from the spec in the code, no test on a column's name, no list of function names standing in for a type. Ask for the type: `{"a","b"}` and `{UPPER("a")}` are both text.
5. A result that depends on the order the engine walks the rows cannot be derived here: refuse it.
6. **No new kind of value in the evaluator.** If Power BI shows a BLANK with a type, it is `None` plus a static type.
7. Run the replay (`PYTHONPATH=. python tools/parity_check.py`, about 2 minutes, no pytest) after every Part: a refusal on a locked item is a regression.
8. Every saved value must match or be refused with a true reason; nothing may become `DIFF` or `CRASH`; no locked item may change. A refusal must raise `MeasureError` (`dax_typed.refusal`), never `MeasureRuntimeError`, which IFERROR would turn into a value.
9. **Finish with the full gate and paste its last lines.** `PYTHONPATH=. python tools/parity_check.py --tests` stops at the first failing test: if it fails, also run `QT_QPA_PLATFORM=offscreen python -m pytest -q` and report **every** failing test. Never write "gate passed" unless that exact command printed `PARITY GATE PASSED`.
10. **New: compare with `main` before you stop.** Export `main` with `git archive main analytics_studio tools | tar -x -C <scratch>`. Write at least 5,000 expressions around each thing you changed: other functions, other values, wrapped in `+1`, `&"z"`, `ISBLANK`, `IFERROR`, a comparison, a VAR, a column of `ADDCOLUMNS`, a constructor beside each other type. Answer them with both engines. Read every answer that changed and justify it from a rule, in groups, in `HANDOFF.md`. An answer that changed for no reason you can state is a bug. A Python exception anywhere is a bug in your change.
11. Branch `antigravity/strict-types-6` from `main`. No `--freeze`, `--accept`, commit, merge; no Power BI VM; no global `str.replace` on `measures.py`; no edits to existing tests (list them in `HANDOFF.md` for Claude).
12. Write what you did and refused in `HANDOFF.md`, set Task 16 READY FOR REVIEW and "Active agent: Claude". "Working tree clean" means no uncommitted change: say no if there is one.

## Not in Task 16 (parked, reasons in `HANDOFF.md`)
Non-ASCII collation and composed / decomposed text (1,657), engine row orders (TOCSV, CONCATENATEX, SUMMARIZE, TABLEOF, about 665), LINEST rank-deficient or perfect fits (701), SUBSTITUTEWITHINDEX (857), NaN beside other numbers in a Variant MAXX / MINX (117), Currency in the statistical iterators (136), varying dates in VARX / STDEVX (125), `SIN` digits in CONCATENATEX (7), GEOMEANX of mixed signs.
