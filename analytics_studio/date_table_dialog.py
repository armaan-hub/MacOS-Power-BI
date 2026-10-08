"""Dialog for marking a loaded model column as a date table."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from analytics_studio.date_tables import DateTableError, validate_date_table_rows
from analytics_studio.file_import import ImportCandidate


class DateTableDialog(QDialog):
    """Choose a loaded Date/DateTime column, or clear its date-table mark."""

    def __init__(
        self,
        tables: list[dict[str, Any]],
        candidates: dict[str, ImportCandidate],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tables = [dict(table) for table in tables]
        self._candidates = dict(candidates)
        self._accepted_source_id = ""
        self._accepted_column = ""
        self._action = ""
        self.setWindowTitle("Mark as date table")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(9)
        title = QLabel("Choose the date column for a model table")
        title.setStyleSheet("font-size: 17px; font-weight: 600; color: #273b49;")
        layout.addWidget(title)
        help_label = QLabel(
            "The column must use the Date or DateTime model type, contain unique "
            "nonblank dates, and cover every day in its range. DateTime values "
            "must use the same time of day."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #526477;")
        layout.addWidget(help_label)

        form = QFormLayout()
        self.table_combo = QComboBox()
        self.column_combo = QComboBox()
        for table in self._tables:
            self.table_combo.addItem(
                str(table.get("displayName", table.get("name", "Table"))),
                str(table.get("sourceId", "")),
            )
        form.addRow("Model table", self.table_combo)
        form.addRow("Date column", self.column_combo)
        layout.addLayout(form)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        self.mark_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.mark_button.setText("Mark as date table")
        self.clear_button = QPushButton("Clear mark")
        self.buttons.addButton(self.clear_button, QDialogButtonBox.ButtonRole.ResetRole)
        self.buttons.accepted.connect(self._accept_mark)
        self.buttons.rejected.connect(self.reject)
        self.clear_button.clicked.connect(self._clear_mark)
        layout.addWidget(self.buttons)

        self.table_combo.currentIndexChanged.connect(self._refresh_columns)
        self.column_combo.currentIndexChanged.connect(self._refresh_validation)
        self._refresh_columns()

    @property
    def source_id(self) -> str:
        return self._accepted_source_id

    @property
    def date_column(self) -> str:
        return self._accepted_column

    @property
    def action(self) -> str:
        return self._action

    def _selected_table(self) -> dict[str, Any] | None:
        source_id = str(self.table_combo.currentData() or "")
        return next((
            table for table in self._tables
            if str(table.get("sourceId", "")) == source_id
        ), None)

    def _refresh_columns(self, *_args: Any) -> None:
        table = self._selected_table()
        type_map = (table or {}).get("columnTypes", {})
        columns = [
            str(column) for column in (table or {}).get("headers", [])
            if type_map.get(column) in {"date", "datetime"}
        ]
        previous = str((table or {}).get("dateColumn", ""))
        self.column_combo.blockSignals(True)
        self.column_combo.clear()
        self.column_combo.addItems(columns)
        if previous in columns:
            self.column_combo.setCurrentText(previous)
        self.column_combo.blockSignals(False)
        self.clear_button.setEnabled(bool((table or {}).get("dateColumn")))
        self._refresh_validation()

    def _refresh_validation(self, *_args: Any) -> None:
        table = self._selected_table()
        source_id = str(self.table_combo.currentData() or "")
        column = self.column_combo.currentText()
        self._accepted_source_id = ""
        self._accepted_column = ""
        self._action = ""
        self.mark_button.setEnabled(False)
        if table is None or not source_id or not column:
            self.error_label.setText(
                "Set a loaded column's model type to Date or DateTime before marking it."
            )
            self.error_label.setVisible(True)
            return
        candidate = self._candidates.get(source_id)
        column_type = str(table.get("columnTypes", {}).get(column, ""))
        try:
            if candidate is None or column not in candidate.headers:
                raise DateTableError("The selected date column is not loaded.")
            count = validate_date_table_rows(candidate.rows, column, column_type)
        except DateTableError as exc:
            self.error_label.setText(str(exc))
            self.error_label.setStyleSheet("color: #a4262c;")
            self.error_label.setVisible(True)
            return
        self._accepted_source_id = source_id
        self._accepted_column = column
        self.error_label.setText(f"{count:,} dates are valid and continuous.")
        self.error_label.setStyleSheet("color: #107c41;")
        self.error_label.setVisible(True)
        self.mark_button.setEnabled(True)

    def _accept_mark(self) -> None:
        self._refresh_validation()
        if not self._accepted_source_id or not self._accepted_column:
            return
        self._action = "mark"
        super().accept()

    def _clear_mark(self) -> None:
        table = self._selected_table()
        if table is None or not table.get("dateColumn"):
            return
        self._accepted_source_id = str(table.get("sourceId", ""))
        self._accepted_column = ""
        self._action = "clear"
        super().accept()
