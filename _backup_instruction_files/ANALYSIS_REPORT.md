# Council Analysis — Iteration 25

## Result

This iteration replaces broad “the suite is green” claims with a capability-to-evidence matrix and closes the locally reproducible gaps found by the final review. The final suite is **778 passed, 616 subtests passed**, up from the Iteration 24 record of 744 tests and 503 subtests. Compilation, whitespace, and targeted lint checks passed.

The cumulative experiment log contains **26 KEEP entries and 0 DISCARD entries** (100% keep rate). Iteration 25's measured additions are 34 tests and 113 subtests versus the prior recorded suite count.

## What worked

- Reviews repeatedly surfaced test evidence that was split across layers. Adding real QTest and controller paths exposed and fixed a DAX function picker completion defect and proved relationship-to-model-view-to-measure refresh behavior.
- A native Power Query render found a dark-palette issue that offscreen layout checks could not detect. The editor now sets light pane/header surfaces, has a regression test, and retains a screenshot artifact for inspection.
- Connector tests now distinguish protocol/adapter limits from UI routing and downstream use. The Web source-picker route reaches a typed model table and measure; its separate lifecycle case proves save/reopen/refresh.
- Workbook evidence is clearly marked manual and tied to a local temporary-copy run, not treated as a stable automated fixture.

## Remaining constraints

- The app does not embed Microsoft's full Mashup/M or DAX/Tabular runtimes. The 54-entry DAX catalog consists of 50 evaluator functions plus four parser/editor forms; references do not prove complete semantics.
- Live SQL Server acceptance needs a Microsoft ODBC driver, server, and credentials. The current host reports no installed ODBC drivers.
- Public OData/Web probes are best-effort observations. Broader authentication and service variants remain unverified.
- Minimum-supported-Mac performance and full native accessibility acceptance remain open.

## Recommendations

1. Keep `docs/verification-coverage.md` as the release evidence ledger and add rows when new product capabilities are introduced.
2. For each source family, preserve separate evidence for picker/dialog, parser/commit, model/report use, persistence, and refresh.
3. Do not close the M/DAX parity boundary until a compatible runtime or semantic oracle is selected and its lifecycle behavior is tested.
4. Schedule live SQL and minimum-Mac/native accessibility acceptance when those environments are available.

## Orchestration note

The installed `council-orchestrator` supports stage advancement and completion checks but does not implement the skill-documented `keep`, `experiment`, or `analysis` commands. The KEEP decision and metric were recorded in `.council/EXPERIMENT_LOG.md`; this report was generated manually from that log and the final verification evidence.
