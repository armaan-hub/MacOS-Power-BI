import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

Item {
    id: root
    objectName: "modelViewRoot"
    property var appController
    property string modelTableSearchText: ""
    readonly property var visibleModelTables: root.tableCatalog.filter(function(table) {
        if (table.kind === "query" && !Boolean(table.loadEnabled))
            return false
        var query = root.modelTableSearchText.trim().toLowerCase()
        if (!query)
            return true
        if (String(table.displayName || table.name || "").toLowerCase().indexOf(query) >= 0)
            return true
        var headers = table.headers || []
        for (var index = 0; index < headers.length; ++index) {
            if (String(headers[index]).toLowerCase().indexOf(query) >= 0)
                return true
        }
        return false
    })
    signal importRequested()
    signal dataViewRequested(string sourceId)

    readonly property var tables: appController ? (appController.modelTables || []) : []
    readonly property var tableCatalog: appController ? (appController.tableCatalog || []) : []
    readonly property var relationships: appController ? (appController.modelRelationships || []) : []
    readonly property var relationshipCatalog: appController
                                                ? (appController.modelRelationshipCatalog || []) : []
    readonly property var measures: appController ? (appController.modelMeasures || []) : []
    property bool diagramMode: true
    property real diagramAvailableWidth: 0
    readonly property var diagramTables: buildDiagramTables()
    readonly property var diagramNodes: buildDiagramNodes()
    readonly property var diagramRelationships: relationshipCatalog.filter(function(relationship) {
        return Number(relationship.relationship_version) === 1
                && root.diagramNodeForTableId(String(relationship.from_table_id))
                && root.diagramNodeForTableId(String(relationship.to_table_id))
    })
    readonly property var diagramRelationshipRoutes: buildDiagramRelationshipRoutes()
    readonly property int diagramUnmappedRelationshipCount:
        Math.max(0, relationshipCatalog.length - diagramRelationships.length)
    readonly property real diagramSceneHeight: {
        var bottom = 0
        for (var index = 0; index < root.diagramNodes.length; ++index)
            bottom = Math.max(bottom, Number(root.diagramNodes[index].y)
                              + Number(root.diagramNodes[index].height))
        for (var routeIndex = 0; routeIndex < root.diagramRelationshipRoutes.length; ++routeIndex) {
            var route = root.diagramRelationshipRoutes[routeIndex]
            for (var sampleIndex = 1; sampleIndex < 32; ++sampleIndex) {
                var point = root.diagramRelationshipPoint(
                    route.fromX, route.fromY, route.controlX, route.controlY,
                    route.toX, route.toY, sampleIndex / 32
                )
                bottom = Math.max(bottom, point.y)
            }
        }
        return bottom > 0 ? bottom + 24 : 72
    }
    readonly property var calculatedTables: tableCatalog.filter(function(table) {
        return table.calculatedColumns && table.calculatedColumns.length > 0
    })
    readonly property var fields: appController ? (appController.headers || []) : []
    property string selectedModelTableId: ""
    property string selectedModelColumn: ""
    readonly property var selectedModelTable: {
        for (var index = 0; index < root.tableCatalog.length; ++index) {
            if (String(root.tableCatalog[index].id) === root.selectedModelTableId)
                return root.tableCatalog[index]
        }
        return null
    }
    readonly property string selectedModelKeyColumn: root.selectedModelTable
            ? String(root.selectedModelTable.keyColumnName || "")
            : ""
    readonly property var selectedModelKeyOptions: {
        var options = [{ "label": "No key column", "value": "", "enabled": true }]
        var table = root.selectedModelTable
        if (table && table.loaded) {
            var headers = table.headers || []
            var calculated = table.calculatedColumns || []
            for (var index = 0; index < headers.length; ++index) {
                var header = String(headers[index])
                var isCalculated = calculated.some(function(item) {
                    return String(item.name) === header
                })
                if (!isCalculated)
                    options.push({ "label": header, "value": header, "enabled": true })
            }
        }
        if (root.selectedModelKeyColumn
                && options.every(function(item) {
                    return String(item.value) !== root.selectedModelKeyColumn
                })) {
            options.push({
                "label": root.selectedModelKeyColumn + " (unavailable)",
                "value": root.selectedModelKeyColumn,
                "enabled": false
            })
        }
        return options
    }
    readonly property string selectedModelColumnType: {
        if (!root.selectedModelTable || !root.selectedModelTable.columnTypes)
            return ""
        return String(root.selectedModelTable.columnTypes[root.selectedModelColumn] || "")
    }
    readonly property bool selectedModelColumnCalculated: {
        if (!root.selectedModelTable || !root.selectedModelTable.calculatedColumns)
            return false
        return root.selectedModelTable.calculatedColumns.some(function(item) {
            return String(item.name) === root.selectedModelColumn
        })
    }
    readonly property bool selectedModelColumnLoaded: Boolean(
        root.selectedModelTable
        && root.selectedModelTable.loaded
        && root.selectedModelTable.headers
        && root.selectedModelTable.headers.indexOf(root.selectedModelColumn) >= 0
    )
    readonly property bool selectedModelColumnNumeric: ["whole_number", "decimal_number"].indexOf(
        root.selectedModelColumnType
    ) >= 0
    readonly property bool selectedModelColumnHasSortRule: Boolean(
        root.selectedModelTable
        && root.selectedModelTable.columnSortBy
        && Object.prototype.hasOwnProperty.call(
            root.selectedModelTable.columnSortBy, root.selectedModelColumn
        )
    )
    readonly property string selectedModelColumnSortBy: {
        if (!root.selectedModelColumnHasSortRule)
            return ""
        return String(root.selectedModelTable.columnSortBy[root.selectedModelColumn] || "")
    }
    readonly property var selectedModelColumnGroupByColumns: {
        if (!root.selectedModelTable || !root.selectedModelTable.groupByColumns)
            return []
        return root.selectedModelTable.groupByColumns[root.selectedModelColumn] || []
    }
    readonly property string selectedModelColumnGroupBySummary:
        root.selectedModelColumnGroupByColumns.length > 0
            ? root.selectedModelColumnGroupByColumns.join(", ")
            : "None"
    readonly property var selectedModelColumnSortStatus: {
        if (!root.selectedModelColumnHasSortRule
                || !root.selectedModelTable.columnSortByStatuses)
            return ({ "active": false, "reason": "The saved rule has not been validated." })
        return root.selectedModelTable.columnSortByStatuses[root.selectedModelColumn]
                || ({ "active": false, "reason": "The saved rule has not been validated." })
    }
    readonly property bool canEditSelectedModelSortBy: Boolean(
        root.selectedModelTable
        && root.selectedModelColumnLoaded
        && !root.selectedModelColumnCalculated
    )
    readonly property bool canEditSelectedModelGroupBy: Boolean(
        root.selectedModelTable
        && root.selectedModelColumnLoaded
        && !root.selectedModelColumnCalculated
    )
    readonly property var selectedModelSortOptions: {
        var options = [{ "label": "No sort by column", "value": "", "enabled": true }]
        if (root.canEditSelectedModelSortBy) {
            var headers = root.selectedModelTable.headers || []
            var calculated = root.selectedModelTable.calculatedColumns || []
            for (var index = 0; index < headers.length; ++index) {
                var header = String(headers[index])
                var isCalculated = calculated.some(function(item) {
                    return String(item.name) === header
                })
                if (header !== root.selectedModelColumn && !isCalculated)
                    options.push({ "label": header, "value": header, "enabled": true })
            }
            if (root.selectedModelColumnHasSortRule
                    && options.every(function(item) {
                        return String(item.value) !== root.selectedModelColumnSortBy
                    })) {
                options.push({
                    "label": root.selectedModelColumnSortBy + " (unavailable)",
                    "value": root.selectedModelColumnSortBy,
                    "enabled": false
                })
            }
        }
        return options
    }
    readonly property string selectedModelSortDescription: {
        if (!root.selectedModelTableId || !root.selectedModelColumn)
            return "Select a loaded source column to set its sort by column."
        var tableName = String(root.selectedModelTable
                               ? root.selectedModelTable.displayName
                               : root.selectedModelTableId)
        if (!root.selectedModelTable || !root.selectedModelTable.loaded)
            return "The source for " + root.selectedModelColumn + " in " + tableName
                    + " is unavailable. Its saved sort rule can be cleared in Saved sort rules."
        if (root.selectedModelColumnCalculated)
            return root.selectedModelColumn + " in " + tableName
                    + " is calculated. Sort by column is available for loaded source columns."
        if (!root.selectedModelColumnLoaded)
            return root.selectedModelColumn + " in " + tableName
                    + " is unavailable in the loaded source."
        if (root.selectedModelColumnHasSortRule) {
            var sortColumn = root.selectedModelColumnSortBy
            if (Boolean(root.selectedModelColumnSortStatus.active))
                return "Sort " + root.selectedModelColumn + " in " + tableName
                        + " by " + sortColumn + ". This rule is active for supported category consumers."
            return "Saved sort by " + sortColumn + " for " + root.selectedModelColumn
                    + " in " + tableName + " is inactive. "
                    + String(root.selectedModelColumnSortStatus.reason || "The source data no longer validates the rule.")
                    + " Clear the rule here or in Saved sort rules."
        }
        return "Choose another loaded source column to order " + root.selectedModelColumn
                + " in " + tableName + " across supported category consumers."
    }
    readonly property var savedModelSortRules: {
        var rules = []
        var catalog = root.tableCatalog || []
        for (var tableIndex = 0; tableIndex < catalog.length; ++tableIndex) {
            var table = catalog[tableIndex]
            var sortBy = table.columnSortBy || {}
            var statuses = table.columnSortByStatuses || {}
            var targets = Object.keys(sortBy).sort()
            for (var targetIndex = 0; targetIndex < targets.length; ++targetIndex) {
                var target = String(targets[targetIndex])
                var sortColumn = String(sortBy[target] || "")
                var status = statuses[target] || ({
                    "active": false,
                    "reason": table.loaded
                        ? "The saved rule has not been validated."
                        : "The table source is unavailable."
                })
                var active = Boolean(status.active)
                var reason = String(status.reason || "")
                rules.push({
                    "tableId": String(table.id),
                    "tableName": String(table.displayName || table.name || table.id),
                    "target": target,
                    "sortColumn": sortColumn,
                    "active": active,
                    "reason": reason,
                    "status": active ? "Active" : "Inactive: " + reason
                })
            }
        }
        return rules
    }
    readonly property string selectedModelColumnDescription: {
        if (!root.selectedModelTableId || !root.selectedModelColumn)
            return "Select a model column to inspect its default summarization."
        var tableName = String(root.selectedModelTable
                               ? root.selectedModelTable.displayName
                               : root.selectedModelTableId)
        if (!root.selectedModelTable || !root.selectedModelTable.loaded)
            return "The source for " + root.selectedModelColumn + " in " + tableName
                    + " is unavailable. Load the source to edit its default summarization."
        if (root.selectedModelColumnCalculated)
            return root.selectedModelColumn + " in " + tableName
                    + " is a calculated column. Default summarization is available for loaded numeric source columns."
        if (!root.selectedModelColumnNumeric)
            return root.selectedModelColumn + " in " + tableName + " has type "
                    + (root.selectedModelColumnType || "unknown")
                    + ", which is not numeric. Default summarization is available for loaded numeric source columns."
        if (!root.selectedModelColumnLoaded)
            return root.selectedModelColumn + " in " + tableName
                    + " is unavailable in the loaded source."
        return root.selectedModelColumn + " in " + tableName
                + " is a loaded numeric source column. Its default applies to newly added value fields."
    }
    readonly property bool canEditSelectedModelSummarization: Boolean(
        root.selectedModelColumnLoaded
        && root.selectedModelColumnNumeric
        && !root.selectedModelColumnCalculated
    )
    readonly property bool hasOneLoadedTable: tableCatalog.filter(function(table) {
        return Boolean(table.loaded)
    }).length === 1

    function selectModelColumn(tableId, column) {
        root.selectedModelTableId = String(tableId)
        root.selectedModelColumn = String(column)
    }

    function buildDiagramTables() {
        var tables = (root.tableCatalog || []).filter(function(table) {
            return table.kind !== "query" || Boolean(table.loadEnabled)
        })
        var tableById = ({})
        var tableOrder = ({})
        var neighbors = ({})
        for (var tableIndex = 0; tableIndex < tables.length; ++tableIndex) {
            var tableId = String(tables[tableIndex].id || "")
            tableById[tableId] = tables[tableIndex]
            tableOrder[tableId] = tableIndex
            neighbors[tableId] = []
        }
        for (var relationshipIndex = 0;
             relationshipIndex < (root.relationshipCatalog || []).length;
             ++relationshipIndex) {
            var relationship = root.relationshipCatalog[relationshipIndex]
            if (Number(relationship.relationship_version) !== 1)
                continue
            var fromId = String(relationship.from_table_id || "")
            var toId = String(relationship.to_table_id || "")
            if (!tableById[fromId] || !tableById[toId])
                continue
            if (neighbors[fromId].indexOf(toId) < 0)
                neighbors[fromId].push(toId)
            if (neighbors[toId].indexOf(fromId) < 0)
                neighbors[toId].push(fromId)
        }

        var ordered = []
        var visited = ({})
        for (var startIndex = 0; startIndex < tables.length; ++startIndex) {
            var startId = String(tables[startIndex].id || "")
            if (visited[startId])
                continue
            var queue = [startId]
            while (queue.length > 0) {
                var currentId = queue.shift()
                if (visited[currentId])
                    continue
                visited[currentId] = true
                ordered.push(tableById[currentId])
                var connectedIds = (neighbors[currentId] || []).slice().sort(function(left, right) {
                    return Number(tableOrder[left]) - Number(tableOrder[right])
                })
                for (var neighborIndex = 0; neighborIndex < connectedIds.length; ++neighborIndex) {
                    if (!visited[connectedIds[neighborIndex]])
                        queue.push(connectedIds[neighborIndex])
                }
            }
        }
        return ordered
    }

    function buildDiagramNodes() {
        var tables = root.diagramTables || []
        if (tables.length === 0)
            return []

        var hubTableId = ""
        var hubLeafCount = 0
        var hubMemberIds = ({})
        if (tables.length >= 3) {
            var tableIds = ({})
            var tableNeighbors = ({})
            for (var degreeIndex = 0; degreeIndex < tables.length; ++degreeIndex) {
                var degreeTableId = String(tables[degreeIndex].id || "")
                tableIds[degreeTableId] = true
                tableNeighbors[degreeTableId] = []
            }
            for (var edgeIndex = 0; edgeIndex < root.relationshipCatalog.length; ++edgeIndex) {
                var edge = root.relationshipCatalog[edgeIndex]
                if (Number(edge.relationship_version) !== 1)
                    continue
                var edgeFrom = String(edge.from_table_id || "")
                var edgeTo = String(edge.to_table_id || "")
                if (tableIds[edgeFrom] && tableIds[edgeTo] && edgeFrom !== edgeTo) {
                    if (tableNeighbors[edgeFrom].indexOf(edgeTo) < 0)
                        tableNeighbors[edgeFrom].push(edgeTo)
                    if (tableNeighbors[edgeTo].indexOf(edgeFrom) < 0)
                        tableNeighbors[edgeTo].push(edgeFrom)
                }
            }
            for (var hubIndex = 0; hubIndex < tables.length; ++hubIndex) {
                var candidateHubId = String(tables[hubIndex].id || "")
                var candidateNeighbors = tableNeighbors[candidateHubId]
                if (candidateNeighbors.length < 2)
                    continue
                var isStar = true
                for (var leafIndex = 0; leafIndex < candidateNeighbors.length; ++leafIndex) {
                    var leafId = candidateNeighbors[leafIndex]
                    if (tableNeighbors[leafId].length !== 1
                            || tableNeighbors[leafId][0] !== candidateHubId) {
                        isStar = false
                        break
                    }
                }
                if (isStar) {
                    hubTableId = candidateHubId
                    hubLeafCount = candidateNeighbors.length
                    hubMemberIds[hubTableId] = true
                    for (var memberIndex = 0; memberIndex < candidateNeighbors.length; ++memberIndex)
                        hubMemberIds[candidateNeighbors[memberIndex]] = true
                    break
                }
            }
        }

        var availableWidth = Math.max(240,
            Number(root.diagramAvailableWidth || root.width) - 24)
        var minCardWidth = 250
        var horizontalGap = 24
        var columns = Math.max(1, Math.min(3,
            Math.floor((availableWidth + horizontalGap) / (minCardWidth + horizontalGap))))
        var verticalHubStack = hubTableId && hubLeafCount > columns * 2
        if (verticalHubStack)
            columns = 2
        var splitHubRows = hubTableId && !verticalHubStack && hubLeafCount > columns
        var hubLayoutRowCount = verticalHubStack ? hubLeafCount
                : (splitHubRows ? 3 : 2)
        var cardWidth = Math.max(hubTableId ? 180 : 220, Math.min(360,
            (availableWidth - horizontalGap * (columns - 1)) / columns))
        var rowHeights = []
        var nodes = []
        var leafIndex = 0
        var nonHubIndex = 0
        for (var index = 0; index < tables.length; ++index) {
            var table = tables[index]
            var currentTableId = String(table.id || "")
            var height = table.loaded ? 236 : 112
            var row = Math.floor(index / columns)
            var column = index % columns
            if (hubTableId && hubMemberIds[currentTableId]) {
                if (currentTableId === hubTableId) {
                    row = verticalHubStack
                            ? Math.floor(hubLeafCount / 2)
                            : (splitHubRows ? 1 : 0)
                    column = verticalHubStack ? 0 : (columns - 1) / 2
                } else {
                    if (verticalHubStack) {
                        row = leafIndex
                        column = 1
                    } else if (splitHubRows) {
                        var topLeafCount = Math.ceil(hubLeafCount / 2)
                        var isTopLeaf = leafIndex < topLeafCount
                        var withinRowIndex = isTopLeaf
                                ? leafIndex : leafIndex - topLeafCount
                        var leavesInRow = isTopLeaf
                                ? topLeafCount : hubLeafCount - topLeafCount
                        row = isTopLeaf ? 0 : 2
                        column = leavesInRow === 1
                                ? Math.floor((columns - 1) / 2)
                                : Math.round(withinRowIndex * (columns - 1) / (leavesInRow - 1))
                    } else {
                        row = 1
                        column = hubLeafCount === 2
                                ? (leafIndex === 0 ? 0 : columns - 1)
                                : Math.round(leafIndex * (columns - 1) / (hubLeafCount - 1))
                    }
                    leafIndex += 1
                }
            } else if (hubTableId) {
                row = hubLayoutRowCount + Math.floor(nonHubIndex / columns)
                column = nonHubIndex % columns
                nonHubIndex += 1
            }
            rowHeights[row] = Math.max(rowHeights[row] || 0, height)
            nodes.push({
                "table": table,
                "id": String(table.id || ""),
                "index": index,
                "row": row,
                "column": column,
                "diagramLayout": hubMemberIds[currentTableId]
                        ? (verticalHubStack ? "hub_stack" : "hub_grid") : "grid",
                "width": cardWidth,
                "height": height
            })
        }
        var rowY = []
        var nextY = 18
        for (var rowIndex = 0; rowIndex < rowHeights.length; ++rowIndex) {
            rowY[rowIndex] = nextY
            nextY += rowHeights[rowIndex] + 58
        }
        for (var nodeIndex = 0; nodeIndex < nodes.length; ++nodeIndex) {
            nodes[nodeIndex].x = 12 + nodes[nodeIndex].column * (cardWidth + horizontalGap)
            nodes[nodeIndex].y = rowY[nodes[nodeIndex].row]
        }
        return nodes
    }

    function diagramNodeForTableId(tableId) {
        for (var index = 0; index < root.diagramNodes.length; ++index) {
            if (root.diagramNodes[index].id === String(tableId))
                return root.diagramNodes[index]
        }
        return null
    }

    function diagramRouteIntersectsOtherTable(nodes, fromTableId, toTableId,
                                              fromX, fromY, controlX, controlY,
                                              toX, toY) {
        var margin = 16
        for (var sampleIndex = 1; sampleIndex < 40; ++sampleIndex) {
            var point = root.diagramRelationshipPoint(
                fromX, fromY, controlX, controlY, toX, toY, sampleIndex / 40
            )
            for (var nodeIndex = 0; nodeIndex < nodes.length; ++nodeIndex) {
                var node = nodes[nodeIndex]
                if (node.id === String(fromTableId) || node.id === String(toTableId))
                    continue
                if (point.x >= Number(node.x) - margin
                        && point.x <= Number(node.x) + Number(node.width) + margin
                        && point.y >= Number(node.y) - margin
                        && point.y <= Number(node.y) + Number(node.height) + margin)
                    return true
            }
        }
        return false
    }

    function diagramStackPortOffset(tableId, otherTableId) {
        var neighbors = []
        var relationships = root.diagramRelationships || []
        for (var index = 0; index < relationships.length; ++index) {
            var relationship = relationships[index]
            var fromId = String(relationship.from_table_id || "")
            var toId = String(relationship.to_table_id || "")
            var neighborId = fromId === String(tableId) ? toId
                    : (toId === String(tableId) ? fromId : "")
            if (neighborId !== "" && neighborId !== String(tableId)
                    && neighbors.indexOf(neighborId) < 0)
                neighbors.push(neighborId)
        }
        neighbors.sort(function(leftId, rightId) {
            var leftNode = root.diagramNodeForTableId(leftId)
            var rightNode = root.diagramNodeForTableId(rightId)
            return Number(leftNode ? leftNode.y : 0) - Number(rightNode ? rightNode.y : 0)
        })
        var portIndex = neighbors.indexOf(String(otherTableId))
        if (portIndex < 0 || neighbors.length < 2)
            return 0
        var node = root.diagramNodeForTableId(String(tableId))
        if (!node)
            return 0
        var inset = Math.min(14, Number(node.height) * 0.08)
        var topOffset = -Number(node.height) / 2 + inset
        var bottomOffset = Number(node.height) / 2 - inset
        return topOffset + (bottomOffset - topOffset) * portIndex / (neighbors.length - 1)
    }

    function buildDiagramRelationshipRoutes() {
        var relationships = root.diagramRelationships || []
        var groups = ({})
        var pairForIndex = []
        for (var index = 0; index < relationships.length; ++index) {
            var relationship = relationships[index]
            var endpoints = [String(relationship.from_table_id), String(relationship.to_table_id)]
            endpoints.sort()
            var pairKey = endpoints.join("\u001f")
            pairForIndex[index] = pairKey
            if (!groups[pairKey])
                groups[pairKey] = []
            groups[pairKey].push(index)
        }

        var routes = []
        for (var routeIndex = 0; routeIndex < relationships.length; ++routeIndex) {
            var item = relationships[routeIndex]
            var fromNode = root.diagramNodeForTableId(String(item.from_table_id))
            var toNode = root.diagramNodeForTableId(String(item.to_table_id))
            if (!fromNode || !toNode)
                continue

            var fromCenterX = Number(fromNode.x) + Number(fromNode.width) / 2
            var fromCenterY = Number(fromNode.y) + Number(fromNode.height) / 2
            var toCenterX = Number(toNode.x) + Number(toNode.width) / 2
            var toCenterY = Number(toNode.y) + Number(toNode.height) / 2
            var dx = toCenterX - fromCenterX
            var dy = toCenterY - fromCenterY
            var length = Math.sqrt(dx * dx + dy * dy) || 1
            var normalX = -dy / length
            var normalY = dx / length
            var fromX = fromCenterX
            var fromY = fromCenterY
            var toX = toCenterX
            var toY = toCenterY
            var verticalHubStack = String(fromNode.diagramLayout) === "hub_stack"
                    && String(toNode.diagramLayout) === "hub_stack"
            if (verticalHubStack || (Number(fromNode.row) === Number(toNode.row)
                    && Math.abs(dx) >= Math.abs(dy))) {
                fromX += dx >= 0 ? Number(fromNode.width) / 2 + 8 : -Number(fromNode.width) / 2 - 8
                toX += dx >= 0 ? -Number(toNode.width) / 2 - 8 : Number(toNode.width) / 2 + 8
                if (verticalHubStack) {
                    fromY += root.diagramStackPortOffset(fromNode.id, toNode.id)
                    toY += root.diagramStackPortOffset(toNode.id, fromNode.id)
                }
            } else {
                var sourcePortX = Math.max(-Number(fromNode.width) * 0.34,
                    Math.min(Number(fromNode.width) * 0.34, dx * 0.18))
                var targetPortX = Math.max(-Number(toNode.width) * 0.34,
                    Math.min(Number(toNode.width) * 0.34, -dx * 0.18))
                fromX += sourcePortX
                toX += targetPortX
                fromY += dy >= 0 ? Number(fromNode.height) / 2 + 8 : -Number(fromNode.height) / 2 - 8
                toY += dy >= 0 ? -Number(toNode.height) / 2 - 8 : Number(toNode.height) / 2 + 8
            }

            var group = groups[pairForIndex[routeIndex]] || []
            var laneIndex = group.indexOf(routeIndex)
            var laneOffset = (laneIndex - (group.length - 1) / 2) * 20
            var canonicalFromId = String(fromNode.id) < String(toNode.id)
                    ? String(fromNode.id) : String(toNode.id)
            var orientation = String(fromNode.id) === canonicalFromId ? 1 : -1
            var orientedOffset = laneOffset * orientation
            fromX += normalX * orientedOffset * 0.5
            fromY += normalY * orientedOffset * 0.5
            toX += normalX * orientedOffset * 0.5
            toY += normalY * orientedOffset * 0.5
            var baseControlX = (fromX + toX) / 2 + normalX * orientedOffset * 1.8
            var baseControlY = (fromY + toY) / 2 + normalY * orientedOffset * 1.8
            var positiveSceneSign = Math.abs(normalY) >= Math.abs(normalX)
                    ? (normalY >= 0 ? 1 : -1)
                    : (normalX >= 0 ? 1 : -1)
            var detourOffset = 0
            for (var detourStep = 0; detourStep <= 24; ++detourStep) {
                var detourMagnitude = detourStep * 40
                var candidates = detourStep === 0
                        ? [0] : [detourMagnitude * positiveSceneSign,
                                 -detourMagnitude * positiveSceneSign]
                var foundClearRoute = false
                for (var candidateIndex = 0; candidateIndex < candidates.length; ++candidateIndex) {
                    var candidateOffset = candidates[candidateIndex]
                    var candidateControlX = baseControlX + normalX * candidateOffset
                    var candidateControlY = baseControlY + normalY * candidateOffset
                    if (!root.diagramRouteIntersectsOtherTable(
                                root.diagramNodes, fromNode.id, toNode.id, fromX, fromY,
                                candidateControlX, candidateControlY, toX, toY)) {
                        detourOffset = candidateOffset
                        foundClearRoute = true
                        break
                    }
                }
                if (foundClearRoute)
                    break
            }
            var controlX = baseControlX + normalX * detourOffset
            var controlY = baseControlY + normalY * detourOffset
            var labelPoint = root.diagramRelationshipPoint(fromX, fromY, controlX, controlY, toX, toY, 0.5)
            var fromName = String(fromNode.table.displayName || fromNode.table.name || fromNode.id)
            var toName = String(toNode.table.displayName || toNode.table.name || toNode.id)
            var active = Boolean(item.is_active)
            var cardinality = String(item.cardinality || "")
            var directions = root.relationshipFilterDirections(item)
            var directionDescription = active
                    ? "Filters are disabled."
                    : "No filter direction is configured for this inactive relationship."
            if (directions.length === 2) {
                directionDescription = active
                        ? "Filters flow in both directions."
                        : "Configured filter direction is both directions."
            } else if (directions.length === 1 && directions[0] === "from_to") {
                directionDescription = active
                        ? "Filters flow from " + fromName + " to " + toName + "."
                        : "Configured filter direction is from " + fromName + " to " + toName + "."
            } else if (directions.length === 1 && directions[0] === "to_from") {
                directionDescription = active
                        ? "Filters flow from " + toName + " to " + fromName + "."
                        : "Configured filter direction is from " + toName + " to " + fromName + "."
            }
            var cardinalityLabel = cardinality === "one_to_many" ? "one to many"
                    : (cardinality === "many_to_one" ? "many to one"
                    : (cardinality === "one_to_one" ? "one to one"
                    : (cardinality === "many_to_many" ? "many to many" : "unknown")))
            var fromMark = cardinality === "one_to_many" || cardinality === "one_to_one"
                    ? "1" : "*"
            var toMark = cardinality === "one_to_many" ? "*"
                    : (cardinality === "many_to_one" || cardinality === "one_to_one" ? "1" : "*")
            routes.push({
                "relationship": item,
                "relationshipId": String(item.id || routeIndex),
                "parallelCount": group.length,
                "laneOffset": laneOffset,
                "detourOffset": detourOffset,
                "fromX": fromX,
                "fromY": fromY,
                "controlX": controlX,
                "controlY": controlY,
                "toX": toX,
                "toY": toY,
                "labelX": labelPoint.x,
                "labelY": labelPoint.y,
                "active": active,
                "cardinality": cardinality,
                "fromMark": fromMark,
                "toMark": toMark,
                "filterDirections": directions.slice(),
                "accessibleName": (active ? "Active" : "Inactive") + " relationship: "
                        + fromName + "[" + String(item.from_column) + "] to "
                        + toName + "[" + String(item.to_column) + "]",
                "accessibleDescription": (active ? "Solid active relationship. " : "Dashed inactive relationship. ")
                        + cardinalityLabel + " cardinality. " + directionDescription
                        + " Select to inspect the source column."
            })
        }
        return routes
    }

    function diagramRelationshipPoint(fromX, fromY, controlX, controlY, toX, toY, amount) {
        var inverse = 1 - amount
        return {
            "x": inverse * inverse * fromX + 2 * inverse * amount * controlX + amount * amount * toX,
            "y": inverse * inverse * fromY + 2 * inverse * amount * controlY + amount * amount * toY
        }
    }

    function relationshipFilterDirections(relationship) {
        if (relationship.filter_direction_override === "none")
            return []
        if (relationship.filter_direction_override === "both"
                || relationship.cross_filter_direction === "both")
            return ["from_to", "to_from"]
        if (["from_to", "to_from"].indexOf(relationship.filter_direction_override) >= 0)
            return [String(relationship.filter_direction_override)]
        return relationship.cardinality === "many_to_one" ? ["to_from"] : ["from_to"]
    }

    function isRelationshipColumn(tableId, column) {
        for (var index = 0; index < root.relationshipCatalog.length; ++index) {
            var relationship = root.relationshipCatalog[index]
            if (Number(relationship.relationship_version) !== 1)
                continue
            if ((String(relationship.from_table_id) === String(tableId)
                    && String(relationship.from_column) === String(column))
                    || (String(relationship.to_table_id) === String(tableId)
                    && String(relationship.to_column) === String(column)))
                return true
        }
        return false
    }

    function drawDiagramArrow(context, x1, y1, x2, y2, color) {
        var angle = Math.atan2(y2 - y1, x2 - x1)
        var size = 7
        context.fillStyle = color
        context.beginPath()
        context.moveTo(x2, y2)
        context.lineTo(x2 - size * Math.cos(angle - Math.PI / 6),
                       y2 - size * Math.sin(angle - Math.PI / 6))
        context.lineTo(x2 - size * Math.cos(angle + Math.PI / 6),
                       y2 - size * Math.sin(angle + Math.PI / 6))
        context.closePath()
        context.fill()
    }

    Accessible.name: "Model workspace"
    Accessible.description: "Shows model tables, saved relationship diagrams and definitions, column properties including sort rules, and local measure results. Use Data view for temporary row filters or Transform data for saved query filters."

    Loader {
        anchors.fill: parent
        active: root.appController !== null && root.appController !== undefined
        sourceComponent: Component {
            ColumnLayout {
                anchors.fill: parent
                spacing: 0

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 48
                Layout.leftMargin: 18
                Layout.rightMargin: 18
                spacing: 10

                Icon {
                    name: "model"
                    color: "#526c80"
                    implicitWidth: 20
                    implicitHeight: 20
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Text {
                        text: "Model"
                        color: "#263645"
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                    }
                    Text {
                        objectName: "modelWorkspaceFilterGuidance"
                        text: "Relationships & properties · Data = preview filter; Transform = saved"
                        color: "#596a79"
                        font.pixelSize: 10
                        elide: Text.ElideRight
                        Accessible.name: text
                    }
                }

                Rectangle {
                    visible: root.appController.sourceLoaded
                    radius: 10
                    color: "#e7f4f1"
                    implicitWidth: readOnlyLabel.implicitWidth + 16
                    implicitHeight: 22
                    Text {
                        id: readOnlyLabel
                        anchors.centerIn: parent
                        text: "Local measures"
                        color: "#107c71"
                        font.pixelSize: 10
                    }
                }
                Button {
                    objectName: "modelOpenDataViewButton"
                    visible: root.width >= 810
                    text: root.width < 960 ? "Data view" : "Open Data view"
                    enabled: root.appController.sourceLoaded
                             && String(root.appController.activeTableId || "") !== ""
                    Accessible.name: "Open Data view"
                    Accessible.description: "Inspect the active table's rows and temporary preview filters. Use Transform data to save a row filter that changes the model."
                    onClicked: root.dataViewRequested(
                        String(root.appController.activeTableId)
                    )
                }
                Button {
                    objectName: "toggleModelDiagramButton"
                    text: root.diagramMode ? "Table list" : "Diagram view"
                    Accessible.name: root.diagramMode ? "Show model table list" : "Show model relationship diagram"
                    Accessible.description: root.diagramMode
                            ? "Switch to the table list and column properties."
                            : "Show model tables and their saved relationship links."
                    onClicked: root.diagramMode = !root.diagramMode
                }
                Button {
                    objectName: "newDaxMeasureButton"
                    text: "New DAX measure"
                    enabled: root.appController.sourceLoaded
                    Accessible.name: "Create a DAX measure"
                    Accessible.description: enabled
                            ? "Open the local DAX measure editor. It supports the functions listed in the editor help."
                            : "Import a table before creating a measure."
                    ToolTip.visible: hovered && !enabled
                    ToolTip.text: Accessible.description
                    onClicked: root.appController.executeCommand("newMeasure")
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: "#e4e6e8"
                border.color: "#d2d6da"
                clip: true

                ScrollView {
                    id: canvasScroll
                    objectName: "modelCanvasScrollView"
                    anchors.fill: parent
                    anchors.margins: 16
                    clip: true
                    contentWidth: availableWidth
                    ScrollBar.horizontal.policy: ScrollBar.AsNeeded
                    ScrollBar.vertical.policy: ScrollBar.AsNeeded

                    ColumnLayout {
                        id: modelCanvasContent
                        width: canvasScroll.availableWidth
                        height: Math.max(implicitHeight, canvasScroll.availableHeight)
                        spacing: 14

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: !root.appController.sourceLoaded
                                               && root.tables.length === 0
                                               && root.relationships.length === 0
                            visible: !root.appController.sourceLoaded
                            implicitHeight: Math.max(128, importPrompt.implicitHeight + 28)
                            radius: 6
                            color: "#f8f9fa"
                            border.color: "#d3d8dc"
                            Accessible.name: "No data source loaded"
                            Accessible.description: root.appController.sourceWarning !== ""
                                                    ? root.appController.sourceWarning
                                                    : "Import a CSV, Excel, JSON, XML, or Parquet file to load its table into the model."

                            RowLayout {
                                id: importPrompt
                                anchors.centerIn: parent
                                width: Math.min(parent.width - 28, implicitWidth)
                                spacing: 12

                                Icon {
                                    name: "getData"
                                    color: "#647b8e"
                                    implicitWidth: 22
                                    implicitHeight: 22
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 3
                                    Text {
                                        text: root.appController.sourceWarning !== ""
                                              ? "The linked source is unavailable"
                                              : "Add data to your model"
                                        color: "#344251"
                                        font.pixelSize: 13
                                        font.weight: Font.DemiBold
                                        wrapMode: Text.Wrap
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: root.appController.sourceWarning !== ""
                                              ? root.appController.sourceWarning
                                              : "Import a CSV, Excel, JSON, XML, or Parquet file to load its table and fields."
                                        color: "#596a79"
                                        font.pixelSize: 11
                                        wrapMode: Text.Wrap
                                    }
                                }

                                Button {
                                    text: "Import data"
                                    Accessible.name: "Import data into the model"
                                    Accessible.description: "Choose a CSV, Excel, JSON, XML, or Parquet file to link to this project."
                                    background: Rectangle { radius: 4; color: parent.hovered ? "#edf2f5" : "#f7f9fa"; border.color: "#cfd9df" }
                                    contentItem: Text { text: parent.text; color: "#405765"; font.pixelSize: 10; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                    onClicked: root.importRequested()
                                }
                            }
                        }

                        Rectangle {
                            objectName: "daxMeasuresSection"
                            Layout.fillWidth: true
                            visible: root.diagramMode
                                     ? root.measures.length > 0
                                     : root.appController.sourceLoaded || root.measures.length > 0
                            implicitHeight: root.diagramMode
                                            ? diagramMeasuresSummary.implicitHeight + 20
                                            : measuresContent.implicitHeight + 24
                            radius: 6
                            color: "#f8f9fa"
                            border.color: "#d3d8dc"
                            Accessible.name: "DAX measures"

                            RowLayout {
                                id: diagramMeasuresSummary
                                objectName: "diagramMeasuresSummary"
                                anchors.fill: parent
                                anchors.leftMargin: 12
                                anchors.rightMargin: 12
                                visible: root.diagramMode && root.measures.length > 0
                                spacing: 10

                                Icon {
                                    name: "measure"
                                    color: "#107c71"
                                    implicitWidth: 17
                                    implicitHeight: 17
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: String(root.measures.length)
                                          + (root.measures.length === 1 ? " measure" : " measures")
                                          + " · open Table list for definitions"
                                    color: "#344251"
                                    font.pixelSize: 11
                                    Accessible.name: String(root.measures.length)
                                                          + (root.measures.length === 1
                                                             ? " measure; definition is available in Table list"
                                                             : " measures; definitions are available in Table list")
                                }
                                Button {
                                    objectName: "showModelMeasureDefinitionsButton"
                                    text: "Table list"
                                    Accessible.name: "Show measure definitions in the table list"
                                    Accessible.description: "Switch to the table list to inspect measure expressions and properties."
                                    onClicked: root.diagramMode = false
                                }
                            }

                            ColumnLayout {
                                id: measuresContent
                                objectName: "daxMeasureDetails"
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 8
                                visible: !root.diagramMode

                                RowLayout {
                                    Layout.fillWidth: true
                                    Icon { name: "measure"; color: "#107c71"; implicitWidth: 17; implicitHeight: 17 }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Measures"
                                        color: "#344251"
                                        font.pixelSize: 12
                                        font.weight: Font.DemiBold
                                    }
                                    Text { text: String(root.measures.length); color: "#596a79"; font.pixelSize: 10 }
                                }

                                Rectangle { Layout.fillWidth: true; height: 1; color: "#e2e6e9" }

                                ListView {
                                    objectName: "daxMeasureList"
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: contentHeight
                                    implicitHeight: contentHeight
                                    interactive: false
                                    clip: false
                                    model: root.measures
                                    delegate: ColumnLayout {
                                        objectName: "daxMeasureDelegate"
                                        required property var modelData
                                        width: ListView.view.width
                                        spacing: 3
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Text {
                                                Layout.fillWidth: true
                                                text: String(modelData.name)
                                                color: "#344251"
                                                font.pixelSize: 11
                                                font.weight: Font.DemiBold
                                                elide: Text.ElideRight
                                            }
                                            Text {
                                                visible: Boolean(modelData.is_hidden)
                                                text: "Hidden"
                                                color: "#7a4d00"
                                                font.pixelSize: 9
                                            }
                                            Text {
                                                text: String(modelData.value || "—")
                                                color: "#107c71"
                                                font.pixelSize: 11
                                                font.weight: Font.DemiBold
                                            }
                                            Button {
                                                objectName: "editDaxMeasureButton"
                                                text: "Edit"
                                                Accessible.name: "Edit DAX measure " + String(modelData.name)
                                                Accessible.description: "Open the DAX editor with this measure's name and expression."
                                                Layout.preferredWidth: 48
                                                Layout.preferredHeight: 24
                                                onClicked: root.appController.formulaBar.beginEditMeasure(String(modelData.name))
                                            }
                                            Button {
                                                objectName: "deleteDaxMeasureButton"
                                                text: "Delete"
                                                Accessible.name: "Delete DAX measure " + String(modelData.name)
                                                Accessible.description: "Remove this measure after checking dependent formulas."
                                                Layout.preferredWidth: 56
                                                Layout.preferredHeight: 24
                                                onClicked: root.appController.deleteMeasure(String(modelData.name))
                                            }
                                        }
                                        Text {
                                            visible: String(modelData.display_folder || "").length > 0
                                            Layout.fillWidth: true
                                            text: "Folder: " + String(modelData.display_folder || "")
                                            color: "#526477"
                                            font.pixelSize: 9
                                            wrapMode: Text.Wrap
                                        }
                                        Text {
                                            visible: String(modelData.description || "").length > 0
                                            Layout.fillWidth: true
                                            text: String(modelData.description || "")
                                            color: "#526477"
                                            font.pixelSize: 9
                                            wrapMode: Text.Wrap
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: String(modelData.expression)
                                            color: "#596a79"
                                            font.pixelSize: 10
                                            wrapMode: Text.Wrap
                                        }
                                        Text {
                                            visible: String(modelData.error || "").length > 0
                                            Layout.fillWidth: true
                                            text: String(modelData.error || "")
                                            color: "#a4262c"
                                            font.pixelSize: 10
                                            wrapMode: Text.Wrap
                                        }
                                        Rectangle { Layout.fillWidth: true; height: 1; color: "#e9edef" }
                                    }
                                }

                                Text {
                                    visible: root.measures.length === 0
                                    Layout.fillWidth: true
                                    text: "No measures yet. Select New DAX measure to create one."
                                    color: "#596a79"
                                    font.pixelSize: 10
                                    wrapMode: Text.Wrap
                                }
                            }
                        }

                        Rectangle {
                            objectName: "calculatedTableDefinitions"
                            Layout.fillWidth: true
                            visible: !root.diagramMode && root.calculatedTables.length > 0
                            implicitHeight: calculatedContent.implicitHeight + 24
                            radius: 6
                            color: "#f8f9fa"
                            border.color: "#d3d8dc"
                            Accessible.name: "DAX calculated columns"

                            ColumnLayout {
                                id: calculatedContent
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 8

                                RowLayout {
                                    Layout.fillWidth: true
                                    Icon { name: "column"; color: "#107c71"; implicitWidth: 17; implicitHeight: 17 }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Calculated columns"
                                        color: "#344251"
                                        font.pixelSize: 12
                                        font.weight: Font.DemiBold
                                    }
                                }

                                Rectangle { Layout.fillWidth: true; height: 1; color: "#e2e6e9" }

                                Repeater {
                                    model: root.calculatedTables
                                    delegate: ColumnLayout {
                                        required property var modelData
                                        property var tableData: modelData
                                        Layout.fillWidth: true
                                        spacing: 4
                                        Text {
                                            Layout.fillWidth: true
                                            text: String(tableData.displayName)
                                            color: "#425261"
                                            font.pixelSize: 10
                                            font.weight: Font.DemiBold
                                        }
                                        Repeater {
                                            model: tableData.calculatedColumns
                                            delegate: ColumnLayout {
                                                required property var modelData
                                                Layout.fillWidth: true
                                                spacing: 2
                                                Text {
                                                    Layout.fillWidth: true
                                                    text: String(modelData.name)
                                                    color: "#344251"
                                                    font.pixelSize: 10
                                                    font.weight: Font.DemiBold
                                                }
                                                Text {
                                                    Layout.fillWidth: true
                                                    text: String(modelData.expression)
                                                    color: "#596a79"
                                                    font.pixelSize: 10
                                                    wrapMode: Text.Wrap
                                                }
                                            }
                                        }
                                        Rectangle { Layout.fillWidth: true; height: 1; color: "#e9edef" }
                                    }
                                }
                            }
                        }

                        Rectangle {
                            objectName: "modelSourceSummary"
                            Layout.fillWidth: true
                            visible: root.appController.sourceLoaded && !root.diagramMode
                            implicitHeight: sourceSummary.implicitHeight + 20
                            radius: 6
                            color: "#f8f9fa"
                            border.color: "#d3d8dc"
                            Accessible.name: "Loaded data source summary"

                            RowLayout {
                                id: sourceSummary
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 12

                                Icon { name: root.appController.sourceIconName; color: "#647b8e"; implicitWidth: 18; implicitHeight: 18 }
                                Text {
                                    Layout.fillWidth: true
                                    text: root.appController.sourceName
                                    color: "#344251"
                                    font.pixelSize: 12
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideMiddle
                                    Accessible.name: "Loaded source name"
                                }
                                Text {
                                    text: Number(root.appController.rowCount).toLocaleString(Qt.locale(), 'f', 0) + " rows"
                                    color: "#53616d"
                                    font.pixelSize: 10
                                    Accessible.name: Number(root.appController.rowCount).toLocaleString(Qt.locale(), 'f', 0) + " source rows"
                                }
                                Text {
                                    text: root.appController.columnCount + " columns"
                                    color: "#53616d"
                                    font.pixelSize: 10
                                    Accessible.name: root.appController.columnCount + " source columns"
                                }
                            }
                        }

                        Rectangle {
                            objectName: "modelActiveTableFields"
                            Layout.fillWidth: true
                            visible: root.appController.sourceLoaded
                                     && !root.hasOneLoadedTable
                                     && !root.diagramMode
                            implicitHeight: sourceFields.implicitHeight + 20
                            radius: 6
                            color: "#f8f9fa"
                            border.color: "#d3d8dc"
                            Accessible.name: "Fields in the active table"
                            Accessible.description: "These fields belong to the currently selected table."

                            ColumnLayout {
                                id: sourceFields
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 7

                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Fields in active table"
                                        color: "#344251"
                                        font.pixelSize: 11
                                        font.weight: Font.DemiBold
                                    }
                                    Text {
                                        text: root.appController.columnCount + " columns"
                                        color: "#53616d"
                                        font.pixelSize: 10
                                    }
                                }

                                Flow {
                                    id: sourceFieldChips
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: implicitHeight
                                    spacing: 6
                                    Repeater {
                                        model: root.fields
                                        delegate: Rectangle {
                                            required property var modelData
                                            width: Math.min(sourceFieldChips.width, fieldLabel.implicitWidth + 18)
                                            height: 24
                                            radius: 4
                                            color: "#eef1f3"
                                            HoverHandler { id: fieldHover }
                                            ToolTip.visible: fieldHover.hovered
                                            ToolTip.text: "Field " + String(modelData)
                                            ToolTip.delay: 450
                                            Text {
                                                id: fieldLabel
                                                anchors.left: parent.left
                                                anchors.right: parent.right
                                                anchors.verticalCenter: parent.verticalCenter
                                                anchors.leftMargin: Math.min(9, parent.width / 4)
                                                anchors.rightMargin: Math.min(9, parent.width / 4)
                                                text: String(modelData)
                                                color: "#425261"
                                                font.pixelSize: 10
                                                Accessible.name: "Field " + String(modelData)
                                                elide: Text.ElideRight
                                                clip: true
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        GridLayout {
                            id: tableWorkspace
                            objectName: "modelTableWorkspace"
                            Layout.fillWidth: true
                            columns: width >= 900 ? 2 : 1
                            columnSpacing: 14
                            rowSpacing: 14

                            ColumnLayout {
                                objectName: "modelTableHeaderRegion"
                                Layout.fillWidth: true
                                Layout.columnSpan: tableWorkspace.columns
                                Layout.alignment: Qt.AlignTop
                                spacing: 8

                                Text {
                                    visible: root.tables.length > 0
                                    text: root.diagramMode ? "Model diagram" : "Tables"
                                    color: "#344251"
                                    font.pixelSize: 12
                                    font.weight: Font.DemiBold
                                }

                                RowLayout {
                                    objectName: "modelTableSearchRow"
                                    visible: root.tables.length > 0 && !root.diagramMode
                                    Layout.fillWidth: true
                                    spacing: 6

                                    TextField {
                                        id: modelTableSearchField
                                        objectName: "modelTableSearch"
                                        Layout.fillWidth: true
                                        implicitHeight: 34
                                        text: root.modelTableSearchText
                                        placeholderText: "Search tables or columns"
                                        color: "#344251"
                                        placeholderTextColor: "#657483"
                                        selectionColor: "#107c71"
                                        selectedTextColor: "#ffffff"
                                        Accessible.name: "Search model tables and columns"
                                        Accessible.description: "Narrows the Table list by table or column name. It does not filter table rows or report results."
                                        onTextEdited: root.modelTableSearchText = text

                                        background: Rectangle {
                                            objectName: "modelTableSearchBackground"
                                            color: "#ffffff"
                                            property color searchBorderColor:
                                                modelTableSearchField.activeFocus
                                                ? "#107c71" : "#7c8993"
                                            border.color: searchBorderColor
                                            border.width: 1
                                            radius: 4
                                        }
                                    }

                                    Button {
                                        objectName: "clearModelTableSearchButton"
                                        visible: root.modelTableSearchText.length > 0
                                        text: "Clear"
                                        Accessible.name: "Clear model table search"
                                        Accessible.description: "Show all eligible tables in the Table list."
                                        onClicked: root.modelTableSearchText = ""
                                    }
                                }
                            }

                            ColumnLayout {
                                id: tableCardsRegion
                                Layout.fillWidth: true
                                Layout.alignment: Qt.AlignTop
                                Layout.preferredWidth: tableWorkspace.columns === 2
                                                       ? tableWorkspace.width * 0.69
                                                       : tableWorkspace.width
                                spacing: 8

                                Item {
                                    id: modelDiagram
                                    objectName: "modelRelationshipDiagram"
                                    visible: root.diagramMode
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: root.diagramSceneHeight
                                    onWidthChanged: root.diagramAvailableWidth = Math.min(width, canvasScroll.availableWidth)
                                    Component.onCompleted: root.diagramAvailableWidth = Math.min(width, canvasScroll.availableWidth)

                                    Canvas {
                                        id: relationshipCanvas
                                        anchors.fill: parent
                                        z: 0
                                        Accessible.name: "Model relationship links"
                                        Accessible.description: "Solid lines are active relationships, dashed lines are inactive, 1 and asterisk marks show cardinality, and arrows show filter direction."
                                        onPaint: {
                                            var context = getContext("2d")
                                            context.clearRect(0, 0, width, height)
                                            context.lineWidth = 2
                                            context.lineCap = "round"
                                            context.lineJoin = "round"
                                            for (var index = 0; index < root.diagramRelationshipRoutes.length; ++index) {
                                                var route = root.diagramRelationshipRoutes[index]
                                                var relationship = route.relationship
                                                var active = Boolean(relationship.is_active)
                                                var color = active ? "#107c71" : "#8a949d"
                                                context.strokeStyle = color
                                                context.setLineDash(active ? [] : [6, 5])
                                                context.beginPath()
                                                context.moveTo(route.fromX, route.fromY)
                                                context.quadraticCurveTo(
                                                    route.controlX, route.controlY, route.toX, route.toY
                                                )
                                                context.stroke()
                                                context.setLineDash([])

                                                if (active) {
                                                    var directions = root.relationshipFilterDirections(relationship)
                                                    var arrowStart = root.diagramRelationshipPoint(
                                                        route.fromX, route.fromY,
                                                        route.controlX, route.controlY,
                                                        route.toX, route.toY, 0.42
                                                    )
                                                    var arrowEnd = root.diagramRelationshipPoint(
                                                        route.fromX, route.fromY,
                                                        route.controlX, route.controlY,
                                                        route.toX, route.toY, 0.58
                                                    )
                                                    if (directions.indexOf("from_to") >= 0)
                                                        root.drawDiagramArrow(
                                                            context, arrowStart.x, arrowStart.y,
                                                            arrowEnd.x, arrowEnd.y, color
                                                        )
                                                    if (directions.indexOf("to_from") >= 0)
                                                        root.drawDiagramArrow(
                                                            context, arrowEnd.x, arrowEnd.y,
                                                            arrowStart.x, arrowStart.y, color
                                                        )
                                                }

                                                var fromMark = String(route.fromMark)
                                                var toMark = String(route.toMark)
                                                context.font = "bold 11px sans-serif"
                                                context.textAlign = "center"
                                                context.textBaseline = "middle"
                                                context.fillStyle = "#263645"
                                                var fromLabel = root.diagramRelationshipPoint(
                                                    route.fromX, route.fromY,
                                                    route.controlX, route.controlY,
                                                    route.toX, route.toY, 0.08
                                                )
                                                var toLabel = root.diagramRelationshipPoint(
                                                    route.fromX, route.fromY,
                                                    route.controlX, route.controlY,
                                                    route.toX, route.toY, 0.92
                                                )
                                                context.fillStyle = "#ffffff"
                                                context.fillRect(fromLabel.x - 7, fromLabel.y - 8, 14, 16)
                                                context.fillRect(toLabel.x - 7, toLabel.y - 8, 14, 16)
                                                context.fillStyle = "#263645"
                                                context.fillText(fromMark, fromLabel.x, fromLabel.y)
                                                context.fillText(toMark, toLabel.x, toLabel.y)
                                            }
                                        }
                                        onWidthChanged: requestPaint()
                                        onHeightChanged: requestPaint()
                                        Component.onCompleted: requestPaint()
                                        Connections {
                                            target: root.appController
                                            function onStateChanged() { relationshipCanvas.requestPaint() }
                                        }
                                    }

                                    Repeater {
                                        model: root.diagramRelationshipRoutes
                                        delegate: Button {
                                            id: relationshipLinkButton
                                            required property var modelData
                                            property var route: modelData
                                            objectName: "modelDiagramRelationshipLink_" + String(route.relationshipId)
                                            x: Number(route.labelX) - width / 2
                                            y: Number(route.labelY) - height / 2
                                            width: 22
                                            height: 22
                                            padding: 0
                                            flat: true
                                            Accessible.name: String(route.accessibleName)
                                            Accessible.description: String(route.accessibleDescription)
                                            ToolTip.visible: hovered
                                            ToolTip.delay: 350
                                            ToolTip.text: Accessible.name + ". " + Accessible.description
                                            onClicked: root.selectModelColumn(
                                                String(route.relationship.from_table_id),
                                                String(route.relationship.from_column)
                                            )
                                            background: Rectangle {
                                                objectName: "modelDiagramRelationshipLinkBackground_"
                                                             + String(route.relationshipId)
                                                property int effectiveBorderWidth:
                                                    relationshipLinkButton.activeFocus ? 2 : 1
                                                property color effectiveBorderColor:
                                                    relationshipLinkButton.activeFocus ? "#005a9e"
                                                        : (route.active ? "#107c71" : "#8a949d")
                                                radius: width / 2
                                                color: route.active ? "#ffffff" : "#f4f5f6"
                                                border.width: effectiveBorderWidth
                                                border.color: effectiveBorderColor
                                            }
                                            contentItem: Text {
                                                text: route.active ? "●" : "○"
                                                color: route.active ? "#107c71" : "#68747e"
                                                font.pixelSize: 13
                                                horizontalAlignment: Text.AlignHCenter
                                                verticalAlignment: Text.AlignVCenter
                                            }
                                        }
                                    }

                                    Repeater {
                                        model: root.diagramNodes
                                        delegate: Rectangle {
                                            required property var modelData
                                            property var tableRecord: modelData.table
                                            x: Number(modelData.x)
                                            y: Number(modelData.y)
                                            width: Number(modelData.width)
                                            height: Number(modelData.height)
                                            z: 1
                                            radius: 6
                                            color: "#ffffff"
                                            border.color: tableRecord.sourceId === root.appController.activeTableId
                                                          ? "#107c71" : "#cfd5da"
                                            border.width: tableRecord.sourceId === root.appController.activeTableId ? 2 : 1
                                            Accessible.name: "Diagram table " + String(tableRecord.displayName)
                                            Accessible.description: tableRecord.loaded
                                                    ? Number(tableRecord.rowCount).toLocaleString(Qt.locale(), 'f', 0)
                                                      + " rows, " + Number(tableRecord.columnCount) + " columns."
                                                    : "Saved table metadata; its source is unavailable."

                                            ColumnLayout {
                                                anchors.fill: parent
                                                anchors.margins: 9
                                                spacing: 5

                                                RowLayout {
                                                    Layout.fillWidth: true
                                                    Icon { name: "table"; color: "#526c80"; implicitWidth: 16; implicitHeight: 16 }
                                                    Text {
                                                        Layout.fillWidth: true
                                                        text: String(tableRecord.displayName)
                                                        color: "#2f4050"
                                                        font.pixelSize: 11
                                                        font.weight: Font.DemiBold
                                                        elide: Text.ElideRight
                                                    }
                                                }
                                                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#e2e6e9" }
                                                Text {
                                                    Layout.fillWidth: true
                                                    visible: tableRecord.loaded
                                                    text: Number(tableRecord.rowCount).toLocaleString(Qt.locale(), 'f', 0)
                                                          + " rows · " + Number(tableRecord.columnCount) + " columns"
                                                    color: "#596a79"
                                                    font.pixelSize: 9
                                                }
                                                ListView {
                                                    visible: tableRecord.loaded
                                                    Layout.fillWidth: true
                                                    Layout.fillHeight: true
                                                    model: tableRecord.loaded ? tableRecord.headers : []
                                                    property var tableData: tableRecord
                                                    clip: true
                                                    spacing: 1
                                                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                                                    delegate: Button {
                                                        required property var modelData
                                                        property string columnName: String(modelData)
                                                        property var diagramTableData: ListView.view
                                                                                         ? ListView.view.tableData
                                                                                         : null
                                                        width: ListView.view
                                                               ? ListView.view.width : 0
                                                        height: 22
                                                        padding: 2
                                                        flat: true
                                                        objectName: "modelDiagramFieldSelect_"
                                                                     + String(diagramTableData
                                                                             ? diagramTableData.id : "")
                                                                     + "_" + columnName
                                                        Accessible.name: diagramTableData
                                                                ? String(diagramTableData.displayName)
                                                                  + " column " + columnName
                                                                : "Model table column " + columnName
                                                        onClicked: root.selectModelColumn(
                                                            String(diagramTableData
                                                                   ? diagramTableData.id : ""), columnName
                                                        )
                                                        background: Rectangle {
                                                            radius: 2
                                                            color: diagramTableData
                                                                   && root.isRelationshipColumn(
                                                                       String(diagramTableData.id), columnName
                                                                   ) ? "#edf7f5" : "transparent"
                                                        }
                                                        contentItem: RowLayout {
                                                            Icon {
                                                                name: "column"
                                                                color: diagramTableData
                                                                       && root.isRelationshipColumn(
                                                                           String(diagramTableData.id), columnName
                                                                       ) ? "#107c71" : "#718191"
                                                                implicitWidth: 12
                                                                implicitHeight: 12
                                                            }
                                                            Text {
                                                                Layout.fillWidth: true
                                                                text: columnName
                                                                color: "#425261"
                                                                font.pixelSize: 9
                                                                elide: Text.ElideRight
                                                            }
                                                        }
                                                    }
                                                }
                                                Text {
                                                    visible: !tableRecord.loaded
                                                    Layout.fillWidth: true
                                                    text: "Source unavailable"
                                                    color: "#596a79"
                                                    font.pixelSize: 9
                                                    wrapMode: Text.Wrap
                                                }
                                            }
                                        }
                                    }

                                    Text {
                                        visible: root.diagramNodes.length === 0
                                        anchors.centerIn: parent
                                        text: "Add or load model tables to show them here."
                                        color: "#596a79"
                                        font.pixelSize: 10
                                    }
                                }

                                Text {
                                    visible: root.diagramMode && root.diagramUnmappedRelationshipCount > 0
                                    Layout.fillWidth: true
                                    text: String(root.diagramUnmappedRelationshipCount)
                                          + " saved relationship(s) have legacy or unavailable endpoints and are listed below."
                                    color: "#7a5a18"
                                    font.pixelSize: 9
                                    wrapMode: Text.Wrap
                                }

                                RowLayout {
                                    visible: root.diagramMode
                                    Layout.fillWidth: true
                                    Text {
                                        visible: root.diagramRelationships.length > 0
                                        Layout.fillWidth: true
                                        text: "Solid: active · dashed: inactive · 1 / *: cardinality · arrows: filter direction"
                                        color: "#596a79"
                                        font.pixelSize: 9
                                        wrapMode: Text.Wrap
                                    }
                                    Button {
                                        text: "Manage relationships"
                                        enabled: root.appController.canManageRelationships
                                        Accessible.name: "Manage model relationships"
                                        onClicked: root.appController.executeCommand("manageRelationships")
                                    }
                                }

                                Flow {
                                    id: tableCards
                                    objectName: "modelTableCardsFlow"
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: implicitHeight
                                    spacing: 12
                                    visible: root.tables.length > 0 && !root.diagramMode

                                    Repeater {
                                        model: root.visibleModelTables

                                        delegate: Rectangle {
                                    required property var modelData
                                    width: Math.max(270, Math.min(360, tableCards.width))
                                    height: modelData.loaded ? 250 : 112
                                    radius: 6
                                    color: "#ffffff"
                                    border.color: modelData.sourceId === root.appController.activeTableId
                                                  ? "#107c71" : "#cfd5da"
                                    border.width: modelData.sourceId === root.appController.activeTableId
                                                  ? 2 : 1
                                    Accessible.name: "Table " + String(modelData.displayName)
                                    Accessible.description: modelData.loaded
                                                            ? Number(modelData.rowCount).toLocaleString(Qt.locale(), 'f', 0) + " rows, "
                                                              + Number(modelData.columnCount) + " columns. "
                                                              + (["calculated_table", "calendar", "calendar_auto"].indexOf(modelData.queryOperation) >= 0
                                                                 ? "Expression: " + String(modelData.queryExpression) + ". " : "")
                                                              + (modelData.sourceId === root.appController.activeTableId
                                                                 ? "This is the active table. " : "")
                                                              + "Fields are listed below."
                                                            : "Table metadata is saved, but its source is unavailable."

                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 12
                                        spacing: 7

                                        RowLayout {
                                            Layout.fillWidth: true
                                            Icon { name: "table"; color: "#526c80"; implicitWidth: 18; implicitHeight: 18 }
                                            Text {
                                                Layout.fillWidth: true
                                                text: String(modelData.displayName)
                                                color: "#2f4050"
                                                font.pixelSize: 12
                                                font.weight: Font.DemiBold
                                                elide: Text.ElideRight
                                            }
                                            Text {
                                                text: ["calendar", "calendar_auto"].indexOf(modelData.queryOperation) >= 0
                                                      ? "Calendar table"
                                                      : (modelData.queryOperation === "calculated_table"
                                                      ? "Calculated table"
                                                      : (modelData.kind === "query" ? "Derived query" : "Table")
                                                      )
                                                color: "#596a79"
                                                font.pixelSize: 9
                                            }
                                        }

                                        Rectangle { Layout.fillWidth: true; height: 1; color: "#e2e6e9" }

                                        Text {
                                            visible: modelData.loaded
                                            Layout.fillWidth: true
                                            text: Number(modelData.rowCount).toLocaleString(Qt.locale(), 'f', 0)
                                                  + " rows  ·  " + Number(modelData.columnCount) + " columns"
                                            color: "#53616d"
                                            font.pixelSize: 10
                                        }

                                        RowLayout {
                                            visible: modelData.loaded
                                            Layout.fillWidth: true
                                            Text {
                                                Layout.fillWidth: true
                                                text: modelData.sourceId === root.appController.activeTableId
                                                      ? "Active table" : ""
                                                color: "#107c71"
                                                font.pixelSize: 9
                                            }
                                            Button {
                                                objectName: "openModelTableDataButton"
                                                property string tableSourceId: String(modelData.sourceId)
                                                text: "Open data"
                                                enabled: Boolean(modelData.loaded)
                                                Accessible.name: "Open data for " + String(modelData.displayName)
                                                Accessible.description: "Select this loaded table and inspect its rows in Data view."
                                                onClicked: root.dataViewRequested(String(modelData.sourceId))
                                            }
                                        }

                                        Text {
                                            visible: modelData.loaded
                                                     && ["calculated_table", "calendar", "calendar_auto"].indexOf(modelData.queryOperation) >= 0
                                            Layout.fillWidth: true
                                            text: String(modelData.queryExpression)
                                            color: "#596a79"
                                            font.pixelSize: 9
                                            wrapMode: Text.Wrap
                                            maximumLineCount: 2
                                            elide: Text.ElideRight
                                        }

                                        Text {
                                            visible: Boolean(modelData.dateColumn)
                                            Layout.fillWidth: true
                                            text: "Date table: " + String(modelData.dateColumn)
                                            color: "#107c41"
                                            font.pixelSize: 9
                                            elide: Text.ElideRight
                                            Accessible.name: "Marked date column " + String(modelData.dateColumn)
                                        }

                                        ListView {
                                            visible: modelData.loaded
                                            Layout.fillWidth: true
                                            Layout.fillHeight: true
                                            model: modelData.loaded ? modelData.headers : []
                                            property var tableRecord: modelData
                                            clip: true
                                            spacing: 1
                                            Accessible.name: "Fields for " + String(modelData.displayName)
                                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                                            delegate: Button {
                                                required property var modelData
                                                width: ListView.view.width
                                                height: 25
                                                objectName: "modelFieldSelect_"
                                                             + String(ListView.view.tableRecord.id)
                                                             + "_" + String(modelData)
                                                property string tableId: String(ListView.view.tableRecord.id)
                                                property string columnName: String(modelData)
                                                property string tableName: String(ListView.view.tableRecord.displayName)
                                                property string columnType: String(
                                                    ListView.view.tableRecord.columnTypes[columnName] || "unknown"
                                                )
                                                activeFocusOnTab: true
                                                Accessible.name: "Select column " + columnName + " in " + tableName
                                                Accessible.description: String(
                                                    ListView.view.tableRecord.calculatedColumns.some(function(item) {
                                                        return String(item.name) === columnName
                                                    })
                                                    ? columnName + " is a calculated column in " + tableName + ". Select it to inspect its properties."
                                                    : "Select " + columnName + " in " + tableName + ", type " + columnType + ", to inspect its model properties."
                                                )
                                                onClicked: root.selectModelColumn(tableId, columnName)
                                                background: Rectangle {
                                                    radius: 3
                                                    color: root.selectedModelTableId === parent.tableId
                                                           && root.selectedModelColumn === parent.columnName
                                                           ? "#dff2ef" : (parent.hovered ? "#eef2f4" : "#f6f8f9")
                                                    border.color: parent.activeFocus ? "#107c71" : "transparent"
                                                }
                                                RowLayout {
                                                    anchors.fill: parent
                                                    anchors.leftMargin: 7
                                                    anchors.rightMargin: 7
                                                    Icon { name: "column"; color: "#718191"; implicitWidth: 13; implicitHeight: 13 }
                                                    Text {
                                                        Layout.fillWidth: true
                                                        text: parent.parent.columnName
                                                        color: "#425261"
                                                        font.pixelSize: 10
                                                        elide: Text.ElideRight
                                                    }
                                                }
                                            }
                                        }

                                        Text {
                                            visible: !modelData.loaded
                                            Layout.fillWidth: true
                                            text: "Saved table metadata; its source is not currently loaded."
                                            color: "#596a79"
                                            font.pixelSize: 10
                                            wrapMode: Text.Wrap
                                        }
                                    }
                                        }
                                    }
                                    Text {
                                        objectName: "modelTableSearchEmptyState"
                                        visible: !root.diagramMode
                                                 && root.modelTableSearchText.trim().length > 0
                                                 && root.visibleModelTables.length === 0
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: visible ? 48 : 0
                                        text: "No tables or columns match \""
                                              + root.modelTableSearchText + "\"."
                                        color: "#596a79"
                                        font.pixelSize: 10
                                        wrapMode: Text.Wrap
                                        Accessible.name: text
                                    }
                                }
                            }

                            Rectangle {
                                objectName: "modelColumnInspector"
                                Layout.fillWidth: true
                                visible: !root.diagramMode || root.selectedModelColumn.length > 0
                                Layout.alignment: Qt.AlignTop
                                Layout.preferredWidth: tableWorkspace.columns === 2
                                                       ? tableWorkspace.width * 0.29
                                                       : tableWorkspace.width
                                Layout.minimumWidth: 220
                                Layout.preferredHeight: columnInspectorContent.implicitHeight + 24
                                radius: 6
                                color: "#ffffff"
                                border.color: "#cfd5da"
                                Accessible.name: "Selected column properties"
                                Accessible.description: root.selectedModelColumnDescription

                                ColumnLayout {
                                    id: columnInspectorContent
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 8

                                    Text {
                                        Layout.fillWidth: true
                                        text: "Column properties"
                                        color: "#344251"
                                        font.pixelSize: 12
                                        font.weight: Font.DemiBold
                                    }
                                    Rectangle { Layout.fillWidth: true; height: 1; color: "#e2e6e9" }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Table: " + (root.selectedModelTable
                                              ? String(root.selectedModelTable.displayName)
                                              : "Select a field")
                                        color: "#425261"
                                        font.pixelSize: 10
                                        wrapMode: Text.Wrap
                                    }
                                    Text {
                                        objectName: "modelTableSearchSelectionNotice"
                                        visible: !root.diagramMode
                                                 && root.modelTableSearchText.trim().length > 0
                                                 && root.selectedModelTable !== null
                                                 && root.visibleModelTables.every(function(table) {
                                                     return String(table.id) !== root.selectedModelTableId
                                                 })
                                        Layout.fillWidth: true
                                        text: "The selected table card is hidden by this search. Its column properties remain available here; clear search to show the card."
                                        color: "#596a79"
                                        font.pixelSize: 10
                                        wrapMode: Text.Wrap
                                        Accessible.name: text
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Key column"
                                        color: "#344251"
                                        font.pixelSize: 10
                                        font.weight: Font.DemiBold
                                    }
                                    ComboBox {
                                        id: modelTableKeyColumnCombo
                                        objectName: "modelTableKeyColumn"
                                        Layout.fillWidth: true
                                        model: root.selectedModelKeyOptions
                                        textRole: "label"
                                        valueRole: "value"
                                        currentIndex: {
                                            var options = root.selectedModelKeyOptions
                                            for (var index = 0; index < options.length; ++index) {
                                                if (String(options[index].value)
                                                        === root.selectedModelKeyColumn)
                                                    return index
                                            }
                                            return 0
                                        }
                                        enabled: root.selectedModelTable !== null
                                                 && root.selectedModelTable.hasModelMetadata !== false
                                                 && (Boolean(root.selectedModelTable.loaded)
                                                     || Boolean(root.selectedModelKeyColumn))
                                        Accessible.name: "Key column for "
                                                         + (root.selectedModelTable
                                                            ? String(root.selectedModelTable.displayName)
                                                            : "selected table")
                                        Accessible.description:
                                            "Choose a unique loaded source column as this table's key."
                                        delegate: ItemDelegate {
                                            required property var modelData
                                            width: modelTableKeyColumnCombo.width
                                            text: String(modelData.label)
                                            enabled: modelData.enabled !== false
                                        }
                                        onActivated: {
                                            if (root.selectedModelTable
                                                    && root.selectedModelTable.hasModelMetadata !== false
                                                    && (String(currentValue) === ""
                                                        || Boolean(root.selectedModelTable.loaded)))
                                                root.appController.set_model_key_column(
                                                    root.selectedModelTableId,
                                                    String(currentValue)
                                                )
                                        }
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "The table key is used by relationship autodetection."
                                        color: "#596a79"
                                        font.pixelSize: 9
                                        wrapMode: Text.Wrap
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Column: " + (root.selectedModelColumn || "—")
                                        color: "#425261"
                                        font.pixelSize: 10
                                        wrapMode: Text.Wrap
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Type: " + (root.selectedModelColumnType || "—")
                                        color: "#425261"
                                        font.pixelSize: 10
                                        wrapMode: Text.Wrap
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Default summarization"
                                        color: "#344251"
                                        font.pixelSize: 10
                                        font.weight: Font.DemiBold
                                    }
                                    ComboBox {
                                        objectName: "modelColumnDefaultSummarization"
                                        Layout.fillWidth: true
                                        model: [
                                            { "label": "Auto", "value": "auto" },
                                            { "label": "Sum", "value": "sum" },
                                            { "label": "Average", "value": "average" },
                                            { "label": "Count", "value": "count" }
                                        ]
                                        textRole: "label"
                                        valueRole: "value"
                                        currentIndex: {
                                            var values = ["auto", "sum", "average", "count"]
                                            var saved = root.selectedModelTable
                                                    && root.selectedModelTable.columnSummarizations
                                                    ? String(root.selectedModelTable.columnSummarizations[root.selectedModelColumn] || "auto")
                                                    : "auto"
                                            return Math.max(0, values.indexOf(saved))
                                        }
                                        enabled: root.canEditSelectedModelSummarization
                                        Accessible.name: "Default summarization for "
                                                         + (root.selectedModelColumn || "selected column")
                                        Accessible.description: root.selectedModelColumnDescription
                                        onActivated: {
                                            if (root.canEditSelectedModelSummarization)
                                                root.appController.set_column_default_summarization(
                                                    root.selectedModelTableId,
                                                    root.selectedModelColumn,
                                                    String(currentValue)
                                                )
                                        }
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: root.selectedModelColumnDescription
                                        color: "#596a79"
                                        font.pixelSize: 10
                                        wrapMode: Text.Wrap
                                        Accessible.name: "Column summarization availability"
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Sort by column"
                                        color: "#344251"
                                        font.pixelSize: 10
                                        font.weight: Font.DemiBold
                                    }
                                    ComboBox {
                                        id: modelColumnSortByCombo
                                        objectName: "modelColumnSortBy"
                                        Layout.fillWidth: true
                                        model: root.selectedModelSortOptions
                                        textRole: "label"
                                        valueRole: "value"
                                        currentIndex: {
                                            var options = root.selectedModelSortOptions
                                            for (var index = 0; index < options.length; ++index) {
                                                if (String(options[index].value)
                                                        === root.selectedModelColumnSortBy)
                                                    return index
                                            }
                                            return -1
                                        }
                                        enabled: root.canEditSelectedModelSortBy
                                        Accessible.name: "Sort by column for "
                                                         + (root.selectedModelColumn || "selected column")
                                                         + " in "
                                                         + (root.selectedModelTable
                                                            ? String(root.selectedModelTable.displayName)
                                                            : "selected table")
                                        Accessible.description: root.selectedModelSortDescription
                                        delegate: ItemDelegate {
                                            required property var modelData
                                            width: modelColumnSortByCombo.width
                                            text: String(modelData.label)
                                            enabled: modelData.enabled !== false
                                        }
                                        onActivated: {
                                            if (root.canEditSelectedModelSortBy)
                                                root.appController.set_model_column_sort_by(
                                                    root.selectedModelTableId,
                                                    root.selectedModelColumn,
                                                    String(currentValue)
                                                )
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        visible: root.selectedModelColumnHasSortRule
                                        Text {
                                            Layout.fillWidth: true
                                            text: Boolean(root.selectedModelColumnSortStatus.active)
                                                  ? "Active"
                                                  : "Inactive: " + String(
                                                        root.selectedModelColumnSortStatus.reason
                                                        || "The saved rule is not valid for the current source."
                                                    )
                                            color: Boolean(root.selectedModelColumnSortStatus.active)
                                                   ? "#107c71" : "#8a4b08"
                                            font.pixelSize: 9
                                            wrapMode: Text.Wrap
                                            Accessible.name: "Sort rule status for "
                                                             + root.selectedModelColumn + " in "
                                                             + (root.selectedModelTable
                                                                ? String(root.selectedModelTable.displayName)
                                                                : root.selectedModelTableId)
                                            Accessible.description: text
                                        }
                                        Button {
                                            objectName: "modelColumnSortClearSelected"
                                            text: "Clear"
                                            visible: root.selectedModelColumnHasSortRule
                                            enabled: root.selectedModelTable !== null
                                            activeFocusOnTab: true
                                            Accessible.name: "Clear sort by column for "
                                                             + root.selectedModelColumn + " in "
                                                             + (root.selectedModelTable
                                                                ? String(root.selectedModelTable.displayName)
                                                                : root.selectedModelTableId)
                                            Accessible.description: "Remove the saved sort rule for "
                                                                    + root.selectedModelColumn + " in "
                                                                    + (root.selectedModelTable
                                                                       ? String(root.selectedModelTable.displayName)
                                                                       : root.selectedModelTableId)
                                                                    + ". " + root.selectedModelSortDescription
                                            onClicked: root.appController.clear_model_column_sort_by(
                                                root.selectedModelTableId,
                                                root.selectedModelColumn
                                            )
                                        }
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        visible: !root.selectedModelColumnHasSortRule
                                        text: root.selectedModelSortDescription
                                        color: "#596a79"
                                        font.pixelSize: 10
                                        wrapMode: Text.Wrap
                                        Accessible.name: "Sort by column availability"
                                        Accessible.description: text
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Group by columns"
                                        color: "#344251"
                                        font.pixelSize: 10
                                        font.weight: Font.DemiBold
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: root.selectedModelColumnGroupBySummary
                                        color: "#425261"
                                        font.pixelSize: 10
                                        wrapMode: Text.Wrap
                                        Accessible.name: "Group by columns for "
                                                         + (root.selectedModelColumn || "selected column")
                                    }
                                    Button {
                                        objectName: "modelColumnGroupByEdit"
                                        text: "Edit group by columns…"
                                        enabled: root.canEditSelectedModelGroupBy
                                        Accessible.name: "Edit group by columns for "
                                                         + root.selectedModelColumn
                                        Accessible.description:
                                            "Choose same-table columns that identify this field."
                                        onClicked: root.appController.edit_model_column_group_by(
                                                       root.selectedModelTableId,
                                                       root.selectedModelColumn
                                                   )
                                    }
                                }
                            }
                        }

                        Rectangle {
                            objectName: "modelSavedSortRules"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 200
                            Layout.preferredWidth: 320
                            Layout.minimumHeight: 132
                            implicitHeight: 44 + Math.max(1, root.savedModelSortRules.length) * 56
                            Layout.preferredHeight: 44 + Math.max(1, root.savedModelSortRules.length) * 56
                            radius: 6
                            color: "#f8f9fa"
                            border.color: "#d3d8dc"
                            Accessible.name: "Saved sort rules"
                            Accessible.description: "Saved category sort rules for all model tables, including unavailable and load-disabled tables."

                            ColumnLayout {
                                id: savedSortRulesContent
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 7

                                RowLayout {
                                    id: savedSortRulesHeader
                                    Layout.fillWidth: true
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Saved sort rules"
                                        color: "#344251"
                                        font.pixelSize: 11
                                        font.weight: Font.DemiBold
                                        Accessible.name: "Saved sort rules"
                                    }
                                    Text {
                                        text: String(root.savedModelSortRules.length)
                                        color: "#596a79"
                                        font.pixelSize: 10
                                        Accessible.name: String(root.savedModelSortRules.length)
                                                       + " saved sort rules"
                                    }
                                }

                                Text {
                                    visible: root.savedModelSortRules.length === 0
                                    Layout.fillWidth: true
                                    text: "No saved sort rules yet."
                                    color: "#596a79"
                                    font.pixelSize: 10
                                    Accessible.name: text
                                }

                                Repeater {
                                    model: root.savedModelSortRules
                                    delegate: Rectangle {
                                        required property var modelData
                                        required property int index
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: Math.max(48, savedSortRuleRow.implicitHeight + 8)
                                        radius: 4
                                        color: "#ffffff"
                                        border.color: "#e0e5e8"
                                        Accessible.name: "Sort rule for " + String(modelData.target)
                                                         + " in " + String(modelData.tableName)
                                        Accessible.description: "Sort by "
                                                                + String(modelData.sortColumn) + ". "
                                                                + String(modelData.status)

                                        RowLayout {
                                            id: savedSortRuleRow
                                            anchors.fill: parent
                                            anchors.margins: 6
                                            spacing: 8

                                            ColumnLayout {
                                                Layout.fillWidth: true
                                                spacing: 2
                                                Text {
                                                    Layout.fillWidth: true
                                                    text: String(modelData.tableName) + " · "
                                                          + String(modelData.target) + " → "
                                                          + String(modelData.sortColumn)
                                                    color: "#425261"
                                                    font.pixelSize: 10
                                                    wrapMode: Text.Wrap
                                                    Accessible.name: String(modelData.tableName)
                                                                   + ", " + String(modelData.target)
                                                                   + " sorted by "
                                                                   + String(modelData.sortColumn)
                                                }
                                                Text {
                                                    Layout.fillWidth: true
                                                    text: String(modelData.status)
                                                    color: modelData.active ? "#107c71" : "#8a4b08"
                                                    font.pixelSize: 9
                                                    wrapMode: Text.Wrap
                                                    Accessible.name: String(modelData.status)
                                                }
                                            }

                                            Button {
                                                id: savedSortRuleClearButton
                                                objectName: "modelSavedSortRuleClear_"
                                                             + String(modelData.tableId) + "_"
                                                             + String(modelData.target)
                                                text: "Clear"
                                                activeFocusOnTab: true
                                                Accessible.name: "Clear sort by column for "
                                                                 + String(modelData.target) + " in "
                                                                 + String(modelData.tableName)
                                                Accessible.description: "Remove the saved sort rule "
                                                                        + "for " + String(modelData.target)
                                                                        + " in " + String(modelData.tableName)
                                                                        + ". Sort by "
                                                                        + String(modelData.sortColumn)
                                                                        + ". " + String(modelData.status)
                                                onActiveFocusChanged: {
                                                    if (!activeFocus)
                                                        return
                                                    Qt.callLater(function() {
                                                        var flickable = canvasScroll.contentItem
                                                        var itemY = savedSortRuleClearButton.mapToItem(
                                                            modelCanvasContent, 0, 0
                                                        ).y
                                                        var currentY = Number(flickable.contentY)
                                                        var viewportHeight = canvasScroll.availableHeight
                                                        if (itemY < currentY)
                                                            flickable.contentY = itemY
                                                        else if (itemY + savedSortRuleClearButton.height
                                                                 > currentY + viewportHeight)
                                                            flickable.contentY = itemY
                                                                    + savedSortRuleClearButton.height
                                                                    - viewportHeight
                                                    })
                                                }
                                                onClicked: root.appController.clear_model_column_sort_by(
                                                    String(modelData.tableId),
                                                    String(modelData.target)
                                                )
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            visible: root.appController.sourceLoaded
                                     || root.tables.length > 0
                                     || root.relationships.length > 0
                            implicitHeight: relationshipContent.implicitHeight + 20
                            radius: 6
                            color: "#f8f9fa"
                            border.color: "#d3d8dc"
                            Accessible.name: "Saved relationships"
                            Accessible.description: "Saved relationships between model columns. Use Modeling to create, edit, or remove them."

                            ColumnLayout {
                                id: relationshipContent
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 8

                                RowLayout {
                                    Layout.fillWidth: true
                                    Icon { name: "relationship"; color: "#526c80"; implicitWidth: 17; implicitHeight: 17 }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Relationships"
                                        color: "#344251"
                                        font.pixelSize: 12
                                        font.weight: Font.DemiBold
                                    }
                                    Text {
                                        text: String(root.relationships.length)
                                        color: "#596a79"
                                        font.pixelSize: 10
                                        Accessible.name: String(root.relationships.length) + " saved relationships"
                                    }
                                }

                                Rectangle { Layout.fillWidth: true; height: 1; color: "#e2e6e9" }

                                Repeater {
                                    objectName: "savedRelationshipRepeater"
                                    model: root.relationships
                                    delegate: Text {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        text: String(modelData)
                                        color: "#425261"
                                        font.pixelSize: 11
                                        wrapMode: Text.Wrap
                                        Accessible.name: "Saved relationship: " + String(modelData)
                                    }
                                }

                                Text {
                                    visible: root.relationships.length === 0
                                    Layout.fillWidth: true
                                    text: "No relationships yet. Use Modeling → Manage relationships to connect columns from loaded tables. Active relationships can filter qualified measures; built-in charts and general visual filters still use the active table."
                                    color: "#596a79"
                                    font.pixelSize: 10
                                    wrapMode: Text.Wrap
                                    Accessible.name: text
                                }
                            }
                        }
                    }
                }
            }
            }
        }
    }
}
