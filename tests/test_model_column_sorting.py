"""Lifecycle contract tests for model Sort by Column metadata and consumers."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCandidate, parse_file
from analytics_studio.power_query_values import PowerQueryCellError
from analytics_studio.project import FORMAT_VERSION, ProjectFileError, new_project, validate_project


def _controller(
    rows: list[dict[str, object]],
    column_types: dict[str, str],
    *,
    table_id: str = "sales-catalog-id",
    source_id: str = "sales-source-id",
    calculated_columns: list[dict[str, object]] | None = None,
) -> StudioController:
    headers = list(column_types)
    normalized_rows = [dict(row) for row in rows]
    controller = StudioController()
    controller._project["data_sources"] = [{
        "id": source_id,
        "name": "Sales",
        "kind": "inline",
        "headers": headers,
        "rows": normalized_rows,
    }]
    controller._project["model"]["tables"] = [{
        "id": table_id,
        "source_id": source_id,
        "name": "Sales",
        "column_types": dict(column_types),
        "calculated_columns": deepcopy(calculated_columns or []),
    }]
    candidate = ImportCandidate(
        "inline", headers, normalized_rows, {"name": "Sales"}, []
    )
    candidate.set_source_identity(source_id)
    controller._install_source(None, source_id, candidate)
    controller._refresh_model_view()
    controller._refresh_report()
    return controller


def _visual(
    controller: StudioController,
    visual_type: str,
    title: str,
    fields: dict[str, str],
) -> dict[str, object]:
    controller.add_visual(visual_type, title, 20, 20, 320, 240)
    for well, field in fields.items():
        controller.add_field_to_well(well, field)
    return next(
        visual for visual in controller._active_page()["visuals"]
        if visual.get("title") == title
    )


def _set_sort(controller: StudioController, category: str, sort_column: str) -> bool:
    return controller.set_model_column_sort_by(
        controller._active_model_table_id(), category, sort_column
    )


def test_new_project_is_current_and_v79_migration_adds_sort_map() -> None:
    project = new_project("v79")
    project["format_version"] = 79
    project["model"]["tables"] = [{
        "id": "orders-catalog",
        "source_id": "orders-source",
        "name": "Orders",
        "column_types": {"Month": "text", "MonthNumber": "whole_number"},
        "column_summarizations": {"MonthNumber": "sum"},
        "calculated_columns": [],
    }]

    migrated = validate_project(project)
    current = new_project("current")

    assert FORMAT_VERSION >= 80
    assert current["format_version"] == FORMAT_VERSION
    assert migrated["format_version"] == FORMAT_VERSION
    assert migrated["model"]["tables"][0]["column_sort_by"] == {}
    assert migrated["model"]["tables"][0]["column_summarizations"] == {
        "MonthNumber": "sum",
    }


def test_structural_sort_map_keeps_stale_names_and_rejects_malformed_maps() -> None:
    project = new_project("sort metadata")
    project["model"]["tables"] = [{
        "id": "orders", "source_id": "orders", "name": "Orders",
        "column_types": {"Month": "text"},
        "column_sort_by": {"Removed Month": "Removed Order"},
    }]
    validated = validate_project(project)
    assert validated["model"]["tables"][0]["column_sort_by"] == {
        "Removed Month": "Removed Order",
    }

    for invalid in (
        [], None, "Month=Order", {" ": "Order"}, {"Month": " "},
        {1: "Order"}, {"Month": 2},
    ):
        project["model"]["tables"][0]["column_sort_by"] = invalid
        with pytest.raises(ProjectFileError, match="sort"):
            validate_project(project)


def test_setter_uses_catalog_id_and_rejects_invalid_updates_transactionally() -> None:
    controller = _controller([
        {"Category": "A", "Order": 1, "Ambiguous": 1},
        {"Category": "A", "Order": 1, "Ambiguous": 1},
        {"Category": "B", "Order": 2, "Ambiguous": 1},
    ], {
        "Category": "text", "Order": "whole_number", "Ambiguous": "whole_number",
    })
    table_id = controller._active_model_table_id()

    assert table_id == "sales-catalog-id"
    assert _set_sort(controller, "Category", "Order")
    assert controller._project["model"]["tables"][0]["column_sort_by"] == {
        "Category": "Order",
    }
    assert not controller.set_model_column_sort_by(table_id, "Category", "Category")
    assert not controller.set_model_column_sort_by(table_id, "Category", "Ambiguous")
    assert controller._project["model"]["tables"][0]["column_sort_by"] == {
        "Category": "Order",
    }
    assert controller._table_catalog[0]["columnSortByStatuses"]["Category"]["active"]


def test_setter_checks_both_mapping_directions_and_rejects_blank_error_and_bad_cells() -> None:
    for rows in (
        [{"Category": "A", "Order": 1}, {"Category": "A", "Order": 2}],
        [{"Category": "A", "Order": 1}, {"Category": "B", "Order": 1}],
        [{"Category": "A", "Order": None}, {"Category": "B", "Order": 2}],
        [{"Category": None, "Order": 1}, {"Category": "B", "Order": 2}],
        [{"Category": "", "Order": 1}, {"Category": "B", "Order": 2}],
        [{"Category": "A", "Order": ""}, {"Category": "B", "Order": 2}],
        [{"Category": "A", "Order": 1}, {"Category": "B", "Order": PowerQueryCellError(
            "DataFormat.Error", "bad order", row=2,
        )}],
        [{"Category": PowerQueryCellError(
            "DataFormat.Error", "bad category", row=1,
        ), "Order": 1}, {"Category": "B", "Order": 2}],
    ):
        controller = _controller(rows, {"Category": "text", "Order": "any"})
        assert not _set_sort(controller, "Category", "Order")
        assert controller._project["model"]["tables"][0]["column_sort_by"] == {}
        assert controller._table_catalog[0]["columnSortByStatuses"]["Category"]["active"] is False
        assert controller._table_catalog[0]["columnSortByStatuses"]["Category"]["reason"]

    normalized_sort_duplicate = _controller([
        {"Category": "A", "Order": 1}, {"Category": "B", "Order": "1"},
    ], {"Category": "text", "Order": "whole_number"})
    assert not _set_sort(normalized_sort_duplicate, "Category", "Order")
    normalized_category_duplicate = _controller([
        {"Category": 1, "Order": 1}, {"Category": "1", "Order": 2},
    ], {"Category": "whole_number", "Order": "whole_number"})
    assert not _set_sort(normalized_category_duplicate, "Category", "Order")

    unsupported = _controller(
        [{"Category": "A", "Order": 1}, {"Category": "B", "Order": 2}],
        {"Category": "text", "Order": "any"},
    )
    unsupported._loaded_candidates["sales-source-id"].rows[0]["Order"] = [1]
    unsupported._refresh_model_view()
    assert not _set_sort(unsupported, "Category", "Order")
    assert "unsupported" in unsupported._table_catalog[0]["columnSortByStatuses"]["Category"]["reason"].casefold()


@pytest.mark.parametrize(
    ("rows", "types", "active"),
    [
        (
            [{"Category": "A", "Order": 1}, {"Category": "B", "Order": 2}],
            {"Category": "any", "Order": "whole_number"}, True,
        ),
        (
            [{"Category": "A", "Order": 1}, {"Category": True, "Order": 2}],
            {"Category": "any", "Order": "whole_number"}, False,
        ),
        (
            [{"Category": "A", "Order": 1}, {"Category": "B", "Order": "2"}],
            {"Category": "text", "Order": "any"}, False,
        ),
    ],
)
def test_any_columns_require_one_supported_scalar_family(rows, types, active) -> None:
    controller = _controller(rows, types)
    assert _set_sort(controller, "Category", "Order") is active


def test_sort_comparator_is_numeric_boolean_text_and_whitespace_aware() -> None:
    numeric = _controller([
        {"Category": "ten", "Order": 10}, {"Category": "two", "Order": 2},
    ], {"Category": "text", "Order": "whole_number"})
    assert _set_sort(numeric, "Category", "Order")
    _visual(numeric, "column", "Numbers", {"X-axis": "Category", "Y-axis": "Order"})
    assert [item["label"] for item in numeric.visualSeries("Numbers")] == ["two", "ten"]

    boolean = _controller([
        {"Category": "true", "Order": True}, {"Category": "false", "Order": False},
    ], {"Category": "text", "Order": "boolean"})
    assert _set_sort(boolean, "Category", "Order")
    _visual(boolean, "slicer", "Boolean slicer", {"Fields": "Category"})
    assert [item["label"] for item in boolean.visualSeries("Boolean slicer")] == [
        "false", "true",
    ]

    text = _controller([
        {"Category": "lower", "Order": "alpha"},
        {"Category": "upper", "Order": "Alpha"},
        {"Category": "space", "Order": " "},
    ], {"Category": "text", "Order": "text"})
    assert _set_sort(text, "Category", "Order")
    _visual(text, "slicer", "Text slicer", {"Fields": "Category"})
    assert [item["label"] for item in text.visualSeries("Text slicer")] == [
        "space", "upper", "lower",
    ]


def test_normalized_category_keys_cover_each_raw_representation_in_consumers() -> None:
    controller = _controller([
        {"Category": 1, "Order": 1, "Sales": 10},
        {"Category": "1", "Order": "1", "Sales": 20},
    ], {
        "Category": "whole_number", "Order": "whole_number", "Sales": "whole_number",
    })
    assert _set_sort(controller, "Category", "Order")
    _visual(controller, "column", "Normalized category", {
        "X-axis": "Category", "Y-axis": "Sales",
    })
    assert controller.visualSeries("Normalized category") == [
        {"label": "1", "value": 10.0}, {"label": "1", "value": 20.0},
    ]

    boolean_duplicate = _controller([
        {"Category": "A", "Order": True},
        {"Category": "B", "Order": "TRUE"},
    ], {"Category": "text", "Order": "boolean"})
    assert not _set_sort(boolean_duplicate, "Category", "Order")


def test_temporal_sorting_uses_date_and_datetime_contract() -> None:
    dates = _controller([
        {"Category": "late", "Order": "2024-10-01"},
        {"Category": "early", "Order": "2024-02-01"},
    ], {"Category": "text", "Order": "date"})
    assert _set_sort(dates, "Category", "Order")
    _visual(dates, "slicer", "Date slicer", {"Fields": "Category"})
    assert [item["label"] for item in dates.visualSeries("Date slicer")] == ["early", "late"]

    naive = _controller([
        {"Category": "late", "Order": "2024-01-01T12:00:00"},
        {"Category": "early", "Order": "2024-01-01T02:00:00"},
    ], {"Category": "text", "Order": "datetime"})
    assert _set_sort(naive, "Category", "Order")
    _visual(naive, "slicer", "Naive time slicer", {"Fields": "Category"})
    assert [item["label"] for item in naive.visualSeries("Naive time slicer")] == [
        "early", "late",
    ]

    aware = _controller([
        {"Category": "utc", "Order": "2024-01-01T00:00:00+00:00"},
        {"Category": "offset", "Order": "2023-12-31T19:00:00-05:00"},
    ], {"Category": "text", "Order": "datetime"})
    assert _set_sort(aware, "Category", "Order")
    _visual(aware, "slicer", "Aware time slicer", {"Fields": "Category"})
    assert [item["label"] for item in aware.visualSeries("Aware time slicer")] == [
        "offset", "utc",
    ]

    mixed = _controller([
        {"Category": "naive", "Order": "2024-01-01T00:00:00"},
        {"Category": "aware", "Order": "2024-01-01T00:00:00+00:00"},
    ], {"Category": "text", "Order": "datetime"})
    assert not _set_sort(mixed, "Category", "Order")

    times = _controller([
        {"Category": "late", "Order": "15:00:00"},
        {"Category": "early", "Order": "09:00:00"},
    ], {"Category": "text", "Order": "time"})
    assert _set_sort(times, "Category", "Order")
    _visual(times, "slicer", "Time slicer", {"Fields": "Category"})
    assert [item["label"] for item in times.visualSeries("Time slicer")] == ["early", "late"]

    aware_times = _controller([
        {"Category": "offset", "Order": "08:00:00+00:00"},
        {"Category": "plain", "Order": "09:00:00"},
    ], {"Category": "text", "Order": "time"})
    assert not _set_sort(aware_times, "Category", "Order")


def test_aware_datetime_equal_instants_use_iso_tie_break() -> None:
    controller = _controller([
        {"Category": "utc", "Order": "2024-01-01T00:00:00+00:00"},
        {"Category": "offset", "Order": "2023-12-31T19:00:00-05:00"},
    ], {"Category": "text", "Order": "datetime"})
    assert _set_sort(controller, "Category", "Order")
    _visual(controller, "slicer", "Tie slicer", {"Fields": "Category"})
    assert [item["label"] for item in controller.visualSeries("Tie slicer")] == [
        "offset", "utc",
    ]


def test_setter_rejects_calculated_unloaded_and_missing_columns_and_stale_clear() -> None:
    controller = _controller([
        {"Category": "A", "Order": 1, "Calc": 5},
        {"Category": "B", "Order": 2, "Calc": 6},
    ], {"Category": "text", "Order": "whole_number", "Calc": "whole_number"},
        calculated_columns=[{"name": "Calc", "expression": "1"}])
    table_id = controller._active_model_table_id()
    assert not controller.set_model_column_sort_by(table_id, "Category", "Calc")
    assert not controller.set_model_column_sort_by(table_id, "Category", "Missing")
    assert controller.set_model_column_sort_by(table_id, "Category", "Order")

    controller._loaded_candidates.clear()
    controller._refresh_model_view()
    assert controller.clear_model_column_sort_by(table_id, "Category")
    assert controller._project["model"]["tables"][0]["column_sort_by"] == {}


def test_same_named_columns_remain_scoped_to_their_model_table() -> None:
    controller = _controller([
        {"Category": "A", "Order": 1, "Sales": 10},
        {"Category": "B", "Order": 2, "Sales": 20},
    ], {"Category": "text", "Order": "whole_number", "Sales": "whole_number"})
    other_id = "other-source"
    other_catalog_id = "other-catalog"
    other_rows = [{"Category": "A", "Order": 2}, {"Category": "B", "Order": 1}]
    controller._project["data_sources"].append({
        "id": other_id, "name": "Other", "kind": "inline",
        "headers": ["Category", "Order"], "rows": other_rows,
    })
    controller._project["model"]["tables"].append({
        "id": other_catalog_id, "source_id": other_id, "name": "Other",
        "column_types": {"Category": "text", "Order": "whole_number"},
        "calculated_columns": [],
    })
    other = ImportCandidate("inline", ["Category", "Order"], other_rows, {}, [])
    other.set_source_identity(other_id)
    controller._loaded_candidates[other_id] = other
    controller._refresh_model_view()

    assert controller.set_model_column_sort_by("sales-catalog-id", "Category", "Order")
    assert controller.set_model_column_sort_by(other_catalog_id, "Category", "Order")
    assert controller.clear_model_column_sort_by(other_catalog_id, "Category")
    assert controller._project["model"]["tables"][0]["column_sort_by"] == {
        "Category": "Order",
    }
    assert controller._project["model"]["tables"][1]["column_sort_by"] == {}

    assert controller.set_model_column_sort_by(other_catalog_id, "Category", "Order")
    controller._project["model"]["measures"] = [{
        "name": "Total Sales", "expression": "SUM([Sales])",
    }]
    dax_visual = _visual(controller, "column", "Other DAX binding", {
        "X-axis": "Category", "Y-axis": "__dax_measure__:Total Sales",
    })
    dax_visual["fields"]["X-axis"] = [{
        "table_id": other_catalog_id, "column": "Category",
    }]
    assert [item["label"] for item in controller.visualSeries("Other DAX binding")] == [
        "A", "B",
    ]


def test_direct_chart_stacked_legend_kpi_slicer_and_matrix_use_model_order() -> None:
    controller = _controller([
        {"Category": "Alpha", "CategoryOrder": 2, "Brand": "Alpha", "BrandOrder": 2,
         "Period": "Q10", "PeriodOrder": 10, "Goal": 1, "Sales": 10},
        {"Category": "Zulu", "CategoryOrder": 1, "Brand": "Zulu", "BrandOrder": 1,
         "Period": "Q2", "PeriodOrder": 2, "Goal": 2, "Sales": 20},
        {"Category": "Alpha", "CategoryOrder": 2, "Brand": "Zulu", "BrandOrder": 1,
         "Period": "Q1", "PeriodOrder": 1, "Goal": 3, "Sales": 30},
    ], {
        "Category": "text", "CategoryOrder": "whole_number", "Brand": "text",
        "BrandOrder": "whole_number", "Period": "text", "PeriodOrder": "whole_number",
        "Goal": "whole_number", "Sales": "whole_number",
    })
    for category, order in (
        ("Category", "CategoryOrder"), ("Brand", "BrandOrder"),
        ("Period", "PeriodOrder"),
    ):
        assert _set_sort(controller, category, order)

    _visual(controller, "column", "Category chart", {
        "X-axis": "Category", "Y-axis": "Sales",
    })
    assert [item["label"] for item in controller.visualSeries("Category chart")] == [
        "Zulu", "Alpha",
    ]

    _visual(controller, "stackedColumn", "Stacked", {
        "X-axis": "Category", "Y-axis": "Sales", "Legend": "Brand",
    })
    assert controller.visualSeries("Stacked") == [
        {"label": "Zulu", "value": 20.0, "segments": [
            {"label": "Zulu", "value": 20.0}, {"label": "Alpha", "value": 0.0},
        ]},
        {"label": "Alpha", "value": 40.0, "segments": [
            {"label": "Zulu", "value": 30.0}, {"label": "Alpha", "value": 10.0},
        ]},
    ]

    _visual(controller, "kpi", "Period KPI", {
        "Indicator": "Sales", "Trend axis": "Period", "Target goals": "Goal",
    })
    kpi = controller.visualKpiData("Period KPI")
    assert [item["label"] for item in kpi["trend"]] == ["Q1", "Q2", "Q10"]
    assert kpi["value"] == 10.0
    assert kpi["target"] == 1.0

    controller._project["model"]["measures"] = [{
        "name": "Total Sales", "expression": "SUM([Sales])",
    }]
    _visual(controller, "kpi", "DAX Period KPI", {
        "Indicator": "__dax_measure__:Total Sales",
        "Trend axis": "Period", "Target goals": "Goal",
    })
    dax_kpi = controller.visualKpiData("DAX Period KPI")
    assert [item["label"] for item in dax_kpi["trend"]] == ["Q1", "Q2", "Q10"]
    assert dax_kpi["value"] == 10.0
    assert dax_kpi["target"] == 1.0

    _visual(controller, "slicer", "Category slicer", {"Fields": "Category"})
    assert [item["label"] for item in controller.visualSeries("Category slicer")] == [
        "Zulu", "Alpha",
    ]

    _visual(controller, "matrix", "Matrix", {
        "Rows": "Category", "Columns": "Period", "Values": "Sales",
    })
    matrix = controller.visualMatrixData("Matrix")
    assert matrix["columns"] == ["Category", "Q1", "Q2", "Q10"]
    assert [row["category"] for row in matrix["rows"]] == ["Zulu", "Alpha"]


def test_dax_measure_chart_categories_and_stacked_legend_use_raw_values() -> None:
    controller = _controller([
        {"Category": 10, "Order": 2, "Segment": "Zed", "SegmentOrder": 2, "Sales": 100},
        {"Category": 2, "Order": 1, "Segment": "Alpha", "SegmentOrder": 1, "Sales": 20},
        {"Category": 2, "Order": 1, "Segment": "Zed", "SegmentOrder": 2, "Sales": 30},
    ], {
        "Category": "whole_number", "Order": "whole_number", "Segment": "text",
        "SegmentOrder": "whole_number", "Sales": "whole_number",
    })
    controller._project["model"]["measures"] = [{
        "name": "Total Sales", "expression": "SUM([Sales])",
    }]
    assert _set_sort(controller, "Category", "Order")
    assert _set_sort(controller, "Segment", "SegmentOrder")

    measure = "__dax_measure__:Total Sales"
    _visual(controller, "column", "DAX chart", {
        "X-axis": "Category", "Y-axis": measure,
    })
    assert controller.visualSeries("DAX chart") == [
        {"label": "2", "value": 50.0}, {"label": "10", "value": 100.0},
    ]

    _visual(controller, "stackedColumn", "DAX stacked", {
        "X-axis": "Category", "Y-axis": measure, "Legend": "Segment",
    })
    assert controller.visualSeries("DAX stacked") == [
        {"label": "2", "value": 50.0, "segments": [
            {"label": "Alpha", "value": 20.0}, {"label": "Zed", "value": 30.0},
        ]},
        {"label": "10", "value": 100.0, "segments": [
            {"label": "Zed", "value": 100.0},
        ]},
    ]


def test_no_rule_and_cleared_rule_keep_exact_consumer_fallback_orders() -> None:
    controller = _controller([
        {"Category": "Z", "Order": 2, "Period": "10", "PeriodOrder": 10,
         "Rank": 10, "Sales": 30},
        {"Category": "A", "Order": 1, "Period": "2", "PeriodOrder": 2,
         "Rank": 30, "Sales": 10},
        {"Category": "M", "Order": 3, "Period": "1", "PeriodOrder": 1,
         "Rank": 20, "Sales": 20},
    ], {
        "Category": "text", "Order": "whole_number", "Period": "text",
        "PeriodOrder": "whole_number", "Rank": "whole_number", "Sales": "whole_number",
    })
    _visual(controller, "column", "Lexical", {"X-axis": "Category", "Y-axis": "Sales"})
    _visual(controller, "bar", "Value ranked", {"X-axis": "Category", "Y-axis": "Sales"})
    _visual(controller, "kpi", "Numeric KPI", {"Indicator": "Sales", "Trend axis": "Period"})

    assert [item["label"] for item in controller.visualSeries("Lexical")] == ["A", "M", "Z"]
    assert [item["label"] for item in controller.visualSeries("Value ranked")] == ["Z", "M", "A"]
    assert [item["label"] for item in controller.visualKpiData("Numeric KPI")["trend"]] == [
        "1", "2", "10",
    ]

    controller._project["model"]["tables"][0]["column_sort_by"] = {
        "Category": "Missing", "Period": "Missing",
    }
    controller._refresh_model_view()
    controller._refresh_report()
    assert [item["label"] for item in controller.visualSeries("Lexical")] == [
        "A", "M", "Z",
    ]
    assert [item["label"] for item in controller.visualSeries("Value ranked")] == [
        "Z", "M", "A",
    ]
    assert [item["label"] for item in controller.visualKpiData("Numeric KPI")["trend"]] == [
        "1", "2", "10",
    ]

    assert _set_sort(controller, "Category", "Order")
    assert _set_sort(controller, "Period", "PeriodOrder")
    assert [item["label"] for item in controller.visualSeries("Lexical")] == ["A", "Z", "M"]
    assert [item["label"] for item in controller.visualSeries("Value ranked")] == ["A", "Z", "M"]
    assert [item["label"] for item in controller.visualKpiData("Numeric KPI")["trend"]] == [
        "1", "2", "10",
    ]

    assert controller.clear_model_column_sort_by(
        controller._active_model_table_id(), "Category"
    )
    assert controller.clear_model_column_sort_by(
        controller._active_model_table_id(), "Period"
    )
    assert [item["label"] for item in controller.visualSeries("Lexical")] == ["A", "M", "Z"]
    assert [item["label"] for item in controller.visualSeries("Value ranked")] == ["Z", "M", "A"]
    assert [item["label"] for item in controller.visualKpiData("Numeric KPI")["trend"]] == [
        "1", "2", "10",
    ]


def test_absent_and_inactive_rules_keep_legacy_slicer_stacked_dax_and_matrix_orders() -> None:
    controller = _controller([
        {"Category": "Z", "BadCategoryOrder": 1, "Segment": "Y",
         "BadSegmentOrder": 1, "Sales": 10},
        {"Category": "Z", "BadCategoryOrder": 1, "Segment": "B",
         "BadSegmentOrder": 1, "Sales": 5},
        {"Category": "A", "BadCategoryOrder": 1, "Segment": "Y",
         "BadSegmentOrder": 1, "Sales": 40},
        {"Category": "A", "BadCategoryOrder": 1, "Segment": "B",
         "BadSegmentOrder": 1, "Sales": 20},
        {"Category": "M", "BadCategoryOrder": 1, "Segment": "Y",
         "BadSegmentOrder": 1, "Sales": 30},
        {"Category": "M", "BadCategoryOrder": 1, "Segment": "B",
         "BadSegmentOrder": 1, "Sales": 15},
    ], {
        "Category": "text", "BadCategoryOrder": "whole_number",
        "Segment": "text", "BadSegmentOrder": "whole_number",
        "Sales": "whole_number",
    })
    controller._project["model"]["measures"] = [{
        "name": "Total Sales", "expression": "SUM([Sales])",
    }]
    _visual(controller, "slicer", "Fallback slicer", {"Fields": "Category"})
    _visual(controller, "stackedColumn", "Fallback direct stacked", {
        "X-axis": "Category", "Y-axis": "Sales", "Legend": "Segment",
    })
    _visual(controller, "column", "Fallback DAX", {
        "X-axis": "Category", "Y-axis": "__dax_measure__:Total Sales",
    })
    _visual(controller, "stackedColumn", "Fallback DAX stacked", {
        "X-axis": "Category", "Y-axis": "__dax_measure__:Total Sales",
        "Legend": "Segment",
    })
    _visual(controller, "matrix", "Fallback matrix", {
        "Rows": "Category", "Columns": "Segment", "Values": "Sales",
    })

    def assert_legacy_order() -> None:
        assert [item["label"] for item in controller.visualSeries("Fallback slicer")] == [
            "A", "M", "Z",
        ]
        direct = controller.visualSeries("Fallback direct stacked")
        assert [item["label"] for item in direct] == ["A", "M", "Z"]
        assert [item["label"] for item in direct[0]["segments"]] == ["B", "Y"]
        dax = controller.visualSeries("Fallback DAX")
        assert [item["label"] for item in dax] == ["A", "M", "Z"]
        dax_stacked = controller.visualSeries("Fallback DAX stacked")
        assert [item["label"] for item in dax_stacked] == ["A", "M", "Z"]
        assert [item["label"] for item in dax_stacked[0]["segments"]] == ["B", "Y"]
        matrix = controller.visualMatrixData("Fallback matrix")
        assert matrix["columns"] == ["Category", "B", "Y"]
        assert [row["category"] for row in matrix["rows"]] == ["A", "M", "Z"]

    assert_legacy_order()
    controller._project["model"]["tables"][0]["column_sort_by"] = {
        "Category": "BadCategoryOrder", "Segment": "BadSegmentOrder",
    }
    controller._refresh_model_view()
    controller._refresh_report()
    assert not controller._table_catalog[0]["columnSortByStatuses"]["Category"]["active"]
    assert not controller._table_catalog[0]["columnSortByStatuses"]["Segment"]["active"]
    assert_legacy_order()


def test_top_n_membership_is_unchanged_while_output_uses_model_order() -> None:
    controller = _controller([
        {"Region": "A", "RegionOrder": 3, "Sales": 100},
        {"Region": "B", "RegionOrder": 2, "Sales": 90},
        {"Region": "C", "RegionOrder": 1, "Sales": 80},
    ], {"Region": "text", "RegionOrder": "whole_number", "Sales": "whole_number"})
    visual = _visual(controller, "column", "Region revenue", {
        "X-axis": "Region", "Y-axis": "Sales",
    })
    controller._active_page()["visual_filters"] = [{
        "visual_name": "Region revenue", "table_id": controller._active_model_table_id(),
        "column": "Region", "logic": "and", "clauses": [{
            "operator": "top_n", "direction": "top", "count": 2,
            "order_by": {"table_id": controller._active_model_table_id(), "column": "Sales"},
        }],
    }]
    controller._refresh_report()
    original = controller.visualSeries("Region revenue")
    assert {item["label"] for item in original} == {"A", "B"}
    assert [item["label"] for item in original] == ["A", "B"]

    assert _set_sort(controller, "Region", "RegionOrder")
    sorted_series = controller.visualSeries("Region revenue")
    assert {item["label"] for item in sorted_series} == {"A", "B"}
    assert [item["label"] for item in sorted_series] == ["B", "A"]
    assert [item["value"] for item in sorted_series] == [90.0, 100.0]


def test_bound_table_identity_prevents_same_name_sort_from_other_table() -> None:
    controller = _controller([
        {"Category": "A", "Order": 2, "Sales": 1},
        {"Category": "B", "Order": 1, "Sales": 1},
    ], {"Category": "text", "Order": "whole_number", "Sales": "whole_number"})
    other_rows = [
        {"Category": "A", "Order": 1}, {"Category": "B", "Order": 2},
    ]
    controller._project["data_sources"].append({
        "id": "other-source", "name": "Other", "kind": "inline",
        "headers": ["Category", "Order"], "rows": other_rows,
    })
    controller._project["model"]["tables"].append({
        "id": "other-catalog", "source_id": "other-source", "name": "Other",
        "column_types": {"Category": "text", "Order": "whole_number"},
        "calculated_columns": [],
    })
    candidate = ImportCandidate("inline", ["Category", "Order"], other_rows, {}, [])
    candidate.set_source_identity("other-source")
    controller._loaded_candidates["other-source"] = candidate
    controller._refresh_model_view()
    assert controller.set_model_column_sort_by("other-catalog", "Category", "Order")
    visual = _visual(controller, "column", "Other category", {
        "X-axis": "Category", "Y-axis": "Sales",
    })
    visual["fields"]["X-axis"] = [{
        "table_id": "other-catalog", "column": "Category",
    }]

    assert [item["label"] for item in controller.visualSeries("Other category")] == ["A", "B"]


def test_refresh_invalidates_then_recovers_saved_rule_across_reopen(tmp_path: Path) -> None:
    source_path = tmp_path / "months.csv"
    source_path.write_text(
        "Month,MonthNumber,Sales\nMarch,3,30\nJanuary,1,10\nFebruary,2,20\n",
        encoding="utf-8",
    )
    controller = StudioController(settings=QSettings(
        str(tmp_path / "initial.ini"), QSettings.Format.IniFormat,
    ))
    assert controller._commit_import(source_path, parse_file(source_path))
    table_id = controller._active_model_table_id()
    _visual(controller, "column", "Monthly", {"X-axis": "Month", "Y-axis": "Sales"})
    assert controller.set_model_column_sort_by(table_id, "Month", "MonthNumber")
    assert [item["label"] for item in controller.visualSeries("Monthly")] == [
        "January", "February", "March",
    ]

    valid_project = tmp_path / "valid.npa"
    assert controller._save_to(valid_project)
    reopened = StudioController(settings=QSettings(
        str(tmp_path / "valid-reopened.ini"), QSettings.Format.IniFormat,
    ))
    assert reopened.open_project_path(valid_project)
    assert [item["label"] for item in reopened.visualSeries("Monthly")] == [
        "January", "February", "March",
    ]

    source_path.write_text(
        "Month,MonthNumber,Sales\nMarch,1,30\nJanuary,1,10\nFebruary,2,20\n",
        encoding="utf-8",
    )
    reopened.refresh_source()
    assert [item["label"] for item in reopened.visualSeries("Monthly")] == [
        "February", "January", "March",
    ]
    assert reopened._project["model"]["tables"][0]["column_sort_by"] == {
        "Month": "MonthNumber",
    }
    assert not reopened._table_catalog[0]["columnSortByStatuses"]["Month"]["active"]

    dormant_project = tmp_path / "dormant.npa"
    assert reopened._save_to(dormant_project)
    dormant = StudioController(settings=QSettings(
        str(tmp_path / "dormant-reopened.ini"), QSettings.Format.IniFormat,
    ))
    assert dormant.open_project_path(dormant_project)
    assert dormant._project["model"]["tables"][0]["column_sort_by"] == {
        "Month": "MonthNumber",
    }
    assert [item["label"] for item in dormant.visualSeries("Monthly")] == [
        "February", "January", "March",
    ]

    source_path.write_text(
        "Month,MonthNumber,Sales\nMarch,3,30\nJanuary,1,10\nFebruary,2,20\n",
        encoding="utf-8",
    )
    dormant.refresh_source()
    assert [item["label"] for item in dormant.visualSeries("Monthly")] == [
        "January", "February", "March",
    ]
    assert dormant._table_catalog[0]["columnSortByStatuses"]["Month"]["active"]
