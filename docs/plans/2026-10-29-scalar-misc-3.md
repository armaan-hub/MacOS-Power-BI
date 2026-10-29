# Task 10: scalar-misc-3 (ALLCROSSFILTERED beside other filters, EVALUATEANDLOG in filters, IF.EAGER and CUSTOMDATA leftovers, TABLEOF order, XNPV extremes, text collation)

**Branch:** `antigravity/scalar-misc-3`  **Written by:** Claude, 2026-10-29  **Status:** see `HANDOFF.md`
**Start condition:** Task 9 (`pending-gaps-1`) is DONE (reviewed, locked, merged) and `HANDOFF.md` says Active agent: Antigravity. Branch from `main`.

Read first: `AGENTS.md` ("Compute, never look up"), `HANDOFF.md`, the "Review outcome" of `docs/plans/2026-10-29-pending-gaps-1.md` and of `docs/plans/2026-10-26-table-fns-2.md`.

## Goal
Make the app answer what Power BI answers for these valid expressions the app refuses today (`PARITY_LEDGER.md`, section "Pending work"; their saved answers are in `tools/parity/<battery>.json`, find an item with `grep -n "<text>" PARITY_LEDGER.md`). About 92 items in four parts. No VM is needed for the build (the saved answers are the specification); Claude tests against Power BI in the review. Do not edit saved answers; do not read them at run time (`tests/test_no_answer_key_in_app.py`).

## Part A: ALLCROSSFILTERED beside other CALCULATE filters (battery `dax_battery_scalar_misc2_extra`, 30 items)
`CALCULATE(COUNTROWS(Facts),ALLCROSSFILTERED(Facts),<another filter>)`, inside SUMX/MAXX/CONCATENATEX row contexts, and inside a FILTER predicate scalar (`Facts[Quantity]>CALCULATE(AVERAGE(Facts[Quantity]),ALLCROSSFILTERED(Facts))`). Task 4 made the bare form work (`CALCULATE(COUNTROWS(Facts),ALLCROSSFILTERED(Facts))` is 6). Work out from the saved answers how Power BI orders the clear and the other filter (`ALLCROSSFILTERED(Facts),Facts[Region] IN {"East","West"}` is 5, `ALLCROSSFILTERED(Facts),ALL(Facts)` is 6, `ALL(Facts),ALLCROSSFILTERED(Facts)` is 6, `ALLCROSSFILTERED(Facts),VALUES(Facts[Region])` is 6, `ALLCROSSFILTERED(Facts),ISAFTER(Facts[Quantity],3)` is 2). Express it with the same filter machinery the other clear functions (`ALL`, `REMOVEFILTERS`) use; do not add a new evaluator.

## Part B: EVALUATEANDLOG, IF.EAGER, CUSTOMDATA, TABLEOF (batteries `dax_battery_scalar_misc2_extra` and `_extra2`, about 25 items)
- `EVALUATEANDLOG(x)` as a CALCULATE filter argument (a table or a column comparison): it returns `x` unchanged, so the filter means what `x` means. Also `EVALUATEANDLOG(ROW("a",1))` at the top, and the 3-argument form `EVALUATEANDLOG(1,"a",Facts[Quantity])`.
- `IF.EAGER(TRUE(),DATE(2020,1,1),2)` (a date beside a number is a number: 43831), `MAXX(Facts,IF.EAGER(cond,Facts[Sales],BLANK()))`, `IFERROR(ERROR("e"),x)` in an iterator, `SUMX(Facts,IF.EAGER(TRUE(),1,ERROR("x")))` and `...VALUE("x")` (6: the error branch is evaluated and the error is NOT raised when the condition picks the other branch; read the saved answers for the exact rule and for the cases that are errors).
- `MAXX(Facts,CUSTOMDATA())` / `MINX` are BLANK.
- `TABLEOF(Facts[Region])` walked in order (`CONCATENATEX(TABLEOF(Facts[Region]),Facts[Region],",")` is `East,East,East,West,West,North`, i.e. the row order of the table), `TOPN(n,TABLEOF(col),col)` and `MAXX/SUMX(TOPN(1,TABLEOF(...)...))`. TOPN with tied sort values lists tied rows in an order that depends on the data (open item in `HANDOFF.md`): model it only for the shapes where the rule is clear and check it on data whose rows are in another order; otherwise refuse.

## Part C: XNPV extremes (battery `dax_battery_xnpv2`, 36 items)
Rate argument from `ROW("a",0.1)`; very large rates (`1E200`, `1E308` give `-1000`); `1/0` and `0/0` rates and dates; Infinity/NaN in the values (`IF([n]=365,1/0,[v])` is `Infinity`; `[v]*1E308*10` is NaN); Currency values (the result is a Currency: `17.4343`); dates past 9999-12-31 (`DATE` serials 2958466 and beyond, and `1E12`: read the saved answers for what XNPV does with them). Keep every saved Power BI error refused. XNPV was done in Task 3 (`analytics_studio/measures.py`, search `XNPV`): extend it, do not rewrite it.

## Part D (optional, only if the rule is derived and checked on fresh strings): text collation (battery `dax_battery_scalar_misc2_extra2`, 21 items)
`"é"<"e"` is False, `"ä"<"b"` True, `"Z"<"ä"` False, `"éa"<"eb"` True, `MAX("ä","z")` is `z`, `ISAFTER("é","e")` True, `"æ"="ae"` True, `"ǆ"="dž"` True, `"ä"="ä"` (composed against decomposed) True. This is a linguistic collation (letters first, accents next, case ignored), not code-point order. Derive the comparison from a general rule (for example Unicode canonical decomposition plus the expansion of ligatures, comparing base letters before accents) and apply it ONLY to strings whose characters you can classify (Latin letters with diacritics); refuse every other non-ASCII text (Greek, Cyrillic, CJK, symbols). A rule that matches the 21 saved items but is a lookup of those strings is not accepted. If you cannot derive it, leave Part D refused and say so.

## Rules
1. Tests first. Compute every answer from DAX semantics; `tests/test_no_answer_key_in_app.py` must stay green.
2. Check on data that is not the standard six rows: the Task 8 and 9 reviews found that matching the saved items can be luck (row order, ties, groups that are not alphabetical). If an order or a rule is not derivable, refuse with `MeasureError`; refusing is better than a wrong answer.
3. Every Power BI error saved in these batteries (answer starts with `ERR:`) must stay refused.
4. Branch `antigravity/scalar-misc-3` from `main` (after the user has approved the Task 9 lock/commit/merge). No `--freeze`, `--accept`, commit, merge; no Power BI VM; no global `str.replace` on `measures.py`.
5. Finish with `PYTHONPATH=. python tools/parity_check.py --tests`, write what you did and refused in `HANDOFF.md`, set Task 10 READY FOR REVIEW and "Active agent: Claude".

## Not in Task 10
LINEST / LINESTX (806 items) and SUBSTITUTEWITHINDEX (934 items) extra shapes, ADDMISSINGITEMS over SUMMARIZECOLUMNS/TOPN order (312 items): rules not derivable so far. RANKX/INDEX inside a CALCULATE filter, `INFO.TABLES()`, FIRSTNONBLANKVALUE in a filter, nested CALCULATETABLE in a filter scalar, `IF(TRUE(),1,"a")` beside a text column (about 24 items left from Task 9: `dax_battery_sdet_filters`, `_round2` to `_round5`).
