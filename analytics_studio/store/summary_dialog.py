"""Read-only summary dialog for a large-data table (Stage B4b task 14).

Shows the numbers from ``TableStats``. It never changes the table, the
project or the store. Imported lazily by the controller, never by
``analytics_studio.store``.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analytics_studio.dialog_theme import apply_light_dialog_theme
from analytics_studio.store.stats import TableStats

WARNED_ROW_BACKGROUND = "#fff4d6"
TEXT_COLOR = "#243746"

HEADERS = (
    "Column", "Type", "Rows", "Blank cells", "Empty text", "Distinct values",
    "Longest text", "Average text length", "Approx. size", "Notes",
)
_NUMERIC_COLUMNS = frozenset({2, 3, 4, 5, 6, 7, 8})


def human_size(num_bytes: int) -> str:
    """Return a size as KB, MB or GB with one decimal."""
    if num_bytes >= 1024 ** 3:
        return f"{num_bytes / 1024 ** 3:.1f} GB"
    if num_bytes >= 1024 ** 2:
        return f"{num_bytes / 1024 ** 2:.1f} MB"
    return f"{num_bytes / 1024:.1f} KB"


class _NumericItem(QTableWidgetItem):
    """Sorts on the raw number stored in Qt.UserRole, not on the display text."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        mine = self.data(Qt.ItemDataRole.UserRole)
        theirs = other.data(Qt.ItemDataRole.UserRole)
        if isinstance(mine, (int, float)) and isinstance(theirs, (int, float)):
            return mine < theirs
        return super().__lt__(other)


class LargeTableSummaryDialog(QDialog):
    """Per-column statistics and table warnings for one store table."""

    def __init__(self, table_name: str, stats: TableStats, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        apply_light_dialog_theme(self)
        self.setWindowTitle("Large-data table summary")
        self.setMinimumSize(760, 420)
        self.resize(860, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)

        self.header_label = QLabel(
            f"{table_name}: {stats.rows:,} rows, {len(stats.columns)} columns, "
            f"about {human_size(stats.approx_bytes)} in memory"
        )
        self.header_label.setStyleSheet("font-size: 16px; font-weight: 600; color: #273b49;")
        layout.addWidget(self.header_label)

        self.summary_table = QTableWidget(len(stats.columns), len(HEADERS), self)
        self.summary_table.setHorizontalHeaderLabels(list(HEADERS))
        self.summary_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.summary_table.horizontalHeader().setStretchLastSection(True)
        self._fill(stats)
        layout.addWidget(self.summary_table, 1)

        self.warnings_label = QLabel(
            "\n".join(stats.warnings) if stats.warnings else "No warnings."
        )
        self.warnings_label.setWordWrap(True)
        self.warnings_label.setStyleSheet("color: #526477;")
        layout.addWidget(self.warnings_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.ok_button = QPushButton("OK", self)
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self.accept)
        buttons.addWidget(self.ok_button)
        layout.addLayout(buttons)

    def _fill(self, stats: TableStats) -> None:
        table = self.summary_table
        table.setSortingEnabled(False)
        for row, column in enumerate(stats.columns):
            warned = bool(column.warnings)
            values: list[tuple[str, Any]] = [
                (column.name, None),
                (column.label, None),
                (f"{column.rows:,}", column.rows),
                (f"{column.null_count:,}", column.null_count),
                (f"{column.empty_count:,}", column.empty_count),
                (f"{column.distinct_approx:,}", column.distinct_approx),
                (f"{column.max_chars:,}", column.max_chars),
                (f"{column.avg_chars:,.1f}", float(column.avg_chars)),
                (f"{column.approx_bytes:,}", column.approx_bytes),
                ("; ".join(column.warnings), None),
            ]
            for col, (text, raw) in enumerate(values):
                item = _NumericItem(text) if col in _NUMERIC_COLUMNS else QTableWidgetItem(text)
                if raw is not None:
                    item.setData(Qt.ItemDataRole.UserRole, raw)
                if col in _NUMERIC_COLUMNS:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if warned:
                    item.setBackground(QBrush(QColor(WARNED_ROW_BACKGROUND)))
                    item.setForeground(QBrush(QColor(TEXT_COLOR)))
                table.setItem(row, col, item)
        # Keep the source order: clear the sort indicator before turning sorting on.
        table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        table.setSortingEnabled(True)
