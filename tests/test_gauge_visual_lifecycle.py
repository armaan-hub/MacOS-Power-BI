from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file


def _items(item: QQuickItem):
    yield item
    for child in item.childItems():
        yield from _items(child)


def test_gauge_visual_values_highlights_and_lifecycle(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["gauge visual tests"])
    source_path = tmp_path / "sales.csv"
    source_path.write_text(
        "Category,Amount,Floor,Ceiling,Target\n"
        "A,10,0,100,50\nB,20,0,100,50\nC,30,0,100,50\n",
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
        window.runCommand("chart.type.gauge")

        gauge_title = "Gauge"
        gauge = controller.activeVisualObjects[-1]
        assert gauge["type"] == "gauge"
        assert controller.selectedChartType == "gauge"
        assert [well["name"] for well in controller.activeVisualWells] == [
            "Value", "Minimum", "Maximum", "Target", "Tooltips",
        ]

        for well, field in (
            ("Value", "Amount"),
            ("Minimum", "Floor"),
            ("Maximum", "Ceiling"),
            ("Target", "Target"),
        ):
            controller.add_field_to_well(well, field)
            assert controller.visualFieldAggregation(well, field) == "Sum"
        controller.add_field_to_well("Value", "Floor")
        assert "one field in each value well" in controller.statusMessage
        assert gauge["fields"]["Value"] == ["Amount"]
        for field in ("Floor", "Ceiling", "Target"):
            well = {"Floor": "Minimum", "Ceiling": "Maximum", "Target": "Target"}[field]
            controller.set_field_aggregation(well, field, "Average")

        assert controller.visualGaugeData(gauge_title) == {
            "value": 60.0,
            "minimum": 0.0,
            "maximum": 100.0,
            "target": 50.0,
            "highlight_value": None,
            "has_value": True,
        }

        app.processEvents()
        card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == f"chartCard_{gauge_title}"
        )
        assert card.property("chartType") == "gauge"
        assert card.property("gaugeData") == controller.visualGaugeData(gauge_title)
        canvas = next(
            item for item in _items(card)
            if "CanvasItem" in item.metaObject().className()
        )
        assert canvas.width() > 0 and canvas.height() > 0

        controller.add_visual("column", "Source", 420, 40, 360, 240)
        controller.add_field_to_well("X-axis", "Category")
        controller.add_field_to_well("Y-axis", "Amount")
        controller.set_visual_interaction("Source", gauge_title, "Highlight")
        controller.toggle_cross_filter("Source", "A")
        assert controller.visualGaugeData(gauge_title)["value"] == 60.0
        assert controller.visualGaugeHighlightData(gauge_title)["value"] == 10.0
        app.processEvents()
        card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == f"chartCard_{gauge_title}"
        )
        assert card.property("gaugeData")["highlight_value"] == 10.0

        controller.toggle_cross_filter("Source", "A")
        project_path = tmp_path / "gauge-visual.npa"
        assert controller._save_to(project_path)
        reopened = StudioController(
            QApplication.instance(),
            QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened.open_project_path(project_path)
        reopened.selectVisual(gauge_title)
        saved = next(item for item in reopened.activeVisualObjects if item["id"] == gauge["id"])
        assert saved["fields"] == {
            "Value": ["Amount"],
            "Minimum": ["Floor"],
            "Maximum": ["Ceiling"],
            "Target": ["Target"],
        }
        assert saved["field_aggregations"] == {
            "Amount": "sum",
            "Floor": "average",
            "Ceiling": "average",
            "Target": "average",
        }
        assert reopened.visualGaugeData(gauge_title) == controller.visualGaugeData(gauge_title)

        source_path.write_text(
            "Category,Amount,Floor,Ceiling,Target\n"
            "A,15,0,100,50\nB,25,0,100,50\nC,35,0,100,50\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        assert reopened.visualGaugeData(gauge_title) == {
            "value": 75.0,
            "minimum": 0.0,
            "maximum": 100.0,
            "target": 50.0,
            "highlight_value": None,
            "has_value": True,
        }
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()
