from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QSettings, QUrl, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file

QQuickStyle.setStyle("Basic")


def _items(item: QQuickItem):
    yield item
    for child in item.childItems():
        yield from _items(child)


def _write_csv(path: Path, rows: list[str]) -> None:
    path.write_text("Step,Change\n" + "\n".join(rows) + "\n", encoding="utf-8")


def test_waterfall_running_totals_interaction_and_persistence(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["waterfall visual tests"])
    csv_path = tmp_path / "bridge.csv"
    _write_csv(csv_path, ["A,100", "B,-30", "B,-10", "C,50"])
    controller = StudioController(
        app,
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )
    assert controller._commit_import(csv_path, parse_file(csv_path))
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
        window.runCommand("insert.newVisual")
        window.runCommand("chart.type.waterfall")
        visual = controller.activeVisualObjects[-1]
        assert visual["type"] == "waterfall"
        assert visual["title"] == "Waterfall chart"
        assert [well["name"] for well in controller.activeVisualWells] == [
            "X-axis", "Y-axis", "Tooltips",
        ]
        controller.add_field_to_well("X-axis", "Step")
        controller.add_field_to_well("Y-axis", "Change")

        expected = [
            {"label": "A", "value": 100.0},
            {"label": "B", "value": -40.0},
            {"label": "C", "value": 50.0},
        ]
        assert controller.visualSeries("Waterfall chart") == expected
        controller.set_field_aggregation("Y-axis", "Change", "Count")
        assert controller.visualSeries("Waterfall chart") == [
            {"label": "A", "value": 1.0},
            {"label": "B", "value": 2.0},
            {"label": "C", "value": 1.0},
        ]
        controller.set_field_aggregation("Y-axis", "Change", "Average")
        assert controller.visualSeries("Waterfall chart") == [
            {"label": "A", "value": 100.0},
            {"label": "B", "value": -20.0},
            {"label": "C", "value": 50.0},
        ]
        controller.set_field_aggregation("Y-axis", "Change", "Sum")

        app.processEvents()
        QTest.qWait(50)
        card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "chartCard_Waterfall chart"
        )
        assert card.property("chartType") == "waterfall"
        assert card.property("series") == expected
        canvas = next(
            item for item in _items(card)
            if "CanvasItem" in item.metaObject().className()
        )
        assert canvas.width() > 0 and canvas.height() > 0

        plot_left = 38
        plot_top = 9
        plot_width = canvas.width() - 46
        plot_height = canvas.height() - 34
        step = plot_width / 3
        x = plot_left + step * 1.5
        y_top = plot_top + plot_height * (120 - 100) / 140
        y_bottom = plot_top + plot_height * (120 - 60) / 140
        scene_point = canvas.mapToScene(QPointF(x, (y_top + y_bottom) / 2))
        click_point = QPoint(round(scene_point.x()), round(scene_point.y()))
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click_point)
        QTest.qWait(40)
        app.processEvents()
        assert controller.selectedCrossFiltersForVisual("Waterfall chart") == ["B"]
        controller.toggle_cross_filter("Waterfall chart", "B")

        controller.add_visual("column", "Step source", 800, 500, 300, 200)
        controller.add_field_to_well("X-axis", "Step")
        controller.add_field_to_well("Y-axis", "Change")
        controller.set_visual_interaction("Step source", "Waterfall chart", "highlight")
        controller.toggle_cross_filter("Step source", "B")
        assert controller.visualHighlightSeries("Waterfall chart") == [
            {"label": "B", "value": -40.0},
        ]

        project_path = tmp_path / "waterfall.npa"
        assert controller._save_to(project_path)
        reopened = StudioController(
            QApplication.instance(),
            QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened.open_project_path(project_path)
        saved = next(item for item in reopened.activeVisualObjects if item["title"] == "Waterfall chart")
        assert saved["type"] == "waterfall"
        assert saved["fields"] == {"X-axis": ["Step"], "Y-axis": ["Change"]}
        assert reopened.visualSeries("Waterfall chart") == expected

        _write_csv(csv_path, ["A,120", "B,-20", "B,-20", "C,60"])
        reopened.refresh_source()
        assert reopened.visualSeries("Waterfall chart") == [
            {"label": "A", "value": 120.0},
            {"label": "B", "value": -40.0},
            {"label": "C", "value": 60.0},
        ]
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()
