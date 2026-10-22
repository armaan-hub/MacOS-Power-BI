import QtQuick 6.5

Item {
    id: root
    property string kind: "text"
    implicitWidth: 22
    implicitHeight: 20
    width: implicitWidth
    height: implicitHeight

    readonly property bool isMeasure: kind === "measure"
    readonly property bool isDate: ["date", "datetime"].indexOf(kind) >= 0
    readonly property bool isTime: kind === "time"
    readonly property bool isNumber: ["whole_number", "decimal_number"].indexOf(kind) >= 0
    readonly property bool isBoolean: kind === "boolean"
    readonly property color accent: isMeasure ? "#1769aa"
            : isDate || isTime ? "#75549a"
            : isNumber ? "#147a6c"
            : isBoolean ? "#8a6511" : "#586d7a"
    readonly property color surface: isMeasure ? "#e8f2fb"
            : isDate || isTime ? "#f1edf7"
            : isNumber ? "#eaf5f2"
            : isBoolean ? "#f8f3e5" : "#eff2f4"

    Rectangle {
        anchors.fill: parent
        radius: 4
        color: root.surface
        border.color: Qt.darker(root.surface, 1.12)
        border.width: 1
    }

    Icon {
        visible: root.isDate
        anchors.centerIn: parent
        name: "calendar"
        color: root.accent
        implicitWidth: 13
        implicitHeight: 13
    }

    Text {
        visible: !root.isDate
        anchors.centerIn: parent
        text: root.isTime ? "◷"
              : root.isMeasure ? "ƒx"
              : root.isNumber ? "123"
              : root.isBoolean ? "✓" : "ABC"
        color: root.accent
        font.pixelSize: root.isNumber || (!root.isMeasure && !root.isBoolean && !root.isTime) ? 7 : 10
        font.weight: Font.DemiBold
        font.family: root.isMeasure ? "monospace" : "sans-serif"
    }
}
