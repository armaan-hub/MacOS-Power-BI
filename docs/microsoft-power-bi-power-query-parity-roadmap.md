# Microsoft Power BI and Power Query Parity Roadmap

**Baseline date:** 2026-10-19
**Product compared:** Analytics Studio
**Comparison target:** Microsoft Power BI Desktop and Power Query Desktop first; Power BI Service, Microsoft Fabric, mobile, Report Server, paginated reporting, and embedding are tracked as separate expansion tracks.

This roadmap compares Microsoft’s documented capability families with the current Analytics Studio implementation and records the gaps as work items. It is an inventory and delivery order, not a promise that every Microsoft connector, licensed service, preview, or third-party extension will be implemented.

## 1. How to read the comparison

Power BI includes several hosts with different capabilities: Desktop, the cloud Service, Power Query Online, Fabric, mobile apps, Report Server, and embedded experiences. Connector availability, authentication, gateways, refresh, and feature access vary by host, license, tenant, region, and preview status. Therefore, parity is tracked by host and workflow rather than treating Power BI as one executable with one feature list. Microsoft maintains a host-specific [Power Query connector matrix](https://learn.microsoft.com/en-us/power-query/connectors/) and describes the distinct Power BI [Desktop and Service roles](https://learn.microsoft.com/en-us/power-bi/fundamentals/service-service-vs-desktop).

Analytics Studio currently targets a local-first native desktop workflow on Apple Silicon macOS. Microsoft Power BI Desktop is a Windows application. The first target in this roadmap is **capability parity for common Desktop authoring workflows**, not identical implementation, pixel-perfect UI, PBIX runtime compatibility, or equivalence with every cloud service. Full Desktop parity therefore requires explicit decisions about platform support, project interchange, engine reuse, and product scope.

Status labels:

| Label | Meaning |
|---|---|
| **Implemented** | A scoped workflow is present and has recorded acceptance. This does not imply Microsoft-wide parity. |
| **Partial** | A bounded subset works, or implementation exists but a live, manual, or broader acceptance gate remains. |
| **Missing** | No meaningful end-to-end workflow is available in the app. |
| **Separate track** | The capability belongs to a different host or product surface and needs a product/architecture decision before implementation. |

Priority labels:

| Priority | Meaning |
|---|---|
| **P0 — Scope and inventory** | Establish a maintainable, versioned comparison and close release-blocking accuracy gaps. |
| **P1 — Local desktop foundation** | Work needed for a dependable local authoring product and common Desktop-style workflows. |
| **P2 — Desktop depth and interchange** | Broader language, model, visual, performance, and project compatibility. |
| **P3 — Cloud and organizational platform** | Requires identity, hosted services, multi-user storage, and operations. |
| **P4 — Separate host and extension products** | Mobile, paginated, Report Server, embedding, and specialized integrations. |

## 2. Current Analytics Studio position

| Capability family | Current state | Comparison with Microsoft |
|---|---|---|
| Local sources and project workflow | **Partial** | CSV, Excel, JSON, XML, Parquet, folders, SQLite, SQL Server, OData, and anonymous Web workflows are present in documented subsets. Live acceptance is still pending for SQL Server and broad OData/Web behavior. The project format is `.npa`, not PBIX. |
| Power Query shaping | **Implemented within listed local scope** | The project roadmap records 51 listed local query-management and shaping workflows with lifecycle acceptance. The editor, operation set, and expression behavior remain a bounded local subset. |
| Power Query M | **Partial** | Advanced Editor and round-trip coverage exist for supported forms. There is no general Microsoft Mashup runtime, complete M library, query folding, or full Power Query execution compatibility. |
| Query management | **Partial** | A separate session supports query navigation, steps, groups, reference/append/merge/duplicate/delete, load and refresh flags, parameters/functions in supported forms, and staged Apply. Privacy controls, broad credential management, remote/schema-changing workflows, and full M behavior remain open. |
| Semantic model and DAX | **Partial** | Relationships, scoped filters, calculations, and many report workflows work in tested subsets. The local evaluator recognizes 53 DAX function names with partial semantics; this is not a compatible Tabular/DAX engine. Iteration 34 adds measure-only numeric `MAXX`/`MINX` over loaded tables and supported `ALL`-family forms, with blank skipping, editor guidance, and report/project lifecycle coverage; broader Microsoft type, variant, and table-expression forms remain unsupported. Iteration 33 adds table-scoped Sort by Column metadata for loaded source fields, active/inactive rule status and recovery, and order in supported chart categories/legends, KPI trend axes, slicers, and Matrix axes, including bound DAX-measure grouping. Iteration 32 adds table-scoped Model-view defaults (`Auto`, `Sum`, `Average`, `Count`) for loaded numeric source columns and seeds new bindings in the supported value wells; dormant defaults survive field/source unavailability and visuals keep their saved aggregations. Iteration 31 corrected `DIVIDE` zero-denominator behavior and added scalar-measure `COALESCE`, with numeric zero and Boolean false preserved and unsupported calculated-column, row-iterator, and table-valued uses rejected. Generated Quick Measures use a table-qualified field reference and retain their source across table switching and source refresh. |
| Report authoring and visuals | **Partial** | Pages, a broad set of built-in visuals, field wells, formatting, interactions, themes, and static objects have scoped acceptance. One bounded Table workflow groups a qualified measure by a related dimension field; other visuals still use a single-table context. Broader formatting, maps, visual catalogs, and authoring behavior remain open. |
| Security, service, and administration | **Missing** | No hosted workspaces, publishing, organization-wide sharing, tenant administration, RLS/OLS enforcement, service refresh, or governance system. |
| Mobile, paginated, Report Server, and embedded | **Separate track** | No native mobile reader, RDL authoring/rendering, Report Server deployment, or Power BI embedding/API workflow. |
| Developer interchange and extension | **Missing** | No PBIX/PBIT/PBIP compatibility, TMDL authoring, XMLA, Power BI external-tool protocol, custom visual package runtime, or Power BI content APIs. |

The latest recorded scoped verification is Iteration 34 (2026-10-19): the focused Model/DAX/project/report integration passed **210 tests and 215 subtests**; the fresh full offscreen suite is pending; independent critic and SDET reviews passed. This does not establish full Power BI parity or native macOS, live-service, minimum-Mac performance, or accessibility acceptance. See the [Iteration 34 test results](../.council/TEST_RESULTS_ITER34.md) after the full regression gate, [verification sign-off](../.council/VERIFICATION_SIGN_OFF_ITER34.md), [functionality progress snapshot](../POWER_BI_FUNCTIONALITY_PROGRESS.md), and [master functionality map](../POWER_BI_FUNCTIONALITY_ROADMAP.md).

## 3. Capability comparison and missing-work register

### A. Product hosts, project boundaries, and compatibility

| ID | Capability | Microsoft Power BI / Power Query | Analytics Studio now | Work to add |
|---|---|---|---|---|
| A1 | Host and platform support | Desktop authoring, Service authoring/consumption, Power Query Online, Fabric, mobile, Report Server, and embedded surfaces have host-specific behavior. | Native local desktop app; first supported platform is Apple Silicon macOS. | **P0:** Maintain separate Desktop, Service/Fabric, and other-host matrices. Decide whether Windows support or only workflow-level cross-platform parity is a goal. |
| A2 | Project and template files | PBIX reports, PBIT templates, PBIP project folders, model metadata, and service artifacts have distinct compatibility and lifecycle behavior. | Versioned `.npa` project with save/reopen and migration support. | **P2:** Define an interchange strategy. Inventory PBIX/PBIT import/export, PBIP report/model folders, and semantic-model metadata. Prototype one-way report/data import before promising round-trip compatibility. |
| A3 | Release and preview tracking | Microsoft features can be host-, license-, region-, tenant-, and preview-specific and may be retired. | Roadmap snapshots have dated status; some older inventory files are stale. | **P0:** Put a checked date, host, preview/GA/retired status, source link, and local acceptance evidence on every comparison row. Review the official catalogs each release. |

### B. Data connections and Power Query

Power Query’s connector index spans files, databases, cloud services, business applications, semantic models, and other sources; the index explicitly warns that support differs by host. The target should be a prioritized, explicit connector set rather than a claim to implement every marketplace connector.

| ID | Capability gap | Priority | Planned scope / acceptance |
|---|---|---:|---|
| B1 | Connector catalog reconciliation | P0 | Compare the official connector index against the app’s visible picker. For each connector, record host support, owner, auth modes, gateway need, preview/retirement state, limits, import/refresh mode, and decision: implement, defer, or exclude. Remove stale “available” entries or explain why disabled. |
| B2 | Connector breadth and navigation | P1/P2 | Add prioritized file, relational, warehouse, cloud-storage, SaaS, web/API, and semantic-model connectors. Support multi-object navigation, schema discovery, preview, table selection, cancellation, error recovery, and save/reopen/refresh per connector. Keep long-tail and vendor connectors in the inventory until individually decided. |
| B3 | Authentication and connection management | P1 | Add reusable connection records and credential lifecycle for supported anonymous, username/password, database, OAuth/Microsoft Entra, key/token, and supported SSO methods. Provide edit, test, clear, rotation, expiry, and safe error flows; never expose secrets in project files or logs. |
| B4 | Privacy levels and data isolation | P1 | Implement source privacy classifications and a data privacy firewall for cross-source combinations. Validate that local previews, folding, logs, error messages, exports, refresh, and staged Apply cannot leak data across privacy boundaries. |
| B5 | Gateway and hosted refresh | P3 | Add gateway configuration, source-to-gateway binding, credential ownership, gateway health, and refresh-through-gateway only if a hosted Service is approved. |
| B6 | Power Query editor operation coverage | P1/P2 | Build an operation-level comparison from the current Desktop ribbon and M references. Add missing shaping, parsing, aggregation, row/column, date/time, list/record/table, and error-handling operations with option parity and deterministic replay. Maintain a tracked operation checklist rather than equating existing local operation count with Power Query parity. |
| B7 | Full M language and standard library | P2 | Decide between a supported compatible runtime, a managed integration, or a clearly versioned subset. Track M syntax, values, types, functions, records/lists/tables, sections, metadata, recursion, evaluation, culture, nulls, and error behavior against Microsoft’s M specification and function reference. Every unsupported construct must fail visibly without losing edits or applying partial transformations. |
| B8 | M editor authoring experience | P1/P2 | Add multi-line editing, syntax diagnostics, completion, formatting, inline errors, function/parameter help, step-to-code synchronization, and safe script round-trips. Existing formula-first custom-column UI and bounded editor are starting points. |
| B9 | Query folding and source execution | P2 | Add connector-specific folding, folding indicators, query plans, native-query support where safe, diagnostics, and clear step boundaries. Verify generated source requests and privacy rules. Folding is not applicable to every source or every step. |
| B10 | Query dependencies and groups | P1/P2 | Extend current dependency view and flat groups with editable dependency operations, nested groups, broader query properties, diagnostics, and robust cycles/missing-source handling. |
| B11 | Query parameters and reusable functions | P1/P2 | Expand current typed parameters and scalar-function subset to supported M parameter and function patterns, dynamic source parameters, reusable function invocation, and query-level parameter management. Validate security and refresh behavior. |
| B12 | Join and combine parity | P1/P2 | Extend exact local joins with fuzzy matching, configurable match thresholds, selected-column expansion, aggregation, nested table behavior, locale/collation choices, duplicate handling, and source-folding outcomes where supported. |
| B13 | Data profiling and diagnostics | P1 | Expand quality/profile views with column distribution, value distribution, error drilldown, full-dataset vs preview scope, profiling controls, diagnostics traces, and per-step/source timing. Keep preview-only statistics clearly labeled. |
| B14 | Source schema evolution | P1 | Support a reviewed workflow for changed source columns/types, dependent query revalidation, relationship and DAX impact analysis, migration, rollback, and refresh. Current remote edits require unchanged output schema/types. |
| B15 | Refresh breadth | P1/P3 | Complete live remote source checks; add source-specific refresh history and recovery. Treat local Refresh All, scheduled Service refresh, incremental refresh, real-time DirectQuery refresh, and dataflow refresh as separate workflows. |
| B16 | Dataflows | P3 | Add a separate Dataflow Gen1/Gen2 decision and architecture. Track browser-based Power Query authoring, shared cloud connections, destinations, orchestration, refresh, and capacity prerequisites; do not assume the desktop M bridge provides dataflows. |

### C. Semantic model and DAX

Microsoft’s DAX reference documents more than 250 functions across aggregation, date/time, filter, financial, information, logical, math, relationship, statistical, table-manipulation, text, and time-intelligence families. Microsoft Power BI also supports multiple storage and connection modes. The current local evaluator and model are partial implementations.

| ID | Capability gap | Priority | Planned scope / acceptance |
|---|---|---:|---|
| C1 | DAX compatibility target | P0 | Select and version a DAX support contract by function, syntax, data type, host behavior, and known deviations. Generate a function/operator matrix from the Microsoft reference. Do not use recognized function-name count as a parity metric. |
| C2 | DAX parser, editor, and semantics | P2 | Expand the current editor and evaluator to the declared target, including variables, full expression grammar, table expressions, row/filter context, context transition, expanded tables, auto-exist, relationships, blank/error/coercion rules, collation, time intelligence, and relevant DAX query forms. Iteration 34 adds only two-argument numeric/blank `MAXX` and `MINX` measure forms; variant, text/date/Boolean, mixed-type, arbitrary table-expression, and calculated-column forms remain open. The generated Quick Measure context bug is closed for new measures: the selected active table is embedded in the expression. Keep manually authored unqualified expressions unchanged; continue the compatibility work against a semantic oracle and regression corpus. |
| C3 | Tabular model metadata | P1/P2 | **Partial:** default summarization and a v80 Sort by Column subset now have Model-pane persistence and lifecycle coverage. Add table/column descriptions, formats, data categories, hierarchies, folders, translations, perspectives, format strings/home-table reassignment for measures, and remaining sort behavior with migration and save/reopen coverage. Existing measure descriptions, display folders, and hidden state are supported. The Microsoft authoring surface is Report view's Column tools; Analytics Studio's Model inspector is a local design choice. |
| C4 | Relationships and diagrams | P1/P2 | Expand relationship behavior to documented cardinality, many-to-many, bidirectional filtering, inactive relationships, ambiguity/paths, security propagation, composite models, and editable model diagrams/layouts. Add explainable diagnostics for invalid or ambiguous paths. |
| C5 | Model calculations | P2 | Add full calculated-table and calculated-column behavior, calculation groups/items, dynamic format strings, field parameters, what-if parameters, and additional model-level calculation objects as separately testable features. |
| C6 | Storage and connection modes | P2/P3 | Design Import, DirectQuery, Dual, Hybrid, live semantic-model connection, composite models, and Fabric Direct Lake as separate storage modes. Track restrictions and user-visible behavior per connector and host. |
| C7 | Scale and model processing | P2/P3 | Add a scalable columnar model engine or a documented compatible engine, partitions, large-model support, aggregations, incremental refresh policies, processing/refresh states, memory diagnostics, and performance benchmarks. |
| C8 | Semantic model reuse | P3 | If a Service is built, add shared semantic models, Build permission, thin reports, endorsement/certification, model discovery, and cross-workspace permissions. |
| C9 | RLS and OLS | P3 | Implement role authoring, static/dynamic row filters, object-level table/column protection where supported, role membership, “view as” testing, and server identity integration. Security acceptance must cover DAX, visuals, profile panes, data grids, exports, refresh, query editor, logs, and project open/save. Keep security controls disabled until every path is enforced. |

### D. Report authoring, visuals, and interaction

Power BI’s report surface includes built-in and custom visuals, flexible field wells, filters, formatting, analytics, bookmarks, navigation, tooltips, accessibility, and mobile layouts. Current Analytics Studio features have scoped acceptance but do not expose full model-wide visual query context.

| ID | Capability gap | Priority | Planned scope / acceptance |
|---|---|---:|---|
| D1 | Multi-table visual query context | P1 | **First local slice implemented:** a Table visual can group one dimension column by one explicitly table-qualified DAX measure over a direct active, single-direction one-to-many relationship. Field identity persists by model-table ID; results stay stable when the Data pane's active table changes; save/reopen/refresh and visible fail-closed diagnostics are covered. Accepted constraints: unique nonblank dimension keys, nonblank and fully matched fact keys, one active path, compatible key types. **Still open:** multiple dimensions/measures, matrix and chart wells, multi-hop paths, broader relationship directions/cardinalities, drill paths, totals, and full Power BI query semantics. See `docs/verification-coverage.md` and tests `test_cross_table_table_visual_lifecycle.py` / `test_cross_table_table_visual_ui.py`. |
| D2 | Visual catalog reconciliation | P0/P1 | Compare each built-in Power BI visual category and its supported wells/options to Analytics Studio. Record supported, partial, missing, preview, and host-only status. Implement selected missing visuals only with model-query, formatting, interactions, and persistence together. |
| D3 | Maps and geospatial | P1/P2 | **First local slice implemented:** filled/shape visuals can load bounded user-selected GeoJSON/TopoJSON boundaries, bind report Location/Legend/Values fields, aggregate and select regions, and participate in report filtering/highlighting. Runtime and save/reopen/refresh acceptance remains open. Evaluate geocoding, basemaps, Azure Maps, ArcGIS, and location privacy as separate network-backed options. |
| D4 | Advanced and AI visuals | P2/P4 | Track decomposition tree, key influencers, waterfall extensions, sparklines, R/Python visuals, Q&A/natural-language visuals, and other AI visuals. Implement only with isolated execution, licensing/privacy decisions, and fallback behavior. |
| D5 | Custom visuals | P4 | Define a sandboxed extension/package format, capabilities, signing, data permissions, accessibility requirements, versioning, and gallery/review policy. Power BI `.pbiviz` packages are not automatically compatible. |
| D6 | Visual field wells and authoring | P1/P2 | Expand field parameters, hierarchies, default summarization, drag/drop semantics, visual-level error handling, field search, personal visual changes, and measure/column role validation for all visual types. |
| D7 | Formatting and analytics | P1/P2 | Complete visual-specific format properties, axis controls, conditional formatting, data bars/icons, dynamic colors/format strings, visual calculations, analytics/reference lines, forecast/anomaly features where supported, labels, legends, backgrounds, effects, and theme import/export. |
| D8 | Page and object layout | P1 | Add page size/aspect presets, wallpaper/background, grid/snap, align/distribute, lock, duplicate page, hide page, page tooltip settings, selection pane, and precise multi-object editing. Keep the current resize, grouping, z-order, and static-object workflows. |
| D9 | Navigation and exploration | P1 | Add bookmarks with saved filter/visibility state, bookmark/page navigators, drill down/up, drillthrough (including cross-report where supported), report-page tooltips, visual header controls, and reader personalization. |
| D10 | Filter system | P1/P2 | Expand the existing report/page/visual filters with drillthrough filters, locked/hidden filter cards, filter-pane formatting, advanced filter UX, hierarchy filters, dynamic filters, and equivalent interactions across every supported visual. |
| D11 | Slicer parity | P1 | Add slicer types and behavior including list/dropdown/button/date range, hierarchy, sync across pages, select-all, search, single/multi-select, responsive behavior, and slicer-specific formatting. |
| D12 | Accessibility | P1 | Add keyboard-complete authoring/reading, screen-reader labels, focus and reading order, high contrast, color-independent status, accessible exports, and user review with native macOS assistive technology. |
| D13 | Mobile layout | P4 | Author phone layouts independently from desktop pages, preview device sizes/orientation, and validate touch interactions in a mobile reader. |
| D14 | Report performance | P1/P2 | Add Performance Analyzer-style per-visual/query timing, model/query profiling, large-report benchmarks, render cancellation, and optimization guidance. |

### E. Export, print, and developer interchange

| ID | Capability gap | Priority | Planned scope / acceptance |
|---|---|---:|---|
| E1 | Report/data export | P1/P2 | Add selected visual summarized/underlying data export, workbook export, PDF, image, and print workflows with filter/bookmark state, pagination, Unicode, and security behavior tested. Distinguish local export from Service export restrictions. |
| E2 | Project interchange | P2 | Decide whether to support PBIX/PBIT import/export, PBIP source projects, or an explicit migration-only path. Define compatibility limits for report pages, visuals, Power Query, model metadata, and DAX before exposing file-picker commands. |
| E3 | TMDL/XMLA/external tools | P2/P3 | Assess model scripting with TMDL/TMSL/TOM, XMLA read/write, external tools, and model metadata round trips. Keep cloud-only operations separate from local model editing. |
| E4 | APIs and automation | P3/P4 | Add stable project/report APIs, CLI automation, import/export contracts, and (only with hosted content) Power BI-like REST/JavaScript embedding APIs. Track auth, permissions, versioning, rate limits, and audit. |
| E5 | Versioning and team development | P2/P3 | Add human-reviewable project structure, migration tooling, Git-friendly diffs, merge/conflict handling, automated validation, and environment promotion. PBIP compatibility requires a separate design. |

### F. Power BI Service, Fabric, collaboration, and governance

These features require a cloud product, identity system, durable shared storage, tenant operations, and security engineering. They are not just additional ribbon buttons.

| ID | Capability gap | Priority | Planned scope / acceptance |
|---|---|---:|---|
| F1 | Identity and hosted content | P3 | Establish authentication, organization/tenant boundaries, cloud storage, content ownership, sharing permissions, deletion/recovery, and licensing model before any publish command is enabled. |
| F2 | Workspaces, roles, and apps | P3 | Add workspaces, role-based content permissions, semantic-model permissions, app packaging/audiences, content discovery, and consumer experience. |
| F3 | Publish and collaborate | P3 | Add publish/update workflows, comments, notifications, subscriptions, email delivery, Teams/SharePoint integration, sharing links, and public embed only with explicit security policy. |
| F4 | Dashboards and alerts | P3 | Add the distinct single-canvas dashboard model, tiles, pinning, mixed-source content, data alerts, notifications, and scorecards/goals where the product target warrants them. |
| F5 | Service refresh and connections | P3 | Add scheduled refresh, refresh history, connection ownership, cloud/on-prem gateway, credential rotation, failure notifications, and incremental/real-time refresh paths. |
| F6 | Fabric and OneLake | P3 | Add OneLake catalog discovery, Fabric lakehouse/warehouse/semantic-model connectors, Direct Lake, Fabric capacity awareness, dataflows, and cross-item lineage where supported. |
| F7 | Deployment and Git | P3 | Add dev/test/prod environments, deployment pipelines, Git integration, review gates, rollback, environment rules, and semantic-model/report compatibility checks. |
| F8 | Tenant administration | P3 | Add tenant/workspace/capacity administration, usage and activity metrics, refresh monitoring, quotas, feature controls, audit logs, and operational health views. |
| F9 | Governance and data protection | P3 | Add sensitivity labels, export and sharing controls, DLP integration, endorsement/certification, lineage/impact analysis, retention and audit policies, and controlled external collaboration. |

### G. Separate host and adjacent-product tracks

| ID | Capability gap | Priority | Planned scope / acceptance |
|---|---|---:|---|
| G1 | Paginated reports | P4 | Evaluate RDL authoring/rendering, parameters, page headers/footers, repeated tables, export formats, subscriptions, and print fidelity as a dedicated product and renderer. |
| G2 | Power BI Report Server | P4 | Treat on-premises server hosting, release-specific Desktop compatibility, permissions, subscriptions, portal, and operations as a separate deployment target. |
| G3 | Native mobile reader | P4 | Add iOS/Android authentication, report/dashboard consumption, phone layouts, touch drill/filters, favorites, alerts/notifications, and device testing. |
| G4 | Embedded analytics | P4 | Design user-owns-data and app-owns-data models, secure token issuance, tenant isolation, JavaScript SDK, embedding permissions, licensing, and audit. |
| G5 | Power Platform actions | P4 | Evaluate Power Apps and Power Automate visuals and Fabric translytical task flows as service-dependent action surfaces with permission, writeback, and transactional safety. |
| G6 | Natural language and Copilot | P4 | Track natural-language and Copilot workflows, licensing/capacity, tenant controls, model preparation, privacy, generated artifact review, and product lifecycle. Microsoft’s current pages show Q&A scheduled for retirement, with dates that differ across pages; recheck the authoritative lifecycle notice before planning legacy Q&A. Prefer evaluating its supported successor path over adding a retiring feature. |

## 4. Delivery order and gates

This order keeps a usable local desktop product ahead of service expansion. No calendar estimate is attached until the target scope and engine decisions are approved.

| Phase | Goal | Included work | Exit gate |
|---|---|---|---|
| **0. Establish the parity ledger** | Make “all missing” maintainable. | B1, C1, D2, A3; connector, M, DAX, visual, host, and export catalogs with source/version/status; stale roadmap cleanup. | Every capability has an owner/status, a Microsoft source, an Analytics Studio state, a scope decision, and a testable acceptance statement. |
| **1. Close local product gaps** | Make the local desktop workflows reliable. | Live connector acceptance, auth/connection design, source schema evolution, query diagnostics, accessibility, performance gates, export, report/model failure recovery. | Supported local workflows pass controller, save/reopen/refresh, UI, and documented boundary checks on the supported Mac matrix. |
| **2. Expand Desktop authoring depth** | Move from bounded subsets to a declared compatibility target. | M runtime decision and M coverage; DAX engine decision and DAX coverage; multi-table visual context; model metadata; missing report authoring and formatting. | Versioned M/DAX contracts and differential test suites show where behavior matches and where it does not. |
| **3. Interchange and ecosystem** | Make projects portable and support professional development. | PBIX/PBIT/PBIP decision, TMDL/XMLA/external tools, APIs, custom visuals, Git-friendly projects. | Compatibility claims are verified by round-trip or clearly constrained import/export tests. |
| **4. Hosted Service/Fabric product** | Add multi-user and cloud workflows. | Identity, workspaces, sharing, publishing, dashboards, refresh/gateway, dataflows, Fabric/OneLake, governance, audit, deployment. | Threat model, tenancy model, operational plan, licensing, recovery, and end-to-end security acceptance are complete before release. |
| **5. Separate hosts and advanced experiences** | Expand beyond desktop. | Mobile, paginated reports, Report Server, embedding, Power Platform actions, AI. | Each track has its own supported host matrix, compatibility rules, privacy/security review, and product acceptance plan. |

## 5. Acceptance rules for every roadmap item

1. State which Microsoft host and workflow is being compared; include the official documentation link and review date.
2. State whether the item is required for the local desktop target, a cloud expansion, or a separate product track.
3. Cover the successful workflow and cancel, invalid input, unsupported input, resource limits, and failure recovery.
4. For persisted features, verify create/edit/delete as applicable, save/reopen, source refresh, migration, and dependency impact.
5. For language/runtime features, compare against Microsoft-compatible reference cases and retain an explicit unsupported-case test. A parser round trip alone is not runtime compatibility.
6. For connectors, test real endpoints in addition to mocks, along with authentication, TLS, paging, schema changes, rate limits, refresh, and secret handling.
7. For security, test every route that can expose data, including formulas, visuals, profile/statistics panes, tables, exports, query previews, refresh, and logs.
8. Keep unsupported commands disabled or clearly explained. Never describe a bounded subset as full Power Query, DAX, Power BI, or Fabric compatibility.

## 6. Microsoft reference catalog

These official Microsoft pages are the starting point for the capability ledger. Their host applicability and lifecycle notes must be checked again when a roadmap item is scheduled.

Lifecycle note at this snapshot: Microsoft’s [real-time streaming documentation](https://learn.microsoft.com/en-us/power-bi/connect-data/service-real-time-streaming) says creation of new real-time semantic models remains available until 2027-10-31 and recommends exploring Fabric Real-Time Intelligence. The [visualization overview](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualizations-overview) and Q&A pages currently show differing retirement dates for Q&A; reconcile the lifecycle notice before treating Q&A as a target.

### Power Query and data

- [Power Query connectors and host support](https://learn.microsoft.com/en-us/power-query/connectors/)
- [Get Data experience, connections, credentials, and gateways](https://learn.microsoft.com/en-us/power-query/get-data-experience)
- [Power Query M language specification](https://learn.microsoft.com/en-us/powerquery-m/power-query-m-language-specification) and [M function reference](https://learn.microsoft.com/en-us/powerquery-m/)
- [Query folding examples and diagnostics](https://learn.microsoft.com/en-us/power-query/query-folding-examples)
- [Power Query privacy levels](https://learn.microsoft.com/en-us/power-query/privacy-levels)
- [Dataflows Gen2 overview](https://learn.microsoft.com/en-us/fabric/data-factory/dataflows-gen2-overview)

### Power BI modeling and reports

- [DAX function reference](https://learn.microsoft.com/en-us/dax/dax-function-reference) and [DAX overview](https://learn.microsoft.com/en-us/dax/dax-overview)
- [Semantic model storage modes](https://learn.microsoft.com/en-us/power-bi/connect-data/service-dataset-modes-understand), [composite models](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-composite-models), and [incremental refresh](https://learn.microsoft.com/en-us/power-bi/connect-data/incremental-refresh-overview)
- [Power BI report capabilities](https://learn.microsoft.com/en-us/power-bi/create-reports/power-bi-reports-overview)
- [Visualizations overview and custom visuals](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualizations-overview) and [custom visual development](https://learn.microsoft.com/en-us/power-bi/developer/visuals/develop-power-bi-visuals)
- [Visual interactions](https://learn.microsoft.com/en-us/power-bi/create-reports/service-reports-visual-interactions), [tooltips](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualization-tooltips-overview), and [mobile layouts](https://learn.microsoft.com/en-us/power-bi/create-reports/power-bi-create-mobile-optimized-report-about)

### Service, security, and extensions

- [Power BI Service concepts](https://learn.microsoft.com/en-us/power-bi/fundamentals/service-basic-concepts) and [workspaces](https://learn.microsoft.com/en-us/power-bi/collaborate-share/end-user-workspaces)
- [RLS guidance](https://learn.microsoft.com/en-us/power-bi/guidance/rls-guidance) and [object-level security](https://learn.microsoft.com/en-us/analysis-services/tabular-models/object-level-security)
- [Power BI security overview](https://learn.microsoft.com/en-us/fabric/security/power-bi-security)
- [Power BI projects (PBIP)](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview), [TMDL view](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-tmdl-view), and [deployment pipelines](https://learn.microsoft.com/en-us/power-bi/create-reports/deployment-pipelines-overview)
- [Power BI REST APIs](https://learn.microsoft.com/en-us/rest/api/power-bi/), [mobile apps](https://learn.microsoft.com/en-us/power-bi/consumer/mobile/mobile-apps-for-mobile-devices), [paginated reports](https://learn.microsoft.com/en-us/power-bi/paginated-reports/paginated-reports-report-builder-power-bi), and [Report Server](https://learn.microsoft.com/en-us/power-bi/report-server/get-started)

## 7. Related Analytics Studio roadmaps

- [Whole-product functionality map](../POWER_BI_FUNCTIONALITY_ROADMAP.md)
- [Local implementation roadmap](implementation-roadmap.md)
- [Data import inventory](../DATA_IMPORT_FUNCTIONALITY_INVENTORY.md)
- [Report authoring inventory](../REPORT_AUTHORING_FUNCTIONALITY_INVENTORY.md)
- [DAX compatibility contract](../DAX_COMPATIBILITY_CONTRACT.md)
