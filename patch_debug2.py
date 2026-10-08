with open("tests/test_calculate_advanced_combinations.py", "r") as f:
    text = f.read()

import re
old_assert = """        from decimal import Decimal
        print(values)
        self.assertEqual(values["Prior year East shipped sales"], Decimal("100"))"""

new_assert = """        from decimal import Decimal
        print('CALENDAR FILTER ROWS:', [r['Date'] for r in values.get('__debug_calendar_rows', [])])
        print('ORDERS FILTER ROWS:', [r['OrderDate'] for r in values.get('__debug_orders_rows', [])])
        self.assertEqual(values["Prior year East shipped sales"], Decimal("100"))"""

text = text.replace(old_assert, new_assert)
with open("tests/test_calculate_advanced_combinations.py", "w") as f:
    f.write(text)

# Also let's patch measures.py to return the rows for debugging
# wait, values is just the dictionary of evaluated measures.
