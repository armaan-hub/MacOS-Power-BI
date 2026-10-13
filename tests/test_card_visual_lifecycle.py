from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QSettings, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.power_query_values import PowerQueryCellError

QQuickStyle.setStyle("Basic")


def _items(item: QQuickItem) -> Iterator[QQuickItem]:
    yield item
    for child in item.childItems():
        yield from _items(child)


def test_card_visual_aggregates_filters_highlights_and_persists(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["card visual tests"])
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
    controller.add_visual("card", "Revenue KPI", 14, 14, 120, 80)
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
        app.processEvents()
        # Existing summary cards use the same renderer and still show built-in values.
        assert controller.visualCardData("Revenue KPI")["value"] == "47"
        builtin_card = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "cardVisual_Revenue KPI"
        )
        assert builtin_card.property("visible") is True
        assert builtin_card.property("cardData")["value"] == "47"

        window.runCommand("insert.newVisual")
        window.runCommand("chart.type.card")
        visual = controller.activeVisualObjects[-1]
        assert visual["type"] == "card"
        assert visual["title"] == "Card"
        assert controller.selectedChartType == "card"
        assert [well["name"] for well in controller.activeVisualWells] == ["Fields", "Tooltips"]
        assert controller.activeVisualInteractions == []
        assert controller.visualCardData("Card")["value"] == "Add a field"

        controller.add_field_to_well("Fields", "Amount")
        assert controller.visualCardData("Card") == {
            "label": "Amount",
            "value": "47",
            "aggregation": "Sum",
            "highlight_value": "",
            "has_highlights": False,
        }
        app.processEvents()
        card_visual = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "cardVisual_Card"
        )
        assert card_visual.property("cardData")["value"] == "47"

        aggregation_button = next(
            item for item in _items(window.contentItem())
            if item.objectName() == "visualFieldAggregation" and item.isVisible()
        )
        assert aggregation_button.property("text") == "Sum"
        aggregation_button.click()
        app.processEvents()
        menu = window.findChild(QObject, "visualAggregationMenu")
        assert menu is not None
        assert menu.property("wellName") == "Fields"
        menu.chooseAggregation("Average")
        assert controller.visualCardData("Card")["value"] == "15.67"

        # Count is available for the same bound field and updates the card.
        controller.set_field_aggregation("Fields", "Amount", "Count")
        assert controller.visualCardData("Card")["value"] == "3"
        controller.set_field_aggregation("Fields", "Amount", "Average")

        controller.add_visual("column", "Category source", 720, 80, 330, 248)
        controller.selectVisual("Category source")
        controller.add_field_to_well("X-axis", "Category")
        controller.add_field_to_well("Y-axis", "Amount")
        controller.set_visual_interaction("Category source", "Card", "highlight")
        controller.toggle_cross_filter("Category source", "A")
        assert controller.visualCardData("Card") == {
            "label": "Amount",
            "value": "15.67",
            "aggregation": "Average",
            "highlight_value": "11",
            "has_highlights": True,
        }
        controller.toggle_cross_filter("Category source", "A")

        project_path = tmp_path / "card-visual.npa"
        assert controller._save_to(project_path)
        reopened = StudioController(
            QApplication.instance(),
            QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        assert reopened.open_project_path(project_path)
        saved = next(
            item for item in reopened.activeVisualObjects if item["id"] == visual["id"]
        )
        assert saved["type"] == "card"
        assert saved["fields"] == {"Fields": ["Amount"]}
        assert saved["field_aggregations"] == {"Amount": "average"}
        assert reopened.visualCardData("Card")["value"] == "15.67"

        source_path.write_text(
            "Category,Amount\nA,30\nB,50\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        assert reopened.visualCardData("Card")["value"] == "40"
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()


def test_card_shows_power_query_cell_errors_instead_of_partial_aggregates(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication(["card Power Query error tests"])
    source_path = tmp_path / "error-sales.json"
    source_path.write_text(
        '[{"Category":"A","Amount":10},{"Category":"B","Amount":20}]',
        encoding="utf-8",
    )
    controller = StudioController(
        app,
        QSettings(str(tmp_path / "error-settings.ini"), QSettings.Format.IniFormat),
    )
    assert controller._commit_import(source_path, parse_file(source_path))
    controller.add_visual("card", "Error card", 14, 14, 120, 80)
    controller.add_field_to_well("Fields", "Amount")
    source_id = str(controller._active_source_id)
    controller._loaded_candidates[source_id].rows[0]["Amount"] = PowerQueryCellError(
        "DataFormat.Error", "invalid amount", "bad", "decimal_number", row=1,
    )
    controller._report_filter_context_cache.clear()

    assert controller.visualCardData("Error card")["value"] == "Error"
