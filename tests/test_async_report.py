"""Tests for evaluating report visuals off the window thread with engine guard, cancellation, worker, and busy overlay."""

from __future__ import annotations

import os
import sys
import time
import unittest
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController, _format_report_number
from analytics_studio.file_import import ImportCandidate
from analytics_studio.measures import (
    MeasureError,
    MeasureEvaluationCancelled,
    evaluate_measures,
)


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class TestAsyncReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = _ensure_app()

    def setUp(self) -> None:
        self.controller = StudioController()
        # Seed test candidate table
        self.rows = [
            {"Region": "North", "Amount": "100", "Units": "2", "Date": "2026-01-15", "Cat": "A"},
            {"Region": "South", "Amount": "200", "Units": "4", "Date": "2026-01-20", "Cat": "B"},
            {"Region": "East", "Amount": "300", "Units": "6", "Date": "2026-02-10", "Cat": "A"},
            {"Region": "West", "Amount": "400", "Units": "8", "Date": "2026-02-25", "Cat": "B"},
        ]
        self.headers = ["Region", "Amount", "Units", "Date", "Cat"]
        candidate = ImportCandidate(
            "inline",
            list(self.headers),
            [dict(r) for r in self.rows],
            {},
            [],
            source_id="src_1",
        )
        self.controller._source_id = "src_1"
        self.controller._active_source_id = "src_1"
        self.controller._headers = list(self.headers)
        self.controller._rows = [dict(r) for r in self.rows]
        self.controller._loaded_candidates["src_1"] = candidate
        self.controller._table_catalog = [
            {
                "id": "src_1",
                "name": "Sales",
                "sourceId": "src_1",
                "loaded": True,
                "loadEnabled": True,
            }
        ]
        self.controller._project["model"]["tables"] = [
            {
                "id": "src_1",
                "name": "Sales",
                "columns": list(self.headers),
                "headers": list(self.headers),
                "sourceId": "src_1",
                "source_id": "src_1",
            }
        ]

    def test_worker_result_equals_sync_result_for_eight_formulas(self) -> None:
        formulas = [
            ("M_SUM", "SUM(Sales[Amount])"),
            ("M_SUMX", "SUMX(Sales, Sales[Amount] * Sales[Units])"),
            ("M_CALC_FILTER", "CALCULATE(SUM(Sales[Amount]), Sales[Region] = \"East\")"),
            ("M_DIVIDE", "DIVIDE(SUM(Sales[Amount]), SUM(Sales[Units]))"),
            ("M_RANKX", "RANKX(ALL(Sales), CALCULATE(SUM(Sales[Amount])))"),
            ("M_ADDCOL_SUMX", "SUMX(ADDCOLUMNS(Sales, \"DoubleAmt\", Sales[Amount] * 2), [DoubleAmt])"),
            ("M_CROSSJOIN_COUNT", "COUNTROWS(CROSSJOIN(SELECTCOLUMNS(Sales, \"R1\", Sales[Region]), SELECTCOLUMNS(Sales, \"R2\", Sales[Region])))"),
            ("M_DATE", "YEAR(DATE(2026, 11, 22))"),
        ]
        measure_defs = [{"name": name, "expression": expr} for name, expr in formulas]

        # Sync evaluation
        sync_result = evaluate_measures(
            measure_defs,
            self.rows,
            self.headers,
            "Sales",
        )

        # Worker / async evaluation via controller
        self.controller._project["model"]["measures"] = measure_defs
        self.controller._refresh_report_async()

        # Pump Qt event loop until task finishes
        deadline = time.perf_counter() + 5.0
        while self.controller.reportBusy and time.perf_counter() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

        self.assertFalse(self.controller.reportBusy)
        for name, _ in formulas:
            val = sync_result[name]
            expected_formatted = _format_report_number(val) if val is not None else "—"
            actual_value = self.controller._measure_values.get(name)
            self.assertIsNotNone(actual_value, f"Missing result for {name}")
            self.assertEqual(actual_value, expected_formatted, f"Worker formatted string for {name} ({actual_value}) != expected ({expected_formatted})")

    def test_responsiveness_slow_report_measure(self) -> None:
        # 160,000 rows for SUMX(T, CALCULATE(COUNTROWS(T)))
        large_rows = [{"val": str(i)} for i in range(160000)]
        large_headers = ["val"]
        slow_measure = [{"name": "Slow", "expression": "SUMX(Sales, CALCULATE(COUNTROWS(Sales)))"}]

        # Setup controller with large data
        self.controller._rows = large_rows
        self.controller._headers = large_headers
        candidate = ImportCandidate("inline", list(large_headers), [dict(r) for r in large_rows], {}, [], source_id="src_1")
        self.controller._loaded_candidates["src_1"] = candidate
        self.controller._project["model"]["tables"] = [
            {"id": "src_1", "name": "Sales", "columns": list(large_headers), "headers": list(large_headers), "sourceId": "src_1", "source_id": "src_1"}
        ]
        self.controller._table_catalog = [
            {"id": "src_1", "name": "Sales", "sourceId": "src_1", "loaded": True, "loadEnabled": True}
        ]
        self.controller._project["model"]["measures"] = slow_measure

        # Setup 20 ms QTimer to count ticks
        ticks = [0]
        timer = QTimer()
        timer.setInterval(20)
        timer.timeout.connect(lambda: ticks.__setitem__(0, ticks[0] + 1))
        timer.start()

        self.controller._refresh_report_async()
        self.assertTrue(self.controller.reportBusy)

        # Poll to a generous deadline (120 s) and assert on QTimer ticks during run
        deadline = time.perf_counter() + 120.0
        while self.controller.reportBusy and time.perf_counter() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

        timer.stop()
        self.assertFalse(self.controller.reportBusy)
        self.assertGreater(ticks[0], 10, f"Expected > 10 ticks while pumping events, got {ticks[0]}")

    def test_cancel_latency_sumx_and_crossjoin(self) -> None:
        # 1. SUMX formula cancel latency
        large_rows = [{"val": str(i)} for i in range(8000)]
        slow_measure = [{"name": "Slow", "expression": "SUMX(T, CALCULATE(COUNTROWS(T)))"}]

        import threading
        cancel_event = threading.Event()
        # Schedule cancel trigger after 50 ms
        trigger_timer = threading.Timer(0.05, cancel_event.set)
        t_start = time.perf_counter()
        trigger_timer.start()
        try:
            evaluate_measures(slow_measure, large_rows, ["val"], "T", cancel_check=cancel_event.is_set)
            self.fail("Expected MeasureEvaluationCancelled")
        except MeasureEvaluationCancelled:
            t_cancelled = time.perf_counter()
            cancel_latency = t_cancelled - (t_start + 0.05)
        finally:
            trigger_timer.cancel()

        print(f"Measured SUMX cancel latency: {cancel_latency:.4f}s")
        self.assertLess(cancel_latency, 2.0, f"SUMX cancel latency {cancel_latency:.4f}s exceeds 2.0s")

        # 2. CROSSJOIN / GROUPBY-heavy formula cancel latency
        cj_rows = [{"val": str(i % 10), "id": str(i)} for i in range(1000)]
        cj_measure = [{"name": "Heavy", "expression": "COUNTROWS(CROSSJOIN(T, T))"}]

        cancel_event_cj = threading.Event()
        trigger_timer_cj = threading.Timer(0.02, cancel_event_cj.set)
        t_start_cj = time.perf_counter()
        trigger_timer_cj.start()
        try:
            evaluate_measures(cj_measure, cj_rows, ["val", "id"], "T", cancel_check=cancel_event_cj.is_set)
            self.fail("Expected MeasureEvaluationCancelled")
        except MeasureEvaluationCancelled:
            t_cancelled_cj = time.perf_counter()
            cj_latency = t_cancelled_cj - (t_start_cj + 0.02)
        finally:
            trigger_timer_cj.cancel()

        print(f"Measured CROSSJOIN cancel latency: {cj_latency:.4f}s")
        self.assertLess(cj_latency, 5.0, f"CROSSJOIN cancel latency {cj_latency:.4f}s exceeds 5.0s")

    def test_stale_drop(self) -> None:
        # Start refresh A (slow measure), immediately start refresh B with a different filter
        page = self.controller._active_page()
        page["visuals"] = [
            {"title": "RegionSlicer", "type": "slicer", "table_id": "src_1", "fields": {"Fields": ["Region"]}},
            {"title": "Target", "type": "bar", "table_id": "src_1", "fields": {"X-axis": ["Region"], "Y-axis": ["Amount"]}},
        ]
        large_rows = [{"Region": "East", "Amount": "100", "Units": "1"}] * 4000 + [{"Region": "West", "Amount": "200", "Units": "2"}] * 4000
        self.controller._rows = large_rows
        self.controller._loaded_candidates["src_1"].rows = [dict(r) for r in large_rows]
        self.controller._headers = ["Region", "Amount", "Units"]
        self.controller._project["model"]["measures"] = [
            {"name": "TotalAmt", "expression": "SUM(Sales[Amount])"},
            {"name": "Revenue", "expression": "SUM(Sales[Amount])"},
        ]

        # Trigger A
        self.controller._cross_filters = {"RegionSlicer": ["East"]}
        self.controller._refresh_report_async()
        req_id_a = self.controller._report_request_id

        # Immediately trigger B
        self.controller._cross_filters = {"RegionSlicer": ["West"]}
        self.controller._refresh_report_async()
        req_id_b = self.controller._report_request_id
        self.assertGreater(req_id_b, req_id_a)

        # Wait for completion
        deadline = time.perf_counter() + 15.0
        while self.controller.reportBusy and time.perf_counter() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

        self.assertFalse(self.controller.reportBusy)
        # Ensure only B's request ID was accepted and applied
        self.assertEqual(self.controller._report_request_id, req_id_b)
        # Assert applied _measure_values and _kpis match filter B (West: 800,000) and not filter A (East: 400,000)
        self.assertEqual(self.controller._measure_values.get("TotalAmt"), "800,000")
        self.assertEqual(self.controller._measure_values.get("Revenue"), "800,000")
        self.assertEqual(self.controller._kpis.get("Revenue"), "800,000")
        self.assertNotEqual(self.controller._measure_values.get("TotalAmt"), "400,000")

    def test_stale_async_result_dropped_after_sync_refresh(self) -> None:
        # Reproduce item 1: async refresh started with slow measure, then sync refresh with other measures,
        # then event loop pumps. Async completion must NOT overwrite sync values.
        large_rows = [{"Region": "East", "Amount": "100", "Units": "1"}] * 4000
        self.controller._source_id = "src_1"
        self.controller._rows = large_rows
        self.controller._headers = ["Region", "Amount", "Units"]
        candidate = ImportCandidate("inline", ["Region", "Amount", "Units"], [dict(r) for r in large_rows], {}, [], source_id="src_1")
        self.controller._loaded_candidates["src_1"] = candidate
        self.controller._project["model"]["tables"] = [
            {"id": "src_1", "name": "Sales", "columns": ["Region", "Amount", "Units"], "headers": ["Region", "Amount", "Units"], "sourceId": "src_1", "source_id": "src_1"}
        ]
        self.controller._table_catalog = [
            {"id": "src_1", "name": "Sales", "sourceId": "src_1", "loaded": True, "loadEnabled": True}
        ]
        self.controller._project["model"]["measures"] = [
            {"name": "A", "expression": "SUMX(Sales, CALCULATE(COUNTROWS(Sales)))"}
        ]

        # Trigger async refresh for measure A
        self.controller._refresh_report_async()
        self.assertTrue(self.controller.reportBusy)

        # Immediately run synchronous refresh with different measures (e.g. measure B)
        self.controller._project["model"]["measures"] = [
            {"name": "B", "expression": "20"}
        ]
        self.controller._refresh_report()
        self.assertEqual(self.controller._measure_values, {"B": "20"})

        # Pump events for the pool to finish queued worker task
        deadline = time.perf_counter() + 10.0
        while self.controller.reportBusy and time.perf_counter() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        for _ in range(50):
            self.app.processEvents()
            time.sleep(0.01)

        # Stale worker task must NOT have overwritten sync result
        self.assertEqual(self.controller._measure_values, {"B": "20"})
        self.assertNotIn("A", self.controller._measure_values)

    def test_sync_create_measure_during_active_worker_cancels_and_succeeds(self) -> None:
        large_rows = [{"Region": "East", "Amount": "100", "Units": "1"}] * 4000
        self.controller._rows = large_rows
        self.controller._headers = ["Region", "Amount", "Units"]
        self.controller._project["model"]["measures"] = [
            {"name": "SlowM", "expression": "SUMX(Sales, CALCULATE(COUNTROWS(Sales)))"}
        ]

        # Start async worker
        self.controller._refresh_report_async()
        self.assertTrue(self.controller.reportBusy)

        # Call sync create_measure
        created = self.controller.create_measure("NewM", "SUM(Sales[Amount])", home_table_id="src_1")
        self.assertTrue(created)
        self.assertIn("NewM", self.controller._measure_values)

    def test_deep_recursion_depth_60(self) -> None:
        expr = "1"
        for _ in range(60):
            expr = f"({expr} + 1)"
        deep_measure = [{"name": "Deep60", "expression": expr}]
        self.controller._project["model"]["measures"] = deep_measure

        self.controller._refresh_report_async()
        deadline = time.perf_counter() + 5.0
        while self.controller.reportBusy and time.perf_counter() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

        self.assertFalse(self.controller.reportBusy)
        self.assertEqual(self.controller._measure_values.get("Deep60"), "61")

    def test_report_busy_property_toggles(self) -> None:
        busy_states: list[bool] = []
        self.controller.reportBusyChanged.connect(busy_states.append)

        large_rows = [{"val": str(i)} for i in range(4000)]
        self.controller._rows = large_rows
        self.controller._headers = ["val"]
        self.controller._project["model"]["measures"] = [
            {"name": "Slow", "expression": "SUMX(Sales, CALCULATE(COUNTROWS(Sales)))"}
        ]

        self.assertFalse(self.controller.reportBusy)
        self.controller._refresh_report_async()
        self.assertTrue(self.controller.reportBusy)

        deadline = time.perf_counter() + 10.0
        while self.controller.reportBusy and time.perf_counter() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

        self.assertFalse(self.controller.reportBusy)
        self.assertIn(True, busy_states)
        self.assertEqual(busy_states[-1], False)

    def test_interactive_filter_slots_async(self) -> None:
        large_rows = [
            {"Region": "North" if i % 2 == 0 else "South", "Amount": "10", "Units": "1", "Date": "2026-01-15", "Cat": "A"}
            for i in range(4000)
        ]
        candidate = ImportCandidate(
            "inline",
            list(self.headers),
            [dict(r) for r in large_rows],
            {},
            [],
            source_id="src_1",
        )
        self.controller._rows = [dict(r) for r in large_rows]
        self.controller._loaded_candidates["src_1"] = candidate
        self.controller._project["model"]["measures"] = [
            {"name": "SlowCount", "expression": "SUMX(Sales, CALCULATE(COUNTROWS(Sales)))"}
        ]
        self.controller._refresh_report()

        # 1. Test setRegionFilterInteractive
        sync_controller = StudioController()
        sync_controller._source_id = "src_1"
        sync_controller._active_source_id = "src_1"
        sync_controller._headers = list(self.headers)
        sync_controller._rows = [dict(r) for r in large_rows]
        sync_controller._loaded_candidates["src_1"] = ImportCandidate(
            "inline", list(self.headers), [dict(r) for r in large_rows], {}, [], source_id="src_1"
        )
        sync_controller._table_catalog = list(self.controller._table_catalog)
        sync_controller._project = {
            "model": {
                "tables": list(self.controller._project["model"]["tables"]),
                "measures": [{"name": "SlowCount", "expression": "SUMX(Sales, CALCULATE(COUNTROWS(Sales)))"}],
                "relationships": [],
            },
            "report": {"pages": [{"id": "page_1", "name": "Page 1", "filters": [], "visual_filters": []}]},
        }
        sync_controller._refresh_report()
        sync_controller.setRegionFilter("North")
        expected_kpis = dict(sync_controller._kpis)
        expected_measures = dict(sync_controller._measure_values)

        t0 = time.perf_counter()
        self.controller.setRegionFilterInteractive("North")
        t_call = time.perf_counter() - t0
        self.assertLess(t_call, 0.5, f"setRegionFilterInteractive blocked for {t_call:.3f}s")
        self.assertTrue(self.controller.reportBusy)

        deadline = time.perf_counter() + 10.0
        while self.controller.reportBusy and time.perf_counter() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

        self.assertFalse(self.controller.reportBusy)
        self.assertEqual(self.controller._kpis, expected_kpis)
        self.assertEqual(self.controller._measure_values, expected_measures)

        # 2. Test addReportFilterRuleInteractive
        sync_controller.addReportFilterRule("src_1", "Region", "equals", "North", "", "", "and")
        expected_kpis = dict(sync_controller._kpis)
        expected_measures = dict(sync_controller._measure_values)

        t0 = time.perf_counter()
        ret = self.controller.addReportFilterRuleInteractive("src_1", "Region", "equals", "North", "", "", "and")
        t_call = time.perf_counter() - t0
        self.assertTrue(ret)
        self.assertLess(t_call, 0.5, f"addReportFilterRuleInteractive blocked for {t_call:.3f}s")
        self.assertTrue(self.controller.reportBusy)

        deadline = time.perf_counter() + 10.0
        while self.controller.reportBusy and time.perf_counter() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

        self.assertFalse(self.controller.reportBusy)
        self.assertEqual(self.controller._kpis, expected_kpis)
        self.assertEqual(self.controller._measure_values, expected_measures)

        # 3. Test addPageFilterRuleInteractive
        sync_controller.addPageFilterRule("src_1", "Region", "equals", "North", "", "", "and")
        expected_kpis = dict(sync_controller._kpis)
        expected_measures = dict(sync_controller._measure_values)

        t0 = time.perf_counter()
        ret = self.controller.addPageFilterRuleInteractive("src_1", "Region", "equals", "North", "", "", "and")
        t_call = time.perf_counter() - t0
        self.assertTrue(ret)
        self.assertLess(t_call, 0.5, f"addPageFilterRuleInteractive blocked for {t_call:.3f}s")
        self.assertTrue(self.controller.reportBusy)

        deadline = time.perf_counter() + 10.0
        while self.controller.reportBusy and time.perf_counter() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

        self.assertFalse(self.controller.reportBusy)
        self.assertEqual(self.controller._kpis, expected_kpis)
        self.assertEqual(self.controller._measure_values, expected_measures)

        # 4. Test addVisualFilterRuleInteractive
        page = self.controller._active_page()
        page["visuals"] = [{"id": "v1", "title": "Region revenue", "type": "bar", "table_id": "src_1", "fields": {}}]
        sync_page = sync_controller._active_page()
        if sync_page is None:
            sync_page = sync_controller._project["report"]["pages"][0]
            sync_controller._active_page_id = sync_page.get("id")
        sync_page["visuals"] = [{"id": "v1", "title": "Region revenue", "type": "bar", "table_id": "src_1", "fields": {}}]

        sync_controller.addVisualFilterRule("Region revenue", "src_1", "Region", "equals", "North", "", "", "and")
        expected_kpis = dict(sync_controller._kpis)
        expected_measures = dict(sync_controller._measure_values)

        t0 = time.perf_counter()
        ret = self.controller.addVisualFilterRuleInteractive("Region revenue", "src_1", "Region", "equals", "North", "", "", "and")
        t_call = time.perf_counter() - t0
        self.assertTrue(ret)
        self.assertLess(t_call, 0.5, f"addVisualFilterRuleInteractive blocked for {t_call:.3f}s")
        self.assertTrue(self.controller.reportBusy)

        deadline = time.perf_counter() + 10.0
        while self.controller.reportBusy and time.perf_counter() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

        self.assertFalse(self.controller.reportBusy)
        self.assertEqual(self.controller._kpis, expected_kpis)
        self.assertEqual(self.controller._measure_values, expected_measures)

        # 5. Test removeReportFilterInteractive
        sync_controller.removeReportFilter(0)
        expected_kpis = dict(sync_controller._kpis)
        expected_measures = dict(sync_controller._measure_values)

        t0 = time.perf_counter()
        ret = self.controller.removeReportFilterInteractive(0)
        t_call = time.perf_counter() - t0
        self.assertTrue(ret)
        self.assertLess(t_call, 0.5, f"removeReportFilterInteractive blocked for {t_call:.3f}s")
        self.assertTrue(self.controller.reportBusy)

        deadline = time.perf_counter() + 10.0
        while self.controller.reportBusy and time.perf_counter() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

        self.assertFalse(self.controller.reportBusy)
        self.assertEqual(self.controller._kpis, expected_kpis)
        self.assertEqual(self.controller._measure_values, expected_measures)


if __name__ == "__main__":
    unittest.main()
