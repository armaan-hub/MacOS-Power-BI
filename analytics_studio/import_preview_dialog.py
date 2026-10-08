"""Native preview and confirmation dialog for local file imports."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QRunnable,
    QThreadPool,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from analytics_studio.file_import import (
    ImportCancelledError,
    ImportCandidate,
    default_options,
    inspect_excel_options,
    kind_for_path,
    list_sqlite_tables,
    normalize_options,
    parse_file,
)


PREVIEW_ROW_LIMIT = 100
ASYNC_PREVIEW_THRESHOLD_BYTES = 256 * 1024
_DELIMITERS = ((",", "Comma"), (";", "Semicolon"), ("\t", "Tab"), ("|", "Pipe"))
_ENCODINGS = (
    ("utf-8-sig", "UTF-8 (BOM aware)"),
    ("utf-8", "UTF-8"),
    ("utf-16", "UTF-16"),
    ("cp1252", "Windows-1252"),
)


class _ImportParseSignals(QObject):
    progress = Signal(int, str)
    completed = Signal(int, object)
    failed = Signal(int, str)
    cancelled = Signal(int)


class _ImportParseTask(QRunnable):
    def __init__(
        self,
        request_id: int,
        path: Path,
        options: dict[str, Any],
        cancel_event: threading.Event,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.path = path
        self.options = options
        self.cancel_event = cancel_event
        self.signals = _ImportParseSignals()

    def run(self) -> None:
        try:
            candidate = parse_file(
                self.path,
                options=self.options,
                cancel_event=self.cancel_event,
                progress_callback=lambda message: self.signals.progress.emit(
                    self.request_id, message
                ),
            )
        except ImportCancelledError:
            self.signals.cancelled.emit(self.request_id)
        except Exception as exc:
            self.signals.failed.emit(
                self.request_id,
                str(exc) or "Could not parse this file with the selected options.",
            )
        else:
            self.signals.completed.emit(self.request_id, candidate)


class _SourceOptionsSignals(QObject):
    progress = Signal(int, str)
    completed = Signal(int, object)
    failed = Signal(int, str)
    cancelled = Signal(int)


class _SourceOptionsTask(QRunnable):
    def __init__(
        self,
        request_id: int,
        path: Path,
        kind: str,
        options: dict[str, Any],
        cancel_event: threading.Event,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.path = path
        self.kind = kind
        self.options = options
        self.cancel_event = cancel_event
        self.signals = _SourceOptionsSignals()

    def run(self) -> None:
        try:
            if self.kind == "excel":
                self.signals.progress.emit(self.request_id, "Checking workbook contents…")
                result = inspect_excel_options(
                    self.path,
                    preferred_sheet=self.options.get("sheet_name"),
                    cancel_event=self.cancel_event,
                    progress_callback=lambda message: self.signals.progress.emit(
                        self.request_id, message
                    ),
                )
            elif self.kind == "sqlite":
                self.signals.progress.emit(self.request_id, "Listing SQLite tables and views…")
                result = list_sqlite_tables(
                    self.path,
                    cancel_event=self.cancel_event,
                )
            else:
                raise ValueError(f"Unsupported source-options kind {self.kind!r}.")
        except ImportCancelledError:
            self.signals.cancelled.emit(self.request_id)
        except Exception as exc:
            self.signals.failed.emit(
                self.request_id,
                str(exc) or "Could not read source options.",
            )
        else:
            if self.cancel_event.is_set():
                self.signals.cancelled.emit(self.request_id)
            else:
                self.signals.completed.emit(self.request_id, result)


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
        initial_options: dict[str, Any] | None = None,
        existing_sqlite_tables: set[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = Path(path).expanduser().resolve()
        self.replacing = replacing
        self.initial_options = dict(initial_options or {})
        self.existing_sqlite_tables = set(existing_sqlite_tables or ())
        self._kind: str | None = None
        self._base_options: dict[str, Any] = {}
        self._preview_candidate: ImportCandidate | None = None
        self._accepted_candidate: ImportCandidate | None = None
        self._last_error = ""
        self._parse_pool = QThreadPool.globalInstance()
        self._parse_tasks: dict[int, _ImportParseTask] = {}
        self._parse_events: dict[int, threading.Event] = {}
        self._active_parse_id: int | None = None
        self._next_parse_id = 0
        self._options_tasks: dict[int, _SourceOptionsTask] = {}
        self._options_events: dict[int, threading.Event] = {}
        self._active_options_id: int | None = None
        self._next_options_id = 0
        self._source_options_pending = False

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

        heading = QLabel("Review source data")
        heading.setStyleSheet("font-size: 19px; font-weight: 600;")
        layout.addWidget(heading)

        self.file_label = QLabel(str(self.path))
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.file_label.setWordWrap(True)
        self.file_label.setStyleSheet("color: #526477;")
        layout.addWidget(self.file_label)

        self.replacement_label = QLabel(
            "This file is already linked to a table in this project. Importing will replace that table's data and saved transform steps."
        )
        self.replacement_label.setWordWrap(True)
        self.replacement_label.setStyleSheet(
            "padding: 8px 10px; color: #6a4d00; background: #fff5d6;"
            "border: 1px solid #e8d391; border-radius: 3px;"
        )
        self.replacement_label.setVisible(self.replacing)
        layout.addWidget(self.replacement_label)

        self.options_group = QGroupBox("Source options")
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

        self.progress_label = QLabel("Preparing preview…")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        progress_row = QHBoxLayout()
        progress_row.addWidget(self.progress_label, 1)
        progress_row.addWidget(self.progress_bar, 1)
        self.progress_widget = QWidget(self)
        self.progress_widget.setLayout(progress_row)
        self.progress_widget.setVisible(False)
        layout.addWidget(self.progress_widget)

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

        self.count_label = QLabel("Choose a supported source to see a preview.")
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
            self._base_options = normalize_options(
                self._kind,
                {**default_options(self._kind), **self.initial_options},
            )
        except Exception as exc:
            self._show_error(str(exc) or "This file cannot be imported.")
            self.count_label.setText("No preview is available.")
            return

        source_options_pending = False
        if self._kind == "csv":
            self._build_csv_options()
        elif self._kind == "excel":
            if self.path.suffix.casefold() == ".xls":
                self.format_note.setText(
                    "Legacy .xls import reads saved formula results without recalculating formulas. "
                    "Date-formatted numbers use the workbook's 1900 or 1904 date system."
                )
            source_options_pending = self._build_excel_options()
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
        elif self._kind == "parquet":
            self.format_note.setText(
                "Imports flat scalar Parquet columns. Values become text, nulls appear blank, "
                "and source types are not retained. Nested and binary columns are not supported."
            )
        elif self._kind == "sqlite":
            self.format_note.setText(
                "Connects read-only to one table or view in this local SQLite database. "
                "Nulls become blank, values become text, and BLOB columns are not supported."
            )
            source_options_pending = self._build_sqlite_options()
        if not source_options_pending:
            self._refresh_preview()

    def _build_sqlite_options(self) -> bool:
        self.table_combo = QComboBox()
        self.table_combo.addItem("Reading tables…", None)
        self.table_combo.setEnabled(False)
        self.options_form.addRow("Table or view", self.table_combo)
        self._start_background_options_discovery()
        return True

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

    def _build_excel_options(self) -> bool:
        self.sheet_combo = QComboBox()
        self.sheet_combo.addItem("Reading worksheets…", None)
        self.sheet_combo.setEnabled(False)
        self.options_form.addRow("Worksheet", self.sheet_combo)

        header_row = self._base_options.get("header_row")
        self.header_auto_checkbox = QCheckBox("Detect header row automatically")
        self.header_auto_checkbox.setChecked(header_row is None)
        self.header_row_spin = QSpinBox()
        max_rows = 65_536 if self.path.suffix.casefold() == ".xls" else 1_048_576
        self.header_row_spin.setRange(1, max_rows)
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
        self._start_background_options_discovery()
        return True

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
        elif self._kind == "sqlite":
            options.update(
                table_name=self.table_combo.currentData(),
            )
        return options

    def _start_background_options_discovery(self) -> None:
        assert self._kind in {"excel", "sqlite"}
        self._next_options_id += 1
        request_id = self._next_options_id
        cancel_event = threading.Event()
        task = _SourceOptionsTask(
            request_id,
            self.path,
            self._kind,
            dict(self._base_options),
            cancel_event,
        )
        task.signals.progress.connect(self._on_options_progress)
        task.signals.completed.connect(self._on_options_completed)
        task.signals.failed.connect(self._on_options_failed)
        task.signals.cancelled.connect(self._on_options_cancelled)
        self._options_tasks[request_id] = task
        self._options_events[request_id] = cancel_event
        self._active_options_id = request_id
        self._source_options_pending = True
        self.options_group.setEnabled(False)
        self._set_preview_busy(True)
        self.count_label.setText("Reading source options before preparing the preview…")
        self._parse_pool.start(task)

    def _release_options_task(self, request_id: int) -> bool:
        self._options_tasks.pop(request_id, None)
        self._options_events.pop(request_id, None)
        return request_id == self._active_options_id

    def _on_options_progress(self, request_id: int, message: str) -> None:
        if request_id == self._active_options_id:
            self.progress_label.setText(message)

    def _on_options_completed(self, request_id: int, result: object) -> None:
        is_current = self._release_options_task(request_id)
        if not is_current:
            return
        self._active_options_id = None
        self._source_options_pending = False
        self._set_preview_busy(False)
        self.options_group.setEnabled(True)
        if self._kind == "excel":
            sheets, recommended_sheet = result
            self._apply_excel_options(sheets, recommended_sheet)
        elif self._kind == "sqlite":
            self._apply_sqlite_options(result)
        self._refresh_preview()

    def _on_options_failed(self, request_id: int, message: str) -> None:
        is_current = self._release_options_task(request_id)
        if not is_current:
            return
        self._active_options_id = None
        self._source_options_pending = False
        self._set_preview_busy(False)
        self.options_group.setEnabled(True)
        self._show_preview_error(message)

    def _on_options_cancelled(self, request_id: int) -> None:
        is_current = self._release_options_task(request_id)
        if not is_current:
            return
        self._active_options_id = None
        self._source_options_pending = False
        self._set_preview_busy(False)
        self.import_button.setEnabled(False)

    def _apply_excel_options(
        self,
        sheets: list[str],
        recommended_sheet: str | None,
    ) -> None:
        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        self.sheet_combo.addItems(sheets)
        selected_sheet = self._base_options.get("sheet_name")
        if selected_sheet not in sheets:
            selected_sheet = recommended_sheet
        if selected_sheet in sheets:
            self.sheet_combo.setCurrentText(selected_sheet)
        self.sheet_combo.setEnabled(bool(sheets))
        self.sheet_combo.blockSignals(False)
        self.sheet_combo.currentIndexChanged.connect(self._refresh_preview)

    def _apply_sqlite_options(self, table_names: list[str]) -> None:
        self.table_combo.blockSignals(True)
        self.table_combo.clear()
        for table_name in table_names:
            self.table_combo.addItem(table_name, table_name)
        saved_name = self._base_options.get("table_name")
        if saved_name in table_names:
            self.table_combo.setCurrentIndex(self.table_combo.findData(saved_name))
        elif saved_name:
            self.table_combo.insertItem(0, f"{saved_name} (not found)", saved_name)
            self.table_combo.setCurrentIndex(0)
            self.format_note.setText(
                f"The saved SQLite table or view {saved_name!r} is missing. "
                "Choose another object to import from this database."
            )
        self.table_combo.setEnabled(bool(table_names))
        self.table_combo.blockSignals(False)
        self.table_combo.currentIndexChanged.connect(self._refresh_preview)

    def _refresh_preview(self, *_args: Any) -> None:
        if self._source_options_pending:
            return
        self._cancel_pending_preview()
        self._preview_candidate = None
        model = self.table.model()
        assert isinstance(model, ImportPreviewTableModel)
        model.set_candidate(None)
        self.import_button.setEnabled(False)

        if self._requires_background_parse():
            self._start_background_preview()
            return

        try:
            candidate = parse_file(self.path, options=self._current_options())
        except Exception as exc:
            self._show_preview_error(
                str(exc) or "Could not parse this file with the selected options."
            )
            return

        self._show_preview_candidate(candidate)

    def _requires_background_parse(self) -> bool:
        # Excel archives can expand far beyond their compressed size, and SQLite
        # sources can include a WAL or return a large view from a small database.
        if self._kind in {"excel", "sqlite"}:
            return True
        try:
            return self.path.stat().st_size >= ASYNC_PREVIEW_THRESHOLD_BYTES
        except OSError:
            return False

    def _start_background_preview(self) -> None:
        self._next_parse_id += 1
        request_id = self._next_parse_id
        cancel_event = threading.Event()
        task = _ImportParseTask(
            request_id,
            self.path,
            self._current_options(),
            cancel_event,
        )
        task.signals.progress.connect(self._on_parse_progress)
        task.signals.completed.connect(self._on_parse_completed)
        task.signals.failed.connect(self._on_parse_failed)
        task.signals.cancelled.connect(self._on_parse_cancelled)
        self._parse_tasks[request_id] = task
        self._parse_events[request_id] = cancel_event
        self._active_parse_id = request_id
        self._set_preview_busy(True)
        self.count_label.setText("Preparing the full-data preview…")
        self._parse_pool.start(task)

    def _cancel_pending_options(self) -> None:
        request_id = self._active_options_id
        if request_id is None:
            return
        cancel_event = self._options_events.get(request_id)
        if cancel_event is not None:
            cancel_event.set()
        self._active_options_id = None
        self._source_options_pending = False

    def _cancel_pending_preview(self) -> None:
        request_id = self._active_parse_id
        if request_id is None:
            return
        cancel_event = self._parse_events.get(request_id)
        if cancel_event is not None:
            cancel_event.set()
        self._active_parse_id = None

    def _release_parse_task(self, request_id: int) -> bool:
        self._parse_tasks.pop(request_id, None)
        self._parse_events.pop(request_id, None)
        return request_id == self._active_parse_id

    def _on_parse_progress(self, request_id: int, message: str) -> None:
        if request_id == self._active_parse_id:
            self.progress_label.setText(message)

    def _on_parse_completed(
        self, request_id: int, candidate: ImportCandidate
    ) -> None:
        is_current = self._release_parse_task(request_id)
        if not is_current:
            return
        self._active_parse_id = None
        self._set_preview_busy(False)
        self._show_preview_candidate(candidate)

    def _on_parse_failed(self, request_id: int, message: str) -> None:
        is_current = self._release_parse_task(request_id)
        if not is_current:
            return
        self._active_parse_id = None
        self._set_preview_busy(False)
        self._show_preview_error(message)

    def _on_parse_cancelled(self, request_id: int) -> None:
        is_current = self._release_parse_task(request_id)
        if not is_current:
            return
        self._active_parse_id = None
        self._set_preview_busy(False)
        self.count_label.setText("Preview canceled. Change an option to try again.")
        self.import_button.setEnabled(False)

    def _set_preview_busy(self, busy: bool) -> None:
        self.progress_widget.setVisible(busy)
        if busy:
            self.progress_label.setText("Reading source data…")
            self.import_button.setEnabled(False)

    def _show_preview_error(self, message: str) -> None:
        model = self.table.model()
        assert isinstance(model, ImportPreviewTableModel)
        model.set_candidate(None)
        self.notice_label.clear()
        self.notice_label.setVisible(False)
        self.count_label.setText("No preview is available until the file options are valid.")
        self._show_error(message)
        self.import_button.setEnabled(False)

    def _show_preview_candidate(self, candidate: ImportCandidate) -> None:
        self._preview_candidate = candidate
        if self._kind == "sqlite":
            selected_table = self._current_options().get("table_name")
            self.replacement_label.setVisible(
                bool(selected_table and selected_table in self.existing_sqlite_tables)
            )
        model = self.table.model()
        assert isinstance(model, ImportPreviewTableModel)
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
        self._cancel_pending_options()
        self._cancel_pending_preview()
        self._accepted_candidate = None
        super().reject()
