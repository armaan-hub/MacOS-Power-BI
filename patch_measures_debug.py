with open("analytics_studio/measures.py", "r") as f:
    text = f.read()

import re
old_eval = """        try:
            return evaluate(node)
        finally:"""

new_eval = """        try:
            val = evaluate(node)
            if 'Prior year East shipped sales' in [n for n, _, _ in items]:
                print('DEBUG calendar rows:', [r.get('Date') for r in rows_by_table_id.get('calendar-id', [])])
                print('DEBUG orders rows:', [r.get('OrderDate') for r in rows_by_table_id.get('orders-id', [])])
            return val
        finally:"""

# wait, items is not available here. 
# let's just print unconditionally if calendar-id is in rows_by_table_id
# but it will print many times. That's fine.

old_eval2 = """        try:
            return evaluate(node)
        finally:"""

new_eval2 = """        try:
            res = evaluate(node)
            print("cal:", len(rows_by_table_id.get('calendar-id', [])), "orders:", len(rows_by_table_id.get('orders-id', [])))
            return res
        finally:"""

text = text.replace(old_eval2, new_eval2)
# actually no, I shouldn't patch it this way.
