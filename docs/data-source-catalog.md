# Get Data source catalog

## What appears

The picker groups sources under File, Database, Power BI, Microsoft, Online Services, and Other. The All view combines those categories and collapses duplicate labels.

This is a presentation catalog. Excel Workbook and Text/CSV open working file importers. Power BI semantic models, OneLake catalog, SQL Server, Dataverse, and the remaining connector entries are informational; their connection workflows are not implemented.

## Implementation status

- **Excel Workbook:** opens `.xlsx` and `.xlsm` workbooks and imports the first worksheet into the active project, using its first non-empty row as column names. Legacy `.xls` files are not supported.
- **Text/CSV:** opens the CSV importer and loads data into the active project.
- **OneLake catalog, SQL Server, and Dataverse:** remain visible as informational connector choices; their connection workflows are not implemented.
- **Other entries:** remain selectable for information, but do not start connections or authentication.
- **Recent sources:** shows the currently loaded CSV or Excel workbook when available; otherwise it shows an empty state.
- **Insert menus:** More visuals, Buttons/Navigator, and Shapes are presentation surfaces; selecting an entry reports that the report-editing workflow is not implemented yet.
