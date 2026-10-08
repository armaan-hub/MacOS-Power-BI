import re

with open("analytics_studio/measures.py", "r") as f:
    text = f.read()

old_block = """        if function == "FILTER":
            raise MeasureError(
                "FILTER is supported only as the sole table-valued CALCULATE filter argument."
            )"""

new_block = """        if function == "FILTER":
            raise MeasureError(
                "FILTER is supported only as the sole table-valued CALCULATE filter argument."
            )
        if function in _TIME_FILTER_FUNCTIONS:
            raise MeasureError(
                f"{function} returns a date table; use it as a filter in CALCULATE."
            )"""

text = text.replace(old_block, new_block)

# Now remove the normalize_measure static check!

old_norm = """    parsed_expression = parse_expression(clean_expression)
    if (
        _contains_table_call(parsed_expression)
        and not _is_supported_time_filter_calculate(parsed_expression)
        and not _is_supported_table_filter_calculate(parsed_expression)
        and not _has_supported_all_usage(parsed_expression)
    ):
        raise MeasureError("Table-valued functions are not supported in measure expressions.")
    return {"name": clean_name, "expression": clean_expression}"""

new_norm = """    parsed_expression = parse_expression(clean_expression)
    return {"name": clean_name, "expression": clean_expression}"""

text = text.replace(old_norm, new_norm)

with open("analytics_studio/measures.py", "w") as f:
    f.write(text)
print("done")
