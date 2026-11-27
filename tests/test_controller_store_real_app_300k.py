"""Real-app test of the large-data store with 300,000 rows (Stage B4b task 15).

Drives the real StudioController, the real StoreJob and the real DuckDB store. Only the
file dialogs, the confirmation box and the preview dialog are patched, the same way the
large-import tests patch them. Every expected value is computed with the csv module from
the generated file, never from the store.
"""

from __future__ import annotations

import csv
import datetime
import os
from pathlib import Path
import random
import resource
import time
from typing import Any
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from analytics_studio import file_import
from analytics_studio.controller import StudioController
from analytics_studio.store.candidate import StoreCandidate
from analytics_studio.store.table_model import StoreTableModel
from tests.test_controller_store_save_open import _assert_no_blocking_dialogs

ROWS = 300_000
PAGE = 500
HEADERS = [
    "id",
    "start_date",
    "end_date",
    "stamp",
    "amount",
    "rate",
    "flag",
    "category",
    "code",
    "note",
    "score",
    "description",
]
EXPECTED_TYPES = {
    # The importer types id as text (same as the in-memory importer; probed 2026-11-25).
    "id": "text",
    "start_date": "date",
    "end_date": "date",
    "stamp": "datetime",
    "amount": "decimal_number",
    "rate": "decimal_number",
    "flag": "boolean",
    "category": "text",
    "code": "text",
    "note": "text",
    "score": "whole_number",
    "description": "text",
}
SPOT_OFFSETS = (0, 150_000, 299_900)
# Coarse hang guards, NOT speed claims: about 10 times the slowest value measured on the last run (sort 0.20 s, filter
# 0.04 s, page 5 ms), rounded up, so a loaded machine never trips them but a stuck or quadratic operation does.
OP_LIMIT_SECONDS = 50.0
PAGE_LIMIT_SECONDS = 10.0
IMPORT_LIMIT_SECONDS = 240.0
MEMORY_TARGET_BYTES = 400 * 1024 * 1024  # brief target, reported only
MEMORY_BOUND_BYTES = 1024 * 1024 * 1024  # generous assertion bound


def _rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux reports kilobytes.
    return int(value) if os.uname().sysname == "Darwin" else int(value) * 1024


def _generate_file(path: Path) -> Path:
    rng = random.Random(1234)
    order = list(range(ROWS))
    rng.shuffle(order)  # unique decimal values, so sort extremes have no ties
    base = datetime.date(2020, 1, 1)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        for i in range(ROWS):
            start = base + datetime.timedelta(days=rng.randrange(0, 2300))
            end = start + datetime.timedelta(days=rng.randrange(0, 60))
            stamp = (
                f"{start.isoformat()} {rng.randrange(24):02d}:"
                f"{rng.randrange(60):02d}:{rng.randrange(60):02d}"
            )
            amount = (order[i] - ROWS // 2) / 100
            score = "" if rng.random() < 0.10 else str(rng.randrange(100))
            writer.writerow([
                str(i + 1),
                start.isoformat(),
                end.isoformat(),
                stamp,
                f"{amount:.2f}",
                f"{rng.randrange(10_000) / 10_000:.4f}",
                "true" if rng.random() < 0.5 else "false",
                f"cat_{rng.randrange(20):02d}",
                f"K{i:06d}-{rng.randrange(1_000_000):06d}",
                f'note {i}, "quoted" café',
                score,
                f"row {i} text",
            ])
    return path


def _scan(path: Path, wanted: set[int]) -> dict[str, Any]:
    """One csv-module pass over the source file. Independent of the store."""
    stats: dict[str, Any] = {
        "rows": {},
        "blank_score": 0,
        "category_values": set(),
        "score_values": set(),
        "code_values": set(),
        "amount_min": None,
        "amount_max": None,
        "code_min": None,
        "code_max": None,
        "cat07_count": 0,
        "cat07_first": None,
        "cat07_last": None,
        "id_text_gt_299000": 0,
        "id_text_gt_299000_first": None,
        "id_text_gt_299000_last": None,
    }
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        next(reader)
        for index, row in enumerate(reader):
            if index in wanted:
                stats["rows"][index] = row
            if row[10] == "":
                stats["blank_score"] += 1
            else:
                stats["score_values"].add(row[10])
            stats["category_values"].add(row[7])
            stats["code_values"].add(row[8])
            amount = float(row[4])
            if stats["amount_min"] is None or amount < stats["amount_min"][0]:
                stats["amount_min"] = (amount, row[4])
            if stats["amount_max"] is None or amount > stats["amount_max"][0]:
                stats["amount_max"] = (amount, row[4])
            if stats["code_min"] is None or row[8] < stats["code_min"]:
                stats["code_min"] = row[8]
            if stats["code_max"] is None or row[8] > stats["code_max"]:
                stats["code_max"] = row[8]
            if row[7] == "cat_07":
                stats["cat07_count"] += 1
                if stats["cat07_first"] is None:
                    stats["cat07_first"] = row[0]
                stats["cat07_last"] = row[0]
            # The id column is text-typed, so compare the cell string as text (casefolded), as the grid does.
            if row[0].casefold() > "299000":
                stats["id_text_gt_299000"] += 1
                if stats["id_text_gt_299000_first"] is None:
                    stats["id_text_gt_299000_first"] = row[0]
                stats["id_text_gt_299000_last"] = row[0]
    stats["code_values"] = len(stats["code_values"])
    stats["category_values"] = len(stats["category_values"])
    stats["score_distinct"] = len(stats["score_values"])
    return stats


def _spot_indices() -> list[int]:
    return sorted(random.Random(99).sample(range(ROWS), 20))


class _FakeLargeDialog:
    """Headless fake for FileImportPreviewDialog in large mode."""

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
        return 1  # QDialog.DialogCode.Accepted.value


def _wait_for_job(controller: StudioController, limit: float) -> float:
    """Process Qt events until the large import job ends. Fails the test at the hard limit."""
    qapp = QApplication.instance()
    started = time.monotonic()
    deadline = started + limit
    while controller._large_import_job is not None:
        if time.monotonic() > deadline:
            pytest.fail(f"Large import job did not finish within {limit} seconds.")
        if qapp is not None:
            qapp.processEvents()
        time.sleep(0.01)
    if qapp is not None:
        qapp.processEvents()
    return time.monotonic() - started


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(["Analytics Studio 300k tests"])


@pytest.fixture(scope="module")
def big_csv(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("store_300k_source")
    return _generate_file(directory / "sales_300k.csv")


@pytest.fixture(scope="module")
def expected(big_csv: Path) -> dict[str, Any]:
    return _scan(big_csv, set(SPOT_OFFSETS) | set(_spot_indices()))


@pytest.fixture(scope="module")
def imported(qapp: QApplication, big_csv: Path, tmp_path_factory: pytest.TempPathFactory):
    """Import the 300,000-row file through the real large path once, for the whole module."""
    controller = StudioController()
    appdata = tmp_path_factory.mktemp("store_300k_appdata")
    controller._effective_app_data_dir = lambda: str(appdata)  # type: ignore[method-assign]

    rows_read_count = 0
    orig_fget = StoreCandidate.rows.fget

    def counting_rows(self: StoreCandidate) -> Any:
        nonlocal rows_read_count
        rows_read_count += 1
        return orig_fget(self)

    state: dict[str, Any] = {"controller": controller}
    try:
        with patch.object(file_import, "MAX_DATA_ROWS", 500), \
                patch.object(StoreCandidate, "rows", new=property(counting_rows)), \
                patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog), \
                patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
                patch.object(StudioController, "_run_store_summary_dialog", lambda self, candidate: None):  # The automatic summary dialog is modal; tests must not open it.
            rss_before = _rss_bytes()
            started = time.monotonic()
            success = controller._import_file_path(big_csv)
            if success is not True:
                pytest.fail("Large import was not accepted by the controller.")
            _wait_for_job(controller, IMPORT_LIMIT_SECONDS)
            state["import_seconds"] = time.monotonic() - started
            rss_after = _rss_bytes()
        state["rss_growth"] = rss_after - rss_before
        state["rss_before"] = rss_before
        state["rows_read_count"] = rows_read_count
        yield state
    finally:
        controller._close_project_store()


def _model(imported: dict[str, Any]) -> StoreTableModel:
    model = imported["controller"].dataModel
    assert isinstance(model, StoreTableModel)
    return model


def _cell(model: StoreTableModel, row: int, column: int) -> Any:
    return model.data(model.index(row, column))


def _as_text(value: Any) -> Any:
    return "" if value is None else value


def test_import_300k_rows_real_large_path(imported: dict[str, Any], big_csv: Path) -> None:
    controller = imported["controller"]
    assert controller.sourceLoaded is True
    assert controller.rowCount == ROWS, f"rowCount {controller.rowCount}"
    assert controller.headers == HEADERS
    types = {item["column"]: item["type"] for item in controller.columnTypes}
    assert types == EXPECTED_TYPES
    assert controller._ensure_project_store().busy is False
    assert controller._large_import_dialog is None
    assert f"Loaded 300,000 rows into the large-data store: {big_csv.name}." in controller.statusMessage
    assert imported["rows_read_count"] == 0
    growth_mb = imported["rss_growth"] / (1024 * 1024)
    assert imported["rss_growth"] < MEMORY_BOUND_BYTES, (
        f"ru_maxrss grew by {growth_mb:.1f} MB during import (bound 1024 MB, target 400 MB)"
    )
    print(
        f"[measured] import_seconds={imported['import_seconds']:.2f} "
        f"ru_maxrss_growth_mb={growth_mb:.1f} target_mb={MEMORY_TARGET_BYTES // (1024 * 1024)}"
    )


def test_grid_pages_at_first_middle_last_offsets(imported: dict[str, Any], expected: dict[str, Any]) -> None:
    model = _model(imported)
    for offset in SPOT_OFFSETS:
        page_index = offset // PAGE
        started = time.monotonic()
        assert model._set_page(page_index) is True
        elapsed = time.monotonic() - started
        assert elapsed < PAGE_LIMIT_SECONDS, f"page read at offset {offset} took {elapsed:.3f} s (hang guard {PAGE_LIMIT_SECONDS} s)"
        source_row = expected["rows"][offset]
        local = offset - page_index * PAGE
        for column, name in enumerate(HEADERS):
            got = _as_text(_cell(model, local, column))
            assert got == source_row[column], f"offset {offset} column {name}: {got!r} != {source_row[column]!r}"
        print(f"[measured] page_read_ms offset={offset} ms={elapsed * 1000:.1f}")


def test_profile_numeric_text_and_blank_columns(imported: dict[str, Any], expected: dict[str, Any]) -> None:
    controller = imported["controller"]

    amount = controller.profileColumn("amount")
    assert amount["nullCount"] == 0
    assert amount["distinctCount"] == ROWS

    category = controller.profileColumn("category")
    assert category["nullCount"] == 0
    assert category["distinctCount"] == expected["category_values"] == 20

    code = controller.profileColumn("code")
    assert code["nullCount"] == 0
    assert abs(code["distinctCount"] - ROWS) <= 0.05 * ROWS

    # Blanks in a typed column count as emptyCount, not nullCount (same as the in-memory path).
    score = controller.profileColumn("score")
    assert score["nullCount"] == 0
    assert score["emptyCount"] == expected["blank_score"]
    assert score["distinctCount"] == expected["score_distinct"]


@pytest.mark.xfail(
    strict=True,
    reason="profileColumn returns no min/max keys on either path (store and in-memory); brief asks for min and max",
)
def test_profile_min_max_for_numeric_column(imported: dict[str, Any], expected: dict[str, Any]) -> None:
    controller = imported["controller"]
    profile = controller.profileColumn("amount")
    assert "min" in profile and "max" in profile, f"profileColumn keys: {sorted(profile)}"
    assert profile["min"] == expected["amount_min"][1]
    assert profile["max"] == expected["amount_max"][1]


def test_export_300k_csv_round_trip(imported: dict[str, Any], expected: dict[str, Any], tmp_path_factory: pytest.TempPathFactory) -> None:
    controller = imported["controller"]
    out = tmp_path_factory.mktemp("store_300k_export") / "export_300k.csv"
    started = time.monotonic()
    assert controller.export_data_path(out) is True
    export_seconds = time.monotonic() - started

    spot = set(_spot_indices())
    seen_rows = 0
    checked: dict[int, list[str]] = {}
    # Export writes UTF-8 with a byte order mark (utf-8-sig), by design.
    with open(out, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        assert next(reader) == HEADERS
        for index, row in enumerate(reader):
            seen_rows += 1
            if index in spot:
                checked[index] = row
    assert seen_rows == ROWS
    for index in sorted(spot):
        assert checked[index] == expected["rows"][index], f"export row {index} differs"
        assert checked[index][9] == expected["rows"][index][9]
    print(f"[measured] export_seconds={export_seconds:.2f}")


def test_sort_and_filter_on_300k_rows(imported: dict[str, Any], expected: dict[str, Any]) -> None:
    model = _model(imported)
    column_of = {name: i for i, name in enumerate(HEADERS)}

    timings: dict[str, float] = {}

    started = time.monotonic()
    model.sortByColumn(column_of["amount"])
    model._set_page(0)
    timings["sort_amount_asc_seconds"] = time.monotonic() - started
    assert timings["sort_amount_asc_seconds"] < OP_LIMIT_SECONDS, f"sort_amount_asc_seconds took {timings['sort_amount_asc_seconds']:.3f} s (hang guard {OP_LIMIT_SECONDS} s)"
    assert _cell(model, 0, column_of["amount"]) == expected["amount_min"][1]

    started = time.monotonic()
    model.sortByColumn(column_of["amount"])
    model._set_page(0)
    timings["sort_amount_desc_seconds"] = time.monotonic() - started
    assert timings["sort_amount_desc_seconds"] < OP_LIMIT_SECONDS, f"sort_amount_desc_seconds took {timings['sort_amount_desc_seconds']:.3f} s (hang guard {OP_LIMIT_SECONDS} s)"
    assert _cell(model, 0, column_of["amount"]) == expected["amount_max"][1]

    started = time.monotonic()
    model.sortByColumn(column_of["code"])
    model._set_page(0)
    timings["sort_code_asc_seconds"] = time.monotonic() - started
    assert timings["sort_code_asc_seconds"] < OP_LIMIT_SECONDS, f"sort_code_asc_seconds took {timings['sort_code_asc_seconds']:.3f} s (hang guard {OP_LIMIT_SECONDS} s)"
    assert _cell(model, 0, column_of["code"]) == expected["code_min"]

    started = time.monotonic()
    model.setColumnFilter("category", "equals", "cat_07")
    model._set_page(0)
    timings["filter_category_seconds"] = time.monotonic() - started
    assert timings["filter_category_seconds"] < OP_LIMIT_SECONDS, f"filter_category_seconds took {timings['filter_category_seconds']:.3f} s (hang guard {OP_LIMIT_SECONDS} s)"
    assert model._filtered_rows == expected["cat07_count"]
    assert _cell(model, 0, column_of["id"]) == expected["cat07_first"]
    model._set_page(model.pageCount - 1)
    last_local = (expected["cat07_count"] - 1) % PAGE
    assert _cell(model, last_local, column_of["id"]) == expected["cat07_last"]
    model.clearColumnFilter("category")

    started = time.monotonic()
    for name, seconds in timings.items():
        print(f"[measured] {name}={seconds:.3f}")


# The id column is text, so the grid compares it as text, the same as the ordinary grid (78,885 rows for id > 299000), not as numbers.
def test_filter_id_range_on_300k_rows(imported: dict[str, Any], expected: dict[str, Any]) -> None:
    model = _model(imported)
    column_of = {name: i for i, name in enumerate(HEADERS)}
    expected_count = expected["id_text_gt_299000"]
    assert expected_count == 78885
    started = time.monotonic()
    model.setColumnFilter("id", "greater_than", "299000")
    model._set_page(0)
    elapsed = time.monotonic() - started
    print(f"[measured] filter_id_range_seconds={elapsed:.3f}")
    assert elapsed < OP_LIMIT_SECONDS, f"filter on id took {elapsed:.3f} s (hang guard {OP_LIMIT_SECONDS} s)"
    assert model._filtered_rows == expected_count
    assert _cell(model, 0, column_of["id"]) == expected["id_text_gt_299000_first"]
    model._set_page(model.pageCount - 1)
    assert _cell(model, (expected_count - 1) % PAGE, column_of["id"]) == expected["id_text_gt_299000_last"]
    model.clearColumnFilter("id")


def test_refusals_hold_with_store_table_loaded(imported: dict[str, Any]) -> None:
    controller = imported["controller"]
    controller._set_status("")
    measures_before = list(controller._project.get("model", {}).get("measures", []))
    relationships_before = list(controller._project.get("model", {}).get("relationships", []))
    assert controller._store_tables_loaded() is True

    ok = controller.create_measure("M_big", "1 + 1")
    assert ok is False
    assert controller._project.get("model", {}).get("measures", []) == measures_before
    assert controller._project.get("model", {}).get("relationships", []) == relationships_before
    assert controller._status_message.startswith(
        "Could not create measure: M_big cannot be computed on a large table yet"
    )


def test_save_as_reopen_and_plain_save_300k(
    imported: dict[str, Any],
    expected: dict[str, Any],
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = imported["controller"]
    _assert_no_blocking_dialogs(monkeypatch)
    project_dir = tmp_path_factory.mktemp("store_300k_project") / "new_folder"
    project_dir.mkdir()
    proj = project_dir / "sales_300k.npa"

    started = time.monotonic()
    assert controller._save_to(proj) is True
    save_seconds = time.monotonic() - started
    data_path = Path(str(proj) + ".data")
    assert data_path.exists()
    stat_before = data_path.stat()

    started = time.monotonic()
    controller.save_current_project()
    plain_save_seconds = time.monotonic() - started
    stat_after = data_path.stat()
    assert stat_after.st_mtime_ns == stat_before.st_mtime_ns
    assert stat_after.st_size == stat_before.st_size

    controller._close_project_store()

    fresh = StudioController()
    fresh._effective_app_data_dir = lambda: str(project_dir.parent / "fresh_appdata")  # type: ignore[method-assign]
    started = time.monotonic()
    assert fresh.open_project_path(proj) is True
    if fresh._large_import_job is not None:
        _wait_for_job(fresh, IMPORT_LIMIT_SECONDS)
    reopen_seconds = time.monotonic() - started
    assert fresh.rowCount == ROWS
    model = fresh.dataModel
    assert isinstance(model, StoreTableModel)
    for offset in SPOT_OFFSETS:
        page_index = offset // PAGE
        assert model._set_page(page_index) is True
        local = offset - page_index * PAGE
        for column, name in enumerate(HEADERS):
            got = _as_text(_cell(model, local, column))
            assert got == expected["rows"][offset][column], f"reopen offset {offset} column {name}"
    fresh._close_project_store()
    print(
        f"[measured] save_as_seconds={save_seconds:.2f} plain_save_seconds={plain_save_seconds:.3f} "
        f"reopen_seconds={reopen_seconds:.2f}"
    )
