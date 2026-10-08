import sys

with open("analytics_studio/measures.py", "r", encoding="utf-8") as f:
    text = f.read()

bad_call = """        filtered_rows_by_id = dict(rows_by_table_id)
        filtered_rows_by_id[table_id] = propagate_relationship_filters(
            updated_by_id, relationships, updated_filter_roots, False, None
        )"""

good_call = """        updated_contexts = list(updated_by_id.values())
        try:
            filtered_rows_by_id = propagate_relationship_filters(
                updated_contexts,
                relationship_definitions,
                updated_filter_roots,
            )
        except RelationshipError as exc:
            raise MeasureError(str(exc)) from exc"""

if bad_call in text:
    text = text.replace(bad_call, good_call)

with open("analytics_studio/measures.py", "w", encoding="utf-8") as f:
    f.write(text)
