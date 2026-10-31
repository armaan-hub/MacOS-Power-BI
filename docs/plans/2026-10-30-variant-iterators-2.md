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

## Review outcome (Claude, 2026-10-30)
Antigravity's build matched 1,160 of the 1,161 spec items, and all 163,762 locked items stayed intact. Part A (VAR after `&&`, `||`, `^`), Part B2 (text BLANK) and Part B3 (text aggregates) held up on fresh shapes, and so did the new Variant comparison ordering (12,000 probes, no difference). Part B1 did not: fresh Power BI probes (about 130,000 answers on four Facts tables, none of them saved before) found 269 distinct wrong answers, nearly all shapes `main` had honestly refused and this build answered wrongly. The mechanism was the one Rule 3 warns about: refusals removed or narrowed without knowing the rule for every shape they had covered.

Measured and fixed:
- **`&&`, `||`, AND, OR:** a value that decides, on either side, swallows the other side's conversion error. An empty text on the left is False. On the right of an undecided left it displays as BLANK yet ISBLANK is False, so it is refused.
- **A constant IF over a text column:** `iterator_body_as_scanned`. A condition that reads no row is settled first. IF reduces to the taken bare column beside any other branch; IF.EAGER only beside a literal-like one (`_literal_like_branch`). SWITCH, COALESCE, VAR blocks and EVALUATEANDLOG do not reduce. Whether the reduction happens depends on the scan, and differently for MAXX / MINX and COUNTX (`_scan_class`, 30 table shapes); an outer filter or row stops it unless ALL clears it. SUMX never reduces. Replaces `_active_branch` and `_has_computed_numeric_branch`, which were fitted to the saved items.
- **Infinity and NaN in a Variant MAXX / MINX:** Infinity counts where a plain number body gives BLANK; nothing but NaN is NaN; NaN beside other numbers depends on the engine's walk (Infinity with a text column in the other branch, NaN with a literal), so it is refused.
- **A variable in a branch:** `body_value_type` sees through VAR blocks, so text reached through a variable is no longer converted to a number (`SUMX(Facts,VAR v=1 RETURN IF(Facts[Quantity]>2,v,"5"))` was 18, Power BI says 3).
- **Refused, because the rule is not known:** an AVERAGEX over a Currency beside other number types that does not land on 4 decimals, text in a Variant statistic (PRODUCTX, MEDIANX), a CONCATENATEX whose walk follows column values (`concatenate_walk_is_unmodelled`).
- **Typed at compile time:** FIRSTNONBLANK and its relatives in the numeric iterators; VALUE of Infinity or NaN is an error.
- **Real-app bug found by running the unpatched app:** a measure whose result is a date before day zero or past 9999 raised while a card formatted it, which broke every later measure. The evaluator now refuses it (`evaluate_measures`). `main` had this too.

Lessons carried into Task 13: a replay run takes 2 minutes, so run it after every narrowing (a first version of the CONCATENATEX refusal broke 384 locked items, caught before the gate); never run heavy jobs beside the gate; test the real app without the full-precision patch at least once.
