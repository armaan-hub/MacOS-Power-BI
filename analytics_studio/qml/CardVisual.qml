import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Rectangle {
    id: root
    property string title: "Card"
    property string visualName: title
    property var cardData: ({ label: "", value: "Add a field", aggregation: "", highlight_value: "", has_highlights: false })
    readonly property string detailLabel: !cardData.label
            ? ""
            : String(cardData.aggregation) === "Measure"
                ? String(cardData.label)
                : String(cardData.aggregation) + " of " + String(cardData.label)
    property color valueColor: "#0078D4"
    property bool selected: false
    signal requestedSelection(string visualName)
    signal multipleSelectionRequested(string visualName)

    function requestSelection(modifiers) {
        if ((modifiers & Qt.ShiftModifier) !== 0) {
            root.multipleSelectionRequested(root.visualName)
            return false
        }
        root.requestedSelection(root.visualName)
        return true
    }

    implicitWidth: 250
    implicitHeight: 150
    radius: 7
    color: "#ffffff"
    border.width: selected || activeFocus ? 2 : 1
    border.color: selected ? "#0078D4" : (activeFocus ? "#718b9e" : "#d9e0e6")
    Accessible.name: title + ": " + String(cardData.value || "")
    Accessible.description: root.detailLabel || "Card visual. Add a field to show a value."
    Accessible.role: Accessible.Button
    activeFocusOnTab: true
    Keys.onReturnPressed: requestedSelection(visualName)
    Keys.onSpacePressed: requestedSelection(visualName)

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 3

        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: root.title
                color: "#283746"
                font.pixelSize: 13
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Text {
                text: root.selected ? "Selected" : ""
                color: "#426b8b"
                font.pixelSize: 10
            }
        }

        Item { Layout.fillHeight: true }
        Text {
            Layout.fillWidth: true
            text: String(root.cardData.value || "—")
            color: root.valueColor
            font.pixelSize: Math.min(34, Math.max(18, root.height * 0.23))
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        Text {
            Layout.fillWidth: true
            visible: Boolean(root.cardData.label)
            text: root.detailLabel
            color: "#647382"
            font.pixelSize: 10
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
        }
        Text {
            Layout.fillWidth: true
            visible: Boolean(root.cardData.has_highlights)
            text: "Selected: " + String(root.cardData.highlight_value || "—")
            color: "#647382"
            font.pixelSize: 10
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
        }
        Item { Layout.fillHeight: true }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        onClicked: function(mouse) { root.requestSelection(mouse.modifiers) }
    }
}
