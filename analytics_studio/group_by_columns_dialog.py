"""Edit the companion columns used to group a model column."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


class GroupByColumnsDialog(QDialog):
    """Choose same-table columns that identify the selected model column."""

    def __init__(
        self,
        table_name: str,
        column_name: str,
        headers: list[str],
        selected_columns: list[str],
        parent=None,
        *,
        available_headers: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Group by columns")
        self.setMinimumSize(420, 430)
        self.resize(500, 520)
        self._items: list[QListWidgetItem] = []
        self._selected_order = list(selected_columns)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        heading = QLabel(f"Group {table_name}[{column_name}] by columns")
        heading.setStyleSheet("font-size: 18px; font-weight: 600; color: #273b49;")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        note = QLabel(
            "Select the same-table columns that identify this field. "
            "Clear all selections to remove the grouping metadata."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #526477;")
        layout.addWidget(note)

        self.columns = QListWidget()
        self.columns.setAccessibleName(f"Group by columns for {column_name}")
        self.columns.setStyleSheet(
            "QListWidget { background: #ffffff; border: 1px solid #cfd8df; } "
            "QListWidget::item { padding: 5px 7px; }"
        )
        selected = set(selected_columns)
        available = set(available_headers if available_headers is not None else headers)
        for header in headers:
            if header == column_name:
                continue
            name = str(header)
            is_available = name in available and name != column_name
            item = QListWidgetItem(
                name if is_available else f"{name} (unavailable)"
            )
            item.setData(Qt.ItemDataRole.UserRole, name)
            if not is_available:
                item.setToolTip("This saved column is not currently loaded.")
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
            )
            item.setCheckState(
                Qt.CheckState.Checked if header in selected else Qt.CheckState.Unchecked
            )
            self.columns.addItem(item)
            self._items.append(item)
        layout.addWidget(self.columns, 1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    @property
    def selected_columns(self) -> list[str]:
        checked = {
            str(item.data(Qt.ItemDataRole.UserRole))
            for item in self._items
            if item.checkState() == Qt.CheckState.Checked
        }
        result = [column for column in self._selected_order if column in checked]
        result.extend(
            str(item.data(Qt.ItemDataRole.UserRole))
            for item in self._items
            if item.checkState() == Qt.CheckState.Checked
            and str(item.data(Qt.ItemDataRole.UserRole)) not in self._selected_order
        )
        return result
