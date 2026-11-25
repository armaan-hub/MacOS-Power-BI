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
