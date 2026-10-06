# Analytics Studio Project Format

## Overview

The `.npa` format is a UTF-8 JSON document owned by Analytics Studio. It is deliberately readable and easy to version-control. Version 1 stores project identity, view state, report pages, supported chart types, linked data-source paths, and model metadata. It does not embed imported data.

The top-level `format` value is `com.analytics-studio.project`; `format_version` is the integer `1`.

## Version 1 shape

```json
{
  "format": "com.analytics-studio.project",
  "format_version": 1,
  "project_id": "UUID",
  "name": "Untitled Project",
  "created_at": "2026-10-05T10:00:00Z",
  "modified_at": "2026-10-05T10:00:00Z",
  "active_view": "Report",
  "data_sources": [],
  "report": {
    "pages": [
      {
        "id": "UUID",
        "name": "Overview",
        "visuals": ["Revenue KPI", "Monthly revenue", "Region revenue"]
      }
    ],
    "active_page_id": "UUID",
    "chart_types": {"monthly": "column", "region": "bar"}
  },
  "model": {"tables": [], "relationships": []}
}
```

### Fields

- `project_id` and report page `id` values are UUID strings.
- Timestamps are UTC ISO 8601 strings.
- `active_view` is `Report`, `Data`, or `Model`.
- `data_sources` entries contain `id`, `name`, `kind`, and `path`. Version 1 imports CSV files and currently reconnects one CSV source in the UI.
- Report pages have unique IDs, names, and a list of visual names. `active_page_id` must identify a page in `pages`.
- `chart_types` values are `column`, `bar`, or `line`.
- `model.tables` and `model.relationships` hold metadata. The current UI lists imported tables; relationship editing is not implemented.

## Linked data paths

CSV files remain external to the `.npa` document. When a source is inside the project file's directory tree, the app stores a relative path from that directory. Otherwise it stores an absolute path. Moving a project with an external source can break that link; when a source is missing, the app opens the project and reports the missing path so the user can restore or re-import the CSV.

## Save and recovery behavior

1. The app writes the new JSON to a temporary file beside the project.
2. It flushes the temporary file and atomically replaces the project file.
3. Before replacing an existing readable project during a normal save, it keeps the previous file as `<project>.npa.bak` (for example, `Sales.npa.bak`).
4. If a project is unreadable or invalid, opening it tries the `.bak` copy. If recovery succeeds, the app reports that fact. Saving the recovered project repairs the main file and preserves the backup.
5. A project with a newer unsupported `format_version` is rejected explicitly; the app does not silently open an older backup in its place.
6. Unsaved edits prompt before New, Open, or Quit. Save errors leave the current project open and marked as unsaved.

The first save of a new project has no prior file to back up. The backup is created on a later save.

## Versioning rule

Any incompatible schema change must increment `format_version` and add an explicit migration before the new version is accepted. Until that migration exists, the app rejects unsupported versions with a clear message and leaves the project files untouched.
