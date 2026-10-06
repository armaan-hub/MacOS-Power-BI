# Analytics Studio Project Format

## Overview

The `.npa` format is a UTF-8 JSON document owned by Analytics Studio. It is deliberately readable and easy to version-control. Version 2 stores project identity, view state, report pages, supported chart types, linked data-source paths, the active file source and its parser options, and model metadata. It does not embed imported data.

The top-level `format` value is `com.analytics-studio.project`; `format_version` is the integer `2`.

## Version 2 shape

```json
{
  "format": "com.analytics-studio.project",
  "format_version": 2,
  "project_id": "UUID",
  "name": "Untitled Project",
  "created_at": "2026-10-05T10:00:00Z",
  "modified_at": "2026-10-05T10:00:00Z",
  "active_view": "Report",
  "active_source_id": "source-uuid",
  "data_sources": [
    {
      "id": "source-uuid",
      "name": "sales.csv",
      "kind": "csv",
      "path": "sales.csv",
      "parser_options": {
        "delimiter": ",",
        "encoding": "utf-8-sig",
        "has_header": true
      }
    }
  ],
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
- `active_source_id` is null when no file source is selected; otherwise it identifies an entry in `data_sources`. Only its table is loaded in this release. Other source metadata can remain in the project.
- `data_sources` entries contain `id`, `name`, `kind`, and `path`. The supported file kinds are `csv`, `excel`, `json`, and `xml`; Folder, PDF, and Parquet remain unavailable.
- `parser_options` stores settings needed to reproduce the active source on refresh. CSV stores `delimiter`, `encoding`, and `has_header`. Excel stores `sheet_name` and one-based `header_row`; null selects the first worksheet and first non-empty header row. JSON and XML use an empty options object.
- Report pages have unique IDs, names, and a list of visual names. `active_page_id` must identify a page in `pages`.
- `chart_types` values are `column`, `bar`, or `line`.
- `model.tables` and `model.relationships` hold metadata. The current UI lists imported tables; relationship editing is not implemented.

## Linked data paths

CSV, Excel workbook, JSON, and XML files remain external to the `.npa` document. When a source is inside the project file's directory tree, the app stores a relative path from that directory. Otherwise it stores an absolute path. Moving a project with an external source can break that link; when a source is missing, the app opens the project and reports the missing path while retaining the selected source ID and options so the user can restore or re-import the file.

## Save and recovery behavior

1. The app writes the new JSON to a temporary file beside the project.
2. It flushes the temporary file and atomically replaces the project file.
3. Before replacing an existing readable project during a normal save, it keeps the previous file as `<project>.npa.bak` (for example, `Sales.npa.bak`).
4. If a project is unreadable or invalid, opening it tries the `.bak` copy. If recovery succeeds, the app reports that fact. Saving the recovered project repairs the main file and preserves the backup.
5. A project with a newer unsupported `format_version` is rejected explicitly; the app does not silently open an older backup in its place.
6. Unsaved edits prompt before New, Open, or Quit. Save errors leave the current project open and marked as unsaved.

The first save of a new project has no prior file to back up. The backup is created on a later save.

## Versioning rule

Version 1 projects migrate in memory to version 2: the active source becomes the first CSV or Excel entry, matching the v1 application behavior, and supported file sources receive default parser options. Opening a project does not rewrite its file; the next explicit save writes v2. Any incompatible schema change must increment `format_version` and add an explicit migration before the new version is accepted. Newer unsupported versions are rejected with a clear message and left untouched.
