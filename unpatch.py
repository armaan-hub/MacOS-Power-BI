import re

with open("patch_measures.py", "r", encoding="utf-8") as f:
    patch_code = f.read()

exec(patch_code, globals()) # gets transition_code, new_evaluate, new_calc, old_evaluate, old_calc

with open("analytics_studio/measures.py", "r", encoding="utf-8") as f:
    code = f.read()

if "def evaluate_with_context_transition(" in code:
    print("Reverting transition_code")
    code = code.replace(transition_code + "\n    def evaluate(", "    def evaluate(")
    code = code.replace("        " + transition_code.strip() + "\n    def evaluate(", "    def evaluate(")

print("Reverting new_evaluate")
code = code.replace(new_evaluate, old_evaluate)
print("Reverting new_calc")
code = code.replace(new_calc, old_calc)

with open("analytics_studio/measures.py", "w", encoding="utf-8") as f:
    f.write(code)

