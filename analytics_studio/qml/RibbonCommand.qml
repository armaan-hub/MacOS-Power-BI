import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Item {
    id: root
    property string label: "Command"
    property string visibleLabel: ""
    property string accessibleLabel: ""
    property string iconName: "report"
    property color iconColor: "#647382"
    property string commandId: ""
    property string description: ""
    property string unavailableReason: ""
    property bool available: true
    property bool appearanceAvailable: false
    property bool hasDropdown: false
    property bool splitGetData: false
    property bool selected: false
    property int iconSize: 22
    property int commandWidth: 34
    readonly property string widestVisibleLine: {
        const labelText = visibleLabel.length > 0 ? visibleLabel : label
        const lines = labelText.split("\n")
        let widest = ""
        for (let i = 0; i < lines.length; ++i) {
            if (lines[i].length > widest.length)
                widest = lines[i]
        }
        return widest
    }
    signal triggered(string commandId, var sourceItem)
    signal dropdownTriggered(var sourceItem)
    implicitWidth: Math.max(commandWidth, Math.ceil(labelMetrics.advanceWidth) + 12)
    implicitHeight: 68
    width: implicitWidth
    height: implicitHeight

    TextMetrics {
        id: labelMetrics
        font.pixelSize: 11
        text: root.widestVisibleLine
    }

    HoverHandler { id: hover }
    ToolTip.visible: hover.hovered
    ToolTip.text: (root.label.length > 0 ? root.label : root.visibleLabel)
                  + (root.description.length > 0 ? "\n" + root.description : "")
                  + (root.unavailableReason.length > 0 ? "\n" + root.unavailableReason
                     : (!root.available && root.description.length === 0
                        ? "\nThis command is not available in this release." : ""))
    ToolTip.delay: 450

    Button {
        id: button
        anchors.fill: parent
        visible: !root.splitGetData
        enabled: root.available
        hoverEnabled: true
        padding: 2
        focusPolicy: Qt.StrongFocus
        Accessible.name: root.accessibleLabel.length > 0 ? root.accessibleLabel : root.label
        Accessible.description: root.description
                                + (root.unavailableReason.length > 0 ? " " + root.unavailableReason
                                   : (!root.available && root.description.length === 0
                                      ? " This command is not available in this release." : ""))
        onClicked: {
            if (root.available)
                root.triggered(root.commandId, button)
        }

        background: Rectangle {
            radius: 4
            color: !root.available ? "transparent"
                   : (button.down ? "#dfe7ed" : (button.hovered || root.selected ? "#edf1f5" : "transparent"))
            border.width: button.activeFocus ? 2 : (root.selected ? 1 : 0)
            border.color: button.activeFocus ? "#426b8b" : (root.selected ? "#c4d1db" : "transparent")
        }

        contentItem: ColumnLayout {
            spacing: 1
            Icon {
                Layout.alignment: Qt.AlignHCenter
                name: root.iconName
                color: root.selected ? "#0078D4" : root.iconColor
                opacity: root.available || root.appearanceAvailable ? 1 : 0.78
                implicitWidth: root.iconSize
                implicitHeight: root.iconSize
            }
            Text {
                Layout.fillWidth: true
                Layout.preferredHeight: 30
                Layout.minimumHeight: 30
                Layout.maximumHeight: 30
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                text: root.visibleLabel.length > 0 ? root.visibleLabel : root.label
                color: root.available || root.appearanceAvailable ? "#283a48" : "#65717b"
                font.pixelSize: 11
                maximumLineCount: 2
                wrapMode: Text.WordWrap
            }
            Text {
                visible: root.hasDropdown
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredHeight: root.hasDropdown ? 8 : 0
                Layout.minimumHeight: root.hasDropdown ? 8 : 0
                Layout.maximumHeight: root.hasDropdown ? 8 : 0
                text: "⌄"
                color: root.available || root.appearanceAvailable ? "#45515A" : "#78838C"
                font.pixelSize: 9
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
        }
    }

    Column {
        anchors.fill: parent
        visible: root.splitGetData
        spacing: 0

        Button {
            id: getDataPrimaryButton
            width: parent.width
            height: 41
            enabled: root.available
            hoverEnabled: true
            focusPolicy: Qt.StrongFocus
            Accessible.name: "Get data"
            Accessible.description: "Open the full Get Data connector picker."
            onClicked: if (root.available) root.triggered(root.commandId, getDataPrimaryButton)
            background: Rectangle {
                radius: 4
                color: getDataPrimaryButton.down ? "#dfe7ed"
                       : (getDataPrimaryButton.hovered ? "#edf1f5" : "transparent")
                border.width: getDataPrimaryButton.activeFocus ? 2 : 0
                border.color: "#426b8b"
            }
            contentItem: Icon {
                name: root.iconName
                color: root.iconColor
                implicitWidth: root.iconSize
                implicitHeight: root.iconSize
            }
        }

        Button {
            id: getDataMenuButton
            width: parent.width
            height: parent.height - getDataPrimaryButton.height
            enabled: root.available
            hoverEnabled: true
            focusPolicy: Qt.StrongFocus
            Accessible.name: "Common data sources"
            Accessible.description: "Open the common data sources menu."
            onClicked: if (root.available) root.dropdownTriggered(getDataMenuButton)
            background: Rectangle {
                radius: 3
                color: getDataMenuButton.down ? "#dfe7ed"
                       : (getDataMenuButton.hovered ? "#edf1f5" : "transparent")
                border.width: getDataMenuButton.activeFocus ? 2 : 0
                border.color: "#426b8b"
            }
            contentItem: RowLayout {
                spacing: 1
                Text {
                    Layout.fillWidth: true
                    text: "Get\ndata"
                    color: "#283a48"
                    font.pixelSize: 9
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    wrapMode: Text.WordWrap
                    maximumLineCount: 2
                }
                Text {
                    text: "⌄"
                    color: "#45515a"
                    font.pixelSize: 10
                    verticalAlignment: Text.AlignVCenter
                    rightPadding: 2
                }
            }
        }
    }
}
