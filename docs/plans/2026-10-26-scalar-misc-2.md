# Task 4: scalar-misc-2 (IF.EAGER, ERROR, CUSTOMDATA, ISAFTER, NAMEOF, TABLEOF, EVALUATEANDLOG, ALLCROSSFILTERED in CALCULATE)

**Branch:** `antigravity/scalar-misc-2`  **Written by:** Claude, 2026-10-26  **Status:** see `HANDOFF.md`
**Start condition:** Task 3 (`xnpv-1`) is DONE and `HANDOFF.md` says Active agent: Antigravity. Branch from `main`.

## Goal
Add seven small DAX functions so that every non-error Power BI answer saved in `tools/parity/dax_battery_scalar_misc2.json` is reproduced (142 expressions: 99 real answers to implement, 43 Power BI errors that must stay refused). No VM is needed. Do not run `--freeze`.

## Rules, per function (from the saved answers; read exact expressions and results from the JSON)

**IF.EAGER(cond, then, [else])** : like `IF`, but both branches are evaluated before the choice. Same results as `IF` when no error occurs (`IF.EAGER(TRUE(),1,2)` is `1`; `IF.EAGER(FALSE(),1)` is BLANK; `IF.EAGER(BLANK(),1,2)` is `2`; a number is a condition like in `IF`: `0` false, other true; a text condition is an error). 2 or 3 arguments only. Tested: an error in the unused branch (`ERROR("x")`, `1/0`, `SQRT(-1)`, `VALUE("x")`) does NOT change the answer in Power BI (`IF.EAGER(TRUE(),1,ERROR("x"))` is `1`), so for the saved cases the result equals `IF`. A table result is an error (refuse). A bare column as condition is an error (refuse).

**ERROR(text)** : raises an error with that text. The argument must be a string literal (a constant). `ERROR("x"&"y")`, `ERROR(1)`, `ERROR(BLANK())`, `ERROR(TRUE())`, `ERROR(UNICHAR(65))` are errors (refuse). The raised error is catchable: `IFERROR(ERROR("x"),5)` is `5`, `ISERROR(ERROR("x"))` is `True`, `IFERROR(ERROR("a"),BLANK())` is BLANK; `IF(TRUE(),1,ERROR("x"))` is `1` (branch not evaluated), `IF(FALSE(),1,ERROR("x"))` is an error. `SUMX(Facts,IF(Facts[Quantity]>10,ERROR("big"),1))` is `6` (never raised); with `>2` it is an error. `COALESCE(ERROR("x"),1)` is an error (NOT caught). An error stays an error through `&` and `+` unless inside `IFERROR`.

**CUSTOMDATA()** : no arguments; returns BLANK. `CUSTOMDATA()&"x"` is `x`, `LEN(CUSTOMDATA())` is BLANK, `ISBLANK(CUSTOMDATA())` is `True`. With an argument it is an error (refuse). (The environment-dependent `USEROBJECTID` is NOT in this task.)

**ISAFTER(v1, v2, [order, v1b, v2b, ...])** : `True` when the value list `v1...` sorts strictly after `v2...` in the given order; 2 arguments compare `v1` and `v2` ascending. Order keywords `ASC`/`DESC` apply to the pair that follows. The saved cases cover: numbers, text (case-insensitive: `ISAFTER("b","a")` is `True`, `ISAFTER("a","B")` is `False`), dates, Booleans (`TRUE` after `FALSE`), BLANK (BLANK sorts as `0` for numbers and as empty text for text, and is never after itself: `ISAFTER(BLANK(),-1)` `True`, `ISAFTER(-1,BLANK())` `False`, `ISAFTER(BLANK(),0)` `False`, `ISAFTER(0,BLANK())` `True`, `ISAFTER(BLANK(),1)` `False`, `ISAFTER(1,BLANK())` `True`, `ISAFTER(BLANK(),"")` `False`, `ISAFTER("",BLANK())` `True`, `ISAFTER(BLANK(),BLANK())` `False`; the JSON is the truth), `Infinity` from `1/0` sorts after any finite number (`ISAFTER(1/0,1)` `True`), equal values give `False`, several pairs compare in order (`ISAFTER(1,1,ASC,2,1)` is `True`). Mixed types (`ISAFTER(1,"a")`) and an incomplete pair (`ISAFTER(1,1,ASC,2)`) are errors (refuse).

**NAMEOF(ref)** : the qualified name of a column or table as text: `NAMEOF(Facts[Sales])` is `'Facts'[Sales]`, `NAMEOF(Facts)` is `'Facts'`. Anything else (an aggregate, a number, a measure that does not exist, a missing column, a second argument, no argument) is an error (refuse).

**TABLEOF(column)** : the whole table the column belongs to, as a table (`COUNTROWS(TABLEOF(Facts[Sales]))` is `6`, `SUMX(TABLEOF(Facts[Quantity]),Facts[Quantity])` is `15`). Used where a scalar is needed it is an error (refuse). `TABLEOF(Facts)`, `TABLEOF(1)` and 2 arguments are errors (refuse). Only support it where a table function already accepts a table expression.

**EVALUATEANDLOG(value, [label], [maxRows])** : returns `value` unchanged (scalar or table); label and maxRows are ignored. 1 to 3 arguments. `EVALUATEANDLOG(3)` is `3`, `COUNTROWS(EVALUATEANDLOG(Facts))` is `6`, `EVALUATEANDLOG(BLANK())` is BLANK, `EVALUATEANDLOG(1/0)` is `Infinity`, `CALCULATE(COUNTROWS(Facts),Facts[Quantity]>EVALUATEANDLOG(3))` is `2` (it behaves like the plain value in a filter). `EVALUATEANDLOG(Facts[Quantity])` (a bare column) is an error (refuse). **Careful:** `IFERROR(EVALUATEANDLOG(ERROR("x")),5)` is an ERROR in Power BI (not 5): an error raised inside `EVALUATEANDLOG` is not caught by `IFERROR`. Keep that refused.

**ALLCROSSFILTERED(table)** : only as a filter argument of CALCULATE: `CALCULATE(COUNTROWS(Facts),ALLCROSSFILTERED(Facts))` is `6`; it removes the filters on the table and on tables related to it; an explicit filter next to it still applies (`CALCULATE(COUNTROWS(Facts),Facts[Region]="East",ALLCROSSFILTERED(Facts))` is `3`). Used as a table expression (`COUNTROWS(ALLCROSSFILTERED(Facts))`) or on a column it is an error (refuse). With a single table model there is no related table; do not invent cross-table behaviour.

## Where to look (do not trust line numbers; search for the text)
- `analytics_studio/measures.py`: how `IF`, `IFERROR`, `ISERROR`, `COALESCE`, `ALL`, `NAMEOF`-like name handling and error classes (`MeasureError`, soft errors for `IFERROR`) work; the battery `dax_battery_iferror_hard_errors` documents which errors `IFERROR` does and does not catch.
- `tools/dax_oracle_diff.py` function `local()`; `tests/test_iteration89_scalar_gaps_1.py` (after Task 1 is merged) as a test model.

## Must NOT change
- Anything refused today and not listed above. All 43 items whose saved Power BI answer starts with `ERR:` must still be refused (the gate reports DIFF if the app answers).
- Behaviour of every supported function; saved answers; `PARITY_LEDGER.md`; `tools/parity_check.py`; `tools/dax_battery_*.json`; existing tests.
- `USEROBJECTID`, `SELECTEDMEASURE*`, `NATURALJOINUSAGE`, `DETAILROWS`, `APPROXIMATEDISTINCTCOUNT`: out of scope (they depend on the environment or model objects the app does not have).
- If a shape is not in the saved answers, refuse it and write the question under "Open questions" in `HANDOFF.md`.

## Acceptance checks
1. New test file `tests/test_iteration92_scalar_misc_2.py` (new file, allowed). Write the failing test first. It loads `tools/parity/dax_battery_scalar_misc2.json` and asserts `status(item["powerbi"], dax.local(item["expr"])) == "match"` for every item (that covers both the answers and the refusals), plus an explicit list of at least 8 refusals: `ERROR(1)`, `ERROR("x"&"y")`, `CUSTOMDATA(1)`, `NAMEOF(SUM(Facts[Quantity]))`, `TABLEOF(Facts)`, `ISAFTER(1,"a")`, `IFERROR(EVALUATEANDLOG(ERROR("x")),5)`, `COUNTROWS(ALLCROSSFILTERED(Facts))`.
2. `PYTHONPATH=. python tools/parity_check.py`: group `dax_battery_scalar_misc2` has 0 pending, DIFF 0, CRASH 0; everything locked still matches.
3. `PYTHONPATH=. caffeinate -i python tools/parity_check.py --tests` ends with PARITY GATE PASSED, 0 pytest failures; paste the real summary lines into the `HANDOFF.md` entry.
4. Do not run `--freeze` or `--accept`.

## Hand-over
Status `READY FOR REVIEW`, a `HANDOFF.md` entry from the template, all changed files listed, and anything not done stated.
