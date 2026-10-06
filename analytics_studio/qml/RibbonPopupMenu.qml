import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Popup {
    id: root
    property string menuType: "commonSources"
    property var controller
    property var returnFocusItem: null
    property var navigatorTrigger: null
    property var navigatorFirstButton: null
    property var firstMenuButton: null
    property bool transferFocus: false
    readonly property var menuItems: {
        if (menuType === "commonSources")
            return [
                { label: "Power BI semantic models", icon: "databaseMultiple", action: "source.semanticModels" },
                { label: "Text/CSV", icon: "csv", action: "source.csv", enabled: true },
                { label: "Web", icon: "getData", action: "source.web" },
                { label: "OData feed", icon: "database", action: "source.odata" },
                { label: "Blank query", icon: "script", action: "source.blankQuery" },
                { divider: true },
                { label: "More…", icon: "add", action: "data.more" }
            ]
        if (menuType === "recentSources") {
            if (controller && controller.sourceLoaded)
                return [{ label: controller.sourceName, icon: "csv", action: "recent.csv", detail: "Text/CSV" }]
            return [{ label: "No recent sources", icon: "history", enabled: false,
                      detail: "Your recent data sources will appear here." }]
        }
        if (menuType === "moreVisuals")
            return [
                { label: "From AppSource", icon: "apps", action: "visuals.appSource", detail: "Browse more visuals" },
                { label: "From my files", icon: "open", action: "visuals.fromFiles", detail: "Import a visual file" }
            ]
        if (menuType === "buttons")
            return [
                { label: "Left arrow", icon: "arrow_left", action: "button.leftArrow" },
                { label: "Right arrow", icon: "arrow_right", action: "button.rightArrow" },
                { label: "Reset", icon: "reset", action: "button.reset" },
                { label: "Back", icon: "arrow_left", action: "button.back" },
                { label: "Information", icon: "about", action: "button.information" },
                { label: "Help", icon: "help", action: "button.help" },
                { label: "Bookmark", icon: "bookmark", action: "button.bookmark" },
                { label: "Blank", icon: "button", action: "button.blank" },
                { label: "Apply all slicers", icon: "checkmark", action: "button.applySlicers" },
                { label: "Clear all slicers", icon: "clear", action: "button.clearSlicers" },
                { label: "Navigator", icon: "navigation", submenu: true }
            ]
        return []
    }

    signal actionRequested(string action, string label, var focusTarget)

    width: menuType === "buttons" ? 246 : 286
    height: Math.min(menuType === "buttons" ? 492 : 440,
                     menuList.contentHeight + padding * 2)
    padding: 5
    modal: false
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    background: Rectangle {
        color: "#ffffff"
        border.color: "#c8d1d7"
        radius: 4
        Rectangle {
            anchors.fill: parent
            anchors.margins: 1
            color: "transparent"
            border.color: "#f0f2f4"
            radius: 3
        }
    }

    function openAt(overlayItem, trigger, focusTarget) {
        if (!overlayItem || !trigger)
            return
        parent = overlayItem
        menuList.positionViewAtBeginning()
        returnFocusItem = focusTarget || trigger
        transferFocus = false
        const point = trigger.mapToItem(overlayItem, 0, trigger.height)
        x = Math.max(7, Math.min(overlayItem.width - width - 7, point.x))
        y = Math.max(7, Math.min(overlayItem.height - height - 7, point.y))
        open()
    }

    onMenuItemsChanged: firstMenuButton = null
    onOpened: Qt.callLater(function() {
        if (firstMenuButton && firstMenuButton.enabled)
            firstMenuButton.forceActiveFocus()
    })

    function dispatch(action, label) {
        transferFocus = true
        actionRequested(action, label, returnFocusItem)
        close()
    }

    function openNavigator(trigger) {
        navigatorTrigger = trigger
        const point = trigger.mapToItem(parent, 0, 0)
        const rightSpace = parent.width - (x + width)
        navigatorPopup.x = rightSpace >= navigatorPopup.width + 8
                             ? x + width - 4
                             : Math.max(7, x - navigatorPopup.width + 4)
        navigatorPopup.y = Math.max(7, Math.min(parent.height - navigatorPopup.height - 7, point.y - 2))
        navigatorPopup.open()
    }

    onClosed: {
        navigatorPopup.close()
        if (!transferFocus && returnFocusItem) {
            const target = returnFocusItem
            Qt.callLater(function() {
                if (target.visible)
                    target.forceActiveFocus()
            })
        }
        transferFocus = false
    }

    contentItem: ListView {
        id: menuList
        clip: true
        model: root.menuItems
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        delegate: Item {
            id: menuRow
            required property int index
            required property var modelData
            width: menuList.width
            height: modelData.divider ? 8 : 31
            Rectangle {
                visible: Boolean(menuRow.modelData.divider)
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                height: 1
                color: "#e1e5e8"
            }
            Button {
                id: menuButton
                visible: !menuRow.modelData.divider
                anchors.fill: parent
                padding: 5
                enabled: menuRow.modelData.enabled !== false
                hoverEnabled: true
                focusPolicy: Qt.StrongFocus
                Accessible.name: String(menuRow.modelData.label || "")
                Accessible.description: menuRow.modelData.submenu ? "Open Navigator submenu" :
                        (menuRow.modelData.enabled === false ? "Not available in this release." :
                         (menuRow.modelData.detail || "Opens this menu action."))
                background: Rectangle {
                    color: !menuButton.enabled ? "transparent"
                           : (menuButton.down ? "#e7edf1" : (menuButton.hovered || menuButton.activeFocus ? "#f0f4f6" : "transparent"))
                    radius: 3
                    border.color: menuButton.activeFocus ? "#6b9ab8" : "transparent"
                }
                Component.onCompleted: {
                    if (menuRow.index === 0 && !menuRow.modelData.divider
                            && menuRow.modelData.enabled !== false)
                        root.firstMenuButton = menuButton
                }
                contentItem: RowLayout {
                    spacing: 10
                    Icon {
                        name: String(menuRow.modelData.icon || "report")
                        color: menuRow.modelData.enabled === false ? "#a8b1b8" : "#506879"
                        implicitWidth: 18
                        implicitHeight: 18
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        Text {
                            Layout.fillWidth: true
                            text: String(menuRow.modelData.label || "")
                            color: menuRow.modelData.enabled === false ? "#87939b" : "#314450"
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                        Text {
                            visible: Boolean(menuRow.modelData.detail)
                            Layout.fillWidth: true
                            text: String(menuRow.modelData.detail || "")
                            color: "#788691"
                            font.pixelSize: 9
                            elide: Text.ElideRight
                        }
                    }
                    Text {
                        visible: Boolean(menuRow.modelData.preview || menuRow.modelData.submenu)
                        text: menuRow.modelData.submenu ? "›" : "Preview"
                        color: menuRow.modelData.submenu ? "#60717d" : "#8a6d1d"
                        font.pixelSize: menuRow.modelData.submenu ? 17 : 9
                    }
                }
                Keys.onPressed: function(event) {
                    if (menuRow.modelData.submenu && event.key === Qt.Key_Right) {
                        root.openNavigator(menuButton)
                        event.accepted = true
                    }
                }
                onClicked: {
                    if (menuRow.modelData.submenu)
                        root.openNavigator(menuButton)
                    else if (menuRow.modelData.enabled !== false)
                        root.dispatch(String(menuRow.modelData.action || ""), String(menuRow.modelData.label || ""))
                }
            }
        }
    }

    Popup {
        id: navigatorPopup
        parent: root.parent
        width: 218
        height: 82
        padding: 4
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: "#ffffff"; border.color: "#c8d1d7"; radius: 4 }
        onOpened: if (root.navigatorFirstButton) root.navigatorFirstButton.forceActiveFocus()
        onClosed: {
            if (root.visible && root.navigatorTrigger) {
                const trigger = root.navigatorTrigger
                Qt.callLater(function() {
                    if (trigger.visible)
                        trigger.forceActiveFocus()
                })
            }
        }
        contentItem: ColumnLayout {
            id: navigatorList
            spacing: 1
            Repeater {
                model: [
                    { label: "Page navigator", action: "button.pageNavigator" },
                    { label: "Bookmark navigator", action: "button.bookmarkNavigator" }
                ]
                delegate: Button {
                    id: navigatorItem
                    required property int index
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: 36
                    Accessible.name: String(modelData.label)
                    focusPolicy: Qt.StrongFocus
                    Component.onCompleted: if (index === 0) root.navigatorFirstButton = navigatorItem
                    background: Rectangle {
                        color: navigatorItem.activeFocus || navigatorItem.hovered ? "#f0f4f6" : "transparent"
                        border.color: navigatorItem.activeFocus ? "#6b9ab8" : "transparent"
                        radius: 3
                    }
                    contentItem: Text {
                        text: String(modelData.label)
                        color: "#314450"
                        font.pixelSize: 11
                        leftPadding: 9
                        verticalAlignment: Text.AlignVCenter
                    }
                    Keys.onPressed: function(event) {
                        if (event.key === Qt.Key_Left || event.key === Qt.Key_Escape) {
                            navigatorPopup.close()
                            event.accepted = true
                        }
                    }
                    onClicked: root.dispatch(String(modelData.action), String(modelData.label))
                }
            }
        }
    }
}
