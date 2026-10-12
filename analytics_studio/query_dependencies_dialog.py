"""Read-only dependency diagram for the local Power Query session."""

from __future__ import annotations

from math import atan2, cos, sin
from typing import Any

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPen, QPolygonF
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGraphicsLineItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from analytics_studio.dialog_theme import apply_light_dialog_theme


class QueryDependenciesDialog(QDialog):
    """Show source-to-query dependencies captured by the current editor session."""

    NODE_WIDTH = 248
    NODE_HEIGHT = 104
    COLUMN_GAP = 102
    ROW_GAP = 34

    def __init__(
        self,
        queries: list[dict[str, Any]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        apply_light_dialog_theme(self)
        self.setWindowTitle("Query dependencies")
        self.setMinimumSize(760, 500)
        self.resize(1080, 700)
        self.node_items: dict[str, QGraphicsRectItem] = {}
        self.dependency_edges: list[tuple[str, str]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)
        title = QLabel("Query dependencies")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #273b49;")
        layout.addWidget(title)
        explanation = QLabel(
            "Arrows show which source or query feeds each query. Changes flow from left to right."
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet("color: #526477;")
        layout.addWidget(explanation)

        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene, self)
        self.view.setObjectName("powerQueryDependencyDiagram")
        self.view.setBackgroundBrush(QColor("#f4f6f8"))
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setMinimumHeight(340)
        layout.addWidget(self.view, 1)

        footer = QHBoxLayout()
        self.summary_label = QLabel()
        self.summary_label.setStyleSheet("color: #526477;")
        footer.addWidget(self.summary_label, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.connect(self.reject)
        footer.addWidget(self.buttons)
        layout.addLayout(footer)

        self._build_diagram(queries)

    def _build_diagram(self, queries: list[dict[str, Any]]) -> None:
        query_by_id = {
            str(query.get("id", "")).strip(): query
            for query in queries
            if str(query.get("id", "")).strip()
        }
        order = {query_id: index for index, query_id in enumerate(query_by_id)}
        parents: dict[str, list[str]] = {}
        missing_parent_count = 0
        for query_id, query in query_by_id.items():
            definition = query.get("query_definition", {})
            source_ids = definition.get("source_ids", []) if isinstance(definition, dict) else []
            valid_parents = [
                str(parent_id) for parent_id in source_ids
                if str(parent_id) in query_by_id and str(parent_id) != query_id
            ]
            parents[query_id] = valid_parents
            missing_parent_count += max(0, len(source_ids) - len(valid_parents))
            self.dependency_edges.extend((parent_id, query_id) for parent_id in valid_parents)

        depth_by_id: dict[str, int] = {}
        visiting: set[str] = set()

        def depth(query_id: str) -> int:
            cached = depth_by_id.get(query_id)
            if cached is not None:
                return cached
            if query_id in visiting:
                return 0
            visiting.add(query_id)
            parent_depths = [depth(parent_id) for parent_id in parents[query_id]]
            visiting.remove(query_id)
            value = max(parent_depths, default=-1) + 1
            depth_by_id[query_id] = value
            return value

        columns: dict[int, list[str]] = {}
        for query_id in query_by_id:
            columns.setdefault(depth(query_id), []).append(query_id)
        for values in columns.values():
            values.sort(key=order.__getitem__)

        positions: dict[str, tuple[float, float]] = {}
        for column_index, query_ids in columns.items():
            for row_index, query_id in enumerate(query_ids):
                positions[query_id] = (
                    36 + column_index * (self.NODE_WIDTH + self.COLUMN_GAP),
                    36 + row_index * (self.NODE_HEIGHT + self.ROW_GAP),
                )

        for parent_id, child_id in self.dependency_edges:
            source_x, source_y = positions[parent_id]
            target_x, target_y = positions[child_id]
            start = QPointF(source_x + self.NODE_WIDTH, source_y + self.NODE_HEIGHT / 2)
            end = QPointF(target_x, target_y + self.NODE_HEIGHT / 2)
            line = QGraphicsLineItem(start.x(), start.y(), end.x(), end.y())
            line.setPen(QPen(QColor("#728497"), 2))
            line.setZValue(0)
            self.scene.addItem(line)
            angle = atan2(end.y() - start.y(), end.x() - start.x())
            arrow_length = 12
            arrow_width = 5
            base_x = end.x() - arrow_length * cos(angle)
            base_y = end.y() - arrow_length * sin(angle)
            arrow = QPolygonF([
                end,
                QPointF(
                    base_x + arrow_width * sin(angle),
                    base_y - arrow_width * cos(angle),
                ),
                QPointF(
                    base_x - arrow_width * sin(angle),
                    base_y + arrow_width * cos(angle),
                ),
            ])
            arrow_item = QGraphicsPolygonItem(arrow)
            arrow_item.setPen(QPen(QColor("#728497"), 1))
            arrow_item.setBrush(QBrush(QColor("#728497")))
            arrow_item.setZValue(0)
            self.scene.addItem(arrow_item)

        for query_id, query in query_by_id.items():
            x, y = positions[query_id]
            query_kind = self._query_kind(query)
            is_unavailable = query.get("is_unavailable") is True
            border = QColor("#b74b52") if is_unavailable else QColor("#1776ad")
            card = self.scene.addRect(
                x,
                y,
                self.NODE_WIDTH,
                self.NODE_HEIGHT,
                QPen(border, 2),
                QBrush(QColor("#ffffff")),
            )
            card.setZValue(1)
            self.node_items[query_id] = card

            name = str(query.get("name", query_id)).strip() or query_id
            group = str(query.get("query_group", "")).strip()
            heading = QGraphicsTextItem(name, card)
            heading.setDefaultTextColor(QColor("#18364a"))
            heading.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            heading.setTextWidth(self.NODE_WIDTH - 20)
            heading.setPos(x + 10, y + 8)

            details = QGraphicsTextItem(self._details(query, query_kind, group), card)
            details.setDefaultTextColor(QColor("#526477"))
            details.setFont(QFont("Arial", 9))
            details.setTextWidth(self.NODE_WIDTH - 20)
            details.setPos(x + 10, y + 37)

        bounds = self.scene.itemsBoundingRect().adjusted(-24, -24, 24, 24)
        if bounds.isNull():
            bounds.setRect(0, 0, self.NODE_WIDTH + 48, self.NODE_HEIGHT + 48)
        self.scene.setSceneRect(bounds)
        if self.node_items:
            self.view.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

        self.summary_label.setText(
            f"{len(query_by_id):,} queries · {len(self.dependency_edges):,} dependencies"
            + (f" · {missing_parent_count:,} parent reference(s) outside this session" if missing_parent_count else "")
        )

    @staticmethod
    def _query_kind(query: dict[str, Any]) -> str:
        definition = query.get("query_definition", {})
        operation = definition.get("operation") if isinstance(definition, dict) else None
        if query.get("is_duplicate"):
            return "Duplicate"
        return {
            "reference": "Reference query",
            "append": "Append query",
            "merge": "Merge query",
            "calculated_table": "Calculated table",
            "date_table": "Date table",
        }.get(str(operation), "Source query")

    @staticmethod
    def _details(query: dict[str, Any], kind: str, group: str) -> str:
        definition = query.get("query_definition", {})
        operation = str(definition.get("operation", "")) if isinstance(definition, dict) else ""
        if operation == "merge":
            join_kind = str(definition.get("join_kind", "")).replace("_", " ")
            kind = f"Merge · {join_kind}" if join_kind else kind
        elif operation == "calculated_table":
            kind = "Calculated table"
        details = [kind]
        if group:
            details.append(f"Group: {group}")
        if query.get("is_unavailable"):
            details.append("Preview unavailable")
        elif query.get("load_enabled") is False:
            details.append("Load disabled")
        else:
            steps = query.get("steps", [])
            if steps:
                details.append(f"{len(steps)} applied step(s)")
            if query.get("include_in_report_refresh") is False:
                details.append("Refresh disabled")
        return "\n".join(details)
