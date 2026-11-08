# Task 92 (Iteration 181): the 22 INFO functions Power BI has and the app lacks (info-storage-82)

**Goal:** the local engine knows INFO.ANNOTATIONS, INFO.ATTRIBUTEHIERARCHIES, INFO.ATTRIBUTEHIERARCHYSTORAGES,
INFO.CATALOGS, INFO.COLUMNPARTITIONSTORAGES, INFO.COLUMNSTORAGES, INFO.CSDLMETADATA, INFO.CULTURES,
INFO.DICTIONARYSTORAGES, INFO.FUNCTIONS, INFO.MODEL, INFO.PARTITIONS, INFO.PARTITIONSTORAGES, INFO.PROPERTIES,
INFO.SEGMENTMAPSTORAGES, INFO.SEGMENTSTORAGES, INFO.STORAGEFILES, INFO.STORAGEFOLDERS, INFO.STORAGETABLECOLUMNS,
INFO.STORAGETABLECOLUMNSEGMENTS, INFO.STORAGETABLES, INFO.TABLESTORAGES (names from Power BI's own INFO.FUNCTIONS).

**Spec:** `docs/plans/2026-11-08-info-storage-82-spec.json` — `schemas` (each function's columns in order with
their type, read from Power BI) and `cases` (132 expressions with live Power BI answers). Main: 61 match, 71 refused.
An `ERR:` answer is matched by any `LOCAL-REJECT`. Target: every case matches or is refused; no wrong answer.

**Architecture:** follow the existing INFO plumbing in `analytics_studio/measures.py` (grep `_INFO_EMPTY_TABLE_HEADERS`,
`_INFO_EMPTY_COLUMN_TYPES`, `_INFO_RESTRICTION_FUNCTIONS`, `_INFO_FUNCTIONS`, and the `INFO.TABLES` row builder that
uses `_UnmodelledField`). Copy column names and types from the spec into the code as constants (the code must not
read the spec file). Add every name to `DAX_FUNCTION_NAMES`, `dax_function_catalog.py` and any template/contract
lists the existing INFO functions are in (the catalog-equals-supported tests must pass).

## Measured behaviour
- All 22 take Power BI's restriction-name arguments exactly like the existing `_INFO_RESTRICTION_FUNCTIONS`
  (a number → "The 'INFO.X' function expects a constant string representing a restriction name."; one string →
  the even-number-of-arguments error; unknown name → "'a' is not a valid restriction name."). Reuse that code path.
- **Group A, empty tables** (Power BI returns no rows): INFO.ANNOTATIONS, INFO.CULTURES → add to the empty-table
  schemas: COUNTROWS = BLANK, ISEMPTY true, `TOCSV(FILTER(..,FALSE()),3,",",TRUE)` = the header line.
- **Group B, exactly one row**: INFO.MODEL, INFO.CATALOGS, INFO.CSDLMETADATA → one row whose every field is
  `_UnmodelledField(<column>)` (any read, comparison or text of a value refuses). COUNTROWS = 1, ISEMPTY false,
  FILTER(..,FALSE()) is the empty table with the schema's headers (TOCSV header line, COUNTROWS BLANK).
- **Group C, row count depends on engine storage / static engine metadata**: the other 17. The schema is known,
  but rows cannot be computed: any evaluation of their rows is a refusal (`dax_typed.refusal` / the existing
  "not modelled" refusal). Arity / restriction errors still raise Power BI's messages.

## Review focus
1. Group C must never return a row count or an empty table (Power BI has rows: 26, 30, 60, 470 ...).
2. Group B values must never be readable (no invented IDs, names, versions, XML).
3. Column order and names in TOCSV headers must equal the spec exactly (they come out in the spec order).
4. Restriction-name errors must fire for all 22, including inside COUNTROWS.
5. The catalog / intellisense / contract tests must stay green.

## Part 1 (Haiku)
- [ ] Step 1: test `tests/test_iteration181_info_storage_82.py`: load the spec cases (test only); for each, `ERR:` → local starts with
  `LOCAL-REJECT`; otherwise `tools.dax_oracle_diff.same(power_bi, local)` OR (function in Group C and local is a LOCAL-REJECT).
  Keep the Group C name list explicit in the test. Also assert all 22 names are in `measures.DAX_FUNCTION_NAMES`.
- [ ] Step 2: run it (fails on main).
- [ ] Step 3: implement Groups A, B, C.
- [ ] Step 4: score with `tools.dax_oracle_diff.local` over the spec (no LOCAL-CRASH, no wrong); run the new test, `tests/test_iteration125_info_view_25.py`,
  `tests/test_iteration126_info_empty_26.py`, `tests/test_iteration97_pending_gaps_1.py`, `tests/test_dax_intellisense.py`,
  `tests/test_iteration180_other_functions_81.py` and every test file that greps `DAX_FUNCTION_NAMES` or `dax_function_catalog`.
- [ ] Step 5: commit "Task 92: the 22 missing INFO functions (info-storage-82)".
