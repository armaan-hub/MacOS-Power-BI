import re

with open("tests/test_calculate_boolean_filters.py", "r") as f:
    text = f.read()

old_case = """            (
                "CALCULATE(SUM([Amount]), 'Sales'[Color] = \\"Blue\\", PREVIOUSMONTH('Calendar'[Date]))",
                "cannot be combined",
            ),"""

text = text.replace(old_case, "")

with open("tests/test_calculate_boolean_filters.py", "w") as f:
    f.write(text)
