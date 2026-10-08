"""Small native dialogs for entering local table data and previewing transforms."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QIntValidator, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QTableView,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from analytics_studio.file_import import MAX_DATA_ROWS, ImportCandidate
from analytics_studio.import_preview_dialog import ImportPreviewTableModel
from analytics_studio.inline_data import parse_pasted_table
from analytics_studio.measures import (
    MeasureError,
    evaluate_calculated_table,
    normalize_calculated_table_expression,
)
from analytics_studio.query_engine import (
    QueryError,
    append_candidates,
    merge_candidates,
)
from analytics_studio.transformations import (
    FILTER_OPERATORS_WITHOUT_VALUE,
    MAX_CONDITIONAL_CLAUSES,
    MAX_FILTER_CLAUSES,
    MAX_MERGE_SEPARATOR_CHARS,
    TransformationError,
    apply_transformations,
    validate_steps,
)


class EnterDataDialog(QDialog):
    """Create one table from typed CSV or tab-separated clipboard contents."""

    def __init__(
        self,
        *,
        replacing: bool,
        initial_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.replacing = replacing
        self._accepted_candidate: ImportCandidate | None = None
        self._preview_candidate: ImportCandidate | None = None
        self.setWindowTitle("Enter data")
        self.setMinimumSize(620, 440)
        self.resize(820, 590)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(9)

        title = QLabel("Create a table from pasted or typed data")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #273b49;")
        layout.addWidget(title)

        self.replacement_label = QLabel(
            "Creating this table will replace the data source currently loaded in this report."
        )
        self.replacement_label.setWordWrap(True)
        self.replacement_label.setStyleSheet(
            "padding: 7px 9px; color: #6a4d00; background: #fff5d6;"
            "border: 1px solid #e8d391; border-radius: 3px;"
        )
        self.replacement_label.setVisible(replacing)
        layout.addWidget(self.replacement_label)

        name_form = QFormLayout()
        self.name_edit = QLineEdit("Entered data")
        self.name_edit.setMaxLength(120)
        name_form.addRow("Table name", self.name_edit)
        layout.addLayout(name_form)

        help_text = QLabel("Use the first row for column names. Paste cells from Excel or enter comma/tab-separated text.")
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #526477;")
        layout.addWidget(help_text)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("Product\tRegion\tRevenue\nCamera\tWest\t240")
        self.text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text_edit.setPlainText(initial_text)
        layout.addWidget(self.text_edit, 1)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.preview = QTableView()
        self.preview.setMinimumHeight(120)
        self.preview.setMaximumHeight(190)
        self.preview.setAlternatingRowColors(True)
        self.preview.horizontalHeader().setStretchLastSection(True)
        self.preview.setModel(ImportPreviewTableModel(self.preview))
        layout.addWidget(self.preview)

        self.count_label = QLabel("Enter data to see a preview.")
        self.count_label.setStyleSheet("color: #526477;")
        layout.addWidget(self.count_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        self.create_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.create_button.setText("Create table")
        self.create_button.setEnabled(False)
        self.buttons.accepted.connect(self._accept_candidate)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.name_edit.textChanged.connect(self._refresh_preview)
        self.text_edit.textChanged.connect(self._refresh_preview)
        self._refresh_preview()

    @property
    def candidate(self) -> ImportCandidate | None:
        return self._accepted_candidate if self.result() == QDialog.DialogCode.Accepted else None

    def _refresh_preview(self, *_args: Any) -> None:
        model = self.preview.model()
        assert isinstance(model, ImportPreviewTableModel)
        self._preview_candidate = None
        try:
            candidate = parse_pasted_table(
                self.text_edit.toPlainText(), name=self.name_edit.text().strip()
            )
        except (TypeError, ValueError) as exc:
            model.set_candidate(None)
            self.error_label.setText(str(exc))
            self.error_label.setVisible(bool(self.text_edit.toPlainText().strip()))
            self.count_label.setText("No preview is available until the table is valid.")
            self.create_button.setEnabled(False)
            return

        self._preview_candidate = candidate
        model.set_candidate(candidate)
        self.error_label.clear()
        self.error_label.setVisible(False)
        self.count_label.setText(
            f"{len(candidate.headers):,} columns · {candidate.row_count:,} rows"
        )
        self.create_button.setEnabled(bool(candidate.headers))

    def _accept_candidate(self) -> None:
        if self._preview_candidate is None:
            return
        self._accepted_candidate = self._preview_candidate
        super().accept()

    def reject(self) -> None:
        self._accepted_candidate = None
        super().reject()


class AppendQueriesDialog(QDialog):
    """Choose two loaded tables, validate their schema, and preview an append."""

    def __init__(
        self,
        tables: list[dict[str, str]],
        candidates: dict[str, ImportCandidate],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._candidates = dict(candidates)
        self._accepted_candidate: ImportCandidate | None = None
        self._accepted_source_ids: list[str] = []
        self.setWindowTitle("Append queries")
        self.setMinimumSize(680, 450)
        self.resize(860, 570)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(9)
        title = QLabel("Append rows from two loaded tables")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #273b49;")
        layout.addWidget(title)

        form = QFormLayout()
        self.query_name_edit = QLineEdit("Append query")
        self.query_name_edit.setMaxLength(120)
        self.first_combo = QComboBox()
        self.second_combo = QComboBox()
        for table in tables:
            source_id = str(table["sourceId"])
            name = str(table["displayName"])
            self.first_combo.addItem(name, source_id)
            self.second_combo.addItem(name, source_id)
        if self.second_combo.count() > 1:
            self.second_combo.setCurrentIndex(1)
        form.addRow("Query name", self.query_name_edit)
        form.addRow("First table", self.first_combo)
        form.addRow("Second table", self.second_combo)
        layout.addLayout(form)

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
        self.create_button.setText("Create query")
        self.create_button.setEnabled(False)
        self.buttons.accepted.connect(self._accept_query)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.first_combo.currentIndexChanged.connect(self._refresh_preview)
        self.second_combo.currentIndexChanged.connect(self._refresh_preview)
        self.query_name_edit.textChanged.connect(self._refresh_preview)
        self._refresh_preview()

    @property
    def candidate(self) -> ImportCandidate | None:
        return self._accepted_candidate if self.result() == QDialog.DialogCode.Accepted else None

    @property
    def source_ids(self) -> list[str]:
        return list(self._accepted_source_ids)

    @property
    def query_name(self) -> str:
        return self.query_name_edit.text().strip()

    def _refresh_preview(self, *_args: Any) -> None:
        first_id = str(self.first_combo.currentData() or "")
        second_id = str(self.second_combo.currentData() or "")
        model = self.preview.model()
        assert isinstance(model, ImportPreviewTableModel)
        self._accepted_candidate = None
        self.create_button.setEnabled(False)
        if not self.query_name:
            model.set_candidate(None)
            self._show_error("Enter a name for the appended query.")
            self.count_label.setText("No append preview is available.")
            return
        if not first_id or not second_id or first_id == second_id:
            model.set_candidate(None)
            self._show_error("Choose two different source tables.")
            self.count_label.setText("No append preview is available.")
            return
        try:
            candidate = append_candidates([
                self._candidates[first_id],
                self._candidates[second_id],
            ])
        except (KeyError, QueryError) as exc:
            model.set_candidate(None)
            self._show_error(str(exc))
            self.count_label.setText("No append preview is available.")
            return
        self._accepted_candidate = candidate
        model.set_candidate(candidate)
        self.error_label.clear()
        self.error_label.setVisible(False)
        self.count_label.setText(
            f"{len(candidate.headers):,} columns · {candidate.row_count:,} rows after append; previewing the first 100 rows"
        )
        self.create_button.setEnabled(True)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _accept_query(self) -> None:
        self._refresh_preview()
        if self._accepted_candidate is None:
            return
        self._accepted_source_ids = [
            str(self.first_combo.currentData()),
            str(self.second_combo.currentData()),
        ]
        super().accept()


class CalculatedTableDialog(QDialog):
    """Create a distinct-value calculated table from one loaded model column."""

    def __init__(
        self,
        tables: list[dict[str, Any]],
        candidates: dict[str, ImportCandidate],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tables = [dict(table) for table in tables]
        self._candidates = dict(candidates)
        self._accepted_candidate: ImportCandidate | None = None
        self._accepted_source_id = ""
        self._accepted_definition: dict[str, Any] = {}
        self._accepted_output_types: dict[str, str] = {}
        self.setWindowTitle("New calculated table")
        self.setMinimumSize(680, 470)
        self.resize(820, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(9)
        title = QLabel("Create a calculated table from distinct column values")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #273b49;")
        layout.addWidget(title)
        help_label = QLabel(
            "This local DAX subset supports DISTINCT('Table'[Column]). "
            "The result keeps one copy of each exact value, including blank, "
            "in the order first seen. It recalculates when its source refreshes."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #526477;")
        layout.addWidget(help_label)

        form = QFormLayout()
        self.table_name_edit = QLineEdit("Distinct values")
        self.table_name_edit.setMaxLength(120)
        self.source_combo = QComboBox()
        self.column_combo = QComboBox()
        for table in self._tables:
            self.source_combo.addItem(
                str(table.get("displayName", table.get("name", "Table"))),
                str(table.get("sourceId", "")),
            )
        self.expression_edit = QLineEdit()
        self.expression_edit.setReadOnly(True)
        self.expression_edit.setAccessibleName("Calculated table DAX expression")
        form.addRow("Table name", self.table_name_edit)
        form.addRow("Source table", self.source_combo)
        form.addRow("Source column", self.column_combo)
        form.addRow("DAX expression", self.expression_edit)
        layout.addLayout(form)

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

        self.source_combo.currentIndexChanged.connect(self._refresh_columns)
        self.column_combo.currentIndexChanged.connect(self._refresh_preview)
        self.table_name_edit.textChanged.connect(self._refresh_preview)
        self._refresh_columns()

    @property
    def candidate(self) -> ImportCandidate | None:
        return self._accepted_candidate if self.result() == QDialog.DialogCode.Accepted else None

    @property
    def source_ids(self) -> list[str]:
        return [self._accepted_source_id] if self._accepted_source_id else []

    @property
    def query_definition(self) -> dict[str, Any]:
        return deepcopy(self._accepted_definition)

    @property
    def query_name(self) -> str:
        return self.table_name_edit.text().strip()

    @property
    def output_types(self) -> dict[str, str]:
        return dict(self._accepted_output_types)

    def _selected_table(self) -> dict[str, Any] | None:
        source_id = str(self.source_combo.currentData() or "")
        return next(
            (table for table in self._tables if str(table.get("sourceId", "")) == source_id),
            None,
        )

    def _refresh_columns(self, *_args: Any) -> None:
        table = self._selected_table()
        headers = [str(header) for header in (table or {}).get("headers", [])]
        previous = self.column_combo.currentText()
        self.column_combo.blockSignals(True)
        self.column_combo.clear()
        self.column_combo.addItems(headers)
        if previous in headers:
            self.column_combo.setCurrentText(previous)
        self.column_combo.blockSignals(False)
        self._refresh_preview()

    def _refresh_preview(self, *_args: Any) -> None:
        model = self.preview.model()
        assert isinstance(model, ImportPreviewTableModel)
        model.set_candidate(None)
        self._accepted_candidate = None
        self._accepted_definition = {}
        self._accepted_output_types = {}
        self.create_button.setEnabled(False)
        table = self._selected_table()
        source_id = str(self.source_combo.currentData() or "")
        column = self.column_combo.currentText()
        if not self.query_name or "\x00" in self.query_name:
            self._show_error("Enter a valid name for the calculated table.")
            self.expression_edit.clear()
            self.count_label.setText("No calculated-table preview is available.")
            return
        if table is None or not source_id or not column:
            self._show_error("Choose a loaded source table and column.")
            self.expression_edit.clear()
            self.count_label.setText("No calculated-table preview is available.")
            return
        source_name = str(table.get("name", ""))
        escaped_table = source_name.replace("'", "''")
        expression = f"DISTINCT('{escaped_table}'[{column}])"
        self.expression_edit.setText(expression)
        try:
            definition = normalize_calculated_table_expression(
                expression, source_name, table.get("headers", [])
            )
            source_candidate = self._candidates[source_id]
            headers, rows = evaluate_calculated_table(
                definition["expression"], source_candidate, source_name
            )
            candidate = ImportCandidate(
                kind="query", headers=headers, rows=rows, options={}, notices=[]
            )
        except (KeyError, MeasureError) as exc:
            self._show_error(str(exc))
            self.count_label.setText("No calculated-table preview is available.")
            return
        model.set_candidate(candidate)
        self._accepted_candidate = candidate
        self._accepted_source_id = source_id
        self._accepted_definition = {
            "operation": "calculated_table",
            "source_ids": [source_id],
            "expression": definition["expression"],
            "source_table": source_name,
        }
        source_types = table.get("columnTypes", {})
        self._accepted_output_types = {
            headers[0]: str(source_types.get(headers[0], "text"))
        }
        self.error_label.clear()
        self.error_label.setVisible(False)
        self.count_label.setText(
            f"1 column · {candidate.row_count:,} distinct rows; previewing the first 100 rows"
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


class MergeQueriesDialog(QDialog):
    """Configure, validate, and preview a saved local table merge."""

    _JOIN_OPTIONS = [
        ("Left outer · keep all left rows", "left_outer"),
        ("Right outer · keep all right rows", "right_outer"),
        ("Full outer · keep rows from both", "full_outer"),
        ("Inner · keep matching rows", "inner"),
        ("Left anti · left rows without a match", "left_anti"),
        ("Right anti · right rows without a match", "right_anti"),
    ]

    def __init__(
        self,
        tables: list[dict[str, str]],
        candidates: dict[str, ImportCandidate],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tables = [dict(table) for table in tables]
        self._candidates = dict(candidates)
        self._accepted_candidate: ImportCandidate | None = None
        self._accepted_query_definition: dict[str, Any] | None = None
        self._key_pair_rows: list[dict[str, Any]] = []
        self.setWindowTitle("Merge queries")
        self.setMinimumSize(760, 560)
        self.resize(980, 700)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(9)
        title = QLabel("Merge two loaded tables into a saved query")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #273b49;")
        layout.addWidget(title)

        form = QFormLayout()
        self.query_name_edit = QLineEdit("Merge query")
        self.query_name_edit.setMaxLength(120)
        self.left_combo = QComboBox()
        self.right_combo = QComboBox()
        for table in self._tables:
            source_id = str(table["sourceId"])
            name = str(table["displayName"])
            self.left_combo.addItem(name, source_id)
            self.right_combo.addItem(name, source_id)
        if self.right_combo.count() > 1:
            self.right_combo.setCurrentIndex(1)
        self.join_kind_combo = QComboBox()
        for label, value in self._JOIN_OPTIONS:
            self.join_kind_combo.addItem(label, value)
        form.addRow("Query name", self.query_name_edit)
        form.addRow("Left table", self.left_combo)
        form.addRow("Right table", self.right_combo)
        form.addRow("Join kind", self.join_kind_combo)
        layout.addLayout(form)

        key_title = QLabel("Matching key columns")
        key_title.setStyleSheet("font-weight: 600; color: #273b49;")
        layout.addWidget(key_title)
        key_help = QLabel(
            "Add one or more column pairs. Each left column matches the right column on its row. "
            "Values compare exactly; blank keys do not match."
        )
        key_help.setWordWrap(True)
        key_help.setStyleSheet("color: #526477;")
        layout.addWidget(key_help)
        self.key_pairs_container = QWidget()
        self.key_pairs_layout = QVBoxLayout(self.key_pairs_container)
        self.key_pairs_layout.setContentsMargins(0, 0, 0, 0)
        self.key_pairs_layout.setSpacing(4)
        layout.addWidget(self.key_pairs_container)
        self.add_key_pair_button = QPushButton("Add key pair")
        layout.addWidget(self.add_key_pair_button, 0, Qt.AlignmentFlag.AlignLeft)

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
        self.create_button.setText("Create query")
        self.create_button.setEnabled(False)
        self.buttons.accepted.connect(self._accept_query)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.left_combo.currentIndexChanged.connect(self._sources_changed)
        self.right_combo.currentIndexChanged.connect(self._sources_changed)
        self.join_kind_combo.currentIndexChanged.connect(self._refresh_preview)
        self.query_name_edit.textChanged.connect(self._refresh_preview)
        self.add_key_pair_button.clicked.connect(self._add_key_pair)
        self._sources_changed()

    @property
    def candidate(self) -> ImportCandidate | None:
        return self._accepted_candidate if self.result() == QDialog.DialogCode.Accepted else None

    @property
    def query_definition(self) -> dict[str, Any]:
        return deepcopy(self._accepted_query_definition or {})

    @property
    def query_name(self) -> str:
        return self.query_name_edit.text().strip()

    def _selected_ids(self) -> tuple[str, str]:
        return (
            str(self.left_combo.currentData() or ""),
            str(self.right_combo.currentData() or ""),
        )

    def _clear_key_pairs(self) -> None:
        while self.key_pairs_layout.count():
            item = self.key_pairs_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._key_pair_rows.clear()

    def _sources_changed(self, *_args: Any) -> None:
        self._clear_key_pairs()
        left_id, right_id = self._selected_ids()
        left = self._candidates.get(left_id)
        right = self._candidates.get(right_id)
        if left is not None and right is not None and left.headers and right.headers:
            common = next((name for name in left.headers if name in right.headers), None)
            self._append_key_pair(left.headers, right.headers, common, common)
        self._refresh_preview()

    def _append_key_pair(
        self,
        left_headers: list[str],
        right_headers: list[str],
        left_value: str | None = None,
        right_value: str | None = None,
    ) -> None:
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        left_combo = QComboBox()
        right_combo = QComboBox()
        left_combo.addItems(left_headers)
        right_combo.addItems(right_headers)
        if left_value is not None:
            left_combo.setCurrentIndex(max(0, left_combo.findText(left_value)))
        if right_value is not None:
            right_combo.setCurrentIndex(max(0, right_combo.findText(right_value)))
        remove_button = QPushButton("Remove")
        row_layout.addWidget(QLabel("Left"))
        row_layout.addWidget(left_combo, 1)
        row_layout.addWidget(QLabel("matches"))
        row_layout.addWidget(QLabel("Right"))
        row_layout.addWidget(right_combo, 1)
        row_layout.addWidget(remove_button)
        self.key_pairs_layout.addWidget(row_widget)
        pair = {
            "widget": row_widget,
            "left": left_combo,
            "right": right_combo,
            "remove": remove_button,
        }
        self._key_pair_rows.append(pair)
        left_combo.currentIndexChanged.connect(self._refresh_preview)
        right_combo.currentIndexChanged.connect(self._refresh_preview)
        remove_button.clicked.connect(
            lambda _checked=False, selected=pair: self._remove_key_pair(selected)
        )
        self._update_key_pair_controls()

    def _add_key_pair(self, *_args: Any) -> None:
        left_id, right_id = self._selected_ids()
        left = self._candidates.get(left_id)
        right = self._candidates.get(right_id)
        if left is None or right is None:
            return
        used_left = {str(pair["left"].currentText()) for pair in self._key_pair_rows}
        used_right = {str(pair["right"].currentText()) for pair in self._key_pair_rows}
        next_left = next((name for name in left.headers if name not in used_left), None)
        next_right = next((name for name in right.headers if name not in used_right), None)
        if next_left is None or next_right is None:
            self._show_error("There are no unused columns available for another key pair.")
            return
        self._append_key_pair(left.headers, right.headers, next_left, next_right)
        self._refresh_preview()

    def _remove_key_pair(self, pair: dict[str, Any]) -> None:
        if len(self._key_pair_rows) <= 1:
            return
        self._key_pair_rows.remove(pair)
        pair["widget"].deleteLater()
        self._update_key_pair_controls()
        self._refresh_preview()

    def _update_key_pair_controls(self) -> None:
        can_remove = len(self._key_pair_rows) > 1
        for pair in self._key_pair_rows:
            pair["remove"].setEnabled(can_remove)
        left_id, right_id = self._selected_ids()
        left = self._candidates.get(left_id)
        right = self._candidates.get(right_id)
        self.add_key_pair_button.setEnabled(
            left is not None and right is not None
            and len(self._key_pair_rows) < min(len(left.headers), len(right.headers))
        )

    def _refresh_preview(self, *_args: Any) -> None:
        model = self.preview.model()
        assert isinstance(model, ImportPreviewTableModel)
        self._accepted_candidate = None
        self._accepted_query_definition = None
        self.create_button.setEnabled(False)
        if not self.query_name:
            model.set_candidate(None)
            self._show_error("Enter a name for the merged query.")
            self.count_label.setText("No merge preview is available.")
            return
        left_id, right_id = self._selected_ids()
        if not left_id or not right_id or left_id == right_id:
            model.set_candidate(None)
            self._show_error("Choose two different source tables.")
            self.count_label.setText("No merge preview is available.")
            return
        if not self._key_pair_rows:
            model.set_candidate(None)
            self._show_error("Add at least one matching key pair.")
            self.count_label.setText("No merge preview is available.")
            return
        left_keys = [str(pair["left"].currentText()) for pair in self._key_pair_rows]
        right_keys = [str(pair["right"].currentText()) for pair in self._key_pair_rows]
        if len(set(left_keys)) != len(left_keys) or len(set(right_keys)) != len(right_keys):
            model.set_candidate(None)
            self._show_error("Each source column can only be used once as a merge key.")
            self.count_label.setText("No merge preview is available.")
            return
        try:
            right_name = str(self.right_combo.currentText())
            candidate = merge_candidates(
                self._candidates[left_id],
                self._candidates[right_id],
                left_keys=left_keys,
                right_keys=right_keys,
                join_kind=str(self.join_kind_combo.currentData()),
                right_name=right_name,
            )
        except (KeyError, QueryError) as exc:
            model.set_candidate(None)
            self._show_error(str(exc))
            self.count_label.setText("No merge preview is available.")
            return
        self._accepted_candidate = candidate
        self._accepted_query_definition = {
            "operation": "merge",
            "source_ids": [left_id, right_id],
            "left_keys": left_keys,
            "right_keys": right_keys,
            "join_kind": str(self.join_kind_combo.currentData()),
            "right_name": right_name,
        }
        model.set_candidate(candidate)
        self.error_label.clear()
        self.error_label.setVisible(False)
        self.count_label.setText(
            f"{len(candidate.headers):,} columns · {candidate.row_count:,} rows after merge; "
            "right-side columns are expanded in the preview (first 100 rows shown)"
        )
        self.create_button.setEnabled(True)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _accept_query(self) -> None:
        self._refresh_preview()
        if self._accepted_candidate is None:
            return
        super().accept()


class TransformDataDialog(QDialog):
    """Build and preview an ordered, replayable local transformation sequence."""

    def __init__(
        self,
        source_candidate: ImportCandidate,
        steps: list[dict[str, Any]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._source_candidate = source_candidate
        self._steps = validate_steps(steps or [])
        self._accepted_candidate: ImportCandidate | None = None
        self._accepted_steps: list[dict[str, Any]] | None = None
        self._preview_candidate = apply_transformations(self._source_candidate, self._steps)
        self.setWindowTitle("Transform data")
        self.setMinimumSize(660, 470)
        self.resize(900, 640)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(9)
        title = QLabel("Preview local table steps")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #273b49;")
        layout.addWidget(title)
        type_note = QLabel(
            "Type steps validate and standardize values. The model saves each column type; table cells are stored as normalized text."
        )
        type_note.setWordWrap(True)
        type_note.setStyleSheet("color: #526477;")
        layout.addWidget(type_note)

        body = QHBoxLayout()
        body.setSpacing(12)
        layout.addLayout(body, 1)

        step_column = QVBoxLayout()
        step_column.addWidget(QLabel("Applied steps"))
        self.step_list = QListWidget()
        self.step_list.setMinimumWidth(225)
        step_column.addWidget(self.step_list, 1)
        step_buttons = QHBoxLayout()
        self.remove_button = QPushButton("Remove")
        self.up_button = QPushButton("Up")
        self.down_button = QPushButton("Down")
        step_buttons.addWidget(self.remove_button)
        step_buttons.addWidget(self.up_button)
        step_buttons.addWidget(self.down_button)
        step_column.addLayout(step_buttons)
        body.addLayout(step_column)

        editor = QVBoxLayout()
        form = QFormLayout()
        self.operation_combo = QComboBox()
        for label, value in (
            ("Rename column", "rename_column"),
            ("Remove column", "remove_column"),
            ("Filter rows", "filter_rows"),
            ("Filter rows (advanced)", "filter_rows_advanced"),
            ("Sort rows", "sort_rows"),
            ("Sort rows by multiple columns", "sort_rows_by_columns"),
            ("Convert type", "convert_type"),
            ("Change type using locale", "convert_type_using_locale"),
            ("Replace values", "replace_value"),
            ("Extract text before/after delimiter", "extract_text_by_delimiter"),
            ("Extract text between delimiters", "extract_text_between_delimiters"),
            ("Split column by delimiter", "split_column"),
            ("Split column at every delimiter into columns", "split_column_by_each_delimiter"),
            ("Split column into rows", "split_column_to_rows"),
            ("Split column by positions", "split_column_by_positions"),
            ("Merge columns", "merge_columns"),
            ("Fill down", "fill_down"),
            ("Fill up", "fill_up"),
            ("Duplicate column", "duplicate_column"),
            ("Add index column", "add_index_column"),
            ("Group by and aggregate rows", "group_by"),
            ("Unpivot selected columns", "unpivot_columns"),
            ("Unpivot other columns", "unpivot_other_columns"),
            ("Pivot column", "pivot_column"),
            ("Add custom column", "add_custom_column"),
            ("Add conditional column", "conditional_column"),
            ("Trim text", "trim_text"),
            ("Clean text", "clean_text"),
            ("Lowercase text", "lowercase_text"),
            ("Uppercase text", "uppercase_text"),
            ("Capitalize each word", "proper_case_text"),
            ("Reverse text", "reverse_text"),
            ("Remove duplicates", "remove_duplicates"),
            ("Keep duplicates", "keep_duplicates"),
            ("Remove blank rows", "remove_blank_rows"),
            ("Remove top rows", "remove_top_rows"),
            ("Remove bottom rows", "remove_bottom_rows"),
            ("Keep top rows", "keep_top_rows"),
            ("Keep bottom rows", "keep_bottom_rows"),
            ("Keep range of rows", "keep_range_rows"),
            ("Remove alternate rows", "remove_alternate_rows"),
            ("Keep columns", "keep_columns"),
            ("Reorder columns", "reorder_columns"),
            ("Use first row as headers", "promote_headers"),
            ("Use headers as first row", "demote_headers"),
            ("Transpose table", "transpose_table"),
        ):
            self.operation_combo.addItem(label, value)
        self.column_combo = QComboBox()
        self.sort_criteria_widget = QWidget()
        sort_criteria_layout = QVBoxLayout(self.sort_criteria_widget)
        sort_criteria_layout.setContentsMargins(0, 0, 0, 0)
        sort_criteria_layout.setSpacing(4)
        self.sort_criteria_table = QTableWidget(0, 2)
        self.sort_criteria_table.setObjectName("sortCriteriaTable")
        self.sort_criteria_table.setHorizontalHeaderLabels(("Column", "Order"))
        self.sort_criteria_table.verticalHeader().setVisible(False)
        self.sort_criteria_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.sort_criteria_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.sort_criteria_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.sort_criteria_table.setMaximumHeight(142)
        sort_criteria_layout.addWidget(self.sort_criteria_table)
        sort_criteria_buttons = QHBoxLayout()
        self.sort_add_button = QPushButton("Add level")
        self.sort_add_button.setObjectName("addSortLevelButton")
        self.sort_remove_button = QPushButton("Remove")
        self.sort_remove_button.setObjectName("removeSortLevelButton")
        self.sort_up_button = QPushButton("Up")
        self.sort_down_button = QPushButton("Down")
        sort_criteria_buttons.addWidget(self.sort_add_button)
        sort_criteria_buttons.addWidget(self.sort_remove_button)
        sort_criteria_buttons.addWidget(self.sort_up_button)
        sort_criteria_buttons.addWidget(self.sort_down_button)
        sort_criteria_layout.addLayout(sort_criteria_buttons)
        self.sort_criteria_widget.setToolTip(
            "Top rows have higher priority. Each key can sort ascending or descending."
        )
        self.value_edit = QLineEdit()
        self.culture_edit = QLineEdit("en-US")
        self.culture_edit.setObjectName("transformCultureEdit")
        self.culture_edit.setPlaceholderText("en-US")
        self.culture_edit.setToolTip(
            "Culture is saved with this step and used again when the source refreshes. "
            "Examples: en-US, en-GB, de-DE, fr-FR."
        )
        self.range_first_row_edit = QLineEdit()
        self.range_first_row_edit.setObjectName("keepRangeFirstRowEdit")
        self.alternate_first_row_edit = QLineEdit()
        self.alternate_first_row_edit.setObjectName("removeAlternateFirstRowEdit")
        self.alternate_remove_count_edit = QLineEdit()
        self.alternate_remove_count_edit.setObjectName("removeAlternateCountEdit")
        self.alternate_keep_count_edit = QLineEdit()
        self.alternate_keep_count_edit.setObjectName("keepAlternateCountEdit")
        self.index_start_edit = QLineEdit()
        self.index_start_edit.setObjectName("indexColumnStartEdit")
        self.index_increment_edit = QLineEdit()
        self.index_increment_edit.setObjectName("indexColumnIncrementEdit")
        self._row_count_validator = QIntValidator(0, MAX_DATA_ROWS, self)
        self._first_row_validator = QIntValidator(1, MAX_DATA_ROWS, self)
        self._index_value_validator = QRegularExpressionValidator(
            QRegularExpression(r"-?[0-9]{1,19}"), self
        )
        self.index_start_edit.setMaxLength(20)
        self.index_increment_edit.setMaxLength(20)
        self.custom_expression_edit = QPlainTextEdit()
        self.custom_expression_edit.setObjectName("customColumnExpressionEdit")
        self.custom_expression_edit.setPlaceholderText(
            'if [Amount] > 100 then "High" else "Low"'
        )
        self.custom_expression_edit.setMaximumHeight(76)
        self.custom_expression_label = QLabel("M-style formula")
        self.custom_expression_edit.setToolTip(
            "Supports field references, literals, arithmetic, comparisons, if/then/else, "
            "and selected Text, Number, and Date functions. This is not full M."
        )
        self._conditional_clauses: list[dict[str, str]] = []
        self._filter_clauses: list[dict[str, str]] = []
        self.advanced_filter_widget = QWidget()
        advanced_filter_layout = QVBoxLayout(self.advanced_filter_widget)
        advanced_filter_layout.setContentsMargins(0, 0, 0, 0)
        advanced_filter_layout.setSpacing(4)
        advanced_filter_join_row = QHBoxLayout()
        advanced_filter_join_row.addWidget(QLabel("Clause connector"))
        self.advanced_filter_join_combo = QComboBox()
        self.advanced_filter_join_combo.setObjectName("advancedFilterJoinCombo")
        self.advanced_filter_join_combo.addItem("AND", "and")
        self.advanced_filter_join_combo.addItem("OR", "or")
        self.advanced_filter_join_combo.setToolTip(
            "This connector joins the selected clause to the clause before it. "
            "AND is evaluated before OR. The first clause has no connector."
        )
        advanced_filter_join_row.addWidget(self.advanced_filter_join_combo)
        advanced_filter_join_row.addStretch(1)
        advanced_filter_layout.addLayout(advanced_filter_join_row)
        self.advanced_filter_clause_list = QListWidget()
        self.advanced_filter_clause_list.setObjectName("advancedFilterClausesList")
        self.advanced_filter_clause_list.setMaximumHeight(96)
        self.advanced_filter_clause_list.setToolTip(
            "Clauses form one flat expression; AND binds more tightly than OR. "
            "Use separate filter steps for nested logic."
        )
        advanced_filter_layout.addWidget(self.advanced_filter_clause_list)
        advanced_filter_buttons = QHBoxLayout()
        self.add_advanced_filter_clause_button = QPushButton("Add clause")
        self.add_advanced_filter_clause_button.setObjectName("addAdvancedFilterClauseButton")
        self.update_advanced_filter_clause_button = QPushButton("Update clause")
        self.update_advanced_filter_clause_button.setObjectName("updateAdvancedFilterClauseButton")
        self.remove_advanced_filter_clause_button = QPushButton("Remove clause")
        self.remove_advanced_filter_clause_button.setObjectName("removeAdvancedFilterClauseButton")
        advanced_filter_buttons.addWidget(self.add_advanced_filter_clause_button)
        advanced_filter_buttons.addWidget(self.update_advanced_filter_clause_button)
        advanced_filter_buttons.addWidget(self.remove_advanced_filter_clause_button)
        advanced_filter_layout.addLayout(advanced_filter_buttons)
        self.conditional_column_widget = QWidget()
        conditional_layout = QVBoxLayout(self.conditional_column_widget)
        conditional_layout.setContentsMargins(0, 0, 0, 0)
        conditional_layout.setSpacing(4)

        condition_row = QHBoxLayout()
        self.conditional_test_column_combo = QComboBox()
        self.conditional_test_column_combo.setObjectName("conditionalTestColumnCombo")
        self.conditional_operator_combo = QComboBox()
        self.conditional_operator_combo.setObjectName("conditionalOperatorCombo")
        for label, value in (
            ("Equals", "equals"),
            ("Does not equal", "not_equals"),
            ("Greater than", "greater_than"),
            ("Greater than or equal", "greater_than_or_equal"),
            ("Less than", "less_than"),
            ("Less than or equal", "less_than_or_equal"),
            ("Begins with", "begins_with"),
            ("Does not begin with", "does_not_begin_with"),
            ("Ends with", "ends_with"),
            ("Does not end with", "does_not_end_with"),
            ("Contains", "contains"),
            ("Does not contain", "does_not_contain"),
        ):
            self.conditional_operator_combo.addItem(label, value)
        condition_row.addWidget(QLabel("If"))
        condition_row.addWidget(self.conditional_test_column_combo, 2)
        condition_row.addWidget(self.conditional_operator_combo, 3)
        conditional_layout.addLayout(condition_row)

        compare_row = QHBoxLayout()
        self.conditional_test_value_kind_combo = QComboBox()
        self.conditional_test_value_kind_combo.setObjectName("conditionalTestValueKindCombo")
        self.conditional_test_value_kind_combo.addItem("Value", "value")
        self.conditional_test_value_kind_combo.addItem("Column", "column")
        self.conditional_test_value_edit = QLineEdit()
        self.conditional_test_value_edit.setObjectName("conditionalTestValueEdit")
        self.conditional_test_value_edit.setPlaceholderText("Compare value")
        self.conditional_test_value_column_combo = QComboBox()
        self.conditional_test_value_column_combo.setObjectName("conditionalTestValueColumnCombo")
        compare_row.addWidget(QLabel("Against"))
        compare_row.addWidget(self.conditional_test_value_kind_combo)
        compare_row.addWidget(self.conditional_test_value_edit, 2)
        compare_row.addWidget(self.conditional_test_value_column_combo, 2)
        conditional_layout.addLayout(compare_row)

        output_row = QHBoxLayout()
        self.conditional_output_kind_combo = QComboBox()
        self.conditional_output_kind_combo.setObjectName("conditionalOutputKindCombo")
        self.conditional_output_kind_combo.addItem("Value", "value")
        self.conditional_output_kind_combo.addItem("Column", "column")
        self.conditional_output_edit = QLineEdit()
        self.conditional_output_edit.setObjectName("conditionalOutputValueEdit")
        self.conditional_output_edit.setPlaceholderText("Return value")
        self.conditional_output_column_combo = QComboBox()
        self.conditional_output_column_combo.setObjectName("conditionalOutputColumnCombo")
        output_row.addWidget(QLabel("Return"))
        output_row.addWidget(self.conditional_output_kind_combo)
        output_row.addWidget(self.conditional_output_edit, 2)
        output_row.addWidget(self.conditional_output_column_combo, 2)
        conditional_layout.addLayout(output_row)

        self.conditional_clause_list = QListWidget()
        self.conditional_clause_list.setObjectName("conditionalClausesList")
        self.conditional_clause_list.setMaximumHeight(76)
        self.conditional_clause_list.setToolTip(
            "Rules run from top to bottom. The first matching rule supplies the output."
        )
        conditional_layout.addWidget(self.conditional_clause_list)
        clause_buttons = QHBoxLayout()
        self.add_conditional_clause_button = QPushButton("Add clause")
        self.add_conditional_clause_button.setObjectName("addConditionalClauseButton")
        self.update_conditional_clause_button = QPushButton("Update clause")
        self.update_conditional_clause_button.setObjectName("updateConditionalClauseButton")
        self.remove_conditional_clause_button = QPushButton("Remove clause")
        self.remove_conditional_clause_button.setObjectName("removeConditionalClauseButton")
        self.up_conditional_clause_button = QPushButton("Up")
        self.down_conditional_clause_button = QPushButton("Down")
        clause_buttons.addWidget(self.add_conditional_clause_button)
        clause_buttons.addWidget(self.update_conditional_clause_button)
        clause_buttons.addWidget(self.remove_conditional_clause_button)
        clause_buttons.addWidget(self.up_conditional_clause_button)
        clause_buttons.addWidget(self.down_conditional_clause_button)
        conditional_layout.addLayout(clause_buttons)

        else_row = QHBoxLayout()
        self.conditional_else_kind_combo = QComboBox()
        self.conditional_else_kind_combo.setObjectName("conditionalElseKindCombo")
        self.conditional_else_kind_combo.addItem("Value", "value")
        self.conditional_else_kind_combo.addItem("Column", "column")
        self.conditional_else_edit = QLineEdit()
        self.conditional_else_edit.setObjectName("conditionalElseValueEdit")
        self.conditional_else_edit.setPlaceholderText("Else value")
        self.conditional_else_column_combo = QComboBox()
        self.conditional_else_column_combo.setObjectName("conditionalElseColumnCombo")
        else_row.addWidget(QLabel("Else"))
        else_row.addWidget(self.conditional_else_kind_combo)
        else_row.addWidget(self.conditional_else_edit, 2)
        else_row.addWidget(self.conditional_else_column_combo, 2)
        conditional_layout.addLayout(else_row)

        self.replacement_edit = QLineEdit()
        self.replacement_edit.setObjectName("replacementValueEdit")
        self.delimiter_edit = QLineEdit()
        self.delimiter_edit.setObjectName("splitColumnDelimiterEdit")
        self.delimiter_edit.setMaxLength(MAX_MERGE_SEPARATOR_CHARS)
        self.end_delimiter_edit = QLineEdit()
        self.end_delimiter_edit.setObjectName("extractBetweenEndDelimiterEdit")
        self.end_delimiter_edit.setMaxLength(MAX_MERGE_SEPARATOR_CHARS)
        self.end_occurrence_edit = QLineEdit()
        self.end_occurrence_edit.setObjectName("extractBetweenEndOccurrenceEdit")
        self.end_occurrence_edit.setMaxLength(6)
        self.end_occurrence_edit.setValidator(self._row_count_validator)
        self.delimiter_label = QLabel("Delimiter (first match)")
        self.end_delimiter_label = QLabel("End delimiter")
        self.end_occurrence_label = QLabel("End occurrence (zero-based)")
        self.option_combo = QComboBox()
        self.value_label = QLabel("Value")
        self.range_first_row_label = QLabel("First row")
        self.alternate_first_row_label = QLabel("First row to remove")
        self.alternate_remove_count_label = QLabel("Number of rows to remove")
        self.alternate_keep_count_label = QLabel("Number of rows to keep")
        self.index_start_label = QLabel("Starting index")
        self.index_increment_label = QLabel("Increment")
        self.replacement_label = QLabel("Replace with")
        self.option_label = QLabel("Option")
        self.culture_label = QLabel("Culture")
        self.column_label = QLabel("Column")
        self.pivot_value_column_combo = QComboBox()
        self.pivot_value_column_combo.setObjectName("pivotValueColumnCombo")
        self.pivot_value_column_label = QLabel("Value column")
        self.keep_columns_list = QListWidget()
        self.keep_columns_list.setObjectName("keepTransformColumnsList")
        self.keep_columns_list.setMaximumHeight(90)
        self.keep_columns_label = QLabel("Columns to keep")
        self.attribute_name_edit = QLineEdit("Attribute")
        self.attribute_name_edit.setObjectName("unpivotAttributeNameEdit")
        self.attribute_name_label = QLabel("Attribute column")
        self.value_column_name_edit = QLineEdit("Value")
        self.value_column_name_edit.setObjectName("unpivotValueNameEdit")
        self.value_column_name_label = QLabel("Value column")
        self._group_aggregations: list[dict[str, str]] = []
        self.group_aggregation_widget = QWidget()
        group_aggregation_layout = QVBoxLayout(self.group_aggregation_widget)
        group_aggregation_layout.setContentsMargins(0, 0, 0, 0)
        group_aggregation_layout.setSpacing(4)
        group_aggregation_fields = QHBoxLayout()
        group_aggregation_fields.setSpacing(4)
        group_aggregation_fields.addWidget(QLabel("Operation"))
        self.group_aggregate_operation_combo = QComboBox()
        self.group_aggregate_operation_combo.setObjectName("groupAggregateOperationCombo")
        self.group_aggregate_operation_combo.setToolTip("Choose the aggregation to calculate per group.")
        for label, value in (
            ("Sum", "sum"),
            ("Average", "average"),
            ("Median", "median"),
            ("Minimum", "min"),
            ("Maximum", "max"),
            ("Count distinct values", "count_distinct_values"),
            ("Count rows", "count_rows"),
            ("Count distinct rows", "count_distinct_rows"),
        ):
            self.group_aggregate_operation_combo.addItem(label, value)
        self.group_aggregate_column_combo = QComboBox()
        self.group_aggregate_column_combo.setObjectName("groupAggregateColumnCombo")
        self.group_aggregate_column_combo.setToolTip(
            "Source column for column-based aggregations."
        )
        self.group_aggregate_name_edit = QLineEdit()
        self.group_aggregate_name_edit.setObjectName("groupAggregateNameEdit")
        self.group_aggregate_name_edit.setPlaceholderText("Output column (optional)")
        group_aggregation_fields.addWidget(self.group_aggregate_operation_combo, 2)
        group_aggregation_fields.addWidget(self.group_aggregate_column_combo, 2)
        group_aggregation_fields.addWidget(self.group_aggregate_name_edit, 2)
        group_aggregation_layout.addLayout(group_aggregation_fields)
        group_aggregation_buttons = QHBoxLayout()
        self.add_group_aggregation_button = QPushButton("Add aggregation")
        self.add_group_aggregation_button.setObjectName("addGroupAggregationButton")
        self.remove_group_aggregation_button = QPushButton("Remove aggregation")
        self.remove_group_aggregation_button.setObjectName("removeGroupAggregationButton")
        group_aggregation_buttons.addWidget(self.add_group_aggregation_button)
        group_aggregation_buttons.addWidget(self.remove_group_aggregation_button)
        group_aggregation_layout.addLayout(group_aggregation_buttons)
        self.group_aggregations_list = QListWidget()
        self.group_aggregations_list.setObjectName("groupAggregationsList")
        self.group_aggregations_list.setMaximumHeight(72)
        self.group_aggregations_list.setToolTip(
            "Numeric and min/max aggregates ignore empty cells. Numeric aggregates report "
            "invalid non-empty numbers. "
            "Distinct-value counts include blank cells."
        )
        group_aggregation_layout.addWidget(self.group_aggregations_list)
        form.addRow("Operation", self.operation_combo)
        form.addRow(self.column_label, self.column_combo)
        form.addRow("Sort priority", self.sort_criteria_widget)
        form.addRow(self.pivot_value_column_label, self.pivot_value_column_combo)
        form.addRow(self.range_first_row_label, self.range_first_row_edit)
        form.addRow(self.alternate_first_row_label, self.alternate_first_row_edit)
        form.addRow(self.alternate_remove_count_label, self.alternate_remove_count_edit)
        form.addRow(self.alternate_keep_count_label, self.alternate_keep_count_edit)
        form.addRow(self.value_label, self.value_edit)
        form.addRow(self.index_start_label, self.index_start_edit)
        form.addRow(self.index_increment_label, self.index_increment_edit)
        form.addRow(self.custom_expression_label, self.custom_expression_edit)
        form.addRow("Conditional rules", self.conditional_column_widget)
        form.addRow("Filter conditions", self.advanced_filter_widget)
        form.addRow(self.replacement_label, self.replacement_edit)
        form.addRow(self.delimiter_label, self.delimiter_edit)
        form.addRow(self.end_occurrence_label, self.end_occurrence_edit)
        form.addRow(self.end_delimiter_label, self.end_delimiter_edit)
        form.addRow(self.option_label, self.option_combo)
        form.addRow(self.culture_label, self.culture_edit)
        form.addRow(self.keep_columns_label, self.keep_columns_list)
        form.addRow(self.attribute_name_label, self.attribute_name_edit)
        form.addRow(self.value_column_name_label, self.value_column_name_edit)
        form.addRow("Aggregations", self.group_aggregation_widget)
        editor.addLayout(form)

        self.add_button = QPushButton("Add step")
        self.add_button.setObjectName("addTransformStepButton")
        self.update_button = QPushButton("Update selected")
        self.update_button.setObjectName("updateTransformStepButton")
        action_row = QHBoxLayout()
        action_row.addWidget(self.add_button)
        action_row.addWidget(self.update_button)
        action_row.addStretch(1)
        editor.addLayout(action_row)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setVisible(False)
        editor.addWidget(self.error_label)
        editor.addWidget(QLabel("Preview"))
        self.preview = QTableView()
        self.preview.setAlternatingRowColors(True)
        self.preview.horizontalHeader().setStretchLastSection(True)
        self.preview.setModel(ImportPreviewTableModel(self.preview))
        editor.addWidget(self.preview, 1)
        body.addLayout(editor, 1)

        self.count_label = QLabel()
        self.count_label.setStyleSheet("color: #526477;")
        layout.addWidget(self.count_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        self.apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.apply_button.setText("Apply steps")
        self.buttons.accepted.connect(self._accept_candidate)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.operation_combo.currentIndexChanged.connect(self._configure_editor)
        self.option_combo.currentIndexChanged.connect(
            self._update_filter_value_visibility
        )
        self.sort_add_button.clicked.connect(self._add_sort_level)
        self.sort_remove_button.clicked.connect(self._remove_sort_level)
        self.sort_up_button.clicked.connect(lambda: self._move_sort_level(-1))
        self.sort_down_button.clicked.connect(lambda: self._move_sort_level(1))
        self.sort_criteria_table.currentCellChanged.connect(
            lambda *_args: self._update_sort_level_controls()
        )
        self.column_combo.currentIndexChanged.connect(self._update_pivot_value_choices)
        self.group_aggregate_operation_combo.currentIndexChanged.connect(
            self._configure_group_aggregate_fields
        )
        self.add_group_aggregation_button.clicked.connect(self._add_group_aggregation)
        self.remove_group_aggregation_button.clicked.connect(self._remove_group_aggregation)
        self.group_aggregations_list.currentRowChanged.connect(
            lambda _row: self._update_group_aggregation_controls()
        )
        self.add_button.clicked.connect(self._add_or_start_new_step)
        self.update_button.clicked.connect(self._update_selected_step)
        self.remove_button.clicked.connect(self._remove_step)
        self.up_button.clicked.connect(lambda: self._move_step(-1))
        self.down_button.clicked.connect(lambda: self._move_step(1))
        self.step_list.currentRowChanged.connect(self._select_step)
        self.conditional_test_value_kind_combo.currentIndexChanged.connect(
            self._configure_conditional_fields
        )
        self.conditional_output_kind_combo.currentIndexChanged.connect(
            self._configure_conditional_fields
        )
        self.conditional_else_kind_combo.currentIndexChanged.connect(
            self._configure_conditional_fields
        )
        self.conditional_clause_list.currentRowChanged.connect(
            self._select_conditional_clause
        )
        self.advanced_filter_clause_list.currentRowChanged.connect(
            self._select_advanced_filter_clause
        )
        self.add_advanced_filter_clause_button.clicked.connect(
            self._add_advanced_filter_clause
        )
        self.update_advanced_filter_clause_button.clicked.connect(
            self._update_advanced_filter_clause
        )
        self.remove_advanced_filter_clause_button.clicked.connect(
            self._remove_advanced_filter_clause
        )
        self.add_conditional_clause_button.clicked.connect(self._add_conditional_clause)
        self.update_conditional_clause_button.clicked.connect(self._update_conditional_clause)
        self.remove_conditional_clause_button.clicked.connect(self._remove_conditional_clause)
        self.up_conditional_clause_button.clicked.connect(
            lambda: self._move_conditional_clause(-1)
        )
        self.down_conditional_clause_button.clicked.connect(
            lambda: self._move_conditional_clause(1)
        )
        self._render_steps()
        self._refresh_preview()
        self._configure_editor()
        self._configure_group_aggregate_fields()
        self._update_step_controls()

    @property
    def candidate(self) -> ImportCandidate | None:
        return self._accepted_candidate if self.result() == QDialog.DialogCode.Accepted else None

    @property
    def steps(self) -> list[dict[str, Any]] | None:
        return deepcopy(self._accepted_steps) if self.result() == QDialog.DialogCode.Accepted else None

    def _configure_editor(self, *_args: Any) -> None:
        op = str(self.operation_combo.currentData())
        selected_index = self.step_list.currentRow()
        base_candidate = (
            apply_transformations(
                self._source_candidate,
                self._steps[:selected_index],
            )
            if 0 <= selected_index < len(self._steps)
            else self._preview_candidate
        )
        self.column_combo.clear()
        self.column_combo.addItems(base_candidate.headers)
        self.pivot_value_column_combo.clear()
        self.conditional_test_column_combo.clear()
        self.conditional_test_column_combo.addItems(base_candidate.headers)
        self.conditional_test_value_column_combo.clear()
        self.conditional_test_value_column_combo.addItems(base_candidate.headers)
        self.conditional_output_column_combo.clear()
        self.conditional_output_column_combo.addItems(base_candidate.headers)
        self.conditional_else_column_combo.clear()
        self.conditional_else_column_combo.addItems(base_candidate.headers)
        self.value_edit.clear()
        self.culture_edit.setText("en-US")
        self.value_edit.setValidator(None)
        self.range_first_row_edit.clear()
        self.range_first_row_edit.setValidator(None)
        self.alternate_first_row_edit.clear()
        self.alternate_first_row_edit.setValidator(None)
        self.alternate_remove_count_edit.clear()
        self.alternate_remove_count_edit.setValidator(None)
        self.alternate_keep_count_edit.clear()
        self.alternate_keep_count_edit.setValidator(None)
        self.index_start_edit.clear()
        self.index_start_edit.setValidator(None)
        self.index_increment_edit.clear()
        self.index_increment_edit.setValidator(None)
        self.custom_expression_edit.clear()
        self.conditional_test_value_edit.clear()
        self.conditional_output_edit.clear()
        self.conditional_else_edit.clear()
        self._conditional_clauses = []
        self.conditional_clause_list.clear()
        self._filter_clauses = []
        self.advanced_filter_clause_list.clear()
        self._set_combo_data(self.advanced_filter_join_combo, "and")
        self.delimiter_edit.setPlaceholderText("Delimiter")
        self.conditional_test_value_kind_combo.setCurrentIndex(0)
        self.conditional_output_kind_combo.setCurrentIndex(0)
        self.conditional_else_kind_combo.setCurrentIndex(0)
        self.replacement_edit.clear()
        self.delimiter_edit.clear()
        self.end_delimiter_edit.clear()
        self.end_occurrence_edit.clear()
        self.attribute_name_edit.clear()
        self.value_column_name_edit.clear()
        self.option_combo.clear()
        self.option_combo.setToolTip("")
        pivot_visible = op == "pivot_column"
        self.pivot_value_column_label.setVisible(pivot_visible)
        self.pivot_value_column_combo.setVisible(pivot_visible)
        option_visible = op in {
            "filter_rows", "filter_rows_advanced", "sort_rows", "convert_type", "convert_type_using_locale",
            "pivot_column", "extract_text_by_delimiter",
        }
        self.option_combo.setVisible(option_visible)
        self.option_label.setVisible(option_visible)
        self.option_label.setText(
            "Aggregate values"
            if pivot_visible
            else "Extract"
            if op == "extract_text_by_delimiter"
            else "Target type"
            if op in {"convert_type", "convert_type_using_locale"}
            else "Filter operator"
            if op in {"filter_rows", "filter_rows_advanced"}
            else "Option"
        )
        culture_visible = op == "convert_type_using_locale"
        self.culture_edit.setVisible(culture_visible)
        self.culture_label.setVisible(culture_visible)
        custom_visible = op == "add_custom_column"
        self.custom_expression_label.setVisible(custom_visible)
        self.custom_expression_edit.setVisible(custom_visible)
        conditional_visible = op == "conditional_column"
        self.conditional_column_widget.setVisible(conditional_visible)
        advanced_filter_visible = op == "filter_rows_advanced"
        self.advanced_filter_widget.setVisible(advanced_filter_visible)
        range_rows_visible = op == "keep_range_rows"
        self.range_first_row_label.setVisible(range_rows_visible)
        self.range_first_row_edit.setVisible(range_rows_visible)
        alternate_rows_visible = op == "remove_alternate_rows"
        for widget in (
            self.alternate_first_row_label,
            self.alternate_first_row_edit,
            self.alternate_remove_count_label,
            self.alternate_remove_count_edit,
            self.alternate_keep_count_label,
            self.alternate_keep_count_edit,
        ):
            widget.setVisible(alternate_rows_visible)
        index_column_visible = op == "add_index_column"
        self.index_start_label.setVisible(index_column_visible)
        self.index_start_edit.setVisible(index_column_visible)
        self.index_increment_label.setVisible(index_column_visible)
        self.index_increment_edit.setVisible(index_column_visible)
        value_visible = op in {
            "rename_column", "filter_rows", "filter_rows_advanced", "replace_value", "add_custom_column", "add_index_column",
            "conditional_column", "merge_columns", "duplicate_column",
            "remove_top_rows", "remove_bottom_rows", "keep_top_rows", "keep_bottom_rows",
            "keep_range_rows", "extract_text_by_delimiter", "extract_text_between_delimiters",
        }
        self.value_edit.setVisible(value_visible)
        self.value_label.setVisible(value_visible)
        name_entry = op in {
            "rename_column", "add_custom_column", "add_index_column", "conditional_column", "merge_columns",
            "duplicate_column",
        }
        self.value_label.setText("New column name" if name_entry else "Value to match")
        self.value_edit.setPlaceholderText("New column name" if name_entry else "Value to match")
        if op == "filter_rows_advanced":
            self.value_label.setText("Clause value")
            self.value_edit.setPlaceholderText("Value to match")
        if op in {"extract_text_by_delimiter", "extract_text_between_delimiters"}:
            self.value_label.setText(
                "Start occurrence (zero-based)"
                if op == "extract_text_between_delimiters"
                else "Occurrence (zero-based)"
            )
            self.value_edit.setPlaceholderText("0")
            self.value_edit.setValidator(self._row_count_validator)
            self.value_edit.setText("0")
        elif op == "keep_range_rows":
            self.value_label.setText("Number of rows")
            self.value_edit.setPlaceholderText("1")
            self.value_edit.setValidator(self._row_count_validator)
            self.value_edit.setText("1")
            self.range_first_row_edit.setValidator(self._first_row_validator)
            self.range_first_row_edit.setPlaceholderText("1")
            self.range_first_row_edit.setText("1")
        elif op == "remove_alternate_rows":
            self.value_edit.setVisible(False)
            self.value_label.setVisible(False)
            self.alternate_first_row_edit.setValidator(self._first_row_validator)
            self.alternate_first_row_edit.setPlaceholderText("2")
            self.alternate_first_row_edit.setText("2")
            self.alternate_remove_count_edit.setValidator(self._row_count_validator)
            self.alternate_remove_count_edit.setPlaceholderText("1")
            self.alternate_remove_count_edit.setText("1")
            self.alternate_keep_count_edit.setValidator(self._row_count_validator)
            self.alternate_keep_count_edit.setPlaceholderText("1")
            self.alternate_keep_count_edit.setText("1")
        elif op == "add_index_column":
            self.value_label.setText("New column name")
            self.value_edit.setPlaceholderText("Index")
            self.value_edit.setText("Index")
            self.index_start_edit.setValidator(self._index_value_validator)
            self.index_start_edit.setPlaceholderText("0")
            self.index_start_edit.setText("0")
            self.index_increment_edit.setValidator(self._index_value_validator)
            self.index_increment_edit.setPlaceholderText("1")
            self.index_increment_edit.setText("1")
        elif op in {"remove_top_rows", "remove_bottom_rows", "keep_top_rows", "keep_bottom_rows"}:
            self.value_label.setText("Number of rows")
            self.value_edit.setPlaceholderText("0")
            self.value_edit.setValidator(self._row_count_validator)
            self.value_edit.setText("1")
        else:
            self.value_edit.setValidator(None)
            self.range_first_row_edit.setValidator(None)
            self.alternate_first_row_edit.setValidator(None)
            self.alternate_remove_count_edit.setValidator(None)
            self.alternate_keep_count_edit.setValidator(None)
            self.index_start_edit.setValidator(None)
            self.index_increment_edit.setValidator(None)
        replacement_visible = op == "replace_value"
        self.replacement_edit.setVisible(replacement_visible)
        self.replacement_label.setVisible(replacement_visible)
        delimiter_visible = op in {
            "extract_text_by_delimiter", "extract_text_between_delimiters", "split_column", "split_column_by_each_delimiter", "split_column_to_rows",
            "split_column_by_positions", "merge_columns"
        }
        self.delimiter_edit.setVisible(delimiter_visible)
        self.delimiter_label.setVisible(delimiter_visible)
        between_delimiters = op == "extract_text_between_delimiters"
        self.end_delimiter_edit.setVisible(between_delimiters)
        self.end_delimiter_label.setVisible(between_delimiters)
        self.end_occurrence_edit.setVisible(between_delimiters)
        self.end_occurrence_label.setVisible(between_delimiters)
        if between_delimiters:
            self.delimiter_label.setText("Start delimiter")
            self.delimiter_edit.setPlaceholderText("Start delimiter")
            self.end_delimiter_label.setText("End delimiter")
            self.end_delimiter_edit.setPlaceholderText("End delimiter")
            self.end_occurrence_label.setText("End occurrence (zero-based)")
            self.end_occurrence_edit.setPlaceholderText("0")
            self.end_occurrence_edit.setText("0")
            self.end_occurrence_edit.setValidator(self._row_count_validator)
        if op == "extract_text_between_delimiters":
            self.delimiter_edit.setToolTip("The opening delimiter to search for.")
            self.end_delimiter_edit.setToolTip(
                "The closing delimiter to find after the selected opening delimiter."
            )
        elif op == "extract_text_by_delimiter":
            self.delimiter_label.setText("Delimiter")
            self.delimiter_edit.setPlaceholderText("Delimiter text")
            self.delimiter_edit.setToolTip(
                "Extracts text before or after the selected zero-based delimiter occurrence. "
                "A missing occurrence reports the row and column."
            )
        elif op == "split_column":
            self.delimiter_label.setText("Delimiter (first match)")
            self.delimiter_edit.setToolTip(
                "Text after the first match stays in the second output; missing matches leave it blank."
            )
        elif op == "split_column_by_each_delimiter":
            self.delimiter_label.setText("Delimiter (each match, columns)")
            self.delimiter_edit.setPlaceholderText("Delimiter text")
            self.delimiter_edit.setText("")
            self.delimiter_edit.setToolTip(
                "Each match starts another output column. Rows with fewer parts receive blank values."
            )
        elif op == "split_column_to_rows":
            self.delimiter_label.setText("Delimiter (each match)")
            self.delimiter_edit.setToolTip(
                "Each delimited item becomes a row; the other column values repeat."
            )
        elif op == "split_column_by_positions":
            self.delimiter_label.setText("Split starts (zero-based positions)")
            self.delimiter_edit.setPlaceholderText("0, 6, 14")
            self.delimiter_edit.setText("0, 6")
            self.delimiter_edit.setToolTip(
                "Enter increasing character positions starting with 0. Each position starts an output segment."
            )
        elif op == "merge_columns":
            self.delimiter_label.setText("Separator")
            self.delimiter_edit.setPlaceholderText("Space, comma, or custom text")
            self.delimiter_edit.setText(" ")
            self.delimiter_edit.setToolTip(
                "The separator is inserted between selected values. Blank values remain in their positions."
            )
        reorder_columns = op == "reorder_columns"
        self.keep_columns_list.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove
            if reorder_columns
            else QAbstractItemView.DragDropMode.NoDragDrop
        )
        self.keep_columns_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.keep_columns_list.setMaximumHeight(220 if reorder_columns else 90)
        self.keep_columns_list.clear()
        for header in base_candidate.headers:
            item = QListWidgetItem(header)
            if reorder_columns:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            else:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if op in {"remove_duplicates", "keep_duplicates"}
                    else Qt.CheckState.Unchecked
                )
            self.keep_columns_list.addItem(item)
        unpivot_visible = op in {"unpivot_columns", "unpivot_other_columns"}
        self.attribute_name_label.setVisible(unpivot_visible)
        self.attribute_name_edit.setVisible(unpivot_visible)
        self.value_column_name_label.setVisible(unpivot_visible)
        self.value_column_name_edit.setVisible(unpivot_visible)
        if unpivot_visible:
            self.attribute_name_edit.setText("Attribute")
            self.value_column_name_edit.setText("Value")
        keep_columns_visible = op in {
            "keep_columns",
            "remove_duplicates",
            "keep_duplicates",
            "merge_columns",
            "fill_down",
            "fill_up",
            "group_by",
            "unpivot_columns",
            "unpivot_other_columns",
            "reorder_columns",
        }
        self.keep_columns_list.setVisible(keep_columns_visible)
        self.keep_columns_label.setVisible(keep_columns_visible)
        selection_labels = {
            "remove_duplicates": "Columns that define duplicates",
            "keep_duplicates": "Columns to check for duplicates",
            "merge_columns": "Columns to merge",
            "fill_down": "Columns to fill down",
            "fill_up": "Columns to fill up",
            "group_by": "Columns to group by",
            "unpivot_columns": "Columns to unpivot",
            "unpivot_other_columns": "Columns to keep",
            "keep_columns": "Columns to keep",
            "reorder_columns": "Column order",
        }
        self.keep_columns_label.setText(selection_labels.get(op, "Columns to keep"))
        selection_tooltips = {
            "remove_duplicates": (
                "Rows with identical exact, case-sensitive values in the selected columns are reduced to one; "
                "the first row is retained. All columns are selected by default."
            ),
            "keep_duplicates": (
                "Keeps every row when its exact, case-sensitive selected key values occur more than once. "
                "All columns are selected by default; output row order is preserved."
            ),
            "merge_columns": (
                "Selected columns are combined in displayed order, then replaced by the new text column."
            ),
            "fill_down": "Blank cells receive the preceding non-empty value; leading blanks remain blank.",
            "fill_up": "Blank cells receive the following non-empty value; trailing blanks remain blank.",
            "group_by": "Rows are grouped by the exact values in the selected columns.",
            "unpivot_columns": (
                "Each non-empty selected cell becomes an attribute/value row; other columns stay fixed."
            ),
            "unpivot_other_columns": (
                "Selected columns stay fixed; each non-empty cell in every other column is unpivoted."
            ),
            "keep_columns": "Selected columns remain in their current source order.",
            "reorder_columns": (
                "Drag columns to set their order. Unspecified columns keep their positions."
            ),
        }
        self.keep_columns_list.setToolTip(selection_tooltips.get(op, ""))
        self.group_aggregation_widget.setVisible(op == "group_by")
        if op == "group_by":
            selected_is_group_step = (
                0 <= selected_index < len(self._steps)
                and self._steps[selected_index]["op"] == "group_by"
            )
            self._group_aggregations = (
                deepcopy(self._steps[selected_index]["aggregations"])
                if selected_is_group_step
                else []
            )
            self.group_aggregate_column_combo.clear()
            self.group_aggregate_column_combo.addItems(base_candidate.headers)
            self._render_group_aggregations()
        column_visible = op not in {
            "remove_duplicates",
            "keep_duplicates",
            "remove_blank_rows",
            "remove_top_rows",
            "remove_bottom_rows",
            "keep_top_rows",
            "keep_bottom_rows",
            "keep_range_rows",
            "remove_alternate_rows",
            "add_index_column",
            "keep_columns",
            "reorder_columns",
            "promote_headers",
            "demote_headers",
            "transpose_table",
            "merge_columns",
            "fill_down",
            "fill_up",
            "group_by",
            "unpivot_columns",
            "unpivot_other_columns",
            "add_custom_column",
            "conditional_column",
            "sort_rows_by_columns",
        }
        self.column_combo.setVisible(column_visible)
        self.column_label.setVisible(column_visible)
        self.column_label.setText(
            "Column to pivot"
            if pivot_visible
            else "Filter column"
            if op == "filter_rows_advanced"
            else "Column"
        )
        if op in {"filter_rows", "filter_rows_advanced"}:
            self.option_combo.addItem("Equals", "equals")
            self.option_combo.addItem("Does not equal", "not_equals")
            self.option_combo.addItem("Is blank", "is_blank")
            self.option_combo.addItem("Is not blank", "is_not_blank")
            self.option_combo.addItem("Contains", "contains")
            self.option_combo.addItem("Does not contain", "does_not_contain")
            self.option_combo.addItem("Begins with", "begins_with")
            self.option_combo.addItem("Does not begin with", "does_not_begin_with")
            self.option_combo.addItem("Ends with", "ends_with")
            self.option_combo.addItem("Does not end with", "does_not_end_with")
            self.option_combo.addItem("Greater than", "greater_than")
            self.option_combo.addItem("Greater than or equal", "greater_than_or_equal")
            self.option_combo.addItem("Less than", "less_than")
            self.option_combo.addItem("Less than or equal", "less_than_or_equal")
            self.option_combo.setToolTip(
                "Text filters compare exact, case-sensitive values. Empty text criteria follow normal substring, prefix, or suffix matching. "
                "Numeric greater/less-than filters use finite invariant numbers and exclude blank cells. "
                "Blank means an empty string; whitespace-only values are not blank."
            )
        elif op == "sort_rows":
            self.option_combo.addItem("Ascending", "asc")
            self.option_combo.addItem("Descending", "desc")
        elif op == "extract_text_by_delimiter":
            self.option_combo.addItem("Before delimiter", "before")
            self.option_combo.addItem("After delimiter", "after")
        elif op == "convert_type":
            self.option_combo.addItem("Text", "text")
            self.option_combo.addItem("Whole number", "whole_number")
            self.option_combo.addItem("Decimal number", "decimal_number")
            self.option_combo.addItem("Boolean", "boolean")
            self.option_combo.addItem("Date (YYYY-MM-DD)", "date")
            self.option_combo.addItem("Date/time (ISO 8601)", "datetime")
            self.option_combo.addItem("Time (ISO 8601)", "time")
        elif op == "convert_type_using_locale":
            self.option_combo.addItem("Whole number", "whole_number")
            self.option_combo.addItem("Decimal number", "decimal_number")
            self.option_combo.addItem("Date", "date")
            self.option_combo.addItem("Date/time", "datetime")
            self.option_combo.addItem("Time", "time")
            self.option_combo.setToolTip(
                "Parses numbers and dates with a Babel/CLDR culture. Date parsing uses "
                "the Gregorian calendar; localized dates use numeric Babel/CLDR patterns; localized date-times require a date followed by a colon-form clock time; CLDR AM/PM markers are accepted."
            )
        elif op == "pivot_column":
            self.option_combo.addItem("Don't aggregate", "none")
            self.option_combo.addItem("Count (all)", "count_all")
            self.option_combo.addItem("Count (not blank)", "count_non_blank")
            self.option_combo.addItem("Minimum", "min")
            self.option_combo.addItem("Maximum", "max")
            self.option_combo.addItem("Median", "median")
            self.option_combo.addItem("Sum", "sum")
            self.option_combo.addItem("Average", "average")
            self.option_combo.setToolTip(
                "Default is Don't aggregate. Repeated row-key and pivot-value pairs then show an error; choose an aggregation to combine them."
            )
            self._update_pivot_value_choices()
        self.column_combo.setEnabled(self.column_combo.count() > 0)
        if op == "extract_text_between_delimiters":
            column_tooltip = (
                "Extracts text between two exact delimiters from a Text-typed column."
            )
        elif op == "extract_text_by_delimiter":
            column_tooltip = (
                "Extracts before or after a selected delimiter occurrence from a Text-typed column."
            )
        elif op == "split_column":
            column_tooltip = (
                "Replaces the selected column with <column>.1 and <column>.2."
            )
        elif op == "split_column_by_each_delimiter":
            column_tooltip = (
                "Replaces the selected column with numbered text columns, one per delimited part."
            )
        elif op == "split_column_to_rows":
            column_tooltip = (
                "Creates one row for each delimited item and repeats the other column values."
            )
        elif op == "pivot_column":
            column_tooltip = "Distinct values in this column become output column names."
        elif op == "clean_text":
            column_tooltip = (
                "Removes control characters throughout the value. The current column type must be Text."
            )
        elif op == "lowercase_text":
            column_tooltip = (
                "Converts values with locale-neutral Unicode lowercase rules. The current column type must be Text."
            )
        elif op == "uppercase_text":
            column_tooltip = (
                "Converts values with locale-neutral Unicode uppercase rules. The current column type must be Text."
            )
        elif op == "proper_case_text":
            column_tooltip = (
                "Capitalizes each word with locale-neutral Unicode title casing. The current column type must be Text."
            )
        elif op == "reverse_text":
            column_tooltip = (
                "Reverses the Unicode code points in each value. The current column type must be Text."
            )
        elif op == "duplicate_column":
            column_tooltip = "Appends a copy of this column, including its saved type."
        else:
            column_tooltip = ""
        self.column_combo.setToolTip(column_tooltip)
        self._configure_conditional_fields()
        self._configure_group_aggregate_fields()
        multi_sort_visible = op == "sort_rows_by_columns"
        self.sort_criteria_widget.setVisible(multi_sort_visible)
        if multi_sort_visible:
            selected_sort_step = (
                self._steps[selected_index]
                if 0 <= selected_index < len(self._steps)
                and self._steps[selected_index]["op"] == "sort_rows_by_columns"
                else None
            )
            sort_levels = (
                deepcopy(selected_sort_step["sorts"])
                if selected_sort_step is not None
                else ([{"column": base_candidate.headers[0], "direction": "asc"}]
                      if base_candidate.headers else [])
            )
            self._set_sort_levels(base_candidate.headers, sort_levels)
        else:
            self._set_sort_levels(base_candidate.headers, [])
        self._update_advanced_filter_clause_controls()

    def _set_sort_levels(
        self,
        headers: list[str],
        sorts: list[dict[str, str]],
    ) -> None:
        table = self.sort_criteria_table
        table.setRowCount(0)
        for sort in sorts:
            row = table.rowCount()
            table.insertRow(row)
            column_combo = QComboBox(table)
            column_combo.addItems(headers)
            if sort["column"] not in headers:
                column_combo.addItem(sort["column"])
            column_combo.setCurrentText(sort["column"])
            column_combo.setObjectName(f"sortColumnCombo{row}")
            direction_combo = QComboBox(table)
            direction_combo.addItem("Ascending", "asc")
            direction_combo.addItem("Descending", "desc")
            direction_combo.setCurrentIndex(
                max(0, direction_combo.findData(sort["direction"]))
            )
            direction_combo.setObjectName(f"sortDirectionCombo{row}")
            table.setCellWidget(row, 0, column_combo)
            table.setCellWidget(row, 1, direction_combo)
            table.setRowHeight(row, 30)
        table.setColumnWidth(0, 180)
        if table.rowCount():
            table.setCurrentCell(0, 0)
        self._update_sort_level_controls()

    def _read_sort_levels(self) -> list[dict[str, str]]:
        sorts = []
        for row in range(self.sort_criteria_table.rowCount()):
            column_combo = self.sort_criteria_table.cellWidget(row, 0)
            direction_combo = self.sort_criteria_table.cellWidget(row, 1)
            if not isinstance(column_combo, QComboBox) or not isinstance(
                direction_combo, QComboBox
            ):
                continue
            sorts.append({
                "column": column_combo.currentText(),
                "direction": str(direction_combo.currentData()),
            })
        return sorts

    def _add_sort_level(self) -> None:
        sorts = self._read_sort_levels()
        headers = [
            self.column_combo.itemText(index)
            for index in range(self.column_combo.count())
        ]
        used = {sort["column"] for sort in sorts}
        next_column = next((header for header in headers if header not in used), None)
        if next_column is None:
            self._show_error("Each column can appear only once in the sort priority list.")
            return
        sorts.append({"column": next_column, "direction": "asc"})
        self._set_sort_levels(headers, sorts)
        self.sort_criteria_table.setCurrentCell(len(sorts) - 1, 0)
        self._clear_error()

    def _remove_sort_level(self) -> None:
        sorts = self._read_sort_levels()
        row = self.sort_criteria_table.currentRow()
        if len(sorts) <= 1 or row < 0:
            return
        sorts.pop(row)
        headers = [
            self.column_combo.itemText(index)
            for index in range(self.column_combo.count())
        ]
        self._set_sort_levels(headers, sorts)
        self.sort_criteria_table.setCurrentCell(min(row, len(sorts) - 1), 0)

    def _move_sort_level(self, offset: int) -> None:
        sorts = self._read_sort_levels()
        row = self.sort_criteria_table.currentRow()
        target = row + offset
        if row < 0 or not 0 <= target < len(sorts):
            return
        sorts[row], sorts[target] = sorts[target], sorts[row]
        headers = [
            self.column_combo.itemText(index)
            for index in range(self.column_combo.count())
        ]
        self._set_sort_levels(headers, sorts)
        self.sort_criteria_table.setCurrentCell(target, 0)

    def _update_sort_level_controls(self) -> None:
        row = self.sort_criteria_table.currentRow()
        count = self.sort_criteria_table.rowCount()
        self.sort_add_button.setEnabled(count < self.column_combo.count())
        self.sort_remove_button.setEnabled(count > 1 and row >= 0)
        self.sort_up_button.setEnabled(row > 0)
        self.sort_down_button.setEnabled(0 <= row < count - 1)

    def _update_pivot_value_choices(self, *_args: Any) -> None:
        if str(self.operation_combo.currentData()) != "pivot_column":
            return
        attribute_column = self.column_combo.currentText()
        selected_value = self.pivot_value_column_combo.currentText()
        headers = [
            self.column_combo.itemText(index)
            for index in range(self.column_combo.count())
            if self.column_combo.itemText(index) != attribute_column
        ]
        self.pivot_value_column_combo.clear()
        self.pivot_value_column_combo.addItems(headers)
        selected_index = self.pivot_value_column_combo.findText(selected_value)
        if selected_index < 0 and headers:
            selected_index = 0
        if selected_index >= 0:
            self.pivot_value_column_combo.setCurrentIndex(selected_index)
        self.pivot_value_column_combo.setEnabled(bool(headers))

    def _update_filter_value_visibility(self, *_args: Any) -> None:
        if str(self.operation_combo.currentData()) not in {
            "filter_rows", "filter_rows_advanced"
        }:
            return
        needs_value = self.option_combo.currentData() not in FILTER_OPERATORS_WITHOUT_VALUE
        self.value_edit.setVisible(needs_value)
        self.value_label.setVisible(needs_value)

    def _select_step(self, index: int) -> None:
        if index < 0 or index >= len(self._steps):
            self._configure_editor()
            self._update_step_controls()
            return
        step = self._steps[index]
        operation_index = self.operation_combo.findData(step["op"])
        previous_block_state = self.operation_combo.blockSignals(True)
        self.operation_combo.setCurrentIndex(operation_index)
        self.operation_combo.blockSignals(previous_block_state)
        self._group_aggregations = (
            deepcopy(step["aggregations"]) if step["op"] == "group_by" else []
        )
        self._configure_editor()
        if "column" in step:
            column_index = self.column_combo.findText(step["column"])
            if column_index >= 0:
                self.column_combo.setCurrentIndex(column_index)
        if "operator" in step:
            option_index = self.option_combo.findData(step["operator"])
            if option_index >= 0:
                self.option_combo.setCurrentIndex(option_index)
            self.value_edit.setText(step["value"])
        elif "side" in step:
            option_index = self.option_combo.findData(step["side"])
            if option_index >= 0:
                self.option_combo.setCurrentIndex(option_index)
        elif "direction" in step:
            option_index = self.option_combo.findData(step["direction"])
            if option_index >= 0:
                self.option_combo.setCurrentIndex(option_index)
        elif "type" in step:
            type_name = "decimal_number" if step["type"] == "number" else step["type"]
            option_index = self.option_combo.findData(type_name)
            if option_index >= 0:
                self.option_combo.setCurrentIndex(option_index)
        if "culture" in step:
            self.culture_edit.setText(step["culture"])
        elif "aggregation" in step:
            option_index = self.option_combo.findData(step["aggregation"])
            if option_index >= 0:
                self.option_combo.setCurrentIndex(option_index)
        if "count" in step:
            self.value_edit.setText(str(step["count"]))
        if "occurrence" in step:
            self.value_edit.setText(str(step["occurrence"]))
        if "start_occurrence" in step:
            self.value_edit.setText(str(step["start_occurrence"]))
        if "end_occurrence" in step:
            self.end_occurrence_edit.setText(str(step["end_occurrence"]))
        if "first_row" in step:
            self.range_first_row_edit.setText(str(step["first_row"]))
        if step["op"] == "remove_alternate_rows":
            self.alternate_first_row_edit.setText(str(step["first_row_to_remove"]))
            self.alternate_remove_count_edit.setText(str(step["remove_count"]))
            self.alternate_keep_count_edit.setText(str(step["keep_count"]))
        if step["op"] == "add_index_column":
            self.index_start_edit.setText(str(step["start"]))
            self.index_increment_edit.setText(str(step["increment"]))
        if "attribute_column" in step:
            attribute_index = self.column_combo.findText(step["attribute_column"])
            if attribute_index >= 0:
                self.column_combo.setCurrentIndex(attribute_index)
        if "value_column" in step:
            value_index = self.pivot_value_column_combo.findText(step["value_column"])
            if value_index >= 0:
                self.pivot_value_column_combo.setCurrentIndex(value_index)
        if "new_name" in step:
            self.value_edit.setText(step["new_name"])
        if "name" in step:
            self.value_edit.setText(step["name"])
        if "expression" in step:
            self.custom_expression_edit.setPlainText(step["expression"])
        if step["op"] == "conditional_column":
            self._conditional_clauses = deepcopy(step["clauses"])
            self._set_combo_data(self.conditional_else_kind_combo, step["else_kind"])
            if step["else_kind"] == "column":
                self._set_combo_text(self.conditional_else_column_combo, step["else_value"])
            else:
                self.conditional_else_edit.setText(step["else_value"])
            self._render_conditional_clauses()
        elif step["op"] == "filter_rows_advanced":
            self._filter_clauses = deepcopy(step["clauses"])
            self._render_advanced_filter_clauses(select_row=0)
        if "replacement" in step:
            self.value_edit.setText(step["value"])
            self.replacement_edit.setText(step["replacement"])
        if "delimiter" in step:
            self.delimiter_edit.setText(step["delimiter"])
        if "start_delimiter" in step:
            self.delimiter_edit.setText(step["start_delimiter"])
        if "end_delimiter" in step:
            self.end_delimiter_edit.setText(step["end_delimiter"])
        if "positions" in step:
            self.delimiter_edit.setText(", ".join(str(position) for position in step["positions"]))
        if "separator" in step:
            self.delimiter_edit.setText(step["separator"])
        if "attribute_name" in step:
            self.attribute_name_edit.setText(step["attribute_name"])
        if "value_name" in step:
            self.value_column_name_edit.setText(step["value_name"])
        if step["op"] == "reorder_columns":
            items_by_name = {}
            while self.keep_columns_list.count():
                item = self.keep_columns_list.takeItem(0)
                items_by_name[item.text()] = item
            current_order = list(items_by_name)
            requested = [
                column for column in step["columns"] if column in items_by_name
            ]
            selected = set(requested)
            slots = [
                item_index for item_index, name in enumerate(current_order)
                if name in selected
            ]
            for item_index, column_name in zip(slots, requested):
                current_order[item_index] = column_name
            self.keep_columns_list.clear()
            for column_name in current_order:
                item = items_by_name.get(column_name)
                if item is not None:
                    self.keep_columns_list.addItem(item)
        elif "columns" in step:
            selected_columns = set(step["columns"])
            for item_index in range(self.keep_columns_list.count()):
                item = self.keep_columns_list.item(item_index)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if item.text() in selected_columns
                    else Qt.CheckState.Unchecked
                )
        self._render_group_aggregations()
        self._clear_error()
        self._update_step_controls()

    def _add_or_start_new_step(self) -> None:
        if self.step_list.currentRow() >= 0:
            self.step_list.setCurrentRow(-1)
            self.operation_combo.setCurrentIndex(0)
            self._configure_editor()
            self._clear_error()
            return
        self._add_step()

    def _create_step(self) -> dict[str, Any]:
        op = str(self.operation_combo.currentData())
        column = self.column_combo.currentText()
        if op in {"promote_headers", "demote_headers", "transpose_table"}:
            return {"op": op}
        if op == "rename_column":
            return {"op": op, "column": column, "new_name": self.value_edit.text().strip()}
        if op == "remove_column":
            return {"op": op, "column": column}
        if op == "filter_rows":
            operator = str(self.option_combo.currentData())
            return {
                "op": op, "column": column,
                "operator": operator,
                "value": "" if operator in FILTER_OPERATORS_WITHOUT_VALUE else self.value_edit.text(),
            }
        if op == "filter_rows_advanced":
            return {"op": op, "clauses": deepcopy(self._filter_clauses)}
        if op == "sort_rows":
            return {"op": op, "column": column, "direction": str(self.option_combo.currentData())}
        if op == "sort_rows_by_columns":
            return {"op": op, "sorts": self._read_sort_levels()}
        if op == "replace_value":
            return {
                "op": op,
                "column": column,
                "value": self.value_edit.text(),
                "replacement": self.replacement_edit.text(),
            }
        if op == "extract_text_by_delimiter":
            try:
                occurrence = int(self.value_edit.text().strip())
            except ValueError as exc:
                raise TransformationError(
                    "Enter a zero-based delimiter occurrence from 0 to 100,000."
                ) from exc
            return {
                "op": op,
                "column": column,
                "side": str(self.option_combo.currentData()),
                "delimiter": self.delimiter_edit.text(),
                "occurrence": occurrence,
            }
        if op == "extract_text_between_delimiters":
            try:
                start_occurrence = int(self.value_edit.text().strip())
                end_occurrence = int(self.end_occurrence_edit.text().strip())
            except ValueError as exc:
                raise TransformationError(
                    "Enter zero-based start and end occurrences from 0 to 100,000."
                ) from exc
            return {
                "op": op,
                "column": column,
                "start_delimiter": self.delimiter_edit.text(),
                "end_delimiter": self.end_delimiter_edit.text(),
                "start_occurrence": start_occurrence,
                "end_occurrence": end_occurrence,
            }
        if op in {"split_column", "split_column_by_each_delimiter", "split_column_to_rows"}:
            return {
                "op": op,
                "column": column,
                "delimiter": self.delimiter_edit.text(),
            }
        if op == "split_column_by_positions":
            raw_positions = [part.strip() for part in self.delimiter_edit.text().split(",")]
            if any(not part or not part.isascii() or not part.isdecimal() for part in raw_positions):
                raise TransformationError(
                    "Enter comma-separated zero-based positions starting with 0, such as 0, 6, 14."
                )
            try:
                positions = [int(part) for part in raw_positions]
            except ValueError as exc:
                raise TransformationError(
                    "Enter comma-separated whole-number split positions."
                ) from exc
            return {"op": op, "column": column, "positions": positions}
        if op == "merge_columns":
            columns = [
                self.keep_columns_list.item(index).text()
                for index in range(self.keep_columns_list.count())
                if self.keep_columns_list.item(index).checkState() == Qt.CheckState.Checked
            ]
            return {
                "op": op,
                "columns": columns,
                "separator": self.delimiter_edit.text(),
                "new_name": self.value_edit.text().strip(),
            }
        if op == "duplicate_column":
            return {
                "op": op,
                "column": column,
                "new_name": self.value_edit.text().strip(),
            }
        if op == "add_index_column":
            try:
                start = int(self.index_start_edit.text().strip())
                increment = int(self.index_increment_edit.text().strip())
            except ValueError as exc:
                raise TransformationError(
                    "Enter whole numbers for the starting index and increment."
                ) from exc
            return {
                "op": op,
                "new_name": self.value_edit.text().strip(),
                "start": start,
                "increment": increment,
            }
        if op in {"fill_down", "fill_up"}:
            columns = [
                self.keep_columns_list.item(index).text()
                for index in range(self.keep_columns_list.count())
                if self.keep_columns_list.item(index).checkState() == Qt.CheckState.Checked
            ]
            return {"op": op, "columns": columns}
        if op in {"trim_text", "clean_text", "lowercase_text", "uppercase_text", "proper_case_text", "reverse_text"}:
            return {"op": op, "column": column}
        if op in {"remove_duplicates", "keep_duplicates"}:
            columns = [
                self.keep_columns_list.item(index).text()
                for index in range(self.keep_columns_list.count())
                if self.keep_columns_list.item(index).checkState() == Qt.CheckState.Checked
            ]
            return {"op": op, "columns": columns}
        if op == "remove_blank_rows":
            return {"op": op}
        if op == "keep_range_rows":
            try:
                first_row = int(self.range_first_row_edit.text().strip())
                count = int(self.value_edit.text().strip())
            except ValueError as exc:
                raise TransformationError(
                    f"Enter a first row from 1 to {MAX_DATA_ROWS:,} and a row count from 0 to {MAX_DATA_ROWS:,}."
                ) from exc
            return {"op": op, "first_row": first_row, "count": count}
        if op == "remove_alternate_rows":
            try:
                first_row_to_remove = int(self.alternate_first_row_edit.text().strip())
                remove_count = int(self.alternate_remove_count_edit.text().strip())
                keep_count = int(self.alternate_keep_count_edit.text().strip())
            except ValueError as exc:
                raise TransformationError(
                    "Enter a first row to remove and whole-number remove/keep counts."
                ) from exc
            return {
                "op": op,
                "first_row_to_remove": first_row_to_remove,
                "remove_count": remove_count,
                "keep_count": keep_count,
            }
        if op in {"remove_top_rows", "remove_bottom_rows", "keep_top_rows", "keep_bottom_rows"}:
            raw_count = self.value_edit.text().strip()
            try:
                count = int(raw_count)
            except ValueError as exc:
                raise TransformationError(
                    f"Enter a whole number from 0 to {MAX_DATA_ROWS:,}."
                ) from exc
            return {"op": op, "count": count}
        if op == "keep_columns":
            columns = [
                self.keep_columns_list.item(index).text()
                for index in range(self.keep_columns_list.count())
                if self.keep_columns_list.item(index).checkState() == Qt.CheckState.Checked
            ]
            return {"op": op, "columns": columns}
        if op == "reorder_columns":
            columns = [
                self.keep_columns_list.item(index).text()
                for index in range(self.keep_columns_list.count())
            ]
            return {"op": op, "columns": columns}
        if op == "group_by":
            columns = [
                self.keep_columns_list.item(index).text()
                for index in range(self.keep_columns_list.count())
                if self.keep_columns_list.item(index).checkState() == Qt.CheckState.Checked
            ]
            return {
                "op": op,
                "columns": columns,
                "aggregations": deepcopy(self._group_aggregations),
            }
        if op in {"unpivot_columns", "unpivot_other_columns"}:
            columns = [
                self.keep_columns_list.item(index).text()
                for index in range(self.keep_columns_list.count())
                if self.keep_columns_list.item(index).checkState() == Qt.CheckState.Checked
            ]
            return {
                "op": op,
                "columns": columns,
                "attribute_name": self.attribute_name_edit.text().strip(),
                "value_name": self.value_column_name_edit.text().strip(),
            }
        if op == "pivot_column":
            return {
                "op": op,
                "attribute_column": self.column_combo.currentText(),
                "value_column": self.pivot_value_column_combo.currentText(),
                "aggregation": str(self.option_combo.currentData()),
            }
        if op == "add_custom_column":
            return {
                "op": op,
                "name": self.value_edit.text().strip(),
                "expression": self.custom_expression_edit.toPlainText().strip(),
            }
        if op == "conditional_column":
            return {
                "op": op,
                "name": self.value_edit.text().strip(),
                "clauses": deepcopy(self._conditional_clauses),
                "else_value": (
                    self.conditional_else_column_combo.currentText()
                    if self.conditional_else_kind_combo.currentData() == "column"
                    else self.conditional_else_edit.text()
                ),
                "else_kind": str(self.conditional_else_kind_combo.currentData()),
            }
        if op == "convert_type_using_locale":
            return {
                "op": op,
                "column": column,
                "type": str(self.option_combo.currentData()),
                "culture": self.culture_edit.text(),
            }
        return {"op": op, "column": column, "type": str(self.option_combo.currentData())}

    def _configure_conditional_fields(self, *_args: Any) -> None:
        test_uses_column = self.conditional_test_value_kind_combo.currentData() == "column"
        output_uses_column = self.conditional_output_kind_combo.currentData() == "column"
        else_uses_column = self.conditional_else_kind_combo.currentData() == "column"
        self.conditional_test_value_edit.setVisible(not test_uses_column)
        self.conditional_test_value_column_combo.setVisible(test_uses_column)
        self.conditional_output_edit.setVisible(not output_uses_column)
        self.conditional_output_column_combo.setVisible(output_uses_column)
        self.conditional_else_edit.setVisible(not else_uses_column)
        self.conditional_else_column_combo.setVisible(else_uses_column)
        self._update_conditional_clause_controls()

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _set_combo_text(combo: QComboBox, value: str) -> None:
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _current_conditional_clause(self) -> dict[str, str]:
        test_value_kind = str(self.conditional_test_value_kind_combo.currentData())
        output_kind = str(self.conditional_output_kind_combo.currentData())
        return {
            "column": self.conditional_test_column_combo.currentText(),
            "operator": str(self.conditional_operator_combo.currentData()),
            "test_value": (
                self.conditional_test_value_column_combo.currentText()
                if test_value_kind == "column"
                else self.conditional_test_value_edit.text()
            ),
            "test_value_kind": test_value_kind,
            "output": (
                self.conditional_output_column_combo.currentText()
                if output_kind == "column"
                else self.conditional_output_edit.text()
            ),
            "output_kind": output_kind,
        }

    def _add_conditional_clause(self) -> None:
        if len(self._conditional_clauses) >= MAX_CONDITIONAL_CLAUSES:
            self._show_error(
                f"A conditional column may contain at most {MAX_CONDITIONAL_CLAUSES} clauses."
            )
            return
        clause = self._current_conditional_clause()
        if not clause["column"]:
            self._show_error("Choose a column for the conditional test.")
            return
        if clause["test_value_kind"] == "column" and not clause["test_value"]:
            self._show_error("Choose a comparison column.")
            return
        if clause["output_kind"] == "column" and not clause["output"]:
            self._show_error("Choose an output column.")
            return
        self._conditional_clauses.append(clause)
        self._render_conditional_clauses(select_row=len(self._conditional_clauses) - 1)
        self._clear_error()

    def _update_conditional_clause(self) -> None:
        index = self.conditional_clause_list.currentRow()
        if not 0 <= index < len(self._conditional_clauses):
            return
        clause = self._current_conditional_clause()
        if not clause["column"]:
            self._show_error("Choose a column for the conditional test.")
            return
        if clause["test_value_kind"] == "column" and not clause["test_value"]:
            self._show_error("Choose a comparison column.")
            return
        if clause["output_kind"] == "column" and not clause["output"]:
            self._show_error("Choose an output column.")
            return
        self._conditional_clauses[index] = clause
        self._render_conditional_clauses(select_row=index)
        self._clear_error()

    def _remove_conditional_clause(self) -> None:
        index = self.conditional_clause_list.currentRow()
        if not 0 <= index < len(self._conditional_clauses):
            return
        self._conditional_clauses.pop(index)
        next_index = min(index, len(self._conditional_clauses) - 1)
        self._render_conditional_clauses(select_row=next_index)
        self._clear_error()

    def _move_conditional_clause(self, direction: int) -> None:
        index = self.conditional_clause_list.currentRow()
        target = index + direction
        if not 0 <= index < len(self._conditional_clauses):
            return
        if not 0 <= target < len(self._conditional_clauses):
            return
        self._conditional_clauses[index], self._conditional_clauses[target] = (
            self._conditional_clauses[target],
            self._conditional_clauses[index],
        )
        self._render_conditional_clauses(select_row=target)
        self._clear_error()

    def _render_conditional_clauses(self, *, select_row: int = -1) -> None:
        previous_block_state = self.conditional_clause_list.blockSignals(True)
        self.conditional_clause_list.clear()
        for clause in self._conditional_clauses:
            operator_index = self.conditional_operator_combo.findData(clause["operator"])
            operator_label = (
                self.conditional_operator_combo.itemText(operator_index)
                if operator_index >= 0
                else clause["operator"].replace("_", " ")
            )
            test_value = (
                f"column {clause['test_value']}"
                if clause["test_value_kind"] == "column"
                else repr(clause["test_value"])
            )
            output = (
                f"column {clause['output']}"
                if clause["output_kind"] == "column"
                else repr(clause["output"])
            )
            self.conditional_clause_list.addItem(
                f"If {clause['column']} {operator_label} {test_value} → {output}"
            )
        if 0 <= select_row < self.conditional_clause_list.count():
            self.conditional_clause_list.setCurrentRow(select_row)
        else:
            self.conditional_clause_list.setCurrentRow(-1)
        self.conditional_clause_list.blockSignals(previous_block_state)
        if 0 <= select_row < len(self._conditional_clauses):
            self._load_conditional_clause(select_row)
        self._update_conditional_clause_controls()

    def _select_conditional_clause(self, index: int) -> None:
        if 0 <= index < len(self._conditional_clauses):
            self._load_conditional_clause(index)
        self._update_conditional_clause_controls()

    def _load_conditional_clause(self, index: int) -> None:
        clause = self._conditional_clauses[index]
        self._set_combo_text(self.conditional_test_column_combo, clause["column"])
        self._set_combo_data(self.conditional_operator_combo, clause["operator"])
        self._set_combo_data(self.conditional_test_value_kind_combo, clause["test_value_kind"])
        if clause["test_value_kind"] == "column":
            self._set_combo_text(self.conditional_test_value_column_combo, clause["test_value"])
            self.conditional_test_value_edit.clear()
        else:
            self.conditional_test_value_edit.setText(clause["test_value"])
        self._set_combo_data(self.conditional_output_kind_combo, clause["output_kind"])
        if clause["output_kind"] == "column":
            self._set_combo_text(self.conditional_output_column_combo, clause["output"])
            self.conditional_output_edit.clear()
        else:
            self.conditional_output_edit.setText(clause["output"])
        self._configure_conditional_fields()

    def _update_conditional_clause_controls(self) -> None:
        index = self.conditional_clause_list.currentRow()
        selected = 0 <= index < len(self._conditional_clauses)
        self.update_conditional_clause_button.setEnabled(selected)
        self.remove_conditional_clause_button.setEnabled(selected)
        self.up_conditional_clause_button.setEnabled(selected and index > 0)
        self.down_conditional_clause_button.setEnabled(
            selected and index < len(self._conditional_clauses) - 1
        )

    def _current_advanced_filter_clause(self, *, index: int | None = None) -> dict[str, str]:
        operator = str(self.option_combo.currentData())
        join = "and" if index == 0 or not self._filter_clauses else str(
            self.advanced_filter_join_combo.currentData()
        )
        return {
            "column": self.column_combo.currentText(),
            "operator": operator,
            "value": "" if operator in FILTER_OPERATORS_WITHOUT_VALUE else self.value_edit.text(),
            "join": join,
        }

    def _add_advanced_filter_clause(self) -> None:
        if len(self._filter_clauses) >= MAX_FILTER_CLAUSES:
            self._show_error(
                f"An advanced filter may contain at most {MAX_FILTER_CLAUSES} clauses."
            )
            return
        clause = self._current_advanced_filter_clause()
        if not clause["column"]:
            self._show_error("Choose a column for this filter clause.")
            return
        if not clause["operator"]:
            self._show_error("Choose an operator for this filter clause.")
            return
        if not self._filter_clauses:
            clause["join"] = "and"
        self._filter_clauses.append(clause)
        self._render_advanced_filter_clauses(select_row=len(self._filter_clauses) - 1)
        self._clear_error()

    def _update_advanced_filter_clause(self) -> None:
        index = self.advanced_filter_clause_list.currentRow()
        if not 0 <= index < len(self._filter_clauses):
            return
        clause = self._current_advanced_filter_clause(index=index)
        if not clause["column"]:
            self._show_error("Choose a column for this filter clause.")
            return
        if not clause["operator"]:
            self._show_error("Choose an operator for this filter clause.")
            return
        self._filter_clauses[index] = clause
        self._render_advanced_filter_clauses(select_row=index)
        self._clear_error()

    def _remove_advanced_filter_clause(self) -> None:
        index = self.advanced_filter_clause_list.currentRow()
        if not 0 <= index < len(self._filter_clauses):
            return
        self._filter_clauses.pop(index)
        if self._filter_clauses:
            self._filter_clauses[0]["join"] = "and"
        self._render_advanced_filter_clauses(
            select_row=min(index, len(self._filter_clauses) - 1)
        )
        self._clear_error()

    def _render_advanced_filter_clauses(self, *, select_row: int = -1) -> None:
        previous_block_state = self.advanced_filter_clause_list.blockSignals(True)
        self.advanced_filter_clause_list.clear()
        for index, clause in enumerate(self._filter_clauses):
            operator_index = self.option_combo.findData(clause["operator"])
            operator_label = (
                self.option_combo.itemText(operator_index)
                if operator_index >= 0
                else clause["operator"].replace("_", " ")
            )
            connector = "FIRST" if index == 0 else clause["join"].upper()
            value_text = (
                ""
                if clause["operator"] in FILTER_OPERATORS_WITHOUT_VALUE
                else f" {clause['value']!r}"
            )
            self.advanced_filter_clause_list.addItem(
                f"{connector}: {clause['column']} {operator_label}{value_text}"
            )
        if 0 <= select_row < self.advanced_filter_clause_list.count():
            self.advanced_filter_clause_list.setCurrentRow(select_row)
        else:
            self.advanced_filter_clause_list.setCurrentRow(-1)
        self.advanced_filter_clause_list.blockSignals(previous_block_state)
        if 0 <= select_row < len(self._filter_clauses):
            self._load_advanced_filter_clause(select_row)
        self._update_advanced_filter_clause_controls()

    def _select_advanced_filter_clause(self, index: int) -> None:
        if 0 <= index < len(self._filter_clauses):
            self._load_advanced_filter_clause(index)
        self._update_advanced_filter_clause_controls()

    def _load_advanced_filter_clause(self, index: int) -> None:
        clause = self._filter_clauses[index]
        self._set_combo_text(self.column_combo, clause["column"])
        self._set_combo_data(self.option_combo, clause["operator"])
        self.value_edit.setText(clause["value"])
        self._set_combo_data(
            self.advanced_filter_join_combo,
            "and" if index == 0 else clause["join"],
        )

    def _update_advanced_filter_clause_controls(self) -> None:
        selected = 0 <= self.advanced_filter_clause_list.currentRow() < len(
            self._filter_clauses
        )
        self.add_advanced_filter_clause_button.setEnabled(
            len(self._filter_clauses) < MAX_FILTER_CLAUSES
        )
        self.update_advanced_filter_clause_button.setEnabled(selected)
        self.remove_advanced_filter_clause_button.setEnabled(selected)

    def _configure_group_aggregate_fields(self, *_args: Any) -> None:
        operation = str(self.group_aggregate_operation_combo.currentData())
        needs_column = operation not in {"count_rows", "count_distinct_rows"}
        self.group_aggregate_column_combo.setVisible(needs_column)
        self._update_group_aggregation_controls()

    def _update_group_aggregation_controls(self) -> None:
        self.remove_group_aggregation_button.setEnabled(
            self.group_aggregations_list.currentRow() >= 0
        )

    def _render_group_aggregations(self) -> None:
        self.group_aggregations_list.clear()
        for aggregate in self._group_aggregations:
            operation = self.group_aggregate_operation_combo.findData(
                aggregate["operation"]
            )
            label = (
                self.group_aggregate_operation_combo.itemText(operation)
                if operation >= 0
                else aggregate["operation"].replace("_", " ").title()
            )
            detail = label
            if "column" in aggregate:
                detail += f" of {aggregate['column']}"
            detail += f" → {aggregate['new_name']}"
            self.group_aggregations_list.addItem(QListWidgetItem(detail))
        self._update_group_aggregation_controls()

    def _add_group_aggregation(self) -> None:
        group_columns = [
            self.keep_columns_list.item(index).text()
            for index in range(self.keep_columns_list.count())
            if self.keep_columns_list.item(index).checkState() == Qt.CheckState.Checked
        ]
        if not group_columns:
            self._show_error("Select one or more columns to group by first.")
            return
        operation = str(self.group_aggregate_operation_combo.currentData())
        aggregate: dict[str, str] = {"operation": operation}
        if operation not in {"count_rows", "count_distinct_rows"}:
            column = self.group_aggregate_column_combo.currentText()
            if not column:
                self._show_error("Select a source column for this aggregation.")
                return
            aggregate["column"] = column
        name = self.group_aggregate_name_edit.text().strip()
        if not name:
            label = self.group_aggregate_operation_combo.currentText()
            name = label if "column" not in aggregate else f"{label} of {aggregate['column']}"
        aggregate["new_name"] = name
        next_aggregations = [*self._group_aggregations, aggregate]
        draft_step = {
            "op": "group_by",
            "columns": group_columns,
            "aggregations": next_aggregations,
        }
        selected_index = self.step_list.currentRow()
        next_steps = deepcopy(self._steps)
        try:
            if 0 <= selected_index < len(next_steps):
                next_steps[selected_index] = draft_step
            else:
                next_steps.append(draft_step)
            next_steps = validate_steps(next_steps)
            transformed = apply_transformations(self._source_candidate, next_steps)
        except TransformationError as exc:
            self._show_error(str(exc))
            return
        self._group_aggregations = next_aggregations
        if 0 <= selected_index < len(self._steps):
            self._steps = next_steps
            self._preview_candidate = transformed
            self._render_steps()
            self._refresh_preview()
            self.step_list.setCurrentRow(selected_index)
        else:
            self._render_group_aggregations()
        self.group_aggregate_name_edit.clear()
        self._clear_error()

    def _remove_group_aggregation(self) -> None:
        selected_aggregate = self.group_aggregations_list.currentRow()
        if selected_aggregate < 0:
            return
        next_aggregations = deepcopy(self._group_aggregations)
        next_aggregations.pop(selected_aggregate)
        selected_step = self.step_list.currentRow()
        if 0 <= selected_step < len(self._steps):
            next_steps = deepcopy(self._steps)
            next_steps[selected_step]["aggregations"] = next_aggregations
            try:
                transformed = apply_transformations(self._source_candidate, next_steps)
            except TransformationError as exc:
                self._show_error(str(exc))
                return
            self._steps = next_steps
            self._preview_candidate = transformed
            self._render_steps()
            self._refresh_preview()
            self.step_list.setCurrentRow(selected_step)
        else:
            self._group_aggregations = next_aggregations
            self._render_group_aggregations()
        self._clear_error()

    def _add_step(self) -> None:
        try:
            next_steps = validate_steps([*self._steps, self._create_step()])
            transformed = apply_transformations(self._source_candidate, next_steps)
        except TransformationError as exc:
            self._show_error(str(exc))
            return
        self._steps = next_steps
        self._preview_candidate = transformed
        self._render_steps()
        self._refresh_preview()
        self._configure_editor()
        self.step_list.setCurrentRow(self.step_list.count() - 1)
        self._clear_error()

    def _remove_step(self) -> None:
        index = self.step_list.currentRow()
        if index < 0:
            return
        removed_step = self._steps.pop(index)
        try:
            transformed = apply_transformations(self._source_candidate, self._steps)
        except TransformationError as exc:
            self._steps.insert(index, removed_step)
            self._show_error(str(exc))
            return
        self._preview_candidate = transformed
        self._render_steps()
        self._refresh_preview()
        self._configure_editor()
        self.step_list.setCurrentRow(min(index, self.step_list.count() - 1))

    def _move_step(self, offset: int) -> None:
        index = self.step_list.currentRow()
        target = index + offset
        if index < 0 or target < 0 or target >= len(self._steps):
            return
        self._steps[index], self._steps[target] = self._steps[target], self._steps[index]
        try:
            self._preview_candidate = apply_transformations(self._source_candidate, self._steps)
        except TransformationError as exc:
            self._steps[index], self._steps[target] = self._steps[target], self._steps[index]
            self._show_error(str(exc))
            return
        self._render_steps()
        self._refresh_preview()
        self.step_list.setCurrentRow(target)

    def _update_selected_step(self) -> None:
        index = self.step_list.currentRow()
        if index < 0 or index >= len(self._steps):
            return
        next_steps = deepcopy(self._steps)
        try:
            next_steps[index] = self._create_step()
            next_steps = validate_steps(next_steps)
            transformed = apply_transformations(self._source_candidate, next_steps)
        except TransformationError as exc:
            self._show_error(str(exc))
            return
        self._steps = next_steps
        self._preview_candidate = transformed
        self._render_steps()
        self._refresh_preview()
        self.step_list.setCurrentRow(index)
        self._clear_error()

    def _render_steps(self) -> None:
        self.step_list.clear()
        for step in self._steps:
            op = (
                "Keep Range of Rows"
                if step["op"] == "keep_range_rows"
                else "Remove Alternate Rows"
                if step["op"] == "remove_alternate_rows"
                else f"Extract Text {step['side'].title()} Delimiter"
                if step["op"] == "extract_text_by_delimiter"
                else "Extract Text Between Delimiters"
                if step["op"] == "extract_text_between_delimiters"
                else "Capitalize Each Word"
                if step["op"] == "proper_case_text"
                else "Reverse Text"
                if step["op"] == "reverse_text"
                else "Sort Rows by Multiple Columns"
                if step["op"] == "sort_rows_by_columns"
                else "Advanced Filter Rows"
                if step["op"] == "filter_rows_advanced"
                else "Use First Row as Headers"
                if step["op"] == "promote_headers"
                else "Use Headers as First Row"
                if step["op"] == "demote_headers"
                else step["op"].replace("_", " ").title()
            )
            detail = step.get("column", "")
            if "culture" in step:
                op = "Change Type Using Locale"
            if step["op"] == "promote_headers":
                detail = "first data row becomes column names"
            elif step["op"] == "demote_headers":
                detail = "column names become the first data row"
            elif step["op"] == "transpose_table":
                detail = "rows ↔ columns; original column names are dropped"
            elif step["op"] == "sort_rows_by_columns":
                detail = ", ".join(
                    f"{sort['column']} {sort['direction']}" for sort in step["sorts"]
                )
            elif step["op"] == "split_column_by_positions":
                detail = (
                    f"{step['column']} at {', '.join(map(str, step['positions']))} (zero-based)"
                )
            elif step["op"] == "add_index_column":
                detail = (
                    f"start {step['start']}, increment {step['increment']} "
                    f"→ {step['new_name']}"
                )
            elif step["op"] == "merge_columns":
                detail = (
                    f"{', '.join(step['columns'])} {step['separator']!r} "
                    f"→ {step['new_name']}"
                )
            elif step["op"] == "extract_text_by_delimiter":
                detail = (
                    f"{step['column']} occurrence {step['occurrence']} "
                    f"{step['delimiter']!r}"
                )
            elif step["op"] == "extract_text_between_delimiters":
                detail = (
                    f"{step['column']} {step['start_delimiter']!r} "
                    f"({step['start_occurrence']}) … {step['end_delimiter']!r} "
                    f"({step['end_occurrence']})"
                )
            elif step["op"] == "reorder_columns":
                detail = " → ".join(step["columns"])
                if len(detail) > 80:
                    detail = detail[:77] + "…"
            elif "new_name" in step:
                detail += f" → {step['new_name']}"
            elif "replacement" in step:
                detail += f" {step['value']!r} → {step['replacement']!r}"
            elif "delimiter" in step:
                split_mode = {
                    "split_column": "first",
                    "split_column_by_each_delimiter": "each into columns",
                    "split_column_to_rows": "each into rows",
                }.get(step["op"], "")
                detail += f" at {split_mode} {step['delimiter']!r}"
            elif (
                step["op"] == "filter_rows"
                and step["operator"] in FILTER_OPERATORS_WITHOUT_VALUE
            ):
                detail += (
                    " is blank"
                    if step["operator"] == "is_blank"
                    else " is not blank"
                )
            elif "value" in step:
                detail += f" {step['operator']} {step['value']}"
            elif "direction" in step:
                detail += f" {step['direction']}"
            elif "type" in step:
                detail += f" → {step['type']}"
                if "culture" in step:
                    detail += f" ({step['culture']})"
            elif step["op"] == "add_custom_column":
                expression = step["expression"].replace("\n", " ").strip()
                if len(expression) > 52:
                    expression = expression[:49] + "…"
                detail = f"{expression} → {step['name']}"
            elif step["op"] == "conditional_column":
                detail = f"{len(step['clauses'])} clauses → {step['name']}"
            elif step["op"] == "filter_rows_advanced":
                detail = f"{len(step['clauses'])} clauses; AND before OR"
            elif step["op"] in {"fill_down", "fill_up"}:
                detail = ", ".join(step["columns"])
            elif step["op"] == "pivot_column":
                detail = (
                    f"{step['attribute_column']} → {step['value_column']}; "
                    f"{step['aggregation'].replace('_', ' ')}"
                )
            elif "columns" in step:
                if step["op"] == "group_by":
                    keys = ", ".join(step["columns"])
                    aggregates = "; ".join(
                        f"{aggregate['operation'].replace('_', ' ')}"
                        + (f"({aggregate['column']})" if "column" in aggregate else "")
                        + f" → {aggregate['new_name']}"
                        for aggregate in step["aggregations"]
                    )
                    detail = f"{keys}; {aggregates}"
                elif step["op"] in {"unpivot_columns", "unpivot_other_columns"}:
                    mode = (
                        "unpivot"
                        if step["op"] == "unpivot_columns"
                        else "keep; unpivot other"
                    )
                    detail = (
                        f"{mode} {', '.join(step['columns'])}; "
                        f"{step['attribute_name']} / {step['value_name']}"
                    )
                elif step["op"] in {"remove_duplicates", "keep_duplicates"}:
                    detail = f"keys: {', '.join(step['columns'])}"
                else:
                    detail = ", ".join(step["columns"])
            elif step["op"] == "remove_duplicates":
                detail = "entire rows"
            elif step["op"] == "remove_blank_rows":
                detail = "all fields empty"
            elif step["op"] == "keep_range_rows":
                detail = f"from row {step['first_row']}, {step['count']} rows"
            elif step["op"] == "remove_alternate_rows":
                detail = (
                    f"from row {step['first_row_to_remove']}; remove "
                    f"{step['remove_count']}, keep {step['keep_count']}"
                )
            elif step["op"] in {"remove_top_rows", "remove_bottom_rows", "keep_top_rows", "keep_bottom_rows"}:
                detail = str(step["count"])
            self.step_list.addItem(QListWidgetItem(f"{op}: {detail}"))
        self._update_step_controls()

    def _refresh_preview(self) -> None:
        model = self.preview.model()
        assert isinstance(model, ImportPreviewTableModel)
        model.set_candidate(self._preview_candidate)
        self.count_label.setText(
            f"{len(self._preview_candidate.headers):,} columns · "
            f"{self._preview_candidate.row_count:,} rows after steps"
        )

    def _update_step_controls(self) -> None:
        index = self.step_list.currentRow()
        valid = 0 <= index < len(self._steps)
        self.remove_button.setEnabled(valid)
        self.up_button.setEnabled(valid and index > 0)
        self.down_button.setEnabled(valid and index < len(self._steps) - 1)
        self.add_button.setText("New step" if valid else "Add step")
        self.update_button.setEnabled(valid)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _clear_error(self) -> None:
        self.error_label.clear()
        self.error_label.setVisible(False)

    def _accept_candidate(self) -> None:
        try:
            steps = validate_steps(self._steps)
            candidate = apply_transformations(self._source_candidate, steps)
        except TransformationError as exc:
            QMessageBox.warning(self, "Could not apply transformations", str(exc))
            return
        self._accepted_candidate = candidate
        self._accepted_steps = steps
        super().accept()

    def reject(self) -> None:
        self._accepted_candidate = None
        self._accepted_steps = None
        super().reject()
