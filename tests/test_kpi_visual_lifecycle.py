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


def test_kpi_visual_trend_target_highlight_and_lifecycle(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["KPI visual tests"])
    source_path = tmp_path / "sales.csv"
    source_path.write_text(
        "Period,Category,Actual,Goal\n"
        "2026-01,A,10,12\n2026-01,B,4,8\n"
        "2026-02,A,20,18\n2026-02,B,8,10\n"
        "2026-03,A,30,25\n2026-03,B,12,14\n",
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
        window.runCommand("chart.type.kpi")

        title = "KPI"
        kpi = controller.activeVisualObjects[-1]
        assert kpi["type"] == "kpi"
        assert controller.selectedChartType == "kpi"
        assert [well["name"] for well in controller.activeVisualWells] == [
            "Indicator", "Trend axis", "Target goals", "Tooltips",
        ]
        for well, field in (
            ("Indicator", "Actual"),
            ("Trend axis", "Period"),
            ("Target goals", "Goal"),
        ):
            controller.add_field_to_well(well, field)
        assert controller.visualKpiData(title) == {
            "field": "Actual",
            "trend_field": "Period",
            "value": 42.0,
            "target": 39.0,
            "label": "2026-03",
            "trend": [
                {"label": "2026-01", "value": 14.0, "target": 20.0},
                {"label": "2026-02", "value": 28.0, "target": 28.0},
                {"label": "2026-03", "value": 42.0, "target": 39.0},
            ],
            "highlight_value": None,
            "has_value": True,
        }

        controller.add_field_to_well("Indicator", "Goal")
        assert "one field in each indicator" in controller.statusMessage
        assert kpi["fields"]["Indicator"] == ["Actual"]
        controller.set_field_aggregation("Indicator", "Actual", "Average")
        assert controller.visualKpiData(title)["value"] == 21.0
        controller.set_field_aggregation("Indicator", "Actual", "Count")
        assert controller.visualKpiData(title)["value"] == 2.0
        controller.set_field_aggregation("Indicator", "Actual", "Sum")
        controller.set_field_aggregation("Target goals", "Goal", "Average")
        assert controller.visualKpiData(title)["target"] == 19.5
        controller.set_field_aggregation("Target goals", "Goal", "Sum")

        app.processEvents()
        card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == f"chartCard_{title}"
        )
        assert card.property("chartType") == "kpi"
        assert card.property("kpiData") == controller.visualKpiData(title)
        canvas = next(
            item for item in _items(card)
            if "CanvasItem" in item.metaObject().className()
        )
        assert canvas.width() > 0 and canvas.height() > 0
        click_scene = canvas.mapToScene(QPointF(18, canvas.height() * 0.72))
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(round(click_scene.x()), round(click_scene.y())),
        )
        app.processEvents()
        assert controller.selectedCrossFiltersForVisual(title) == ["2026-01"]
        controller.toggle_cross_filter(title, "2026-01")

        controller.add_visual("column", "Source", 420, 40, 360, 240)
        controller.add_field_to_well("X-axis", "Category")
        controller.add_field_to_well("Y-axis", "Actual")
        controller.set_visual_interaction("Source", title, "Highlight")
        controller.toggle_cross_filter("Source", "A")
        assert controller.visualKpiData(title)["value"] == 42.0
        assert controller.visualKpiData(title)["highlight_value"] == 30.0
        app.processEvents()
        card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == f"chartCard_{title}"
        )
        assert card.property("kpiData")["highlight_value"] == 30.0

        controller.set_visual_interaction("Source", title, "Filter")
        assert controller.visualKpiData(title)["value"] == 30.0
        assert controller.visualKpiData(title)["highlight_value"] is None
        controller.toggle_cross_filter("Source", "A")
        controller.set_visual_interaction("Source", title, "Highlight")

        project_path = tmp_path / "kpi-visual.npa"
        assert controller._save_to(project_path)
        reopened = StudioController(
            QApplication.instance(),
            QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened.open_project_path(project_path)
        reopened.selectVisual(title)
        saved = next(item for item in reopened.activeVisualObjects if item["id"] == kpi["id"])
        assert saved["fields"] == {
            "Indicator": ["Actual"],
            "Trend axis": ["Period"],
            "Target goals": ["Goal"],
        }
        assert saved["field_aggregations"] == {"Actual": "sum", "Goal": "sum"}
        assert reopened.visualKpiData(title) == controller.visualKpiData(title)

        source_path.write_text(
            "Period,Category,Actual,Goal\n"
            "2026-01,A,15,12\n2026-01,B,5,8\n"
            "2026-02,A,25,18\n2026-02,B,9,10\n"
            "2026-03,A,35,25\n2026-03,B,15,14\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        assert reopened.visualKpiData(title)["value"] == 50.0
        assert reopened.visualKpiData(title)["target"] == 39.0
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()
