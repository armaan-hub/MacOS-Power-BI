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
    implicitWidth: kind === "measureStructure" ? structure.implicitWidth
                   : (kind === "measureFormatting" ? formatting.implicitWidth
                      : (kind === "measureProperties" ? properties.implicitWidth
                         : (kind === "tableStructure" ? tableStructure.implicitWidth : 0)))
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
}
