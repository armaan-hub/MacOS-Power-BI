import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Popup {
    id: root
    property var controller
    property var returnFocusItem: null
    property var firstShapeButton: null
    property bool transferFocus: false
    readonly property var shapeGroups: [
        { title: "Rectangles", shapes: ["Rectangle", "Rounded rectangle", "Snip upper-right corner", "Snip both upper corners", "Round upper-right corner", "Round both upper corners"] },
        { title: "Basic Shapes", shapes: ["Oval", "Capsule", "Triangle", "Right triangle", "Parallelogram", "Trapezoid", "Pentagon", "Hexagon", "Octagon", "Heart", "Callout", "Line"] },
        { title: "Block Arrows", shapes: ["Right arrow", "Left arrow", "Up arrow", "Down arrow", "Right pentagon arrow", "Chevron"] }
    ]

    signal shapeChosen(string shapeName)

    width: 336
    height: Math.min(452, parent ? parent.height - 16 : 436)
    padding: 5
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    background: Rectangle { color: "#ffffff"; border.color: "#c8d1d7"; radius: 4 }

    function openAt(overlayItem, trigger, focusTarget) {
        if (!overlayItem || !trigger)
            return
        parent = overlayItem
        returnFocusItem = focusTarget || trigger
        transferFocus = false
        const point = trigger.mapToItem(overlayItem, 0, trigger.height)
        x = Math.max(7, Math.min(overlayItem.width - width - 7, point.x))
        y = Math.max(7, Math.min(overlayItem.height - height - 7, point.y))
        open()
    }

    onOpened: Qt.callLater(function() {
        if (firstShapeButton)
            firstShapeButton.forceActiveFocus()
    })

    onClosed: {
        if (!transferFocus && returnFocusItem) {
            const target = returnFocusItem
            Qt.callLater(function() {
                if (target.visible)
                    target.forceActiveFocus()
            })
        }
        transferFocus = false
    }

    contentItem: Flickable {
        id: paletteFlick
        clip: true
        contentWidth: width
        contentHeight: groupColumn.childrenRect.height
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        Column {
            id: groupColumn
            width: paletteFlick.width
            spacing: 8
            Repeater {
                model: root.shapeGroups
                delegate: Column {
                    id: shapeGroupDelegate
                    required property var modelData
                    width: groupColumn.width
                    spacing: 4
                    Text {
                        text: String(modelData.title)
                        color: "#526571"
                        font.pixelSize: 10
                        font.weight: Font.DemiBold
                        leftPadding: 8
                        height: 19
                        verticalAlignment: Text.AlignVCenter
                    }
                    GridLayout {
                        width: parent.width - 8
                        anchors.horizontalCenter: parent.horizontalCenter
                        columns: 4
                        rowSpacing: 2
                        columnSpacing: 2
                        Repeater {
                            model: modelData.shapes
                            delegate: Button {
                                id: shapeButton
                                required property int index
                                required property string modelData
                                Layout.fillWidth: true
                                Layout.preferredWidth: 70
                                Layout.preferredHeight: 48
                                padding: 2
                                hoverEnabled: true
                                focusPolicy: Qt.StrongFocus
                                Accessible.name: String(modelData)
                                Accessible.description: "Choose " + String(modelData)
                                        + ". Adding shapes to the report is not implemented yet."
                                ToolTip.visible: hovered
                                ToolTip.text: String(modelData)
                                background: Rectangle {
                                    color: shapeButton.down ? "#dfeaf0"
                                           : (shapeButton.hovered || shapeButton.activeFocus ? "#eef4f7" : "transparent")
                                    border.color: shapeButton.activeFocus ? "#6b9ab8" : "transparent"
                                    radius: 3
                                }
                                contentItem: ShapeGlyph {
                                    anchors.centerIn: parent
                                    shapeName: String(shapeButton.modelData)
                                    width: 42
                                    height: 28
                                }
                                Component.onCompleted: {
                                    if (index === 0 && shapeGroupDelegate.modelData.title === "Rectangles")
                                        root.firstShapeButton = shapeButton
                                }
                                onClicked: {
                                    root.transferFocus = true
                                    root.shapeChosen(String(modelData))
                                    root.close()
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
