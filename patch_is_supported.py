import re

with open("analytics_studio/measures.py", "r") as f:
    text = f.read()

old_block = """def _is_supported_time_filter_calculate(node: Any) -> bool:
    if not (
        isinstance(node, tuple)
        and len(node) == 3
        and node[0] == "call"
        and node[1] == "CALCULATE"
        and len(node[2]) == 2
        and node[2][1][0] == "call"
        and node[2][1][1] in {
            "DATEADD", "SAMEPERIODLASTYEAR", "PREVIOUSYEAR", "PREVIOUSQUARTER", "PREVIOUSMONTH",
            "DATESYTD", "DATESQTD", "DATESMTD", "DATESBETWEEN", "DATESINPERIOD",
        }
    ):
        return False
    return not _contains_table_call(node[2][0])"""

new_block = """def _is_supported_time_filter_calculate(node: Any) -> bool:
    if not (
        isinstance(node, tuple)
        and len(node) == 3
        and node[0] == "call"
        and node[1] == "CALCULATE"
        and len(node[2]) >= 2
    ):
        return False
    # Verify that there's at least one time-filter argument
    has_time_filter = any(
        arg[0] == "call" and arg[1] in _TIME_FILTER_FUNCTIONS
        for arg in node[2][1:]
    )
    if not has_time_filter:
        return False
    return not _contains_table_call(node[2][0])"""

if old_block in text:
    text = text.replace(old_block, new_block)
    with open("analytics_studio/measures.py", "w") as f:
        f.write(text)
    print("Patched _is_supported_time_filter_calculate")
else:
    print("Could not find block")
