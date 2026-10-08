"""Service-root navigation, preview, and confirmation for OData Feed."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
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
)

from analytics_studio.file_import import ImportCandidate
from analytics_studio.import_preview_dialog import ImportPreviewTableModel, PREVIEW_ROW_LIMIT
from analytics_studio.odata import ODataError, list_odata_entity_sets, read_odata_entity_set, validate_service_root


class ODataFeedImportDialog(QDialog):
    """Connect anonymously to an HTTPS OData v4 service and select an entity set."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import from OData Feed")
        self.setMinimumSize(760, 520)
        self.resize(960, 670)
        self._entity_sets: list[dict[str, str]] = []
        self._candidate: ImportCandidate | None = None
        self._accepted_candidate: ImportCandidate | None = None
        self._accepted_service_root = ""
        self._busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        heading = QLabel("Connect to an OData Feed")
        heading.setStyleSheet("font-size: 19px; font-weight: 600;")
        layout.addWidget(heading)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(7)
        self.service_root_edit = QLineEdit()
        self.service_root_edit.setPlaceholderText("https://example.com/odata/")
        form.addRow("Service root URL", self.service_root_edit)
        layout.addLayout(form)

        self.connection_note = QLabel(
            "This importer supports anonymous OData v4 over HTTPS. The server certificate is validated. "
            "Basic, Windows, and organizational sign-in are not supported yet."
        )
        self.connection_note.setWordWrap(True)
        self.connection_note.setStyleSheet("color: #526477; padding: 2px 0;")
        layout.addWidget(self.connection_note)

        connect_row = QHBoxLayout()
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self._connect)
        connect_row.addWidget(self.connect_button)
        connect_row.addWidget(QLabel("Entity set"))
        self.entity_set_combo = QComboBox()
        self.entity_set_combo.setEnabled(False)
        self.entity_set_combo.currentIndexChanged.connect(self._load_selected_entity_set)
        connect_row.addWidget(self.entity_set_combo, 1)
        layout.addLayout(connect_row)

        self.status_label = QLabel("Enter an HTTPS service root URL, then connect to list entity sets.")
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
        self.import_button = QPushButton("Import data")
        self.import_button.setEnabled(False)
        buttons.addButton(self.import_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        self.import_button.clicked.connect(self._accept_import)
        layout.addWidget(buttons)

        self.service_root_edit.textChanged.connect(self._invalidate_connection)

    @property
    def candidate(self) -> ImportCandidate | None:
        return self._accepted_candidate if self.result() == QDialog.DialogCode.Accepted else None

    @property
    def service_root(self) -> str:
        return self._accepted_service_root if self.result() == QDialog.DialogCode.Accepted else ""

    def _root(self) -> str:
        return validate_service_root(self.service_root_edit.text())

    def _connect(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._clear_preview()
        try:
            service_root = self._root()
            self._entity_sets = list_odata_entity_sets(service_root)
            self.entity_set_combo.blockSignals(True)
            self.entity_set_combo.clear()
            for item in self._entity_sets:
                self.entity_set_combo.addItem(item["entity_set_name"], item)
            self.entity_set_combo.blockSignals(False)
            self.entity_set_combo.setEnabled(bool(self._entity_sets))
            if not self._entity_sets:
                self.status_label.setText("Connected, but the service document has no entity sets.")
            else:
                self.status_label.setText(
                    f"Connected · {len(self._entity_sets):,} entity set(s) available."
                )
                self.status_label.setStyleSheet("color: #526477; padding: 2px 0;")
        except (ODataError, TypeError, ValueError) as exc:
            self.entity_set_combo.blockSignals(False)
            self.entity_set_combo.clear()
            self.entity_set_combo.setEnabled(False)
            self._set_error(str(exc))
        finally:
            self._set_busy(False)
        if self._entity_sets:
            self._load_selected_entity_set(self.entity_set_combo.currentIndex())

    def _load_selected_entity_set(self, index: int) -> None:
        if self._busy or index < 0 or index >= len(self._entity_sets):
            return
        self._set_busy(True)
        self._clear_preview()
        try:
            self._candidate = read_odata_entity_set(
                {"service_root": self._root()},
                self._selected_options(),
                row_limit=PREVIEW_ROW_LIMIT,
            )
            self.preview_model.set_candidate(self._candidate)
            notice = f" {' '.join(self._candidate.notices)}" if self._candidate.notices else ""
            self.status_label.setText(
                f"Preview · showing up to {min(self._candidate.row_count, PREVIEW_ROW_LIMIT):,} rows. "
                f"Import data follows OData next-page links within local limits.{notice}"
            )
            self.status_label.setStyleSheet("color: #526477; padding: 2px 0;")
            self.import_button.setEnabled(True)
        except (ODataError, TypeError, ValueError) as exc:
            self._set_error(str(exc))
        finally:
            self._set_busy(False)

    def _accept_import(self) -> None:
        if self._candidate is None:
            return
        self._set_busy(True)
        self.status_label.setText("Importing selected OData entity set…")
        try:
            service_root = self._root()
            candidate = read_odata_entity_set(
                {"service_root": service_root}, self._selected_options()
            )
        except (ODataError, TypeError, ValueError) as exc:
            self._set_error(str(exc))
            self._set_busy(False)
            return
        self._accepted_candidate = candidate
        self._accepted_service_root = service_root
        self.accept()

    def _selected_options(self) -> dict[str, str]:
        value = self.entity_set_combo.currentData()
        return dict(value) if isinstance(value, dict) else {}

    def _invalidate_connection(self, *_args: Any) -> None:
        if self._busy:
            return
        self._entity_sets = []
        self.entity_set_combo.clear()
        self.entity_set_combo.setEnabled(False)
        self._clear_preview()
        self.status_label.setText("Service root changed. Connect again to refresh the entity-set list.")
        self.status_label.setStyleSheet("color: #526477; padding: 2px 0;")

    def _clear_preview(self) -> None:
        self._candidate = None
        self.preview_model.set_candidate(None)
        self.import_button.setEnabled(False)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.connect_button.setEnabled(not busy)
        self.service_root_edit.setEnabled(not busy)
        self.entity_set_combo.setEnabled(not busy and bool(self._entity_sets))
        self.import_button.setEnabled(not busy and self._candidate is not None)

    def _set_error(self, message: str) -> None:
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: #a12b2b; padding: 2px 0;")
