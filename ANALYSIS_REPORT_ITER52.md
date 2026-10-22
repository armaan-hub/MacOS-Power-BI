# Council Analysis — Iteration 52

## Result

The local filter-discoverability increment passed its final verification: **984 tests and 722 subtests** in the complete offscreen suite. The narrow Model route/responsiveness selection passed 3 tests. Compileall, targeted Ruff, and `git diff --check` passed. The changes reuse existing filters and clarify scope across Report, Data, and Model.

## Evidence and limits

REA captured screenshot-only views of the Power BI Desktop and Power Query Editor Parallels windows. The proxies were too small for detailed comparison, accessibility mapping was ambiguous, and REA could not establish the local Qt process identity. There was no click-through or behavioral comparison. This iteration verifies local routes and filter scope; it does not establish Microsoft Power BI parity or resolve the reported calculation mismatch.

## Iteration pattern

The experiment log records **52 KEEP entries and no DISCARD entries**. Repeated high-value work has combined focused lifecycle tests, a fresh full suite, review of transaction and responsive-layout edges, and explicit documentation of runtime boundaries. Test counts indicate regression coverage, not whole-product feature parity.

## Next step

Close the current Power Query filter coverage split with one acceptance path: author a filter through the real header dropdown, accept through the Transform session, save and reopen the project, change the source, refresh, and assert the saved step and exact output rows. Broader M/Mashup and DAX/Tabular behavior, report/model filters, chart parity, and the user's calculation discrepancy remain open.

## Orchestration note

The installed `council-orchestrator` does not expose the skill-documented `analysis` command (`Unknown command: analysis`). This report was written manually from the verified test record, `.council/EXPERIMENT_LOG.md`, and `.council/council_journal.md`.
