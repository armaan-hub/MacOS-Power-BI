# Analytics Studio project progress summary

**Status date:** 2026-10-26  
**Project status:** In progress; the Power BI parity goal is currently paused.  
**Latest verified full test run:** 998 tests and 738 subtests passed in Iteration 62. This run predates the unfinished Iteration 63 edits described below.

**Latest status (2026-10-26, after Iteration 91, Task 3 xnpv-1).** Task 3 (the DAX function `XNPV`) is built by Antigravity, reviewed and fixed by Claude, locked and merged. Full gate: pytest 1,926 passed (6,281 subtests), real app 575/575, 47,054 saved Power BI answers replayed with 0 differ and 0 crash, 45,998 locked. Claude asked live Power BI about 258 more XNPV shapes (new battery `dax_battery_xnpv2`: 221 match, 37 refused and pending) and fixed five wrong answers in the first build: Currency values (Power BI returns 4 decimals), dates after 9999-12-31 (Power BI answers erratically), a NaN date (crash), text-typed values that are blank in every row, and compile-time XNPV errors inside an unused IF/SWITCH/IFERROR/COALESCE argument (IFERROR and COALESCE now check their unused arguments too). The pending list is 1,036 items (the work list for Tasks 4 to 8). Next: Task 4 `scalar-misc-2` (Antigravity). Parked: `XIRR`, week time-intelligence functions, visual calculations, `INFO.*`.

**Earlier status (2026-10-26, after Iteration 90, Task 2 var-scoping-1).** Task 2 (nested VAR blocks, VAR block after an operator, table VAR inside COUNTROWS, bare CR ends a line comment, VAR in a CALCULATE filter) is built by Antigravity, reviewed and fixed by Claude, locked and merged. Full gate: pytest 1,922 passed, real app 575/575, 46,796 saved Power BI answers replayed with 0 differ and 0 crash, 45,684 locked. A new battery `dax_battery_var_scoping` (90 live answers, 70 match) was added; the 20 shapes the app still refuses (VAR after a comparison or `&`, table VAR in SUMX/FILTER/DISTINCT, VAR filters holding text, dates or computed values) are on the pending list (1,092 items, the work list for Tasks 3 to 8). Next: Task 3 `xnpv-1` (Antigravity). Parked: `XIRR`, week time-intelligence functions, visual calculations, `INFO.*`.

**Earlier status (2026-10-26, after Iteration 89 research).** The DAX engine work is at Iteration 88/89 (the notes below stop earlier). Parity gate on `antigravity/scalar-gaps-1`: pytest 1,919 passed, real app 575/575, saved Power BI answers 45,516 replayed with 0 differ and 0 crash, 45,426 locked (45,607 after the Task 1 lock and the new batteries). A read-only study of the live Power BI Desktop 2.157.879.0 found 470 DAX functions, 137 of which the app does not yet recognise (72 are `INFO.*`). Six new batteries (XNPV, small scalar functions, type tests, TOCSV/TOJSON, LINEST, table functions) were saved: the replay now covers 46,706 answers with 0 differ, 0 crash, and 1,079 pending items that form the work list. Work is split between two agents (Antigravity writes feature code, Claude plans/tests/fixes); plans for Tasks 2 to 8 are in `docs/plans/` and the board is `HANDOFF.md`. Parked: `XIRR` (Power BI's solver stops early, algorithm research needed), week time-intelligence functions (need calendar model objects), visual calculations, `INFO.*`.

## Project objective

Analytics Studio is a new desktop analytics application that recreates selected Power BI Desktop workflows. It is an independent application, not Microsoft Power BI, and it does not read or write PBIX files. The current app uses Python with PySide6 and QML. It has local implementations for data import, Power Query-style shaping, a semantic model, a bounded DAX evaluator, and report visuals.

The goal has been to make the important workflows behave like Power BI where evidence supports it, while documenting where the local implementation is still a subset. Full Power BI parity is not complete, and there is no reliable overall completion percentage.

## How the work has been done

1. **Inspect the existing app and record the gaps.** We reviewed the project, the user's screenshots, current UI behavior, and the feature roadmap. The concerns raised include import opening the main workspace too soon, incomplete Power Query and Model experiences, DAX suggestions/help, chart resizing, incorrect calculated values, and missing or confusing filters.
2. **Use REA and Power BI runtime evidence.** The reference environment is Windows Power BI Desktop running in a Parallels VM. REA has been used for static/runtime inspection and screenshots where available. Read-only ADOMD queries have supplied stronger model-level evidence when native UI capture was unavailable. The user's Power BI project was kept unchanged during the recorded read-only comparisons.
3. **Turn observations into scoped iterations.** The council workflow has recorded a Think → Plan → Create → Review → Verify cycle with plans, critiques, test results, and sign-offs in `.council/`. Each iteration targets a narrow behavior rather than claiming broad parity from a single screenshot.
4. **Verify the local implementation.** Work has used focused lifecycle tests, offscreen Qt/QML interaction tests, full pytest runs, `compileall`, targeted Ruff checks, and `git diff --check`. Automated tests prove the covered local behavior; they do not establish general Power BI compatibility.
5. **Keep evidence and limits visible.** The roadmap and work log record what passed and what remains unknown. A recent `.gitignore` change hides newly generated `.council/` artifacts from ordinary Git status; already tracked council files remain tracked.

## What is implemented and tested

### Data import and preview

- Local CSV, Excel, JSON, XML, Parquet, legacy XLS, folder combine, SQLite, and multiple-table workflows have import, refresh, and persistence coverage.
- SQL Server, OData, and Web import paths exist, with mocked lifecycle coverage; live endpoint acceptance is still pending.
- Import preview, source settings, asynchronous parsing, cancellation/progress, recent sources, refresh, and save/reopen workflows are implemented in bounded local forms.
- Excel now distinguishes automatic Load behavior from an explicit raw/row-based Transform start. The VAT workbook path preserves worksheet row positions and can replay the cleanup to 573 rows by 14 columns.
- Iteration 62 fixed OOXML `_xHHHH_` escape decoding in shared, inline, and cached Excel strings, including escaped literal tokens.

### Power Query-style workflows

- Transform Data is a separate editor with Home, Transform, Add Column, View, Tools, and Help tabs, a query navigator, previews, Applied Steps, and a bounded Advanced Editor bridge.
- The local engine has 46 listed transformation operation IDs with a round-trip test matrix. Covered operations include filtering, type conversion, sorting, splitting/merging, grouping, pivot/unpivot, duplicate handling, row cleanup, transpose, custom columns, and conditional columns.
- Saved query Reference, Append, Merge, Duplicate, Delete, groups, load/refresh settings, parameters, and simple query functions have lifecycle coverage.
- The progress record reports 51 of 51 listed local query-management workflows passing their defined lifecycle checks.
- The editor does not run Microsoft's Mashup engine. General M functions, query folding, privacy levels, broad parameter support, and full M semantics remain open.

### Model and DAX

- The app supports multiple local tables, relationships, model column types, calculated columns/tables, date tables, measure authoring, and saved model metadata.
- DAX support is a local subset. The evaluator recognizes 57 function names, but all have partial semantics. Tested examples include aggregates, `CALCULATE` filters/modifiers, date calculations, selected iterators, `COALESCE`, `RELATED` in a bounded relationship case, and distinct counts.
- Measure authoring has supported-function templates, limited syntax guidance, and suggestions for loaded fields and saved measures. It is not the full Microsoft DAX editor or function catalog.
- Some model/report filters and cross-filter interactions are implemented, but the app does not provide full Power BI filter semantics or every filter surface.

### Reports and visuals

- The report view supports a range of local visuals, including bar/column/line/area charts, stacked and 100% stacked charts, scatter, pie/donut, funnel, waterfall, ribbon, treemap, matrix, table, card, gauge, KPI, map, and slicer.
- Text boxes, local images, shapes, themes, visual formatting, selection/copy/paste, grouping, z-order, and button URL actions have varying lifecycle or offscreen UI coverage.
- Chart resize behavior has had local fixes and pointer tests across report zoom levels, including minimum-size and save/reopen checks. That verifies the implemented local behavior; it does not establish live Power BI parity on the user's display.

### Interface workflow

- New reports start blank. The Data Home ribbon exposes import, Transform Data, refresh, and calculation actions. Model view supports relationship work and measure management. Report, Data, and Model views are present.
- Power BI-style ribbon layouts and several reference screenshots guided the design. The app remains an independent interface rather than a pixel-perfect clone.

## Power BI comparison findings

The strongest recent comparison used the same VAT workbook and the running Windows Power BI Desktop **2.157.879.0** model. The Power BI table was queried read-only through ADOMD.

- Both sides contain **573 rows × 14 columns**, with matching ordered headers and a unique one-to-one `Voucher No` row key.
- The five numeric columns `Value`, `Gross Total`, `Sales`, `VAT-5%`, and `Discount` match within `1e-6`.
- Strict text comparison still finds 12 differing cells: 8 in `Particulars`, 3 in `Address`, and 1 in `Emirates`. The `Particulars` differences compare equal after trimming whitespace; the other four compare equal after case-folding. Analytics Studio preserves the source spellings; no global normalization was applied.
- The local query preview has 32 `DataFormat.Error` values in `TRN`, while the loaded Power BI model shows blanks for the matching records. Iteration 63 was planned to preserve errors in Power Query while presenting blanks to model/DAX/report consumers.
- Earlier source replay established cleanup counts of 623 → 585 → 574 → 573 and matching displayed totals for the supplied workbook. These checks cover the observed workbook and transformations, not all Excel or Power Query behavior.

Full cell-by-cell equality, general DAX/Tabular semantics, full Mashup execution, and live parity for charts, filters, and model interactions have not been established.

## Verification history and current state

- The latest signed-off verification is Iteration 62: **998 tests plus 738 subtests passed**, with compile, targeted Ruff, and diff checks passing. The sign-off applies to the Excel escape-decoding fix and the documented comparison scope.
- Iteration 63's objective and plan are documented: separate error-bearing query outputs from model-facing candidates, then cover project open, import, query-session Apply, dependency rebuild, refresh, save/reopen, and error operations.
- An implementation attempt began during the last session: a projection helper and one regression test were added, and controller cache paths were partly changed. **The Iteration 63 refactor was interrupted before all call sites were updated and no tests were run after those edits. Treat that code as incomplete and unverified.** The previous Iteration 62 green test result does not validate the current worktree.
- The overall workspace contains substantial uncommitted changes. No claim is made that all current workspace changes belong to one clean, reviewed commit.
- Native REA UI capture has been unreliable: accessibility bounds sometimes match multiple Parallels windows, and an A/V capture attempt failed. The latest display check did not detect the iPad Sidecar output, so the requested side-by-side visual verification is still pending. Read-only ADOMD comparison remains useful for model values, but cannot substitute for visual interaction testing.

## Main work still outstanding

1. Finish or safely unwind the partial Iteration 63 cache split. Preserve Power Query errors, project blanks to model consumers, and test downstream Reference/Append/Merge, Remove Errors/Replace Errors, refresh, Apply, save, and reopen.
2. Re-run focused and full test suites after the cache work is complete. The 998/738 result is the last verified baseline, not a result for current uncommitted code.
3. Resume the live comparison when the Sidecar display is available and REA can identify the relevant windows reliably. Compare the same view, table, visual, and filter context on both apps.
4. Resolve the user's reported calculation mismatch from the exact DAX expression and filter context. Existing DAX tests cover a subset and do not identify that specific discrepancy.
5. Continue the reported UX parity checks: resize a chart in the live interface, inspect DAX help/suggestions, and compare Power Query, Data, Model, and Report filter behavior.
6. Address broader product gaps recorded in the roadmap: full DAX and Mashup engines, more connectors and live-server acceptance, advanced model/report authoring, service/security features, and performance checks on the minimum supported hardware.

## Source records

- [Power BI functionality progress](POWER_BI_FUNCTIONALITY_PROGRESS.md)
- [Power BI functionality roadmap](POWER_BI_FUNCTIONALITY_ROADMAP.md)
- [Power BI functionality work log](POWER_BI_FUNCTIONALITY_WORK_LOG.md)
- [REA Power BI Desktop comparison notes](docs/rea-power-bi-desktop-2.157.879.0.md)
- [Iteration 62 verification sign-off](.council/VERIFICATION_SIGN_OFF_ITER62.md)
- [Iteration 63 thought report](.council/THOUGHT_REPORT_ITER63.md)
- [Iteration 63 execution plan](.council/TASK_EXECUTION_PLAN_ITER63.md)
