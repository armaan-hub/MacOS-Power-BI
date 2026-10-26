# Project structure and work status

Status reviewed: 2026-10-21. This is a map of the Analytics Studio workspace and the next work recorded in the project status notes. It is not a new verification run.

## Workspace tree

```text
Power BI tool/
├── analytics_studio/                 Python desktop app (PySide6 + QML)
│   ├── qml/                           Report, Data, Model, and import/query UI
│   │   └── icons/                     UI icons
│   ├── controller.py                  App commands and UI coordination
│   ├── project.py                     Project state, persistence, migration
│   ├── file_import.py                 Local file parsing and import
│   ├── folder_import*.py              Folder import and combine
│   ├── web_import*.py                 Web source workflow
│   ├── odata*.py                      OData source workflow
│   ├── sql_server*.py                 SQL Server source workflow
│   ├── transformations.py             Local table shaping operations
│   ├── power_query_*.py               M subset, values, and editor support
│   ├── query_*.py                     Query evaluation, functions, and state
│   ├── measures.py                    Bounded local DAX evaluation
│   ├── relationships.py               Semantic model relationships
│   └── calendar_tables.py, date_tables.py, ...
├── tests/                             132 Python test modules and fixtures
├── docs/
│   ├── adr/                           Architecture decisions
│   ├── screenshots/                   UI reference captures
│   ├── superpowers/                   Plans and implementation notes
│   ├── verification-artifacts/        Saved verification evidence
│   ├── rea-power-bi-desktop-*.md      Power BI/REA comparison notes
│   └── *.md                           Data source, format, and roadmap docs
├── .council/                          Iteration plans, reviews, results, sign-offs
├── spikes/                            C++ and PySide technology experiments
├── rea/                               Separate REA tooling repository
├── gridcraft/                         Separate Rust spreadsheet repository
├── README.md
├── PROJECT_PROGRESS_SUMMARY.md        Detailed cumulative status and limitations
├── POWER_BI_FUNCTIONALITY_ROADMAP.md  Capability-by-capability roadmap
├── POWER_BI_FUNCTIONALITY_PROGRESS.md Progress snapshot
├── POWER_BI_FUNCTIONALITY_WORK_LOG.md Iteration history
├── DAX_COMPATIBILITY_CONTRACT.md      Supported DAX subset and boundaries
├── pytest.ini
└── requirements.txt
```

`rea/` and `gridcraft/` are nested Git repositories, not Analytics Studio packages. `gridcraft/` currently has local edits in `Cargo.toml`, `Cargo.lock`, `xtask/src/layers.rs`, and a new `crates/m/` directory; those files were left untouched. `.council/` is ignored for new files by the root `.gitignore`, but its existing evidence is retained.

## Work completed to date

- Built an independent Python, PySide6, and QML desktop analytics app with import, transform, model, and report workspaces.
- Implemented local import workflows for CSV, Excel, JSON, XML, Parquet, legacy XLS, folders, and SQLite. SQL Server, OData, and Web workflows have mocked lifecycle coverage; live service acceptance remains open.
- Added a separate Transform Data workflow and a bounded local Power Query/M implementation. The project records 46 listed transformation operation IDs and 51 of 51 listed local query-management lifecycle checks passing.
- Added a semantic model with multiple tables, relationships, column types, calculated objects, date tables, and a partial local DAX evaluator. The function picker recognizes 57 names; this is not full DAX compatibility.
- Added report visuals, formatting, slicers, and some filtering and cross-highlighting behavior, with lifecycle and offscreen UI tests for covered flows.
- Compared the VAT workbook with Windows Power BI Desktop 2.157.879.0 through read-only model queries. Both produced 573 rows by 14 columns; the five checked numeric columns matched within `1e-6`. Twelve strict text cell differences and 32 `TRN` error-versus-blank differences remain documented.
- Used REA and recorded its limits: reliable native Power BI UI capture was blocked by ambiguous Parallels window bounds and capture/provider failures. Read-only ADOMD evidence supports model comparisons but does not replace interactive UI comparison.

## Work still needed

### First: restore a verified baseline

1. Finish or safely unwind the incomplete Iteration 63 cache split. Power Query previews should retain source errors while model, DAX, and report consumers see the intended blank values.
2. Cover that behavior across import, query Apply, Reference/Append/Merge dependencies, Remove Errors/Replace Errors, refresh, save, and reopen.
3. Run the focused and full test suites after the implementation is complete. The last recorded full run was **998 tests plus 738 subtests in Iteration 62**; it predates the current unverified edits.

### Then: resolve the reported behavior gaps

4. Reproduce the incorrect calculation with its exact DAX expression, selected rows, filters, and expected Power BI value; add a regression case and compare both engines.
5. Compare the live Transform, Data, Model, and Report workflows side by side with Windows Power BI using REA when the Power BI window can be identified reliably. Check filter discovery and behavior, DAX function help/suggestions, and chart resize handles and persistence.
6. Expand the documented Power Query/M and DAX subsets only against reproducible Power BI evidence. The local engines do not provide general Mashup or Tabular semantics.
7. Record live acceptance for SQL Server, OData, and Web sources, and run the large-file benchmark on the M1 hardware target.
8. Keep broader Power BI parity open: advanced model/report authoring, full filter semantics, service/security features, connector breadth, and full M/DAX compatibility are not complete.

## Cleanup performed

Removed root-level one-off patch/debug scripts and patch fragments, the extracted `Main.qml.head` fragment, obsolete measure snapshots, Finder `.DS_Store` metadata in the main project, and regenerable Python/test caches. Kept application source, tests, status/evidence documents, project data, experiment directories, `.council/` iteration evidence, and the nested repositories.

## Status references

- [Detailed project progress summary](PROJECT_PROGRESS_SUMMARY.md)
- [Functionality roadmap](POWER_BI_FUNCTIONALITY_ROADMAP.md)
- [Functionality progress](POWER_BI_FUNCTIONALITY_PROGRESS.md)
- [Cumulative work log](POWER_BI_FUNCTIONALITY_WORK_LOG.md)
- [DAX compatibility contract](DAX_COMPATIBILITY_CONTRACT.md)
- [REA and Power BI comparison notes](docs/rea-power-bi-desktop-2.157.879.0.md)
