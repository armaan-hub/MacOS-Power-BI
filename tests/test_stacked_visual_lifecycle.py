from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QSettings, QUrl, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtTest import QTest
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file

QQuickStyle.setStyle("Basic")


def _items(item: QQuickItem):
    yield item
    for child in item.childItems():
        yield from _items(child)


def _write_sales_csv(path: Path, rows: list[str]) -> None:
    path.write_text(
        "Category,Segment,Amount\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )


def test_stacked_chart_families_group_legend_data_and_persist(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["stacked visual tests"])
    csv_path = tmp_path / "sales.csv"
    _write_sales_csv(csv_path, [
        "A,Online,10", "A,Online,20", "A,Retail,20", "B,Online,30", "B,Retail,40",
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
        {"label": "A", "value": 50.0, "segments": [
            {"label": "Online", "value": 30.0}, {"label": "Retail", "value": 20.0},
        ]},
        {"label": "B", "value": 70.0, "segments": [
            {"label": "Online", "value": 30.0}, {"label": "Retail", "value": 40.0},
        ]},
    ]

    try:
        window.show()
        controller.setCurrentView("Report")
        created = []
        for chart_type, title in (
            ("stackedColumn", "Stacked column chart"),
            ("stackedBar", "Stacked bar chart"),
            ("column100", "100% stacked column chart"),
            ("bar100", "100% stacked bar chart"),
            ("stackedArea", "Stacked area chart"),
            ("area100", "100% stacked area chart"),
        ):
            window.runCommand("insert.newVisual")
            window.runCommand(f"chart.type.{chart_type}")
            visual = controller.activeVisualObjects[-1]
            created.append(visual)
            assert visual["type"] == chart_type
            assert visual["title"] == title
            assert [well["name"] for well in controller.activeVisualWells] == [
                "X-axis", "Y-axis", "Legend", "Tooltips",
            ]
            controller.add_field_to_well("X-axis", "Category")
            controller.add_field_to_well("Y-axis", "Amount")
            controller.add_field_to_well("Legend", "Segment")
            controller.set_visual_property("show_legend", True)
            assert controller.visualSeries(title) == expected
            controller.set_field_aggregation("Y-axis", "Amount", "Count")
            assert controller.visualSeries(title) == [
                {"label": "A", "value": 3.0, "segments": [
                    {"label": "Online", "value": 2.0}, {"label": "Retail", "value": 1.0},
                ]},
                {"label": "B", "value": 2.0, "segments": [
                    {"label": "Online", "value": 1.0}, {"label": "Retail", "value": 1.0},
                ]},
            ]
            controller.set_field_aggregation("Y-axis", "Amount", "Average")
            assert controller.visualSeries(title) == [
                {"label": "A", "value": 35.0, "segments": [
                    {"label": "Online", "value": 15.0}, {"label": "Retail", "value": 20.0},
                ]},
                {"label": "B", "value": 70.0, "segments": [
                    {"label": "Online", "value": 30.0}, {"label": "Retail", "value": 40.0},
                ]},
            ]
            controller.set_field_aggregation("Y-axis", "Amount", "Sum")

            app.processEvents()
            QTest.qWait(50)
            card = next(
                item for item in _items(window.contentItem())
                if item.objectName() == f"chartCard_{title}"
            )
            assert card.property("chartType") == chart_type
            assert card.property("series") == expected
            canvas = next(
                item for item in _items(card)
                if "CanvasItem" in item.metaObject().className()
            )
            assert canvas.width() > 0 and canvas.height() > 0

            plot_left = 38
            plot_top = 27
            plot_width = canvas.width() - plot_left - 8
            plot_height = canvas.height() - plot_top - 25
            if chart_type in {"stackedColumn", "column100"}:
                step = plot_width / 2
                bar_width = step * 0.56
                x = plot_left + (step - bar_width) / 2 + bar_width / 2
                first_segment_height = plot_height * (30 / 50 if chart_type == "column100" else 30 / 70)
                y = plot_top + plot_height - first_segment_height / 2
            elif chart_type in {"stackedBar", "bar100"}:
                step = plot_height / 2
                y = plot_top + step * 0.18 + step * 0.32
                x = plot_left + plot_width * (0.6 if chart_type == "bar100" else 30 / 70) / 2
            else:
                step = plot_width / 2
                x = plot_left + step / 2
                y = plot_top + plot_height * 0.75
            scene_point = canvas.mapToScene(QPointF(x, y))
            QTest.mouseClick(
                window,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                QPoint(round(scene_point.x()), round(scene_point.y())),
            )
            QTest.qWait(40)
            app.processEvents()
            assert controller.selectedCrossFiltersForVisual(title) == ["A"]
            controller.toggle_cross_filter(title, "A")

        controller.add_visual("column", "Category source", 800, 500, 300, 200)
        controller.add_field_to_well("X-axis", "Category")
        controller.add_field_to_well("Y-axis", "Amount")
        for stacked in created:
            controller.set_visual_interaction("Category source", stacked["title"], "highlight")
        controller.toggle_cross_filter("Category source", "A")
        for stacked in created:
            assert controller.visualHighlightSeries(stacked["title"]) == [
                {"label": "A", "value": 50.0, "segments": [
                    {"label": "Online", "value": 30.0},
                    {"label": "Retail", "value": 20.0},
                ]},
            ]

        project_path = tmp_path / "stacked-visuals.npa"
        assert controller._save_to(project_path)
        reopened = StudioController(
            QApplication.instance(),
            QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened.open_project_path(project_path)
        for chart_type, title in (
            ("stackedColumn", "Stacked column chart"),
            ("stackedBar", "Stacked bar chart"),
            ("column100", "100% stacked column chart"),
            ("bar100", "100% stacked bar chart"),
            ("stackedArea", "Stacked area chart"),
            ("area100", "100% stacked area chart"),
        ):
            saved = next(item for item in reopened.activeVisualObjects if item["title"] == title)
            assert saved["type"] == chart_type
            assert saved["fields"] == {
                "X-axis": ["Category"],
                "Y-axis": ["Amount"],
                "Legend": ["Segment"],
            }
            assert saved["show_legend"] is True
            assert reopened.visualSeries(title) == expected

        _write_sales_csv(csv_path, [
            "A,Online,15", "A,Online,25", "A,Retail,25", "B,Online,35", "B,Retail,45",
        ])
        reopened.refresh_source()
        refreshed = [
            {"label": "A", "value": 65.0, "segments": [
                {"label": "Online", "value": 40.0}, {"label": "Retail", "value": 25.0},
            ]},
            {"label": "B", "value": 80.0, "segments": [
                {"label": "Online", "value": 35.0}, {"label": "Retail", "value": 45.0},
            ]},
        ]
        for title in (
            "Stacked column chart", "Stacked bar chart",
            "100% stacked column chart", "100% stacked bar chart",
            "Stacked area chart", "100% stacked area chart",
        ):
            assert reopened.visualSeries(title) == refreshed
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()
