import sys

with open("analytics_studio/measures.py", "r", encoding="utf-8") as f:
    text = f.read()

bad = """        target_context["filter_column_rows"] = updated_column_rows
        target_context["filter_context_complete"] = True
        
        updated_filter_roots = evaluation_filter_ids | {table_id}"""

good = """        target_context["filter_column_rows"] = updated_column_rows
        target_context["filter_context_complete"] = True
        target_context["filter_rows"] = [
            row for row_index, row in enumerate(target_context["rows"])
            if all(row_index in indexes for indexes in updated_column_rows.values())
        ]
        
        updated_filter_roots = evaluation_filter_ids | {table_id}"""

if bad in text:
    text = text.replace(bad, good)
else:
    print("bad not found")

with open("analytics_studio/measures.py", "w", encoding="utf-8") as f:
    f.write(text)
