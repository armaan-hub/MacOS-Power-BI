with open("analytics_studio/measures.py", "r") as f:
    text = f.read()

old_err = """            target_context, actual_column = targets_by_key[key]
            table_id = target_context["id"]
            if not target_context.get("filter_context_complete", False):
                if table_id in evaluation_filter_ids:
                    raise MeasureError(
                        "CALCULATE cannot replace a saved filter because its per-column "
                        "filter context is unavailable."
                    )"""

new_err = """            target_context, actual_column = targets_by_key[key]
            table_id = target_context["id"]
            if not target_context.get("filter_context_complete", False):
                is_date_replacement = extra_date_filters is not None and key in extra_date_filters
                if table_id in evaluation_filter_ids and not is_date_replacement:
                    raise MeasureError(
                        "CALCULATE cannot replace a saved filter because its per-column "
                        "filter context is unavailable."
                    )"""

text = text.replace(old_err, new_err)

with open("analytics_studio/measures.py", "w") as f:
    f.write(text)
