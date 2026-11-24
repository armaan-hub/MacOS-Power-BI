"""Review fixes for the large-data table reload (Stage B4b task 16b)."""

from __future__ import annotations

import csv
import logging
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

from analytics_studio.controller import StudioController
from analytics_studio.store import stats as st
from analytics_studio.store.base import StoreError
from analytics_studio.store.session import ProjectStore
from analytics_studio.store.table_model import StoreTableModel

REPO_ROOT = Path(__file__).resolve().parents[1]
CRITICAL: list[str] = []


@pytest.fixture
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["controller_store_reload_16b_test"])
    return app


@pytest.fixture(autouse=True)
def no_blocking_dialogs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    CRITICAL.clear()

    def bad_dialog(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"Blocking dialog was unexpectedly invoked: {args} {kwargs}")

    monkeypatch.setattr(QFileDialog, "getOpenFileName", bad_dialog)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", bad_dialog)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", bad_dialog)
    monkeypatch.setattr(QMessageBox, "information", bad_dialog)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, text: CRITICAL.append(text))
    monkeypatch.setattr(QMessageBox, "question", bad_dialog)
    monkeypatch.setattr(QInputDialog, "getText", bad_dialog)
    monkeypatch.setattr(QInputDialog, "getItem", bad_dialog)
    monkeypatch.setattr(QDialog, "exec", bad_dialog)
    monkeypatch.setattr(QDialog, "exec_", bad_dialog)
    return CRITICAL


def _csv(path: Path, headers: list[str], rows: list[list[str]]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def _wait(controller: StudioController, timeout: float = 20.0) -> None:
    import time

    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while controller._large_import_job is not None and time.monotonic() < deadline:
        if app is not None:
            app.processEvents()
        time.sleep(0.01)
    if app is not None:
        app.processEvents()
    if controller._large_import_job is not None:
        raise TimeoutError("Large import job timed out.")


def _import_initial(controller: StudioController, path: Path) -> None:
    assert controller._import_large(path, {"kind": "csv", "options": {}}) is True
    _wait(controller)


def _reload(controller: StudioController) -> bool:
    started = controller.reloadLargeTable()
    if started:
        _wait(controller)
    return started


def _snapshot(controller: StudioController) -> dict[str, Any]:
    sid = controller._active_store_candidate.source_id
    return {
        "project": deepcopy(controller._project),
        "candidate": controller._active_store_candidate,
        "loaded": controller._loaded_candidates.get(sid),
        "raw": controller._raw_candidates.get(sid),
        "query": controller._query_candidates.get(sid),
        "headers": list(controller._headers),
        "dirty": controller._dirty,
        "grid_table": controller._store_table_model._table_name,
        "grid_rows": controller._store_table_model.rowCount(),
        "warning": controller._source_warning,
    }


def _setup(tmp_path: Path, name: str = "data.csv", saved: bool = True,
           headers: list[str] | None = None, rows: list[list[str]] | None = None
           ) -> tuple[StudioController, Path, str]:
    csv_file = _csv(tmp_path / name, headers or ["id", "val"], rows or [["1", "A"], ["2", "B"]])
    controller = StudioController()
    _import_initial(controller, csv_file)
    if saved:
        assert controller._save_to(tmp_path / "p.npa") is True
    return controller, csv_file, controller._active_store_candidate.source_id


# ------------------------------------------------------------------ M1

FAIL_SENTENCE = "Could not load the reloaded table from the store. The large-data table was not reloaded."


def _assert_unchanged_after_failed_reload(controller: StudioController, before: dict[str, Any],
                                          source_id: str) -> None:
    after = _snapshot(controller)
    assert after == before
    tables = controller._project_store.call(lambda s: s.table_names())
    assert tables == [ProjectStore.table_name(source_id, 1)]
    assert controller.statusMessage == FAIL_SENTENCE
    assert controller.dirty is False


def test_replace_data_false_changes_nothing(qapp: QApplication, tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    controller, csv_file, sid = _setup(tmp_path)
    try:
        before = _snapshot(controller)
        _csv(csv_file, ["id", "val"], [["3", "C"], ["4", "D"], ["5", "E"]])
        monkeypatch.setattr(StoreTableModel, "replace_data", lambda self, *a, **k: False)
        assert _reload(controller) is True
        _assert_unchanged_after_failed_reload(controller, before, sid)
    finally:
        controller._close_project_store()


def test_replace_data_raises_changes_nothing(qapp: QApplication, tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    controller, csv_file, sid = _setup(tmp_path)
    try:
        before = _snapshot(controller)
        _csv(csv_file, ["id", "val"], [["3", "C"]])

        def boom(self: Any, *args: Any, **kwargs: Any) -> bool:
            raise RuntimeError("grid broke")

        monkeypatch.setattr(StoreTableModel, "replace_data", boom)
        assert _reload(controller) is True
        _assert_unchanged_after_failed_reload(controller, before, sid)
    finally:
        controller._close_project_store()


def test_replace_data_store_error_changes_nothing(qapp: QApplication, tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    controller, csv_file, sid = _setup(tmp_path)
    try:
        before = _snapshot(controller)
        _csv(csv_file, ["id", "val"], [["3", "C"]])

        def boom(self: Any, *args: Any, **kwargs: Any) -> bool:
            raise StoreError("store broke")

        monkeypatch.setattr(StoreTableModel, "replace_data", boom)
        assert _reload(controller) is True
        _assert_unchanged_after_failed_reload(controller, before, sid)
    finally:
        controller._close_project_store()


def test_project_validation_failure_changes_nothing(qapp: QApplication, tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    import analytics_studio.controller as ctl
    from analytics_studio.project import ProjectFileError

    controller, csv_file, sid = _setup(tmp_path)
    try:
        before = _snapshot(controller)
        _csv(csv_file, ["id", "val"], [["3", "C"]])

        def bad(project: Any) -> Any:
            raise ProjectFileError("project is invalid")

        monkeypatch.setattr(ctl, "validate_project", bad)
        assert _reload(controller) is True
        assert _snapshot(controller) == before
        assert controller._project_store.call(lambda s: s.table_names()) == [ProjectStore.table_name(sid, 1)]
        assert controller.statusMessage == FAIL_SENTENCE
    finally:
        controller._close_project_store()


def test_exception_after_the_swap_restores_everything(qapp: QApplication, tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    controller, csv_file, sid = _setup(tmp_path)
    try:
        before = _snapshot(controller)
        _csv(csv_file, ["id", "val"], [["3", "C"], ["4", "D"], ["5", "E"]])

        def boom(self: StudioController) -> None:
            raise RuntimeError("refresh broke")

        monkeypatch.setattr(StudioController, "_refresh_report", boom)
        assert _reload(controller) is True
        monkeypatch.undo()
        _assert_unchanged_after_failed_reload(controller, before, sid)
    finally:
        controller._close_project_store()


def test_reload_then_save_keeps_the_grid_on_a_live_table(qapp: QApplication, tmp_path: Path) -> None:
    controller, csv_file, sid = _setup(tmp_path)
    try:
        _csv(csv_file, ["id", "val"], [["3", "Cherry"], ["4", "Date"], ["5", "Cherry"]])
        assert _reload(controller) is True
        g2 = ProjectStore.table_name(sid, 2)
        assert controller._store_table_model._table_name == g2
        assert controller._save_to(tmp_path / "p.npa") is True
        assert controller._project_store.call(lambda s: s.table_names()) == [g2]
        model = controller._store_table_model
        model.setColumnFilter("val", "equals", "Cherry")
        assert model.rowCount() == 2
    finally:
        controller._close_project_store()


def test_failed_reload_then_save_keeps_the_old_table_and_grid(qapp: QApplication, tmp_path: Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    controller, csv_file, sid = _setup(tmp_path)
    try:
        _csv(csv_file, ["id", "val"], [["3", "C"]])
        monkeypatch.setattr(StoreTableModel, "replace_data", lambda self, *a, **k: False)
        assert _reload(controller) is True
        monkeypatch.undo()
        assert controller._save_to(tmp_path / "p.npa") is True
        model = controller._store_table_model
        model.setColumnFilter("val", "equals", "A")
        assert model.rowCount() == 1
    finally:
        controller._close_project_store()


# ------------------------------------------------------------------ M2

def _calc_controller(tmp_path: Path, csv_name: str = "src.csv") -> tuple[StudioController, Path, str]:
    return _setup(tmp_path, name=csv_name, headers=["id", "amt", "cat"], rows=[["1", "10", "A"]])


def _reload_without_amt(controller: StudioController, csv_file: Path) -> None:
    _csv(csv_file, ["id", "cat"], [["1", "A"]])
    assert _reload(controller) is True


def _refused(controller: StudioController, sid: str) -> None:
    assert "The reloaded file no longer has the columns amt that the project uses. " \
           "The large-data table was not reloaded." in controller.statusMessage
    assert controller._project_store.call(lambda s: s.table_names()) == [ProjectStore.table_name(sid, 1)]


def test_measure_with_other_case_column_is_detected(qapp: QApplication, tmp_path: Path) -> None:
    controller, csv_file, sid = _calc_controller(tmp_path)
    try:
        controller._project.setdefault("model", {}).setdefault("measures", []).append(
            {"name": "T", "expression": "SUM(src[AMT])"})
        _reload_without_amt(controller, csv_file)
        _refused(controller, sid)
    finally:
        controller._close_project_store()


def test_removed_column_with_capitals_is_reported_by_its_own_name(qapp: QApplication, tmp_path: Path) -> None:
    controller, csv_file, sid = _setup(tmp_path, name="src.csv", headers=["id", "Amt"], rows=[["1", "10"]])
    try:
        controller._project.setdefault("model", {}).setdefault("measures", []).append(
            {"name": "T", "expression": "SUM(src[amt])"})
        assert controller._columns_used_in_project(sid, ["Amt"]) == ["Amt"]
        _csv(csv_file, ["id"], [["1"]])
        assert _reload(controller) is True
        assert "columns Amt that the project uses" in controller.statusMessage
    finally:
        controller._close_project_store()


def test_measure_with_other_case_table_name_is_detected(qapp: QApplication, tmp_path: Path) -> None:
    controller, csv_file, sid = _calc_controller(tmp_path)
    try:
        controller._project.setdefault("model", {}).setdefault("measures", []).append(
            {"name": "T", "expression": "SUM(SRC[amt])"})
        _reload_without_amt(controller, csv_file)
        _refused(controller, sid)
    finally:
        controller._close_project_store()


def test_measure_with_quoted_table_name_is_detected(qapp: QApplication, tmp_path: Path) -> None:
    controller, csv_file, sid = _calc_controller(tmp_path)
    try:
        controller._project.setdefault("model", {}).setdefault("measures", []).append(
            {"name": "T", "expression": "SUM('Src'[Amt])"})
        _reload_without_amt(controller, csv_file)
        _refused(controller, sid)
    finally:
        controller._close_project_store()


def test_table_less_reference_with_other_case_is_detected(qapp: QApplication, tmp_path: Path) -> None:
    controller, csv_file, sid = _calc_controller(tmp_path)
    try:
        controller._project.setdefault("model", {}).setdefault("measures", []).append(
            {"name": "T", "expression": "SUM([AMT])"})
        _reload_without_amt(controller, csv_file)
        _refused(controller, sid)
    finally:
        controller._close_project_store()


def test_relationship_column_with_other_case_is_detected(qapp: QApplication, tmp_path: Path) -> None:
    controller, csv_file, sid = _calc_controller(tmp_path)
    try:
        model = controller._project.setdefault("model", {})
        model.setdefault("relationships", []).append(
            {"from_table_id": sid, "from_column": "AMT", "to_table_id": "other", "to_column": "k"})
        _reload_without_amt(controller, csv_file)
        _refused(controller, sid)
        model["relationships"] = [
            {"from_table_id": "other", "from_column": "k", "to_table_id": sid, "to_column": "AMT"}]
        _reload_without_amt(controller, csv_file)
        _refused(controller, sid)
    finally:
        controller._close_project_store()


def test_calculated_column_with_other_case_is_detected(qapp: QApplication, tmp_path: Path) -> None:
    controller, csv_file, sid = _calc_controller(tmp_path)
    try:
        table = controller._project["model"]["tables"][0]
        table["calculated_columns"] = [{"name": "Double", "expression": "[AMT] * 2"}]
        _reload_without_amt(controller, csv_file)
        _refused(controller, sid)
        table["calculated_columns"] = [{"name": "Double", "expression": "SRC[AMT] * 2"}]
        _reload_without_amt(controller, csv_file)
        _refused(controller, sid)
    finally:
        controller._close_project_store()


def test_unparsable_measure_with_the_column_is_refused(qapp: QApplication, tmp_path: Path,
                                                       caplog: pytest.LogCaptureFixture) -> None:
    controller, csv_file, sid = _calc_controller(tmp_path)
    try:
        controller._project.setdefault("model", {}).setdefault("measures", []).append(
            {"name": "T", "expression": "SUM(src[AMT]"})
        with caplog.at_level(logging.WARNING, logger="analytics_studio.controller"):
            _reload_without_amt(controller, csv_file)
        _refused(controller, sid)
        assert any("could not be parsed" in record.getMessage() for record in caplog.records)
    finally:
        controller._close_project_store()


def test_unparsable_calculated_column_with_the_column_is_refused(qapp: QApplication, tmp_path: Path) -> None:
    controller, csv_file, sid = _calc_controller(tmp_path)
    try:
        controller._project["model"]["tables"][0]["calculated_columns"] = [
            {"name": "Bad", "expression": "((([Amt]"}]
        _reload_without_amt(controller, csv_file)
        _refused(controller, sid)
    finally:
        controller._close_project_store()


def test_unparsable_measure_without_the_column_is_not_used(qapp: QApplication, tmp_path: Path) -> None:
    controller, csv_file, sid = _calc_controller(tmp_path)
    try:
        controller._project.setdefault("model", {}).setdefault("measures", []).append(
            {"name": "T", "expression": "SUM((("})
        assert controller._columns_used_in_project(sid, ["amt"]) == []
        _reload_without_amt(controller, csv_file)
        assert "no longer has the columns" not in controller.statusMessage
    finally:
        controller._close_project_store()


def test_other_columns_are_not_reported(qapp: QApplication, tmp_path: Path) -> None:
    controller, csv_file, sid = _calc_controller(tmp_path)
    try:
        model = controller._project.setdefault("model", {})
        model.setdefault("measures", []).append({"name": "T", "expression": "SUM(src[cat])"})
        model["relationships"] = [
            {"from_table_id": "other", "from_column": "AMT", "to_table_id": "x", "to_column": "AMT"}]
        assert controller._columns_used_in_project(sid, ["amt"]) == []
    finally:
        controller._close_project_store()


# ------------------------------------------------------------------ M3

def test_answer_no_sets_a_plain_status(qapp: QApplication, tmp_path: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    controller, csv_file, sid = _setup(tmp_path)
    try:
        assert controller.statusMessage.startswith("Saved")
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
        _csv(csv_file, ["id", "other"], [["1", "A"]])
        assert _reload(controller) is True
        assert controller.statusMessage == "Reload canceled."
        assert controller._project_store.call(lambda s: s.table_names()) == [ProjectStore.table_name(sid, 1)]
    finally:
        controller._close_project_store()


def test_refusal_sets_the_refusal_status(qapp: QApplication, tmp_path: Path) -> None:
    controller, csv_file, sid = _calc_controller(tmp_path)
    try:
        controller._project.setdefault("model", {}).setdefault("measures", []).append(
            {"name": "T", "expression": "SUM(src[amt])"})
        assert controller.statusMessage.startswith("Saved")
        _reload_without_amt(controller, csv_file)
        assert controller.statusMessage == (
            "The reloaded file no longer has the columns amt that the project uses. "
            "The large-data table was not reloaded."
        )
    finally:
        controller._close_project_store()


# ------------------------------------------------------------------ M4

def test_changed_columns_question_defaults_to_no(qapp: QApplication, tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    controller, csv_file, sid = _setup(tmp_path)
    seen: list[Any] = []
    try:
        def fake(parent: Any, title: str, msg: str, buttons: Any, default: Any = None) -> Any:
            seen.append((buttons, default))
            return QMessageBox.StandardButton.No

        monkeypatch.setattr(QMessageBox, "question", fake)
        _csv(csv_file, ["id", "other"], [["1", "A"]])
        assert _reload(controller) is True
        assert len(seen) == 1
        buttons, default = seen[0]
        assert default == QMessageBox.StandardButton.No
        assert buttons == QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    finally:
        controller._close_project_store()


def test_question_box_real_default_button_is_no(qapp: QApplication, tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    controller, csv_file, sid = _setup(tmp_path)
    seen: list[Any] = []
    try:
        def spy(parent: Any, title: str, msg: str, buttons: Any, default: Any) -> Any:
            box = QMessageBox(QMessageBox.Icon.Question, title, msg, buttons)
            box.setDefaultButton(default)
            seen.append(box.defaultButton().text() if box.defaultButton() else "")
            box.deleteLater()
            return QMessageBox.StandardButton.No

        monkeypatch.setattr(QMessageBox, "question", spy)
        _csv(csv_file, ["id", "other"], [["1", "A"]])
        assert _reload(controller) is True
        assert len(seen) == 1
        assert seen[0].replace("&", "") == "No"
    finally:
        controller._close_project_store()


def test_second_reload_is_refused_while_one_runs(qapp: QApplication, tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    import analytics_studio.store.large_import as li

    controller, csv_file, sid = _setup(tmp_path)
    gate = threading.Event()
    real = li.run_large_import

    def slow(*args: Any, **kwargs: Any) -> Any:
        gate.wait(15)
        return real(*args, **kwargs)

    try:
        monkeypatch.setattr(li, "run_large_import", slow)
        _csv(csv_file, ["id", "val"], [["3", "C"]])
        assert controller.reloadLargeTable() is True
        controller._set_status("before")
        assert controller.reloadLargeTable() is False
        assert controller.statusMessage == "A large-data import is already running."
        gate.set()
        _wait(controller)
        assert "Reloaded 1 rows" in controller.statusMessage
    finally:
        gate.set()
        controller._close_project_store()


def test_table_record_column_types_follow_the_swap(qapp: QApplication, tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    controller, csv_file, sid = _calc_controller(tmp_path)
    try:
        old_types = dict(controller._project["model"]["tables"][0]["column_types"])
        assert old_types["amt"] != "text"
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        _csv(csv_file, ["id", "amt", "cat"], [["1", "Ten", "A"]])
        assert _reload(controller) is True
        record = controller._project["model"]["tables"][0]
        assert record["column_types"]["amt"] == "text"
        assert record["column_types"] == dict(controller._active_store_candidate.model_types)
    finally:
        controller._close_project_store()


def test_validate_table_runs_on_the_new_table_before_the_swap(qapp: QApplication, tmp_path: Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    controller, csv_file, sid = _setup(tmp_path)
    calls: list[tuple[Any, ...]] = []
    old_candidate = controller._active_store_candidate
    real = ProjectStore.validate_table

    def spy(self: ProjectStore, table: str, *args: Any) -> Any:
        calls.append((table, controller._active_store_candidate is old_candidate))
        return real(self, table, *args)

    try:
        monkeypatch.setattr(ProjectStore, "validate_table", spy)
        _csv(csv_file, ["id", "val"], [["3", "C"]])
        assert _reload(controller) is True
        assert calls == [(ProjectStore.table_name(sid, 2), True)]
        assert controller._active_store_candidate is not old_candidate
    finally:
        controller._close_project_store()


def test_failing_validate_table_changes_nothing(qapp: QApplication, tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch,
                                                no_blocking_dialogs: list[str]) -> None:
    controller, csv_file, sid = _setup(tmp_path)
    try:
        before = _snapshot(controller)

        def bad(self: ProjectStore, *args: Any) -> None:
            raise StoreError("table is damaged")

        monkeypatch.setattr(ProjectStore, "validate_table", bad)
        _csv(csv_file, ["id", "val"], [["3", "C"]])
        assert _reload(controller) is True
        assert _snapshot(controller) == before
        assert no_blocking_dialogs == ["table is damaged"]
        assert controller._project_store.call(lambda s: s.table_names()) == [ProjectStore.table_name(sid, 1)]
    finally:
        controller._close_project_store()


def test_all_candidate_maps_and_stats_point_at_the_new_candidate(qapp: QApplication,
                                                                 tmp_path: Path) -> None:
    controller, csv_file, sid = _setup(tmp_path)
    try:
        old = controller._active_store_candidate
        old_stats = old.stats
        _csv(csv_file, ["id", "val"], [["3", "C"], ["4", "D"], ["5", "E"]])
        assert _reload(controller) is True
        new = controller._active_store_candidate
        assert new is not old
        assert controller._loaded_candidates[sid] is new
        assert controller._raw_candidates[sid] is new
        assert controller._query_candidates[sid] is new
        assert new.stats is not None
        assert new.stats is not old_stats
        assert new.stats.rows == 3
        assert new.stats.table == ProjectStore.table_name(sid, 2)
    finally:
        controller._close_project_store()


def _warn_csv(path: Path, rows: int = 2000) -> Path:
    return _csv(path, ["id", "name"], [[str(i), f"n{i}"] for i in range(rows)])


def test_summary_offer_follows_the_warnings(qapp: QApplication, tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(StudioController, "_run_store_summary_dialog",
                        lambda self, candidate: calls.append(candidate))
    controller, csv_file, sid = _setup(tmp_path, headers=["id", "name"],
                                       rows=[[str(i), f"n{i}"] for i in range(2000)])
    try:
        assert calls == []
        # clean reload: no offer
        _warn_csv(csv_file, 1999)
        assert _reload(controller) is True
        assert calls == []
        # reload with warnings: one offer on the new candidate
        monkeypatch.setattr(st, "_UNIQUE_MIN_ROWS", 10)
        _warn_csv(csv_file, 2001)
        assert _reload(controller) is True
        assert calls == [controller._active_store_candidate]
    finally:
        controller._close_project_store()


@pytest.mark.parametrize("state", ["busy", "closed"])
def test_post_save_drop_is_skipped_when_store_is_busy_or_closed(
        qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    controller, csv_file, sid = _setup(tmp_path)
    try:
        _csv(csv_file, ["id", "val"], [["3", "C"]])
        assert _reload(controller) is True
        drops: list[Any] = []
        monkeypatch.setattr(ProjectStore, "drop_unreferenced", lambda self, keep: drops.append(keep) or [])
        store = controller._project_store
        real_prop = getattr(ProjectStore, state)
        flag = {"on": False}

        def prop(self: ProjectStore) -> bool:
            return True if flag["on"] else real_prop.fget(self)

        monkeypatch.setattr(ProjectStore, state, property(prop))
        # turn the state on only after the save itself has written the data file
        real_set_status = StudioController._set_status

        def set_status(self: StudioController, text: str) -> None:
            if text.startswith("Saved"):
                flag["on"] = True
            real_set_status(self, text)

        monkeypatch.setattr(StudioController, "_set_status", set_status)
        assert controller._save_to(tmp_path / "p.npa") is True
        assert controller.statusMessage.startswith("Saved")
        assert drops == []
        flag["on"] = False
        assert ProjectStore.table_name(sid, 1) in store.call(lambda s: s.table_names())
    finally:
        controller._close_project_store()


def test_reload_and_summary_buttons_visibility(qapp: QApplication, tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtCore import QObject, QUrl
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    from analytics_studio.file_import import parse_file

    monkeypatch.setattr(StudioController, "_run_store_summary_dialog", lambda self, candidate: None)
    QQuickStyle.setStyle("Basic")
    controller = StudioController()
    engine = QQmlEngine()
    component = QQmlComponent(engine)
    component.loadUrl(QUrl.fromLocalFile(str(REPO_ROOT / "analytics_studio" / "qml" / "Main.qml")))
    assert not component.isError(), "\n".join(error.toString() for error in component.errors())
    window = component.createWithInitialProperties({"studioController": controller})
    assert window is not None, "\n".join(error.toString() for error in component.errors())
    try:
        controller.setCurrentView("Data")
        qapp.processEvents()
        reload_button = window.findChild(QObject, "reloadTableButton")
        summary_button = window.findChild(QObject, "tableSummaryButton")
        assert reload_button is not None and summary_button is not None
        assert reload_button.property("visible") is False
        assert summary_button.property("visible") is False

        small = _csv(tmp_path / "ordinary.csv", ["a", "b"], [["1", "x"], ["2", "y"]])
        assert controller._commit_import(small, parse_file(small)) is True
        qapp.processEvents()
        assert controller.largeTableLoaded is False
        assert reload_button.property("visible") is False
        assert summary_button.property("visible") is False

        big = _csv(tmp_path / "large.csv", ["id", "val"], [["1", "A"], ["2", "B"]])
        _import_initial(controller, big)
        qapp.processEvents()
        assert controller.largeTableLoaded is True
        assert reload_button.property("visible") is True
        assert summary_button.property("visible") is True
    finally:
        window.deleteLater()
        engine.deleteLater()
        qapp.processEvents()
        controller._close_project_store()


# ------------------------------------------------------------------ M5

def test_reload_flag_exists_on_a_fresh_controller(qapp: QApplication) -> None:
    controller = StudioController()
    assert controller.__dict__["_large_import_is_reload"] is False
