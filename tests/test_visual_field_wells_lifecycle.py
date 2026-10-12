from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QSettings, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file

QQuickStyle.setStyle("Basic")


def _controller(tmp_path: Path, csv_path: Path) -> StudioController:
    app = QApplication.instance() or QApplication(["visual field well tests"])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    controller = StudioController(app, settings)
    assert controller._commit_import(csv_path, parse_file(csv_path))
    controller.add_visual("bar", "Sales by category", 40, 40, 360, 240)
    controller.add_field_to_well("X-axis", "Category")
    controller.add_field_to_well("Y-axis", "Amount")
    return controller


def _write_sales_csv(path: Path, rows: list[str]) -> None:
    path.write_text("Category,Amount\n" + "\n".join(rows) + "\n", encoding="utf-8")


def test_field_wells_aggregate_loaded_rows_and_replay_after_reopen_refresh(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "sales.csv"
    _write_sales_csv(csv_path, ["A,10", "A,20", "B,30", "B,", "B,invalid"])
    controller = _controller(tmp_path, csv_path)

    visual = next(
        item for item in controller.activeVisualObjects
        if item["title"] == "Sales by category"
    )
    assert visual["table_id"] == controller._active_model_table_id()
    assert visual["fields"] == {
        "X-axis": ["Category"],
        "Y-axis": ["Amount"],
    }
    assert controller.visualFieldAggregation("Y-axis", "Amount") == "Sum"
    assert controller.visualSeries("Sales by category") == [
        {"label": "A", "value": 30.0},
        {"label": "B", "value": 30.0},
    ]

    controller.set_field_aggregation("Y-axis", "Amount", "Count")
    assert controller.visualSeries("Sales by category") == [
        {"label": "A", "value": 2.0},
        {"label": "B", "value": 2.0},
    ]

    controller.set_field_aggregation("Y-axis", "Amount", "Average")
    assert controller.visualSeries("Sales by category") == [
        {"label": "B", "value": 30.0},
        {"label": "A", "value": 15.0},
    ]
    assert visual["field_aggregations"] == {"Amount": "average"}

    project_path = tmp_path / "visual-field-wells.npa"
    assert controller._save_to(project_path)
    reopened = StudioController(
        QApplication.instance(),
        QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
    )
    assert reopened.open_project_path(project_path)
    reopened.selectVisual("Sales by category")
    assert reopened.visualFieldAggregation("Y-axis", "Amount") == "Average"
    assert reopened.visualSeries("Sales by category") == [
        {"label": "B", "value": 30.0},
        {"label": "A", "value": 15.0},
    ]

    _write_sales_csv(csv_path, ["A,40", "A,60", "B,15", "B,25"])
    reopened.refresh_source()
    assert reopened.visualSeries("Sales by category") == [
        {"label": "A", "value": 50.0},
        {"label": "B", "value": 20.0},
    ]

    reopened.remove_field_from_well("Y-axis", "Amount")
    visual = next(
        item for item in reopened.activeVisualObjects
        if item["title"] == "Sales by category"
    )
    assert "Amount" not in visual["fields"]["Y-axis"]
    assert visual["field_aggregations"] == {}


def test_visual_aggregation_control_tracks_controller_state(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["visual aggregation UI tests"])
    csv_path = tmp_path / "sales.csv"
    _write_sales_csv(csv_path, ["A,10", "A,20", "B,30"])
    controller = _controller(tmp_path, csv_path)
    controller._dirty = False
    engine = QQmlEngine()
    component = QQmlComponent(engine)
    qml_path = Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml"
    component.loadUrl(QUrl.fromLocalFile(str(qml_path)))
    assert not component.isError(), "\n".join(error.toString() for error in component.errors())
    window = component.createWithInitialProperties({"studioController": controller})
    assert window is not None, "\n".join(error.toString() for error in component.errors())

    def items(item: QQuickItem):
        yield item
        for child in item.childItems():
            yield from items(child)

    try:
        window.show()
        controller.setCurrentView("Report")
        app.processEvents()
        aggregation_control = next(
            item for item in items(window.contentItem())
            if item.objectName() == "visualFieldAggregation" and item.isVisible()
        )
        assert aggregation_control.property("text") == "Sum"

        menu = window.findChild(QObject, "visualAggregationMenu")
        assert menu is not None
        aggregation_control.click()
        app.processEvents()
        assert menu.property("wellName") == "Y-axis"
        assert menu.property("fieldName") == "Amount"
        average = next(child for child in menu.children() if child.property("text") == "Average")
        assert average.property("text") == "Average"
        menu.chooseAggregation("Average")
        app.processEvents()

        assert menu.property("aggregation") == "Average"
        assert menu.property("targetButton") is not None
        assert menu.property("targetButton").property("text") == "Average"
        assert aggregation_control.property("text") == "Average"
        card = next(
            item for item in items(window.contentItem())
            if item.metaObject().className().startswith("ChartCard")
            and item.property("visualName") == "Sales by category"
        )
        assert [(item["label"], item["value"]) for item in card.property("series")] == [
            ("B", 30.0),
            ("A", 15.0),
        ]
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()


def test_saved_dax_measure_drives_grouped_chart_card_and_matrix(tmp_path: Path) -> None:
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text(
        "Category,Month,Amount\nA,Jan,10\nA,Feb,5\nB,Jan,7\nB,Feb,13\n",
        encoding="utf-8",
    )
    app = QApplication.instance() or QApplication(["measure visual tests"])
    controller = StudioController(
        app,
        QSettings(str(tmp_path / "measure-settings.ini"), QSettings.Format.IniFormat),
    )
    assert controller._commit_import(csv_path, parse_file(csv_path))
    assert controller.create_measure("Sales Total", "SUM([Amount])")
    measure_binding = "__dax_measure__:Sales Total"
    assert measure_binding in controller.filteredFields
    assert controller.visualFieldLabel(measure_binding) == "Measure · Sales Total"

    controller.add_visual("column", "Sales by category", 40, 40, 360, 240)
    controller.add_field_to_well("X-axis", "Category")
    controller.add_field_to_well("Y-axis", measure_binding)
    assert controller.activeVisualObjects[-1]["fields"]["Y-axis"] == [measure_binding]
    assert controller.visualFieldAggregation("Y-axis", measure_binding) == ""
    assert controller.visualSeries("Sales by category") == [
        {"label": "A", "value": 15.0},
        {"label": "B", "value": 20.0},
    ]

    controller.add_visual("card", "Sales total card", 420, 40, 220, 130)
    controller.add_field_to_well("Fields", measure_binding)
    card = controller.visualCardData("Sales total card")
    assert card["label"] == "Measure · Sales Total"
    assert card["value"] == "35"
    assert card["aggregation"] == "Measure"

    controller.add_visual("matrix", "Sales matrix", 420, 200, 360, 240)
    controller.add_field_to_well("Rows", "Category")
    controller.add_field_to_well("Columns", "Month")
    controller.add_field_to_well("Values", measure_binding)
    matrix = controller.visualMatrixData("Sales matrix")
    assert matrix["columns"] == ["Category", "Feb", "Jan"]
    assert [row["values"] for row in matrix["rows"]] == [
        ["A", "5", "10"],
        ["B", "13", "7"],
    ]

    assert not controller.remove_measure("Sales Total")
    assert "Remove 'Sales Total' from visual" in controller.statusMessage
    assert controller.update_measure("Sales Total", "Sales Amount", "SUM([Amount])")
    renamed_binding = "__dax_measure__:Sales Amount"
    assert controller.visualSeries("Sales by category") == [
        {"label": "A", "value": 15.0},
        {"label": "B", "value": 20.0},
    ]
    assert renamed_binding in controller.activeVisualObjects[0]["fields"]["Y-axis"]

    project_path = tmp_path / "measure-visual.npa"
    assert controller._save_to(project_path)
    reopened = StudioController(
        app,
        QSettings(str(tmp_path / "measure-reopened.ini"), QSettings.Format.IniFormat),
    )
    assert reopened.open_project_path(project_path)
    reopened.selectVisual("Sales by category")
    assert reopened.visualSeries("Sales by category") == [
        {"label": "A", "value": 15.0},
        {"label": "B", "value": 20.0},
    ]
    csv_path.write_text(
        "Category,Month,Amount\nA,Jan,100\nB,Feb,25\n",
        encoding="utf-8",
    )
    reopened.refresh_source()
    assert reopened.visualSeries("Sales by category") == [
        {"label": "A", "value": 100.0},
        {"label": "B", "value": 25.0},
    ]
    assert reopened.visualCardData("Sales total card")["value"] == "125"

    controller.selectVisual("Sales total card")
    controller.remove_field_from_well("Fields", renamed_binding)
    controller.selectVisual("Sales matrix")
    controller.remove_field_from_well("Values", renamed_binding)
    controller.selectVisual("Sales by category")
    controller.remove_field_from_well("Y-axis", renamed_binding)
    assert controller.remove_measure("Sales Amount"), controller.statusMessage


def test_table_visual_evaluates_measure_columns_at_group_grain_and_refreshes(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "table-measures.csv"
    csv_path.write_text(
        "Category,Month,Amount\n"
        "A,Jan,10\nA,Jan,5\nA,Feb,3\nB,Jan,7\nB,Feb,\n",
        encoding="utf-8",
    )
    app = QApplication.instance() or QApplication(["table measure tests"])
    controller = StudioController(
        app,
        QSettings(str(tmp_path / "table-measure-settings.ini"), QSettings.Format.IniFormat),
    )
    assert controller._commit_import(csv_path, parse_file(csv_path))
    assert controller.create_measure("Sales Total", "SUM([Amount])")
    assert controller.create_measure(
        "Nonblank Sales", "COUNTX('table-measures', [Amount])"
    )
    assert controller.create_measure("Numeric zero", "0")

    controller.add_visual("table", "Grouped table", 40, 40, 480, 300)
    controller.add_field_to_well("Fields", "Category")
    controller.add_field_to_well("Fields", "__dax_measure__:Sales Total")
    controller.add_field_to_well("Fields", "Month")
    controller.add_field_to_well("Fields", "__dax_measure__:Nonblank Sales")
    controller.add_field_to_well("Fields", "__dax_measure__:Numeric zero")

    expected = {
        "columns": ["Category", "Sales Total", "Month", "Nonblank Sales", "Numeric zero"],
        "rows": [
            {"values": ["A", "15", "Jan", "2", "0"], "category": "A", "highlighted": False},
            {"values": ["A", "3", "Feb", "1", "0"], "category": "A", "highlighted": False},
            {"values": ["B", "7", "Jan", "1", "0"], "category": "B", "highlighted": False},
            {"values": ["B", "0", "Feb", "", "0"], "category": "B", "highlighted": False},
        ],
        "total_rows": 4,
    }
    assert controller.visualTableData("Grouped table") == expected

    controller.add_visual("table", "Measure only table", 540, 40, 360, 240)
    controller.add_field_to_well("Fields", "__dax_measure__:Sales Total")
    controller.add_field_to_well("Fields", "__dax_measure__:Nonblank Sales")
    assert controller.visualTableData("Measure only table") == {
        "columns": ["Sales Total", "Nonblank Sales"],
        "rows": [
            {"values": ["25", "4"], "category": "", "highlighted": False},
        ],
        "total_rows": 1,
    }

    controller.add_visual("table", "Measure first table", 540, 300, 360, 240)
    controller.add_field_to_well("Fields", "__dax_measure__:Sales Total")
    controller.add_field_to_well("Fields", "Category")
    measure_first_visual = next(
        item for item in controller.activeVisualObjects
        if item["title"] == "Measure first table"
    )
    # Older saved visuals may omit table_id; the renderer uses the active table.
    measure_first_visual.pop("table_id")
    assert controller.visualTableData("Measure first table")["rows"] == [
        {"values": ["18", "A"], "category": "A", "highlighted": False},
        {"values": ["7", "B"], "category": "B", "highlighted": False},
    ]
    controller.toggle_cross_filter("Measure first table", "B")
    assert controller.visualTableData("Measure only table")["rows"] == [
        {"values": ["7", "1"], "category": "", "highlighted": False},
    ]
    controller.toggle_cross_filter("Measure first table", "B")
    assert controller.visualTableData("Measure only table")["rows"] == [
        {"values": ["25", "4"], "category": "", "highlighted": False},
    ]

    controller.add_visual("slicer", "Category filter", 920, 40, 260, 240)
    controller.add_field_to_well("Fields", "Category")
    controller.toggle_cross_filter("Category filter", "B")
    assert [row["values"] for row in controller.visualTableData("Grouped table")["rows"]] == [
        ["B", "7", "Jan", "1", "0"],
        ["B", "0", "Feb", "", "0"],
    ]
    assert controller.visualTableData("Measure only table")["rows"] == [
        {"values": ["7", "1"], "category": "", "highlighted": False},
    ]
    controller.toggle_cross_filter("Category filter", "B")

    project_path = tmp_path / "table-measures.npa"
    assert controller._save_to(project_path)
    reopened = StudioController(
        app,
        QSettings(str(tmp_path / "table-measure-reopened.ini"), QSettings.Format.IniFormat),
    )
    assert reopened.open_project_path(project_path)
    assert reopened.visualTableData("Grouped table") == expected

    csv_path.write_text(
        "Category,Month,Amount\nA,Jan,20\nB,Feb,9\n",
        encoding="utf-8",
    )
    reopened.refresh_source()
    refreshed = reopened.visualTableData("Grouped table")
    assert [row["values"] for row in refreshed["rows"]] == [
        ["A", "20", "Jan", "1", "0"],
        ["B", "9", "Feb", "1", "0"],
    ]
    assert refreshed["total_rows"] == 2

    csv_path.write_text(
        "Category,Amount\nA,20\nB,9\n",
        encoding="utf-8",
    )
    reopened.refresh_source()
    stale = reopened.visualTableData("Grouped table")
    assert stale["rows"] == []
    assert stale["total_rows"] == 0
    assert stale["error"] == (
        "Table fields 'Month' are no longer available. "
        "Remove or replace the field after refreshing the source."
    )

    csv_path.write_text(
        "Category,Month,Amount\nA,Jan,20\nB,Feb,9\n",
        encoding="utf-8",
    )
    reopened.refresh_source()
    grouped_visual = next(
        item for item in reopened.activeVisualObjects
        if item["title"] == "Grouped table"
    )
    grouped_visual["fields"]["Fields"][1] = "__dax_measure__:Removed Measure"
    failed_measure = reopened.visualTableData("Grouped table")
    assert failed_measure["rows"] == []
    assert failed_measure["error"].startswith(
        "Measure 'Removed Measure' could not be evaluated:"
    )
