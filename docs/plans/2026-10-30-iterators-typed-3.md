# Task 13: iterators-typed-3 (Variant Infinity / NaN, BLANK and one-column bodies, strict comparison, VAR in filters)

**Branch:** `antigravity/iterators-typed-3`  **Written by:** Claude, 2026-10-30  **Status:** see `HANDOFF.md`
**Start condition:** Task 12 (`variant-iterators-2`) is DONE (reviewed, locked, merged) and `HANDOFF.md` says Active agent: Antigravity. Branch from `main`.

Read first: `AGENTS.md` ("Compute, never look up"), `HANDOFF.md` (open items), and the "Review outcome" of `docs/plans/2026-10-30-variant-iterators-2.md`.
That review is the reason for Rules 3 and 4 below: the Task 12 build matched 1,160 of its 1,161 saved items, and fresh Power BI probes then found 269 distinct wrong answers, nearly all shapes that `main` had honestly refused.

## Goal
Power BI answers a value, the app refuses ("pending"). All items have Power BI's answer saved in `tools/parity/task13_typed3_spec.json` (fields `part`, `battery`, `expr`, `powerbi`, `app_refusal`).
1,180 items. Every item is in a replayed battery, so no `--freeze` is needed. No new function is added. The spec file is a copy for reading; it is **not** a replay battery and must not be read at run time.

## Part A: Variant bodies with Infinity, NaN or a constant True/False
- **A1 (207 items).** `SUMX(Facts,IF.EAGER(Facts[Quantity]>2,"5",0/0))` is NaN, `AVERAGEX(Facts,IF.EAGER(Facts[Quantity]>2,"5",-1/0))` is -Infinity, `COUNTX(Facts,IF(Facts[Quantity]>2,1/0,UPPER(Facts[Region])))` is 3, `COUNTAX(Facts,IF(Facts[Quantity]>2,Facts[Quantity]/0,"5"))` is 6. The app refuses "over a Variant that returns Infinity or NaN". Model them with plain double arithmetic where the saved answers allow it, and keep MAXX / MINX as they are: there NaN beside other numbers depends on the walk.
- **A2 (91 items).** `COUNTX(Facts,IF(TRUE(),TRUE(),Facts[Note]))` is 6, `COUNTX(Facts,IF.EAGER(TRUE(),TRUE(),1/0))` is BLANK, while a row-dependent condition counts 3. Compare with the Task 12 reduction of a constant IF (`iterator_body_as_scanned`) before writing a new rule.

## Part B: bodies the app does not accept
- **B1 (201 items).** `BLANK()` as the body of PRODUCTX, MEDIANX, VARX.P, AVERAGEX, PERCENTILEX.INC: `MEDIANX(FILTER(Facts,FALSE()),BLANK())` is BLANK, `MEDIANX(CALCULATETABLE(Facts,Facts[Region]="East"),BLANK())` is BLANK.
- **B2 (235 items).** A one-column table where one value is wanted: `MAXX(EXCEPT(Facts,Facts),VALUES(Facts[Region]))` is BLANK, `COUNTROWS(ADDCOLUMNS(CALCULATETABLE(Facts,Facts[Region]="East"),"q",VALUES(Facts[Region])))` is 3. It is a value when one row is left and BLANK when none is; several rows are an error, as an unknown column is, and over an empty table Task 11's placeholder row applies.

## Part C: typing
- **C1 (79 items).** `==` between Variants: `IF(FALSE(),1,"a")==IF(TRUE(),1,TRUE())` is False. Task 12 gave `=`, `<>`, `<`, `>`, `<=`, `>=` a Variant ordering in `dax_typed.compare`; `==` does not have it yet.
- **C2 (32 items).** A date beside a number in a Variant, compared or returned: `IF(TRUE(),DATE(2020,1,1),1)>IF(1=1,5,"x")` is True, `IF(TRUE(),TIME(6,0,0)+TRUE(),1)` is 1.25.
- **C3 (61 items).** A text or date condition in an iterator body: `MAXX(Facts,IF("TRUE",LEFT("a",1),Facts[Region]))` is a, `MAXX(Facts,IF(DATE(2020,1,1),1=1,Facts[Region]))` is BLANK.
- **C4 (66 items).** FIRSTNONBLANK and its relatives in iterator and filter bodies: `MAXX(Facts,FIRSTNONBLANK(Facts[Region],1))` is West, `COUNTROWS(FILTER(VALUES(Facts[Note]),FIRSTNONBLANK(Facts[Region],1)="West"))` is BLANK. Task 12 made them errors in SUMX and the numeric iterators; these are the places they are accepted.
- **C5 (80 items).** PRODUCTX / MEDIANX of a constant IF over a text column: `PRODUCTX(Facts,IF.EAGER(1=1,Facts[Region],2.5))` is BLANK.

## Part D: filters
- **D1 (58 items).** A VAR block computing the filter value: `CALCULATE(COUNTROWS(Facts),VAR t = IF(TRUE(),2,3) RETURN Facts[Quantity]>t)` is 3, `COUNTROWS(CALCULATETABLE(Facts,VAR t = 2 VAR u = t+1 RETURN Facts[Quantity]>u))` is 2.
- **D2 (70 items).** KEEPFILTERS around a table or inside EVALUATEANDLOG: `COUNTROWS(ADDCOLUMNS(KEEPFILTERS(CALCULATETABLE(Facts,Facts[Region]="Nowhere")),"q",TRUE()))` is BLANK, `CALCULATE(SUM(Facts[Quantity]),EVALUATEANDLOG(EVALUATEANDLOG(KEEPFILTERS(Facts[Region]="East"))))` is 8.

## Rules
1. Tests first (`tests/test_iteration101_iterators_typed_3.py`). Compute every answer from DAX semantics, never from the saved answers or the spec file.
2. Check each new rule on the standard Facts table **and** on tables A and B of `tests/fixtures_misc3_alt.json`, and on all three tables of `tests/fixtures_variant2_review_alt.json` (`tests/test_iteration100_variant_iterators_2_review.py` shows how to load them).
3. **Do not turn a refusal into a value unless you know the rule for every shape it now lets through.** Removing a refusal changes shapes outside the spec. For each refusal you remove or narrow, write down in `HANDOFF.md` which shapes it still covers and why the others are now right. If a rule only holds for some shapes, keep the refusal for the rest.
4. Keep rows, scans and walks in mind. A result that depends on the order the engine walks the rows, or on which columns the body reads, cannot be derived here: refuse it. Task 12 examples: NaN beside other numbers in a Variant MAXX, and `CONCATENATEX` over a constant IF on anything but the plain table. Compare any such rule across all the alternate tables before trusting it.
5. Do not widen a refusal to cover a problem without running the replay: it is quick (`PYTHONPATH=. python tools/parity_check.py`, about 2 minutes, no pytest) and a refusal on a locked item is a regression. Run it after every rule.
6. Every saved value in the spec must match or be refused with a true reason; nothing may become `DIFF` or `CRASH`; no locked item may change.
7. Branch `antigravity/iterators-typed-3` from `main`. No `--freeze`, `--accept`, commit, merge; no Power BI VM; no global `str.replace` on `measures.py`; no edits to existing tests (list them in `HANDOFF.md` for Claude).
8. Finish with `PYTHONPATH=. python tools/parity_check.py --tests`, write what you did and refused in `HANDOFF.md`, set Task 13 READY FOR REVIEW and "Active agent: Claude".

## Not in Task 13 (parked, reasons in `HANDOFF.md`)
Non-ASCII collation and composed / decomposed text (1,657), engine row orders (921), LINEST rank-deficient or perfect fits (697), SUBSTITUTEWITHINDEX (263), the empty text on the right of `&&` / `||` (310: displays BLANK yet ISBLANK is False), `date*BLANK()` inside arithmetic, `SELECTCOLUMNS` column lineage, CONCATENATEX walk order of `||` / `&&` bodies, the fold of a constant IF over scans not yet measured.

## Review outcome (Claude, 2026-10-31)
The build matched 1,155 of 1,180 spec items and fresh Power BI probes found 556 of 17,632 answers wrong. Causes: rules keyed to how an expression looks (a body that calls DATE, a literal argument), refusals removed without knowing what they let through, and one failing test missing from the report.
Rules that hold now, measured on four Facts tables: a date beside any number is a number whichever branch runs; beside text or True/False it is a Variant and stays a date; two dates in MIN / MAX stay a date; a date-typed BLANK counts as day zero in + and -. Stored scans (`Facts`, `ALL(Facts)`, `VALUES(Facts)`, FILTER of those) and row sets (DISTINCT, SUMMARIZE, TOPN, ADDCOLUMNS, UNION ...) treat NaN differently in COUNTX, COUNTAX, AVERAGEX, MAXX and MINX. The sum of dates is a date; their average or variance is a number; PRODUCTX, MEDIANX, GEOMEANX and PERCENTILEX of a date fail at compile time even in a branch not taken. Every branch is compiled, so a wrong branch fails whether it runs or not.
Lesson for the reviewer: the first fresh probes missed date-valued iterators and date sets as branches. The older critic tests caught them. When a rule says "a branch that cannot be typed stays as it is", list what cannot be typed.
Result: spec 1,153 match, 27 refused, 0 wrong; about 127,000 fresh answers, 13 differ (5 expressions, Part E of Task 14).
