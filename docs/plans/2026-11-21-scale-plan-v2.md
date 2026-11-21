# Speed and scale plan, version 2 (final)

Written by Fable 5.2 on 2026-11-21. Status: APPROVED by Armaan on 2026-11-21 ("everything is approved"); this version 2 is the result of the third, deeper investigation he asked for after approving. It replaces `SCALE_PLAN_v1.md` (kept for history) and replaces Phase 2 of `TEAM_PLAN.md`.
Nothing in `/Users/armaan/Power BI tool` was changed. All numbers were measured on Armaan's Mac (Apple M5 Pro, 18 cores, 48 GB, Python 3.14.4) unless marked "guess" or "unchecked".

Scripts (all in `/Users/armaan/pbi_scratch/fable/`): `speed_probe.py`, `profile_probe.py`, `import_probe.py`, `engine_compare.py`, `parity_risk_probe.py`, `scale_risk_probe.py`, `import_engine_probe.py`, `quickwin_timing.py`. Folder `proto/` holds a private patched copy of the engine used for one timing test; it is not project code.

## 1. Answer in 8 lines
1. Today the app refuses any file over 10 MB or 100,000 rows. Data is held as Python text, 607 bytes per row.
2. Python is right for the window, the model and the DAX rules. Python is wrong for touching every row.
3. Tuning the Python engine is not enough. I tested the most promising quick fix on a copy: it gave 1.3 times, not the 2 to 4 times I guessed in version 1. That guess was wrong and is corrected here.
4. A column engine (DuckDB) under the Python engine handles 1,000,000,000 rows on this Mac, and also when limited to 4 GB memory and 4 CPU threads (a small laptop).
5. Answers stay the same when DAX rules are mapped correctly: 15 of 15 mapped test formulas matched our engine under the gate's own comparison rule. Mapped carelessly, 3 of 3 came out wrong. So the mapping rules are the real work.
6. The Power Query engine is also row by row (about 40 microseconds per row per step). It needs the same treatment or import stays slow.
7. The old engine stays as the reference. The fast path must equal it on every formula or it is not used. This check needs no Power BI and no virtual machine.
8. Honest limit: a formula that runs CALCULATE once for each row of a billion-row table is slow in Power BI too. The target is that the tool never freezes, never crashes, and answers the common shapes in seconds.

## 2. Evidence

### 2.1 Where the time goes today
| Finding | Evidence |
|---|---|
| Import limits: 10 MB, 100,000 rows, 500,000 cells | `analytics_studio/file_import.py` lines 36 to 45; a 150,000-row CSV is refused |
| Power Query result cap 100,000 rows | `analytics_studio/m_engine/table_fns.py` line 29 |
| 607 bytes per row, all cells text; 100,000 rows import in 2.8 s | `import_probe.py` |
| Numbers re-parsed from text on every run | `measures.py` line 16563 `numeric_values` |
| Iterators: about 30 to 40 microseconds per row | `SUMX(Facts, Sales*Quantity)` 100,000 rows: 4.2 s (`quickwin_timing.py`; 6.7 s in an earlier run under other load) |
| Type lookup repeated 13 times per row | `profile_probe.py`: `row_columns`, `static_scope`, `_static_numeric_type` |
| Caching that lookup gives only 1.3 times | Patched copy: 3.0 s against 4.2 s; `AVERAGEX` 1.95 s against 2.46 s; same answers |
| CALCULATE inside an iterator is quadratic | `transition_filters`, `measures.py` line 19856: 300 rows 3.2 s, 2,000 rows 20.6 s |
| Power Query steps on 100,000 rows: filter 4.9 s, add column 3.4 s, group 4.2 s, join 5.4 s | measured through `m_engine.evaluator.evaluate_to_text` |
| Measures run on the window thread, one core, one full evaluation per visual cell | `controller.py` lines 9053, 14330, 14487 |
| Project file is one JSON document | `project.py` line 1896 |
| Gate takes 36 minutes (41,261 tests, 2,148 s) | `/Users/armaan/pbi_scratch/gate245*.log`; `pytest-xdist` 3.8.0 is installed |
| App code loads fast (import of controller 0.86 s) | measured; start-up is not a problem |

### 2.2 What the column engine does (DuckDB 1.5.5, one file, 1,000,000,000 rows, 5.3 GB on disk)
| Query (DAX meaning) | 16 GB limit, 18 threads | 4 GB limit, 4 threads |
|---|---|---|
| SUM of a column | 0.16 s | 2.2 s |
| Sum by Customer tier (join to a 50,000-row table) | 0.89 s | 4.3 s |
| Join plus filter on one city | 0.16 s | 0.65 s |
| Matrix Year by Tier (two joins) | 1.0 s | 3.9 s |
| Year-to-date by month | 0.39 s | 1.2 s |
| One day filter | 0.13 s | 0.40 s |
| Top 10 customers | 0.87 s | 2.9 s |
| Grid page at row 900,000,000 | 0.03 s | 0.08 s |
| Sort whole table, first 100 rows | 1.1 s | 4.5 s |
| Distinct rows over 4 columns (heavy) | 16.4 s | 49.9 s, no failure |
| Cancel a running query | stops in 1.0 s | stops in 1.1 s |
Peak process memory: 16.1 GB and 5.1 GB.

Import: a 20,000,000-row CSV (1.94 GB, 7 columns, dates as dd/mm/yyyy) loads in 3.6 s into a 0.67 GB store. Our importer would need about 9 minutes for the same rows if the limit were lifted (estimate from 2.8 s per 100,000).

Column sizes for 20,000,000 rows: Region 8 MB, CustomerName (50,000 distinct) 4 MB, Sales 43 MB, a unique text ID 412 MB. One unique text column is 78% of the file. This limit exists in every engine, Power BI included.

Other engines on the same Parquet file: Polars was 2 to 9 times slower than DuckDB on group-by and distinct count and was not tested with data larger than memory. PyArrow alone has no query planner. DuckDB stays the choice.

### 2.3 Do answers stay the same? (`parity_risk_probe.py`, 50,000 rows with blanks and mixed-case text)
- 15 formulas matched our engine when DAX rules were mapped: SUM, SUMX product, AVERAGE, MIN, COUNT, COUNTROWS, DISTINCTCOUNT, CALCULATE with text and number filters, SUMMARIZE row count, DIVIDE, VAR.S, MEDIAN. The comparison used the gate's rule (`tools/dax_oracle_diff.py` `same`, relative difference 1e-9).
- 3 formulas were wrong with plain SQL and right after mapping:
  - Text compare: DAX ignores case; SQL does not.
  - Blank compare: in DAX `Quantity = 0` is also true for BLANK; in SQL it is not.
  - Distinct count: DAX counts BLANK as a value; SQL does not.
- Float sums: a plain floating sum over 1,000,000,000 rows was off by 0.005 on 49,999,162,474.42. DuckDB's exact-sum function `fsum` gave the exact value in 0.57 s. Rule: use `fsum` for decimal-number columns and integer or DECIMAL types for whole and fixed-decimal columns.
- Division by zero inside an iterator: our engine returns `Infinity`, DuckDB returns `inf`. Same meaning, different text; the result converter must handle it.

### 2.4 A possible wrong answer found on the way (not about speed)
With mixed-case text in one column (`East`, `east`, `EAST`), `SUMX(VALUES(Facts[Region]), CALCULATE(SUM(Facts[Sales])))` returns 2 for 4 rows of value 1; rows with the other spellings are lost. `VALUES` treats the spellings as one value but the row filter matches exact text. Real Power BI stores one spelling per value at load, so its answer would be 4 (unchecked against Power BI). Real data often has mixed case. This becomes task B5.

### 2.5 How Power BI handles data (from public articles, unchecked against Microsoft documentation)
Column store; number and dictionary encoding; run-length compression; columns cut into segments scanned on all cores; a single-thread formula engine that asks a multi-thread storage engine for small result tables; relationships stored as indexes; for very large data: incremental refresh, aggregation tables, DirectQuery, Direct Lake. This plan copies that design. No open DAX engine that runs without Microsoft Analysis Services was found, so the DAX layer stays ours.

## 3. Design

```
Qt window (Python)            never blocked: all work on background threads, with progress and cancel
   |
DAX formula engine (Python)   the existing rules; decides what to ask the store; finishes on small results
   |            \
   |             old row engine (unchanged): reference for tests, and the path for small tables
table store interface         load, row count, page, filter, group, aggregate, join
   |
DuckDB file beside the project (later: a second implementation that sends queries to a database)
```

Rules of the design:
1. One switch per table: at or below a size threshold (start: 200,000 rows) the old engine runs exactly as today. Every existing test and saved answer keeps passing from the first day.
2. Above the threshold only pushed-down shapes are answered. Any other formula is refused with a message that names the reason. Never a wrong answer, never a freeze.
3. A pushed-down shape is allowed only after it passed the differential test (section 5).
4. The store file is a cache. It can always be rebuilt from the sources by refresh. The project JSON holds the model, steps and measures.
5. Three general techniques, in this order of preference, for any formula part:
   - a. Translate to one store query (aggregates, filters, group-by, joins).
   - b. Distinct-combination evaluation: for a row formula that cannot be translated, ask the store for the distinct combinations of the columns the formula reads, with a row count for each; run the old Python engine once per combination; combine with the counts. This keeps the proven rules and turns a billion rows into the number of distinct combinations. It applies to iterators without context transition; refuse if the number of combinations is above a limit (start: 1,000,000).
   - c. Old row engine on Python rows, only below the threshold.

Type mapping (fixed before any pushdown work):
| Power BI type | Store type | Sum rule |
|---|---|---|
| Whole number | BIGINT | integer sum |
| Decimal number | DOUBLE | `fsum` |
| Fixed decimal | DECIMAL(19,4) | decimal sum |
| Date/time | TIMESTAMP | not summed |
| Text | VARCHAR, one stored spelling per case-insensitive value, plus the engine's fold for compare | not summed |
| True/false | BOOLEAN | |
BLANK is stored as NULL. All BLANK rules stay in the Python engine: each pushed query also returns the counts the engine needs (rows, non-blank rows, unmatched relationship keys).
Every table gets a row-number column so the original order is never lost.

## 4. Stages

Each stage ends with: gate passes, differential test passes, speed table reported. Engine-core tasks are coded by Sonnet and reviewed by a second Sonnet; function-level tasks and tests by Haiku; Opus plans and merges (as in `TEAM_PLAN.md`).

### Stage A: foundations, no change in answers (small; can run next to Phase 0 and Phase 1)
- A1 `tools/perf_check.py`: fixed formula list, sizes 100,000 / 1,000,000 / 10,000,000 / 100,000,000 / 1,000,000,000 rows, prints time and peak memory. Start from the scripts in this folder.
- A2 Gate under 10 minutes: run pytest with `-n` on all cores (xdist is installed); keep one serial run per day as a safety net.
- A3 Differential test tool `tools/engine_diff.py`: runs a list of formulas through two paths on the same data and compares with `same`. First use: old engine against itself on generated data (proves the tool).
- A4 All measure and visual evaluation moves off the window thread, with a busy indicator and a Cancel button. Results that arrive after a newer request are dropped.
- A5 Replace the row scan in `transition_filters` with an index built once per table. Removes the quadratic cost for small tables.
- Exit: window stays responsive during a 10-second measure; `SUMX(Facts, CALCULATE(SUM(Facts[Sales])))` at 100,000 rows under 10 s; gate under 10 minutes.

### Stage B: the store (medium to large)
- B1 Store interface and DuckDB implementation; `duckdb` added to `requirements.txt`. One file `<project>.npa.data` beside the project; opened by one app instance only.
- B2 Streaming import for CSV and Parquet straight into the store; then Excel, JSON, XML, SQLite through the existing parsers in batches. Import limits raised step by step: 1,000,000, then 10,000,000, then 100,000,000 rows. Progress bar and Cancel.
- B3 Type detection and the type mapping of section 3, including date formats and locale. Each column's detected type must equal what the old importer decides on the same file (differential test on the existing import tests).
- B4 The grid, the Power Query preview and the import preview read pages from the store. Power Query editing works on a preview of the first 1,000 rows, as Power BI does; the full run happens on Apply.
- B5 Text case: store one spelling per case-insensitive value (the first seen). Check the rule against Power BI with the Power BI answer check on 20 cases before coding; also fix the old path (finding 2.4).
- B6 Project file keeps no table rows for store-backed tables; old `.npa` files still open; "Save" never rewrites the data file.
- B7 After import, show size per column and warn about unique text columns (finding 2.2).
- Exit: 10,000,000-row CSV imports in under 30 s with under 2 GB memory; grid scrolls to the last row in under 0.5 s; small tables behave exactly as before; gate passes.

### Stage C: DAX on the store (large; the main work)
- C0 Rules proof: implement the mappings of section 2.3 and 3 in one module, with the differential test on at least 200 formulas over data with blanks, mixed case, negative numbers, very large and very small numbers, dates. No pushdown is enabled before this passes.
- C1 Aggregates in the current filter context: SUM, MIN, MAX, AVERAGE, COUNT, COUNTA, COUNTROWS, COUNTBLANK, DISTINCTCOUNT.
- C2 Filters: CALCULATE with column predicates, ALL, REMOVEFILTERS, ALLEXCEPT, KEEPFILTERS, VALUES, DISTINCT, slicer and visual filters.
- C3 Relationships as joins, including the blank row for unmatched keys, RELATED, USERELATIONSHIP, cross-filter direction.
- C4 Visual batching: one store query per visual (group by the axis columns) instead of one evaluation per cell.
- C5 Iterators without context transition: SUMX, AVERAGEX, MINX, MAXX, COUNTX, FILTER. Arithmetic row formulas become one column expression (technique a); everything else uses distinct-combination evaluation (technique b).
- C6 Iterators over VALUES, SUMMARIZE, ADDCOLUMNS, SUMMARIZECOLUMNS with CALCULATE inside: one group-by query, then Python on the small result.
- C7 Time intelligence over a Date table as date-range filters: TOTALYTD, DATESYTD, SAMEPERIODLASTYEAR, DATEADD, DATESBETWEEN, PARALLELPERIOD.
- C8 TOPN and RANKX over a grouped result; ties follow the old engine's rule or the shape is refused.
- Everything else: refused on large tables with a clear message; listed in a "not yet fast" report so the next shapes are chosen by real use.
- Exit: every formula of the Phase 1 exit test that falls in C1 to C8 runs on 100,000,000 rows in under 5 s; 0 differences in the differential test; 0 wrong against saved Power BI answers; gate passes.

### Stage D: Power Query on the store (large)
- D1 Folding of the common steps into store queries: select and remove columns, rename, change type, filter rows, sort, remove duplicates, group by, merge (join), append, add column with arithmetic or text formulas, replace values, fill down, split column, first and last N rows.
- D2 Steps that cannot fold run row by row only below the threshold; above it the step is refused with the reason and the name of the step.
- D3 Differential test: for each folded step, the store result must equal the row-by-row M engine result on generated tables (order included).
- Exit: a 10-step query on 100,000,000 rows applies in under 60 s; 0 differences.

### Stage E: one billion rows and Linux (medium)
- E1 Incremental refresh: partitions by a date column; refresh loads only changed partitions.
- E2 Aggregation tables: user-defined first (a summary table plus a mapping), used automatically when the visual's columns allow it.
- E3 Memory and temp-disk limits as settings; default memory limit half of the machine's memory; a clear message when temp disk runs out.
- E4 Run the gate, the differential test and `tools/perf_check.py` on Linux (machine or container). Unchecked today.
- Exit: exit-test formulas in C1 to C8 on 1,000,000,000 rows: under 5 s on this Mac, under 30 s with a 4 GB memory limit; no crash in a 1-hour mixed test.

### Stage F: data that stays in a database (later, not planned in detail)
A second implementation of the store interface that sends the same queries to PostgreSQL, SQL Server or a warehouse. The interface of B1 must not assume DuckDB-only features, except where a fallback is written down.

## 5. How the team proves each step (and stays fast itself)
- Differential test: fast path against old engine on the same generated data; thousands of formulas in minutes; no Power BI, no virtual machine. This is the main daily proof.
- Power BI answer check: unchanged role. It stays the authority for the rules. It is needed only when a rule is new (for example B5), not for speed work.
- Gate: unchanged, plus the differential test and `tools/perf_check.py` at 1,000,000 rows as a speed guard (fail if a locked formula becomes 2 times slower).
- Standing rules of `TEAM_PLAN.md` still apply: no shape patches, `measures.py` must not grow. New store code lives in new modules, not in `measures.py`.

## 6. What the user of the tool sees
| Data size | Experience after each stage |
|---|---|
| Up to 200,000 rows | Same answers as today; window no longer freezes (A) |
| Up to 10,000,000 rows | Opens in seconds, grid scrolls (B); common measures in under 1 s (C) |
| Up to 100,000,000 rows | Import in minutes with progress; common measures and visuals in seconds (C, D) |
| 1,000,000,000 rows | Import with partitions; common measures in seconds on a strong Mac, tens of seconds on a 4 GB laptop (E) |
| Any size | A formula the fast path cannot do is refused with the reason; long work shows progress and can be cancelled; no crash from memory |

## 7. Risks that remain
| Risk | Status | Guard |
|---|---|---|
| A DAX rule is mapped wrongly and gives a wrong number on large data | Real; 3 examples found | C0 before any pushdown; differential test on every shape; refuse when not proven |
| Pushdown covers too few real formulas | Unknown until the Phase 1 exit-test list exists | "Not yet fast" report; technique b covers many iterators |
| Stage C and D are larger than estimated | Likely; sizes are guesses | Each sub-step ships alone and is useful alone |
| Real data is wider or dirtier than the random test data | Unchecked | Needs Armaan's real file (section 8) |
| Linux differences | Unchecked | E4 |
| Old path and fast path drift apart over time | Possible | Differential test in the gate, permanently |
| Order-dependent functions | Known | Row-number column; not pushed down until proven |

## 8. Still needed from Armaan (work can start without them)
1. One real data file or its description: source type, rows, columns, widest text column.
2. Will data stay in a database for some users (Stage F), or always be loaded into the tool?
3. The smallest computer the tool must run well on (memory and cores).

## 9. Not checked
Real data; Linux; Excel files above 100,000 rows; Microsoft's own documentation of VertiPaq; report visuals drawing time with many points; many users at once; DuckDB behaviour on a full disk; the exact Power BI answer for finding 2.4.
