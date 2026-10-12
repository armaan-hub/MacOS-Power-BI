from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QSettings, Qt, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file


def _items(item: QQuickItem):
    yield item
    for child in item.childItems():
        yield from _items(child)


def _point_in_canvas(points: list[dict[str, object]], canvas: QQuickItem, label: str) -> QPoint:
    point = next(item for item in points if item["label"] == label)
    latitudes = [float(item["latitude"]) for item in points]
    longitudes = [float(item["longitude"]) for item in points]
    latitude_padding = max(0.8, (max(latitudes) - min(latitudes)) * 0.12)
    longitude_padding = max(0.8, (max(longitudes) - min(longitudes)) * 0.12)
    min_latitude = max(-90, min(latitudes) - latitude_padding)
    max_latitude = min(90, max(latitudes) + latitude_padding)
    min_longitude = max(-180, min(longitudes) - longitude_padding)
    max_longitude = min(180, max(longitudes) + longitude_padding)
    plot_width = max(1, canvas.width() - 32)
    plot_height = max(1, canvas.height() - 35)
    x = 16 + (float(point["longitude"]) - min_longitude) / (max_longitude - min_longitude) * plot_width
    y = 9 + (max_latitude - float(point["latitude"])) / (max_latitude - min_latitude) * plot_height
    scene_point = canvas.mapToScene(QPointF(x, y))
    return QPoint(round(scene_point.x()), round(scene_point.y()))


def test_map_visual_coordinates_interactions_and_lifecycle(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["map visual tests"])
    source_path = tmp_path / "locations.csv"
    source_path.write_text(
        "City,Latitude,Longitude,Sales,Country\n"
        "Dubai,25.2048,55.2708,50,UAE\n"
        "Abu Dhabi,24.4539,54.3773,30,UAE\n"
        "London,51.5072,-0.1276,80,UK\n"
        "Invalid,91,200,5,Bad\n",
        encoding="utf-8",
    )
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
        window.runCommand("insert.newVisual")
        window.runCommand("chart.type.map")

        title = "Map"
        visual = controller.activeVisualObjects[-1]
        assert visual["type"] == "map"
        assert controller.selectedChartType == "map"
        assert [well["name"] for well in controller.activeVisualWells] == [
            "Location", "Latitude", "Longitude", "Size", "Legend", "Tooltips",
        ]
        for well, field in (
            ("Location", "City"),
            ("Latitude", "Latitude"),
            ("Longitude", "Longitude"),
            ("Size", "Sales"),
            ("Legend", "Country"),
        ):
            controller.add_field_to_well(well, field)
        controller.add_field_to_well("Latitude", "Longitude")
        assert "one field in each location" in controller.statusMessage
        assert visual["fields"]["Latitude"] == ["Latitude"]

        points = controller.visualMapData(title)
        assert [point["label"] for point in points] == ["Dubai", "Abu Dhabi", "London"]
        assert points[0]["group"] == "UAE"
        assert points[0]["size"] == 50.0
        assert all(-90 <= point["latitude"] <= 90 for point in points)
        assert all(-180 <= point["longitude"] <= 180 for point in points)

        app.processEvents()
        card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == f"chartCard_{title}"
        )
        assert card.property("chartType") == "map"
        assert card.property("mapPoints") == points
        canvas = next(
            item for item in _items(card)
            if "CanvasItem" in item.metaObject().className()
        )
        assert canvas.width() > 0 and canvas.height() > 0
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            _point_in_canvas(points, canvas, "Dubai"),
        )
        app.processEvents()
        assert controller.selectedCrossFiltersForVisual(title) == ["Dubai"]
        controller.toggle_cross_filter(title, "Dubai")

        controller.add_visual("column", "Source", 420, 40, 360, 240)
        controller.add_field_to_well("X-axis", "City")
        controller.add_field_to_well("Y-axis", "Sales")
        controller.set_visual_interaction(title, "Source", "Filter")
        app.processEvents()
        card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == f"chartCard_{title}"
        )
        canvas = next(
            item for item in _items(card)
            if "CanvasItem" in item.metaObject().className()
        )
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            _point_in_canvas(controller.visualMapData(title), canvas, "Dubai"),
        )
        assert controller.visualSeries("Source") == [{"label": "Dubai", "value": 50.0}]
        controller.toggle_cross_filter(title, "Dubai")

        controller.set_visual_interaction("Source", title, "Highlight")
        controller.toggle_cross_filter("Source", "London")
        assert [point["label"] for point in controller.visualMapData(title, True)] == ["London"]
        app.processEvents()
        card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == f"chartCard_{title}"
        )
        assert [point["label"] for point in card.property("highlightMapPoints")] == ["London"]

        controller.set_visual_interaction("Source", title, "Filter")
        assert [point["label"] for point in controller.visualMapData(title)] == ["London"]
        assert controller.visualMapData(title, True) == []
        controller.toggle_cross_filter("Source", "London")
        controller.set_visual_interaction("Source", title, "Highlight")

        project_path = tmp_path / "map-visual.npa"
        assert controller._save_to(project_path)
        reopened = StudioController(
            QApplication.instance(),
            QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened.open_project_path(project_path)
        reopened.selectVisual(title)
        saved = next(item for item in reopened.activeVisualObjects if item["id"] == visual["id"])
        assert saved["fields"] == {
            "Location": ["City"],
            "Latitude": ["Latitude"],
            "Longitude": ["Longitude"],
            "Size": ["Sales"],
            "Legend": ["Country"],
        }
        assert reopened.visualMapData(title) == controller.visualMapData(title)

        source_path.write_text(
            "City,Latitude,Longitude,Sales,Country\n"
            "Dubai,25.2048,55.2708,60,UAE\n"
            "Abu Dhabi,24.4539,54.3773,35,UAE\n"
            "London,51.5072,-0.1276,90,UK\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        refreshed = reopened.visualMapData(title)
        assert [point["size"] for point in refreshed] == [60.0, 35.0, 90.0]
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()
