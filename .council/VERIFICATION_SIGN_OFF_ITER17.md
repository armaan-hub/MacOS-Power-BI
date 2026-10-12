# Iteration 17 verification sign-off — Table measures and Slicer fields

## Scope

Add bounded DAX measure support to Table visuals and enforce column-only Slicer bindings. This increment does not supply full DAX/Tabular behavior, general cross-table visual queries, or the full Power Query/Mashup runtime.

## Behavior verified

- A Table may combine assigned model columns and multiple saved measures. Distinct assigned-column tuples define the row groups and each measure evaluates per group.
- A measure-only Table evaluates one total-context row. Blank measure cells remain empty; numeric zero remains visible as `0`.
- Table row selection resolves the first valid dimension field even when a measure appears first. Older saved Tables without `table_id` use the same active-model-table fallback as the renderer.
- Slicer field selection hides measures, controller binding rejects them, and a persisted legacy measure binding produces no selectable values.
- A refresh that removes a Table dimension shows an explicit stale-field message and no misleading total rows. Missing/failing measures show an evaluation message instead of being treated as genuine blanks.
- Save/reopen and changed-source refresh preserve supported Table measure behavior.

## Verification results

- Focused Table/Slicer/report group: **20 passed**.
- Full pytest: **667 passed, 476 subtests passed**.
- Full unittest: **610 tests passed**.
- `python3 -m compileall -q analytics_studio tests`: passed.
- `git diff --check`: passed.

## Review and limits

The independent critic found that measure-first row selection must resolve the Table's first valid dimension and that legacy visuals may omit `table_id`; both were fixed and covered. It also identified the stale-column total-display issue; the visual now surfaces a warning. The final review found no remaining blocker in the scoped changes.

Table measures remain limited to one bound model table, without grouped total rows or general visual query context. The local evaluator recognizes 49 function names with partial semantics. No external Tabular oracle or manual macOS UI acceptance was used. General Power Query M and Microsoft's Mashup runtime remain unavailable. These gaps keep the overall user objective open.

See [Iteration 17 test results](TEST_RESULTS_ITER17.md).
