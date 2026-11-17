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


def test_line_stacked_column_fields_series_and_lifecycle(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["line stacked column chart tests"])
    source_path = tmp_path / "sales.csv"
    # Category, Region, Units, Revenue
    # Cat A, North: Units=2, Revenue=10
    # Cat A, South: Units=3, Revenue=30
    # Cat B, North: Units=4, Revenue=20
    # Cat C, South: Units=5, Revenue=40
    source_path.write_text(
        "Category,Region,Units,Revenue\nA,North,2,10\nA,South,3,30\nB,North,4,20\nC,South,5,40\n",
        encoding="utf-8",
    )
    controller = StudioController(
        app,
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )
    assert controller._commit_import(source_path, parse_file(source_path))

    root_dir = Path(__file__).resolve().parents[1]
    engine = QQmlEngine()
    component = QQmlComponent(engine)
    qml_path = root_dir / "analytics_studio" / "qml" / "Main.qml"
    component.loadUrl(QUrl.fromLocalFile(str(qml_path)))
    assert not component.isError(), "\n".join(error.toString() for error in component.errors())
    window = component.createWithInitialProperties({"studioController": controller})
    assert window is not None, "\n".join(error.toString() for error in component.errors())

    try:
        window.show()
        controller.setCurrentView("Report")

        # Verify gallery tile is enabled and active
        gallery_tile = next(
            (
                item for item in _items(window.contentItem())
                if item.objectName() == "visualTypeTile_lineStackedColumn"
            ),
            None,
        )
        assert gallery_tile is not None, "visualTypeTile_lineStackedColumn gallery tile not found"
        assert gallery_tile.property("enabled") is True

        window.runCommand("insert.newVisual")
        window.runCommand("chart.type.lineStackedColumn")

        chart_title = "Line and stacked column chart"
        visual = controller.activeVisualObjects[-1]
        assert visual["type"] == "lineStackedColumn"
        assert visual["title"] == chart_title
        assert controller.selectedChartType == "lineStackedColumn"
        assert [well["name"] for well in controller.activeVisualWells] == [
            "X-axis", "Column Y-axis", "Column legend", "Line Y-axis", "Tooltips",
        ]

        # 1. Fill fields: X-axis = Category, Column y-axis = Units, Column legend = Region, Line y-axis = Revenue
        controller.add_field_to_well("X-axis", "Category")
        controller.add_field_to_well("Column Y-axis", "Units")
        controller.add_field_to_well("Column legend", "Region")
        controller.add_field_to_well("Line Y-axis", "Revenue")

        assert controller.visualFieldAggregation("Column Y-axis", "Units") == "Sum"
        assert controller.visualFieldAggregation("Line Y-axis", "Revenue") == "Sum"

        # Verify series values per category and legend equal hand-computed sums:
        # Category A: North=2, South=3 -> total=5.0
        # Category B: North=4 -> total=4.0
        # Category C: South=5 -> total=5.0
        series = controller.visualSeries(chart_title)
        assert len(series) == 3
        assert series[0]["label"] == "A"
        assert series[0]["value"] == 5.0
        assert series[0]["segments"] == [
            {"label": "North", "value": 2.0},
            {"label": "South", "value": 3.0},
        ]
        assert series[1]["label"] == "B"
        assert series[1]["value"] == 4.0
        assert series[1]["segments"] == [
            {"label": "North", "value": 4.0},
            {"label": "South", "value": 0.0},
        ]
        assert series[2]["label"] == "C"
        assert series[2]["value"] == 5.0
        assert series[2]["segments"] == [
            {"label": "North", "value": 0.0},
            {"label": "South", "value": 5.0},
        ]

        # Line values equal clustered combo's line values for the same fields (Sum of Revenue per Category)
        # A: 10 + 30 = 40.0
        # B: 20.0
        # C: 40.0
        line_series = controller.visualLineSeries(chart_title)
        assert line_series == [
            {"label": "A", "value": 40.0},
            {"label": "B", "value": 20.0},
            {"label": "C", "value": 40.0},
        ]

        app.processEvents()
        QTest.qWait(50)
        chart_card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == f"chartCard_{chart_title}"
        )
        assert chart_card.property("chartType") == "lineStackedColumn"
        assert chart_card.property("series") == series
        assert chart_card.property("lineSeries") == line_series

        # 2. With no legend there is one plain column series (non-stacked / flat)
        controller.remove_field_from_well("Column legend", "Region")
        no_legend_series = controller.visualSeries(chart_title)
        assert no_legend_series == [
            {"label": "A", "value": 5.0},
            {"label": "B", "value": 4.0},
            {"label": "C", "value": 5.0},
        ]
        assert "segments" not in no_legend_series[0]

        # Add legend back for save/load and switching tests
        controller.add_field_to_well("Column legend", "Region")

        # 3. Switching type to lineClusteredColumn and back keeps the fields
        window.runCommand("chart.type.lineClusteredColumn")
        assert controller.selectedChartType == "lineClusteredColumn"
        current_visual = controller.activeVisualObjects[-1]
        assert current_visual["type"] == "lineClusteredColumn"
        assert current_visual["fields"]["X-axis"] == ["Category"]
        assert current_visual["fields"]["Column Y-axis"] == ["Units"]
        assert current_visual["fields"]["Line Y-axis"] == ["Revenue"]

        # Switch back to lineStackedColumn
        window.runCommand("chart.type.lineStackedColumn")
        assert controller.selectedChartType == "lineStackedColumn"
        current_visual = controller.activeVisualObjects[-1]
        assert current_visual["type"] == "lineStackedColumn"
        assert current_visual["fields"]["X-axis"] == ["Category"]
        assert current_visual["fields"]["Column Y-axis"] == ["Units"]
        assert current_visual["fields"]["Column legend"] == ["Region"]
        assert current_visual["fields"]["Line Y-axis"] == ["Revenue"]

        # 4. Save and load round-trip
        project_path = tmp_path / "line-stacked-combo.npa"
        assert controller._save_to(project_path)

        reopened = StudioController(
            QApplication.instance(),
            QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened.open_project_path(project_path)
        reopened.selectVisual(chart_title)
        saved = next(item for item in reopened.activeVisualObjects if item["id"] == visual["id"])
        assert saved["type"] == "lineStackedColumn"
        assert saved["fields"] == {
            "X-axis": ["Category"],
            "Column Y-axis": ["Units"],
            "Column legend": ["Region"],
            "Line Y-axis": ["Revenue"],
        }
        assert saved["field_aggregations"] == {"Units": "sum", "Revenue": "sum"}
        assert reopened.visualSeries(chart_title) == controller.visualSeries(chart_title)
        assert reopened.visualLineSeries(chart_title) == controller.visualLineSeries(chart_title)

    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()


def test_line_y_axis_ignores_column_legend(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["line stacked column legend tests"])
    source_path = tmp_path / "sales.csv"
    # Category, Region, Units, Revenue
    source_path.write_text(
        "Category,Region,Units,Revenue\nA,North,2,10\nA,South,3,30\nB,North,4,20\nC,South,5,40\n",
        encoding="utf-8",
    )
    controller = StudioController(
        app,
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )
    assert controller._commit_import(source_path, parse_file(source_path))
    assert controller.create_measure("Revenue total", "SUM([Revenue])")
    measure_binding = "__dax_measure__:Revenue total"

    stacked_title = "Stacked measure line"
    clustered_title = "Clustered measure line"
    controller.add_visual("lineStackedColumn", stacked_title, 20, 20, 360, 240)
    controller.add_field_to_well("X-axis", "Category")
    controller.add_field_to_well("Column Y-axis", "Units")
    controller.add_field_to_well("Column legend", "Region")
    controller.add_field_to_well("Line Y-axis", measure_binding)

    controller.add_visual("lineClusteredColumn", clustered_title, 20, 280, 360, 240)
    controller.add_field_to_well("X-axis", "Category")
    controller.add_field_to_well("Column Y-axis", "Units")
    controller.add_field_to_well("Line Y-axis", measure_binding)

    # Line is never split by the column legend: one point per category, no legend segments.
    expected_line = [
        {"label": "A", "value": 40.0},
        {"label": "B", "value": 20.0},
        {"label": "C", "value": 40.0},
    ]
    stacked_line = controller.visualLineSeries(stacked_title)
    assert stacked_line == expected_line
    assert stacked_line == controller.visualLineSeries(clustered_title)
    for point in stacked_line:
        assert "segments" not in point
