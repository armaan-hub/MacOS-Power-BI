import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Item {
    id: root
    property var appController

    Loader {
        anchors.fill: parent
        active: root.appController !== null && root.appController !== undefined
        sourceComponent: Component {
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 12

            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Text { text: "Data"; color: "#263645"; font.pixelSize: 20; font.weight: Font.DemiBold }
                    Text {
                        text: root.appController.sourceLoaded
                              ? root.appController.sourceName + " · " + Number(root.appController.rowCount).toLocaleString(Qt.locale(), 'f', 0) + " rows · " + root.appController.columnCount + " columns"
                              : "Preview a CSV, Excel, JSON, or XML source linked to this project"
                        color: "#5d6975"; font.pixelSize: 12; elide: Text.ElideRight
                    }
                }
                Button {
                    text: "Import data"
                    Accessible.name: "Import CSV, Excel, JSON, or XML data"
                    background: Rectangle { radius: 4; color: parent.down ? "#0d665d" : (parent.hovered ? "#16897d" : "#107C71"); border.color: "#0d665d" }
                    contentItem: Text { text: parent.text; color: "#ffffff"; font.pixelSize: 10; font.weight: Font.DemiBold; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: root.appController.executeCommand("importData")
                }
                Button {
                    text: "Refresh"
                    enabled: root.appController.sourceLoaded
                    Accessible.name: "Refresh linked data file"
                    background: Rectangle { radius: 4; color: parent.enabled ? (parent.hovered ? "#edf5fb" : "#f7fafc") : "#f6f7f8"; border.color: parent.enabled ? "#c4dcec" : "#d5dce1" }
                    contentItem: Text { text: parent.text; color: parent.enabled ? "#0067b8" : "#929ca3"; font.pixelSize: 10; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: root.appController.executeCommand("refreshSource")
                }
            }

            Rectangle {
                visible: !root.appController.sourceLoaded
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
                            implicitHeight: 34
                            implicitWidth: Math.max(110, headerLabel.implicitWidth + 24)
                        color: "#f0f5f8"
                            border.color: "#e0e5e9"
                            Text {
                                id: headerLabel
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 8
                                verticalAlignment: Text.AlignVCenter
                                text: display
                                color: "#465463"
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
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
                text: "Preview up to 500 rows. Report summaries recognize Revenue, Cost, Margin, Units, Order Date beginning YYYY-MM, and Region."
                color: "#5d6975"
                font.pixelSize: 11
            }
            }
        }
    }
}
