import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Item {
    id: root
    property var appController

    function typeForColumn(column) {
        const types = root.appController ? (root.appController.columnTypes || []) : []
        for (let index = 0; index < types.length; index++) {
            if (String(types[index].column) === String(column))
                return String(types[index].type)
        }
        return "text"
    }

    function queryGroupFor(sourceId) {
        const tables = root.appController ? (root.appController.tableCatalog || []) : []
        for (let index = 0; index < tables.length; index++) {
            if (String(tables[index].sourceId) === String(sourceId))
                return String(tables[index].queryGroup || "")
        }
        return ""
    }

    Loader {
        anchors.fill: parent
        active: root.appController !== null && root.appController !== undefined
        sourceComponent: Component {
            ColumnLayout {
                id: dataPage
                property var activeColumnProfile: ({})
                anchors.fill: parent
                anchors.margins: 18
                spacing: 12

                function refreshColumnProfile() {
                    const column = typeColumnCombo.currentText
                    activeColumnProfile = root.appController && column !== ""
                            ? root.appController.profileColumn(column)
                            : ({})
                }

                Component.onCompleted: refreshColumnProfile()

                Connections {
                    target: root.appController
                    ignoreUnknownSignals: true
                    function onStateChanged() { dataPage.refreshColumnProfile() }
                }

            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Text { text: "Data"; color: "#263645"; font.pixelSize: 20; font.weight: Font.DemiBold }
                    Text {
                        text: root.appController.sourceLoaded
                              ? root.appController.sourceName + " · " + Number(root.appController.rowCount).toLocaleString(Qt.locale(), 'f', 0) + " rows · " + root.appController.columnCount + " columns"
                              : "Preview a local data source linked to this project"
                        color: "#5d6975"; font.pixelSize: 12; elide: Text.ElideRight
                    }
                }
                ComboBox {
                    visible: (root.appController.tableCatalog || []).length > 0
                    Layout.preferredWidth: 210
                    model: root.appController.tableCatalog || []
                    textRole: "displayName"
                    currentIndex: root.appController.activeTableIndex
                    Accessible.name: "Active table"
                    Accessible.description: "Select a loaded table to inspect its data and report results."
                    delegate: ItemDelegate {
                        required property int index
                        text: String(root.appController.tableCatalog[index].displayName)
                        enabled: Boolean(root.appController.tableCatalog[index].loaded)
                        Accessible.name: text + (enabled
                                ? ""
                                : (root.appController.tableCatalog[index].loadEnabled
                                   ? ", source unavailable"
                                   : ", load disabled"))
                    }
                    onActivated: function(index) {
                        const selected = root.appController.tableCatalog[index]
                        if (selected && selected.loaded)
                            root.appController.selectTable(String(selected.sourceId))
                    }
                }
                Button {
                    visible: root.appController.activeTableId !== ""
                    text: "Remove table"
                    Accessible.name: "Remove active table from this project"
                    Accessible.description: "Removes the table and its saved steps from the project. Linked files and folder contents on disk are kept."
                    background: Rectangle { radius: 4; color: parent.hovered ? "#f9eeee" : "#fffafa"; border.color: "#e3caca" }
                    contentItem: Text { text: parent.text; color: "#a4262c"; font.pixelSize: 10; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: root.appController.removeTable(String(root.appController.activeTableId))
                }
                Button {
                    text: root.appController.modelTables.length > 0 ? "Add table" : "Import data"
                    Accessible.name: "Add CSV, Excel, JSON, XML, or Parquet table"
                    background: Rectangle { radius: 4; color: parent.down ? "#0d665d" : (parent.hovered ? "#16897d" : "#107C71"); border.color: "#0d665d" }
                    contentItem: Text { text: parent.text; color: "#ffffff"; font.pixelSize: 10; font.weight: Font.DemiBold; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: root.appController.executeCommand("importData")
                }
                Button {
                    visible: (root.appController.tableCatalog || []).filter(function(table) {
                        return Boolean(table.evaluated)
                    }).length >= 2
                    text: "Append queries"
                    Accessible.name: "Append two available tables"
                    Accessible.description: "Create a saved query by appending rows from two evaluated tables with the same ordered columns."
                    onClicked: root.appController.executeCommand("appendQueries")
                }
                Button {
                    visible: (root.appController.tableCatalog || []).filter(function(table) {
                        return Boolean(table.evaluated)
                    }).length >= 2
                    text: "Merge queries"
                    Accessible.name: "Merge two available tables"
                    Accessible.description: "Join two evaluated tables by matching one or more column pairs and choose the join kind."
                    onClicked: root.appController.executeCommand("mergeQueries")
                }
                Button {
                    text: "Refresh"
                    enabled: root.appController.canRefreshSource
                    Accessible.name: "Refresh active local source"
                    Accessible.description: root.appController.canRefreshSource
                            ? "Reload the active linked source or saved query and refresh included dependent queries. Excluded queries keep their last evaluated result."
                            : (root.appController.activeSourceExcludedFromRefresh
                               ? "This saved query is excluded from report refresh."
                            : (root.appController.sourceLoaded
                               ? "Inline tables are stored in the project and do not have a linked source to refresh."
                               : "Import a linked file or folder before refreshing."))
                    ToolTip.visible: hovered && !enabled
                    ToolTip.text: Accessible.description
                    background: Rectangle { radius: 4; color: parent.enabled ? (parent.hovered ? "#edf5fb" : "#f7fafc") : "#f6f7f8"; border.color: parent.enabled ? "#c4dcec" : "#d5dce1" }
                    contentItem: Text { text: parent.text; color: parent.enabled ? "#0067b8" : "#929ca3"; font.pixelSize: 10; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: root.appController.executeCommand("refreshSource")
                }
                Button {
                    text: "Refresh all"
                    enabled: root.appController.canRefreshAllSources
                    Accessible.name: "Refresh all linked sources"
                    Accessible.description: root.appController.canRefreshAllSources
                            ? "Reload every supported linked source and rebuild included saved queries. Excluded queries keep their last evaluated result."
                            : "Import or connect at least one linked source before refreshing all."
                    ToolTip.visible: hovered && !enabled
                    ToolTip.text: Accessible.description
                    background: Rectangle { radius: 4; color: parent.enabled ? (parent.hovered ? "#edf5fb" : "#f7fafc") : "#f6f7f8"; border.color: parent.enabled ? "#c4dcec" : "#d5dce1" }
                    contentItem: Text { text: parent.text; color: parent.enabled ? "#0067b8" : "#929ca3"; font.pixelSize: 10; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: root.appController.executeCommand("refreshAllSources")
                }
            }

            RowLayout {
                visible: root.appController.activeTableId !== ""
                Layout.fillWidth: true
                spacing: 8
                Text {
                    text: "Query group · " + (root.queryGroupFor(root.appController.activeTableId) || "None")
                    color: "#526575"
                    font.pixelSize: 11
                    elide: Text.ElideRight
                }
                Item { Layout.fillWidth: true }
                Button {
                    text: root.queryGroupFor(root.appController.activeTableId) ? "Change group" : "Group query"
                    Accessible.name: "Assign active query to a group"
                    Accessible.description: "Set or clear the active table's saved query group. Group names are shared with other items using the same name."
                    onClicked: root.appController.editQueryGroup(String(root.appController.activeTableId))
                }
            }

            ColumnLayout {
                visible: (root.appController.tableCatalog || []).some(function(table) {
                    return table.kind === "query"
                })
                Layout.fillWidth: true
                spacing: 3
                Text {
                    text: "Saved query settings"
                    color: "#344251"
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                }
                ListView {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(contentHeight, 114)
                    clip: true
                    model: (root.appController.tableCatalog || []).filter(function(table) {
                        return table.kind === "query"
                    })
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    delegate: RowLayout {
                        required property var modelData
                        width: ListView.view.width
                        height: 38
                        Text {
                            Layout.fillWidth: true
                            text: String(modelData.displayName)
                            color: "#526575"
                            font.pixelSize: 10
                            elide: Text.ElideRight
                        }
                        CheckBox {
                            text: "Load to model"
                            checked: Boolean(modelData.loadEnabled)
                            enabled: Boolean(modelData.evaluated) || Boolean(modelData.loadEnabled)
                            Accessible.name: "Enable load for " + String(modelData.name)
                            Accessible.description: checked
                                    ? "Include this query result in the model."
                                    : (modelData.evaluated
                                       ? "Keep evaluating this query for downstream queries, but exclude it from model tables."
                                       : "This query is unavailable until its inputs can be evaluated.")
                            onToggled: root.appController.setQueryLoadEnabled(
                                String(modelData.sourceId), checked
                            )
                        }
                        CheckBox {
                            text: "Include in refresh"
                            checked: Boolean(modelData.includeInReportRefresh)
                            Accessible.name: "Include " + String(modelData.name) + " in report refresh"
                            Accessible.description: checked
                                    ? "Refresh this query when its source chain is refreshed."
                                    : "Keep this query's last evaluated result during refresh; included downstream queries can use that result."
                            onToggled: root.appController.setQueryRefreshIncluded(
                                String(modelData.sourceId), checked
                            )
                        }
                    }
                }
            }

            RowLayout {
                visible: root.appController.sourceLoaded && root.appController.columnCount > 0
                Layout.fillWidth: true
                spacing: 8

                Text {
                    text: "Column type"
                    color: "#526575"
                    font.pixelSize: 11
                }
                ComboBox {
                    id: typeColumnCombo
                    Layout.preferredWidth: 210
                    model: root.appController.headers || []
                    Accessible.name: "Column to change type"
                    onActivated: dataPage.refreshColumnProfile()
                    onCurrentIndexChanged: dataPage.refreshColumnProfile()
                }
                ComboBox {
                    id: typeValueCombo
                    Layout.preferredWidth: 180
                    textRole: "label"
                    valueRole: "value"
                    model: [
                        { label: "Text", value: "text" },
                        { label: "Whole number", value: "whole_number" },
                        { label: "Decimal number", value: "decimal_number" },
                        { label: "True/False", value: "boolean" },
                        { label: "Date", value: "date" },
                        { label: "Date/time", value: "datetime" },
                        { label: "Time", value: "time" }
                    ]
                    currentIndex: {
                        const selectedType = root.typeForColumn(typeColumnCombo.currentText)
                        const typeNames = ["text", "whole_number", "decimal_number", "boolean", "date", "datetime", "time"]
                        const found = typeNames.indexOf(selectedType)
                        return found < 0 ? 0 : found
                    }
                    Accessible.name: "Selected Power BI column type"
                }
                Button {
                    text: "Apply type"
                    enabled: typeColumnCombo.currentText !== ""
                    Accessible.name: "Apply type to selected column"
                    onClicked: root.appController.setColumnType(
                        typeColumnCombo.currentText,
                        typeValueCombo.currentValue
                    )
                }
                Item { Layout.fillWidth: true }
            }

            RowLayout {
                visible: root.appController.sourceLoaded && dataPage.activeColumnProfile.column !== undefined
                Layout.fillWidth: true
                spacing: 12

                Text {
                    text: "Profile · " + dataPage.activeColumnProfile.column + " · all rows"
                    color: "#344251"
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
                Text {
                    text: "Valid " + dataPage.activeColumnProfile.validCount
                          + " (" + dataPage.activeColumnProfile.validPercent + "%)"
                    color: "#107c71"
                    font.pixelSize: 10
                }
                Text {
                    text: "Errors " + dataPage.activeColumnProfile.errorCount
                          + " (" + dataPage.activeColumnProfile.errorPercent + "%)"
                    color: dataPage.activeColumnProfile.errorCount > 0 ? "#a4262c" : "#596a79"
                    font.pixelSize: 10
                }
                Text {
                    text: "Empty " + dataPage.activeColumnProfile.emptyCount
                          + " (" + dataPage.activeColumnProfile.emptyPercent + "%)"
                    color: "#596a79"
                    font.pixelSize: 10
                }
                Text {
                    text: "Distinct " + dataPage.activeColumnProfile.distinctCount
                          + " · unique " + dataPage.activeColumnProfile.uniqueCount
                    color: "#596a79"
                    font.pixelSize: 10
                }
                Text {
                    Layout.fillWidth: true
                    text: {
                        const top = dataPage.activeColumnProfile.topValues || []
                        const values = top.map(function(item) {
                            return String(item.value) + " (" + item.count + ")"
                        })
                        return "Top: " + (values.length ? values.join(", ") : "No non-empty values")
                    }
                    color: "#596a79"
                    font.pixelSize: 10
                    elide: Text.ElideRight
                }
            }

            Rectangle {
                visible: !root.appController.sourceLoaded || root.appController.sourceWarning !== ""
                Layout.fillWidth: true
                implicitHeight: noticeText.implicitHeight + 20
                radius: 6
                color: root.appController.sourceWarning !== "" ? "#f7f0e8" : "#eef2f5"
                border.color: "#dce3e9"
                Text {
                    id: noticeText
                    anchors.fill: parent
                    anchors.margins: 10
                    text: root.appController.sourceWarning !== ""
                          ? root.appController.sourceWarning
                          : "No data source loaded. Choose Import data to preview rows."
                    color: "#556575"
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                    verticalAlignment: Text.AlignVCenter
                    Accessible.name: "Data source status"
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 6
                color: "#ffffff"
                border.color: "#dce2e8"
                clip: true

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    HorizontalHeaderView {
                        id: headerView
                        Layout.fillWidth: true
                        syncView: tableView
                        clip: true
                        delegate: Rectangle {
                            implicitHeight: 44
                            implicitWidth: Math.max(110, headerLabel.implicitWidth + 24)
                            color: "#f0f5f8"
                            border.color: "#e0e5e9"
                            Text {
                                id: headerLabel
                                anchors.top: parent.top
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.topMargin: 5
                                anchors.leftMargin: 10
                                anchors.rightMargin: 8
                                text: display
                                color: "#465463"
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                                Accessible.name: String(display)
                                       + ", " + root.typeForColumn(String(display))
                            }
                            Text {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                anchors.leftMargin: 10
                                anchors.rightMargin: 8
                                anchors.bottomMargin: 4
                                text: {
                                    const selectedType = root.typeForColumn(String(display))
                                    const labels = {
                                        text: "Text",
                                        whole_number: "Whole number",
                                        decimal_number: "Decimal number",
                                        boolean: "True/False",
                                        date: "Date",
                                        datetime: "Date/time",
                                        time: "Time"
                                    }
                                    return labels[selectedType] || selectedType
                                }
                                color: "#107c71"
                                font.pixelSize: 9
                                elide: Text.ElideRight
                            }
                        }
                    }

                    TableView {
                        id: tableView
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: root.appController.dataModel
                        clip: true
                        columnSpacing: 1
                        rowSpacing: 1
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.horizontal: ScrollBar {}
                        ScrollBar.vertical: ScrollBar {}
                        columnWidthProvider: function(column) { return Math.max(120, Math.min(260, width / Math.max(1, root.appController.columnCount))) }
                        rowHeightProvider: function(row) { return 30 }
                        delegate: Rectangle {
                            implicitWidth: 150
                            implicitHeight: 30
                            color: row % 2 === 0 ? "#ffffff" : "#fafbfc"
                            Text {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 8
                                verticalAlignment: Text.AlignVCenter
                                text: typeof display === "undefined" ? "" : String(display)
                                color: "#344251"
                                font.pixelSize: 12
                                elide: Text.ElideRight
                            }
                        }
                    }
                }

                Text {
                    anchors.centerIn: parent
                    visible: root.appController.sourceLoaded && root.appController.rowCount === 0
                    text: "The source has headers but no rows."
                    color: "#5d6975"
                    font.pixelSize: 13
                }
            }

            Text {
                Layout.fillWidth: true
                text: "The table preview shows up to 500 rows; column profiles use all rows in the active table. Report cards and charts recognize common sales, date, geographic, cost, and quantity field names."
                color: "#5d6975"
                font.pixelSize: 11
            }
            }
        }
    }
}
