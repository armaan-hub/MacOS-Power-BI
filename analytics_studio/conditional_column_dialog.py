"""Power BI style Add Conditional Column dialog.

The dialog only collects input. It produces the same ``conditional_column`` step the
transformation engine already replays, so there is a single implementation of the
behaviour (``analytics_studio.transformations``).
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from analytics_studio.dialog_theme import apply_light_dialog_theme
from analytics_studio.transformations import MAX_CONDITIONAL_CLAUSES

CONDITIONAL_OPERATORS: tuple[tuple[str, str], ...] = (
    ("equals", "equals"),
    ("does not equal", "not_equals"),
    ("begins with", "begins_with"),
    ("does not begin with", "does_not_begin_with"),
    ("ends with", "ends_with"),
    ("does not end with", "does_not_end_with"),
    ("contains", "contains"),
    ("does not contain", "does_not_contain"),
    ("is greater than", "greater_than"),
    ("is greater than or equal to", "greater_than_or_equal"),
    ("is less than", "less_than"),
    ("is less than or equal to", "less_than_or_equal"),
)


class ValueOrColumnField(QWidget):
    """A typed value or a column reference, chosen with the small ABC / column picker."""

    changed = Signal()

    def __init__(
        self,
        headers: list[str],
        placeholder: str,
        *,
        object_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.kind_combo = QComboBox(self)
        self.kind_combo.setObjectName(f"{object_name}Kind")
        self.kind_combo.addItem("ABC", "value")
        self.kind_combo.addItem("Column", "column")
        self.kind_combo.setItemData(0, "Enter a value", Qt.ItemDataRole.ToolTipRole)
        self.kind_combo.setItemData(1, "Select a column", Qt.ItemDataRole.ToolTipRole)
        self.kind_combo.setToolTip("Choose whether to type a value or select a column")
        self.kind_combo.setAccessibleName("Value type")
        self.kind_combo.setFixedWidth(82)
        self.stack = QStackedWidget(self)
        self.edit = QLineEdit(self)
        self.edit.setObjectName(f"{object_name}Value")
        self.edit.setPlaceholderText(placeholder)
        self.edit.setAccessibleName(placeholder)
        self.column_combo = QComboBox(self)
        self.column_combo.setObjectName(f"{object_name}Column")
        self.column_combo.addItems(headers)
        self.column_combo.setAccessibleName(f"{placeholder} column")
        self.stack.addWidget(self.edit)
        self.stack.addWidget(self.column_combo)
        layout.addWidget(self.kind_combo)
        layout.addWidget(self.stack, 1)
        self.kind_combo.currentIndexChanged.connect(self._kind_changed)
        self.edit.textChanged.connect(lambda *_: self.changed.emit())
        self.column_combo.currentIndexChanged.connect(lambda *_: self.changed.emit())

    def _kind_changed(self, *_args: Any) -> None:
        self.stack.setCurrentIndex(0 if self.kind_combo.currentData() == "value" else 1)
        self.changed.emit()

    def set_value(self, kind: str, value: str) -> None:
        index = self.kind_combo.findData(kind)
        self.kind_combo.setCurrentIndex(max(0, index))
        if kind == "column":
            column_index = self.column_combo.findText(value)
            if column_index >= 0:
                self.column_combo.setCurrentIndex(column_index)
        else:
            self.edit.setText(value)

    def value(self) -> tuple[str, str]:
        if self.kind_combo.currentData() == "column":
            return "column", self.column_combo.currentText()
        return "value", self.edit.text()


class ConditionalClauseRow(QWidget):
    """One ``If`` / ``Else If`` row: column, operator, value, then output."""

    removeRequested = Signal(object)
    changed = Signal()

    def __init__(
        self,
        headers: list[str],
        *,
        first: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("conditionalClauseRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)
        self.prefix_label = QLabel("If" if first else "Else If", self)
        self.prefix_label.setMinimumWidth(48)
        self.column_combo = QComboBox(self)
        self.column_combo.setObjectName("conditionalClauseColumn")
        self.column_combo.addItems(headers)
        self.column_combo.setAccessibleName("Column name")
        self.column_combo.setMinimumWidth(120)
        self.operator_combo = QComboBox(self)
        self.operator_combo.setObjectName("conditionalClauseOperator")
        for label, value in CONDITIONAL_OPERATORS:
            self.operator_combo.addItem(label, value)
        self.operator_combo.setAccessibleName("Operator")
        self.test_value = ValueOrColumnField(
            headers, "Value", object_name="conditionalClauseTest", parent=self
        )
        self.then_label = QLabel("Then", self)
        self.output = ValueOrColumnField(
            headers, "Output", object_name="conditionalClauseOutput", parent=self
        )
        self.remove_button = QPushButton("✕", self)
        self.remove_button.setObjectName("removeConditionalClauseRow")
        self.remove_button.setToolTip("Remove this clause")
        self.remove_button.setAccessibleName("Remove clause")
        self.remove_button.setFixedWidth(28)
        self.remove_button.setVisible(not first)
        layout.addWidget(self.prefix_label)
        layout.addWidget(self.column_combo, 3)
        layout.addWidget(self.operator_combo, 3)
        layout.addWidget(self.test_value, 3)
        layout.addWidget(self.then_label)
        layout.addWidget(self.output, 3)
        layout.addWidget(self.remove_button)
        self.remove_button.clicked.connect(lambda: self.removeRequested.emit(self))
        self.column_combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self.test_value.changed.connect(self.changed)
        self.output.changed.connect(self.changed)

    def set_first(self, first: bool) -> None:
        self.prefix_label.setText("If" if first else "Else If")
        self.remove_button.setVisible(not first)

    def clause(self) -> dict[str, str]:
        test_kind, test_value = self.test_value.value()
        output_kind, output = self.output.value()
        return {
            "column": self.column_combo.currentText(),
            "operator": str(self.operator_combo.currentData()),
            "test_value": test_value,
            "test_value_kind": test_kind,
            "output": output,
            "output_kind": output_kind,
        }

    def load(self, clause: dict[str, str]) -> None:
        index = self.column_combo.findText(clause["column"])
        if index >= 0:
            self.column_combo.setCurrentIndex(index)
        index = self.operator_combo.findData(clause["operator"])
        if index >= 0:
            self.operator_combo.setCurrentIndex(index)
        self.test_value.set_value(clause["test_value_kind"], clause["test_value"])
        self.output.set_value(clause["output_kind"], clause["output"])


class ConditionalColumnDialog(QDialog):
    """Add Conditional Column: new name, If / Else If clauses, and a final Else."""

    def __init__(
        self,
        headers: list[str],
        *,
        initial_step: dict[str, Any] | None = None,
        default_column: str | None = None,
        validate_callback: Callable[[dict[str, Any]], str | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        apply_light_dialog_theme(self)
        self.setObjectName("powerQueryConditionalColumnDialog")
        self.setWindowTitle("Add Conditional Column")
        self.setMinimumWidth(820)
        self._headers = list(headers)
        self._default_column = default_column if default_column in headers else None
        self._validate_callback = validate_callback
        self.clause_rows: list[ConditionalClauseRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        heading = QLabel(
            "Add a conditional column that is computed from the other columns or values."
        )
        heading.setWordWrap(True)
        layout.addWidget(heading)

        name_row = QHBoxLayout()
        name_label = QLabel("New column name")
        self.name_edit = QLineEdit(self)
        self.name_edit.setObjectName("conditionalColumnNameEdit")
        self.name_edit.setAccessibleName("New column name")
        self.name_edit.setText("Custom")
        name_row.addWidget(name_label)
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)

        self.rows_container = QWidget(self)
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(2)
        self.rows_layout.addStretch(1)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumHeight(110)
        scroll.setWidget(self.rows_container)
        layout.addWidget(scroll, 1)

        self.add_clause_button = QPushButton("Add Clause", self)
        self.add_clause_button.setObjectName("addConditionalClauseButton")
        add_row = QHBoxLayout()
        add_row.addWidget(self.add_clause_button)
        add_row.addStretch(1)
        layout.addLayout(add_row)

        else_row = QHBoxLayout()
        else_row.setSpacing(6)
        else_label = QLabel("Else")
        else_label.setMinimumWidth(48)
        self.else_output = ValueOrColumnField(
            headers, "Output", object_name="conditionalElse", parent=self
        )
        else_row.addWidget(else_label)
        else_row.addWidget(self.else_output, 1)
        layout.addLayout(else_row)

        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.cancel_button = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.ok_button.setObjectName("conditionalColumnOkButton")
        self.cancel_button.setObjectName("conditionalColumnCancelButton")
        layout.addWidget(self.buttons)
        self.buttons.accepted.connect(self._accept_step)
        self.buttons.rejected.connect(self.reject)
        self.add_clause_button.clicked.connect(lambda: self.add_clause())
        self.name_edit.textChanged.connect(self._refresh_state)

        if initial_step is not None:
            self.name_edit.setText(str(initial_step.get("name", "")))
            for clause in initial_step.get("clauses", []):
                self.add_clause(clause)
            self.else_output.set_value(
                str(initial_step.get("else_kind", "value")),
                str(initial_step.get("else_value", "")),
            )
        if not self.clause_rows:
            self.add_clause()
        self._refresh_state()

    def add_clause(self, clause: dict[str, str] | None = None) -> ConditionalClauseRow | None:
        if len(self.clause_rows) >= MAX_CONDITIONAL_CLAUSES:
            return None
        row = ConditionalClauseRow(
            self._headers, first=not self.clause_rows, parent=self.rows_container
        )
        if clause is not None:
            row.load(clause)
        elif self._default_column is not None:
            row.column_combo.setCurrentText(self._default_column)
        row.removeRequested.connect(self._remove_clause)
        row.changed.connect(self._refresh_state)
        self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)
        self.clause_rows.append(row)
        self._refresh_state()
        return row

    def _remove_clause(self, row: ConditionalClauseRow) -> None:
        if row not in self.clause_rows or len(self.clause_rows) == 1:
            return
        self.clause_rows.remove(row)
        self.rows_layout.removeWidget(row)
        row.hide()
        row.deleteLater()
        for index, remaining in enumerate(self.clause_rows):
            remaining.set_first(index == 0)
        self._refresh_state()

    def _refresh_state(self, *_args: Any) -> None:
        self.add_clause_button.setEnabled(len(self.clause_rows) < MAX_CONDITIONAL_CLAUSES)
        self.ok_button.setEnabled(
            bool(self.name_edit.text().strip())
            and bool(self.clause_rows)
            and all(row.column_combo.currentText() for row in self.clause_rows)
        )

    def step(self) -> dict[str, Any]:
        else_kind, else_value = self.else_output.value()
        return {
            "op": "conditional_column",
            "name": self.name_edit.text().strip(),
            "clauses": [row.clause() for row in self.clause_rows],
            "else_value": else_value,
            "else_kind": else_kind,
        }

    def _accept_step(self) -> None:
        step = self.step()
        if self._validate_callback is not None:
            error = self._validate_callback(step)
            if error:
                self.error_label.setText(error)
                self.error_label.setVisible(True)
                return
        super().accept()
