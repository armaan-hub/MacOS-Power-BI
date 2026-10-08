from analytics_studio.measures import parse_expression, _contains_table_call
node = parse_expression("DIVIDE(1, DATEADD('D'[D], 1, YEAR))")
print(_contains_table_call(node))
