# Task 58: the 10 missing DAX functions (missing-functions-48)

**Goal:** the engine knows APPROXIMATEDISTINCTCOUNT, CALENDARAUTO, DATESWTD, TOTALWTD, DETAILROWS, PATH,
SELECTEDMEASURE, SELECTEDMEASURENAME, ISSELECTEDMEASURE, USEROBJECTID. Each one answers like Power BI where we
have measured Power BI, computes the documented result where the app's model supports it, and refuses
(dax_typed.refusal) otherwise. Never a wrong answer.

**Live Power BI answers (2026-11-05, guest model: one table Facts, no DateTime column, no measures, import mode):**
- CALENDARAUTO(), CALENDARAUTO(3), CALENDARAUTO(13), CALENDARAUTO(0), CALENDARAUTO(Facts[Quantity]) ->
  error "CALENDARAUTO function can not find a base column of DateTime type in the model."
- APPROXIMATEDISTINCTCOUNT(Facts[<any>]) -> error "The function APPROXIMATEDISTINCTCOUNT isn't supported for this storage mode."
- USEROBJECTID() -> "S-1-5-18" (the Windows SID of the process user; USERNAME() there is "NT AUTHORITY\SYSTEM").
- SELECTEDMEASURE() -> error "There is no measure reference in the current context to be applied as SELECTEDMEASURE."
- SELECTEDMEASURENAME(), ISBLANK(SELECTEDMEASURENAME()) -> error "There is no measure reference in the current context that can be used by SELECTEDMEASURENAME."
- ISSELECTEDMEASURE(1) -> error "Invalid input arguments for ISSELECTEDMEASURE."
- PATH(Facts[Quantity],Facts[Quantity]) -> error "The columns specified in the PATH function must be from the same table, have the same data type and that type must be Integer or Text."
- PATH(1,BLANK()) -> error "Function Path expects a column reference as argument number 1."
- PATH([id],[p]) inside ADDCOLUMNS(DATATABLE(...)) -> error "[id] is not a valid reference to a column in a table."
- DATESWTD(<anything not a calendar>) -> error "DATESWTD's parameter 1 must be a calendar reference."
- TOTALWTD(expr, <not a calendar>) -> error "TOTALWTD's parameter 2 must be a calendar reference."
- DETAILROWS(1), DETAILROWS(SUM(...)) -> error "The input parameter for the DETAILROWS function is not a valid measure reference."

**Parts (each: code in analytics_studio/measures.py or a small new module dax_model_fns.py; tests in
tests/test_iteration148_missing_functions_48.py):**
- A. Register all 10 names (arity) so they appear in DAX_FUNCTION_NAMES; parse-time/eval errors with the messages above.
- B. CALENDARAUTO([fiscal_year_end_month]): no DateTime/Date column in the model -> the measured error.
  Otherwise reuse analytics_studio/calendar_tables.generate_calendar_auto (same rules as the existing dialog):
  one column [Date], whole fiscal years covering every non-blank date in the model's imported date columns.
  Argument outside 1..12 -> refuse. (Date-model results are documented, not yet measured: mark in the test.)
- C. APPROXIMATEDISTINCTCOUNT(col): the app is import-only, so always the storage-mode error.
- D. USEROBJECTID(): Windows -> the current user's SID string; other OS -> refuse (environment value, like USERNAME; not in the battery).
- E. SELECTEDMEASURE/SELECTEDMEASURENAME/ISSELECTEDMEASURE: the app has no calculation groups, so outside a
  calculation item always the measured errors; ISSELECTEDMEASURE with a measure reference -> refuse (unmeasured).
- F. PATH(id_col, parent_col): argument checks with the measured errors; with two base columns of one model table,
  same type Integer or Text: documented parent-child path "a|b|c" from the root to the current row (row context
  required); a missing parent, a loop, or other unmeasured case -> refuse.
- G. DATESWTD / TOTALWTD: the app has no calendar references -> always the measured errors.
- H. DETAILROWS: argument not a measure reference -> measured error; a measure reference -> refuse (no detail-rows definitions in the app).

**Done when:** every Power BI answer above matches (errors match errors), dax_intellisense shows all 10 as supported,
full pytest + replay pass with 0 DIFF/0 CRASH, no app code reads tools/parity or fixtures.
**Open (needs a model change on the guest; ask the user later):** measure CALENDARAUTO/PATH with a date table and a parent-child table.

## Review outcome (2026-11-05)
Shipped as Iteration 147. Locked 482193.
