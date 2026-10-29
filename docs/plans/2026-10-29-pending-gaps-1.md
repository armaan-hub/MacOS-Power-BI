# Task 9: pending-gaps-1 (VAR scoping in operators and filters; scalar subqueries in CALCULATE filters)

Created by Claude 2026-10-29. Built by Antigravity, reviewed by Claude. Read `AGENTS.md` ("Compute, never look up"), `HANDOFF.md`, and the "Part A/B/C review outcome" sections of `docs/plans/2026-10-26-table-fns-2.md` first.

Source of the work: `PARITY_LEDGER.md`, section "Pending work": the app refuses these expressions, Power BI answers a value. Their saved answers are in `tools/parity/<battery>.json`; find an item with `grep -n "<text>" PARITY_LEDGER.md`. Do not edit the saved answers; do not read them at run time.

## Part A: VAR inside operators, iterators and CALCULATE filters (20 items, battery `dax_battery_var_scoping`)
Shapes: a `VAR ... RETURN` as the right side of a comparison or `&` (`1>VAR y=2 RETURN y`, `"a"&VAR y="b" RETURN y`); a table VAR read by DISTINCT, SUMX, FILTER, or by another VAR (`VAR t=Facts RETURN SUMX(t,Facts[Quantity])`); a VAR inside a CALCULATE filter argument (`CALCULATE(COUNTROWS(Facts),VAR t = 2 RETURN Facts[Quantity]>t)`, nested VARs, a VAR holding a column `Facts[Quantity]` used as `t>2`, `t IN {1,2}`, `ISBLANK(t)`), and the same inside CALCULATETABLE.
The scoping rules are the ones of Task 2 (`docs/plans/2026-10-26-var-scoping-1.md`, already locked). A VAR that holds a column reference in a filter keeps the column's lineage: `VAR t = Facts[Quantity] RETURN t>t` is BLANK, `RETURN t` alone is 5 (look at the saved answers to see what Power BI does, then find the rule; do not special-case the text).

## Part B: scalar subqueries in a CALCULATE / CALCULATETABLE filter (29 items, batteries `dax_battery_sdet_filters` 5, `dax_battery_round2` 16, `dax_battery_round3` 8)
`CALCULATE(COUNTROWS(Facts), Facts[Quantity] > COUNTROWS(<table expression>))` and similar: the right side of the comparison is a scalar computed from a table function (VALUES, ALL, DISTINCT, CALCULATETABLE, UNION, CROSSJOIN, GENERATESERIES, DATATABLE, CALENDAR, SUBSTITUTEWITHINDEX, INFO.TABLES, ...), an IF, a VAR, FIRSTNONBLANKVALUE or CONCATENATEX. Part A, B, C of Task 8 now evaluate several of these table functions; where the saved answer is a Power BI error or the rule cannot be derived, leave the item refused and say so. `INFO.TABLES()` and the RANKX/INDEX items (`dax_battery_round2` INDEX, `dax_battery_round4` RANKX) are optional: skip them if the rule is not clear.

## Rules (same as before)
1. Tests first. Compute every answer from DAX semantics; `tests/test_no_answer_key_in_app.py` must stay green.
2. Group and join on lineage, not display names. Check ordering on data whose groups are not alphabetical (Task 8 lesson: matching the saved items can be luck). If an order or a rule is not derivable, refuse with `MeasureError`; refusing is better than a wrong answer.
3. Branch `antigravity/pending-gaps-1` from `main` (after the user has approved the Task 8 Part C merge). No `--freeze`, `--accept`, commit, merge; no Power BI VM; no global `str.replace` on `measures.py`.
4. Finish with `PYTHONPATH=. python tools/parity_check.py --tests`, write what you did and refused in `HANDOFF.md`, set Task 9 READY FOR REVIEW and "Active agent: Claude".

## Later (not in Task 9)
Text collation (`"é"<"e"`, `ISAFTER("é","e")`, `"æ"="ae"`, MAX/MIN of accented text; about 20 items in `dax_battery_scalar_misc2_extra*`), `ALLCROSSFILTERED` combinations (about 30 items), `EVALUATEANDLOG` / `TABLEOF` / `CUSTOMDATA` / `IF.EAGER` leftovers, XNPV extreme values and dates beyond 12/31/9999 (`dax_battery_xnpv2`, 37 items), and the deliberate LINEST / SUBSTITUTEWITHINDEX refusals (about 2,000 items, rules not derivable).
