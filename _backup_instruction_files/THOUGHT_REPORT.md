# Thought Report - Row-to-Filter Context Transition

## Interpretation from Domain Perspective
In Power BI DAX, when iterators like `SUMX` run, they create a "row context" that holds the values of the currently iterated row. Unlike "filter context", row context does not automatically filter other tables or aggregations.
However, when `CALCULATE` is invoked (or a measure is referenced, which implies an implicit `CALCULATE`), context transition occurs. The row context is converted into an equivalent filter context, filtering the iterated table (and by relationship propagation, its related tables) to only the row(s) whose column values exactly match the current row. Explicit `CALCULATE` filters override these transition filters if they touch the same columns. 

## Constraints
1. The local evaluator evaluates AST recursively without evaluating Python `eval`.
2. Existing iteration `row_context` passes the active table, text row dictionary, and index. 
3. Explicit `CALCULATE` arguments must seamlessly apply on top of the transition context.
4. We cannot change the signature of `row_context: dict[str, Any]` across the whole AST unless necessary.

## Architectures compared
- **Native inline filtering in CALCULATE:** Modify `evaluate` to check `if row_context is not None` inside `CALCULATE` and measure references, manually constructing a context copy, establishing the base filter, and proceeding. (Selected — matches existing `evaluate_with_boolean_filters` style, simplest, YAGNI compliant).
- **Sub-evaluation Context Object:** Refactor `current_context` to handle sub-contexts. (Too complex).

## Recommended Approach
Add a local `evaluate_with_context_transition` method inside `evaluate_measures`. When `CALCULATE` or a measure reference is encountered with an active `row_context`, this method calculates a row index mask evaluating to identical column values. It creates a new current context containing these filters, validates and propagates them, and calls `evaluate(node)` without `row_context`. The `node` (either `CALCULATE` or measure) will then evaluate in the new context natively.
# Iteration 12 — Existing local source settings in Power Query

## Interpretation

The user wants a functional, separate Power Query editing session on macOS and a complete DAX/model experience. The current editor is a native session with six ribbon tabs and bounded local M support; its own audit does not establish Desktop or Mashup parity. Microsoft documents those six Desktop tabs and a separate Advanced Editor, while Power BI Desktop itself requires Windows. The target here is therefore an independent Mac app with a clearly bounded engine, not an unverified claim that Microsoft's Windows runtime is embedded.

## Round 1 proposals

**Power Query and ETL Architect:** Add a Home → Edit Source Settings workflow for existing CSV, Excel, JSON, XML, and Parquet root queries. Stage the new path/options, replay existing steps and dependencies, and commit source metadata plus rows/types transactionally.

**Tabular Model and DAX Architect:** Do not try to satisfy “all DAX” by adding names or templates. First prove a true runtime adapter on Apple Silicon against a versioned semantic oracle; existing candidate engines are incomplete or unverified, and XMLA would be a separate connected-model feature.

## Round 2 cross-critique

**DAX Architect on the Power Query proposal:** Source editing is coherent but doesn't add any DAX engine or semantics; it must be reported as a separate Power Query increment. Preserve IDs and table names, block Apply on missing dependent columns/model bindings, and don't reuse replacement-import behavior that discards steps.

**Power Query Architect on the DAX proposal:** The runtime gate is sound but doesn't answer the user's current Power Query workflow need. Continue the working editor's end-to-end workflows and keep the Mashup boundary explicit.

## Round 3 convergence — Head decision

Implement source settings as the next concrete Power Query increment, limited to supported local file roots. Reuse the existing file preview/parser controls in a non-destructive staging mode. Retain source/query/model IDs, names, steps, and other metadata; preview dependent query results; block invalid schema/model references; commit path, parser settings, data, and type maps in one Close & Apply transaction. Cancel and failures must leave the project and caches unchanged. SQLite, folder, SQL Server, OData, and Web source editing remain out of this slice because their settings or credentials require connector-specific handling.

The full DAX requirement remains open and is not satisfied by this Power Query feature. No locally runnable, verified Mac DAX engine was found in the current audit. Keep the existing evaluator labeled partial; the next DAX work remains a local engine-adapter/semantic-oracle feasibility gate. The critic's null/empty/error data-model, refresh-exclusion-on-reopen, manual Mac acceptance, and performance concerns remain explicit follow-up gates.
