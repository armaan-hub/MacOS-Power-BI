"""Generate a saved calendar table from a date range or model dates."""

from __future__ import annotations

import calendar
from copy import deepcopy
from datetime import date
from typing import Any

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from analytics_studio.calendar_tables import (
    CalendarTableError,
    calendar_expression,
    generate_calendar,
    generate_calendar_auto,
)
from analytics_studio.file_import import ImportCandidate
from analytics_studio.import_preview_dialog import ImportPreviewTableModel


class CalendarTableDialog(QDialog):
    """Preview a fixed or model-driven contiguous calendar table."""

    def __init__(
        self,
        tables: list[dict[str, Any]],
        candidates: dict[str, ImportCandidate],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tables = [dict(table) for table in tables]
        self._candidates = dict(candidates)
        self._auto_source_ids: list[str] = []
        self._date_columns = self._find_model_date_columns()
        self._accepted_candidate: ImportCandidate | None = None
        self._accepted_definition: dict[str, Any] = {}
        self._accepted_output_types: dict[str, str] = {}
        self.setWindowTitle("New calendar table")
        self.setMinimumSize(680, 470)
        self.resize(820, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(9)
        title = QLabel("Generate a contiguous calendar table")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #273b49;")
        layout.addWidget(title)
        help_label = QLabel(
            "Choose an inclusive date range or automatically span the loaded model's "
            "Date and DateTime columns. Automatic calendars expand to full fiscal years "
            "and recalculate when their source data refreshes."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #526477;")
        layout.addWidget(help_label)

        self.form = QFormLayout()
        self.table_name_edit = QLineEdit("Calendar")
        self.table_name_edit.setMaxLength(120)
        self.range_mode_combo = QComboBox()
        self.range_mode_combo.addItem("Fixed date range (CALENDAR)", "calendar")
        self.range_mode_combo.addItem("Automatic from model dates (CALENDARAUTO)", "calendar_auto")

        current_year = QDate.currentDate().year()
        self.start_date_edit = QDateEdit(QDate(current_year, 1, 1))
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.end_date_edit = QDateEdit(QDate(current_year, 12, 31))
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.range_widget = QWidget()
        range_layout = QHBoxLayout(self.range_widget)
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.addWidget(self.start_date_edit)
        range_layout.addWidget(QLabel("through"))
        range_layout.addWidget(self.end_date_edit)

        self.fiscal_month_combo = QComboBox()
        for month in range(1, 13):
            self.fiscal_month_combo.addItem(calendar.month_name[month], month)
        self.fiscal_month_combo.setCurrentIndex(11)
        self.date_column_summary = QLabel()
        self.date_column_summary.setWordWrap(True)
        self.date_column_summary.setStyleSheet("color: #526477;")

        self.form.addRow("Table name", self.table_name_edit)
        self.form.addRow("Range", self.range_mode_combo)
        self.form.addRow("Start and end dates", self.range_widget)
        self.form.addRow("Fiscal year ends in", self.fiscal_month_combo)
        self.form.addRow("Date columns included", self.date_column_summary)
        layout.addLayout(self.form)

        self.expression_edit = QLineEdit()
        self.expression_edit.setReadOnly(True)
        self.expression_edit.setAccessibleName("Calendar table expression")
        layout.addWidget(self.expression_edit)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.preview = QTableView()
        self.preview.setAlternatingRowColors(True)
        self.preview.horizontalHeader().setStretchLastSection(True)
        self.preview.setModel(ImportPreviewTableModel(self.preview))
        layout.addWidget(self.preview, 1)

        self.count_label = QLabel()
        self.count_label.setStyleSheet("color: #526477;")
        layout.addWidget(self.count_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        self.create_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.create_button.setText("Create table")
        self.create_button.setEnabled(False)
        self.buttons.accepted.connect(self._accept_table)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.range_mode_combo.currentIndexChanged.connect(self._refresh_preview)
        self.start_date_edit.dateChanged.connect(self._refresh_preview)
        self.end_date_edit.dateChanged.connect(self._refresh_preview)
        self.fiscal_month_combo.currentIndexChanged.connect(self._refresh_preview)
        self.table_name_edit.textChanged.connect(self._refresh_preview)
        self._refresh_preview()

    @property
    def candidate(self) -> ImportCandidate | None:
        return self._accepted_candidate if self.result() == QDialog.DialogCode.Accepted else None

    @property
    def source_ids(self) -> list[str]:
        return list(self._accepted_definition.get("source_ids", []))

    @property
    def query_definition(self) -> dict[str, Any]:
        return deepcopy(self._accepted_definition)

    @property
    def query_name(self) -> str:
        return self.table_name_edit.text().strip()

    @property
    def output_types(self) -> dict[str, str]:
        return dict(self._accepted_output_types)

    def _find_model_date_columns(self) -> list[dict[str, str]]:
        columns: list[dict[str, str]] = []
        excluded_operations = {"calculated_table", "calendar", "calendar_auto"}
        tables_by_source = {
            str(table.get("sourceId", "")): table for table in self._tables
        }

        def derives_from_generated_table(source_id: str, visiting: set[str] | None = None) -> bool:
            path = set() if visiting is None else visiting
            if source_id in path:
                return False
            next_path = path | {source_id}
            table = tables_by_source.get(source_id, {})
            operation = str(table.get("queryOperation", ""))
            if operation in excluded_operations:
                return True
            if table.get("kind") == "query":
                if operation not in {"append", "merge"}:
                    return True
                return any(
                    derives_from_generated_table(str(dependency), next_path)
                    for dependency in table.get("querySourceIds", [])
                )
            return False

        for table in self._tables:
            source_id = str(table.get("sourceId", ""))
            if (
                not source_id
                or not table.get("loaded")
                or not table.get("loadEnabled")
                or source_id not in self._candidates
            ):
                continue
            if derives_from_generated_table(source_id):
                continue
            self._auto_source_ids.append(source_id)
            types = table.get("columnTypes", {})
            calculated = {
                str(item.get("name")) for item in table.get("calculatedColumns", [])
            }
            headers = self._candidates[source_id].headers
            table_name = str(table.get("name", "Table"))
            for column in headers:
                column_type = str(types.get(column, ""))
                if column_type in {"date", "datetime"} and column not in calculated:
                    columns.append({
                        "source_id": source_id,
                        "column": str(column),
                        "type": column_type,
                        "table_name": table_name,
                    })
        return columns

    def _refresh_preview(self, *_args: Any) -> None:
        model = self.preview.model()
        assert isinstance(model, ImportPreviewTableModel)
        model.set_candidate(None)
        self._accepted_candidate = None
        self._accepted_definition = {}
        self._accepted_output_types = {}
        self.create_button.setEnabled(False)

        operation = str(self.range_mode_combo.currentData() or "calendar")
        fixed_range = operation == "calendar"
        self.range_widget.setVisible(fixed_range)
        self.form.labelForField(self.range_widget).setVisible(fixed_range)
        self.fiscal_month_combo.setVisible(not fixed_range)
        self.form.labelForField(self.fiscal_month_combo).setVisible(not fixed_range)
        self.date_column_summary.setVisible(not fixed_range)

        name = self.query_name
        if not name or "\x00" in name:
            self._show_error("Enter a valid name for the calendar table.")
            self.expression_edit.clear()
            self.count_label.setText("No calendar preview is available.")
            return

        try:
            if fixed_range:
                start_value = self.start_date_edit.date().toString("yyyy-MM-dd")
                end_value = self.end_date_edit.date().toString("yyyy-MM-dd")
                candidate = generate_calendar(start_value, end_value)
                definition = {
                    "operation": "calendar",
                    "source_ids": [],
                    "start_date": start_value,
                    "end_date": end_value,
                }
                self.date_column_summary.clear()
            else:
                if not self._date_columns:
                    raise CalendarTableError(
                        "Load at least one table with a Date or DateTime typed column for automatic range."
                    )
                date_columns = [
                    {key: column[key] for key in ("source_id", "column", "type")}
                    for column in self._date_columns
                ]
                fiscal_month = int(self.fiscal_month_combo.currentData())
                candidate = generate_calendar_auto(
                    self._candidates, date_columns, fiscal_month
                )
                definition = {
                    "operation": "calendar_auto",
                    "source_ids": list(dict.fromkeys(self._auto_source_ids)),
                    "fiscal_year_end_month": fiscal_month,
                }
                labels = [
                    f"{column['table_name']}[{column['column']}]"
                    for column in self._date_columns
                ]
                self.date_column_summary.setText(
                    f"{len(labels)} column(s): {', '.join(labels)}"
                )

            self.expression_edit.setText(calendar_expression(definition))
        except CalendarTableError as exc:
            self._show_error(str(exc))
            self.expression_edit.clear()
            self.count_label.setText("No calendar preview is available.")
            return

        model.set_candidate(candidate)
        self._accepted_candidate = candidate
        self._accepted_definition = definition
        self._accepted_output_types = {"Date": "date"}
        self.error_label.clear()
        self.error_label.setVisible(False)
        self.count_label.setText(
            f"1 column · {candidate.row_count:,} dates; previewing the first 100 rows"
        )
        self.create_button.setEnabled(True)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _accept_table(self) -> None:
        self._refresh_preview()
        if self._accepted_candidate is None:
            return
        super().accept()
