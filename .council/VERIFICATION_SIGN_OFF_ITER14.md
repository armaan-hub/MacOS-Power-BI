# Iteration 14 verification sign-off — folder source settings

## Scope

Existing folder roots can change folder path and combine recipe in the Power Query session. The recipe covers file kind, recursive discovery, filename filter, sample file, sample parser options, and `Source.Name` inclusion. The session preserves the root ID, query/model metadata, and applied steps; Apply validates the reviewed folder snapshot and dependent schema/type output before committing.

## Verification

- Focused local source, Home workflow, and Power Query session group:
  `python3 -m pytest -q tests/test_local_source_expansion.py tests/test_home_file_workflows.py tests/test_power_query_session_combine.py`
  Result: **96 passed, 46 subtests passed**.
- Full pytest:
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 QT_QPA_PLATFORM=offscreen PYTHONPATH=. python3 -m pytest -x -q --tb=short`
  Result: **655 passed, 471 subtests passed**.
- Full unittest:
  `QT_QPA_PLATFORM=offscreen PYTHONPATH=. python3 -m unittest discover -s tests`
  Result: **600 tests passed**.
- Static/whitespace checks:
  `python3 -m compileall -q analytics_studio tests`
  `git diff --check`
  Result: both passed.

## Reviewed regressions

- The folder editor restores recursion, filename filter, sample selection, parser options, and source-name inclusion; it uses apply-settings language and hides the replacement warning.
- The controller reuses the separate folder dialog for path/recipe edits. The ribbon and Queries context menu both stage the edit.
- A changed folder recipe updates the root and dependent Reference preview; source identity and applied steps remain intact through Apply, save/reopen, and changed-folder refresh.
- Folder content drift after preview rejects Apply while leaving the project, raw candidates, and loaded candidates unchanged.

Independent review found no code blocker. It identified stale progress wording, which was corrected. Manual macOS UI/accessibility acceptance was not performed; the UI checks run in Qt offscreen mode.

## Limits

This increment edits local folder sources only. SQL Server, OData, and Web source editing; schema migration; minimum-Mac performance; Microsoft Mashup execution; full M; complete DAX; and manual macOS acceptance remain open. The local M bridge and DAX evaluator remain bounded subsets.
