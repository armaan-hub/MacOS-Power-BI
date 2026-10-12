from __future__ import annotations

import os
from math import cos, pi, sin
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QSettings, QUrl, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file


def _overlaps(left: dict, right: dict) -> bool:
    return (
        float(left["x"]) < float(right["x"]) + float(right["width"])
        and float(left["x"]) + float(left["width"]) > float(right["x"])
        and float(left["y"]) < float(right["y"]) + float(right["height"])
        and float(left["y"]) + float(left["height"]) > float(right["y"])
    )


def _items(item: QQuickItem):
    yield item
    for child in item.childItems():
        yield from _items(child)


def test_insert_visual_chooser_creates_blank_chart_and_persists_field_bindings(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication(["visual chooser tests"])
    source_path = tmp_path / "sales.csv"
    source_path.write_text("Category,Amount\nA,10\nB,25\n", encoding="utf-8")
    controller = StudioController(
        app,
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )
    assert controller._commit_import(source_path, parse_file(source_path))
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
        controller._dirty = False
        existing_visuals = [dict(item) for item in controller.activeVisualObjects]

        window.runCommand("insert.newVisual")

        assert controller.creatingVisual is True
        assert controller.selectedVisual == ""
        assert window.property("visualizationsVisible") is True
        assert window.property("activeVisualTab") == "build"
        assert controller._dirty is False

        # The visual gallery uses this same command when the user picks a chart tile.
        window.runCommand("chart.type.column")

        visual = controller.activeVisualObjects[-1]
        assert visual["type"] == "column"
        assert visual["title"] == "Column chart"
        assert visual.get("fields", {}) == {}
        assert controller.selectedVisual == "Column chart"
        assert controller.selectedChartType == "column"
        assert controller.creatingVisual is False
        assert not any(_overlaps(visual, old) for old in existing_visuals)

        controller.add_field_to_well("X-axis", "Category")
        controller.add_field_to_well("Y-axis", "Amount")
        assert controller.visualSeries("Column chart") == [
            {"label": "A", "value": 10.0},
            {"label": "B", "value": 25.0},
        ]

        project_path = tmp_path / "visual-chooser.npa"
        assert controller._save_to(project_path)
        reopened = StudioController(
            QApplication.instance(),
            QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened.open_project_path(project_path)
        saved = next(item for item in reopened.activeVisualObjects if item["id"] == visual["id"])
        assert saved["type"] == "column"
        assert saved["fields"] == {"X-axis": ["Category"], "Y-axis": ["Amount"]}
        assert reopened.visualSeries("Column chart") == [
            {"label": "A", "value": 10.0},
            {"label": "B", "value": 25.0},
        ]

        window.runCommand("insert.newVisual")
        window.runCommand("chart.type.area")
        area_visual = controller.activeVisualObjects[-1]
        assert area_visual["type"] == "area"
        assert area_visual["title"] == "Area chart"
        controller.add_field_to_well("X-axis", "Category")
        controller.add_field_to_well("Y-axis", "Amount")
        assert controller.visualSeries("Area chart") == [
            {"label": "A", "value": 10.0},
            {"label": "B", "value": 25.0},
        ]
        app.processEvents()
        area_card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "chartCard_Area chart"
        )
        assert area_card.property("chartType") == "area"
        assert area_card.property("series") == [
            {"label": "A", "value": 10.0},
            {"label": "B", "value": 25.0},
        ]

        assert controller._save_to(project_path)
        reopened_area = StudioController(
            QApplication.instance(),
            QSettings(str(tmp_path / "reopened-area-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened_area.open_project_path(project_path)
        saved_area = next(
            item for item in reopened_area.activeVisualObjects if item["id"] == area_visual["id"]
        )
        assert saved_area["type"] == "area"
        assert saved_area["fields"] == {"X-axis": ["Category"], "Y-axis": ["Amount"]}
        assert reopened_area.visualSeries("Area chart") == [
            {"label": "A", "value": 10.0},
            {"label": "B", "value": 25.0},
        ]

        for chart_type, title in (("pie", "Pie chart"), ("donut", "Donut chart")):
            window.runCommand("insert.newVisual")
            window.runCommand(f"chart.type.{chart_type}")
            chart_visual = controller.activeVisualObjects[-1]
            assert chart_visual["type"] == chart_type
            assert chart_visual["title"] == title
            assert controller.selectedChartType == chart_type
            assert [well["name"] for well in controller.activeVisualWells] == [
                "X-axis", "Y-axis", "Legend", "Tooltips",
            ]
            controller.add_field_to_well("X-axis", "Category")
            controller.add_field_to_well("Y-axis", "Amount")
            controller.set_visual_property("show_legend", True)
            controller.set_visual_property("show_data_labels", True)
            assert controller.visualSeries(title) == [
                {"label": "B", "value": 25.0},
                {"label": "A", "value": 10.0},
            ]
            app.processEvents()
            QTest.qWait(50)
            chart_card = next(
                item for item in _items(window.contentItem())
                if item.objectName() == f"chartCard_{title}"
            )
            assert chart_card.property("chartType") == chart_type
            assert chart_card.property("series") == controller.visualSeries(title)
            canvas = next(
                item for item in _items(chart_card)
                if "CanvasItem" in item.metaObject().className()
            )
            assert canvas.width() > 0 and canvas.height() > 0

            geometry = {
                "center_x": canvas.width() * 0.30,
                "center_y": canvas.height() / 2,
                "radius": min(canvas.width() * 0.60, canvas.height()) * 0.40,
            }
            first_slice_middle = -pi / 2 + pi * (25 / 35)
            local_slice = QPointF(
                geometry["center_x"] + geometry["radius"] * 0.70 * cos(first_slice_middle),
                geometry["center_y"] + geometry["radius"] * 0.70 * sin(first_slice_middle),
            )
            scene_slice = canvas.mapToScene(local_slice)
            click_slice = QPoint(round(scene_slice.x()), round(scene_slice.y()))
            QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click_slice)
            QTest.qWait(50)
            app.processEvents()
            assert controller.selectedCrossFiltersForVisual(title) == ["B"]

            if chart_type == "donut":
                scene_hole = canvas.mapToScene(QPointF(geometry["center_x"], geometry["center_y"]))
                QTest.mouseClick(
                    window,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                    QPoint(round(scene_hole.x()), round(scene_hole.y())),
                )
                QTest.qWait(50)
                app.processEvents()
                assert controller.selectedCrossFiltersForVisual(title) == ["B"]

            QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click_slice)
            QTest.qWait(50)
            app.processEvents()
            assert controller.selectedCrossFiltersForVisual(title) == []

        assert controller._save_to(project_path)
        reopened_pie = StudioController(
            QApplication.instance(),
            QSettings(str(tmp_path / "reopened-pie-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened_pie.open_project_path(project_path)
        for chart_type, title in (("pie", "Pie chart"), ("donut", "Donut chart")):
            saved_chart = next(
                item for item in reopened_pie.activeVisualObjects if item["title"] == title
            )
            assert saved_chart["type"] == chart_type
            assert saved_chart["fields"] == {"X-axis": ["Category"], "Y-axis": ["Amount"]}
            assert saved_chart["show_legend"] is True
            assert saved_chart["show_data_labels"] is True
            assert reopened_pie.visualSeries(title) == [
                {"label": "B", "value": 25.0},
                {"label": "A", "value": 10.0},
            ]
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()
