with open("tests/test_calculate_advanced_combinations.py", "r") as f:
    text = f.read()

import re
old_assert = """        from decimal import Decimal
        self.assertEqual(values["Prior year East shipped sales"], Decimal("100"))"""

new_assert = """        from decimal import Decimal
        print(values)
        self.assertEqual(values["Prior year East shipped sales"], Decimal("100"))"""

text = text.replace(old_assert, new_assert)
with open("tests/test_calculate_advanced_combinations.py", "w") as f:
    f.write(text)
