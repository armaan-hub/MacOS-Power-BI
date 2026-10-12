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
    path.write_text("Period,Product,Amount\n" + "\n".join(rows) + "\n", encoding="utf-8")


def test_ribbon_ranking_legend_interaction_and_persistence(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["ribbon visual tests"])
    csv_path = tmp_path / "sales.csv"
    _write_csv(csv_path, [
        "Jan,Alpha,100", "Jan,Beta,60", "Jan,Gamma,20",
        "Feb,Alpha,40", "Feb,Beta,90", "Feb,Gamma,50",
        "Mar,Alpha,80", "Mar,Beta,30", "Mar,Gamma,70",
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
        {"label": "Feb", "value": 180.0, "segments": [
            {"label": "Alpha", "value": 40.0}, {"label": "Beta", "value": 90.0},
            {"label": "Gamma", "value": 50.0},
        ]},
        {"label": "Jan", "value": 180.0, "segments": [
            {"label": "Alpha", "value": 100.0}, {"label": "Beta", "value": 60.0},
            {"label": "Gamma", "value": 20.0},
        ]},
        {"label": "Mar", "value": 180.0, "segments": [
            {"label": "Alpha", "value": 80.0}, {"label": "Beta", "value": 30.0},
            {"label": "Gamma", "value": 70.0},
        ]},
    ]

    try:
        window.show()
        controller.setCurrentView("Report")
        window.runCommand("insert.newVisual")
        window.runCommand("chart.type.ribbon")
        visual = controller.activeVisualObjects[-1]
        assert visual["type"] == "ribbon"
        assert visual["title"] == "Ribbon chart"
        assert [well["name"] for well in controller.activeVisualWells] == [
            "X-axis", "Y-axis", "Legend", "Tooltips",
        ]
        controller.add_field_to_well("X-axis", "Period")
        controller.add_field_to_well("Y-axis", "Amount")
        controller.add_field_to_well("Legend", "Product")
        controller.set_visual_property("show_legend", True)
        assert controller.visualSeries("Ribbon chart") == expected

        app.processEvents()
        QTest.qWait(50)
        card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "chartCard_Ribbon chart"
        )
        assert card.property("chartType") == "ribbon"
        assert card.property("series") == expected
        canvas = next(
            item for item in _items(card)
            if "CanvasItem" in item.metaObject().className()
        )
        assert canvas.width() > 0 and canvas.height() > 0

        plot_left = 38
        plot_top = 27
        plot_width = canvas.width() - 46
        plot_height = canvas.height() - plot_top - 25
        step = plot_width / 3
        scene_point = canvas.mapToScene(QPointF(
            plot_left + step * 1.5,
            plot_top + plot_height * 0.4,
        ))
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(round(scene_point.x()), round(scene_point.y())),
        )
        QTest.qWait(40)
        app.processEvents()
        assert controller.selectedCrossFiltersForVisual("Ribbon chart") == ["Jan"]
        controller.toggle_cross_filter("Ribbon chart", "Jan")

        controller.add_visual("column", "Period source", 800, 500, 300, 200)
        controller.add_field_to_well("X-axis", "Period")
        controller.add_field_to_well("Y-axis", "Amount")
        controller.set_visual_interaction("Period source", "Ribbon chart", "highlight")
        controller.toggle_cross_filter("Period source", "Jan")
        assert controller.visualHighlightSeries("Ribbon chart") == [expected[1]]

        project_path = tmp_path / "ribbon.npa"
        assert controller._save_to(project_path)
        reopened = StudioController(
            QApplication.instance(),
            QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened.open_project_path(project_path)
        saved = next(item for item in reopened.activeVisualObjects if item["title"] == "Ribbon chart")
        assert saved["type"] == "ribbon"
        assert saved["fields"] == {
            "X-axis": ["Period"], "Y-axis": ["Amount"], "Legend": ["Product"],
        }
        assert saved["show_legend"] is True
        assert reopened.visualSeries("Ribbon chart") == expected

        _write_csv(csv_path, [
            "Jan,Alpha,120", "Jan,Beta,40", "Jan,Gamma,30",
            "Feb,Alpha,40", "Feb,Beta,90", "Feb,Gamma,50",
            "Mar,Alpha,80", "Mar,Beta,30", "Mar,Gamma,70",
        ])
        reopened.refresh_source()
        refreshed = [dict(item) for item in expected]
        refreshed[1] = {"label": "Jan", "value": 190.0, "segments": [
            {"label": "Alpha", "value": 120.0}, {"label": "Beta", "value": 40.0},
            {"label": "Gamma", "value": 30.0},
        ]}
        assert reopened.visualSeries("Ribbon chart") == refreshed
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()
