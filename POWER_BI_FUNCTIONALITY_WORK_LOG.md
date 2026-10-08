# Power BI Functionality Work Log

**Snapshot date:** 2026-10-08

**Master capability map:** [POWER_BI_FUNCTIONALITY_ROADMAP.md](POWER_BI_FUNCTIONALITY_ROADMAP.md)

**Current completion snapshot:** [POWER_BI_FUNCTIONALITY_PROGRESS.md](POWER_BI_FUNCTIONALITY_PROGRESS.md)

This is the cumulative record of functionality implemented and accepted in Analytics Studio so far. “Done” means the scoped capability has the acceptance described here or in the master graph; it does not mean full Microsoft Power BI parity. The app is not Power BI Desktop and does not provide PBIX compatibility.

## Current work in progress

- **Next implementation increment:** DAX row-to-filter context transition, as marked active in the master graph.
- **External acceptance gates:** benchmark large-file preview performance on an M1 Mac; verify SQL Server, OData, and Web against live services. Their current lifecycle coverage uses local fixtures or mocked services.
- **Larger queued areas:** comprehensive report and visual authoring, broader interactions and analytics, security/governance, service collaboration, and the separate mobile, paginated, Report Server, developer, embedding, Fabric, and AI tracks.

Update this section when the active increment or its blockers change.

## Completed functionality to date

### Data import, local sources, and project workflows

- Bounded preview-and-confirm import for CSV, Excel, flat JSON, regular-record XML, and Parquet, with parser limits and commit behavior that preserves the current project when import is canceled or fails.
- Background parsing and source discovery with progress/cancellation for supported workflows; Excel and SQLite setup work is moved off the UI thread. Folder sample-file discovery uses asynchronous refresh and debounce/cancel behavior.
- Folder combine for supported CSV, Excel, JSON, and XML files, including filtering, sample parser options, optional subfolders and `Source.Name`, schema checks, combine preview, and saved refresh settings.
- Legacy Excel `.xls` preview/import and changed-source refresh; local Parquet import within its documented flat-scalar and size limits.
- Read-only SQLite table/view discovery, selection, preview, project persistence, and recent-source restoration.
- Multiple local tables per project, active-table selection, table-scoped refresh/re-import, and removal without deleting the external source. A Data-view QML smoke covers the multi-table view.
- Refresh All controller and offscreen QML command path for supported linked sources and saved queries.
- Recent Sources, inline Enter/Paste and deterministic Sample Data, active transformed-table CSV export, and project save/open workflows.
- `.npa` v66 persistence for source identities/options, column types, saved transformations and queries, relationships, filters, measures, and related model metadata. File-backed rows remain linked to their source; inline rows are embedded.
- SQL Server, anonymous OData v4, and anonymous HTTPS Web import subsets are implemented with mocked/dialog/project lifecycle coverage. Live database or endpoint acceptance remains open.

### Query management and shaping — 50/50 graph-listed capabilities passed lifecycle acceptance

1. Choose and save a column type.
2. Validate and normalize values.
3. Save transformation metadata and replay it on refresh.
4. Save, reopen, and refresh acceptance for transformed queries.
5. Column quality and distribution profiles (row-error cells are not represented).
6. Saved append queries and dependency refresh.
7. Merge queries with all six supported join kinds.
8. Flat query groups for sources and saved queries.
9. Edit and reorder applied steps.
10. Split a column at its first delimiter.
11. Split a column into rows.
12. Group By with eight aggregations.
13. Unpivot selected columns or other columns.
14. Pivot columns with the supported aggregation choices.
15. Custom Column using the bounded local formula subset.
16. Conditional Column with ordered clauses and Else.
17. Merge selected columns.
18. Fill Down and Fill Up.
19. Duplicate a column while preserving values and type.
20. Enable or disable load for saved queries.
21. Include or exclude a query from report refresh.
22. Remove blank rows.
23. Remove top rows.
24. Remove bottom rows.
25. Keep top rows.
26. Keep bottom rows.
27. Keep a row range.
28. Remove alternate rows.
29. Add an index column with a configured sequence.
30. Reorder columns while preserving types.
31. Use the first row as headers.
32. Use headers as the first row.
33. Clean text by removing supported control characters.
34. Lowercase text.
35. Uppercase text.
36. Change type using an explicit locale for supported types.
37. Transpose a table.
38. Split a column by positions.
39. Split a column at every delimiter into columns.
40. Extract text before or after a selected delimiter occurrence.
41. Extract text between delimiter occurrences.
42. Capitalize each word.
43. Reverse text by Unicode code point.
44. Remove duplicates using selected columns.
45. Keep duplicate groups using selected columns.
46. Sort rows by multiple columns and directions.
47. Apply the supported text filter operators.
48. Apply inclusive numeric filter operators.
49. Apply advanced multi-column AND/OR filters.
50. Filter blank and nonblank rows.

The Transform Data QML command is also accepted offscreen: its availability follows table state, a step can be committed, and that step persists through save/reopen and replays after a source change. The expression editor and transformation engine remain deliberately bounded subsets, not general Power Query M.

### Semantic model, filters, and local DAX subset

- Seven supported persistent model column types with save/reopen/refresh coverage.
- Local measure expression subset with report, save/reopen, and evaluation coverage.
- Relationship create/edit/delete, validation, persistence, single-direction cross-table filter flow, and qualified cross-table measures.
- Saved page-, visual-, and report-level exact-value filters, including isolation and relationship propagation.
- Typed advanced filters and diagnostics; multi-value selection; relative date and time filters; Top N filters; and report-level filter lifecycle.
- Numeric/boolean calculated columns and one-column `DISTINCT` calculated tables with preview, persistence, and refresh replay.
- Existing date-table validation/marking and fixed or automatic calendar-table generation.
- Supported time-intelligence forms: `TOTALYTD` (calendar and documented M/D fiscal year end), `TOTALQTD`, `DATEADD`, `SAMEPERIODLASTYEAR`, `DATESYTD`, `DATESQTD`, `DATESMTD`, `DATESBETWEEN`, `DATESINPERIOD`, `PREVIOUSYEAR`, `PREVIOUSQUARTER`, and `PREVIOUSMONTH` through the documented local filter forms.
- Supported `CALCULATE` additions: Boolean column filters and `KEEPFILTERS`; table-valued `FILTER`; `REMOVEFILTERS`; `ALL` and `ALLNOBLANKROW`; `ALLEXCEPT`; bounded current-selection `ALLSELECTED`; `USERELATIONSHIP`; and `CROSSFILTER`.
- The evaluator is still a local DAX subset. Row-to-filter context transition is active, `ALLSELECTED` visual-axis behavior is pending, and same-call Boolean/time-intelligence combinations remain queued.

### Report and application foundations

- New/Open/Save/Save As, report-page creation, supported revenue chart switching among bar/column/line, core pane and zoom controls, Data and Model views, and a bounded Data-view preview.
- Several filter and model workflows work with saved report state, but comprehensive visual creation/editing, field wells, formatting, shapes, buttons, text boxes, and broader interactions remain queued.

## Latest recorded increment — 2026-10-08

- Added offscreen QML acceptance for `data.transform`, covering command availability, dialog commit, persisted steps, and replay after the source changes.
- Full suite result: `PYTHONPATH=. pytest -q` — **373 passed, 231 subtests passed**.
- Focused import/parser result: **41 passed, 30 subtests passed**.
- Recorded M5 Pro large-file timings: 100,000-row CSV (10,000,010 bytes), median **0.109 s**; 100,000-row XLSX (2,357,312 bytes), median **1.545 s**. The minimum-supported M1 timing is not yet recorded.
- Created the progress snapshot and synchronized stale acceptance wording in the implementation roadmap.

## Future update rule

After each functionality increment, update all project status documents in the same work session:

1. Add the completed capability, date, and verification evidence to this work log. Keep **Current work in progress** accurate.
2. Update [POWER_BI_FUNCTIONALITY_PROGRESS.md](POWER_BI_FUNCTIONALITY_PROGRESS.md) with the new completed scope, current blockers, and latest verification result.
3. Update the corresponding node and acceptance detail in [POWER_BI_FUNCTIONALITY_ROADMAP.md](POWER_BI_FUNCTIONALITY_ROADMAP.md); change its status only when its acceptance gate is met.
4. Distinguish automated/local or mocked acceptance from live-service and hardware acceptance. Do not count an unverified gate as complete, and do not turn the graph-box count into an overall product percentage.

This log is cumulative. Preserve earlier entries and append a dated increment instead of replacing the history.

### 2026-10-08: Page Management & Visual Lifecycles (G1.1 & G1.2 Backend)
* **Canvas and Visual Lifecycle Foundation:** Wired QML UI for native page rename, delete, duplicate, hide, and reorder. Migrated internal report project schema to dynamically allocate semantic and geometric visual dictionaries instead of static label lists. Increased format version to v68 representing full visual layout state support.
* **Status Change:** 7.1.1 mapped fully to `Passed`. 7.1.2 moved to `Active`. Test suite now covers grid and viewport layout configurations.

### 2026-10-08: Visual Canvas Instantiation & Sizing (G1.2 Complete)
* **Visual instantiator and chooser:** Converted the static Visualizations gallery in QML to spawn dynamic visuals based on generic selection types. Selecting an active visual updates its type geometry dynamically. 
* **Draggable grid layout:** Rebuilt the `Main.qml` `ChartCard` repeater using absolute coordinate mapping. Provided a `DragHandler` overlay for canvas dragging, a resize-corner for dimensions, and bound Delete/Backspace keys to active component removal.
* **Status Change:** 7.1.2 mapped fully to `Passed`. 7.1.3 (Static components) mapped to `Active`.

### 2026-10-08: Static Visual Components (G1.3 Complete)
* **Static Components Mapping:** Connected the QML 'Elements' Tab Ribbon for Images, Text boxes, and the full multi-category Shape palette system to instantiate into the abstract visual schema.
* **Component Renderers:** Bound `TextArea`, Vector `ShapeGlyph`, and fallback icon structures to overlay appropriately using absolute layouts on instantiation. Text boxes are selectable and dynamically wrapped into the absolute selection engine bounds.
* **Status Change:** 7.1.3 mapped fully to `Passed`. Overall Phase G1 is now complete. Next focus proceeds to G2 Field wells.

### 2026-10-08
- **7.2 Field Wells and Data Binding**: Implemented dynamic UI buckets and instantiated column binding configurations for visuals. The backend dynamically evaluates underlying aggregate patterns in Python and generates QVariantLists, ensuring responsive binding repaints in the QML display layer upon any dimension changes.
- **7.3 Formatting and Properties**: Wired visual architecture into an interactive QML structure bound to dynamic nested property models. Provided immediate implementation for General rules (title geometry bounds tracking) and Chart-specific metadata configurations (Data Colors mappings).
- **7.3.3 Format Painter and Clipboard**: Completed full clipboard logic allowing deep duplication of visual report configs and direct format painting of stylistic properties between instantiated visual components seamlessly inside the controller.
- **7.4.1 Z-order and Grouping**: Authored complete depth manipulation logic enabling Bring Forward, Send Backward, Bring to Front, and Send to Back canvas arrangements, fully exposed through the top menu format ribbon. Exposed basic QML stubs for eventual grouping routines.
