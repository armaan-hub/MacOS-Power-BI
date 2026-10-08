"""Editor for local row-scoped DAX calculated columns."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from analytics_studio.measures import MeasureError, normalize_calculated_column


class CalculatedColumnDialog(QDialog):
    """Create, edit, or remove one calculated column on the active table."""

    def __init__(
        self,
        definitions: list[dict[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._definitions = [dict(item) for item in definitions]
        self._accepted_column: dict[str, str] | None = None
        self._action = "save"
        self._original_name = ""
        self.setWindowTitle("Calculated column")
        self.setMinimumWidth(540)
        self.resize(620, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        title = QLabel("Create or edit a calculated column")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #273b49;")
        layout.addWidget(title)

        form = QFormLayout()
        self.saved_combo = QComboBox()
        self.saved_combo.addItem("New calculated column", "")
        for definition in self._definitions:
            self.saved_combo.addItem(definition["name"], definition["name"])
        form.addRow("Column", self.saved_combo)

        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(120)
        form.addRow("Column name", self.name_edit)
        self.expression_edit = QPlainTextEdit()
        self.expression_edit.setPlaceholderText("[Quantity] * [Unit price]")
        self.expression_edit.setMaximumHeight(130)
        form.addRow("DAX expression", self.expression_edit)
        layout.addLayout(form)

        help_label = QLabel(
            "Supported row expressions: numeric/boolean columns and TRUE()/FALSE() literals, arithmetic, comparisons, "
            "IF, AND, OR, NOT, ABS, and ROUND. Columns must come from this table. "
            "Calculated columns recompute when the source refreshes or the project opens."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #526477;")
        layout.addWidget(help_label)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        self.save_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.save_button.setText("Save column")
        self.delete_button = self.buttons.addButton(
            "Delete column", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.delete_button.setEnabled(False)
        self.buttons.accepted.connect(self._accept_column)
        self.buttons.rejected.connect(self.reject)
        self.delete_button.clicked.connect(self._delete_column)
        layout.addWidget(self.buttons)

        self.saved_combo.currentIndexChanged.connect(self._load_selected)
        self.name_edit.textChanged.connect(self._refresh_error)
        self.expression_edit.textChanged.connect(self._refresh_error)
        self._load_selected()

    @property
    def action(self) -> str:
        return self._action

    @property
    def original_name(self) -> str:
        return self._original_name

    @property
    def column(self) -> dict[str, str] | None:
        return dict(self._accepted_column) if self._accepted_column else None

    def _load_selected(self, *_args: object) -> None:
        selected_name = str(self.saved_combo.currentData() or "")
        definition = next(
            (item for item in self._definitions if item["name"] == selected_name), None
        )
        self._original_name = selected_name
        self.name_edit.setText(definition["name"] if definition else "")
        self.expression_edit.setPlainText(definition["expression"] if definition else "")
        self.delete_button.setEnabled(definition is not None)
        self._refresh_error()

    def _current_column(self) -> dict[str, str]:
        column = normalize_calculated_column(
            self.name_edit.text(), self.expression_edit.toPlainText()
        )
        duplicate = next((
            item["name"] for item in self._definitions
            if item["name"].casefold() == column["name"].casefold()
            and item["name"].casefold() != self._original_name.casefold()
        ), None)
        if duplicate:
            raise MeasureError(f"A calculated column named {duplicate!r} already exists.")
        return column

    def _refresh_error(self, *_args: object) -> None:
        try:
            self._current_column()
        except MeasureError as exc:
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)
            self.save_button.setEnabled(False)
            return
        self.error_label.clear()
        self.error_label.setVisible(False)
        self.save_button.setEnabled(True)

    def _accept_column(self) -> None:
        try:
            self._accepted_column = self._current_column()
        except MeasureError as exc:
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)
            return
        self._action = "save"
        super().accept()

    def _delete_column(self) -> None:
        if not self._original_name:
            return
        self._action = "delete"
        self._accepted_column = None
        super().accept()

    def reject(self) -> None:
        self._accepted_column = None
        super().reject()
