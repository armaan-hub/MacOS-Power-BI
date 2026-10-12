from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file

QQuickStyle.setStyle("Basic")


def _controller(tmp_path: Path) -> StudioController:
    app = QApplication.instance() or QApplication(["visual z-order tests"])
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


def _custom_order(controller: StudioController) -> list[str]:
    names = {"First chart", "Second chart", "Third chart"}
    return [
        item["title"] for item in controller.activeVisualObjects
        if item["title"] in names
    ]


def test_z_order_commands_reorder_visuals_and_persist_in_page_order(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication(["visual z-order QML tests"])
    controller = _controller(tmp_path)
    engine, component, window = _qml_window(controller)

    try:
        window.show()
        controller.selectVisual("First chart")
        window.runCommand("arrange.bringForward")
        assert _custom_order(controller) == ["Second chart", "First chart", "Third chart"]

        window.runCommand("arrange.sendBackward")
        assert _custom_order(controller) == ["First chart", "Second chart", "Third chart"]

        window.runCommand("arrange.bringToFront")
        assert _custom_order(controller) == ["Second chart", "Third chart", "First chart"]

        window.runCommand("arrange.sendToBack")
        assert _custom_order(controller) == ["First chart", "Second chart", "Third chart"]

        controller._dirty = False
        window.runCommand("arrange.sendToBack")
        assert not controller.dirty
        controller.selectVisual("Third chart")
        window.runCommand("arrange.bringToFront")
        assert not controller.dirty

        project_path = tmp_path / "visual-order.npa"
        assert controller._save_to(project_path)
        reopened = StudioController(
            app,
            QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened.open_project_path(project_path)
        assert _custom_order(reopened) == ["First chart", "Second chart", "Third chart"]
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        app.processEvents()
