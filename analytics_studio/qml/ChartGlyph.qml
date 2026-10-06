import QtQuick 6.5

Item {
    id: root
    property string type: "bar"
    property color color: "#647382"
    implicitWidth: 24
    implicitHeight: 24

    function drawPath(ctx, points, close, fill) {
        ctx.beginPath()
        ctx.moveTo(points[0][0], points[0][1])
        for (let i = 1; i < points.length; ++i)
            ctx.lineTo(points[i][0], points[i][1])
        if (close)
            ctx.closePath()
        if (fill)
            ctx.fill()
        ctx.stroke()
    }

    function drawBars(ctx, vertical, mode) {
        const starts = [3, 9, 15]
        const values = [11, 16, 8]
        const pieces = [
            [5, 3, 3], [7, 4, 5], [3, 2, 3]
        ]
        for (let i = 0; i < 3; ++i) {
            if (vertical) {
                const total = mode === 2 ? 15 : values[i]
                let used = 0
                const segments = mode === 0 ? [total] : pieces[i]
                const sum = segments.reduce((a, b) => a + b, 0)
                for (let j = 0; j < segments.length; ++j) {
                    const h = mode === 2 ? total * segments[j] / sum : segments[j]
                    ctx.strokeRect(starts[i], 20 - used - h, 4, h)
                    used += h
                }
            } else {
                const total = mode === 2 ? 16 : values[i]
                let used = 0
                const segments = mode === 0 ? [total] : pieces[i]
                const sum = segments.reduce((a, b) => a + b, 0)
                for (let j = 0; j < segments.length; ++j) {
                    const w = mode === 2 ? total * segments[j] / sum : segments[j]
                    ctx.strokeRect(3 + used, starts[i], w, 4)
                    used += w
                }
            }
        }
    }

    function drawSlice(ctx, x, y, radius, start, end, hole) {
        ctx.beginPath()
        ctx.moveTo(x, y)
        ctx.arc(x, y, radius, start, end)
        ctx.closePath()
        ctx.fill()
        ctx.stroke()
        if (hole) {
            ctx.beginPath()
            ctx.arc(x, y, radius * 0.48, 0, Math.PI * 2)
            ctx.fillStyle = "#ffffff"
            ctx.fill()
            ctx.strokeStyle = root.color
            ctx.stroke()
        }
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        Connections {
            target: root
            function onTypeChanged() { canvas.requestPaint() }
            function onColorChanged() { canvas.requestPaint() }
        }
        onPaint: {
            const ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            ctx.save()
            ctx.scale(width / 24, height / 24)
            ctx.strokeStyle = root.color
            ctx.fillStyle = "#e8edf0"
            ctx.lineWidth = 1.4
            ctx.lineCap = "round"
            ctx.lineJoin = "round"

            switch (root.type) {
            case "bar": drawBars(ctx, false, 0); break
            case "stackedBar": drawBars(ctx, false, 1); break
            case "bar100": drawBars(ctx, false, 2); break
            case "column": drawBars(ctx, true, 0); break
            case "stackedColumn": drawBars(ctx, true, 1); break
            case "column100": drawBars(ctx, true, 2); break
            case "line":
                root.drawPath(ctx, [[3, 17], [8, 12], [12, 14], [19, 5]], false, false)
                for (const p of [[3, 17], [8, 12], [12, 14], [19, 5]]) {
                    ctx.beginPath(); ctx.arc(p[0], p[1], 1.2, 0, Math.PI * 2); ctx.fillStyle = root.color; ctx.fill()
                }
                break
            case "area":
                root.drawPath(ctx, [[3, 20], [3, 14], [8, 10], [12, 15], [18, 6], [21, 20]], true, true)
                break
            case "stackedArea":
                root.drawPath(ctx, [[3, 20], [3, 15], [8, 12], [12, 15], [18, 9], [21, 11], [21, 20]], true, true)
                root.drawPath(ctx, [[3, 15], [8, 17], [12, 14], [18, 17], [21, 15]], false, false)
                break
            case "lineStackedColumn":
                root.drawBars(ctx, true, 1)
                root.drawPath(ctx, [[3, 8], [8, 11], [13, 6], [20, 7]], false, false)
                break
            case "lineClusteredColumn":
                root.drawBars(ctx, true, 0)
                root.drawPath(ctx, [[3, 8], [8, 5], [13, 9], [20, 4]], false, false)
                break
            case "ribbon":
                root.drawPath(ctx, [[3, 6], [8, 10], [13, 6], [20, 11]], false, false)
                root.drawPath(ctx, [[3, 12], [8, 7], [13, 13], [20, 8]], false, false)
                root.drawPath(ctx, [[3, 18], [8, 15], [13, 17], [20, 14]], false, false)
                break
            case "waterfall":
                ctx.strokeRect(3, 15, 4, 6); ctx.strokeRect(8, 11, 4, 4)
                ctx.strokeRect(13, 8, 4, 3); ctx.strokeRect(18, 5, 4, 16)
                ctx.beginPath(); ctx.moveTo(7, 15); ctx.lineTo(8, 15); ctx.moveTo(12, 11); ctx.lineTo(13, 11); ctx.moveTo(17, 8); ctx.lineTo(18, 8); ctx.stroke()
                break
            case "funnel":
                root.drawPath(ctx, [[3, 4], [21, 4], [17, 10], [14, 13], [14, 20], [10, 22], [10, 13], [7, 10]], false, false)
                break
            case "scatter":
                for (const p of [[5, 17], [8, 8], [12, 13], [16, 5], [19, 16]]) { ctx.beginPath(); ctx.arc(p[0], p[1], 1.6, 0, Math.PI * 2); ctx.stroke() }
                break
            case "pie":
            case "donut":
                root.drawSlice(ctx, 12, 12, 9, -Math.PI / 2, Math.PI * 0.25, root.type === "donut")
                root.drawSlice(ctx, 12, 12, 9, Math.PI * 0.25, Math.PI * 1.15, root.type === "donut")
                root.drawSlice(ctx, 12, 12, 9, Math.PI * 1.15, Math.PI * 1.5, root.type === "donut")
                break
            case "treemap":
                ctx.strokeRect(3, 3, 18, 18); ctx.strokeRect(3, 3, 8, 9); ctx.strokeRect(11, 3, 10, 5); ctx.strokeRect(11, 8, 5, 13); ctx.strokeRect(16, 8, 5, 13)
                break
            case "map":
            case "filledMap":
                ctx.beginPath(); ctx.moveTo(3, 7); ctx.lineTo(8, 4); ctx.lineTo(12, 7); ctx.lineTo(17, 4); ctx.lineTo(21, 7); ctx.lineTo(21, 17); ctx.lineTo(16, 20); ctx.lineTo(12, 17); ctx.lineTo(7, 20); ctx.lineTo(3, 17); ctx.closePath()
                if (root.type === "filledMap") ctx.fill()
                ctx.stroke(); ctx.beginPath(); ctx.moveTo(8, 4); ctx.lineTo(7, 20); ctx.moveTo(12, 7); ctx.lineTo(12, 17); ctx.moveTo(17, 4); ctx.lineTo(16, 20); ctx.stroke()
                break
            case "shapeMap":
                root.drawPath(ctx, [[4, 7], [8, 4], [11, 7], [10, 12], [6, 14], [3, 11]], true, true)
                root.drawPath(ctx, [[14, 5], [20, 6], [21, 11], [17, 13], [13, 10]], true, true)
                root.drawPath(ctx, [[8, 16], [12, 14], [16, 17], [14, 21], [9, 20]], true, true)
                break
            case "arcgisMap":
                ctx.beginPath(); ctx.arc(11, 11, 8, 0, Math.PI * 2); ctx.stroke()
                ctx.beginPath(); ctx.arc(11, 11, 4, 0, Math.PI * 2); ctx.stroke()
                ctx.beginPath(); ctx.arc(16, 7, 3, Math.PI, 0); ctx.lineTo(16, 13); ctx.closePath(); ctx.stroke()
                break
            case "gauge":
                ctx.beginPath(); ctx.arc(12, 14, 8, Math.PI, Math.PI * 2); ctx.stroke()
                ctx.beginPath(); ctx.moveTo(12, 14); ctx.lineTo(17, 8); ctx.stroke()
                ctx.beginPath(); ctx.arc(12, 14, 1.5, 0, Math.PI * 2); ctx.fillStyle = root.color; ctx.fill()
                break
            case "card":
            case "scorecard":
                ctx.strokeRect(3, 4, 18, 16); ctx.beginPath(); ctx.moveTo(6, 9); ctx.lineTo(13, 9); ctx.moveTo(6, 13); ctx.lineTo(18, 13); ctx.moveTo(6, 17); ctx.lineTo(15, 17); ctx.stroke()
                break
            case "kpi":
                ctx.beginPath(); ctx.moveTo(4, 18); ctx.lineTo(9, 13); ctx.lineTo(13, 15); ctx.lineTo(20, 6); ctx.stroke()
                ctx.beginPath(); ctx.moveTo(16, 6); ctx.lineTo(20, 6); ctx.lineTo(20, 10); ctx.stroke()
                break
            case "slicer":
                ctx.beginPath(); ctx.moveTo(4, 7); ctx.lineTo(20, 7); ctx.moveTo(4, 12); ctx.lineTo(20, 12); ctx.moveTo(4, 17); ctx.lineTo(20, 17); ctx.stroke()
                ctx.fillStyle = "#ffffff"; ctx.beginPath(); ctx.arc(9, 7, 2, 0, Math.PI * 2); ctx.fill(); ctx.stroke()
                ctx.beginPath(); ctx.arc(15, 12, 2, 0, Math.PI * 2); ctx.fill(); ctx.stroke()
                break
            case "table":
            case "matrix":
                ctx.strokeRect(3, 4, 18, 16); ctx.beginPath(); ctx.moveTo(3, 9); ctx.lineTo(21, 9); ctx.moveTo(3, 14); ctx.lineTo(21, 14); ctx.moveTo(9, 4); ctx.lineTo(9, 20); ctx.moveTo(15, 4); ctx.lineTo(15, 20); ctx.stroke()
                break
            case "rScript":
                ctx.font = "bold 16px sans-serif"; ctx.fillStyle = root.color; ctx.fillText("R", 6, 18)
                break
            case "pythonScript":
                ctx.font = "bold 10px sans-serif"; ctx.fillStyle = root.color; ctx.fillText("Py", 3, 15); ctx.strokeRect(4, 17, 16, 3)
                break
            case "keyInfluencers":
                ctx.beginPath(); ctx.arc(8, 9, 4, 0, Math.PI * 2); ctx.stroke(); ctx.beginPath(); ctx.moveTo(11, 12); ctx.lineTo(17, 18); ctx.moveTo(14, 9); ctx.lineTo(20, 9); ctx.moveTo(17, 6); ctx.lineTo(17, 12); ctx.stroke()
                break
            case "decomposition":
                ctx.beginPath(); ctx.moveTo(6, 5); ctx.lineTo(6, 10); ctx.lineTo(12, 10); ctx.lineTo(12, 15); ctx.moveTo(12, 10); ctx.lineTo(18, 10); ctx.lineTo(18, 15); ctx.stroke()
                ctx.strokeRect(4, 3, 4, 3); ctx.strokeRect(10, 15, 4, 4); ctx.strokeRect(16, 15, 4, 4)
                break
            case "qa":
                ctx.font = "16px sans-serif"; ctx.fillStyle = root.color; ctx.fillText("?", 8, 19)
                break
            case "visualFilter":
            case "funnelFilter":
                root.drawPath(ctx, [[3, 5], [21, 5], [15, 12], [15, 19], [9, 21], [9, 12]], false, false)
                break
            case "quickVisual":
                ctx.strokeRect(4, 12, 3, 8); ctx.strokeRect(10, 8, 3, 12); ctx.strokeRect(16, 4, 3, 16)
                ctx.beginPath(); ctx.moveTo(7, 8); ctx.lineTo(10, 5); ctx.lineTo(14, 7); ctx.lineTo(19, 3); ctx.stroke()
                break
            case "smartVisual":
                ctx.beginPath(); ctx.arc(11, 11, 7, 0, Math.PI * 2); ctx.stroke()
                ctx.beginPath(); ctx.moveTo(11, 3); ctx.lineTo(11, 19); ctx.moveTo(4, 11); ctx.lineTo(18, 11); ctx.moveTo(6, 6); ctx.lineTo(16, 16); ctx.moveTo(16, 6); ctx.lineTo(6, 16); ctx.stroke()
                break
            case "image":
                ctx.strokeRect(3, 4, 18, 16); ctx.beginPath(); ctx.arc(15, 9, 1.5, 0, Math.PI * 2); ctx.stroke()
                root.drawPath(ctx, [[5, 18], [10, 12], [13, 15], [16, 12], [20, 18]], false, false)
                break
            case "moreVisuals":
                for (let y = 6; y <= 18; y += 6) for (let x = 6; x <= 18; x += 6) ctx.strokeRect(x - 1, y - 1, 2, 2)
                break
            }
            ctx.restore()
        }
    }
}
