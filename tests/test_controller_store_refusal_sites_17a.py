"""Classification test that makes refusal sites and gaps visible (Stage B4b task 17a Item 3).

AST-only analysis of analytics_studio/controller.py to verify all refusal and store-checking
functions are explicitly classified into 'refuse', 'housekeeping', or 'static'.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Mapping of function name -> class ("refuse", "housekeeping", "static")
# Built from AST scan of calls to self._store_tables_loaded() and
# self._large_data_refusal(...) / self._notice_silent_refusal(...).
CLASSIFIED: dict[str, str] = {
    # Housekeeping: closing or cleaning up project store on large import
    "_import_large": "housekeeping",
    "_on_large_import_done": "housekeeping",
    # Static: classmethod / staticmethod / helper calling refusal directly without self._store_tables_loaded
    "_notice_silent_refusal": "static",
    "_query_candidate": "static",
    # Refusal: standard user-facing or internal entry-point refusals
    "_add_report_filter": "refuse",
    "_build_preview_inputs": "refuse",
    "_commit_odata_import": "refuse",
    "_commit_sql_server_import": "refuse",
    "_commit_transform_session": "refuse",
    "_commit_transform_steps": "refuse",
    "_commit_web_import": "refuse",
    "_create_saved_query": "refuse",
    "_generate_dynamic_visual_series": "refuse",
    "_measure_dialog": "refuse",
    "_measure_table_context": "refuse",
    "_plan_calculated_column_change": "refuse",
    "_preview_measure_expression": "refuse",
    "_preview_measure_expression_async": "refuse",
    "_refresh_report": "refuse",
    "_refresh_report_async": "refuse",
    "_refresh_transform_query_preview": "refuse",
    "_report_filter_context": "refuse",
    "_report_view_refusal_for_user_action": "refuse",
    "_run_relationship_dialog": "refuse",
    "_validate_loaded_relationship_candidates": "refuse",
    "_validate_model_column_sort_rule": "refuse",
    "_validate_relationship_candidate": "refuse",
    "add_field_to_well": "refuse",
    "append_queries_dialog": "refuse",
    "calculated_column_dialog": "refuse",
    "calculated_table_dialog": "refuse",
    "calendar_table_dialog": "refuse",
    "connectDataSource": "refuse",
    "create_measure": "refuse",
    "deleteMeasure": "refuse",
    "deleteRelationship": "refuse",
    "editMeasure": "refuse",
    "editRelationship": "refuse",
    "enter_data_dialog": "refuse",
    "import_csv_path": "refuse",
    "import_data_dialog": "refuse",
    "import_data_path": "refuse",
    "import_excel_path": "refuse",
    "import_folder_dialog": "refuse",
    "import_folder_path": "refuse",
    "load_sample_data": "refuse",
    "mark_date_table_dialog": "refuse",
    "merge_queries_dialog": "refuse",
    "openRecentSource": "refuse",
    "pageFilterValues": "refuse",
    "power_query_m_editor_dialog": "refuse",
    "refresh_all_sources": "refuse",
    "refresh_source": "refuse",
    "regions": "refuse",
    "remove_measure": "refuse",
    "save_calculated_column": "refuse",
    "searchPageFilterValues": "refuse",
    "setColumnType": "refuse",
    "set_model_column_sort_by": "refuse",
    "set_model_key_column": "refuse",
    "transform_data_dialog": "refuse",
    "update_measure": "refuse",
    "validate_calculated_column": "refuse",
    "visualCardData": "refuse",
    "visualGaugeData": "refuse",
    "visualKpiData": "refuse",
    "visualMapData": "refuse",
    "visualMatrixData": "refuse",
    "visualScatterData": "refuse",
    "visualShapeMapData": "refuse",
    "visualTableData": "refuse",
}


def _collect_call_sites(controller_path: Path) -> set[str]:
    src = controller_path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    target_attrs = {
        "_store_tables_loaded",
        "_large_data_refusal",
        "_notice_silent_refusal",
    }

    class RefusalVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []
            self.found_functions: set[str] = set()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            attr = None
            if isinstance(func, ast.Attribute):
                attr = func.attr
            elif isinstance(func, ast.Name):
                attr = func.id
            if attr in target_attrs:
                enclosing = self.stack[-1] if self.stack else "<module>"
                self.found_functions.add(enclosing)
            self.generic_visit(node)

    visitor = RefusalVisitor()
    visitor.visit(tree)
    return visitor.found_functions


def test_all_refusal_and_store_sites_are_classified() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    controller_path = repo_root / "analytics_studio" / "controller.py"
    assert controller_path.is_file(), f"controller.py not found at {controller_path}"

    found = _collect_call_sites(controller_path)
    classified_names = set(CLASSIFIED.keys())

    unclassified = sorted(found - classified_names)
    assert not unclassified, (
        f"Found {len(unclassified)} unclassified function(s) calling refusal or store check: {unclassified}"
    )

    stale = sorted(classified_names - found)
    assert not stale, (
        f"Found {len(stale)} classified function(s) that no longer call refusal or store check: {stale}"
    )

    valid_classes = {"refuse", "housekeeping", "static"}
    invalid_classes = {name: cls for name, cls in CLASSIFIED.items() if cls not in valid_classes}
    assert not invalid_classes, f"Found invalid class labels in CLASSIFIED: {invalid_classes}"


# Import entry points audit mapping: function name -> (classification, reason)
# Classification must be "guarded", "protected-by-callers", or "exempt"
IMPORT_ENTRY_POINTS: dict[str, tuple[str, str]] = {
    "openRecentSource": ("guarded", "Guards _store_tables_loaded before dispatching to file or folder import"),
    "import_data_dialog": ("guarded", "Guards _store_tables_loaded before invoking file preview dialog"),
    "import_folder_dialog": ("guarded", "Guards _store_tables_loaded before invoking directory chooser dialog"),
    "import_folder_path": ("guarded", "Guards _store_tables_loaded before delegating to _import_folder_path"),
    "import_csv_path": ("guarded", "Guards _store_tables_loaded before delegating to _import_file_path"),
    "import_excel_path": ("guarded", "Guards _store_tables_loaded before delegating to _import_file_path"),
    "import_data_path": ("guarded", "Guards _store_tables_loaded before delegating to _import_file_path"),
    "enter_data_dialog": ("guarded", "Guards _store_tables_loaded before constructing dialog or committing inline"),
    "load_sample_data": ("guarded", "Guards _store_tables_loaded before committing sample data inline"),
    "_import_folder_path": ("protected-by-callers", "Private helper called only from guarded import_folder_path and import_folder_dialog"),
    "_import_file_path": ("protected-by-callers", "Private helper called only from guarded path import functions and dialogs"),
}

EXPECTED_CALL_SITE_COUNTS: dict[str, dict[str, int]] = {
    "_add_report_filter": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "_build_preview_inputs": {"_store_tables_loaded": 1, "_large_data_refusal": 2},
    "_commit_odata_import": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "_commit_sql_server_import": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "_commit_transform_session": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "_commit_transform_steps": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "_commit_web_import": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "_create_saved_query": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "_generate_dynamic_visual_series": {"_store_tables_loaded": 1, "_large_data_refusal": 0},
    "_import_large": {"_store_tables_loaded": 2, "_large_data_refusal": 1},
    "_measure_dialog": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "_measure_table_context": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "_notice_silent_refusal": {"_store_tables_loaded": 0, "_large_data_refusal": 1},
    "_on_large_import_done": {"_store_tables_loaded": 1, "_large_data_refusal": 0},
    "_plan_calculated_column_change": {"_store_tables_loaded": 1, "_large_data_refusal": 2},
    "_preview_measure_expression": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "_preview_measure_expression_async": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "_query_candidate": {"_store_tables_loaded": 0, "_large_data_refusal": 1},
    "_refresh_report": {"_store_tables_loaded": 1, "_large_data_refusal": 2},
    "_refresh_report_async": {"_store_tables_loaded": 1, "_large_data_refusal": 2},
    "_refresh_transform_query_preview": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "_report_filter_context": {"_store_tables_loaded": 1, "_large_data_refusal": 0},
    "_report_view_refusal_for_user_action": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "_run_relationship_dialog": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "_validate_loaded_relationship_candidates": {"_store_tables_loaded": 1, "_large_data_refusal": 0},
    "_validate_model_column_sort_rule": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "_validate_relationship_candidate": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "add_field_to_well": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "append_queries_dialog": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "calculated_column_dialog": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "calculated_table_dialog": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "calendar_table_dialog": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "connectDataSource": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "create_measure": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "deleteMeasure": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "deleteRelationship": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "editMeasure": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "editRelationship": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "enter_data_dialog": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "import_csv_path": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "import_data_dialog": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "import_data_path": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "import_excel_path": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "import_folder_dialog": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "import_folder_path": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "load_sample_data": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "mark_date_table_dialog": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "merge_queries_dialog": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "openRecentSource": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "pageFilterValues": {"_store_tables_loaded": 1, "_large_data_refusal": 0},
    "power_query_m_editor_dialog": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "refresh_all_sources": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "refresh_source": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "regions": {"_store_tables_loaded": 1, "_large_data_refusal": 0},
    "remove_measure": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "save_calculated_column": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "searchPageFilterValues": {"_store_tables_loaded": 1, "_large_data_refusal": 0},
    "setColumnType": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "set_model_column_sort_by": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "set_model_key_column": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "transform_data_dialog": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "update_measure": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "validate_calculated_column": {"_store_tables_loaded": 1, "_large_data_refusal": 1},
    "visualCardData": {"_store_tables_loaded": 1, "_large_data_refusal": 0},
    "visualGaugeData": {"_store_tables_loaded": 1, "_large_data_refusal": 0},
    "visualKpiData": {"_store_tables_loaded": 1, "_large_data_refusal": 0},
    "visualMapData": {"_store_tables_loaded": 1, "_large_data_refusal": 0},
    "visualMatrixData": {"_store_tables_loaded": 1, "_large_data_refusal": 0},
    "visualScatterData": {"_store_tables_loaded": 1, "_large_data_refusal": 0},
    "visualShapeMapData": {"_store_tables_loaded": 1, "_large_data_refusal": 0},
    "visualTableData": {"_store_tables_loaded": 1, "_large_data_refusal": 0},
}


def test_import_entry_points_are_classified_and_guarded() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    controller_path = repo_root / "analytics_studio" / "controller.py"
    src = controller_path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    target_calls = {
        "_import_file_path",
        "_commit_import",
        "_commit_inline",
        "_import_folder_path",
        "_import_large",
    }

    class CallerVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []
            # fn -> list of (lineno, call_attr)
            self.all_calls: dict[str, list[tuple[int, str]]] = {}

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node: ast.Call) -> None:
            attr = None
            if isinstance(node.func, ast.Attribute) and getattr(node.func.value, "id", None) == "self":
                attr = node.func.attr
            elif isinstance(node.func, ast.Name):
                attr = node.func.id
            if self.stack and attr is not None:
                self.all_calls.setdefault(self.stack[-1], []).append((node.lineno, attr))
            self.generic_visit(node)

    visitor = CallerVisitor()
    visitor.visit(tree)

    # Functions calling any of target_calls
    callers = {
        fn: calls
        for fn, calls in visitor.all_calls.items()
        if any(attr in target_calls for _, attr in calls)
    }

    # 1. Unlisted caller fails
    unlisted = sorted(set(callers.keys()) - set(IMPORT_ENTRY_POINTS.keys()))
    assert not unlisted, f"Found unlisted import entry point(s) calling downstream import: {unlisted}"

    stale = sorted(set(IMPORT_ENTRY_POINTS.keys()) - set(callers.keys()))
    assert not stale, f"Found stale import entry point(s) in IMPORT_ENTRY_POINTS: {stale}"

    # 2. Check guarded functions have _store_tables_loaded before first target call in source order
    valid_classes = {"guarded", "protected-by-callers", "exempt"}
    for fn, (cls, reason) in IMPORT_ENTRY_POINTS.items():
        assert cls in valid_classes, f"Invalid class {cls!r} for {fn}"
        assert reason and isinstance(reason, str), f"Missing reason for {fn}"
        calls = callers[fn]
        first_target_line = min(line for line, attr in calls if attr in target_calls)
        guard_lines = [line for line, attr in calls if attr == "_store_tables_loaded"]

        if cls == "guarded":
            has_guard_before = any(line < first_target_line for line in guard_lines)
            assert has_guard_before, (
                f"Function {fn!r} is classified 'guarded' but has no self._store_tables_loaded() "
                f"before first import call at line {first_target_line}"
            )


def test_call_site_counts_and_large_import_refusal_split() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    controller_path = repo_root / "analytics_studio" / "controller.py"
    src = controller_path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    class CallSiteCounter(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []
            self.counts: dict[str, dict[str, int]] = {}
            self.import_large_refusal_args: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node: ast.Call) -> None:
            attr = None
            if isinstance(node.func, ast.Attribute):
                attr = node.func.attr
            elif isinstance(node.func, ast.Name):
                attr = node.func.id
            if self.stack and attr in ("_store_tables_loaded", "_large_data_refusal"):
                fn = self.stack[-1]
                self.counts.setdefault(fn, {"_store_tables_loaded": 0, "_large_data_refusal": 0})
                self.counts[fn][attr] += 1
                if fn == "_import_large" and attr == "_large_data_refusal":
                    arg = getattr(node.args[0], "value", None) or getattr(node.args[0], "s", None) if node.args else None
                    if arg is not None:
                        self.import_large_refusal_args.append(str(arg))
            self.generic_visit(node)

    counter = CallSiteCounter()
    counter.visit(tree)

    # Assert exact per-function call counts match EXPECTED_CALL_SITE_COUNTS
    assert set(counter.counts.keys()) == set(EXPECTED_CALL_SITE_COUNTS.keys())
    for fn, expected in EXPECTED_CALL_SITE_COUNTS.items():
        actual = counter.counts.get(fn, {"_store_tables_loaded": 0, "_large_data_refusal": 0})
        # Check actual has at least the expected counts (or exact match, allowing extra guards as long as expected are present)
        assert actual["_large_data_refusal"] == expected["_large_data_refusal"], (
            f"{fn} expected {expected['_large_data_refusal']} _large_data_refusal calls, got {actual['_large_data_refusal']}"
        )
        assert actual["_store_tables_loaded"] >= expected["_store_tables_loaded"], (
            f"{fn} expected at least {expected['_store_tables_loaded']} _store_tables_loaded calls, got {actual['_store_tables_loaded']}"
        )

    # Split _import_large assertion: must contain a self._large_data_refusal("Import") call
    assert "Import" in counter.import_large_refusal_args, (
        f"_import_large must contain self._large_data_refusal('Import'), found {counter.import_large_refusal_args}"
    )
