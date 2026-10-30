# Task 12: variant-iterators-2 (VAR after && / ||, Variant bodies in MAXX / MINX, text MAXX / MINX that find no value)

**Branch:** `antigravity/variant-iterators-2`  **Written by:** Claude, 2026-10-30  **Status:** see `HANDOFF.md`
**Start condition:** Task 11 (`gaps-2`) is DONE (reviewed, locked, merged) and `HANDOFF.md` says Active agent: Antigravity. Branch from `main`.

Read first: `AGENTS.md` ("Compute, never look up"), `HANDOFF.md` (open items), the "Review outcome" of `docs/plans/2026-10-29-gaps-2.md`,
and the iteration 87 notes on Variant bodies in `analytics_studio/measures.py` (`iterator_body_kind`, `has_number_branch`, the `variant_body` branches).

## Goal
Power BI answers a value, the app refuses ("pending"). Four families, 1,161 expressions, all with Power BI's answer saved in
`tools/parity/task12_variant2_spec.json` (fields `part`, `battery`, `expr`, `powerbi`, `app_refusal`). Every item is also in one of the replayed batteries
named in `battery`, so no `--freeze` is needed: when the app answers, the replay shows `match` and the pending count drops. No new function is added.
The spec file is a copy for reading; it is **not** a replay battery and must not be read at run time (`tests/test_no_answer_key_in_app.py`).

## Part A: a VAR block as the right operand of && and || (293 items, `dax_battery_pending_extra`, `_extra2`)
`TRUE()||VAR y=1.5 RETURN y&"z"` is True, `10&&VAR y=-1 RETURN y+1` is False, `0&&VAR y=BLANK() RETURN ISBLANK(y)` is False,
`10||VAR y="b" RETURN y*y` is True (192 True, 84 False, a few numbers; no error among them). The app answers "Function VAR is not supported". Task 9 already
runs a VAR block on the right of a comparison and of `&`; the logical operators are the same shape. The left operand is converted to True/False first
(a number, `BLANK()` and text such as `"a"` appear on the left in the saved items), and the block on the right takes the type of its RETURN expression
(Task 9 review). Whether a right operand that would be an error is evaluated when the left operand already decides is not guessed: the saved items show it.

## Part B1: IF / IF.EAGER / SWITCH bodies whose branches differ in type, in MAXX and MINX (490 items, mostly `dax_battery_misc3_extra`)
`MAXX(Facts,IF.EAGER(TRUE(),1,DATE(2020,1,1)))` is 1, `MAXX(Facts,IF.EAGER(TRUE(),2.5,TRUE()))` is 2.5, `MAXX(Facts,IF.EAGER(TRUE(),"a",Facts[Sales]))` is BLANK,
`MAXX(Facts,EVALUATEANDLOG(DATE(2020,1,1)+0.5,"a"))` is a date. The app refuses with "Iterator arithmetic comparisons need numeric operands" or
"Iterator IF comparison branches need matching local data types". The rules for SUMX / AVERAGEX over a Variant body exist (iteration 87: only numbers and
dates count, text and True/False count for nothing, a number beside a date is one number type, `IF.EAGER` makes a date beside a number a number); MAXX / MINX
must follow the same typing and return the extreme of what counts. Derive the rule from the saved answers **and** check it on the second Facts table
(`tests/fixtures_misc3_alt.json`, datasets A and B hold the same shapes).

## Part B2: MAXX / MINX of text that finds no value (282 items)
`MAXX(Facts,IF.EAGER(FALSE(),Facts[Region]))` is BLANK. The app refuses: "MAXX of text found no value, and a text BLANK is not modelled". Power BI's answer is
BLANK in every saved item; the open question is where a text BLANK is later read (`&`, `=`, `LEN`, `ISBLANK`, FORMAT): read the saved answers that wrap such a
result before choosing between "return BLANK" and "refuse only where the BLANK is read".

## Part B3: MAXX / MINX / COUNTX / COUNTAX over a text aggregate body (96 items, `dax_battery_gaps2_extra2`)
`MAXX(CALCULATETABLE(Facts,Facts[Region]="East"),MAX(Facts[Region]))` is West; `COUNTAX(...,CALCULATE(MAX(Facts[Region])))` over an empty table is BLANK.
The app refuses with "Iterator MAX argument 1 needs a numeric expression". MAX / MIN of a text column is a text value (Task 11 gave it the static type Text);
the iterator should take it where Power BI does (MAXX / MINX / COUNTAX / COUNTX: yes, SUMX and the rest: error, Task 11).

## Rules
1. Tests first (`tests/test_iteration100_variant_iterators_2.py`). Compute every answer from DAX semantics, never from the saved answers or the spec file.
2. Check each new rule on the standard Facts table **and** on tables A and B of `tests/fixtures_misc3_alt.json` (`tests/test_iteration98_scalar_misc_3_review.py`
   shows how to load them: patch `dax.ROWS`, `dax.LOCAL_ROWS`).
3. Every saved value in the spec must match or be refused with a reason that is true; nothing may become `DIFF` or `CRASH`; no locked item may change.
4. Branch `antigravity/variant-iterators-2` from `main`. No `--freeze`, `--accept`, commit, merge; no Power BI VM; no global `str.replace` on `measures.py`.
5. Finish with `PYTHONPATH=. python tools/parity_check.py --tests`, write what you did and refused in `HANDOFF.md`, set Task 12 READY FOR REVIEW and "Active agent: Claude".

## Not in Task 12 (parked, reasons in `HANDOFF.md`)
Non-ASCII text collation (1,456 pending: Greek, Cyrillic, CJK need a measured collation, not a rule), VertiPaq-internal row orders (594 + 300 + 27: INDEX, TOPN ties,
DISTINCT), LINEST rank-deficient fits (433 + 244 + 20), SUBSTITUTEWITHINDEX shapes (206 + 34 + 23), the typed column of a computed SELECTCOLUMNS column over an
empty table, `NOW()` and `LASTNONBLANK` walk orders.
