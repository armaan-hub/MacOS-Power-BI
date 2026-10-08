import sys

with open("analytics_studio/measures.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

new_func = """
    def evaluate_with_context_transition(
        expression_node: tuple[Any, ...],
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
            return evaluate(expression_node)
        finally:
            rows_by_table_id = previous_rows
            current_context = previous_context
            evaluation_contexts_by_id = previous_contexts
            evaluation_filter_ids = previous_filter_ids
"""

insert_line = 3369

lines.insert(insert_line, new_func + "\n")

with open("analytics_studio/measures.py", "w", encoding="utf-8") as f:
    f.writelines(lines)
