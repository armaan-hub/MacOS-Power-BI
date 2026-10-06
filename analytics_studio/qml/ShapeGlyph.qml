import QtQuick 6.5

Canvas {
    id: root
    property string shapeName: "Rectangle"
    implicitWidth: 31
    implicitHeight: 23

    function polygon(ctx, points) {
        ctx.beginPath()
        ctx.moveTo(points[0][0], points[0][1])
        for (let i = 1; i < points.length; ++i)
            ctx.lineTo(points[i][0], points[i][1])
        ctx.closePath()
        ctx.fill()
        ctx.stroke()
    }

    function rectangle(ctx, x, y, w, h) {
        ctx.beginPath()
        ctx.rect(x, y, w, h)
        ctx.fill()
        ctx.stroke()
    }

    function roundedRectangle(ctx, x, y, w, h, radius) {
        const r = Math.min(radius, w / 2, h / 2)
        ctx.beginPath()
        ctx.moveTo(x + r, y)
        ctx.lineTo(x + w - r, y)
        ctx.quadraticCurveTo(x + w, y, x + w, y + r)
        ctx.lineTo(x + w, y + h - r)
        ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h)
        ctx.lineTo(x + r, y + h)
        ctx.quadraticCurveTo(x, y + h, x, y + h - r)
        ctx.lineTo(x, y + r)
        ctx.quadraticCurveTo(x, y, x + r, y)
        ctx.closePath()
        ctx.fill()
        ctx.stroke()
    }

    function cornerRectangle(ctx, w, h, shape) {
        const x = 2, y = 3, right = w - 2, bottom = h - 3, cut = 5
        const snipped = shape.indexOf("snip") === 0
        const both = shape.indexOf("both") >= 0
        ctx.beginPath()
        if (both) {
            ctx.moveTo(x + (snipped ? cut : 4), y)
            ctx.lineTo(right - (snipped ? cut : 4), y)
            if (snipped) {
                ctx.lineTo(right, y + cut)
            } else {
                ctx.quadraticCurveTo(right, y, right, y + 4)
            }
        } else {
            ctx.moveTo(x, y)
            ctx.lineTo(right - (snipped ? cut : 4), y)
            if (snipped) {
                ctx.lineTo(right, y + cut)
            } else {
                ctx.quadraticCurveTo(right, y, right, y + 4)
            }
        }
        ctx.lineTo(right, bottom)
        ctx.lineTo(x, bottom)
        if (both) {
            if (snipped) {
                ctx.lineTo(x, y + cut)
            } else {
                ctx.lineTo(x, y + 4)
                ctx.quadraticCurveTo(x, y, x + 4, y)
            }
        }
        ctx.closePath()
        ctx.fill()
        ctx.stroke()
    }

    function arrowPoints(direction, w, h) {
        if (direction === "Right")
            return [[2,h*0.3],[w*0.64,h*0.3],[w*0.64,2],[w-2,h/2],[w*0.64,h-2],[w*0.64,h*0.7],[2,h*0.7]]
        if (direction === "Left")
            return [[w-2,h*0.3],[w*0.36,h*0.3],[w*0.36,2],[2,h/2],[w*0.36,h-2],[w*0.36,h*0.7],[w-2,h*0.7]]
        if (direction === "Up")
            return [[w*0.3,h-2],[w*0.3,h*0.38],[2,h*0.38],[w/2,2],[w-2,h*0.38],[w*0.7,h*0.38],[w*0.7,h-2]]
        return [[w*0.3,2],[w*0.3,h*0.62],[2,h*0.62],[w/2,h-2],[w-2,h*0.62],[w*0.7,h*0.62],[w*0.7,2]]
    }

    function regularPolygon(ctx, w, h, sides, rotation) {
        const points = []
        for (let i = 0; i < sides; ++i) {
            const a = rotation + i * Math.PI * 2 / sides
            points.push([w / 2 + Math.cos(a) * w * 0.43,
                         h / 2 + Math.sin(a) * h * 0.43])
        }
        polygon(ctx, points)
    }

    onPaint: {
        const ctx = getContext("2d")
        const w = width
        const h = height
        const name = shapeName.toLowerCase()
        ctx.clearRect(0, 0, w, h)
        ctx.strokeStyle = "#42484c"
        ctx.fillStyle = "#ffffff"
        ctx.lineWidth = 1.7
        ctx.lineJoin = "round"
        ctx.lineCap = "round"

        if (name === "rectangle") {
            rectangle(ctx, 2, 3, w - 4, h - 6)
        } else if (name === "rounded rectangle" || name === "capsule") {
            roundedRectangle(ctx, 2, 3, w - 4, h - 6, name === "capsule" ? h / 2 : 5)
        } else if (name.indexOf("snip ") === 0 || name.indexOf("round ") === 0) {
            cornerRectangle(ctx, w, h, name)
        } else if (name === "oval") {
            ctx.beginPath()
            ctx.ellipse(w * 0.06, h * 0.1, w * 0.88, h * 0.8)
            ctx.fill()
            ctx.stroke()
        } else if (name === "triangle") {
            polygon(ctx, [[w/2,2],[w-2,h-2],[2,h-2]])
        } else if (name === "right triangle") {
            polygon(ctx, [[3,3],[3,h-3],[w-3,h-3]])
        } else if (name === "parallelogram") {
            polygon(ctx, [[w*0.25,3],[w-2,3],[w*0.75,h-3],[2,h-3]])
        } else if (name === "trapezoid") {
            polygon(ctx, [[2,3],[w-2,3],[w*0.75,h-3],[w*0.25,h-3]])
        } else if (name === "pentagon") {
            regularPolygon(ctx, w, h, 5, -Math.PI / 2)
        } else if (name === "hexagon") {
            regularPolygon(ctx, w, h, 6, 0)
        } else if (name === "octagon") {
            regularPolygon(ctx, w, h, 8, Math.PI / 8)
            ctx.fillStyle = "#314b5b"
            ctx.font = "bold 11px sans-serif"
            ctx.textAlign = "center"
            ctx.textBaseline = "middle"
            ctx.fillText("8", w / 2, h / 2 + 0.5)
        } else if (name === "heart") {
            ctx.beginPath()
            ctx.moveTo(w/2, h-2)
            ctx.bezierCurveTo(w*0.36,h*0.78,3,h*0.48,3,h*0.3)
            ctx.bezierCurveTo(3,h*0.02,w*0.34,1,w/2,h*0.22)
            ctx.bezierCurveTo(w*0.66,1,w-3,h*0.02,w-3,h*0.3)
            ctx.bezierCurveTo(w-3,h*0.48,w*0.64,h*0.78,w/2,h-2)
            ctx.closePath()
            ctx.fill()
            ctx.stroke()
        } else if (name === "callout") {
            ctx.beginPath()
            ctx.moveTo(3,3)
            ctx.lineTo(w-3,3)
            ctx.lineTo(w-3,h*0.64)
            ctx.lineTo(w*0.62,h*0.64)
            ctx.lineTo(w*0.5,h-2)
            ctx.lineTo(w*0.43,h*0.64)
            ctx.lineTo(3,h*0.64)
            ctx.closePath()
            ctx.fill()
            ctx.stroke()
        } else if (name === "line") {
            ctx.beginPath()
            ctx.moveTo(3,3)
            ctx.lineTo(w-3,h-3)
            ctx.stroke()
        } else if (name === "right arrow") {
            polygon(ctx, arrowPoints("Right", w, h))
        } else if (name === "left arrow") {
            polygon(ctx, arrowPoints("Left", w, h))
        } else if (name === "up arrow") {
            polygon(ctx, arrowPoints("Up", w, h))
        } else if (name === "down arrow") {
            polygon(ctx, arrowPoints("Down", w, h))
        } else if (name === "right pentagon arrow") {
            polygon(ctx, [[2,2],[w*0.59,2],[w-2,h/2],[w*0.59,h-2],[2,h-2]])
        } else if (name === "chevron") {
            polygon(ctx, [[2,2],[w*0.52,2],[w-2,h/2],[w*0.52,h-2],[2,h-2],[w*0.47,h/2]])
        } else {
            rectangle(ctx, 3, 3, w - 6, h - 6)
        }
    }

    onShapeNameChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
}
