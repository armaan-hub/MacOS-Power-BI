from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QSettings, QUrl, Qt
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem
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


def test_funnel_chart_renders_selects_and_persists_field_bindings(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["funnel chart tests"])
    source_path = tmp_path / "sales.csv"
    source_path.write_text("Category,Amount\nA,10\nB,25\nC,15\n", encoding="utf-8")
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
        window.runCommand("chart.type.funnel")
        visual = controller.activeVisualObjects[-1]
        assert visual["type"] == "funnel"
        assert visual["title"] == "Funnel chart"
        assert controller.selectedChartType == "funnel"
        assert [well["name"] for well in controller.activeVisualWells] == [
            "X-axis", "Y-axis", "Legend", "Tooltips",
        ]
        controller.add_field_to_well("X-axis", "Category")
        controller.add_field_to_well("Y-axis", "Amount")
        assert controller.visualSeries("Funnel chart") == [
            {"label": "B", "value": 25.0},
            {"label": "C", "value": 15.0},
            {"label": "A", "value": 10.0},
        ]

        app.processEvents()
        QTest.qWait(50)
        chart_card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "chartCard_Funnel chart"
        )
        assert chart_card.property("chartType") == "funnel"
        assert chart_card.property("series") == controller.visualSeries("Funnel chart")
        canvas = next(
            item for item in _items(chart_card)
            if "CanvasItem" in item.metaObject().className()
        )

        plot_top = 9
        plot_height = max(12, canvas.height() - 34)
        segment_height = max(5, plot_height / 3 * 0.76)
        first_segment_y = plot_top + (plot_height / 3 - segment_height) / 2 + segment_height / 2
        scene_click = canvas.mapToScene(QPointF(canvas.width() / 2, first_segment_y))
        click_point = QPoint(round(scene_click.x()), round(scene_click.y()))
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click_point)
        QTest.qWait(50)
        app.processEvents()
        assert controller.selectedCrossFiltersForVisual("Funnel chart") == ["B"]

        QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click_point)
        QTest.qWait(50)
        app.processEvents()
        assert controller.selectedCrossFiltersForVisual("Funnel chart") == []

        project_path = tmp_path / "funnel-chart.npa"
        assert controller._save_to(project_path)
        reopened = StudioController(
            QApplication.instance(),
            QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened.open_project_path(project_path)
        saved = next(
            item for item in reopened.activeVisualObjects if item["id"] == visual["id"]
        )
        assert saved["type"] == "funnel"
        assert saved["fields"] == {"X-axis": ["Category"], "Y-axis": ["Amount"]}
        assert reopened.visualSeries("Funnel chart") == controller.visualSeries("Funnel chart")
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()
