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
    app = QApplication.instance() or QApplication(["visual clipboard tests"])
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("Category,Amount\nA,10\nB,20\n", encoding="utf-8")
    controller = StudioController(
        app,
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )
    assert controller._commit_import(csv_path, parse_file(csv_path))
    controller.add_visual("bar", "Source chart", 40, 50, 360, 240)
    controller.add_field_to_well("X-axis", "Category")
    controller.add_field_to_well("Y-axis", "Amount")
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


def test_visual_copy_cut_and_paste_keep_clipboard_through_refresh_and_reopen(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication(["visual clipboard QML tests"])
    controller = _controller(tmp_path)
    controller.selectVisual("Source chart")
    engine, component, window = _qml_window(controller)
    source = next(item for item in controller.activeVisualObjects if item["title"] == "Source chart")

    try:
        window.show()
        window.runCommand("format.copy")
        assert controller._clipboard_visual_config["title"] == "Source chart"

        window.runCommand("format.paste")
        app.processEvents()
        pasted = next(
            item for item in controller.activeVisualObjects
            if item["title"] == "Source chart (2)"
        )
        assert pasted["id"] != source["id"]
        assert (pasted["x"], pasted["y"]) == (source["x"] + 20, source["y"] + 20)
        assert pasted["fields"] == source["fields"]
        assert pasted["field_aggregations"] == source["field_aggregations"]

        window.runCommand("format.cut")
        app.processEvents()
        assert not any(item["title"] == "Source chart (2)" for item in controller.activeVisualObjects)
        assert controller._clipboard_visual_config["title"] == "Source chart (2)"

        window.runCommand("format.paste")
        app.processEvents()
        restored = next(
            item for item in controller.activeVisualObjects
            if item["title"] == "Source chart (2)"
        )
        assert restored["id"] != pasted["id"]
        assert (restored["x"], restored["y"]) == (pasted["x"] + 20, pasted["y"] + 20)

        project_path = tmp_path / "visual-clipboard.npa"
        assert controller._save_to(project_path)
        reopened = StudioController(
            app,
            QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened.open_project_path(project_path)
        reopened_visual = next(
            item for item in reopened.activeVisualObjects
            if item["title"] == "Source chart (2)"
        )
        assert reopened_visual["fields"] == source["fields"]
        assert (reopened_visual["x"], reopened_visual["y"]) == (
            restored["x"], restored["y"]
        )
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        app.processEvents()


def test_format_painter_copies_visual_format_once_without_changing_chart_type(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication(["format painter tests"])
    controller = _controller(tmp_path)
    controller.set_visual_property("color", "#123ABC")
    controller.set_visual_property("show_data_labels", False)
    controller.set_visual_property("show_legend", True)
    controller.add_visual("line", "Target chart", 450, 50, 360, 240)
    target_before = next(
        item for item in controller.activeVisualObjects
        if item["title"] == "Target chart"
    )
    target_before.update({
        "color": "#ABCDEF",
        "show_data_labels": True,
        "show_legend": False,
    })
    controller.selectVisual("Source chart")
    engine, component, window = _qml_window(controller)

    try:
        window.show()
        controller._dirty = False
        window.runCommand("format.painter")
        app.processEvents()
        assert controller.formatPainterActive is True

        controller.apply_format_painter("Target chart")
        assert controller.formatPainterActive is False
        target = next(
            item for item in controller.activeVisualObjects
            if item["title"] == "Target chart"
        )
        assert target["color"] == "#123ABC"
        assert target["show_data_labels"] is False
        assert target["show_legend"] is True
        assert target["type"] == "line"
        assert (target["x"], target["y"], target["width"], target["height"]) == (
            target_before["x"], target_before["y"],
            target_before["width"], target_before["height"],
        )
        assert controller.dirty

        controller.add_visual("column", "Unpainted chart", 860, 50, 360, 240)
        unpainted = next(
            item for item in controller.activeVisualObjects
            if item["title"] == "Unpainted chart"
        )
        controller.apply_format_painter("Unpainted chart")
        assert "color" not in unpainted
        assert controller.formatPainterActive is False

        project_path = tmp_path / "painted-visual.npa"
        assert controller._save_to(project_path)
        reopened = StudioController(
            app,
            QSettings(str(tmp_path / "painted-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened.open_project_path(project_path)
        painted = next(
            item for item in reopened.activeVisualObjects
            if item["title"] == "Target chart"
        )
        assert painted["color"] == "#123ABC"
        assert painted["show_data_labels"] is False
        assert painted["show_legend"] is True
        assert painted["type"] == "line"
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        app.processEvents()
