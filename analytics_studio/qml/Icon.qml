import QtQuick 6.5

Item {
    id: root
    property string name: "report"
    property color color: "#647382"
    implicitWidth: 22
    implicitHeight: 22
    width: implicitWidth
    height: implicitHeight
    Accessible.ignored: true

    readonly property string assetName: {
        switch (name) {
        case "file": case "project": case "document": return "document"
        case "folder": return "folder_open"
        case "semanticModel": return "flowchart"
        case "home": return "home"
        case "insert": case "plus": return "add"
        case "close": return "dismiss"
        case "share": return "share"
        case "optimize": return "gauge"
        case "model": return "flowchart"
        case "relationship": return "branch"
        case "view": case "eye": return "eye"
        case "help": return "question"
        case "about": return "info"
        case "report": case "chart": return "data_histogram"
        case "data": case "table": return "table"
        case "open": return "folder_open"
        case "getData": return "database_arrow_right"
        case "database": return "database"
        case "databaseMultiple": return "database_multiple"
        case "databaseLink": return "database_link"
        case "tableAdd": return "table_add"
        case "tableEdit": return "table_edit"
        case "history": return "history"
        case "cut": return "cut"
        case "copy": return "copy"
        case "paste": return "clipboard_paste"
        case "formatPainter": return "paint_brush"
        case "button": return "button"
        case "shape": return "shapes"
        case "save": return "save"
        case "saveAs": return "save_copy"
        case "csv": case "import": return "document_arrow_right"
        case "refresh": return "arrow_sync"
        case "clear": return "filter_dismiss"
        case "filter": return "filter"
        case "page": return "document_add"
        case "text": return "text_add"
        case "image": return "image"
        case "measure": case "dataLine": return "data_line"
        case "newVisual": return "data_bar_vertical_add"
        case "column": return "data_bar_vertical"
        case "bar": return "data_bar_horizontal"
        case "stackedColumn": return "data_bar_vertical_add"
        case "stackedBar": return "chart_multiple"
        case "line": return "data_line"
        case "area": return "data_area"
        case "pie": return "data_pie"
        case "donut": return "circle_multiple_concentric"
        case "treemap": return "data_treemap"
        case "map": return "map"
        case "scatter": return "data_scatter"
        case "waterfall": return "data_waterfall"
        case "funnel": return "data_funnel"
        case "barCluster": return "data_bar_horizontal"
        case "columnCluster": return "data_bar_vertical_ascending"
        case "combo": case "ribbonChart": return "chart_multiple"
        case "filledMap": return "map_drive"
        case "card": return "card_ui"
        case "multiCard": return "card_ui"
        case "kpi": case "dataTrending": return "data_trending"
        case "gauge": return "gauge"
        case "slicer": return "filter"
        case "quickVisual": return "sparkle"
        case "smartVisual": return "brain_sparkle"
        case "matrix": return "table_multiple"
        case "script": return "code"
        case "keyInfluencers": return "branch"
        case "decomposition": return "flowchart"
        case "qaVisual": return "question"
        case "narrative": return "text_align_left"
        case "sparkline": return "data_line"
        case "quickMeasure": return "calculator_arrow_clockwise"
        case "calendar": return "calendar"
        case "form": return "form"
        case "eye": return "eye"
        case "security": return "shield_checkmark"
        case "lightbulb": return "lightbulb"
        case "pause": return "pause"
        case "phone": return "phone"
        case "grid": return "grid"
        case "bookmark": return "bookmark"
        case "checkmark": return "checkmark"
        case "book": return "book_open"
        case "video": return "video_clip"
        case "support": return "person_support"
        case "people": return "people"
        case "plug": return "plug_connected"
        case "paintBrush": return "paint_brush"
        case "math": return "math_symbols"
        case "lock": return "shield_checkmark"
        case "collapsePane": return "chevron_double_right"
        case "collapseLeft": return "chevron_double_left"
        case "arrow_left": return "chevron_double_left"
        case "arrow_right": return "chevron_double_right"
        case "visual": case "gallery": case "moreVisuals": case "apps": return "apps"
        case "properties": return "settings"
        case "navigation": return "panel_left"
        case "inspector": return "panel_right"
        case "zoomIn": return "zoom_in"
        case "zoomOut": return "zoom_out"
        case "fit": return "zoom_fit"
        case "reset": return "arrow_reset"
        case "search": return "search"
        case "shortcuts": return "keyboard"
        case "format": return "text_align_left"
        case "dax": case "tmdl": return "code"
        default: return "question"
        }
    }

    readonly property string exactAssetPath: {
        switch (name) {
        case "stackedBar": return "icons/visuals/stacked_bar.svg"
        case "bar100": return "icons/visuals/bar_100.svg"
        case "stackedColumn": return "icons/visuals/stacked_column.svg"
        case "column100": return "icons/visuals/column_100.svg"
        case "stackedArea": return "icons/visuals/stacked_area.svg"
        case "lineStackedColumn": return "icons/visuals/line_stacked_column.svg"
        case "lineClusteredColumn": return "icons/visuals/line_clustered_column.svg"
        case "ribbonChart": return "icons/visuals/ribbon_chart.svg"
        case "filledMap": return "icons/visuals/filled_map.svg"
        case "shapeMap": return "icons/visuals/shape_map.svg"
        case "arcgisMap": return "icons/visuals/arcgis_map.svg"
        case "scorecard": return "icons/visuals/scorecard.svg"
        case "galleryMore": return "icons/visuals/more_visuals.svg"
        case "csv": return "icons/get_data_csv.svg"
        case "excel": return "icons/excel_workbook.svg"
        case "excelTile": return "icons/excel_tile.svg"
        case "sqlServer": return "icons/sql_server.svg"
        case "pasteTable": return "icons/paste_table.svg"
        case "sampleData": return "icons/sample_data.svg"
        case "xml": return "icons/get_data_xml.svg"
        case "json": return "icons/get_data_json.svg"
        case "pdf": return "icons/get_data_pdf.svg"
        case "parquet": return "icons/get_data_parquet.svg"
        case "button": return "icons/ribbon/report_button.svg"
        case "text": return "icons/ribbon/text_box.svg"
        default: return ""
        }
    }

    readonly property string tintKey: {
        const hex = String(root.color).toLowerCase().slice(-6)
        switch (hex) {
        case "0078d4": return "0078d4"
        case "107c71": return "107c71"
        case "c65911": return "c65911"
        case "8a6d1d": case "9a7940": return "8a6d1d"
        default: return "647382"
        }
    }
    readonly property real glyphOpacity: {
        const hex = String(root.color).toLowerCase().slice(-6)
        if (hex === "a5adb4" || hex === "a8afb5" || hex === "b6bdc3" || hex === "9aa6af")
            return 0.55
        if (hex === "85939c" || hex === "718191")
            return 0.76
        return 1.0
    }

    Image {
        anchors.fill: parent
        source: Qt.resolvedUrl(root.exactAssetPath.length > 0
                               ? root.exactAssetPath
                               : "icons/fluent/" + root.assetName + "_" + root.tintKey + "_20_regular.svg")
        sourceSize.width: 20
        sourceSize.height: 20
        fillMode: Image.PreserveAspectFit
        smooth: true
        opacity: root.glyphOpacity
    }
}
