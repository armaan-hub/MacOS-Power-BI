"""Create, edit, and remove local model relationships."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from analytics_studio.relationships import RelationshipError, RELATIONSHIP_VERSION


class RelationshipDialog(QDialog):
    """Edit persisted table links; the caller validates them against loaded rows."""

    def __init__(
        self,
        table_catalog: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
        validate_candidate: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage relationships")
        self.setMinimumSize(760, 590)
        self.resize(860, 680)
        self._tables = [
            dict(table) for table in table_catalog
            if table.get("loaded") and table.get("loadEnabled") and table.get("headers")
        ]
        self._table_by_id = {str(table["id"]): table for table in self._tables}
        self._relationships = deepcopy(relationships)
        self._validate_candidate = validate_candidate
        self._editing_index: int | None = None
        self._refreshing_list = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        heading = QLabel("Manage model relationships")
        heading.setStyleSheet("font-size: 19px; font-weight: 600; color: #273b49;")
        layout.addWidget(heading)
        note = QLabel(
            "Connect columns from two loaded tables. One-side keys must be unique. "
            "Active relationships can filter qualified measures; built-in charts and general "
            "visual filters still use the active table."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #526477;")
        layout.addWidget(note)

        list_header = QHBoxLayout()
        list_header.addWidget(QLabel("Relationships"), 1)
        self.new_button = QPushButton("New relationship")
        self.new_button.clicked.connect(self._start_new)
        list_header.addWidget(self.new_button)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._delete_selected)
        list_header.addWidget(self.delete_button)
        layout.addLayout(list_header)

        self.relationship_list = QListWidget()
        self.relationship_list.setMinimumHeight(125)
        self.relationship_list.currentRowChanged.connect(self._select_relationship)
        layout.addWidget(self.relationship_list)

        self.legacy_note = QLabel()
        self.legacy_note.setWordWrap(True)
        self.legacy_note.setStyleSheet("color: #8a5b00;")
        self.legacy_note.hide()
        layout.addWidget(self.legacy_note)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(9)
        self.from_table = QComboBox()
        self.to_table = QComboBox()
        for table in self._tables:
            table_id = str(table["id"])
            display_name = str(table.get("displayName") or table.get("name") or table_id)
            self.from_table.addItem(display_name, table_id)
            self.to_table.addItem(display_name, table_id)
        self.from_column = QComboBox()
        self.to_column = QComboBox()
        self.cardinality = QComboBox()
        for label, value in (
            ("One-to-many (1:*)", "one_to_many"),
            ("Many-to-one (*:1)", "many_to_one"),
            ("One-to-one (1:1)", "one_to_one"),
            ("Many-to-many (*:*)", "many_to_many"),
        ):
            self.cardinality.addItem(label, value)
        self.cross_filter = QComboBox()
        self.cross_filter.addItem("Single", "single")
        self.cross_filter.addItem("Both", "both")
        self.active_check = QCheckBox("Make this relationship active")
        form.addRow("From table", self.from_table)
        form.addRow("From column", self.from_column)
        form.addRow("To table", self.to_table)
        form.addRow("To column", self.to_column)
        form.addRow("Cardinality", self.cardinality)
        form.addRow("Cross-filter direction", self.cross_filter)
        form.addRow("", self.active_check)
        layout.addLayout(form)

        self.apply_button = QPushButton("Add relationship")
        self.apply_button.clicked.connect(self._apply_form)
        layout.addWidget(self.apply_button, 0, Qt.AlignmentFlag.AlignRight)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #526477;")
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.from_table.currentIndexChanged.connect(
            lambda *_args: self._populate_columns(self.from_table, self.from_column)
        )
        self.to_table.currentIndexChanged.connect(
            lambda *_args: self._populate_columns(self.to_table, self.to_column)
        )
        self._populate_columns(self.from_table, self.from_column)
        self._populate_columns(self.to_table, self.to_column)
        self._refresh_relationship_list()
        self._set_editable(bool(self._tables) and len(self._tables) > 1)
        if self._relationships:
            self.relationship_list.setCurrentRow(0)
        else:
            self._start_new()

    @property
    def relationships(self) -> list[dict[str, Any]]:
        return deepcopy(self._relationships) if self.result() == QDialog.DialogCode.Accepted else []

    def _refresh_relationship_list(self, select_index: int | None = None) -> None:
        self._refreshing_list = True
        self.relationship_list.clear()
        for index, relationship in enumerate(self._relationships):
            item = QListWidgetItem(self._relationship_label(relationship))
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.relationship_list.addItem(item)
        self._refreshing_list = False
        if select_index is not None and 0 <= select_index < len(self._relationships):
            self.relationship_list.setCurrentRow(select_index)
        elif not self._relationships:
            self.relationship_list.setCurrentRow(-1)

    def _relationship_label(self, relationship: dict[str, Any]) -> str:
        if relationship.get("relationship_version") != RELATIONSHIP_VERSION:
            return f"{relationship.get('from', '?')} → {relationship.get('to', '?')} · legacy metadata"
        from_name = self._table_name(str(relationship.get("from_table_id", "")))
        to_name = self._table_name(str(relationship.get("to_table_id", "")))
        state = "active" if relationship.get("is_active") else "inactive"
        cardinality = str(relationship.get("cardinality", "")).replace("_", "-")
        return (
            f"{from_name}[{relationship.get('from_column', '?')}] → "
            f"{to_name}[{relationship.get('to_column', '?')}] · {cardinality} · "
            f"{relationship.get('cross_filter_direction', 'single')} · {state}"
        )

    def _table_name(self, table_id: str) -> str:
        table = self._table_by_id.get(table_id)
        if table is None:
            return f"Missing table ({table_id})"
        return str(table.get("name", table.get("displayName", table_id)))

    def _select_relationship(self, row: int) -> None:
        if self._refreshing_list:
            return
        if row < 0 or row >= len(self._relationships):
            self.delete_button.setEnabled(False)
            self._start_new(clear_selection=False)
            return
        self.delete_button.setEnabled(True)
        relationship = self._relationships[row]
        if relationship.get("relationship_version") != RELATIONSHIP_VERSION:
            self._editing_index = row
            self.legacy_note.setText(
                "This project contains older display-only relationship metadata. "
                "It cannot be converted automatically; delete it and create a new relationship."
            )
            self.legacy_note.show()
            self._set_editable(False)
            return
        self.legacy_note.hide()
        self._editing_index = row
        self._set_table_selection(self.from_table, relationship.get("from_table_id"))
        self._set_table_selection(self.to_table, relationship.get("to_table_id"))
        self._populate_columns(self.from_table, self.from_column, relationship.get("from_column"))
        self._populate_columns(self.to_table, self.to_column, relationship.get("to_column"))
        self._set_combo_data(self.cardinality, relationship.get("cardinality"))
        self._set_combo_data(self.cross_filter, relationship.get("cross_filter_direction"))
        self.active_check.setChecked(bool(relationship.get("is_active", True)))
        self.apply_button.setText("Update relationship")
        self._set_editable(len(self._tables) > 1)

    def _start_new(self, *, clear_selection: bool = True) -> None:
        self._editing_index = None
        if clear_selection:
            self.relationship_list.clearSelection()
        self.legacy_note.hide()
        self._set_editable(len(self._tables) > 1)
        self.apply_button.setText("Add relationship")
        self.cardinality.setCurrentIndex(max(0, self.cardinality.findData("many_to_one")))
        self.cross_filter.setCurrentIndex(max(0, self.cross_filter.findData("single")))
        self.active_check.setChecked(True)
        if len(self._tables) > 1:
            self.from_table.setCurrentIndex(0)
            self.to_table.setCurrentIndex(1)
            self._populate_columns(self.from_table, self.from_column, "")
            self._populate_columns(self.to_table, self.to_column, "")
        else:
            self._populate_columns(self.from_table, self.from_column)
            self._populate_columns(self.to_table, self.to_column)
        self.status_label.setText(
            "Load two tables to create a relationship."
            if len(self._tables) < 2 else "Choose related columns, cardinality, and filter direction."
        )

    def _delete_selected(self) -> None:
        row = self.relationship_list.currentRow()
        if 0 <= row < len(self._relationships):
            self._relationships.pop(row)
            next_row = min(row, len(self._relationships) - 1)
            self._refresh_relationship_list(next_row if next_row >= 0 else None)
            if next_row < 0:
                self._start_new()

    def _apply_form(self) -> None:
        from_table_id = self.from_table.currentData()
        to_table_id = self.to_table.currentData()
        from_column = self.from_column.currentData()
        to_column = self.to_column.currentData()
        if not all((from_table_id, to_table_id, from_column, to_column)):
            QMessageBox.warning(self, "Relationship incomplete", "Choose a table and column at both ends.")
            return
        if from_table_id == to_table_id:
            QMessageBox.warning(self, "Relationship invalid", "Choose two different tables.")
            return
        existing_id = (
            self._relationships[self._editing_index].get("id")
            if self._editing_index is not None
            else str(uuid4())
        )
        relationship = {
            "relationship_version": RELATIONSHIP_VERSION,
            "id": str(existing_id or uuid4()),
            "from": self._endpoint_label(str(from_table_id), str(from_column)),
            "to": self._endpoint_label(str(to_table_id), str(to_column)),
            "from_table_id": str(from_table_id),
            "from_column": str(from_column),
            "to_table_id": str(to_table_id),
            "to_column": str(to_column),
            "cardinality": str(self.cardinality.currentData()),
            "cross_filter_direction": str(self.cross_filter.currentData()),
            "is_active": self.active_check.isChecked(),
        }
        if self._editing_index is None:
            self._relationships.append(relationship)
            selected = len(self._relationships) - 1
        else:
            self._relationships[self._editing_index] = relationship
            selected = self._editing_index
        self._refresh_relationship_list(selected)
        self.status_label.setText("Relationship saved in this dialog. Select Save to store it in the project.")

    def _endpoint_label(self, table_id: str, column: str) -> str:
        return f"{self._table_name(table_id)}[{column}]"

    def _set_table_selection(self, combo: QComboBox, table_id: Any) -> None:
        index = combo.findData(table_id)
        if index < 0 and table_id:
            combo.addItem(f"Missing table ({table_id})", str(table_id))
            index = combo.count() - 1
        if index >= 0:
            combo.setCurrentIndex(index)

    def _populate_columns(
        self,
        table_combo: QComboBox,
        column_combo: QComboBox,
        selected_column: Any = None,
    ) -> None:
        if selected_column is None:
            selected_column = column_combo.currentData()
        table = self._table_by_id.get(str(table_combo.currentData()))
        columns = [str(value) for value in table.get("headers", [])] if table else []
        column_combo.blockSignals(True)
        column_combo.clear()
        for column in columns:
            column_combo.addItem(column, column)
        if selected_column and column_combo.findData(selected_column) < 0:
            column_combo.addItem(f"{selected_column} (missing)", str(selected_column))
        self._set_combo_data(column_combo, selected_column)
        column_combo.blockSignals(False)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: Any) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _set_editable(self, enabled: bool) -> None:
        for widget in (
            self.from_table,
            self.from_column,
            self.to_table,
            self.to_column,
            self.cardinality,
            self.cross_filter,
            self.active_check,
            self.apply_button,
        ):
            widget.setEnabled(enabled)
        self.new_button.setEnabled(len(self._tables) > 1)

    def _save(self) -> None:
        try:
            self._relationships = self._validate_candidate(self._relationships)
        except RelationshipError as exc:
            QMessageBox.warning(self, "Relationship validation", str(exc))
            return
        self.accept()
