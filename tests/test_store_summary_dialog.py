"""Summary dialog for a large-data table and its controller hooks (Stage B4b task 14)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QTableWidget

from analytics_studio.controller import StudioController
from analytics_studio.store import stats as st
from analytics_studio.store.candidate import StoreCandidate
from analytics_studio.store.stats import ColumnStat, TableStats

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(["Analytics Studio tests"])


def _col(name: str, label: str, stored: str, rows: int, *, nulls: int = 0,
         empties: int = 0, distinct: int = 0, max_chars: int = 0,
         avg_chars: float = 0.0, approx: int = 0,
         warnings: tuple[str, ...] = ()) -> ColumnStat:
    return ColumnStat(
        name=name, label=label, stored_type=stored, rows=rows,
        null_count=nulls, empty_count=empties, distinct_approx=distinct,
        max_chars=max_chars, avg_chars=avg_chars, approx_bytes=approx,
        warnings=warnings,
    )


def _sample_stats(table_warnings: tuple[str, ...] = ("The table has 101 columns. Wide tables use much more memory; keep only the columns you need.",)) -> TableStats:
    columns = (
        _col("order_id", "whole_number", "whole", 10, distinct=10, approx=80),
        _col("code", "text", "text", 10, nulls=7, empties=2, distinct=1,
             max_chars=3, avg_chars=2.5, approx=40,
             warnings=("Column 'code' is almost empty (90% of cells are empty).",)),
        _col("description", "text", "text", 10, distinct=10, max_chars=1500,
             avg_chars=812.5, approx=9000),
    )
    return TableStats(table="sales", rows=10, columns=columns,
                      approx_bytes=9120, warnings=table_warnings)


def _sort_stats() -> TableStats:
    columns = (
        _col("large", "whole_number", "whole", 10, approx=10),
        _col("small", "whole_number", "whole", 9, approx=9),
    )
    return TableStats(table="t", rows=10, columns=columns, approx_bytes=19, warnings=())


def _dialog(stats: TableStats, name: str = "Sales"):
    from analytics_studio.store.summary_dialog import LargeTableSummaryDialog
    return LargeTableSummaryDialog(name, stats)


HEADERS = ["Column", "Type", "Rows", "Blank cells", "Empty text", "Distinct values",
           "Longest text", "Average text length", "Approx. size", "Notes"]


def _cell(dialog: Any, row: int, col: int) -> str:
    return dialog.summary_table.item(row, col).text()


def test_dialog_header_and_title(qapp: QApplication) -> None:
    dialog = _dialog(_sample_stats())
    assert dialog.windowTitle() == "Large-data table summary"
    assert dialog.header_label.text() == "Sales: 10 rows, 3 columns, about 8.9 KB in memory"
    assert dialog.minimumWidth() >= 760
    assert dialog.minimumHeight() >= 420
    dialog.deleteLater()


def test_dialog_uses_light_stylesheet(qapp: QApplication) -> None:
    from analytics_studio.dialog_theme import LIGHT_DIALOG_STYLESHEET
    dialog = _dialog(_sample_stats())
    assert dialog.styleSheet() == LIGHT_DIALOG_STYLESHEET
    dialog.deleteLater()


def test_dialog_size_units_and_thousands(qapp: QApplication) -> None:
    big = TableStats(table="big", rows=1_234_567, columns=(
        _col("a", "whole_number", "whole", 1_234_567, approx=3 * 1024 ** 3),
    ), approx_bytes=3 * 1024 ** 3, warnings=())
    dialog = _dialog(big, name="big")
    assert dialog.header_label.text() == "big: 1,234,567 rows, 1 columns, about 3.0 GB in memory"
    dialog.deleteLater()


def test_dialog_column_headers(qapp: QApplication) -> None:
    dialog = _dialog(_sample_stats())
    table = dialog.summary_table
    assert isinstance(table, QTableWidget)
    assert table.isSortingEnabled()
    assert [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())] == HEADERS
    assert table.rowCount() == 3
    assert table.editTriggers() == QTableWidget.EditTrigger.NoEditTriggers
    dialog.deleteLater()


def test_dialog_every_cell_text_in_source_order(qapp: QApplication) -> None:
    dialog = _dialog(_sample_stats())
    expected = [
        ["order_id", "whole_number", "10", "0", "0", "10", "0", "0.0", "80", ""],
        ["code", "text", "10", "7", "2", "1", "3", "2.5", "40",
         "Column 'code' is almost empty (90% of cells are empty)."],
        ["description", "text", "10", "0", "0", "10", "1,500", "812.5", "9,000", ""],
    ]
    for r, values in enumerate(expected):
        for c, value in enumerate(values):
            assert _cell(dialog, r, c) == value, (r, c)
    dialog.deleteLater()


def test_dialog_numbers_right_aligned_text_left(qapp: QApplication) -> None:
    dialog = _dialog(_sample_stats())
    table = dialog.summary_table
    for c in range(2, 9):
        align = table.item(0, c).textAlignment()
        assert align & Qt.AlignmentFlag.AlignRight, c
    for c in (0, 1, 9):
        align = table.item(0, c).textAlignment()
        assert not (align & Qt.AlignmentFlag.AlignRight), c
    dialog.deleteLater()


def test_dialog_numeric_user_role_values(qapp: QApplication) -> None:
    dialog = _dialog(_sample_stats())
    table = dialog.summary_table
    assert table.item(1, 2).data(Qt.ItemDataRole.UserRole) == 10
    assert table.item(1, 3).data(Qt.ItemDataRole.UserRole) == 7
    assert table.item(2, 6).data(Qt.ItemDataRole.UserRole) == 1500
    assert table.item(2, 7).data(Qt.ItemDataRole.UserRole) == pytest.approx(812.5)
    assert table.item(2, 8).data(Qt.ItemDataRole.UserRole) == 9000
    dialog.deleteLater()


def test_amber_only_on_warned_row(qapp: QApplication) -> None:
    dialog = _dialog(_sample_stats())
    table = dialog.summary_table
    amber_rows = []
    for r in range(table.rowCount()):
        brush = table.item(r, 0).background()
        if brush.style() != Qt.BrushStyle.NoBrush and brush.color().name() == "#fff4d6":
            amber_rows.append(r)
    assert amber_rows == [1]
    for c in range(table.columnCount()):
        assert table.item(1, c).background().color().name() == "#fff4d6"
        assert table.item(1, c).foreground().color().name() == "#243746"
    dialog.deleteLater()


def test_sort_by_rows_is_numeric(qapp: QApplication) -> None:
    dialog = _dialog(_sort_stats())
    table = dialog.summary_table
    table.sortByColumn(2, Qt.SortOrder.AscendingOrder)
    assert [_cell(dialog, r, 0) for r in range(2)] == ["small", "large"]
    table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
    assert [_cell(dialog, r, 0) for r in range(2)] == ["large", "small"]
    dialog.deleteLater()


def test_sort_by_approx_size_is_numeric(qapp: QApplication) -> None:
    dialog = _dialog(_sort_stats())
    table = dialog.summary_table
    table.sortByColumn(8, Qt.SortOrder.AscendingOrder)
    assert [_cell(dialog, r, 0) for r in range(2)] == ["small", "large"]
    dialog.deleteLater()


def test_ok_button_is_default(qapp: QApplication) -> None:
    dialog = _dialog(_sample_stats())
    assert dialog.ok_button.text() == "OK"
    assert dialog.ok_button.isDefault()
    dialog.deleteLater()


def test_table_warnings_listed(qapp: QApplication) -> None:
    dialog = _dialog(_sample_stats())
    assert dialog.warnings_label.text() == (
        "The table has 101 columns. Wide tables use much more memory; keep only the columns you need."
    )
    dialog.deleteLater()


def test_no_table_warnings_says_no_warnings(qapp: QApplication) -> None:
    dialog = _dialog(_sample_stats(table_warnings=()))
    assert dialog.warnings_label.text() == "No warnings."
    dialog.deleteLater()


def test_multiple_table_warnings_one_per_line(qapp: QApplication) -> None:
    dialog = _dialog(_sample_stats(table_warnings=("First warning.", "Second warning.")))
    assert dialog.warnings_label.text().split("\n") == ["First warning.", "Second warning."]
    dialog.deleteLater()


def test_notes_join_multiple_warnings(qapp: QApplication) -> None:
    stats = TableStats(table="t", rows=5, columns=(
        _col("c", "text", "text", 5, nulls=5, distinct=1, max_chars=2000, approx=10,
             warnings=("First note.", "Second note.")),
    ), approx_bytes=10, warnings=())
    dialog = _dialog(stats)
    assert _cell(dialog, 0, 9) == "First note.; Second note."
    dialog.deleteLater()


# ---------------------------------------------------------------- controller

def _wait_for_large_job(controller: StudioController, timeout: float = 30.0) -> None:
    import time
    qapp = QApplication.instance()
    deadline = time.monotonic() + timeout
    while controller._large_import_job is not None and time.monotonic() < deadline:
        if qapp is not None:
            qapp.processEvents()
        time.sleep(0.01)
    if qapp is not None:
        qapp.processEvents()
    if controller._large_import_job is not None:
        raise TimeoutError("Large import job timed out.")


def _generate_csv(path: Path, rows: int = 2000) -> Path:
    lines = ["id,name,score,is_active,created_at"]
    for i in range(rows):
        lines.append(f"{i},name_{i},{i * 1.5},{'true' if i % 2 == 0 else 'false'},2026-01-01 12:00:00")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class _FakeLargeDialog:
    def __init__(self, path: Path, **kwargs: Any) -> None:
        self.path = Path(path)
        self.kwargs = kwargs
        self.candidate = None
        self.large_request = {
            "path": str(self.path.resolve()),
            "kind": "csv",
            "options": {"delimiter": ",", "has_header": True},
            "limit_kind": "rows",
        }
        self.selected_action = "load"

    def exec(self) -> int:
        return 1


def _import_csv(controller: StudioController, csv_file: Path) -> None:
    with patch_preview():
        with _patched_question():
            assert controller._import_file_path(csv_file) is True
    _wait_for_large_job(controller)


def patch_preview():
    from unittest.mock import patch
    return patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog)


def _patched_question():
    from unittest.mock import patch
    return patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []

    def fake(self: StudioController, candidate: Any) -> None:
        calls.append(candidate)

    monkeypatch.setattr(StudioController, "_run_store_summary_dialog", fake)
    return calls


def test_clean_import_does_not_show_summary(qapp: QApplication, tmp_path: Path, recorder: list[Any]) -> None:
    csv_file = _generate_csv(tmp_path / "clean.csv")
    controller = StudioController()
    try:
        _import_csv(controller, csv_file)
        assert controller.sourceLoaded is True
        assert controller._active_store_candidate.stats is not None
        assert recorder == []
    finally:
        controller._close_project_store()


def test_warned_import_shows_summary_once(qapp: QApplication, tmp_path: Path, recorder: list[Any],
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(st, "_UNIQUE_MIN_ROWS", 10)
    csv_file = _generate_csv(tmp_path / "warned.csv")
    controller = StudioController()
    try:
        _import_csv(controller, csv_file)
        candidate = controller._active_store_candidate
        assert len(recorder) == 1
        assert recorder[0] is candidate
        assert any(w for c in candidate.stats.columns for w in c.warnings)
    finally:
        controller._close_project_store()


def test_slot_without_store_table_sets_status(qapp: QApplication, recorder: list[Any]) -> None:
    controller = StudioController()
    controller.showLargeTableSummary()
    assert controller.statusMessage == "Open a large-data table first."
    assert recorder == []


def test_slot_after_reopen_without_stats_sets_status(qapp: QApplication, tmp_path: Path,
                                                     recorder: list[Any]) -> None:
    csv_file = _generate_csv(tmp_path / "reopen.csv")
    controller = StudioController()
    try:
        _import_csv(controller, csv_file)
        del controller._active_store_candidate.stats
        controller.showLargeTableSummary()
        assert controller.statusMessage == (
            "Summary statistics are not available for this table. Import the file again to compute them."
        )
        assert recorder == []
    finally:
        controller._close_project_store()


def test_slot_with_stats_calls_dialog(qapp: QApplication, tmp_path: Path, recorder: list[Any]) -> None:
    csv_file = _generate_csv(tmp_path / "slot.csv")
    controller = StudioController()
    try:
        _import_csv(controller, csv_file)
        assert recorder == []
        controller.showLargeTableSummary()
        assert len(recorder) == 1
        assert recorder[0] is controller._active_store_candidate
    finally:
        controller._close_project_store()


def test_dialog_exception_does_not_undo_import(qapp: QApplication, tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch,
                                               caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(st, "_UNIQUE_MIN_ROWS", 10)

    def boom(self: StudioController, candidate: Any) -> None:
        raise RuntimeError("dialog broke")

    monkeypatch.setattr(StudioController, "_run_store_summary_dialog", boom)
    csv_file = _generate_csv(tmp_path / "boom.csv")
    controller = StudioController()
    try:
        with caplog.at_level(logging.WARNING, logger="analytics_studio.controller"):
            _import_csv(controller, csv_file)
        assert controller.sourceLoaded is True
        assert controller.rowCount == 2000
        assert isinstance(controller._active_store_candidate, StoreCandidate)
        assert controller._project["data_sources"]
        assert controller.statusMessage == (
            f"Loaded 2,000 rows into the large-data store: {csv_file.name}."
        )
        assert any("dialog broke" in r.getMessage() or "dialog broke" in str(r.exc_info)
                   for r in caplog.records if r.levelno == logging.WARNING)
    finally:
        controller._close_project_store()


def test_controller_import_does_not_load_summary_module() -> None:
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(REPO_ROOT)
    code = (
        "import sys\n"
        "import analytics_studio.controller\n"
        "print('analytics_studio.store.summary_dialog' in sys.modules)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=str(REPO_ROOT), env=env,
                         capture_output=True, text=True, timeout=120, check=True)
    assert out.stdout.strip().splitlines()[-1] == "False"


def test_large_table_loaded_property(qapp: QApplication, tmp_path: Path, recorder: list[Any]) -> None:
    controller = StudioController()
    assert controller.largeTableLoaded is False
    csv_file = _generate_csv(tmp_path / "prop.csv")
    try:
        _import_csv(controller, csv_file)
        assert controller.largeTableLoaded is True
    finally:
        controller._close_project_store()


def test_qml_has_table_summary_entry() -> None:
    text = (REPO_ROOT / "analytics_studio" / "qml" / "DataView.qml").read_text(encoding="utf-8")
    assert 'text: "Table summary"' in text
    assert "root.appController.showLargeTableSummary()" in text
    assert "enabled: root.appController.largeTableLoaded" in text
