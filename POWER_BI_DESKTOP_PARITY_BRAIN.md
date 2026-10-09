# Power BI Desktop Parity — Research Brain

**Status:** Research baseline; the native QML application has local import, query, model, and report workflows. The full workspace suite passes 396 tests and 229 subtests as of 2026-10-09; chart/slicer cross-filter QML cases pass, while broader workflow acceptance, live connectors, hardware benchmarks, and whole-product parity remain pending. Current implementation status is tracked in [POWER_BI_FUNCTIONALITY_PROGRESS.md](POWER_BI_FUNCTIONALITY_PROGRESS.md).
**Research date:** 2026-10-04
**Starting point:** Fresh scratch product. No prior implementation or git history used.
**Product intent:** Build an independent desktop analytics authoring product for macOS and Linux, with whole-product functional parity with Microsoft Power BI Desktop as the long-term north star.
**User-confirmed boundaries:** No web UI/browser/webview application. Prefer a product-owned local project format first, not PBIX round-trip as a prerequisite. Whole-product functionality and 1:1 UI/workflow fidelity remain long-term north-star requirements, not first-release claims. The user selected a PySide6 + Qt Quick/QML frontend with Python project/data logic; the previous Qt Widgets shell is being replaced at the presentation layer.
**Target platform decision (2026-10-05):** First release targets Apple Silicon (M1 or newer), macOS Sonoma 14.4 or later, with checks on Sonoma 14.4, Sequoia 15, and Tahoe 26. Linux follows Mac: Ubuntu 24.04 LTS x86_64 is the first support target; elementary OS is an optional Mac-familiarity check. Linux ARM desktop support is deferred.

---

## 1. Executive conclusion

A clean-scratch, native macOS/Linux implementation is a **new product**, not a port of Microsoft Power BI Desktop. Microsoft's documentation describes Power BI Desktop as a Windows application. Its broad capability set spans data connectivity, Power Query transformations and the M language, semantic modeling and relationships, DAX calculations, report authoring and interactions, file/project formats, external visuals and tools, refresh, and service integration. Each area has substantial behavior of its own.

The project should preserve **whole-product functional parity and 1:1 UI/workflow fidelity as long-range north-star requirements**, but translate them into a capability inventory, explicit compatibility definitions, and staged proof points. These are aspirations to validate over time, not claims that the first release can meet them. Recreate the user-facing layout, interactions, workflows, and documented behavior through an independent implementation; do not copy Microsoft source, assets, trademarks, branding, or undocumented file assumptions. Product visual similarity and any trade-dress or other IP constraints require qualified legal review before distribution.

**Selected Stage 1 direction:** use **Python + PySide6 with Qt Quick/QML** for the native shell and project lifecycle. The separate Qt Widgets comparison remains a disposable spike. Build the next local-first import/report vertical slice on this stack; DuckDB remains a candidate embedded SQL engine, not a replacement for DAX, Power Query M, VertiPaq, or a complete tabular semantic model.

---

## 2. User intent and non-negotiable product boundaries

- **Native desktop:** deliver installable macOS and Linux desktop applications, not a browser app, embedded webview, or cloud-hosted authoring UI. Electron and Tauri are excluded as implementation choices because they rely on embedded web UI approaches and conflict with the native-desktop-only requirement.
- **Power BI Desktop breadth and fidelity:** aim over time for complete user-facing functional parity and 1:1 UI/workflow fidelity, including the recognizable authoring layout, interactions, and task flows. These are long-term goals, not first-release claims. Independently implement the behavior and interface; do not copy Microsoft source, proprietary internals, trademarks, or assets. Seek qualified legal review of visual similarity and any trade-dress or other IP issues before distribution.
- **Local-first authoring:** create, edit, save, reopen, refresh, and render reports locally without requiring a Power BI account or cloud authoring service.
- **No web UI is not necessarily offline-only:** remote database/data-service connectors can remain candidates if accessed from the native application. Desktop-initiated service publishing is an eventual parity target but deferred from early releases; cloud-hosted authoring is excluded from the native standalone core. Service workspaces, hosted report sharing and administration are separate deferred capabilities.
- **Own project format first:** design a documented, versioned local format. Treat PBIX import/export and round-trip fidelity as separate future compatibility research; never assume PBIP/TMDL implies PBIX compatibility.
- **Fresh scratch:** do not inspect/use git history or old product implementations as a starting point. This brain is the product research base.

### Parity is not a single feature

Track parity independently for: (1) UI/workflow, (2) connectors and authentication, (3) transformations/M, (4) model/relationships/storage modes, (5) DAX semantics, (6) visuals and their configuration, (7) filtering/interactions/navigation, (8) project/persistence/interoperability, (9) performance/accessibility/localization, (10) extension ecosystem, and (11) publishing/cloud capabilities. Each needs a defined supported subset and verification corpus.

---

## 3. What Power BI Desktop does: capability map

Microsoft presents the authoring path as connect and prepare data, model it, create visual reports, save locally, and optionally publish to the Power BI service. The service adds sharing, collaboration and cloud administration functions. [Power BI overview](https://learn.microsoft.com/en-us/power-bi/fundamentals/power-bi-overview) · [Desktop getting started](https://learn.microsoft.com/en-us/power-bi/fundamentals/desktop-getting-started)

### A. Data connectivity and import

Desktop uses Power Query to connect to a changing inventory of files, databases, online sources and services. A connector is more than a protocol label: it may require its own navigation experience, authentication, data types, capabilities, driver/native dependencies, query folding behavior, and refresh path. Some connectors are Beta/Preview; availability and functionality vary by host and source. [Desktop data sources](https://learn.microsoft.com/en-us/power-bi/connect-data/desktop-data-sources) · [Power Query connectors](https://learn.microsoft.com/en-us/power-query/connectors/)

**Product consequence:** publish and test connectors one by one. “Supports many data sources” must refer to a named connector matrix and tested auth/refresh capabilities. A no-webview UI still permits a native connector to contact a remote source, if that is supported by product policy.

### B. Power Query and M transformation

Power Query is a repeatable data preparation/transformation engine with a graphical editor. It records query steps, supports operations such as filtering, type conversion, merge, append, group, pivot and unpivot, and generates M. M can also be edited directly. The host determines where results are loaded. Query folding—pushing work back to a source—is dependent on connector, source, and operation; it is not universal. [What is Power Query?](https://learn.microsoft.com/en-us/power-query/power-query-what-is-power-query) · [M language reference](https://learn.microsoft.com/en-us/powerquery-m/) · [Query folding basics](https://learn.microsoft.com/en-us/power-query/query-folding-basics)

**Product consequence:** distinguish a product-owned transformation plan from Power Query/M compatibility. Recreating the GUI for a small subset is not implementing an M evaluator, compatible function library and host behavior, connector catalog, authentication behavior, folding, refresh, and integration.

### C. Semantic model and relationships

The model includes tables, columns, types, measures, calculated objects, and relationships. Relationships have cardinality, active/inactive state, and cross-filter direction; they propagate filters and participate in evaluation. Microsoft recommends star-schema design with dimensions and facts. [Model relationships](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-relationships-understand) · [Star schema guidance](https://learn.microsoft.com/en-us/power-bi/guidance/star-schema)

**Product consequence:** relationships are executable semantics, not merely lines in a diagram. The model/view layer, query evaluator, filters and formula engine must agree on propagation, ambiguity, inactive relationships and model errors.

### D. DAX and model calculations

DAX is a formula language for tabular models. It supports dynamic measures, calculated columns and tables, row-level security expressions, and queries. A measure's output depends on evaluation context, report filters and relationships. [DAX overview](https://learn.microsoft.com/en-us/dax/dax-overview) · [Measures in Power BI Desktop](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-measures)

**Product consequence:** SQL aggregates or a formula editor are not DAX parity. Specify DAX language version/function coverage, types, blanks, context behavior, errors, relationship handling, and security semantics. Any subset must be clearly named and tested against a conformance corpus. Full compatibility is a major independent program.

### E. Report pages, visuals and authoring UX

Reports are interactive, multi-page documents with visuals on a canvas. Desktop authoring includes field bindings, visual selection/formatting, page layout, filters and slicers, themes, bookmarks, buttons/navigation, tooltips, drillthrough, and accessibility support. Visuals can cross-filter or cross-highlight other visuals, with configurable interaction behavior. [Reports overview](https://learn.microsoft.com/en-us/power-bi/create-reports/power-bi-reports-overview) · [Visual interactions](https://learn.microsoft.com/en-us/power-bi/create-reports/service-reports-visual-interactions) · [Performance Analyzer](https://learn.microsoft.com/en-us/power-bi/create-reports/performance-analyzer)

**Product consequence:** define declarative page and visual metadata, interaction/query contracts, a layout/selection system, and core visuals before building a visual plug-in ecosystem. A list of charts alone does not establish behavior or parity.

### F. Local projects and file compatibility

PBIP is a documented folder project format separating report and semantic-model definitions. The current report-project docs describe PBIR as generally available and the default, while PBIR-Legacy remains supported; documentation and support for external edits vary by file. For example, `report.json` and several other project files have undocumented schemas and are unsupported for edits outside Desktop. TMDL model metadata is documented. Microsoft's documentation says PBIX↔PBIP conversion is performed through Power BI Desktop Save As, not programmatically through a documented converter. [PBIP overview](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview) · [Project report folder](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report) · [Project semantic model folder](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-dataset) · [TMDL overview](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview?view=sql-analysis-services-2025)

**Bounded research finding:** I did not find a complete PBIX format specification in the official Microsoft materials reviewed. This does **not** assert that no such material exists anywhere. Our first native project should be our own documented, versioned format with explicit migrations, integrity checks, assets and cache boundaries.

### G. Service/cloud boundary

Desktop can publish reports/models to a Power BI service workspace. The service adds online sharing, workspaces, apps, collaboration, scheduled refresh, alerts, subscriptions, service governance and administration. [Power BI overview](https://learn.microsoft.com/en-us/power-bi/fundamentals/power-bi-overview) · [Power BI service basics](https://learn.microsoft.com/en-us/power-bi/fundamentals/service-basic-concepts) · [Publish from Desktop](https://learn.microsoft.com/en-us/power-bi/create-reports/desktop-upload-desktop-files)

**Product consequence:** treat Desktop-initiated publishing and its required service integration as eventual parity targets, but defer them from early local-first releases. The absence of browser/webview UI does not itself prohibit native service integration. Record publishing, cloud workspaces, shared datasets and service administration as deliberate early-release gaps; preserve the distinction between connecting to remote data sources, using a native UI to publish, and providing cloud-hosted authoring.

---

## 4. Platform and implementation options

### Existing Microsoft product platform

Microsoft describes Power BI Desktop as a **Windows application** and documents Windows-specific requirements. The reviewed documentation does not document native Microsoft Power BI Desktop support on macOS/Linux. This project therefore requires a new implementation. Do not infer from the WebView2 requirement that all of Desktop is a web application. [Power BI Desktop introduction](https://learn.microsoft.com/en-us/power-bi/fundamentals/desktop-getting-started) · [Power BI Desktop requirements](https://learn.microsoft.com/en-us/power-bi/fundamentals/desktop-get-the-desktop)

### UI and language candidates

| Candidate | Strengths for this product | Caveats / decision evidence |
|---|---|---|
| **Python + PySide6 + Qt Widgets (previous shell)** | Python enables rapid product/data-layer experiments (productivity is an engineering inference). Qt Widgets supplies conventional desktop controls, menus, dialogs and data views. Qt documents macOS/Linux support. [Qt Widgets](https://doc.qt.io/qt-6/qtwidgets-index.html) · [Qt platforms](https://doc.qt.io/qt-6/supported-platforms.html) | Standard controls follow desktop styling and do not automatically reproduce a custom analytics ribbon. This shell is being replaced in the current UI migration. Platform support, packaging, and licensing constraints still apply as described below. |
| **Python + PySide6 + Qt Quick/QML (selected)** | QML provides a declarative custom surface for the ribbon, panes, and report canvas while Python retains project and data logic. Qt Quick and PySide expose Python integration. [Qt user interface technologies](https://doc.qt.io/qt-6/topics-ui.html) · [PySide6 Qt Quick](https://doc.qt.io/qtforpython-6/PySide6/QtQuick/index.html) | A custom UI still requires deliberate implementation of controls, keyboard behavior, scaling, and accessibility. It does not automatically produce exact Power BI appearance or behavior. Qt's OS, packaging, and licensing constraints apply. |
| **C++ + Qt Widgets / Qt Quick** | Same Qt platform breadth and mature UI components; allows a direct C++ application/engine path. Consider if performance, native integration, distribution control, or team experience outweigh slower iteration (trade-off partly inference). [Qt Widgets](https://doc.qt.io/qt-6/qtwidgets-index.html) · [Qt platforms](https://doc.qt.io/qt-6/supported-platforms.html) | Higher implementation/build complexity for a Python-first team is an inference. Qt licensing and the specific supported OS/version/distribution/architecture matrix still apply. Qt Quick Controls are suitable for custom declarative UI, but Qt documents ongoing work toward more native desktop look/feel. [Qt Quick Controls](https://doc.qt.io/qt-6/qtquickcontrols-index.html) |
| **C#/.NET + Avalonia** | Credible alternative if team is C#-first or wants its documented MIT license. Avalonia docs describe macOS and Linux desktop targets, with Linux X11/Wayland considerations. [Avalonia platforms](https://docs.avaloniaui.net/docs/supported-platforms) · [MIT license](https://github.com/AvaloniaUI/Avalonia/blob/main/licence.md) | UI toolkit/native-feel, target OS tier, font/rendering, accessibility and packaging need hands-on assessment. OS support does not show Power BI parity. |
| **Rust + Slint** | Candidate for a purpose-built declarative UI with Rust integration and desktop targets. [Slint docs](https://docs.slint.dev/latest/docs/slint/) · [Licensing](https://slint.dev/pricing) | Validate chart/table/accessibility/editor readiness and proprietary licensing terms for intended distribution. Not selected over Qt absent evidence that it meets these specific needs. |
| **Rust + egui/eframe** | Native macOS/Linux targets and MIT OR Apache-2.0 licensing. [egui project](https://github.com/emilk/egui) | egui explicitly describes itself as immediate-mode and does not target native-looking UI; conventional rich authoring panes and accessibility may require bespoke work. [egui project](https://github.com/emilk/egui) |

### Stage 1 implementation choice: Python/PySide6 + Qt Quick/QML

The native shell and project-lifecycle stage uses Python/PySide6 + Qt Quick/QML by user selection. QML owns the custom ribbon and workspace surface; Python retains project lifecycle and local data logic. The current shell migration is not evidence of broad performance, exact visual parity, or packaging readiness. The separate C++ prototype remains a disposable comparison artifact.

The screenshot-guided shell presents File, Home, Insert, Modeling, View, Optimize, and Help tabs; a narrow Report/Data/Model rail; a centered 16:9 report page; and right-side Filters, Visualizations, and Data panes. DAX/TMDL, unsupported connectors, collaboration, and unsupported visuals remain disabled. A macOS launch and visual review caught and fixed a workspace sizing issue; this is a manual shell check, not a test of project reopen/recovery or whole-product parity.

Use Qt 6.12 or later for the selected macOS 14.4 minimum. Before a first release, build and assess the packaged app on the declared macOS matrix, including signing/notarization, startup, data loading, and accessibility basics. Linux packaging remains a later, separately verified target.

The earlier stack spike plan was:

1. Native app window with menus, dockable panes, table preview, file dialogs, keyboard navigation, and a custom canvas placeholder.
2. Load and preview a moderately large CSV and Parquet file; measure startup, memory, and responsiveness on representative macOS and Linux targets.
3. Build signed/notarizable macOS package and Linux package for named supported distributions from clean machines; record binary size, cold start, crash logs, upgrade behavior.
4. Verify accessibility basics, high-DPI, themes, and native file/clipboard interactions.
5. Complete a Qt module/plugin license inventory and select a documented commercial/open-source distribution path with legal review.

Decide from measured delivery, iteration speed, packaging, runtime, UI feel, team skill and license obligations. The spike is research, not committed product architecture.

---

## 5. Data/analytics engine choices

### DuckDB — preferred first engine candidate

DuckDB is an in-process analytical SQL database designed for analytical queries and can be embedded in an application. It is suitable for local ingestion, profiling, query previews and executing SQL-based transformations; the project repository identifies the MIT license. [Why DuckDB](https://duckdb.org/why_duckdb) · [DuckDB repository](https://github.com/duckdb/duckdb)

**Boundary:** these sources establish embedded SQL capabilities, not DAX compatibility, a Power BI tabular semantic model, VertiPaq compatibility, Power Query M execution, or Power BI connector behavior. Treat any substitution claim as unverified until a behavior-specific implementation and conformance suite proves it.

### Polars — optional, not an automatic companion

Polars is a Rust-based DataFrame query engine with Python/Rust interfaces, lazy/eager processing, optimization and streaming options. It may be useful if DataFrame-native workflows or measured transformation performance justify it. [Polars documentation](https://docs.pola.rs/) · [Polars repository](https://github.com/pola-rs/polars)

**Recommendation:** do not ship both DuckDB and Polars by default; avoid two overlapping execution/data paths before profiling identifies a real need.

### Apache Arrow — interoperability, not the whole engine

Arrow defines a language-independent columnar in-memory representation and libraries for data exchange and analytics. It can become useful across C++/Python boundaries or when zero-copy interchange is demonstrated to matter. [Apache Arrow docs](https://arrow.apache.org/docs/)

**Recommendation:** defer a direct Arrow dependency until the language/runtime boundary needs it. Arrow alone is not an SQL database, DAX evaluator, or Power Query implementation.

---

## 6. Proposed staged path to the parity north star

This is a product strategy, not an implementation plan. Do not implement these stages until stack and scope are approved.

### Stage 0 — definition and feasibility gates

- Freeze parity vocabulary and exclusions; make a versioned capability matrix.
- Set macOS minimum versions/architectures and Linux distro/architecture/package baselines.
- Run Python/PySide6-vs-C++/Qt UI and packaging spike.
- Decide Qt license route and legal review; test distribution on clean machines.
- Define performance, dataset-size, startup and resource baselines.

**Exit evidence:** runnable native package on the declared platform matrix, measured spike report, signed-off product boundaries and engine architecture decision.

### Stage 1 — native shell and project lifecycle

- Native menus, file dialogs, panels, keyboard navigation, logging and diagnostics.
- New/open/save/reopen project; documented versioned project manifest; migrations and safe recovery.
- Local file import, schema inspection, preview, profiling and refresh.
- Keep UI and project format independent of any future PBIX interoperability.

**Exit evidence:** project survives close/reopen; malformed files have recoverable errors; cross-platform shell flows pass on declared targets.

### Stage 2 — transformation and report vertical slice

- Small named set of local-file connectors and operations; repeatable steps; preview and refresh behavior.
- Initial local query execution candidate (DuckDB) behind a replaceable data access boundary.
- Paged report canvas with a small common visual set, formatting, field bindings, basic filters/slicers, save/reopen and export.
- Make no Power Query/M or broad connector parity claim.

**Exit evidence:** end-to-end sample projects with known outputs and interaction tests on macOS/Linux.

### Stage 3 — semantic model and declared expression subset

- Model tables, metadata, relationships, filter propagation, explicit measures and calculation evaluation.
- Publish a named/versioned DAX subset or product expression language, and explicitly surface unsupported syntax/functions.
- Validate against golden fixtures for types, blanks, filters, relationships and context.

**Exit evidence:** semantic test corpus, deterministic results, unsupported behavior documented, query inspection/performance diagnostics.

### Stage 4 — broad compatibility programs

Only after prior stages are stable, consider separate programs for M evaluation and function/host compatibility, connectors/query folding; broader DAX/time-intelligence/RLS; richer visuals and custom extension API; advanced model/storage modes; PBIP/TMDL/PBIX compatibility; and Desktop-initiated publishing/service integration. Publishing is an eventual parity target but is explicitly deferred from early local-first releases. Each program gets its own compatibility contract, licensing/security review, and conformance fixtures.

**Exit evidence:** compatibility matrix published with pass rates and known gaps; do not claim parity by feature count alone.

---

## 7. Important risks, open questions, and guardrails

### Feasibility risks

- Whole-product parity is a very large product effort by inference: broad semantics, connectors, visual ecosystem, polished authoring UI, platform packaging and compatibility maintenance are independent workstreams. No staffing, budget, or schedule was provided, so this research cannot make an economic commitment or promise delivery time.
- Microsoft releases Power BI Desktop monthly and supports only the latest version, so tracking changes would be ongoing compatibility work rather than a one-time copy. The target operating-system lifecycle is a separate platform planning input. [Desktop installation and updates](https://learn.microsoft.com/en-us/power-bi/fundamentals/desktop-get-the-desktop)
- “macOS/Linux” needs concrete OS, CPU, package, signing and support definitions. Qt officially supports listed configurations; arbitrary Linux distribution/hardware behavior cannot be assumed. [Qt platforms](https://doc.qt.io/qt-6/supported-platforms.html)
- A native visual extension ecosystem is not automatically compatible with Power BI custom visuals. Third-party runtime, security sandbox, rendering and package compatibility must be designed separately. [Power BI custom visuals](https://learn.microsoft.com/en-us/power-bi/developer/visuals/power-bi-custom-visuals)
- Omitting service publishing/workspaces/cloud refresh intentionally sacrifices some recognizable Desktop ecosystem workflows. [Power BI overview](https://learn.microsoft.com/en-us/power-bi/fundamentals/power-bi-overview)

### Intellectual property guardrail

Implement the intended UI/workflow fidelity independently in original code. Do not reuse Microsoft source, names, icons, visual assets, or branding; treat public documentation as evidence of behavior, not permission to use proprietary assets. The 1:1 visual-fidelity goal may raise trade-dress or other IP questions distinct from copying code or assets; obtain qualified legal review before distribution. Compatibility references should be accurate and avoid implying Microsoft affiliation or endorsement.

### Decisions still required before a build plan

1. **Parity contract:** which capabilities are acceptance-critical at each release; how to define “equivalent” objectively?
2. **Platform matrix:** the first-release OS and CPU targets are selected above. Packaging, update strategy, Linux display systems (X11/Wayland), and future architecture expansion still need release decisions.
3. **Network policy:** user clarified no web UI. Which remote database and web-service data sources may the native app connect to? Any credentials/cloud accounts prohibited?
4. **First vertical slice:** CSV/Parquet/Excel/SQL? Which two workflows must be end-to-end first?
5. **Engine spike acceptance:** sample dataset size, startup/memory limits, responsiveness, package size and minimum hardware?
6. **Licensing/distribution:** Qt Community obligations vs commercial license, product source distribution, plugins/modules, notarization/signing, Linux packaging and support costs?
7. **Compatibility:** whether to explore PBIP/TMDL read/import later, in addition to the stated own-format-first decision; PBIX is not a first-stage promise.
8. **Security and privacy:** OS credential store, local cache encryption, imported-file handling, plugin trust/sandbox, telemetry/offline controls?
9. **Localization/accessibility:** supported languages, keyboard/screen-reader targets and conformance criteria?
10. **Resources:** team experience, staffing, budget and a definition of sufficient parity for a usable first release?

---

## 8. Research source index

### Microsoft product and semantics

- [Power BI overview: Desktop vs service](https://learn.microsoft.com/en-us/power-bi/fundamentals/power-bi-overview)
- [Power BI Desktop getting started](https://learn.microsoft.com/en-us/power-bi/fundamentals/desktop-getting-started)
- [Power BI Desktop requirements and updates](https://learn.microsoft.com/en-us/power-bi/fundamentals/desktop-get-the-desktop)
- [Desktop data sources](https://learn.microsoft.com/en-us/power-bi/connect-data/desktop-data-sources)
- [Power Query overview](https://learn.microsoft.com/en-us/power-query/power-query-what-is-power-query)
- [Power Query M language reference](https://learn.microsoft.com/en-us/powerquery-m/)
- [Query folding](https://learn.microsoft.com/en-us/power-query/query-folding-basics)
- [DAX overview](https://learn.microsoft.com/en-us/dax/dax-overview)
- [Relationships](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-relationships-understand)
- [Star schema guidance](https://learn.microsoft.com/en-us/power-bi/guidance/star-schema)
- [Report overview](https://learn.microsoft.com/en-us/power-bi/create-reports/power-bi-reports-overview)
- [Visual interactions](https://learn.microsoft.com/en-us/power-bi/create-reports/service-reports-visual-interactions)
- [Performance Analyzer](https://learn.microsoft.com/en-us/power-bi/create-reports/performance-analyzer)
- [PBIP](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview)
- [PBIP report folder](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report)
- [PBIP semantic model folder](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-dataset)
- [TMDL](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview?view=sql-analysis-services-2025)
- [Power BI service basics](https://learn.microsoft.com/en-us/power-bi/fundamentals/service-basic-concepts)
- [Publishing from Desktop](https://learn.microsoft.com/en-us/power-bi/create-reports/desktop-upload-desktop-files)
- [Power BI custom visuals](https://learn.microsoft.com/en-us/power-bi/developer/visuals/power-bi-custom-visuals)

### Native UI, engines and licensing

- [Qt Widgets](https://doc.qt.io/qt-6/qtwidgets-index.html)
- [Qt Quick Controls](https://doc.qt.io/qt-6/qtquickcontrols-index.html)
- [Qt supported platforms](https://doc.qt.io/qt-6/supported-platforms.html)
- [Qt for Python `pyside6-deploy`](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html)
- [Qt for Python commercial/community editions](https://doc.qt.io/qtforpython-6/commercial/index.html)
- [Qt LGPL/GPL obligations](https://www.qt.io/development/open-source-lgpl-obligations)
- [Qt for Python third-party licenses](https://doc.qt.io/qtforpython-6/licenses.html)
- [DuckDB architecture](https://duckdb.org/why_duckdb)
- [DuckDB license and project](https://github.com/duckdb/duckdb)
- [Polars docs](https://docs.pola.rs/)
- [Apache Arrow docs](https://arrow.apache.org/docs/)
- [Avalonia platforms](https://docs.avaloniaui.net/docs/supported-platforms)
- [Avalonia license](https://github.com/AvaloniaUI/Avalonia/blob/main/licence.md)
- [Slint docs](https://docs.slint.dev/latest/docs/slint/)
- [Slint license options](https://slint.dev/pricing)
- [egui/eframe](https://github.com/emilk/egui)

---

## 9. Evidence labels and reading rule

- **Documented fact** means the cited source states the behavior/platform/license point.
- **Recommendation** means a proposed architecture choice, not a Microsoft or framework guarantee.
- **Inference** means a reasoned engineering judgment that must be tested.
- **Bounded unknown** means not established in sources reviewed; it is not proof that no implementation or document exists.

Use this brain file as a research baseline, not as proof of compatibility. The shell and lifecycle stage is now authorized; define the remaining capability matrix and turn each claimed feature into reproducible acceptance checks before release.
