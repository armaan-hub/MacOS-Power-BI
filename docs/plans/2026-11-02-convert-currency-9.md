# Task 19: convert-currency-9 (CONVERT typing, Currency with Infinity or NaN, ISBLANK that never evaluates, BLANKs that cancel an error, text dates, sign of zero)

**Branch:** `haiku/convert-currency-9`  **Written by:** Claude Opus 5.5, 2026-11-02  **Status:** see `HANDOFF.md`
**Who builds:** Haiku 5.5, one Part at a time, started by Opus 5.5. A Part that fails twice goes to Sonnet 5.5.

Read first: `AGENTS.md` ("Compute, never look up"). Every rule below was measured in Power BI Desktop on 2026-11-01 and 2026-11-02, 23,192 expressions on each of three Facts tables.

## Goal
5,778 items in `tools/parity/task19_convert_currency_spec.json` (fields `part`, `expr`, `powerbi`, and `app_answer` or `app_refusal`). 2,419 are wrong today, 3,359 are refused. The spec is for reading and for the scoring script; the app must never read it. Clearing a wrong answer matters most. An honest refusal is acceptable for a shape no rule below covers; a wrong answer is not.

## Part B (449 wrong): Currency with Infinity or NaN
- `*` between a Currency and an Infinity or NaN is an error: "The result of a conversion or arithmetic operation is either too large or too small." Both operand orders, Currency 0 too.
- `/` with a Currency numerator and a NaN or 0 denominator is an error: "A division by zero has been encountered." `CURRENCY(2)/(1/0)` is 0.
- `+` and `-` keep today's answers: `CURRENCY(2)-(1/0)` is -Infinity.
- A DIVIDE that gives BLANK is a BLANK, not an Infinity: `CURRENCY(2)-DIVIDE(1,0)` is 2.
- `ISNUMBER`, `ISTEXT`, `ISLOGICAL` and the other type tests of these errors are errors. `ISBLANK` follows Part C: `ISBLANK((0/0)*CURRENCY(2))` is False. `ISERROR` is True and `IFERROR` takes the alternate.
- Both errors are hard over rows: they stop `SUMX`, `MAXX`, `AVERAGEX` and `ADDCOLUMNS`.
- `CONVERT(x,CURRENCY)` and `CONVERT(x,INTEGER)` of Infinity, NaN or 1E300 are the same "too large or too small" error.

## Part A (758 wrong): CONVERT
1. A CONVERT has its target type statically, also through `IF`, `VAR`, `COALESCE`, `IFERROR` (`_static_numeric_type` knows CONVERT; the iterator check does not reach it). So, whatever the table, also an empty one, and whatever the branch taken:
   - `SUMX`, `AVERAGEX`, `PRODUCTX`, `GEOMEANX`, `STDEVX.*`, `VARX.*` of a String or Boolean body are the error "The function X cannot work with values of type String." (or Boolean).
   - `PRODUCTX`, `GEOMEANX` of a Date body are the error "... of type Date."
   - `MEDIANX` of String, Boolean or Date is its own error "MEDIANX does not support expressions of type string/Boolean/..." Copy the text from the spec's `powerbi` field, starting at `MEDIANX`.
2. A date-typed body stays a date: `MAXX`, `MINX` and `SUMX` of `IF(TRUE(),CONVERT(1,DATETIME))` print `12/31/1899 00:00:00`.
3. `CONVERT(x,DATETIME)` of Infinity, -Infinity or NaN stays non-finite. It only prints as `12/31/9999 23:59:59`, `01/01/0100 00:00:00` or `12/30/1899 00:00:00`. (Corrected in review: the first version of this rule clamped the value, and measurement showed it does not.)
4. `CONVERT(BLANK(),BOOLEAN)` is False, so `COUNTAX` counts it. `CONVERT("",BOOLEAN)` is BLANK.
5. `STDEVX.S` and `VARX.S` of a Currency body over one row are "A division by zero has been encountered." A Double body gives NaN as today.
6. `STDEVX.S` of a Currency body rounds to 4 decimals: `STDEVX.S({1,2},CONVERT([Value],CURRENCY))` is 0.7071.
7. Text to DATETIME is Part E.

## Part C (174 wrong): ISBLANK of something that can never be blank
Power BI does not evaluate `ISBLANK(x)` when `x` can never be blank: the answer is False, and any error inside is never seen. Measured on 1,336 expressions: of the 342 this rule says False, all 342 are False.
Add `_never_blank(node)`, static, on the parsed node:
- A number, string, boolean literal: yes.
- `SQRT`, `LN`, `LOG10`, `LOG`, `VALUE`, `MOD`, `DATE`, `TRUE`, `FALSE`: yes.
- `IF` with three arguments: both branches.
- `CURRENCY(x)`: when `x` can never be blank.
- `+`, `-`, `&` (the `concat` node): either operand. `*`, `^`: both operands. `/`: the left operand.
- `VAR q=x RETURN ISBLANK(q)`: an argument that is exactly a variable is judged by its bound expression. A variable as an operand of arithmetic is still no.
- Everything else, a `var` and a `let` included: no. `FACT`, `SIN` and `ERROR` are no.
A listed function counts only when all its arguments can never be blank, and data-reading arguments stay evaluated: `ISBLANK(SQRT(BLANK()))` is True. Then `ISBLANK(x)` is False when `_never_blank(x)`. Otherwise evaluate; an error passes through. Remove the "swallowed" branch of `ISBLANK` in `evaluate` only as far as these tests require: a call that the old rule swallowed and `_never_blank` does not cover must keep its answer or be raised, as the locked items show.
Examples: `ISBLANK(("a"*2)/SUM(Facts[Sales]))` False. `ISBLANK(MAX(Facts[Sales])/LOG10(0))` error. `ISBLANK((VAR y=1 RETURN y)*LN(0))` error. `ISBLANK(FACT(-1)/"b")` error.

## Part D (515 wrong): a BLANK that needs no scan cancels an error
Extends the corrections of Task 18. In `x*y`, and `x/y` for a left `x`, a BLANK operand cancels an error or text in the other operand when working it out scans no column values. These cancel when they give BLANK: `SELECTEDVALUE(col)`, `SELECTEDVALUE(col,BLANK())`, `IF(HASONEVALUE(col),1)`, `IF(ISFILTERED(col),1)`, `IF(ISINSCOPE(col),1)`, `IF(COUNTROWS(Facts)=0,1)`, `IF(SELECTEDVALUE(col)="x",1)`, `HASONEVALUE(col)*BLANK()`, `ISBLANK(1)*BLANK()`, and those inside `CALCULATE(..)` with no filter, `COALESCE(..,BLANK())` or a VAR.
These do not, and stay errors: `IF(SUM(col)<-9,1)`, `SWITCH(SUM(col),..)`, `LOOKUPVALUE`, `MINX`, `FIRSTNONBLANK`, `COUNTROWS(FILTER(..))`, `SELECTEDVALUE(col,1)`.
`+` never cancels; a right-hand BLANK in `/` never cancels. Write a new predicate beside `_reads_no_data` and use it at the BLANK cancel test only (`measures.py` near line 15269). Do not change `_reads_no_data`: the date rule uses it.
Corrected in review, by measurement: the cancel works at top level and through IF, VAR and plain iterators. CALCULATE with a filter other than ALL blocks it, and so does a row context over model rows; ALL, ALLSELECTED, REMOVEFILTERS and KEEPFILTERS(ALL) do not, and neither do tables with no model rows.

## Part E (40 wrong, 538 refused): text that is a date or a time
Text in arithmetic, `VALUE`, and `CONVERT(..,DOUBLE)` is first read as a number as today. If that fails it is read as a date and time with the parser behind `DATEVALUE` and `TIMEVALUE` in `dax_dates.py`, and the result is the day number with the time as a fraction: `VALUE("2020-01-02")` 43832, `"12:30"+0` 0.520833333333333, `"1/2/2020"-DATE(2020,1,1)` is 1, a number, `DATE(2020,1,1)-"2020-01-02"` is `12/29/1899 00:00:00`, a date. `"13/1/2020"` is 43843. `"5%"`, `"TRUE"`, `""`, `"Jan"`, `"2020-13-01"` and `"2020-01-02T03:04:05"` stay errors. `CONVERT(..,INTEGER)` and `CONVERT(..,CURRENCY)` of a date text stay errors. Comparison stays an error.
`CONVERT(text,DATETIME)`: a date text gives the date. A number text is the error "Cannot convert value 'x' of type Text to type Date." (`"3"`, `"2020"`, `" 7 "` shows `'7'`, `"-3"`, `"$5"`, `"1e3"`). `"1/2"`, `"1-2"`, `"1 1/2"`, `"1,000"`, `"3.5"` as dates: use the spec if the parser can do it simply, otherwise leave them refused; `"1/2"` depends on the current year, so tests must compute it.

## Part F (178 wrong): a logical operator can never be blank
Rewritten 2026-11-02 after the first version, a refusal, broke 342 locked items. Measured on three tables: a logical operator counts as never blank in Part C's rule, and all 184 such cases are False, 0 exceptions.
- `_never_blank` also says yes to: the `logical` node (`&&`, `||`), `AND`, `OR`, `NOT`, the `comparison` node, and a `unary` by its operand. So `ISBLANK((0||"")*(1&&""))` and `ISBLANK((1&&"")/(0/0))` are False, and `ISBLANK((0||"")*SUM(Facts[Sales]))` is evaluated as today.
- `COALESCE(x,..)` with `_never_blank(x)` returns `x` and never looks further: `COALESCE((2.5&&"")*CURRENCY(2),5)` is BLANK, 0 of 116 measured cases fall through.
- A logical operator's BLANK on the left of `*` or `/`, or on the right of `*`, cancels an error like the BLANKs of Part D: `IFERROR((2.5&&"")/SQRT(-1),"e")` is BLANK, `ISERROR((1&&"")/("a"*2))` False.
- `ISNUMBER` has no such rule: leave it. No new kind of value.

## Part G (274 wrong): the sign of zero and NaN, and large Doubles as text
All of this is IEEE arithmetic on a Double: `-(0.0)`, `0.0*-1` and `0/-1` are -0, and print `-0`. `1/-0` is -Infinity. `(0/0)&"z"` is `-nan(ind)z`, but `(-(0/0))&"z"` and a division by -0 of 0 are `nanz`. `FORMAT` prints `nan`, `inf`, `-inf` in those cases.
A Double of 1E15 or more in size prints as text with an exponent: `((3)*-(1E15))&"z"` is `-3E+15z`, `((1E16)/(2))&"z"` is `5E+15z`.
A Part that breaks a locked item here stops and reports; do not force it.

## Not in Task 19
Part H of the spec (COUNTAX of NaN), `STDEVX.P` noise, `CONVERT` of a column's text in a table that is empty.

## Rules
1. One Part at a time, in the order B, A, C, D, E, F, G, then stop and report. Do not start the next Part.
2. Tests first, in `tests/test_iteration108_convert_currency_9.py`. Compute expected answers from the rule above.
3. Change the fewest lines you can, and reuse what exists.
4. No rule keyed to how an expression looks. No literal text from the spec in the code. No new kind of value. A result that depends on row order stays refused.
5. A refusal raises `MeasureError` (`dax_typed.refusal`), never `MeasureRuntimeError`.
6. After each Part run the scoring script for that Part (`PYTHONPATH=. QT_QPA_PLATFORM=offscreen python <scratchpad>/t19/score.py B`) and the replay (about 2 minutes): `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python tools/parity_check.py`. It must show 0 DIFF, 0 CRASH, `locked 343798`.
7. Never run `--freeze`, `--accept`, commit, merge, push or Power BI. No global replace on `measures.py`. No edits to existing tests or saved answers: list those in your report. Scratch files go in the scratchpad.

## Review outcome (2026-11-02)
Shipped as Iteration 108. Part A rule 3, Part D and Part F were corrected by measurement. Part G's sign of zero stayed out: it needs Double arithmetic in the evaluator path, so 4 tests are expected failures. Part H stayed out as planned. Review: 117,156 results on 3 tables in three batches, 0 regressions, 12,293 wrong to right, 2,746 wrong on both, 9 match to refused. Real app 0 wrong. Gate passed, locked 382,125.
