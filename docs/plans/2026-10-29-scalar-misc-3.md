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

## Review outcome (Claude, 2026-10-29)
**Verdict:** the first build matched every saved item and was wrong on fresh shapes; Part A is accepted as built, Parts B, C and D were corrected in the review
(the same pattern as Tasks 7 to 9: the saved items fit, the rules behind them did not). Method: 52,979 fresh answers from Power BI Desktop 2.157.879.0 on the iPad
guest (headless, nothing on the main screen), none of them in a saved battery, asked on the standard Facts table and on two other Facts tables (A: 9 rows, B: 10 rows,
rows in other orders), plus 3,600 of them created as measures in the real app (Qt offscreen) and compared with Power BI's answer. Differences of the first build on the
standard table: Part A 0 of 563 (also 0 on the two other tables); Part B 207 of 2,536 (54 new against `main`, 153 older); Part C 205 + 12 crashes of 1,286; Part D 336 of 5,819.
After the fixes below every set has 0 differences except the three families listed under "Open".

**Part A (ALLCROSSFILTERED beside other filters), accepted.** It is one more member of the clearing list that `ALL` / `REMOVEFILTERS` use; 563 fresh shapes (every aggregate
x 25 other filters in both orders, inside SUMX / MAXX / CONCATENATEX, in FILTER predicates, nested CALCULATEs, CALCULATETABLE) match on all three tables.

**Part B, fixed in the review.**
- `EVALUATEANDLOG(x)` around `REMOVEFILTERS`, `ALLCROSSFILTERED`, `ALLEXCEPT`, `ALLSELECTED` or an `IN` predicate is an error in Power BI ("cannot be used as a table expression",
  "CONTAINSROW in a table filter"); the first build unwrapped it and answered. Now refused. With a table as first argument a non-constant third argument is an error too.
- `IF.EAGER`: a bare column outside a row context is an error also in the branch not taken (the static check did not know `IF.EAGER`; it did not know `FORMAT` or the expression of
  a `CALCULATE` either). A date beside a number of any kind (literal, column, `1/0`, `VALUE("x")`, `CURRENCY`, `COUNTROWS`...) makes the whole `IF` / `IF.EAGER` a number whichever
  branch is taken, also inside an iterator; the first build did it only at the top level and only for literal numbers. A literal condition (`TRUE()`, `0`, `BLANK()`) folds the other
  branch away before an unordered walk reads its columns (`CONCATENATEX(Facts,IF.EAGER(TRUE(),Facts[Quantity],Facts[Sales]),"|")` walks `Quantity`).
- `TABLEOF`: the first build removed the refusal and answered `TOPN(...TABLEOF)` and `UNION(TABLEOF,TABLEOF)` in the wrong order (6 of 6 differ). The order is known only straight under
  `CONCATENATEX`; anything with more than one row built from `TABLEOF` is refused again, `TOPN(1,TABLEOF(..),key)` stays answered when it keeps one row.
- `MAXX/MINX(Facts,CUSTOMDATA())`, the 3-argument `EVALUATEANDLOG`, `IFERROR(ERROR(..))`: accepted.

**Part C (XNPV extremes), rebuilt.** The first build fitted the 36 saved items with special cases (a rate above 1E100 gave a zero term, NaN and -Infinity dates gave NaN, an
Infinity date gave a zero term, Currency values were not rounded). A controlled matrix (498 queries: NaN / Infinity / -Infinity in the values and in the dates, at each row position,
under seven rates) shows Power BI computes plain IEEE double arithmetic: `v / (1+rate) ^ ((date - earliest) / 365)`, the earliest date being capped at serial 2958465, so a NaN date
or rate gives NaN unless the rate is 0 (`1 ^ NaN` is 1) or the exponent is 0 (`NaN ^ 0` is 1), an overflowing factor is Infinity (term 0), an underflowing one is 0 (term +-Infinity or NaN).
The loop is now exactly that (402 of 402 controlled shapes and 1,286 x 3 fresh shapes match). Also refused: Currency values computed with arithmetic (`CURRENCY([v])/3` is rounded to four
decimals before XNPV reads it: 1733.3335, exact arithmetic 1733.3333) or a non-finite Currency result, and a table constructor with several columns (`[Value1]` cannot be found).
The two Task 3 refusals that this task was meant to open (NaN / 1E12 / past-9999 dates, Currency) were removed from `tests/test_iteration91_xnpv_1.py` after Power BI answered them.

**Part D (text collation), narrowed.** Accepted rule: ASCII letters and digits with at most one accent of the thirteen measured; base letters first, case ignored, then the accents
left to right; the expansions `ß`, `æ`, `œ`, `ĳ`, `ǆ`. The first build was wrong on letters with no decomposition (`ł đ ø ð þ ı ŀ ŉ ſ` sort as letters of their own: most of the 336 differences),
ordered accents by code point (Power BI: acute < grave < dot above < circumflex < diaeresis < caron < breve < macron < tilde < ring < ogonek < cedilla < double acute, measured as a
13 x 13 matrix on ten base letters, identical for all), treated an apostrophe like a letter (it counts for almost nothing), compared two accents on one letter in order (Power BI: as a set)
and took `ſ` for `s`. All of these are refused now, as is `MAX` / `MIN` of two texts that differ only in case. 21,424 fresh comparisons (random words, equivalent spellings, case,
composed against decomposed, ligatures, digits, column and CONCATENATEX / TOPN / MAXX shapes) match.

**Open (older than this task, logged in `HANDOFF.md`; 200 shapes left out of the review batteries):** TOPN with tied sort values (110); `IF` / `IF.EAGER` with a column condition and
branches of different types in an unordered walk (33); plain `IF` with a date in one branch and a number in the other is a number in Power BI (59 of 59 shapes) but a locked `IF` whose other
branch is a Variant stays a date, so the rule was applied to `IF.EAGER` only; a date-typed `IF` / `IF.EAGER` result with a BLANK branch used in arithmetic, or averaged with a NaN (a date in
Power BI, a number here; 57 with the previous family). The error families found with the empty-table probes (1,476 shapes, 120 + 142 wrong answers) became Task 11
(`docs/plans/2026-10-29-gaps-2.md`, specification saved in `tools/parity/dax_battery_gaps2.json` and `tests/fixtures_gaps2_alt.json`, not yet in the replay list).

**Real app (Qt offscreen, nothing on the screen):** 3,600 of the fresh shapes created as measures through `StudioController.create_measure` (Facts imported from an .xlsx) and the shown
value compared with Power BI's answer: 29 of 30 differences are date results the app card prints as a serial number (`DATE(2020,1,1)` alone shows the same), the 30th is the open TOPN-ties
family. Added: batteries `dax_battery_misc3_extra` (6,103 items), `dax_battery_misc3_extra2` (20,909), `tests/fixtures_misc3_alt.json` (6,000 on two other Facts tables), test
`tests/test_iteration98_scalar_misc_3_review.py`; `tests/test_iteration91_xnpv_1.py` and `tests/test_iteration92_scalar_misc_2.py` no longer list as refused what Task 10 answers.
**Gate:** pytest 2,005 passed (6,281 subtests) in 0:38:02; real app 575/575; replay 145,168 answers (140,227 match, 4,941 refused), 0 DIFF, 0 CRASH; locked 115,531 before approval
(`--accept` would lock 140,227).
