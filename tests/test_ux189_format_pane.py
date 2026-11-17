import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtWidgets import QApplication
import pytest

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.project import ProjectFileError, validate_project

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
    controller._project["report"]["pages"][0]["visuals"] = []
    controller._dirty = False
    return controller


def _items(item: QQuickItem):
    yield item
    for child in item.childItems():
        yield from _items(child)


def test_column_chart_groups_tabs_and_toggles(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    controller.add_visual("column", "Sales Chart", 10, 10, 400, 300)
    controller.selectVisual("Sales Chart")

    groups = controller.activeVisualPropertyGroups
    assert [g["tab"] for g in groups] == [
        "Visual", "Visual", "Visual", "Visual", "Visual", "Visual",
        "General", "General", "General", "General"
    ]
    assert [g["name"] for g in groups] == [
        "X-axis", "Y-axis", "Gridlines", "Colors", "Data labels", "Legend",
        "Properties", "Title", "Effects > Background", "Effects > Visual border"
    ]
    toggles = {g["name"]: (g["toggleKey"], g["toggleValue"]) for g in groups}
    assert toggles["X-axis"] == ("show_x_axis", True)
    assert toggles["Y-axis"] == ("show_y_axis", True)
    assert toggles["Gridlines"] == ("show_gridlines", True)
    assert toggles["Colors"] == (None, False)
    assert toggles["Data labels"] == ("show_data_labels", False)
    assert toggles["Legend"] == ("show_legend", False)
    assert toggles["Properties"] == (None, False)
    assert toggles["Title"] == ("show_title", True)
    assert toggles["Effects > Background"] == ("show_background", True)
    assert toggles["Effects > Visual border"] == ("show_border", True)


def test_property_validation(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    controller.add_visual("column", "Sales Chart", 10, 10, 400, 300)
    controller.selectVisual("Sales Chart")

    # Boolean keys
    for bool_key in ("show_title", "show_x_axis", "show_x_title", "show_y_axis", "show_y_title", "show_gridlines", "show_background", "show_border"):
        controller.set_visual_property(bool_key, False)
        visual = controller.activeVisualObjects[0]
        assert visual[bool_key] is False
        controller.set_visual_property(bool_key, "invalid_boolean")
        assert controller.statusMessage == "Choose whether to show this visual element."

    # Color keys
    for color_key in ("title_color", "data_label_color", "background_color", "border_color"):
        controller.set_visual_property(color_key, "#112233")
        visual = controller.activeVisualObjects[0]
        assert visual[color_key] == "#112233"
        controller.set_visual_property(color_key, "invalid_color")
        assert controller.statusMessage == "Enter a color in #RRGGBB format."

    # Font size (8 - 40)
    controller.set_visual_property("title_font_size", 20)
    assert controller.activeVisualObjects[0]["title_font_size"] == 20.0
    controller.set_visual_property("title_font_size", 5)
    assert controller.statusMessage == "Enter a font size between 8 and 40."
    controller.set_visual_property("title_font_size", 50)
    assert controller.statusMessage == "Enter a font size between 8 and 40."

    # Title alignment (left, center, right)
    controller.set_visual_property("title_align", "center")
    assert controller.activeVisualObjects[0]["title_align"] == "center"
    controller.set_visual_property("title_align", "justify")
    assert controller.statusMessage == "Choose an alignment of left, center, or right."

    # Legend position (top, bottom)
    controller.set_visual_property("legend_position", "bottom")
    assert controller.activeVisualObjects[0]["legend_position"] == "bottom"
    controller.set_visual_property("legend_position", "left")
    assert controller.statusMessage == "Choose a legend position of top or bottom."

    # Background transparency (0 - 100)
    controller.set_visual_property("background_transparency", 50)
    assert controller.activeVisualObjects[0]["background_transparency"] == 50.0
    controller.set_visual_property("background_transparency", -10)
    assert controller.statusMessage == "Enter a transparency between 0 and 100."
    controller.set_visual_property("background_transparency", 110)
    assert controller.statusMessage == "Enter a transparency between 0 and 100."

    # Border radius (0 - 30)
    controller.set_visual_property("border_radius", 15)
    assert controller.activeVisualObjects[0]["border_radius"] == 15.0
    controller.set_visual_property("border_radius", -5)
    assert controller.statusMessage == "Enter a border radius between 0 and 30."
    controller.set_visual_property("border_radius", 35)
    assert controller.statusMessage == "Enter a border radius between 0 and 30."


def test_project_save_load_roundtrips_new_keys(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    controller.add_visual("column", "Sales Chart", 10, 10, 400, 300)
    controller.selectVisual("Sales Chart")
    controller.set_visual_property("show_title", False)
    controller.set_visual_property("title_font_size", 18)
    controller.set_visual_property("title_color", "#AABBCC")
    controller.set_visual_property("title_align", "right")
    controller.set_visual_property("show_x_axis", False)
    controller.set_visual_property("show_x_title", True)
    controller.set_visual_property("show_y_axis", False)
    controller.set_visual_property("show_y_title", True)
    controller.set_visual_property("show_gridlines", False)
    controller.set_visual_property("data_label_color", "#DDEEFF")
    controller.set_visual_property("legend_position", "bottom")
    controller.set_visual_property("show_background", False)
    controller.set_visual_property("background_color", "#123456")
    controller.set_visual_property("background_transparency", 40)
    controller.set_visual_property("show_border", False)
    controller.set_visual_property("border_color", "#654321")
    controller.set_visual_property("border_radius", 12)

    project_file = tmp_path / "test_format_keys.npa"
    assert controller._save_to(project_file)

    reopened = _controller(tmp_path)
    assert reopened.open_project_path(project_file)
    visual = reopened.activeVisualObjects[0]
    assert visual["show_title"] is False
    assert visual["title_font_size"] == 18.0
    assert visual["title_color"] == "#AABBCC"
    assert visual["title_align"] == "right"
    assert visual["show_x_axis"] is False
    assert visual["show_x_title"] is True
    assert visual["show_y_axis"] is False
    assert visual["show_y_title"] is True
    assert visual["show_gridlines"] is False
    assert visual["data_label_color"] == "#DDEEFF"
    assert visual["legend_position"] == "bottom"
    assert visual["show_background"] is False
    assert visual["background_color"] == "#123456"
    assert visual["background_transparency"] == 40.0
    assert visual["show_border"] is False
    assert visual["border_color"] == "#654321"
    assert visual["border_radius"] == 12.0

    # Old project without new keys loads with defaults in activeVisualPropertyGroups
    old_project_data = reopened._project
    old_visual = old_project_data["report"]["pages"][0]["visuals"][0]
    for key in (
        "show_title", "title_font_size", "title_color", "title_align",
        "show_x_axis", "show_x_title", "show_y_axis", "show_y_title",
        "show_gridlines", "data_label_color", "legend_position",
        "show_background", "background_color", "background_transparency",
        "show_border", "border_color", "border_radius"
    ):
        old_visual.pop(key, None)

    validated = validate_project(old_project_data)
    reopened._project = validated
    reopened.selectVisual("Sales Chart")
    groups = reopened.activeVisualPropertyGroups
    props = {p["key"]: p["value"] for g in groups for p in g["properties"]}
    assert props["title_font_size"] == 14
    assert props["title_color"] == "#283746"
    assert props["title_align"] == "left"
    assert props["legend_position"] == "top"
    assert props["background_color"] == "#FFFFFF"
    assert props["background_transparency"] == 0
    assert props["border_color"] == "#d9e0e6"
    assert props["border_radius"] == 7


def test_qml_format_pane_rendering_and_tabs(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["format pane test"])
    controller = _controller(tmp_path)
    engine = QQmlEngine()
    component = QQmlComponent(engine)
    qml_path = Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml"
    component.loadUrl(QUrl.fromLocalFile(str(qml_path)))
    assert not component.isError(), "\n".join(e.toString() for e in component.errors())
    window = component.createWithInitialProperties({"studioController": controller})
    assert window is not None, "\n".join(e.toString() for e in component.errors())

    try:
        window.show()
        controller.setCurrentView("Report")
        controller.add_visual("column", "Category amount", 20, 20, 400, 300)
        controller.add_field_to_well("X-axis", "Category")
        controller.add_field_to_well("Y-axis", "Amount")
        controller.selectVisual("Category amount")
        app.processEvents()

        chart = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "chartCard_Category amount"
        )
        assert chart is not None

        # Setting show_title false hides the chart title item
        title_item = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "chartTitleText"
        )
        assert title_item.isVisible() is True
        controller.set_visual_property("show_title", False)
        app.processEvents()
        title_item = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "chartTitleText"
        )
        assert title_item.isVisible() is False

        # legend_position "bottom" puts legend below plot
        controller.set_visual_property("show_legend", True)
        controller.set_visual_property("legend_position", "top")
        app.processEvents()
        top_legend = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "chartLegendTop"
        )
        bottom_legend = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "chartLegendBottom"
        )
        assert top_legend.isVisible() is True
        assert bottom_legend.isVisible() is False

        controller.set_visual_property("legend_position", "bottom")
        app.processEvents()
        top_legend = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "chartLegendTop"
        )
        bottom_legend = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "chartLegendBottom"
        )
        assert top_legend.isVisible() is False
        assert bottom_legend.isVisible() is True
        # Compare y positions: bottom legend is lower down than top legend was
        assert bottom_legend.y() > top_legend.y()

        # show_gridlines false and background_color change ChartCard's properties
        controller.set_visual_property("show_gridlines", False)
        controller.set_visual_property("background_color", "#ABCDEF")
        app.processEvents()
        chart = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "chartCard_Category amount"
        )
        assert chart.property("showGridlines") is False
        assert chart.property("backgroundColor").name() == "#abcdef"

        # Tab buttons switch visible cards
        format_tab = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "visualTab_format"
        )
        format_tab.click()
        app.processEvents()

        tab_visual = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "formatTabVisual"
        )
        tab_general = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "formatTabGeneral"
        )

        card_xaxis = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "formatCard_X-axis"
        )
        card_properties = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "formatCard_Properties"
        )

        # Default tab is Visual: card_xaxis visible, card_properties hidden
        tab_visual.click()
        app.processEvents()
        assert card_xaxis.isVisible() is True
        assert card_properties.isVisible() is False

        # Switch to General: card_xaxis hidden, card_properties visible
        tab_general.click()
        app.processEvents()
        assert card_xaxis.isVisible() is False
        assert card_properties.isVisible() is True

    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()
