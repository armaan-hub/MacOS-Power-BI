"""Import preview dialog: large mode is off by default and, when on, previews the first 1,000 rows."""

from __future__ import annotations

import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from PySide6.QtWidgets import QApplication

from analytics_studio import file_import
from analytics_studio import import_preview_dialog as dialog_module
from analytics_studio.file_import import FileImportError
from analytics_studio.import_preview_dialog import FileImportPreviewDialog

LARGE_NOTICE = "Showing the first 1,000 of a large file. It will be loaded into the large-data store."


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication(["Analytics Studio tests"])


@pytest.fixture
def small_limit(monkeypatch) -> None:
    monkeypatch.setattr(file_import, "MAX_DATA_ROWS", 500)


def _csv(tmp_path: Path, rows: int = 3000, delimiter: str = ",", name: str = "big.csv") -> Path:
    path = tmp_path / name
    lines = [f"Name{delimiter}Amount"] + [f"item {i}{delimiter}{i}" for i in range(rows)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _wait(qapp: QApplication, condition, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()
    assert condition()


def _settled(dialog: FileImportPreviewDialog) -> bool:
    return dialog.import_button.isEnabled() or bool(dialog.error_label.text())


def test_default_flag_shows_the_old_error_for_an_over_limit_file(qapp, tmp_path, small_limit) -> None:
    path = _csv(tmp_path)
    dialog = FileImportPreviewDialog(path, replacing=False)
    try:
        _wait(qapp, lambda: _settled(dialog))
        assert dialog.error_label.text() == "The file exceeds the 500-row import limit."
        assert dialog.large_request is None
        assert dialog.candidate is None
        assert dialog.large_mode_enabled is False
    finally:
        dialog.deleteLater()


def test_large_mode_previews_the_first_1000_rows(qapp, tmp_path, small_limit) -> None:
    path = _csv(tmp_path)
    dialog = FileImportPreviewDialog(path, replacing=False, large_mode_enabled=True)
    try:
        _wait(qapp, lambda: dialog.import_button.isEnabled())
        model = dialog.table.model()
        assert model.rowCount() == 1000
        assert dialog.notice_label.text() == LARGE_NOTICE
        assert dialog.transform_button.isHidden()
        assert dialog.allow_transform is False
        assert dialog.error_label.text() == ""
        assert dialog.large_request is None
    finally:
        dialog.deleteLater()


def test_large_mode_accept_sets_large_request_and_no_candidate(qapp, tmp_path, small_limit) -> None:
    path = _csv(tmp_path)
    dialog = FileImportPreviewDialog(path, replacing=False, large_mode_enabled=True)
    try:
        _wait(qapp, lambda: dialog.import_button.isEnabled())
        dialog._accept_candidate("load")
        assert dialog.result() == dialog.DialogCode.Accepted.value
        assert dialog.candidate is None
        assert dialog.large_request is not None
        assert dialog.large_request["path"] == str(path.resolve())
        assert dialog.large_request["kind"] == "csv"
        assert dialog.large_request["limit_kind"] == "rows"
        options = dialog.large_request["options"]
        assert options["delimiter"] == ","
        assert options["has_header"] is True
        assert options == file_import.normalize_options("csv", options)
    finally:
        dialog.deleteLater()


def test_large_mode_reruns_only_the_head_when_the_delimiter_changes(qapp, tmp_path, small_limit, monkeypatch) -> None:
    path = _csv(tmp_path, delimiter=";")
    calls = []
    original = dialog_module.parse_file

    def counting_parse_file(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(dialog_module, "parse_file", counting_parse_file)
    dialog = FileImportPreviewDialog(path, replacing=False, large_mode_enabled=True)
    try:
        _wait(qapp, lambda: dialog.import_button.isEnabled())
        assert len(dialog._preview_candidate.headers) == 1
        dialog.delimiter_combo.setCurrentIndex(dialog.delimiter_combo.findData(";"))
        _wait(qapp, lambda: dialog._preview_candidate is not None and len(dialog._preview_candidate.headers) == 2 and dialog.import_button.isEnabled())
        assert dialog.table.model().rowCount() == 1000
        assert dialog.notice_label.text() == LARGE_NOTICE
        assert len(calls) == 1, "the full file must not be parsed again in large mode"
        dialog._accept_candidate("load")
        assert dialog.large_request["options"]["delimiter"] == ";"
    finally:
        dialog.deleteLater()


def test_large_mode_head_failure_shows_the_error(qapp, tmp_path, small_limit, monkeypatch) -> None:
    path = _csv(tmp_path)

    def failing_head(*args, **kwargs):
        raise FileImportError("head failed for test")

    monkeypatch.setattr(dialog_module, "parse_head", failing_head)
    dialog = FileImportPreviewDialog(path, replacing=False, large_mode_enabled=True)
    try:
        _wait(qapp, lambda: bool(dialog.error_label.text()))
        assert dialog.error_label.text() == "head failed for test"
        assert dialog.candidate is None
        assert dialog.large_request is None
    finally:
        dialog.deleteLater()


def test_large_mode_parquet_over_limit(qapp, tmp_path, small_limit) -> None:
    path = tmp_path / "big.parquet"
    table = pa.table({"id": list(range(3000)), "name": [f"n{i}" for i in range(3000)]})
    pq.write_table(table, path, row_group_size=700)
    dialog = FileImportPreviewDialog(path, replacing=False, large_mode_enabled=True)
    try:
        _wait(qapp, lambda: dialog.import_button.isEnabled())
        assert dialog.table.model().rowCount() == 1000
        assert "Showing the first 1,000 of a large file." in dialog.notice_label.text()
        assert dialog.notice_label.text().endswith("It will be loaded into the large-data store.")
        assert dialog.transform_button.isHidden()
        dialog._accept_candidate("load")
        assert dialog.candidate is None
        assert dialog.large_request["kind"] == "parquet"
        assert dialog.large_request["limit_kind"] == "rows"
    finally:
        dialog.deleteLater()


def test_small_file_with_flag_on_behaves_like_flag_off(qapp, tmp_path) -> None:
    path = tmp_path / "small.csv"
    path.write_text("Name;Amount\nAlice;10\nBob;20\n", encoding="utf-8")
    results = []
    for flag in (False, True):
        dialog = FileImportPreviewDialog(path, replacing=False, large_mode_enabled=flag)
        try:
            _wait(qapp, lambda: dialog.import_button.isEnabled())
            dialog._accept_candidate("load")
            results.append((
                [list(row.items()) for row in dialog.candidate.rows],
                dialog.candidate.headers,
                dialog.large_request,
            ))
        finally:
            dialog.deleteLater()
    assert results[0] == results[1]
    assert results[1][2] is None
    assert results[1][0]


def test_excel_over_limit_with_flag_on_keeps_the_error(qapp, tmp_path, small_limit) -> None:
    from openpyxl import Workbook

    path = tmp_path / "big.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Name", "Amount"])
    for i in range(3000):
        sheet.append([f"item {i}", i])
    workbook.save(path)
    dialog = FileImportPreviewDialog(path, replacing=False, large_mode_enabled=True)
    try:
        _wait(qapp, lambda: bool(dialog.error_label.text()) or dialog.import_button.isEnabled())
        assert dialog.error_label.text() == "The file exceeds the 500-row import limit."
        assert dialog.large_request is None
        assert dialog.candidate is None
    finally:
        dialog.deleteLater()


def test_large_mode_from_background_parse_for_a_big_file(qapp, tmp_path, small_limit) -> None:
    path = tmp_path / "wide.csv"
    filler = "x" * 120
    lines = ["Name,Amount"] + [f"item {i} {filler},{i}" for i in range(3000)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert path.stat().st_size >= dialog_module.ASYNC_PREVIEW_THRESHOLD_BYTES
    dialog = FileImportPreviewDialog(path, replacing=False, large_mode_enabled=True)
    try:
        _wait(qapp, lambda: dialog.import_button.isEnabled())
        assert dialog.table.model().rowCount() == 1000
        assert dialog.notice_label.text() == LARGE_NOTICE
        dialog._accept_candidate("load")
        assert dialog.candidate is None
        assert dialog.large_request["kind"] == "csv"
    finally:
        dialog.deleteLater()
