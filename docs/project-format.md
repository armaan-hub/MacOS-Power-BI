# Analytics Studio Project Format

## Overview

The `.npa` format is a readable UTF-8 JSON document. Version 66 stores project identity, active view and page, report chart settings and report/page/visual filters, model metadata including optional date-table columns, optional relationship definitions, per-column data types, measure and calculated-column definitions, linked local files, SQLite objects, SQL Server objects, OData Feed entity sets, and Web URLs/navigation settings, optional embedded tables, replayable local table transformations, derived append/merge/calculated/calendar-table query definitions, query groups, and saved-query load/refresh settings. File and remote database rows remain external; only tables entered or loaded as built-in sample data are embedded.

The top-level `format` value is `com.analytics-studio.project`; `format_version` is `66`.

## Linked file source

```json
{
  "id": "source-uuid",
  "name": "sales.csv",
  "kind": "csv",
  "path": "sales.csv",
  "parser_options": {
    "delimiter": ",",
    "encoding": "utf-8-sig",
    "has_header": true
  },
  "transform_steps": []
}
```

Supported single-file kinds are `csv`, `excel`, `json`, `xml`, `parquet`, and `sqlite`. Excel supports `.xls`, `.xlsx`, and `.xlsm`; parser options are `sheet_name` and one-based `header_row`. CSV options are `delimiter`, `encoding`, and `has_header`; JSON, XML, and Parquet use an empty parser-options object. SQLite supports `.db`, `.sqlite`, and `.sqlite3` files; its parser option `table_name` names the selected table or view. SQLite files open read-only, and each selected object is stored as its own linked source. File imports use at most 10 MiB, 100,000 rows, 512 columns, and 500,000 cells. Modern Excel workbook contents have an 80 MiB uncompressed cap; Parquet and SQLite have an 80 MiB rendered-text result cap; Parquet also has an 80 MiB row-group uncompressed cap.

SQLite import lists user tables and views, converts scalar values to text, maps nulls to blank strings, normalizes blank or duplicate headers, and rejects BLOB values. The 10 MiB input limit includes the database and its optional write-ahead log; table reads are interrupted after roughly 10 seconds of SQLite virtual-machine work. Recent-source records retain the last selected object. The application does not write to SQLite files.

Parquet files use PyArrow and support flat scalar null, boolean, integer, finite floating-point, decimal, string, date, time, and timestamp columns. Values are converted to text, nulls become blank, and the source type information is not retained. Nested, binary, and unsupported extension types are rejected. This app supports one local file per source; it does not connect to cloud Parquet locations or load partitioned directories.

## Linked SQL Server source

```json
{
  "id": "sql-source-uuid",
  "name": "Sales.dbo.Orders",
  "kind": "sql_server",
  "connection": {
    "server": "sql.example.com",
    "port": 1433,
    "database": "Sales",
    "username": "analytics_reader",
    "driver": "ODBC Driver 18 for SQL Server",
    "encrypt": true,
    "credential_ref": "keychain-reference-uuid"
  },
  "parser_options": {
    "schema": "dbo",
    "table_name": "Orders",
    "object_type": "TABLE"
  },
  "transform_steps": []
}
```

The source is pathless. The project stores server, port, database, SQL login, installed driver name, selected schema/object/type, and an opaque credential reference; it never stores the password or a full connection string. Passwords are saved in macOS Keychain, shared by tables that use the same server/database/login. If a project is opened on a Mac without that Keychain item, the user is prompted for the password. Removing the last project table that uses a credential removes its Keychain item where possible.

The connector supports SQL Server username/password authentication with Microsoft ODBC Driver 17 or 18. It explicitly enables TLS and server-certificate validation (`Encrypt=yes`, `TrustServerCertificate=no`). Install the Microsoft driver separately; see [Microsoft's macOS installation guide](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/install-microsoft-odbc-driver-sql-server-macos?view=sql-server-2017). The workflow enumerates user tables and views, previews at most 100 rows, then imports the selected object using a bracket-quoted `SELECT`. SQL `NULL` values become blank strings; booleans become `TRUE`/`FALSE`; dates and times use ISO text; scalar values become text. Binary, XML, unbounded text, unsupported values, and non-finite numbers are rejected. Imports cap at 100,000 rows, 512 columns, 500,000 cells, 1 MiB per cell, and 80 MiB rendered UTF-8 text. Login attempts use an 8-second timeout and each metadata/table command uses a 10-second timeout. The operation issues metadata reads and `SELECT` only; the SQL login's own server permissions are not changed. SQL Server sources reopen and refresh from the saved object identity. They are not part of the local Recent Sources list. Import mode is supported; Windows/Entra authentication, generic ODBC, DirectQuery, query folding, and gateway or Service refresh are not part of this source record.

## Linked OData Feed source

```json
{
  "id": "odata-source-uuid",
  "name": "Products · OData Feed",
  "kind": "odata",
  "connection": {
    "service_root": "https://services.example.com/odata/"
  },
  "parser_options": {
    "entity_set_name": "Products",
    "entity_url": "https://services.example.com/odata/Products"
  },
  "transform_steps": []
}
```

The source is pathless and stores only the HTTPS service root and selected entity-set name/URL. It stores no credential or arbitrary request headers. The importer reads an OData JSON service document, previews the chosen entity set, follows same-origin `@odata.nextLink` pages, and refreshes from the saved entity URL. Redirects and page links must remain on the same HTTPS origin; certificate validation stays enabled. Only anonymous OData v4 with flat scalar entity properties is supported. Nested properties, other authentication methods, empty entity sets without inferable columns, custom headers, query folding, DirectQuery, and Service/gateway refresh are outside this increment. Responses are limited to 10 MiB each and 100 MiB total; requests time out after 10 seconds; the result is capped at 100,000 rows, 512 columns, 500,000 cells, 1 MiB per cell, and 80 MiB rendered UTF-8. Runtime acceptance against a live OData endpoint remains pending. See Microsoft's [OData Feed connector](https://learn.microsoft.com/en-us/power-query/connectors/odata-feed) and the [OData JSON v4 format](https://docs.oasis-open.org/odata/odata-json-format/v4.0/csd01/odata-json-format-v4.0-csd01.html).

## Linked Web source

```json
{
  "id": "web-source-uuid",
  "name": "Products · Web",
  "kind": "web",
  "connection": {
    "url": "https://example.com/products.json"
  },
  "parser_options": {
    "resource_type": "json",
    "json_path": ["products"]
  },
  "transform_steps": []
}
```

The source is pathless. The complete HTTPS URL and selected object/parser options are saved; credentials and custom headers are not supported. Import uses anonymous HTTPS GET with TLS certificate validation, HTTPS-only redirects, a 10-second timeout, and a 10 MiB response cap. Supported responses are CSV, flat scalar-record JSON collections, regular-record XML, Excel workbooks (the recommended tabular worksheet is selected automatically), Parquet, and static HTML tables. PDF files are not supported by this Web increment. CSV stores delimiter, encoding, and header settings. HTML navigation stores the table index and header choice; JSON navigation stores a bounded path into the response. Rows, columns, cells, and rendered text use the shared import limits. POST, cookies, API-key sign-in, pagination, browser rendering, and JavaScript-generated page content are not supported. Project open and Refresh fetch the URL again. Runtime acceptance against public HTTPS sources remains pending.

When Excel options are automatic, preview recommends a likely table worksheet and header row based on table density and common column labels. The selected sheet and row are saved in `parser_options`; the user can change either in the preview. The `.xls` reader imports stored formula results without recalculating formulas and interprets date-formatted numbers with the workbook's 1900/1904 system. Ambiguous or invalid date serials remain numeric.

## Linked folder source

A folder source links to a directory and stores the combine recipe with its source record:

```json
{
  "id": "folder-source-uuid",
  "name": "monthly-sales",
  "kind": "folder",
  "path": "monthly-sales",
  "parser_options": {
    "file_kind": "csv",
    "recursive": false,
    "name_contains": "",
    "sample_file": "January.csv",
    "file_options": {
      "delimiter": ",",
      "encoding": "utf-8-sig",
      "has_header": true
    },
    "include_source_name": true
  },
  "transform_steps": []
}
```

Only matching CSV, Excel, JSON, or XML files are considered. Each source file is limited to 10 MiB; the folder importer caps a selection at 500 files and 100 MiB combined source size, and applies the existing row, column, and cell limits to the combined result. Files must match the sample file's ordered columns. The optional `Source.Name` column is enabled by default. Refresh reruns the saved discovery and combine recipe.

## Embedded inline source

Enter Data, Paste Data, and Sample Data use a pathless source record:

```json
{
  "id": "source-uuid",
  "name": "Sales table",
  "kind": "inline",
  "headers": ["Region", "Revenue"],
  "rows": [
    {"Region": "East", "Revenue": "12"},
    {"Region": "West", "Revenue": "20"}
  ],
  "transform_steps": []
}
```

Inline tables do not contain `path` or `parser_options`. Cells are JSON scalar values or null. Inline data is limited to 100,000 rows, 512 columns, 500,000 cells, and 10 MiB of serialized UTF-8 JSON. Inline tables are saved in the project and do not have a file to refresh.

## Derived append, merge, calculated-table, and calendar-table queries

Append and merge queries store their operation and source IDs instead of copying derived rows into the project. Calculated tables use the same saved-query dependency path and store a bounded DAX expression; the current table-expression subset is `DISTINCT('Table'[Column])`, which emits one row per exact value, including blank, in first-seen order. Calendar tables also use saved query definitions: `CALENDAR` stores an inclusive fixed start/end range, while `CALENDARAUTO` scans eligible loaded Date/DateTime model columns and expands to complete fiscal years around their minimum and maximum values. Automatic calendar dependencies are synchronized with eligible model tables, and generated dates are replayed on open and refresh. Query dependency cycles are rejected. A query source contains no `path`, `parser_options`, `headers`, or `rows` fields. Append queries reference two or more distinct project sources; merge queries reference exactly two; calculated tables reference one source table; fixed calendar queries have no source dependencies, while automatic calendar queries track their model sources. Query sources may set `load_enabled` to `false` to omit their output from the model while continuing to evaluate the query for downstream dependencies; the default is `true`. The independent `include_in_report_refresh` setting defaults to `true`; when false, explicit refresh keeps the query's last in-memory result and included downstream queries may continue from it. If there is no cached result, the dependent refresh fails with an actionable error. Opening a project currently reevaluates saved queries to reconstruct their local results because the project stores query definitions rather than materialized query data. Any source may optionally store a `query_group` string of up to 80 characters to organize query and table entries; group labels are flat and do not affect evaluation.

```json
{
  "id": "query-uuid",
  "name": "All sales",
  "kind": "query",
  "load_enabled": true,
  "include_in_report_refresh": true,
  "query_definition": {
    "operation": "append",
    "source_ids": ["sales-east-uuid", "sales-west-uuid"]
  },
  "transform_steps": []
}
```

```json
{
  "id": "merge-query-uuid",
  "name": "Sales with customers",
  "kind": "query",
  "query_definition": {
    "operation": "merge",
    "source_ids": ["sales-uuid", "customers-uuid"],
    "left_keys": ["Customer ID", "Country"],
    "right_keys": ["ID", "Country"],
    "join_kind": "left_outer",
    "right_name": "Customers"
  },
  "transform_steps": []
}
```

```json
{
  "id": "calculated-table-uuid",
  "name": "Sales regions",
  "kind": "query",
  "load_enabled": true,
  "include_in_report_refresh": true,
  "query_definition": {
    "operation": "calculated_table",
    "source_ids": ["sales-source-uuid"],
    "expression": "DISTINCT('Sales'[Region])",
    "source_table": "Sales"
  },
  "transform_steps": []
}
```

```json
{
  "id": "calendar-table-uuid",
  "name": "Calendar",
  "kind": "query",
  "load_enabled": true,
  "include_in_report_refresh": true,
  "query_definition": {
    "operation": "calendar",
    "source_ids": [],
    "start_date": "2024-01-01",
    "end_date": "2024-12-31"
  },
  "transform_steps": []
}
```

An automatic calendar query uses `"operation": "calendar_auto"`, the synchronized `source_ids` list, and `"fiscal_year_end_month": 12` (or 1–11 for another fiscal year end). Both calendar operations create one Date-typed `Date` column. The local generated-table row cap is 100,000.

Append currently combines two loaded tables with identical ordered column names. Merge currently joins two loaded tables using one or more paired key columns and supports inner, left/right/full outer, and left/right anti joins. Merge outputs all columns from both tables; duplicate right-side column names use the saved right table name as a prefix. Key values compare exactly as stored, and blank keys do not match. Calculated tables currently support `DISTINCT` over one selected column, preserve its saved column type, and use the source model table name and source ID saved in the definition. Calendar tables use `CALENDAR` for an inclusive entered range or `CALENDARAUTO` to scan eligible loaded Date/DateTime columns; automatic calendars ignore blanks and cover full fiscal years. They exclude calculated columns and calculated/calendar tables from date discovery and are marked with their generated `Date` column. All query operations apply the normal row, column, and cell limits, save definitions instead of derived rows, and replay query steps after evaluation. On open, sources load in dependency order; refreshing a query reloads its dependencies and rebuilds downstream queries. Save As leaves query records unchanged because they contain no paths.

## Report pages and filters

The report object stores a `filters` list for conditions that apply across all pages. It uses the same `table_id`, `column`, `clauses`, and `logic` fields as page filters, with up to 256 distinct table/column filters. Report filters support the same typed and relative-date/time operators; Top N remains visual-only. The report filter list is independent of every page's and visual's filters.

Each report page stores a `filters` list. A page filter has `table_id`, `column`, `clauses`, and `logic`. Scalar clauses have an `operator` and text `value`; `is_any_of` and `is_none_of` clauses instead store a `values` list of 1–1000 distinct text values. Relative-date clauses store `operator: "relative_date"`, a `direction` (`last`, `this`, or `next`), `count` (1–1000; normalized to 1 for `this`), `unit` (`days`, `weeks`, `calendar_weeks`, `months`, `calendar_months`, `years`, or `calendar_years`), and a boolean `include_today`. Relative-time clauses store `operator: "relative_time"`, a `direction` (`last`, `this`, or `next`), `count` (1–1000; normalized to 1 for `this`), and a `unit` (`minutes` or `hours`). Relative-date and relative-time clauses must be the filter's only clause; they can target Date and Date/time fields respectively. Other filters contain one or two clauses joined with `and` or `or`; each page can store at most one filter per table column and 256 filters total. Multi-value selection compares typed numbers and date/time fields using their saved model type; blank is a selectable value. Exact and negative text comparisons may use an empty value; text matching and equality are case-sensitive. `is_blank` and `is_not_blank` take no value. Text columns support equality, text matching, multi-value selection, and blank checks. Boolean columns support equality, multi-value selection, and blank checks. Numeric and date/time columns support equality, ordered comparisons, multi-value selection, and blank checks; Date columns also support relative-date rules and Date/time columns support relative-time rules. Numeric values compare as finite decimals; date, date/time, and time values use the saved model type and ISO representation. A filter targeting an unloaded or changed field stays saved and is ignored until the field is available again.

Relative-date rules use the current UTC date as their anchor; report, page, and visual relative filters share that anchor during a report refresh. Last/Next rules for Days, Weeks, Months, and Years use rolling intervals; `include_today` controls whether the anchor date belongs to those intervals. Calendar units select complete calendar periods, calendar weeks run Sunday through Saturday, and `this` selects the current day, calendar week, month, or year. An open report refreshes its relative-date results at UTC midnight. Relative-time rules use one shared UTC timestamp anchor during a report refresh. Last/Next use rolling minute/hour intervals; `this` selects the current UTC minute or hour. Offset timestamps normalize to UTC, and timezone-naive values are treated as UTC. The open report recalculates relative-time results at each UTC minute boundary. This follows Microsoft's [relative date filter guide](https://learn.microsoft.com/en-us/power-bi/visuals/desktop-slicer-filter-date-range) and [relative-time filter guide](https://learn.microsoft.com/en-us/power-bi/create-reports/slicer-filter-relative-time), which documents DateTime columns, Last/This/Next, Minutes/Hours, and UTC-based filtering.

Each page also stores a `visual_filters` list. A visual filter adds `visual_name` to the page-filter fields and applies only to that named visual. A page can store at most 256 visual filters and one condition group per visual/table/column. Different conditions for the same field at page and visual scope intersect. The Filters pane lists and removes filters for the selected visual; a filter remains saved if its visual, table, or field is temporarily unavailable.

Conditions within one field use the selected `logic`; filters on different fields combine with AND. Report, page, and visual filters constrain their selected tables and can propagate through active relationship directions. A visual filter changes only that visual's KPI, chart, or supported measure result. It affects active-table summaries only when the filtered table is the active table or connected to it; filters on disconnected tables do not change those summaries. Relative-date and relative-time rules are available at report, page, and visual scope.

Top N is visual-only. A Top N clause records `operator: "top_n"`, `direction` (`top` or `bottom`), `count` (1–1000), and an `order_by` object containing `table_id` and `column`. In this local implementation, only the Region revenue chart is supported; it ranks the active table’s detected Region values by the sum of a selected numeric field. Equal totals use ascending category labels as a stable tie break.

```json
{
  "id": "a65ec88b-e0bf-4ed3-918a-21e8e1b0b90b",
  "name": "Overview",
  "visuals": ["Revenue KPI", "Monthly revenue"],
  "filters": [
    {"table_id": "60aaece8-55a2-4ac8-94c7-1bd65261f55a", "column": "Country", "clauses": [{"operator": "is_any_of", "values": ["UAE", "Oman"]}], "logic": "and"}
  ],
  "visual_filters": [
    {"visual_name": "Monthly revenue", "table_id": "60aaece8-55a2-4ac8-94c7-1bd65261f55a", "column": "Channel", "clauses": [{"operator": "equals", "value": "Online"}], "logic": "and"}
  ]
}
```

## Model column types

Each model table may store a `column_types` map keyed by its current column names. Supported values are `text`, `whole_number`, `decimal_number`, `boolean`, `date`, `datetime`, and `time`. Columns created by transformations use operation-derived types where available and otherwise default to `text`; custom, conditional, merged, dynamically pivoted, delimiter-split, and position-split columns default to `text` and can be converted with a later step. Type changes also create replayable conversion steps on the corresponding source, so refresh applies the same conversion. Projects v1–v65 migrate to v66 with their existing type metadata, report filters, calculated columns, and query definitions preserved. Project format v65 introduced optional date-table column metadata; v66 adds saved calendar-table definitions. Each model table may also store `date_column` as null or the name of a date/datetime typed column. The marked column must use a date-capable model type; loaded values are checked for blanks, duplicate calendar days, gaps, and consistent time-of-day for DateTime columns whenever the source opens or refreshes. Invalid refresh data is rejected while the last loaded rows remain available. The project stores the mark, not a copy of linked-source rows.

Each model table may also store `calculated_columns`, an ordered list of `{ "name", "expression" }` definitions. The local DAX row evaluator currently accepts numeric and boolean expressions using same-table columns, arithmetic, comparisons, `IF`, `AND`, `OR`, `NOT`, `ABS`, and `ROUND`. It recomputes these values after source transformations on project open and source refresh. Aggregates, measures, cross-table references, and text results are rejected in this calculated-column subset.

```json
{
  "id": "source-uuid",
  "name": "Sales",
  "source_id": "source-uuid",
  "column_types": {
    "Order Date": "date",
    "Revenue": "decimal_number"
  },
  "calculated_columns": [
    {"name": "Line total", "expression": "[Quantity] * [Unit price]"}
  ]
}
```

## Transform steps

`transform_steps` is an ordered JSON list saved with each source. Steps are replayed after parsing the linked file or reading an embedded table. The source file is never modified. Supported operations are:

```json
{"op": "rename_column", "column": "Old", "new_name": "New"}
{"op": "remove_column", "column": "Old"}
{"op": "filter_rows", "column": "Revenue", "operator": "greater_than", "value": "10"}
{"op": "filter_rows", "column": "Region", "operator": "is_blank", "value": ""}
{"op": "filter_rows", "column": "Region", "operator": "is_not_blank", "value": ""}
{"op": "filter_rows_advanced", "clauses": [
  {"column": "Region", "operator": "equals", "value": "West", "join": "and"},
  {"column": "Year", "operator": "greater_than_or_equal", "value": "2024", "join": "or"}
]}
{"op": "sort_rows", "column": "Revenue", "direction": "desc"}
{"op": "sort_rows_by_columns", "sorts": [{"column": "Region", "direction": "asc"}, {"column": "Revenue", "direction": "desc"}]}
{"op": "convert_type", "column": "Revenue", "type": "number"}
{"op": "convert_type_using_locale", "column": "Revenue", "type": "decimal_number", "culture": "de-DE"}
{"op": "replace_value", "column": "Region", "value": "N. America", "replacement": "North America"}
{"op": "extract_text_by_delimiter", "column": "Email", "side": "before", "delimiter": "@", "occurrence": 0}
{"op": "extract_text_between_delimiters", "column": "Code", "start_delimiter": "[", "end_delimiter": "]", "start_occurrence": 0, "end_occurrence": 0}
{"op": "split_column", "column": "Account", "delimiter": " "}
{"op": "split_column_by_each_delimiter", "column": "Tags", "delimiter": ","}
{"op": "split_column_to_rows", "column": "Accounts", "delimiter": ";"}
{"op": "merge_columns", "columns": ["First", "Last"], "separator": " ", "new_name": "Full name"}
{"op": "fill_down", "columns": ["Region", "Category"]}
{"op": "fill_up", "columns": ["Region", "Category"]}
{"op": "duplicate_column", "column": "Revenue", "new_name": "Revenue copy"}
{"op": "group_by", "columns": ["Region", "Year"], "aggregations": [
  {"operation": "sum", "column": "Revenue", "new_name": "Total revenue"},
  {"operation": "count_rows", "new_name": "Order count"}
]}
{"op": "unpivot_columns", "columns": ["2024", "2025"], "attribute_name": "Year", "value_name": "Revenue"}
{"op": "unpivot_other_columns", "columns": ["Region"], "attribute_name": "Attribute", "value_name": "Value"}
{"op": "pivot_column", "attribute_column": "Attribute", "value_column": "Value", "aggregation": "none"}
{"op": "add_custom_column", "name": "Net sales", "expression": "[Units] * [#\"Unit Price\"]"}
{"op": "conditional_column", "name": "Price tier", "clauses": [{"column": "Tier", "operator": "equals", "test_value": "1", "test_value_kind": "value", "output": "Tier 1 Price", "output_kind": "column"}], "else_value": "Tier 3 Price", "else_kind": "column"}
{"op": "trim_text", "column": "Region"}
{"op": "clean_text", "column": "Region"}
{"op": "lowercase_text", "column": "Region"}
{"op": "proper_case_text", "column": "Region"}
{"op": "reverse_text", "column": "Region"}
{"op": "remove_duplicates"}
{"op": "remove_duplicates", "columns": ["Customer ID", "Country"]}
{"op": "keep_duplicates", "columns": ["Customer ID", "Country"]}
{"op": "remove_blank_rows"}
{"op": "remove_top_rows", "count": 4}
{"op": "remove_bottom_rows", "count": 4}
{"op": "keep_top_rows", "count": 4}
{"op": "keep_bottom_rows", "count": 4}
{"op": "keep_range_rows", "first_row": 6, "count": 8}
{"op": "remove_alternate_rows", "first_row_to_remove": 2, "remove_count": 1, "keep_count": 1}
{"op": "add_index_column", "new_name": "Index", "start": 0, "increment": 1}
{"op": "keep_columns", "columns": ["Date", "Region", "Revenue"]}
{"op": "reorder_columns", "columns": ["Revenue", "Region", "Date"]}
{"op": "promote_headers"}
{"op": "demote_headers"}
{"op": "transpose_table"}
{"op": "split_column_by_positions", "column": "Code", "positions": [0, 4, 9]}
```

Every-delimiter column splitting uses the exact saved delimiter and replaces the source field with `<column>.1`, `<column>.2`, and later text fields. The output width matches the largest part count across the current input rows, with at least two fields; shorter rows are padded with empty strings, while adjacent and trailing delimiters preserve empty parts. Output-name collisions and the existing column/cell limits are checked before rebuilding rows.

Delimiter extraction keeps the text before or after a selected zero-based occurrence of an exact, non-empty delimiter in one Text-typed column. Occurrence `0` means the first match, `1` the second, and so on. The source column is updated in place and remains Text; empty cells remain empty. A non-empty value without the requested occurrence reports the row and column as a transformation error. The step must precede conversion to a non-text type.

Between-delimiter extraction keeps the text after a selected occurrence of the start delimiter and before a selected occurrence of the end delimiter that follows it. Both delimiters are exact, non-empty strings; occurrence indexes are zero-based and counted from the start delimiter match (the end occurrence is searched from the end of the selected start delimiter). The selected Text-typed column is updated in place and remains Text. Empty cells remain empty; if either requested delimiter occurrence is missing, the error reports the row and column. Numeric occurrence indexes from the start are supported; Power Query's relative-from-end index-list form is not implemented. The step must precede conversion to a non-text type.

Filter operators are `equals`, `not_equals`, `contains`, `does_not_contain`, `begins_with`, `does_not_begin_with`, `ends_with`, `does_not_end_with`, `greater_than`, `greater_than_or_equal`, `less_than`, `less_than_or_equal`, `is_blank`, and `is_not_blank`. Numeric comparisons parse finite invariant numbers; inclusive comparisons retain values equal to the threshold, while blank cells do not match. Text matching is exact and case-sensitive; empty text criteria follow ordinary substring, prefix, and suffix rules. Advanced filter steps store 1–64 clauses across columns. `is_blank` and `is_not_blank` do not take a comparison value; they match empty and non-empty normalized strings respectively, so whitespace-only values are nonblank. Source nulls and empty strings are normalized to the same empty string. Every clause after the first joins to its predecessor with `and` or `or`; `and` binds more tightly than `or`, so clauses are evaluated as OR-separated AND groups. The editor stores a flat expression without nested groups; use separate filter steps for nested logic. Advanced numeric clauses use the same blank and invalid-value handling and report the affected row and column. Sort direction is `asc` or `desc`. Multi-column sort steps save an ordered list of distinct `{column, direction}` keys; the first key has highest priority and each key has an independent direction. Sorting is stable, keeps blank values last for each key, uses invariant numeric ordering when all non-empty values parse as finite numbers, and otherwise uses case-sensitive Unicode ordinal text order. `convert_type` supports `text`, `whole_number`, `decimal_number`, `boolean`, ISO date (`YYYY-MM-DD`), ISO date/time, and ISO time. Its legacy `number` type remains readable and maps to `decimal_number` metadata. `convert_type_using_locale` supports whole number, decimal number, date, date/time, and time with an explicit Babel/CLDR culture ID such as `en-US`, `en-GB`, or `de-DE`. The selected culture is canonicalized and saved with the step, so replay is independent of the machine's current locale. Numeric parsing uses CLDR separators and decimal rules. Localized date parsing uses Babel's Gregorian numeric date patterns; date-times support date-only values or a date followed by a colon-form clock time and recognized CLDR AM/PM markers, while ISO strings retain ISO parsing. Month-name dates, Power Query calendar-specific behavior such as Hijri dates, localized UTC offsets, currency/percentage parsing, and locale-aware booleans are not implemented. Conversion errors include the value, row, column, type, and culture. Replacement matches exact cell values. Trim Text removes leading and trailing whitespace. Clean Text removes Unicode control-category characters (U+0000–U+001F and U+007F–U+009F) anywhere in a text-typed value without inserting spaces; non-control whitespace (such as U+0020 SPACE) and other Unicode code points are preserved, while control whitespace such as tab, line feed, and carriage return is removed. No Unicode normalization is performed. Microsoft documents `Text.Clean` as removing control characters but does not enumerate the code points; this is the app's explicit local rule. Clean Text requires a text-typed value and must precede a later conversion to a non-text type. Lowercase Text, Uppercase Text, and Capitalize Each Word require a text-typed value at their step position, apply locale-neutral Unicode casing, and must precede later non-text conversion. Capitalize Each Word uses Python str.title(), lowercases other cased characters, and may capitalize after punctuation such as apostrophes; culture-specific casing and exact Power Query word-boundary parity are outside this increment. None of these operations has a culture selector. Reverse Text also requires a text-typed column, reverses Unicode code points, leaves empty values empty, preserves the Text type, and does not reverse multi-code-point grapheme clusters as a unit. The output column for each operation is capped at 80 MiB UTF-8, and values that cannot be encoded as UTF-8 are rejected. Unicode casing may expand one character into multiple output characters, and that expanded output counts toward the cap. Remove Duplicates accepts optional `columns` as its comparison keys; when omitted, it compares every field for backward compatibility. It uses exact, case-sensitive cell values and keeps the first matching row in current table order. Keep Duplicates requires one or more `columns` and retains every row whose exact, case-sensitive key tuple occurs more than once, preserving all matching rows in current order.

Promote Headers uses the first current data row as field names and removes that row. Names are trimmed; blank names use `Column N`, and duplicates receive `.1`, `.2`, and later suffixes. A table with no data rows cannot promote headers. Promoted columns default to text; later conversion steps still apply. Demote Headers moves current column names into a new first data row and replaces them with Column1, Column2, and later names. It adds one row and is rejected if row or cell limits would be exceeded. Demoted columns default to text; later conversion steps still apply. Transpose Table turns current data rows into output columns and current columns into output rows. Original column names are dropped; generated output columns are named `Column1`, `Column2`, and so on. Output values default to text and can be converted by later steps. The operation rejects a table with no data rows because it would produce zero columns, and it enforces the existing column and cell limits. Column splitting at the first exact delimiter replaces the source with `<column>.1` and `<column>.2`; text after the first match remains in the second output, and a missing delimiter produces an empty second value. Split-to-rows uses each exact delimiter, repeats the remaining values for each output row, and keeps empty items between adjacent delimiters. Position-based splitting requires 2–512 strictly increasing zero-based Unicode-code-point positions beginning with 0. Each position starts one output segment; the last segment receives the remaining suffix. It replaces the source in place with `<column>.1`, `<column>.2`, and later text fields, pads short values with empty trailing segments, and rejects output-name collisions or tables exceeding the column/cell limits. Duplicate Column appends an exact copy of a selected field and preserves its current model type; the output name must be unique. Reorder Columns saves a `columns` list and places those names into the existing positions they occupied; unlisted columns keep their positions. The interactive editor saves the full displayed order. Missing listed columns produce an error. Fill Down and Fill Up operate on selected columns and propagate the nearest non-empty cell in the chosen direction into blank cells. Source nulls are normalized to empty strings, so these blank strings are filled; leading blanks without an earlier value remain blank for Fill Down, and trailing blanks without a later value remain blank for Fill Up. Remove Blank Rows drops rows only when every normalized cell is an empty string; a whitespace-only cell or other text keeps the row. Remove Top Rows accepts a whole-number count from 0 to 100,000, removes that many rows from the current start of the table, and preserves the order of the remaining rows. Remove Bottom Rows accepts a whole-number count from 0 to 100,000, removes that many rows from the current end of the table, and preserves the order of the preceding rows. Keep Top Rows accepts a whole-number count from 0 to 100,000, retains up to that many rows from the current start, and preserves their order. Keep Bottom Rows accepts the same count range and retains up to that many rows from the current end in original order; a count of zero keeps no rows, and a count above the row count keeps all rows. Keep Range of Rows accepts a first row from 1 to 100,000 and a count from 0 to 100,000, then retains that contiguous slice in original order; a range past the table end yields only available rows or no rows. Remove Alternate Rows accepts a first row to remove from 1 to 100,000 and remove/keep counts from 0 to 100,000. It retains all earlier rows, then repeats the remove/keep pattern; at least one count must be positive. A zero remove count keeps all rows after the start, and a zero keep count removes all rows after each removed block. Add Index Column appends a new signed 64-bit whole-number field, defaulting to start 0 and increment 1, and supports custom signed 64-bit whole-number values. The output name must not collide with an existing column, and generated values must remain in the signed 64-bit range. Group By accepts one or more exact-value key columns and multiple aggregations: sum, average, median, min, max, count rows, count distinct rows, and count distinct values. Numeric and min/max operations ignore blank cells; numeric operations reject invalid non-empty numbers. Distinct-value counts include the blank string as one value. The output is flat and drops ungrouped source columns; nested All Rows and fuzzy grouping are unsupported. Unpivot selected columns keeps every other column and creates one attribute/value row for each selected non-empty cell; unpivot other columns keeps the selected columns fixed and unpivots the remaining columns. Output rows follow source row order and source column order. Attribute and value output names must differ and must not collide with retained columns. Empty cells are omitted because source nulls are normalized to empty strings in this table model. The two generated columns have text type; retained columns keep their existing types. Pivot turns unique values from the selected attribute column into output headers and uses every other column except the chosen value field as row keys. It preserves first-seen category columns and sorts result rows by the first key column. `none` requires one input value per key/category pair and reports duplicates; `count_all`, `count_non_blank`, `min`, `max`, `median`, `sum`, and `average` resolve repeated pairs. Numeric aggregates ignore blanks and reject invalid non-empty numbers. Pivot attributes must be non-empty, and generated headers cannot collide with key fields. Missing key/category combinations are blank; generated pivot columns default to text and can be converted in a later step. All transformation steps replay on refresh and enforce project row, column, and cell limits. Remove Duplicates keeps the first row for each selected key; Keep Duplicates retains all rows whose selected key repeats, preserving table order. Keep Columns retains selected fields in source order. A missing or colliding column and a failed conversion are reported; refresh keeps the last good in-memory table. Values are serialized as normalized text; conversion validates their contents while the model retains the selected type.

Custom-column formulas use a bounded safe M-style expression subset, not a full M engine. Supported syntax includes field references (`[Name]` or quoted `[#"Name with spaces"]`), text/number/null/logical literals, `if … then … else`, `??`, logical/comparison/arithmetic/text-concatenation operators, and a fixed set of `Text.*`, `Number.*`, and `Date.*` functions documented in the functionality roadmap. Numeric text uses invariant decimal notation; date parsing accepts ISO dates and date-times. Empty source cells act as null; null results serialize as blanks. Formula output is normalized to text and receives text type, which can be changed by a later `convert_type` step. Missing fields are rejected before row evaluation; evaluation errors identify the output column and row. Formula length is limited to 2,000 characters and 512 tokens; each text result and the total output column are capped at 80 MiB UTF-8. Arbitrary Python and unsupported M syntax are rejected.

Conditional-column steps store an ordered list of up to 64 clauses and a final Else value. Each clause names a test column and operator, then uses either a literal or another column for its comparison and output. The first matching clause wins. Supported operators are equals/not-equals, greater/less-than (including inclusive forms), begins/ends-with, and contains, with text negations for begins/ends/contains. Equality and text checks are case-sensitive. Ordered checks use invariant decimal comparison when both values are finite numbers and otherwise compare strings ordinally. Empty cells are blank strings and can match an empty literal. Results are text and can be converted by a later step. Missing referenced columns and output-name collisions reject the step.

Merge-column steps save at least two input column names, the exact text separator, and the output name. The separator is limited to 32,767 characters. Values are concatenated in the saved column order with the separator between every selected value, including blank cells. The selected input columns are removed and the text output is inserted at the first selected column's position. The output name may reuse one of the selected names but may not collide with an unselected column. The combined output is capped at 80 MiB UTF-8.

## Other document fields

- `project_id` and page `id` values are UUID strings; timestamps use UTC ISO 8601.
- `active_view` is `Report`, `Data`, or `Model`.
- `active_source_id` is null or identifies the selected source in `data_sources`. Projects can contain multiple local sources; supported sources load independently, and this field selects the table shown in Data and used by report summaries and unqualified measure references. Qualified measure aggregates can read other loaded tables through active relationships. Each local source currently maps to one model table.
- Report pages contain unique IDs, names, visual-name lists, page-scoped and visual-scoped condition filters, and `chart_types` values of `column`, `bar`, or `line` for monthly and regional charts. Each filter has one or two typed clauses and an AND/OR join.
- `model.tables` stores table names, source IDs, and per-column type metadata. `model.relationships` accepts legacy `{ "from": ..., "to": ... }` display-only entries and structured relationship definitions. A structured relationship entry has `relationship_version: 1`, a unique `id`, display labels `from`/`to`, `from_table_id`, `from_column`, `to_table_id`, `to_column`, `cardinality` (`one_to_one`, `one_to_many`, `many_to_one`, or `many_to_many`), `cross_filter_direction` (`single` or `both`), and boolean `is_active`. The editor validates loaded endpoints, column presence, compatible types, duplicate endpoint pairs, unique values on each one side (including blanks), and at most one active relationship per table pair. Active relationships propagate the current Region, page, and visual condition filters into supported measures and active-table report summaries; ambiguous filter paths show the competing table routes. Broad cross-table DAX is not implemented.
- `model.measures` stores `{ "name": ..., "expression": ... }` definitions. Results are recomputed from the current transformed model context and are not persisted. The local evaluator supports `SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT`, `COUNTA`, and `DISTINCTCOUNT` over unqualified active-table or qualified related-table columns; `COUNTROWS()` counts the active table. `DIVIDE`, arithmetic, parentheses, and measure references are supported. `TOTALYTD(expression, marked_date_column)` supports the default calendar year and current saved date-filter context; `TOTALYTD(expression, marked_date_column,, "M/D")` supports an ASCII month/day fiscal year end. This bounded evaluator also supports TOTALQTD, TOTALMTD, DATEADD, SAMEPERIODLASTYEAR, DATESYTD, DATESQTD, DATESMTD, DATESBETWEEN, DATESINPERIOD, PREVIOUSYEAR, PREVIOUSQUARTER, and PREVIOUSMONTH in the documented marked-date `CALCULATE` filter forms. `CALCULATE(expression)` also evaluates in the current filter context, and Boolean filters support typed single-column comparisons, AND/OR/NOT composition, multiple ANDed arguments, same-column replacement, and `KEEPFILTERS` intersection. Ordinary comparisons coerce `BLANK()` to zero, false, empty text, or 1899-12-30 by column type. A Boolean filter nested inside a time-intelligence `CALCULATE` preserves the outer date set when per-column provenance is available. Mixed replacement and `KEEPFILTERS` arguments for the same column are rejected. Boolean and time-intelligence filters cannot yet appear together in one `CALCULATE` call; table-valued filters, other filter modifiers, row-to-filter context transition, calendar-reference input, and broader DAX remain unsupported.
- Cross-project recent source history is stored in user QSettings, not in `.npa` files.

## Linked data paths

CSV, Excel, JSON, XML, and Parquet files stay outside the project. A Folder source links to a directory and stores its file-type filter, filename filter, recursive setting, sample-file path, parser options, and source-name-column setting in `parser_options`. Sources inside the project directory use relative paths; other sources use absolute paths. Save As recalculates paths for all sources. Missing links leave the project open with a warning, preserve that source's metadata, and do not prevent other tables from loading. Re-importing a linked path updates its table; adding a different file or folder creates another table. Removing a table deletes its project link and embedded rows but never deletes external files or folder contents.

## Save and recovery behavior

1. Save validates the full project and writes JSON to a temporary file beside the destination.
2. It flushes the temporary file and atomically replaces the project.
3. A later save keeps the previous project as `<project>.npa.bak`.
4. If a project is invalid or unreadable, opening tries the backup. Saving a recovered project repairs the main file and retains the recovery copy.
5. A newer unsupported `format_version` is rejected; it is never silently replaced by an older backup.
6. Unsaved changes prompt before New, Open, or Quit. Canceled or failed saves leave the current project open and dirty.

## Versioning and migrations

Validation migrates projects in memory along explicit schema steps: v1 → v2 adds the active file source and parser options; v2 → v3 adds pathless inline sources; v3 → v4 adds ordered transformation steps; v4 → v5 adds an empty measure list; v5 → v6 adds per-table column type metadata; v6 → v7 enables derived append-query sources; v7 → v8 adds merge-query definitions; v8 → v9 supports saved query group names; v9 → v10 supports delimiter-split transformation steps; v10 → v11 supports split-to-rows steps; v11 → v12 supports group-by steps; v12 → v13 supports unpivot steps; v13 → v14 supports pivot steps; v14 → v15 supports custom-column formula steps; v15 → v16 supports conditional-column steps; v16 → v17 supports merge-column steps; v17 → v18 supports Fill Down and Fill Up steps; v18 → v19 supports Duplicate Column steps; v19 → v20 adds saved-query `load_enabled`, defaulting to `true`; v20 → v21 adds `include_in_report_refresh`, defaulting to `true`; v21 → v22 supports Remove Blank Rows steps; v22 → v23 supports Remove Top Rows steps; v23 → v24 supports Remove Bottom Rows steps; v24 → v25 supports Keep Top Rows steps; v25 → v26 supports Keep Bottom Rows steps; v26 → v27 supports Keep Range of Rows steps; v27 → v28 supports Remove Alternate Rows steps; v28 → v29 supports Add Index Column steps; v29 → v30 supports Reorder Columns steps; v30 → v31 supports Use First Row as Headers steps; v31 → v32 supports Use Headers as First Row steps; v32 → v33 enables Clean Text steps without changing record shapes; v33 → v34 enables Lowercase Text steps without changing record shapes; v34 → v35 enables Uppercase Text steps without changing record shapes; v35 → v36 supports Change Type Using Locale steps; v36 → v37 supports Transpose Table steps; v37 → v38 supports Split Column by Positions steps; v38 → v39 supports splitting a column at every delimiter into columns; v39 → v40 supports extracting text before or after a selected delimiter occurrence; v40 → v41 supports extracting text between selected delimiters; v41 → v42 supports Capitalize Each Word steps without changing record shapes; v42 → v43 supports Reverse Text steps without changing record shapes; v43 → v44 supports optional comparison columns on Remove Duplicates steps while preserving legacy whole-row steps; v44 → v45 supports Keep Duplicates steps; v45 → v46 supports multi-column sorting; v46 → v47 enables the additional text filter operators; v47 → v48 adds inclusive numeric row-filter operators; v48 → v49 adds saved multi-column filter clauses; v49 → v50 adds blank/nonblank row-filter operators; v50 → v51 adds linked SQLite table and view sources; v51 → v52 adds pathless SQL Server sources with Keychain credential references; v52 → v53 enables pathless OData Feed source records; v53 → v54 enables pathless Web source records; v54 → v55 adds an empty page-filter list to every report page; v55 → v56 adds an empty visual-filter list to every page; v56 → v57 converts existing exact-value page and visual filters into single `equals` conditions; v57 → v58 enables `is_any_of` and `is_none_of` value-list clauses without rewriting existing conditions; v58 → v59 enables relative-date clauses without rewriting existing filters; v59 → v60 enables relative-time clauses without rewriting existing filters; v60 → v61 enables visual Top N clauses without changing existing filters; v61 → v62 adds an empty report-wide filter collection; v62 → v63 adds an empty calculated-column list to each model table; v63 → v64 supports saved DAX calculated-table query definitions; v64 → v65 adds optional date-table column metadata; v65 → v66 supports saved `CALENDAR` and `CALENDARAUTO` query definitions. Opening never rewrites the project; the next explicit save writes v66. Newer unsupported versions are rejected with a clear message.
