# Test Results — 2026-10-12

## Full workspace suite

Command:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 QT_QPA_PLATFORM=offscreen PYTHONPATH=. python3 -m pytest -x -q --tb=short
```

Result: **605 passed, 450 subtests passed** in 21.45 seconds.

## Focused Power Query/session regression suite

Command:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 QT_QPA_PLATFORM=offscreen PYTHONPATH=. python3 -m pytest -x -q --tb=short tests/test_power_query_m_editor.py tests/test_power_query_session_combine.py tests/test_query_parameters.py tests/test_home_file_workflows.py tests/test_refresh_all.py
```

Result: **154 passed, 194 subtests passed** in 3.32 seconds.

Coverage added in this increment confirms an edited excluded-query dependency remains cache-backed and produces the same rows in its preview, its downstream query preview, and Close & Apply.

## Focused DAX measure/report/model suite

Command:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 QT_QPA_PLATFORM=offscreen PYTHONPATH=. python3 -m pytest -x -q --tb=short tests/test_measures.py tests/test_report_and_measure_workflow.py tests/test_calculated_column_lifecycle.py
```

Result: **41 passed, 37 subtests passed** in 0.33 seconds. This includes bounded `COUNTX` and `COUNTAX` measure forms, same-table typed text comparisons, recursive expression typing, numeric ordering comparisons, empty-string expressions, rejection of mixed/date-time/unverified comparison types, rejection of text passed to numeric scalar expressions or `COUNT`, prevalidation of Boolean conditions even when the input table is empty, and scalar aggregate/nested-iterator references to a second table.

## Additional checks

- `python3 -m compileall -q analytics_studio tests` — passed.
- `git diff --check` — passed.

These checks cover the local implementation. They do not establish full Power Query Desktop/Mashup parity, complete DAX semantics, live SQL Server/OData/Web behavior, or manual macOS acceptance.
