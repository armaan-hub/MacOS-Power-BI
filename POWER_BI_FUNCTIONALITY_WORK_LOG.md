# Power BI Functionality Work Log

**Snapshot date:** 2026-10-21

**Master capability map:** [POWER_BI_FUNCTIONALITY_ROADMAP.md](POWER_BI_FUNCTIONALITY_ROADMAP.md)

**Current completion snapshot:** [POWER_BI_FUNCTIONALITY_PROGRESS.md](POWER_BI_FUNCTIONALITY_PROGRESS.md)

This is the cumulative record of functionality implemented and accepted in Analytics Studio so far. “Done” means the scoped capability has the acceptance described here or in the master graph; it does not mean full Microsoft Power BI parity. The app is not Power BI Desktop and does not provide PBIX compatibility.

## Current work in progress

- **Current increment:** Excel import preview separates automatic Load from an explicit row-1 Transform start. The choice is reparsed asynchronously, manual header choices are preserved, and Excel source identity includes sheet and header mode. Legacy numeric-header sources are reused only during an explicit automatic reimport when their row matches current detection; exact option matches win first. The ambiguity of old numeric settings remains because they do not record whether the user selected Auto or a manual row.
- **Latest recorded full verification:** **957 pytest tests and 719 subtests passed** for Iteration 48; the focused import lifecycle run passed **28 tests and 22 subtests**. See [Iteration 48 verification](.council/TEST_RESULTS_ITER48.md). These are local app tests, not a measure of Power BI parity.
- **Completed source-edit coverage:** existing CSV, Excel, JSON, XML, Parquet, SQLite, and folder roots stage path and parser/combine changes. SQLite also allows choosing tables/views. The new SQL Server/OData/Web editing flow is implemented but not yet accepted. Source identity, query metadata, and steps persist; included reference/append/merge descendants refresh together. Root/dependent schema and type changes remain rejected. Apply checks final SQLite binding uniqueness across edited and new sources using SQLite-compatible ASCII folding while preserving exact stored names, and checks active relationship constraints when both endpoints have loaded candidate data.
- **Remaining source-edit gaps:** remote edit lifecycle acceptance, schema migration, live remote acceptance, and manual macOS UI acceptance.
- **External acceptance gates:** benchmark large-file preview performance on an M1 Mac; verify SQL Server, OData, and Web against live services. Their current lifecycle coverage uses local fixtures or mocked services.
- **Unavailable product families:** RLS/OLS, role authoring, cloud publishing/collaboration, mobile/paginated reports, Report Server, embedding, and Q&A/Copilot. Their UI actions are disabled and they require separate implementation programs.
- **Larger queued areas:** broader report/visual workflows and interactions, complete DAX/M compatibility, additional connectors, security/governance, and service/platform extensions.

Update this section when the active increment or its blockers change.

### 2026-10-19: Add per-table Data-view column sorting

- **REA evidence:** `DataSourceHostService.GetQueryInfo` in the installed `Microsoft.PowerBI.Client.Windows.dll` calls its sort-info and filter-info readers, then writes the results into `ModelQueryInfo.OrderBy` and `ModelQueryInfo.Filters`. The host keeps `sortFilterColumns` keyed by table name; the sort record has `Column` and `Direction` fields, and the filter record has `Column` and `Filter` fields. Static evidence is `ev_778d983469bbd44a163648b0be7ec6cecdd2153d526474cd496300c0055e1b08` and selected type metadata is `ev_cece080def8c568eeb73eb456843ea0359ca7b2f1405196ff596ee5605af82dd`, both bound to Desktop 2.157.879.0 `Microsoft.PowerBI.Client.Windows.dll` SHA-256 `f0dd0953a7e647bbda3b606fcc28712dbfd05d1d6c8afa5e1ac0d2da3501c347`. This is static bridge evidence; no Desktop UI/runtime behavior was captured.
- **Implementation:** clicking a Data-view column header sorts all loaded rows by that column, toggles ascending/descending, then resets the visible page to the first 500-row window. Sort state is held per active table during the app session and is reapplied after a refresh or table switch. Saved column types guide parsing of numeric, boolean, and ISO date/time text values.
- **Scope:** the local grid supports one sort column at a time. Power BI's list-shaped `OrderBy` permits broader ordering, but the inspected bridge does not establish the header gesture or tie behavior. Filter controls and cell/column/table copy remain open. Local blank/error ordering, locale collation, and non-ISO date sorting are approximations.
- **Verification:** Python syntax compilation, QML lint, and `git diff --check` only; no tests or UI runtime checks were run.

### 2026-10-19: Persist an explicit table key for relationship detection

- **REA evidence:** Modeling Engine candidate selection admits a column when its `IsKey` flag is set, even if it is not unique or contains nulls; the cardinality and existing relationship-role score still applies. Minerva's Model-view source exposes `getKeyColumnOptions` and a `setKeyColumn` schema-change path, listing Data columns and reporting duplicate-value validation. Evidence is bound to Modeling Engine SHA-256 `466838efa60138e8bc685a07e3ee61063fd8ab8c104bd556107e6999736b128b`; the Minerva analysis `ev_b89dc33d93576194cd4561ef9dd4f60b5c04dc9b498154b1e032edb048120f20` is partial.
- **Implementation:** project format v82 persists an optional per-table `key_column`; the Model-view inspector offers loaded source columns and checks uniqueness before setting it. Relationship detection uses the marker to bypass its unique-and-null-free primary-candidate gate.
- **Scope:** this models the detector's explicit-key signal and the visible key-column editor only. Featured-table data-search curation, row labels, and full featured-table behavior are not implemented.
- **Verification:** `py_compile` and `git diff --check` only; no tests or UI runtime checks were run.

### 2026-10-19: Recover relationship cardinality query semantics

- **REA evidence:** selected CIL shows uniqueness is `DistinctRowCount == RowCount`; null presence is read from the cardinality result. The `DataValidationConstants` initializer contains query templates using `DISTINCTCOUNT`, `COUNTROWS`, and `ISBLANK` (`ev_3881722dc5402026f24a5fa78d98ead4b9710ae5b4919f30f108e56781c8f48b`, `ev_357fd938cfefceb6a60a6c444b2bbf2604bf806cae76a90decbfcb1f6402b61b`, Modeling Engine SHA-256 `466838efa60138e8bc685a07e3ee61063fd8ab8c104bd556107e6999736b128b`). Microsoft documents that `DISTINCTCOUNT` includes BLANK and that BLANK and empty strings are not equivalent in every operation.
- **Disposition:** this confirms the query shape and blank counting, but static evidence does not establish how each import path preserves empty text in the model. No comparison behavior was changed.
- **Verification:** static REA CIL inspection and Microsoft Learn documentation only; no tests or target runtime checks were run.

### 2026-10-19: Skip empty tables during relationship key grouping

- **REA evidence:** the installed detector's `GetColumnsByKey` scans nonempty import tables before collecting key columns. This condition is recorded from static CIL for Modeling Engine SHA-256 `466838efa60138e8bc685a07e3ee61063fd8ab8c104bd556107e6999736b128b` in `ev_e32d8e815db901433ceec5b5e5c34463216f9aebdc7975169c3558f4f01d122f`.
- **Implementation:** Analytics Studio now removes zero-row tables before building relationship key groups, so empty tables cannot consume the observed per-key and per-table-signature candidate caps.
- **Verification:** static checks only; no tests or UI runtime checks were run.

### 2026-10-19: Confirm stable ordering for equal relationship paths

- **REA evidence:** `FilterAndSortColumnPairs` calls `Where`, `OrderBy`, then `Select`; the ordering selector reads `ValueTuple.Item2` (the path length), and the projection returns `Item1` (the original pair). The lambda CIL is in `ev_4b7cf4765698367b157fdffbda63f5de84efcaa0403f67b08940233d235e46be` and `ev_a3c643870203e3829d4e1609570dd99c1621628bdb93d61d32fbfb4c6a24f96e`; resolved call edges are in `ev_cc26e6d43df337ad16d1d3d901784527e351e52d6d0e7421c8a8cab649fcae64`. The target was statically inspected and not executed.
- **Implementation:** retained detector discovery order for equal path lengths and changed the local sort key to path length only, relying on Python's stable sort. Equal-path proposals have a directly evidenced tie rule; the `Pair<IColumn>` type is not a secondary sort key.
- **Verification:** `py_compile` and `git diff --check` only; no tests or UI runtime checks were run.

### 2026-10-19: Match single-table autodetection scope semantics

- **REA evidence:** `AreTablesConnected` returns true when its requested-table count is less than two (CIL token `0x060003bb`, build-local to the evidence's assembly identity).
- **Implementation:** removed the low-level detector's minimum-two-target guard so a one-table scope advances through the native first path threshold. The visible scope picker still requires at least two selections, as a single table does not define a useful user-facing connection target set.
- **Verification:** `py_compile` and `git diff --check` only; no tests or UI runtime checks were run.

### 2026-10-19: Persisted Group by columns metadata for relationship detection

- **REA evidence:** `GetColumnsByKey` excludes a column when its related-column `GroupByColumns` list is nonempty. The Modeler exposes `SetGroupByColumns`, which writes that metadata (`ev_a9975afe0d32ed9d8df5e638b8f1a17cdd21f00535702f0b538da63115ab1af1`, bound to Modeler SHA-256 `c5d5bb827acc2c634eb0993a70dd4f64b1641b86dff67baa1bed188536803e1d`). The inspected target UI did not establish a generic editor for this property.
- **Implementation:** added project format v81 `group_by_columns` metadata, a Model-view checklist editor for same-table companion columns, and relationship detector filtering when a candidate's saved list is nonempty. The relationship-dialog input now reads calculated-column and grouping metadata from the project table record, fixing a mismatch between project and view-model field names that prevented calculated-column exclusions from reaching the detector.
- **Scope:** this models the property and its detector effect. It does not apply grouping metadata to visuals, filters, or DAX, and does not reproduce the target's undiscovered editing UI.
- **Verification:** static syntax checks and `git diff --check`; no tests or manual UI runtime checks were run.

### 2026-10-19: Scoped relationship autodetection from REA path evidence

- **REA evidence:** focused managed-code analysis of Power BI Desktop 2.157.879.0 covers `FilterAndSortColumnPairs`, `GetColumnPairsPathLengths`, `MarkTableRelationships`, `AreTablesConnected`, and `TraverseReachableTables` in `Microsoft.PowerBI.Modeling.Engine.dll` (`ev_e32d8e815db901433ceec5b5e5c34463216f9aebdc7975169c3558f4f01d122f`; selected-type coverage view `ev_6e9056145578dfe1dd1864f6c0788f9fd22446ef557293e8463b2346b592172a`). A separate analysis of the installed package's `Pair<T>` type is `ev_193ee52c6fb4c0124aab2e173c85c89faf687cf18a621d2fb1d97cdad5f9f2e3`. Static CIL shows the path threshold starts at 1, rises to the caller's limit of 4, and stops when requested tables connect. It also shows the pass is skipped for a null or empty table scope. The assembly was not executed, and this evidence does not establish the native UI entry point or tie comparer behavior.
- **Implementation:** kept the existing unscoped Autodetect action and added a menu option to choose target tables. The detector traverses saved relationships and proposed candidate links in either direction, sorts scoped suggestions by path length, and applies the observed 1–4 threshold/connected-table stopping behavior. Other tables can act as intermediate links; equal-length proposals retain discovery order, matching the native stable path-length sort. Suggestions remain reviewable and are staged until Save.
- **Verification:** `py_compile` and `git diff --check` are the static gates for this increment. No tests or manual UI runtime checks were run.

### 2026-10-19: REA-guided local filled and shape maps

- **REA evidence:** inspected the installed Power BI 2.157.879.0 `minerva` map bundle and UK TopoJSON from the mounted Windows volume. Focused static analysis recorded the `MapVisuals` webpack chunk and three modules (`ev_b22899da14e5a636dc8451aa27367a0e55a5efc5a265937e14609d9a856a6bce`, with parent analysis `ev_2462e91727bb976d7cf74772574250d061b55e8ea7b7c0dab9afdc48114cb066`). The JS and TopoJSON hashes match REA's cached copies. Bundled code was not executed; findings are partial static evidence.
- **Implementation:** added bounded local GeoJSON/TopoJSON parsing and custom boundary selection in `analytics_studio/shape_map.py` and `analytics_studio/controller.py`; integrated map field wells and gallery choices in `analytics_studio/qml/Main.qml`; rendered locally projected regions and selection/highlight behavior in `analytics_studio/qml/ChartCard.qml`. Aggregations support Sum, Count, and Average, with report measure support for Values. Also corrected a duplicate QML ID found during linting. No Microsoft boundary asset is copied into the app.
- **Limits:** input files are capped at 8 MB, 5,000 regions, and 100,000 coordinate vertices. This increment does not add geocoding, basemaps, Azure Maps, or ArcGIS. Runtime, save/reopen, and refresh lifecycle acceptance remains pending.
- **Verification:** `py_compile`, `git diff --check`, and `pyside6-qmllint` pass. QML lint reports layout-positioning warnings and an unused-import note. No tests were run for this increment.

### 2026-10-13: Edit remote source settings in Power Query

- Added Edit Source Settings to existing SQL Server, OData, and Web root queries. Each dialog restores the saved connection and selected table/entity/data object so users can make targeted changes.
- Remote source changes retain the existing source ID, query metadata, and transformation steps. Included query descendants refresh from the edited preview, and Apply uses that same remote snapshot. The current schema and type checks still reject replacements that would break model/report references.
- SQL password changes are staged in memory and assigned a new connection-bound Keychain reference. The old credential is removed only after a successful project commit; project files do not receive the password.
- **Acceptance status:** implementation is in place; automated lifecycle and manual macOS acceptance have not yet been recorded. Live SQL Server, OData, and Web endpoints remain external gates.
- **Next:** cover the remote source-edit flows through focused lifecycle acceptance, then address schema-changing replacements and additional local M mappings.

### 2026-10-12: Edit SQLite source settings

- Added Edit Source Settings for existing SQLite roots in the Power Query ribbon and query context menu. The dialog restores the selected object, supports switching tables/views, and preserves the source ID, query metadata, and applied steps when the path or `table_name` changes.
- Close & Apply checks database/table bindings across the complete staged source set, including newly staged SQLite roots. Preview allows intermediate conflicts while the user edits multiple sources; Apply rejects only a duplicate final binding. Matching-schema table/view changes preserve dependent previews, save/reopen, and source refresh. Failed collision Apply leaves the project and raw/loaded caches unchanged.
- **Review:** independent review found that checking only project sources missed collisions with a new source staged in the same session and could reject a binding another source was moving away from. Follow-up review also caught Unicode casefold and whitespace-trimming false positives. The preview-only check was removed; final staged-project validation covers the full source set while preserving SQLite's ASCII-only case folding and exact stored names.
- **Verification:** focused source-settings/session/Home/SQLite tests passed **89 tests and 46 subtests**; full pytest passed **650 tests and 471 subtests**; full unittest passed **595 tests**; compileall and `git diff --check` passed.
- **Boundary:** folder and remote source editing, schema migration, large-file performance on the minimum M1 Mac, and manual UI acceptance remain open. The local M bridge and DAX evaluator remain partial; this does not claim Power Query/Mashup or full DAX parity.

### 2026-10-12: Edit existing folder source settings

- Added a folder-source settings mode to the separate folder combine dialog. It restores file kind, recursive discovery, filename filtering, sample file, parser options, and `Source.Name` inclusion; the title and button describe applying settings, and the replacement warning is hidden.
- Edit Source Settings now stages the new folder path and full combine recipe from the Power Query ribbon and Queries context menu. The same root ID, query metadata, and applied steps survive preview and Apply. Included Reference descendants use the reviewed folder preview and follow refresh; schema/type changes remain blocked.
- Tests verify folder edit-mode controls, controller dialog routing, context-menu invocation, dependent preview, save/reopen and changed-folder refresh, plus source drift rejection that preserves project/raw/loaded caches.
- **Review:** independent review found no transaction or data-integrity blocker and caught stale status text, which was corrected.
- **Verification:** focused local-source/session/Home group **96 passed, 46 subtests passed**; full pytest **655 passed, 471 subtests passed**; full unittest **600 tests passed**; compileall and `git diff --check` passed. See [Iteration 14 sign-off](.council/VERIFICATION_SIGN_OFF_ITER14.md).
- **Boundary:** SQL Server/OData/Web source editing, schema migration, minimum-Mac performance, manual macOS acceptance, Microsoft Mashup execution, complete M, and full DAX remain open. This does not complete Power Query or semantic-model parity.

### 2026-10-12: Stage local sources in Power Query

- Added Home actions for New Source (file) and From Folder. They reuse the file-options/import-preview and folder-combine preview dialogs, but stage the source in the open Power Query session rather than committing it immediately.
- A staged local source receives its own ID and keeps the selected path, parser options, inferred types, steps, and preview. It can feed Reference/Append/Merge, be renamed, and be duplicated; Close & Apply checks the current file/folder preview before publishing source, model-table, type, and candidate state together.
- Acceptance covers session preview refresh, same-session Reference, file/folder apply, save/reopen/source refresh, cancel preserving project and caches, and changed-file rejection.
- **Verification:** focused session/M/parameters/file workflow/refresh/migration/profile tests: **201 passed**; full unittest: **570 passed**; full pytest: **625 passed and 467 subtests**; compileall and `git diff --check` passed.
- **Boundary:** only local file and folder inputs are available in this session action. SQL Server/OData/Web authoring, full Power Query Desktop ribbons, general Mashup execution, and full DAX remain open.

### 2026-10-11: Persist authored Power Query M text

- Supported M scripts that parse to the current local `transform_steps` now persist byte-for-byte as optional source metadata. The standalone Data-view editor and the multi-query Power Query session restore that text only while the query name and canonical steps still match. Comments and user-chosen binding names survive preview, Apply, save, and reopen.
- Ribbon edits, formula-bar changes, query renames, and duplicated query names invalidate mismatched authored text. Refresh continues to replay the validated local steps; it never runs the saved script through a Mashup engine.
- `.npa` format v75 migrates v74 projects without adding required fields; saved M text has a 32,000-character and null-character validation limit.
- Acceptance covers exact script restoration, standalone/session Apply, project save/reopen, source refresh, stale text fallback, and metadata validation. Focused tests and the full suite are being finalized.
- **Boundary:** This preserves supported authoring text. Arbitrary M, connectors, privacy, folding, and Microsoft Mashup execution remain unavailable.

### 2026-10-11: Guided DAX measure authoring

- The measure editor can search and insert recognized local function names, qualified references to fields in loaded model tables, and saved measure references. Validate / preview runs a draft through the existing local evaluator in the current report context without changing project data or dirty state.
- Acceptance checks function/field insertion, custom table-name escaping, a composed formula preview, and controller-side project immutability.
- **Boundary:** This adds authoring support only. The evaluator still recognizes 46 function names with partial semantics; this does not add function implementations or imply DAX compatibility.

### 2026-10-11: Duplicate/Delete Query lifecycle

- **Duplicate:** The Queries pane context menu and Home ribbon stage an independent copy with a new ID. Root-source copies retain their source settings; saved-query copies preserve their query definition, steps, descriptions, groups, load/refresh settings, and step metadata. Copies can also be duplicated again within the same open session.
- **Delete:** Deletion is staged until Close & Apply, confirms with the user, removes model/source/cache records atomically, and leaves the linked source file intact. It blocks surviving query, relationship, report-binding, calculated-table, and DAX dependencies. Query names freed by deletion can be reused by a new query in the same Apply.
- **Unavailable sources:** Non-active queries whose previews fail remain visible with the failure reason. Editing, duplication, and reference creation are disabled for those query entries; Delete remains available. Users can remove a failed dependent before deleting its parent.
- **Review fixes:** Dependency tracking includes unavailable child queries; the transaction checks deletion blockers before validating the final project and excludes deleted IDs from name collision checks.
- **Acceptance:** Duplicate/save/reopen/refresh, atomic deletion/save/reopen/refresh, dependent blockers, failed child/parent deletion, name reuse, and query navigator regressions pass. Focused lifecycle cases passed; the full suite passed **528 tests and 389 subtests**. `py_compile` and `git diff --check` passed.
- **Boundary:** This completes the staged Duplicate/Delete lifecycle only. Per-operation settings, dependency Diagram view, parameters/functions, a general Mashup runtime, and full DAX semantics remain open.

### 2026-10-11: Reference Query staged-parent and metadata review

- **Preview behavior:** A newly staged Reference Query now tracks later edits to its parent inside the same editor session. Its preview and inherited type map update when the parent is changed, including schema changes and type-only changes. A new reference is evaluated once on Apply even when **Include in report refresh** is off; later Refresh All preserves its cached result.
- **Collision and profiling fixes:** Generated reference names account for model tables and saved query names that are not in the open navigator. Commit validation rejects a manually renamed reference that collides with an existing model/query name. Column profiles use inherited types.
- **Review:** Independent code review identified parent-edit Apply failures, stale inherited types, missing-name collision checks, and profile type loss. Those cases now have regressions alongside the existing cancel, save/reopen, and refresh coverage.
- **Acceptance:** `tests/test_home_file_workflows.py` passed **36 tests and 46 subtests**; the affected query/session group passed **73 tests and 52 subtests**; the full suite passed **521 tests and 389 subtests**. `py_compile` and `git diff --check` passed.
- **Boundary:** This increment implemented Reference Query; Duplicate/Delete Query is recorded above. Diagram view, broader M, and complete DAX remain open.

### 2026-10-11: `Table.Transpose` M mapping and type-safety review

- **M authoring:** The Advanced Editor now round-trips the one-argument `Table.Transpose(previousStep)` form to the local `transpose_table` step. The optional `columns` argument remains outside the subset.
- **Safety:** Compatibility review found multiple losses after transpose: numeric-looking text can be aggregated as numeric locally, native numeric precision/equality can differ, and normalized storage merges M null with empty text. Cell-dependent M transformations after transpose are now rejected, including Group, filtering, and distinct, even with explicit casts; schema-only changes and row-position operations remain supported.
- **Acceptance:** Focused M suite passed **48 tests and 112 subtests**; the complete suite passed **517 tests and 389 subtests**. `py_compile` and `git diff --check` passed.
- **References:** Microsoft documents transpose output behavior in [`Table.Transpose`](https://learn.microsoft.com/en-us/power-query/transpose-table) and numeric list aggregation in [List functions](https://learn.microsoft.com/en-us/powerquery-m/list-functions).
- **Boundary and next:** This is local parser/replay validation only; no Microsoft Mashup runtime is present. Conditional Column, keep-duplicates, negative text filters, per-operation settings, query duplicate/reference/delete, the dependency diagram, broad M runtime coverage, and full DAX remain open.

### 2026-10-11: M culture-aware type conversion

- **M authoring:** `Table.TransformColumnTypes` now accepts an optional literal culture string and maps supported columns into the existing `convert_type_using_locale` steps. The local bridge supports whole/decimal number, date, datetime, and time types; culture names are canonicalized and validated by the local conversion validator. Culture records and types outside this local set remain unsupported.
- **Acceptance:** Focused `tests/test_power_query_m_editor.py` passed **46 tests and 107 subtests**. Cases cover multi-column calls, multiple cultures, all five type families, canonical round-trip, unsupported cultures/types, Currency.Type rejection, default ties-to-even rounding, signed Int64 boundaries/overflow, and decimal Double overflow/underflow handling for both locale and invariant conversions. The direct controller diagnostic regression now reports only the remaining unsupported transpose step. Full `PYTHONPATH=. pytest -q` passed **515 tests and 385 subtests**; `python3 -m py_compile analytics_studio/power_query_m.py analytics_studio/transformations.py` and `git diff --check` passed.
- **References:** Microsoft specifies culture-aware type conversion in [`Table.TransformColumnTypes`](https://learn.microsoft.com/en-us/powerquery-m/table-transformcolumntypes), ties-to-even as the default for [`Int64.From`](https://learn.microsoft.com/en-us/powerquery-m/int64-from), and fixed-decimal rounding/range for [`Currency.From`](https://learn.microsoft.com/en-us/powerquery-m/currency-from), and the [M number value specification](https://learn.microsoft.com/en-us/powerquery-m/m-spec-values).
- **Boundary:** This is a literal-culture M subset, not general M evaluation. The bridge still runs locally and does not provide Microsoft's Mashup engine or full Power Query compatibility.
- **Next:** Implement another bounded M shape with direct-versus-M value/type replay, or prioritize query-session gaps. Conditional Column, transpose, keep-duplicates, negative text filters, per-operation settings, and query duplicate/reference/delete actions remain open. DAX compatibility remains a separate open program.

### 2026-10-11: M delimiter extract, split, and merge mappings

- **M authoring:** Added exact emitter/parser forms for before/after/between delimiter extraction, first-delimiter split, every-delimiter split, split into rows, and merge columns. The every-delimiter width is derived from the current table, remains at least two output columns, and re-evaluates as data changes. Extraction and row splitting coalesce null/empty inputs to empty text; M literal and identifier escapes are encoded and decoded.
- **Safety boundary:** The parser accepts literal delimiters, numeric zero-based occurrences, `QuoteStyle.None`, the exact null-coalesced `Text.Split` plus `Table.ExpandListColumn` row shape, and `Combiner.CombineTextByDelimiter` only. It rejects relative-from-end occurrence selectors, non-text input types, numeric unpivot values without explicit text conversion, numeric custom-column results, known-invalid nested calls and arguments, explicit nulls in required text-function parameters and unsupported precision positions, null conditional predicates, text operations after Pivot, text operations after schema reshaping without an explicit text conversion, fixed-width all-delimiter splits, quote-aware forms, and other unsupported shapes. Group min/max retain the type of unpivoted values. M character escapes are decoded inside custom expressions and quoted field references. Supported nullable function positions are preserved. The local model continues to collapse source null/empty values and does not run Microsoft's Mashup engine.
- **Acceptance:** `PYTHONPATH=. pytest -q tests/test_power_query_m_editor.py` passed **42 tests and 88 subtests**. Cases cover multi-character delimiters, repeated/leading/trailing/adjacent separators, empty tables, data-dependent width growth, row expansion order, merge separators and selected-column order, output headers/type maps, M escape round trips including custom expressions, null normalization, Group type propagation, custom-column type validation, invalid nested calls and known-invalid arguments alongside unknown fields, explicit-null argument rejection and nested null propagation, null-condition/precision rejection, and unsupported index/fixed-width shapes. `PYTHONPATH=. pytest -q` passed **511 tests and 365 subtests**.
- **References:** Microsoft documents the occurrence selectors and relative end-index behavior in [Text.BeforeDelimiter](https://learn.microsoft.com/en-us/powerquery-m/text-beforedelimiter), [Text.AfterDelimiter](https://learn.microsoft.com/en-us/powerquery-m/text-afterdelimiter), and [Text.BetweenDelimiters](https://learn.microsoft.com/en-us/powerquery-m/text-betweendelimiters); split width/defaults and row expansion in [Table.SplitColumn](https://learn.microsoft.com/en-us/powerquery-m/table-splitcolumn), [Splitter.SplitTextByEachDelimiter](https://learn.microsoft.com/en-us/powerquery-m/splitter-splittextbyeachdelimiter), [Text.Split](https://learn.microsoft.com/en-us/powerquery-m/text-split), and [Table.ExpandListColumn](https://learn.microsoft.com/en-us/powerquery-m/table-expandlistcolumn); and merge behavior in [Table.CombineColumns](https://learn.microsoft.com/en-us/powerquery-m/table-combinecolumns).
- **Next at this historical increment:** Continue mapping remaining exposed local operations through the same parser/output/type/lifecycle gate; Conditional Column, locale conversion, transpose, keep-duplicates, and negative text-filter forms remained open then. The DAX evaluator and broader session parity also remained open.

### 2026-10-11: M row-window, blank-row, and text-reversal mappings

- **M authoring:** Added parser/emitter round trips for `Table.RemoveLastN`, `Table.Range`, and `Table.AlternateRows`, mapping them to remove-bottom, keep-range, and remove-alternate row steps. The parser handles `RemoveLastN`'s omitted count and `Range`'s omitted/null count; `Range` uses the local engine's 100,000-row ceiling for the latter case. `Table.TransformColumns` maps `Text.Reverse` to Reverse Text. Remove Blank Rows emits a constrained `Table.SelectRows` expression using `Record.FieldValues`, `List.RemoveMatchingItems`, and `List.IsEmpty`; it removes null/empty strings and preserves whitespace-only text.
- **Acceptance:** Focused `tests/test_power_query_m_editor.py` passed **30 tests and 58 subtests**, comparing canonical steps, direct/local M-replayed rows, and type maps and rejecting a whitespace near-match that would change behavior. Microsoft documents row removal, range, alternating rows, text reversal, column transforms, and the list/record operations in the [RemoveLastN](https://learn.microsoft.com/en-us/powerquery-m/table-removelastn), [Range](https://learn.microsoft.com/en-us/powerquery-m/table-range), [AlternateRows](https://learn.microsoft.com/en-us/powerquery-m/table-alternaterows), [Text.Reverse](https://learn.microsoft.com/en-us/powerquery-m/text-reverse), [Table.TransformColumns](https://learn.microsoft.com/en-us/powerquery-m/table-transformcolumns), [List functions](https://learn.microsoft.com/en-us/powerquery-m/list-functions), [List.RemoveMatchingItems](https://learn.microsoft.com/en-us/powerquery-m/list-removematchingitems), and [Record.FieldValues](https://learn.microsoft.com/en-us/powerquery-m/record-fieldvalues) references.
- **Full regression:** `QT_QPA_PLATFORM=offscreen python3 -m pytest -q` passed **499 tests and 335 subtests**.
- **Boundary:** M execution still uses the local bounded engine, not Microsoft's Mashup runtime. Split/extract/merge, Conditional Column, locale conversion, transpose, keep-duplicates, and negative text-filter variants remain outside the tested M bridge.

### 2026-10-11: Saved-query load and report-refresh settings

- **Query Settings:** Added independent **Enable load** and **Include in report refresh** controls for saved queries in the separate Power Query session. These settings are staged with query edits and commit atomically; turning off load for the active query switches the session to another loaded source when available.
- **Persistence and regression:** The flags save and reopen, and the regression toggles both off and on through project reopen. Query switching now blocks widget signals while repopulating the form so the previous query's controls cannot overwrite the newly selected query's flags.
- **Acceptance:** Focused query lifecycle test passed (**1 test**). The full `QT_QPA_PLATFORM=offscreen python3 -m pytest -q` suite passed **496 tests and 327 subtests**.
- **Boundary:** Duplicate/reference/delete commands in the session, per-operation dialogs, Diagram view, parameters/functions, privacy/credential authoring, broad M support, and a general M runtime remain open. This local M editor and the local DAX subset still do not establish Power BI parity.

### 2026-10-11: Power Query M Group By, Pivot, and unpivot mappings

- **M authoring:** The Advanced Editor parser/exporter now round-trips bounded `Table.Group`, `Table.Pivot`, `Table.Unpivot`, and `Table.UnpivotOtherColumns` forms into the local transform model. Group By supports sum, average, median, min, max, row count, distinct-row count, and distinct-value count; Pivot supports current-table category discovery with sum, average, median, min, max, count, or no aggregation.
- **Acceptance:** Focused `tests/test_power_query_m_editor.py` passed **27 tests and 50 subtests**. The direct-versus-M matrix checks canonical steps, headers, rows, local type maps, and rejection of static/unrelated pivot category lists. `QT_QPA_PLATFORM=offscreen python3 -m pytest -q` passed **495 tests and 327 subtests**.
- **Boundary:** This bridge still does not run the Microsoft Mashup engine. M grouping comparers, local group ordering controls, optional aggregate type declarations, many other functions/operations, local null/empty distinctions, and external runtime equivalence remain unsupported or unverified.

### 2026-10-11: Query names and descriptions

- **Query Settings:** Added editable names and descriptions alongside query groups. Query names are validated for length/control characters and uniqueness within the editor session; descriptions have a bounded length.
- **Model consistency:** Renaming a loaded query renames its model table and rewrites quoted or unquoted DAX table references in measures, calculated columns, and calculated-table definitions. Stable source IDs preserve relationships and query dependencies. Source display labels remain separate from model query names.
- **Persistence and acceptance:** Query names/descriptions save and reopen. A lifecycle test renames a source used by both a measure and a DISTINCT calculated table, verifies rewritten formulas and refreshed output, and checks measure evaluation after reopen. The full workspace suite passed **491 tests and 319 subtests**.
- **Boundary:** This does not add full DAX evaluation or query editor parity. The local DAX function set remains partial; per-operation settings surfaces, Diagram view, parameters/functions, and full M are still open.

### 2026-10-11: Applied-step names and descriptions

- **Authoring:** Applied Steps now offers Rename Step and Edit Description from the step context menu. Custom labels and descriptions follow a step when it is moved, update when the selected step's operation changes, and remain independent of the local transformation expression.
- **Persistence and validation:** Per-step metadata is stored alongside a source's transformation list, validated against step count and bounded text lengths, and saved/reopened with the project. Empty metadata is omitted to preserve the existing project shape. M edits retain metadata only for unchanged operations at the same index.
- **Acceptance:** The focused schema/editor/session run passed **97 tests and 103 subtests**. The full workspace suite passed **489 tests and 319 subtests**.
- **Boundary:** Per-operation settings dialogs, query diagram view, parameters/functions, privacy/credential authoring, and a full M runtime remain open. Query-level names and descriptions were added in the later query-properties increment. The DAX evaluator remains a partial local subset.

### 2026-10-11: Multi-query Power Query session shell

- **Session workflow:** Added a Queries navigator with separate step state and previews, Query Settings for assigning/removing query groups, a supported single-line formula bar, selected-step preview, column quality/profile tabs, and explicit Close & Apply.
- **Freshness and transaction behavior:** Local files refresh when the session opens. Included query previews are built in dependency order. Excluded queries retain their last evaluated result through upstream changes, and included downstream queries use that cached result. Query-step and source snapshots are validated before applying; independent edits commit together, while staged dependent step edits are rejected.
- **Preview/profiling behavior:** Selecting an Applied Step shows that stage's rows and profile. Blank values do not count as distinct or unique values. Equal-frequency profile values have a stable case-folded/original-value order; cell errors are labeled not tracked because the local text model does not preserve them.
- **Acceptance:** Focused session, M, and profile run passed **52 tests and 88 subtests**. Full `QT_QPA_PLATFORM=offscreen python3 -m pytest -q` passed **487 tests and 319 subtests**. Added regressions for rebuilding an unchanged dependent query after an upstream transformation edit and for preserving raw-source snapshots when query-settings validation fails. Profile assertions verify the selected applied step updates quality and distribution values.
- **Boundary:** This is a useful session shell, not a full Power Query Desktop editor. Per-operation step settings, dependency Diagram view, parameters/functions, privacy/credential editing, query folding, many local operations in M, and a general Mashup runtime remain open. Query and Applied Step names/descriptions are now implemented. The DAX evaluator still has 46 recognized function names with partial semantics.
- **Next:** Continue the query-settings/step-management surface and expand M mappings only with parser, output/type, and lifecycle acceptance. Complete the DAX engine feasibility decision before claiming broader DAX compatibility.

### 2026-10-11: Power Query M bridge safety and compatibility reporting

- **All-blocker diagnostics:** Added an emitter/parser-based representability report. Transform Data and the direct Advanced Editor command now show every unsupported saved step with its position and operation, leave the command discoverable, and do not construct an editor from a lossy partial sequence.
- **Preview integrity:** Editing M clears the previous preview, steps, and candidate immediately. Failed parsing/replay leaves Apply disabled. Apply re-runs the current script and accepts only its successful replay.
- **Round-trip fixes:** Single and multi-column sort directions now preserve `asc`/`desc`; the `number` type alias canonicalizes to `decimal_number`; `Table.AddIndexColumn` supports its default start/increment; and non-text `Table.AddColumn` types are rejected instead of silently discarded by the text-cell engine.
- **Acceptance:** The table-driven M test covers every operation shape emitted by this local bridge and compares direct versus M-replayed candidate output and type maps. `QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/test_power_query_m_editor.py tests/test_home_file_workflows.py` passed **30 tests and 88 subtests**.
- **Full regression run:** `QT_QPA_PLATFORM=offscreen python3 -m pytest -q` passed **466 tests and 319 subtests**.
- **Boundary:** This closes a safety gate for the bounded local M subset. It does not add the separate Power Query session shell, a general M runtime, all 46 local transform operations to M, or complete DAX. See [POWER_QUERY_EDITOR_AUDIT.md](POWER_QUERY_EDITOR_AUDIT.md) and [DAX_COMPATIBILITY_CONTRACT.md](DAX_COMPATIBILITY_CONTRACT.md).
- **Next:** Implement the query navigator/settings/formula bar/selected-step/profile workflows, and decide the DAX runtime/support target before adding more function names.

### 2026-10-09: Gauge visual lifecycle

- **Fields and aggregation:** Enabled the Gauge gallery tile with Value, Minimum, Maximum, Target, and Tooltips wells. Each value well accepts a separate Sum, Count, or Average aggregation.
- **Rendering and interaction:** Added a semicircular range display, value label, optional target tick, and a linked Highlight marker calculated from the selected source rows.
- **Persistence:** Well bindings, aggregation choices, and visual type survive save/reopen; changed-source refresh recalculates the gauge. The QML lifecycle test checks the actual Gauge card binding after a visual refresh.
- **Verification:** Gauge and Combo lifecycle focus tests passed **2 tests**. Full `PYTHONPATH=. python3 -m pytest -q` passed **442 tests and 231 subtests**.
- **Next:** Add a KPI visual with a trend line, current indicator, target, and lifecycle coverage.

### 2026-10-09: KPI visual lifecycle

- **Fields and calculations:** Enabled Indicator, Trend axis, and Target goals wells. Sum, Count, and Average work for indicator and target values; the latest sorted trend-axis category supplies the displayed indicator and goal.
- **Rendering and interaction:** Added a latest-value card with target status and a line trend. Clicking a trend period selects that category; linked Filter and Highlight modes update KPI values and highlights.
- **Persistence:** Well bindings and aggregation choices survive save/reopen, and source refresh recalculates the trend, current indicator, and target.
- **Verification:** KPI lifecycle passed **1 test**. Full `PYTHONPATH=. python3 -m pytest -q` passed **443 tests and 231 subtests**.
- **Next:** Add a local coordinate bubble Map with location, latitude, longitude, size, and legend fields.

### 2026-10-09: Coordinate bubble Map lifecycle

- **Fields and rendering:** Enabled the Map gallery tile with Location, Latitude, Longitude, Size, Legend, and Tooltips wells. Valid coordinate rows render on a locally fitted latitude/longitude grid; invalid or out-of-range coordinates are skipped. Size scales bubbles and Legend colors groups.
- **Interaction:** Clicking a location selects its category. Linked Filter limits visible points; linked Highlight dims unselected points and outlines selected locations.
- **Persistence:** Field bindings and Map type survive save/reopen; changed-source refresh reloads valid points and marker sizes.
- **Scope:** This is a local coordinate map. It does not geocode labels or load geographic basemaps. A first local filled/shape map slice is now implemented; Azure Maps and other network-backed providers remain queued.
- **Verification:** Map lifecycle passed **1 test**. Full `PYTHONPATH=. python3 -m pytest -q` passed **444 tests and 231 subtests**.
- **Next:** Complete runtime, save/reopen, and refresh acceptance for the local filled/shape map implementation.

### 2026-10-09: Blank visual chooser and chart acceptance

- **Chooser:** Insert → New visual and Home → New visual now open the Build gallery for blank bar, column, line, area, pie, donut, funnel, table, card, and slicer visuals. New visuals get unique titles and non-overlapping initial placement.
- **Area chart:** Enabled the Area gallery tile, rendered a filled area with category-ordered points, and kept selected-value highlight markers visible. Line and Area series use category order so connecting lines follow the X-axis sequence.
- **Pie and Donut charts:** Added per-category slices, a bounded category legend, percentage labels, highlight dimming, and category hit testing. Donut hole clicks do not select a category.
- **Lifecycle:** Offscreen QML acceptance verifies the visual type and field-bound series reach the chart card; pie/donut clicks select and clear categories; field bindings, labels, and legend settings survive project save/reopen.
- **Verification:** The chooser and static visual focus tests passed **2 tests**. Full `python3 -m pytest -q` passed **425 tests and 229 subtests**.
- **Next:** Add a blank Card visual with field aggregation, formatting, and save/reopen coverage.

### 2026-10-09: Table visual lifecycle

- **Fields and rows:** Added a Table visual with a Fields well, loaded-row display, horizontal and vertical scrolling, and a 50-row display cap. Row filtering uses the first field as its category; peer visual highlighting marks matching rows.
- **Interaction and persistence:** Row selection participates in cross-filtering; save/reopen and changed-source refresh preserve the type and field bindings.
- **Verification:** Chooser, static visual, and Table visual focus tests passed **3 tests**. Full `python3 -m pytest -q` passed **426 tests and 229 subtests**.
- **Next:** Add a blank Card visual with field aggregation, formatting, and save/reopen coverage.

### 2026-10-09: Card visual lifecycle

- **Values:** Blank Card visuals bind one field and display Sum, Count, or Average; the field well exposes the aggregation menu. Existing KPI cards display their built-in values through the same Card renderer.
- **Interactions:** Cards accept visual filters and show selected values for Highlight interactions. They do not offer source interaction controls because an aggregate card has no category selection.
- **Persistence:** The field and aggregation survive save/reopen; changed-source refresh updates the card value.
- **Verification:** Card visual lifecycle passed; full `python3 -m pytest -q` passed **427 tests and 229 subtests**.
- **Next:** Add a Funnel chart with value-scaled segments, category labels, selection, and save/reopen coverage.

### 2026-10-09: Funnel chart lifecycle

- **Rendering:** Enabled the Funnel gallery tile and rendered descending category values as tapered segments; category labels remain visible and data labels show values when enabled.
- **Interaction and persistence:** Segment hit testing maps clicks back to the correct category for cross-filtering. X/Y field bindings persist through save/reopen.
- **Verification:** Funnel and Card focused tests passed; full `python3 -m pytest -q` passed **428 tests and 229 subtests**.
- **Next:** Add Stacked Column and Stacked Bar charts with Legend grouping and segment-level interactions.

### 2026-10-09: Stacked and 100% stacked chart lifecycle

- **Rendering and binding:** Enabled Stacked Bar, Stacked Column, Stacked Area, 100% Stacked Bar, 100% Stacked Column, and 100% Stacked Area. X-axis categories group their Y-axis values by the optional Legend field; percentage variants normalize each category to 100% while retaining underlying aggregate values for labels and highlights.
- **Interaction and aggregation:** Clicking a stack segment selects its category. Sum, Count, and Average are applied within each category/Legend pair, and peer Highlight interactions render the selected values over dimmed stacks.
- **Persistence:** Legend bindings and chart types survive save/reopen, and changed-source refresh recomputes segment values. The lifecycle test covers all six chart types through the QML canvas.
- **Verification:** Stacked chart lifecycle passed; full `python3 -m pytest -q` passed **429 tests and 229 subtests**.
- **Next:** Add a Waterfall chart with running totals, category selection, and save/reopen coverage.

### 2026-10-09: Waterfall chart lifecycle

- **Rendering and values:** Enabled the Waterfall gallery tile with X/Y wells. Bars move a running total across ordered categories; positive and negative contributions use separate colors, and connectors show each intermediate total.
- **Interaction:** Clicking a contribution selects its category. Linked Highlight interactions dim the base contributions and overlay selected values.
- **Persistence and aggregation:** Sum, Count, and Average work in the value well. The type and fields survive save/reopen, and changed-source refresh recomputes the series.
- **Verification:** Waterfall lifecycle passed; full `python3 -m pytest -q` passed **430 tests and 229 subtests**.
- **Next:** Add a Ribbon chart with category ranking, Legend grouping, selection, and save/reopen coverage.

### 2026-10-09: Ribbon chart lifecycle

- **Rendering and ranking:** Enabled Ribbon with X-axis periods, Y-axis values, and Legend categories. Each period sorts categories by value, then connects each category's band across periods so rank changes remain visible.
- **Interaction:** Clicking a ribbon selects its X-axis category; linked Highlight interactions dim the full ribbons and overlay selected values.
- **Persistence:** Field bindings, chart type, and legend settings survive save/reopen; changed-source refresh recomputes category ranks and values.
- **Verification:** Ribbon lifecycle passed; full `python3 -m pytest -q` passed **431 tests and 229 subtests**.
- **Next:** Add a Treemap visual with area-scaled categories, selection, and save/reopen coverage.

### 2026-10-09: Treemap visual lifecycle

- **Rendering:** Enabled the Treemap gallery tile with X/Y field wells. Positive values determine tile area; tiles are arranged largest first, with category labels shown when there is enough room and values available as data labels.
- **Interaction:** Clicking a tile selects its category. Incoming highlights dim unrelated tiles and retain the selected category colors.
- **Persistence:** The visual type, field bindings, and data-label setting survive save/reopen; changed-source refresh re-sorts and re-sizes the tiles.
- **Verification:** Treemap lifecycle passed; full `python3 -m pytest -q` passed **432 tests and 229 subtests**.
- **Next:** Add a Matrix visual with row/column grouping, aggregated cells, selection, and save/reopen coverage.

### 2026-10-09: Matrix visual lifecycle

- **Field wells and values:** Enabled Rows, Columns, Values, and Tooltips wells. One row field and one column field pivot the selected value field into matrix cells; Sum, Count, and Average are supported.
- **Interaction:** Clicking a row selects its group, and incoming Highlight interactions mark matching matrix rows.
- **Persistence:** Group fields, value aggregation, and matrix type survive save/reopen; changed-source refresh recomputes grouped cells.
- **Verification:** Matrix lifecycle passed; full `python3 -m pytest -q` passed **433 tests and 229 subtests**.
- **Next:** Add a Scatter chart with numeric X/Y fields, category grouping, point selection, and save/reopen coverage.

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
- `.npa` v73 persistence for source identities/options, column types, saved transformations and queries, relationships, filters, measures, field bindings and aggregation choices, visual interactions, groups, report theme, button URL settings, and related model metadata. File-backed rows remain linked to their source; inline rows are embedded.
- SQL Server, anonymous OData v4, and anonymous HTTPS Web import subsets are implemented with mocked/dialog/project lifecycle coverage. Live database or endpoint acceptance remains open.

### Query management and shaping — 51/51 graph-listed capabilities passed lifecycle acceptance

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
51. Create a typed Reference Query from the Power Query Home ribbon; commit/cancel, save/reopen, and upstream refresh lifecycle.

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
- The evaluator is still a local DAX subset. A simple measure reference inside an iterator now has a focused row-context transition test; broader DAX, `ALLSELECTED` visual-axis behavior, and filter-clear/time-intelligence combinations remain open.

### Report and application foundations

- New/Open/Save/Save As, report-page creation, supported revenue chart switching among bar/column/line, core pane and zoom controls, Data and Model views, and a bounded Data-view preview.
- Field wells bind supported visuals to loaded data; Sum/Count/Average choices and Filter/Highlight/None chart interactions pass lifecycle acceptance. Comprehensive visual creation/editing, formatting, shapes, buttons, text boxes, and broader visual workflows remain queued.

## Previous recorded increment — 2026-10-10

- Added **Edit** and **Delete** actions to saved DAX measures. Formula edits are prefilled, validated, and saved transactionally; renames and deletes are rejected if they break dependent measures. Measure actions do not create or modify report visuals.
- Added a Power Query **Advanced Editor** with a safe, linear `let … in` M subset. Supported table calls are parsed to existing applied steps, previewed with the local transformation engine, and saved in the same refreshable step sequence. Unsupported M syntax is rejected; no arbitrary script execution or full M runtime is claimed.
- Added direct Home-ribbon access in Data view to **Advanced Editor (M)**, **Append queries**, **Merge queries**, **New DAX measure**, **Quick measure**, **New column**, and **New table**. Commands are disabled with an explanation until their table requirements are met. The Modeling ribbon's calculated-table action now routes to its dialog; all non-disabled ribbon action IDs have an explicit handler.
- Kept the Data-view header focused on table and cleaning controls so DAX and M actions appear in the ribbon where users expect to find them.
- Added a six-tab ribbon inside the Power Query Editor: **Home**, **Transform**, **Add Column**, **View**, **Tools**, and **Help**. Direct ribbon buttons route all 46 supported transformation operations to their existing parameter controls. View toggles the preview and applied-step panes and opens Advanced Editor; Tools adds, updates, removes, and reorders steps. Unavailable features such as the formula bar, column profiling, and full M execution are documented rather than represented as working commands.
- Fixed empty parameter labels appearing for operations that do not use those controls.
- Added automated checks for M preview and round-trip, unsafe/unsupported scripts, DAX edit/delete dependency handling, Model-view actions, and measure save/reopen.
- Focused Power Query dialog run: **20 passed, 46 subtests passed**. Full `QT_QPA_PLATFORM=offscreen python3 -m pytest -q`: **457 passed, 277 subtests passed**.
- **Next:** expand high-value M transformations and DAX authoring/evaluation compatibility, with a tested increment before returning to the queued visual roadmap.

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

### 2026-10-08: Static Visual Components (G1.3 implementation)
* **Static Components Mapping:** Connected the QML 'Elements' Tab Ribbon for Images, Text boxes, and the full multi-category Shape palette system to instantiate into the abstract visual schema.
* **Component Renderers:** Bound `TextArea`, Vector `ShapeGlyph`, and fallback icon structures to overlay appropriately using absolute layouts on instantiation. Text boxes are selectable and dynamically wrapped into the absolute selection engine bounds.
* **Status Change:** 7.1.3 implementation is present; its acceptance remains pending. Phase G1 remains active while the visual and field-well workflows are verified.

### 2026-10-08
- **7.2 Field Wells and Data Binding**: Added field-well bindings and Python-side aggregation for loaded data. End-to-end field binding and visual update acceptance remains open.
- **7.3 Formatting and Properties**: Added QML controls for general title properties and chart color configuration. Broader formatting behavior and lifecycle acceptance remain open.
- **7.3.3 Format Painter and Clipboard**: Added visual and format copy/apply paths; their full workflow acceptance remains open.
- **7.4.1 Z-order and Grouping**: Added depth-order commands for visuals. Grouping and ungrouping remain stubs.
- **7.4.2 Themes**: Added theme choices and color state for Default, Executive, High Contrast, and Sunset; cross-visual persistence and rendering acceptance remain open.
- **7.4.3 Buttons and Actions**: Added a basic external URL action to button visuals; broader action types and workflow acceptance remain open.

### 2026-10-09: Verification audit and corrections

- **8.1 Cross-filtering:** Replaced the mocked `self._tables`/pandas path with filters built from loaded model-table rows and the actual QML field-well shape. Dynamic visual series now consume report, page, visual, and cross-filter context. Selections remain transient and do not mark the project dirty. Controller and offscreen QML tests cover chart/slicer clicks, peer updates, clearing, selected-state rendering, page-filter interaction, month formats, page/project transitions, visual deletion, and recovery from relationship errors while peer rows fail closed. Cross-highlighting and configurable interaction behavior are not implemented.
- **Slicer canvas fix:** Removed a duplicate QML slicer delegate that rendered two overlapping lists for one slicer. The regression test now requires exactly one list and verifies click-to-filter behavior.
- **Transient interaction lifecycle:** Clear cross-filter selections when changing, adding, duplicating, or deleting the active page, replacing the project, or deleting the source visual. Refresh report contexts after visual add/delete so removed selections cannot remain in cached peer results.
- **Relationship-error recovery:** Keep the source visual's own choices available so a user can deselect after a peer relationship error; peer visuals remain empty until the transient selection is cleared.
- **Interaction performance:** Cache each visual's report filter context until report state or its visual configuration changes. A regression test verifies repeated series reads reuse relationship propagation and a cross-filter refresh invalidates the cache. Large-row-count and many-visual timing still needs measurement.
- **9. Security and Governance:** The previous RLS claim was incorrect. The production controller had no `_tables` attribute, and 21 injected role branches referenced missing data or undefined variables. Removed those branches. Role preview and RLS are unavailable; the legacy controller call now reports that clearly, and the Manage roles/View as actions are disabled. The current code does not enforce data security.
- **10. Service and Collaboration:** Publishing and service collaboration are unavailable. Disabled the Publish action; there is no service publishing backend.
- **11. Mobile, Paginated, Report Server:** These capabilities are unavailable. Disabled the Mobile layout action; there is no mobile report layout, RDL, or Report Server implementation.
- **12. Developer, Embedded, Fabric, AI:** Embedding, Fabric integration, Q&A, and Copilot are unavailable. Disabled Q&A setup; no generative or service workflow is connected.
- **Verification:** Full `PYTHONPATH=. pytest -q` run passed **396 tests and 229 subtests** on 2026-10-09. `tests/test_report_interactions.py` passed **14 tests**. The prior 385-test snapshot and unsupported Phase 9–12 completion claims are superseded by this audit.

### 2026-10-09: Field wells, aggregation, and visual interactions

- **Field binding:** Bound selected fields to the active model table and added Y-axis Sum, Count, and Average choices. Lifecycle coverage checks blanks and invalid values, default Sum, field removal, project save/reopen, and changed-source refresh. The QML menu and button state are covered offscreen.
- **Cross-highlighting and configuration:** Added source-to-target Filter, Highlight, and None modes in the Build visual pane. Filter remains the default; Highlight retains the target series and displays selected chart values; None suppresses the target response. Interaction settings persist by visual IDs, while selected categories remain transient. Removed visuals also remove their saved pair rules.
- **Project format:** v68→v69 supports saved field aggregation values; v69→v70 adds page-level visual interaction rules. Both migrations preserve existing visual and report state.
- **Verification:** The focused field-well, interaction, migration, and report-interaction group passed **37 tests**. Full `python3 -m pytest -q` passed **407 tests and 229 subtests**.
- **Next:** Accept visual properties and formatting controls, then continue with Format Painter/clipboard and advanced authoring commands.


### 2026-10-09: Visual properties, data colors, labels, and legends

- **General properties:** Title edits rebind selected-visual state and saved visual filters; geometry accepts finite values with bounded position and size; primary color validates as `#RRGGBB`. These values save and reopen.
- **Chart formatting:** The Format pane exposes saved Data Labels and Legend toggles. Chart cards draw values for the supported single series and show a legend keyed by the Y-axis field. The primary color, label setting, legend setting, and Y-axis legend name are covered by offscreen QML binding checks.
- **Project format:** v70 → v71 adds `show_data_labels` and `show_legend` flags with false defaults; validation rejects non-boolean values. Earlier visual properties and interaction settings are preserved.
- **Verification:** The focused visual properties, migration, field-well, interaction, and report-interaction group passed **42 tests**. Full `python3 -m pytest -q` passed **412 tests and 229 subtests**.
- **Next:** Accept Format Painter and clipboard workflows, then continue with advanced authoring commands.


### 2026-10-09: Format Painter and visual clipboard

- **Copy, Cut, and Paste:** Copying and cutting retain an in-memory visual snapshot across report refresh. Paste gives the duplicate a new ID, unique title, and a 20-pixel offset; repeated paste and Cut→Paste keep the field bindings and aggregations. New and Open clear the in-app clipboard.
- **Format Painter:** Copying enables the painter and notifies QML. A target receives the source primary color, data-label visibility, and legend visibility once; its chart type and placement remain intact. These properties persist after save/reopen.
- **Verification:** The focused report-authoring group passed **44 tests**. Full `python3 -m pytest -q` passed **414 tests and 229 subtests**.
- **Next:** Accept z-order, inspect the grouping stubs, and continue with themes and button actions.

### 2026-10-09: Z-order and visual grouping acceptance

- **Z-order:** Arrange commands move visuals one position or to either end. Boundary commands are no-ops and leave project dirty state unchanged; the saved list order survives reopen.
- **Grouping:** Shift-click selects multiple visuals; Group and Ungroup operate on selected IDs, group movement applies the same delta to every member, and deleting a member dissolves a one-item remainder. Group membership persists through save/reopen.
- **Project format:** v71→v72 adds optional page-scoped `group_id`; pasted visuals start ungrouped.
- **Verification:** Focused report-authoring group passed **49 tests**. Full `python3 -m pytest -q` passed **419 tests and 229 subtests**.
- **Next:** Persist report themes and accept button URL actions, then verify static components.

### 2026-10-09: Report themes and button URL actions

- **Themes:** Default, Executive, High Contrast, and Sunset apply their primary color across report visuals. The report stores the selected theme; later visual refresh and project reopen preserve it.
- **Buttons:** Button text and HTTP(S) URL fields are editable and persist across reopen. Double-click and Control-click route to the desktop URL handler, which rejects non-HTTP(S) targets.
- **Project format:** v72→v73 saves the report theme and migrates older projects to Default.
- **Verification:** Theme/button and migration focus group passed **28 tests**. Full `python3 -m pytest -q` passed **423 tests and 229 subtests**.
- **Next:** Enable the Insert → New visual chooser for supported blank visuals and cover its QML command route.

### 2026-10-09: Static report components

- **Text boxes:** Enabled both Home and Insert ribbon commands. Inline TextArea edits update the project; text persists across save/reopen.
- **Images:** Enabled local image selection and rendering. Image paths save relative to the project when possible and resolve again on open; the Format pane can replace or clear the path.
- **Shapes:** Enabled the shape palette and its shape buttons. Vector shapes remain selectable, resizable, and persist with visual placement.
- **Verification:** Report-authoring group passed **54 tests**. Full `python3 -m pytest -q` passed **424 tests and 229 subtests**. QML acceptance loaded an image containing spaces, edited text on-canvas, inserted a shape, and verified save/reopen.
- **Next:** Add a chooser for supported blank visual types, starting with bar, column, and line charts.

### 2026-10-09: Scatter chart lifecycle

- **Fields and rendering:** Added numeric X-axis and Y-axis point plotting, optional Legend coloring, Details labels, a bounded numeric grid/legend, and nearest-point selection. Each scatter well accepts one field; raw point values are used without an aggregation selector.
- **Interactions and persistence:** Scatter point selection participates in cross-filtering through Details, then Legend, then X-axis. Incoming Highlight interactions retain all points and emphasize the selected subset. Legend/Details bindings and visibility persist across save/reopen; changed-source refresh updates the plotted coordinates.
- **Verification:** `python3 -m pytest -q tests/test_scatter_visual_lifecycle.py` passed **1 test**. Full `python3 -m pytest -q` passed **434 tests and 229 subtests**.
- **Next:** Expand local DAX support for same-call Boolean and time-intelligence filter combinations (roadmap item 6.5.6.3.15).

### 2026-10-09: Same-call Boolean and time-intelligence filters

- **Filter evaluation:** Accepted `CALCULATE` calls that apply marked-date time-intelligence filters together with typed Boolean filters. Replacement filters preserve the date range and unrelated filters; multiple Boolean columns combine, and `KEEPFILTERS` intersects the existing page filter.
- **Lifecycle:** Added a controller acceptance case that saves combined YTD measures, reopens them after the source changes, and verifies updated totals while date and Region page filters remain active.
- **Verification:** `python3 -m pytest -q tests/test_totalytd.py tests/test_calculate_boolean_filters.py` passed **102 tests and 92 subtests**. Full `python3 -m pytest -q` passed **435 tests and 229 subtests**.
- **Next:** Combine `REMOVEFILTERS` with supported time-intelligence filters in one `CALCULATE` call.

### 2026-10-09: Mixed `REMOVEFILTERS` and Boolean filters

- **Filter evaluation:** A single `CALCULATE` call can now clear all, one loaded table, or selected columns with `REMOVEFILTERS`, then apply bounded typed Boolean filters. The Boolean filters replace cleared or existing target columns; `KEEPFILTERS` still intersects the surviving filter on its target column. `ALL` and other filter modifiers remain sole arguments.
- **Validation:** Mixed table-valued `FILTER` and time-intelligence arguments are rejected with clear messages; their ordering/context semantics are not implemented in this increment.
- **Lifecycle:** Added clear-column, clear-table, and clear-all cases with multiple Boolean predicates, `KEEPFILTERS`, save/reopen, and changed-source recalculation.
- **Verification:** `python3 -m pytest -q tests/test_calculate_boolean_filters.py` passed **60 tests and 94 subtests**. Full `python3 -m pytest -q` passed **437 tests and 231 subtests**.
- **Next:** Combine `REMOVEFILTERS` with supported time-intelligence filters in one `CALCULATE` call.

### 2026-10-09: Mixed `REMOVEFILTERS` and time-intelligence filters

- **Filter evaluation:** A mixed call computes its supported time-intelligence date set from the incoming context, clears the selected filters, then reapplies the date set and Boolean filters. The result preserves the original time selection even when the modifier clears that date column, its table, or all filters.
- **Lifecycle:** Added clear-column, clear-table, and clear-all plus DATESYTD measures to the page-filter, save/reopen, and changed-source scenario.
- **Verification:** `python3 -m pytest -q tests/test_totalytd.py tests/test_calculate_boolean_filters.py` passed **104 tests and 93 subtests**. Full `python3 -m pytest -q` passed **437 tests and 230 subtests**.
- **Next:** Combine `ALL` with supported Boolean filters in one `CALCULATE` call.

### 2026-10-09: Mixed `ALL` and Boolean filters

- **Filter evaluation:** `ALL()` and its supported table/column forms can accompany bounded Boolean `CALCULATE` filters. The clear occurs before the Boolean predicates; replacement and `KEEPFILTERS` behavior follow the same bounded semantics as the existing filter path. Mixed table-valued `FILTER` remains rejected.
- **Lifecycle:** Added column/table/all clear cases, multiple Boolean predicates, `KEEPFILTERS`, save/reopen, and changed-source recalculation.
- **Verification:** `python3 -m pytest -q tests/test_calculate_boolean_filters.py tests/test_totalytd.py` passed **106 tests and 92 subtests**. Full `python3 -m pytest -q` passed **439 tests and 229 subtests**.
- **Next:** Combine `ALL` with supported time-intelligence filters in one `CALCULATE` call.

### 2026-10-09: Mixed `ALL` and time-intelligence filters

- **Filter evaluation:** The supported date set is computed from the incoming context, then `ALL` clears the selected filters and the date set plus Boolean predicates are reapplied. This preserves the selected YTD period when `ALL` clears the marked date column, its table, a related Region column, or all filters.
- **Lifecycle:** Added column/table/all clear cases with `DATESYTD`, Boolean replacement, save/reopen, and changed-source recalculation.
- **Verification:** `python3 -m pytest -q tests/test_totalytd.py tests/test_calculate_boolean_filters.py` passed **106 tests and 92 subtests**. Full `python3 -m pytest -q` passed **439 tests and 229 subtests**.
- **Next:** Combine table-valued `FILTER` with supported filter-clear modifiers while preserving the rowset captured from its incoming context.

### 2026-10-09: Table-valued `FILTER` with filter-clear modifiers

- **Filter evaluation:** A single table-valued `FILTER` argument can accompany `REMOVEFILTERS`, `ALL`, `ALLNOBLANKROW`, or `ALLEXCEPT`. Its matching rows are captured from the incoming context before clearing filters, then reapplied as a bounded rowset. Additional Boolean or second table filter arguments remain outside this increment.
- **Lifecycle:** Added column/table/all clear cases, `ALLNOBLANKROW` and `ALLEXCEPT` cases, rowset preservation after the clear, save/reopen, changed-source recalculation, and validation for unsupported additional arguments.
- **Verification:** `python3 -m pytest -q tests/test_calculate_boolean_filters.py tests/test_totalytd.py` passed **106 tests and 93 subtests**. Full `python3 -m pytest -q` passed **439 tests and 230 subtests**.
- **Next:** Combine `ALLSELECTED` with supported Boolean filters in one `CALCULATE` call while retaining the current-selection scope.

### 2026-10-09: `ALLSELECTED` with supported filter arguments

- **Filter evaluation:** In the current report evaluator, `ALLSELECTED` keeps report/page/visual selections because query-axis context is not modeled. It can now accompany supported Boolean filters, supported time-intelligence filters, or one table-valued `FILTER`; the modifier's target is still resolved and checked.
- **Lifecycle:** Added Boolean replacement and `KEEPFILTERS` cases, a table-filter case, and a DATESYTD case, all through save/reopen and changed-source recalculation.
- **Verification:** `python3 -m pytest -q tests/test_calculate_boolean_filters.py tests/test_totalytd.py` passed **106 tests and 95 subtests**. Full `python3 -m pytest -q` passed **439 tests and 232 subtests**.
- **Next:** Combine `USERELATIONSHIP` with supported Boolean filters in one `CALCULATE` call and preserve relationship-state restoration.

### 2026-10-09: Relationship modifiers with Boolean filters

- **Filter evaluation:** `USERELATIONSHIP` and `CROSSFILTER` can accompany the bounded typed Boolean filters, including `KEEPFILTERS`. Their temporary relationship definitions and propagated rows are restored after calculation.
- **Lifecycle:** Added inactive-date-role and bidirectional-filter Boolean measures, including save/reopen and source-change replay.
- **Verification:** `python3 -m pytest -q tests/test_calculate_boolean_filters.py tests/test_totalytd.py` passed **106 tests and 94 subtests**. Full `python3 -m pytest -q` passed **439 tests and 231 subtests**.
- **Next:** Combine supported time-intelligence filters with `USERELATIONSHIP` and `CROSSFILTER`, preserving temporary relationship state and changed-source recalculation.

### 2026-10-09: Line and clustered column Combo chart

- **Visual:** Enabled the Line and clustered column gallery item. Added separate Column Y-axis and Line Y-axis wells with independent Sum/Count/Average settings, aligned both series by category, and rendered the line over the clustered columns.
- **Interactions and lifecycle:** Combo categories filter peers, linked highlights render on both series, and both field bindings and aggregations persist and recompute after source refresh.
- **Verification:** `python3 -m pytest -q tests/test_combo_chart_lifecycle.py tests/test_visual_field_wells_lifecycle.py tests/test_visual_interactions_lifecycle.py` passed **7 tests**. Full `python3 -m pytest -q` passed **440 tests and 231 subtests**.
- **Next:** Combine supported time-intelligence filters with `USERELATIONSHIP` and `CROSSFILTER`, preserving temporary relationship state and changed-source recalculation.

### 2026-10-09: Time-intelligence filters with relationship modifiers

- **Filter evaluation:** `USERELATIONSHIP` and `CROSSFILTER` can accompany the supported time-intelligence filter expressions and bounded Boolean filters. The date set is captured from the incoming context before temporarily changing relationship state; the relationship and date filters are then applied together, and temporary state is restored after evaluation.
- **Lifecycle:** Added inactive ShipDate-role YTD evaluation, `CROSSFILTER(None)` behavior, Boolean predicates, original relationship-state checks, save/reopen, and source-change recalculation.
- **Verification:** `python3 -m pytest -q tests/test_totalytd.py tests/test_calculate_boolean_filters.py` passed **107 tests and 94 subtests**. Full `python3 -m pytest -q` passed **441 tests and 231 subtests**.
- **Next:** Add a local Gauge visual with value/minimum/maximum/target wells, aggregation, linked interactions, and save/reopen/refresh coverage.


## 2026-10-11 — Guarded negative text filters in the local M bridge

Advanced Editor now round-trips Does Not Contain, Does Not Begin With, and Does Not End With. Generated M handles null explicitly so blank rows follow the local filter behavior. The parser rejects unguarded negative predicates and the compatibility report rejects text filters after a non-text conversion.

Verification: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. python3 -m pytest -q tests/test_power_query_m_editor.py` passed **52 tests and 118 subtests**; the full workspace suite passed **530 tests and 395 subtests**; `py_compile` and `git diff --check` passed. This increment does not add Conditional Column or keep-duplicates M mappings and does not provide a general M runtime or complete DAX.

## 2026-10-11 — Conditional Column M round-trip

The Advanced Editor now translates local ordered Conditional Column rules through bounded `Table.AddColumn` M if-chains. Supported shapes include literal/column outputs, equality, all six text predicates with explicit null guards, and numeric ordered comparisons after an explicit type conversion. Numeric equality, ambiguous null/empty text comparisons, and column-valued text search terms reject rather than being silently reinterpreted. Empty-string search terms retain blank behavior through a value-specific guard. Unsupported nested or unguarded text-predicate expressions reject instead of falling through to custom-column parsing. Direct local execution and M export/reparse produce identical rows for the covered shapes.

Verification: focused M tests passed **59 tests and 142 subtests**; the full workspace suite passed **537 tests and 419 subtests**; `py_compile` and `git diff --check` passed. This is local parser/replay evidence only, not execution against Microsoft Mashup. Keep-duplicates, a general M runtime, and full DAX remain open.

## 2026-10-11 — Append and Merge inside the Power Query session

The separate editor's Home ribbon now offers Append Queries and Merge Queries. Both dialogs use the current session previews; Append validates matching ordered schemas, and Merge retains the existing exact-match join and key options. New queries are staged with their dependency definition, type conversions, preview, and active selection. Newly staged queries track parent step edits before Apply. Close & Apply validates and commits the source definitions, model table, type map, evaluated rows, and active selection together; Cancel leaves the project untouched. Save/reopen and changed-source refresh are covered for both operations.

Review also caught and fixed a regression where rebuilding every saved append/merge preview during navigation would replace an excluded query's frozen cached result. Rebuilding is now limited to newly staged query dependencies; the existing save/refresh lifecycle remains intact.

Independent controller review found that a new combine could still be rebuilt at Apply from a parent's saved steps after that parent had been edited in the open session. Apply now uses accepted current-session preview candidates for newly staged Append/Merge, validates the rebuilt source and result against the editor preview, and preserves the existing refresh/cache behavior of already-saved queries. Controller-level regression tests cover edited-parent Append and Merge.

Focused editor/session tests passed **52 tests and 52 subtests**. The full suite passed **544 tests and 419 subtests**. Compilation and whitespace checks passed. This adds two session workflows; it does not provide generic M execution, Power Query Desktop parity, or full DAX. Dependency Diagram, parameters/functions, per-operation settings, privacy/credentials, keep-duplicates M, a general Mashup runtime, and full DAX remain open.

## Iteration 7 — Keep Duplicates in the bounded M bridge

Advanced Editor now round-trips the existing Keep Duplicates by Selected Columns step through one canonical grouped-composite-key M form. It accepts text-typed single or composite keys, uses ordinal comparison, preserves input order with a generated index, and preserves the empty output schema. Other M shapes and non-text keys reject. Local null values are normalized to empty text to match the app's current cell model; M sources that distinguish null from empty text can therefore behave differently. This is bounded parser/replay support, not Microsoft Mashup execution.

Review found no further correctness issue with the documented scope. Focused tests passed **63 tests**; the full `python3 -m unittest discover -s tests` suite passed **493 tests**. Compilation and whitespace checks are recorded with the final verification. The broader Power Query ribbon/session, general M runtime, and complete DAX catalog remain open.

## 2026-10-11 — Query dependency diagram and type-preservation repairs

The Power Query View ribbon now opens a read-only dependency diagram. It lays out source and saved queries from left to right, draws arrows for Reference/Append/Merge dependencies, shows query group/load/refresh state, and reports parent references outside the current editor session. A focused UI test covers ribbon entry; diagram tests cover edge/layout generation and missing parents.

Lifecycle review found three data-shaping defects and added regression coverage:

- Transform Data now seeds its column type map from conservative import inference; calculated-column edits preserve that type map when rebuilding the model table.
- Type inference requires a colon-formatted value before it considers Python's permissive time parser, preventing numeric strings such as `10` and `20` from becoming times.
- Close & Apply no longer treats a newly staged dependent query's initial type-conversion steps as a conflict with editing its parent in the same session. The staged query is rebuilt and validated against the accepted parent preview.

Verification: focused diagram, type inference, calculated-column, and dependent-merge tests passed. The complete suite passed **567 tests and 422 subtests** with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 QT_QPA_PLATFORM=offscreen PYTHONPATH=. python3 -m pytest -x -q --tb=short`. `py_compile` and `git diff --check` passed.

Boundary: the dependency diagram is read-only. The local Advanced Editor still executes only a bounded M subset; parameters, a dedicated schema view, privacy/credential authoring, query folding, and a general Mashup runtime remain open. The DAX evaluator remains partial and does not cover Microsoft's full function catalog or Tabular semantics.

## 2026-10-11 — Fixed-position split in the local M bridge

The Advanced Editor now exports and parses `Table.SplitColumn` with `Splitter.SplitTextByPositions` for the local fixed-position split step. It validates the positions with the transformation engine, requires the editor's numbered output fields and empty-text default, and uses the documented M default direction. Round-trip tests compare parsed local output and model headers with direct transform output, including short and blank cells; invalid positions and custom output names are rejected.

Focused fixed-position split tests passed **2 tests and 4 subtests**. The official [Splitter.SplitTextByPositions reference](https://learn.microsoft.com/en-us/powerquery-m/splitter-splittextbypositions) defines the M operation. After this increment, the full suite passed **568 tests and 423 subtests** in 19.69 seconds; `py_compile` and `git diff --check` passed.


## 2026-10-11 — Advanced multi-column filter support in the local M bridge

The Advanced Editor now imports and exports the existing multi-column filter operation. Generated M preserves the local AND-before-OR grouping and null guards for text predicates; parsing returns replayable `filter_rows_advanced` steps. Parenthesized boolean groupings that cannot be represented by the local step schema are rejected with a clear error.

Focused M tests passed **2 tests**. The full suite passed **570 tests and 423 subtests** with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 QT_QPA_PLATFORM=offscreen PYTHONPATH=. python3 -m pytest -x -q --tb=short`. This validates the local parser and replay path, not execution against Microsoft Mashup or complete Power Query parity.


## 2026-10-11 — Blank-safe numeric filters in the local M bridge

Generated numeric filter comparisons now convert the source field with `Number.From` and check null/empty cells first. The parser maps that form back to the local numeric filter step, so Advanced Editor round-trips use the transformation engine's numeric comparison instead of comparing text values. The same mapping applies inside multi-column AND/OR filters.

Focused M and advanced-filter lifecycle tests passed **75 tests and 143 subtests**. The full suite passed **571 tests and 423 subtests**; `py_compile` and `git diff --check` passed. Numeric text conversion follows the local finite-decimal filter contract; this remains bounded local M translation, not execution by Microsoft Mashup.

## 2026-10-12 — Typed parameters in filters and supported M comparisons

Project format v76 stores typed scalar Power Query parameters. Manage Parameters creates and edits Text, Whole number, Decimal number, Boolean, Date, and DateTime values. Simple and advanced row-filter controls can bind a parameter, and the bounded M bridge keeps those references symbolic in supported comparison forms. Current values are resolved during preview and refresh rather than copied into the saved step.

Focused parameter, M, session-combine, transform-persistence, and migration tests passed **120 tests and 157 subtests**. The full suite passed **579 tests and 428 subtests**. Parameter use in custom formulas and other transforms was not covered by this increment.

## 2026-10-12 — Saved measures drive supported report visuals

Saved DAX measures now appear in report field selection and can bind to supported grouped charts, cards, gauges, KPIs, and matrix values. Grouped visuals evaluate the measure in category context; rename, delete-safety, save/reopen, and changed-source refresh are covered. Measure bindings do not expose a raw-column aggregation control.

Focused visual lifecycle tests passed **7 tests**. The full suite passed **580 tests and 428 subtests**. This connects saved measures to a bounded set of visual query contexts; it does not make the partial DAX evaluator complete.

## 2026-10-12 — Typed parameters in custom-column formulas and Advanced Editor

The safe custom-column expression subset now resolves typed scalar parameters, including numeric arithmetic and text concatenation. The Transform Data operation controls offer an Insert parameter selector. Advanced Editor preserves parameter names in supported `Table.AddColumn` expressions, validates the authored script, and previews it through the same local transformation engine. Changed parameter values are used again during source refresh.

Focused parameter/M editor/project tests passed **116 tests and 157 subtests**. The full suite passed **583 tests and 428 subtests** in 19.85 seconds with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 QT_QPA_PLATFORM=offscreen PYTHONPATH=. python3 -m pytest -x -q --tb=short`. `py_compile` and `git diff --check` passed. This adds custom-column parameter references only; general M execution, query functions, Microsoft Mashup, and full DAX remain open.

## 2026-10-12 — Selected-step Schema view

The Transform Data View ribbon now opens a dedicated Schema tab for the currently selected applied step. It lists column order, names, local data types, and up to three example values from the first 100 preview rows. The schema refreshes with the same step selection and replay used by the data preview; the table is read-only.

Focused UI, parameter, M editor, and profile tests passed **130 tests and 194 subtests**. The full suite passed **584 tests and 428 subtests** in 20.05 seconds. Compilation and `git diff --check` passed. The view exposes local inferred/model types and preview examples; it does not add source-native metadata or a Mashup schema engine.

## 2026-10-12 — Measure metadata in the semantic model

Measure authoring now includes optional Description, Display folder, and Hidden properties. The create/edit dialog persists the properties, the Model view displays them, and hidden measures remain available to other measure expressions while staying out of report field pickers and KPI selection. Existing three-argument controller edits preserve metadata unless callers explicitly change it. Project format v77 accepts these optional fields and migrates v76 projects without changing existing measure definitions.

Focused measure, project-migration, and dialog coverage passed **63 tests and 21 subtests**. The full suite passed **588 tests and 431 subtests**. `py_compile` and `git diff --check` passed. Full DAX semantics, measure format strings/home-table reassignment, and broad model metadata remain open; these tests validate the added local properties only.

## 2026-10-12 — Power Query Refresh Preview and M filter canonicalization

Added Home → Refresh Preview to reread the active source graph and replay query steps in the Power Query session. Refresh now carries updated parent source candidates, type maps, and previews through staged dependencies, including parent edits and newly staged Append queries. Close & Apply accepts external file changes only when they were explicitly refreshed and the accepted preview matches. Failed refreshes keep the last valid preview. Excluded saved queries continue using cached results. A one-clause advanced filter now canonicalizes to its equivalent simple filter for the bounded M emitter/parser contract.

Verification: `tests/test_power_query_m_editor.py` passed **75 tests and 143 subtests**; the focused M/session pair passed **84 tests and 143 subtests**; the full suite passed **592 tests and 431 subtests**. `py_compile` and `git diff --check` passed. Power Query remains a bounded local implementation without Microsoft's Mashup runtime; the DAX evaluator remains a partial 46-name local subset.

## 2026-10-12 — Refresh Preview parameter and transaction fixes

Independent review found that Refresh Preview replayed staged dependency queries with saved parameter values, even when the editor had unsaved parameter changes. The callback now receives the current typed parameter snapshot, so upstream and target previews use the same values that Close & Apply validates. Refresh Preview is disabled for saved queries excluded from report refresh and explains that their preview is cache-backed. Regression coverage verifies current-parameter propagation through an Append dependency, failed-refresh snapshot preservation, Cancel without controller mutation, and rollback after an Apply-time source-read failure.

Focused tests passed **153 tests and 194 subtests** across the Power Query M editor, session-combine, parameter, file workflow, and Refresh All suites. The full suite passed **601 tests and 433 subtests** in 22.28 seconds. Regression tests confirm that changed remote snapshots apply as previewed and excluded dependencies use cached source inputs while replaying current parameter values or user-edited steps consistently through downstream previews and Apply. Explicit refresh of included SQL Server, OData, and Web dependencies may call configured connectors; live endpoint and credential behavior is not covered by local tests. This closes the reviewed Refresh Preview defects only and does not establish full Power Query or DAX parity.

## 2026-10-12 — Bounded `COUNTX` and `COUNTAX` measures

The searchable DAX measure editor now inserts `COUNTX` and `COUNTAX`. The evaluator supports loaded tables or supported `ALL` table expressions with numeric and text column results, Boolean result distinctions, blanks and empty-string expression results, arithmetic row expressions, and simple `IF` outputs. Iterator `IF` conditions type-check supported expressions recursively: equality/inequality supports matching numeric, Boolean, or text types, and ordering comparisons require numeric operands. Same-table text equality/inequality between columns or a column and literal uses Unicode case-folding. Mixed, date/time, and unverifiable operand types reject; model-specific collation is not stored. Formula-produced `""` counts, stored empty cells and `BLANK()` are skipped, and an empty iterator currently returns zero rather than DAX blank. The functions are measure-only in this increment; general table expressions, cross-table row references, calculated-column use, and DAX's blank-result propagation for empty counts remain outside the local evaluator.

Review found several paths where invalid typed iterator values could reach Boolean conditions: typed text directly under `AND`, inside a nested `IF`, through numeric functions such as `ABS` or `COUNT`, or through a numeric `IF` predicate. The evaluator now checks the complete iterator row expression before evaluating it, validates Boolean/`IF` condition categories, validates numeric scalar arguments, rejects unverifiable Boolean conditions, uses the nested iterator's own table schema, resolves scalar aggregate references against their own model table, and performs these checks even when an input table is empty. Inferred Boolean references remain supported when paired with `TRUE()`/`FALSE()`; typed text cannot be coerced to Boolean.

Focused measure, report/workflow, and calculated-column tests passed **41 tests and 37 subtests** in 0.33 seconds. The full suite passed **605 tests and 450 subtests** in 21.45 seconds. Focused Power Query/session/parameter/home/refresh tests passed **154 tests and 194 subtests**. `compileall` and `git diff --check` passed. This adds two partial function forms and does not establish complete DAX or Tabular parity.

## 2026-10-12 — Reusable typed scalar Power Query functions

Project format v78 stores reusable one-argument scalar function definitions. The Transform Data Home ribbon opens Manage Functions; definitions can be created, edited, inserted into custom-column formulas, and previewed through the existing safe expression engine. Optional custom-column `output_type` values preserve scalar text, whole-number, decimal, Boolean, date, and datetime results. Advanced Editor places used function definitions after `Source`, emits nullable parameter/result types, and accepts only definitions matching the saved registry. Function edits are staged and replay through Preview, Close & Apply, save/reopen, and Refresh All.

Review fixes make changed functions invalidate excluded saved-query results and replay them from cached source snapshots. A query whose source is unavailable keeps its persisted transformation steps for function-reference checks; changing a function used by that unavailable query is rejected with a visible message. M library namespace names, including `Table`, cannot be reused for function or function-parameter identifiers. Function result values must match the declared scalar type instead of being parsed from text; whole-number function inputs and results enforce signed Int64 bounds, and null values round-trip with nullable M signatures. A changed function also rebuilds an excluded saved Reference Query from the staged parent preview, so preview and Apply agree.

Focused Power Query/function/parameter/M/session/migration tests passed **149 unittest tests**. The full `python3 -m unittest discover -s tests` run passed **563 tests**. The full pytest run passed **618 tests and 463 subtests**. `python3 -m compileall -q analytics_studio tests` and `git diff --check` passed. Additional end-to-end coverage verifies edited definitions through Refresh Preview, a directly dependent excluded query, and an excluded Reference Query without its own function call, then save/reopen and Refresh All. The complete Mashup runtime, multi-argument/nested/general M functions, broader Power Query ribbon workflows, and complete DAX catalog/runtime remain open; this iteration does not complete the user's broader parity request.

## 2026-10-12 — Staged remote New Source and credential safety

Power Query Home can now stage existing SQL Server, OData Feed, and anonymous Web connector workflows inside the separate editor session, alongside staged local file/folder inputs. These root sources use the existing connector preview dialogs and commit together with their model tables, type maps, and source records on Close & Apply. If a remote root is explicitly refreshed in the session, Apply uses the snapshot the user reviewed instead of fetching a second time. SQL password values remain in session memory until validated Apply. Keychain accounts are bound to the connection identity; an unbound entry from an older version is not sent and requires a one-time password re-entry. Failed staged credential writes trigger cleanup for all attempted references, and deleting an unused SQL source removes its in-memory and Keychain secret. Web URL validation preserves normal anonymous query parameters but rejects common token, signature, auth, key, and password parameter names because the URL is saved in the project.

Focused Power Query session tests passed **24 tests** and SQL Server/OData/Web lifecycle suites passed **11 tests**. Full `unittest` passed **577 tests**; full pytest passed **632 tests and 471 subtests** in 23.80 seconds. `python3 -m compileall -q analytics_studio tests` and `git diff --check` passed. Connector and Keychain calls are stubbed in local tests; live remote endpoint acceptance remains pending. Broader connector catalog, query privacy, general credential manager, folding, full M/Mashup, and complete DAX remain open.

## 2026-10-12 — Edit existing file source settings

Power Query Home and the Queries context menu can stage path and parser-option changes for an existing CSV, Excel, JSON, XML, or Parquet root. The source ID, connector kind, query metadata, and applied steps are preserved. Preview refreshes included Reference/Append/Merge descendants in dependency order; excluded queries continue using their cached results. Apply overlays the source settings in a cloned project, checks the file again against the accepted preview, validates source and descendant output headers/types and active model relationship constraints, and only then commits. Cancel, schema/type rejection, parse failure, and Apply-time source drift leave project and controller caches unchanged. Append/Merge input types now reconcile parent type maps consistently across the editor session, apply, refresh, and reopen.

Acceptance covers changing a CSV delimiter and path, preserved source/query IDs and steps, Reference → Append → Merge preview propagation, excluded Reference cache behavior, type inheritance/reconciliation, schema-change rejection, Cancel, Apply-time file drift, save/reopen, and subsequent refresh. The file preview dialog labels this workflow as **Edit source settings / Apply settings** and starts with the saved parser options.

Focused `test_power_query_session_combine.py`, `test_home_file_workflows.py`, and `test_transform_persistence.py` passed **83 tests and 52 subtests**. The full pytest suite passed **642 tests and 471 subtests**; full unittest passed **587 tests**. `compileall` and `git diff --check` passed. Editing SQLite, folders, SQL Server, OData, and Web sources, schema-changing replacements, the general Mashup engine, complete M, and complete DAX remain open.

## 2026-10-12 — Bounded `RELATED` lookup in DAX measure iterators

Added `RELATED` to the searchable measure-function picker with an editable qualified-column template. The local evaluator supports numeric target columns in `SUMX`, `AVERAGEX`, `COUNTX`, and `COUNTAX` row expressions through one direct, active, unambiguous many-to-one relationship. The lookup indexes the complete related table, so a filter on the lookup table does not constrain the lookup itself; a missing key returns BLANK. Numeric keys use typed numeric equality. Text keys use Unicode case-folding because model collation is not stored; locale-specific behavior can differ. The same comparer now drives relationship propagation and one-side uniqueness validation, and case-fold collisions on a one side are rejected during source refresh before project/cache commit. Invalid scope, missing/inactive/ambiguous relationships, and nonnumeric targets fail with specific errors. This does not add calculated-column lookup, text result values, inactive or multi-hop relationship support, or full DAX semantics.

Acceptance covers the requested `SUMX(Sales, Quantity * RELATED(Products[Unit Price]))` pattern, orphan-key blanks, lookup filter behavior, case-folded text keys, cross-filter propagation, one-side collision rejection, editor insertion, measure save/reopen, and changed lookup-source refresh including atomic rejection of a new collation collision. Focused DAX/report/relationship tests passed **49 tests and 42 subtests**. The full pytest suite passed **662 tests and 476 subtests**; full unittest passed **607 tests**. `python3 -m compileall -q analytics_studio tests` and `git diff --check` passed. Microsoft's [`RELATED` reference](https://learn.microsoft.com/en-us/dax/related-function-dax) documents its row-context and many-to-one behavior and filter-independent lookup. Full DAX remains open. Automated tests ran in Qt offscreen mode; manual macOS UI acceptance remains pending.

## 2026-10-12 — Preserve COUNTX/COUNTAX blank results through reports

Corrected the earlier bounded iterator behavior that returned numeric zero when no row-expression result qualified. `COUNTX` and `COUNTAX` now produce a nullable result: `None` for no countable value, with numeric zero and formula-produced `""` remaining countable. The result survives direct measure aliases and the supported `CALCULATE` wrappers. Draft preview, KPI/card values, grouped chart points, gauge/KPI state, and matrix cells retain blank; charts omit missing points while matrix categories remain present. A numeric-zero control case stays visibly zero.

Coverage includes empty and filtered-empty tables, all-blank inputs, Boolean-only `COUNTX`, Boolean `COUNTAX`, formula-produced empty strings, numeric zero, aliases, `ALL`, draft preview, report visuals, save/reopen, and changed-source refresh. Focused DAX/report/visual tests passed **56 tests and 42 subtests**. Full pytest passed **665 tests and 476 subtests**; full unittest passed **610 tests**. `compileall` and `git diff --check` passed. Microsoft documents blank when there are no rows to count/aggregate. Applying that wording to nonempty all-blank and Boolean-only `COUNTX` inputs is an inference; no external Tabular engine was used as a semantic oracle. Arithmetic still coerces BLANK to zero in this local evaluator, and broader DAX/Mashup parity remains open.

## 2026-10-12 — Group DAX measures in Table visuals

Table field wells now accept columns and multiple DAX measures together. Distinct tuples of the assigned columns define row groups; measures are evaluated once per group. Measure-only Tables show one total-context row, and blank measure results remain empty while numeric zero renders as `0`. Slicers now hide and reject measure fields so a scalar value cannot appear as a selectable category. Legacy saved measure bindings in Slicers produce no fake blank category.

Review also caught and the implementation fixed several edge cases. Table row selection resolves its first column field even when a measure is first in the field list, including older visuals without a saved `table_id`. If a refresh removes a grouped column, the Table displays an explicit stale-field message instead of showing a blank group with an unfiltered total. Missing or failing measures also display an evaluation message instead of silently looking like a valid blank result.

Coverage verifies repeated category/month tuples, multiple measures, blank versus zero, measure-only totals, measure-first row cross-filtering, Slicer filtering and rejection, save/reopen, normal source refresh, and refresh after a bound dimension is removed. The focused Table/Slicer/report run passed **20 tests**. The full pytest suite passed **667 tests and 476 subtests**; full unittest passed **610 tests**. `compileall` and `git diff --check` passed. These are local, single-table semantics; full DAX/Tabular behavior, cross-table visual queries, grouped totals, and manual macOS UI acceptance remain open.

## 2026-10-12 — Home Advanced Editor and Pivot count M round-trip

Power Query Home now has a direct **Advanced Editor (M)** action that opens the existing separate editor with the active query/session state; the View entry remains available. The M bridge now round-trips Pivot Count (not blank) through the exact `each List.Count(List.RemoveItems(_, {null, ""}))` aggregation and rejects near-matching forms. Pivot Count all and Count not blank now keep whole-number type metadata, including output categories derived after Promote Headers.

The separate-window/cancel route and local output/header/type parity are covered. Focused Power Query M/Home/session/transform tests passed **153 tests and 223 subtests**. Full pytest passed **672 tests and 480 subtests**; the full unittest suite passed **615 tests**. `compileall` and `git diff --check` passed. This is one bounded M mapping; general Mashup execution and the complete Power Query ribbon remain open.

## 2026-10-12 — DAX distinct-count blank semantics

The local DAX evaluator now counts a normalized blank cell as one distinct value for `DISTINCTCOUNT`, and the searchable function editor and Quick Measure picker offer `DISTINCTCOUNTNOBLANK` to omit that value. Both return blank for a zero-row result; a blank-only nonempty table returns 1 and 0 respectively. Zero and whitespace-only values remain countable. The Quick Measure name now follows the selected calculation type.

Tests cover duplicate, blank, zero, whitespace, filter-to-empty, blank-versus-zero display, function insertion, Quick Measure creation, an editor function-and-field insertion → controller-backed preview → save → KPI flow, `COUNTX`/`COUNTAX` with the new distinct-count scalar, and both distinct-count measures as cards through save/reopen/refresh. Microsoft documents the `DISTINCTCOUNT` blank/no-row behavior and the nonblank variant's blank exclusion at [DISTINCTCOUNT](https://learn.microsoft.com/en-us/dax/distinctcount-function-dax) and [DISTINCTCOUNTNOBLANK](https://learn.microsoft.com/en-us/dax/distinctcountnoblank-function-dax). For `DISTINCTCOUNTNOBLANK`, the blank result on zero rows follows the local aggregate convention; the cited Microsoft page does not state that case. Focused DAX/editor/report tests passed **53 tests and 42 subtests**. Full pytest passed **676 tests and 480 subtests**; full unittest passed **619 tests**. `compileall` and `git diff --check` passed. Unittest emitted non-fatal Qt/platform and resource warnings, including unclosed SQLite-connection warnings. Null and empty text remain normalized together, and local string distinctness does not claim model collation parity; full DAX/Tabular behavior remains open.

## 2026-10-12 — Power Query editor and runtime feasibility review

The current workspace source opens a separate **Power Query Editor** with six ribbon tabs and separate Advanced Editor entry points from Home and View. The source also exposes **New DAX measure** on the Home and Modeling ribbons and in Model view. Focused current-source UI/workflow tests passed **134 tests and 197 subtests**. The supplied October 10 screenshots show the older `Transform data` operation dialog; the difference suggests a different or older running build, but the user's running app was not inspected directly.

The editor's local M parser and transform engine remain bounded. Microsoft lists an M engine in Excel for Mac; the audit now states the narrower finding that no supported standalone or embeddable arbitrary-query M runtime for this app has been identified. The Power Query SDK/PQTest path could not be probed here because `dotnet` and `PQTest.exe` are absent. A pinned `pbix-mcp` install attempt failed because DNS could not resolve pypi.org, so no DAX candidate was installed or evaluated. Python 3.14 compatibility is unverified, not known-incompatible. The app's 50 local DAX function names still have partial semantics. No runtime integration was made; full M/Mashup and DAX/Tabular functionality remain open.

## 2026-10-12 — Append M source round-trip

The Advanced Editor now emits and parses the two parent references of a saved Append query as `Table.Combine`, then builds its source preview from those parents' staged query results. The source references remain tied to the session's Append definition and changed references are rejected with directions to Home → Append Queries. A regression test found that Apply compared model query names such as `north` to imported filenames such as `north.csv`, causing a valid authored script to be discarded. Controller validation now resolves parent names through their model tables. Coverage verifies parser/emitter round-trip, downstream filter preview, changed-source rejection, Apply, M persistence, and project save/reopen; the controller's direct M entry routes saved Append queries through the Power Query session. Focused tests passed **127 tests and 151 subtests**; full pytest passed **680 tests and 480 subtests**; `compileall` and `git diff --check` passed. Independent review and manual macOS acceptance remain separate gates. Query references are currently changed through Append Queries, while the M parser and DAX evaluator remain bounded/partial; this increment does not claim full Power Query or DAX parity.


## 2026-10-13 — Add `Text.Clean` to custom-column M formulas

The bounded custom-column expression evaluator now accepts `Text.Clean`. It removes Unicode control-category (`Cc`) characters, matching the local Clean Text step and Microsoft's documented behavior. The M expression type checker preserves its nullable text result, and the formula placeholder now demonstrates the function. This extends the local M subset; it does not add arbitrary M execution.

Acceptance now covers C0/C1 control removal, preservation of a non-control format character, nullable `Text.Clean(null)` evaluation, custom-column M emit/parse/replay, preview, save/reopen, and refresh after source changes. The local normalized-cell model still stores a null formula result as empty text.

## 2026-10-13 — Complete local Power Query operation-ID M coverage

The Power Query M operation matrix now enumerates the Transform Data editor's 46 operation IDs and requires a representative script to emit, parse, replay, and produce the same local rows and type map as the direct transformation. The added cases cover advanced filters, locale conversion, delimiter extraction, all split forms, merge columns, Group, both Unpivot forms, Pivot, Keep Duplicates, and Transpose. Focused M tests also round-trip `Text.Clean` formulas with nullable output. This closes P2 operation-ID coverage for the bounded local bridge; it does not prove every possible M form or external Mashup equivalence.

Two regression assertions were corrected: Append M rebinding now checks that the source comment and newline remain in place, and the Merge lifecycle fixture updates its source-type metadata consistently with its derived type map. Focused Power Query M, custom-column lifecycle, and session-combine coverage passed **134 tests and 166 subtests**. The full pytest suite passed **686 tests and 495 subtests**; `compileall` and `git diff --check` passed. These checks use the local bridge and do not establish Mashup-runtime behavior or null/empty fidelity.

## 2026-10-13 — Report all row failures from type conversions

Invariant and locale-aware type conversion now scan every row before returning. If any value fails, the transformation still fails atomically, and its error includes the exact number of invalid values plus up to 20 bounded examples with the 1-based row ordinal at the current step input, column, raw value, target type, and culture. Long values are truncated in the message; structured diagnostics retain the example values. The editor displays this message when a type-change preview fails. This is deterministic conversion diagnosis, not persistent cell-level Error values, source-row lineage, null/empty separation, or a Remove Errors operation.

Acceptance covers multiple invalid values in both conversion paths, locale details, bounded examples, unchanged source candidates, and the editor error message.

Focused transformations, Power Query M/editor lifecycle, and session-combine suites passed **153 tests and 186 subtests**. Full `python3 -m pytest -q` passed **690 tests and 495 subtests**. `python3 -m compileall -q analytics_studio tests` and `git diff --check` passed. The run was local and does not establish Mashup equivalence or persistent cell-level errors.

## 2026-10-13 — Complete supported local P3 cell semantics and evaluate P4 runtime

The supported local table lifecycle now preserves native scalar values, Null, empty text, and tagged PowerQueryCellError values as separate states. Invariant and locale-aware conversions retain invalid cells as errors while converting valid rows. Remove Errors drops rows containing errors in all or selected columns. Column profiles count Null, empty text, and errors separately. Typed keys, report filter tokens and direct text equality keep Null separate from empty text. Keep Duplicates M encodes Null as N: and empty text as T0:. Homogeneous Unpivot outputs retain their common type metadata; mixed outputs retain native values but still lack an any union type. The supported split, fill, reshape, group, pivot, filter, relationship, DAX consumer, and visual paths now preserve, handle, or surface tagged errors according to their operation; visuals with direct cell errors show an error state instead of partial aggregates. Conditional Column M now round-trips numeric equality and text equality against an empty literal or another column. Nullable text search terms remain outside the M subset.

The P4 runtime search found an Excel for Mac Mashup Container host and engine assemblies. The signed host did not expose command-line help; invoking it with --help produced no output and waited until the four-second timeout, consistent with an internal Excel IPC worker. No documented standalone invocation or embedding API is available to this application, and dotnet, pwsh, mono, and PQTest are absent. Microsoft's PQTest documentation describes a connector test harness, while the Fabric Execute Query API runs remotely against an existing dataflow, requires execute permission, has a 90-second limit, and streams Arrow results. The local host is not a viable supported general-M integration path; P4 remains open pending a supported runtime or an explicit cloud-runtime design.

Focused Power Query M, transformation, visual-error, report-filter, and unpivot tests passed 136 tests and 191 subtests. The full python3 -m pytest -q suite passed 715 tests and 501 subtests. python3 -m compileall -q analytics_studio tests passed. git diff --check passed after removing one extra trailing blank line. Tests exercise the local engine and do not establish full Mashup equivalence, mixed-type any metadata, stable source-row lineage, manual macOS UI acceptance, or live remote endpoint behavior. See the P3/P4 roadmap decision and the Microsoft Execute Query API and PQTest overview.
The P3 regression review also corrected mixed numeric/text filter picker collisions, scoped measure visual errors to measure evaluation, counted empty text in `COUNTA` and `DISTINCTCOUNTNOBLANK`, preserved Boolean M conditional equality after logical conversion, and made type inference validate original whitespace-only cells.

Focused Power Query M, transformation, DAX measure, visual-error, report-filter, and unpivot tests passed **189 tests and 233 subtests**. The full `python3 -m pytest -q` suite passed **718 tests and 501 subtests**. `python3 -m compileall -q analytics_studio tests` passed. `git diff --check` passed after editing this entry. Tests exercise the local engine and do not establish full Mashup equivalence, mixed-type `any` metadata, stable source-row lineage, manual macOS UI acceptance, or live remote endpoint behavior. See the P3/P4 roadmap decision and the Microsoft Execute Query API and PQTest overview.

## 2026-10-19 — Related-dimension Table visual

The report Table visual can now group one explicitly qualified DAX measure from a fact table by one field from a directly related dimension table. The saved field identity includes the model-table ID, and measure evaluation remains anchored to that dimension when the Report field pane switches tables. Save/reopen and changed-source refresh preserve the field binding and recompute totals. The visual rejects inactive, ambiguous, bidirectional, unsupported-cardinality, incompatible-key, duplicate/blank dimension-key, blank/unmatched fact-key, and unsupported measure cases with a visible error and no partial rows. Existing string bindings remain supported.

Independent review confirmed the multi-measure/orphan-key and dimension-first persistence gaps are closed. The independent Testing Agent noted missing removal and non-Table rejection coverage; both now have direct regressions. The focused lifecycle and QML suites passed **14 tests and 4 subtests**; full pytest passed **817 tests and 629 subtests**. `compileall`, `git diff --check`, and Ruff on the two new test files passed. Multi-table chart/matrix wells, multiple cross-table dimensions/measures, multi-hop relationships, full DAX/Mashup compatibility, and native macOS visual/accessibility acceptance remain open.

## 2026-10-19 — Scalar COALESCE and DIVIDE blank behavior

Corrected local `DIVIDE(numerator, denominator)` so a zero denominator returns blank when the alternate is omitted. Added `COALESCE` to the parser catalog and Measure editor. It evaluates scalar arguments in order and returns the first value other than `None`, preserving numeric zero and Boolean false. `BLANK()` is now permitted inside COALESCE arguments while remaining rejected as a standalone measure expression. COALESCE rejects table-valued arguments and is limited to scalar measures; calculated columns and SUMX/AVERAGEX/COUNTX/COUNTAX row expressions fail validation before persistence.

The dialog inserts the two-argument template, and the lifecycle regression fills it into `COALESCE(DIVIDE(SUM([Numerator]), SUM([Denominator])), 7)`, previews and saves it, adds a card, saves/reopens, then refreshes changed source data (7 becomes 5). Unit cases cover zero/nonzero/explicit-alternate DIVIDE; ordered, all-blank, zero and false COALESCE; arity and omitted arguments; table/iterator/calculated-column rejection; and evaluated errors. Review identified and closed a false-fallback case, a template-to-preview continuity gap, an interior omission case, and a regex warning.

Focused DAX/report tests passed **67 tests and 53 subtests**. The full offscreen suite passed **827 tests and 640 subtests**. `compileall`, targeted Ruff, and `git diff --check` passed. All **55/55** picker entries are referenced by tests. Microsoft documents the default blank behavior for [DIVIDE](https://learn.microsoft.com/en-us/dax/divide-function-dax), first-nonblank behavior for [COALESCE](https://learn.microsoft.com/en-us/dax/coalesce-function-dax), and blank/empty-string distinction in [BLANK](https://learn.microsoft.com/en-us/dax/blank-function-dax). At this date, local alternate-expression acceptance for DIVIDE remained a known deviation from Microsoft's constant-alternate guidance; Iteration 58 addresses the tested form. Mixed text/type coercion, complete DAX/Tabular semantics, the full Power Query/Mashup engine, and native macOS review remain open.

## 2026-10-21 — Power BI `DIVIDE` alternate validation

- A read-only ADOMD check against the running Power BI Desktop 2.157.879.0 engine accepted numeric and `BLANK()` alternates and rejected arithmetic, aggregate, and function alternates with the constant-numeric diagnostic. Microsoft documents the constant alternate requirement in [DIVIDE](https://learn.microsoft.com/en-us/dax/divide-function-dax).
- Analytics Studio now accepts a numeric literal with one unary sign or exactly `BLANK()` as the third argument. It rejects computed alternates before evaluation and returns local blank (`None`) for the zero-denominator/`BLANK()` case. Two-argument behavior and nonzero quotient behavior are preserved.
- Focused and full-suite results are recorded in [Iteration 58 test results](.council/TEST_RESULTS_ITER58.md). The exact formula and filter context behind the user's reported incorrect calculation are still unknown; this change is a separate verified compatibility correction.

## 2026-10-21 — Power BI `DIVIDE` blank operand behavior

- A read-only ADOMD comparison against Power BI Desktop 2.157.879.0 confirmed blank-numerator precedence, blank-denominator fallback, and numeric-zero distinction. It also returned `0.5` for `DIVIDE(TRUE(),2)`, `0` for `DIVIDE(FALSE(),2)`, `1` for a `TRUE()` denominator, and the alternate for a `FALSE()` denominator. `ABS(BLANK())` returned blank; `COALESCE(ABS(BLANK()),7)` returned `7`; `DIVIDE(ABS(BLANK()),2)` returned blank.
- Additional queries confirmed `COALESCE(BLANK() + 1, 7)` returns `1` and `DIVIDE(1, ABS(BLANK()), 9)` returns `9`.
- Analytics Studio now accepts direct `BLANK()` operands and Boolean operands in `DIVIDE`, preserves blank results for the tested nested local scalar forms, and preserves blank through `ABS` in its supported `COALESCE` and `DIVIDE` contexts. Standalone scalar-measure `ABS(BLANK())` remains rejected by the local literal validator. Runtime output does not establish short-circuit evaluation; both operands are evaluated locally.
- The native UI capture remains blocked by an ambiguous Parallels accessibility-window match; no click or project change was made. Read-only ADOMD queries used the guest's current-user execution path. The exact user-reported formula and filter context remain unknown.
- Focused and full test, lint, compile, and whitespace results are recorded in [Iteration 59 test results](.council/TEST_RESULTS_ITER59.md). This is a bounded compatibility correction, not a resolution of the user's separate calculation report.

## 2026-10-19 — Model column default summarization

Added per-table default summarization for loaded numeric source columns in the Model view: Auto, Sum, Average, and Count. The keyboard-selectable column inspector adapts between wide and narrow layouts and describes unavailable, nonnumeric, and calculated-column states. Defaults apply only to a newly created visual binding and preserve the app's existing fallback for Auto; a later Model-view change does not rewrite an existing visual's aggregation. Dormant values stay attached to their table when the source/field is unavailable or changes to nonnumeric and resume only when the same numeric source field returns. Calculated columns and same-named columns from other tables do not inherit the default.

Defaults seed every non-Scatter visual's `Y-axis`, Combo `Column Y-axis` and `Line Y-axis`, Gauge Value/Minimum/Maximum/Target, Card Fields, and Matrix Values. The Y-axis regression checks every one of the 16 current non-Scatter visual types exposing that well. Project format v79 adds `column_summarizations` and migrates v78 projects.

Focused Model-pane/project/report tests passed **91 tests and 135 subtests**. Full pytest passed **844 tests and 692 subtests**. `compileall`, targeted Ruff, and `git diff --check` passed. Critic review closed the original three-chart Y-axis scope gap; final critic and SDET reviews approved the bounded implementation. The SDET notes two remaining test edges: Auto is not separately checked with text-only/all-blank Card or Matrix data, and the QML unavailable-state message uses a simulated unavailable catalog entry while missing-source lifecycle behavior is covered at controller level. Four local choices do not claim all Microsoft summarization modes or Tabular semantics; native macOS visual/accessibility acceptance remains open.

## 2026-10-19 — Model Sort by Column

Added v80 `column_sort_by` metadata per model table and a Model-view column inspector for setting and clearing a same-table, loaded source-column mapping. The controller validates typed category/sort pairs against complete candidate rows, rejects blanks/errors/unsupported and ambiguous mappings, exposes active or inactive reasons, and retains rules through source refresh even when fields disappear or the query is unavailable. The Saved sort rules panel keeps dormant rules clearable. Supported direct and DAX-measure chart categories and stacked legends, KPI trend axes, slicer options, and Matrix rows/columns apply ascending typed order; raw bound-table categories are ordered before display formatting. Top N membership is selected before model ordering. Existing per-consumer fallback orders remain in place when rules are absent or inactive.

Coverage includes v79→v80 migration, numeric/boolean/text/date/time/datetime ordering, Unicode casefold ties, normalized typed pair validation, duplicate ambiguity, null/empty/error cases on either mapped field, missing fields, loaded/unloaded state, transactional set/clear, DAX same-name table isolation, direct and DAX consumers, KPI latest-value behavior, Matrix axes, Top N, invalid refresh then save/reopen/reactivation, exact fallback behavior, and keyboard clearing at 560 px. Independent SDET review approved the bounded increment.

Focused integration passed **166 tests and 185 subtests**; the full offscreen suite passed **869 tests and 700 subtests**. `compileall`, targeted Ruff E9/F821, and `git diff --check` passed. Microsoft documents this model ordering separately from visual sorting and places the Desktop command in Report view's Column tools. The app's Model inspector placement is a local design choice. Flat Table row ordering, Scatter/Map legends, cross-table/calculated fields, multiple keys, descending order, locale collation, full Tabular/DAX behavior, and native macOS accessibility remain open; see the [parity roadmap](docs/microsoft-power-bi-power-query-parity-roadmap.md) and [.council verification sign-off](.council/VERIFICATION_SIGN_OFF_ITER33.md).

## 2026-10-19 — REA package inspection and relationship key normalization

Inventoried the full installed Power BI Desktop 2.157.879.0 Windows package from the Parallels guest: 7,263 files and 2,862,839,642 bytes. REA also inspected the embedded Minerva UI tree and the managed relationship detector. Its static CIL evidence shows `DetectionHelper` normalizes names using camel-case, parenthetical-comment, digit, and noise-word handling; its configured noise words include `name`, `id`, `key`, `code`, `pk`, and `fk`. It also exposes primary/foreign-key candidate tracking, batched cardinality requests, uniqueness/null checks, and relationship-path helpers.

Updated `detect_relationship_candidates` to remove parenthetical annotations and digits during key-name normalization, ignore those generic noise words, and retain the table-name rule for matching an ID-only column. Candidate generation now requires a unique, null-free one side, ranks by key-name fit and cardinality, and does not require sampled values on both sides to overlap. REA also shows whole-number and decimal columns use distinct relationship-key types and that `Variant` is `InvalidKey`, so autodetect no longer pairs those numeric types or treats `any` as a wildcard. The Date/DateTime/Time mapping remained open in this entry; a later static CIL decode resolves it below. This better reflects the retained detector call flow while leaving suggestions reviewable; the exact Power BI ranking remains unknown. Package and detector evidence and limitations are in [the REA investigation notes](docs/rea-power-bi-desktop-2.157.879.0.md). Tests were not run for this increment.

## 2026-10-19 — REA relationship key and name normalization details

Decoded the retained `GetRelationshipKeyType` switch with its `DataType` and `RelationshipKeyType` constants: Binary/Variant map to InvalidKey; Boolean to Boolean; Currency/Number to Double; Date, DateTime, and Time each keep their own key type; WholeNumber maps to Int; and Text maps to String. Analytics Studio's supported model types match these categories (`decimal_number` maps to Number/Double); `Currency` is not a currently exposed local type. This closes the previous static mapping question without claiming a runtime observation.

REA's `DetectionHelper` metadata also exposes the exact comment, number, and camel-case patterns plus its delimiter set. `name_tokens` now uses those rules directly before filtering the observed noise words, replacing the earlier generic camel-boundary and Unicode-word split. The key-type map already kept date, datetime, and time separate, rejected `any`, and kept whole-number/decimal pairs distinct. Updated the investigation notes with the new evidence IDs and mapping. Tests were not run for this increment.

## 2026-10-19 — REA relationship detector passes and candidate priority

REA's `Detect` state machine runs `DetectCore` with key normalization disabled and then enabled, concatenates both results, and applies a shared filter/sort stage. Replaced the detector's fuzzy name-score heuristic with exact key-token equality in both passes. The normalized pass strips the recovered number/comment patterns, handles dot-qualified names, and filters the observed noise words. `GetColumnKey` falls back to the table name whenever a pass leaves no words, while `IsIdColumnKey` excludes a key whose complete name is one of those noise words; therefore literal `ID`-to-`ID` matching is filtered, and an ID-only column can match through table-name fallback.

REA's primary-key selector admits an explicit key or a unique, null-free column and uses cardinality multiplied by ten as its leading rank, with existing PK/FK flags as tie-breakers. Analytics Studio's detection input does not carry those role flags, so the local sort uses deterministic table/column names for ties. Exact pass and priority evidence and remaining limits are recorded in the REA notes. Tests were not run for this increment.

## 2026-10-19 — REA relationship candidate filters and graph behavior

Decoded the `GetColumnsByKey` column predicate and the helper that checks composite-key metadata. Power BI excludes calculated columns, columns with unsupported relationship key types, and columns whose `RelatedColumnDetails.GroupByColumns` list is nonempty. The local model already stores calculated-column definitions, so the relationship detector input now carries those names and the detector skips them. The project model has no matching `GroupByColumns` field, so composite-key columns cannot currently be represented or screened locally.

The detector's graph traversal follows all model relationship records in both directions; no active-state check appears in the inspected CIL. The local autodetector now uses active and inactive saved relationships when screening connected paths. `GetColumnsByKey` also has two count gates with the literal value 30 for repeated same-key columns and repeated candidates for the same participating-table set. These observed limits are recorded in the REA notes; their full output effects remain under investigation.

Tests were not run for this increment.

## 2026-10-19 — REA autodetection type gate and key-group limits

Decoded the existing `GetColumnsByKey` CIL and its compiler-generated column predicate in Power BI Desktop 2.157.879.0. The predicate admits only relationship key enum values 1–3; enum field order identifies those as String, Int, and Double. Boolean, Date, DateTime, and Time have key-type mappings but are filtered out before candidate generation. The local autodetector now follows that evidence and only considers text, whole-number, and decimal columns.

Traced both literal 30 gates through `KeyCounter<T>.Add`: the per-table/per-key counter increments then branches on `>= 30`, retaining at most 29 columns for that key in each pass; the second counter increments for each key group sharing the comma-joined distinct participating table names and branches on `> 30`, retaining at most 30 such groups. `detect_relationship_candidates` now applies both caps independently in the literal-name and normalized-name passes. Evidence is in the retained `ev_e32d8e815db901433ceec5b5e5c34463216f9aebdc7975169c3558f4f01d122f` managed CIL record; method tokens are build-local to the documented DLL digest.

Tests were not added or run for this increment.

## 2026-10-19 — REA direct relationship map and candidate path filtering

Decoded the existing relationship call flow more deeply. `MapExistingRelationships` records saved relationships as direct table-pair keys, and `AreRelated` checks that set rather than computing transitive connectivity. `FilterAndSortColumnPairs` separately assigns path lengths across existing and proposed edges, sorts by those lengths, and grows its maximum from 1 up to the caller's limit of 4, stopping when the requested table set is connected or the limit is reached. The local detector receives all eligible candidate tables, so its prior per-candidate breadth-first check was dropping suggestions based on transitive paths that the direct-pair gate does not reject. Removed that extra suppression while retaining the existing direct-pair check. Scoped path-length selection remained open at this checkpoint and is implemented in the later scoped-autodetection increment above.

REA CIL evidence is retained in `ev_e32d8e815db901433ceec5b5e5c34463216f9aebdc7975169c3558f4f01d122f`; method tokens remain build-local to the recorded assembly digest. Tests were not added or run for this increment.

## 2026-10-19 — REA relationship key discovery and primary-key order

Decoded the `DetectCore` loop and `GetPrioritizedPKColumnsWithTheSameKey` delegates from the installed Modeling Engine assembly. The detector visits discovered key groups in order, sorts eligible primary-key columns by distinct cardinality multiplied by ten plus foreign/primary-key role flags, and checks each group's other columns in discovery order. Its local model has no persisted column-role flags, so Analytics Studio now preserves key-group order and sorts unique, null-free candidates by cardinality, retaining discovery order on ties. It records each proposed table pair before proceeding to later groups and the normalized pass.

Updated `detect_relationship_candidates` to follow that sequence instead of selecting the largest-cardinality candidate across each table pair and globally sorting the results. At this checkpoint the path-length selection pass, explicit key roles, and composite-key metadata remained unmodeled; the later scoped-autodetection increment closes the path-filter gap. Static evidence is retained in `ev_e32d8e815db901433ceec5b5e5c34463216f9aebdc7975169c3558f4f01d122f`. Tests were not added or run for this increment.

## 2026-10-19 — REA identical-schema relationship suppression

Decoded the detector's `HasIdenticalSchema` guard and its helpers. Power BI rejects a candidate when both tables have the same column count and every user column in one has a matching name and data type in the other; the user-column filter excludes Tabular's RowNumber column type. Analytics Studio's detector now skips candidates when the loaded header/type schemas match, including local calculated-column names when the loaded input does not already include them. The controller supplies calculated-column names as strings, so the detector now handles both that payload and dictionary-shaped names and correctly excludes them from key groups.

The app's model does not represent a separate RowNumber column, so this covers its persisted schema shape rather than all Tabular table metadata. Evidence is in the retained 2.157.879.0 Modeling Engine and Tabular artifacts associated with `ev_e32d8e815db901433ceec5b5e5c34463216f9aebdc7975169c3558f4f01d122f`. Tests were not added or run.

## 2026-10-19 — REA request scope and blank-only relationship candidates

Traced `RelationshipDetectionHandler.Detect` through its request callback. A nonempty `RelationshipDetectionRequest.Tables` list becomes `tablesToBeConnected`, and the native detector runs `FilterAndSortColumnPairs` only when that list is nonempty. At this checkpoint the manual relationship dialog had no target-table scope, so its global action correctly followed the native null/empty-scope path. The later scoped-autodetection increment preserves that global action and adds optional selected-table scope.

Decoded `GetPrioritizedPKColumnsWithTheSameKey`: its predicate admits an `IsKey` column or a column that is unique and has no nulls. The separate `CanBeOneSideOfRelationship` helper accepts missing cardinality information and otherwise requires uniqueness with no nulls. Neither inspected path contains a separate nonblank-value predicate. Removed Analytics Studio's additional nonblank gate for otherwise unique/null-free loaded columns. The local project does not store `IsKey` or composite-key metadata, and static CIL does not establish whether empty text is reported as a model blank. REA evidence is bound to Modeling Engine SHA256 `466838efa60138e8bc685a07e3ee61063fd8ab8c104bd556107e6999736b128b`, including handler request-flow Evidence `ev_6057f01b993187526228d6318a70ca066f6abc1f4cba75daad8d7f27dfeb7cbd` and detector Evidence `ev_4f1004c9adcf58cfae5b5b76d6ccf6c4007f69ab723d6daa1a8b14919da1f0be`. Tests were not added or run.

## 2026-10-19 — REA relationship key-role ranking

Inspected `RelationshipDetectionFast` fields and call flow. Power BI keeps PK and FK column sets, populates them from existing relationships, and adds each accepted candidate with the candidate endpoint as FK and selected unique endpoint as PK. Its descending priority is `distinct cardinality * 10 + (not FK ? 1 : 0) + (PK ? 2 : 0)`. Existing one-to-one relationships orient those role sets by comparing endpoint distinct cardinalities; other relationships use stored from/to order.

Analytics Studio now reconstructs those role sets from loaded saved relationships, updates them for each proposal, and uses the same score. Equal scores keep key-group member order. At the time of this entry, the model had no explicit `IColumn.IsKey` property; this gap was addressed on 2026-10-19 with the persisted table `key_column` signal described above. REA evidence is bound to Modeling Engine SHA256 `466838efa60138e8bc685a07e3ee61063fd8ab8c104bd556107e6999736b128b`; role-set fields and method anchors are retained in `ev_2f9ce59167571bebe975ee8cdc97e5ea1dcd6349bb3b03f22ab9f122a4a81c2f`. Tests were not run.

## 2026-10-19 — Model relationship diagram view

Added a Diagram view switch to the existing Model workspace. It lays out the existing model table cards, draws saved structured relationships with active/inactive line styles, one/many cardinality markers, and single/both filter-direction arrows, highlights relationship columns, and lets users select a field for the existing column inspector. The existing table list and Manage relationships workflow remain available; older display-only links or links whose tables are not currently shown are called out and remain in the saved relationship list. No project-format change was needed.

REA analyzed the installed Minerva `modelView.html` and `scripts/desktopModelView.min.js` as inert source under Evidence `ev_b89dc33d93576194cd4561ef9dd4f60b5c04dc9b498154b1e032edb048120f20`. The script's semantic graph exceeded the result budget, so this analysis anchors the installed page and bundle, not detailed runtime behavior. `pyside6-qmllint` parsed `ModelView.qml` with no errors; its output includes existing style warnings across the file. `python3 -m py_compile analytics_studio/controller.py` and `git diff --check` passed. Tests were not run. Exact Power BI auto-layout, drag/move, zoom, and relationship editing interactions remain unverified and unsupported by this increment.

## 2026-10-19 — REA relationship dialog result and delete confirmations

The installed `scripts/desktopDialogHost.lazy-modeling-dialogs.min.js` contains the `LazyModelingDialogModule` (Webpack module key `37735`). Static source references include an autodetection result notice for either a found count or no-results case, plus an OK/Cancel confirmation before deletion. Its selection model is configured for multi-select and the selected delete action submits all selected relationships together. Analytics Studio now shows the autodetection result in an information dialog, supports extended relationship selection, and confirms a staged batch deletion once. The relationship changes remain staged until the user selects Save.

REA Evidence `ev_3d3caf60d9a88de48ceeef82215c909fd6e82ebb115d322335a54bba8e54b6d6` records the selected source analysis; the feature traces are `ev_26ff59fe02a7a6194cdd2afcce3ec799c71f28800954cdd1d9a8403833a48a78` and `ev_e768f4a20faa33abbce78bd709a4c02e22904214b3768ccb0c5fc7f917999c0d`. These are static findings only: the analysis selected one file, left 2,603 inventoried files outside scope, and did not execute Power BI. `python3 -m py_compile analytics_studio/relationship_dialog.py` and `git diff --check` passed. Tests were not run.

## 2026-10-19 — REA relationship list filters

Added checkable Cardinality and Cross-filter direction menus to the existing Manage relationships list. Multiple choices within each menu match as an OR group; when both menus have selections, a relationship must match at least one selected value from each group. Clear filters restores the full staged list. The local editor uses its four persisted cardinality forms and Single/Both directions.

The installed lazy modeling dialog's `RelationshipsMatTableDataSource.filterPredicate` implements the same within-group OR / across-group AND rule. Its values are `ManyToOne`, `OneToOne`, and `OneToMany`, with `ManyToMany` when the model supports it; these map to the four local cardinality values. Native `OneDirection`/`BothDirections` map to local `single`/`both`. The filter and editor now use the native cardinality option order. REA filter-label traces `ev_297f20e95ac00068f1e759b72cb2601d63474f2e90e2888a7e57675d95666fa8` and `ev_bb3af16e72e8e6dc0f5f97940a85e025fb8427f910ca2497effce02f2c3c4680` link the labels to the selected lazy modeling module. This is static artifact evidence, not runtime behavior.

## 2026-10-19 — REA relationship-list sorting

Added a display-only sort menu for the four relationship-table dimensions observed in `RelationshipsMatTableDataSource`: From table/column, combined relationship cardinality/direction, To table/column, and active state. The menu supports ascending and descending order and defaults to ascending From table/column. The list rebuild maps visible rows back to the original relationship definitions, so sorting does not reorder the project data. REA's selected module sorts by each endpoint column's lowercased display name, concatenated cardinality and cross-filter enum strings, and the Boolean text for active state. Analytics Studio now uses those same sort keys: column names alone, mapped PascalCase enum values, and `true`/`false` (`false` sorts before `true`, so inactive relationships appear first in ascending order).

The static source is retained in REA Evidence `ev_3d3caf60d9a88de48ceeef82215c909fd6e82ebb115d322335a54bba8e54b6d6`, for `desktopDialogHost.lazy-modeling-dialogs.min.js` SHA-256 `9aeceaf59c7c79d2467d4ea45ab9941d69dc052deccc4c2231d82a90ea79b0c1`. This source analysis did not execute Power BI. `python3 -m py_compile analytics_studio/relationship_dialog.py` and `git diff --check` passed; tests were not run.

## 2026-10-19 — REA autodetection From/To orientation

REA's installed detector constructs each result pair with the candidate column first and the selected primary-key column second (`RelationshipDetectionFast.DetectCore`, `ev_e32d8e815db901433ceec5b5e5c34463216f9aebdc7975169c3558f4f01d122f`). `RelationshipEditor.GetRelationshipCandidates` passes those pair items to `TryConstructDefaultRelationship` as `fromColumn` and `toColumn`; the helper checks uniqueness and nulls on both ends. With automatic direction enabled, it reverses endpoints when the proposed To end is not eligible as the one side. For the ordinary non-unique candidate and unique key case, Power BI keeps candidate → key and creates Many-to-One; if both ends are unique and null-free, it creates One-to-One. The helper sets Both cross-filtering when both endpoint cardinalities match, so One-to-One defaults to Both and Many-to-One to Single. The Minerva action consumes the returned `fromColumnUrn` and `toColumnUrn` directly (`ev_3d3caf60d9a88de48ceeef82215c909fd6e82ebb115d322335a54bba8e54b6d6`).

Analytics Studio previously reversed those endpoints and stored One-to-Many for the common candidate/fact case. It now keeps candidate → key when the selected key is unique and null-free, returns Many-to-One for a non-unique or nullable candidate, and switches endpoints when the selected key fails that one-side check. If both endpoints are unique and null-free, it keeps candidate → key and returns One-to-One. Generated One-to-One suggestions use Both cross-filtering; Many-to-One uses Single. This follows the helper's default orientation and direction. Supporting CIL evidence is `ev_0b709365fb2b9857be7d2316e29f89030509ba11d006d5e87a543277250ade57`, `ev_937439fe1e80909415035f28e47be04ba76654a8d74a18f67c0d0bf24574e9f0`, and `ev_ea9f7ab552ab43e8c1441591a1709a605b76b7e75bee93d29545577cf990222a`, bound to Modeling Engine SHA-256 `466838efa60138e8bc685a07e3ee61063fd8ab8c104bd556107e6999736b128b`. This is static artifact evidence; target runtime acceptance remains pending. Tests were not run.

## 2026-10-19 — REA relationship graph admission gap

REA's `RelationshipGraphEx.CanCreateRelationship` calls basic relationship validation and active-path checks (`EnsurePathIsUnambiguous`). At this checkpoint, the local implementation used a simple route-collision approximation and skipped proposals when neither endpoint could serve as the unique, null-free one side. The following entries replace the approximation with the CIL-derived path model and retry sequence. Evidence `ev_920d8e25c4123c1116cee4db638961232924cffa3d859ddfb73ddd277eec795f` covers the graph methods; `ev_ea9f7ab552ab43e8c1441591a1709a605b76b7e75bee93d29545577cf990222a` covers the helper. Only static CIL evidence was collected; runtime acceptance remains open.

## 2026-10-19 — REA shared-path relationship admission

- **REA evidence:** deeper CIL inspection of `RelationshipGraphEx.IsPathAmbiguous`, `CreateRelationshipsFilterGraph`, `FilterGraph<T>`, and `PathNode` shows that graph admission builds both relationship orientations, intersects reachable-table sets, reverses/composes path nodes, and compares directness (`ev_96fdfd356ca451b98b9920050aa10fcae832a3540e0e3534b6ae26ef569d9a86`, `ev_43daefd90048afa07b678c1f2e400ae11edcf0217abed3c2d5d715778780530c`). This establishes that endpoint reachability alone misses graph shapes that form a second route through shared tables.
- **Initial implementation:** the first pass used a directed simple-path collision check. The following increment supersedes that approximation with the static-CIL path model.
- **Verification:** the first pass used `python3 -m py_compile analytics_studio/relationships.py` and `git diff --check`; tests were not run.

## 2026-10-19 — REA relationship directness and default retries

- **REA evidence:** `RelationshipGraphEx` constructs forward and reverse graphs, `FilterGraph<T>` tracks edge directness, and `PathNode` retains directness while reversing and composing paths. `CanCreateRelationship` checks Single and Both behavior through `EnsurePathIsUnambiguous`; `TryConstructDefaultRelationship` retries cardinality, direction, and cross-filter behavior before falling back to inactive. Evidence: `ev_920d8e25c4123c1116cee4db638961232924cffa3d859ddfb73ddd277eec795f`, `ev_ea9f7ab552ab43e8c1441591a1709a605b76b7e75bee93d29545577cf990222a`, `ev_96fdfd356ca451b98b9920050aa10fcae832a3540e0e3534b6ae26ef569d9a86`, and `ev_43daefd90048afa07b678c1f2e400ae11edcf0217abed3c2d5d715778780530c`. The mounted package DLL and REA-cache copy have matching SHA-256 `466838efa60138e8bc685a07e3ee61063fd8ab8c104bd556107e6999736b128b`.
- **Implementation:** `detect_relationship_candidates` now builds both oriented graphs, keeps DFS paths with directness labels, prefers an all-direct path per table, composes candidate paths, and applies the recovered Single/Both checks. It also retries the default candidate as Many-to-One/Both, One-to-Many/Both, Many-to-One/Single, and One-to-Many/Single when applicable; failed admission returns an inactive review suggestion. Accepted suggestions join the graph for later candidates.
- **Scope:** this is an interpretation of static CIL, not proof of byte-for-byte or runtime equivalence. The mounted .NET Framework collection bodies are now inspected; how Power BI's model relationship enumeration maps to the local saved list, source-import blank behavior, and target runtime/lifecycle acceptance remain open.
- **Verification:** `python3 -m py_compile analytics_studio/relationships.py` and `git diff --check` passed; tests and target-runtime checks were not run.

## 2026-10-19 — REA relationship key-profile blank semantics

- **REA evidence:** `GetColumnsCardinalityInfoHandler.BuildColumnCardinalityInfoDax` formats the installed detector's profile query from `distinctCount`/`DISTINCTCOUNT`, `totalCount`/`COUNTROWS`, and `containsNull`/`NOT ISEMPTY(FILTER(table, ISBLANK(column)))` templates (`ev_357fd938cfefceb6a60a6c444b2bbf2604bf806cae76a90decbfcb1f6402b61b`, bound to Modeling Engine SHA-256 `466838efa60138e8bc685a07e3ee61063fd8ab8c104bd556107e6999736b128b`). Microsoft documents DAX model blank handling for nulls, blank values, empty cells, and missing values, while warning that empty strings and blanks can differ by operation ([Power BI data types](https://learn.microsoft.com/en-us/power-bi/connect-data/desktop-data-types), [DAX BLANK](https://learn.microsoft.com/en-us/dax/blank-function-dax)).
- **Implementation:** relationship autodetection's local column profile now counts zero-length text as a blank for its uniqueness, distinct-value, and null-presence calculation. `_relationship_value_key` retains the separate local key category for other relationship consumers.
- **Scope:** the mapping is a reasoned DAX-profile approximation. REA could not inspect `Microsoft.MashupEngine.Library45.dll` member metadata because it exceeded the 64 MiB representation budget, and the Windows VM has no accessible interactive session in this capture context. Connector-specific source-import behavior and the profile query's runtime result remain unverified.
- **Verification:** `python3 -m py_compile analytics_studio/relationships.py` and `git diff --check`; tests were not run.

## 2026-10-19 — REA relationship path directness correction

- **REA evidence:** focused member inspection and CIL decoding of `FilterGraph<T>.CollectReachableTablesDFS`, its callback, `PathNode.GetPathToRoot`, `PathNode.ToList`, `PathNode.IsAmbiguous`, and its predicate lambdas show two separate rules. DFS replaces a previously reached table only when a newly discovered path is all-direct and the previous path is not. Ambiguity compares `IsDirect` across nodes present in only one path; shared nodes are filtered out first. Evidence: `ev_f800ffa436da0d5f39fa379cd11244b40ddc6f9253c7ad0dbe5c06a9f11af9ad` and `ev_3aeaaabba90dafd5800ddbaea3c79aee3169d7f9ef0d9974c244a4e9a327a304`, bound to Modeling Engine SHA-256 `466838efa60138e8bc685a07e3ee61063fd8ab8c104bd556107e6999736b128b`.
- **Implementation:** corrected `paths_are_ambiguous` to compare whether each nonshared segment is all-direct. The prior version compared shared nodes and used the cumulative `AllDirect` flag on one side; that did not match the installed CIL.
- **Scope:** this refines the static-CIL graph port. Enumeration order, source-import blank handling, and target-runtime behavior remain open.
- **Verification:** `python3 -m py_compile analytics_studio/relationships.py` and `git diff --check`; tests and target-runtime checks were not run.

## 2026-10-19 — REA filter-graph edge identity

- **REA evidence:** `FilterGraph<T>.Add` stores `KeyValuePair<T, bool>` edges in a `HashSet`, while `RelationshipGraphEx` loads all model relationships into per-`FromTable` lists and `CreateRelationshipsFilterGraph` checks activity only after flattening those lists (`ev_7a04705a4c214d99801ac8088cb5b9f6ab2d2e52981f88d089ed0f1d303ead66`, `ev_c92635acd6461906d255a400c0990ca02c416e909bfa2934920df0f4a6a2136f`, `ev_920d8e25c4123c1116cee4db638961232924cffa3d859ddfb73ddd277eec795f`). Identical `(target, isDirect)` edges collapse, but the same target with different directness remains a distinct graph edge; inactive relationships still establish their table-group order.
- **Implementation:** the local filter graph now keys edge identity by `(target table, isDirect)` and keeps both directness variants. It retains inactive saved relationships until table grouping is built, then filters them while materializing active edges. DFS can retain the direct path when a table is reached through both direct and indirect edges.
- **Scope:** this closes the edge-identity mismatch. Collection enumeration order remained open at this checkpoint; the following entry records the static-CIL resolution. Target-runtime behavior remains open.
- **Verification:** `python3 -m py_compile analytics_studio/relationships.py` and `git diff --check`; tests and target-runtime checks were not run.

## 2026-10-19 — REA filter-graph collection order

- **REA evidence:** the mounted .NET Framework `Dictionary<TKey,TValue>.Enumerator.MoveNext` and `HashSet<T>.Enumerator.MoveNext` scan their backing arrays by increasing index. `Dictionary.Insert` allocates at `count` when its free list is empty; `HashSet<T>.AddIfNotPresent` allocates at `m_lastIndex` when its free list is empty. The `Resize` and `SetCapacity` loops preserve those slot indices. The filter graph groups relationships in a dictionary and per-source lists, then adds edges to HashSets without removing entries, so the native containers enumerate those graph insertions in order. Evidence: `ev_c7318fb29ded17db2a2de5b396e712e3182e3553678cfab0bb21fecb588fda55` (mscorlib enumerators), `ev_6ffa0727ec7b4b8f7cf08ec464a6b4bccd92a512b1b2bfa7f2213e43ff9a92b1` (mscorlib Dictionary), `ev_b5545f62aa494c100df4539e8e8f72dd1ea4717c26e27b1cf2a76ded26b5fa4d` (System.Core enumerators), and `ev_355dfe695279185df18a0dbf6c855c469496278007794658d16bac590f277971` (System.Core HashSet). These BCL files are from the mounted Windows image; their SHA-256 values are recorded in the REA index.
- **Implementation:** the local filter graph already uses insertion-ordered Python dictionaries/lists and keeps a list alongside an edge-membership set. No code change was needed; the native collection inspection confirms that representation for the graph's no-removal build path.
- **Scope:** this established the graph's internal container traversal order. The following entry traces its relationship input sequence through the installed model adapter. Source-import behavior and target-runtime/lifecycle parity remain open.
- **Verification:** static evidence inspection only; tests and target-runtime checks were not run.

## 2026-10-19 — REA relationship model-collection order

- **REA evidence:** `RelationshipGraphEx` enumerates `IDataModel.Relationships` directly. `TabularDataModel.get_Relationships` obtains `Microsoft.AnalysisServices.Tabular.Model.Relationships` and passes the collection through `ModelObjectConverter`; its enumerable adapter uses LINQ `Select`. The Tabular `RelationshipCollection` delegates to `NamedMetadataObjectCollection`, whose Analysis Services backing collection enumerator walks the ordered key list: `ModelComponentEnumerator` gets a `StringEnumerator` from `StringCollection`, and the .NET Framework `ArrayListEnumeratorSimple` advances through the backing array by index. The supporting evidence is `ev_e29f85c0a5742c27ab5a8daaa5c45418f79761ef7eb1c1f3d4fe717a6520900d`, `ev_970adfcc4f4fdf6acf4d1c56978c82e8e2ff73d6fff1c2bba846cae9274d5937`, `ev_55ba82fe0d04175e9b84e8dc4ca7b508dd39dd8f4a3053208548ae0278afe940`, `ev_044188a59a7ce51f736093b83fd3d30d5c033c003cda199827535f6343a76aff`, `ev_3274d5361a13c4aa6559257c5761102f211f2536e79fc99f9280321075b46040`, `ev_6965583185de1ff4356de85b49bd4ee6d14c7727e5e548b3ec4d4052f2dff68e`, `ev_449bf6a6d8149b2305d96b3f9e2b976c9968654b645c170da9a7a53da1b06b34`, `ev_154460047590eabe4420f18e4e597de88581c4acc3731a9c464cd4fafa985122`, `ev_524f459afb4eec854c4605023a867d867a5752459f3d4d531e563b42fa8a91c3`, `ev_cfa8ea83e8af9933d23fa5c8fc89c0f6f61a571290f452d146b8b31324633b65`, and `ev_9422249bef2396c3d79e169062c5e2657a0ed5af4fc227e0bb6b00c611290722`. Artifact hashes and the exported REA snapshot are in the evidence index.
- **Implementation:** the app already matches this sequence for its own models: the relationship dialog appends new definitions, project normalization retains list order, and autodetection iterates the saved list without sorting it. Added a code comment at the detector input loop to preserve this behavior. No algorithm change was needed.
- **Scope:** this resolves source-collection ordering for Analytics Studio-authored projects. Analytics Studio does not import PBIX models, so translation of an external model's serialized order is not covered. Connector-specific blank import behavior and target-runtime/lifecycle acceptance remain open.
- **Verification:** `python3 -m py_compile analytics_studio/relationships.py` and `git diff --check`; tests and target-runtime checks were not run.

## 2026-10-19 — Power BI text relationship-key trailing spaces

- **Evidence:** Microsoft's Power BI data-types documentation describes the in-memory model as case-insensitive and says trailing spaces are removed or trimmed while leading spaces remain. This affects one-side uniqueness and matching for relationship keys.
- **Implementation:** the shared local relationship comparer now removes trailing ASCII spaces before Unicode case-folding text keys. Leading spaces remain significant. A value made only of trailing ASCII spaces enters the existing empty-text category; the autodetection profile then applies its existing DAX-blank approximation.
- **Scope:** this follows documented model behavior, not an REA runtime trace. It does not establish connector-specific empty-text import behavior, locale-specific collation, or trimming of tabs and other whitespace. Target-runtime/lifecycle acceptance remains open.
- **Verification at implementation time:** tests had not yet been run; static checks were `python3 -m py_compile analytics_studio/relationships.py` and `git diff --check`. The REA verification follow-up below records the later regression and full-suite results.

## 2026-10-19 — REA relationship scope regression and verification

- **Regression coverage:** added focused checks for detector ordering/caps/type gates and graph retry behavior, relationship-dialog scope/filter/sort/delete staging, controller wiring of `key_column` and `group_by_columns`, their project migrations and save/reopen behavior, trailing-space key comparison, and the Model diagram's saved-endpoint/field-selection path.
- **Fixes found during verification:** normalized key-name noise filtering before comparing noise words; apply the selected-table path filter before constructing graph/default suggestions; guard transiently unavailable `ListView.view` data while Model diagram delegates initialize; and update a stale format-version assertion after project format advanced to v82.
- **Focused verification:** `QT_QPA_PLATFORM=offscreen PYTHONPATH=. python3 -m pytest -q tests/test_relationship_autodetect.py tests/test_relationship_dialog_rea.py tests/test_relationship_lifecycle.py tests/test_project_migration.py tests/test_model_data_views.py tests/test_model_column_sorting.py` passed **112 tests and 106 subtests** after the controller integration check was added.
- **Full application verification:** `QT_QPA_PLATFORM=offscreen PYTHONPATH=. python3 -m pytest -q tests` passed **906 tests and 712 subtests**. `python3 -m compileall -q analytics_studio tests` and `git diff --check` passed. `pyside6-qmllint analytics_studio/qml/ModelView.qml` parsed with no errors; it still reports pre-existing style and unqualified-access warnings across the file.
- **Test discovery note:** unrestricted `python3 -m pytest -q` crawled into `gridcraft/target/macos-package`, including GIMP's embedded Python 3.10 standard-library tests, and stopped with collection errors there. The supported app suite is under `tests/`; that explicit full run passed.
- **Remaining scope:** this verifies Analytics Studio's local implementation. REA evidence remains static, so Power BI runtime suggestion parity, connector-specific empty-text profiling, locale-specific collation, the full featured-table key experience, GroupByColumns effects on visuals/filters/DAX, and exact Model diagram layout/edit/zoom behavior remain unverified or out of scope. The local diagram is a tested read-only visualization of saved relationships, and manual acceptance in the Windows Power BI target remains pending.

## 2026-10-19 — Full functionality test rerun and app startup

- **Full pytest:** `QT_QPA_PLATFORM=offscreen PYTHONPATH=. python3 -m pytest -q tests` passed **906 tests and 712 subtests**.
- **Full unittest:** `QT_QPA_PLATFORM=offscreen PYTHONPATH=. python3 -W default::ResourceWarning -m unittest discover -s tests -q` passed **829 tests**. The run no longer reported unclosed SQLite connections.
- **Test-fixture cleanup:** changed SQLite fixture connections to close after their commit/rollback context. Python's SQLite connection context manager manages transactions; it does not close the connection. A few `TemporaryDirectory` implicit-cleanup warnings and expected offscreen Qt/font/image-plugin messages remain.
- **App startup smoke:** ran `analytics_studio.main.main()` under offscreen Qt, loaded and created the actual `Main.qml` window, let the event loop run briefly, then exited via a timer. Exit code was 0.
- **Static checks:** `python3 -m compileall -q analytics_studio tests` and `git diff --check` passed. The QML lint parse was already run during the REA relationship verification entry above; it reported no parse errors and existing style/access warnings.
- **Environment boundary:** these checks verify local automated workflows and an offscreen launch. Live SQL Server, OData/Web endpoint acceptance, native macOS interaction review, and interactive Power BI Desktop comparison still require their respective service/desktop environments.

## 2026-10-20 — Import Load / Transform choice and Power Query staging

- **Implementation:** file, folder, SQL Server, OData, and Web import previews now offer **Load** and **Transform data**. Transform stages the selected source in Power Query; **Close & Apply** commits it, while Cancel leaves the project unchanged. Connector previews launched from within Power Query do not open a nested editor. Remote credentials remain staged until commit.
- **REA reference:** installed Power BI Desktop `2.157.879.0` managed metadata inspection found distinct commit/cancel labels and query-editor flow contracts in `Microsoft.Mashup.Client.Desktop.UI.dll`. Evidence records `ev_fbbb0e33d7846e39bc124531a801ada7221d26be2d8d9e516595d2541d65b91d` and `ev_a80e91090da537999357418bf179cdb44c5045c4847424d64a22d16ccc3584bd`; JavaScript host analysis is partial (`ev_17c66fe791ba3e41fb6e4565e8566947afaabc12a936788abf1b49ecc64c7d18`). These are static findings, not proof of live Power BI behavior. Evidence export: `/Users/armaan/Library/Caches/codex-powerbi-rea/2.157.879.0/rea-evidence-bundle-20261020-import-transform.json`.
- **Additional fix:** explicitly set the Power Query preview and Applied Steps panes to the editor palette, preventing dark-mode palette inheritance from changing their widget colors.
- **Verification:** `QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests` passed **918 tests and 715 subtests**. `python3 -m compileall -q analytics_studio tests` and `git diff --check` passed. Restarted `python3 -m analytics_studio.main` for interactive review.
- **Remaining scope:** the import staging workflow is implemented and locally tested. The local M transformation engine is still a partial subset, not Microsoft's Mashup engine; full operation, connector, preview, and runtime parity remains open. A recording of the matching Power BI import/transform steps and a shareable sample workbook would help resolve visible behavior against the installed target.

## 2026-10-20 — Power Query and Data view filter discoverability

- **Power Query UI:** the preview column header now clearly signals its sort/filter menu. It offers **Filter by values** with search, visible-value selection, distinct null/empty choices, and an applied filter step; **Filter by condition** remains available for comparisons. The active filter column is highlighted. Value filters are bounded to 64 selected values and 2,000 distinct preview values; error cells must be removed or replaced before value filtering.
- **Data view UI:** replaced the subtle header chevron with a visible filter glyph and active-filter styling. Data view filters remain preview-only and do not change model rows, report results, or saved query steps.
- **Verification:** focused Power Query/Data view tests passed **130 tests and 184 subtests**. The complete suite passed **921 tests and 715 subtests**. Coverage includes menu selection, search/check state, OR-based selected-value filtering, null versus empty text, M round-trip, active-filter indication, preview-only Data view behavior, and table switching. `python3 -m compileall -q analytics_studio tests` and `git diff --check` passed.
- **Remaining scope:** the local filter list is intentionally bounded and the local M bridge is not Microsoft's Mashup engine. Numeric/date filter parity against a running Power BI Desktop session remains unverified.


## 2026-10-20 — Model relationship diagram layout

Kept Diagram as the default Model view and improved bounded star-model placement, disconnected-table ordering, relationship route clearance, and stacked hub ports. Added regressions for mixed models and six-/eight-table hubs. The focused Model suite passed 26 tests; the full offscreen suite passed 930 tests and 715 subtests. Ruff, compileall, and targeted diff checks passed. REA evidence remains version-bound static evidence for selected Power BI internals; no runtime diagram-layout parity is claimed.

## 2026-10-20 — Model diagram viewport and details

- The Sidecar window capture showed that the first Model diagram viewport included a full measure-expression panel, source summary, active-table field chips, and an unselected column inspector before the relationship graph.
- Diagram mode now shows a compact count and a direct Table list action when measures exist. Full measure expressions and calculated-column definitions stay available in Table list mode; source/active-field summaries are also scoped there. Selecting a diagram field restores its column inspector.
- Added a linked two-table compact-width regression at 800 px covering the one-column workspace, measure-summary action, restored formulas/column definitions, and inspector transition.
- Independent visual review found no material blocker. The test suite passed **27 focused Model tests** and **931 full-suite tests with 715 subtests**. Ruff, compileall, and diff checks passed.
- Analytics Studio was displayed on Sidecar and captured from its app window only using a temporary in-memory four-table model and measure. The sample was not saved. The app's production minimum width is 1040 px, so the running preview stayed within Sidecar; no live Power BI interaction or runtime diagram comparison is claimed. REA's inspected Model-view bundle is partial static evidence. Draggable/persisted coordinates, multiple disconnected star layouts, formulas inside diagram cards, and native accessibility remain open.

## 2026-10-20 — Zoom-stable visual resize target

- **Finding:** the selected visual's 14-unit resize grip was measured in report-local coordinates while the report canvas was zoomed. At 15% zoom the pointer target shrank to 2.1 Qt scene units, making precise resizing impractical.
- **Change:** scale the grip dimensions, diagonal spacing, and stroke width inversely with report zoom, targeting 16 Qt scene units when the visual is large enough. The hit area remains bounded by the visual. Added an accessible name and pointer-drag coverage for grow/shrink at 15% and 150% zoom.
- **Verification:** the regression measured the 2.1-unit pre-fix target, then passed all four zoom/direction combinations after the fix. The full offscreen suite passed twice (**937 tests and 715 subtests** each); `compileall`, targeted Ruff, and `git diff --check` passed.
- **Scope:** this verifies Analytics Studio's local QML/controller behavior. No live Power BI resize comparison was made; the user asked to keep the app on Sidecar without activating or disturbing their work, and the current REA window inspection exposes no child controls. Tiny visuals remain bounded by their own dimensions; keyboard resizing is not covered.

## 2026-10-20 — COUNTROWS optional-table guidance

- **Finding:** the local measure editor showed only `COUNTROWS('Table')` and described the table as a required argument, even though the local evaluator already accepted `COUNTROWS()` using the measure's home table. Microsoft's [COUNTROWS reference](https://learn.microsoft.com/en-us/dax/countrows-function-dax) documents the table argument as optional with the current expression's home table as its default.
- **Change:** the selected-function syntax and caret help now explain the optional argument, home-table default, and supported local explicit table forms. The evaluator and calculation behavior were not changed.
- **Verification:** the focused dialog/editor and existing home-table/average checks passed; the final offscreen project suite passed **938 tests and 715 subtests**, with an independent full run at the same counts. `compileall`, targeted Ruff on the changed dialog/test files, and `git diff --check` passed. An offscreen visual probe with a typed `SUM` prefix showed the suggestion list and inline help.
- **Scope:** no live Power BI UI was activated, raised, moved, or clicked. The sample average path is local evidence, not validation of the user's formula or dataset; broad DAX/Tabular compatibility and native Sidecar acceptance remain open.

## 2026-10-20 — Model table-list search

- **Finding:** Model → Table list showed every eligible table and column with no name-based way to find a specific item. The Model diagram's relationship arrows describe filter direction; they are not row filters.
- **Change:** added transient case-insensitive table/display-name and loaded-column search, Clear and no-results states, a notice when the retained inspector selection is hidden, and continued Open data navigation. Search does not mutate project state, row data, or report filters. Added a regression for the search header spanning the full workspace above the table cards.
- **Verification:** the focused lifecycle test passed. The fresh full offscreen suite, compileall, targeted Ruff, and diff check are recorded in `.council/TEST_RESULTS_ITER39.md`.
- **Visual correction:** a main-display smoke exposed a dark host-style search field and faint placeholder/border. The field now has explicit dark text, a 4.80:1 placeholder, white background, 3.59:1 normal border and 5.07:1 focus border, plus selected-text colors. Contrast regressions cover the placeholder and both border states. The actual local app is left open on the main display with a disposable synthetic three-table project; its screenshot is [here](docs/verification-artifacts/model-table-list-search-contrast.png).
- **REA/runtime boundary:** the pinned installed Model-view bundle was partially parsed as inert JavaScript. Its `Search tables` localization string is not runtime proof. The user authorized the main display for the local app preview, but the current Windows guest exposes no Power BI window handle/title; no live Power BI comparison or activation occurred. See [REA target notes](docs/rea-power-bi-desktop-2.157.879.0.md).
- **Remaining scope:** this search narrows the Table list only; it is not Power Query value filtering, Data-view row filtering, Power BI featured-table data search, or model/report filtering. Full Power BI runtime and visual parity remain open.

## 2026-10-20 — Model-aware DAX reference help

- **Change:** local measure authoring now suggests loaded table names, qualified columns, home-table columns, and saved measures inside the matching open DAX reference. Acceptance preserves surrounding formula text, handles quoted/apostrophe names and Qt UTF-16 cursor positions, and places the caret after an existing closing token. Function completion remains separate.
- **Local verification:** `SUM([Sales])` previewed as 350 against an in-memory two-row sample. DAX completion regressions cover field/measure/table suggestions, apostrophes, suffix preservation, click/keyboard acceptance, cursor state, and suppression inside strings/completed references.
- **Live Power BI comparison:** after the user's authorization to use the main display, typing `SUM(` in Power BI showed `SUM(ColumnName)`, “Adds all the numbers in a column,” and loaded-column suggestions. REA evidence: window 12568, `ev_b82caa80e075bb1ec249440800a00ec89f938a93fd4b7c3ebe9648763e11929d`. The Parallels `WinAppHelper` proxy exposed only its top-level window to REA; this is visual UI evidence, not access to the Windows DAX engine. The Power BI draft was canceled without saving.
- **Verification:** full local pytest **941 passed, 715 subtests passed**; focused DAX completion **2 passed**; targeted Ruff, compileall, and `git diff --check` passed.
- **Open:** this is local partial DAX editor help, not full IntelliSense or Tabular parity. The user's incorrect-value report remains unresolved until the exact expression and expected result are captured. Power Query header mouse behavior, model-view visual parity, and live chart resize comparison remain open.

## 2026-10-20 — Chart resize minimum and visible lifecycle check

- **Finding:** the resize drag handler enforced a 50-pixel floor while the controller and project schema accepted 10-pixel dimensions. Dragging a valid 40×40 chart inward could therefore enlarge it to 50×50.
- **Change:** aligned the QML drag floor with the existing 10-pixel controller/schema minimum. Added an offscreen pointer regression for 40×40 → 20×20 → 10×10, including save/reopen at each checked size.
- **Verification:** focused resize/zoom/lifecycle selection passed **7 tests**; full suite passed **949 tests and 719 subtests**. Ruff, `compileall`, and `git diff --check` passed. A temporary project on the main display grew and shrank a normal chart, saved at **380×250**, and reopened at the same size. The app-window capture is [here](docs/verification-artifacts/iteration46-chart-resize-after-reopen.png).
- **Boundary:** REA could not observe the Python process because its launch time was unavailable, and no Power BI resize comparison was made. The VAT workbook window remained untouched. Keyboard resizing and tiny-chart handle usability remain open; calculation accuracy and Power Query/Model filter concerns are separate.

## 2026-10-20 — Excel automatic-header reparse consistency

- **Finding:** the live comparison showed the local Data view at 573 rows and Transform preview at 611. Power BI displayed a cleaned 573-row query with cleanup steps and a separate 622-row raw query, so the counts alone do not define which intermediate row policy should match. A direct local parser reproduction isolated a state bug: automatic import detected row 12 and returned it as a numeric parser option; later reparsing treated that auto-detected value as an explicit manual row and preserved blank worksheet positions.
- **Change:** `.xlsx` and `.xls` candidates now keep `header_row=None` when the user selected automatic detection, while the locally detected row still drives header extraction and the preview notice. Explicit numeric header selections keep their current blank-row behavior. No project schema change or migration was added because saved numeric values do not record whether they were manual.
- **Verification:** tests cover omitted internal and trailing blank rows through automatic parse/reparse, Load, staged Transform, Apply, save/reopen, and `.xls` refresh. Focused imports/lifecycle passed **49 tests and 34 subtests**; full pytest passed **949 tests and 719 subtests**. Targeted Ruff, `compileall`, and `git diff --check` passed. The supplied VAT workbook returned **573 rows** on both first parse and reparse with equal headers and rows.
- **Compatibility boundary:** this proves local import-option idempotence, not Power Query/M or DAX parity. The old 611-row project options remain ambiguous unless the user selects Auto or reimports. REA could not attach to the running Parallels host during this session; the earlier Power BI comparison was direct visible UI evidence rather than a new REA capture. See [Iteration 47 verification](.council/TEST_RESULTS_ITER47.md) and [the review record](.council/CRITIQUE_REPORT_ITER47.md).

### 2026-10-21: Separate Excel Load and Transform start modes

- **Change:** Excel import preview keeps Load on automatic header detection and adds an explicit Transform option to treat worksheet row 1 as column names. The row-1 candidate is reparsed in the existing background worker; the Transform editor opens only after success. Manual header choices are kept, a failed reparse can be retried, and Cancel ignores stale completion.
- **Source identity:** Excel source matching includes the worksheet and `header_row`. Exact option matches win over the legacy fallback. On explicit automatic reimport, an older numeric-header source is reused only when the saved row equals current detection; the saved project is not changed merely by opening it. Numeric legacy settings cannot distinguish an old automatic choice from a manual one, so reimport of that same row remains ambiguous.
- **Power BI observation:** the main-display capture showed queries `VAT 5%` and `Table 3 (VAT 5%)`. The selected query displayed 573 rows × 14 columns and the applied steps `Source`, `Navigation`, `FilterNullAndWhitespace`, `Removed Bottom Rows`, `Removed Top Rows`, `Promoted Headers`, and `Changed Type`. It did not reveal the step arguments. A direct local parse of the supplied workbook returned 573 × 14 for Auto and 622 × 14 with row 1 selected as column names. This supports a separate Transform start choice, but does not establish the full cleanup that produced Power BI's 573-row query.
- **REA boundary:** the current REA `list_documents` request returned `provider_unavailable`; the diagnostic listed Ghidra as unconfigured, Hopper as missing, and IDA/Kuna as unconfigured. The current screenshot is direct system capture, not new REA evidence or a Mashup runtime trace. The attempted window arrangement also did not produce a reliable simultaneous side-by-side Power BI/local comparison.
- **Verification:** focused import tests passed **28 tests and 22 subtests**; the final fresh pytest run passed **957 tests and 719 subtests** in 38.87 seconds. `compileall`, Ruff on changed preview/parser/tests, and `git diff --check` passed. Ruff on the entire `controller.py` continues to report 12 unrelated existing findings; the source-lookup change is covered by regression tests. Critic and independent SDET reviews found no blocking issue. See [Iteration 48 test results](.council/TEST_RESULTS_ITER48.md), [critique](.council/CRITIQUE_REPORT_ITER48.md), [review issues](.council/REVIEW_ISSUES_ITER48.md), and [sign-off](.council/VERIFICATION_SIGN_OFF_ITER48.md).
- **Remaining scope:** Power Query row/value filter controls, full step-argument dialogs, exact cleanup-step parity, complete M/Mashup and DAX behavior, visible Model filtering, chart sizing, and reported calculation discrepancies remain open, independent tasks under the broader parity objective.

## 2026-10-21 — Power Query header dropdown controls

- **Finding:** the preview column header's painted funnel/menu area had no individual button or accessible label. Whole-header clicks already opened the local sort/value/condition filter menu, but the icon itself was difficult to discover and could not be focused as a control.
- **Change:** added a bounded pool of real `QToolButton` children for dropdown rectangles fully inside the header viewport. The down-arrow control has unique object names, accessible name/description and tooltip, and visible-only keyboard focus. It routes once to the existing menu while preserving clicks elsewhere on the header. The buttons rebind and reposition on scroll, resize, section geometry, and profile changes; hiding a focused button returns focus to the header. Tab order follows visible columns; modified Tab combinations pass through to Qt.
- **Review:** independent critic and test audit found no blocking issue. Review-driven regressions cover partial-scroll order/routing, Ctrl/Alt+Tab pass-through, focus leaving the full visible button sequence, and geometry/rebinding.
- **Verification:** focused header tests passed **6**; the Power Query M/editor module passed **117 tests and 181 subtests**; the full suite passed **963 tests and 719 subtests**. Compileall, targeted Ruff, and changed-file `git diff --check` passed. A temporary synthetic-data Power Query window was visually inspected on the main display; no project was saved.
- **REA/runtime boundary:** REA could not attach to the Python Qt smoke process (`target-mismatch`), and the analysis provider was unavailable. This is local Qt and visual evidence, not a new REA observation or live Power BI semantic comparison. No filter logic or M semantics were changed.
- **Open:** full Power Query/Mashup and DAX parity, Model/Report filtering, reported calculation discrepancies, and overall Power BI parity remain open. See [Iteration 49 results](.council/TEST_RESULTS_ITER49.md) and [verification sign-off](.council/VERIFICATION_SIGN_OFF_ITER49.md).

## 2026-10-21 — Power Query sparse-row formula parity

- REA directly observed the selected Power BI formula-bar M for `FilterNullAndWhitespace`, both sparse edge predicates, and `PromoteAllScalars=true`. The evidence bundle contains IDs and screenshot hashes; this is selected-step UI evidence, not the complete Advanced Editor query or Mashup runtime.
- Analytics Studio now maps those observed sparse steps, keeps the helper while any sparse trim still uses it, removes it after the final trim is deleted/replaced, and preserves later steps when editing an earlier formula-bar expression.
- A real VAT workbook smoke saved a temporary project, reopened it, reparsed the unchanged source, and replayed to **573 rows × 14 columns** with the Grand Total preserved. Local intermediate counts were **622 → 584 → 574 → 573**; Power BI showed **585 → 574 → 573** for the selected cleanup stages, so the bottom boundary differs by one row. An extra sparse row in Power BI source/navigation removed by the later top trim could explain this; that is an inference because Navigation was not captured. The original file hash did not change, and no Power BI project was saved.
- Reviewer follow-up confirmed no remaining implementation blocker. It identified a missing regression for replacing the only sparse trim; that case is now covered and passes.
- Automated verification after the final regression: sparse/header checks passed **12 tests and 2 subtests**; the full Power Query editor module passed **128 tests and 183 subtests**; full pytest passed **976 tests and 722 subtests**. `compileall`, targeted Ruff, and whitespace checks passed.
- Remaining scope: exact source/navigation and `Changed Type` expressions were not captured; row-by-row parity against Power BI's full output is not established. The UI controller's full project-open/refresh path, general Mashup execution, broad M/DAX behavior, reported calculation discrepancy, Model/Report filters, and chart parity remain open. See [REA evidence](docs/rea-power-bi-desktop-2.157.879.0.md#iteration-50-power-query-sparse-row-formulas-2026-10-21) and [Iteration 50 verification](.council/VERIFICATION_SIGN_OFF_ITER50.md).

## 2026-10-21 — Power BI VAT raw worksheet source

- Read-only ADOMD metadata identified the clean VAT query's no-header source and resolved the one-row trim difference from Iteration 50. The source produces 623 → 585 → 574 → 573 rows before/after the sparse trims and header promotion.
- Added persisted raw Excel source mode for Transform while preserving automatic Load and explicit-header behavior. A 14-column fixture tests Transform preview, Close & Load, save/reopen, and refresh with complete rows and metadata; the supplied workbook was replayed read-only with its source hash unchanged.
- Final verification: **190 focused tests and 217 subtests**, then **981 full tests and 722 subtests**; compileall, targeted Ruff, and `git diff --check` passed. REA UI screenshot capture was blocked by ambiguous Parallels proxy bounds; prior ADOMD evidence remains the comparison source.
- Full Mashup/M, DAX/Tabular, Model/Report filtering, visual, and overall Power BI parity remain open. See [Iteration 51 results](.council/TEST_RESULTS_ITER51.md) and [sign-off](.council/VERIFICATION_SIGN_OFF_ITER51.md).

## 2026-10-21 — Filter discovery and scope

- The Report Filters pane now starts open and Reset Layout restores it; the Region quick-filter card is omitted when there are no Region values. Data view exposes the existing Values/Condition dialog through a Filter rows action, labels its preview-only scope, and reports the number of active filters. Model view clarifies that it holds relationships/properties and offers a width-adaptive route to Data view. At the 1,040 px app minimum, the direct header action is hidden to preserve compact layout; the tested Table list → Open data route remains available.
- Regression coverage at a 1,040 px main-window width with two tables verifies the Data action remains in-window, Append/Merge remain visible, the dialog opens for the selected column, and the count changes 1 → 2 → 1 → 0. Existing preview-only filter lifecycle checks remain in force.
- Focused filter/report tests passed **126 tests and 54 subtests**; a fresh full suite passed **984 tests and 722 subtests**. Compileall, targeted Ruff, and `git diff --check` passed. One earlier focused group had an intermittent dialog-visibility failure; the test passed alone and the repeated group and final full run passed.
- After display authorization, REA captured screenshot-only observations for Power BI Desktop and Power Query Editor through Parallels (`ev_626d3c5c…` and `ev_8f2bfc8d…`). The tiny proxy windows do not expose a unique AX tree, and REA could not attach to the local Python Qt process because launch-time identity was unavailable. No click or key entry occurred; there is still no usable side-by-side behavioral comparison.
- Open: an integrated Power Query header-filter → Apply → save/reopen → changed-source refresh test, complete M/Mashup and DAX/Tabular semantics, reported calculation mismatch, live visual/model parity, and the broader product goal. See [Iteration 52 results](.council/TEST_RESULTS_ITER52.md), [review](.council/REVIEW_ISSUES_ITER52.md), and [sign-off](.council/VERIFICATION_SIGN_OFF_ITER52.md).

## 2026-10-21 — Power Query header value-filter lifecycle

- Added an integrated header-authored Region value filter test through the real value dialog, Apply, Close & Load, project save, reopen, and changed-source refresh. It asserts East OR North and row IDs `[1, 2, 4, 5]` → `[7, 8]` → `[11, 12]`.
- The test exposed a PySide `Qt.CheckState` conversion bug in Select All; the handler now compares enum values and applies the intended partial-selection behavior. Critic follow-up added direct coverage for selecting from unchecked and keeping search-hidden values unchanged.
- Focused Power Query suite passed **175 tests and 183 subtests**; the final full suite passed **985 tests and 722 subtests** after review-driven selector assertions and watchdog cleanup. The exact lifecycle test passed again. Compileall, targeted Ruff, and `git diff --check` passed. Critic approved; the testing audit's cleanup nit was addressed.
- REA captured Power BI Data view (`VAT 5%`, 622 rows) and Query Editor (`Table 3 (VAT 5%)`, 573 × 14); local preview matched only the latter's shape. The selected views were different tables, so cell equality and full model parity are not established. No Power BI query edit/apply/save occurred. See [REA evidence](docs/rea-power-bi-desktop-2.157.879.0.md#iteration-53-main-display-power-query-comparison-2026-10-21), [results](.council/TEST_RESULTS_ITER53.md), [review](.council/REVIEW_ISSUES_ITER53.md), and [sign-off](.council/VERIFICATION_SIGN_OFF_ITER53.md).
- Remaining scope includes native popup hit-testing, cancellation/error recovery, model/report consumption, broad M/Mashup and DAX/Tabular behavior, chart parity, and the reported calculation discrepancy.

## 2026-10-21 — Selected Applied Step value-filter insertion

- A header value filter now inserts after the selected Applied Step because its available values come from that selected preview; no selection or a final-step selection appends. The staged pipeline and metadata are replayed before dialog state is committed, preserving state on replay failure.
- Lifecycle coverage verifies selected-preview versus full-chain output, metadata through Apply/save/reopen/changed-source refresh, rollback, append behavior, and the supported local M round-trip. Critic review approved after the rollback test was corrected to deep-copy mutable candidate snapshots.
- Verification: focused Power Query tests passed **133 tests and 186 subtests**; full pytest passed **987 tests and 725 subtests**. Compileall, targeted Ruff, and `git diff --check` passed.
- The updated app is open in a separate main-display window as an empty project; the prior app process and user's Power BI project were left untouched. REA could not inspect the Python window because launch-time identity is unavailable. A fresh read-only Power BI observation failed with `ambiguous-window` on the Parallels proxy; no UI action occurred. The earlier Power BI capture exposes no child controls, so native header-action placement remains unverified. Full M/Mashup and DAX/Tabular parity, model/report filters, chart behavior, and the reported calculation issue remain open. See [Iteration 54 results](.council/TEST_RESULTS_ITER54.md) and [verification sign-off](.council/VERIFICATION_SIGN_OFF_ITER54.md).

## 2026-10-21 — Sparse-row cleanup authoring

- Added sparse top/bottom cleanup commands to the Transform picker and ribbons. Picker, ribbon, and Applied Steps tooltips now describe the engine's nonblank-cell and cell-error stopping rules.
- Regressions author the steps through UI controls and verify M helper generation, step text, the 623 → 585 → 574 → 573 lifecycle, 14 headers, and project save/reopen/refresh using the synthetic VAT-shaped fixture.
- Fresh full pytest passed **989 tests and 729 subtests**. Compileall, targeted Ruff, and `git diff --check` passed.
- Read-only main-display smoke on the original workbook matched the staged counts and 573 × 14 final shape; rounded inclusive `Value` total is **1,498,307.26**. The workbook hash remained unchanged. The screenshot is recorded at `/tmp/analytics-studio-vat-sparse-cleanup-iter56.png`.
- REA's retained screenshot shows the captured UI/query shape for this slice; it does not establish cell equality or full M/Mashup behavior. The overall Power BI parity objective remains open.

## 2026-10-21 — Iteration 60 Excel source identity follow-up

- Review found that Excel source matching omitted the persisted `raw_rows` mode. A raw worksheet candidate and an automatic-header candidate can both use `header_row=None`, so reimport could otherwise replace the wrong source.
- Source matching now checks raw-row mode before comparing header settings or applying the legacy automatic-header fallback. The regression creates both source modes, verifies distinct IDs before and after save/reopen, and checks that the preview replacement callback maps Load and Transform candidates to the corresponding source.
- Final verification after this fix passed **994 tests and 738 subtests**; `tests/test_import_lifecycle.py` passed **24 tests and 15 subtests**. The exact new regression passed. Compileall, targeted Ruff, and `git diff --check` passed. Critic and lifecycle reviews found no blocker.
- Power BI model/workbook evidence remains read-only. The workbook-specific row-1 Load behavior and 573-row cleaned query are documented in [Iteration 60 REA notes](docs/rea-power-bi-desktop-2.157.879.0.md#iteration-60-excel-load-source-identity-2026-10-21). This does not establish general connector defaults, full Power Query/Mashup parity, exact DAX calculations, or chart/model parity.

## 2026-10-21 — Iteration 61 chart-axis `ALLSELECTED`

- Added a bounded visual-axis filter context for qualified `ALLSELECTED` on the same column used as the sole, non-stacked chart category axis. It restores the filtered axis selection during the measure denominator and retains other column and relationship filters.
- Captured the category selection before local Top N trimming. Added lifecycle tests for page selection, a Month filter, plain aggregation and Card controls, related-table filter propagation, save/reopen, source refresh, and a saved Top 1 visual filter exercised through public `visualSeries`.
- A read-only ADOMD query against Power BI Desktop 2.157.879.0 returned Dubai/Abu Dhabi values 259,801.81 and 406,165.51, shared selected total 665,967.32, and shares 0.390111950238039 / 0.609888049761961. Power BI retained that total/share when an outer Top N returned Abu Dhabi only.
- Final full pytest passed **997 tests and 738 subtests**. `compileall`, the new Top N test's Ruff check, and `git diff --check` passed. The whole-file Ruff check still reports 33 existing diagnostics in the large controller/evaluator modules.
- The independent critic approved the implementation and confirmed the public Top N test closes its earlier coverage caveat. REA's current native UI capture remains unavailable due ambiguous proxy geometry and audio/video capture failure; no interaction was made. The user's exact formula remains unknown, and general DAX/visual parity remains open. See [Iteration 61 test results](.council/TEST_RESULTS_ITER61.md), [critique](.council/CRITIQUE_REPORT_ITER61.md), [sign-off](.council/VERIFICATION_SIGN_OFF_ITER61.md), and [Power BI evidence](docs/rea-power-bi-desktop-2.157.879.0.md#iteration-61-chart-axis-allselected-comparison-2026-10-21).

## 2026-10-21 — Iteration 63 model-facing projection of Power Query errors

- Power Query keeps `DataFormat.Error` cells in an error-bearing query cache (`_query_candidates`); the loaded model (`_loaded_candidates`) receives blanks at those cells, matching the Iteration 62 Power BI Desktop ADOMD observation (32 `TRN` errors loaded as blanks). Other error reasons are preserved; row lineage is preserved.
- The projection was only partly wired. Completed it for single-query transform commit, the multi-query session commit (including query deletion), source refresh (dependents now read error-bearing inputs; excluded queries keep their last query result), source deletion, file/folder, SQL Server and OData re-import, saved-query creation, and calculated-column updates. A critic found the last four gaps; each is now covered.
- Updated four tests that expected errors inside the model cache and added regressions for session apply/delete, refresh with dependents, re-import freshness, and saved-query blanking. Reverting each fix makes its regression fail.
- Verification: full pytest **1003 passed, 738 subtests**; `compileall` and `git diff --check` clean; ruff clean on touched tests; the controller's 12 ruff diagnostics are identical to HEAD.
- Open (critic minor findings, not fixed): the Power Query session preview of an excluded-from-refresh query reads the model cache, so errors appear as blanks there until commit; query results do not carry calculated columns, so dependents of sources without a query-cache entry could differ before/after reopen. Data-view column profiling now reports model blanks, not error counts. No live Power BI comparison was made this iteration, and broad M/DAX, visual and model parity remain open. `.council/` was not readable or writable in this session, so no `.council` iteration reports were produced.


## 2026-10-21 — Iteration 64 DAX differential harness and scalar math

- Added `tools/dax_oracle_diff.py` and `tools/dax_battery.json`: a repeatable comparison of the local DAX evaluator against the running Power BI Desktop 2.157.879.0 engine (ADOMD in the Parallels guest; scripts are written to the shared Mac home folder because the guest rejects long command lines). The scratch `Facts` table is created in the unsaved model and always deleted.
- Baseline: 93 expressions; 47 match, 43 are unsupported locally, no mismatch among supported functions. Early "differences" (`COUNTA`, `DISTINCTCOUNTNOBLANK`, numeric `=BLANK()`) were harness mistakes (blank is `None`; column types must be supplied) and are documented in the REA note.
- Implemented `INT`, `TRUNC`, `SIGN`, `SQRT`, `EXP`, `LN`, `MOD`, `POWER` for measures and calculated columns with Power BI's blank and error behavior (`_scalar_math` in `measures.py`), plus editor templates. Tests: `tests/test_scalar_math_functions.py` (6 tests, 46 subtests; mutation-checked for `MOD` sign, `INT` floor, and `EXP` blank).
- Independent critic review found four defects in the first cut (TRUNC/MOD 28-digit limit, no double-range guard, negative zero, literal `BLANK()` rejected); all fixed with mutation-checked regressions (10 tests, 60 subtests). Final live battery: 49 edge expressions 47 match / 2 documented gaps; 93-expression baseline 58 match / 35 unsupported / 0 mismatches.
- Verification: **1013 tests passed, 798 subtests**; compileall, `git diff --check`, and ruff on new files are clean; `measures.py` has 21 ruff diagnostics against 22 at HEAD.
- Open: `LN(BLANK())`, `POWER` of negative base with fractional exponent, string/boolean results, `SWITCH`/`IFERROR`/`ISBLANK`, text and information functions, `VALUES`/`SELECTEDVALUE`/`HASONEVALUE`, `VAR/RETURN`, and table-level comparison on the user's loaded data once applied in Power BI.


## 2026-10-21 — Iteration 65 blank arithmetic, conditionals, more functions

- Side-by-side with Power BI Desktop 2.157.879.0 (`tools/dax_oracle_diff.py`): 264 expressions, 230 match, 34 refused, 0 differ. Blank arithmetic (`BLANK()*5` blank, `BLANK()+1` = 1) now follows Power BI, which changed one old calculated-column test; `IF` with two arguments, `ISBLANK`, `IFERROR`, `SWITCH`, `CEILING`, `FLOOR`, `MEDIAN`, `PRODUCT`, `COUNTBLANK` added for measures, calculated columns and row iterators (tests: `tests/test_blank_and_logical_functions.py`).
- One live mismatch fixed: division by zero reaching a comparison, `ISBLANK` or `SWITCH` is refused (Power BI treats it as Infinity).

## 2026-10-21 — Iteration 66 table-level comparison with the user's workbook and review fixes

- The user confirmed `Downloads/DSI.xlsx` as the test data. New `tools/table_oracle_diff.py` loads it into the unsaved Power BI model through Power BI's own Power Query engine (TMSL + M partition, no UI, file only read), dumps every cell and runs 108 measure expressions against the local importer and evaluator. First run: 2,738 cell differences (row/column order only — fixed by comparing as multisets), then real findings: Power BI's model trims trailing spaces/control characters from loaded text, stores ASCII case variants under the first-seen spelling and compares column text case-insensitively for ASCII only; Excel doubles read as the shortest round-trip number. All observations are in `docs/rea-power-bi-desktop-2.157.879.0.md` (Iteration 66) and `DAX_COMPATIBILITY_CONTRACT.md`.
- Fixed: model-load rules in `_model_candidate_with_format_errors_as_blank` (`power_query_values.model_text_normalizer`), ASCII-insensitive `CALCULATE` text filters and `DISTINCTCOUNT`, Excel numeric cells as doubles. Two old tests encoded the earlier assumption (case-sensitive filters; `" "` distinct from `""`) and now state the Power BI behaviour; the Power Query dialog still profiles untrimmed, case-sensitive query values.
- Independent critic's six defects fixed with mutation-checked regressions: negative zero, double-range overflow in `+ - * /`, `CEILING`/`FLOOR` precision, `MAXX`/`MINX`/`COUNTX` over `IF`/`IFERROR`/`ISBLANK`/`SWITCH`, `ABS`/`ROUND`/`CALCULATE` blank leakage (Power BI returns blank for `ABS(BLANK())` and `CALCULATE(BLANK())`, so those stay), and division-by-zero conditions swallowed by `IFERROR`.
- Result: workbook table 371×10 cells identical, 106/108 measures match, 2 refused, 0 differ; merged DAX batteries 289 expressions, 251 match, 38 refused, 0 differ. Full suite 1049 tests (see verification).
- Next gap by value: `COUNTROWS(FILTER(...))` / `SUMX(FILTER(...))` (the two refused workbook measures), then text/boolean results, `VAR/RETURN`, `VALUES`/`SELECTEDVALUE`.

## 2026-10-21 — Iteration 67 FILTER as a table argument

- `FILTER(table, predicate)` and `FILTER(ALL(table), predicate)` now work as the table argument of `COUNTROWS`, `SUMX`, `AVERAGEX`, `MAXX`, `MINX`, `COUNTX` and `COUNTAX` (same bounded predicate language as the `CALCULATE` FILTER: column-versus-literal comparisons joined with `&&`, `||`, `AND`, `OR`, `NOT`). It reads the rows visible in the current filter context, so `CALCULATE(COUNTROWS(FILTER(T,…)),T[x]="a")` filters first, while the `ALL` base ignores that filter. `FILTER(ALL(…),…)` stays rejected as a `CALCULATE` filter argument.
- Side-by-side with Power BI Desktop 2.157.879.0: new `tools/dax_battery_filter_tables.json` (33 expressions: 33 match, 0 differ) and the DSI.xlsx workbook battery is now 108/108 match (the two previously refused measures included), table cells still identical. Tests: `tests/test_filter_table_iterators.py`; full suite 1054 passed.
- Still refused: `FILTER` predicates that compare two columns or call functions, `FILTER` over a measure/table expression other than a loaded table or `ALL(table)`, text/boolean results, `VAR/RETURN`, `VALUES`/`SELECTEDVALUE`.

## 2026-10-21 — Iteration 68 standing test file and real-app run

The standing test workbook is now `tests/Data/Vat File -Aug 2026.xlsx` (sheet `VAT 5%`, header row 12; 611 rows × 14 columns; SHA-256 `8f7e4656…3965`). `tools/table_oracle_diff.py` gained `--sheet`, a generic numeric-role mapping for its battery, and a per-name report file (`table_oracle_report_VAT.json`). Live against Power BI Desktop 2.157.879.0: all 611×14 cells identical; 507 of 508 measures match, the one refusal is `AVERAGEX(VAT,VAT[Quantity]/VAT[Gross Total])` (Power BI returns NaN). Three vendor names that contain CR+LF were excluded from the generated battery because the guest script cannot carry a CR in a literal; checked separately: Power BI matches `UNICHAR(13)&UNICHAR(10)` to 4 rows, the same as the app.

`tools/app_smoke.py` starts the real shell (hidden offscreen window), imports the workbook, creates all measures through `create_measure` in batches (the model caps at 100 measures; Power BI has no such cap), compares the displayed values with Power BI's, builds a card/column/table, saves and reopens. Result: 507/507 created measures equal Power BI (to the app's 2-decimal display), visuals render, save/reopen restores 611 rows, 3 measures and 3 visuals. Open: measure binding into a card through `add_field_to_well` was not exercised correctly by the script; the card shows its column sum 1,498,307.26 (equals Power BI); the 100-measure cap; measure display rounds to 2 decimals.

## 2026-10-21 — Iteration 69 parity gate (standing rule)
- New `tools/parity_check.py`: replays every saved Power BI answer (4 DAX batteries frozen from Power BI 2.157.879.0 into `tools/parity/*.json`, plus the VAT workbook report) against the app; `--accept` locks matches (`tools/parity/baseline.json`), `--tests` adds pytest and the real-app run, `--freeze` re-asks the live Power BI. Writes `PARITY_LEDGER.md`.
- Result: 798 answers replayed, 761 match (all locked), 37 pending (app refuses), 0 differ, 0 crash; pytest 1054 passed; real app 507/507. Regression path verified by locking a pending item (gate failed, restored).
- DSI.xlsx answers (108 earlier matches) cannot be replayed: workbook missing.
- Rule written to project CLAUDE.md and memory.

## 2026-10-21 — Iteration 70 typed values, text, dates, math, statistics (all compared with Power BI 2.157.879.0)
- New modules: `dax_typed.py` (text/True-False/number coercion, comparison, string functions), `dax_format.py` (FORMAT, VBA rules), `dax_dates.py` (DateTime = day number with a tag; DATE/TIME/YEAR..DATEDIFF/EOMONTH/EDATE/WEEKDAY/WEEKNUM/DATEVALUE/TIMEVALUE/TODAY/NOW; date FORMAT), `dax_math.py` (ROUND*, MROUND, EVEN/ODD, LOG, trig, FACT, GCD/LCM, STDEV/VAR/PERCENTILE/GEOMEAN and their X variants).
- Engine: `&`, `^`, `VAR … RETURN`, text/Boolean/date/Infinity/NaN results, text comparison `< >`, MIN/MAX of text and date columns, two-argument MAX/MIN, VALUES/DISTINCT of a column or table, SELECTEDVALUE, HASONEVALUE, CONCATENATEX, CONVERT, CALCULATE filters whose other side is any scalar expression (variables, AVERAGE(...), DATE(...)).
- Limits lifted: measures 100→5000, expression 2000→50000 characters (Power BI has none).
- App: cards/tables/measure list show text, True/False, dates, Infinity, NaN.
- Gate: 1884 saved Power BI answers, all matching and locked; 575 VAT measures through the real app equal Power BI; pytest 1058 passed (includes tests/test_parity_ledger.py).
- Still pending: TOPN, RANKX, ADDCOLUMNS, SUMMARIZE, UNION/EXCEPT/INTERSECT/CROSSJOIN, GENERATESERIES, ROW, CALCULATETABLE, IN {..}, CONTAINS, LOOKUPVALUE, FIRSTNONBLANK, EARLIER, ISFILTERED/ISINSCOPE/HASONEFILTER, general FILTER predicates.

## 2026-10-21 — Iteration 71 derived-table DAX functions (compared with Power BI 2.157.879.0)
- Engine: ADDCOLUMNS, SELECTCOLUMNS, SUMMARIZE, UNION/INTERSECT/EXCEPT/CROSSJOIN, GENERATESERIES, ROW, TOPN (ties included, blank sorts as typed zero), RANKX / RANK.EQ (SKIP/DENSE, ASC/DESC, omitted arguments), CALCULATETABLE inside table consumers, EARLIER/EARLIEST via row stack, IN {..} and CONTAINS/CONTAINSROW/LOOKUPVALUE, FIRSTNONBLANK/LASTNONBLANK, ISFILTERED/ISINSCOPE; context transition over derived tables keeps column lineage (ALL/VALUES/DISTINCT outputs now carry it).
- New battery `tools/dax_battery_tables.json` (344 expressions, answers saved from Power BI in `tools/parity/dax_battery_tables.json`): 344 match, 0 differ. Gate: 2330 answers match and are locked; pytest 1058 passed; real app 575/575 equal to Power BI.
- Editor: function catalog has templates for all new table functions.
- Still pending (Power BI answers, app refuses): CALCULATE with table-valued filter arguments (`FILTER(ALL(col),..)`, `col IN VALUES(..)`), EARLIER inside FILTER within CALCULATE, CALCULATETABLE as a scalar, ISONORAFTER, mixed-type `{1,"a"}` error, SUMMARIZECOLUMNS/GROUPBY/TREATAS/NATURALINNERJOIN, SAMPLE, MAXA/MINA/AVERAGEA edge cases, `(-8)^(1/3)`, measure display precision, UI side-by-side on the iPad screen.

## 2026-10-21 — Iteration 72 locking, regression triage, honest refusal of nested FILTER overrides
- Locked 10,580 saved Power BI answers (`tools/parity_check.py --accept`): tables2 434, stats 2645, misc 2438, finance 436, bonds 2280, new `dax_battery_filter_shapes` 17, plus the earlier groups. `misc`, `adversarial`, `finance`, `bonds` were frozen but missing from `DAX_BATTERIES`; they are registered now.
- The suite had 15 failures from the batteries work. Real defects fixed: (1) `ALL(column)` over a numeric column crashed on an empty cell (`order_distinct_values` now treats it as blank); (2) a Boolean `CALCULATE` filter nested inside an outer `FILTER(table, …)` returned wrong numbers (Power BI 1/2/BLANK vs app 3/4/2) because the general-path fallback swallowed the legacy "FILTER rowset" refusal; those shapes are refused again, as is a saved filter without per-column context.
- Stale tests corrected from Power BI evidence: `ALL`/`ALLNOBLANKROW(column)` ignore filters on their own table (adversarial battery: `CALCULATE(COUNTROWS(ALL(Facts[Region])),Facts[Quantity]>3)` = 3); `COALESCE` inside iterators is valid (8/8 live matches); `FILTER` text ordering is valid and number-vs-text is an error in both; `IN {}` is an error in Power BI and now in the app.
- Open (7 DIFFs, all `dax_battery_adversarial`, listed in `PARITY_LEDGER.md`): `ALLSELECTED(column)` under `CALCULATE` filters (3), `EARLIER` inside nested `FILTER`/`MINX`/`MAXX` (2), `TOPN(…SUMMARIZE…)` as a filter (1), `CONCATENATEX(SELECTCOLUMNS…)` row order (1). Plus 25 adversarial and 6 filter-shape expressions the app refuses (Power BI keeps a `FILTER` table as whole rows; a nested column override keeps the other columns' row identity). Relationship-level `ALL(table)` semantics could not be compared live: Power BI Desktop rejects relationship creation over XMLA.
- Gate: replay 13,352 answers, 13,314 match, 31 refused, 7 differ, 0 crash; pytest 1480 passed, 1 failed (the ledger test that reports the 7 DIFFs).

## 2026-10-21 — Iteration 73 FILTER tables as whole rows, EARLIER in FILTER, ALLSELECTED(column)
- **Whole-row FILTER tables ("shapes").** Power BI keeps a table passed to `CALCULATE` (`FILTER(Facts,…)`, `FILTER(ALL(c1,c2),…)`, a multi-column Boolean filter) as a set of whole rows. A later filter, `REMOVEFILTERS`, `ALL(column)` or `ALLEXCEPT` on one of its columns drops only that column from the rows' identity; the other columns keep constraining by the rows' values there. `with_column_filters` and the two clearing paths now do that projection (`filter_shapes` on the table context, `shape_projection_rows`, `clear_columns_from_shapes`), `KEEPFILTERS` intersects with the shape and keeps its own set (`filter_column_extra`), and resets/clears forget the shape. Shapes that were combined with other filters on the same columns are refused instead of guessed. The earlier honest refusals became 1,000 compared expressions in four new batteries (`dax_battery_filter_shapes`, `…2`, `…3`, `…4`: nesting to three levels, KEEPFILTERS, clearing functions, context transition): all match Power BI.
- **EARLIER inside a FILTER predicate.** A predicate whose right-hand side contains `EARLIER` depends on the row being filtered, so it is no longer compiled as a constant (Power BI 9 and BLANK, the app gave 10 and 3).
- **ALLSELECTED(column).** It is the values of those columns after the filters on the table's other columns are cleared (a filter on one of the columns stays), in storage order: 110 of 112 compared expressions match (`dax_battery_allselected`, from 73). Two documented gaps are kept out of the gate in `tools/parity/pending/`: inside an iteration `ALLSELECTED` also keeps the iterated rows (`FILTER`, `TOPN`, `CALCULATETABLE`) as a shadow filter and drops row-transition filters (14 of 25 probes differ), and an empty `ALLSELECTED(column)` iteration with a bare column in its body is a static error in Power BI but BLANK here.
- **Unspecified iteration order.** Without an `ORDER BY`, Power BI iterates in storage order (numbers ascending, blank first, text by first appearance) and the app uses row order. Two order-dependent adversarial expressions moved to `known_deviations.json`; 25 probes saved in `tools/parity/pending/dax_battery_iteration_order.json`.
- Corrected one claim from iteration 72: the two `EARLIER` differences were not caused by the FILTER-rows model (they were the constant-predicate shortcut above).
- Tests updated to Power BI's answers: `ALLEXCEPT`/`REMOVEFILTERS(column)` over a FILTER rowset, nested Boolean filter over a FILTER table, and a workflow test that now uses a still-refused shape.
- Gate: replay 14,437 answers: 14,412 match, 25 refused (all `dax_battery_adversarial`), 0 differ, 0 crash; **14,403 locked**; pytest 1481 passed; real app 575/575. **PARITY GATE PASSED.**
- Open (25 refused, listed in `PARITY_LEDGER.md`): `FILTER(...)` held in a `VAR` and passed to `CALCULATE` (4), `ISBLANK` in a `FILTER` predicate over a text column (14; the local predicate converts the column to a number), a Boolean filter that references a second column or a table function (3), `EARLIER` arithmetic inside iterator comparisons (4), `MAXX(VALUES(…),CALCULATE(COUNTROWS(VALUES(…))))` (2).

## 2026-10-21 — Iteration 74 ISBLANK over text columns inside iterator rows
- Root cause: `ISBLANK` evaluated its argument in numeric mode, so any text column inside `SUMX`/`FILTER` rows raised "contains a non-numeric value … convert it to a number first" (broader than the ledger showed: `SUMX(Facts,IF(ISBLANK(Facts[Note]),1,0))` failed too). The argument is now evaluated with `allow_text=True`; empty text cells count as blank, as in Power BI.
- Test added: `test_isblank_accepts_text_columns_in_iterator_rows`. 12 adversarial expressions that were refused now match Power BI and are locked.
- Gate: replay 14,437 answers: 14,424 match, 13 refused, 0 differ, 0 crash; **14,415 locked**; pytest 1482 passed; real app 575/575. **PARITY GATE PASSED.**
- Open (13 refused, all `dax_battery_adversarial`): `FILTER(...)` held in a `VAR` passed to `CALCULATE` (4), a Boolean filter referencing a second column or a table function (3), `EARLIER` arithmetic inside iterator comparisons (4), `MAXX(VALUES(…),CALCULATE(COUNTROWS(VALUES(…))))` (2).

## 2026-10-21 — Iteration 75 tables held in VARs
- Root cause: `_validate_literal_positions` validated each `VAR` value as a scalar, so a held `FILTER(...)`/`ALL(...)` hit "supported only as a CALCULATE filter". `_has_supported_all_usage` had no `let` branch, so its generic walk skipped the first binding by accident (a single table VAR passed, a second one was refused). Now a held table expression is checked in a table position and every binding is checked.
- New battery `tools/dax_battery_var_tables.json` (209 expressions: FILTER over the table, over `ALL(cols)`, `VALUES`, `DISTINCT`, `ALL`, two VARs, KEEPFILTERS, plain filters, REMOVEFILTERS, nesting, `SUMX` over a held table): all 209 match Power BI 2.157.879.0 and are locked. Test `test_filter_and_all_tables_held_in_variables_filter_calculate` added.
- Gate: replay 14,646 answers: 14,637 match, 9 refused, 0 differ, 0 crash; pytest 1483; real app 575/575. **PARITY GATE PASSED.**
- Open (9 refused, all `dax_battery_adversarial`): Boolean filter referencing a second column or a table function (3), `EARLIER` arithmetic inside iterator comparisons (4), `MAXX(VALUES(…),CALCULATE(COUNTROWS(VALUES(…))))` (2).

## 2026-10-22 — Iteration 76 the nine refused DAX shapes, proved by five independent testing rounds
- **The nine refusals are closed** (all in `dax_battery_adversarial`, now 2,764 of 2,764 match): `EARLIER`/`EARLIEST` arithmetic inside iterator comparisons (4), a CALCULATE Boolean filter with a scalar table expression on the right (3), `MAXX(VALUES(…),CALCULATE(COUNTROWS(VALUES(…))))` (2).
- **Root causes.** (1) `iterator_expression_category` typed `EARLIER` as "unknown", so arithmetic around it was refused (now typed by the column it reads; `MAXX`/`MINX`/`COUNTX` validation rows are included). (2) A Boolean filter `Column op scalar` evaluated the scalar once per row, where a `CALCULATETABLE` transitioned the test's own row; Power BI evaluates it once in the outer context. `preevaluate_filter_scalars` now substitutes the constant at the start of `CALCULATE` (right-hand side, top level, `CALCULATETABLE` filters all plain Booleans); other shapes are refused instead of guessed. (3) A `FILTER(Facts, col op CALCULATETABLE(…))` predicate was compiled as one constant; it now runs per row (a bug in the shipped app: 8 of 8 hand-checked variants differed from Power BI).
- **Power BI's refusal rule, verified** (`dax_battery_boolean_filter_functions`): `FILTER`, `CALCULATE`, `TOPN`, `SELECTCOLUMNS`, `LOOKUPVALUE`, `ADDCOLUMNS`, `SUMMARIZE(COLUMNS)`, `GROUPBY`, `EXCEPT`, `INTERSECT`, `ROW`, `SAMPLE`, `TOPNSKIP`, `RANKX`, `FIRSTNONBLANK`, `LASTNONBLANK`, `OFFSET`, `WINDOW`, `INDEX`, `RANK`, `ROWNUMBER` are errors in a Boolean filter, but only outside an X-iterator.
- **Found by the testing agents and fixed:** DAX comments (`//`, `--`, nested `/* */`) were unsupported and `--` was read as a double minus; `rename_table_references` now keeps comments verbatim; column names are no longer trimmed (`[ Quantity ]` is an error); only space, tab, CR and LF are whitespace; a top-level `{1}` crashed; `COMBINA(0,0)` crashed; huge `COMBIN`/`PERMUT`/`COMBINA` arguments **hung the app** (now Power BI's limits: n ≥ 2,147,483,647 or a result above double-max errors, checked with `lgamma` first); `GCD`/`LCM` round half away from zero and error above 2^53 or below 0; Boolean values in `SUMX`/`AVERAGEX`/`COUNTX`/`PRODUCTX`/`MEDIANX`… are errors (two old tests assumed `COUNTX` ignores Booleans; Power BI disagrees); `EARLIEST` needs two row contexts; `IF`/`SWITCH`/`IFERROR`/`COALESCE` return FALSE (not BLANK) when every result branch is Boolean or a literal `BLANK()`; `CONCATENATEX` order keys of mixed types crashed (now numbers/dates with BLANK as 0, then text, then Booleans).
- **Agents.** Round-by-round: 2 investigators (read-only root causes), then Testing Agent rounds 1–5 (about 14,000 new independent probes against live Power BI 2.157.879.0) and one Critic review. Each round's FAIL was acted on before the next: round 1 found 56 wrong answers in my first version (hoisting was unsound for some `CALCULATETABLE` forms), round 2 found 320 + 14 crashes (mostly old gaps), round 3 found the `IF` rule too eager and too narrow, round 4 a hang and column/nested cases, round 5 the `VAR`/`IFERROR` details. The Critic found the table-rename-after-comment bug and a mixed-operand shape (`Quantity + SUMX(VALUES(…),CALCULATE(…)) > 3`) the app answered wrongly; both fixed.
- **New batteries** (all saved Power BI answers, all replayed by the gate): `earlier_arith`, `boolean_scalar_rhs`, `filter_transition`, `boolean_filter_functions`, `sdet_filters`, `comments_booleans`, `round2_scope`, `critic_shapes`, `round2`, `round3`, `round4`, `round5`. Open differences from the testers are in `tools/parity/pending/dax_battery_round{2,3,4,5}_findings.json` (not replayed).
- Tests added: `tests/test_dax_boolean_filter_scalars_power_bi.py` (14 groups replaying saved Power BI answers; 40 subtests fail against the engine from before rounds 3–5), `test_earlier_arithmetic_inside_iterator_comparisons`; three tests updated to Power BI's answer (COUNTX with a Boolean, a stale "refused" expectation).
- Gate: replay 31,703 answers: 30,468 match, 1,235 refused, 0 differ, 0 crash; **30,459 locked** (was 14,870); pytest 1494; real app 575/575. **PARITY GATE PASSED.**
- Trade-offs: 16 shapes the old engine happened to answer correctly (a `CALCULATETABLE` scalar below the top level, inside another CALCULATE or a row context) are now refused until their Power BI semantics are modelled; a Boolean *column* in `SUMX` errors (as Power BI does for derived Boolean columns).
- Open (work list, none are wrong answers in the locked set): `WINDOW`/`OFFSET`/`INDEX`/`RANK`/`ROWNUMBER` evaluated in a plain iterator row, `FORMAT` edge cases, UTF-16 text length and case mapping, date/time rounding, numeric literals over 17 digits (doubles in Power BI), static type errors in never-evaluated branches, `IFERROR` catching errors Power BI lets through, tie order in `CONCATENATEX` (storage order), and the 1,235 refusals listed in `PARITY_LEDGER.md`.

## 2026-10-22 — Iteration 77 the biggest DIFF groups (compared with Power BI 2.157.879.0)
- **Start.** Replaying every DIFF the testers had saved (`sdet4/ALL_RESULTS.json` 703, rounds 3–5 and the `pending/*_findings.json`, 1,193 distinct expressions with saved Power BI answers) against the current app gave **649 real differences** (the 703 in the log were a snapshot taken before iteration 76 finished). After this iteration: **168 left, 136 of them real** (the other 32 are the test harness unable to carry non-ASCII text or a dropped connection).
- **Static checks (about 240 DIFFs).** Power BI compiles the whole query, also the branches that never run. New post-evaluation checks in `evaluate_measures`: a bare column reference with no row context (also in a dead `IF`/`SWITCH`/`COALESCE`/`IFERROR` branch), a column or table that does not exist, comparison of operands whose static types differ (Text vs Number vs True/False, also when the value would be BLANK, e.g. `IF(c,BLANK())=FALSE()`), `SUMX`/`AVERAGEX` of text, `SUMX`/`MAXX` of True/False, `SUM`/`AVERAGE` of a text column, `MAX(TRUE(),FALSE())`, `EARLIER(col, n)` with a non-integer `n`. Date columns stay untyped (ISO text filters). Engine messages still win over the static ones.
- **Window functions (about 150).** `OFFSET`/`WINDOW`/`INDEX`/`RANK`/`ROWNUMBER` now read the row contexts on the stack as filters on the base table, so they work inside `SUMX`, `FILTER(ALL(table))`, `VALUES` and `ADDCOLUMNS` iterations (not inside the implicit rows of a Boolean `CALCULATE` filter). `INDEX`/`OFFSET`/`WINDOW` refuse a relation that keeps whole rows of a table (`ALL(table)`, `VALUES(table)`, `FILTER`/`TOPN`/`ADDCOLUMNS`/`SELECTCOLUMNS` over it, `UNION`) with Power BI's "may have duplicate rows" error; `RANK`/`ROWNUMBER` do not.
- **FORMAT (about 90).** A number is a date/time pattern when a date letter comes before the first `0`, `#` or `.` (`"n"`, `"General"` give minutes: `Ge0eral`); `TRUE`/`FALSE` format as -1/0 under number patterns; `@ & < >` text placeholders; a value that rounds to zero loses its sign and uses the zero section (empty zero section falls back to the first); `.00` shows the whole part; `[Red]` tags ignored; `mmmmm`, `ttttt`; day 0 prints as a time only (`TIME(1,2,3)&""` is `1:02:03 AM`).
- **Smaller.** Decimal literals with more than 15 digits are doubles (`2.4999999999999999=2.5`); `UPPER`/`LOWER` map one character to one (`ß`, `µ`, `İ`); `HOUR`/`MINUTE`/`SECOND` truncate; `COUNT`/`COUNTA`/`DISTINCTCOUNTNOBLANK` of nothing non-blank are BLANK (an old test said 0); blank in, blank out for `ASIN ASINH ATAN ATANH DEGREES RADIANS SIN SINH TAN TANH SQRTPI EVEN QUOTIENT REPT`, `TIME(BLANK,BLANK,BLANK)`; `FIND`/`SEARCH` with a blank search text or blank start.
- **Locked.** New battery `dax_battery_diff_groups` (484 saved Power BI answers). Open items (136, none wrong in the locked set) are in `tools/parity/pending/dax_battery_diff_groups_findings.json`: `CONCATENATEX` tie order (storage order, which DAX does not define), `IFERROR` catching iterator/`IN` runtime errors Power BI lets through, UTF-16 positions, `CURRENCY` range, `NATURAL*JOIN` common-column check, double arithmetic near .5 and `PI()` trig, `+TRUE()`, `TIME`/`YEAR`/`SEARCH` argument ranges.
- **Gate.** replay 32,187 answers: 30,952 match, 1,235 refused, 0 differ, 0 crash; **30,943 locked** (was 30,459); pytest 1,498 passed; real app 575/575. **PARITY GATE PASSED.**

## 2026-10-22 — Iteration 78 IFERROR and thrown errors (compared with Power BI 2.157.879.0)
- **Rule found with 190 live probes.** Power BI returns some errors as values (Infinity from `x/0`, `NaN`) and throws the rest. `IFERROR`/`ISERROR` only catch the values. A thrown error cannot be caught when it happens: inside a row expression of `SUMX`/`AVERAGEX`/`MAXX`/`MINX`/`COUNTX`/`COUNTAX`/the `…X` statistics, `RANKX`, `FILTER`, `TOPN`; in `IN`/`CONTAINSROW`/`CONTAINS`/`LOOKUPVALUE` operands; in `ROW`, `GENERATESERIES` and the `TOPN` count; in the scalar side of a `CALCULATE` filter (both sides); in a used `ADDCOLUMNS`/`SELECTCOLUMNS` column; and from a `VAR` once it is used (an unused `VAR` is fine). `CONCATENATEX` is the exception (still caught). Functions that reject Infinity as an argument inside a row throw (`INT`, `SQRT`, `EXP`, `LN`, `POWER`, `SIGN`, `FLOOR`, `CEILING`, `MROUND`, `ROUND`, `ROUNDUP`, `FACT`, `SIN`, `TIME`); `ABS`, negation, `TRUNC`, `ROUNDDOWN`, `MAX`, `MIN` and arithmetic pass Infinity through. `LN`/`LOG`/`LOG10` of BLANK is -Infinity (caught). `COUNTROWS(ADDCOLUMNS(...))` never evaluates the added columns.
- **Code.** New `_HardError(MeasureError)` and `in_row_expression()` in `measures.py` (converts runtime/decimal/overflow errors except `_DivisionError` and errors tagged `.infinity`); `evaluate_let`'s deferred VAR failure raises it on use; `lazy_column_calls` lets `COUNTROWS` skip unread columns; `FIXED` is a text function for the static `SUMX` check; `TRUNC`/`ROUNDDOWN` pass Infinity through; `LN`/`LOG` of BLANK are tagged `.infinity`.
- **Agents.** Critic (BI Compatibility and Data Integrity Auditor, read-only) ran all 31,740 saved answers through the old and new engine (only the 76 new items changed) and found 3 real gaps plus 3 weak tests; each was put to live Power BI before it was fixed (LN of BLANK, scalar-left CALCULATE filter, table-function arguments, lazy columns, TRUNC+VALUE). Testing Agent (Analytics Lifecycle SDET) ran the full gate under REA `capture_process_scenario`.
- **Locked.** New battery `dax_battery_iferror_hard_errors` (165 saved Power BI answers), tests `tests/test_iferror_hard_errors.py` (11, assert a real `_HardError`).
- **Open (verified, in `tools/parity/pending/dax_battery_iferror_hard_errors_findings.json`, 21):** Power BI evaluates both sides of `&&`/`||`/`AND`/`OR` inside an iterator row (no short-circuit) with optimizer exceptions (`ISBLANK(<constant error>)`, `X || TRUE()` are folded); `COUNTROWS` skips unread `SUMMARIZE` columns and `{1,VALUE("a")}` items; `LN(BLANK())` inside a `FILTER` comparison; a lazy `ADDCOLUMNS` held in a `VAR`. The remaining `diff_groups` list is 121.
- **Gate.** replay 32,352 answers: 31,117 match, 1,235 refused, 0 differ, 0 crash; **31,108 locked** (was 30,943); pytest 1,509 passed; real app 575/575. **PARITY GATE PASSED.**
