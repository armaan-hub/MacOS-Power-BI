import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Rectangle {
    id: root
    property string title: "Chart"
    property string visualName: title
    property string chartType: "column"
    property string emptyMessage: "No data is available yet."
    property var series: []
    property color seriesColor: "#0078D4"
    property bool selected: false
    property bool filterOnCategory: false
    signal requestedSelection(string visualName)
    signal categoryRequested(string label)

    function axisLabel(value) {
        const label = String(value || "")
        const monthly = label.match(/^(\d{4})-(\d{2})$/)
        if (root.visualName === "Monthly revenue" && monthly) {
            const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            const month = Number(monthly[2])
            if (month >= 1 && month <= 12)
                return months[month - 1] + " " + monthly[1].slice(-2)
        }
        return label.slice(0, 5)
    }
    implicitWidth: 330
    implicitHeight: 248
    radius: 7
    color: "#ffffff"
    border.width: selected || activeFocus ? 2 : 1
    border.color: selected ? "#0078D4" : (activeFocus ? "#718b9e" : "#d9e0e6")
    Accessible.name: title + " chart"
    Accessible.description: "Activate to select this chart. " + (series.length ? series.length + " categories." : "No data is available yet.")
    Accessible.role: Accessible.Button

    Keys.onReturnPressed: requestedSelection(visualName)
    Keys.onSpacePressed: requestedSelection(visualName)
    activeFocusOnTab: true

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: root.title
                color: "#283746"
                font.pixelSize: 14
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Text {
                text: root.selected ? "Selected" : ""
                color: "#426b8b"
                font.pixelSize: 10
            }
        }

        Canvas {
            id: chart
            Layout.fillWidth: true
            Layout.fillHeight: true
            Accessible.ignored: true

            onPaint: {
                const ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                const padLeft = 38
                const padRight = 8
                const padTop = 9
                const padBottom = 25
                const plotW = Math.max(12, width - padLeft - padRight)
                const plotH = Math.max(12, height - padTop - padBottom)
                const values = root.series || []
                let maxValue = 0
                for (let i = 0; i < values.length; ++i)
                    maxValue = Math.max(maxValue, Number(values[i].value) || 0)

                ctx.strokeStyle = "#e7ebef"
                ctx.lineWidth = 1
                for (let g = 0; g < 4; ++g) {
                    const y = padTop + plotH * g / 3
                    ctx.beginPath(); ctx.moveTo(padLeft, y); ctx.lineTo(width - padRight, y); ctx.stroke()
                }

                if (!values.length) {
                    ctx.fillStyle = "#5d6975"
                    ctx.font = "12px sans-serif"
                    ctx.textAlign = "center"
                    ctx.textBaseline = "middle"
                    const words = root.emptyMessage.split(" ")
                    const lines = []
                    let line = ""
                    for (let i = 0; i < words.length; ++i) {
                        const nextLine = line.length ? line + " " + words[i] : words[i]
                        if (line.length && ctx.measureText(nextLine).width > width - 24) {
                            lines.push(line)
                            line = words[i]
                        } else {
                            line = nextLine
                        }
                    }
                    if (line.length) lines.push(line)
                    const lineHeight = 16
                    const firstY = height / 2 - (lines.length - 1) * lineHeight / 2
                    for (let i = 0; i < lines.length; ++i)
                        ctx.fillText(lines[i], width / 2, firstY + i * lineHeight)
                    return
                }
                maxValue = maxValue || 1
                const color = root.seriesColor
                if (root.chartType === "line") {
                    ctx.strokeStyle = color
                    ctx.lineWidth = 2
                    ctx.beginPath()
                    for (let i = 0; i < values.length; ++i) {
                        const x = padLeft + plotW * (i + 0.5) / values.length
                        const y = padTop + plotH - plotH * (Number(values[i].value) || 0) / maxValue
                        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
                    }
                    ctx.stroke()
                    ctx.fillStyle = color
                    for (let i = 0; i < values.length; ++i) {
                        const x = padLeft + plotW * (i + 0.5) / values.length
                        const y = padTop + plotH - plotH * (Number(values[i].value) || 0) / maxValue
                        ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fill()
                    }
                } else if (root.chartType === "bar") {
                    const step = plotH / values.length
                    ctx.font = "10px sans-serif"
                    ctx.textAlign = "right"
                    ctx.textBaseline = "middle"
                    const labelStride = Math.max(1, Math.ceil(12 / step))
                    for (let i = 0; i < values.length; ++i) {
                        const label = String(values[i].label || "").slice(0, 7)
                        const y = padTop + i * step + step * 0.2
                        const barH = Math.max(3, step * 0.58)
                        const barW = plotW * (Number(values[i].value) || 0) / maxValue
                        ctx.fillStyle = root.seriesColor
                        ctx.fillRect(padLeft, y, barW, barH)
                        if (i % labelStride === 0) {
                            ctx.fillStyle = "#647382"
                            ctx.fillText(label, padLeft - 5, y + barH / 2, padLeft - 8)
                        }
                    }
                } else {
                    const step = plotW / values.length
                    ctx.font = "10px sans-serif"
                    ctx.textAlign = "center"
                    ctx.textBaseline = "top"
                    const labels = []
                    let maxLabelWidth = 0
                    for (let i = 0; i < values.length; ++i) {
                        const label = root.axisLabel(values[i].label)
                        labels.push(label)
                        maxLabelWidth = Math.max(maxLabelWidth, ctx.measureText(label).width)
                    }
                    const labelCount = Math.max(1, Math.min(values.length,
                        Math.floor(plotW / Math.max(1, maxLabelWidth + 6))))
                    const showLabel = []
                    for (let labelSlot = 0; labelSlot < labelCount; ++labelSlot) {
                        const labelIndex = labelCount === 1
                            ? values.length - 1
                            : Math.round(labelSlot * (values.length - 1) / (labelCount - 1))
                        showLabel[labelIndex] = true
                    }
                    for (let i = 0; i < values.length; ++i) {
                        const v = Number(values[i].value) || 0
                        const barH = plotH * v / maxValue
                        const barW = Math.max(5, step * 0.56)
                        const x = padLeft + i * step + (step - barW) / 2
                        ctx.fillStyle = root.seriesColor
                        ctx.fillRect(x, padTop + plotH - barH, barW, barH)
                        if (showLabel[i]) {
                            ctx.fillStyle = "#647382"
                            ctx.fillText(labels[i], x + barW / 2, padTop + plotH + 5)
                        }
                    }
                }
            }
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
        }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        onClicked: function(mouse) {
            root.requestedSelection(root.visualName)
            if (!root.filterOnCategory || !root.series || root.series.length === 0)
                return
            const point = chart.mapFromItem(root, mouse.x, mouse.y)
            const values = root.series
            let index = -1
            if (root.chartType === "bar") {
                const plotLeft = 38
                const plotWidth = Math.max(1, chart.width - 46)
                const plotTop = 9
                const plotHeight = Math.max(1, chart.height - 34)
                if (point.x >= plotLeft && point.x < plotLeft + plotWidth
                        && point.y >= plotTop && point.y < plotTop + plotHeight) {
                    const candidate = Math.floor((point.y - plotTop) / (plotHeight / values.length))
                    let maxValue = 0
                    for (let i = 0; i < values.length; ++i)
                        maxValue = Math.max(maxValue, Number(values[i].value) || 0)
                    maxValue = maxValue || 1
                    if (candidate >= 0 && candidate < values.length) {
                        const barWidth = plotWidth * (Number(values[candidate].value) || 0) / maxValue
                        if (point.x <= plotLeft + barWidth)
                            index = candidate
                    }
                }
            } else {
                const plotLeft = 38
                const plotWidth = Math.max(1, chart.width - 46)
                const plotTop = 9
                const plotHeight = Math.max(1, chart.height - 34)
                if (point.x >= plotLeft && point.x < plotLeft + plotWidth
                        && point.y >= plotTop && point.y < plotTop + plotHeight)
                    index = Math.floor((point.x - plotLeft) / (plotWidth / values.length))
            }
            if (index >= 0 && index < values.length)
                root.categoryRequested(String(values[index].label || ""))
        }
    }

    onSeriesChanged: chart.requestPaint()
    onSeriesColorChanged: chart.requestPaint()
    onChartTypeChanged: chart.requestPaint()
    onEmptyMessageChanged: chart.requestPaint()
    onSelectedChanged: chart.requestPaint()
}
