# Critic review of Iteration 84 (main at 206bce7)

Role: BI Compatibility and Data Integrity Auditor.  Parity claims were treated as false until a live Power BI Desktop answer and a reproducible test said otherwise.
Nothing in production code, locked tests or `tools/parity/*.json` was changed.  Only this file and `tests/fixtures_critic84.json` were added.

## 1. What was run

Oracle: live Power BI Desktop 2.157.879.0 through `tools/model_diff.py` (headless `prlctl exec` as SYSTEM, ADOMD/TMSL, nothing on screen, project never saved).
Models: ZO (orphans, blank keys), ZB (bidirectional star), ZS (snowflake, two facts), ZM (one-to-one, many-to-many).  Each model was installed **alone** for its run (see 6.1).

| | probes |
|---|---|
| unique (model, expression) pairs sent to Power BI (47 also occur in `tests/fixtures_iter84_*.json`, 36,241 are new) | **36,288** |
| match (value equals value: 26,931; both sides error: 3,967) | 30,898 |
| gap-reject (we refuse, Power BI answers) | 4,203 |
| **DIFF** (both answer, differently: 832; we answer, Power BI errors: 355) | **1,187** |
| CRASH (evaluator exception) | 0 |

Per model: ZO 12,116 match / 1,689 gap / 558 DIFF; ZB 8,740 / 1,281 / 253; ZS 7,875 / 1,221 / 287; ZM 2,167 / 12 / 89.
Generators (all adversarial): nested date sets to depth 3, VAR-held sets, several date filters per CALCULATE, ALL / ALLSELECTED / REMOVEFILTERS / ALLEXCEPT / KEEPFILTERS combined with date functions, USERELATIONSHIP, 11 fiscal year-end texts x 12 anchor dates, month-end and leap-day grids, blank and fractional bounds, iterators over dates and over fact rows, slicer-shaped outer filters, balances, FIRST/LASTNONBLANK(VALUE), date scalars (EOMONTH, EDATE, DATEDIFF, WEEKNUM, FORMAT, DATEVALUE, TIME ...), and a random grammar fuzz (7,500 + 6,600 expressions).

Every DIFF is in `tests/fixtures_critic84.json` (`model, expr, powerbi, ours, status`, plus `cluster` and `minimal`).  60 rows have `"minimal": true`: hand-reduced reproducers, all re-run a second time and still DIFF (stable).
The 355 "we answer, Power BI errors" rows are wrong answers too: a formula Power BI refuses must not show a number.

Reproduce one row: put `{"model":"ZO","expr":"..."}` in a list, then `PYTHONPATH=. python3 tools/model_diff.py in.json out.json --install ZO`.

Clusters of the 1,187 DIFFs:

| rows | cluster | severity |
|---|---|---|
| 405 | VAR-held table used as a CALCULATE filter keeps the outer date filters (date-key wipe lost) | Critical |
| 281 | `DATESBETWEEN(<table expression>, ..)`: Power BI errors, we answer | Important |
| 181 | date set evaluated inside a row context (iterator over Fact / over `ALL(Year)`) ignores the row | Important |
| 89 | ZM one-to-one relationship blank member | Important |
| 63 | `DATESINPERIOD` on a fact date column (month-aligned window) | Important |
| 54 | `FILTER`/iterator over a date set reads another column: Power BI errors, we answer | Important |
| 14 + 10 | `TOTALxTD(.., Fact[Dt], Cal[Date]=..)` filter argument; `UNION`/`EXCEPT` of date sets as a filter | Important |
| 12 | `TOTALYTD` year-end texts `"2/29/2024"`, `"Feb 29"`, `"29 Feb"`, `"2/29/2023"` | Important |
| 35 + 20 + 20 + 3 | date/time scalar edges, date-vs-number result type, other "Power BI errors, we answer", 3 deep nests | Minor |

## 2. CRITICAL

### C1. A table held in a VAR and then used as a CALCULATE filter is not treated like the same expression written inline

The most common prior-period idiom returns BLANK instead of the number.

| reproducer (model ZO) | Power BI | ours |
|---|---|---|
| `CALCULATE(VAR s=SAMEPERIODLASTYEAR(ZO_Cal[Date]) RETURN CALCULATE([mSum],s),ZO_Cal[Year]=2024,ZO_Cal[MonthNo]=2)` | 50 | BLANK |
| `CALCULATE(VAR s=PREVIOUSYEAR(ZO_Cal[Date]) RETURN CALCULATE(SUM(ZO_Fact[Amt]),s),ZO_Cal[Year]=2024)` | 85 | BLANK |
| `CALCULATE(VAR s=DATEADD(ZO_Cal[Date],-1,YEAR) RETURN CALCULATE(COUNTROWS(ZO_Fact),s),ZO_Cal[Year]=2024)` | 4 | BLANK |
| `CALCULATE(VAR s=PREVIOUSMONTH(ZO_Cal[Date]) RETURN CALCULATE(SUM(ZO_Fact[Amt]),s),ZO_Cal[MonthNo]=2)` | 10 | BLANK |
| `CALCULATE(VAR s=DATESBETWEEN(ZO_Cal[Date],DATE(2023,6,1),DATE(2024,5,31)) RETURN CALCULATE(SUM(ZO_Fact[Amt]),s),ZO_Cal[Year]=2024)` | 195 | 170 |
| `CALCULATE(VAR s=DATESQTD(ZO_Cal[Date]) RETURN CALCULATE(COUNTROWS(ZO_Cal),s),ZO_Cal[Year]=2024,ZO_Cal[MonthNo]=2)` | 60 | 29 |
| `CALCULATE(VAR s=ALL(ZO_Cal[Date]) RETURN CALCULATE(COUNTROWS(ZO_Cal),s),ZO_Cal[MonthNo]=2)` | 731 | 57 |
| `CALCULATE(VAR s=ALL(ZO_Cal[Date]) RETURN CALCULATE(IF(ISFILTERED(ZO_Cal[Year]),1,0),s),ZO_Cal[Year]=2030)` | 0 | 1 |
| `VAR s=SAMEPERIODLASTYEAR(ZO_Cal[Date]) RETURN CALCULATE(CALCULATE(MIN(ZO_Cal[Date]),s),ZO_Cal[MonthNo]>=11)` | 01/01/2023 | 11/01/2023 |
| ZS: `CALCULATE(VAR s=DATEADD(ZS_Cal[Date],-1,MONTH) RETURN CALCULATE(SUM(ZS_Fact[Amt]),s,s),ZS_Cal[Year]=2024,ZS_Cal[MonthNo]=2)` | 55 | BLANK |

Controlled comparison (16 date sets x 5 outer contexts x 3 bodies on ZO): the inline form `CALCULATE(CALCULATE(body, set), ctx)` matches Power BI in 240 of 240 probes; `VAR s=set RETURN CALCULATE(body, s)` has 84 DIFFs in 240 (the `KEEPFILTERS(s)` form matches 240 of 240).
The inline form (`CALCULATE(CALCULATE(SUM(..),SAMEPERIODLASTYEAR(ZO_Cal[Date])),ZO_Cal[Year]=2024,..)`) matches Power BI, and so does `VAR s=.. RETURN CALCULATE(.., s, <explicit month filter>)` (live: Power BI keeps the explicit filter).
In Power BI a filter on the key column `Date` replaces every outer filter of the calendar table; the engine implements that rule for inline sets and predicates but not for a VAR.
In a report visual the Year / Month rows play the role of the outer `ZO_Cal[Year]=2024,ZO_Cal[MonthNo]=2` filters, so `PY = VAR s = SAMEPERIODLASTYEAR(Cal[Date]) RETURN CALCULATE([Sales], s)` would show BLANK for every Year/Month row.
`PARITY_LEDGER.md` itself lists "VAR/RETURN" under "Not yet compared with Power BI", but the iteration-84 contract text presents the date-set slice as finished.

Suspected cause: `measures.py:9424-9426` (`evaluate_let` materialises a table VAR into a `_TableValue`), then `measures.py:6214-6218` feeds it back through the generic table-filter path.  The "applying a date set to a date key column first removes the other outer filters of its expanded table" step (`wiped_ids`, `measures.py:6978-6980` in `evaluate_with_date_values`) is only reached for inline date-set calls.
The same missing wipe shows in `CALCULATE(CALCULATE(COUNTROWS(ZO_Cal),UNION(ALL(ZO_Cal[Date]),VALUES(ZO_Cal[Date]))),ZO_Cal[MonthNo]=2)` (UNION/EXCEPT filters, 10 rows) and in TOTALxTD with a fact date column (I6).

## 3. IMPORTANT

### I1. `DATESBETWEEN` with a table expression as first argument: Power BI errors, we answer (281 rows)
Power BI: "DatesBetween and DatesInPeriod functions are only accepting date column reference as a first argument."
`CALCULATE(SUM(ZO_Fact[Amt]),DATESBETWEEN(VALUES(ZO_Cal[Date]),DATE(2024,1,1),DATE(2024,1,31)))` -> PBI error, ours 55.
Same for `ALL(..)`, `DISTINCT`, `ALLSELECTED`, `DATESYTD(..)`, `FILTER(ALL(..),TRUE())`, `TREATAS`, `SELECTCOLUMNS`, `CALCULATETABLE(..)`, `VALUES(ZO_Fact[Dt])`, with or without BLANK() bounds.
Cause: `_TIME_SET_ARITY` gives `DATESBETWEEN` the generic "column or table expression" check (`measures.py:557-583`, `_validate_time_set_call`).  `DATESBETWEEN` and `DATESINPERIOD` need a plain column reference.

### I2. Date set evaluated inside a row context ignores the row (181 rows)
Power BI treats the row of the iterated table as a filter for a bare date-set argument; we evaluate it in the outer filter context.
- `SUMX(ALL(ZO_Cal[Year]),COUNTROWS(DATESYTD(ZO_Cal[Date])))`: PBI 731, ours 1098.
- `COUNTX(ALL(ZO_Cal[Year]),MINX(STARTOFYEAR(ZO_Cal[Date]),ZO_Cal[Date]))`: PBI 2, ours 3.
- `SUMX(ZS_Fact,COUNTROWS(PREVIOUSDAY(ZS_Cal[Date])))`: PBI 10, ours BLANK.
- `MAXX(ZS_Fact,MAXX(FIRSTDATE(ZS_Cal[Date]),ZS_Cal[Date]))`: PBI 03/15/2024, ours 01/01/2023.
- `CALCULATE(AVERAGEX(ZS_Fact,MAXX(ZS_Fact,MAXX(DATESQTD(ZS_Cal[Date]),ZS_Cal[Date]))),ZS_Cal[Year]=2024,ZS_Cal[MonthNo]=2)`: PBI 45342 (02/20/2024), ours 45351.
With `CALCULATE(..)` around the date set (context transition) we match.  Cause: `time_filter_dates` builds `visible_dates` from the current filter only (`measures.py:9976-9983`) and never reads the row stack.

### I3. `DATESINPERIOD` on a fact (non-calendar) date column: Power BI aligns the window to whole months (63 rows)
Fact dates in ZO: 2023-12-31, 2024-01-05, 2024-02-10, 2024-02-20, 2024-03-15.
- `COUNTROWS(DATESINPERIOD(ZO_Fact[Dt],DATE(2024,3,15),-1,MONTH))`: PBI 1 ({3/15}), ours 2.
- `CALCULATE(SUM(ZO_Fact[Amt]),DATESINPERIOD(ZO_Fact[Dt],DATE(2024,3,15),-3,MONTH))`: PBI 170, ours 195.
- `MAXX(DATESINPERIOD(ZO_Fact[Dt],DATE(2024,1,5),1,MONTH),ZO_Fact[Dt])`: PBI 02/20/2024, ours 01/05/2024.
- `COUNTROWS(DATESINPERIOD(ZO_Fact[Dt],DATE(2024,1,6),1,MONTH))`: PBI 2, ours BLANK.
Pattern in the live answers (6 anchors x 10 period lengths x 4 forms = 240 probes): for MONTH/QUARTER/YEAR a negative count starts on the 1st of the month `|n|-1` months back from the anchor month (`-1 MONTH` from 3/15 = 3/1; `-1 YEAR` from 3/15/2024 = 4/1/2023); a positive count ends on the last day of the month `n` months ahead (`+1 MONTH` from 1/5 ends 2/29).  DAY windows and calendar columns follow the exact-day rule the engine implements (903/903 per the comment at `measures.py:10175`), which is therefore true only for a full calendar column.
Cause: `measures.py:10159-10182` uses one rule for both column kinds; the claim at `measures.py:9973` ("any Date/DateTime column works, a fact table's Dt included") is not true for this function.

### I4. Filter argument that is a table of "FILTER over a date set" reading another column: Power BI errors, we answer BLANK (54 rows)
`CALCULATE(SUM(ZO_Fact[Amt]),FILTER(NEXTQUARTER(ZO_Cal[Date]),ZO_Cal[Day]>10),ZO_Cal[Date]=DATE(2023,2,28))` -> PBI "A single value for column 'Day' ... cannot be determined", ours BLANK.  Same for DATEADD, PREVIOUSDAY, NEXTYEAR, PARALLELPERIOD(Fact[Ship]).  The iterator form is refused correctly (`measures.py:658`), the FILTER form is not.

### I5. ZM one-to-one relationship: unmatched rows form a blank member that `<>` filters include (89 rows)
ZM_U (k1..k4) and ZM_W (k1,k2,k3,k5) are 1:1 (both ways); W has k5 without U partner, U has k4 without W partner.
- `CALCULATE(COUNTROWS(ZM_W),ZM_U[K]<>"k1")`: PBI 3, ours 2.
- `CALCULATE(COUNTROWS(ZM_F),ZM_W[K]<>"k1")`: PBI 4, ours 2.
- `CALCULATE(COUNTROWS(VALUES(ZM_U[K])),ZM_W[K]="k5")`: PBI BLANK, ours 1.
- `CALCULATE(LASTNONBLANKVALUE(ZM_B[K],COUNTROWS(ZM_W)),ZM_U[K]<>"k1")`: PBI 3, ours 2.
Suspected cause: the blank-member rules were built for many-to-one (ZO); for a 1:1 link the unmatched rows of the other table are not added when the filter admits BLANK (`<>`).

### I6. TOTALxTD on a fact date column with a filter argument, and nested TOTALxTD (14 rows)
- `CALCULATE(TOTALYTD(COUNTROWS(ZS_Cal),ZS_Fact[Dt],ZS_Cal[Date]=DATE(2023,1,31)),ZS_Cal[Year]=2024,ZS_Cal[MonthNo]=2)`: PBI 1, ours BLANK.
- `CALCULATE(TOTALQTD(COUNTROWS(ZS_Cal),ZS_Fact[Dt],ZS_Cal[Date]<=DATE(2024,3,31)),ZS_Cal[MonthNo]=12,ZS_Cal[Year]=2023)`: PBI 456, ours 31.
- `TOTALYTD(TOTALQTD(COUNTROWS(ZS_Cal),ZS_Fact[Dt],ZS_Cal[Date]<=DATE(2024,3,31)),ZS_Cal[Date],ZS_Cal[Day]>=20)`: PBI 456, ours 171.
Same date-key wipe as C1, missing on the fact-column path (`measures.py:2880-2930` rewrite to DATESxTD).

### I7. Two year-end parsers that disagree, and `TOTALYTD` uses the wrong one (12 rows)
`measures.py:522` `_parse_year_end_date` and `dax_time_sets.py:55` `parse_year_end_text` differ on 6 of 269 sampled texts: `"2/29/2024"` (2,1 vs 2,29), `"2/29/2023"` (2,1 vs error), `"Feb 29"`, `"29 Feb"`, `"31 Mar."` (accepted vs error), `"6.30"` (error vs 12/30).
- `CALCULATE(TOTALYTD(COUNTROWS(ZO_Cal),ZO_Cal[Date],"2/29/2024"),ZO_Cal[Date]=DATE(2024,3,15))`: PBI 15, ours 43.
- `.. "Feb 29" ..` at 3/15/2024: PBI 43, ours 15.   `.. "2/29/2023" ..`: PBI error ("Type mismatch"), ours 43.
The same fiscal text therefore gives different answers in TOTALYTD and ENDOFYEAR/STARTOFYEAR.  Delete one parser (see section 5).

### I8. A measure may share its name with a column of its own table; Power BI binds `[Name]` to the column
Live TMSL check: adding measure `Qty` to `ZO_Fact` (which has column `Qty`) is accepted by the engine, then `SUMX(ZO_Fact,[Qty])` = 39 (the column sum), bare `[Qty]` = error.
Ours: `evaluate_measures` with measure `Quantity=1` and column `Quantity`: `SUMX(Facts,[Quantity])` = 6 (uses the measure), bare `[Quantity]` = 1.  The formula bar commits such a measure without warning (`FormulaBarController.commit("Quantity = SUM(Orders[Quantity])")` returns True).  A wrong silent answer for the next formula that reads `[Quantity]`.  (Whether Desktop's UI blocks the name was not tested, only the engine.)

### I9. Formula bar: unsaved draft is lost silently
Verified with `StudioController` + `FormulaBarController` offscreen:
1. `_open()` (`formula_bar.py:130`) never checks `dirty`.  With a dirty draft, `beginEditMeasure("Other")` / `beginNewMeasure()` replace it.  Only `syncFormulaBarToSelection` honours `dirty` (`Main.qml:751`); the field menu (`Main.qml:792,799`), `data.newMeasure` / `model.newCalculatedColumn` (`controller.py:4259-4260`), `ModelView.qml:1036`, `Main.qml:2438,4646` do not.
2. `_replace_with_new_project` (`controller.py:13274`) and `open_project_path` never reset the bar.  After New project, `bar.active` stays True with the old text and a stale home table id (`commit` then fails with "home table that is not loaded").  `_confirm_replace_project` (`controller.py:13258`) and `Main.qml:4945 onClosing` ignore a dirty draft, so quitting drops it without a prompt.

### I10. Advanced Editor: custom step names and descriptions move to the wrong step
`local_table_dialogs.py:10104-10120` keeps `previous_metadata[index]` when `previous_steps[index]["op"] == step["op"]`, i.e. by position.  Verified: three Removed Columns steps with descriptions "why Column2/3/4"; delete the first step in the editor and press Done -> the Column3 step now says "why Column2" and the Column4 step says "why Column3".  The correct mapping is by step identity (name / content).

### I11. Conditional Column dialog silently rebinds a missing column on edit
`ConditionalClauseRow.load` / `ValueOrColumnField.set_value` (`conditional_column_dialog.py:94-103, 181-190`) ignore `findText == -1`.  Verified: editing a step whose clause columns are `Gone`, `Missing` (and else column) in a table with headers A, B returns `column "A"`, test column `"A"`, else `"A"` and OK writes that without a message.

## 4. MINOR

Date/time scalars (35 rows, all in the fixture file):
- Time of day is rounded to whole seconds; Power BI rounds to 1/300 s (SQL datetime ticks): `DAY(DATE(2024,2,29)+0.999999)` PBI 29 / ours 1; `EOMONTH(DATE(2024,2,29)+0.999999,0)` PBI 02/29/2024 / ours 03/31/2024; `SECOND(0.99999999)` PBI 0 / ours 59.
- Two-digit years: `DATEVALUE("1/1/50")` PBI 1950 / ours 2050 (pivot is 49/50 in Power BI); `YEAR("1/1/0001")` PBI 2001 / ours 1.
- Accepted but Power BI errors: `TIMEVALUE("24:00")`, `("12:60")`, `("-1:00")`, `TIME(-1,0,0)`, `TIME(0,0,86400)`, `DATEVALUE("2024-01-01T12:00:00")`, `DATE(1900,2,29)` (and YEAR/MONTH/DAY of it), `YEAR(-693593)`, `MEDIANX(VALUES(Cal[Date]),Cal[Date])`, `TOTALYTD(..,"2/29/2023")`.
- Years before 100: Power BI clamps to 0100-01-01 (`DATE(100,1,-1)`, `EDATE(DATE(100,1,1),-1)`); negative serial plus a time fraction follows the OLE rule (`DATE(1899,12,29)+0.5` PBI 12/30/1899 12:00 / ours 12/29/1899 12:00).
- `WEEKNUM(DATE(100,1,1),21)` 52 vs 53; `FORMAT(DATE(2024,2,29)+0.75,"H AMPM")` PBI "6 PM" / ours "18 A2P2"; `FORMAT(DATE(100,1,1),"General Date")` "1/1/0100" vs "1/1/100".
Result types (20 rows): `GENERATESERIES(DATE..,DATE..)` values are dates in Power BI (`MAXX(..,[Value])` 01/03/2024, ours 45294); `SELECTEDVALUE(Cal[Date])+0` on an empty selection is a date (12/30/1899), ours 0; `COALESCE(MAX(date),0)` and `SWITCH(..,0,MAX(date))` are numbers in Power BI (45657), ours dates; `SUMX(VALUES(Year),MAX(date))` is a number (90732), ours a date.
`ISCROSSFILTERED(ZO_Fact)` after `VAR s=VALUES(ZO_Cal)` used as a filter: PBI 1, ours 0 (a full-table filter still counts).
Union of date sets as filter (`UNION(NEXTQUARTER(..),DATESINPERIOD(..))`, 10 rows) drops an operand in some nests.

UI / editor:
- `FormulaBarController.setName("A = B")` produces `A = B = <expr>`; the name box accepts `=` (`formula_bar.py:266-279`).
- `setHomeTable` on a saved measure sets the local table id even when `update_measure` refused the move (`formula_bar.py:292-300`).
- IntelliSense never offers a column or table whose name contains `]` (`dax_intellisense.py:263,271,278,320`, by design) although Power BI does.
- Advanced Editor refuses every `/* .. */` block comment (before `let`, after `Source`, inside a call, after `in`) with unrelated messages such as "Expected a quoted M name or text value, got '/* c */ A'" (`power_query_m.py` parser); line comments work.
- Ribbon command on a middle applied step appends at the end (no "Insert step" prompt) and can fail with `Column 'Column2' does not exist.` when the grid shows an earlier step (`_select_ribbon_operation`, `local_table_dialogs.py:5405-5430`).
- `Table.SelectRows(Source, each [Column1] > 1)` on a text column returns rows (numeric compare of text); in M this is a type error.  Conditional Column: "10" > "9" on a text column is a numeric compare, a text column compares as text in M (`_conditional_clause_matches`, `transformations.py:2586-2640`).  Not checked against Power Query (no oracle for M here).
- Status line "No syntax errors have been detected." is shown for `Source = #"Sheet_1"` scripts that Power BI could not run; the claim is about the local subset only.
- Contract text is stale: `DAX_COMPATIBILITY_CONTRACT.md:36` lists 19 time-intelligence functions as "Partial" (no FIRSTDATE, STARTOF*, ENDOF*, OPENING/CLOSINGBALANCE*, FIRST/LASTNONBLANK), line 54 says "69 names in `_FUNCTIONS`" (code: 328), line 45 says MAXX/MINX reject date results (they accept them now).

Dismissed after checking: Advanced Editor accepts only linear chains (branch from Source, unused step, forward reference, duplicate names, wrong `in` result are all refused with clear messages); M `or`/`and` precedence is right; `Web.Contents`/`File.Contents`/`Expression.Evaluate` are refused; Discard/Done prompts and `closeEvent` work; 173 offscreen UI/engine tests (formula bar, IntelliSense, Advanced Editor, conditional column, column menu, direct apply, ribbon, iteration-84 fixtures) pass.

## 5. Ponytail review (over-engineering, dead code, duplication)

| # | where | what to delete / shrink | net lines |
|---|---|---|---|
| P1 | `measures.py:3721` `evaluate_measures` | One function of **7,593 lines** (67% of the file) holding ~300 closures, 10 `evaluate_with_*` variants (`6960-9404`, 1,216 lines) that each repeat the same `nonlocal rows_by_table_id, context_sequence, current_context ...` save/restore (7 copies).  Extract one `filter_scope()` context manager and one evaluator class; the point is testability, not only size. | -150 to -250 on the first pass |
| P2 | `time_filter_dates` `measures.py:9964-10203` | The identical 6-line `available_dates = [d for ... if (d := _parse_measure_date(..))]` comprehension is pasted **11 times** (17 `_parse_measure_date` calls in one function), and a branch re-parses the whole date table every time.  Compute it once per (table, column) and cache. | -90 |
| P3 | `measures.py:724-930` + the DATESYTD/QTD/MTD/BETWEEN branches of P2 | `_previousyear_dates`, `_previousquarter_dates`, `_previousmonth_dates`, `_previousday_dates`, `_nextday/_nextmonth/_nextquarter/_nextyear_dates`, `_year_to_date_start`, `_parallelperiod_dates` (about 205 lines) re-implement what `dax_time_sets.date_set` (70 lines) already does for the same function names; every function now has two routes selected by `_legacy_time_shape` (`measures.py:603`) and `_TIME_FILTER_FUNCTIONS` (`:336`).  Route NEXT*/PREVIOUS*/DATES*TD/DATESBETWEEN through `date_set` and keep only DATEADD / SPLY / PARALLELPERIOD / DATESINPERIOD legacy code.  This also removes the root of I7. | -300 to -400 |
| P4 | `measures.py:522-570` vs `dax_time_sets.py:55-128` | Two year-end text parsers (+ `_year_end_reference_year`, `_MONTH_NAMES`) that disagree on 6 inputs (I7).  Keep `parse_year_end_text`. | -50 |
| P5 | `measures.py` dead functions | `order_arguments` (`:5235`, 20 lines), `without_eff` (`:4586`, 8), `_literal_kind` (`:1238`, 6): no reference anywhere in `analytics_studio`, `tests`, `tools`, `qml` (AST + grep). | -34 |
| P6 | `tools/dax_battery_*.json` (40 files, 3.9 MB) | Every battery file has a twin in `tools/parity/` whose expression set is a superset, so the inputs are stored twice.  Let `parity_check.py --freeze` read the parity file. | -3.9 MB (repo size) |
| P7 | tests | `tests/fixtures_iter84_*.json` = 18,291 probes; the six iteration-84 test files take 7m50s; most probes are the same shape across 5 anchors.  Collapse to one probe per (shape, cluster) for the default run, keep the full set behind a flag. | CI time -5x |
| P8 | repo root | 14 progress / timeline / roadmap markdown files (4,800 lines incl. a 1,336-line work log, two `*_HISTORICAL.md`) contradict each other and `PARITY_LEDGER.md`; keep the ledger and the contract. | -3,500 doc lines |
| P9 | `formula_bar.py` | `previewMeasure` / `previewColumn` are one-line wrappers of `beginEdit*(focus=False)`; `_column_names`, `_measure_names` and `_unique_name` are used once each.  Keep, they are small; no action. | 0 |

Estimated code reduction if P1-P5 are done: **about 650 lines of measures.py (-6%)** with no behaviour change except fixing I7.

## 6. Notes for the council

6.1 Tooling hazard: `tools/pbi_model.py install ZO ZB ZS ZM` gives the model measures (`mSum`, `mCnt`, `mYtd`, ...) only to the **first** model ("measure names are global").  A probe like `CALCULATE([mSum],..)` on ZB/ZS then silently reads ZO's fact table (e.g. 375 instead of 300).  My first 300-probe pass showed 17 such false DIFFs.  Install one model per run for measure probes, or refuse `[m*]` on the models without them in `model_diff.py`.
6.2 The live model was left in the standard state (`install ZO ZB ZS ZM`) after the runs; no scratch table or measure remains.
6.3 Not done: the full `tools/parity_check.py --tests` gate (too long for the foreground limit; the six iteration-84 test files, 73 tests, pass), the real GUI (offscreen only), Power Query semantics against a live Power Query (no oracle).
6.4 Everything in 3.I2, 3.I3, 3.I5 is a refusal candidate if a fix is not planned: a documented refusal is cheaper than a wrong answer.
