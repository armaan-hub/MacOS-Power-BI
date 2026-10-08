import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Item {
    id: root
    property var appController
    signal importRequested()

    readonly property var tables: appController ? (appController.modelTables || []) : []
    readonly property var tableCatalog: appController ? (appController.tableCatalog || []) : []
    readonly property var relationships: appController ? (appController.modelRelationships || []) : []
    readonly property var measures: appController ? (appController.modelMeasures || []) : []
    readonly property var calculatedTables: tableCatalog.filter(function(table) {
        return table.calculatedColumns && table.calculatedColumns.length > 0
    })
    readonly property var fields: appController ? (appController.headers || []) : []
    readonly property bool hasOneLoadedTable: tableCatalog.filter(function(table) {
        return Boolean(table.loaded)
    }).length === 1

    Accessible.name: "Model workspace"
    Accessible.description: "Shows model tables, local measure results, and saved relationship definitions."

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
                        text: "Tables, measures, and relationships"
                        color: "#596a79"
                        font.pixelSize: 10
                    }
                }

                Rectangle {
                    radius: 10
                    color: "#e7f4f1"
                    implicitWidth: readOnlyLabel.implicitWidth + 16
                    implicitHeight: 22
                    Text {
                        id: readOnlyLabel
                        anchors.centerIn: parent
                        text: "Local measures"
                        color: "#107c71"
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
                                                    : "Import a CSV, Excel, JSON, XML, or Parquet file to load its table into the model."

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
                                              : "Import a CSV, Excel, JSON, XML, or Parquet file to load its table and fields."
                                        color: "#596a79"
                                        font.pixelSize: 11
                                        wrapMode: Text.Wrap
                                    }
                                }

                                Button {
                                    text: "Import data"
                                    Accessible.name: "Import data into the model"
                                    Accessible.description: "Choose a CSV, Excel, JSON, XML, or Parquet file to link to this project."
                                    background: Rectangle { radius: 4; color: parent.hovered ? "#edf2f5" : "#f7f9fa"; border.color: "#cfd9df" }
                                    contentItem: Text { text: parent.text; color: "#405765"; font.pixelSize: 10; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                    onClicked: root.importRequested()
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            visible: root.appController.sourceLoaded || root.measures.length > 0
                            implicitHeight: measuresContent.implicitHeight + 24
                            radius: 6
                            color: "#f8f9fa"
                            border.color: "#d3d8dc"
                            Accessible.name: "DAX measures"

                            ColumnLayout {
                                id: measuresContent
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 8

                                RowLayout {
                                    Layout.fillWidth: true
                                    Icon { name: "measure"; color: "#107c71"; implicitWidth: 17; implicitHeight: 17 }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Measures"
                                        color: "#344251"
                                        font.pixelSize: 12
                                        font.weight: Font.DemiBold
                                    }
                                    Text { text: String(root.measures.length); color: "#596a79"; font.pixelSize: 10 }
                                }

                                Rectangle { Layout.fillWidth: true; height: 1; color: "#e2e6e9" }

                                Repeater {
                                    model: root.measures
                                    delegate: ColumnLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        spacing: 3
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Text {
                                                Layout.fillWidth: true
                                                text: String(modelData.name)
                                                color: "#344251"
                                                font.pixelSize: 11
                                                font.weight: Font.DemiBold
                                                elide: Text.ElideRight
                                            }
                                            Text {
                                                text: String(modelData.value || "—")
                                                color: "#107c71"
                                                font.pixelSize: 11
                                                font.weight: Font.DemiBold
                                            }
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: String(modelData.expression)
                                            color: "#596a79"
                                            font.pixelSize: 10
                                            wrapMode: Text.Wrap
                                        }
                                        Text {
                                            visible: String(modelData.error || "").length > 0
                                            Layout.fillWidth: true
                                            text: String(modelData.error || "")
                                            color: "#a4262c"
                                            font.pixelSize: 10
                                            wrapMode: Text.Wrap
                                        }
                                        Rectangle { Layout.fillWidth: true; height: 1; color: "#e9edef" }
                                    }
                                }

                                Text {
                                    visible: root.measures.length === 0
                                    Layout.fillWidth: true
                                    text: "No measures yet. Use Modeling → New measure to create one."
                                    color: "#596a79"
                                    font.pixelSize: 10
                                    wrapMode: Text.Wrap
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            visible: root.calculatedTables.length > 0
                            implicitHeight: calculatedContent.implicitHeight + 24
                            radius: 6
                            color: "#f8f9fa"
                            border.color: "#d3d8dc"
                            Accessible.name: "DAX calculated columns"

                            ColumnLayout {
                                id: calculatedContent
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 8

                                RowLayout {
                                    Layout.fillWidth: true
                                    Icon { name: "column"; color: "#107c71"; implicitWidth: 17; implicitHeight: 17 }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Calculated columns"
                                        color: "#344251"
                                        font.pixelSize: 12
                                        font.weight: Font.DemiBold
                                    }
                                }

                                Rectangle { Layout.fillWidth: true; height: 1; color: "#e2e6e9" }

                                Repeater {
                                    model: root.calculatedTables
                                    delegate: ColumnLayout {
                                        required property var modelData
                                        property var tableData: modelData
                                        Layout.fillWidth: true
                                        spacing: 4
                                        Text {
                                            Layout.fillWidth: true
                                            text: String(tableData.displayName)
                                            color: "#425261"
                                            font.pixelSize: 10
                                            font.weight: Font.DemiBold
                                        }
                                        Repeater {
                                            model: tableData.calculatedColumns
                                            delegate: ColumnLayout {
                                                required property var modelData
                                                Layout.fillWidth: true
                                                spacing: 2
                                                Text {
                                                    Layout.fillWidth: true
                                                    text: String(modelData.name)
                                                    color: "#344251"
                                                    font.pixelSize: 10
                                                    font.weight: Font.DemiBold
                                                }
                                                Text {
                                                    Layout.fillWidth: true
                                                    text: String(modelData.expression)
                                                    color: "#596a79"
                                                    font.pixelSize: 10
                                                    wrapMode: Text.Wrap
                                                }
                                            }
                                        }
                                        Rectangle { Layout.fillWidth: true; height: 1; color: "#e9edef" }
                                    }
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
                            Accessible.name: "Fields in the active table"
                            Accessible.description: "These fields belong to the currently selected table."

                            ColumnLayout {
                                id: sourceFields
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 7

                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Fields in active table"
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
                                            ToolTip.text: "Field " + String(modelData)
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
                                                Accessible.name: "Field " + String(modelData)
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
                                model: root.tableCatalog.filter(function(table) {
                                    return table.kind !== "query" || Boolean(table.loadEnabled)
                                })

                                delegate: Rectangle {
                                    required property var modelData
                                    width: Math.max(270, Math.min(360, tableCards.width))
                                    height: modelData.loaded ? 250 : 112
                                    radius: 6
                                    color: "#ffffff"
                                    border.color: "#cfd5da"
                                    Accessible.name: "Table " + String(modelData.displayName)
                                    Accessible.description: modelData.loaded
                                                            ? Number(modelData.rowCount).toLocaleString(Qt.locale(), 'f', 0) + " rows, "
                                                              + Number(modelData.columnCount) + " columns. "
                                                              + (["calculated_table", "calendar", "calendar_auto"].indexOf(modelData.queryOperation) >= 0
                                                                 ? "Expression: " + String(modelData.queryExpression) + ". " : "")
                                                              + "Fields are listed below."
                                                            : "Table metadata is saved, but its source is unavailable."

                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 12
                                        spacing: 7

                                        RowLayout {
                                            Layout.fillWidth: true
                                            Icon { name: "table"; color: "#526c80"; implicitWidth: 18; implicitHeight: 18 }
                                            Text {
                                                Layout.fillWidth: true
                                                text: String(modelData.displayName)
                                                color: "#2f4050"
                                                font.pixelSize: 12
                                                font.weight: Font.DemiBold
                                                elide: Text.ElideRight
                                            }
                                            Text {
                                                text: ["calendar", "calendar_auto"].indexOf(modelData.queryOperation) >= 0
                                                      ? "Calendar table"
                                                      : (modelData.queryOperation === "calculated_table"
                                                      ? "Calculated table"
                                                      : (modelData.kind === "query" ? "Derived query" : "Table")
                                                      )
                                                color: "#596a79"
                                                font.pixelSize: 9
                                            }
                                        }

                                        Rectangle { Layout.fillWidth: true; height: 1; color: "#e2e6e9" }

                                        Text {
                                            visible: modelData.loaded
                                            Layout.fillWidth: true
                                            text: Number(modelData.rowCount).toLocaleString(Qt.locale(), 'f', 0)
                                                  + " rows  ·  " + Number(modelData.columnCount) + " columns"
                                            color: "#53616d"
                                            font.pixelSize: 10
                                        }

                                        Text {
                                            visible: modelData.loaded
                                                     && ["calculated_table", "calendar", "calendar_auto"].indexOf(modelData.queryOperation) >= 0
                                            Layout.fillWidth: true
                                            text: String(modelData.queryExpression)
                                            color: "#596a79"
                                            font.pixelSize: 9
                                            wrapMode: Text.Wrap
                                            maximumLineCount: 2
                                            elide: Text.ElideRight
                                        }

                                        Text {
                                            visible: Boolean(modelData.dateColumn)
                                            Layout.fillWidth: true
                                            text: "Date table: " + String(modelData.dateColumn)
                                            color: "#107c41"
                                            font.pixelSize: 9
                                            elide: Text.ElideRight
                                            Accessible.name: "Marked date column " + String(modelData.dateColumn)
                                        }

                                        ListView {
                                            visible: modelData.loaded
                                            Layout.fillWidth: true
                                            Layout.fillHeight: true
                                            model: modelData.loaded ? modelData.headers : []
                                            clip: true
                                            spacing: 1
                                            Accessible.name: "Fields for " + String(modelData.displayName)
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
                                            visible: !modelData.loaded
                                            Layout.fillWidth: true
                                            text: "Saved table metadata; its source is not currently loaded."
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
                            Accessible.name: "Saved relationships"
                            Accessible.description: "Saved relationships between model columns. Use Modeling to create, edit, or remove them."

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
                                        Accessible.name: String(root.relationships.length) + " saved relationships"
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
                                        Accessible.name: "Saved relationship: " + String(modelData)
                                    }
                                }

                                Text {
                                    visible: root.relationships.length === 0
                                    Layout.fillWidth: true
                                    text: "No relationships yet. Use Modeling → Manage relationships to connect columns from loaded tables. Active relationships can filter qualified measures; built-in charts and general visual filters still use the active table."
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
