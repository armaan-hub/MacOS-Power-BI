"""URL discovery, tabular-object preview, and confirmation for Web imports."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from analytics_studio.file_import import ImportCandidate
from analytics_studio.import_preview_dialog import ImportPreviewTableModel, PREVIEW_ROW_LIMIT
from analytics_studio.web_import import (
    WebImportError,
    discover_web_objects,
    fetch_web_payload,
    parse_web_payload,
    read_web_source,
    validate_web_url,
)


class WebImportDialog(QDialog):
    """Import public HTTPS file responses, JSON data, or static HTML tables."""

    def __init__(
        self,
        parent=None,
        *,
        source_editing: bool = False,
        allow_transform: bool = True,
        initial_connection: dict[str, Any] | None = None,
        initial_options: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self._source_editing = source_editing
        self.allow_transform = bool(allow_transform) and not source_editing
        self._initial_options = dict(initial_options or {})
        self.setWindowTitle(
            "Edit Web source settings" if source_editing else "Import from Web"
        )
        self.setMinimumSize(760, 520)
        self.resize(960, 670)
        self._payload = None
        self._objects: list[dict[str, Any]] = []
        self._candidate: ImportCandidate | None = None
        self._accepted_candidate: ImportCandidate | None = None
        self._accepted_url = ""
        self._accepted_action: str | None = None
        self._busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        heading = QLabel("Connect to a Web source")
        heading.setStyleSheet("font-size: 19px; font-weight: 600;")
        layout.addWidget(heading)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(7)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com/data.csv")
        if initial_connection:
            self.url_edit.setText(str(initial_connection.get("url", "")))
        form.addRow("URL", self.url_edit)
        layout.addLayout(form)

        self.connection_note = QLabel(
            "Supports anonymous HTTPS GET for CSV, JSON, XML, Excel, Parquet, and static HTML tables. "
            "Credentials, custom headers, POST, and JavaScript-rendered pages are not supported. "
            "The full URL is saved in the project; token-like query parameters are rejected."
        )
        self.connection_note.setWordWrap(True)
        self.connection_note.setStyleSheet("color: #526477; padding: 2px 0;")
        layout.addWidget(self.connection_note)

        connect_row = QHBoxLayout()
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self._connect)
        connect_row.addWidget(self.connect_button)
        connect_row.addWidget(QLabel("Available data"))
        self.object_combo = QComboBox()
        self.object_combo.setEnabled(False)
        self.object_combo.currentIndexChanged.connect(self._load_selected_object)
        connect_row.addWidget(self.object_combo, 1)
        layout.addLayout(connect_row)

        self.csv_options = QWidget()
        csv_form = QFormLayout(self.csv_options)
        csv_form.setContentsMargins(0, 0, 0, 0)
        csv_form.setHorizontalSpacing(18)
        self.delimiter_combo = QComboBox()
        for label, delimiter in (("Comma", ","), ("Semicolon", ";"), ("Tab", "\t"), ("Pipe", "|")):
            self.delimiter_combo.addItem(label, delimiter)
        self.encoding_combo = QComboBox()
        for label, encoding in (
            ("UTF-8", "utf-8-sig"),
            ("UTF-8 (no BOM)", "utf-8"),
            ("UTF-16", "utf-16"),
            ("Windows-1252", "cp1252"),
        ):
            self.encoding_combo.addItem(label, encoding)
        self.header_check = QCheckBox("First row contains column names")
        self.header_check.setChecked(True)
        csv_form.addRow("Delimiter", self.delimiter_combo)
        csv_form.addRow("Encoding", self.encoding_combo)
        csv_form.addRow("Headers", self.header_check)
        self.csv_options.setVisible(False)
        layout.addWidget(self.csv_options)

        self.status_label = QLabel("Enter a public HTTPS URL, then connect to find tables or tabular content.")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #526477; padding: 2px 0;")
        layout.addWidget(self.status_label)

        self.preview_model = ImportPreviewTableModel(self)
        self.preview_table = QTableView()
        self.preview_table.setModel(self.preview_model)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setSelectionMode(QTableView.SelectionMode.NoSelection)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.preview_table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.import_button = QPushButton(
            "Apply settings" if source_editing else "Load"
        )
        self.import_button.setEnabled(False)
        buttons.addButton(self.import_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.transform_button = QPushButton("Transform data")
        self.transform_button.setVisible(self.allow_transform)
        self.transform_button.setEnabled(False)
        buttons.addButton(self.transform_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        self.import_button.clicked.connect(lambda: self._accept_import("load"))
        self.transform_button.clicked.connect(
            lambda: self._accept_import("transform")
        )
        layout.addWidget(buttons)

        self.url_edit.textChanged.connect(self._invalidate_url)
        self.delimiter_combo.currentIndexChanged.connect(self._refresh_csv_preview)
        self.encoding_combo.currentIndexChanged.connect(self._refresh_csv_preview)
        self.header_check.stateChanged.connect(self._refresh_csv_preview)

    @property
    def candidate(self) -> ImportCandidate | None:
        return self._accepted_candidate if self.result() == QDialog.DialogCode.Accepted else None

    @property
    def url(self) -> str:
        return self._accepted_url if self.result() == QDialog.DialogCode.Accepted else ""

    @property
    def selected_action(self) -> str | None:
        return (
            self._accepted_action
            if self.result() == QDialog.DialogCode.Accepted
            else None
        )

    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        self.import_button.setEnabled(enabled)
        self.transform_button.setEnabled(enabled and self.allow_transform)

    def _connect(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._clear_preview()
        try:
            self._accepted_url = validate_web_url(self.url_edit.text())
            self._payload = fetch_web_payload(self._accepted_url)
            self._objects = discover_web_objects(self._payload)
            self.object_combo.blockSignals(True)
            self.object_combo.clear()
            for item in self._objects:
                self.object_combo.addItem(item["label"], item["options"])
            preferred_index = self._initial_object_index()
            if preferred_index >= 0:
                options = self._objects[preferred_index].get("options", {})
                if isinstance(options, dict) and options.get("resource_type") == "csv":
                    self._restore_csv_options()
                self.object_combo.setCurrentIndex(preferred_index)
            self.object_combo.blockSignals(False)
            self.object_combo.setEnabled(bool(self._objects))
            self.status_label.setText(
                f"Connected · {len(self._objects):,} selectable object(s) found."
            )
            self.status_label.setStyleSheet("color: #526477; padding: 2px 0;")
        except (WebImportError, TypeError, ValueError) as exc:
            self.object_combo.blockSignals(False)
            self.object_combo.clear()
            self.object_combo.setEnabled(False)
            self._payload = None
            self._objects = []
            self._set_error(str(exc))
        finally:
            self._set_busy(False)
        if self._objects:
            self._load_selected_object(self.object_combo.currentIndex())

    def _load_selected_object(self, index: int) -> None:
        if self._busy or self._payload is None or index < 0 or index >= len(self._objects):
            return
        self._preview_selected()

    def _refresh_csv_preview(self, *_args: Any) -> None:
        if self._busy or self._candidate is None:
            return
        options = self._selected_options()
        if options.get("resource_type") == "csv":
            self._preview_selected()

    def _preview_selected(self) -> None:
        if self._payload is None:
            return
        self._set_busy(True)
        self._clear_preview()
        try:
            self._candidate = parse_web_payload(
                self._payload,
                self._selected_options(),
                row_limit=PREVIEW_ROW_LIMIT,
            )
            self.preview_model.set_candidate(self._candidate)
            self.csv_options.setVisible(self._candidate.options.get("resource_type") == "csv")
            notice = f" {' '.join(self._candidate.notices)}" if self._candidate.notices else ""
            self.status_label.setText(
                f"Preview · showing up to {min(self._candidate.row_count, PREVIEW_ROW_LIMIT):,} rows.{notice}"
            )
            self.status_label.setStyleSheet("color: #526477; padding: 2px 0;")
            self._set_action_buttons_enabled(True)
        except (WebImportError, TypeError, ValueError) as exc:
            self._set_error(str(exc))
        finally:
            self._set_busy(False)

    def _accept_import(self, action: str = "load") -> None:
        if self._candidate is None:
            return
        if action not in {"load", "transform"}:
            return
        if action == "transform" and not self.allow_transform:
            return
        self._set_busy(True)
        self.status_label.setText("Importing the selected Web data…")
        try:
            url = validate_web_url(self.url_edit.text())
            candidate = read_web_source({"url": url}, self._selected_options())
        except (WebImportError, TypeError, ValueError) as exc:
            self._set_error(str(exc))
            self._set_busy(False)
            return
        self._accepted_candidate = candidate
        self._accepted_url = url
        self._accepted_action = action
        self.accept()

    def _selected_options(self) -> dict[str, Any]:
        value = self.object_combo.currentData()
        options = dict(value) if isinstance(value, dict) else {}
        if options.get("resource_type") == "csv":
            options.update({
                "delimiter": self.delimiter_combo.currentData(),
                "encoding": self.encoding_combo.currentData(),
                "has_header": self.header_check.isChecked(),
            })
        return options

    def _initial_object_index(self) -> int:
        if not self._initial_options:
            return -1
        for index, item in enumerate(self._objects):
            options = item.get("options", {})
            if not isinstance(options, dict):
                continue
            if all(
                options.get(key) == self._initial_options.get(key)
                for key in ("resource_type", "table_index", "json_path", "table_name")
                if key in self._initial_options
            ):
                return index
        return -1

    def _restore_csv_options(self) -> None:
        options = self._initial_options
        delimiter_index = self.delimiter_combo.findData(options.get("delimiter"))
        if delimiter_index >= 0:
            self.delimiter_combo.setCurrentIndex(delimiter_index)
        encoding_index = self.encoding_combo.findData(options.get("encoding"))
        if encoding_index >= 0:
            self.encoding_combo.setCurrentIndex(encoding_index)
        if isinstance(options.get("has_header"), bool):
            self.header_check.setChecked(options["has_header"])

    def _invalidate_url(self, *_args: Any) -> None:
        if self._busy:
            return
        self._payload = None
        self._objects = []
        self.object_combo.clear()
        self.object_combo.setEnabled(False)
        self.csv_options.setVisible(False)
        self._clear_preview()
        self.status_label.setText("URL changed. Connect again to refresh the available data.")
        self.status_label.setStyleSheet("color: #526477; padding: 2px 0;")

    def _clear_preview(self) -> None:
        self._candidate = None
        self.preview_model.set_candidate(None)
        self._set_action_buttons_enabled(False)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.connect_button.setEnabled(not busy)
        self.url_edit.setEnabled(not busy)
        self.object_combo.setEnabled(not busy and bool(self._objects))
        self.delimiter_combo.setEnabled(not busy)
        self.encoding_combo.setEnabled(not busy)
        self.header_check.setEnabled(not busy)
        self._set_action_buttons_enabled(not busy and self._candidate is not None)

    def _set_error(self, message: str) -> None:
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: #a12b2b; padding: 2px 0;")

