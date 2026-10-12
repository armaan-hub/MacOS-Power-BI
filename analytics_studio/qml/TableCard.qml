import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Rectangle {
    id: root
    property string title: "Table"
    property string visualName: title
    property var tableData: ({ columns: [], rows: [], total_rows: 0 })
    property var columns: tableData.columns || []
    property var rows: tableData.rows || []
    property int totalRows: Number(tableData.total_rows || 0)
    property string tableError: String(tableData.error || "")
    property var activeFilters: []
    property bool selected: false
    property bool filterOnCategory: true
    signal requestedSelection(string visualName)
    signal multipleSelectionRequested(string visualName)
    signal categoryRequested(string label)

    function requestSelection(modifiers) {
        if ((modifiers & Qt.ShiftModifier) !== 0) {
            root.multipleSelectionRequested(root.visualName)
            return false
        }
        root.requestedSelection(root.visualName)
        return true
    }

    implicitWidth: 420
    implicitHeight: 270
    radius: 7
    color: "#ffffff"
    border.width: selected || activeFocus ? 2 : 1
    border.color: selected ? "#0078D4" : (activeFocus ? "#718b9e" : "#d9e0e6")
    Accessible.name: title + " table"
    Accessible.description: tableError.length > 0
            ? title + ". " + tableError
            : (columns.length
               ? title + " table with " + columns.length + " columns and " + totalRows + " rows."
               : title + " table. Add fields to display data.")
    Accessible.role: Accessible.Table
    activeFocusOnTab: true
    Keys.onReturnPressed: requestedSelection(visualName)
    Keys.onSpacePressed: requestedSelection(visualName)

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 7

        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: root.title
                color: "#283746"
                font.pixelSize: 14
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Text {
                text: root.selected ? "Selected" : ""
                color: "#426b8b"
                font.pixelSize: 10
            }
        }

        Text {
            Layout.fillWidth: true
            visible: root.tableError.length > 0
            text: root.tableError
            color: "#a33b32"
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }

        Flickable {
            id: tableView
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.tableError.length === 0
            clip: true
            contentWidth: Math.max(width, root.columns.length * 130)
            contentHeight: 28 + root.rows.length * 26
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            ScrollBar.horizontal: ScrollBar {}

            Column {
                id: tableContents
                width: tableView.contentWidth

                Rectangle {
                    width: parent.width
                    height: 28
                    color: "#eef3f6"
                    Row {
                        anchors.fill: parent
                        Repeater {
                            model: root.columns
                            delegate: Rectangle {
                                required property var modelData
                                width: 130
                                height: 28
                                color: "transparent"
                                Text {
                                    anchors.fill: parent
                                    anchors.leftMargin: 8
                                    anchors.rightMargin: 6
                                    verticalAlignment: Text.AlignVCenter
                                    text: String(modelData)
                                    color: "#344251"
                                    font.pixelSize: 11
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }

                Repeater {
                    model: root.rows
                    delegate: Item {
                        id: tableRow
                        objectName: "tableRow_" + root.visualName + "_" + index
                        required property int index
                        required property var modelData
                        property var rowData: modelData
                        width: tableView.contentWidth
                        height: 26

                        Rectangle {
                            anchors.fill: parent
                            color: tableRow.rowData.highlighted
                                    ? "#fff2cc"
                                    : (root.activeFilters.indexOf(String(tableRow.rowData.category)) !== -1
                                       ? "#dceef9"
                                       : (tableRow.index % 2 === 0 ? "#ffffff" : "#fafbfc"))
                        }
                        Row {
                            anchors.fill: parent
                            Repeater {
                                model: root.columns
                                delegate: Rectangle {
                                    required property int index
                                    width: 130
                                    height: 26
                                    color: "transparent"
                                    border.width: 0.5
                                    border.color: "#e7ebef"
                                    Text {
                                        anchors.fill: parent
                                        anchors.leftMargin: 8
                                        anchors.rightMargin: 6
                                        verticalAlignment: Text.AlignVCenter
                                        text: String(tableRow.rowData.values[index] || "")
                                        color: "#344251"
                                        font.pixelSize: 11
                                        elide: Text.ElideRight
                                    }
                                }
                            }
                        }
                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.LeftButton
                            onClicked: function(mouse) {
                                if (!root.requestSelection(mouse.modifiers))
                                    return
                                if (root.filterOnCategory && String(tableRow.rowData.category || ""))
                                    root.categoryRequested(String(tableRow.rowData.category))
                            }
                        }
                    }
                }
            }

            Text {
                anchors.centerIn: parent
                visible: root.tableError.length === 0
                        && root.columns.length > 0 && root.rows.length === 0
                text: "No rows match the current filters."
                color: "#647382"
                font.pixelSize: 11
            }
        }

        Text {
            Layout.fillWidth: true
            visible: root.columns.length === 0 || root.totalRows > root.rows.length
            text: root.columns.length === 0
                    ? "Add fields to display rows."
                    : "Showing " + root.rows.length + " of " + root.totalRows + " rows."
            color: "#647382"
            font.pixelSize: 10
            elide: Text.ElideRight
        }
    }
}
