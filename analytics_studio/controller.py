"""Python state and project lifecycle exposed to the Qt Quick interface."""

from __future__ import annotations

import csv
import re
import zipfile
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    Property,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from analytics_studio.project import (
    ProjectFileError,
    load_project,
    new_project,
    resolve_source_path,
    save_project,
    source_path_for_save,
)
from analytics_studio.data_sources import DATA_SOURCE_CATALOG


PREVIEW_ROW_LIMIT = 500
CHART_TYPES = {"column", "bar", "line"}
CHART_VISUALS = {"Monthly revenue", "Region revenue"}
EXCEL_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
EXCEL_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
SUPPORTED_SOURCE_KINDS = {"csv", "excel"}


class AnalyticsExcelStyles:
    @staticmethod
    def read(workbook: zipfile.ZipFile, main_ns: str) -> tuple[set[int], set[int]]:
        if "xl/styles.xml" not in workbook.namelist():
            return set(), set()
        root = ElementTree.fromstring(workbook.read("xl/styles.xml"))
        custom_formats = {
            int(item.attrib["numFmtId"]): item.attrib.get("formatCode", "")
            for item in root.findall(f"{main_ns}numFmts/{main_ns}numFmt")
            if "numFmtId" in item.attrib
        }
        cell_xfs = root.find(f"{main_ns}cellXfs")
        if cell_xfs is None:
            return set(), set()

        date_styles: set[int] = set()
        time_styles: set[int] = set()
        built_in_dates = set(range(14, 23)) | {45, 46, 47}
        for style_index, style in enumerate(cell_xfs):
            number_format = int(style.attrib.get("numFmtId", "0"))
            format_code = custom_formats.get(number_format, "")
            is_elapsed_time = re.search(r"\[(?:h+|m+|s+)\]", format_code, re.IGNORECASE) is not None
            normalized = re.sub(r'"[^"]*"|\\.|\[[^]]+\]', "", format_code).casefold()
            is_date = not is_elapsed_time and (
                number_format in built_in_dates or any(char in normalized for char in "ymd")
            )
            if is_date:
                date_styles.add(style_index)
                if number_format in {18, 19, 20, 21, 22, 45, 46, 47} or any(
                    char in normalized for char in "hs"
                ):
                    time_styles.add(style_index)
        return date_styles, time_styles


class AnalyticsExcelCell:
    @staticmethod
    def text(
        cell: ElementTree.Element,
        shared_strings: list[str],
        date_styles: set[int],
        time_styles: set[int],
        date_1904: bool,
        main_ns: str,
    ) -> str:
        cell_type = cell.attrib.get("t", "")
        style_index = int(cell.attrib.get("s", "0"))
        if cell_type == "inlineStr":
            inline = cell.find(f"{main_ns}is")
            return "".join(item.text or "" for item in inline.iter(f"{main_ns}t")) if inline is not None else ""

        value = cell.find(f"{main_ns}v")
        raw = value.text if value is not None and value.text is not None else ""
        if cell_type == "s":
            try:
                return shared_strings[int(raw)]
            except (ValueError, IndexError):
                return ""
        if cell_type == "b":
            return "TRUE" if raw == "1" else "FALSE"
        if cell_type in {"str", "e"} or not raw:
            return raw
        if style_index in date_styles:
            try:
                serial = Decimal(raw)
                epoch = datetime(1904, 1, 1) if date_1904 else datetime(1899, 12, 30)
                value_as_date = epoch + timedelta(days=float(serial))
                if style_index in time_styles:
                    return value_as_date.isoformat(sep=" ", timespec="seconds")
                return value_as_date.date().isoformat()
            except (ArithmeticError, ValueError):
                return raw
        try:
            number = Decimal(raw)
            return str(number.quantize(Decimal(1))) if number == number.to_integral_value() else format(number.normalize(), "f")
        except ArithmeticError:
            return raw


class CsvTableModel(QAbstractTableModel):
    """Read-only CSV preview model, limited to the first 500 records."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._headers: list[str] = []
        self._rows: list[dict[str, str | None]] = []

    def replace_data(self, headers: list[str], rows: list[dict[str, str | None]]) -> None:
        self.beginResetModel()
        self._headers = list(headers)
        self._rows = list(rows[:PREVIEW_ROW_LIMIT])
        self.endResetModel()

    def clear(self) -> None:
        self.replace_data([], [])

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802 (Qt API)
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802 (Qt API)
        if parent.isValid():
            return 0
        return len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        if index.row() >= len(self._rows) or index.column() >= len(self._headers):
            return None
        value = self._rows[index.row()].get(self._headers[index.column()], "")
        return value or ""

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:  # noqa: N802 (Qt API)
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self._headers):
            return self._headers[section]
        if orientation == Qt.Orientation.Vertical:
            return section + 1
        return None

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802 (Qt API)
        # Qt Quick TableView delegates can read the standard display role by name.
        return {int(Qt.ItemDataRole.DisplayRole): b"display"}


class StudioController(QObject):
    """Owns application state and exposes deliberate, synchronous QML APIs."""

    stateChanged = Signal()
    statusChanged = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._project = new_project()
        self._project_path: Path | None = None
        self._recovered_from_backup = False
        self._dirty = False
        self._current_view = "Report"
        self._active_page_id = self._project["report"]["active_page_id"]
        self._headers: list[str] = []
        self._rows: list[dict[str, str | None]] = []
        self._source_path: Path | None = None
        self._source_id: str | None = None
        self._source_warning = ""
        self._field_query = ""
        self._current_region: str | None = None
        self._selected_visual = ""
        self._status_message = "Ready · new project"
        self._kpis: dict[str, str] = {}
        self._monthly_series: list[dict[str, str | float]] = []
        self._region_series: list[dict[str, str | float]] = []
        self._model_tables: list[str] = []
        self._model_relationships: list[str] = []
        self._table_model = CsvTableModel(self)
        self._refresh_model_view()
        self._refresh_report()

    # QML-facing state. The dictionaries/lists are returned as fresh QVariant values.
    @Property(str, notify=stateChanged)
    def windowTitle(self) -> str:  # noqa: N802
        suffix = " *" if self._dirty else ""
        return f"Analytics Studio — {self._project.get('name', 'Untitled Project')}{suffix}"

    @Property(str, notify=stateChanged)
    def projectName(self) -> str:  # noqa: N802
        return str(self._project.get("name", "Untitled Project"))

    @Property(str, notify=stateChanged)
    def projectPathLabel(self) -> str:  # noqa: N802
        return self._project_path.name if self._project_path else "Unsaved project"

    @Property(bool, notify=stateChanged)
    def dirty(self) -> bool:
        return self._dirty

    @Property(str, notify=stateChanged)
    def currentView(self) -> str:  # noqa: N802
        return self._current_view

    @Property("QVariantList", notify=stateChanged)
    def pages(self) -> list[dict[str, str]]:
        return [
            {"id": str(page["id"]), "name": str(page["name"])}
            for page in self._project["report"]["pages"]
        ]

    @Property("QVariantList", constant=True)
    def dataSourceCatalog(self) -> list[dict[str, object]]:  # noqa: N802
        """Return category-specific source rows for the UI-only picker catalog."""
        return [dict(item) for item in DATA_SOURCE_CATALOG]

    @Property(int, notify=stateChanged)
    def activePageIndex(self) -> int:  # noqa: N802
        pages = self._project["report"]["pages"]
        return next(
            (index for index, page in enumerate(pages) if page["id"] == self._active_page_id),
            0,
        )

    @Property(str, notify=stateChanged)
    def activePageName(self) -> str:  # noqa: N802
        pages = self._project["report"]["pages"]
        index = self.activePageIndex
        return str(pages[index]["name"]) if pages else ""

    @Property("QVariantList", notify=stateChanged)
    def activePageVisuals(self) -> list[str]:  # noqa: N802
        pages = self._project["report"]["pages"]
        index = self.activePageIndex
        return list(pages[index].get("visuals", [])) if pages else []

    @Property(str, notify=stateChanged)
    def sourceName(self) -> str:  # noqa: N802
        if self._source_path:
            return self._source_path.name
        source = next(
            (item for item in self._project.get("data_sources", [])
             if item.get("kind") in SUPPORTED_SOURCE_KINDS),
            None,
        )
        return str(source.get("name", "")) if source else ""

    @Property(str, notify=stateChanged)
    def sourceIconName(self) -> str:  # noqa: N802
        return "excel" if self._source_path and self._source_path.suffix.casefold() in {".xlsx", ".xlsm"} else "csv"

    @Property(bool, notify=stateChanged)
    def sourceLoaded(self) -> bool:  # noqa: N802
        return self._source_path is not None

    @Property(str, notify=stateChanged)
    def sourceWarning(self) -> str:  # noqa: N802
        return self._source_warning

    @Property(int, notify=stateChanged)
    def rowCount(self) -> int:  # noqa: N802
        return len(self._rows)

    @Property(int, notify=stateChanged)
    def columnCount(self) -> int:  # noqa: N802
        return len(self._headers)

    @Property("QVariantList", notify=stateChanged)
    def headers(self) -> list[str]:
        return list(self._headers)

    @Property(QObject, notify=stateChanged)
    def dataModel(self) -> QObject:  # noqa: N802
        return self._table_model

    @Property("QVariantList", notify=stateChanged)
    def fieldNames(self) -> list[str]:  # noqa: N802
        return list(self._headers)

    @Property("QVariantList", notify=stateChanged)
    def filteredFields(self) -> list[str]:  # noqa: N802
        query = self._field_query.casefold()
        return [field for field in self._headers if query in field.casefold()]

    @Property("QVariantMap", notify=stateChanged)
    def reportKpis(self) -> dict[str, str]:  # noqa: N802
        return dict(self._kpis)

    @Property("QVariantList", notify=stateChanged)
    def monthlySeries(self) -> list[dict[str, str | float]]:  # noqa: N802
        return [dict(item) for item in self._monthly_series]

    @Property("QVariantList", notify=stateChanged)
    def regionSeries(self) -> list[dict[str, str | float]]:  # noqa: N802
        return [dict(item) for item in self._region_series]

    @Property(str, notify=stateChanged)
    def monthlyChartType(self) -> str:  # noqa: N802
        return str(self._project["report"]["chart_types"]["monthly"])

    @Property(str, notify=stateChanged)
    def regionChartType(self) -> str:  # noqa: N802
        return str(self._project["report"]["chart_types"]["region"])

    @Property(str, notify=stateChanged)
    def selectedVisual(self) -> str:  # noqa: N802
        return self._selected_visual

    @Property(str, notify=stateChanged)
    def selectedChartType(self) -> str:  # noqa: N802
        key = self._chart_key(self._selected_visual)
        return str(self._project["report"]["chart_types"].get(key, "")) if key else ""

    @Property("QVariantList", notify=stateChanged)
    def regions(self) -> list[str]:
        values = sorted({str(row.get("Region", "")) for row in self._rows if row.get("Region")})
        return ["All regions", *values]

    @Property(str, notify=stateChanged)
    def currentRegion(self) -> str:  # noqa: N802
        return self._current_region or "All regions"

    @Property(bool, notify=stateChanged)
    def filterActive(self) -> bool:  # noqa: N802
        return self._current_region is not None

    @Property("QVariantList", notify=stateChanged)
    def modelTables(self) -> list[str]:  # noqa: N802
        return list(self._model_tables)

    @Property("QVariantList", notify=stateChanged)
    def modelRelationships(self) -> list[str]:  # noqa: N802
        return list(self._model_relationships)

    @Property(str, notify=statusChanged)
    def statusMessage(self) -> str:  # noqa: N802
        return self._status_message

    # Command entry point shared by the ribbon, menu and keyboard shortcuts.
    @Slot(str)
    def executeCommand(self, command_id: str) -> None:  # noqa: N802
        commands = {
            "newProject": self.new_project_dialog,
            "openProject": self.open_project_dialog,
            "saveProject": self.save_current_project,
            "saveProjectAs": self.save_project_as,
            "importCsv": self.import_csv_dialog,
            "importExcel": self.import_excel_dialog,
            "importData": self.import_data_dialog,
            "refreshSource": self.refresh_source,
            "clearFilters": self.clear_filters,
            "addPage": self.add_page,
            "addMonthlyChart": lambda: self.add_chart("Monthly revenue"),
            "addRegionChart": lambda: self.add_chart("Region revenue"),
            "about": self.show_about,
            "shortcuts": self.show_shortcuts,
            "projectFormat": self.show_project_format,
            "quit": self.quit_application,
        }
        action = commands.get(command_id)
        if action is None:
            self._set_status(f"Unsupported command: {command_id}")
            return
        action()

    @Slot(str, result=bool)
    def connectDataSource(self, source_id: str) -> bool:  # noqa: N802
        """Dispatch only the one connector backed by this application."""
        source = next((item for item in DATA_SOURCE_CATALOG if item["id"] == source_id), None)
        if source is None:
            self._set_status("Unknown data source selection")
            return False
        if not source["implemented"]:
            self._set_status(f"{source['name']} is cataloged; its connector is not implemented.")
            return False
        if source_id == "file_text_csv":
            self.import_csv_dialog()
            return True
        if source_id == "file_excel_workbook":
            self.import_excel_dialog()
            return True
        self._set_status(f"{source['name']} does not have an importer in this release.")
        return False

    @Slot(str, str)
    def reportStagedAction(self, name: str, reason: str) -> None:  # noqa: N802
        """Show honest UI-only feedback for a visible but inactive command."""
        label = (name or "This action").strip()
        detail = (reason or "This workflow is not available in this release.").strip()
        self._set_status(f"{label} · {detail}")

    @Slot(str)
    def setCurrentView(self, view_name: str) -> None:  # noqa: N802
        if view_name not in {"Report", "Data", "Model"}:
            return
        if self._current_view == view_name:
            return
        self._current_view = view_name
        self._dirty = True
        self._set_status(f"{view_name} view")
        self.stateChanged.emit()

    @Slot(int)
    def setActivePage(self, index: int) -> None:  # noqa: N802
        pages = self._project["report"]["pages"]
        if index < 0 or index >= len(pages):
            return
        page_id = pages[index]["id"]
        if self._active_page_id == page_id:
            return
        self._active_page_id = page_id
        self._project["report"]["active_page_id"] = page_id
        self._selected_visual = ""
        self._dirty = True
        self.stateChanged.emit()

    @Slot(str)
    def selectVisual(self, visual_name: str) -> None:  # noqa: N802
        if visual_name not in CHART_VISUALS or visual_name not in self.activePageVisuals:
            return
        if self._selected_visual == visual_name:
            return
        self._selected_visual = visual_name
        self.stateChanged.emit()

    @Slot(str)
    def setChartType(self, chart_type: str) -> None:  # noqa: N802
        key = self._chart_key(self._selected_visual)
        if key is None or chart_type not in CHART_TYPES:
            return
        if self._project["report"]["chart_types"][key] == chart_type:
            return
        self._project["report"]["chart_types"][key] = chart_type
        self._dirty = True
        self.stateChanged.emit()

    @Slot(str)
    def setRegionFilter(self, region: str) -> None:  # noqa: N802
        next_region = None if region in ("", "All regions") else region
        if next_region is not None and next_region not in self.regions:
            return
        if self._current_region == next_region:
            return
        self._current_region = next_region
        self._refresh_report()
        self.stateChanged.emit()

    @Slot(str)
    def setFieldQuery(self, query: str) -> None:  # noqa: N802
        query = query or ""
        if self._field_query == query:
            return
        self._field_query = query
        self.stateChanged.emit()

    @Slot(result=bool)
    def confirmClose(self) -> bool:  # noqa: N802
        return self._confirm_replace_project()

    def new_project_dialog(self) -> None:
        if not self._confirm_replace_project():
            return
        self._replace_with_new_project()

    def open_project_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            None,
            "Open Analytics Studio project",
            "",
            "Analytics Studio projects (*.npa);;JSON files (*.json)",
        )
        if path:
            self.open_project_path(Path(path))

    def open_project_path(self, path: Path) -> bool:
        if not self._confirm_replace_project():
            return False
        path = Path(path).expanduser().resolve()
        try:
            candidate, recovered = load_project(path)
        except ProjectFileError as exc:
            QMessageBox.critical(None, "Could not open project", str(exc))
            return False
        except OSError as exc:
            QMessageBox.critical(None, "Could not open project", str(exc))
            return False

        # Resolve and parse the prospective source before swapping out the live document.
        candidate = deepcopy(candidate)
        for source in candidate.get("data_sources", []):
            source["path"] = str(resolve_source_path(source["path"], path))

        parsed_source: tuple[Path, str, list[str], list[dict[str, str | None]]] | None = None
        warnings: list[str] = []
        source_warning = ""
        source_notices: list[str] = []
        sources = candidate.get("data_sources", [])
        linked_source = next(
            (item for item in sources if item.get("kind") in SUPPORTED_SOURCE_KINDS), None
        )
        if linked_source:
            source_path = Path(linked_source["path"])
            if source_path.is_file():
                try:
                    headers, rows = self._parse_source_file(source_path)
                    parsed_source = (source_path, linked_source["id"], headers, rows)
                except (OSError, UnicodeError, csv.Error, ValueError) as exc:
                    source_warning = f"Could not read linked data file {source_path.name}: {exc}"
                    warnings.append(source_warning)
            else:
                source_warning = f"Linked data file is missing: {source_path}"
                warnings.append(source_warning)
        if len(sources) > 1:
            notice = "Only one data source is loaded in this release; other entries remain in the project."
            warnings.append(notice)
            source_notices.append(notice)
        unsupported = sorted(
            {str(item.get("kind", "unknown")) for item in sources
             if item.get("kind") not in SUPPORTED_SOURCE_KINDS}
        )
        if unsupported:
            notice = f"Unsupported source type(s): {', '.join(unsupported)}."
            warnings.append(notice)
            source_notices.append(notice)
        if source_notices:
            source_warning = "\n".join(([source_warning] if source_warning else []) + source_notices)

        self._project = candidate
        self._project_path = path
        self._recovered_from_backup = recovered
        self._dirty = False
        self._current_view = candidate["active_view"]
        self._active_page_id = candidate["report"]["active_page_id"]
        self._selected_visual = ""
        self._field_query = ""
        self._current_region = None
        if parsed_source:
            source_path, source_id, headers, rows = parsed_source
            self._install_source(source_path, source_id, headers, rows)
        else:
            self._clear_source()
        self._source_warning = source_warning
        self._refresh_model_view()
        self._refresh_report()
        self._dirty = False
        self.stateChanged.emit()
        self._set_status(f"Opened {path.name}" + (" from recovery copy" if recovered else ""))

        if recovered:
            QMessageBox.warning(
                None,
                "Project recovered",
                "The project file was unreadable, so its last known-good backup was opened.\n\n"
                f"Saving will repair the project and keep the recovery copy at {path.name}.bak.",
            )
        if warnings:
            QMessageBox.warning(None, "Some project data is unavailable", "\n".join(warnings))
        return True

    def import_csv_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            None, "Import CSV data", "", "CSV files (*.csv);;All files (*)"
        )
        if path:
            self.import_csv_path(Path(path))

    def import_excel_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            None, "Import Excel workbook", "",
            "Excel workbooks (*.xlsx *.xlsm);;All files (*)",
        )
        if path:
            self.import_excel_path(Path(path))

    def import_data_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            None, "Import data", "",
            "Data files (*.csv *.xlsx *.xlsm);;CSV files (*.csv);;Excel workbooks (*.xlsx *.xlsm)",
        )
        if path:
            source_path = Path(path)
            if source_path.suffix.casefold() == ".csv":
                self.import_csv_path(source_path)
            else:
                self.import_excel_path(source_path)

    def import_csv_path(self, path: Path) -> bool:
        return self._import_data_path(path, "csv")

    def import_excel_path(self, path: Path) -> bool:
        return self._import_data_path(path, "excel")

    def _import_data_path(self, path: Path, source_kind: str) -> bool:
        path = Path(path).expanduser().resolve()
        try:
            if source_kind == "csv":
                headers, rows = self._parse_csv(path)
            else:
                headers, rows = self._parse_excel(path)
        except (OSError, UnicodeError, csv.Error, ValueError) as exc:
            file_type = "CSV" if source_kind == "csv" else "Excel workbook"
            QMessageBox.critical(None, f"Could not import {file_type}", str(exc))
            return False
        existing_sources = list(self._project.get("data_sources", []))
        prior_source = next(
            (item for item in existing_sources
             if item.get("kind") in SUPPORTED_SOURCE_KINDS), None
        )
        source_id = self._source_id or (str(prior_source["id"]) if prior_source else str(uuid4()))
        self._current_region = None
        self._install_source(path, source_id, headers, rows)
        source_record = {"id": source_id, "name": path.name, "kind": source_kind, "path": str(path)}
        updated_sources = []
        source_replaced = False
        for source in existing_sources:
            if source.get("id") == source_id:
                updated_sources.append({**source, **source_record})
                source_replaced = True
            else:
                updated_sources.append(source)
        if not source_replaced:
            updated_sources.append(source_record)
        self._project["data_sources"] = updated_sources
        self._source_warning = self._source_metadata_warning(updated_sources)

        model = self._project.setdefault("model", {"tables": [], "relationships": []})
        tables = list(model.get("tables", []))
        table_record = {"id": source_id, "name": path.stem, "source_id": source_id}
        table_replaced = False
        for index, table in enumerate(tables):
            if table.get("id") == source_id or table.get("source_id") == source_id:
                tables[index] = {**table, **table_record}
                table_replaced = True
                break
        if not table_replaced:
            tables.append(table_record)
        model["tables"] = tables
        self._dirty = True
        self._refresh_model_view()
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status(f"Loaded {path.name} · {len(rows):,} rows")
        return True

    def refresh_source(self) -> None:
        if self._source_path is None or self._source_id is None:
            self._set_status("No data source to refresh")
            return
        try:
            headers, rows = self._parse_source_file(self._source_path)
        except (OSError, UnicodeError, csv.Error, ValueError) as exc:
            self._source_warning = f"Could not read linked data file {self._source_path.name}: {exc}"
            self.stateChanged.emit()
            QMessageBox.critical(None, "Could not refresh source", str(exc))
            return
        self._install_source(self._source_path, self._source_id, headers, rows)
        self._source_warning = self._source_metadata_warning(self._project.get("data_sources", []))
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status(f"Refreshed {self._source_path.name}")

    def add_page(self) -> None:
        pages = self._project["report"]["pages"]
        page = {"id": str(uuid4()), "name": f"Page {len(pages) + 1}", "visuals": []}
        pages.append(page)
        self._active_page_id = page["id"]
        self._project["report"]["active_page_id"] = page["id"]
        self._selected_visual = ""
        self._dirty = True
        self.stateChanged.emit()
        self._set_status(f"Added {page['name']}")

    def add_chart(self, visual_name: str) -> None:
        if visual_name not in CHART_VISUALS:
            return
        page = self._project["report"]["pages"][self.activePageIndex]
        visuals = page.setdefault("visuals", [])
        if visual_name not in visuals:
            visuals.append(visual_name)
            self._dirty = True
        self._selected_visual = visual_name
        self.stateChanged.emit()
        self._set_status(f"Added {visual_name}")

    def clear_filters(self) -> None:
        if self._current_region is None:
            return
        self._current_region = None
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status("Region filter cleared")

    def show_about(self) -> None:
        QMessageBox.about(
            None,
            "About Analytics Studio",
            "Analytics Studio\nA native desktop analytics authoring workspace.",
        )

    def show_shortcuts(self) -> None:
        QMessageBox.information(
            None,
            "Keyboard shortcuts",
            "New Project: ⌘N / Ctrl+N\nOpen Project: ⌘O / Ctrl+O\n"
            "Save Project: ⌘S / Ctrl+S\nSave As: ⇧⌘S / Ctrl+Shift+S",
        )

    def show_project_format(self) -> None:
        QMessageBox.information(
            None,
            "Project format",
            "Analytics Studio projects use the versioned, human-readable .npa JSON format. "
            "Imported files stay linked as external sources. A .bak recovery copy is kept on later saves.",
        )

    def quit_application(self) -> None:
        if self._confirm_replace_project():
            QApplication.quit()

    def save_current_project(self) -> bool:
        if self._project_path is None:
            return self.save_project_as()
        return self._save_to(self._project_path)

    def save_project_as(self) -> bool:
        suggested = f"{self.projectName}.npa"
        path, _ = QFileDialog.getSaveFileName(
            None, "Save Analytics Studio project", suggested, "Analytics Studio project (*.npa)"
        )
        if not path:
            return False
        if not path.lower().endswith(".npa"):
            path += ".npa"
        return self._save_to(Path(path))

    def _save_to(self, path: Path) -> bool:
        path = Path(path).expanduser().resolve()
        candidate = self._document_for_save(path)
        try:
            saved = save_project(
                path,
                candidate,
                recovered_from_backup=(
                    self._recovered_from_backup and path == self._project_path
                ),
            )
        except (OSError, ProjectFileError) as exc:
            QMessageBox.critical(None, "Could not save project", str(exc))
            return False

        self._project = saved
        self._project_path = path
        self._recovered_from_backup = False
        self._dirty = False
        self._active_page_id = saved["report"]["active_page_id"]
        self.stateChanged.emit()
        self._set_status(f"Saved {path.name}")
        return True

    def _document_for_save(self, path: Path) -> dict[str, Any]:
        document = deepcopy(self._project)
        document["name"] = path.stem if path != self._project_path else self.projectName
        document["active_view"] = self._current_view
        document["report"]["active_page_id"] = self._active_page_id
        document["report"]["chart_types"] = {
            "monthly": self.monthlyChartType,
            "region": self.regionChartType,
        }

        if self._source_path is not None and self._source_id is not None:
            source_record = {
                "id": self._source_id,
                "name": self._source_path.name,
                "kind": self._source_kind_for_path(self._source_path),
                "path": source_path_for_save(self._source_path, path),
            }
            source_replaced = False
            for index, source in enumerate(document.get("data_sources", [])):
                if source.get("id") == self._source_id:
                    document["data_sources"][index] = {**source, **source_record}
                    source_replaced = True
                else:
                    source["path"] = self._source_path_for_save(source["path"], path)
            if not source_replaced:
                document.setdefault("data_sources", []).append(source_record)

            table_record = {
                "id": self._source_id,
                "name": self._source_path.stem,
                "source_id": self._source_id,
            }
            tables = document["model"].setdefault("tables", [])
            for index, table in enumerate(tables):
                if table.get("id") == self._source_id or table.get("source_id") == self._source_id:
                    tables[index] = {**table, **table_record}
                    break
            else:
                tables.append(table_record)
        else:
            # Paths were resolved on open so Save As can preserve links from the new location.
            for source in document.get("data_sources", []):
                source["path"] = self._source_path_for_save(source["path"], path)
        return document

    def _source_path_for_save(self, stored_path: str, destination: Path) -> str:
        source_path = Path(stored_path).expanduser()
        if not source_path.is_absolute() and self._project_path is not None:
            source_path = resolve_source_path(stored_path, self._project_path)
        if source_path.is_absolute():
            return source_path_for_save(source_path, destination)
        return stored_path

    def _confirm_replace_project(self) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            None,
            "Unsaved project changes",
            "Save changes to this project before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_current_project()
        return answer == QMessageBox.StandardButton.Discard

    def _replace_with_new_project(self) -> None:
        self._project = new_project()
        self._project_path = None
        self._recovered_from_backup = False
        self._dirty = False
        self._current_view = "Report"
        self._active_page_id = self._project["report"]["active_page_id"]
        self._selected_visual = ""
        self._field_query = ""
        self._current_region = None
        self._clear_source()
        self._refresh_model_view()
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status("New project")

    @staticmethod
    def _parse_csv(path: Path) -> tuple[list[str], list[dict[str, str | None]]]:
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            headers = list(reader.fieldnames or [])
            rows = list(reader)
        return headers, rows

    @classmethod
    def _parse_source_file(cls, path: Path) -> tuple[list[str], list[dict[str, str | None]]]:
        if path.suffix.casefold() == ".csv":
            return cls._parse_csv(path)
        return cls._parse_excel(path)

    @staticmethod
    def _source_kind_for_path(path: Path) -> str:
        return "csv" if path.suffix.casefold() == ".csv" else "excel"

    @staticmethod
    def _parse_excel(path: Path) -> tuple[list[str], list[dict[str, str | None]]]:
        if path.suffix.casefold() not in {".xlsx", ".xlsm"}:
            raise ValueError("Choose an .xlsx or .xlsm workbook. Legacy .xls files are not supported.")

        try:
            with zipfile.ZipFile(path) as workbook:
                main_ns = f"{{{EXCEL_MAIN_NS}}}"
                relationship_ns = f"{{{EXCEL_REL_NS}}}id"
                workbook_root = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
                sheets = workbook_root.findall(f"{main_ns}sheets/{main_ns}sheet")
                if not sheets:
                    raise ValueError("The workbook does not contain a worksheet.")

                workbook_rels = ElementTree.fromstring(
                    workbook.read("xl/_rels/workbook.xml.rels")
                )
                targets = {
                    relationship.attrib.get("Id", ""): relationship.attrib.get("Target", "")
                    for relationship in workbook_rels.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
                }
                target = targets.get(sheets[0].attrib.get(relationship_ns, ""), "")
                if not target:
                    raise ValueError("The workbook's first worksheet could not be found.")
                if target.startswith("/"):
                    sheet_path = target.lstrip("/")
                elif target.startswith("xl/"):
                    sheet_path = target
                else:
                    import posixpath
                    sheet_path = posixpath.normpath(posixpath.join("xl", target))

                shared_strings = []
                if "xl/sharedStrings.xml" in workbook.namelist():
                    shared_root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
                    shared_strings = [
                        "".join(node.text or "" for node in item.iter(f"{main_ns}t"))
                        for item in shared_root.findall(f"{main_ns}si")
                    ]

                date_styles, time_styles = AnalyticsExcelStyles.read(workbook, main_ns)
                workbook_properties = workbook_root.find(f"{main_ns}workbookPr")
                date_1904 = bool(
                    workbook_properties is not None
                    and workbook_properties.attrib.get("date1904", "0").casefold() in {"1", "true"}
                )
                sheet_root = ElementTree.fromstring(workbook.read(sheet_path))
                sheet_data = sheet_root.find(f"{main_ns}sheetData")
                if sheet_data is None:
                    raise ValueError("The first worksheet is empty.")

                rows_by_number: list[list[str]] = []
                max_column = 0
                for row in sheet_data.findall(f"{main_ns}row"):
                    values: dict[int, str] = {}
                    next_column = 0
                    for cell in row.findall(f"{main_ns}c"):
                        reference = cell.attrib.get("r", "")
                        match = re.match(r"([A-Z]+)", reference.upper())
                        if match:
                            column = 0
                            for letter in match.group(1):
                                column = column * 26 + ord(letter) - ord("A") + 1
                            column -= 1
                        else:
                            column = next_column
                        next_column = column + 1
                        max_column = max(max_column, column + 1)
                        values[column] = AnalyticsExcelCell.text(
                            cell, shared_strings, date_styles, time_styles, date_1904, main_ns
                        )
                    rows_by_number.append([values.get(index, "") for index in range(max_column)])
                rows_by_number = [
                    row + [""] * (max_column - len(row)) for row in rows_by_number
                ]
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
            raise ValueError("This is not a readable Excel .xlsx/.xlsm workbook.") from exc

        header_index = next(
            (index for index, row in enumerate(rows_by_number) if any(value.strip() for value in row)),
            None,
        )
        if header_index is None:
            raise ValueError("The first worksheet has no data.")

        raw_headers = rows_by_number[header_index]
        headers = []
        for index, value in enumerate(raw_headers):
            name = value.strip() or f"Column {index + 1}"
            unique_name = name
            duplicate = 2
            while unique_name in headers:
                unique_name = f"{name}_{duplicate}"
                duplicate += 1
            headers.append(unique_name)

        data_rows = []
        for values in rows_by_number[header_index + 1:]:
            if not any(value.strip() for value in values):
                continue
            data_rows.append({
                header: values[index] if index < len(values) else ""
                for index, header in enumerate(headers)
            })
        return headers, data_rows

    def _install_source(
        self,
        path: Path,
        source_id: str,
        headers: list[str],
        rows: list[dict[str, str | None]],
    ) -> None:
        self._source_path = path
        self._source_id = source_id
        self._headers = list(headers)
        self._rows = list(rows)
        self._table_model.replace_data(headers, rows)
        if self._current_region not in self.regions:
            self._current_region = None

    def _clear_source(self) -> None:
        self._source_path = None
        self._source_id = None
        self._headers = []
        self._rows = []
        self._current_region = None
        self._source_warning = ""
        self._table_model.clear()

    def _refresh_report(self) -> None:
        if self._source_path is None:
            self._kpis = {name: "—" for name in ("Revenue", "Cost", "Margin", "Units", "Orders")}
            self._monthly_series = []
            self._region_series = []
            return

        rows = [
            row
            for row in self._rows
            if self._current_region is None or row.get("Region") == self._current_region
        ]

        def amount(value: Any) -> Decimal:
            try:
                return Decimal(value) if value else Decimal(0)
            except (ArithmeticError, ValueError, TypeError):
                return Decimal(0)

        sums = {
            key: sum((amount(row.get(key, "")) for row in rows), Decimal(0))
            for key in ("Revenue", "Cost", "Margin", "Units")
            if key in self._headers
        }
        self._kpis = {
            key: (
                f"{sums[key]:,.2f}"
                if key in ("Cost", "Margin")
                else f"{sums[key]:,.0f}"
            )
            for key in sums
        }
        for key in ("Revenue", "Cost", "Margin", "Units"):
            self._kpis.setdefault(key, "—")
        self._kpis["Orders"] = f"{len(rows):,}"

        monthly: defaultdict[str, Decimal] = defaultdict(Decimal)
        regions: defaultdict[str, Decimal] = defaultdict(Decimal)
        for row in rows:
            if "Revenue" not in self._headers:
                continue
            revenue = amount(row.get("Revenue", ""))
            if "Order Date" in self._headers:
                monthly[str(row.get("Order Date", "") or "")[:7]] += revenue
            if "Region" in self._headers:
                regions[str(row.get("Region", "Unknown") or "Unknown")] += revenue
        self._monthly_series = [
            {"label": key, "value": float(value)} for key, value in sorted(monthly.items())
        ]
        self._region_series = [
            {"label": key, "value": float(value)} for key, value in sorted(regions.items())
        ]

    def _refresh_model_view(self) -> None:
        model = self._project.get("model", {})
        self._model_tables = [
            str(table.get("name", "Unnamed table")) for table in model.get("tables", [])
        ]
        self._model_relationships = [
            f"{relationship.get('from', '?')} → {relationship.get('to', '?')}"
            for relationship in model.get("relationships", [])
        ]

    @staticmethod
    def _source_metadata_warning(sources: list[dict[str, Any]]) -> str:
        notices = []
        if len(sources) > 1:
            notices.append(
                "Only one data source is loaded in this release; other entries remain in the project."
            )
        unsupported = sorted(
            {str(item.get("kind", "unknown")) for item in sources
             if item.get("kind") not in SUPPORTED_SOURCE_KINDS}
        )
        if unsupported:
            notices.append(f"Unsupported source type(s): {', '.join(unsupported)}.")
        return "\n".join(notices)

    def _chart_key(self, visual_name: str) -> str | None:
        return {"Monthly revenue": "monthly", "Region revenue": "region"}.get(visual_name)

    def _set_status(self, message: str) -> None:
        self._status_message = message
        self.statusChanged.emit(message)
