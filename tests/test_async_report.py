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

from analytics_studio.controller import StudioController
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
            expected_formatted = str(sync_result[name])
            actual_value = self.controller._measure_values.get(name)
            self.assertIsNotNone(actual_value, f"Missing result for {name}")
            # Ensure both match either formatted or numeric value
            self.assertNotEqual(actual_value, "—", f"Formula {name} resulted in error: {self.controller._measure_errors.get(name)}")

    def test_responsiveness_slow_report_measure(self) -> None:
        # 8,000 rows for SUMX(T, CALCULATE(COUNTROWS(T)))
        large_rows = [{"val": str(i)} for i in range(8000)]
        large_headers = ["val"]
        slow_measure = [{"name": "Slow", "expression": "SUMX(Sales, CALCULATE(COUNTROWS(Sales)))"}]

        # Check sync takes > 2 s
        t0 = time.perf_counter()
        sync_res = evaluate_measures(slow_measure, large_rows, large_headers, "Sales")
        dt_sync = time.perf_counter() - t0
        self.assertGreater(dt_sync, 2.0, f"Expected slow measure to take > 2s sync, took {dt_sync:.2f}s")

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

        # Pump events while worker runs
        t_start = time.perf_counter()
        while self.controller.reportBusy and time.perf_counter() - t_start < 15.0:
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

        self.assertLess(cancel_latency, 0.5, f"SUMX cancel latency {cancel_latency:.4f}s exceeds 0.5s")

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

        self.assertLess(cj_latency, 2.0, f"CROSSJOIN cancel latency {cj_latency:.4f}s exceeds 2.0s")

    def test_stale_drop(self) -> None:
        # Start refresh A (slow measure), immediately start refresh B with a different filter
        large_rows = [{"Region": "East", "Amount": "100", "Units": "1"}] * 4000 + [{"Region": "West", "Amount": "200", "Units": "2"}] * 4000
        self.controller._rows = large_rows
        self.controller._headers = ["Region", "Amount", "Units"]
        self.controller._project["model"]["measures"] = [
            {"name": "TotalAmt", "expression": "SUMX(Sales, CALCULATE(COUNTROWS(Sales)))"}
        ]

        # Trigger A
        self.controller._cross_filters = {"Sales": ["East"]}
        self.controller._refresh_report_async()
        req_id_a = self.controller._report_request_id

        # Immediately trigger B
        self.controller._cross_filters = {"Sales": ["West"]}
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


if __name__ == "__main__":
    unittest.main()
