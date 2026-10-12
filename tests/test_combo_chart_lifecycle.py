from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QSettings, QUrl, Qt
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


def test_combo_chart_fields_interaction_render_and_lifecycle(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["combo chart tests"])
    source_path = tmp_path / "sales.csv"
    source_path.write_text(
        "Category,Units,Revenue\nA,2,10\nA,3,30\nB,4,20\nC,5,40\n",
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
        window.runCommand("chart.type.lineClusteredColumn")

        combo_title = "Line and clustered column chart"
        visual = controller.activeVisualObjects[-1]
        assert visual["type"] == "lineClusteredColumn"
        assert visual["title"] == combo_title
        assert controller.selectedChartType == "lineClusteredColumn"
        assert [well["name"] for well in controller.activeVisualWells] == [
            "X-axis", "Column Y-axis", "Line Y-axis", "Tooltips",
        ]

        controller.add_field_to_well("X-axis", "Category")
        controller.add_field_to_well("Column Y-axis", "Units")
        controller.add_field_to_well("Line Y-axis", "Revenue")
        assert controller.visualFieldAggregation("Column Y-axis", "Units") == "Sum"
        assert controller.visualFieldAggregation("Line Y-axis", "Revenue") == "Sum"
        controller.set_field_aggregation("Line Y-axis", "Revenue", "Average")
        assert controller.visualFieldAggregation("Line Y-axis", "Revenue") == "Average"
        assert controller.visualSeries(combo_title) == [
            {"label": "A", "value": 5.0},
            {"label": "B", "value": 4.0},
            {"label": "C", "value": 5.0},
        ]
        assert controller.visualLineSeries(combo_title) == [
            {"label": "A", "value": 20.0},
            {"label": "B", "value": 20.0},
            {"label": "C", "value": 40.0},
        ]

        app.processEvents()
        QTest.qWait(50)
        chart_card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == f"chartCard_{combo_title}"
        )
        assert chart_card.property("chartType") == "lineClusteredColumn"
        assert chart_card.property("series") == controller.visualSeries(combo_title)
        assert chart_card.property("lineSeries") == controller.visualLineSeries(combo_title)
        canvas = next(
            item for item in _items(chart_card)
            if "CanvasItem" in item.metaObject().className()
        )
        assert canvas.width() > 0 and canvas.height() > 0

        plot_left = 38
        plot_width = max(12, canvas.width() - 46)
        click_scene = canvas.mapToScene(QPointF(plot_left + plot_width / 6, canvas.height() / 2))
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(round(click_scene.x()), round(click_scene.y())),
        )
        QTest.qWait(50)
        app.processEvents()
        assert controller.selectedCrossFiltersForVisual(combo_title) == ["A"]

        controller.add_visual("column", "Target", 420, 40, 360, 240)
        controller.add_field_to_well("X-axis", "Category")
        controller.add_field_to_well("Y-axis", "Revenue")
        controller.set_visual_interaction(combo_title, "Target", "Filter")
        assert controller.visualSeries("Target") == [{"label": "A", "value": 40.0}]
        controller.toggle_cross_filter(combo_title, "A")
        assert controller.selectedCrossFiltersForVisual(combo_title) == []

        controller.add_visual("bar", "Peer", 800, 40, 360, 240)
        controller.add_field_to_well("X-axis", "Category")
        controller.set_visual_interaction("Peer", combo_title, "Highlight")
        controller.toggle_cross_filter("Peer", "A")
        assert controller.visualLineHighlightSeries(combo_title) == [
            {"label": "A", "value": 20.0},
        ]

        controller.toggle_cross_filter("Peer", "A")
        project_path = tmp_path / "combo-chart.npa"
        assert controller._save_to(project_path)
        reopened = StudioController(
            QApplication.instance(),
            QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened.open_project_path(project_path)
        reopened.selectVisual(combo_title)
        saved = next(item for item in reopened.activeVisualObjects if item["id"] == visual["id"])
        assert saved["fields"] == {
            "X-axis": ["Category"],
            "Column Y-axis": ["Units"],
            "Line Y-axis": ["Revenue"],
        }
        assert saved["field_aggregations"] == {"Units": "sum", "Revenue": "average"}
        assert reopened.visualSeries(combo_title) == controller.visualSeries(combo_title)
        assert reopened.visualLineSeries(combo_title) == controller.visualLineSeries(combo_title)

        source_path.write_text(
            "Category,Units,Revenue\nA,1,30\nA,1,60\nB,2,40\nC,5,100\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        assert reopened.visualSeries(combo_title) == [
            {"label": "A", "value": 2.0},
            {"label": "B", "value": 2.0},
            {"label": "C", "value": 5.0},
        ]
        assert reopened.visualLineSeries(combo_title) == [
            {"label": "A", "value": 45.0},
            {"label": "B", "value": 40.0},
            {"label": "C", "value": 100.0},
        ]
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()
