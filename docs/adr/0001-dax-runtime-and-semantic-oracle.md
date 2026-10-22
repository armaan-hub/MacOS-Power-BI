# ADR 0001: DAX runtime and semantic oracle

**Date:** 2026-10-12 (revisited)
**Status:** Accepted as a compatibility gate; runtime selection deferred  
**Decision owners:** Analytics Studio maintainers

## Context

The product targets a native macOS desktop workflow and stores local data and model metadata in `.npa` projects. Users have requested the full DAX function set and Power BI-like calculation behavior. The current editor catalog has 57 entries: 53 evaluator function names plus the parser/editor forms `BLANK`, `DISTINCT`, `FALSE`, and `TRUE`. These are partial local semantics, not 57 complete function implementations. The evaluator does not implement the complete DAX language, Tabular model, VertiPaq storage, visual query context, lineage, or complete type/error behavior. A bounded `RELATED` form supports numeric target values through direct active many-to-one relationships inside measure iterators. A shared relationship comparer uses typed numeric equality and Unicode case-folding for text keys across lookups, filter propagation, and one-side uniqueness validation; locale-specific collation is not stored. This does not change the compatibility boundary.

Microsoft's [DAX function reference](https://learn.microsoft.com/en-us/dax/dax-function-reference) documents more than 250 functions and says support can vary by product and version. Function-name recognition alone is therefore not an acceptance target. A compatible implementation must also reproduce syntax, binding, result types, blank/error handling, relationship behavior, filter and row context, and lifecycle behavior in a versioned model.

The reviewed options do not presently meet those requirements:

| Candidate | Evidence | Assessment |
|---|---|---|
| Integrated local evaluator | Native to the app and safe to package, with 53 evaluator function names and four parser/editor forms, all with bounded semantics. | Keep as a bounded local subset; it is not the requested full engine. |
| Microsoft Power BI Desktop/Tabular runtime | Microsoft's [Desktop requirements](https://learn.microsoft.com/en-us/power-bi/fundamentals/desktop-get-the-desktop) specify Windows. No supported native macOS Tabular runtime or embedding API has been identified for this application. | Does not currently meet native macOS packaging requirements. |
| Remote XMLA endpoint | Microsoft's [XMLA documentation](https://learn.microsoft.com/en-us/fabric/enterprise/powerbi/service-premium-connect-tools) describes client access to a Power BI/Fabric semantic model through a configured service endpoint. | A remote connected-model feature, not offline evaluation of the current local `.npa` model. It also introduces service, capacity, authentication, and network requirements. |
| `dax-rs` | Its [project README](https://github.com/daxrs/dax-rs) reports 122 of 211 functions and describes an AGPL-3.0-or-later XMLA/SOAP server using TMSL and Parquet. | Incomplete for the target; not a drop-in local evaluator. Redistribution and model-adapter work also need review. |
| [`pbix-mcp`](https://github.com/d0nk3yhm/pbix-mcp) | The project claims Desktop-conformance coverage for 435 of 467 catalogued DAX functions; its own limitations say probes and a real-world corpus do not establish every argument combination. PyPI lists v0.9.140, MIT, Beta, Python >=3.10, and dependencies on MCP, xpress9, xmhuffman, Pydantic, and APSW; its classifiers run through Python 3.13. Current upstream documentation describes a batch API using column arrays, row arrays, simple filter value sets, and relationship dictionaries; this API description is not verified against pinned v0.9.140 because installation failed. | Adapter-prototype candidate only. A pinned install attempt failed because the environment could not resolve pypi.org, so it is not installed or locally exercised against `.npa` projects. Python >=3.10 permits 3.14, but the published classifiers stop at 3.13, so compatibility is unverified rather than known-incompatible. App-specific filter provenance, grouped visuals, lifecycle, diagnostics, and performance still need proof. |
| Implement all DAX in the existing Python evaluator | The DAX specification includes table/scalar forms and context-sensitive semantics. There is no independent semantic oracle currently connected to this app. | Not a responsible path for claiming parity without a substantial engine and differential-validation project. |

## Decision

Keep the local evaluator clearly labeled **partial**, retain existing supported workflows, and do not add function names as stubs or describe them as Power BI-equivalent. Evaluate `pbix-mcp` with a local adapter prototype before adoption; upstream claims alone do not satisfy the acceptance gate. The pinned package install could not proceed because DNS could not resolve pypi.org, so no integration is made in this increment. This does not satisfy the user's request for full DAX; it records the next compatibility gate. XMLA is a client/server protocol; a Power BI Service endpoint is a separate remote-model option, not a local runtime for `.npa` data.

## Consequences

- Existing `.npa` projects continue to use the local evaluator and its current compatibility contract.
- New DAX work must be scoped to tested semantic families until a runtime and reference oracle are selected.
- A future engine proposal must establish macOS Apple Silicon support, distribution and licensing terms, model import/export mapping, diagnostics, cancellation/transaction behavior, representative performance, and save/reopen/refresh integration.
- No candidate is ruled out permanently. A remote XMLA adapter may be evaluated as a separate connected-model product feature, but it cannot be presented as local or offline DAX execution.

## Reconsideration gates

Before expanding the function catalog, produce a compatibility prototype that:

1. Runs on the supported Mac hardware and can be distributed under approved terms.
2. Evaluates representative scalar aggregation, filter replacement/intersection, context transition, table functions and grouped totals, inactive relationships, blanks, errors, and type coercion against a selected semantic oracle or approved reference fixtures.
3. Measures refresh/evaluation at 10k, 100k, and 1M rows and defines limits for the UI.
4. Preserves the current local report/model workflows or documents a deliberate migration path for `.npa` projects.
5. Defines a versioned syntax and function/form matrix before calling any capability compatible.

For `pbix-mcp`, also verify package installation on the supported Mac/Python runtime, compare its current public API and expression diagnostics to the pinned upstream release, and explicitly adapt the app's per-column filter provenance and grouped visual context without silently dropping either.

