# Analytics Studio

Native desktop analytics authoring application. The frontend uses PySide6 with Qt Quick/QML; Python owns project lifecycle and local CSV, Excel, JSON, and XML data behavior. The workspace provides Report, Data, and Model views, a tabbed ribbon, data preview, and versioned project open/save/recovery.

## Run from source

Use Python 3.10 or newer with an Apple Silicon build on macOS:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m analytics_studio.main
```

Open an existing `.npa` project from **File → Open Project**, or pass its path as the first argument.

## Target platforms

- **First release:** Apple Silicon Macs (M1 or newer), macOS Sonoma 14.4 or later. The intended support and manual-check matrix is Sonoma 14.4, Sequoia 15, and Tahoe 26.
- **Later Linux target:** Ubuntu 24.04 LTS on x86_64.
- **Mac-like Linux desktop check:** elementary OS, as a user-experience check rather than a separate supported deployment target.

The current frontend uses PySide6 and Qt Quick/QML. Ribbon and pane glyphs use curated Fluent System Icons SVGs under their MIT license; see `analytics_studio/qml/icons/fluent/README.md`. App-authored SVGs supply file-format marks in the connector picker. The `.npa` format and core project code use Python's standard library.

## Current scope

Report, Data, and Model are native workspace views. The ribbon follows the supplied Power BI layout references with File, Home, Insert, Modeling, View, Optimize, and Help tabs. Switching to Report or Data selects Home; switching to Model selects Modeling. Data has a source-fields pane beside its 500-row preview, and Model retains Properties and Data panes. Home includes a split Get data control and a Recent sources menu. The searchable picker groups file, database, Power BI, Microsoft, online, and other sources. Text/CSV, Excel Workbook (`.xlsx`/`.xlsm`), JSON, and XML use a shared preview-and-confirm import workflow. The preview provides CSV delimiter/encoding/header options and Excel worksheet/header-row options. Imports are limited to 10 MiB per source, 100,000 rows, 512 columns, and 500,000 cells; Excel workbook contents are limited to 80 MiB uncompressed. These are defensive caps, not measured performance guarantees for the minimum supported Mac. Power BI semantic models, OneLake catalog, SQL Server, Dataverse, and other listed connectors remain unavailable. See [the source catalog notes](docs/data-source-catalog.md) for supported formats and staged entries. Transform data and query editing are not available, so there is no Query workspace. File imports populate the active table in Model and KPI summaries. Monthly and regional revenue charts use `Revenue`, `Order Date` (beginning with `YYYY-MM`), and `Region`; missing fields are reported in the chart instead of being presented as zeroes. One file source is loaded at a time, while other source and model metadata remains in the project. `.npa` version 2 stores the active source and parser options; version 1 files migrate in memory and are upgraded on explicit save. Relationship editing, DAX, sharing, additional connector implementations, and most other visual types remain unavailable. The Insert More visuals, Buttons/Navigator, and Shapes menus are visible presentation surfaces; choosing an entry reports its staged status. The independent shell follows the reference layout but does not provide whole-product parity.

The QML shell is rendered in offscreen Qt across Report, Data, and Model, including the 1040×680 minimum layout. See the [empty-project capture](docs/screenshots/powerbi-guided-home-empty-project.png), [Insert ribbon](docs/screenshots/powerbi-guided-insert.png), [CSV-loaded report](docs/screenshots/powerbi-guided-csv-loaded.png), [Data view](docs/screenshots/powerbi-guided-data.png), and [Model view](docs/screenshots/powerbi-guided-modeling.png).

Offscreen renders also cover the [connector picker](docs/screenshots/powerbi-guided-get-data-picker.png), its [minimum layout](docs/screenshots/powerbi-guided-get-data-picker-min.png), the [common sources menu](docs/screenshots/powerbi-guided-common-sources.png), [More visuals](docs/screenshots/powerbi-guided-more-visuals-menu.png), [Buttons/Navigator](docs/screenshots/powerbi-guided-buttons-menu.png), and [Shapes](docs/screenshots/powerbi-guided-shapes-menu.png). These captures show layout only; most connector and report-editing workflows remain staged.

The ribbon uses the supplied Power BI references for command density and group order. Report Home shows Clipboard, Data, Queries, Insert, Calculations, Sensitivity, and Share groups. The Insert tab uses Pages, Visuals, AI visuals, Elements, and Sparklines groups. Ribbon labels wrap fully within their controls. New page works, while unavailable commands remain disabled. The More visuals, Buttons/Navigator, and Shapes menus are selectable but report staged status because their workflows are not implemented. Data Home retains Excel workbook, OneLake catalog, SQL Server, Enter data, Dataverse, Recent sources, Transform data, and Refresh commands. Modeling starts with Data & model navigation, then Relationships, Calculations, Calendars, Page refresh, Parameters, Security, and Q&A. View and Optimize expose their pane, page, and analysis groups. Working CSV, Excel, JSON, and XML import, page, zoom, and chart actions remain active.

The Visualizations pane draws each chart glyph from the local vector icon set, aligned with its own selectable tile. Bar, Column, and Line are active; unsupported visual types are disabled. The pane includes Build, Format, and Analytics tabs plus Values and Drill through wells. In Report, Filters and Data remain narrow rails by default, and the Visualizations pane stays open. The Data workspace has a separate fields pane. Active actions use blue, teal, and amber accents.

The screenshots are offscreen Qt renders, so the native macOS title bar and system menu placement are not represented. The interface is an independent, screenshot-guided shell, not a pixel-identical Power BI clone or a claim of whole-product parity.

Project file behavior is documented in [docs/project-format.md](docs/project-format.md).

See the [functionality implementation roadmap](docs/implementation-roadmap.md) for the planned order from file imports through Home and the remaining ribbon workflows.
