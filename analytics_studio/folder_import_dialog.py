"""Folder discovery, sample-file settings, and combined-data preview dialog."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from analytics_studio.file_import import (
    ImportCancelledError,
    ImportCandidate,
    default_options,
)
from analytics_studio.folder_import import (
    FOLDER_FILE_KINDS,
    FileImportError,
    discover_folder_files,
    normalize_folder_options,
    parse_folder,
)
from analytics_studio.import_preview_dialog import FileImportPreviewDialog, ImportPreviewTableModel


_FILE_KIND_LABELS = (
    ("csv", "CSV files"),
    ("excel", "Excel workbooks"),
    ("json", "JSON files"),
    ("xml", "XML files"),
)


class _FolderParseSignals(QObject):
    progress = Signal(int, str)
    completed = Signal(int, object)
    failed = Signal(int, str)
    cancelled = Signal(int)


class _FolderParseTask(QRunnable):
    def __init__(
        self,
        request_id: int,
        folder: Path,
        options: dict[str, Any],
        cancel_event: threading.Event,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.folder = folder
        self.options = options
        self.cancel_event = cancel_event
        self.signals = _FolderParseSignals()

    def run(self) -> None:
        try:
            candidate = parse_folder(
                self.folder,
                self.options,
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
                str(exc) or "Could not combine the selected folder files.",
            )
        else:
            self.signals.completed.emit(self.request_id, candidate)


class _FolderDiscoveryTask(QRunnable):
    def __init__(
        self,
        request_id: int,
        folder: Path,
        file_kind: str,
        recursive: bool,
        name_contains: str,
        cancel_event: threading.Event,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.folder = folder
        self.file_kind = file_kind
        self.recursive = recursive
        self.name_contains = name_contains
        self.cancel_event = cancel_event
        self.signals = _FolderParseSignals()

    def run(self) -> None:
        try:
            files = discover_folder_files(
                self.folder,
                file_kind=self.file_kind,
                recursive=self.recursive,
                name_contains=self.name_contains,
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
                str(exc) or "Could not list the selected folder files.",
            )
        else:
            self.signals.completed.emit(self.request_id, files)


class FolderImportDialog(QDialog):
    """Select matching files, configure a sample parser, and preview the combine."""

    def __init__(
        self,
        folder: Path,
        *,
        replacing: bool,
        initial_options: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.folder = Path(folder).expanduser().resolve()
        self.replacing = replacing
        self._options = normalize_folder_options(initial_options)
        self._file_options = dict(self._options["file_options"])
        self._candidate: ImportCandidate | None = None
        self._files: list[Path] = []
        self._selected_sample_name = self._options["sample_file"]
        self._parse_pool = QThreadPool.globalInstance()
        self._parse_tasks: dict[int, _FolderParseTask] = {}
        self._parse_events: dict[int, threading.Event] = {}
        self._active_parse_id: int | None = None
        self._next_parse_id = 0
        self._discovery_tasks: dict[int, _FolderDiscoveryTask] = {}
        self._discovery_events: dict[int, threading.Event] = {}
        self._active_discovery_id: int | None = None
        self._next_discovery_id = 0
        self._discovery_canceled = False
        self._file_refresh_timer = QTimer(self)
        self._file_refresh_timer.setSingleShot(True)
        self._file_refresh_timer.setInterval(160)
        self._file_refresh_timer.timeout.connect(self._refresh_file_list)

        self.setWindowTitle("Combine files from folder")
        self.setMinimumSize(760, 520)
        self.resize(980, 650)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(9)

        title = QLabel("Combine files from folder")
        title.setStyleSheet("font-size: 19px; font-weight: 600;")
        layout.addWidget(title)

        self.folder_label = QLabel(str(self.folder))
        self.folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.folder_label.setWordWrap(True)
        self.folder_label.setStyleSheet("color: #526477;")
        layout.addWidget(self.folder_label)

        self.replacement_label = QLabel(
            "This folder is already linked to a table. Importing will replace that table's data and saved transform steps."
        )
        self.replacement_label.setWordWrap(True)
        self.replacement_label.setStyleSheet(
            "padding: 8px 10px; color: #6a4d00; background: #fff5d6;"
            "border: 1px solid #e8d391; border-radius: 3px;"
        )
        self.replacement_label.setVisible(replacing)
        layout.addWidget(self.replacement_label)

        filters = QGroupBox("Folder selection")
        form = QFormLayout(filters)
        form.setContentsMargins(12, 9, 12, 9)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(7)

        self.file_kind_combo = QComboBox()
        for value, label in _FILE_KIND_LABELS:
            self.file_kind_combo.addItem(label, value)
        self.file_kind_combo.setCurrentIndex(max(0, self.file_kind_combo.findData(self._options["file_kind"])))
        form.addRow("File type", self.file_kind_combo)

        self.name_filter = QLineEdit(self._options["name_contains"])
        self.name_filter.setMaxLength(120)
        self.name_filter.setPlaceholderText("Optional filename text")
        form.addRow("Name contains", self.name_filter)

        self.recursive_checkbox = QCheckBox("Include subfolders")
        self.recursive_checkbox.setChecked(self._options["recursive"])
        form.addRow("", self.recursive_checkbox)

        self.sample_combo = QComboBox()
        form.addRow("Sample file", self.sample_combo)

        option_row = QHBoxLayout()
        self.source_name_checkbox = QCheckBox("Add a Source.Name column")
        self.source_name_checkbox.setChecked(self._options["include_source_name"])
        option_row.addWidget(self.source_name_checkbox)
        option_row.addStretch(1)
        self.sample_options_button = QPushButton("Sample file options…")
        option_row.addWidget(self.sample_options_button)
        form.addRow("", option_row)
        layout.addWidget(filters)

        self.files_label = QLabel()
        self.files_label.setStyleSheet("color: #526477;")
        layout.addWidget(self.files_label)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.notice_label = QLabel()
        self.notice_label.setWordWrap(True)
        self.notice_label.setStyleSheet("color: #526477;")
        self.notice_label.setVisible(False)
        layout.addWidget(self.notice_label)

        self.table = QTableView()
        self.table.setModel(ImportPreviewTableModel(self.table))
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setDefaultSectionSize(145)
        self.table.verticalHeader().setDefaultSectionSize(25)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.preview_button = QPushButton("Preview combined data")
        footer.addWidget(self.preview_button)
        footer.addStretch(1)
        layout.addLayout(footer)

        self.count_label = QLabel("Preview matching files before importing.")
        self.count_label.setStyleSheet("color: #526477;")
        layout.addWidget(self.count_label)

        self.progress_label = QLabel("Preparing combined preview…")
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

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        self.import_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.import_button.setText("Import folder")
        self.import_button.setEnabled(False)
        self.buttons.accepted.connect(self._accept_candidate)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.file_kind_combo.currentIndexChanged.connect(self._file_kind_changed)
        self.name_filter.textChanged.connect(self._filters_changed)
        self.recursive_checkbox.toggled.connect(self._filters_changed)
        self.sample_combo.currentIndexChanged.connect(self._sample_selection_changed)
        self.source_name_checkbox.toggled.connect(self._clear_candidate)
        self.sample_options_button.clicked.connect(self._edit_sample_options)
        self.preview_button.clicked.connect(self._toggle_preview)
        self._refresh_file_list()

    @property
    def candidate(self) -> ImportCandidate | None:
        return self._candidate if self.result() == QDialog.DialogCode.Accepted else None

    def _current_options(self) -> dict[str, Any]:
        return normalize_folder_options({
            "file_kind": self.file_kind_combo.currentData(),
            "recursive": self.recursive_checkbox.isChecked(),
            "name_contains": self.name_filter.text(),
            "sample_file": str(self.sample_combo.currentData() or ""),
            "file_options": self._file_options,
            "include_source_name": self.source_name_checkbox.isChecked(),
        })

    def _file_kind_changed(self, _index: int) -> None:
        file_kind = str(self.file_kind_combo.currentData())
        if file_kind in FOLDER_FILE_KINDS:
            self._file_options = default_options(file_kind)
        self._filters_changed()

    def _filters_changed(self, *_args: Any) -> None:
        self._clear_candidate()
        current_sample = str(self.sample_combo.currentData() or "")
        if current_sample:
            self._selected_sample_name = current_sample
        self._file_refresh_timer.stop()
        self._cancel_pending_discovery()
        self._discovery_canceled = False
        self._files = []
        self.sample_combo.blockSignals(True)
        self.sample_combo.clear()
        self.sample_combo.blockSignals(False)
        self.sample_combo.setEnabled(False)
        self.sample_options_button.setEnabled(False)
        self.files_label.setText("Updating matching files…")
        self._update_preview_button()
        self._file_refresh_timer.start()

    def _sample_selection_changed(self, *_args: Any) -> None:
        selected = str(self.sample_combo.currentData() or "")
        if selected:
            self._selected_sample_name = selected
        self._clear_candidate()

    def _refresh_file_list(self) -> None:
        self._file_refresh_timer.stop()
        self._cancel_pending_discovery()
        self._discovery_canceled = False
        self._files = []
        self._clear_error()
        self.sample_combo.blockSignals(True)
        self.sample_combo.clear()
        self.sample_combo.blockSignals(False)
        self.sample_combo.setEnabled(False)
        self.sample_options_button.setEnabled(False)
        self.files_label.setText("Scanning folder for matching files…")

        self._next_discovery_id += 1
        request_id = self._next_discovery_id
        cancel_event = threading.Event()
        task = _FolderDiscoveryTask(
            request_id,
            self.folder,
            str(self.file_kind_combo.currentData()),
            self.recursive_checkbox.isChecked(),
            self.name_filter.text(),
            cancel_event,
        )
        task.signals.progress.connect(self._on_discovery_progress)
        task.signals.completed.connect(self._on_discovery_completed)
        task.signals.failed.connect(self._on_discovery_failed)
        task.signals.cancelled.connect(self._on_discovery_cancelled)
        self._discovery_tasks[request_id] = task
        self._discovery_events[request_id] = cancel_event
        self._active_discovery_id = request_id
        self._set_discovery_busy(True)
        self._parse_pool.start(task)

    def _populate_file_list(self, files: list[Path], error: str = "") -> None:
        self._files = files
        self.sample_combo.blockSignals(True)
        self.sample_combo.clear()
        for path in self._files:
            relative = path.relative_to(self.folder).as_posix()
            self.sample_combo.addItem(relative, relative)
        if self._files:
            index = self.sample_combo.findData(self._selected_sample_name)
            self.sample_combo.setCurrentIndex(index if index >= 0 else 0)
            self._selected_sample_name = str(self.sample_combo.currentData() or "")
        self.sample_combo.blockSignals(False)
        self.sample_combo.setEnabled(bool(self._files))
        self.files_label.setText(
            f"{len(self._files):,} matching file(s) · limits: 500 files, 100 MiB combined source size"
        )
        self.sample_options_button.setEnabled(bool(self._files))
        self._update_preview_button()
        if error:
            self._show_error(error)
        elif self._files:
            self._clear_error()
        else:
            self._show_error("No files match this selection. Change the file type or filters.")

    def _release_discovery_task(self, request_id: int) -> bool:
        self._discovery_tasks.pop(request_id, None)
        self._discovery_events.pop(request_id, None)
        return request_id == self._active_discovery_id

    def _on_discovery_progress(self, request_id: int, message: str) -> None:
        if request_id == self._active_discovery_id:
            self.progress_label.setText(message)

    def _on_discovery_completed(self, request_id: int, files: list[Path]) -> None:
        if not self._release_discovery_task(request_id):
            return
        self._active_discovery_id = None
        self._set_discovery_busy(False)
        self._populate_file_list(files)

    def _on_discovery_failed(self, request_id: int, message: str) -> None:
        if not self._release_discovery_task(request_id):
            return
        self._active_discovery_id = None
        self._set_discovery_busy(False)
        self._populate_file_list([], message)

    def _on_discovery_cancelled(self, request_id: int) -> None:
        if not self._release_discovery_task(request_id):
            return
        self._active_discovery_id = None
        self._set_discovery_busy(False)
        self.files_label.setText("Folder scan canceled.")

    def _cancel_pending_discovery(self) -> None:
        request_id = self._active_discovery_id
        if request_id is None:
            return
        cancel_event = self._discovery_events.get(request_id)
        if cancel_event is not None:
            cancel_event.set()
        self._active_discovery_id = None
        self._set_discovery_busy(False)

    def _set_discovery_busy(self, busy: bool) -> None:
        self.progress_widget.setVisible(busy or self._active_parse_id is not None)
        if busy:
            self.progress_label.setText("Scanning folder entries…")
        self._update_preview_button()

    def _update_preview_button(self) -> None:
        if self._active_parse_id is not None:
            self.preview_button.setText("Cancel preview")
            self.preview_button.setEnabled(True)
        elif self._active_discovery_id is not None:
            self.preview_button.setText("Cancel scan")
            self.preview_button.setEnabled(True)
        elif self._file_refresh_timer.isActive():
            self.preview_button.setText("Updating folder list…")
            self.preview_button.setEnabled(False)
        elif self._discovery_canceled:
            self.preview_button.setText("Scan folder")
            self.preview_button.setEnabled(True)
        else:
            self.preview_button.setText("Preview combined data")
            self.preview_button.setEnabled(bool(self._files))

    def _edit_sample_options(self) -> None:
        sample_name = str(self.sample_combo.currentData() or "")
        sample_path = self.folder / sample_name
        if not sample_name or not sample_path.is_file():
            self._show_error("Choose an available sample file first.")
            return
        dialog = FileImportPreviewDialog(
            sample_path,
            replacing=False,
            initial_options=self._file_options,
            parent=self,
        )
        dialog.setWindowTitle("Set sample file options")
        dialog.import_button.setText("Use these options")
        dialog.replacement_label.hide()
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return
        self._file_options = dict(dialog.candidate.options)
        self._clear_candidate()
        self.notice_label.setText("Sample parsing options saved. Preview the full folder selection before importing.")
        self.notice_label.setVisible(True)

    def _toggle_preview(self) -> None:
        if self._active_parse_id is not None:
            self._cancel_pending_preview()
            self.count_label.setText("Combined preview canceled.")
            return
        if self._active_discovery_id is not None:
            self._cancel_pending_discovery()
            self._discovery_canceled = True
            self.files_label.setText("Folder scan canceled.")
            self.count_label.setText("Scan canceled. Select Scan folder to try again.")
            self._update_preview_button()
            return
        if self._discovery_canceled:
            self._discovery_canceled = False
            self._refresh_file_list()
            return
        self._preview_combined()

    def _preview_combined(self) -> None:
        if self._active_discovery_id is not None or self._file_refresh_timer.isActive():
            return
        if not self._files:
            return
        self._cancel_pending_preview()
        self._clear_candidate()
        self._clear_error()
        self._next_parse_id += 1
        request_id = self._next_parse_id
        cancel_event = threading.Event()
        task = _FolderParseTask(
            request_id,
            self.folder,
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
        self.count_label.setText("Preparing the combined-data preview…")
        self._parse_pool.start(task)

    def _cancel_pending_preview(self) -> None:
        request_id = self._active_parse_id
        if request_id is None:
            return
        cancel_event = self._parse_events.get(request_id)
        if cancel_event is not None:
            cancel_event.set()
        self._active_parse_id = None
        self._set_preview_busy(False)

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
        if not self._release_parse_task(request_id):
            return
        self._active_parse_id = None
        self._set_preview_busy(False)
        self._candidate = candidate
        model = self.table.model()
        assert isinstance(model, ImportPreviewTableModel)
        model.set_candidate(candidate)
        self.error_label.setVisible(False)
        self.notice_label.setText(" ".join(candidate.notices))
        self.notice_label.setVisible(bool(candidate.notices))
        self.count_label.setText(
            f"{candidate.row_count:,} rows · {len(candidate.headers):,} columns · "
            f"{len(self._files):,} files combined"
        )
        self.import_button.setEnabled(True)

    def _on_parse_failed(self, request_id: int, message: str) -> None:
        if not self._release_parse_task(request_id):
            return
        self._active_parse_id = None
        self._set_preview_busy(False)
        self._clear_candidate()
        self._show_error(message)

    def _on_parse_cancelled(self, request_id: int) -> None:
        if not self._release_parse_task(request_id):
            return
        self._active_parse_id = None
        self._set_preview_busy(False)
        self.count_label.setText("Combined preview canceled.")

    def _set_preview_busy(self, busy: bool) -> None:
        self.progress_widget.setVisible(busy or self._active_discovery_id is not None)
        if busy:
            self.progress_label.setText("Scanning and reading matching files…")
            self.import_button.setEnabled(False)
        self._update_preview_button()

    def _clear_candidate(self, *_args: Any) -> None:
        self._cancel_pending_preview()
        self._candidate = None
        self.import_button.setEnabled(False)
        self.notice_label.clear()
        self.notice_label.setVisible(False)
        model = self.table.model()
        if isinstance(model, ImportPreviewTableModel):
            model.set_candidate(None)
        self.count_label.setText("Preview matching files before importing.")

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _clear_error(self) -> None:
        self.error_label.clear()
        self.error_label.setVisible(False)

    def _accept_candidate(self) -> None:
        if self._candidate is None:
            return
        self.accept()

    def reject(self) -> None:
        self._file_refresh_timer.stop()
        self._cancel_pending_preview()
        self._cancel_pending_discovery()
        self._candidate = None
        super().reject()
