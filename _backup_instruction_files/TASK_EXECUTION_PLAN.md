# Task Execution Plan — Power Query and DAX capability increments

## Current increment — Refresh Preview consistency and DAX counting iterators

Home → Refresh Preview rereads included sources in the selected graph, replays current steps and session parameter values, and updates staged dependency previews without writing project data until Close & Apply. Excluded saved dependencies use cached raw inputs and replay staged steps; explicitly refreshed remote snapshots carry through Apply. Editing steps on an excluded dependency remains cache-backed and commits the same output shown to downstream previews. Its regression verifies the staged preview, committed parent and child output, saved steps, refresh exclusion, and unchanged raw snapshot. The Apply guard recognizes data the user explicitly refreshed and previewed; an unrefreshed local source change still blocks commit. Failed refresh, Cancel, and Apply-time failure leave controller state unchanged. The M compatibility checker also canonicalizes the emitter's one-clause advanced filter to the equivalent simple-filter step. The DAX measure editor/evaluator adds bounded `COUNTX` and `COUNTAX` iterator forms, including numeric/text results, Boolean behavior, formula-produced empty strings, blanks, and simple `IF` expressions. Iterator comparisons type-check supported expressions recursively; equality/inequality accepts matching numeric, Boolean, or text types, while ordering requires numeric operands. Mixed, date/time, and unverifiable operand types reject. DAX `BLANK()` propagation for empty iterators remains unsupported.

Acceptance: the Power Query M/session/parameter/home/refresh group passes **153 tests and 194 subtests**; the DAX measure/report/model group passes **40 tests and 29 subtests**; the full suite passes **604 tests and 442 subtests**. `compileall` and `git diff --check` pass. These are local implementation checks; they do not add a general Mashup runtime or full DAX. Live SQL Server, OData, and Web endpoint behavior remains unverified.

## Completed increment: `Table.Transpose`

The one-argument `Table.Transpose` parser/emitter form is implemented for the local `transpose_table` operation. Output/header/type behavior is covered; optional M output-column names and post-transpose cell-dependent expressions are rejected where local normalized text cannot preserve their semantics. Focused and full tests passed. This increment did not provide a Mashup runtime or complete M/DAX support.

## Previous increment: Duplicate/Delete Query lifecycle

The separate editor can stage Duplicate Query and Delete Query actions from the Home ribbon or Queries pane context menu. Copies receive independent IDs and preserve source/query definitions, transformations, and query metadata. Deletion checks surviving query, relationship, report, calculated-table, and DAX references before atomically removing project, model, and cached data. Failed non-active query previews remain visible and deletable so dependent queries can be removed before their parents. Names freed by deletion can be reused by a newly staged query in the same Apply. Focused lifecycle checks passed; the full suite passes **528 tests and 389 subtests**. `py_compile` and `git diff --check` pass.

## Latest increment: Conditional Column M round-trip

The Advanced Editor now serializes and parses bounded ordered Conditional Column rules using `Table.AddColumn` if-chains. Literal and column outputs, representable equality, six guarded text predicates, and numeric ordered comparisons after explicit type conversion round-trip against the local step engine. Numeric equality, ambiguous null/empty text comparisons, and nullable column-valued text search terms reject. Focused M tests pass **59 tests and 142 subtests**; the full suite passes **537 tests and 419 subtests**. This remains a bounded local M bridge, not the Microsoft Mashup engine.

## Previous increment: Guarded negative text filters

Does Not Contain, Does Not Begin With, and Does Not End With round-trip using explicit null handling; text predicates after non-text conversion reject.

## Previous increment: Reference Query in the Power Query session

The editor Home ribbon can create a staged Reference Query from the active query preview. Close & Apply validates the dependency, preserves supported column types and query metadata, and commits it atomically. Cancel leaves the project unchanged; saved references replay from their source dependency after reopen and upstream refresh. The current Power Query ribbon and DAX capability matrix is in [POWER_QUERY_EDITOR_AUDIT.md](POWER_QUERY_EDITOR_AUDIT.md). The DAX runtime selection and semantic oracle remain an explicit open gate in [ADR 0001](docs/adr/0001-dax-runtime-and-semantic-oracle.md).

Review fixes also keep the new reference preview synchronized with parent schema/type edits made later in the session, inherit the parent type map for profiling and commit, choose names around unloaded model tables, and reject apply-time collisions without mutating the project. The focused query/session group passes **73 tests and 52 subtests**; the full suite passes **521 tests and 389 subtests**. `py_compile` and `git diff --check` pass.

## Previous increment baseline: delimiter extraction, split, and merge

Extend the local Advanced Editor bridge to cover existing Transform Data operations for delimiter extraction, first/every-delimiter splitting, split-to-rows, and merge columns. Keep exact output, column order, row order, and type behavior inside the app's normalized-text model.

## Architecture

The validated transformation step list remains the execution source of truth. `steps_to_m_script` emits a narrow native M shape; `parse_m_script` accepts only that exact supported grammar and translates it back to the existing local operation. The editor previews and applies through the local transformation engine. It is not the Microsoft Mashup runtime, so M semantic claims must remain bounded and tests must identify local versus external validation.

## Implementation

1. Verify official function semantics and local transformation behavior for each operation.
2. Add failing operation/output/type and rejection tests before production changes.
3. Add parser/emitter support for null/empty guarded delimiter extraction; first split with `Splitter.SplitTextByEachDelimiter`; every split with a data-derived output width; null-coalesced `Text.Split` plus `Table.ExpandListColumn`; and `Table.CombineColumns` with `QuoteStyle.None`.
4. Encode/decode M text escapes. Reject unsupported index selectors, quote-sensitive forms, fixed split widths, text operations on columns typed as non-text earlier in the sequence, and unproven text types after reshaping.
5. Run focused M tests and full regression tests; update the audit, progress, roadmap, work log, and council state with exact limits.

## Acceptance

- Each supported operation round-trips to its canonical local step.
- Direct local execution and the M parser/emitter path produce identical output headers, order, rows, values, and type maps.
- Coverage includes empty/missing and repeated delimiters, dynamic width growth and empty tables, row expansion order, merge separators and selected-column order, null normalization, M text escapes, and fail-closed type checks after unpivot/pivot and schema reshaping.
- Unsupported M shapes fail with a clear diagnostic before state mutation.
- Documentation calls this a bounded local M bridge and does not claim Mashup-runtime or Power BI parity.

## Product gaps still open

The Duplicate/Delete Query increment is complete, but it does not finish Power Query parity or DAX. Keep-duplicates M mapping, Schema/Diagram views, per-operation settings, parameters/functions, source privacy/credentials, a general M runtime, full DAX semantics, and runtime/oracle selection remain roadmap work. M locale conversion supports literal cultures and five local type families only. `pbix-mcp` is a newly identified DAX adapter candidate, but upstream claims have not been validated locally because the environment cannot resolve PyPI.

## Review follow-up

The strict custom M expression checker now verifies `Number.Round`'s optional precision and every known argument even if a sibling field type is unknown. It distinguishes an explicit `null` from an unknown field, propagates definite-null nested results, and rejects null in required text parameters, conditional predicates, and unsupported precision positions while permitting supported nullable M positions. A bounded culture-aware `Table.TransformColumnTypes` form now round-trips for five local types and literal cultures; whole-number conversion with or without a culture uses M default ties-to-even rounding and signed Int64 bounds, decimal conversions reject Double overflow and normalize underflow, and `Currency.Type` rejects. Focused M acceptance passes **46 tests and 107 subtests**; the complete workspace suite passes **515 tests and 385 subtests**. These remain local parser and replay checks; external Mashup execution is not verified.

The transpose increment maps only `Table.Transpose(table)`. Semantic review found that normalized local text loses native cell types and merges M nulls with empty text. The bridge blocks cell-dependent operations after transpose and permits only schema changes, row windows, index creation, and the exact blank-row removal shape. Focused M tests pass **48 tests and 112 subtests**; the full workspace suite passes **517 tests and 389 subtests**; compilation and whitespace checks pass. These remain local parser and replay checks, not external Mashup execution.

## Iteration 6 — In-session Append/Merge (verified)

The Power Query Editor Home ribbon can stage Append and Merge from current session previews. Newly staged combinations follow parent edits and commit with their query definitions, type maps, model tables, and results in one Apply transaction. A controller review found a stale-parent commit path; the fix rebuilds new combines from their accepted parent previews and verifies the result against the editor preview while preserving saved-query cache behavior.

Focused Power Query/session tests pass **52 tests and 52 subtests**. The full workspace suite passes **544 tests and 419 subtests**. `py_compile` and `git diff --check` pass. Full M, Power Query Desktop parity, and full DAX remain open.
# Iteration 12 — Edit existing local source settings

## Objective

Add a working Home → Edit Source Settings action inside the separate Power Query session for existing CSV, Excel, JSON, XML, and Parquet root queries.

## Plan

1. Add failing tests for the session action, stable source/query identity and applied steps, dependency previews, cancel and failure isolation, Apply-time file drift, and Close & Apply/save/reopen/refresh from the changed path/options.
2. Add a source-settings mode to the existing file preview dialog and a staged callback for an existing CSV, Excel, JSON, XML, or Parquet root. Keep the source ID, connector kind, display/query metadata, and applied steps; let users change the file path and parser options only.
3. Pass the existing source record into the editor session. Overlay staged file path/options for preview and Apply, rebuild included descendants through the saved reference/append/merge graph, and preserve excluded-query cache behavior.
4. Compare root and dependent output headers and type maps before accepting source settings. Reject schema/type changes in this increment so model, report, relationship, and DAX bindings cannot silently become invalid. Keep all staged work local until Apply; any parse, replay, validation, or drift failure leaves project and controller caches unchanged.
5. Run focused tests, then the previously authorized full test suites, compilation and whitespace checks. Update the roadmap/audit with exact support and keep full DAX and Microsoft Mashup parity open.

## Explicit boundaries

SQLite, folder combine recipes, SQL Server, OData, and Web source-edit flows are deferred. Full Mashup execution and complete DAX are not part of this source-edit slice and remain unsatisfied. Existing workspace changes must be preserved.
