# Power BI Functionality Progress

**Status date:** 2026-10-08

**Master roadmap:** [POWER_BI_FUNCTIONALITY_ROADMAP.md](</Users/armaan/Power BI tool/POWER_BI_FUNCTIONALITY_ROADMAP.md>)

**Cumulative completed-work log:** [POWER_BI_FUNCTIONALITY_WORK_LOG.md](POWER_BI_FUNCTIONALITY_WORK_LOG.md)

## Overall status

Analytics Studio has working local data-import, query-shaping, and semantic-model foundations. Work is still in progress: broad report authoring, service collaboration, governance, and platform capabilities remain open. This roadmap describes Power BI-comparable capabilities for Analytics Studio; it does not make the app Microsoft Power BI or provide PBIX compatibility.

The roadmap graph currently has **109 of 137 boxes marked done or implemented**, **5 active**, **17 queued**, and **6 summary/other**. The 78% figure is only the share of graph boxes colored done. It counts summary areas and individual capabilities equally, so it is **not an overall product-completion percentage**.

The clearest functional measure is that **all 50 listed query-management and shaping capabilities have passed lifecycle acceptance**. The automated project suite currently reports **381 passed tests and 229 passed subtests**.

## Progress by area

| Area | Completed or working | Still open |
|---|---|---|
| Local data and import | Bounded preview and commit; CSV, Excel, JSON, XML, Parquet, legacy XLS, folder combine, SQLite, multiple local tables, recent sources, and refresh workflows have lifecycle coverage. Import workers report progress and support cancellation. | Large-file performance timing on the minimum supported M1 Mac is pending. The measured host is an M5 Pro MacBook Pro with 48 GB RAM. SQL Server, OData, and Web need live-server/endpoint acceptance. Additional connectors remain queued. |
| Query management and shaping | **50/50** graph-listed capabilities passed lifecycle acceptance, covering saved query dependencies, append/merge, groups, load and refresh settings, transformation steps, and save/reopen/refresh replay. The `data.transform` QML command route now has offscreen UI acceptance. | This is a bounded local Power Query-style editor, not a general Power Query M engine. |
| Semantic model and DAX | Column types, local measures, calculated columns and tables, date/calendar tables, relationship authoring and propagation, scoped/report filters, Top N, and a growing local DAX subset have lifecycle coverage. | Row-to-filter context transition passed. Time-intelligence filter expressions are complete. Visual-axis behavior for `ALLSELECTED`, broader DAX, and some combined time-intelligence/filter forms remain open. |
| Reports, visuals, and interactions | Basic report-page workflows, selected chart types, and several filter interactions exist; filter/model capabilities are tracked individually in the master graph. | Comprehensive visual authoring, field wells, formatting, visual interactions, and broader analytics are planned. |
| Service, security, and platform | The master roadmap records these as separate product families and tracks the service scope decision. | Collaboration/service workflows and security/governance are queued. Mobile, paginated, and Report Server are separate tracks; developer, embedding, Fabric, and AI capabilities are also separate tracks. |

## Verification recorded for this snapshot

- Full suite: `PYTHONPATH=. pytest -q` — **381 passed, 229 subtests passed**.
- Transform Data UI route: `test_transform_data_qml_command_reaches_dialog_and_commits_step` in [test_home_file_workflows.py](</Users/armaan/Power BI tool/tests/test_home_file_workflows.py>) passed. It checks command availability, committing a transform step, saving/reopening, and replay after a source change.
- Import lifecycle tests: **41 passed, 30 subtests passed** in the focused parser/import run.
- Large-file timings currently recorded for the M5 Pro host: CSV, 10,000,010 bytes and 100,000 rows, median **0.109 s**; XLSX, 2,357,312 bytes and 100,000 rows, median **1.545 s**. The M1 benchmark remains an external hardware gate.

## Next work and outstanding gates

1. Continue with **7.1 Canvas and Visual Lifecycle**, implementing page management and visual instantiation workflows as marked active in the master graph.
2. Run and record the large-file benchmark on an M1 Mac before closing that performance gate.
3. Verify SQL Server, OData, and Web workflows against live services in addition to their mocked lifecycle coverage.
4. Then progress through the planned report authoring, interactions, and remaining product-family tracks shown in the master roadmap.

The color-coded, capability-by-capability state is maintained in the [master roadmap](</Users/armaan/Power BI tool/POWER_BI_FUNCTIONALITY_ROADMAP.md>). Update this snapshot and the [work log](POWER_BI_FUNCTIONALITY_WORK_LOG.md) after each increment.
