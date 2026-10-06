import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Item {
    id: root
    property var appController
    signal importRequested()

    readonly property var tables: appController ? (appController.modelTables || []) : []
    readonly property var relationships: appController ? (appController.modelRelationships || []) : []
    readonly property var fields: appController ? (appController.headers || []) : []
    readonly property bool hasOneLoadedTable: appController
                                               && appController.sourceLoaded
                                               && tables.length === 1

    Accessible.name: "Read-only model workspace"
    Accessible.description: "Shows table and relationship metadata from the current project. Model editing is unavailable."

    Loader {
        anchors.fill: parent
        active: root.appController !== null && root.appController !== undefined
        sourceComponent: Component {
            ColumnLayout {
                anchors.fill: parent
                spacing: 0

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 48
                Layout.leftMargin: 18
                Layout.rightMargin: 18
                spacing: 10

                Icon {
                    name: "model"
                    color: "#526c80"
                    implicitWidth: 20
                    implicitHeight: 20
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Text {
                        text: "Model"
                        color: "#263645"
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                    }
                    Text {
                        text: "Read-only tables and relationship metadata"
                        color: "#596a79"
                        font.pixelSize: 10
                    }
                }

                Rectangle {
                    radius: 10
                    color: "#edf0f2"
                    implicitWidth: readOnlyLabel.implicitWidth + 16
                    implicitHeight: 22
                    Text {
                        id: readOnlyLabel
                        anchors.centerIn: parent
                        text: "Read only"
                        color: "#53616d"
                        font.pixelSize: 10
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: "#e4e6e8"
                border.color: "#d2d6da"
                clip: true

                ScrollView {
                    id: canvasScroll
                    anchors.fill: parent
                    anchors.margins: 16
                    clip: true
                    contentWidth: availableWidth
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    ScrollBar.vertical.policy: ScrollBar.AsNeeded

                    ColumnLayout {
                        width: canvasScroll.availableWidth
                        height: Math.max(implicitHeight, canvasScroll.availableHeight)
                        spacing: 14

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: !root.appController.sourceLoaded
                                               && root.tables.length === 0
                                               && root.relationships.length === 0
                            visible: !root.appController.sourceLoaded
                            implicitHeight: Math.max(128, importPrompt.implicitHeight + 28)
                            radius: 6
                            color: "#f8f9fa"
                            border.color: "#d3d8dc"
                            Accessible.name: "No data source loaded"
                            Accessible.description: root.appController.sourceWarning !== ""
                                                    ? root.appController.sourceWarning
                                                    : "Import a CSV, Excel, JSON, or XML file to load its table into the model."

                            RowLayout {
                                id: importPrompt
                                anchors.centerIn: parent
                                width: Math.min(parent.width - 28, implicitWidth)
                                spacing: 12

                                Icon {
                                    name: "getData"
                                    color: "#647b8e"
                                    implicitWidth: 22
                                    implicitHeight: 22
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 3
                                    Text {
                                        text: root.appController.sourceWarning !== ""
                                              ? "The linked source is unavailable"
                                              : "Add data to your model"
                                        color: "#344251"
                                        font.pixelSize: 13
                                        font.weight: Font.DemiBold
                                        wrapMode: Text.Wrap
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: root.appController.sourceWarning !== ""
                                              ? root.appController.sourceWarning
                                              : "Import a CSV, Excel, JSON, or XML file to load its table and fields."
                                        color: "#596a79"
                                        font.pixelSize: 11
                                        wrapMode: Text.Wrap
                                    }
                                }

                                Button {
                                    text: "Import data"
                                    Accessible.name: "Import data into the model"
                                    Accessible.description: "Choose a CSV, Excel, JSON, or XML file to link to this project."
                                    background: Rectangle { radius: 4; color: parent.hovered ? "#edf2f5" : "#f7f9fa"; border.color: "#cfd9df" }
                                    contentItem: Text { text: parent.text; color: "#405765"; font.pixelSize: 10; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                    onClicked: root.importRequested()
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            visible: root.appController.sourceLoaded
                            implicitHeight: sourceSummary.implicitHeight + 20
                            radius: 6
                            color: "#f8f9fa"
                            border.color: "#d3d8dc"
                            Accessible.name: "Loaded data source summary"

                            RowLayout {
                                id: sourceSummary
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 12

                                Icon { name: root.appController.sourceIconName; color: "#647b8e"; implicitWidth: 18; implicitHeight: 18 }
                                Text {
                                    Layout.fillWidth: true
                                    text: root.appController.sourceName
                                    color: "#344251"
                                    font.pixelSize: 12
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideMiddle
                                    Accessible.name: "Loaded source name"
                                }
                                Text {
                                    text: Number(root.appController.rowCount).toLocaleString(Qt.locale(), 'f', 0) + " rows"
                                    color: "#53616d"
                                    font.pixelSize: 10
                                    Accessible.name: Number(root.appController.rowCount).toLocaleString(Qt.locale(), 'f', 0) + " source rows"
                                }
                                Text {
                                    text: root.appController.columnCount + " columns"
                                    color: "#53616d"
                                    font.pixelSize: 10
                                    Accessible.name: root.appController.columnCount + " source columns"
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            visible: root.appController.sourceLoaded && !root.hasOneLoadedTable
                            implicitHeight: sourceFields.implicitHeight + 20
                            radius: 6
                            color: "#f8f9fa"
                            border.color: "#d3d8dc"
                            Accessible.name: "Fields in the loaded CSV"
                            Accessible.description: "These are source fields; table mapping is not available for multiple saved tables."

                            ColumnLayout {
                                id: sourceFields
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 7

                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Fields in loaded CSV"
                                        color: "#344251"
                                        font.pixelSize: 11
                                        font.weight: Font.DemiBold
                                    }
                                    Text {
                                        text: root.appController.columnCount + " columns"
                                        color: "#53616d"
                                        font.pixelSize: 10
                                    }
                                }

                                Flow {
                                    id: sourceFieldChips
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: implicitHeight
                                    spacing: 6
                                    Repeater {
                                        model: root.fields
                                        delegate: Rectangle {
                                            required property var modelData
                                            width: Math.min(sourceFieldChips.width, fieldLabel.implicitWidth + 18)
                                            height: 24
                                            radius: 4
                                            color: "#eef1f3"
                                            HoverHandler { id: fieldHover }
                                            ToolTip.visible: fieldHover.hovered
                                            ToolTip.text: "CSV field " + String(modelData)
                                            ToolTip.delay: 450
                                            Text {
                                                id: fieldLabel
                                                anchors.left: parent.left
                                                anchors.right: parent.right
                                                anchors.verticalCenter: parent.verticalCenter
                                                anchors.leftMargin: Math.min(9, parent.width / 4)
                                                anchors.rightMargin: Math.min(9, parent.width / 4)
                                                text: String(modelData)
                                                color: "#425261"
                                                font.pixelSize: 10
                                                Accessible.name: "CSV field " + String(modelData)
                                                elide: Text.ElideRight
                                                clip: true
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        Text {
                            visible: root.tables.length > 0
                            text: "Tables"
                            color: "#344251"
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                        }

                        Flow {
                            id: tableCards
                            Layout.fillWidth: true
                            Layout.preferredHeight: implicitHeight
                            spacing: 12
                            visible: root.tables.length > 0

                            Repeater {
                                model: root.tables

                                delegate: Rectangle {
                                    required property var modelData
                                    width: Math.max(270, Math.min(360, tableCards.width))
                                    height: root.hasOneLoadedTable ? 250 : 112
                                    radius: 6
                                    color: "#ffffff"
                                    border.color: "#cfd5da"
                                    Accessible.name: "Table " + String(modelData)
                                    Accessible.description: root.hasOneLoadedTable
                                                            ? Number(root.appController.rowCount).toLocaleString(Qt.locale(), 'f', 0) + " rows, "
                                                              + root.appController.columnCount + " columns. Fields are listed below."
                                                            : (root.appController.sourceLoaded
                                                               ? "Saved table metadata. Loaded data source details are shown separately."
                                                               : "Saved table metadata; no data source is currently loaded.")

                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 12
                                        spacing: 7

                                        RowLayout {
                                            Layout.fillWidth: true
                                            Icon { name: "table"; color: "#526c80"; implicitWidth: 18; implicitHeight: 18 }
                                            Text {
                                                Layout.fillWidth: true
                                                text: String(modelData)
                                                color: "#2f4050"
                                                font.pixelSize: 12
                                                font.weight: Font.DemiBold
                                                elide: Text.ElideRight
                                            }
                                            Text {
                                                text: "Table"
                                                color: "#596a79"
                                                font.pixelSize: 9
                                            }
                                        }

                                        Rectangle { Layout.fillWidth: true; height: 1; color: "#e2e6e9" }

                                        Text {
                                            visible: root.hasOneLoadedTable
                                            Layout.fillWidth: true
                                            text: Number(root.appController.rowCount).toLocaleString(Qt.locale(), 'f', 0)
                                                  + " rows  ·  " + root.appController.columnCount + " columns"
                                            color: "#53616d"
                                            font.pixelSize: 10
                                        }

                                        ListView {
                                            visible: root.hasOneLoadedTable
                                            Layout.fillWidth: true
                                            Layout.fillHeight: true
                                            model: root.hasOneLoadedTable ? root.fields : []
                                            clip: true
                                            spacing: 1
                                            Accessible.name: "Fields for " + String(modelData)
                                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                                            delegate: Rectangle {
                                                required property var modelData
                                                width: ListView.view.width
                                                height: 23
                                                color: "#f6f8f9"
                                                RowLayout {
                                                    anchors.fill: parent
                                                    anchors.leftMargin: 7
                                                    anchors.rightMargin: 7
                                                    Icon { name: "column"; color: "#718191"; implicitWidth: 13; implicitHeight: 13 }
                                                    Text {
                                                        Layout.fillWidth: true
                                                        text: String(modelData)
                                                        color: "#425261"
                                                        font.pixelSize: 10
                                                        elide: Text.ElideRight
                                                        Accessible.name: "Field " + String(modelData)
                                                    }
                                                }
                                            }
                                        }

                                        Text {
                                            visible: !root.hasOneLoadedTable
                                            Layout.fillWidth: true
                                            text: root.appController.sourceLoaded
                                                  ? "Saved table metadata. Field mapping is unavailable for multiple saved tables."
                                                  : "Saved project metadata; source fields are not loaded."
                                            color: "#596a79"
                                            font.pixelSize: 10
                                            wrapMode: Text.Wrap
                                        }
                                    }
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            visible: root.appController.sourceLoaded
                                     || root.tables.length > 0
                                     || root.relationships.length > 0
                            implicitHeight: relationshipContent.implicitHeight + 20
                            radius: 6
                            color: "#f8f9fa"
                            border.color: "#d3d8dc"
                            Accessible.name: "Relationship metadata"
                            Accessible.description: "Read-only relationship entries from the project. No connectors are inferred."

                            ColumnLayout {
                                id: relationshipContent
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 8

                                RowLayout {
                                    Layout.fillWidth: true
                                    Icon { name: "relationship"; color: "#526c80"; implicitWidth: 17; implicitHeight: 17 }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Relationships"
                                        color: "#344251"
                                        font.pixelSize: 12
                                        font.weight: Font.DemiBold
                                    }
                                    Text {
                                        text: String(root.relationships.length)
                                        color: "#596a79"
                                        font.pixelSize: 10
                                        Accessible.name: String(root.relationships.length) + " relationship metadata entries"
                                    }
                                }

                                Rectangle { Layout.fillWidth: true; height: 1; color: "#e2e6e9" }

                                Repeater {
                                    model: root.relationships
                                    delegate: Text {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        text: String(modelData)
                                        color: "#425261"
                                        font.pixelSize: 11
                                        wrapMode: Text.Wrap
                                        Accessible.name: "Relationship metadata: " + String(modelData)
                                    }
                                }

                                Text {
                                    visible: root.relationships.length === 0
                                    Layout.fillWidth: true
                                    text: "No relationship metadata is defined. Relationship editing is unavailable."
                                    color: "#596a79"
                                    font.pixelSize: 10
                                    wrapMode: Text.Wrap
                                    Accessible.name: text
                                }
                            }
                        }
                    }
                }
            }
            }
        }
    }
}
