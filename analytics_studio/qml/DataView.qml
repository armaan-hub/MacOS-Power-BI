import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Item {
    id: root
    property var appController
    property string selectedFieldName: ""
    signal selectedColumnRequested(string columnName)

    function typeForColumn(column) {
        const types = root.appController ? (root.appController.columnTypes || []) : []
        for (let index = 0; index < types.length; index++) {
            if (String(types[index].column) === String(column))
                return String(types[index].type)
        }
        return "text"
    }

    function columnNameAt(index) {
        const headers = root.appController ? (root.appController.headers || []) : []
        return index >= 0 && index < headers.length ? String(headers[index]) : ""
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
                objectName: "dataPage"
                property var activeColumnProfile: ({})
                anchors.fill: parent
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                anchors.topMargin: 12
                anchors.bottomMargin: 12
                spacing: 8

                function refreshColumnProfile() {
                    const column = typeColumnCombo.currentText
                    activeColumnProfile = root.appController && column !== ""
                            ? root.appController.profileColumn(column)
                            : ({})
                }

                function refreshProfileForSelection() {
                    const headers = root.appController ? (root.appController.headers || []) : []
                    const selected = headers.indexOf(root.selectedFieldName) >= 0
                            ? root.selectedFieldName
                            : typeColumnCombo.currentText
                    activeColumnProfile = root.appController && selected !== ""
                            ? root.appController.profileColumn(selected)
                            : ({})
                }

                function syncSelectedField() {
                    const headers = root.appController ? (root.appController.headers || []) : []
                    const selectedIndex = headers.indexOf(root.selectedFieldName)
                    if (selectedIndex >= 0 && typeColumnCombo.currentIndex !== selectedIndex)
                        typeColumnCombo.currentIndex = selectedIndex
                    else if (selectedIndex < 0) {
                        const fallbackIndex = headers.length > 0 ? 0 : -1
                        if (typeColumnCombo.currentIndex !== fallbackIndex)
                            typeColumnCombo.currentIndex = fallbackIndex
                    }
                    Qt.callLater(dataPage.refreshProfileForSelection)
                }

                Component.onCompleted: {
                    syncSelectedField()
                    refreshColumnProfile()
                }

                Connections {
                    target: root.appController
                    ignoreUnknownSignals: true
                    function onStateChanged() {
                        dataPage.syncSelectedField()
                        dataPage.refreshColumnProfile()
                    }
                }

                Connections {
                    target: root
                    function onSelectedFieldNameChanged() { dataPage.syncSelectedField() }
                }

                Dialog {
                    id: dataFilterDialog
                    objectName: "dataViewColumnFilterDialog"
                    property string columnName: ""
                    property bool compactLayout: height < 400
                    property bool draftAllSelected: true
                    property var draftValueKeys: ({})
                    property var draftFilterResults: ({})
                    property real overlayWidth: Overlay.overlay ? Overlay.overlay.width : root.width
                    property real overlayHeight: Overlay.overlay ? Overlay.overlay.height : root.height
                    parent: Overlay.overlay
                    anchors.centerIn: Overlay.overlay
                    modal: true
                    width: Math.min(560, Math.max(1, overlayWidth - 32))
                    height: Math.min(580, Math.max(1, overlayHeight - 32))
                    padding: compactLayout ? 6 : 12
                    title: "Filter preview: " + columnName

                    function refreshFilterResults() {
                        if (!root.appController || !root.appController.dataModel)
                            return
                        draftFilterResults = root.appController.dataModel.columnFilterValues(
                            columnName, valueSearch.text
                        )
                    }

                    function valueIsSelected(key) {
                        return draftAllSelected ? !draftValueKeys[key] : Boolean(draftValueKeys[key])
                    }

                    function setValueSelected(key, selected) {
                        const nextKeys = Object.assign({}, draftValueKeys)
                        if (draftAllSelected) {
                            if (selected)
                                delete nextKeys[key]
                            else
                                nextKeys[key] = true
                        } else if (selected) {
                            nextKeys[key] = true
                        } else {
                            delete nextKeys[key]
                        }
                        draftValueKeys = nextKeys
                    }

                    function setAllValuesSelected(selected) {
                        draftAllSelected = selected
                        draftValueKeys = ({})
                    }

                    function valueSelectionSummary() {
                        const count = Object.keys(draftValueKeys).length
                        if (draftAllSelected)
                            return count ? "All except " + count + " excluded" : "All values selected"
                        return count + (count === 1 ? " value selected" : " values selected")
                    }

                    function valueSearchSummary() {
                        const matching = Number(draftFilterResults.matchCount || 0)
                        const total = Number(draftFilterResults.totalCount || 0)
                        if (!matching)
                            return "No values match · " + total + " distinct values"
                        if (draftFilterResults.truncated)
                            return "Showing first 2,000 of " + matching + " matches · " + total + " distinct values"
                        return matching + (matching === 1 ? " match" : " matches")
                                + " · " + total + " distinct values"
                    }

                    onAboutToShow: {
                        const rule = root.appController.dataModel.columnFilter(columnName)
                        filterModeTabs.currentIndex = rule.operator === "values" ? 0 : rule.operator ? 1 : 0
                        const currentOperator = String(rule.operator || "equals")
                        filterOperator.currentIndex = 0
                        for (let index = 0; index < filterOperator.model.length; index++) {
                            if (String(filterOperator.model[index].value) === currentOperator) {
                                filterOperator.currentIndex = index
                                break
                            }
                        }
                        filterValue.text = String(rule.value || "")
                        valueSearch.text = ""
                        draftAllSelected = rule.operator === "values" ? rule.all !== false : true
                        const nextKeys = ({})
                        for (const key of (rule.keys || []))
                            nextKeys[String(key)] = true
                        draftValueKeys = nextKeys
                        Qt.callLater(function() {
                            dataFilterDialog.refreshFilterResults()
                            if (filterModeTabs.currentIndex === 0)
                                valueSearch.forceActiveFocus()
                        })
                    }

                    contentItem: ColumnLayout {
                        spacing: dataFilterDialog.compactLayout ? 3 : 8
                        Label {
                            objectName: "dataViewFilterModeNotice"
                            Layout.fillWidth: true
                            visible: !dataFilterDialog.compactLayout
                            text: "Values and Condition are alternatives. Applying this tab replaces the current filter for this column."
                            wrapMode: Text.WordWrap
                            Accessible.name: text
                        }
                        TabBar {
                            id: filterModeTabs
                            objectName: "dataViewFilterTabs"
                            Layout.fillWidth: true
                            Accessible.name: "Filter mode for " + dataFilterDialog.columnName
                            Accessible.description: "Values and Condition are alternatives. Applying the selected tab replaces the current filter for this column."
                            TabButton {
                                objectName: "dataViewFilterTabValues"
                                text: "Values"
                                Accessible.name: "Values filter for " + dataFilterDialog.columnName
                                onClicked: filterModeTabs.currentIndex = 0
                            }
                            TabButton {
                                objectName: "dataViewFilterTabCondition"
                                text: "Condition"
                                Accessible.name: "Condition filter for " + dataFilterDialog.columnName
                                onClicked: filterModeTabs.currentIndex = 1
                            }
                        }
                        StackLayout {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            currentIndex: filterModeTabs.currentIndex
                            ColumnLayout {
                                spacing: dataFilterDialog.compactLayout ? 3 : 8
                                Label {
                                    Layout.fillWidth: true
                                    visible: !dataFilterDialog.compactLayout
                                    text: "Values are from rows that pass filters on other columns."
                                    wrapMode: Text.WordWrap
                                }
                                TextField {
                                    id: valueSearch
                                    objectName: "dataViewFilterSearch"
                                    Accessible.name: "Search values in " + dataFilterDialog.columnName
                                    Accessible.description: "Search all distinct values in this column; the display limit does not limit search."
                                    Layout.fillWidth: true
                                    placeholderText: "Search values"
                                    maximumLength: 2_000
                                    Layout.preferredHeight: dataFilterDialog.compactLayout ? 36 : implicitHeight
                                    onTextChanged: dataFilterDialog.refreshFilterResults()
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Button {
                                        objectName: "dataViewSelectAllValues"
                                        text: "Select all values"
                                        Accessible.name: text + " in " + dataFilterDialog.columnName
                                        Accessible.description: "Select every value in the checklist, including values hidden by search."
                                        Layout.minimumHeight: dataFilterDialog.compactLayout ? 28 : 0
                                        Layout.preferredHeight: dataFilterDialog.compactLayout ? 32 : implicitHeight
                                        onClicked: dataFilterDialog.setAllValuesSelected(true)
                                    }
                                    Button {
                                        objectName: "dataViewSelectNoValues"
                                        text: "Select no values"
                                        Accessible.name: text + " in " + dataFilterDialog.columnName
                                        Accessible.description: "Deselect every value in the checklist, including values hidden by search."
                                        Layout.minimumHeight: dataFilterDialog.compactLayout ? 28 : 0
                                        Layout.preferredHeight: dataFilterDialog.compactLayout ? 32 : implicitHeight
                                        onClicked: dataFilterDialog.setAllValuesSelected(false)
                                    }
                                    Item { Layout.fillWidth: true }
                                }
                                Label {
                                    objectName: "dataViewFilterSelectionSummary"
                                    Layout.fillWidth: true
                                    text: dataFilterDialog.valueSelectionSummary()
                                    Accessible.name: text
                                }
                                ListView {
                                    id: valueOptionsList
                                    objectName: "dataViewFilterValueList"
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    Layout.minimumHeight: dataFilterDialog.compactLayout ? 32 : 120
                                    Layout.preferredHeight: 260
                                    clip: true
                                    model: dataFilterDialog.draftFilterResults.values || []
                                    delegate: CheckBox {
                                        required property int index
                                        required property var modelData
                                        width: valueOptionsList.width
                                        objectName: "dataViewFilterValueOption_" + index
                                        text: String(modelData.label)
                                        checked: dataFilterDialog.valueIsSelected(String(modelData.key))
                                        Accessible.name: "Include value " + text + " for " + dataFilterDialog.columnName
                                        Accessible.description: "Toggle this distinct value in the Data-view preview filter."
                                        onToggled: dataFilterDialog.setValueSelected(String(modelData.key), checked)
                                    }
                                }
                                Label {
                                    objectName: "dataViewFilterValueNotice"
                                    Layout.fillWidth: true
                                    visible: !dataFilterDialog.compactLayout
                                    text: dataFilterDialog.valueSearchSummary()
                                    wrapMode: Text.WordWrap
                                    Accessible.name: text
                                }
                            }
                            ColumnLayout {
                                spacing: 8
                                Label {
                                    Layout.fillWidth: true
                                    text: "Filter rows shown in Data view. This does not change the loaded table, report calculations, or saved Power Query steps."
                                    wrapMode: Text.WordWrap
                                }
                                ComboBox {
                                    id: filterOperator
                                    objectName: "dataViewFilterOperator"
                                    Accessible.name: "Condition operator for " + dataFilterDialog.columnName
                                    Layout.fillWidth: true
                                    textRole: "label"
                                    valueRole: "value"
                                    model: [
                                        { label: "Equals", value: "equals" },
                                        { label: "Does not equal", value: "not_equals" },
                                        { label: "Contains", value: "contains" },
                                        { label: "Does not contain", value: "does_not_contain" },
                                        { label: "Begins with", value: "begins_with" },
                                        { label: "Ends with", value: "ends_with" },
                                        { label: "Greater than", value: "greater_than" },
                                        { label: "Greater than or equal", value: "greater_than_or_equal" },
                                        { label: "Less than", value: "less_than" },
                                        { label: "Less than or equal", value: "less_than_or_equal" },
                                        { label: "Is blank", value: "is_blank" },
                                        { label: "Is not blank", value: "is_not_blank" },
                                        { label: "Is null", value: "is_null" },
                                        { label: "Is not null", value: "is_not_null" }
                                    ]
                                }
                                TextField {
                                    id: filterValue
                                    objectName: "dataViewFilterValue"
                                    Accessible.name: "Condition value for " + dataFilterDialog.columnName
                                    Layout.fillWidth: true
                                    placeholderText: "Value"
                                    maximumLength: 2_000
                                    enabled: ["is_null", "is_not_null", "is_blank", "is_not_blank"].indexOf(
                                        String(filterOperator.currentValue)
                                    ) < 0
                                }
                            }
                        }
                        Connections {
                            target: root.appController.dataModel
                            function onFilterChanged() { dataFilterDialog.refreshFilterResults() }
                            function onDataReplaced() { dataFilterDialog.refreshFilterResults() }
                        }
                    }

                    footer: RowLayout {
                        spacing: 8
                        Button {
                            objectName: "dataViewClearColumnFilter"
                            text: "Clear filter"
                            Accessible.name: "Clear filter for " + dataFilterDialog.columnName
                            enabled: root.appController.dataModel.activeFilterColumns.indexOf(
                                dataFilterDialog.columnName
                            ) >= 0
                            onClicked: {
                                root.appController.dataModel.clearColumnFilter(
                                    dataFilterDialog.columnName
                                )
                                dataFilterDialog.close()
                            }
                        }
                        Item { Layout.fillWidth: true }
                        Button {
                            objectName: "dataViewCancelColumnFilter"
                            text: "Cancel"
                            Accessible.name: "Cancel filter changes for " + dataFilterDialog.columnName
                            onClicked: dataFilterDialog.reject()
                        }
                        Button {
                            objectName: "dataViewApplyColumnFilter"
                            text: "Apply filter"
                            Accessible.name: text + " for " + dataFilterDialog.columnName
                            Accessible.description: "Applying this tab replaces the current filter for this column."
                            onClicked: {
                                if (filterModeTabs.currentIndex === 0) {
                                    root.appController.dataModel.setColumnValueFilter(
                                        dataFilterDialog.columnName,
                                        dataFilterDialog.draftAllSelected,
                                        Object.keys(dataFilterDialog.draftValueKeys)
                                    )
                                } else {
                                    root.appController.dataModel.setColumnFilter(
                                        dataFilterDialog.columnName,
                                        String(filterOperator.currentValue),
                                        filterValue.text
                                    )
                                }
                                dataFilterDialog.close()
                            }
                        }
                    }
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
                    objectName: "activeTableComboBox"
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
                    objectName: "dataViewImportButton"
                    text: root.appController.modelTables.length > 0 ? "Add table" : "Import data"
                    Accessible.name: "Add CSV, Excel, JSON, XML, or Parquet table"
                    background: Rectangle { radius: 4; color: parent.down ? "#0d665d" : (parent.hovered ? "#16897d" : "#107C71"); border.color: "#0d665d" }
                    contentItem: Text { text: parent.text; color: "#ffffff"; font.pixelSize: 10; font.weight: Font.DemiBold; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: root.appController.executeCommand("importData")
                }
                Button {
                    objectName: "transformDataButton"
                    visible: root.appController.sourceLoaded
                    text: "Transform data"
                    Accessible.name: "Open Power Query Editor for the active table"
                    Accessible.description: "Preview, add, remove, and reorder saved local cleaning steps. The supported custom-column formula syntax is an M-style subset."
                    background: Rectangle { radius: 4; color: parent.hovered ? "#edf5fb" : "#f7fafc"; border.color: "#c4dcec" }
                    contentItem: Text { text: parent.text; color: "#0067b8"; font.pixelSize: 10; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: root.appController.executeCommand("transformData")
                }
                Button {
                    id: dataViewFilterRowsButton
                    objectName: "dataViewFilterRowsButton"
                    visible: root.appController.sourceLoaded && root.appController.columnCount > 0
                    enabled: typeColumnCombo.currentText !== ""
                    text: {
                        const count = root.appController.dataModel.activeFilterColumns.length
                        return count > 0 ? "Filter rows (" + count + ")" : "Filter rows"
                    }
                    Accessible.name: "Filter data view rows"
                    Accessible.description: "Open Values or Condition for the selected column. This filter changes the Data view preview only; it does not change loaded model rows, report calculations, or saved Power Query steps. Use Transform data to save a row filter."
                    ToolTip.visible: hovered
                    ToolTip.text: "Temporary · Data view only. Use Transform data to save a row filter."
                    onClicked: {
                        dataFilterDialog.columnName = typeColumnCombo.currentText
                        dataFilterDialog.open()
                    }
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
                    objectName: "typeColumnCombo"
                    Layout.preferredWidth: 210
                    model: root.appController.headers || []
                    Accessible.name: "Column to change type"
                    onActivated: {
                        root.selectedColumnRequested(currentText)
                        dataPage.refreshColumnProfile()
                    }
                    onCurrentIndexChanged: dataPage.refreshColumnProfile()
                }
                ComboBox {
                    id: typeValueCombo
                    Layout.preferredWidth: 180
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
                    currentIndex: {
                        const selectedType = root.typeForColumn(typeColumnCombo.currentText)
                        const typeNames = ["text", "any", "whole_number", "decimal_number", "boolean", "date", "datetime", "time"]
                        const found = typeNames.indexOf(selectedType)
                        return found < 0 ? 0 : found
                    }
                    Accessible.name: "Selected Power BI column type"
                }
                Button {
                    text: "Apply type"
                    enabled: typeColumnCombo.currentText !== ""
                             && typeValueCombo.currentValue !== "any"
                    Accessible.name: "Apply type to selected column"
                    onClicked: root.appController.setColumnType(
                        typeColumnCombo.currentText,
                        typeValueCombo.currentValue
                    )
                }
                Item { Layout.fillWidth: true }
            }

            RowLayout {
                objectName: "dataViewColumnProfile"
                visible: root.appController.sourceLoaded && dataPage.activeColumnProfile.column !== undefined
                         && dataPage.height >= 320
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
                    text: "Null " + dataPage.activeColumnProfile.nullCount
                          + " (" + dataPage.activeColumnProfile.nullPercent + "%)"
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
                            const typedValue = !item.type || item.type === "text"
                                    ? String(item.value)
                                    : String(item.value) + " [" + item.type + "]"
                            return typedValue + " (" + item.count + ")"
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
                Layout.minimumHeight: 106
                Layout.minimumWidth: 0
                Layout.preferredWidth: 0
                Layout.maximumWidth: dataPage.width
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
                        Layout.minimumWidth: 0
                        Layout.preferredWidth: 0
                        syncView: tableView
                        clip: true
                        delegate: Rectangle {
                            required property int index
                            implicitHeight: 44
                            implicitWidth: Math.max(110, headerLabel.implicitWidth + 24)
                            color: "#f0f5f8"
                            border.color: "#e0e5e9"
                            Accessible.role: Accessible.Button
                            Accessible.name: root.columnNameAt(index) + ", "
                                    + root.typeForColumn(root.columnNameAt(index))
                                    + (root.appController.dataModel.sortColumn === root.columnNameAt(index)
                                       ? ", sorted " + root.appController.dataModel.sortDirection
                                       : "")
                            Accessible.description: "Click the column heading to sort. Use its filter button to filter Data view rows."
                            Text {
                                id: headerLabel
                                objectName: "dataColumnHeaderName_" + index
                                anchors.top: parent.top
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.topMargin: 5
                                anchors.leftMargin: 10
                                anchors.rightMargin: 24
                                text: root.columnNameAt(index)
                                color: "#465463"
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }
                            Text {
                                id: sortIndicator
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.topMargin: 4
                                anchors.rightMargin: 30
                                visible: root.appController.dataModel.sortColumn === root.columnNameAt(index)
                                text: root.appController.dataModel.sortDirection === "ascending"
                                      ? "↑" : "↓"
                                color: "#107c71"
                                font.pixelSize: 14
                                font.weight: Font.DemiBold
                            }
                            Text {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                anchors.leftMargin: 10
                                anchors.rightMargin: 8
                                anchors.bottomMargin: 4
                                text: {
                                    const selectedType = root.typeForColumn(root.columnNameAt(index))
                                    const labels = {
                                        text: "Text",
                                        any: "Any (mixed)",
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
                            TapHandler {
                                acceptedButtons: Qt.LeftButton
                                onTapped: function(eventPoint, button) {
                                    const topLeft = filterColumnButton.mapToItem(null, 0, 0)
                                    const bottomRight = filterColumnButton.mapToItem(
                                        null, filterColumnButton.width, filterColumnButton.height
                                    )
                                    const point = eventPoint.scenePosition
                                    const insideFilterButton = point.x >= topLeft.x
                                            && point.x <= bottomRight.x
                                            && point.y >= topLeft.y
                                            && point.y <= bottomRight.y
                                    if (!insideFilterButton)
                                        root.appController.dataModel.sortByColumn(index)
                                }
                            }
                            Button {
                                id: filterColumnButton
                                objectName: "dataViewFilterColumn_" + index
                                z: 2
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.topMargin: 4
                                width: 24
                                height: 23
                                hoverEnabled: true
                                text: root.appController.dataModel.activeFilterColumns.indexOf(root.columnNameAt(index)) >= 0
                                      ? "▼" : "▽"
                                Accessible.name: "Filter preview rows by " + root.columnNameAt(index)
                                Accessible.description: root.appController.dataModel.activeFilterColumns.indexOf(root.columnNameAt(index)) >= 0
                                        ? "A Data view filter is active. Open to change or clear it."
                                        : "Filter the rows shown in Data view."
                                ToolTip.visible: hovered
                                ToolTip.text: Accessible.description
                                background: Rectangle {
                                    radius: 3
                                    color: parent.hovered ? "#e1ebf1"
                                          : root.appController.dataModel.activeFilterColumns.indexOf(
                                                root.columnNameAt(index)
                                            ) >= 0 ? "#e5f2ef" : "#f7f9fa"
                                    border.color: root.appController.dataModel.activeFilterColumns.indexOf(
                                                      root.columnNameAt(index)
                                                  ) >= 0 ? "#95bcae" : "#d6dee4"
                                }
                                contentItem: Item {
                                    Icon {
                                        objectName: "dataViewFilterIcon"
                                        anchors.centerIn: parent
                                        width: 14
                                        height: 14
                                        name: "filter"
                                        color: root.appController.dataModel.activeFilterColumns.indexOf(
                                                   root.columnNameAt(index)
                                               ) >= 0 ? "#107c71" : "#526575"
                                    }
                                }
                                onClicked: {
                                    dataFilterDialog.columnName = root.columnNameAt(index)
                                    dataFilterDialog.open()
                                }
                            }
                        }
                    }

                    TableView {
                        id: tableView
                        objectName: "dataViewTable"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumHeight: 30
                        Layout.minimumWidth: 0
                        Layout.preferredWidth: 0
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

                    Connections {
                        target: root.appController.dataModel
                        function onPageChanged() {
                            tableView.contentY = 0
                        }
                        function onDataReplaced() {
                            tableView.contentX = 0
                            tableView.contentY = 0
                        }
                    }

                    RowLayout {
                        objectName: "dataViewPagingControls"
                        Layout.fillWidth: true
                        Layout.minimumHeight: 32
                        Layout.preferredHeight: 32
                        spacing: 6

                        Text {
                            objectName: "dataViewPageRange"
                            Layout.fillWidth: true
                            text: root.appController.dataModel.pageRange
                            color: "#526575"
                            font.pixelSize: 11
                            elide: Text.ElideRight
                            Accessible.name: text
                        }
                        Text {
                            objectName: "dataViewPageIndicator"
                            visible: root.appController.dataModel.pageCount > 0
                            text: "Page " + root.appController.dataModel.currentPage
                                  + " of " + root.appController.dataModel.pageCount
                            color: "#526575"
                            font.pixelSize: 11
                            Accessible.name: text
                        }
                        Button {
                            objectName: "dataViewPreviousPage"
                            text: "Previous"
                            Layout.minimumHeight: 32
                            Layout.preferredHeight: 32
                            Layout.maximumHeight: 32
                            enabled: root.appController.dataModel.canGoPrevious
                            Accessible.name: "Previous preview page"
                            onClicked: root.appController.dataModel.previousPage()
                        }
                        Button {
                            objectName: "dataViewNextPage"
                            text: "Next"
                            Layout.minimumHeight: 32
                            Layout.preferredHeight: 32
                            Layout.maximumHeight: 32
                            enabled: root.appController.dataModel.canGoNext
                            Accessible.name: "Next preview page"
                            onClicked: root.appController.dataModel.nextPage()
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
                text: "The table preview shows 500 rows per page; use Previous and Next to inspect all loaded rows. Use the funnel beside a column name to filter the Data view; use Transform data to save a Power Query filter. Column profiles use all rows in the active table."
                color: "#5d6975"
                font.pixelSize: 11
            }
            }
        }
    }
}
