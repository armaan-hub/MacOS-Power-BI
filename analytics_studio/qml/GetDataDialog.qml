import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Dialog {
    id: root
    property var controller
    property var returnFocusItem: null
    property string selectedCategory: "All"
    property string searchText: ""
    property string selectedSourceId: ""
    property string pendingSourceId: ""
    property var categories: ["All", "File", "Database", "Power BI", "Microsoft", "Online Services", "Other"]
    property var visibleSources: {
        const catalog = controller ? controller.dataSourceCatalog : []
        const query = searchText.trim().toLocaleLowerCase()
        const result = []
        const seen = ({})
        for (let i = 0; i < catalog.length; ++i) {
            const source = catalog[i]
            if (selectedCategory !== "All" && source.category !== selectedCategory)
                continue
            const key = String(source.name).toLocaleLowerCase()
            if (query.length > 0 && key.indexOf(query) < 0
                    && String(source.category).toLocaleLowerCase().indexOf(query) < 0)
                continue
            if (selectedCategory === "All") {
                if (seen[key]) {
                    const prior = result[seen[key] - 1]
                    if (prior.categories.indexOf(source.category) < 0)
                        prior.categories.push(source.category)
                    continue
                }
                seen[key] = result.length + 1
                const allRow = Object.assign({}, source)
                allRow.categories = [source.category]
                result.push(allRow)
            } else {
                const row = Object.assign({}, source)
                row.categories = [source.category]
                result.push(row)
            }
        }
        return result
    }
    modal: true
    focus: true
    parent: Overlay.overlay
    anchors.centerIn: Overlay.overlay
    width: Math.min(1080, Math.max(760, Overlay.overlay ? Overlay.overlay.width - 32 : 920))
    height: Math.min(700, Math.max(500, Overlay.overlay ? Overlay.overlay.height - 28 : 620))
    padding: 0
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    function chooseCategory(category) {
        selectedCategory = category
        reconcileSelection()
    }

    function reconcileSelection() {
        if (selectedSourceId.length === 0)
            return
        const rows = visibleSources
        for (let i = 0; i < rows.length; ++i) {
            if (rows[i].id === selectedSourceId)
                return
        }
        selectedSourceId = ""
    }

    function requestConnection() {
        if (selectedSourceId.length === 0)
            return
        const selected = selectedSource()
        if (!selected || !selected.implemented)
            return
        pendingSourceId = selectedSourceId
        close()
    }

    function selectedSource() {
        const rows = visibleSources
        for (let i = 0; i < rows.length; ++i) {
            if (rows[i].id === selectedSourceId)
                return rows[i]
        }
        return null
    }

    onOpened: {
        searchField.forceActiveFocus()
    }
    onClosed: {
        if (pendingSourceId.length > 0) {
            const id = pendingSourceId
            pendingSourceId = ""
            const focusTarget = returnFocusItem
            Qt.callLater(function() {
                if (controller)
                    controller.connectDataSource(id)
                if (focusTarget && focusTarget.visible)
                    focusTarget.forceActiveFocus()
            })
        } else {
            const focusTarget = returnFocusItem
            if (focusTarget)
                Qt.callLater(function() {
                    if (focusTarget.visible)
                        focusTarget.forceActiveFocus()
                })
        }
    }

    background: Rectangle {
        color: "#ffffff"
        border.color: "#b8c2cb"
        radius: 5
    }

    contentItem: ColumnLayout {
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 54
            color: "#ffffff"
            border.color: "#e0e4e7"
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 20
                anchors.rightMargin: 12
                Text {
                    Layout.fillWidth: true
                    text: "Get Data"
                    color: "#263847"
                    font.pixelSize: 19
                    font.weight: Font.DemiBold
                }
                Button {
                    text: "×"
                    implicitWidth: 32
                    implicitHeight: 32
                    Accessible.name: "Close Get Data"
                    onClicked: root.close()
                    background: Rectangle {
                        color: parent.hovered ? "#eef2f5" : "transparent"
                        radius: 3
                    }
                    contentItem: Text {
                        text: parent.text
                        color: "#52616d"
                        font.pixelSize: 20
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 56
            Layout.leftMargin: 18
            Layout.rightMargin: 18
            spacing: 14
            Text {
                text: "Choose a data source"
                color: "#334755"
                font.pixelSize: 13
                font.weight: Font.DemiBold
            }
            Item { Layout.fillWidth: true }
            TextField {
                id: searchField
                Layout.preferredWidth: Math.min(350, root.width * 0.4)
                Layout.preferredHeight: 34
                placeholderText: "Search data sources"
                Accessible.name: "Search data sources"
                onTextChanged: {
                    root.searchText = text
                    root.reconcileSelection()
                }
                background: Rectangle {
                    color: "#ffffff"
                    border.color: parent.activeFocus ? "#0878b9" : "#cbd3d9"
                    radius: 3
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 16
            Layout.rightMargin: 16
            Layout.bottomMargin: 14
            color: "#ffffff"
            border.color: "#cfd6dc"
            RowLayout {
                anchors.fill: parent
                spacing: 0

                Rectangle {
                    Layout.preferredWidth: Math.max(158, root.width * 0.18)
                    Layout.fillHeight: true
                    color: "#f4f6f8"
                    border.color: "#e2e6e9"
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 7
                        spacing: 2
                        Repeater {
                            model: root.categories
                            delegate: Button {
                                id: categoryButton
                                required property string modelData
                                Layout.fillWidth: true
                                Layout.preferredHeight: 38
                                padding: 7
                                hoverEnabled: true
                                Accessible.name: modelData + " category"
                                Accessible.description: modelData === root.selectedCategory ? "Selected category" : "Show " + modelData + " connectors"
                                background: Rectangle {
                                    radius: 3
                                    color: root.selectedCategory === modelData ? "#e4f1f8"
                                           : (categoryButton.activeFocus ? "#f1f7fa"
                                              : (categoryButton.hovered ? "#e9edf0" : "transparent"))
                                    border.color: categoryButton.activeFocus ? "#0878b9"
                                                 : (root.selectedCategory === modelData ? "#b6d6e8" : "transparent")
                                    border.width: categoryButton.activeFocus ? 1.5 : 1
                                }
                                contentItem: RowLayout {
                                    spacing: 8
                                    Rectangle {
                                        visible: root.selectedCategory === modelData
                                        Layout.preferredWidth: 3
                                        Layout.fillHeight: true
                                        radius: 2
                                        color: "#0078d4"
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: modelData
                                        color: "#314450"
                                        font.pixelSize: 11
                                        elide: Text.ElideRight
                                    }
                                }
                                onClicked: root.chooseCategory(modelData)
                            }
                        }
                        Item { Layout.fillHeight: true }
                    }
                }

                Rectangle { Layout.fillHeight: true; width: 1; color: "#dfe4e8" }

                ColumnLayout {
                    Layout.preferredWidth: Math.max(300, root.width * 0.32)
                    Layout.fillHeight: true
                    spacing: 0
                    ListView {
                        id: sourceList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: root.visibleSources
                        currentIndex: -1
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: Button {
                            id: sourceButton
                            required property var modelData
                            width: sourceList.width
                            height: 48
                            padding: 8
                            hoverEnabled: true
                            focusPolicy: Qt.StrongFocus
                            Accessible.name: String(modelData.name)
                            Accessible.description: String(modelData.categories.join(", "))
                                    + (modelData.previewStatus ? ", " + String(modelData.previewStatus) : "")
                                    + (modelData.implemented ? ", available" : ", not connected in this release")
                            ToolTip.visible: hovered && String(modelData.name).length > 22
                            ToolTip.text: String(modelData.name)
                            background: Rectangle {
                                color: root.selectedSourceId === modelData.id ? "#e6f2fa"
                                       : (sourceButton.activeFocus || sourceButton.hovered ? "#f3f7f9" : "#ffffff")
                                border.color: sourceButton.activeFocus ? "#0878b9"
                                             : (root.selectedSourceId === modelData.id ? "#89bedc" : "transparent")
                                border.width: sourceButton.activeFocus ? 1.5 : 1
                            }
                            contentItem: RowLayout {
                                spacing: 9
                                Icon {
                                    name: String(modelData.iconName)
                                    color: modelData.implemented ? "#0078d4" : "#657888"
                                    implicitWidth: 19
                                    implicitHeight: 19
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 1
                                    Text {
                                        Layout.fillWidth: true
                                        text: String(modelData.name)
                                        color: "#2d3d49"
                                        font.pixelSize: 11
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: String(modelData.categories.join(" · "))
                                        color: "#788691"
                                        font.pixelSize: 9
                                        elide: Text.ElideRight
                                    }
                                }
                                Text {
                                    visible: String(modelData.previewStatus).length > 0
                                    text: String(modelData.previewStatus)
                                    color: "#8a6d1d"
                                    font.pixelSize: 9
                                }
                            }
                            onClicked: root.selectedSourceId = String(modelData.id)
                        }
                        Text {
                            anchors.centerIn: parent
                            visible: sourceList.count === 0
                            text: "No matching data sources"
                            color: "#788691"
                            font.pixelSize: 11
                        }
                    }
                }

                Rectangle { Layout.fillHeight: true; width: 1; color: "#dfe4e8" }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumWidth: 225
                    Layout.margins: 18
                    spacing: 12
                    Loader {
                        Layout.preferredWidth: 38
                        Layout.preferredHeight: 38
                        sourceComponent: Rectangle {
                            radius: 5
                            color: root.selectedSource() && root.selectedSource().implemented ? "#e7f3fa" : "#f0f2f4"
                            Icon {
                                anchors.centerIn: parent
                                name: root.selectedSource() ? String(root.selectedSource().iconName) : "getData"
                                color: "#0078d4"
                                width: 22
                                height: 22
                            }
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: root.selectedSource() ? String(root.selectedSource().name) : "Select a data source"
                        color: "#263847"
                        font.pixelSize: 17
                        font.weight: Font.DemiBold
                        wrapMode: Text.Wrap
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: Boolean(root.selectedSource())
                        text: root.selectedSource() ? String(root.selectedSource().categories.join(" · ")) : ""
                        color: "#677783"
                        font.pixelSize: 10
                        wrapMode: Text.Wrap
                    }
                    Rectangle { Layout.fillWidth: true; height: 1; color: "#e0e5e8" }
                    Text {
                        Layout.fillWidth: true
                        visible: Boolean(root.selectedSource())
                        text: root.selectedSource()
                              ? (root.selectedSource().implemented
                                 ? (root.selectedSource().iconName === "excel"
                                    ? "Excel Workbook is ready. Choose an .xlsx or .xlsm file to import its first worksheet; the first non-empty row supplies column names."
                                    : "Text/CSV is ready. Choose a CSV file to import it into the current project.")
                                 : "This connector is listed for discovery; connection support is not implemented in Analytics Studio yet.")
                              : "Choose a connector from the list to see its status."
                        color: "#52636f"
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                        lineHeight: 1.25
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: Boolean(root.selectedSource()) && Boolean(root.selectedSource().previewStatus)
                        text: root.selectedSource()
                              ? String(root.selectedSource().previewStatus) + " connector"
                              : ""
                        color: "#8a6d1d"
                        font.pixelSize: 10
                    }
                    Item { Layout.fillHeight: true }
                    Text {
                        Layout.fillWidth: true
                        text: "Excel Workbook and Text/CSV have active importers in this build."
                        color: "#788691"
                        font.pixelSize: 9
                        wrapMode: Text.Wrap
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 48
            color: "#f7f8f9"
            border.color: "#e0e4e7"
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 17
                anchors.rightMargin: 18
                spacing: 8
                Item { Layout.fillWidth: true }
                Button {
                    text: "Cancel"
                    implicitWidth: 88
                    implicitHeight: 31
                    onClicked: root.close()
                    background: Rectangle {
                        color: parent.hovered ? "#f0f3f5" : "#ffffff"
                        border.color: parent.activeFocus ? "#0878b9" : "#bac5cc"
                        radius: 3
                    }
                    contentItem: Text {
                        text: parent.text
                        color: "#304351"
                        font.pixelSize: 11
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                Button {
                    text: "Connect"
                    implicitWidth: 100
                    implicitHeight: 31
                    enabled: Boolean(root.selectedSource()) && Boolean(root.selectedSource().implemented)
                    Accessible.name: "Connect to selected data source"
                    Accessible.description: enabled ? "Open the selected file picker." : "Only Excel Workbook and Text/CSV are available in this release."
                    onClicked: root.requestConnection()
                    background: Rectangle {
                        color: !parent.enabled ? "#e8ebed" : (parent.hovered ? "#006bb3" : "#0078d4")
                        border.color: parent.activeFocus ? "#005a9e" : "transparent"
                        radius: 3
                    }
                    contentItem: Text {
                        text: parent.text
                        color: parent.enabled ? "#ffffff" : "#849098"
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }
    }
}
