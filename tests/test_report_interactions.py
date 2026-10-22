from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QUrl, Qt
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import analytics_studio.controller as controller_module
from analytics_studio.controller import StudioController

QQuickStyle.setStyle("Basic")


def _loaded_sales_controller() -> StudioController:
    controller = StudioController()
    rows = [
        {"Category": "A", "Amount": "10"},
        {"Category": "A", "Amount": "20"},
        {"Category": "B", "Amount": "30"},
    ]
    controller._source_id = "source-sales"
    controller._active_source_id = "source-sales"
    controller._headers = ["Category", "Amount"]
    controller._rows = rows
    controller._table_catalog = [{
        "id": "SalesModel",
        "sourceId": "source-sales",
        "loaded": True,
        "loadEnabled": True,
        "columnTypes": {"Amount": "whole_number"},
    }]
    controller._loaded_candidates = {
        "source-sales": SimpleNamespace(headers=controller._headers, rows=rows)
    }
    controller._project["report"]["pages"][0].update({
        "filters": [{
            "table_id": "SalesModel",
            "column": "Amount",
            "clauses": [{"operator": "greater_than", "value": "10"}],
            "logic": "and",
        }],
        "visuals": [
            {"title": "Source", "type": "bar", "fields": {"X-axis": ["Category"]}},
            {
                "title": "Target",
                "type": "bar",
                "fields": {"X-axis": ["Category"], "Y-axis": ["Amount"]},
            },
        ],
    })
    return controller


def test_cross_filter_uses_loaded_table_and_qml_field_well_shape() -> None:
    controller = _loaded_sales_controller()

    before, _, _ = controller._report_filter_context("Target")
    assert before["SalesModel"] == [
        {"Category": "A", "Amount": "20"},
        {"Category": "B", "Amount": "30"},
    ]
    assert controller._generate_dynamic_visual_series("Target") == [
        {"label": "B", "value": 30.0},
        {"label": "A", "value": 20.0},
    ]

    controller.toggle_cross_filter("Source", "A")
    after, _, _ = controller._report_filter_context("Target")
    source_after, _, _ = controller._report_filter_context("Source")

    assert after["SalesModel"] == [{"Category": "A", "Amount": "20"}]
    assert source_after["SalesModel"] == [
        {"Category": "A", "Amount": "20"},
        {"Category": "B", "Amount": "30"},
    ]
    assert controller._generate_dynamic_visual_series("Target") == [
        {"label": "A", "value": 20.0}
    ]
    assert not controller._dirty


def test_report_filter_context_is_reused_until_report_refresh(monkeypatch) -> None:
    controller = _loaded_sales_controller()
    calls = 0
    original = controller_module.propagate_relationship_filters

    def count_filter_propagation(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        controller_module, "propagate_relationship_filters", count_filter_propagation
    )
    controller._report_filter_context("Target")
    initial_calls = calls
    controller._report_filter_context("Target")

    assert initial_calls == 1
    assert calls == initial_calls

    controller.toggle_cross_filter("Source", "A")
    refreshed_calls = calls
    controller._report_filter_context("Target")

    assert refreshed_calls > initial_calls
    assert calls == refreshed_calls


def test_removing_cross_filter_source_clears_peer_cache_and_selection() -> None:
    controller = _loaded_sales_controller()
    source_visual = controller._project["report"]["pages"][0]["visuals"][0]
    source_visual["id"] = "source-visual"

    controller.toggle_cross_filter("Source", "A")

    assert controller.visualSeries("Target") == [{"label": "A", "value": 20.0}]
    controller.remove_visual(source_visual["id"])

    assert controller._cross_filters == {}
    assert controller.visualSeries("Target") == [
        {"label": "B", "value": 30.0},
        {"label": "A", "value": 20.0},
    ]

    controller.add_visual("slicer", "Source", 40, 40, 400, 300)

    assert controller.visualSeries("Target") == [
        {"label": "B", "value": 30.0},
        {"label": "A", "value": 20.0},
    ]


def test_selected_chart_has_only_valid_inspector_property_groups() -> None:
    controller = _loaded_sales_controller()

    controller.selectVisual("Target")

    groups = controller.activeVisualPropertyGroups
    assert groups
    assert all(isinstance(group, dict) for group in groups)
    assert all(isinstance(group.get("properties"), list) for group in groups)


def test_qml_chart_click_filters_peer_chart_and_preserves_page_filter() -> None:
    app = QApplication.instance() or QApplication(["report interaction tests"])
    controller = _loaded_sales_controller()
    extra_row = {"Category": "A", "Amount": "25"}
    controller._rows.append(extra_row)
    visuals = controller._project["report"]["pages"][0]["visuals"]
    visuals[0].update({"x": 40, "y": 40, "width": 400, "height": 300})
    visuals[1].update({"x": 480, "y": 40, "width": 400, "height": 300})

    engine = QQmlEngine()
    component = QQmlComponent(engine)
    qml_path = Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml"
    component.loadUrl(QUrl.fromLocalFile(str(qml_path)))
    assert not component.isError(), "\n".join(error.toString() for error in component.errors())
    window = component.createWithInitialProperties({"studioController": controller})
    assert window is not None, "\n".join(error.toString() for error in component.errors())

    def visual_items(item: QQuickItem):
        yield item
        for child in item.childItems():
            yield from visual_items(child)

    try:
        window.show()
        controller.setCurrentView("Report")
        app.processEvents()
        QTest.qWait(100)

        items = list(visual_items(window.contentItem()))
        source = next(
            item for item in items
            if item.metaObject().className().startswith("ChartCard")
            and item.property("visualName") == "Source"
        )
        target = next(
            item for item in items
            if item.metaObject().className().startswith("ChartCard")
            and item.property("visualName") == "Target"
        )
        canvas = next(
            item for item in visual_items(source)
            if "CanvasItem" in item.metaObject().className()
        )

        assert [(item["label"], item["value"]) for item in source.property("series")] == [
            ("A", 2.0),
            ("B", 1.0),
        ]
        assert controller.visualSeries("Target") == [
            {"label": "A", "value": 45.0},
            {"label": "B", "value": 30.0},
        ]

        plot_height = max(1.0, canvas.height() - 34.0)
        local_click = QPointF(50.0, 9.0 + plot_height / (2 * len(source.property("series"))))
        scene_click = canvas.mapToScene(local_click)
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(round(scene_click.x()), round(scene_click.y())),
        )
        QTest.qWait(100)
        app.processEvents()

        assert controller.selectedCrossFiltersForVisual("Source") == ["A"]
        assert [(item["label"], item["value"]) for item in target.property("series")] == [
            ("A", 45.0),
        ]
        assert [(item["label"], item["value"]) for item in source.property("series")] == [
            ("A", 2.0),
            ("B", 1.0),
        ]
        assert not controller._dirty

        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(round(scene_click.x()), round(scene_click.y())),
        )
        QTest.qWait(100)
        app.processEvents()
        assert controller.selectedCrossFiltersForVisual("Source") == []
        assert [(item["label"], item["value"]) for item in target.property("series")] == [
            ("A", 45.0),
            ("B", 30.0),
        ]

        short_bar_end_x = 38.0 + max(1.0, canvas.width() - 46.0) * 0.5
        blank_plot_point = canvas.mapToScene(QPointF(
            short_bar_end_x + 15.0,
            9.0 + plot_height * 0.75,
        ))
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(round(blank_plot_point.x()), round(blank_plot_point.y())),
        )
        QTest.qWait(100)
        app.processEvents()
        assert controller.selectedCrossFiltersForVisual("Source") == []
    finally:
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()


def test_qml_chart_resize_grip_changes_visual_size() -> None:
    app = QApplication.instance() or QApplication(["report interaction tests"])
    controller = StudioController()
    visual_id = controller.add_visual("bar", "Resizable", 100, 100, 300, 200)
    controller.setCurrentView("Report")
    state_changes: list[bool] = []
    controller.stateChanged.connect(lambda: state_changes.append(True))

    engine = QQmlEngine()
    component = QQmlComponent(engine)
    qml_path = Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml"
    component.loadUrl(QUrl.fromLocalFile(str(qml_path)))
    assert not component.isError(), "\n".join(error.toString() for error in component.errors())
    window = component.createWithInitialProperties({"studioController": controller})
    assert window is not None, "\n".join(error.toString() for error in component.errors())

    def visual_items(item: QQuickItem):
        yield item
        for child in item.childItems():
            yield from visual_items(child)

    try:
        window.resize(1280, 900)
        window.show()
        app.processEvents()
        QTest.qWait(100)
        handle = next(
            item for item in visual_items(window.contentItem())
            if item.objectName() == f"visualResizeHandle_{visual_id}"
        )
        mouse_area = next(
            item for item in visual_items(handle)
            if item.objectName() == f"visualResizeMouseArea_{visual_id}"
        )
        visual_delegate = next(
            item for item in visual_items(window.contentItem())
            if item.objectName() == f"reportVisual_{visual_id}"
        )
        assert handle.isVisible()
        start = handle.mapToScene(
            QPointF(handle.width() / 2, handle.height() / 2)
        )
        start_point = QPoint(round(start.x()), round(start.y()))
        end_point = start_point + QPoint(84, 56)

        QTest.mousePress(window, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, start_point)
        app.processEvents()
        assert mouse_area.property("pressed"), (
            f"Resize handle did not receive press at {start_point}; "
            f"handle scene bounds={handle.mapToScene(QPointF(0, 0))}, "
            f"size={handle.width()}x{handle.height()}"
        )
        QTest.mouseMove(window, end_point, 50)
        app.processEvents()
        assert visual_delegate.width() > 300, (
            f"Resize drag did not change delegate width: {visual_delegate.width()}"
        )
        changes_before_release = len(state_changes)
        QTest.mouseRelease(window, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier, end_point)
        QTest.qWait(100)
        app.processEvents()
        assert len(state_changes) > changes_before_release, (
            "Releasing the resize grip did not commit the new size; "
            f"local dimensions are {visual_delegate.width()}x{visual_delegate.height()}"
        )

        visual = next(
            item for item in controller.activeVisualObjects
            if item["id"] == visual_id
        )
        assert visual["width"] >= 350, visual
        assert visual["height"] >= 230, visual
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("report_zoom", [0.15, 1.5], ids=["min-zoom", "max-zoom"])
@pytest.mark.parametrize(
    "drag_delta", [QPoint(30, 24), QPoint(-30, -24)], ids=["grow", "shrink"]
)
def test_qml_chart_resize_grip_stays_usable_across_zoom_and_direction(
    report_zoom: float,
    drag_delta: QPoint,
) -> None:
    app = QApplication.instance() or QApplication(["report interaction tests"])
    controller = StudioController()
    visual_id = controller.add_visual("bar", "Small zoom", 100, 100, 300, 200)
    controller.setCurrentView("Report")

    engine = QQmlEngine()
    component = QQmlComponent(engine)
    qml_path = Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml"
    component.loadUrl(QUrl.fromLocalFile(str(qml_path)))
    assert not component.isError(), "\n".join(error.toString() for error in component.errors())
    window = component.createWithInitialProperties({"studioController": controller})
    assert window is not None, "\n".join(error.toString() for error in component.errors())

    def visual_items(item: QQuickItem):
        yield item
        for child in item.childItems():
            yield from visual_items(child)

    try:
        window.resize(1280, 900)
        window.show()
        app.processEvents()
        QTest.qWait(100)
        # Main.qml schedules Fit to Page on completion. Set the explicit zoom
        # after that initial layout so the test observes the minimum zoom.
        window.setProperty("fitZoom", False)
        window.setProperty("reportZoom", report_zoom)
        app.processEvents()
        assert window.property("reportZoom") == report_zoom
        handle = next(
            item for item in visual_items(window.contentItem())
            if item.objectName() == f"visualResizeHandle_{visual_id}"
        )
        mouse_area = next(
            item for item in visual_items(handle)
            if item.objectName() == f"visualResizeMouseArea_{visual_id}"
        )
        visual_delegate = next(
            item for item in visual_items(window.contentItem())
            if item.objectName() == f"reportVisual_{visual_id}"
        )
        assert handle.isVisible()

        top_left = mouse_area.mapToScene(QPointF(0, 0))
        bottom_right = mouse_area.mapToScene(
            QPointF(mouse_area.width(), mouse_area.height())
        )
        hit_width = bottom_right.x() - top_left.x()
        hit_height = bottom_right.y() - top_left.y()
        assert hit_width == pytest.approx(16, abs=0.2), (
            "The resize target shrinks with report zoom: "
            f"{hit_width:.1f} Qt scene units wide at "
            f"{report_zoom:.0%} zoom"
        )
        assert hit_height == pytest.approx(16, abs=0.2), (
            f"Resize target is only {hit_height:.1f} Qt scene units tall at "
            f"{report_zoom:.0%} zoom"
        )

        start = mouse_area.mapToScene(
            QPointF(mouse_area.width() / 2, mouse_area.height() / 2)
        )
        start_point = QPoint(round(start.x()), round(start.y()))
        end_point = start_point + drag_delta
        QTest.mousePress(window, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, start_point)
        app.processEvents()
        assert mouse_area.property("pressed"), (
            f"Resize target did not receive the press at {report_zoom:.0%} zoom"
        )
        QTest.mouseMove(window, end_point, 50)
        app.processEvents()
        expected_comparison = (
            visual_delegate.width() > 300
            if drag_delta.x() > 0
            else visual_delegate.width() < 300
        )
        assert expected_comparison, (
            f"Resize drag did not {('grow' if drag_delta.x() > 0 else 'shrink')} "
            f"the visual at {report_zoom:.0%} zoom: {visual_delegate.width()}"
        )
        QTest.mouseRelease(window, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier, end_point)
        QTest.qWait(100)
        app.processEvents()
        visual = next(
            item for item in controller.activeVisualObjects
            if item["id"] == visual_id
        )
        expected_width = round(max(10, 300 + drag_delta.x() / report_zoom) / 10) * 10
        expected_height = round(max(10, 200 + drag_delta.y() / report_zoom) / 10) * 10
        assert (visual["width"], visual["height"]) == (
            expected_width,
            expected_height,
        ), visual
        if drag_delta.x() > 0:
            assert visual["width"] > 300 and visual["height"] > 200, visual
        else:
            assert visual["width"] < 300 and visual["height"] < 200, visual
            assert visual["width"] >= 10 and visual["height"] >= 10, visual
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()


def test_qml_chart_can_shrink_below_50_and_keeps_size_after_reopen(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["report interaction tests"])
    controller = StudioController()
    visual_id = controller.add_visual("bar", "Small chart", 100, 100, 40, 40)
    controller.setCurrentView("Report")

    engine = QQmlEngine()
    component = QQmlComponent(engine)
    qml_path = Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml"
    component.loadUrl(QUrl.fromLocalFile(str(qml_path)))
    assert not component.isError(), "\n".join(error.toString() for error in component.errors())
    window = component.createWithInitialProperties({"studioController": controller})
    assert window is not None, "\n".join(error.toString() for error in component.errors())

    def visual_items(item: QQuickItem):
        yield item
        for child in item.childItems():
            yield from visual_items(child)

    try:
        window.resize(1280, 900)
        window.show()
        app.processEvents()
        QTest.qWait(100)
        window.setProperty("fitZoom", False)
        window.setProperty("reportZoom", 1.0)
        app.processEvents()

        mouse_area = next(
            item for item in visual_items(window.contentItem())
            if item.objectName() == f"visualResizeMouseArea_{visual_id}"
        )
        visual_delegate = next(
            item for item in visual_items(window.contentItem())
            if item.objectName() == f"reportVisual_{visual_id}"
        )
        assert (visual_delegate.width(), visual_delegate.height()) == (40, 40)

        start = mouse_area.mapToScene(
            QPointF(mouse_area.width() / 2, mouse_area.height() / 2)
        )
        start_point = QPoint(round(start.x()), round(start.y()))
        end_point = start_point + QPoint(-20, -20)
        QTest.mousePress(window, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, start_point)
        app.processEvents()
        assert mouse_area.property("pressed")
        QTest.mouseMove(window, end_point, 50)
        app.processEvents()
        assert (visual_delegate.width(), visual_delegate.height()) == (20, 20)
        QTest.mouseRelease(window, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier, end_point)
        QTest.qWait(100)
        app.processEvents()

        saved_visual = next(
            visual for visual in controller.activeVisualObjects
            if visual["id"] == visual_id
        )
        assert (saved_visual["width"], saved_visual["height"]) == (20, 20)
        project_path = tmp_path / "small-chart-resize.npa"
        assert controller._save_to(project_path)

        reopened = StudioController()
        assert reopened.open_project_path(str(project_path))
        reopened_visual = next(
            visual for visual in reopened.activeVisualObjects
            if visual["id"] == visual_id
        )
        assert (reopened_visual["width"], reopened_visual["height"]) == (20, 20)

        mouse_area = next(
            item for item in visual_items(window.contentItem())
            if item.objectName() == f"visualResizeMouseArea_{visual_id}"
        )
        visual_delegate = next(
            item for item in visual_items(window.contentItem())
            if item.objectName() == f"reportVisual_{visual_id}"
        )

        minimum_start = mouse_area.mapToScene(
            QPointF(mouse_area.width() / 2, mouse_area.height() / 2)
        )
        minimum_start_point = QPoint(round(minimum_start.x()), round(minimum_start.y()))
        minimum_end_point = minimum_start_point + QPoint(-20, -20)
        QTest.mousePress(window, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, minimum_start_point)
        app.processEvents()
        QTest.mouseMove(window, minimum_end_point, 50)
        app.processEvents()
        assert (visual_delegate.width(), visual_delegate.height()) == (10, 10)
        QTest.mouseRelease(window, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier, minimum_end_point)
        QTest.qWait(100)
        app.processEvents()
        project_path = tmp_path / "small-chart-resize.npa"
        assert controller._save_to(project_path)

        minimum_reopened = StudioController()
        assert minimum_reopened.open_project_path(str(project_path))
        minimum_visual = next(
            visual for visual in minimum_reopened.activeVisualObjects
            if visual["id"] == visual_id
        )
        assert (minimum_visual["width"], minimum_visual["height"]) == (10, 10)
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()


def test_cross_filter_selection_is_transient_ui_state() -> None:
    controller = StudioController()

    controller.toggle_cross_filter("Source", "A")

    assert controller.selectedCrossFiltersForVisual("Source") == ["A"]
    assert not controller._dirty
    controller.toggle_cross_filter("Source", "A")
    assert controller.selectedCrossFiltersForVisual("Source") == []
    assert not controller._dirty


def test_clear_filters_removes_transient_chart_selections_and_restores_peer_rows() -> None:
    controller = _loaded_sales_controller()
    page = controller._project["report"]["pages"][0]
    page["filters"] = []
    page["visual_filters"] = []
    controller._project["report"]["filters"] = []
    page["visuals"] = [
        {"title": "Source", "type": "bar", "fields": {"X-axis": ["Category"]}},
        {"title": "Target", "type": "bar", "fields": {"X-axis": ["Category"], "Y-axis": ["Amount"]}},
    ]
    controller._refresh_report()

    controller.toggle_cross_filter("Source", "A")

    assert controller.filterActive
    assert controller.visualSeries("Target") == [{"label": "A", "value": 30.0}]
    controller._dirty = False
    controller.clear_filters()

    assert controller._cross_filters == {}
    assert controller.selectedCrossFiltersForVisual("Source") == []
    assert not controller.filterActive
    assert controller.visualSeries("Target") == [
        {"label": "A", "value": 30.0},
        {"label": "B", "value": 30.0},
    ]
    assert not controller._dirty


def test_month_chart_selection_matches_loaded_dates_by_month_prefix() -> None:
    controller = _loaded_sales_controller()
    rows = [
        {"Date": "2025-01-03", "Region": "East", "Revenue": "10"},
        {"Date": "2025-01-28", "Region": "West", "Revenue": "20"},
        {"Date": "2025-02-01", "Region": "East", "Revenue": "30"},
    ]
    controller._headers = ["Date", "Region", "Revenue"]
    controller._rows = rows
    controller._loaded_candidates["source-sales"] = SimpleNamespace(
        headers=controller._headers, rows=rows
    )
    controller._table_catalog[0]["columnTypes"] = {"Revenue": "whole_number"}
    controller._project["report"]["pages"][0].update({
        "filters": [],
        "visuals": [
            {"title": "Monthly revenue", "type": "column", "fields": {}},
            {
                "title": "Target",
                "type": "bar",
                "fields": {"X-axis": ["Region"], "Y-axis": ["Revenue"]},
            },
        ],
    })

    controller.toggle_cross_filter("Monthly revenue", "2025-01")
    rows_by_table, _, _ = controller._report_filter_context("Target")

    assert rows_by_table["SalesModel"] == rows[:2]
    assert controller._generate_dynamic_visual_series("Target") == [
        {"label": "West", "value": 20.0},
        {"label": "East", "value": 10.0},
    ]


def test_month_cross_filter_matches_dates_in_supported_display_formats() -> None:
    controller = _loaded_sales_controller()
    rows = [
        {"Date": "01/03/2025", "Region": "East", "Revenue": "10"},
        {"Date": "03-Jan-2025", "Region": "West", "Revenue": "20"},
        {"Date": "2025/02/01", "Region": "North", "Revenue": "30"},
    ]
    controller._headers = ["Date", "Region", "Revenue"]
    controller._rows = rows
    controller._loaded_candidates["source-sales"] = SimpleNamespace(
        headers=controller._headers, rows=rows
    )
    controller._table_catalog[0]["columnTypes"] = {
        "Date": "date", "Revenue": "whole_number"
    }
    controller._project["report"]["pages"][0].update({
        "filters": [],
        "visuals": [
            {"title": "Monthly revenue", "type": "column", "fields": {}},
            {
                "title": "Target",
                "type": "bar",
                "table_id": "SalesModel",
                "fields": {"X-axis": ["Region"], "Y-axis": ["Revenue"]},
            },
        ],
    })

    controller.toggle_cross_filter("Monthly revenue", "2025-01")

    assert controller.visualSeries("Target") == [
        {"label": "West", "value": 20.0},
        {"label": "East", "value": 10.0},
    ]


def test_dynamic_visual_series_uses_its_bound_table_after_active_table_changes() -> None:
    controller = _loaded_sales_controller()
    other_rows = [
        {"Category": "Other", "Amount": "99"},
    ]
    controller._table_catalog.append({
        "id": "OtherModel",
        "sourceId": "source-other",
        "loaded": True,
        "loadEnabled": True,
        "columnTypes": {"Amount": "whole_number"},
    })
    controller._loaded_candidates["source-other"] = SimpleNamespace(
        headers=["Category", "Amount"], rows=other_rows
    )
    for visual in controller._project["report"]["pages"][0]["visuals"]:
        visual["table_id"] = "SalesModel"
    controller._active_source_id = "source-other"
    controller._headers = ["Category", "Amount"]
    controller._rows = other_rows

    assert controller.visualSeries("Target") == [
        {"label": "B", "value": 30.0},
        {"label": "A", "value": 20.0},
    ]

    controller.toggle_cross_filter("Source", "A")

    assert controller.visualSeries("Target") == [{"label": "A", "value": 20.0}]


def test_relationship_error_does_not_show_unfiltered_peer_rows() -> None:
    controller = _loaded_sales_controller()
    other_rows = [
        {"Category": "A", "Amount": "100"},
        {"Category": "B", "Amount": "200"},
    ]
    controller._table_catalog.append({
        "id": "OtherModel",
        "sourceId": "source-other",
        "loaded": True,
        "loadEnabled": True,
        "columnTypes": {"Amount": "whole_number"},
    })
    controller._loaded_candidates["source-other"] = SimpleNamespace(
        headers=["Category", "Amount"], rows=other_rows
    )
    visuals = controller._project["report"]["pages"][0]["visuals"]
    visuals[0].update({
        "type": "slicer",
        "table_id": "SalesModel",
        "fields": {"Fields": ["Category"]},
    })
    visuals[1]["table_id"] = "OtherModel"
    visuals[1]["fields"] = {
        "X-axis": ["Category"],
        "Y-axis": ["Amount"],
    }
    controller._project["report"]["pages"][0]["filters"] = [{
        "table_id": "OtherModel",
        "column": "Amount",
        "clauses": [{"operator": "greater_than", "value": "150"}],
        "logic": "and",
    }]
    controller._project["model"]["relationships"] = [{
        "relationship_version": 1,
        "from_table_id": "SalesModel",
        "from_column": "MissingColumn",
        "to_table_id": "OtherModel",
        "to_column": "Category",
        "cardinality": "many_to_one",
        "is_active": True,
    }]

    controller.toggle_cross_filter("Source", "A")

    assert controller.visualSeries("Target") == []
    assert controller.visualSeries("Source") == [
        {"label": "A", "value": 1.0},
        {"label": "B", "value": 1.0},
    ]
    assert "no longer loaded" in controller._filter_context_error

    controller.toggle_cross_filter("Source", "A")

    assert controller.selectedCrossFiltersForVisual("Source") == []
    assert controller.visualSeries("Target") == [
        {"label": "B", "value": 200.0},
    ]


def test_page_change_clears_transient_visual_cross_filter_selection() -> None:
    controller = _loaded_sales_controller()
    second_page = deepcopy(controller._project["report"]["pages"][0])
    second_page.update({"id": "page-two", "name": "Second page"})
    controller._project["report"]["pages"].append(second_page)
    controller._cross_filters["Source"] = ["A"]

    controller.setActivePage(1)

    assert controller._cross_filters == {}
    assert controller.selectedCrossFiltersForVisual("Source") == []


def test_other_active_page_transitions_clear_transient_visual_selections() -> None:
    for transition in ("add", "duplicate", "delete"):
        controller = _loaded_sales_controller()
        active_page = controller._active_page()
        assert active_page is not None
        controller.toggle_cross_filter("Source", "A")

        if transition == "add":
            controller.add_page()
        elif transition == "duplicate":
            controller.duplicate_page(active_page["id"])
        else:
            second_page = deepcopy(active_page)
            second_page.update({"id": "page-two", "name": "Second page"})
            controller._project["report"]["pages"].append(second_page)
            controller.delete_page(active_page["id"])

        assert controller._cross_filters == {}
        assert controller.selectedCrossFiltersForVisual("Source") == []

    controller = _loaded_sales_controller()
    controller.toggle_cross_filter("Source", "A")
    controller._replace_with_new_project()

    assert controller._cross_filters == {}


def test_slicer_fields_well_supplies_values_and_filters_peer_charts() -> None:
    controller = _loaded_sales_controller()
    controller._project["report"]["pages"][0]["visuals"][0].update({
        "type": "slicer",
        "table_id": "SalesModel",
        "fields": {"Fields": ["Category"]},
    })

    assert controller.visualSeries("Source") == [
        {"label": "A", "value": 1.0},
        {"label": "B", "value": 1.0},
    ]


def test_slicer_field_picker_and_binding_reject_dax_measures() -> None:
    _app = QApplication.instance() or QApplication(["slicer measure eligibility tests"])
    controller = _loaded_sales_controller()
    controller._project["model"].setdefault("measures", []).append({
        "name": "Sales Total", "expression": "SUM([Amount])",
    })
    binding = "__dax_measure__:Sales Total"
    controller.add_visual("slicer", "Measure slicer", 40, 360, 300, 220)
    controller.selectVisual("Measure slicer")

    assert binding in controller.filteredFields
    assert binding not in controller.activeVisualFieldOptions
    controller.add_field_to_well("Fields", binding)
    assert "slicer" in controller.statusMessage.casefold()
    visual = next(
        item for item in controller.activeVisualObjects
        if item["title"] == "Measure slicer"
    )
    assert visual.get("fields", {}).get("Fields", []) == []
    assert controller.visualSeries("Measure slicer") == []

    # Older projects can contain this invalid binding, but it must not become
    # a selectable empty-string category.
    visual.setdefault("fields", {})["Fields"] = [binding]
    assert controller.visualSeries("Measure slicer") == []

    controller.toggle_cross_filter("Source", "A")

    assert controller.visualSeries("Target") == [{"label": "A", "value": 20.0}]
    assert controller.visualSeries("Source") == [
        {"label": "A", "value": 1.0},
        {"label": "B", "value": 1.0},
    ]


def test_qml_slicer_click_updates_peer_chart_and_selected_state() -> None:
    app = QApplication.instance() or QApplication(["slicer interaction tests"])
    controller = _loaded_sales_controller()
    visuals = controller._project["report"]["pages"][0]["visuals"]
    visuals[0].update({
        "type": "slicer",
        "table_id": "SalesModel",
        "x": 40,
        "y": 40,
        "width": 400,
        "height": 300,
        "fields": {"Fields": ["Category"]},
    })
    visuals[1].update({"x": 480, "y": 40, "width": 400, "height": 300})

    engine = QQmlEngine()
    component = QQmlComponent(engine)
    qml_path = Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml"
    component.loadUrl(QUrl.fromLocalFile(str(qml_path)))
    assert not component.isError(), "\n".join(error.toString() for error in component.errors())
    window = component.createWithInitialProperties({"studioController": controller})
    assert window is not None, "\n".join(error.toString() for error in component.errors())

    def visual_items(item: QQuickItem):
        yield item
        for child in item.childItems():
            yield from visual_items(child)

    try:
        window.show()
        controller.setCurrentView("Report")
        app.processEvents()
        QTest.qWait(100)
        items = list(visual_items(window.contentItem()))
        slicers = [
            item for item in items
            if "ListView" in item.metaObject().className()
            and item.property("visualTitle") == "Source"
        ]
        target = next(
            item for item in items
            if item.metaObject().className().startswith("ChartCard")
            and item.property("visualName") == "Target"
        )
        assert len(slicers) == 1
        assert all(item.property("count") == 2 for item in slicers)

        click = slicers[-1].mapToScene(QPointF(30.0, 11.0))
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(round(click.x()), round(click.y())),
        )
        QTest.qWait(100)
        app.processEvents()

        assert controller.selectedCrossFiltersForVisual("Source") == ["A"]
        assert [(item["label"], item["value"]) for item in target.property("series")] == [
            ("A", 20.0),
        ]
        assert all(item.property("activeFilters") == ["A"] for item in slicers)

        other_rows = [
            {"Category": "A", "Amount": "100"},
            {"Category": "B", "Amount": "200"},
        ]
        controller._table_catalog.append({
            "id": "OtherModel",
            "sourceId": "source-other",
            "loaded": True,
            "loadEnabled": True,
            "columnTypes": {"Amount": "whole_number"},
        })
        controller._loaded_candidates["source-other"] = SimpleNamespace(
            headers=["Category", "Amount"], rows=other_rows
        )
        visuals[1].update({
            "table_id": "OtherModel",
            "fields": {"X-axis": ["Category"], "Y-axis": ["Amount"]},
        })
        controller._project["model"]["relationships"] = [{
            "relationship_version": 1,
            "from_table_id": "SalesModel",
            "from_column": "MissingColumn",
            "to_table_id": "OtherModel",
            "to_column": "Category",
            "cardinality": "many_to_one",
            "is_active": True,
        }]
        controller._refresh_report()
        controller.stateChanged.emit()
        QTest.qWait(100)
        app.processEvents()

        items = list(visual_items(window.contentItem()))
        slicers = [
            item for item in items
            if "ListView" in item.metaObject().className()
            and item.property("visualTitle") == "Source"
        ]
        target = next(
            item for item in items
            if item.metaObject().className().startswith("ChartCard")
            and item.property("visualName") == "Target"
        )

        assert controller.selectedCrossFiltersForVisual("Source") == ["A"]
        assert [(item["label"], item["value"]) for item in target.property("series")] == []
        assert all(item.property("count") == 2 for item in slicers)

        click = slicers[-1].mapToScene(QPointF(30.0, 11.0))
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(round(click.x()), round(click.y())),
        )
        QTest.qWait(100)
        app.processEvents()

        assert controller.selectedCrossFiltersForVisual("Source") == []
        assert [(item["label"], item["value"]) for item in target.property("series")] == [
            ("B", 200.0),
            ("A", 100.0),
        ]
    finally:
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()
