import re

with open("analytics_studio/measures.py", "r", encoding="utf-8") as f:
    code = f.read()

transition_code = """
    def evaluate_with_context_transition(
        node: tuple[Any, ...],
        iterated_table: dict[str, Any],
        row: dict[str, Any],
    ) -> Decimal | bool | None:
        '''Create a filter context mimicking the current row context and evaluate.'''
        nonlocal rows_by_table_id, context_sequence, current_context
        nonlocal evaluation_contexts_by_id, evaluation_filter_ids

        table_id = iterated_table["id"]
        allowed_rows = frozenset(
            row_index
            for row_index, iterate_row in enumerate(iterated_table["rows"], 1)
            if all(
                str(iterate_row.get(header, "")).strip() == str(row.get(header, "")).strip()
                for header in iterated_table["headers"]
            )
        )
        
        updated_by_id = {key: dict(value) for key, value in evaluation_contexts_by_id.items()}
        target_context = updated_by_id.get(table_id)
        if target_context is None:
            target_context = dict(iterated_table)
            updated_by_id[table_id] = target_context
            
        updated_column_rows = dict(target_context.get("filter_column_rows", {}))
        for header in iterated_table["headers"]:
            updated_column_rows[header] = allowed_rows
            
        target_context["filter_column_rows"] = updated_column_rows
        target_context["filter_context_complete"] = True
        
        updated_filter_roots = evaluation_filter_ids | {table_id}
        
        filtered_rows_by_id = dict(rows_by_table_id)
        filtered_rows_by_id[table_id] = propagate_relationship_filters(
            updated_by_id, relationships, updated_filter_roots, False, None
        )

        previous_rows = rows_by_table_id
        previous_context = current_context
        previous_contexts = evaluation_contexts_by_id
        previous_filter_ids = evaluation_filter_ids
        context_sequence += 1
        current_context = context_sequence
        evaluation_contexts_by_id = updated_by_id
        evaluation_filter_ids = updated_filter_roots
        rows_by_table_id = filtered_rows_by_id
        try:
            return evaluate(node)
        finally:
            rows_by_table_id = previous_rows
            current_context = previous_context
            evaluation_contexts_by_id = previous_contexts
            evaluation_filter_ids = previous_filter_ids
"""

old_evaluate = """    def evaluate(
        node: tuple[Any, ...],
        row_context: tuple[dict[str, Any], dict[str, Any], int] | None = None,
    ) -> Decimal | bool | None:
        nonlocal rows_by_table_id, context_sequence, current_context
        kind = node[0]
        if kind == "number":
            return node[1]
        if kind == "boolean":
            return node[1]
        if kind == "table":
            raise MeasureError("A table name is only supported as the first argument to SUMX or AVERAGEX.")
        if kind == "reference":
            _, table, name = node
            measure_key = name.casefold()
            if measure_key in by_name:
                if row_context is not None:
                    raise MeasureError(
                        "Measure references inside SUMX/AVERAGEX need context transition, which is not supported."
                    )
                return resolve(measure_key)"""

new_evaluate = """    def evaluate(
        node: tuple[Any, ...],
        row_context: tuple[dict[str, Any], dict[str, Any], int] | None = None,
    ) -> Decimal | bool | None:
        nonlocal rows_by_table_id, context_sequence, current_context
        kind = node[0]
        if kind == "number":
            return node[1]
        if kind == "boolean":
            return node[1]
        if kind == "table":
            raise MeasureError("A table name is only supported as the first argument to SUMX or AVERAGEX.")
        if kind == "reference":
            _, table, name = node
            measure_key = name.casefold()
            if measure_key in by_name:
                if row_context is not None:
                    return evaluate_with_context_transition(node, row_context[0], row_context[1])
                return resolve(measure_key)"""

old_calc = """        if function == "CALCULATE":
            if row_context is not None:
                raise MeasureError("CALCULATE inside SUMX/AVERAGEX needs context transition, which is not supported.")"""

new_calc = """        if function == "CALCULATE":
            if row_context is not None:
                return evaluate_with_context_transition(node, row_context[0], row_context[1])"""

code = code.replace("    def evaluate(", transition_code + "\n    def evaluate(", 1)
code = code.replace(old_evaluate, new_evaluate)
code = code.replace(old_calc, new_calc)

with open("analytics_studio/measures.py", "w", encoding="utf-8") as f:
    f.write(code)
