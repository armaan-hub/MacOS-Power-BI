# Task 34 colstats-utc-24: new DAX functions COLUMNSTATISTICS, UTCNOW and UTCTODAY (114 measured answers)

**Coder:** Antigravity. **Work folder:** git worktree `/Users/armaan/Power BI tool-task34` (branch `antigravity/colstats-utc-24`). Work ONLY there.
**Spec:** `tools/parity/task34_colstats_utc_spec.json`: 114 answers measured live in Power BI Desktop on 2026-11-03 against the standard probe model (table `Facts`: Sales, Quantity, Region, Note; 6 rows). Score with `PYTHONPATH=. python3 tools/score_spec.py tools/parity/task34_colstats_utc_spec.json` (prints counts per Part and "N wrong").

- **Part A (62, 58 refused today): `COLUMNSTATISTICS()`.** A table with one row per column of every model table, columns `[Table Name]`, `[Column Name]`, `[Min]`, `[Max]`, `[Cardinality]`, `[Max Length]`. Measured facts:
  - Rows come in model order and include Power BI's hidden row-number column, named exactly `RowNumber-2662979B-1795-4F74-8F37-6A1BA8059B61` (a fixed name, the same in every model), placed first for each table. Its Min, Max and Max Length are blank; its Cardinality is the row count.
  - Facts: `RowNumber…|Sales|Quantity|Region|Note`; Min `|-1.5|0|East|Late`; Max `|20|5|West|Paid`; Cardinality `6|6|6|3|3`; Max Length `|||5|4`.
  - Cardinality counts distinct values including blank (Sales has a blank and 5 numbers = 6; Note has Paid, Late and blank = 3). Min and Max ignore blanks. Min/Max keep the column's type: a number for numeric columns, text for text columns. Max Length is the longest text length for text columns and blank for others.
  - `COLUMNSTATISTICS()` with any argument: "Too many arguments were passed to the COLUMNSTATISTICS function. The maximum argument count for the function is 0."
  - Under a filter (`CALCULATE(COUNTROWS(COLUMNSTATISTICS()),Facts[Region]="East")`): error "COLUMNSTATISTICS() cannot be used with a filter context." Statistics are always over the whole column, never the current filter.
  - As a scalar (`COLUMNSTATISTICS()` alone): "The expression refers to multiple columns. Multiple columns cannot be converted to a scalar value."
- **Part B (30, 27 refused today): `UTCNOW()` and `UTCTODAY()`.** Like NOW()/TODAY() but in UTC: UTCNOW is a datetime, UTCTODAY is the UTC date at midnight. Any argument errors ("Too many arguments were passed to the UTCNOW function. The maximum argument count for the function is 0.", same for UTCTODAY). Use the host's real UTC clock; the spec only uses expressions whose answers do not depend on the time of day (e.g. `HOUR(UTCTODAY())` is 0, `INT(UTCNOW())=UTCTODAY()` is True).
- **Part C (22, all already match): PATH errors.** Guards only: PATH needs two model columns of the same table and the same Integer/Text type, and every parent value must exist in the id column. Do not change PATH; these rows must keep matching.

## Rules
Compute, never look up (app code must never read `tools/parity/*.json` or test fixtures; `tests/test_no_answer_key_in_app.py` must pass). 0 wrong is mandatory; refuse what the rows do not settle (e.g. models with several tables, date or Boolean columns: refuse unless you are sure). Register the new functions wherever existing functions are registered (function lists, static types, the measure dialog templates) so the DAX contract count updates; run `PYTHONPATH=. python3 tools/sync_dax_contract.py` if the contract test asks for it. Never edit saved Power BI answers or existing tests; new tests go in `tests/test_iteration124_colstats_utc_24.py`. No `--freeze`, `--accept`, commit, merge, push or full pytest. Do not touch other folders.

## Done when
The scorer prints 0 wrong with as many matches as possible, `tools/parity_check.py` replay shows 0 DIFF and 0 CRASH, and a ready-for-review entry with scorer counts per Part and the replay line is in this worktree's `HANDOFF.md`. Leave changes uncommitted.
