with open("tests/test_calculate_advanced_combinations.py", "r") as f:
    text = f.read()

old_orders = """                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount", "Region", "Status"],
                    "rows": order_rows,
                    "filter_rows": order_rows,
                    "column_types": {"OrderDate": "date", "Amount": "whole_number"},
                },"""

new_orders = """                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount", "Region", "Status"],
                    "rows": order_rows,
                    "filter_rows": order_rows,
                    "filter_context_complete": True,
                    "filter_column_rows": {},
                    "column_types": {"OrderDate": "date", "Amount": "whole_number"},
                },"""

text = text.replace(old_orders, new_orders)

with open("tests/test_calculate_advanced_combinations.py", "w") as f:
    f.write(text)
