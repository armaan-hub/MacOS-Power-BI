# Get Data source catalog

## What appears

The picker groups sources under File, Database, Power BI, Online Services, and Other. The All view combines those categories and collapses duplicate labels.

This is a presentation catalog. Only Text/CSV opens a working importer. Power BI semantic models and the remaining entries are informational; their connection workflows are not implemented.

## Implementation status

- **Text/CSV:** opens the existing CSV importer and loads data into the active project.
- **Other entries:** remain selectable for information, but do not start connections or authentication.
- **Recent sources:** shows the loaded CSV when available; otherwise it shows an empty state.
- **Insert menus:** More visuals, Buttons/Navigator, and Shapes are presentation surfaces; selecting an entry reports that the report-editing workflow is not implemented yet.
