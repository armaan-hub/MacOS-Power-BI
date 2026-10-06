# Get Data source catalog

## What appears

The picker groups sources under File, Database, Power BI, Microsoft, Online Services, and Other. The All view combines those categories and collapses duplicate labels.

This is a presentation catalog. Excel Workbook, Text/CSV, XML, and JSON open local-file importers. Power BI semantic models, OneLake catalog, SQL Server, Dataverse, and the remaining connector entries are informational; their connection workflows are not implemented.

## Implementation status

- **Excel Workbook:** opens `.xlsx` and `.xlsm` workbooks; users can select a worksheet and one-based header row. The default is the first worksheet and its first non-empty row. Formulas are not recalculated; saved cached values are used, and missing cached results appear blank. Legacy `.xls` files are not supported.
- **Text/CSV:** lets users choose delimiter, encoding, and whether the first row contains headers. Quoted separators and embedded newlines are supported. Blank and duplicate headers are normalized; short rows are padded and extra cells become additional columns.
- **JSON:** accepts a non-empty top-level array of flat objects with scalar values. Columns follow first-seen key order. Nested objects and arrays, duplicate object keys, and non-array roots are rejected.
- **XML:** accepts one repeated record tag under the root with identical ordered scalar child fields. Attributes, nested or mixed content, irregular fields, and multiple record groups are rejected.
- **Shared import preview:** all four formats show row and column counts and the first 100 rows before import. If a table is loaded, the final Import data action warns that it will be replaced. Canceling or a parse error leaves the current table unchanged.
- **Import limits:** source files are limited to 10 MiB; Excel workbook parts are limited to 80 MiB total uncompressed; tables are limited to 100,000 rows, 512 columns, and 500,000 cells. Oversized files are rejected instead of truncated. These defensive limits have not been benchmarked as performance guarantees for the minimum supported Mac.
- **Folder, PDF, and Parquet:** remain visible but unavailable.
- **OneLake catalog, SQL Server, and Dataverse:** remain visible as informational connector choices; their connection workflows are not implemented.
- **Other entries:** remain selectable for information, but do not start connections or authentication.
- **Recent sources:** currently shows only the loaded file; choosing it refreshes that source with its saved parser options. A multi-file recent-history list is not implemented yet.
- **Insert menus:** More visuals, Buttons/Navigator, and Shapes are presentation surfaces; selecting an entry reports that the report-editing workflow is not implemented yet.
