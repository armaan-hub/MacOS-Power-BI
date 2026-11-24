"""Tests for the permanent data-loss path found in the task 13b re-review (Stage B4b task 13c)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog, QPushButton

from analytics_studio.controller import StudioController
from analytics_studio.project import load_project, save_project
from analytics_studio.store.base import StoreError
from analytics_studio.store.session import ProjectStore
from tests.test_controller_store_save_open import (
    _assert_no_blocking_dialogs,
    _generate_csv_file,
    _import_large_table,
    qapp,
)

__all__ = ["qapp"]

ORIGINAL_TABLE = "src_src_large_1_g1"


def _csv(directory: Path, row_count: int = 2000) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return _generate_csv_file(directory, row_count)


def _saved_store_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, row_count: int = 2000, sub: str = "src"
) -> tuple[Path, Path]:
    """Import a large table, Save As, close the store. Returns (project path, data file path)."""
    csv_file = _csv(tmp_path / sub, row_count)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / f"appdata_{sub}"))
    _import_large_table(controller, csv_file, "csv")
    proj = tmp_path / name
    assert controller._save_to(proj) is True
    controller._close_project_store()
    return proj, Path(str(proj) + ".data")


def _tables_in(data_file: Path) -> list[str]:
    """List the tables of a data file with a second ProjectStore (fails if the file is locked)."""
    probe = ProjectStore.open(str(data_file))
    try:
        return list(probe.store.table_names())
    finally:
        probe.close()


def _bogus_store_source(source_id: str, table: str, data_file: str, row_count: int = 100) -> dict[str, Any]:
    return {
        "id": source_id,
        "name": source_id,
        "kind": "csv",
        "path": "missing_bogus.csv",
        "parser_options": {},
        "store": {
            "source_id": source_id,
            "table": table,
            "data_file": data_file,
            "row_count": row_count,
            "headers": ["a"],
            "physical_types": ["text"],
            "column_types": {"a": "text"},
            "fingerprint": {"size": 100, "mtime_ns": 1000, "head_tail_sha256": "0" * 64},
            "generation": 1,
            "duckdb_version": "1.0.0",
        },
    }


# ---------------------------------------------------------------- HIGH-1


def test_h1_wrong_table_name_in_json_does_not_drop_real_table(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    proj, data_file = _saved_store_project(tmp_path, monkeypatch, "h1.npa")
    original_doc, _ = load_project(proj)
    assert original_doc["data_sources"][0]["store"]["table"] == ORIGINAL_TABLE

    doc, _ = load_project(proj)
    doc["data_sources"][0]["store"]["table"] = "src_other_g2"
    save_project(proj, doc)

    broken = StudioController()
    assert broken.open_project_path(proj) is True
    assert "src_large_1" in broken._source_load_errors
    # the real table is still in the data file (second store can open it: no lock either)
    assert ORIGINAL_TABLE in _tables_in(data_file)

    save_project(proj, original_doc)
    fixed = StudioController()
    assert fixed.open_project_path(proj) is True
    assert "src_large_1" not in fixed._source_load_errors
    assert fixed.rowCount == 2000


def test_h1_wrong_row_count_keeps_table_and_closes_store(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    proj, data_file = _saved_store_project(tmp_path, monkeypatch, "h1_rows.npa")
    doc, _ = load_project(proj)
    doc["data_sources"][0]["store"]["row_count"] = 7
    save_project(proj, doc)

    controller = StudioController()
    assert controller.open_project_path(proj) is True
    assert "src_large_1" in controller._source_load_errors
    assert controller._project_store is None
    # a second store opens the file: it is not locked by this window
    assert ORIGINAL_TABLE in _tables_in(data_file)


def test_h1_same_project_reopen_with_wrong_table_name_drops_nothing(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-open in the window that holds the store: the pinned 13b rule keeps it live, but drops nothing."""
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path, 500)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")
    proj = tmp_path / "h1_same.npa"
    assert controller._save_to(proj) is True
    doc, _ = load_project(proj)
    doc["data_sources"][0]["store"]["table"] = "src_other_g2"
    save_project(proj, doc)

    assert controller.open_project_path(proj) is True
    assert "src_large_1" in controller._source_load_errors
    assert ORIGINAL_TABLE in controller._project_store.store.table_names()


def test_h1_two_store_sources_one_fails_drops_nothing(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    proj, data_file = _saved_store_project(tmp_path, monkeypatch, "h1_two.npa", 500)
    # a real table in the data file that the second (failing) source names, plus an orphan
    seed = ProjectStore.open(str(data_file))
    seed.store.create_table("src_second_g1", [("x", "whole")])
    seed.store.create_table("src_orphan_g1", [("x", "whole")])
    seed.close()
    doc, _ = load_project(proj)
    failing = _bogus_store_source("src_second", "src_second_g1", data_file.name, row_count=5)
    doc["data_sources"].append(failing)
    save_project(proj, doc)

    controller = StudioController()
    assert controller.open_project_path(proj) is True
    assert "src_second" in controller._source_load_errors
    assert "src_large_1" not in controller._source_load_errors
    assert controller.rowCount == 500
    tables = set(controller._project_store.store.table_names())
    assert {ORIGINAL_TABLE, "src_second_g1", "src_orphan_g1"} <= tables


def test_h1_all_validated_drops_stale_table_keeps_referenced(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    proj, data_file = _saved_store_project(tmp_path, monkeypatch, "h1_stale.npa", 500)
    seed = ProjectStore.open(str(data_file))
    seed.store.create_table("src_x_g1", [("x", "whole")])
    seed.close()

    controller = StudioController()
    assert controller.open_project_path(proj) is True
    assert not controller._source_load_errors
    tables = controller._project_store.store.table_names()
    assert "src_x_g1" not in tables
    assert ORIGINAL_TABLE in tables
    assert controller.rowCount == 500


# ---------------------------------------------------------------- S1


def test_s1_open_a_then_b_store_project_unlocks_a(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    proj_a, data_a = _saved_store_project(tmp_path, monkeypatch, "s1_a.npa", 300, "a")
    proj_b, data_b = _saved_store_project(tmp_path, monkeypatch, "s1_b.npa", 700, "b")

    controller = StudioController()
    assert controller.open_project_path(proj_a) is True
    assert controller.open_project_path(proj_b) is True
    assert controller.rowCount == 700
    assert ORIGINAL_TABLE in _tables_in(data_a)
    assert Path(controller._project_store.path).name == data_b.name


def test_s1_open_a_then_project_without_store_unlocks_a(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    proj_a, data_a = _saved_store_project(tmp_path, monkeypatch, "s1_a2.npa", 300, "a")
    plain = tmp_path / "plain.npa"
    assert StudioController()._save_to(plain) is True

    controller = StudioController()
    assert controller.open_project_path(proj_a) is True
    assert controller._project_store is not None
    assert controller.open_project_path(plain) is True
    assert controller._project_store is None
    assert ORIGINAL_TABLE in _tables_in(data_a)


# ---------------------------------------------------------------- S2


def test_s2_stale_store_candidate_on_old_session_does_not_copy(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A StoreCandidate on a closed old session must not make Save As copy the new live store."""
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path, 300)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")
    old_session = controller._project_store
    controller._close_project_store()
    live = controller._ensure_project_store()
    assert live is not old_session
    stale = [c for c in controller._loaded_candidates.values() if getattr(c, "session", None) is old_session]
    assert stale, "setup: a StoreCandidate must still point at the old session"

    target = tmp_path / "s2_copy.npa"
    assert controller._save_to(target) is True
    assert not Path(str(target) + ".data").exists()


# ---------------------------------------------------------------- S3


def test_s3_real_cancel_button_click_during_copy(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path, 500)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    boxes: list[Any] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: boxes.append(a))

    orig_copy_to = controller._project_store.copy_to
    clicked: list[bool] = []

    def click_cancel_then_copy(*args: Any, **kwargs: Any) -> Any:
        dialogs = [w for w in QApplication.topLevelWidgets() if isinstance(w, QProgressDialog) and w.isVisible()]
        assert dialogs
        buttons = [b for b in dialogs[-1].findChildren(QPushButton) if b.text().replace("&", "") == "Cancel"]
        assert len(buttons) == 1
        buttons[0].click()
        clicked.append(True)
        return orig_copy_to(*args, **kwargs)

    monkeypatch.setattr(controller._project_store, "copy_to", click_cancel_then_copy)

    target = tmp_path / "s3_cancel.npa"
    assert controller._save_to(target) is False
    assert clicked == [True]
    assert controller.statusMessage == "Save canceled."
    assert boxes == []
    assert not target.exists()
    assert not Path(str(target) + ".data").exists()
    assert len(list(tmp_path.glob("s3_cancel.npa*"))) == 0


# ---------------------------------------------------------------- S4


@pytest.mark.parametrize("error", [OSError(28, "No space left on device"), StoreError("copy exploded")])
def test_s4_failed_save_replaces_old_success_status(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path, 500)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    first = tmp_path / "s4_first.npa"
    assert controller._save_to(first) is True
    assert controller.statusMessage.startswith("Saved ")

    boxes: list[tuple[Any, Any, Any]] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, text: boxes.append((parent, title, text)))

    def fail_copy(*args: Any, **kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(controller._project_store, "copy_to", fail_copy)
    assert controller._save_to(tmp_path / "s4_second.npa") is False
    assert len(boxes) == 1
    assert controller.statusMessage == boxes[0][2]
    assert controller.statusMessage.startswith("Could not save the large-data table:")
    assert not controller.statusMessage.startswith("Saved ")


# ---------------------------------------------------------------- S5


def test_s5_refresh_all_status_names_skipped_store_source(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    proj, data_file = _saved_store_project(tmp_path, monkeypatch, "s5.npa", 500)
    doc, _ = load_project(proj)
    store_name = doc["data_sources"][0]["name"]
    ord_csv = tmp_path / "ord.csv"
    ord_csv.write_text("id,val\n1,10\n2,20\n", encoding="utf-8")
    doc["data_sources"].append({"id": "src_ord", "name": "ord", "kind": "csv", "path": str(ord_csv), "parser_options": {}})
    doc["model"]["tables"].append({
        "id": "src_ord",
        "source_id": "src_ord",
        "name": "ord",
        "column_types": {"id": "whole_number", "val": "whole_number"},
    })
    data_file.unlink()  # the store source fails to load, so refresh all is not refused as a whole
    save_project(proj, doc)

    controller = StudioController()
    assert controller.open_project_path(proj) is True
    assert "src_large_1" in controller._source_load_errors
    controller.refresh_all_sources()
    assert controller.statusMessage.startswith("Refreshed all supported linked sources")
    assert f"Large-data tables are skipped: {store_name}." in controller.statusMessage


def test_s5_refresh_all_status_has_no_note_without_store_source(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    ord_csv = tmp_path / "ord.csv"
    ord_csv.write_text("id,val\n1,10\n2,20\n", encoding="utf-8")
    proj = tmp_path / "s5_plain.npa"
    seed = StudioController()
    assert seed._save_to(proj) is True
    doc, _ = load_project(proj)
    doc["data_sources"].append({"id": "src_ord", "name": "ord", "kind": "csv", "path": str(ord_csv), "parser_options": {}})
    doc["model"]["tables"].append({
        "id": "src_ord",
        "source_id": "src_ord",
        "name": "ord",
        "column_types": {"id": "whole_number", "val": "whole_number"},
    })
    save_project(proj, doc)
    controller = StudioController()
    assert controller.open_project_path(proj) is True
    controller.refresh_all_sources()
    assert controller.statusMessage.startswith("Refreshed all supported linked sources")
    assert "Large-data tables are skipped" not in controller.statusMessage

