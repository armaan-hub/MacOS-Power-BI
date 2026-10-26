# DAX function gap inventory (Power BI Desktop 2.157.879.0 vs the local engine)

Written by Claude, 2026-10-26. Method: REA read of the installed Power BI package, then live read-only queries to the running Power BI Desktop (headless, through the guest's local Analysis Services port; scratch tables `Facts` and `Cal` created and dropped in the unsaved model; nothing was saved).

## Method
1. `EVALUATE INFO.FUNCTIONS()` on the live model: **470 DAX functions**.
2. Each name called with no arguments through `tools/dax_oracle_diff.py local()`: the app answers "Function X is not supported by the local DAX engine" for **137 of the 470** (72 are `INFO.*`, 65 are others).
3. The 65 others were probed with about 1,100 real expressions. Answers are saved as new batteries (below). A recognised function can still have unsupported shapes: those are the pending ledger items.

## Findings per group (the 65 non-INFO functions)

| Group | Functions | Finding | Next step |
|---|---|---|---|
| Type tests | `ISINTEGER` `ISINT64` `ISDOUBLE` `ISDECIMAL` `ISCURRENCY` | Crisp answers, but they depend on the exact numeric type of every expression (`1` Int64, `1.5` and `1/2` and `ROUND(2.5,0)` and `POWER(2,2)` double, `CURRENCY(1)` currency, `FLOOR(2.5,1)` Int64, `DIVIDE(4,2)` double, `1E15` double, `SUM(Quantity)` Int64, `SUM(Sales)` double). 371 saved. | Task 5 (needs the engine to carry a numeric type; plan after Task 4). |
| Finance | `XNPV` | Pure formula, base date = earliest date, whole days, 365-day year. 107 saved. | **Task 3 plan written.** |
| Finance | `XIRR` | Power BI stops its solver early and returns noise digits (`0.100000008195639` for a true 0.1; the digits depend on the guess; plain Newton does not reproduce them). 43 saved in an unregistered research battery. | Research: find the algorithm (decompile `msmdsrv` / the engine DLL with REA) before any build. Until then stay refused. |
| Small scalar | `IF.EAGER` `ERROR` `CUSTOMDATA` `ISAFTER` `NAMEOF` `TABLEOF` `EVALUATEANDLOG` `ALLCROSSFILTERED` | Simple. 142 saved. `USEROBJECTID` returns the Windows SID of the host process (`S-1-5-18`): environment dependent, skip. | **Task 4 plan written.** |
| Text export | `TOCSV` `TOJSON` | Formats fully captured (separator, header, quoting, row limit, number/date rendering, JSON layout with `rowCount`, 4-significant-digit doubles such as `0.3333`, `20.0`). 185 saved. The 8 old pending items had truncated answers because the reader kept only the first line. | Task 6 (after the reader fix and re-freeze of `dax_battery_round2`). |
| Regression | `LINEST` `LINESTX` | `LINESTX(table, y, x1, ...)`, `LINEST(columnY, columnX1, ...)` (column references only). Returns one row; columns depend on the options (`Slope1`... `Intercept`, standard errors, `CoefficientOfDetermination`, `StandardError`, `FStatistic`, `DegreesOfFreedom`, `RegressionSumOfSquares`, `ResidualSumOfSquares`). 219 saved. | Task 7. |
| Table functions | `ADDMISSINGITEMS` `SUBSTITUTEWITHINDEX` | Semantics captured (166 saved with the ROLLUP family). They unlock 6 of the pending filter items (3 `ADDMISSINGITEMS`, 3 `SUBSTITUTEWITHINDEX`). | Task 8. |
| Grouping | `ROLLUP` `ROLLUPGROUP` `ROLLUPADDISSUBTOTAL` `ROLLUPISSUBTOTAL` `ISSUBTOTAL` | Saved in the same battery; behaviour is intricate (row counts 4, 9, 8, 9, 6 for the probed shapes). | After Task 8. |
| Week time intelligence | `STARTOFWEEK` `ENDOFWEEK` `DATESWTD` `PREVIOUSWEEK` `NEXTWEEK` `TOTALWTD` `OPENINGBALANCEWEEK` `CLOSINGBALANCEWEEK` | **Blocked.** Power BI requires a *calendar object* ("parameter 1 must be a calendar reference"), not a date column. The app has no calendar model objects. | Needs a model feature first (calendars). Park. |
| Visual calculations | `FIRST` `LAST` `NEXT` `PREVIOUS` `LOOKUP` `LOOKUPWITHTOTALS` `RUNNINGSUM` `MOVINGAVERAGE` `RANGE` `EXPAND` `COLLAPSE` `EXPANDALL` `COLLAPSEALL` `ISATLEVEL` | Only meaningful in a visual's data grid. | Park until the visual query layer is planned. |
| Not usable here | `CONVERTTOCSV`, `FULLOUTERJOIN` | Listed in Power BI's editor table but the engine says "Failed to resolve name". Not real functions. | Ignore. |
| Not usable here | `APPROXIMATEDISTINCTCOUNT` | Error "isn't supported for this storage mode" on the scratch model. | Ignore (the app correctly refuses). |
| Needs model objects | `CALENDARAUTO` (needs a date column in the model), `DETAILROWS`, `SELECTEDMEASURE*`, `ISSELECTEDMEASURE`, `NATURALJOINUSAGE`, `EXTERNALMEASURE`, `PATH` (needs a parent-child table), `COLUMNSTATISTICS`, `SAMPLE*`, `UTCNOW`, `UTCTODAY`, `ODDFYIELD` | Depend on model objects, the clock, or are rarely used. `ODDFYIELD` belongs with the bond functions (`dax_battery_bonds`, 2,280 locked). | Later. |
| Metadata | 72 `INFO.*` functions | Model-metadata tables. | Last. |

## New batteries (answers saved from the live Power BI on 2026-10-26)
Replay against the current app: **0 DIFF, 0 CRASH**. "Pending" counts the answers the app still refuses; the rest are Power BI errors the app already refuses.

| Battery | Items | Pending | Plan |
|---|---|---|---|
| `dax_battery_xnpv` | 107 | 93 | Task 3 |
| `dax_battery_scalar_misc2` | 142 | 99 | Task 4 |
| `dax_battery_type_tests` | 371 | 362 | Task 5 |
| `dax_battery_tocsv_tojson` | 185 | 162 | Task 6 |
| `dax_battery_linest` | 219 | 178 | Task 7 |
| `dax_battery_table_fns2` | 166 | 124 | Task 8 |
| `dax_battery_xirr_research` (not registered in the gate) | 43 | 30 | research only |

## Task queue (one at a time; each starts after the previous one is merged)
1. Task 1 `scalar-gaps-1`: built, in review.
2. Task 2 `var-scoping-1`: plan written (7 pending items, no VM).
3. Task 3 `xnpv-1`: plan written.
4. Task 4 `scalar-misc-2`: plan written.
5. Task 5 `type-tests-1`: plan written (the engine stores numbers as Decimal with no type, so the plan uses a static type inferrer, not a value tag).
6. Task 6 `tocsv-tojson-1`, Task 7 `linest-1`, Task 8 `table-fns-2` (three parts, includes ROLLUP and the scalar-subquery filter items): plans written.
7. Research: XIRR algorithm; calendar objects (week functions).

## Pending ledger items by theme (before the new batteries; 61 on 2026-10-26)
| Theme | Items | Task |
|---|---|---|
| VAR scoping, table VAR, CR comment, VAR in a CALCULATE filter | 7 | Task 2 |
| Scalar subqueries in a CALCULATE True/False filter: `KEEPFILTERS`/`ADDMISSINGITEMS` inside SUMX/MAXX/COUNTX | 6 | Task 8 |
| `CALCULATE(COUNTROWS(Facts), col < <scalar subquery>)` | 5 | Task 8 |
| `CALCULATETABLE(ROW("c",1), col > COUNTROWS(<table function>))` | 11 | Task 8 |
| `CALCULATE(COUNTROWS(Facts), col > COUNTROWS(CALCULATETABLE(VALUES(..), ..)))` | 4 | Task 8 |
| `SUBSTITUTEWITHINDEX` and `INFO.TABLES` inside filters | 6 | Task 8 / INFO |
| `RANKX` inside a CALCULATE filter | 4 | later |
| `SWITCH(.., TRUE(), .., BLANK())` with MAXX/SUMX | 2 | later |
| `IFERROR` / text-error and mixed-type `IF` | 6 | later |
| `TOCSV` / `TOJSON` / `CONCATENATEX` + `INDEX` | 9 | Task 6 |
