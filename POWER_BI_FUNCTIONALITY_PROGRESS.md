# Power BI Functionality Progress

**Status date:** 2026-10-09

**Master roadmap:** [POWER_BI_FUNCTIONALITY_ROADMAP.md](</Users/armaan/Power BI tool/POWER_BI_FUNCTIONALITY_ROADMAP.md>)

**Cumulative completed-work log:** [POWER_BI_FUNCTIONALITY_WORK_LOG.md](POWER_BI_FUNCTIONALITY_WORK_LOG.md)

## Overall status

Analytics Studio has working local data-import, query-shaping, and semantic-model foundations. Work is still in progress: broad report authoring, service collaboration, governance, and platform capabilities remain open. This roadmap describes Power BI-comparable capabilities for Analytics Studio; it does not make the app Microsoft Power BI or provide PBIX compatibility.

The roadmap graph mixes summary stages with individual capabilities, and its previous aggregate counts and 78% figure were stale. They are withdrawn: a graph-box ratio is not a useful measure of whole-product parity. Use the tested scopes and open acceptance gates below.

The clearest completed scope is that **all 50 listed query-management and shaping capabilities have passed lifecycle acceptance**. The current workspace test suite reports **396 passed tests and 229 passed subtests**; this confirms implemented local behavior, not Power BI-wide parity.

## Progress by area

| Area | Completed or working | Still open |
|---|---|---|
| Local data and import | Bounded preview and commit; CSV, Excel, JSON, XML, Parquet, legacy XLS, folder combine, SQLite, multiple local tables, recent sources, and refresh workflows have lifecycle coverage. Import workers report progress and support cancellation. | Large-file performance timing on the minimum supported M1 Mac is pending. The measured host is an M5 Pro MacBook Pro with 48 GB RAM. SQL Server, OData, and Web need live-server/endpoint acceptance. Additional connectors remain queued. |
| Query management and shaping | **50/50** graph-listed capabilities passed lifecycle acceptance, covering saved query dependencies, append/merge, groups, load and refresh settings, transformation steps, and save/reopen/refresh replay. The `data.transform` QML command route now has offscreen UI acceptance. | This is a bounded local Power Query-style editor, not a general Power Query M engine. |
| Semantic model and DAX | Multiple local tables, relationships, scoped filters, calculations, date tables, and bounded DAX functions have lifecycle tests. A simple measure reference inside an iterator passes a row-context transition case; several time-intelligence forms pass bounded acceptance. | This is a local DAX subset. Broader language compatibility, visual-axis `ALLSELECTED`, combined filter/time-intelligence cases, model diagrams, and advanced properties remain open. |
| Reports, visuals, and interactions | Page and visual basics, selected chart types, field wells, and filter controls exist. Offscreen QML tests verify chart and slicer clicks update peer charts, selections can be cleared after relationship errors, page/project transitions clear transient selections, and saved page filters remain applied. Repeated series reads reuse filter context within a report refresh. | Broad visual authoring and formatting still need capability-by-capability acceptance. Cross-highlighting, configurable interactions, and large-report performance benchmarks remain open. |
| Service, security, and platform | Local authoring is the current implementation focus. | RLS/OLS, role authoring and previews, service publishing/collaboration, mobile and paginated reports, Report Server, embedding, and Q&A/Copilot are unavailable. Their ribbon actions are disabled; no security or cloud integration is claimed. |

## Verification recorded for this snapshot

- Full suite: `PYTHONPATH=. pytest -q` — **396 passed, 229 subtests passed**.
- Report interactions: `PYTHONPATH=. pytest -q tests/test_report_interactions.py` — **14 passed**; includes offscreen QML chart/slicer selection, peer updates, recovery from relationship errors, page/project transition cleanup, and context-cache checks.
- Report interaction/security audit: [test_report_interactions.py](</Users/armaan/Power BI tool/tests/test_report_interactions.py>) and [test_rls_security.py](</Users/armaan/Power BI tool/tests/test_rls_security.py>) cover real loaded-table rows, page filters, chart field-well values, transient selection state, and the explicit absence of role enforcement. [test_home_file_workflows.py](</Users/armaan/Power BI tool/tests/test_home_file_workflows.py>) checks that role, publish, mobile, and Q&A commands are unavailable.
- Transform Data UI route: `test_transform_data_qml_command_reaches_dialog_and_commits_step` in [test_home_file_workflows.py](</Users/armaan/Power BI tool/tests/test_home_file_workflows.py>) passed. It checks command availability, committing a transform step, saving/reopening, and replay after a source change.
- Import lifecycle tests: **41 passed, 30 subtests passed** in the focused parser/import run.
- Large-file timings currently recorded for the M5 Pro host: CSV, 10,000,010 bytes and 100,000 rows, median **0.109 s**; XLSX, 2,357,312 bytes and 100,000 rows, median **1.545 s**. The M1 benchmark remains an external hardware gate.

## Next work and outstanding gates

1. Expand report acceptance by capability: finish field-well and visual data-binding workflows, then implement cross-highlighting and configurable visual interactions.
2. Keep RLS/OLS and service publishing unavailable until there is a complete design and enforcement path; RLS must cover DAX, visuals, profiles, tables, exports, refresh, and project lifecycle before it can be enabled.
3. Run and record the large-file benchmark on an M1 Mac, and verify SQL Server, OData, and Web workflows against live services in addition to mocked lifecycle coverage.
4. Continue the local DAX and report-authoring compatibility programs. The roadmap's low-confidence estimate remains roughly **two years or more for one developer** to reach a broad local-authoring and cloud-service foundation; mobile, paginated, full DAX/M, connector breadth, and other extension tracks are open-ended and not included in that estimate.

The color-coded, capability-by-capability state is maintained in the [master roadmap](</Users/armaan/Power BI tool/POWER_BI_FUNCTIONALITY_ROADMAP.md>). Update this snapshot and the [work log](POWER_BI_FUNCTIONALITY_WORK_LOG.md) after each increment.
