from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file

QQuickStyle.setStyle("Basic")


def _controller(tmp_path: Path) -> StudioController:
    app = QApplication.instance() or QApplication(["visual group tests"])
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("Category,Amount\nA,10\nB,20\n", encoding="utf-8")
    controller = StudioController(
        app,
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )
    assert controller._commit_import(csv_path, parse_file(csv_path))
    controller.add_visual("bar", "First chart", 40, 40, 360, 240)
    controller.add_visual("column", "Second chart", 450, 40, 360, 240)
    controller.add_visual("line", "Third chart", 860, 40, 360, 240)
    return controller


def _qml_window(controller: StudioController):
    engine = QQmlEngine()
    component = QQmlComponent(engine)
    qml_path = Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml"
    component.loadUrl(QUrl.fromLocalFile(str(qml_path)))
    assert not component.isError(), "\n".join(error.toString() for error in component.errors())
    window = component.createWithInitialProperties({"studioController": controller})
    assert window is not None, "\n".join(error.toString() for error in component.errors())
    return engine, component, window


def _visual(controller: StudioController, title: str) -> dict:
    return next(item for item in controller.activeVisualObjects if item["title"] == title)


def _items(item: QQuickItem):
    yield item
    for child in item.childItems():
        yield from _items(child)


def test_shift_select_group_move_reopen_and_ungroup(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["visual group QML tests"])
    controller = _controller(tmp_path)
    controller.selectVisual("First chart")
    engine, component, window = _qml_window(controller)

    try:
        window.show()
        second_card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "chartCard_Second chart"
        )
        assert second_card.requestSelection(Qt.KeyboardModifier.ShiftModifier.value) is False
        app.processEvents()

        first = _visual(controller, "First chart")
        second = _visual(controller, "Second chart")
        assert set(controller.selectedVisualIds) == {first["id"], second["id"]}
        first_card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "chartCard_First chart"
        )
        assert first_card.property("selected") is True
        assert second_card.property("selected") is True

        window.runCommand("arrange.group")
        app.processEvents()
        first = _visual(controller, "First chart")
        second = _visual(controller, "Second chart")
        third = _visual(controller, "Third chart")
        group_id = first["group_id"]
        assert group_id == second["group_id"]
        assert "group_id" not in third

        controller.move_visual(first["id"], 70, 60)
        assert (first["x"], first["y"]) == (70.0, 60.0)
        assert (second["x"], second["y"]) == (480.0, 60.0)
        assert (third["x"], third["y"]) == (860, 40)

        project_path = tmp_path / "visual-group.npa"
        assert controller._save_to(project_path)
        reopened = StudioController(
            app,
            QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened.open_project_path(project_path)
        reopened_first = _visual(reopened, "First chart")
        reopened_second = _visual(reopened, "Second chart")
        assert reopened_first["group_id"] == reopened_second["group_id"] == group_id
        assert (reopened_first["x"], reopened_second["x"]) == (70.0, 480.0)

        reopened.selectVisual("Second chart")
        reopened.ungroup_visuals()
        assert "group_id" not in _visual(reopened, "First chart")
        assert "group_id" not in _visual(reopened, "Second chart")
        assert reopened.dirty
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        app.processEvents()


def test_deleting_a_group_member_dissolves_singleton_group(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    controller.selectVisual("First chart")
    controller.toggleVisualSelection("Second chart")
    controller.group_visuals()
    group_id = _visual(controller, "First chart")["group_id"]

    controller.remove_visual(_visual(controller, "Second chart")["id"])

    remaining = _visual(controller, "First chart")
    assert remaining.get("group_id") != group_id
    assert "group_id" not in remaining
    assert "Second chart" not in [item["title"] for item in controller.activeVisualObjects]
