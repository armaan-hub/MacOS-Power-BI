"""Differential test: the large-data grid filters and sorts like the ordinary grid (Stage B4b task 15b).

One small CSV is imported twice, the ordinary way (CsvTableModel) and the large way
(StoreTableModel, MAX_DATA_ROWS lowered so the real large path is taken). Every filter operator
with many values on every column, and an ascending and a descending sort on every column, must
give the same visible id column on both models.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
import random
import time
from typing import Any
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from analytics_studio import file_import
from analytics_studio.controller import CsvTableModel, StudioController
from analytics_studio.store.candidate import StoreCandidate
from analytics_studio.store.table_model import StoreTableModel
from tests.test_controller_store_import_large import _FakeLargeDialog, _wait_for_large_job

ROWS = 400
HEADERS = ["id", "whole", "dec", "txt", "day", "stamp", "zeros", "mess", "uni", "flag", "wnc", "dnc"]
OPERATORS = [
    "equals", "not_equals", "is_null", "is_not_null", "is_blank", "is_not_blank",
    "contains", "does_not_contain", "begins_with", "does_not_begin_with",
    "ends_with", "does_not_end_with", "greater_than", "greater_than_or_equal",
    "less_than", "less_than_or_equal",
]
COMMON_VALUES = [
    "", "0", "1", "7", "007", "12", "-5", "+5", " 7", "7 ", "3.5", "-0.5", "1e2",
    "abc", "ABC", "Abc", "a", "x", "(null)", "NaN", "é", "2026-03-05",
    "2026-03-05 10:00:00", "2026-03-05T10:00:00", "true", "True", "100", "399", "400",
]
PER_COLUMN_VALUES = {
    "id": ["150", "1500", "99", "100", "9", "10"],
    "whole": ["50", "49", "-1", "0", "100", "3.5"],
    "dec": ["2.5", "0.00", "-10.25", "10.250", "100.5"],
    "txt": ["alpha", "ALPHA", "Beta", "beta ", "gamma", "al", "ha", "Zed", "zed", "Gamma "],
    "day": ["2026-01-01", "2026-06-15", "2026-12-31", "2025-12-31", "2026-02-30"],
    "stamp": ["2026-01-01 00:00:00", "2026-06-15 12:30:45", "2026-06-15", "2026-06-15 12:30"],
    "zeros": ["007", "0007", "7", "010", "10", "00"],
    "mess": ["+12", "-12", "12", " 12", "12 ", "- 12", "1,000", "+1.5"],
    "uni": ["é", "É", "café", "Cafe", "ü"],
    "flag": ["true", "false", "TRUE", "False", "yes", "1", "0"],
    "wnc": ["5", "+5", "05", "-3", "7", "+6"],
    "dnc": ["2026-01-05", "2026-1-5", "2026-01-15", "2026-03-04"],
}


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(["Analytics Studio tests"])


def _write_csv(path: Path) -> None:
    rng = random.Random(77)
    words = ["alpha", "BETA", "Gamma", "delta", "Zed", "", ""]
    messy = ["+12", "-12", "12", " 12", "- 12", "1,000", "+1.5", "abc", "", "007", "3.50", "-0"]
    unis = ["café", "ünder", "plain", "É", "", "é"]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        for i in range(1, ROWS + 1):
            whole = "" if rng.random() < 0.1 else str(rng.randrange(-5, 101))
            dec = "" if rng.random() < 0.1 else f"{rng.randrange(-2000, 20000) / 100:.2f}"
            day = "" if rng.random() < 0.1 else f"2026-{rng.randrange(1, 13):02d}-{rng.randrange(1, 29):02d}"
            stamp = "" if rng.random() < 0.1 else (
                f"2026-{rng.randrange(1, 13):02d}-{rng.randrange(1, 29):02d} "
                f"{rng.randrange(24):02d}:{rng.randrange(60):02d}:{rng.randrange(60):02d}"
            )
            writer.writerow([
                str(i), whole, dec, rng.choice(words), day, stamp,
                f"{rng.randrange(0, 40):03d}", rng.choice(messy), rng.choice(unis),
                rng.choice(["true", "false", "", "true"]),
                rng.choice(["5", "+5", "05", "-3", "7", "", "+6", "12"]),
                rng.choice(["2026-01-05", "2026-1-5", "2026-01-15", "", "2026-03-04"]),
            ])


def _visible_ids(model: Any) -> list[str]:
    """The id of every visible row, in order (all 400 rows fit on one page)."""
    if isinstance(model, StoreTableModel):
        model._set_page(0)
    id_col = model._headers.index("id")
    return [model.data(model.index(r, id_col)) for r in range(model.rowCount())]


def _count(model: Any) -> int:
    return model._filtered_rows if isinstance(model, StoreTableModel) else len(model._all_rows)


def _import_both(work: Path, path: Path):
    """Import one CSV the ordinary way and the large way; yield (CsvTableModel, StoreTableModel)."""
    parsed = file_import.parse_file(path)

    class _SmallDialog:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.candidate = parsed
            self.large_request = None
            self.selected_action = "load"
            self.checked_sheets: list[Any] = []

        def exec(self) -> int:
            return 1

    ordinary = StudioController()
    with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_SmallDialog):
        assert ordinary._import_file_path(path) is True
    large = StudioController()
    large._effective_app_data_dir = lambda: str(work / "appdata")  # type: ignore[method-assign]
    try:
        with patch.object(file_import, "MAX_DATA_ROWS", 100), \
                patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog), \
                patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            assert large._import_file_path(path) is True
            _wait_for_large_job(large)
        assert isinstance(large._active_store_candidate, StoreCandidate)
        o_model, l_model = ordinary.dataModel, large.dataModel
        assert isinstance(o_model, CsvTableModel)
        assert isinstance(l_model, StoreTableModel)
        yield o_model, l_model
    finally:
        large._close_project_store()
        ordinary._close_project_store()


@pytest.fixture(scope="module")
def models(qapp: QApplication, tmp_path_factory: pytest.TempPathFactory):
    work = tmp_path_factory.mktemp("store_filter_parity")
    path = work / "parity.csv"
    _write_csv(path)
    yield from _import_both(work, path)


@pytest.fixture(scope="module")
def load_rule_models(qapp: QApplication, tmp_path_factory: pytest.TempPathFactory):
    work = tmp_path_factory.mktemp("store_filter_parity_load_rules")
    path = work / "load_rules.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "txt"])
        values = ["alpha", "ALPHA", "zed ", "zed", "Beta", "beta"] * 100
        for i, value in enumerate(values, start=1):
            writer.writerow([str(i), value])
    yield from _import_both(work, path)


def test_both_paths_hold_the_same_rows_and_types(models: Any) -> None:
    o_model, l_model = models
    assert o_model._headers == l_model._headers == HEADERS
    assert o_model._column_types == l_model._column_types
    assert _count(o_model) == _count(l_model) == ROWS
    assert _visible_ids(o_model) == _visible_ids(l_model)
    for header in HEADERS:
        o_col = o_model._headers.index(header)
        l_col = l_model._headers.index(header)
        o_cells = [o_model.data(o_model.index(r, o_col)) for r in range(ROWS)]
        l_cells = [l_model.data(l_model.index(r, l_col)) for r in range(ROWS)]
        assert o_cells == l_cells, header


@pytest.mark.parametrize("column", HEADERS)
def test_every_operator_gives_the_same_rows(models: Any, column: str) -> None:
    o_model, l_model = models
    differences: list[str] = []
    checked = 0
    for operator in OPERATORS:
        for value in COMMON_VALUES + PER_COLUMN_VALUES[column]:
            o_model.setColumnFilter(column, operator, value)
            l_model.setColumnFilter(column, operator, value)
            o_ids, l_ids = _visible_ids(o_model), _visible_ids(l_model)
            checked += 1
            if o_ids != l_ids or _count(o_model) != _count(l_model):
                differences.append(
                    f"{column} {operator} {value!r}: ordinary {_count(o_model)} rows, "
                    f"large {_count(l_model)} rows"
                )
    o_model.clearColumnFilter(column)
    l_model.clearColumnFilter(column)
    assert checked > 400
    assert not differences, f"{len(differences)} of {checked} differ, first 8: {differences[:8]}"


@pytest.mark.parametrize("column", HEADERS)
def test_ascending_and_descending_sort_give_the_same_rows(models: Any, column: str) -> None:
    o_model, l_model = models
    index = HEADERS.index(column)
    for direction in ("ascending", "descending"):
        for model in (o_model, l_model):
            if model.sortColumn == column and model.sortDirection == direction:
                continue
            model.sortByColumn(index)
            if model.sortDirection != direction:
                model.sortByColumn(index)
            assert (model.sortColumn, model.sortDirection) == (column, direction)
        o_ids, l_ids = _visible_ids(o_model), _visible_ids(l_model)
        assert o_ids == l_ids, f"{column} {direction}: first differing position " + str(
            next((i for i, (a, b) in enumerate(zip(o_ids, l_ids)) if a != b), None)
        )


def test_filter_and_sort_together_and_two_filters(models: Any) -> None:
    o_model, l_model = models
    for model in (o_model, l_model):
        model.setColumnFilter("txt", "contains", "ALPHA")
        model.setColumnFilter("whole", "greater_than", "20")
        model.setColumnFilter("dec", "less_than_or_equal", "50")
    assert _visible_ids(o_model) == _visible_ids(l_model)
    assert _count(o_model) == _count(l_model) > 0
    for column in ("txt", "whole", "dec"):
        o_model.clearColumnFilter(column)
        l_model.clearColumnFilter(column)
    assert _count(o_model) == _count(l_model) == ROWS


def test_filter_timing_on_the_small_file(models: Any) -> None:
    _, l_model = models
    started = time.monotonic()
    l_model.setColumnFilter("id", "greater_than", "150")
    l_model._set_page(0)
    print(f"[measured] filter_small_file_seconds={time.monotonic() - started:.3f}")
    assert l_model._filtered_rows > 0, "the filter on id > 150 must keep some rows"
    l_model.clearColumnFilter("id")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "the ordinary importer applies the VertiPaq load rules (trailing spaces dropped, ASCII-case "
        "variants kept under the first-seen spelling; controller._model_candidate_with_format_errors_as_blank), "
        "the store importer keeps the cells as read: 250 of the 500 text cells of the first page differ (measured 2026-11-25). "
        "The grid filters then see different data; this is an import difference, not a filter difference."
    ),
)
def test_text_cells_follow_the_model_load_rules_on_both_paths(load_rule_models: Any) -> None:
    o_model, l_model = load_rule_models
    o_cells = [o_model.data(o_model.index(r, 1)) for r in range(o_model.rowCount())]
    l_cells = [l_model.data(l_model.index(r, 1)) for r in range(l_model.rowCount())]
    assert o_cells == l_cells
