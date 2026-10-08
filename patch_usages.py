import sys

with open("analytics_studio/measures.py", "r", encoding="utf-8") as f:
    text = f.read()

calc_old = """            if row_context is not None:
                raise MeasureError("CALCULATE inside SUMX/AVERAGEX needs context transition, which is not supported.")"""
calc_new = """            if row_context is not None:
                return evaluate_with_context_transition(node, row_context[0], row_context[1])"""

ref_old = """                if row_context is not None:
                    raise MeasureError(
                        "Measure references inside SUMX/AVERAGEX need context transition, which is not supported."
                    )"""
ref_new = """                if row_context is not None:
                    return evaluate_with_context_transition(node, row_context[0], row_context[1])"""

if calc_old in text:
    text = text.replace(calc_old, calc_new)
if ref_old in text:
    text = text.replace(ref_old, ref_new)

with open("analytics_studio/measures.py", "w", encoding="utf-8") as f:
    f.write(text)
