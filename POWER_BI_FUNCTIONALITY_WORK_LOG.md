# Power BI Functionality Work Log

**Snapshot date:** 2026-10-13

**Master capability map:** [POWER_BI_FUNCTIONALITY_ROADMAP.md](POWER_BI_FUNCTIONALITY_ROADMAP.md)

**Current completion snapshot:** [POWER_BI_FUNCTIONALITY_PROGRESS.md](POWER_BI_FUNCTIONALITY_PROGRESS.md)

This is the cumulative record of functionality implemented and accepted in Analytics Studio so far. “Done” means the scoped capability has the acceptance described here or in the master graph; it does not mean full Microsoft Power BI parity. The app is not Power BI Desktop and does not provide PBIX compatibility.

## Current work in progress

- **Current increment:** SQL Server, OData, and Web Edit Source Settings now restore their current connection/navigation choices and stage replacement previews in the Power Query session. Existing source/query identity and applied steps remain stable; SQL password changes use a new connection-bound Keychain reference and wait until Apply to persist. Remote edits use the previewed snapshot and retain the existing schema/type guard. Automated acceptance for this increment is pending.
- **Latest recorded full verification:** **680 pytest tests and 480 subtests passed**; `python3 -m unittest discover -s tests` passed **619 tests**. These counts predate the current remote source-editing increment.
- **Completed source-edit coverage:** existing CSV, Excel, JSON, XML, Parquet, SQLite, and folder roots stage path and parser/combine changes. SQLite also allows choosing tables/views. The new SQL Server/OData/Web editing flow is implemented but not yet accepted. Source identity, query metadata, and steps persist; included reference/append/merge descendants refresh together. Root/dependent schema and type changes remain rejected. Apply checks final SQLite binding uniqueness across edited and new sources using SQLite-compatible ASCII folding while preserving exact stored names, and checks active relationship constraints when both endpoints have loaded candidate data.
- **Remaining source-edit gaps:** remote edit lifecycle acceptance, schema migration, live remote acceptance, and manual macOS UI acceptance.
- **External acceptance gates:** benchmark large-file preview performance on an M1 Mac; verify SQL Server, OData, and Web against live services. Their current lifecycle coverage uses local fixtures or mocked services.
- **Unavailable product families:** RLS/OLS, role authoring, cloud publishing/collaboration, mobile/paginated reports, Report Server, embedding, and Q&A/Copilot. Their UI actions are disabled and they require separate implementation programs.
- **Larger queued areas:** broader report/visual workflows and interactions, complete DAX/M compatibility, additional connectors, security/governance, and service/platform extensions.

Update this section when the active increment or its blockers change.

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
- **Scope:** This is a local coordinate map. It does not geocode labels or load geographic basemaps/boundary polygons; filled, shape, and Azure Maps remain queued.
- **Verification:** Map lifecycle passed **1 test**. Full `PYTHONPATH=. python3 -m pytest -q` passed **444 tests and 231 subtests**.
- **Next:** Add offline filled/shape map support with a bounded local boundary source and lifecycle coverage.

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
