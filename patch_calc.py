import re

with open("analytics_studio/measures.py", "r") as f:
    text = f.read()

start_marker = """            if not (
                len(arguments) == 2
                and arguments[1][0] == "call"
                and arguments[1][1] in _TIME_FILTER_FUNCTIONS
            ):"""

end_marker = """            return evaluate_with_date_values(
                arguments[0], date_table, actual_date_column, shifted_dates
            )"""

start_idx = text.find(start_marker)
end_idx = text.find(end_marker, start_idx) + len(end_marker)

if start_idx == -1 or end_idx == -1:
    print("markers not found")
    import sys; sys.exit(1)

old_block = text[start_idx:end_idx]
inner_text = text[text.find('            date_reference = date_filter_arguments[0]'):text.find('            return evaluate_with_date_values(')]

# Indent inner text
inner_indented = '\n'.join('    ' + line if line.strip() else line for line in inner_text.split('\n'))

new_top = """            time_filters = [
                arg for arg in arguments[1:]
                if arg[0] == "call" and arg[1] in _TIME_FILTER_FUNCTIONS
            ]
            boolean_filters = tuple(
                arg for arg in arguments[1:]
                if not (arg[0] == "call" and arg[1] in _TIME_FILTER_FUNCTIONS)
            )
            if not time_filters:
                return evaluate_with_boolean_filters(
                    arguments[0], boolean_filters
                )

            extra_date_filters = {}
            for date_filter in time_filters:
                date_filter_function = date_filter[1]
                date_filter_arguments = date_filter[2]
"""

new_bottom = """                period_indexes = frozenset(
                    row_index
                    for row_index, row in enumerate(date_table["rows"])
                    if (parsed_date := _parse_measure_date(
                        row.get(actual_date_column), actual_date_column, row_index + 1
                    )) is not None and parsed_date in shifted_dates
                )
                key = (date_table["id"], actual_date_column.casefold())
                extra_date_filters[key] = (date_table, actual_date_column, period_indexes)

            return evaluate_with_boolean_filters(
                arguments[0], boolean_filters, extra_date_filters
            )"""

new_block = new_top + inner_indented + new_bottom

text = text[:start_idx] + new_block + text[end_idx:]

with open("analytics_studio/measures.py", "w") as f:
    f.write(text)
print("Patched successfully")
