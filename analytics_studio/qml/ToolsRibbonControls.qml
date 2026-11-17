import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

// Controls inside the contextual "Table tools" and "Measure tools" ribbon tabs that are not
// plain buttons: the Name box, Home table, Format and Data category.  Anything the model does
// not support yet is shown disabled with a tooltip that says so.
Item {
    id: root
    property string kind: ""
    property var studio: null
    property string selectedBinding: ""
    readonly property var bar: studio ? studio.formulaBar : null
    readonly property var loadedTables: studio ? studio.tableCatalog.filter(function(table) {
        return Boolean(table.loaded) && Boolean(table.loadEnabled)
    }) : []
    readonly property string measureName: {
        if (!studio)
            return ""
        if (bar.active && bar.mode === "measure")
            return bar.name
        if (!studio.visualFieldIsMeasure(selectedBinding))
            return ""
        const label = String(studio.visualFieldLabel(selectedBinding))
        return label.indexOf("Measure · ") === 0 ? label.slice(10) : label
    }
    readonly property string unsupportedFormat: "Measure number formats are not supported yet."
    readonly property string unsupportedColumnFormat: "Column number formats are not supported yet."

    readonly property string columnName: {
        if (!studio)
            return ""
        if (studio.visualFieldIsMeasure && studio.visualFieldIsMeasure(selectedBinding))
            return ""
        const label = String(studio.visualFieldLabel ? studio.visualFieldLabel(selectedBinding) : selectedBinding)
        return (studio.headers || []).indexOf(label) >= 0 ? label : ""
    }

    readonly property var activeTableItem: {
        if (!studio)
            return null
        const catalog = studio.tableCatalog || []
        const currentId = String(studio.activeTableId || "")
        for (let i = 0; i < catalog.length; ++i) {
            if (String(catalog[i].id) === currentId)
                return catalog[i]
        }
        return catalog.length > 0 ? catalog[0] : null
    }

    readonly property string activeModelTableId: {
        return activeTableItem ? String(activeTableItem.id || "") : (studio ? String(studio.activeTableId || "") : "")
    }

    readonly property string columnType: {
        if (!studio || columnName === "")
            return "text"
        const types = studio.columnTypes || []
        for (let i = 0; i < types.length; ++i) {
            if (String(types[i].column) === columnName)
                return String(types[i].type || "text")
        }
        return "text"
    }

    readonly property bool hasTypeChangeSlot: studio !== null && studio !== undefined && typeof studio.setColumnType === "function"

    readonly property bool canEditColumnSummarization: {
        if (!studio || columnName === "" || !activeTableItem)
            return false
        const headers = activeTableItem.headers || studio.headers || []
        const isLoaded = headers.indexOf(columnName) >= 0
        const isNumeric = ["whole_number", "decimal_number"].indexOf(columnType) >= 0
        const calculated = activeTableItem.calculatedColumns || []
        const isCalculated = calculated.some(function(item) {
            return String(item.name) === columnName
        })
        return isLoaded && isNumeric && !isCalculated
    }

    readonly property string currentColumnSummarization: {
        if (!activeTableItem || !activeTableItem.columnSummarizations)
            return "auto"
        return String(activeTableItem.columnSummarizations[columnName] || "auto")
    }

    readonly property bool canEditColumnSortBy: {
        if (!studio || columnName === "" || !activeTableItem)
            return false
        const headers = activeTableItem.headers || studio.headers || []
        const isLoaded = headers.indexOf(columnName) >= 0
        const calculated = activeTableItem.calculatedColumns || []
        const isCalculated = calculated.some(function(item) {
            return String(item.name) === columnName
        })
        return isLoaded && !isCalculated
    }

    readonly property string currentColumnSortBy: {
        if (!activeTableItem || !activeTableItem.columnSortBy)
            return ""
        return String(activeTableItem.columnSortBy[columnName] || "")
    }

    readonly property var columnSortOptions: {
        var options = [{ "label": "No sort by column", "value": "", "enabled": true }]
        if (canEditColumnSortBy && activeTableItem) {
            var headers = activeTableItem.headers || studio.headers || []
            var calculated = activeTableItem.calculatedColumns || []
            for (var index = 0; index < headers.length; ++index) {
                var header = String(headers[index])
                var isCalculated = calculated.some(function(item) {
                    return String(item.name) === header
                })
                if (header !== columnName && !isCalculated)
                    options.push({ "label": header, "value": header, "enabled": true })
            }
            if (currentColumnSortBy !== ""
                    && options.every(function(item) {
                        return String(item.value) !== currentColumnSortBy
                    })) {
                options.push({
                    "label": currentColumnSortBy + " (unavailable)",
                    "value": currentColumnSortBy,
                    "enabled": false
                })
            }
        }
        return options
    }

    implicitWidth: kind === "measureStructure" ? structure.implicitWidth
                   : (kind === "measureFormatting" ? formatting.implicitWidth
                      : (kind === "measureProperties" ? properties.implicitWidth
                         : (kind === "tableStructure" ? tableStructure.implicitWidth
                            : (kind === "columnStructure" ? columnStructure.implicitWidth
                               : (kind === "columnFormatting" ? columnFormatting.implicitWidth
                                  : (kind === "columnProperties" ? columnProperties.implicitWidth
                                     : (kind === "columnSort" ? columnSort.implicitWidth
                                        : (kind === "columnGroups" ? columnGroups.implicitWidth : 0))))))))
    implicitHeight: 60

    GridLayout {
        id: structure
        visible: root.kind === "measureStructure"
        columns: 2
        columnSpacing: 6
        rowSpacing: 4
        Text { text: "Name"; color: "#344553"; font.pixelSize: 11 }
        TextField {
            id: nameBox
            objectName: "measureNameBox"
            Layout.preferredWidth: 130
            Layout.preferredHeight: 24
            font.pixelSize: 11
            padding: 3
            text: root.measureName
            enabled: root.bar !== null && root.bar.active
            Accessible.name: "Measure name"
            HoverHandler { id: nameHover }
            ToolTip.visible: nameHover.hovered && !enabled
            ToolTip.text: "Select a measure to rename it."
            background: Rectangle { color: nameBox.enabled ? "#ffffff" : "#f3f5f6"; border.color: nameBox.activeFocus ? "#6b91aa" : "#cfd7dd" }
            onEditingFinished: {
                if (enabled && text !== root.bar.name)
                    root.bar.setName(text)
            }
        }
        Text { text: "Home table"; color: "#344553"; font.pixelSize: 11 }
        ComboBox {
            id: homeTable
            objectName: "measureHomeTableBox"
            Layout.preferredWidth: 130
            Layout.preferredHeight: 24
            font.pixelSize: 11
            model: root.loadedTables
            textRole: "name"
            enabled: root.bar !== null && root.bar.active && root.loadedTables.length > 1
            currentIndex: {
                const id = root.bar ? String(root.bar.homeTableId) : ""
                return root.loadedTables.findIndex(function(table) { return String(table.id) === id })
            }
            displayText: root.bar ? root.bar.tableName : ""
            Accessible.name: "Home table"
            background: Rectangle { color: homeTable.enabled ? "#ffffff" : "#f3f5f6"; border.color: "#cfd7dd" }
            onActivated: function(index) { root.bar.setHomeTable(String(root.loadedTables[index].id)) }
        }
    }

    GridLayout {
        id: formatting
        visible: root.kind === "measureFormatting"
        columns: 4
        columnSpacing: 4
        rowSpacing: 4
        Text { text: "Format"; color: "#8d969c"; font.pixelSize: 11 }
        ComboBox {
            id: formatBox
            objectName: "measureFormatBox"
            property string disabledReason: root.unsupportedFormat
            Layout.columnSpan: 3
            Layout.preferredWidth: 130
            Layout.preferredHeight: 24
            enabled: false
            model: []
            displayText: ""
            Accessible.name: "Format"
            Accessible.description: root.unsupportedFormat
            HoverHandler { id: formatHover }
            ToolTip.visible: formatHover.hovered
            ToolTip.text: root.unsupportedFormat
            background: Rectangle { color: "#f3f5f6"; border.color: "#dfe3e5" }
        }
        Repeater {
            model: ["$", "%", ",", ".00"]
            delegate: Button {
                id: formatButton
                required property string modelData
                objectName: "measureFormatButton"
                Layout.preferredWidth: 28
                Layout.preferredHeight: 22
                enabled: false
                padding: 0
                Accessible.name: "Format " + modelData
                Accessible.description: root.unsupportedFormat
                HoverHandler { id: buttonHover }
                ToolTip.visible: buttonHover.hovered
                ToolTip.text: root.unsupportedFormat
                background: Rectangle { color: "transparent" }
                contentItem: Text {
                    text: formatButton.modelData
                    color: "#a8afb5"
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }
    }

    RowLayout {
        id: properties
        visible: root.kind === "measureProperties"
        spacing: 6
        Text { text: "Data category"; color: "#8d969c"; font.pixelSize: 11 }
        ComboBox {
            id: categoryBox
            objectName: "measureDataCategoryBox"
            property string disabledReason: "Data categories are not supported yet."
            Layout.preferredWidth: 120
            Layout.preferredHeight: 24
            enabled: false
            model: []
            displayText: ""
            Accessible.name: "Data category"
            Accessible.description: "Data categories are not supported yet."
            HoverHandler { id: categoryHover }
            ToolTip.visible: categoryHover.hovered
            ToolTip.text: "Data categories are not supported yet."
            background: Rectangle { color: "#f3f5f6"; border.color: "#dfe3e5" }
        }
    }

    RowLayout {
        id: tableStructure
        visible: root.kind === "tableStructure"
        spacing: 6
        Text { text: "Table"; color: "#344553"; font.pixelSize: 11 }
        Text {
            objectName: "tableToolsTableName"
            Layout.preferredWidth: 130
            text: root.bar ? root.bar.activeTableName : ""
            color: "#1f2a33"
            font.pixelSize: 11
            font.weight: Font.DemiBold
            elide: Text.ElideRight
            Accessible.name: "Active table " + text
        }
    }

    GridLayout {
        id: columnStructure
        visible: root.kind === "columnStructure"
        columns: 2
        columnSpacing: 6
        rowSpacing: 4
        Text { text: "Name"; color: "#344553"; font.pixelSize: 11 }
        TextField {
            id: columnNameBox
            objectName: "columnToolsName"
            Layout.preferredWidth: 130
            Layout.preferredHeight: 24
            font.pixelSize: 11
            padding: 3
            text: root.columnName
            readOnly: true
            Accessible.name: "Column name"
            HoverHandler { id: colNameHover }
            ToolTip.visible: colNameHover.hovered
            ToolTip.text: "Renaming columns here is not supported yet."
            background: Rectangle { color: "#f3f5f6"; border.color: "#cfd7dd" }
        }
        Text { text: "Data type"; color: "#344553"; font.pixelSize: 11 }
        ComboBox {
            id: columnDataTypeBox
            objectName: "columnToolsDataType"
            Layout.preferredWidth: 130
            Layout.preferredHeight: 24
            font.pixelSize: 11
            textRole: "label"
            valueRole: "value"
            model: [
                { label: "Text", value: "text" },
                { label: "Any (mixed)", value: "any" },
                { label: "Whole number", value: "whole_number" },
                { label: "Decimal number", value: "decimal_number" },
                { label: "True/False", value: "boolean" },
                { label: "Date", value: "date" },
                { label: "Date/time", value: "datetime" },
                { label: "Time", value: "time" }
            ]
            enabled: root.hasTypeChangeSlot && root.columnName !== ""
            currentIndex: {
                const types = ["text", "any", "whole_number", "decimal_number", "boolean", "date", "datetime", "time"]
                const found = types.indexOf(root.columnType)
                return found < 0 ? 0 : found
            }
            Accessible.name: "Column data type"
            background: Rectangle { color: columnDataTypeBox.enabled ? "#ffffff" : "#f3f5f6"; border.color: "#cfd7dd" }
            onActivated: {
                if (root.hasTypeChangeSlot && root.columnName !== "")
                    root.studio.setColumnType(root.columnName, String(currentValue))
            }
        }
    }

    GridLayout {
        id: columnFormatting
        visible: root.kind === "columnFormatting"
        columns: 4
        columnSpacing: 4
        rowSpacing: 4
        Text { text: "Format"; color: "#8d969c"; font.pixelSize: 11 }
        ComboBox {
            id: columnFormatBox
            objectName: "columnToolsFormat"
            property string disabledReason: root.unsupportedColumnFormat
            Layout.columnSpan: 3
            Layout.preferredWidth: 130
            Layout.preferredHeight: 24
            enabled: false
            model: []
            displayText: ""
            Accessible.name: "Format"
            Accessible.description: root.unsupportedColumnFormat
            HoverHandler { id: colFormatHover }
            ToolTip.visible: colFormatHover.hovered
            ToolTip.text: root.unsupportedColumnFormat
            background: Rectangle { color: "#f3f5f6"; border.color: "#dfe3e5" }
        }
        Repeater {
            model: ["$", "%", ",", ".00"]
            delegate: Button {
                id: colFormatButton
                required property string modelData
                objectName: "columnFormatButton"
                Layout.preferredWidth: 28
                Layout.preferredHeight: 22
                enabled: false
                padding: 0
                Accessible.name: "Format " + modelData
                Accessible.description: root.unsupportedColumnFormat
                HoverHandler { id: colBtnHover }
                ToolTip.visible: colBtnHover.hovered
                ToolTip.text: root.unsupportedColumnFormat
                background: Rectangle { color: "transparent" }
                contentItem: Text {
                    text: colFormatButton.modelData
                    color: "#a8afb5"
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }
    }

    GridLayout {
        id: columnProperties
        visible: root.kind === "columnProperties"
        columns: 2
        columnSpacing: 6
        rowSpacing: 4
        Text { text: "Summarization"; color: root.canEditColumnSummarization ? "#344553" : "#8d969c"; font.pixelSize: 11 }
        ComboBox {
            id: columnSummarizationBox
            objectName: "columnToolsSummarization"
            Layout.preferredWidth: 130
            Layout.preferredHeight: 24
            font.pixelSize: 11
            model: [
                { "label": "Don't summarize", "value": "auto" },
                { "label": "Sum", "value": "sum" },
                { "label": "Average", "value": "average" },
                { "label": "Count", "value": "count" }
            ]
            textRole: "label"
            valueRole: "value"
            currentIndex: {
                var values = ["auto", "sum", "average", "count"]
                return Math.max(0, values.indexOf(root.currentColumnSummarization))
            }
            enabled: root.canEditColumnSummarization
            Accessible.name: "Summarization for " + (root.columnName || "selected column")
            background: Rectangle { color: columnSummarizationBox.enabled ? "#ffffff" : "#f3f5f6"; border.color: "#cfd7dd" }
            onActivated: {
                if (root.canEditColumnSummarization && root.studio)
                    root.studio.set_column_default_summarization(
                        root.activeModelTableId,
                        root.columnName,
                        String(currentValue)
                    )
            }
        }
        Text { text: "Data category"; color: "#8d969c"; font.pixelSize: 11 }
        ComboBox {
            id: columnDataCategoryBox
            objectName: "columnToolsDataCategory"
            property string disabledReason: "Data categories are not supported yet."
            Layout.preferredWidth: 130
            Layout.preferredHeight: 24
            enabled: false
            model: []
            displayText: ""
            Accessible.name: "Data category"
            Accessible.description: "Data categories are not supported yet."
            HoverHandler { id: colCategoryHover }
            ToolTip.visible: colCategoryHover.hovered
            ToolTip.text: "Data categories are not supported yet."
            background: Rectangle { color: "#f3f5f6"; border.color: "#dfe3e5" }
        }
    }

    RowLayout {
        id: columnSort
        visible: root.kind === "columnSort"
        spacing: 6
        Text { text: "Sort by column"; color: root.canEditColumnSortBy ? "#344553" : "#8d969c"; font.pixelSize: 11 }
        ComboBox {
            id: columnSortByBox
            objectName: "columnToolsSortBy"
            Layout.preferredWidth: 140
            Layout.preferredHeight: 24
            font.pixelSize: 11
            model: root.columnSortOptions
            textRole: "label"
            valueRole: "value"
            currentIndex: {
                var options = root.columnSortOptions
                for (var index = 0; index < options.length; ++index) {
                    if (String(options[index].value) === root.currentColumnSortBy)
                        return index
                }
                return -1
            }
            enabled: root.canEditColumnSortBy
            Accessible.name: "Sort by column for " + (root.columnName || "selected column")
            delegate: ItemDelegate {
                required property var modelData
                width: columnSortByBox.width
                text: String(modelData.label)
                enabled: modelData.enabled !== false
            }
            background: Rectangle { color: columnSortByBox.enabled ? "#ffffff" : "#f3f5f6"; border.color: "#cfd7dd" }
            onActivated: {
                if (root.canEditColumnSortBy && root.studio)
                    root.studio.set_model_column_sort_by(
                        root.activeModelTableId,
                        root.columnName,
                        String(currentValue)
                    )
            }
        }
    }

    RowLayout {
        id: columnGroups
        visible: root.kind === "columnGroups"
        spacing: 6
        Text { text: "Data groups"; color: "#8d969c"; font.pixelSize: 11 }
        ComboBox {
            id: columnGroupsBox
            objectName: "columnToolsDataGroups"
            property string disabledReason: "Data groups are not supported yet."
            Layout.preferredWidth: 120
            Layout.preferredHeight: 24
            enabled: false
            model: []
            displayText: ""
            Accessible.name: "Data groups"
            Accessible.description: "Data groups are not supported yet."
            HoverHandler { id: colGroupsHover }
            ToolTip.visible: colGroupsHover.hovered
            ToolTip.text: "Data groups are not supported yet."
            background: Rectangle { color: "#f3f5f6"; border.color: "#dfe3e5" }
        }
    }
}
