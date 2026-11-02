# Task 21 currency-double-11 plan

Goal: fix the largest groups left open by Task 20: Currency arithmetic with Doubles, static types beside text numbers, CURRENCY of text and of non-finite values, dates beside Infinity or NaN, the logical BLANK beside an error, and two small functions. Every rule below was measured in Power BI Desktop on the iPad guest on 2026-11-02.

Spec: `tools/parity/task21_currency_double_spec.json` (Parts A to F, each item has the expression, Power BI's answer and today's state). Score with `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python3 <scratchpad>/t21/score.py A`.

## Part A: Currency with a Double in `*` and `/`
Power BI keeps a Currency as a scaled 64-bit integer (value times 10000). With a Double operand it turns that integer into a Double, does the operation in doubles, and rounds half away from zero to a whole number of ten-thousandths: `round(float(ticks) * y)` and `round(float(ticks) / y)`, divided by 10000. 136 of 136 measured Double rows agree: `CURRENCY(1E14)/1.5` is 66666666666666.6624, `CURRENCY(1E14)/7` is 14285714285714.2864, `0.01*CURRENCY(922337203685477)` is 9223372036854.7696. Both orders of `*` are the same. An Int64 operand keeps today's wrapping (`CURRENCY(5E14)*3`). `y/CURRENCY(x)` is a plain Double: `float(y)/float(value)`, so `0.1/CURRENCY(1234.5678)` is 8.10000066420006E-05.
The text of a `SUM(Facts[Sales])` or date operand follows the same rule; see the spec rows.

## Part B: static types
- Text number or logical `+` or `-` Currency is a Double: `ISDOUBLE("2"+CURRENCY(1))` True, `ISCURRENCY` False, and its text is a Double's: `("1E15"+CURRENCY(1))&"z"` is `1E+15z`.
- Text number `*` Currency is a Currency: `ISCURRENCY("2"*CURRENCY(1))` True, including beyond the range without evaluating (`ISCURRENCY("1E15"*CURRENCY(1))` True).
- `/` with a Double divisor is evaluated: `ISCURRENCY(CURRENCY(1E14)/0.1)` is the range error. `*` by a row-dependent Double is evaluated too: `ISCURRENCY(CURRENCY(1E14)*SUM(Facts[Sales]))` is the error, while `ISCURRENCY(CURRENCY(9E14)*1.5)` stays True.
- `ISCURRENCY(CURRENCY(1E14)/DATE(2020,1,1))` and `/"3"` are True (today refused).
- Logical `+` text and the other rows are in the spec.

## Part C: CURRENCY of text and of non-finite values
- CURRENCY or CONVERT of a text beyond the Currency range is the error "Out of present range" (`CURRENCY("1E15")`, `CURRENCY("922337203685478")`, `CURRENCY("922337203685477.5808")`); it propagates through iterators, and ISERROR is True. Within the range it works.
- `CURRENCY(1/0)`, `CURRENCY(0/0)`, `CURRENCY(-1/0)` at top level and through COALESCE are the range error (today they print Infinity or NaN).
- VALUE of a text gives a normal number, not a Decimal keeping its exponent or its digits: `VALUE("1E14")` is 100000000000000, `VALUE("1000000000000000")` is 1E+15, `VALUE("922337203685477.5807")` 922337203685478, `VALUE("0.00005")` 5E-05. It is a Double.

## Part D: a date beside Infinity or NaN
A date `+` or `-` a non-finite number is a date holding the non-finite value (today refused). It prints 12/31/9999 23:59:59 for +Infinity, 01/01/0100 00:00:00 for -Infinity, 12/30/1899 00:00:00 for NaN, reusing the Task 19 CONVERT printing (`oracle_text`), and `&"z"` is `12:00:00 AMz` for NaN. It works through MAXX, MINX, CALCULATE, IF, VAR. SUMX of such a body keeps the date type (`SUMX({1,2},DATE(2020,1,1)-(0/0))` prints 12/30/1899 00:00:00). AVERAGEX is a number (`NaN`). All rows are in the spec.

## Part E: the logical BLANK beside an error
`(x&&"")` or `(x||"")` over a row-dependent `x` (Task 20 Part C `_empty_text_blank`) is a BLANK that cancels an error in `*` (both sides) and on the left of `/`: `IFERROR((MAX(Facts[Sales])&&"")*SQRT(-1),7)` BLANK, `ISERROR(...)` False, `ISBLANK((MAX(Facts[Sales])&&"")*ERROR("x"))` True, and the same with `"a"`. On the right of `/` and in `+` the error stands: `IFERROR("a"/(...),7)` 7, `IFERROR((...)+"a",7)` 7. This is the same cancel as Task 19's BLANK. Constant `x` stays as it is today.

## Part F: small functions
- `UNICHAR(BLANK())` is BLANK (`ISBLANK` True, `ISERROR` False, `&"z"` is `z`).
- DIVIDE with a BLANK numerator: a scanned BLANK (`COUNTROWS(FILTER(Facts,FALSE()))`, `SUMX(FILTER(..),1)`) converts the divisor, so `"a"` is the error; a static BLANK (`BLANK()`, `IF(1=2,1)`, SELECTEDVALUE) does not. Use `_static_blank` from Task 20.

## Rules for the coder
1. Read this file and `AGENTS.md` first. Work on branch `haiku/currency-double-11`.
2. One Part at a time, in the order A, C, F, B, D, E.
3. Change the fewest lines you can, and reuse what exists (`to_currency`, `currency_typed`, `_currency_wrap`, `static_type_of`, `_static_blank`, `oracle_text`).
4. No rule keyed to how an expression looks. No literal text from the spec in the code. No new kind of value. A result that depends on row order stays refused.
5. A refusal raises `MeasureError` (`dax_typed.refusal`), never `MeasureRuntimeError`.
6. After each Part run the scoring script for that Part and the replay: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python3 tools/parity_check.py` (restore the ledger after with `git checkout PARITY_LEDGER.md`). A DIFF in the replay is your bug: fix the code, never saved answers.
7. Never run `--freeze`, `--accept`, commit, merge, push or Power BI. No global replace on `measures.py`. No edits to existing tests or saved answers: list those in your report. Scratch files go in the scratchpad. Do not run the full test suite.
8. Add tests to a new `tests/test_iteration110_currency_double_11.py`, one class per Part, with the measured values.

## Review outcome (2026-11-02)
Shipped as Iteration 110. Haiku's six Parts scored 2,508 match, 29 refused, 0 wrong on the spec. A fresh batch of 5,914 shapes on 3 tables found 10 new wrong answers and 256 wrong on both; Sonnet fixed them in two rounds (Double over Currency at 15 digits, text beyond the Double range, FORMAT of a non-finite date, MINX/MAXX of NaN inside IFERROR, AVERAGEX of Currency, the logical BLANK in chains, type tests of a Currency product beyond range). Final: 0 wrong, 560 wrong to right, 1,036 refused to match. Locked 430,554.
