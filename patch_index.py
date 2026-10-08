import sys

with open("analytics_studio/measures.py", "r", encoding="utf-8") as f:
    text = f.read()

bad = """        allowed_rows = frozenset(
            row_index
            for row_index, iterate_row in enumerate(iterated_table["rows"], 1)
            if all("""

good = """        allowed_rows = frozenset(
            row_index
            for row_index, iterate_row in enumerate(iterated_table["rows"])
            if all("""

text = text.replace(bad, good)

with open("analytics_studio/measures.py", "w", encoding="utf-8") as f:
    f.write(text)
