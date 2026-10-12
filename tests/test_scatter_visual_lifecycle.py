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
    path.write_text("Order,Product,Spend,Revenue\n" + "\n".join(rows) + "\n", encoding="utf-8")


def test_scatter_points_selection_highlighting_and_persistence(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["scatter visual tests"])
    csv_path = tmp_path / "sales.csv"
    _write_csv(csv_path, [
        "O1,Alpha,10,20", "O2,Beta,20,30", "O3,Alpha,30,50", "O4,Gamma,40,80",
    ])
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

    expected = [
        {"id": "O1|Alpha|10.0|20.0", "label": "O1", "group": "Alpha", "x": 10.0, "y": 20.0},
        {"id": "O2|Beta|20.0|30.0", "label": "O2", "group": "Beta", "x": 20.0, "y": 30.0},
        {"id": "O3|Alpha|30.0|50.0", "label": "O3", "group": "Alpha", "x": 30.0, "y": 50.0},
        {"id": "O4|Gamma|40.0|80.0", "label": "O4", "group": "Gamma", "x": 40.0, "y": 80.0},
    ]

    try:
        window.show()
        controller.setCurrentView("Report")
        window.runCommand("insert.newVisual")
        window.runCommand("chart.type.scatter")
        visual = controller.activeVisualObjects[-1]
        assert visual["type"] == "scatter"
        assert visual["title"] == "Scatter chart"
        assert [well["name"] for well in controller.activeVisualWells] == [
            "X-axis", "Y-axis", "Legend", "Details", "Tooltips",
        ]
        controller.add_field_to_well("X-axis", "Spend")
        controller.add_field_to_well("Y-axis", "Revenue")
        controller.add_field_to_well("Legend", "Product")
        controller.add_field_to_well("Details", "Order")
        controller.set_visual_property("show_legend", True)
        assert controller.visualScatterData("Scatter chart") == expected

        app.processEvents()
        QTest.qWait(50)
        card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "chartCard_Scatter chart"
        )
        assert card.property("chartType") == "scatter"
        assert card.property("scatterPoints") == expected
        canvas = next(
            item for item in _items(card)
            if "CanvasItem" in item.metaObject().className()
        )
        assert canvas.width() > 0 and canvas.height() > 0

        plot_left = 48
        plot_top = 29
        plot_width = canvas.width() - 60
        plot_height = canvas.height() - 63
        scene_point = canvas.mapToScene(QPointF(
            plot_left + plot_width * (30 - 10) / (40 - 10),
            plot_top + plot_height - plot_height * (50 - 20) / (80 - 20),
        ))
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(round(scene_point.x()), round(scene_point.y())),
        )
        QTest.qWait(40)
        app.processEvents()
        assert controller.selectedCrossFiltersForVisual("Scatter chart") == ["O3"]
        controller.toggle_cross_filter("Scatter chart", "O3")

        controller.add_visual("column", "Product source", 800, 500, 300, 200)
        controller.add_field_to_well("X-axis", "Product")
        controller.add_field_to_well("Y-axis", "Revenue")
        controller.set_visual_interaction("Product source", "Scatter chart", "highlight")
        controller.toggle_cross_filter("Product source", "Alpha")
        highlighted = controller.visualScatterData("Scatter chart", include_highlights=True)
        assert [point["label"] for point in highlighted] == ["O1", "O3"]
        app.processEvents()
        card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "chartCard_Scatter chart"
        )
        assert [point["label"] for point in card.property("highlightScatterPoints")] == ["O1", "O3"]

        project_path = tmp_path / "scatter.npa"
        assert controller._save_to(project_path)
        reopened = StudioController(
            QApplication.instance(),
            QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened.open_project_path(project_path)
        saved = next(item for item in reopened.activeVisualObjects if item["title"] == "Scatter chart")
        assert saved["type"] == "scatter"
        assert saved["fields"] == {
            "X-axis": ["Spend"], "Y-axis": ["Revenue"],
            "Legend": ["Product"], "Details": ["Order"],
        }
        assert saved["show_legend"] is True
        assert reopened.visualScatterData("Scatter chart") == expected

        _write_csv(csv_path, [
            "O1,Alpha,10,20", "O2,Beta,20,30", "O3,Alpha,35,55", "O4,Gamma,40,80",
        ])
        reopened.refresh_source()
        refreshed = [dict(point) for point in expected]
        refreshed[2] = {"id": "O3|Alpha|35.0|55.0", "label": "O3", "group": "Alpha", "x": 35.0, "y": 55.0}
        assert reopened.visualScatterData("Scatter chart") == refreshed
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()
