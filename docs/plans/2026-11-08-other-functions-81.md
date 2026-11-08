# Task 91 (Iteration 180): five DAX functions Power BI has and the app lacks (other-functions-81)

**Goal:** the local engine knows EXTERNALMEASURE, NATURALJOINUSAGE, SAMPLEAXISWITHLOCALMINMAX,
SAMPLECARTESIANPOINTSBYCOVER and SELECTEDMEASUREFORMATSTRING: it answers what Power BI answers and refuses the rest,
never a wrong value.

**Spec (Power BI answers, live guest 2026-11-08, model `Facts` of `tools/dax_oracle_diff.py`):**
`docs/plans/2026-11-08-other-functions-81-spec.json` (66 cases). Main today: 40 match (Power BI errors, main refuses),
26 refused where Power BI answers. Target: all 66 match. An `ERR:` answer is matched by any `LOCAL-REJECT`; prefer
Power BI's exact message text (given in the spec) where the plan says so.

**Architecture:** a new module `analytics_studio/dax_sampling_fns.py` in the style of `dax_model_fns.py` (names, arity,
parse-time `check_syntax`, evaluation helpers), wired into `measures.py` where `dax_model_fns` is wired
(`_FUNCTIONS`, `_TABLE_FUNCTION_ARITY`, the parse-time check near line 6214, table-function evaluation near line 12415
where SAMPLE is evaluated). Add the five names to `DAX_FUNCTION_NAMES` and to `dax_function_catalog.py`
(one line each, same format) so the catalog-equals-supported tests still pass.

## Global constraints
- App code must compute; never read `tools/parity/*.json`, fixtures, the spec file, plan files or the scratchpad.
- No expression-keyed or name-keyed answer whitelists. Do not edit saved Power BI answers or existing tests.
- Do not run `--freeze` / `--accept`, do not commit or merge outside the worktree branch.

## Measured behaviour (from the spec)

1. **SELECTEDMEASUREFORMATSTRING** — arity (0, 0) (`Too many arguments ... maximum argument count for the function is 0`).
   No calculation groups exist locally, so evaluating it is always the runtime error
   `SELECTEDMEASUREFORMATSTRING misused. There is no measure reference in the current context.`
   It is a **runtime** error, not parse-time: `IF(FALSE(),SELECTEDMEASUREFORMATSTRING(),1)` = `1`.
2. **EXTERNALMEASURE** — arity (1, 3). Any call with 1–3 arguments fails at **parse time** with
   `Failed to resolve name 'EXTERNALMEASURE'. It is not a valid table, variable, or function name.`
   (`IF(FALSE(),EXTERNALMEASURE("m"),1)` is an error).
3. **NATURALJOINUSAGE** — arity (1, 1). Every call with one argument fails at **parse time** with
   `'NATURALJOINUSAGE' function can only be used as a value filter of SUMMARIZECOLUMNS.`
   (also inside CALCULATE, COUNTROWS, SUMMARIZECOLUMNS filter position, and an `IF(FALSE(),…)` branch).
4. **SAMPLEAXISWITHLOCALMINMAX** — minimum 5 arguments (`Too few arguments ... minimum argument count for the function is 5`).
   No successful call was measured: every call is refused (`dax_typed.refusal`). Use the measured message where the
   shape matches the spec; otherwise a refusal.
5. **SAMPLECARTESIANPOINTSBYCOVER(MaxPoints, Table, X, Y [, Radius, MaxMinRatio, MaxBlankRatio])** — arity (4, 7), a
   table function returning the rows of `Table` (all its columns, its row order).
   - Argument 1 converts to Integer (`"6"`, `6.0`, `5+1` all work; `"a"` → `Cannot convert value 'a' of type Text to type Integer.`).
     A non-integral number is refused (rounding not measured). Zero, negative or BLANK →
     `The SampleCartesianPointsByCover function expects a positive numeric parameter value to be specified for argument 1.`
   - Arguments 3 and 4 must be numeric scalar expressions (constants allowed); a text column → `The SampleCartesianPointsByCover function requires coordinate parameter (at argument number 3) to be a numeric scalar expression.` (4 for argument 4).
   - With 5 arguments: `... expects MaxMinRatio as argument 6, since you specified a radius column.`
     With 6: `... expects MaxBlankRatio as argument 7, since you specified a radius column.`
   - Table argument evaluated in the current filter context (CALCULATETABLE(…, Region="East") gives 3 rows; FILTER and
     VALUES / ALL tables work). An empty table gives an empty table (COUNTROWS → BLANK).
   - **If MaxPoints ≥ the row count of the table, the result is the table unchanged.** If MaxPoints < the row count,
     Power BI drops rows by an unmeasured rule → refuse (`dax_typed.refusal`), even for COUNTROWS.

## Review focus
1. A runtime error (SELECTEDMEASUREFORMATSTRING) must not fire inside an untaken IF branch; the parse-time errors (EXTERNALMEASURE, NATURALJOINUSAGE) must.
2. SAMPLECARTESIANPOINTSBYCOVER over a filtered or row-context table must count rows in the current context, not the base table.
3. MaxPoints given as text `"6"` must convert; `"a"` must error, not crash.
4. Never return a sampled subset: MaxPoints < rows is a refusal, also through SUMX/CONCATENATEX/COUNTROWS.
5. The editor catalog and `DAX_FUNCTION_NAMES` must stay equal (existing tests).

## Part 1 (Haiku): module, wiring, catalog
**Files:** create `analytics_studio/dax_sampling_fns.py`; modify `analytics_studio/measures.py`, `analytics_studio/dax_function_catalog.py`;
test `tests/test_iteration180_other_functions_81.py`.

- [ ] Step 1: write `tests/test_iteration180_other_functions_81.py`: load the 66 spec cases from the spec JSON **in the test only**,
  run each through `tools.dax_oracle_diff.local`, and assert: `ERR:` → the local answer starts with `LOCAL-REJECT`; otherwise
  `tools.dax_oracle_diff.same(power_bi, local)`. Also assert the five names are in `measures.DAX_FUNCTION_NAMES`.
- [ ] Step 2: run it, expect 26 failures on main.
- [ ] Step 3: implement the module and wiring per "Measured behaviour".
- [ ] Step 4: run the new test (66 pass), then `tests/test_dax_function_catalog*.py tests/test_dax_intellisense*.py tests/test_iteration148*.py`
  and the 4 newest `tests/test_iteration17*.py` files, all pass. Use `-p no:cacheprovider`.
- [ ] Step 5: commit on branch `antigravity/other-functions-81`: "Task 91: EXTERNALMEASURE, NATURALJOINUSAGE, SAMPLEAXISWITHLOCALMINMAX, SAMPLECARTESIANPOINTSBYCOVER, SELECTEDMEASUREFORMATSTRING (other-functions-81)".

## Review outcome (2026-11-05)
Shipped as Iteration 180. Locked 531486.
