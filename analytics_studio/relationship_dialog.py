"""Create, edit, and remove local model relationships."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
)

from analytics_studio.relationships import (
    RelationshipError,
    RELATIONSHIP_VERSION,
)


class RelationshipDialog(QDialog):
    """Edit persisted table links; the caller validates them against loaded rows."""

    def __init__(
        self,
        table_catalog: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
        validate_candidate: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        parent=None,
        *,
        detect_candidates: Callable[..., list[dict[str, Any]]] | None = None,
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
        self._detect_candidates = detect_candidates
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
        self.filter_button = QToolButton()
        self.filter_button.setText("Filter")
        self.filter_button.setToolTip(
            "Filter relationships by cardinality and cross-filter direction."
        )
        self.filter_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        filter_menu = QMenu(self.filter_button)
        cardinality_menu = filter_menu.addMenu("Cardinality")
        self._cardinality_filter_actions: dict[str, QAction] = {}
        for label, value in (
            ("Many-to-one (*:1)", "many_to_one"),
            ("One-to-one (1:1)", "one_to_one"),
            ("One-to-many (1:*)", "one_to_many"),
            ("Many-to-many (*:*)", "many_to_many"),
        ):
            action = cardinality_menu.addAction(label)
            action.setCheckable(True)
            action.toggled.connect(self._apply_relationship_filters)
            self._cardinality_filter_actions[value] = action
        direction_menu = filter_menu.addMenu("Cross-filter direction")
        self._direction_filter_actions: dict[str, QAction] = {}
        for label, value in (("Single", "single"), ("Both", "both")):
            action = direction_menu.addAction(label)
            action.setCheckable(True)
            action.toggled.connect(self._apply_relationship_filters)
            self._direction_filter_actions[value] = action
        filter_menu.addSeparator()
        clear_filters_action = filter_menu.addAction("Clear filters")
        clear_filters_action.triggered.connect(self._clear_relationship_filters)
        self.filter_button.setMenu(filter_menu)
        list_header.addWidget(self.filter_button)
        self.sort_button = QToolButton()
        self._sort_field = "fromtablecolumn"
        self._sort_order = "asc"
        sort_menu = QMenu(self.sort_button)
        sort_field_menu = sort_menu.addMenu("Sort by")
        self._sort_field_group = QActionGroup(self)
        self._sort_field_group.setExclusive(True)
        self._sort_field_actions: dict[str, QAction] = {}
        for label, value in (
            ("From table/column", "fromtablecolumn"),
            ("Relationship", "relationship"),
            ("To table/column", "totablecolumn"),
            ("Active state", "active"),
        ):
            action = sort_field_menu.addAction(label)
            action.setCheckable(True)
            action.setData(value)
            self._sort_field_group.addAction(action)
            self._sort_field_actions[value] = action
        self._sort_field_actions[self._sort_field].setChecked(True)
        order_menu = sort_menu.addMenu("Order")
        self._sort_order_group = QActionGroup(self)
        self._sort_order_group.setExclusive(True)
        self._sort_order_actions: dict[str, QAction] = {}
        for label, value in (("Ascending", "asc"), ("Descending", "desc")):
            action = order_menu.addAction(label)
            action.setCheckable(True)
            action.setData(value)
            self._sort_order_group.addAction(action)
            self._sort_order_actions[value] = action
        self._sort_order_actions[self._sort_order].setChecked(True)
        self._sort_field_group.triggered.connect(self._sort_changed)
        self._sort_order_group.triggered.connect(self._sort_changed)
        self.sort_button.setMenu(sort_menu)
        self._update_sort_button()
        list_header.addWidget(self.sort_button)
        self.detect_button = QToolButton()
        self.detect_button.setText("Autodetect")
        self.detect_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.detect_button.setToolTip(
            "Suggest relationships from column names, types, and loaded values. "
            "Use the arrow to scope suggestions to selected tables."
        )
        self.detect_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.MenuButtonPopup
        )
        self.detect_button.clicked.connect(
            lambda _checked=False: self._autodetect_relationships()
        )
        detect_menu = QMenu(self.detect_button)
        choose_scope_action = detect_menu.addAction("Choose tables to connect…")
        choose_scope_action.triggered.connect(self._choose_autodetect_scope)
        self.detect_button.setMenu(detect_menu)
        list_header.addWidget(self.detect_button)
        self.new_button = QPushButton("New relationship")
        self.new_button.clicked.connect(self._start_new)
        list_header.addWidget(self.new_button)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._confirm_delete_selected)
        list_header.addWidget(self.delete_button)
        layout.addLayout(list_header)

        self.relationship_list = QListWidget()
        self.relationship_list.setMinimumHeight(125)
        self.relationship_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
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
            ("Many-to-one (*:1)", "many_to_one"),
            ("One-to-one (1:1)", "one_to_one"),
            ("One-to-many (1:*)", "one_to_many"),
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

    def _refresh_relationship_list(
        self,
        select_index: int | None = None,
        selected_indexes: set[int] | None = None,
    ) -> None:
        self._refreshing_list = True
        self.relationship_list.clear()
        relationship_indexes = sorted(
            range(len(self._relationships)),
            key=lambda index: self._relationship_sort_value(
                self._relationships[index]
            ),
            reverse=self._sort_order == "desc",
        )
        for index in relationship_indexes:
            relationship = self._relationships[index]
            item = QListWidgetItem(self._relationship_label(relationship))
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.relationship_list.addItem(item)
        self._refreshing_list = False
        self._apply_relationship_filters()
        if selected_indexes:
            for row in range(self.relationship_list.count()):
                item = self.relationship_list.item(row)
                if (
                    not item.isHidden()
                    and item.data(Qt.ItemDataRole.UserRole) in selected_indexes
                ):
                    item.setSelected(True)
        target_row = next((
            row
            for row in range(self.relationship_list.count())
            if self.relationship_list.item(row).data(Qt.ItemDataRole.UserRole)
            == select_index
            and not self.relationship_list.item(row).isHidden()
        ), None)
        if target_row is None and select_index is not None:
            target_row = next((
                row
                for row in range(self.relationship_list.count())
                if not self.relationship_list.item(row).isHidden()
            ), None)
        if target_row is not None:
            self.relationship_list.setCurrentRow(target_row)
        elif not self._relationships or not any(
            not self.relationship_list.item(row).isHidden()
            for row in range(self.relationship_list.count())
        ):
            self.relationship_list.setCurrentRow(-1)
            self._start_new(clear_selection=False)

    def _relationship_sort_value(self, relationship: dict[str, Any]) -> str:
        field = self._sort_field
        if field == "fromtablecolumn":
            return str(relationship.get("from_column") or "").lower()
        if field == "relationship":
            cardinality = {
                "one_to_one": "OneToOne",
                "many_to_one": "ManyToOne",
                "one_to_many": "OneToMany",
                "many_to_many": "ManyToMany",
            }.get(str(relationship.get("cardinality", "")), "")
            direction = {
                "single": "OneDirection",
                "both": "BothDirections",
            }.get(str(relationship.get("cross_filter_direction", "")), "")
            return cardinality + direction
        if field == "totablecolumn":
            return str(relationship.get("to_column") or "").lower()
        if field == "active":
            if "is_active" not in relationship:
                return ""
            return str(bool(relationship.get("is_active"))).lower()
        return ""

    def _update_sort_button(self) -> None:
        label = self._sort_field_actions[self._sort_field].text()
        direction = "ascending" if self._sort_order == "asc" else "descending"
        arrow = "↑" if self._sort_order == "asc" else "↓"
        self.sort_button.setText(f"Sort {arrow}")
        self.sort_button.setToolTip(f"Sort by {label}, {direction}.")

    def _sort_changed(self, *_args: Any) -> None:
        field_action = self._sort_field_group.checkedAction()
        order_action = self._sort_order_group.checkedAction()
        if field_action is not None:
            self._sort_field = str(field_action.data())
        if order_action is not None:
            self._sort_order = str(order_action.data())
        current_index = self._relationship_index_at(
            self.relationship_list.currentRow()
        )
        selected_indexes = set(self._selected_relationship_indexes())
        self._update_sort_button()
        self._refresh_relationship_list(
            select_index=current_index,
            selected_indexes=selected_indexes,
        )

    def _relationship_index_at(self, row: int) -> int | None:
        item = self.relationship_list.item(row)
        if item is None:
            return None
        index = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(index, int) and 0 <= index < len(self._relationships):
            return index
        return None

    def _selected_relationship_indexes(self) -> list[int]:
        indexes = set()
        for item in self.relationship_list.selectedItems():
            index = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(index, int) and 0 <= index < len(self._relationships):
                indexes.add(index)
        return sorted(indexes)

    def _apply_relationship_filters(self, *_args: Any) -> None:
        cardinalities = {
            value
            for value, action in self._cardinality_filter_actions.items()
            if action.isChecked()
        }
        directions = {
            value
            for value, action in self._direction_filter_actions.items()
            if action.isChecked()
        }
        visible_rows = []
        for row in range(self.relationship_list.count()):
            item = self.relationship_list.item(row)
            relationship_index = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(relationship_index, int):
                continue
            relationship = self._relationships[relationship_index]
            matches_cardinality = (
                not cardinalities or relationship.get("cardinality") in cardinalities
            )
            matches_direction = (
                not directions
                or relationship.get("cross_filter_direction") in directions
            )
            hidden = not (matches_cardinality and matches_direction)
            item.setHidden(hidden)
            if hidden:
                item.setSelected(False)
            else:
                visible_rows.append(row)
        active_filter_count = bool(cardinalities) + bool(directions)
        self.filter_button.setText(
            f"Filter ({active_filter_count})" if active_filter_count else "Filter"
        )
        current_row = self.relationship_list.currentRow()
        if (
            current_row >= 0
            and self.relationship_list.item(current_row).isHidden()
        ):
            self.relationship_list.setCurrentRow(
                visible_rows[0] if visible_rows else -1
            )
        if not visible_rows:
            self.delete_button.setEnabled(False)

    def _clear_relationship_filters(self, *_args: Any) -> None:
        for action in (
            *self._cardinality_filter_actions.values(),
            *self._direction_filter_actions.values(),
        ):
            action.setChecked(False)
        self._apply_relationship_filters()

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
        relationship_index = self._relationship_index_at(row)
        if relationship_index is None:
            self.delete_button.setEnabled(False)
            self._start_new(clear_selection=False)
            return
        self.delete_button.setEnabled(True)
        relationship = self._relationships[relationship_index]
        if relationship.get("relationship_version") != RELATIONSHIP_VERSION:
            self._editing_index = relationship_index
            self.legacy_note.setText(
                "This project contains older display-only relationship metadata. "
                "It cannot be converted automatically; delete it and create a new relationship."
            )
            self.legacy_note.show()
            self._set_editable(False)
            return
        self.legacy_note.hide()
        self._editing_index = relationship_index
        self._set_table_selection(self.from_table, relationship.get("from_table_id"))
        self._set_table_selection(self.to_table, relationship.get("to_table_id"))
        self._populate_columns(self.from_table, self.from_column, relationship.get("from_column"))
        self._populate_columns(self.to_table, self.to_column, relationship.get("to_column"))
        self._set_combo_data(self.cardinality, relationship.get("cardinality"))
        self._set_combo_data(self.cross_filter, relationship.get("cross_filter_direction"))
        self.active_check.setChecked(bool(relationship.get("is_active", True)))
        self.apply_button.setText("Update relationship")
        self._set_editable(len(self._tables) > 1)

    def _choose_autodetect_scope(self) -> None:
        if self._detect_candidates is None or len(self._tables) < 2:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Choose tables to connect")
        dialog.setMinimumWidth(380)
        layout = QVBoxLayout(dialog)
        note = QLabel(
            "Select at least two tables. Suggestions may connect through other tables."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        table_list = QListWidget(dialog)
        for table in self._tables:
            table_id = str(table["id"])
            display_name = str(table.get("displayName") or table.get("name") or table_id)
            item = QListWidgetItem(display_name, table_list)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, table_id)
        layout.addWidget(table_list)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            dialog,
        )
        accept_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        accept_button.setEnabled(False)

        def update_accept_state(*_args: Any) -> None:
            selected_count = sum(
                table_list.item(row).checkState() == Qt.CheckState.Checked
                for row in range(table_list.count())
            )
            accept_button.setEnabled(selected_count >= 2)

        table_list.itemChanged.connect(update_accept_state)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        target_tables = {
            str(table_list.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(table_list.count())
            if table_list.item(row).checkState() == Qt.CheckState.Checked
        }
        if len(target_tables) >= 2:
            self._autodetect_relationships(target_tables)

    def _autodetect_relationships(
        self, tables_to_be_connected: set[str] | None = None
    ) -> None:
        if self._detect_candidates is None:
            return
        try:
            relationship_snapshot = deepcopy(self._relationships)
            if tables_to_be_connected is None:
                suggestions = self._detect_candidates(relationship_snapshot)
            else:
                suggestions = self._detect_candidates(
                    relationship_snapshot, tables_to_be_connected
                )
        except RelationshipError as exc:
            self.status_label.setText(f"Could not detect relationships: {exc}")
            return
        if not suggestions:
            message = (
                "No additional relationships were detected for the selected tables."
                if tables_to_be_connected is not None
                else "No additional relationships were detected."
            )
            QMessageBox.information(
                self,
                "Autodetect",
                message,
            )
            self.status_label.setText(message)
            return
        if tables_to_be_connected is not None:
            result_message = (
                f"Detected {len(suggestions):,} proposed relationship(s) "
                f"to connect {len(tables_to_be_connected):,} selected tables. "
                "Review them, then select Save to keep them."
            )
        else:
            result_message = (
                f"Detected {len(suggestions):,} proposed relationship(s). "
                "Review them, then select Save to keep them."
            )
        QMessageBox.information(
            self,
            "Autodetect",
            result_message,
        )
        self._relationships.extend(deepcopy(suggestions))
        self._refresh_relationship_list(len(self._relationships) - 1)
        self.status_label.setText(result_message)

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

    def _confirm_delete_selected(self) -> None:
        indexes = self._selected_relationship_indexes()
        if not indexes:
            index = self._relationship_index_at(self.relationship_list.currentRow())
            if index is not None:
                indexes = [index]
        if not indexes:
            return
        is_multiple = len(indexes) > 1
        subject = (
            f"Remove {len(indexes):,} selected relationships from the pending changes?"
            if is_multiple
            else "Remove this relationship from the pending changes?"
        )
        if not is_multiple:
            label = self._relationship_label(self._relationships[indexes[0]])
            subject += f"\n\n{label}"
        result = QMessageBox.question(
            self,
            "Delete relationships" if is_multiple else "Delete relationship",
            subject + "\n\nThe project changes when you select Save.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result == QMessageBox.StandardButton.Yes:
            self._delete_selected()

    def _delete_selected(self) -> None:
        indexes = self._selected_relationship_indexes()
        if not indexes:
            index = self._relationship_index_at(self.relationship_list.currentRow())
            if index is not None:
                indexes = [index]
        if not indexes:
            return
        first_index = min(indexes)
        for index in reversed(indexes):
            self._relationships.pop(index)
        next_index = min(first_index, len(self._relationships) - 1)
        self._refresh_relationship_list(next_index if next_index >= 0 else None)
        if next_index < 0:
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
        self.detect_button.setEnabled(
            enabled and self._detect_candidates is not None
        )
        self.new_button.setEnabled(len(self._tables) > 1)

    def _save(self) -> None:
        try:
            self._relationships = self._validate_candidate(self._relationships)
        except RelationshipError as exc:
            QMessageBox.warning(self, "Relationship validation", str(exc))
            return
        self.accept()
