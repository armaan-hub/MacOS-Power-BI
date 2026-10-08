import re

with open("analytics_studio/measures.py", "r") as f:
    text = f.read()

start_marker = """            time_filters = [
                arg for arg in arguments[1:]"""

end_marker = """            return evaluate_with_boolean_filters(
                arguments[0], boolean_filters, extra_date_filters
            )"""

start_idx = text.find(start_marker)
end_idx = text.find(end_marker, start_idx) + len(end_marker)

if start_idx == -1 or end_idx == -1:
    print("Markers not found")
    import sys; sys.exit(1)

old_block = text[start_idx:end_idx]

# We need to extract the loop body again, sigh.
# Let's just do a simpler search and replace.
