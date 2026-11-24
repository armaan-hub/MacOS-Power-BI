"""Tests for the data-loss path found in the task 13c re-review (Stage B4b task 13d).

Save As onto an existing project's data file, answer Yes to the replace question, copy fails or
is canceled: the pre-existing data file must stay byte-identical.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog, QPushButton

from analytics_studio.controller import StudioController
from analytics_studio.store.base import StoreError
from tests.test_controller_store_save_open import (
    _assert_no_blocking_dialogs,
    _import_large_table,
    qapp,
)
from tests.test_controller_store_save_open_13c import _csv, _saved_store_project

__all__ = ["qapp"]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: Any
) -> tuple[Path, Path, tuple[str, list[str]], StudioController, list[Any]]:
    """Another project X.npa + X.npa.data (2000 rows) on disk, plus a controller with a new unsaved import."""
    _assert_no_blocking_dialogs(monkeypatch)
    proj_x, data_x = _saved_store_project(tmp_path, monkeypatch, "x.npa")
    before = (_sha(data_x), sorted(p.name for p in tmp_path.glob("x.npa*")))

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata_new"))
    _import_large_table(controller, _csv(tmp_path / "new_src", 500), "csv")

    questions: list[Any] = []

    def question(*args: Any, **kwargs: Any) -> Any:
        questions.append(args)
        return answer

    monkeypatch.setattr(QMessageBox, "question", question)
    return proj_x, data_x, before, controller, questions


def _assert_x_intact(proj_x: Path, data_x: Path, before: tuple[str, list[str]]) -> None:
    sha_before, listing_before = before
    assert data_x.exists()
    assert _sha(data_x) == sha_before
    assert sorted(p.name for p in data_x.parent.glob("x.npa*")) == listing_before
    reopened = StudioController()
    assert reopened.open_project_path(proj_x) is True
    assert reopened.rowCount == 2000
    reopened._close_project_store()


@pytest.mark.parametrize(
    "error", [StoreError("copy exploded"), OSError(28, "No space left on device")], ids=["store_error", "os_error"]
)
def test_h2_failed_copy_keeps_existing_target_data_file(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    proj_x, data_x, before, controller, questions = _setup(tmp_path, monkeypatch, QMessageBox.StandardButton.Yes)
    boxes: list[Any] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: boxes.append(a))

    def fail_copy(*args: Any, **kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(controller._project_store, "copy_to", fail_copy)
    assert controller._save_to(proj_x) is False
    assert len(questions) == 1
    assert len(boxes) == 1
    assert controller.statusMessage.startswith("Could not save the large-data table:")
    _assert_x_intact(proj_x, data_x, before)


def test_h2_real_cancel_click_keeps_existing_target_data_file(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj_x, data_x, before, controller, questions = _setup(tmp_path, monkeypatch, QMessageBox.StandardButton.Yes)
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
    assert controller._save_to(proj_x) is False
    assert clicked == [True]
    assert len(questions) == 1
    assert boxes == []
    assert controller.statusMessage == "Save canceled."
    _assert_x_intact(proj_x, data_x, before)


def test_h2_control_failed_copy_without_existing_target_leaves_nothing(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, _csv(tmp_path / "src", 500), "csv")
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)

    def fail_copy(dest: str, *args: Any, **kwargs: Any) -> None:
        Path(dest).write_text("partial", encoding="utf-8")  # a partial file at the target
        Path(dest + ".wal").write_text("partial", encoding="utf-8")
        raise StoreError("copy failed")

    monkeypatch.setattr(controller._project_store, "copy_to", fail_copy)
    target = tmp_path / "ctl.npa"
    assert controller._save_to(target) is False
    assert list(tmp_path.glob("ctl.npa*")) == []


def test_h2_answer_no_writes_nothing_and_keeps_existing_file(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj_x, data_x, before, controller, questions = _setup(tmp_path, monkeypatch, QMessageBox.StandardButton.No)
    copy_calls: list[Any] = []
    orig = controller._project_store.copy_to
    monkeypatch.setattr(
        controller._project_store, "copy_to", lambda *a, **k: copy_calls.append(a) or orig(*a, **k)
    )
    assert controller._save_to(proj_x) is False
    assert len(questions) == 1
    assert copy_calls == []
    _assert_x_intact(proj_x, data_x, before)


def test_h2_unexpected_copy_failure_sets_status_text(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, _csv(tmp_path / "src", 500), "csv")
    assert controller._save_to(tmp_path / "first.npa") is True
    assert controller.statusMessage.startswith("Saved ")

    boxes: list[tuple[Any, Any, Any]] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, text: boxes.append((parent, title, text)))

    def fail_copy(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(controller._project_store, "copy_to", fail_copy)
    assert controller._save_to(tmp_path / "second.npa") is False
    assert boxes == [(None, "Could not save project", "boom")]
    assert controller.statusMessage == "Could not save project: boom"
