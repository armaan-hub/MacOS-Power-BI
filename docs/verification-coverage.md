# Verification Coverage — 2026-10-21

This matrix exists because earlier reviews treated a green suite and one successful workbook flow as a complete acceptance gate. Those checks proved only the paths they exercised. This pass maps each advertised local area to its automated or visual evidence and states the remaining boundary beside it.

“Covered” means the documented local behavior has representative deterministic tests. It does not mean every input value, every Microsoft-language syntax combination, every connector host, or every accessibility configuration has been exhaustively tested.

## Local capability evidence

| Area | What was verified | Evidence | Remaining limit |
|---|---|---|---|
| File import | CSV, Excel, JSON, XML, Parquet, SQLite, Folder, and legacy XLS preview/import and saved-source workflows; cancellation and parser boundaries. Explicit Excel header-row imports preserve physical blank rows for Power Query row-count operations, while automatic header detection keeps the normalized blank-row behavior. Iteration 43 routes the detected row-12-header workbook through the controller's actual Load and Transform preview actions; Transform remains staged until the visible Power Query Close & Load command applies it. Both paths preserve the sheet, header row, exact headers, detail row, and `Grand Total` through save/reopen. Live Power BI inspection showed metadata above the VAT table header; the local `Remove Top Rows (10) → Promote Headers → Remove Blank Rows` path returns the same 573 × 14 headers/values as the app's normalized import. Earlier manual end-to-end coverage loaded five worksheets, transformed a VAT query, created a relationship, evaluated DAX `SUM`/`SUMX` with `RELATED`, saved/reopened/refreshed, and left the source workbook unchanged. | `test_file_import.py`, `test_import_lifecycle.py`, `test_legacy_xls_lifecycle.py`, `test_sqlite_import_lifecycle.py`, `test_local_source_expansion.py`, `test_import_boundary_contracts.py`; live Power BI inspection and local-workbook comparison on 2026-10-20; manual workflow on 2026-10-14 | Minimum supported Mac performance benchmark remains open. Excel formulas are imported from stored results when present; they are not recalculated. |
| SQL Server | Fake ODBC navigation/import lifecycle, credential handling, save/reopen/refresh, SQL type rejection, value/count/text bounds, timeout, and connection cleanup | `test_sql_server_lifecycle.py`, `test_existing_source_settings_lifecycle.py` | No Microsoft ODBC driver is installed here, and no SQL Server endpoint/credentials were supplied. Real driver, TLS, login, returned SQL metadata/types, and Keychain acceptance are unverified. |
| OData | Fixture discovery, same-origin pagination, dialog/commit, save/reopen/refresh, malformed/empty/nested results, response/page/row/column/cell/text bounds, timeout, and TLS failure | `test_odata_import_lifecycle.py`, `test_existing_source_settings_lifecycle.py` | Best-effort public probe only; it does not verify every service or authentication mode. |
| Web | Fixture HTML/JSON/CSV/XML/Excel/Parquet dispatch; actual Web dialog discovery and source-picker dispatch into the model/report; typed measure across save/reopen/refresh; response/table/depth/row/column/cell/text bounds, timeout, redirect and TLS failure | `test_web_import_lifecycle.py`, `test_existing_source_settings_lifecycle.py` | Best-effort public CSV probe only. Browser-rendered pages, auth, headers, POST, pagination, and secret storage are unsupported. |
| Power Query editor | All 47 exposed operation IDs have a native transformation vs emitted/parsed M parity case. Focused lifecycle tests cover operation families and representative multi-step apply/save/reopen/refresh flows. The custom-column dialog now shows the active query's schema before the selected step, safely inserts field names (including `]`), lists only implemented and saved functions, inserts parameters, and explains conditional expressions. Add/edit/cancel, downstream replay, and legacy output-type preservation are covered. Preview column headers expose sort, condition-filter, and searchable value-filter menus. Value filters create staged OR conditions, distinguish null from empty text, and are capped at 64 selected and 2,000 distinct preview values. Splitter dragging and dark-palette pane/header colors are tested; visual captures include [the custom-column dialog](verification-artifacts/power-query-custom-column.png) and [the Power Query editor](verification-artifacts/power-query-editor-dark-mode.png). | `test_custom_column_lifecycle.py`, `test_power_query_m_editor.py`, `test_transform_persistence.py`, `test_home_file_workflows.py`, the `*_lifecycle.py` transform suites | The 47-operation parity test does not send every possible settings combination through save/reopen/refresh. The editor implements a documented M subset, not Microsoft's Mashup engine or full ribbon parity. |
| DAX and measures | The picker catalog has 57 entries (53 evaluator function names plus `BLANK`, `DISTINCT`, `FALSE`, and `TRUE` parser/editor forms); tests reference all 57. This inventory check is not semantic proof for every entry. Iteration 34 adds numeric-only measure `MAXX` and `MINX` over loaded tables and supported `ALL`-family forms, including row-expression type validation, blank skipping, dialog preview, card use, save/reopen, and changed-source refresh. Iteration 31 covers default `DIVIDE` blank behavior and scalar-measure `COALESCE`, including blank scoping, ordered fallbacks, zero/false preservation, error propagation, table/iterator rejection, and dialog-to-report save/reopen/refresh. Search, accepted inline function completion, nested-call argument guidance, and suppression inside strings/references are covered alongside aggregate, iterator, filter, time-intelligence, measure/report, save/reopen, changed-source refresh, and error behavior. Generated Quick Measures now qualify the selected column with the active loaded model table, display the table name, and fail closed when table identity is missing. A same-named-column lifecycle test covers active-table switching, save/reopen, apostrophe escaping, and source refresh. Captures show [inline suggestions](verification-artifacts/dax-measure-function-suggestions.png) and [current-argument help](verification-artifacts/dax-measure-inline-help.png). | `test_measures.py`, `test_totalytd.py`, `test_dax_time_extended.py`, `test_calculate_boolean_filters.py`, `test_calculate_advanced_combinations.py`, `test_context_transition.py`, `test_report_and_measure_workflow.py` | The app's evaluator is bounded and has no Microsoft Tabular oracle; not every valid argument form or semantic combination is verified, and full DAX parity is not implemented. Existing manually authored unqualified column references remain unchanged and resolve against the active table in this local evaluator. |
| Data and semantic model | Data preview pages through all loaded rows in windows of at most 500, displays row range/page count, resets after table switch and successful replacement, preserves last-good page/data on failed refresh, starts at page one after reopen, and leaves the project clean on navigation. Exact-500 and empty-table boundaries are covered. Both Report and Data field panes can switch among loaded tables and refresh their field lists. The Model view's right-hand Data pane lists each load-enabled table's own fields, stays stable as the active table changes, survives save/reopen, and labels enabled sources that are unavailable. Web/OData/SQL imports and opening a populated project clear stale field search and expand the report Data pane; relationship created through its dialog, saved/reopened, rendered in Model view, and consumed by a `RELATED`/`SUMX` measure across refresh; create/edit/delete and relationship filtering for all four cardinalities; date tables, calculated columns/tables, query load/refresh settings, groups, append/merge; table-scoped Model column defaults for loaded numeric fields, Auto/Sum/Average/Count, all 16 non-Scatter Y-axis visual types, separate Combo/Gauge/Card/Matrix value wells, dormant metadata, saved visual overrides; and v80 Sort by Column with typed pair validation, dormant/clearable mappings, direct and DAX chart categories/legends, KPI trend/latest value, slicer and Matrix axes, Top N membership preservation, exact fallback order, and keyboard recovery at 560 px | `test_model_data_views.py`, `test_model_column_summarization.py`, `test_model_column_sorting.py`, `test_project_migration.py`, `test_multiple_local_tables.py`, `test_relationship_lifecycle.py`, `test_date_table_lifecycle.py`, `test_calculated_column_lifecycle.py`, `test_calculated_table_lifecycle.py`, `test_query_load_setting_lifecycle.py`, `test_query_refresh_setting_lifecycle.py`, `test_query_group_lifecycle.py`, `test_saved_append_lifecycle.py`, `test_saved_merge_lifecycle.py` | Data view supports per-column sorting and preview-only Condition and searchable multi-select Values filters. Values searches can reach beyond the 2,000-option display cap; filter state follows the selected table and never changes loaded model rows, report calculations, or saved Power Query steps. The Report filter pane opens by default and can be collapsed; Model view directs row inspection to Data view. Table copy remains open. Full Tabular metadata, context propagation, security, and model compatibility are outside the local subset. Native macOS assistive-technology review remains open. |
| Report and visuals | Supported visual authoring, field wells, filters, interactions, clipboard, formatting, save/reopen, measure consumption, and refresh flows. Pointer-level checks drag a column and a DAX measure into chart wells, drop a column and a DAX measure on an existing visual, create a table by dropping a column onto the blank canvas, and create a card by dropping a DAX measure there. A bounded cross-table Table flow groups one explicitly qualified measure by one column from a direct active, single-direction 1:* relationship; the dimension binding persists its model-table ID, is stable under active-table switching, and survives save/reopen/refresh. Unsupported relationship paths and blank, duplicate, or unmatched keys fail visibly without partial rows. | `test_model_data_views.py`, `test_report_interactions.py`, `test_visual_lifecycle.py`, `test_cross_table_table_visual_lifecycle.py`, `test_cross_table_table_visual_ui.py`, and the other `test_*visual*_lifecycle.py`, filter, interaction, and report workflow suites | Multi-table chart/matrix wells, multiple dimensions/measures, multi-hop and other relationship paths, and full Power BI semantic-model behavior are not implemented. Some service-backed and advanced visuals/formatting are also unsupported. |
| Report printing | The report ribbon exports every visible report page as a clean A4 landscape PDF, omits hidden pages, preserves the selected page/visual and transient chart selections, and does not dirty the project. The export fits each page to printable bounds. | `test_report_export_lifecycle.py` | Automated checks verify PDF structure and page count; a native print-dialog/device workflow and every printer's output are not verified. |
| Project integrity | Every supported starting format version v1–v79 upgrades to v80; v79 adds `column_sort_by` while preserving existing model/report metadata; corrupt-primary recovery, unsupported-newer protection, and controller open→save backup preservation | `test_project_migration.py`, `test_model_column_sorting.py`, `test_project_recovery_lifecycle.py` | Generated historical snapshots cover the migration chain; they are not a separate archive of every historical user project. |

## Best-effort live probes

- **OData, 2026-10-14:** `https://services.odata.org/V4/Northwind/Northwind.svc/` returned 26 entity sets; the app read 10 Products rows with the expected ProductID/ProductName/SupplierID/CategoryID headers.
- **Web CSV, 2026-10-14:** `https://raw.githubusercontent.com/plotly/datasets/master/2014_usa_states.csv` returned 52 rows with Rank/State/Postal/Population headers.
- **SQL Server:** `pyodbc` imports, but `pyodbc.drivers()` returned an empty list. Live SQL execution could not run in this environment.

These live checks are observations, not stable test fixtures. The mocked network/ODBC tests are the deterministic acceptance gate.

## Iteration 25 regression gate (2026-10-16)

Pass: `QT_QPA_PLATFORM=offscreen python3 -m pytest -q` — **792 passed, 625 subtests passed**; `python3 -m compileall -q analytics_studio tests` — passed; `git diff --check` — passed; `python3 -m ruff check tests/test_model_data_views.py` — passed. The DAX inventory check found test references for **54/54** catalog entries (50 evaluator function names and four special forms). A full-suite pass verifies the repository tests as written; the feature matrix above still defines their scope and the limits that remain.

## Iteration 26 regression gate (2026-10-17)

The custom-column editor routes from the operation selector and ribbon, carries an inline draft into the formula dialog, lists the active query's columns and local functions, and validates through staged preview. DAX completion supports keyboard navigation and uses Qt UTF-16 cursor offsets safely; argument guidance follows nested calls. Report and Data field panes switch the active loaded table. Regressions cover these interactions, including a formula containing an emoji before the completion point.

The final full repository run passed **803 tests and 625 subtests** with Qt offscreen. Compileall and `git diff --check` passed. Targeted Ruff passed for the DAX editor and its focused tests. A broader check reported five cleanup findings in the touched Power Query/Home files; see `.council/TEST_RESULTS_ITER26.md`. Offscreen captures were inspected for the custom-column and DAX editor surfaces; native macOS accessibility and pixel-level acceptance remain unverified. At this checkpoint the Data and Report field panes chose one active table at a time and cross-table field wells were unsupported; Iteration 27 adds the bounded Table exception below.

## Iteration 27 regression gate (2026-10-19)

The Table visual can group one explicitly qualified measure from a related fact table by one dimension column. The field binding stores its model-table ID, stays stable when the field-pane table changes, and survives save/reopen and changed-source refresh. Inactive, ambiguous, bidirectional, unsupported-cardinality, incompatible-key, duplicate/blank dimension-key, blank/unmatched fact-key, and unsupported-measure cases show a diagnostic without partial rows. UI checks cover selecting the dimension table, adding the field, rendering results, and visible failures. Independent review confirmed the multi-measure orphan-key and dimension-first persistence findings are closed.

The focused lifecycle/QML run passed **14 tests and 4 subtests**; the full offscreen pytest run passed **817 tests and 629 subtests**. `python3 -m compileall -q analytics_studio tests`, `git diff --check`, and Ruff on both new lifecycle tests passed. Native macOS visual/accessibility acceptance, full M/Mashup and DAX/Tabular compatibility, and broader multi-table visual context remain open.

## Iteration 28 regression gate (2026-10-19)

The Model view's right-hand Data pane now binds every load-enabled table row to that table's own loaded headers, independent of the active table. Enabled but unavailable sources remain listed with a `Source unavailable` status and no borrowed fields. The lifecycle regression checks two distinct schemas, active-table switching, save/reopen, and unavailable-source behavior. The cross-table Table UI assertion also follows the persisted dimension-table anchor when the field selector changes back to the fact table.

The focused Model/Data, Home workflow, and measure workflow run passed **89 tests and 51 subtests**. The full offscreen suite passed **818 tests and 629 subtests**. `python3 -m compileall -q analytics_studio tests`, `git diff --check`, and targeted Ruff checks passed. The local table preview still lacks Table view sorting/filtering/copy, and full Tabular/DAX parity and native macOS accessibility acceptance remain open. See `.council/TEST_RESULTS_ITER28.md` and `.council/VERIFICATION_SIGN_OFF_ITER28.md`.

## Iteration 29 regression gate (2026-10-19)

New Quick Measures now contain a fully qualified reference to the active model table, and the dialog shows which table supplies the selected field. The controller rejects a missing or ambiguous active table-catalog mapping before opening the dialog; direct Quick Measure dialogs also cannot accept a formula without table context. Regression coverage checks a same-named Amount column across Orders and Targets, value stability on table switch, save/reopen, refresh of the original Orders source, apostrophe escaping, display-name versus semantic-name handling, and both fail-closed paths. Existing manually authored unqualified expressions are unchanged.

The focused suites passed **71 tests and 45 subtests**; the fresh full offscreen suite passed **820 tests and 629 subtests**. Compileall, `git diff --check`, and targeted Ruff passed. This is a targeted local DAX authoring fix, not full Quick Measure catalog, DAX, or Tabular compatibility. See `.council/TEST_RESULTS_ITER29.md` and `.council/VERIFICATION_SIGN_OFF_ITER29.md` for verification limits.

## Iteration 30 regression gate (2026-10-19)

The Data preview now pages the full loaded table in 500-row windows. Its footer shows the current row range and page count and provides Previous/Next controls with disabled boundary states. Paging is transient and leaves source rows, project metadata, and dirty state untouched. A successful source replacement or active-table change returns to page one and scroll position zero; a failed refresh preserves the last good rows and page. Empty and exactly-500-row inputs have explicit boundaries. Save/reopen returns to page one.

See `.council/TEST_RESULTS_ITER30.md` and `.council/VERIFICATION_SIGN_OFF_ITER30.md` for current verification counts. Power BI Table view sorting, filtering, and copy remain open; the local preview uses paging rather than claiming native interaction parity. Native macOS accessibility and full DAX/Tabular compatibility also remain open.

The focused Data view suite passed **11 tests and 3 subtests**. Two independent full offscreen runs passed **821 tests and 629 subtests**; compileall, `git diff --check`, and the targeted Ruff checks passed. The QML lifecycle fixture has 12 columns at a 900px viewport and verifies pager navigation with horizontal scrolling. This establishes the documented local paging behavior, not every window size or native macOS layout acceptance.


## Iteration 31 regression gate (2026-10-19)

`COALESCE(DIVIDE(SUM([Numerator]), SUM([Denominator])), 7)` is assembled from the actual Measure editor template, previewed and saved through the dialog, added to a report card, saved/reopened, and recomputed after the denominator source changes. Unit coverage also verifies ordered 3-argument fallback, all blank, zero and false preservation, invalid/omitted arity (including an interior omission), error propagation, table-valued rejection, and early calculated-column/row-iterator rejection. The function inventory now has **55/55** picker entries referenced by tests (51 evaluator names and four parser/editor forms).

The focused measure/report suites passed **67 tests and 53 subtests**. The full offscreen suite passed **827 tests and 640 subtests**. `compileall`, targeted Ruff, and `git diff --check` passed. The local evaluator remains a partial DAX implementation without a Microsoft Tabular oracle; mixed types, text/empty-string results, and full DAX coercion semantics remain open. See `.council/TEST_RESULTS_ITER31.md` and `.council/VERIFICATION_SIGN_OFF_ITER31.md`.


## Iteration 32 regression gate (2026-10-19)

The Model view stores per-table defaults for loaded numeric source columns. Tests cover Auto/Sum/Average/Count, application to all 16 declared non-Scatter `Y-axis` visual types plus Combo, Gauge, Card, and Matrix value wells, exclusion of grouping and unsupported wells, persistence and visual override isolation, dormant metadata through missing/nonnumeric/unavailable fields, schema migration, duplicate names, calculated-column collisions, and keyboard/accessibility/responsive inspector behavior. The parity boundary remains four local choices and the existing local aggregation semantics, not complete Power BI summarization or Tabular parity.

The focused Model-pane/project/report suites passed **91 tests and 135 subtests**; the full offscreen suite passed **844 tests and 692 subtests**. `compileall`, targeted Ruff, and `git diff --check` passed. See `.council/TEST_RESULTS_ITER32.md` and `.council/VERIFICATION_SIGN_OFF_ITER32.md`.

## Iteration 33 regression gate (2026-10-19)

Model Sort by Column is persisted in project v80. Tests cover same-table source fields, both mapping directions, typed scalar order and temporal edge cases, null/empty/error handling in either mapped field, refresh invalidation/recovery across save/reopen, bound-table DAX grouping, direct/DAX chart categories and legends, KPI trend/latest value, slicer and Matrix axes, Top N membership, consumer-specific absence/inactive fallbacks, and keyboard-accessible missing/unloaded rule clearing at 560 px.

The focused integration passed **166 tests and 185 subtests**. The full offscreen suite passed **869 tests and 700 subtests**. Compileall, targeted Ruff E9/F821, `git diff --check`, and independent SDET review passed. Microsoft Desktop authoring location and wider visual coverage differ; the automated suite does not establish native macOS accessibility or full Tabular/DAX compatibility. See `.council/TEST_RESULTS_ITER33.md` and `.council/VERIFICATION_SIGN_OFF_ITER33.md`.

## Iteration 35 regression gate (2026-10-20)

Explicit Excel header-row imports now preserve physical blank rows and missing worksheet row positions, allowing Power Query-style row-count steps to operate on source positions. Automatic header detection still omits blank rows. The VAT workbook's local `Remove Top Rows (10) → Promote Headers → Remove Blank Rows` path produces 573 × 14 and matches the app's normalized import; Power BI was inspected to locate the metadata/header layout, but the exact sequence was not applied in Desktop during this pass.

The focused import suite passed **30 tests and 19 subtests**; the full offscreen suite passed **923 tests and 715 subtests**. Compileall and `git diff --check` passed. Full Microsoft Mashup/M parity, native accessibility, and live end-to-end application acceptance remain open. See `.council/TEST_RESULTS_ITER35.md`.


### Iteration 35 Model diagram follow-on (2026-10-20)

Model view defaults to Diagram mode; connected tables are ordered together, the first qualifying star is arranged around its hub, unrelated tables follow that component, and large hubs are stacked with distinct relationship ports. The diagram viewport shows a compact measure count and Table list action; full measure expressions and calculated-column definitions remain in Table list mode, and the column inspector appears after a field is selected. Tests cover one-, two-, four-, six-, and eight-table layouts, disconnected tables, route/card clearance, hit targets, and the linked compact two-table transition at 800 px. The focused Model suite passes **27 tests**; the fresh full suite passes **931 tests and 715 subtests**. Ruff, compileall, and `git diff --check` pass. REA's versioned static report covers selected relationship/modeler code and partial model-view assets but does not establish live diagram layout behavior. Later disconnected stars use the regular grid; drag/persisted positions, formulas inside diagram cards, arbitrary graph layouts, and native visual acceptance remain open.

## Iteration 43 Excel Load/Transform lifecycle (2026-10-20)

The generated `.xlsx` has eleven preamble rows, headers on worksheet row 12,
one detail row, and a `Grand Total` row. The regression clicks the actual
preview Load and Transform controls through `StudioController.import_excel_path`.
For Transform, it checks the query and rows are staged while the project,
loaded candidates, active source, and dirty state remain unchanged; it then
clicks the visible Power Query Close & Load ribbon button. Both flows commit,
save, and reopen with `sheet_name=VAT 5%`, `header_row=12`, the expected three
headers, and both source rows intact.

The focused lifecycle test passed **1 test and 2 subtests**. The fresh full
offscreen suite passed **945 tests and 719 subtests**. Targeted Ruff,
`compileall`, and `git diff --check` passed. The test does not verify refresh,
Power BI row-count equivalence, every Excel layout, or wider Power Query, DAX,
model, and visual parity. See `.council/TEST_RESULTS_ITER43.md` and
`.council/VERIFICATION_SIGN_OFF_ITER43.md`.

## Iteration 51 Excel raw Transform source (2026-10-21)

The Power BI Desktop 2.157.879.0 VAT partition metadata shows that the clean
query begins with `Excel.Workbook(..., null, false)`. Raw Transform now retains
the worksheet's declared range with `Column1…ColumnN`; the existing Load
preview and explicit-header blank-gap behavior remain separate. A populated
14-column regression follows 623 → 585 → 574 → 573, checks varied typed values
and both footer-inclusive/detail totals, then drives preview Transform,
Close & Load, save, reopen, and refresh with complete row equality and persisted
options/steps. Automatic and explicit-header imports ignore inflated declared
tails, and `.xls` raw mode covers BIFF-declared rows.

Focused import/Transform tests passed **190 tests and 217 subtests**; the fresh
full suite passed **981 tests and 722 subtests**. Compileall, targeted Ruff,
and `git diff --check` passed. The supplied VAT workbook was read-only replayed
again at 623 → 585 → 574 → 573 and its displayed totals matched; its source hash
was unchanged. REA's new native-window screenshot attempt was blocked by
ambiguous Power BI proxy geometry. This evidence does not establish full
Mashup/M, DAX/Tabular, Model/Report, or visual parity. See
`.council/TEST_RESULTS_ITER51.md` and `.council/VERIFICATION_SIGN_OFF_ITER51.md`.
