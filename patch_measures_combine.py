import re

with open("analytics_studio/measures.py", "r") as f:
    code = f.read()

# 1. Update parser
old_parser = """                if contains_time_filter and not valid_time_filter:
                    raise MeasureError(
                        "Time-intelligence filters cannot be combined with other "
                        "CALCULATE filters yet."
                    )
                if not valid_time_filter and not valid_table_filter:
                    for filter_argument in arguments[1:]:
                        predicate, _keep = _calculate_filter_argument(filter_argument)
                        _calculate_boolean_filter_column(predicate)"""

new_parser = """                if not valid_time_filter and not valid_table_filter:
                    for filter_argument in arguments[1:]:
                        if filter_argument[0] == "call" and filter_argument[1] in _TIME_FILTER_FUNCTIONS:
                            continue
                        predicate, _keep = _calculate_filter_argument(filter_argument)
                        _calculate_boolean_filter_column(predicate)"""

code = code.replace(old_parser, new_parser)

if old_parser not in code and new_parser not in code:
    print("Parser patch failed")

with open("analytics_studio/measures.py", "w") as f:
    f.write(code)
