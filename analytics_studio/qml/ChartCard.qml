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
    property var lineSeries: []
    property var highlightSeries: []
    property var highlightLineSeries: []
    property var gaugeData: ({})
    property var kpiData: ({})
    property var mapPoints: []
    property var highlightMapPoints: []
    property var scatterPoints: []
    property var highlightScatterPoints: []
    property color seriesColor: "#0078D4"
    property bool showDataLabels: false
    property bool showLegend: false
    property string seriesLabel: ""
    property string lineSeriesLabel: ""
    property bool selected: false
    property bool filterOnCategory: false
    signal requestedSelection(string visualName)
    signal multipleSelectionRequested(string visualName)
    signal categoryRequested(string label)

    function requestSelection(modifiers) {
        if ((modifiers & Qt.ShiftModifier) !== 0) {
            root.multipleSelectionRequested(root.visualName)
            return false
        }
        root.requestedSelection(root.visualName)
        return true
    }

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
    function highlightedValue(label) {
        const values = root.highlightSeries || []
        for (let i = 0; i < values.length; ++i) {
            if (String(values[i].label) === String(label))
                return Number(values[i].value) || 0
        }
        return null
    }
    function highlightedLineValue(label) {
        const values = root.highlightLineSeries || []
        for (let i = 0; i < values.length; ++i) {
            if (String(values[i].label) === String(label))
                return Number(values[i].value) || 0
        }
        return null
    }
    function mapLayout(points, canvasWidth, canvasHeight) {
        const plotLeft = 16
        const plotTop = 9
        const plotWidth = Math.max(1, canvasWidth - 32)
        const plotHeight = Math.max(1, canvasHeight - 35)
        let minLatitude = 90
        let maxLatitude = -90
        let minLongitude = 180
        let maxLongitude = -180
        let maxSize = 0
        for (let i = 0; i < (points || []).length; ++i) {
            const point = points[i]
            const latitude = Number(point.latitude)
            const longitude = Number(point.longitude)
            if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) continue
            minLatitude = Math.min(minLatitude, latitude)
            maxLatitude = Math.max(maxLatitude, latitude)
            minLongitude = Math.min(minLongitude, longitude)
            maxLongitude = Math.max(maxLongitude, longitude)
            maxSize = Math.max(maxSize, Number(point.size) || 0)
        }
        if (maxLatitude < minLatitude || maxLongitude < minLongitude)
            return { points: [], plotLeft: plotLeft, plotTop: plotTop, plotWidth: plotWidth, plotHeight: plotHeight }
        const latitudePadding = Math.max(0.8, (maxLatitude - minLatitude) * 0.12)
        const longitudePadding = Math.max(0.8, (maxLongitude - minLongitude) * 0.12)
        minLatitude = Math.max(-90, minLatitude - latitudePadding)
        maxLatitude = Math.min(90, maxLatitude + latitudePadding)
        minLongitude = Math.max(-180, minLongitude - longitudePadding)
        maxLongitude = Math.min(180, maxLongitude + longitudePadding)
        if (maxLatitude <= minLatitude) { minLatitude = Math.max(-90, minLatitude - 0.5); maxLatitude = Math.min(90, maxLatitude + 0.5) }
        if (maxLongitude <= minLongitude) { minLongitude = Math.max(-180, minLongitude - 0.5); maxLongitude = Math.min(180, maxLongitude + 0.5) }
        const positioned = []
        for (let i = 0; i < (points || []).length; ++i) {
            const point = points[i]
            const latitude = Number(point.latitude)
            const longitude = Number(point.longitude)
            if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) continue
            positioned.push({
                id: String(point.id || ""),
                label: String(point.label || ""),
                group: String(point.group || ""),
                size: Number(point.size) || 0,
                x: plotLeft + (longitude - minLongitude) / Math.max(0.000001, maxLongitude - minLongitude) * plotWidth,
                y: plotTop + (maxLatitude - latitude) / Math.max(0.000001, maxLatitude - minLatitude) * plotHeight,
                radius: 4 + 8 * Math.sqrt(Math.max(0, Number(point.size) || 0) / (maxSize || 1)),
            })
        }
        return { points: positioned, plotLeft: plotLeft, plotTop: plotTop, plotWidth: plotWidth, plotHeight: plotHeight }
    }
    function isStacked() {
        return root.chartType === "stackedBar" || root.chartType === "stackedColumn"
                || root.chartType === "bar100" || root.chartType === "column100"
                || root.chartType === "stackedArea" || root.chartType === "area100"
    }
    function isHundredPercent() {
        return root.chartType === "bar100" || root.chartType === "column100"
                || root.chartType === "area100"
    }
    function isStackedArea() {
        return root.chartType === "stackedArea" || root.chartType === "area100"
    }
    function hasMultiSeriesLegend() {
        return root.isStacked() || root.chartType === "ribbon"
    }
    function drawStackLegend(ctx, canvasWidth, values, padLeft) {
        const segments = values.length ? (values[0].segments || []) : []
        if (!root.showLegend || !segments.length)
            return
        ctx.font = "10px sans-serif"
        ctx.textAlign = "left"
        ctx.textBaseline = "middle"
        let legendX = padLeft
        let legendY = 11
        for (let i = 0; i < segments.length; ++i) {
            const label = String(segments[i].label || "")
            const available = Math.max(12, canvasWidth - legendX - 18)
            let textWidth = Math.min(ctx.measureText(label).width, 74)
            if (textWidth + 19 > available) {
                if (legendY < 23) {
                    legendY = 23
                    legendX = padLeft
                } else {
                    ctx.fillStyle = "#647382"
                    ctx.fillText("…", legendX, legendY, Math.max(8, canvasWidth - legendX - 3))
                    break
                }
            }
            const maxWidth = Math.max(1, Math.min(74, canvasWidth - legendX - 19))
            textWidth = Math.min(textWidth, maxWidth)
            ctx.fillStyle = root.pieColor(i)
            ctx.fillRect(legendX, legendY - 4, 8, 8)
            ctx.fillStyle = "#647382"
            ctx.fillText(label, legendX + 12, legendY, maxWidth)
            legendX += textWidth + 25
        }
    }
    function treemapLayout(values, x, y, width, height) {
        const items = []
        for (let i = 0; i < (values || []).length; ++i) {
            const value = Math.max(0, Number(values[i].value) || 0)
            if (value > 0)
                items.push({ label: String(values[i].label || ""), value: value })
        }
        items.sort(function(left, right) {
            return right.value - left.value || left.label.localeCompare(right.label)
        })
        const tiles = []
        function layout(group, left, top, groupWidth, groupHeight) {
            if (!group.length || groupWidth <= 0 || groupHeight <= 0)
                return
            if (group.length === 1) {
                tiles.push({
                    label: group[0].label,
                    value: group[0].value,
                    x: left,
                    y: top,
                    width: groupWidth,
                    height: groupHeight,
                })
                return
            }
            const total = group.reduce(function(sum, item) { return sum + item.value }, 0)
            let splitIndex = 1
            let leading = group[0].value
            let bestDistance = Math.abs(total / 2 - leading)
            let candidateTotal = leading
            for (let i = 2; i < group.length; ++i) {
                candidateTotal += group[i - 1].value
                const distance = Math.abs(total / 2 - candidateTotal)
                if (distance < bestDistance) {
                    bestDistance = distance
                    leading = candidateTotal
                    splitIndex = i
                }
            }
            const first = group.slice(0, splitIndex)
            const second = group.slice(splitIndex)
            const fraction = leading / total
            if (groupWidth >= groupHeight) {
                const firstWidth = groupWidth * fraction
                layout(first, left, top, firstWidth, groupHeight)
                layout(second, left + firstWidth, top, groupWidth - firstWidth, groupHeight)
            } else {
                const firstHeight = groupHeight * fraction
                layout(first, left, top, groupWidth, firstHeight)
                layout(second, left, top + firstHeight, groupWidth, groupHeight - firstHeight)
            }
        }
        layout(items, x, y, width, height)
        return tiles
    }
    function highlightedSegmentValue(category, segmentLabel) {
        const values = root.highlightSeries || []
        for (let i = 0; i < values.length; ++i) {
            if (String(values[i].label) !== String(category))
                continue
            const segments = values[i].segments || []
            for (let j = 0; j < segments.length; ++j) {
                if (String(segments[j].label) === String(segmentLabel))
                    return Number(segments[j].value) || 0
            }
        }
        return null
    }
    function valueLabel(value) {
        const number = Number(value)
        return isFinite(number) ? number.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(value)
    }
    function pieColor(index) {
        const colors = [String(root.seriesColor), "#70AD47", "#ED7D31", "#8064A2", "#5B9BD5", "#FFC000", "#4472C4", "#A5A5A5"]
        return colors[index % colors.length]
    }
    function scatterLayout(points, canvasWidth, canvasHeight) {
        const padLeft = 48
        const padRight = 12
        const padTop = root.showLegend ? 29 : 9
        const padBottom = 34
        const plotWidth = Math.max(12, canvasWidth - padLeft - padRight)
        const plotHeight = Math.max(12, canvasHeight - padTop - padBottom)
        let minX = Infinity
        let maxX = -Infinity
        let minY = Infinity
        let maxY = -Infinity
        const groups = []
        for (let i = 0; i < points.length; ++i) {
            const x = Number(points[i].x)
            const y = Number(points[i].y)
            if (!isFinite(x) || !isFinite(y))
                continue
            minX = Math.min(minX, x)
            maxX = Math.max(maxX, x)
            minY = Math.min(minY, y)
            maxY = Math.max(maxY, y)
            const group = String(points[i].group || "Series")
            if (groups.indexOf(group) === -1)
                groups.push(group)
        }
        if (!isFinite(minX)) {
            minX = 0; maxX = 1; minY = 0; maxY = 1
        }
        if (minX === maxX) { minX -= 0.5; maxX += 0.5 }
        if (minY === maxY) { minY -= 0.5; maxY += 0.5 }
        const positioned = []
        for (let i = 0; i < points.length; ++i) {
            const point = points[i]
            const x = Number(point.x)
            const y = Number(point.y)
            if (!isFinite(x) || !isFinite(y))
                continue
            const group = String(point.group || "Series")
            positioned.push({
                id: String(point.id || ""),
                label: String(point.label || ""),
                group: group,
                valueX: x,
                valueY: y,
                x: padLeft + plotWidth * (x - minX) / (maxX - minX),
                y: padTop + plotHeight - plotHeight * (y - minY) / (maxY - minY),
                colorIndex: groups.indexOf(group),
            })
        }
        return {
            plotLeft: padLeft, plotTop: padTop, plotWidth: plotWidth, plotHeight: plotHeight,
            minX: minX, maxX: maxX, minY: minY, maxY: maxY,
            points: positioned, groups: groups,
        }
    }
    function pieGeometry(canvasWidth, canvasHeight) {
        const withLegend = root.showLegend
        const centerX = withLegend ? canvasWidth * 0.30 : canvasWidth / 2
        const availableWidth = withLegend ? canvasWidth * 0.60 : canvasWidth
        return {
            centerX: centerX,
            centerY: canvasHeight / 2,
            radius: Math.max(8, Math.min(availableWidth, canvasHeight) * 0.40),
            legendX: canvasWidth * 0.60
        }
    }
    function pieCategoryAt(x, y, canvasWidth, canvasHeight) {
        const values = root.series || []
        const slices = []
        let total = 0
        for (let i = 0; i < values.length; ++i) {
            const value = Math.max(0, Number(values[i].value) || 0)
            if (value > 0) {
                slices.push({ label: String(values[i].label || ""), value: value })
                total += value
            }
        }
        if (!total)
            return ""
        const geometry = root.pieGeometry(canvasWidth, canvasHeight)
        const dx = x - geometry.centerX
        const dy = y - geometry.centerY
        const distance = Math.sqrt(dx * dx + dy * dy)
        if (distance > geometry.radius || (root.chartType === "donut" && distance < geometry.radius * 0.48))
            return ""
        const angle = Math.atan2(dy, dx)
        const relativeAngle = (angle + Math.PI * 2 + Math.PI / 2) % (Math.PI * 2)
        let accumulated = 0
        for (let i = 0; i < slices.length; ++i) {
            accumulated += slices[i].value / total * Math.PI * 2
            if (relativeAngle < accumulated)
                return slices[i].label
        }
        return slices[slices.length - 1].label
    }
    implicitWidth: 330
    implicitHeight: 248
    radius: 7
    color: "#ffffff"
    border.width: selected || activeFocus ? 2 : 1
    border.color: selected ? "#0078D4" : (activeFocus ? "#718b9e" : "#d9e0e6")
    Accessible.name: title + " chart"
    Accessible.description: "Activate to select this chart. " + (chartType === "map"
        ? ((mapPoints || []).length + " mapped locations.")
        : chartType === "kpi"
            ? ((kpiData || {}).has_value ? "Current " + valueLabel(kpiData.value) + "." : "No data is available yet.")
            : chartType === "scatter"
                ? (scatterPoints.length ? scatterPoints.length + " data points." : "No data is available yet.")
                : (series.length ? series.length + " categories." : "No data is available yet."))
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

        RowLayout {
            visible: root.showLegend && !root.hasMultiSeriesLegend()
                    && root.chartType !== "pie" && root.chartType !== "donut" && root.chartType !== "treemap"
                    && root.chartType !== "scatter" && root.chartType !== "gauge"
                    && root.chartType !== "kpi" && root.chartType !== "map"
                    && (root.series || []).length > 0
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? 14 : 0
            spacing: 5
            Rectangle {
                width: 9
                height: 9
                radius: 2
                color: root.seriesColor
            }
            Text {
                Layout.fillWidth: true
                text: root.seriesLabel || "Series"
                color: "#647382"
                font.pixelSize: 10
                elide: Text.ElideRight
            }
            Rectangle {
                visible: root.chartType === "lineClusteredColumn"
                width: visible ? 9 : 0
                height: 2
                color: "#C65911"
            }
            Text {
                visible: root.chartType === "lineClusteredColumn"
                text: root.lineSeriesLabel || "Line"
                color: "#647382"
                font.pixelSize: 10
                elide: Text.ElideRight
            }
        }

        Canvas {
            id: chart
            objectName: "chartCanvas_" + root.visualName
            Layout.fillWidth: true
            Layout.fillHeight: true
            Accessible.ignored: true

            onPaint: {
                const ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                const padLeft = 38
                const padRight = root.showDataLabels && root.chartType === "bar" ? 48 : 8
                const padTop = root.hasMultiSeriesLegend() && root.showLegend
                        ? Math.max(27, root.showDataLabels ? 20 : 0)
                        : (root.showDataLabels ? 20 : 9)
                const padBottom = 25
                const plotW = Math.max(12, width - padLeft - padRight)
                const plotH = Math.max(12, height - padTop - padBottom)
                const values = root.series || []
                const lineValues = root.lineSeries || []
                const highlightScatterPoints = root.highlightScatterPoints || []
                const hasScatterHighlights = root.chartType === "scatter" && highlightScatterPoints.length > 0
                const hasHighlights = (root.highlightSeries || []).length > 0 || hasScatterHighlights
                let maxValue = 0
                for (let i = 0; i < values.length; ++i)
                    maxValue = Math.max(maxValue, Number(values[i].value) || 0)
                if (root.chartType === "lineClusteredColumn") {
                    for (let i = 0; i < lineValues.length; ++i)
                        maxValue = Math.max(maxValue, Number(lineValues[i].value) || 0)
                }

                if (root.chartType !== "pie" && root.chartType !== "donut"
                        && root.chartType !== "gauge"
                        && root.chartType !== "kpi"
                        && root.chartType !== "map"
                        && root.chartType !== "funnel" && root.chartType !== "treemap") {
                    ctx.strokeStyle = "#e7ebef"
                    ctx.lineWidth = 1
                    for (let g = 0; g < 4; ++g) {
                        const y = padTop + plotH * g / 3
                        ctx.beginPath(); ctx.moveTo(padLeft, y); ctx.lineTo(width - padRight, y); ctx.stroke()
                    }
                }

                if (root.chartType === "gauge" ? !(root.gaugeData || {}).has_value
                        : root.chartType === "kpi" ? !(root.kpiData || {}).has_value
                        : root.chartType === "map" ? !(root.mapPoints || []).length
                        : root.chartType === "scatter" ? !(root.scatterPoints || []).length
                        : (root.chartType === "lineClusteredColumn"
                           ? !values.length || !lineValues.length
                           : !values.length)) {
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
                if (root.chartType === "gauge") {
                    const data = root.gaugeData || {}
                    const minimum = Number(data.minimum) || 0
                    let maximum = Number(data.maximum)
                    if (!Number.isFinite(maximum) || maximum <= minimum)
                        maximum = minimum + 1
                    const range = maximum - minimum
                    const rawValue = Number(data.value) || 0
                    const ratio = Math.max(0, Math.min(1, (rawValue - minimum) / range))
                    const centerX = width / 2
                    const centerY = height * 0.80
                    const radius = Math.max(12, Math.min(width * 0.40, height * 0.65))
                    const startAngle = Math.PI
                    const endAngle = Math.PI * 2
                    ctx.lineWidth = 14
                    ctx.lineCap = "round"
                    ctx.strokeStyle = "#e7ebef"
                    ctx.beginPath()
                    ctx.arc(centerX, centerY, radius, startAngle, endAngle)
                    ctx.stroke()
                    ctx.strokeStyle = color
                    ctx.beginPath()
                    ctx.arc(centerX, centerY, radius, startAngle, startAngle + Math.PI * ratio)
                    ctx.stroke()

                    const target = data.target === null || data.target === undefined
                            ? null : Number(data.target)
                    if (target !== null && Number.isFinite(target)) {
                        const targetRatio = Math.max(0, Math.min(1, (target - minimum) / range))
                        const angle = startAngle + Math.PI * targetRatio
                        const markerX = centerX + radius * Math.cos(angle)
                        const markerY = centerY + radius * Math.sin(angle)
                        ctx.strokeStyle = "#425466"
                        ctx.lineWidth = 2
                        ctx.beginPath()
                        ctx.moveTo(centerX + (radius - 10) * Math.cos(angle), centerY + (radius - 10) * Math.sin(angle))
                        ctx.lineTo(centerX + (radius + 10) * Math.cos(angle), centerY + (radius + 10) * Math.sin(angle))
                        ctx.stroke()
                        ctx.fillStyle = "#425466"
                        ctx.beginPath(); ctx.arc(markerX, markerY, 3, 0, Math.PI * 2); ctx.fill()
                    }

                    if (data.highlight_value !== null && data.highlight_value !== undefined) {
                        const selected = Number(data.highlight_value) || 0
                        const selectedRatio = Math.max(0, Math.min(1, (selected - minimum) / range))
                        const angle = startAngle + Math.PI * selectedRatio
                        const markerX = centerX + (radius + 12) * Math.cos(angle)
                        const markerY = centerY + (radius + 12) * Math.sin(angle)
                        ctx.fillStyle = "#C65911"
                        ctx.beginPath(); ctx.arc(markerX, markerY, 5, 0, Math.PI * 2); ctx.fill()
                    }

                    ctx.fillStyle = "#283746"
                    ctx.font = "bold 21px sans-serif"
                    ctx.textAlign = "center"
                    ctx.textBaseline = "middle"
                    ctx.fillText(root.valueLabel(rawValue), centerX, centerY - radius * 0.28)
                    ctx.fillStyle = "#647382"
                    ctx.font = "10px sans-serif"
                    ctx.textAlign = "left"
                    ctx.textBaseline = "top"
                    ctx.fillText(root.valueLabel(minimum), centerX - radius, centerY + 8)
                    ctx.textAlign = "right"
                    ctx.fillText(root.valueLabel(maximum), centerX + radius, centerY + 8)
                    if (target !== null && Number.isFinite(target)) {
                        ctx.textAlign = "center"
                        ctx.fillText("Target " + root.valueLabel(target), centerX, height - 4)
                    }
                } else if (root.chartType === "kpi") {
                    const data = root.kpiData || {}
                    const trend = data.trend || []
                    const plotLeft = 14
                    const plotRight = width - 14
                    const plotTop = 78
                    const plotBottom = height - 20
                    let minimum = Infinity
                    let maximum = -Infinity
                    for (let i = 0; i < trend.length; ++i) {
                        const value = Number(trend[i].value)
                        if (Number.isFinite(value)) {
                            minimum = Math.min(minimum, value)
                            maximum = Math.max(maximum, value)
                        }
                        const targetValue = trend[i].target === null || trend[i].target === undefined
                                ? NaN : Number(trend[i].target)
                        if (Number.isFinite(targetValue)) {
                            minimum = Math.min(minimum, targetValue)
                            maximum = Math.max(maximum, targetValue)
                        }
                    }
                    const selectedValue = Number(data.highlight_value)
                    if (Number.isFinite(selectedValue)) {
                        minimum = Math.min(minimum, selectedValue)
                        maximum = Math.max(maximum, selectedValue)
                    }
                    if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) {
                        minimum = 0
                        maximum = 1
                    }
                    if (maximum <= minimum) {
                        const padding = Math.max(1, Math.abs(maximum) * 0.08)
                        minimum -= padding
                        maximum += padding
                    }
                    const yFor = function(value) {
                        return plotBottom - (Number(value) - minimum) / (maximum - minimum) * (plotBottom - plotTop)
                    }
                    ctx.fillStyle = "#283746"
                    ctx.font = "bold 24px sans-serif"
                    ctx.textAlign = "left"
                    ctx.textBaseline = "top"
                    ctx.fillText(root.valueLabel(data.value), plotLeft, 6)
                    ctx.fillStyle = "#647382"
                    ctx.font = "10px sans-serif"
                    ctx.fillText(String(data.field || "Indicator") + " · " + String(data.label || ""), plotLeft, 39)
                    if (data.target !== null && data.target !== undefined) {
                        ctx.fillStyle = Number(data.value) >= Number(data.target) ? "#21835b" : "#a33b3b"
                        ctx.fillText("Target " + root.valueLabel(data.target), plotLeft, 55)
                    }
                    if (data.highlight_value !== null && data.highlight_value !== undefined) {
                        ctx.fillStyle = "#C65911"
                        ctx.textAlign = "right"
                        ctx.fillText("Selected " + root.valueLabel(data.highlight_value), plotRight, 16)
                    }
                    ctx.strokeStyle = "#e7ebef"
                    ctx.lineWidth = 1
                    ctx.beginPath(); ctx.moveTo(plotLeft, plotBottom); ctx.lineTo(plotRight, plotBottom); ctx.stroke()
                    if (trend.length) {
                        const step = trend.length > 1 ? (plotRight - plotLeft) / (trend.length - 1) : 0
                        const xFor = function(index) { return trend.length > 1 ? plotLeft + step * index : (plotLeft + plotRight) / 2 }
                        let hasTarget = false
                        ctx.strokeStyle = "#647382"
                        ctx.lineWidth = 1
                        ctx.beginPath()
                        for (let i = 0; i < trend.length; ++i) {
                            const targetValue = trend[i].target === null || trend[i].target === undefined
                                    ? NaN : Number(trend[i].target)
                            if (!Number.isFinite(targetValue)) continue
                            if (!hasTarget) ctx.moveTo(xFor(i), yFor(targetValue)); else ctx.lineTo(xFor(i), yFor(targetValue))
                            hasTarget = true
                        }
                        if (hasTarget) ctx.stroke()
                        const hasHighlights = (root.highlightSeries || []).length > 0
                        ctx.strokeStyle = hasHighlights ? "#b8c2cc" : root.seriesColor
                        ctx.lineWidth = 2.5
                        ctx.beginPath()
                        for (let i = 0; i < trend.length; ++i) {
                            const y = yFor(trend[i].value)
                            if (i === 0) ctx.moveTo(xFor(i), y); else ctx.lineTo(xFor(i), y)
                        }
                        ctx.stroke()
                        for (let i = 0; i < trend.length; ++i) {
                            const value = Number(trend[i].value) || 0
                            const selected = root.highlightedValue(trend[i].label)
                            ctx.fillStyle = selected !== null ? "#b8c2cc" : root.seriesColor
                            ctx.beginPath(); ctx.arc(xFor(i), yFor(value), 3, 0, Math.PI * 2); ctx.fill()
                            if (selected !== null) {
                                ctx.fillStyle = "#C65911"
                                ctx.beginPath(); ctx.arc(xFor(i), yFor(selected), 4, 0, Math.PI * 2); ctx.fill()
                            }
                        }
                        ctx.fillStyle = "#647382"
                        ctx.font = "9px sans-serif"
                        ctx.textAlign = "center"
                        ctx.textBaseline = "top"
                        const count = Math.min(trend.length, Math.max(1, Math.floor((plotRight - plotLeft) / 48)))
                        for (let slot = 0; slot < count; ++slot) {
                            const index = count === 1 ? trend.length - 1 : Math.round(slot * (trend.length - 1) / (count - 1))
                            ctx.fillText(String(trend[index].label || "").slice(0, 7), xFor(index), plotBottom + 4, 52)
                        }
                    }
                } else if (root.chartType === "map") {
                    const points = root.mapPoints || []
                    const highlights = root.highlightMapPoints || []
                    const layout = root.mapLayout(points, width, height)
                    const plotted = layout.points || []
                    const hasHighlights = highlights.length > 0
                    const highlightIds = []
                    const groupNames = []
                    let maxSize = 0
                    for (let i = 0; i < highlights.length; ++i)
                        highlightIds.push(String(highlights[i].id || ""))
                    for (let i = 0; i < plotted.length; ++i) {
                        const group = String(plotted[i].group || "")
                        if (group && groupNames.indexOf(group) < 0) groupNames.push(group)
                        maxSize = Math.max(maxSize, Number(plotted[i].size) || 0)
                    }
                    groupNames.sort()
                    ctx.fillStyle = "#edf4f7"
                    ctx.fillRect(layout.plotLeft, layout.plotTop, layout.plotWidth, layout.plotHeight)
                    ctx.strokeStyle = "#d5e1e8"
                    ctx.lineWidth = 1
                    for (let i = 0; i <= 4; ++i) {
                        const x = layout.plotLeft + layout.plotWidth * i / 4
                        const y = layout.plotTop + layout.plotHeight * i / 4
                        ctx.beginPath(); ctx.moveTo(x, layout.plotTop); ctx.lineTo(x, layout.plotTop + layout.plotHeight); ctx.stroke()
                        ctx.beginPath(); ctx.moveTo(layout.plotLeft, y); ctx.lineTo(layout.plotLeft + layout.plotWidth, y); ctx.stroke()
                    }
                    for (let i = 0; i < plotted.length; ++i) {
                        const point = plotted[i]
                        const selected = highlightIds.indexOf(point.id) >= 0
                        const groupIndex = groupNames.indexOf(point.group)
                        const markerColor = groupIndex >= 0 ? root.pieColor(groupIndex) : root.seriesColor
                        ctx.globalAlpha = hasHighlights && !selected ? 0.24 : 0.86
                        ctx.fillStyle = selected ? "#C65911" : markerColor
                        ctx.beginPath(); ctx.arc(point.x, point.y, point.radius, 0, Math.PI * 2); ctx.fill()
                        ctx.globalAlpha = 1
                        if (selected) {
                            ctx.strokeStyle = "#8f3f0b"
                            ctx.lineWidth = 1.5
                            ctx.beginPath(); ctx.arc(point.x, point.y, point.radius + 2, 0, Math.PI * 2); ctx.stroke()
                        }
                        if (root.showDataLabels) {
                            ctx.fillStyle = "#354452"
                            ctx.font = "9px sans-serif"
                            ctx.textAlign = "left"
                            ctx.textBaseline = "middle"
                            ctx.fillText(point.label, point.x + point.radius + 2, point.y, Math.max(20, width - point.x - point.radius - 4))
                        }
                    }
                    if (root.showLegend && groupNames.length) {
                        ctx.font = "9px sans-serif"
                        ctx.textAlign = "left"
                        ctx.textBaseline = "top"
                        let legendX = layout.plotLeft + 4
                        for (let i = 0; i < groupNames.length; ++i) {
                            if (legendX > width - 60) break
                            ctx.fillStyle = root.pieColor(i)
                            ctx.beginPath(); ctx.arc(legendX + 4, 16, 4, 0, Math.PI * 2); ctx.fill()
                            ctx.fillStyle = "#647382"
                            ctx.fillText(groupNames[i], legendX + 11, 11, 58)
                            legendX += Math.min(82, ctx.measureText(groupNames[i]).width + 21)
                        }
                    }
                    ctx.fillStyle = "#647382"
                    ctx.font = "8px sans-serif"
                    ctx.textAlign = "left"
                    ctx.textBaseline = "bottom"
                    ctx.fillText("Longitude", layout.plotLeft, height - 1)
                    ctx.textAlign = "right"
                    ctx.fillText("Latitude", width - 2, layout.plotTop - 1)
                } else if (root.chartType === "scatter") {
                    const layout = root.scatterLayout(root.scatterPoints || [], width, height)
                    const highlightedIds = []
                    for (let i = 0; i < highlightScatterPoints.length; ++i)
                        highlightedIds.push(String(highlightScatterPoints[i].id || ""))

                    ctx.font = "9px sans-serif"
                    ctx.strokeStyle = "#e7ebef"
                    ctx.lineWidth = 1
                    for (let tick = 0; tick <= 4; ++tick) {
                        const x = layout.plotLeft + layout.plotWidth * tick / 4
                        const y = layout.plotTop + layout.plotHeight * tick / 4
                        ctx.beginPath(); ctx.moveTo(x, layout.plotTop); ctx.lineTo(x, layout.plotTop + layout.plotHeight); ctx.stroke()
                        ctx.beginPath(); ctx.moveTo(layout.plotLeft, y); ctx.lineTo(layout.plotLeft + layout.plotWidth, y); ctx.stroke()
                        ctx.fillStyle = "#647382"
                        ctx.textAlign = "center"
                        ctx.textBaseline = "top"
                        ctx.fillText(root.valueLabel(layout.minX + (layout.maxX - layout.minX) * tick / 4), x, layout.plotTop + layout.plotHeight + 4, 55)
                        ctx.textAlign = "right"
                        ctx.textBaseline = "middle"
                        ctx.fillText(root.valueLabel(layout.maxY - (layout.maxY - layout.minY) * tick / 4), layout.plotLeft - 5, y, Math.max(25, layout.plotLeft - 8))
                    }

                    if (root.showLegend && layout.groups.length) {
                        ctx.font = "9px sans-serif"
                        ctx.textAlign = "left"
                        ctx.textBaseline = "middle"
                        let legendX = layout.plotLeft
                        for (let i = 0; i < layout.groups.length; ++i) {
                            const label = layout.groups[i]
                            const itemWidth = Math.min(92, ctx.measureText(label).width) + 20
                            if (legendX + itemWidth > width - 4)
                                break
                            ctx.fillStyle = root.pieColor(i)
                            ctx.beginPath(); ctx.arc(legendX + 4, 14, 3.5, 0, Math.PI * 2); ctx.fill()
                            ctx.fillStyle = "#647382"
                            ctx.fillText(label, legendX + 11, 14, 78)
                            legendX += itemWidth
                        }
                    }

                    for (let i = 0; i < layout.points.length; ++i) {
                        const point = layout.points[i]
                        const highlighted = highlightedIds.indexOf(point.id) !== -1
                        ctx.globalAlpha = hasScatterHighlights && !highlighted ? 0.28 : 1
                        ctx.fillStyle = root.pieColor(point.colorIndex)
                        ctx.beginPath(); ctx.arc(point.x, point.y, 4.5, 0, Math.PI * 2); ctx.fill()
                        ctx.globalAlpha = 1
                        ctx.strokeStyle = "#ffffff"
                        ctx.lineWidth = 1.2
                        ctx.stroke()
                        if (highlighted) {
                            ctx.strokeStyle = root.pieColor(point.colorIndex)
                            ctx.lineWidth = 2
                            ctx.beginPath(); ctx.arc(point.x, point.y, 6.2, 0, Math.PI * 2); ctx.stroke()
                        }
                        if (root.showDataLabels) {
                            ctx.fillStyle = "#425466"
                            ctx.font = "9px sans-serif"
                            ctx.textAlign = "left"
                            ctx.textBaseline = "bottom"
                            ctx.fillText(point.label, point.x + 5, point.y - 4, 68)
                        }
                    }
                } else if (root.chartType === "treemap") {
                    const tiles = root.treemapLayout(values, padLeft, padTop, plotW, plotH)
                    if (!tiles.length) {
                        ctx.fillStyle = "#647382"
                        ctx.font = "11px sans-serif"
                        ctx.textAlign = "center"
                        ctx.textBaseline = "middle"
                        ctx.fillText("No positive values to display.", width / 2, height / 2)
                        return
                    }
                    for (let i = 0; i < tiles.length; ++i) {
                        const tile = tiles[i]
                        const highlighted = root.highlightedValue(tile.label) !== null
                        ctx.globalAlpha = hasHighlights && !highlighted ? 0.32 : 1
                        ctx.fillStyle = root.pieColor(i)
                        ctx.fillRect(tile.x + 0.5, tile.y + 0.5,
                            Math.max(0, tile.width - 1), Math.max(0, tile.height - 1))
                        ctx.globalAlpha = 1
                        ctx.strokeStyle = "#ffffff"
                        ctx.lineWidth = 1.5
                        ctx.strokeRect(tile.x + 0.5, tile.y + 0.5,
                            Math.max(0, tile.width - 1), Math.max(0, tile.height - 1))
                        if (tile.width >= 36 && tile.height >= 24) {
                            const label = root.showDataLabels
                                    ? tile.label + " " + root.valueLabel(tile.value)
                                    : tile.label
                            ctx.fillStyle = "#ffffff"
                            ctx.font = "10px sans-serif"
                            ctx.textAlign = "center"
                            ctx.textBaseline = "middle"
                            ctx.fillText(label, tile.x + tile.width / 2, tile.y + tile.height / 2,
                                Math.max(1, tile.width - 8))
                        }
                    }
                } else if (root.chartType === "pie" || root.chartType === "donut") {
                    const slices = []
                    let total = 0
                    for (let i = 0; i < values.length; ++i) {
                        const value = Math.max(0, Number(values[i].value) || 0)
                        if (value > 0) {
                            slices.push({ label: String(values[i].label || ""), value: value })
                            total += value
                        }
                    }
                    if (!total) {
                        ctx.fillStyle = "#647382"
                        ctx.font = "11px sans-serif"
                        ctx.textAlign = "center"
                        ctx.textBaseline = "middle"
                        ctx.fillText("No positive values to display.", width / 2, height / 2)
                        return
                    }
                    const geometry = root.pieGeometry(width, height)
                    let startAngle = -Math.PI / 2
                    for (let i = 0; i < slices.length; ++i) {
                        const fraction = slices[i].value / total
                        const endAngle = startAngle + fraction * Math.PI * 2
                        const highlighted = root.highlightedValue(slices[i].label) !== null
                        ctx.beginPath()
                        ctx.moveTo(geometry.centerX, geometry.centerY)
                        ctx.arc(geometry.centerX, geometry.centerY, geometry.radius, startAngle, endAngle, false)
                        ctx.closePath()
                        ctx.globalAlpha = hasHighlights && !highlighted ? 0.28 : 1
                        ctx.fillStyle = root.pieColor(i)
                        ctx.fill()
                        ctx.globalAlpha = 1
                        ctx.strokeStyle = "#ffffff"
                        ctx.lineWidth = 1.5
                        ctx.stroke()

                        if (root.showDataLabels && fraction >= 0.06) {
                            const middleAngle = startAngle + (endAngle - startAngle) / 2
                            const labelRadius = geometry.radius * (root.chartType === "donut" ? 0.72 : 0.64)
                            const labelX = geometry.centerX + Math.cos(middleAngle) * labelRadius
                            const labelY = geometry.centerY + Math.sin(middleAngle) * labelRadius
                            ctx.fillStyle = "#ffffff"
                            ctx.font = "10px sans-serif"
                            ctx.textAlign = "center"
                            ctx.textBaseline = "middle"
                            ctx.fillText(Math.round(fraction * 100) + "%", labelX, labelY)
                        }
                        startAngle = endAngle
                    }
                    if (root.chartType === "donut") {
                        ctx.beginPath()
                        ctx.arc(geometry.centerX, geometry.centerY, geometry.radius * 0.48, 0, Math.PI * 2)
                        ctx.fillStyle = "#ffffff"
                        ctx.fill()
                        ctx.fillStyle = "#425466"
                        ctx.font = "11px sans-serif"
                        ctx.textAlign = "center"
                        ctx.textBaseline = "middle"
                        ctx.fillText(root.valueLabel(total), geometry.centerX, geometry.centerY)
                    }
                    if (root.showLegend) {
                        const rowHeight = 18
                        const maxRows = Math.max(1, Math.floor((height - 8) / rowHeight))
                        ctx.font = "10px sans-serif"
                        ctx.textAlign = "left"
                        ctx.textBaseline = "middle"
                        for (let i = 0; i < Math.min(slices.length, maxRows); ++i) {
                            const y = 9 + i * rowHeight
                            ctx.fillStyle = root.pieColor(i)
                            ctx.fillRect(geometry.legendX, y + 2, 8, 8)
                            ctx.fillStyle = "#647382"
                            ctx.fillText(slices[i].label, geometry.legendX + 13, y + 6, Math.max(1, width - geometry.legendX - 15))
                        }
                        if (slices.length > maxRows) {
                            ctx.fillStyle = "#647382"
                            ctx.fillText("…", geometry.legendX + 13, 9 + maxRows * rowHeight + 6)
                        }
                    }
                } else if (root.chartType === "funnel") {
                    const step = plotH / values.length
                    const segmentHeight = Math.max(5, step * 0.76)
                    for (let i = 0; i < values.length; ++i) {
                        const value = Math.max(0, Number(values[i].value) || 0)
                        const previousValue = i === 0
                                ? value
                                : Math.max(0, Number(values[i - 1].value) || 0)
                        const topWidth = plotW * previousValue / maxValue
                        const bottomWidth = plotW * value / maxValue
                        const top = padTop + i * step + (step - segmentHeight) / 2
                        const highlighted = root.highlightedValue(values[i].label) !== null
                        ctx.beginPath()
                        ctx.moveTo(padLeft + (plotW - topWidth) / 2, top)
                        ctx.lineTo(padLeft + (plotW + topWidth) / 2, top)
                        ctx.lineTo(padLeft + (plotW + bottomWidth) / 2, top + segmentHeight)
                        ctx.lineTo(padLeft + (plotW - bottomWidth) / 2, top + segmentHeight)
                        ctx.closePath()
                        ctx.globalAlpha = hasHighlights && !highlighted ? 0.3 : 1
                        ctx.fillStyle = root.pieColor(i)
                        ctx.fill()
                        ctx.globalAlpha = 1
                        ctx.strokeStyle = "#ffffff"
                        ctx.lineWidth = 1.5
                        ctx.stroke()

                        ctx.fillStyle = "#ffffff"
                        ctx.font = "10px sans-serif"
                        ctx.textAlign = "center"
                        ctx.textBaseline = "middle"
                        const label = root.axisLabel(values[i].label)
                        const segmentLabel = root.showDataLabels
                                ? label + "  " + root.valueLabel(value)
                                : label
                        ctx.fillText(segmentLabel, padLeft + plotW / 2, top + segmentHeight / 2, Math.max(1, Math.min(topWidth, bottomWidth)))
                    }
                } else if (root.chartType === "ribbon") {
                    const step = plotW / values.length
                    const segmentLabels = (values[0].segments || []).map(function(segment) {
                        return String(segment.label || "")
                    })
                    const topBySegment = []
                    const bottomBySegment = []
                    const highlightTopBySegment = []
                    const highlightBottomBySegment = []
                    const labelBySegment = []
                    root.drawStackLegend(ctx, width, values, padLeft)
                    for (let j = 0; j < segmentLabels.length; ++j) {
                        topBySegment.push([])
                        bottomBySegment.push([])
                        highlightTopBySegment.push([])
                        highlightBottomBySegment.push([])
                        labelBySegment.push([])
                    }
                    for (let i = 0; i < values.length; ++i) {
                        const ordered = (values[i].segments || []).slice().sort(function(left, right) {
                            const difference = (Number(right.value) || 0) - (Number(left.value) || 0)
                            return difference || String(left.label).localeCompare(String(right.label))
                        })
                        const rowTotal = ordered.reduce(function(total, segment) {
                            return total + Math.max(0, Number(segment.value) || 0)
                        }, 0)
                        let cumulative = 0
                        const x = padLeft + step * (i + 0.5)
                        for (let k = 0; k < ordered.length; ++k) {
                            const segment = ordered[k]
                            const segmentIndex = segmentLabels.indexOf(String(segment.label || ""))
                            if (segmentIndex < 0)
                                continue
                            const rawValue = Math.max(0, Number(segment.value) || 0)
                            const height = rowTotal > 0 ? plotH * rawValue / rowTotal : 0
                            const bottomY = padTop + plotH - plotH * cumulative / (rowTotal || 1)
                            const topY = bottomY - height
                            topBySegment[segmentIndex][i] = { x: x, y: topY }
                            bottomBySegment[segmentIndex][i] = { x: x, y: bottomY }
                            labelBySegment[segmentIndex][i] = {
                                x: x, y: (topY + bottomY) / 2, height: height, value: rawValue,
                            }
                            const highlighted = root.highlightedSegmentValue(values[i].label, segment.label)
                            const highlightedHeight = highlighted === null || rowTotal <= 0
                                    ? 0
                                    : plotH * Math.min(highlighted, rawValue) / rowTotal
                            highlightTopBySegment[segmentIndex][i] = {
                                x: x, y: bottomY - highlightedHeight,
                            }
                            highlightBottomBySegment[segmentIndex][i] = { x: x, y: bottomY }
                            cumulative += height
                        }
                    }

                    for (let j = 0; j < segmentLabels.length; ++j) {
                        const topPoints = topBySegment[j]
                        const bottomPoints = bottomBySegment[j]
                        if (!topPoints.length || !bottomPoints.length)
                            continue
                        ctx.beginPath()
                        ctx.moveTo(topPoints[0].x, topPoints[0].y)
                        for (let i = 1; i < topPoints.length; ++i)
                            ctx.lineTo(topPoints[i].x, topPoints[i].y)
                        for (let i = bottomPoints.length - 1; i >= 0; --i)
                            ctx.lineTo(bottomPoints[i].x, bottomPoints[i].y)
                        ctx.closePath()
                        ctx.fillStyle = hasHighlights ? "#d4dce3" : root.pieColor(j)
                        ctx.globalAlpha = 0.9
                        ctx.fill()
                        ctx.globalAlpha = 1

                        if (hasHighlights) {
                            const highlightTop = highlightTopBySegment[j]
                            const highlightBottom = highlightBottomBySegment[j]
                            ctx.beginPath()
                            ctx.moveTo(highlightTop[0].x, highlightTop[0].y)
                            for (let i = 1; i < highlightTop.length; ++i)
                                ctx.lineTo(highlightTop[i].x, highlightTop[i].y)
                            for (let i = highlightBottom.length - 1; i >= 0; --i)
                                ctx.lineTo(highlightBottom[i].x, highlightBottom[i].y)
                            ctx.closePath()
                            ctx.fillStyle = root.pieColor(j)
                            ctx.fill()
                        }

                        if (root.showDataLabels) {
                            ctx.fillStyle = "#ffffff"
                            ctx.font = "10px sans-serif"
                            ctx.textAlign = "center"
                            ctx.textBaseline = "middle"
                            for (let i = 0; i < labelBySegment[j].length; ++i) {
                                const labelPoint = labelBySegment[j][i]
                                if (labelPoint.height >= 18)
                                    ctx.fillText(root.valueLabel(labelPoint.value), labelPoint.x, labelPoint.y)
                            }
                        }
                    }

                    const labelCount = Math.max(1, Math.min(values.length, Math.floor(plotW / 60)))
                    ctx.fillStyle = "#647382"
                    ctx.font = "10px sans-serif"
                    ctx.textAlign = "center"
                    ctx.textBaseline = "top"
                    for (let slot = 0; slot < labelCount; ++slot) {
                        const index = labelCount === 1
                            ? values.length - 1
                            : Math.round(slot * (values.length - 1) / (labelCount - 1))
                        ctx.fillText(root.axisLabel(values[index].label),
                            padLeft + step * (index + 0.5), padTop + plotH + 5,
                            Math.max(1, plotW / labelCount))
                    }
                } else if (root.chartType === "waterfall") {
                    let running = 0
                    let minTotal = 0
                    let maxTotal = 0
                    const starts = []
                    const ends = []
                    for (let i = 0; i < values.length; ++i) {
                        starts.push(running)
                        running += Number(values[i].value) || 0
                        ends.push(running)
                        minTotal = Math.min(minTotal, running)
                        maxTotal = Math.max(maxTotal, running)
                    }
                    const range = maxTotal - minTotal || 1
                    const yFor = function(value) {
                        return padTop + plotH * (maxTotal - value) / range
                    }
                    const zeroY = yFor(0)
                    ctx.strokeStyle = "#83909b"
                    ctx.lineWidth = 1.2
                    ctx.beginPath(); ctx.moveTo(padLeft, zeroY); ctx.lineTo(width - padRight, zeroY); ctx.stroke()
                    const step = plotW / values.length
                    const barW = Math.max(5, step * 0.56)
                    for (let i = 0; i < values.length; ++i) {
                        const x = padLeft + i * step + (step - barW) / 2
                        const delta = Number(values[i].value) || 0
                        const end = ends[i]
                        const top = yFor(Math.max(starts[i], end))
                        const bottom = yFor(Math.min(starts[i], end))
                        const height = Math.max(1, bottom - top)
                        ctx.fillStyle = hasHighlights ? "#d4dce3" : (delta >= 0 ? root.seriesColor : "#C65911")
                        ctx.fillRect(x, top, barW, height)
                        const highlighted = root.highlightedValue(values[i].label)
                        if (highlighted !== null) {
                            const highlightedEnd = starts[i] + highlighted
                            const highlightTop = yFor(Math.max(starts[i], highlightedEnd))
                            const highlightBottom = yFor(Math.min(starts[i], highlightedEnd))
                            ctx.fillStyle = highlighted >= 0 ? root.seriesColor : "#C65911"
                            ctx.fillRect(x, highlightTop, barW, Math.max(1, highlightBottom - highlightTop))
                        }
                        if (i + 1 < values.length) {
                            const connectorY = yFor(end)
                            ctx.strokeStyle = "#9da8b1"
                            ctx.lineWidth = 1
                            ctx.beginPath()
                            ctx.moveTo(x + barW, connectorY)
                            ctx.lineTo(padLeft + (i + 1) * step + (step - barW) / 2, connectorY)
                            ctx.stroke()
                        }
                        if (root.showDataLabels) {
                            ctx.fillStyle = "#425466"
                            ctx.font = "10px sans-serif"
                            ctx.textAlign = "center"
                            ctx.textBaseline = delta >= 0 ? "bottom" : "top"
                            ctx.fillText(root.valueLabel(delta), x + barW / 2,
                                delta >= 0 ? Math.max(10, top - 3) : bottom + 3)
                        }
                    }

                    const labels = []
                    let maxLabelWidth = 0
                    ctx.font = "10px sans-serif"
                    for (let i = 0; i < values.length; ++i) {
                        const label = root.axisLabel(values[i].label)
                        labels.push(label)
                        maxLabelWidth = Math.max(maxLabelWidth, ctx.measureText(label).width)
                    }
                    const labelCount = Math.max(1, Math.min(values.length,
                        Math.floor(plotW / Math.max(1, maxLabelWidth + 6))))
                    ctx.fillStyle = "#647382"
                    ctx.textAlign = "center"
                    ctx.textBaseline = "top"
                    for (let slot = 0; slot < labelCount; ++slot) {
                        const index = labelCount === 1
                            ? values.length - 1
                            : Math.round(slot * (values.length - 1) / (labelCount - 1))
                        ctx.fillText(labels[index], padLeft + step * (index + 0.5), padTop + plotH + 5)
                    }
                } else if (root.isStackedArea()) {
                    const hundredPercent = root.isHundredPercent()
                    const scaleValue = hundredPercent ? 100 : maxValue
                    const step = plotW / values.length
                    const areaSegments = values[0].segments || []
                    root.drawStackLegend(ctx, width, values, padLeft)
                    for (let j = 0; j < areaSegments.length; ++j) {
                        const topPoints = []
                        const bottomPoints = []
                        const highlightedTop = []
                        const highlightedBottom = []
                        const labelPoints = []
                        let hasSegmentHighlight = false
                        for (let i = 0; i < values.length; ++i) {
                            const rowSegments = values[i].segments || []
                            const rowTotal = Number(values[i].value) || 1
                            let baseValue = 0
                            for (let prior = 0; prior < j; ++prior) {
                                const previous = Math.max(0, Number(rowSegments[prior] ? rowSegments[prior].value : 0) || 0)
                                baseValue += hundredPercent ? 100 * previous / rowTotal : previous
                            }
                            const rawValue = Math.max(0, Number(rowSegments[j] ? rowSegments[j].value : 0) || 0)
                            const value = hundredPercent ? 100 * rawValue / rowTotal : rawValue
                            const x = padLeft + step * (i + 0.5)
                            const baselineY = padTop + plotH - plotH * baseValue / scaleValue
                            const topY = padTop + plotH - plotH * (baseValue + value) / scaleValue
                            topPoints.push({ x: x, y: topY })
                            bottomPoints.push({ x: x, y: baselineY })
                            labelPoints.push({ x: x, y: (baselineY + topY) / 2, height: baselineY - topY })

                            const highlighted = root.highlightedSegmentValue(values[i].label, areaSegments[j].label)
                            const highlightValue = highlighted === null ? 0
                                    : (hundredPercent
                                        ? 100 * Math.min(highlighted, rawValue) / rowTotal
                                        : Math.min(highlighted, rawValue))
                            if (highlightValue > 0)
                                hasSegmentHighlight = true
                            highlightedBottom.push({ x: x, y: baselineY })
                            highlightedTop.push({
                                x: x,
                                y: padTop + plotH - plotH * (baseValue + highlightValue) / scaleValue,
                            })
                        }

                        ctx.beginPath()
                        ctx.moveTo(topPoints[0].x, topPoints[0].y)
                        for (let i = 1; i < topPoints.length; ++i)
                            ctx.lineTo(topPoints[i].x, topPoints[i].y)
                        for (let i = bottomPoints.length - 1; i >= 0; --i)
                            ctx.lineTo(bottomPoints[i].x, bottomPoints[i].y)
                        ctx.closePath()
                        ctx.fillStyle = hasHighlights ? "#d4dce3" : root.pieColor(j)
                        ctx.globalAlpha = hasHighlights ? 0.9 : 0.5
                        ctx.fill()
                        ctx.globalAlpha = 1

                        if (hasHighlights && hasSegmentHighlight) {
                            ctx.beginPath()
                            ctx.moveTo(highlightedTop[0].x, highlightedTop[0].y)
                            for (let i = 1; i < highlightedTop.length; ++i)
                                ctx.lineTo(highlightedTop[i].x, highlightedTop[i].y)
                            for (let i = highlightedBottom.length - 1; i >= 0; --i)
                                ctx.lineTo(highlightedBottom[i].x, highlightedBottom[i].y)
                            ctx.closePath()
                            ctx.fillStyle = root.pieColor(j)
                            ctx.globalAlpha = 0.9
                            ctx.fill()
                            ctx.globalAlpha = 1
                        }

                        if (root.showDataLabels) {
                            ctx.fillStyle = "#425466"
                            ctx.font = "10px sans-serif"
                            ctx.textAlign = "center"
                            ctx.textBaseline = "middle"
                            for (let i = 0; i < labelPoints.length; ++i) {
                                if (labelPoints[i].height < 18)
                                    continue
                                const segmentValue = Number((values[i].segments || [])[j].value) || 0
                                const labelValue = hundredPercent
                                        ? 100 * segmentValue / (Number(values[i].value) || 1)
                                        : segmentValue
                                ctx.fillText(root.valueLabel(labelValue) + (hundredPercent ? "%" : ""),
                                    labelPoints[i].x, labelPoints[i].y)
                            }
                        }
                    }

                    const labelCount = Math.max(1, Math.min(values.length, Math.floor(plotW / 60)))
                    ctx.fillStyle = "#647382"
                    ctx.font = "10px sans-serif"
                    ctx.textAlign = "center"
                    ctx.textBaseline = "top"
                    for (let slot = 0; slot < labelCount; ++slot) {
                        const index = labelCount === 1
                            ? values.length - 1
                            : Math.round(slot * (values.length - 1) / (labelCount - 1))
                        ctx.fillText(root.axisLabel(values[index].label),
                            padLeft + step * (index + 0.5), padTop + plotH + 5,
                            Math.max(1, plotW / labelCount))
                    }
                } else if (root.isStacked()) {
                    const horizontal = root.chartType === "stackedBar" || root.chartType === "bar100"
                    const hundredPercent = root.isHundredPercent()
                    const scaleValue = hundredPercent ? 100 : maxValue
                    root.drawStackLegend(ctx, width, values, padLeft)

                    if (horizontal) {
                        const step = plotH / values.length
                        const labelStride = Math.max(1, Math.ceil(12 / step))
                        ctx.font = "10px sans-serif"
                        ctx.textAlign = "right"
                        ctx.textBaseline = "middle"
                        for (let i = 0; i < values.length; ++i) {
                            const y = padTop + i * step + step * 0.18
                            const barH = Math.max(3, step * 0.64)
                            const rowTotal = Number(values[i].value) || 1
                            let cumulative = 0
                            const segments = values[i].segments || []
                            for (let j = 0; j < segments.length; ++j) {
                                const rawValue = Math.max(0, Number(segments[j].value) || 0)
                                const value = hundredPercent ? 100 * rawValue / rowTotal : rawValue
                                const start = plotW * cumulative / scaleValue
                                const barW = plotW * value / scaleValue
                                ctx.fillStyle = hasHighlights ? "#d4dce3" : root.pieColor(j)
                                ctx.fillRect(padLeft + start, y, barW, barH)
                                const highlighted = root.highlightedSegmentValue(values[i].label, segments[j].label)
                                if (highlighted !== null && highlighted > 0) {
                                    const highlightValue = hundredPercent
                                            ? 100 * Math.min(highlighted, rawValue) / rowTotal
                                            : Math.min(highlighted, rawValue)
                                    ctx.fillStyle = root.pieColor(j)
                                    ctx.fillRect(
                                        padLeft + start, y,
                                        plotW * highlightValue / scaleValue, barH
                                    )
                                }
                                if (root.showDataLabels && barW >= 26) {
                                    ctx.fillStyle = "#ffffff"
                                    ctx.textAlign = "center"
                                    ctx.fillText(root.valueLabel(value) + (hundredPercent ? "%" : ""), padLeft + start + barW / 2, y + barH / 2, barW - 4)
                                    ctx.textAlign = "right"
                                }
                                cumulative += hundredPercent ? value : rawValue
                            }
                            if (i % labelStride === 0) {
                                ctx.fillStyle = "#647382"
                                ctx.fillText(String(values[i].label || "").slice(0, 7), padLeft - 5, y + barH / 2, padLeft - 8)
                            }
                        }
                    } else {
                        const step = plotW / values.length
                        const labels = []
                        let maxLabelWidth = 0
                        ctx.font = "10px sans-serif"
                        for (let i = 0; i < values.length; ++i) {
                            const label = root.axisLabel(values[i].label)
                            labels.push(label)
                            maxLabelWidth = Math.max(maxLabelWidth, ctx.measureText(label).width)
                        }
                        const labelCount = Math.max(1, Math.min(values.length,
                            Math.floor(plotW / Math.max(1, maxLabelWidth + 6))))
                        const showLabel = []
                        for (let slot = 0; slot < labelCount; ++slot) {
                            const index = labelCount === 1
                                ? values.length - 1
                                : Math.round(slot * (values.length - 1) / (labelCount - 1))
                            showLabel[index] = true
                        }
                        for (let i = 0; i < values.length; ++i) {
                            const barW = Math.max(5, step * 0.56)
                            const x = padLeft + i * step + (step - barW) / 2
                            const rowTotal = Number(values[i].value) || 1
                            let cumulative = 0
                            const segments = values[i].segments || []
                            for (let j = 0; j < segments.length; ++j) {
                                const rawValue = Math.max(0, Number(segments[j].value) || 0)
                                const value = hundredPercent ? 100 * rawValue / rowTotal : rawValue
                                const segmentHeight = plotH * value / scaleValue
                                const y = padTop + plotH - plotH * (cumulative + value) / scaleValue
                                ctx.fillStyle = hasHighlights ? "#d4dce3" : root.pieColor(j)
                                ctx.fillRect(x, y, barW, segmentHeight)
                                const highlighted = root.highlightedSegmentValue(values[i].label, segments[j].label)
                                if (highlighted !== null && highlighted > 0) {
                                    const highlightValue = hundredPercent
                                            ? 100 * Math.min(highlighted, rawValue) / rowTotal
                                            : Math.min(highlighted, rawValue)
                                    const highlightedHeight = plotH * highlightValue / scaleValue
                                    ctx.fillStyle = root.pieColor(j)
                                    ctx.fillRect(x, y + segmentHeight - highlightedHeight, barW, highlightedHeight)
                                }
                                if (root.showDataLabels && segmentHeight >= 18) {
                                    ctx.fillStyle = "#ffffff"
                                    ctx.font = "10px sans-serif"
                                    ctx.textAlign = "center"
                                    ctx.textBaseline = "middle"
                                    ctx.fillText(root.valueLabel(value) + (hundredPercent ? "%" : ""), x + barW / 2, y + segmentHeight / 2, barW - 3)
                                }
                                cumulative += hundredPercent ? value : rawValue
                            }
                            if (showLabel[i]) {
                                ctx.fillStyle = "#647382"
                                ctx.font = "10px sans-serif"
                                ctx.textAlign = "center"
                                ctx.textBaseline = "top"
                                ctx.fillText(labels[i], x + barW / 2, padTop + plotH + 5)
                            }
                        }
                    }
                } else if (root.chartType === "line") {
                    ctx.strokeStyle = hasHighlights ? "#b8c2cc" : color
                    ctx.lineWidth = 2
                    ctx.beginPath()
                    for (let i = 0; i < values.length; ++i) {
                        const x = padLeft + plotW * (i + 0.5) / values.length
                        const y = padTop + plotH - plotH * (Number(values[i].value) || 0) / maxValue
                        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
                    }
                    ctx.stroke()
                    ctx.fillStyle = hasHighlights ? "#b8c2cc" : color
                    for (let i = 0; i < values.length; ++i) {
                        const x = padLeft + plotW * (i + 0.5) / values.length
                        const y = padTop + plotH - plotH * (Number(values[i].value) || 0) / maxValue
                        ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fill()
                        if (root.showDataLabels) {
                            ctx.fillStyle = "#425466"
                            ctx.font = "10px sans-serif"
                            ctx.textAlign = "center"
                            ctx.textBaseline = "bottom"
                            ctx.fillText(root.valueLabel(values[i].value), x, Math.max(10, y - 5))
                            ctx.fillStyle = hasHighlights ? "#b8c2cc" : color
                        }
                    }
                    if (hasHighlights) {
                        ctx.fillStyle = color
                        for (let i = 0; i < values.length; ++i) {
                            const selectedValue = root.highlightedValue(values[i].label)
                            if (selectedValue === null) continue
                            const x = padLeft + plotW * (i + 0.5) / values.length
                            const y = padTop + plotH - plotH * selectedValue / maxValue
                            ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill()
                        }
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
                        ctx.fillStyle = hasHighlights ? "#d4dce3" : root.seriesColor
                        ctx.fillRect(padLeft, y, barW, barH)
                        const selectedValue = root.highlightedValue(values[i].label)
                        if (selectedValue !== null) {
                            ctx.fillStyle = color
                            ctx.fillRect(
                                padLeft, y,
                                plotW * Math.min(Math.max(0, selectedValue), Number(values[i].value) || 0) / maxValue,
                                barH
                            )
                        }
                        if (i % labelStride === 0) {
                            ctx.fillStyle = "#647382"
                            ctx.fillText(label, padLeft - 5, y + barH / 2, padLeft - 8)
                        }
                        if (root.showDataLabels) {
                            ctx.fillStyle = "#425466"
                            ctx.textAlign = "left"
                            ctx.textBaseline = "middle"
                            ctx.fillText(
                                root.valueLabel(values[i].value),
                                Math.min(padLeft + barW + 4, width - padRight + 2),
                                y + barH / 2,
                                Math.max(1, width - padRight - Math.min(padLeft + barW + 4, width - padRight + 2))
                            )
                        }
                    }
                } else if (root.chartType === "area") {
                    const step = plotW / values.length
                    const points = []
                    for (let i = 0; i < values.length; ++i) {
                        points.push({
                            x: padLeft + step * (i + 0.5),
                            y: padTop + plotH - plotH * (Number(values[i].value) || 0) / maxValue,
                        })
                    }
                    ctx.beginPath()
                    ctx.moveTo(points[0].x, padTop + plotH)
                    ctx.lineTo(points[0].x, points[0].y)
                    for (let i = 1; i < points.length; ++i)
                        ctx.lineTo(points[i].x, points[i].y)
                    ctx.lineTo(points[points.length - 1].x, padTop + plotH)
                    ctx.closePath()
                    ctx.fillStyle = hasHighlights ? "#d4dce3" : color
                    ctx.globalAlpha = hasHighlights ? 0.8 : 0.24
                    ctx.fill()
                    ctx.globalAlpha = 1

                    ctx.beginPath()
                    ctx.moveTo(points[0].x, points[0].y)
                    for (let i = 1; i < points.length; ++i)
                        ctx.lineTo(points[i].x, points[i].y)
                    ctx.strokeStyle = hasHighlights ? "#b8c2cc" : color
                    ctx.lineWidth = 2
                    ctx.stroke()

                    for (let i = 0; i < points.length; ++i) {
                        ctx.fillStyle = root.highlightedValue(values[i].label) !== null ? color
                                : (hasHighlights ? "#b8c2cc" : color)
                        ctx.beginPath(); ctx.arc(points[i].x, points[i].y, 3, 0, Math.PI * 2); ctx.fill()
                        if (root.showDataLabels) {
                            ctx.fillStyle = "#425466"
                            ctx.font = "10px sans-serif"
                            ctx.textAlign = "center"
                            ctx.textBaseline = "bottom"
                            ctx.fillText(root.valueLabel(values[i].value), points[i].x, Math.max(10, points[i].y - 5))
                        }
                    }
                    const labelCount = Math.max(1, Math.min(values.length, Math.floor(plotW / 60)))
                    ctx.fillStyle = "#647382"
                    ctx.font = "10px sans-serif"
                    ctx.textAlign = "center"
                    ctx.textBaseline = "top"
                    for (let slot = 0; slot < labelCount; ++slot) {
                        const index = labelCount === 1
                            ? values.length - 1
                            : Math.round(slot * (values.length - 1) / (labelCount - 1))
                        ctx.fillText(root.axisLabel(values[index].label), points[index].x, padTop + plotH + 5, Math.max(1, plotW / labelCount))
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
                        ctx.fillStyle = hasHighlights ? "#d4dce3" : root.seriesColor
                        ctx.fillRect(x, padTop + plotH - barH, barW, barH)
                        const selectedValue = root.highlightedValue(values[i].label)
                        if (selectedValue !== null) {
                            const highlightHeight = plotH * Math.min(
                                Math.max(0, selectedValue), v
                            ) / maxValue
                            ctx.fillStyle = color
                            ctx.fillRect(
                                x, padTop + plotH - highlightHeight, barW, highlightHeight
                            )
                        }
                        if (showLabel[i]) {
                            ctx.fillStyle = "#647382"
                            ctx.fillText(labels[i], x + barW / 2, padTop + plotH + 5)
                        }
                        if (root.showDataLabels) {
                            ctx.fillStyle = "#425466"
                            ctx.textAlign = "center"
                            ctx.textBaseline = "bottom"
                            ctx.fillText(root.valueLabel(values[i].value), x + barW / 2, Math.max(10, padTop + plotH - barH - 3))
                        }
                    }
                    if (root.chartType === "lineClusteredColumn" && values.length) {
                        const linePoints = []
                        for (let i = 0; i < values.length; ++i) {
                            let matched = null
                            for (let j = 0; j < lineValues.length; ++j) {
                                if (String(lineValues[j].label) === String(values[i].label)) {
                                    matched = lineValues[j]
                                    break
                                }
                            }
                            if (matched) {
                                linePoints.push({
                                    label: values[i].label,
                                    value: Number(matched.value) || 0,
                                    x: padLeft + plotW * (i + 0.5) / values.length,
                                })
                            }
                        }
                        ctx.strokeStyle = hasHighlights ? "#b8c2cc" : "#C65911"
                        ctx.lineWidth = 2.5
                        ctx.beginPath()
                        for (let i = 0; i < linePoints.length; ++i) {
                            const y = padTop + plotH - plotH * linePoints[i].value / maxValue
                            if (i === 0) ctx.moveTo(linePoints[i].x, y); else ctx.lineTo(linePoints[i].x, y)
                        }
                        ctx.stroke()
                        for (let i = 0; i < linePoints.length; ++i) {
                            const point = linePoints[i]
                            const y = padTop + plotH - plotH * point.value / maxValue
                            ctx.fillStyle = hasHighlights ? "#b8c2cc" : "#C65911"
                            ctx.beginPath(); ctx.arc(point.x, y, 3.5, 0, Math.PI * 2); ctx.fill()
                            const selectedValue = root.highlightedLineValue(point.label)
                            if (selectedValue !== null) {
                                const selectedY = padTop + plotH - plotH * selectedValue / maxValue
                                ctx.fillStyle = "#C65911"
                                ctx.beginPath(); ctx.arc(point.x, selectedY, 4.5, 0, Math.PI * 2); ctx.fill()
                            }
                            if (root.showDataLabels) {
                                ctx.fillStyle = "#425466"
                                ctx.font = "10px sans-serif"
                                ctx.textAlign = "center"
                                ctx.textBaseline = "bottom"
                                ctx.fillText(root.valueLabel(point.value), point.x, Math.max(10, y - 5))
                            }
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
            if (!root.requestSelection(mouse.modifiers))
                return
            if (!root.filterOnCategory || (root.chartType === "scatter"
                    ? !(root.scatterPoints || []).length
                    : root.chartType === "map"
                        ? !(root.mapPoints || []).length
                        : (!root.series || root.series.length === 0)))
                return
            const point = chart.mapFromItem(root, mouse.x, mouse.y)
            const values = root.series
            let index = -1
            if (root.chartType === "map") {
                const layout = root.mapLayout(root.mapPoints || [], chart.width, chart.height)
                let nearest = null
                let nearestDistance = 400
                for (let i = 0; i < layout.points.length; ++i) {
                    const candidate = layout.points[i]
                    const dx = point.x - candidate.x
                    const dy = point.y - candidate.y
                    const distance = dx * dx + dy * dy
                    if (distance < nearestDistance) {
                        nearest = candidate
                        nearestDistance = distance
                    }
                }
                if (nearest)
                    root.categoryRequested(nearest.label)
                return
            } else if (root.chartType === "kpi") {
                const trend = (root.kpiData || {}).trend || []
                if (!trend.length || point.y < chart.height * 0.40)
                    return
                const plotLeft = 14
                const plotRight = chart.width - 14
                index = trend.length === 1 ? 0 : Math.round(
                    Math.max(0, Math.min(1, (point.x - plotLeft) / Math.max(1, plotRight - plotLeft))) * (trend.length - 1)
                )
                if (index >= 0 && index < trend.length)
                    root.categoryRequested(String(trend[index].label || ""))
                return
            } else if (root.chartType === "scatter") {
                const layout = root.scatterLayout(root.scatterPoints || [], chart.width, chart.height)
                let nearest = null
                let nearestDistance = 100
                for (let i = 0; i < layout.points.length; ++i) {
                    const candidate = layout.points[i]
                    const dx = point.x - candidate.x
                    const dy = point.y - candidate.y
                    const distance = dx * dx + dy * dy
                    if (distance < nearestDistance) {
                        nearest = candidate
                        nearestDistance = distance
                    }
                }
                if (nearest)
                    root.categoryRequested(nearest.label)
                return
            } else if (root.chartType === "treemap") {
                const plotLeft = 38
                const plotTop = root.showDataLabels ? 20 : 9
                const plotWidth = Math.max(12, chart.width - plotLeft - 8)
                const plotHeight = Math.max(12, chart.height - plotTop - 25)
                const tiles = root.treemapLayout(values, plotLeft, plotTop, plotWidth, plotHeight)
                for (let i = 0; i < tiles.length; ++i) {
                    const tile = tiles[i]
                    if (point.x >= tile.x && point.x <= tile.x + tile.width
                            && point.y >= tile.y && point.y <= tile.y + tile.height) {
                        root.categoryRequested(tile.label)
                        return
                    }
                }
                return
            } else if (root.chartType === "pie" || root.chartType === "donut") {
                const label = root.pieCategoryAt(point.x, point.y, chart.width, chart.height)
                if (label)
                    root.categoryRequested(label)
                return
            } else if (root.chartType === "funnel") {
                const plotLeft = 38
                const plotWidth = Math.max(12, chart.width - 46)
                const plotTop = 9
                const plotHeight = Math.max(12, chart.height - 34)
                const step = plotHeight / values.length
                const segmentHeight = Math.max(5, step * 0.76)
                if (point.y >= plotTop && point.y < plotTop + plotHeight) {
                    const candidate = Math.floor((point.y - plotTop) / step)
                    if (candidate >= 0 && candidate < values.length) {
                        const segmentTop = plotTop + candidate * step + (step - segmentHeight) / 2
                        if (point.y >= segmentTop && point.y <= segmentTop + segmentHeight) {
                            let maxValue = 0
                            for (let i = 0; i < values.length; ++i)
                                maxValue = Math.max(maxValue, Number(values[i].value) || 0)
                            maxValue = maxValue || 1
                            const current = Math.max(0, Number(values[candidate].value) || 0)
                            const previous = candidate === 0
                                    ? current
                                    : Math.max(0, Number(values[candidate - 1].value) || 0)
                            const topWidth = plotWidth * previous / maxValue
                            const bottomWidth = plotWidth * current / maxValue
                            const fraction = (point.y - segmentTop) / segmentHeight
                            const widthAtPoint = topWidth + (bottomWidth - topWidth) * fraction
                            const left = plotLeft + (plotWidth - widthAtPoint) / 2
                            if (point.x >= left && point.x <= left + widthAtPoint)
                                index = candidate
                        }
                    }
                }
            } else if (root.chartType === "ribbon") {
                const plotLeft = 38
                const plotWidth = Math.max(12, chart.width - plotLeft - 8)
                const plotTop = root.showLegend
                        ? Math.max(27, root.showDataLabels ? 20 : 0)
                        : (root.showDataLabels ? 20 : 9)
                const plotHeight = Math.max(12, chart.height - plotTop - 25)
                if (point.x >= plotLeft && point.x < plotLeft + plotWidth
                        && point.y >= plotTop && point.y < plotTop + plotHeight)
                    index = Math.floor((point.x - plotLeft) / (plotWidth / values.length))
            } else if (root.chartType === "waterfall") {
                const plotLeft = 38
                const plotWidth = Math.max(12, chart.width - plotLeft - 8)
                const plotTop = root.showDataLabels ? 20 : 9
                const plotHeight = Math.max(12, chart.height - plotTop - 25)
                if (point.x >= plotLeft && point.x < plotLeft + plotWidth
                        && point.y >= plotTop && point.y < plotTop + plotHeight) {
                    const step = plotWidth / values.length
                    const candidate = Math.floor((point.x - plotLeft) / step)
                    const barWidth = Math.max(5, step * 0.56)
                    const x = plotLeft + candidate * step + (step - barWidth) / 2
                    let running = 0
                    let minTotal = 0
                    let maxTotal = 0
                    const starts = []
                    const ends = []
                    for (let i = 0; i < values.length; ++i) {
                        starts.push(running)
                        running += Number(values[i].value) || 0
                        ends.push(running)
                        minTotal = Math.min(minTotal, running)
                        maxTotal = Math.max(maxTotal, running)
                    }
                    const range = maxTotal - minTotal || 1
                    const yFor = function(value) {
                        return plotTop + plotHeight * (maxTotal - value) / range
                    }
                    if (candidate >= 0 && candidate < values.length
                            && point.x >= x && point.x <= x + barWidth) {
                        const top = yFor(Math.max(starts[candidate], ends[candidate]))
                        const bottom = yFor(Math.min(starts[candidate], ends[candidate]))
                        if (point.y >= top && point.y <= bottom)
                            index = candidate
                    }
                }
            } else if (root.isStackedArea()) {
                const plotLeft = 38
                const plotWidth = Math.max(12, chart.width - plotLeft - 8)
                const plotTop = root.showLegend ? Math.max(27, root.showDataLabels ? 20 : 0) : (root.showDataLabels ? 20 : 9)
                const plotHeight = Math.max(12, chart.height - plotTop - 25)
                if (point.x >= plotLeft && point.x < plotLeft + plotWidth
                        && point.y >= plotTop && point.y < plotTop + plotHeight) {
                    const step = plotWidth / values.length
                    const candidate = Math.floor((point.x - plotLeft) / step)
                    let maxValue = 0
                    for (let i = 0; i < values.length; ++i)
                        maxValue = Math.max(maxValue, Number(values[i].value) || 0)
                    const total = Number(values[candidate] ? values[candidate].value : 0) || 0
                    const top = root.isHundredPercent()
                            ? plotTop
                            : plotTop + plotHeight - plotHeight * total / (maxValue || 1)
                    if (candidate >= 0 && candidate < values.length && point.y >= top)
                        index = candidate
                }
            } else if (root.chartType === "stackedBar" || root.chartType === "bar100") {
                const plotLeft = 38
                const plotWidth = Math.max(1, chart.width - 46)
                const plotTop = root.showLegend ? Math.max(27, root.showDataLabels ? 20 : 0) : (root.showDataLabels ? 20 : 9)
                const plotHeight = Math.max(1, chart.height - plotTop - 25)
                const step = plotHeight / values.length
                if (point.y >= plotTop && point.y < plotTop + plotHeight) {
                    const candidate = Math.floor((point.y - plotTop) / step)
                    if (candidate >= 0 && candidate < values.length) {
                        const y = plotTop + candidate * step + step * 0.18
                        const barHeight = Math.max(3, step * 0.64)
                        let total = 0
                        const segments = values[candidate].segments || []
                        for (let i = 0; i < segments.length; ++i)
                            total += Math.max(0, Number(segments[i].value) || 0)
                        let maxValue = 0
                        for (let i = 0; i < values.length; ++i)
                            maxValue = Math.max(maxValue, Number(values[i].value) || 0)
                        const barWidth = plotWidth * (root.isHundredPercent() ? 1 : total / (maxValue || 1))
                        if (point.y >= y && point.y <= y + barHeight
                                && point.x >= plotLeft && point.x <= plotLeft + barWidth)
                            index = candidate
                    }
                }
            } else if (root.chartType === "stackedColumn" || root.chartType === "column100") {
                const plotLeft = 38
                const plotWidth = Math.max(12, chart.width - plotLeft - 8)
                const plotTop = root.showLegend ? Math.max(27, root.showDataLabels ? 20 : 0) : (root.showDataLabels ? 20 : 9)
                const plotHeight = Math.max(12, chart.height - plotTop - 25)
                if (point.x >= plotLeft && point.x < plotLeft + plotWidth
                        && point.y >= plotTop && point.y < plotTop + plotHeight) {
                    const step = plotWidth / values.length
                    const candidate = Math.floor((point.x - plotLeft) / step)
                    if (candidate >= 0 && candidate < values.length) {
                        const barWidth = Math.max(5, step * 0.56)
                        const x = plotLeft + candidate * step + (step - barWidth) / 2
                        let maxValue = 0
                        for (let i = 0; i < values.length; ++i)
                            maxValue = Math.max(maxValue, Number(values[i].value) || 0)
                        const barHeight = plotHeight * (root.isHundredPercent()
                                ? 1
                                : (Number(values[candidate].value) || 0) / (maxValue || 1))
                        const barTop = plotTop + plotHeight - barHeight
                        if (point.x >= x && point.x <= x + barWidth
                                && point.y >= barTop && point.y <= plotTop + plotHeight)
                            index = candidate
                    }
                }
            } else if (root.chartType === "bar") {
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
    onLineSeriesChanged: chart.requestPaint()
    onHighlightSeriesChanged: chart.requestPaint()
    onHighlightLineSeriesChanged: chart.requestPaint()
    onGaugeDataChanged: chart.requestPaint()
    onKpiDataChanged: chart.requestPaint()
    onMapPointsChanged: chart.requestPaint()
    onHighlightMapPointsChanged: chart.requestPaint()
    onScatterPointsChanged: chart.requestPaint()
    onHighlightScatterPointsChanged: chart.requestPaint()
    onSeriesColorChanged: chart.requestPaint()
    onShowDataLabelsChanged: chart.requestPaint()
    onShowLegendChanged: chart.requestPaint()
    onChartTypeChanged: chart.requestPaint()
    onEmptyMessageChanged: chart.requestPaint()
    onSelectedChanged: chart.requestPaint()
}
