# Task 93 (Iteration 182): the six week time-intelligence functions (week-functions-83)

**Goal:** the local engine knows STARTOFWEEK, ENDOFWEEK, NEXTWEEK, PREVIOUSWEEK, OPENINGBALANCEWEEK and
CLOSINGBALANCEWEEK and answers exactly as Power BI does in a model without calendar objects.

**Spec:** `docs/plans/2026-11-08-week-functions-83-spec.json` (72 live Power BI cases; every answer is an error because
the guest's compatibility level has no calendars — INFO.CALENDARS is "unavailable", like the app's
`_INFO_UNAVAILABLE_FUNCTIONS`). Main already refuses all 72 (as "not supported"); the task is recognition with
Power BI's exact parse-time messages, the same pattern as DATESWTD / TOTALWTD in `analytics_studio/dax_model_fns.py`.

## Measured behaviour (all at parse time: `IF(FALSE(),…)` and `ISERROR(…)` still fail)
- STARTOFWEEK, ENDOFWEEK, NEXTWEEK, PREVIOUSWEEK: arity (1, 1) with Power BI's "Too few/Too many arguments were passed to
  the X function. The minimum/maximum argument count for the function is 1." messages; any one argument →
  `X's parameter 1 must be a calendar reference.`
- OPENINGBALANCEWEEK, CLOSINGBALANCEWEEK: arity (2, 3) with the same count messages (minimum 2, maximum 3); any 2 or 3
  arguments → `The last argument must be one of these keywords: DAY, MONTH, QUARTER, or YEAR.`

## Part 1 (Haiku)
- [ ] Step 1: test `tests/test_iteration182_week_functions_83.py`: for all 72 spec cases (spec read in the test only) the local
  answer starts with `LOCAL-REJECT` and its message equals the Power BI message after `Query (1, N) ` (strip that prefix
  and the trailing `.`-insensitive quotes); assert the six names are in `measures.DAX_FUNCTION_NAMES`.
- [ ] Step 2: run it (fails on main).
- [ ] Step 3: add the six names to `dax_model_fns.py` (NAMES, ARITY, `check_syntax` branches, constants for the messages;
  the arity messages are Power BI's exact wording above, not the module's current generic refusal), register them in
  `DAX_FUNCTION_NAMES`, `dax_function_catalog.py`, `measure_dialog.py` templates and regenerate
  `DAX_COMPATIBILITY_CONTRACT.md` with `tools/sync_dax_contract.py` if required. App code never reads the spec.
- [ ] Step 4: run the new test, `tests/test_iteration148_missing_functions_48.py`, `tests/test_dax_intellisense.py`,
  `tests/test_iteration180_other_functions_81.py`, `tests/test_iteration181_info_storage_82.py` and every test that greps
  `DAX_FUNCTION_NAMES`, `dax_function_catalog` or `dax_contract` — all pass.
- [ ] Step 5: commit "Task 93: the six week time-intelligence functions (week-functions-83)".

## Review outcome (2026-11-05)
Shipped as Iteration 182. Locked 531486.
