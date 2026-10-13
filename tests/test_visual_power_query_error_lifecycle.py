from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.power_query_values import PowerQueryCellError


def test_visuals_surface_power_query_errors_instead_of_partial_data(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication(["Power Query visual error tests"])
    source_path = tmp_path / "visual-errors.csv"
    source_path.write_text(
        "Category,Amount,Latitude,Longitude,City,Metadata\n"
        "A,10,25.2,55.3,Dubai,ok\n"
        "B,20,24.4,54.4,Abu Dhabi,ok\n",
        encoding="utf-8",
    )
    controller = StudioController(
        app,
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )
    assert controller._commit_import(source_path, parse_file(source_path))
    controller.setCurrentView("Report")

    controller.add_visual("column", "Error chart", 14, 14, 120, 80)
    controller.add_field_to_well("X-axis", "Category")
    controller.add_field_to_well("Y-axis", "Amount")
    controller.add_visual("scatter", "Error scatter", 150, 14, 120, 80)
    controller.add_field_to_well("X-axis", "Amount")
    controller.add_field_to_well("Y-axis", "Latitude")
    controller.add_visual("map", "Error map", 286, 14, 120, 80)
    controller.add_field_to_well("Location", "City")
    controller.add_field_to_well("Latitude", "Latitude")
    controller.add_field_to_well("Longitude", "Longitude")
    controller.add_field_to_well("Size", "Amount")
    controller.add_visual("gauge", "Error gauge", 422, 14, 120, 80)
    controller.add_field_to_well("Value", "Amount")

    assert controller.create_measure("Total Amount", "SUM([Amount])")
    controller.add_visual("column", "Measure chart", 558, 14, 120, 80)
    controller.add_field_to_well("X-axis", "Category")
    controller.add_field_to_well("Y-axis", "__dax_measure__:Total Amount")

    source_id = str(controller._active_source_id)
    controller._loaded_candidates[source_id].rows[0]["Metadata"] = PowerQueryCellError(
        "DataFormat.Error", "unrelated metadata error", "bad", "text", row=1,
    )
    controller._report_filter_context_cache.clear()
    assert controller.visualSeries("Measure chart")
    assert controller.visualErrorMessage("Measure chart") == ""

    controller._loaded_candidates[source_id].rows[0]["Amount"] = PowerQueryCellError(
        "DataFormat.Error", "invalid amount", "bad", "decimal_number", row=1,
    )
    controller._report_filter_context_cache.clear()

    assert controller.visualSeries("Measure chart") == []
    assert controller.visualErrorMessage("Measure chart") == (
        "Power Query errors are present in this visual's data."
    )

    assert controller.visualSeries("Error chart") == []
    assert controller.visualScatterData("Error scatter") == []
    assert controller.visualMapData("Error map") == []
    assert controller.visualGaugeData("Error gauge")["has_value"] is False
    for visual_name in ("Error chart", "Error scatter", "Error map", "Error gauge"):
        assert controller.visualErrorMessage(visual_name) == (
            "Power Query errors are present in this visual's data."
        )
