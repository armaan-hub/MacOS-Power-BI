"""Connection, object selection, preview, and confirmation for SQL Server."""

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
    QSpinBox,
    QTableView,
    QVBoxLayout,
)

from analytics_studio.file_import import ImportCandidate
from analytics_studio.import_preview_dialog import ImportPreviewTableModel, PREVIEW_ROW_LIMIT
from analytics_studio.sql_server import (
    SQLServerError,
    SUPPORTED_DRIVERS,
    list_sql_server_objects,
    read_sql_server_object,
    validate_connection_settings,
)


class SQLServerImportDialog(QDialog):
    """Connect with SQL authentication, select an object, preview, then import."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import from SQL Server")
        self.setMinimumSize(760, 520)
        self.resize(960, 670)
        self._candidate: ImportCandidate | None = None
        self._accepted_candidate: ImportCandidate | None = None
        self._accepted_password = ""
        self._accepted_settings: dict[str, Any] = {}
        self._objects: list[dict[str, str]] = []
        self._busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        heading = QLabel("Connect to SQL Server")
        heading.setStyleSheet("font-size: 19px; font-weight: 600;")
        layout.addWidget(heading)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(7)
        self.server_edit = QLineEdit()
        self.server_edit.setPlaceholderText("server name or IP address")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(1433)
        self.database_edit = QLineEdit()
        self.database_edit.setPlaceholderText("database")
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("SQL Server login")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Password is stored in macOS Keychain after a successful import")
        self.driver_combo = QComboBox()
        self.driver_combo.addItems(SUPPORTED_DRIVERS)
        form.addRow("Server", self.server_edit)
        form.addRow("Port", self.port_spin)
        form.addRow("Database", self.database_edit)
        form.addRow("Username", self.username_edit)
        form.addRow("Password", self.password_edit)
        form.addRow("ODBC driver", self.driver_combo)
        layout.addLayout(form)

        self.connection_note = QLabel(
            "Uses SQL Server username/password authentication over ODBC. Connections require TLS with server certificate validation. "
            "Install Microsoft's SQL Server ODBC Driver 18 if it isn't already installed."
        )
        self.connection_note.setWordWrap(True)
        self.connection_note.setStyleSheet("color: #526477; padding: 2px 0;")
        layout.addWidget(self.connection_note)

        connect_row = QHBoxLayout()
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self._connect)
        connect_row.addWidget(self.connect_button)
        connect_row.addWidget(QLabel("Table or view"))
        self.object_combo = QComboBox()
        self.object_combo.setEnabled(False)
        self.object_combo.currentIndexChanged.connect(self._load_selected_object)
        connect_row.addWidget(self.object_combo, 1)
        layout.addLayout(connect_row)

        self.status_label = QLabel("Enter the connection details, then connect to list tables and views.")
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

        for widget in (
            self.server_edit,
            self.database_edit,
            self.username_edit,
            self.password_edit,
        ):
            widget.textChanged.connect(self._invalidate_connection)
        self.port_spin.valueChanged.connect(self._invalidate_connection)
        self.driver_combo.currentIndexChanged.connect(self._invalidate_connection)

    @property
    def candidate(self) -> ImportCandidate | None:
        return self._accepted_candidate if self.result() == QDialog.DialogCode.Accepted else None

    @property
    def password(self) -> str:
        return self._accepted_password if self.result() == QDialog.DialogCode.Accepted else ""

    @property
    def connection_settings(self) -> dict[str, Any]:
        return dict(self._accepted_settings) if self.result() == QDialog.DialogCode.Accepted else {}

    def _settings(self) -> dict[str, Any]:
        return validate_connection_settings({
            "server": self.server_edit.text(),
            "port": self.port_spin.value(),
            "database": self.database_edit.text(),
            "username": self.username_edit.text(),
            "driver": self.driver_combo.currentText(),
        })

    def _connect(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._clear_preview()
        try:
            settings = self._settings()
            password = self.password_edit.text()
            self._objects = list_sql_server_objects(settings, password)
            self.object_combo.blockSignals(True)
            self.object_combo.clear()
            for item in self._objects:
                label = f"{item['schema']}.{item['table_name']}  ·  {item['table_type'].title()}"
                self.object_combo.addItem(label, item)
            self.object_combo.blockSignals(False)
            self.object_combo.setEnabled(bool(self._objects))
            if not self._objects:
                self.status_label.setText("Connected, but no readable user tables or views were found.")
            else:
                self.status_label.setText(f"Connected · {len(self._objects):,} table(s) and view(s) available.")
        except (SQLServerError, TypeError, ValueError) as exc:
            self.object_combo.blockSignals(False)
            self.object_combo.clear()
            self.object_combo.setEnabled(False)
            self._set_error(str(exc))
        finally:
            self._set_busy(False)
        if self._objects:
            self._load_selected_object(self.object_combo.currentIndex())

    def _load_selected_object(self, index: int) -> None:
        if self._busy or index < 0 or index >= len(self._objects):
            return
        self._set_busy(True)
        self._clear_preview()
        try:
            self._candidate = read_sql_server_object(
                self._settings(),
                self._selected_options(),
                self.password_edit.text(),
                row_limit=PREVIEW_ROW_LIMIT,
            )
            self.preview_model.set_candidate(self._candidate)
            self.status_label.setText(
                f"Preview · showing up to {min(self._candidate.row_count, PREVIEW_ROW_LIMIT):,} rows. "
                "Import data reads the selected table up to the configured row and size limits."
            )
            self.status_label.setStyleSheet("color: #526477; padding: 2px 0;")
            self.import_button.setEnabled(True)
        except (SQLServerError, TypeError, ValueError) as exc:
            self._set_error(str(exc))
        finally:
            self._set_busy(False)

    def _accept_import(self) -> None:
        if self._candidate is None:
            return
        self._set_busy(True)
        self.status_label.setText("Importing selected SQL Server table…")
        try:
            settings = self._settings()
            password = self.password_edit.text()
            candidate = read_sql_server_object(
                settings,
                self._selected_options(),
                password,
            )
        except SQLServerError as exc:
            self._set_error(str(exc))
            self._set_busy(False)
            return
        self._accepted_candidate = candidate
        self._accepted_password = password
        self._accepted_settings = settings
        self.accept()

    def _invalidate_connection(self, *_args: Any) -> None:
        if self._busy:
            return
        self._objects = []
        self.object_combo.clear()
        self.object_combo.setEnabled(False)
        self._clear_preview()
        self.status_label.setText("Connection details changed. Connect again to refresh the object list.")
        self.status_label.setStyleSheet("color: #526477; padding: 2px 0;")

    def _clear_preview(self) -> None:
        self._candidate = None
        self.preview_model.set_candidate(None)
        self.import_button.setEnabled(False)

    def _selected_options(self) -> dict[str, str]:
        selected = dict(self.object_combo.currentData() or {})
        return {
            "schema": str(selected.get("schema", "")),
            "table_name": str(selected.get("table_name", "")),
            "object_type": str(selected.get("table_type", "")),
        }

    def _set_error(self, message: str) -> None:
        self._clear_preview()
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: #a4262c; padding: 2px 0;")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.connect_button.setEnabled(not busy)
        self.server_edit.setEnabled(not busy)
        self.port_spin.setEnabled(not busy)
        self.database_edit.setEnabled(not busy)
        self.username_edit.setEnabled(not busy)
        self.password_edit.setEnabled(not busy)
        self.driver_combo.setEnabled(not busy)
        self.object_combo.setEnabled(not busy and bool(self._objects))
        self.import_button.setEnabled(not busy and self._candidate is not None)
