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
    path.write_text("Category,Amount\n" + "\n".join(rows) + "\n", encoding="utf-8")


def test_treemap_area_selection_and_persistence(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["treemap visual tests"])
    csv_path = tmp_path / "sales.csv"
    _write_csv(csv_path, ["A,100", "A,20", "B,60", "C,40"])
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
        {"label": "A", "value": 120.0},
        {"label": "B", "value": 60.0},
        {"label": "C", "value": 40.0},
    ]

    try:
        window.show()
        controller.setCurrentView("Report")
        window.runCommand("insert.newVisual")
        window.runCommand("chart.type.treemap")
        visual = controller.activeVisualObjects[-1]
        assert visual["type"] == "treemap"
        assert visual["title"] == "Treemap"
        assert [well["name"] for well in controller.activeVisualWells] == [
            "X-axis", "Y-axis", "Tooltips",
        ]
        controller.add_field_to_well("X-axis", "Category")
        controller.add_field_to_well("Y-axis", "Amount")
        controller.set_visual_property("show_data_labels", True)
        assert controller.visualSeries("Treemap") == expected

        app.processEvents()
        QTest.qWait(50)
        card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "chartCard_Treemap"
        )
        assert card.property("chartType") == "treemap"
        assert card.property("series") == expected
        canvas = next(
            item for item in _items(card)
            if "CanvasItem" in item.metaObject().className()
        )
        assert canvas.width() > 0 and canvas.height() > 0

        plot_left = 38
        plot_top = 20
        plot_width = canvas.width() - 46
        plot_height = canvas.height() - plot_top - 25
        scene_point = canvas.mapToScene(QPointF(
            plot_left + plot_width * 0.25,
            plot_top + plot_height * 0.5,
        ))
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(round(scene_point.x()), round(scene_point.y())),
        )
        QTest.qWait(40)
        app.processEvents()
        assert controller.selectedCrossFiltersForVisual("Treemap") == ["A"]
        controller.toggle_cross_filter("Treemap", "A")

        project_path = tmp_path / "treemap.npa"
        assert controller._save_to(project_path)
        reopened = StudioController(
            QApplication.instance(),
            QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened.open_project_path(project_path)
        saved = next(item for item in reopened.activeVisualObjects if item["title"] == "Treemap")
        assert saved["type"] == "treemap"
        assert saved["fields"] == {"X-axis": ["Category"], "Y-axis": ["Amount"]}
        assert saved["show_data_labels"] is True
        assert reopened.visualSeries("Treemap") == expected

        _write_csv(csv_path, ["A,200", "B,50", "C,100"])
        reopened.refresh_source()
        assert reopened.visualSeries("Treemap") == [
            {"label": "A", "value": 200.0},
            {"label": "C", "value": 100.0},
            {"label": "B", "value": 50.0},
        ]
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()
