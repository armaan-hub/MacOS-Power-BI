from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file

QQuickStyle.setStyle("Basic")


def _controller(tmp_path: Path) -> StudioController:
    app = QApplication.instance() or QApplication(["visual property tests"])
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text(
        "Category,Amount\nA,10\nA,20\nB,50\n",
        encoding="utf-8",
    )
    controller = StudioController(
        app,
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )
    assert controller._commit_import(csv_path, parse_file(csv_path))
    controller.add_visual("bar", "Category amount", 40, 40, 360, 240)
    controller.add_field_to_well("X-axis", "Category")
    controller.add_field_to_well("Y-axis", "Amount")
    return controller


def test_general_visual_properties_save_reopen_and_rebind_title(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path)
    old_title = "Category amount"
    table_id = controller._active_model_table_id()
    page = controller._active_page()
    page["visual_filters"] = [{
        "visual_name": old_title,
        "table_id": table_id,
        "column": "Amount",
        "clauses": [{"operator": "not_equals", "value": "10"}],
        "logic": "and",
    }]
    controller._cross_filters[old_title] = ["A"]

    controller.set_visual_property("title", "Revenue by category")
    controller.set_visual_property("x", 12.5)
    controller.set_visual_property("y", 30)
    controller.set_visual_property("width", 420)
    controller.set_visual_property("height", 260)
    controller.set_visual_property("color", "#123ABC")
    controller.set_visual_property("show_data_labels", True)
    controller.set_visual_property("show_legend", True)

    assert controller.selectedVisual == "Revenue by category"
    assert page["visual_filters"][0]["visual_name"] == "Revenue by category"
    assert controller._cross_filters == {}
    visual = next(item for item in page["visuals"] if item["title"] == controller.selectedVisual)
    assert {key: visual[key] for key in ("x", "y", "width", "height", "color")} == {
        "x": 12.5,
        "y": 30.0,
        "width": 420.0,
        "height": 260.0,
        "color": "#123ABC",
    }
    assert visual["show_data_labels"] is True
    assert visual["show_legend"] is True

    project_path = tmp_path / "visual-properties.npa"
    assert controller._save_to(project_path)
    reopened = StudioController(
        QApplication.instance(),
        QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
    )
    assert reopened.open_project_path(project_path)
    reopened.selectVisual("Revenue by category")
    visual = next(
        item for item in reopened.activeVisualObjects
        if item["title"] == "Revenue by category"
    )
    assert visual["color"] == "#123ABC"
    assert visual["show_data_labels"] is True
    assert visual["show_legend"] is True
    assert visual["x"] == 12.5
    assert visual["width"] == 420.0
    assert reopened.visualSeries("Revenue by category") == [
        {"label": "B", "value": 50.0},
        {"label": "A", "value": 20.0},
    ]
    assert reopened._active_page()["visual_filters"][0]["visual_name"] == "Revenue by category"


def test_invalid_visual_properties_leave_project_unchanged(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    controller._dirty = False
    visual = next(item for item in controller.activeVisualObjects if item["title"] == "Category amount")
    original = dict(visual)

    controller.set_visual_property("title", " ")
    controller.set_visual_property("width", "NaN")
    controller.set_visual_property("color", "blue")
    controller.set_visual_property("show_data_labels", 1)

    assert visual == original
    assert not controller._dirty
    controller.set_visual_property("x", -12)
    controller.set_visual_property("height", 4)
    assert visual["x"] == 0.0
    assert visual["height"] == 10.0
    assert controller._dirty


def test_format_tab_commits_general_visual_property_edits(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["visual property QML tests"])
    controller = _controller(tmp_path)
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
        controller.selectVisual("Category amount")
        app.processEvents()
        format_tab = next(
            item for item in items(window.contentItem())
            if item.objectName() == "visualTab_format"
        )
        format_tab.click()
        app.processEvents()
        title_field = next(
            item for item in items(window.contentItem())
            if item.objectName() == "visualProperty_title" and item.isVisible()
        )
        title_field.setProperty("text", "Edited in format pane")
        title_field.applyVisualProperty()
        app.processEvents()

        assert controller.selectedVisual == "Edited in format pane"
        assert any(
            item["title"] == "Edited in format pane"
            for item in controller.activeVisualObjects
        )
        color_field = next(
            item for item in items(window.contentItem())
            if item.objectName() == "visualProperty_color"
        )
        color_field.setProperty("text", "#123ABC")
        color_field.applyVisualProperty()
        app.processEvents()
        chart = next(
            item for item in items(window.contentItem())
            if item.objectName() == "chartCard_Edited in format pane"
        )
        assert chart.property("seriesLabel") == "Amount"
        assert chart.property("seriesColor").name() == "#123abc"
        label_toggle = next(
            item for item in items(window.contentItem())
            if item.objectName() == "visualPropertyToggle_show_data_labels"
        )
        legend_toggle = next(
            item for item in items(window.contentItem())
            if item.objectName() == "visualPropertyToggle_show_legend"
        )
        label_toggle.setProperty("checked", True)
        label_toggle.applyVisualProperty()
        app.processEvents()
        legend_toggle = next(
            item for item in items(window.contentItem())
            if item.objectName() == "visualPropertyToggle_show_legend"
        )
        legend_toggle.setProperty("checked", True)
        legend_toggle.applyVisualProperty()
        app.processEvents()
        edited_visual = next(
            item for item in controller.activeVisualObjects
            if item["title"] == "Edited in format pane"
        )
        assert edited_visual.get("show_data_labels") is True
        assert edited_visual.get("show_legend") is True
        chart = next(
            item for item in items(window.contentItem())
            if item.objectName() == "chartCard_Edited in format pane"
        )
        assert chart.property("showDataLabels") is True
        assert chart.property("showLegend") is True
        assert edited_visual["show_data_labels"] is True
        assert edited_visual["show_legend"] is True
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()
