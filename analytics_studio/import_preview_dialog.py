"""Native preview and confirmation dialog for local file imports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from analytics_studio.file_import import (
    ImportCandidate,
    default_options,
    kind_for_path,
    list_excel_sheets,
    parse_file,
)


PREVIEW_ROW_LIMIT = 100
_DELIMITERS = ((",", "Comma"), (";", "Semicolon"), ("\t", "Tab"), ("|", "Pipe"))
_ENCODINGS = (
    ("utf-8-sig", "UTF-8 (BOM aware)"),
    ("utf-8", "UTF-8"),
    ("utf-16", "UTF-16"),
    ("cp1252", "Windows-1252"),
)


class ImportPreviewTableModel(QAbstractTableModel):
    """Small read-only table model containing at most 100 preview records."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._headers: list[str] = []
        self._rows: list[dict[str, Any]] = []

    def set_candidate(self, candidate: ImportCandidate | None) -> None:
        self.beginResetModel()
        if candidate is None:
            self._headers = []
            self._rows = []
        else:
            self._headers = list(candidate.headers)
            self._rows = list(candidate.rows[:PREVIEW_ROW_LIMIT])
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._headers)

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        if index.row() >= len(self._rows) or index.column() >= len(self._headers):
            return None
        value = self._rows[index.row()].get(self._headers[index.column()], "")
        return "" if value is None else str(value)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self._headers):
            return self._headers[section]
        if orientation == Qt.Orientation.Vertical:
            return section + 1
        return None


class FileImportPreviewDialog(QDialog):
    """Let the user choose file options, inspect a preview, then commit it.

    ``candidate`` is intentionally available only after the Import data button
    accepts the dialog. Parsing and option changes only update the preview.
    """

    def __init__(
        self,
        path: Path,
        replacing: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = Path(path).expanduser().resolve()
        self.replacing = replacing
        self._kind: str | None = None
        self._base_options: dict[str, Any] = {}
        self._preview_candidate: ImportCandidate | None = None
        self._accepted_candidate: ImportCandidate | None = None
        self._last_error = ""

        self.setWindowTitle("Import data")
        self.setMinimumSize(720, 470)
        self.resize(940, 620)

        self._build_ui()
        self._initialize_file()

    @property
    def candidate(self) -> ImportCandidate | None:
        """Return the parsed candidate only after the dialog is accepted."""
        if self.result() == QDialog.DialogCode.Accepted:
            return self._accepted_candidate
        return None

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        heading = QLabel("Review file data")
        heading.setStyleSheet("font-size: 19px; font-weight: 600;")
        layout.addWidget(heading)

        self.file_label = QLabel(str(self.path))
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.file_label.setWordWrap(True)
        self.file_label.setStyleSheet("color: #526477;")
        layout.addWidget(self.file_label)

        self.replacement_label = QLabel(
            "Importing will replace the data source currently loaded in this report."
        )
        self.replacement_label.setWordWrap(True)
        self.replacement_label.setStyleSheet(
            "padding: 8px 10px; color: #6a4d00; background: #fff5d6;"
            "border: 1px solid #e8d391; border-radius: 3px;"
        )
        self.replacement_label.setVisible(self.replacing)
        layout.addWidget(self.replacement_label)

        self.options_group = QGroupBox("File options")
        self.options_form = QFormLayout(self.options_group)
        self.options_form.setContentsMargins(12, 10, 12, 10)
        self.options_form.setHorizontalSpacing(18)
        self.options_form.setVerticalSpacing(7)
        layout.addWidget(self.options_group)

        self.format_note = QLabel()
        self.format_note.setWordWrap(True)
        self.format_note.setStyleSheet("color: #526477; padding: 2px 0;")
        layout.addWidget(self.format_note)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c; padding: 2px 0;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.notice_label = QLabel()
        self.notice_label.setWordWrap(True)
        self.notice_label.setStyleSheet("color: #526477; padding: 2px 0;")
        self.notice_label.setVisible(False)
        layout.addWidget(self.notice_label)

        self.table = QTableView()
        self.table.setModel(ImportPreviewTableModel(self.table))
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setDefaultSectionSize(145)
        self.table.verticalHeader().setDefaultSectionSize(25)
        layout.addWidget(self.table, 1)

        self.count_label = QLabel("Choose a supported file to see a preview.")
        self.count_label.setStyleSheet("color: #526477;")
        layout.addWidget(self.count_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        self.import_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.import_button.setText("Import data")
        self.import_button.setEnabled(False)
        self.buttons.accepted.connect(self._accept_candidate)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _initialize_file(self) -> None:
        try:
            self._kind = kind_for_path(self.path)
            self._base_options = dict(default_options(self._kind))
        except Exception as exc:
            self._show_error(str(exc) or "This file cannot be imported.")
            self.count_label.setText("No preview is available.")
            return

        if self._kind == "csv":
            self._build_csv_options()
        elif self._kind == "excel":
            self._build_excel_options()
        elif self._kind == "json":
            self.format_note.setText(
                "JSON import expects a top-level array of flat records. "
                "Nested objects and arrays are not supported."
            )
        elif self._kind == "xml":
            self.format_note.setText(
                "XML import expects one repeated group of records with scalar fields. "
                "Nested fields and attributes are not supported."
            )
        self._refresh_preview()

    def _build_csv_options(self) -> None:
        delimiter = self._base_options.get("delimiter", ",")
        self.delimiter_combo = QComboBox()
        for value, label in _DELIMITERS:
            self.delimiter_combo.addItem(label, value)
        if delimiter not in [value for value, _ in _DELIMITERS]:
            self.delimiter_combo.addItem(f"Custom ({delimiter})", delimiter)
        index = self.delimiter_combo.findData(delimiter)
        self.delimiter_combo.setCurrentIndex(max(0, index))
        self.options_form.addRow("Delimiter", self.delimiter_combo)
        self.delimiter_combo.currentIndexChanged.connect(self._refresh_preview)

        encoding = self._base_options.get("encoding", "utf-8-sig")
        self.encoding_combo = QComboBox()
        for value, label in _ENCODINGS:
            self.encoding_combo.addItem(label, value)
        if encoding not in [value for value, _ in _ENCODINGS]:
            self.encoding_combo.addItem(encoding, encoding)
        index = self.encoding_combo.findData(encoding)
        self.encoding_combo.setCurrentIndex(max(0, index))
        self.options_form.addRow("Encoding", self.encoding_combo)
        self.encoding_combo.currentIndexChanged.connect(self._refresh_preview)

        self.header_checkbox = QCheckBox("First row contains column names")
        self.header_checkbox.setChecked(bool(self._base_options.get("has_header", True)))
        self.options_form.addRow("", self.header_checkbox)
        self.header_checkbox.toggled.connect(self._refresh_preview)

    def _build_excel_options(self) -> None:
        try:
            sheets = list_excel_sheets(self.path)
        except Exception as exc:
            sheets = []
            self._show_error(str(exc) or "Could not read workbook sheets.")

        self.sheet_combo = QComboBox()
        self.sheet_combo.addItems(sheets)
        selected_sheet = self._base_options.get("sheet_name")
        if selected_sheet in sheets:
            self.sheet_combo.setCurrentText(selected_sheet)
        self.sheet_combo.setEnabled(bool(sheets))
        self.options_form.addRow("Worksheet", self.sheet_combo)
        self.sheet_combo.currentIndexChanged.connect(self._refresh_preview)

        header_row = self._base_options.get("header_row")
        self.header_auto_checkbox = QCheckBox("Use first non-empty row")
        self.header_auto_checkbox.setChecked(header_row is None)
        self.header_row_spin = QSpinBox()
        self.header_row_spin.setRange(1, 1_048_576)
        self.header_row_spin.setValue(int(header_row) if header_row is not None else 1)
        self.header_row_spin.setEnabled(header_row is not None)

        header_row_widget = QWidget(self)
        header_row_layout = QHBoxLayout(header_row_widget)
        header_row_layout.setContentsMargins(0, 0, 0, 0)
        header_row_layout.addWidget(self.header_auto_checkbox)
        header_row_layout.addWidget(QLabel("Header row"))
        header_row_layout.addWidget(self.header_row_spin)
        header_row_layout.addStretch(1)
        self.options_form.addRow("Column names", header_row_widget)
        self.header_auto_checkbox.toggled.connect(self.header_row_spin.setDisabled)
        self.header_auto_checkbox.toggled.connect(self._refresh_preview)
        self.header_row_spin.valueChanged.connect(self._refresh_preview)

    def _current_options(self) -> dict[str, Any]:
        options = dict(self._base_options)
        if self._kind == "csv":
            options.update(
                delimiter=self.delimiter_combo.currentData(),
                encoding=self.encoding_combo.currentData(),
                has_header=self.header_checkbox.isChecked(),
            )
        elif self._kind == "excel":
            options.update(
                sheet_name=self.sheet_combo.currentText(),
                header_row=(
                    None
                    if self.header_auto_checkbox.isChecked()
                    else self.header_row_spin.value()
                ),
            )
        return options

    def _refresh_preview(self, *_args: Any) -> None:
        self._preview_candidate = None
        model = self.table.model()
        assert isinstance(model, ImportPreviewTableModel)
        try:
            candidate = parse_file(self.path, options=self._current_options())
        except Exception as exc:
            model.set_candidate(None)
            self.notice_label.clear()
            self.notice_label.setVisible(False)
            self.count_label.setText("No preview is available until the file options are valid.")
            self._show_error(str(exc) or "Could not parse this file with the selected options.")
            self.import_button.setEnabled(False)
            return

        self._preview_candidate = candidate
        model.set_candidate(candidate)
        self._clear_error()
        visible_rows = min(candidate.row_count, PREVIEW_ROW_LIMIT)
        self.count_label.setText(
            f"{len(candidate.headers):,} columns · {candidate.row_count:,} rows total · "
            f"showing {visible_rows:,} rows"
        )
        notices = [str(notice) for notice in candidate.notices if str(notice).strip()]
        self.notice_label.setText(" ".join(notices))
        self.notice_label.setVisible(bool(notices))
        self.import_button.setEnabled(bool(candidate.headers))

    def _show_error(self, message: str) -> None:
        self._last_error = message
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _clear_error(self) -> None:
        self._last_error = ""
        self.error_label.clear()
        self.error_label.setVisible(False)

    def _accept_candidate(self) -> None:
        if self._preview_candidate is None:
            return
        self._accepted_candidate = self._preview_candidate
        super().accept()

    def reject(self) -> None:
        self._accepted_candidate = None
        super().reject()
