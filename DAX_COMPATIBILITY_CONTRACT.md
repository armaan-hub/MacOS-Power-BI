# DAX compatibility contract

**Status:** Audit baseline; no claim of Power BI DAX parity.

This document describes the DAX behavior currently implemented by Analytics Studio's local Python evaluator. It is a product compatibility contract, not a reference to the complete DAX language. Microsoft’s [DAX function reference](https://learn.microsoft.com/en-us/dax/dax-function-reference) covers more than 250 functions and notes that support varies by product and version.

## Target runtime

- **Product/runtime:** Analytics Studio's local, native desktop analytics application and its saved `.npa` project model.
- **Platform:** macOS is a target platform. Microsoft Power BI Desktop's [minimum requirements](https://learn.microsoft.com/en-us/power-bi/fundamentals/desktop-get-the-desktop) specify Windows 10 or Windows Server 2016 or later; this application is not Microsoft Power BI Desktop.
- **Storage/model engine:** Local imported tables, local relationship metadata, and a bounded safe Python evaluator. The evaluator parses expressions into a small AST; it does not call a Tabular/VertiPaq engine, execute Python supplied by a user, or load PBIX/TMDL models.
- **Version target:** No specific Microsoft engine/version is currently claimed. A versioned target requires the engine feasibility decision recorded below.

## Calculation object scope

| Object | Current behavior | Current boundary |
|---|---|---|
| Measure | Persisted name and expression; optional description, display folder, and hidden flag; evaluated for the local report context and displayed in supported report workflows. | Numeric/scalar subset; format strings, home-table reassignment, general DAX result types, and complete visual query context are not modeled. |
| Calculated column | Persisted name and expression; recalculated row by row after source refresh. | Bounded numeric/boolean expressions over the owning table; general cross-table `RELATED` behavior and broad DAX context are unavailable. |
| Calculated table | Saved query dependency and refresh behavior. | Only a one-column `DISTINCT('Table'[Column])` definition is supported; this is not a general DAX table-expression engine. |
| Power Query custom column | Separately authored in the local M-style expression subset and replayed at source refresh. | Not a DAX calculated column and not a full Power Query M function runtime. |
| Visual calculation | Unavailable. | Not parsed, persisted, or evaluated. |

## Function inventory

The parser's current `_FUNCTIONS` allowlist contains these 50 names. **Every entry below is Partial**: recognition does not imply general argument support, full DAX type coercion, complete context behavior, or parity with Microsoft’s engine. Each family requires supported-form and semantic tests before its status can be upgraded.

| Family | Recognized names | Status |
|---|---|---|
| Aggregation and counting | `SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT`, `COUNTA`, `DISTINCTCOUNT`, `DISTINCTCOUNTNOBLANK`, `COUNTROWS` | Partial |
| Scalar arithmetic and conditionals | `DIVIDE`, `ABS`, `ROUND`, `IF`, `AND`, `OR`, `NOT` | Partial |
| Iterators and row context | `SUMX`, `AVERAGEX`, `COUNTX`, `COUNTAX` | Partial |
| Filter/context operations | `CALCULATE`, `FILTER`, `KEEPFILTERS`, `REMOVEFILTERS`, `ALL`, `ALLNOBLANKROW`, `ALLEXCEPT`, `ALLSELECTED` | Partial |
| Relationship lookup and modifiers | `RELATED`, `USERELATIONSHIP`, `CROSSFILTER` | Partial |
| Time intelligence | `TOTALYTD`, `TOTALQTD`, `TOTALMTD`, `DATESYTD`, `DATESQTD`, `DATESMTD`, `DATESBETWEEN`, `DATESINPERIOD`, `PREVIOUSYEAR`, `PREVIOUSQUARTER`, `PREVIOUSMONTH`, `PREVIOUSDAY`, `NEXTYEAR`, `NEXTQUARTER`, `NEXTMONTH`, `NEXTDAY`, `PARALLELPERIOD`, `DATEADD`, `SAMEPERIODLASTYEAR` | Partial |

Any function absent from this list is **Unsupported** until parser, validation, evaluation, context, error, and lifecycle semantics have been implemented and accepted. Operators and special forms are also bounded; the 50-name count does not enumerate complete DAX syntax.

## Current semantic boundaries

- Expressions are parsed into a small AST with length/token limits. Arbitrary Python or other host-language execution is not allowed.
- Scalar values are predominantly normalized text or decimal numbers. This is not the complete DAX Variant type system; blank, coercion, collation, error, and locale semantics can differ.
- Measures use the current report/page/visual filter and relationship paths, but the evaluator does not model all visual row/column query-axis context. In particular, its supported `ALLSELECTED` behavior does not provide full visual totals.
- Row context exists in bounded `SUMX`, `AVERAGEX`, `COUNTX`, and `COUNTAX` paths. Iterator conditions in `COUNTX`/`COUNTAX` support comparisons when the local operand types can be verified: equality/inequality supports matching numeric, Boolean, or text operands, while ordering comparisons require numeric operands. Logical operands must be Boolean, and declared text columns cannot be coerced to Boolean even if their values spell `true` or `false`. An untyped reference may be inferred as Boolean only when paired with a Boolean expression and only if the row value parses as `true` or `false`. Text equality is limited to same-table text columns or a text column and string literal, using Unicode case-folding. Mismatched, date/time, and unverifiable operand types reject. Model-specific collation is not stored. This is not a complete context-transition, lineage, or expanded-table implementation.
- `RELATED` is supported only inside those measure iterators, with one qualified numeric target column and one direct active, unambiguous many-to-one relationship from the iterated row to the lookup table. Numeric keys use typed numeric equality; text keys use Unicode case-folded equality because project metadata does not store model collation. This shared local comparer is also used by relationship filtering and one-side uniqueness checks. It approximates a common case-insensitive collation and may differ from locale-specific model behavior. Case-fold collisions on a one side are rejected during relationship validation and source refresh. The lookup scans the complete related table regardless of its applied filters; a key without a matching row returns BLANK. It does not support text results, inactive or multi-hop relationships, one-to-one or many-to-many links, calculated columns, `RELATED` inside `FILTER`, or general row-context stacks.
- Relationship paths support the current saved cardinality, direction, active/inactive, and ambiguity rules. This is not a complete Tabular relationship engine.
- Filter functions are limited to enumerated forms. A function accepted by the parser may reject other argument arrangements or combinations.
- Calculated tables, calculated columns, and measures have separate lifecycle semantics; behavior of one object kind must not be inferred from another.

## Measure authoring support

The current Home and Modeling ribbons expose **New DAX measure**, and Model view exposes the same action when a table is loaded. The native measure editor has a searchable insert list for the 50 names in `_FUNCTIONS` plus the parser's `TRUE`, `FALSE`, `BLANK`, and `DISTINCT` special forms, qualified references to fields in loaded model tables, and references to saved measures. Every recognized name inserts a local syntax template and selects its first editable argument; these templates do not imply full Microsoft signatures or behavior. `RELATED` inserts its qualified target-column template and follows only the bounded relationship form above. The editor links to Microsoft's 250+ function catalog and labels the evaluator as partial. **Validate / preview** evaluates a draft against the current page/report and relationship context without saving it or changing report filter diagnostics/cache state. It does not include a visual-specific filter context. Validation and preview use the same bounded local parser and evaluator described above.

### Distinct-count forms — 2026-10-12

`DISTINCTCOUNT([Column])` and `DISTINCTCOUNTNOBLANK([Column])` accept one column reference and work as saved measures in the local evaluator. For `DISTINCTCOUNT`, the normalized blank marker counts once when at least one row is present; `DISTINCTCOUNTNOBLANK` omits it. Both return blank when the evaluated rowset contains no rows. The latter no-row result follows the local aggregate convention; Microsoft's page explicitly documents the no-row result for `DISTINCTCOUNT` but does not state it on the `DISTINCTCOUNTNOBLANK` page. The Quick Measure picker and searchable function list can insert the nonblank form. A scalar distinct-count call is also accepted in the tested `COUNTX`/`COUNTAX` iterator expression subset.

The local table normalizes null and empty text to the same cell value, so those cannot be counted separately. Text distinctness currently uses exact local strings because the project does not store model collation; case/accent behavior can differ from a Power BI model. Zero and whitespace-only strings remain ordinary values. Microsoft documents that `DISTINCTCOUNT` counts BLANK and returns BLANK for no rows, and that `DISTINCTCOUNTNOBLANK` skips BLANK: [DISTINCTCOUNT](https://learn.microsoft.com/en-us/dax/distinctcount-function-dax), [DISTINCTCOUNTNOBLANK](https://learn.microsoft.com/en-us/dax/distinctcountnoblank-function-dax). This local implementation has no differential Tabular oracle and is not a claim of full DAX parity.

`COUNTX` and `COUNTAX` accept a loaded table or supported `ALL` table expression and one row expression. In this local measure-only subset, `COUNTX` counts nonblank numeric or text results and skips Boolean results; `COUNTAX` counts nonblank numbers, text, and Booleans. Direct text columns, numeric row expressions, Boolean expressions, empty-string expression results, blanks, and simple `IF` results are covered. Iterator `IF` conditions support comparisons when operand types can be verified: equality/inequality allows matching numeric, Boolean, or text types, and ordering requires numeric operands. Text equality is limited to text-typed columns, string literals, and supported text-producing `IF` branches; supported arithmetic and scalar expressions are type-checked, while mismatched, date/time, and unverifiable operand types reject. Numeric scalar functions validate the declared categories of their inputs, and iterator row expressions are checked against the correct table schema even when a table is empty. Scalar aggregate column references resolve their type from the aggregate's own model table, independently of the current iterator row. Nested supported iterators may use their own loaded table or `ALL` table scope; references from the inner row expression to an outer table row are unsupported. String matching uses Unicode case-folding because the model does not store a DAX collation. The evaluator does not implement general DAX type coercion. Formula-produced `""` counts, while stored empty cells and `BLANK()` results are skipped after local blank normalization. When no countable result exists, including an empty table or all-blank/Boolean-only `COUNTX` input, `COUNTX`/`COUNTAX` return `BLANK()`; `COUNTX` skips Boolean results and `COUNTAX` counts them. Blank is preserved through direct measure references, the supported `CALCULATE` wrappers, draft preview, KPI/card values, grouped chart points, and matrix cells. A numeric zero remains distinct. The evaluator still coerces blank to zero in numeric operators through its current `as_number` helper; operator-specific DAX blank coercion is not implemented. General table expressions, cross-table row references, and calculated-column use remain unsupported. Microsoft documents these functions at [COUNTX](https://learn.microsoft.com/en-us/dax/countx-function-dax) and [COUNTAX](https://learn.microsoft.com/en-us/dax/countax-function-dax).

**COUNTX/COUNTAX blank inference boundary:** Microsoft's documentation says these functions return blank when there are no rows to count or aggregate and identifies `COUNTAX` for logical values. Applying that wording to a nonempty all-blank iterator and a Boolean-only `COUNTX` is an inference because the references do not show those exact examples. No external Tabular engine was used as a differential oracle. This local contract is covered by evaluator and report lifecycle tests; it is not a claim of Microsoft-engine parity.

## Table and Slicer measure behavior — 2026-10-12

Table visuals accept column and measure fields together. Assigned columns define distinct row groups, and each saved measure is evaluated under that row's filter context; multiple measures are supported. A measure-only Table evaluates one total-context row. Table row selection uses the first displayed column field as its cross-filter category, even when a measure appears first in the field list or an older saved visual omits `table_id`. If a source refresh removes an assigned dimension, the Table displays an explicit stale-field message instead of a blank category with a grand-total measure. A missing or failing saved measure also produces an evaluation message instead of appearing as a genuine blank. Slicers accept columns only: measure choices are hidden and rejected, and persisted invalid measure bindings yield no selectable values.

This is a bounded report feature, not general DAX visual-query behavior. A Table remains bound to one model table; cross-table grouping, grouped-table total rows, broader relationship-driven query context, and explicit no-data row options remain unsupported. The behavior is covered by local evaluator/report lifecycle tests, not by comparison with a Tabular engine. Microsoft documents measures as context-dependent visual values and Table visuals with category columns plus measures at [measures in Power BI](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-measures) and [Table visuals](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualization-tables?tabs=powerbi-desktop); slicers use field values at [Slicer visual](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualization-slicer-visual).

## Required gate before expanding DAX

Maintain [ADR 0001](docs/adr/0001-dax-runtime-and-semantic-oracle.md) and run a small compatibility prototype comparing the current evaluator with viable embedded/sidecar and (if relevant) remote tabular engines. Record:

1. Licensing and redistribution, macOS Apple Silicon support/packaging, project/model import and export, and deployment footprint.
2. Recalculation and interaction performance at representative 10k, 100k, and 1M-row model sizes.
3. Formula diagnostics and debugging, transaction behavior, metadata preservation, and save/reopen/refresh integration.
4. Semantic-oracle results for representative scalar aggregation, filter replacement/intersection, row-to-filter context transition, table functions/visual grouped totals, and inactive relationship calculations.
5. A function/form/syntax matrix against the chosen product/version. If no candidate meets the target, explicitly narrow the local compatibility target before adding new functions.

No new function is called Power BI-equivalent until it has parser, name-binding, argument-validation, evaluation, return-type, blank/error, filter/row-context, relationship, and report-lifecycle tests against the selected semantic oracle or approved reference fixtures.

## Engine feasibility checkpoint — 2026-10-12

The initial macOS-compatible engine check did not identify a drop-in runtime that meets the requested complete DAX scope. The current Python evaluator remains the only engine integrated with Analytics Studio's project, report filters, relationships, and calculation lifecycle.

| Candidate | Assessment | Decision |
|---|---|---|
| Local evaluator | Native to the app and safe to package, but it recognizes only 50 function names with partial semantics and lacks full Tabular model/query behavior. | Keep clearly labeled as partial while compatibility work continues. |
| `dax-rs` | Its project README reports **122 of 211** DAX functions implemented. It is an AGPL-3.0-or-later XMLA/SOAP server using TMSL models and Parquet datasets, not a drop-in Python library for the current `.npa` model. Its own roadmap identifies full function coverage as future work. | Do not integrate as a route to complete DAX. It is incomplete for the requirement, introduces a separately packaged server/model adapter, and its AGPL terms require a product-license review before redistribution. |
| [`pbix-mcp`](https://github.com/d0nk3yhm/pbix-mcp) | The project claims Desktop-conformance coverage for 435 of 467 catalogued DAX functions, using function probes and a report corpus. It also says unsupported expression shapes are refused and warns on in-memory tables above 100,000 rows; its parity claim is bounded by its probes and corpus. PyPI lists v0.9.140 (uploaded 2026-10-11), MIT, Beta, Python >=3.10, with classifiers through Python 3.13 and dependencies on MCP 1.x, xpress9, xmhuffman, Pydantic, and APSW. Current upstream documentation describes a batch API using table column/row arrays, measures, value-set filters, relationships, grouped keys, and culture; this API description has not been checked against pinned v0.9.140 because installation failed. The documented shapes do not directly carry this app's full filter provenance and report/object lifecycle. A pinned install attempt failed because this environment could not resolve pypi.org; the package remains absent and has not been executed locally. | **Prototype candidate only.** Do not treat upstream claims as locally verified or wire it into saved measure evaluation until a native Mac adapter reproduces representative calculations, filter/group/relationship semantics, BLANK/error diagnostics, lifecycle behavior, and performance. Python >=3.10 metadata permits this app's Python 3.14.4, but published classifiers stop at 3.13; 3.14 compatibility is unverified, not ruled out. |
| Microsoft Power BI Desktop/Tabular runtime | Power BI Desktop's published requirements specify Windows. No supported native macOS Tabular runtime or embedding API has been identified for this app. | Does not currently meet this app's native macOS packaging requirements. |

Sources: [`dax-rs` implementation and license status](https://github.com/daxrs/dax-rs), its [1.0 roadmap](https://www.dax.rs/blog/roadmap/), Microsoft's [Power BI Desktop requirements](https://learn.microsoft.com/en-us/power-bi/fundamentals/desktop-get-the-desktop), and Microsoft's [XMLA reference](https://learn.microsoft.com/en-us/analysis-services/xmla/xml-for-analysis-xmla-reference?view=sql-analysis-services-2025).

**Decision:** Keep the integrated local evaluator labeled partial. `pbix-mcp` is a candidate for a controlled adapter prototype, not an approved runtime. The pinned install attempt failed because DNS could not resolve pypi.org; no upstream code has been executed against `.npa` data. Do not silently fall back between engines. It must meet the Mac, Python 3.14, local-project mapping, performance, diagnostics, lifecycle, and semantic-oracle gates above before integration. XMLA is a client/server protocol; connecting to a Power BI Service XMLA endpoint would be a separate remote-model feature and would not provide offline evaluation of the current local model ([XMLA reference](https://learn.microsoft.com/en-us/analysis-services/xmla/xml-for-analysis-xmla-reference?view=sql-analysis-services-2025), [Power BI Service XMLA](https://learn.microsoft.com/en-us/fabric/enterprise/powerbi/service-premium-connect-tools)).

The decision is recorded in [ADR 0001: DAX runtime and semantic oracle](docs/adr/0001-dax-runtime-and-semantic-oracle.md). Runtime selection and the user's full-DAX requirement remain open.

## Roadmap

1. Complete this inventory with exact supported argument forms and tests for each currently recognized name.
2. Run the `pbix-mcp` adapter prototype on a supported Mac/Python runtime and compare it to existing app fixtures, including grouped report visuals and changed-source lifecycle.
3. Decide on a compatible engine or explicitly version and scope the local evaluator.
4. Choose one high-value function family and implement it end to end, including model/report integration and persistence.
5. **Partly complete:** measure descriptions, display folders, and hidden state now save/reopen and appear in Model view; hidden measures remain available to formula dependencies and leave report field pickers. Add format strings with visible report formatting, home-table reassignment, sort-by columns, data categories, hierarchies, and corresponding table/column metadata.
6. Add broader calculation families and model features only behind their own semantic acceptance gates: cross-table calculated columns/tables, visual axes and totals, calculation groups, perspectives, translations, roles/security, and storage-mode behavior.

