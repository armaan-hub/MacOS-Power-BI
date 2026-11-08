# Task 94 (Iteration 183): the 14 visual-calculation functions in measures and queries (visual-calc-names-84)

**Goal:** the local engine knows RUNNINGSUM, MOVINGAVERAGE, FIRST, LAST, NEXT, PREVIOUS, RANGE, LOOKUP,
LOOKUPWITHTOTALS, EXPAND, EXPANDALL, COLLAPSE, COLLAPSEALL and ISATLEVEL, and answers exactly as Power BI does outside a
visual calculation: always an error, with Power BI's message. (Visual calculations themselves, where these functions
return values, are a separate later feature of the report visuals.)

**Spec:** `docs/plans/2026-11-08-visual-calc-names-84-spec.json` (210 live Power BI cases; all errors). Main already
refuses all 210 as "not supported"; the task is recognition with Power BI's exact parse-time messages.

## Measured behaviour (parse time: `IF(FALSE(),…)` and `ISERROR(…)` still fail)
Checks in this order:
1. Argument count, Power BI's wording "Too few arguments were passed to the X function. The minimum argument count for
   the function is N." / "Too many ... The maximum argument count for the function is N.":
   RUNNINGSUM (1,5), MOVINGAVERAGE (2,7), FIRST (1,5), LAST (1,5), NEXT (1,6), PREVIOUS (1,6), RANGE (1,6),
   LOOKUP (1, unbounded), LOOKUPWITHTOTALS (1, unbounded), EXPAND (1, unbounded), EXPANDALL (1,2), COLLAPSE (1, unbounded),
   COLLAPSEALL (1,2), ISATLEVEL (1,1).
2. LOOKUPWITHTOTALS with 2 or more arguments whose argument 2 is not a column reference →
   "Function LOOKUPWITHTOTALS expects a column reference as argument number 2."
3. Otherwise → "X can only be used in the expression of a visual calculation."
Bare keywords such as ROWS / COLUMNS in these arguments must not crash the parser (a refusal or the message above is fine).

## Part 1 (Haiku)
- [ ] Step 1: test `tests/test_iteration183_visual_calc_names_84.py`: all 210 spec cases (spec read in the test only) give a
  `LOCAL-REJECT` whose message equals Power BI's message without the `Query (1, N) ` prefix; assert the 14 names are in
  `measures.DAX_FUNCTION_NAMES`.
- [ ] Step 2: run it (fails on main).
- [ ] Step 3: new module `analytics_studio/dax_visual_calc_fns.py` (NAMES, ARITY, `check_syntax`), wired like
  `dax_sampling_fns` (grep it in `measures.py`); register the names in `DAX_FUNCTION_NAMES`, `dax_function_catalog.py`,
  `measure_dialog.py` templates; regenerate `DAX_COMPATIBILITY_CONTRACT.md` with `tools/sync_dax_contract.py` if required.
  Note FIRST, LAST, NEXT, PREVIOUS, RANGE may collide with existing identifiers or keywords — make sure existing uses
  (e.g. `ORDER BY ... ASC`, `NEXT` in other contexts, columns named First/Last) keep working: run the broad DAX tests.
- [ ] Step 4: run the new test, `tests/test_iteration180_other_functions_81.py`, `tests/test_iteration181_info_storage_82.py`,
  `tests/test_iteration182_week_functions_83.py`, `tests/test_dax_intellisense.py`, every test that greps `DAX_FUNCTION_NAMES`,
  `dax_function_catalog` or `dax_contract`, and every `tests/test_*dax*.py` and `tests/test_measure*.py` — all pass.
- [ ] Step 5: leave the change uncommitted and report (Opus commits).
