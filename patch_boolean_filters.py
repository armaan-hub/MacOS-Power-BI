import re

with open("analytics_studio/measures.py", "r") as f:
    code = f.read()

old_sig = """    def evaluate_with_boolean_filters(
        expression: tuple[Any, ...],
        filter_arguments: tuple[tuple[Any, ...], ...],
    ) -> Decimal:
        nonlocal rows_by_table_id, context_sequence, current_context
        nonlocal evaluation_contexts_by_id, evaluation_filter_ids
        filters_by_column: dict[
            tuple[str, str], list[tuple[frozenset[int], bool, bool]]
        ] = {}
        targets_by_key: dict[
            tuple[str, str], tuple[dict[str, Any], str]
        ] = {}
        for filter_argument in filter_arguments:"""

new_sig = """    def evaluate_with_boolean_filters(
        expression: tuple[Any, ...],
        filter_arguments: tuple[tuple[Any, ...], ...],
        extra_date_filters: dict[tuple[str, str], tuple[dict, str, frozenset[int]]] | None = None,
    ) -> Decimal:
        nonlocal rows_by_table_id, context_sequence, current_context
        nonlocal evaluation_contexts_by_id, evaluation_filter_ids
        filters_by_column: dict[
            tuple[str, str], list[tuple[frozenset[int], bool, bool]]
        ] = {}
        targets_by_key: dict[
            tuple[str, str], tuple[dict[str, Any], str]
        ] = {}
        for key, (target_context, target_column, allowed_rows) in (extra_date_filters or {}).items():
            filters_by_column.setdefault(key, []).append((allowed_rows, False, False))
            targets_by_key[key] = (target_context, target_column)

        for filter_argument in filter_arguments:"""

code = code.replace(old_sig, new_sig)

if old_sig not in code and new_sig not in code:
    print("boolean_filters Patch failed")

with open("analytics_studio/measures.py", "w") as f:
    f.write(code)
