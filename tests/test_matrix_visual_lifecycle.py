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
    path.write_text("Region,Quarter,Sales\n" + "\n".join(rows) + "\n", encoding="utf-8")


def test_matrix_groups_aggregates_and_persists(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["matrix visual tests"])
    csv_path = tmp_path / "sales.csv"
    _write_csv(csv_path, [
        "North,Q1,10", "North,Q1,5", "North,Q2,20",
        "South,Q1,30", "South,Q2,40",
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

    expected = {
        "columns": ["Region", "Q1", "Q2"],
        "rows": [
            {"values": ["North", "15", "20"], "category": "North", "highlighted": False},
            {"values": ["South", "30", "40"], "category": "South", "highlighted": False},
        ],
        "total_rows": 2,
    }

    try:
        window.show()
        controller.setCurrentView("Report")
        window.runCommand("insert.newVisual")
        window.runCommand("chart.type.matrix")
        visual = controller.activeVisualObjects[-1]
        assert visual["type"] == "matrix"
        assert visual["title"] == "Matrix"
        assert [well["name"] for well in controller.activeVisualWells] == [
            "Rows", "Columns", "Values", "Tooltips",
        ]
        controller.add_field_to_well("Rows", "Region")
        controller.add_field_to_well("Columns", "Quarter")
        controller.add_field_to_well("Values", "Sales")
        assert controller.visualFieldAggregation("Values", "Sales") == "Sum"
        assert controller.visualMatrixData("Matrix") == expected

        controller.set_field_aggregation("Values", "Sales", "Count")
        assert controller.visualMatrixData("Matrix") == {
            "columns": ["Region", "Q1", "Q2"],
            "rows": [
                {"values": ["North", "2", "1"], "category": "North", "highlighted": False},
                {"values": ["South", "1", "1"], "category": "South", "highlighted": False},
            ],
            "total_rows": 2,
        }
        controller.set_field_aggregation("Values", "Sales", "Average")
        assert controller.visualMatrixData("Matrix") == {
            "columns": ["Region", "Q1", "Q2"],
            "rows": [
                    {"values": ["North", "7.50", "20"], "category": "North", "highlighted": False},
                {"values": ["South", "30", "40"], "category": "South", "highlighted": False},
            ],
            "total_rows": 2,
        }
        controller.set_field_aggregation("Values", "Sales", "Sum")

        app.processEvents()
        QTest.qWait(50)
        matrix = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "matrixCard_Matrix"
        )
        assert matrix.property("tableData") == expected
        aggregation = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "visualFieldAggregation" and item.isVisible()
        )
        assert aggregation.property("text") == "Sum"

        row = next(
            item for item in _items(matrix)
            if item.objectName() == "tableRow_Matrix_1"
        )
        scene_point = row.mapToScene(QPointF(row.width() / 2, row.height() / 2))
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(round(scene_point.x()), round(scene_point.y())),
        )
        QTest.qWait(40)
        app.processEvents()
        assert controller.selectedCrossFiltersForVisual("Matrix") == ["South"]
        controller.toggle_cross_filter("Matrix", "South")

        controller.add_visual("column", "Region source", 800, 500, 300, 200)
        controller.add_field_to_well("X-axis", "Region")
        controller.add_field_to_well("Y-axis", "Sales")
        controller.set_visual_interaction("Region source", "Matrix", "highlight")
        controller.toggle_cross_filter("Region source", "North")
        highlighted = controller.visualMatrixData("Matrix")
        assert highlighted["rows"][0]["highlighted"] is True
        assert highlighted["rows"][1]["highlighted"] is False

        project_path = tmp_path / "matrix.npa"
        assert controller._save_to(project_path)
        reopened = StudioController(
            QApplication.instance(),
            QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened.open_project_path(project_path)
        saved = next(item for item in reopened.activeVisualObjects if item["title"] == "Matrix")
        assert saved["type"] == "matrix"
        assert saved["fields"] == {
            "Rows": ["Region"], "Columns": ["Quarter"], "Values": ["Sales"],
        }
        assert saved["field_aggregations"] == {"Sales": "sum"}
        assert reopened.visualMatrixData("Matrix") == expected

        _write_csv(csv_path, [
            "North,Q1,25", "North,Q2,10", "South,Q1,45", "South,Q2,15",
        ])
        reopened.refresh_source()
        assert reopened.visualMatrixData("Matrix") == {
            "columns": ["Region", "Q1", "Q2"],
            "rows": [
                {"values": ["North", "25", "10"], "category": "North", "highlighted": False},
                {"values": ["South", "45", "15"], "category": "South", "highlighted": False},
            ],
            "total_rows": 2,
        }
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()
