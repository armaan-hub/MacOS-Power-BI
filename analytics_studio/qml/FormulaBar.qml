import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

// Power BI style formula bar: line numbers, cancel/commit buttons, a code editor with an
// IntelliSense popup anchored under the caret, a parameter hint, and a yellow banner that
// shows the engine's own error text.  All logic lives in FormulaBarController (Python).
Rectangle {
    id: root
    objectName: "formulaBarRoot"
    property var bar: null
    readonly property bool barActive: bar !== null && bar.active
    property var completionItems: []
    property int completionIndex: 0
    property var signatureHint: ({})
    property string notice: ""
    property bool applying: false
    property bool typed: false
    readonly property alias editor: editor
    readonly property string bannerText: notice !== "" ? notice : (bar ? bar.error : "")
    readonly property int lineHeight: 18

    visible: barActive
    color: "#ffffff"
    border.color: "#d4d8dc"
    border.width: 1
    Layout.fillWidth: true
    Layout.preferredHeight: visible ? contentColumn.implicitHeight + 2 : 0
    Layout.minimumHeight: Layout.preferredHeight
    Layout.maximumHeight: Layout.preferredHeight
    clip: false
    z: 5

    function loadFromBar() {
        if (!root.bar)
            return
        root.applying = true
        editor.text = root.bar.text
        root.applying = false
        root.typed = false
        root.notice = ""
        root.completionItems = []
        completionPopup.close()
        signaturePopup.close()
        if (root.bar.active && root.bar.focusRequested)
            Qt.callLater(function() {
                editor.forceActiveFocus()
                editor.select(root.bar.selectionStart, root.bar.selectionEnd)
            })
    }

    function commitFormula() {
        validateTimer.stop()
        root.notice = ""
        if (root.bar.commit())
            root.completionItems = []
    }

    function refreshAssist(invoked) {
        if (!root.bar || !root.bar.active)
            return
        const items = root.bar.completions(editor.text, editor.cursorPosition, invoked)
        root.completionItems = items
        root.completionIndex = 0
        const hint = root.bar.signature(editor.text, editor.cursorPosition)
        root.signatureHint = hint
        if (items.length > 0)
            completionPopup.open()
        else
            completionPopup.close()
        if (hint && hint.function)
            signaturePopup.open()
        else
            signaturePopup.close()
    }

    function afterEdit() {
        if (!root.bar || !root.bar.active)
            return
        if (root.typed) {
            root.typed = false
            root.refreshAssist(false)
        } else {
            completionPopup.close()
            root.signatureHint = root.bar.signature(editor.text, editor.cursorPosition)
            if (root.signatureHint && root.signatureHint.function && editor.activeFocus)
                signaturePopup.open()
            else
                signaturePopup.close()
        }
    }

    function acceptCompletion(index) {
        const position = index === undefined ? root.completionIndex : index
        if (position < 0 || position >= root.completionItems.length)
            return
        const item = root.completionItems[position]
        const result = root.bar.applyCompletion(editor.text, item)
        root.notice = result.message
        if (result.message !== "") {
            completionPopup.close()
            return
        }
        root.applying = true
        editor.text = result.text
        editor.cursorPosition = result.caret
        root.applying = false
        root.bar.setText(result.text)
        root.typed = false
        completionPopup.close()
        validateTimer.restart()
        Qt.callLater(root.afterEdit)
    }

    function hintHtml() {
        const hint = root.signatureHint
        if (!hint || !hint.function)
            return ""
        function esc(value) { return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") }
        const parts = []
        for (let index = 0; index < hint.parameters.length; ++index)
            parts.push(index === hint.activeParameter ? "<b>" + esc(hint.parameters[index]) + "</b>" : esc(hint.parameters[index]))
        let html = esc(hint.function) + "(" + parts.join(", ") + ")"
        if (hint.doc)
            html += "<br/><font color='#5f6b73'>" + esc(hint.doc) + "</font>"
        if (!hint.supported)
            html += "<br/><font color='#a15c00'>Not supported by this app yet.</font>"
        return html
    }

    Connections {
        target: root.bar
        ignoreUnknownSignals: true
        function onTextRevisionChanged() { root.loadFromBar() }
    }
    Component.onCompleted: if (root.barActive) root.loadFromBar()

    Timer {
        id: validateTimer
        interval: 350
        repeat: false
        onTriggered: if (root.bar && root.bar.active) root.bar.validate()
    }

    ColumnLayout {
        id: contentColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 1
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            spacing: 0

            Row {
                Layout.alignment: Qt.AlignTop
                Layout.leftMargin: 6
                Layout.topMargin: 3
                spacing: 2
                Button {
                    objectName: "formulaBarCancel"
                    width: 30; height: 28
                    focusPolicy: Qt.NoFocus
                    hoverEnabled: true
                    Accessible.name: "Cancel (Esc)"
                    ToolTip.visible: hovered
                    ToolTip.text: "Cancel (Esc)"
                    background: Rectangle { radius: 3; color: parent.hovered ? "#fde8e8" : "transparent" }
                    contentItem: Text {
                        text: "✕"
                        color: "#c42b1c"
                        font.pixelSize: 16
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: root.bar.cancel()
                }
                Button {
                    objectName: "formulaBarCommit"
                    width: 30; height: 28
                    focusPolicy: Qt.NoFocus
                    hoverEnabled: true
                    Accessible.name: "Commit (Enter)"
                    ToolTip.visible: hovered
                    ToolTip.text: "Commit (Enter)"
                    background: Rectangle { radius: 3; color: parent.hovered ? "#e5f4ea" : "transparent" }
                    contentItem: Text {
                        text: "✓"
                        color: "#107c10"
                        font.pixelSize: 17
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: root.commitFormula()
                }
            }

            Flickable {
                id: editorFlick
                Layout.fillWidth: true
                Layout.leftMargin: 6
                Layout.topMargin: 4
                Layout.bottomMargin: 4
                Layout.preferredHeight: Math.min(8, Math.max(1, editor.lineCount)) * root.lineHeight + 4
                contentWidth: editorRow.width
                contentHeight: editorRow.height
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                function ensureVisible(rect) {
                    if (contentY >= rect.y)
                        contentY = rect.y
                    else if (contentY + height <= rect.y + rect.height)
                        contentY = rect.y + rect.height - height
                }

                Row {
                    id: editorRow
                    spacing: 8
                    width: Math.max(editorFlick.width, 40 + editor.contentWidth + 40)
                    Column {
                        id: lineNumbers
                        objectName: "formulaBarLineNumbers"
                        width: 18
                        Repeater {
                            model: editor.lineCount
                            delegate: Text {
                                required property int index
                                width: 18
                                height: root.lineHeight
                                text: String(index + 1)
                                horizontalAlignment: Text.AlignRight
                                verticalAlignment: Text.AlignVCenter
                                color: "#6b7780"
                                font.family: "Menlo"
                                font.pixelSize: 11
                            }
                        }
                    }
                    TextEdit {
                        id: editor
                        objectName: "formulaBarEditor"
                        width: Math.max(200, editorFlick.width - 40)
                        height: Math.max(root.lineHeight, contentHeight)
                        font.family: "Menlo"
                        font.pixelSize: 12
                        color: "#1f2a33"
                        selectionColor: "#bcd9f5"
                        selectedTextColor: "#1f2a33"
                        wrapMode: TextEdit.NoWrap
                        selectByMouse: true
                        persistentSelection: false
                        activeFocusOnTab: true
                        Accessible.role: Accessible.EditableText
                        Accessible.name: "DAX formula"
                        Accessible.description: "Type Name = expression. Enter commits, Shift+Enter adds a line, Escape cancels."
                        onCursorRectangleChanged: editorFlick.ensureVisible(cursorRectangle)
                        onTextChanged: {
                            if (root.applying)
                                return
                            root.typed = true
                            root.notice = ""
                            if (root.bar)
                                root.bar.setText(text)
                            validateTimer.restart()
                            Qt.callLater(root.afterEdit)
                        }
                        onCursorPositionChanged: Qt.callLater(root.afterEdit)
                        onActiveFocusChanged: if (!activeFocus) Qt.callLater(function() {
                            if (!editor.activeFocus) {
                                completionPopup.close()
                                signaturePopup.close()
                            }
                        })

                        Keys.onPressed: function(event) {
                            const popupOpen = completionPopup.opened && root.completionItems.length > 0
                            if (event.key === Qt.Key_Escape) {
                                if (popupOpen)
                                    completionPopup.close()
                                else
                                    root.bar.cancel()
                                event.accepted = true
                            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                                if (popupOpen) {
                                    root.acceptCompletion()
                                    event.accepted = true
                                } else if (event.modifiers & (Qt.ShiftModifier | Qt.AltModifier)) {
                                    editor.insert(editor.cursorPosition, "\n")
                                    event.accepted = true
                                } else {
                                    root.commitFormula()
                                    event.accepted = true
                                }
                            } else if (event.key === Qt.Key_Tab) {
                                if (popupOpen)
                                    root.acceptCompletion()
                                else
                                    editor.insert(editor.cursorPosition, "    ")
                                event.accepted = true
                            } else if (popupOpen && event.key === Qt.Key_Down) {
                                root.completionIndex = Math.min(root.completionItems.length - 1, root.completionIndex + 1)
                                completionList.positionViewAtIndex(root.completionIndex, ListView.Contain)
                                event.accepted = true
                            } else if (popupOpen && event.key === Qt.Key_Up) {
                                root.completionIndex = Math.max(0, root.completionIndex - 1)
                                completionList.positionViewAtIndex(root.completionIndex, ListView.Contain)
                                event.accepted = true
                            } else if (event.key === Qt.Key_Space && (event.modifiers & Qt.ControlModifier)) {
                                root.refreshAssist(true)
                                event.accepted = true
                            }
                        }
                    }
                }
            }
        }

        Rectangle {
            objectName: "formulaBarBanner"
            visible: root.bannerText !== ""
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? 24 : 0
            color: "#fff4ce"
            border.color: "#ecdca0"
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                spacing: 6
                Rectangle {
                    Layout.preferredWidth: 14; Layout.preferredHeight: 14
                    radius: 7
                    color: "#d9a300"
                    Text { anchors.centerIn: parent; text: "!"; color: "#ffffff"; font.pixelSize: 10; font.bold: true }
                }
                Text {
                    objectName: "formulaBarBannerText"
                    Layout.fillWidth: true
                    text: root.bannerText
                    color: "#3b3a39"
                    font.pixelSize: 11
                    elide: Text.ElideRight
                    Accessible.name: text
                    Accessible.role: Accessible.AlertMessage
                }
            }
        }
    }

    // ---- IntelliSense list: anchored under the caret -------------------------------------
    Popup {
        id: completionPopup
        objectName: "formulaBarCompletionPopup"
        parent: editor
        x: Math.min(editor.cursorRectangle.x, Math.max(0, editorFlick.width - width))
        y: editor.cursorRectangle.y + editor.cursorRectangle.height + 2
        padding: 0
        focus: false
        modal: false
        closePolicy: Popup.NoAutoClose
        width: 330 + (docPanel.visible ? docPanel.width : 0)
        height: Math.min(10, Math.max(1, root.completionItems.length)) * 24 + 2
        background: Rectangle { color: "#ffffff"; border.color: "#b6bec4"; radius: 2 }
        contentItem: Row {
            ListView {
                id: completionList
                objectName: "formulaBarCompletionList"
                width: 330
                height: parent.height
                clip: true
                model: root.completionItems
                currentIndex: root.completionIndex
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Rectangle {
                    id: itemRow
                    required property int index
                    required property var modelData
                    width: ListView.view.width
                    height: 24
                    readonly property bool selected: index === root.completionIndex
                    color: selected ? "#cfe4f7" : (hoverArea.containsMouse ? "#eef4fa" : "transparent")
                    objectName: "formulaBarCompletionItem_" + modelData.label
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 6
                        anchors.rightMargin: 6
                        spacing: 6
                        Item {
                            Layout.preferredWidth: 20; Layout.preferredHeight: 18
                            Text {
                                visible: modelData.kind === "function" || modelData.kind === "keyword"
                                anchors.centerIn: parent
                                text: modelData.kind === "function" ? "fx" : "abc"
                                font.italic: modelData.kind === "function"
                                font.bold: true
                                font.pixelSize: 11
                                color: modelData.supported ? "#6b3fa0" : "#a8aeb3"
                            }
                            Icon {
                                visible: modelData.kind === "table" || modelData.kind === "column" || modelData.kind === "measure"
                                anchors.centerIn: parent
                                implicitWidth: 15; implicitHeight: 15
                                name: modelData.kind === "table" ? "table" : (modelData.kind === "measure" ? "quickMeasure" : "bar")
                                color: modelData.kind === "measure" ? "#c65911" : "#107c71"
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: modelData.display !== undefined ? modelData.display : modelData.label
                            color: modelData.supported ? "#1f2a33" : "#9aa3a9"
                            font.pixelSize: 12
                            font.italic: !modelData.supported
                            elide: Text.ElideRight
                        }
                        Text {
                            visible: modelData.kind !== "function" || !modelData.supported
                            text: modelData.detail
                            color: "#7a858d"
                            font.pixelSize: 10
                            elide: Text.ElideRight
                            Layout.maximumWidth: 170
                        }
                        Text {
                            visible: modelData.doc !== "" && itemRow.selected
                            text: "›"
                            color: "#5f6b73"
                            font.pixelSize: 14
                        }
                    }
                    MouseArea {
                        id: hoverArea
                        anchors.fill: parent
                        hoverEnabled: true
                        onEntered: root.completionIndex = itemRow.index
                        onClicked: root.acceptCompletion(itemRow.index)
                    }
                }
            }
            Rectangle {
                id: docPanel
                objectName: "formulaBarCompletionDoc"
                readonly property var current: root.completionIndex < root.completionItems.length ? root.completionItems[root.completionIndex] : null
                visible: current !== null && current.doc !== ""
                width: 250
                height: parent.height
                color: "#f7f9fa"
                border.color: "#dfe4e7"
                Text {
                    anchors.fill: parent
                    anchors.margins: 8
                    wrapMode: Text.Wrap
                    textFormat: Text.StyledText
                    font.pixelSize: 11
                    color: "#1f2a33"
                    elide: Text.ElideRight
                    text: docPanel.current === null ? "" :
                          "<b>" + docPanel.current.signature.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") + "</b><br/><br/>" +
                          docPanel.current.doc +
                          (docPanel.current.supported ? "" : "<br/><br/><font color='#a15c00'>Not supported by this app yet.</font>")
                }
            }
        }
    }

    // ---- parameter hint ------------------------------------------------------------------
    Popup {
        id: signaturePopup
        objectName: "formulaBarSignaturePopup"
        parent: editor
        x: Math.min(editor.cursorRectangle.x, Math.max(0, editorFlick.width - width))
        y: editor.cursorRectangle.y - height - 4
        padding: 6
        focus: false
        modal: false
        closePolicy: Popup.NoAutoClose
        width: Math.min(520, hintText.implicitWidth + 12)
        background: Rectangle { color: "#fffef5"; border.color: "#c9c39a"; radius: 2 }
        contentItem: Text {
            id: hintText
            objectName: "formulaBarSignatureText"
            textFormat: Text.StyledText
            wrapMode: Text.Wrap
            width: 508
            font.pixelSize: 11
            color: "#1f2a33"
            text: root.hintHtml()
        }
    }
}
