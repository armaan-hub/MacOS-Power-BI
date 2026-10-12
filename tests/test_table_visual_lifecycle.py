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


def test_table_visual_binds_displays_filters_and_persists(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["table visual tests"])
    source_path = tmp_path / "sales.csv"
    source_path.write_text(
        "Category,Amount\nA,10\nB,25\nA,12\n",
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
        window.runCommand("chart.type.table")

        visual = controller.activeVisualObjects[-1]
        assert visual["type"] == "table"
        assert visual["title"] == "Table"
        assert controller.selectedChartType == "table"
        assert [well["name"] for well in controller.activeVisualWells] == ["Fields", "Tooltips"]

        window_items = list(_items(window.contentItem()))
        chart_card = next(item for item in window_items if item.objectName() == "chartCard_Table")
        table_card = next(item for item in window_items if item.objectName() == "tableCard_Table")
        assert chart_card.property("visible") is False
        assert table_card.property("visible") is True
        assert controller.visualTableData("Table") == {
            "columns": [],
            "rows": [],
            "total_rows": 0,
        }

        controller.add_field_to_well("Fields", "Category")
        controller.add_field_to_well("Fields", "Amount")
        assert controller.visualTableData("Table") == {
            "columns": ["Category", "Amount"],
            "rows": [
                {"values": ["A", "10"], "category": "A", "highlighted": False},
                {"values": ["B", "25"], "category": "B", "highlighted": False},
                {"values": ["A", "12"], "category": "A", "highlighted": False},
            ],
            "total_rows": 3,
        }
        app.processEvents()
        QTest.qWait(50)
        table_card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "tableCard_Table"
        )
        assert table_card.property("columns") == ["Category", "Amount"]
        assert table_card.property("totalRows") == 3
        table_row = next(
            item for item in _items(table_card)
            if item.objectName() == "tableRow_Table_0"
        )
        scene_point = table_row.mapToScene(QPointF(40, 13))
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(round(scene_point.x()), round(scene_point.y())),
        )
        QTest.qWait(50)
        app.processEvents()
        assert controller.selectedCrossFiltersForVisual("Table") == ["A"]
        table_card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "tableCard_Table"
        )
        assert table_card.property("activeFilters") == ["A"]
        controller.toggle_cross_filter("Table", "A")

        controller.add_visual("column", "Highlight source", 720, 80, 330, 248)
        controller.selectVisual("Highlight source")
        controller.add_field_to_well("X-axis", "Category")
        controller.add_field_to_well("Y-axis", "Amount")
        controller.set_visual_interaction("Highlight source", "Table", "highlight")
        controller.toggle_cross_filter("Highlight source", "B")
        highlighted_rows = controller.visualTableData("Table")["rows"]
        assert [row["highlighted"] for row in highlighted_rows] == [False, True, False]
        controller.toggle_cross_filter("Highlight source", "B")

        project_path = tmp_path / "table-visual.npa"
        assert controller._save_to(project_path)
        reopened = StudioController(
            QApplication.instance(),
            QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened.open_project_path(project_path)
        saved = next(
            item for item in reopened.activeVisualObjects if item["id"] == visual["id"]
        )
        assert saved["type"] == "table"
        assert saved["fields"] == {"Fields": ["Category", "Amount"]}
        assert reopened.visualTableData("Table")["columns"] == ["Category", "Amount"]
        assert reopened.visualTableData("Table")["total_rows"] == 3

        source_path.write_text("Category,Amount\nC,7\nA,42\n", encoding="utf-8")
        reopened.refresh_source()
        assert reopened.visualTableData("Table") == {
            "columns": ["Category", "Amount"],
            "rows": [
                {"values": ["C", "7"], "category": "C", "highlighted": False},
                {"values": ["A", "42"], "category": "A", "highlighted": False},
            ],
            "total_rows": 2,
        }
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()
