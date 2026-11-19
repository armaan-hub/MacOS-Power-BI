from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController

QQuickStyle.setStyle("Basic")


def _controller(tmp_path: Path, settings_name: str) -> StudioController:
    app = QApplication.instance() or QApplication(["static visual tests"])
    return StudioController(
        app,
        QSettings(str(tmp_path / settings_name), QSettings.Format.IniFormat),
    )


def _items(item: QQuickItem):
    yield item
    for child in item.childItems():
        yield from _items(child)


def _wait_until(condition, timeout_seconds: float = 5.0) -> bool:
    # Bounded poll: the Image in the report canvas loads asynchronously, so a
    # single processEvents() can return before it is Ready on a loaded machine.
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        QTest.qWait(10)
    return bool(condition())


def test_static_visuals_insert_render_edit_and_reopen(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["static visual QML tests"])
    controller = _controller(tmp_path, "settings.ini")
    image_path = tmp_path / "report image.png"
    image = QImage(12, 12, QImage.Format.Format_RGB32)
    image.fill(0xFF336699)
    assert image.save(str(image_path))

    engine = QQmlEngine()
    component = QQmlComponent(engine)
    qml_path = Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml"
    component.loadUrl(QUrl.fromLocalFile(str(qml_path)))
    assert not component.isError(), "\n".join(error.toString() for error in component.errors())
    window = component.createWithInitialProperties({"studioController": controller})
    assert window is not None, "\n".join(error.toString() for error in component.errors())

    try:
        window.show()
        controller.setCurrentView("Report")
        window.runCommand("insert.textBox")
        text_visual = controller.activeVisualObjects[-1]
        assert text_visual["title"].startswith("Text Box ")
        text_visual_id = text_visual["id"]
        controller.set_visual_property("text", "Notes for the report")

        with patch(
            "analytics_studio.controller.QFileDialog.getOpenFileName",
            return_value=(str(image_path), "Images (*.png)"),
        ):
            window.runCommand("insert.image")
        image_visual = controller.activeVisualObjects[-1]
        assert image_visual["type"] == "image"
        image_visual_id = image_visual["id"]

        shape_id = controller.add_visual("shape", "Rectangle", 420, 100, 100, 100)
        controller.selectVisual("Rectangle")
        controller.resize_visual(shape_id, 130, 90)
        app.processEvents()

        def _find(name: str):
            return next((item for item in _items(window.contentItem()) if item.objectName() == name), None)

        text_name = f"reportTextInput_{text_visual_id}"
        image_name = f"reportImageContainer_{image_visual_id}"
        shape_name = f"reportShape_{shape_id}"
        assert _wait_until(lambda: all(_find(n) is not None for n in (text_name, image_name, shape_name)))
        text_area = _find(text_name)
        image_container = _find(image_name)
        shape_item = _find(shape_name)
        assert text_area.property("text") == "Notes for the report"
        controller.selectVisual(text_visual["title"])
        text_area.forceActiveFocus()
        text_area.setProperty("text", "Typed on the canvas")
        app.processEvents()
        assert next(item for item in controller.activeVisualObjects if item["id"] == text_visual_id)["text"] == "Typed on the canvas"
        assert image_container.property("isImageVisual") is True
        assert _wait_until(lambda: image_container.property("imageReady") is True)
        assert shape_item.property("isShapeVisual") is True
        assert next(item for item in controller.activeVisualObjects if item["id"] == shape_id)["width"] == 130

        project_path = tmp_path / "static-visuals.npa"
        assert controller._save_to(project_path)
        saved = json.loads(project_path.read_text(encoding="utf-8"))
        saved_image = next(
            visual for page in saved["report"]["pages"] for visual in page["visuals"]
            if visual["id"] == image_visual_id
        )
        assert saved_image["image_path"] == "report image.png"

        reopened = _controller(tmp_path, "reopened-settings.ini")
        assert reopened.open_project_path(project_path)
        reopened_visuals = reopened.activeVisualObjects
        assert next(item for item in reopened_visuals if item["id"] == text_visual_id)["text"] == "Typed on the canvas"
        assert next(item for item in reopened_visuals if item["id"] == shape_id)["height"] == 90
        assert next(item for item in reopened_visuals if item["id"] == image_visual_id)["image_path"] == str(image_path.resolve())
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()
