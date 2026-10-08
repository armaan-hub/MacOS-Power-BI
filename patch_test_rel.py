with open("tests/test_calculate_advanced_combinations.py", "r") as f:
    text = f.read()

text = text.replace('"from_table_id": "orders-id",', '"relationship_version": 1,\n                    "from_table_id": "orders-id",')

with open("tests/test_calculate_advanced_combinations.py", "w") as f:
    f.write(text)
