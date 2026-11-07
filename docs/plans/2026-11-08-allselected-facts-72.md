# Task 82: ALLSELECTED of a dimension inside fact-table iterators (allselected-facts-72)

> Haiku codes, Sonnet fixes. Compute, never look up: app code never reads the spec, the model file, fixtures or scratch files; nothing keyed on expression text or table names.

**Problem (live Power BI, scratch guest model, never saved):** when an iterator walks the many side (fact rows, VALUES(Fact[key]), SUMMARIZE(Fact, ...), FILTER(Fact, ...)) and a CALCULATE / measure inside reads `ALLSELECTED(Dim)` or `ALLSELECTED(Dim[col])`, Power BI returns the dimension rows that the selected fact rows reach through the relationship (plus the blank row when selected facts hold unmatched or blank keys), not every dimension row. Example on model ZY (9 Dim items I1-I9; facts use I1-I7, three orphan keys I10-I12 and two blank keys): `MAXX(ZY_Fact,CALCULATE(COUNTROWS(ALLSELECTED(ZY_Dim))))` Power BI 8 (I1-I7 + blank), ours 9; `SUMX(ZY_Fact,CALCULATE(COUNTROWS(ALLSELECTED(ZY_Dim))))` Power BI 240 = 30 x 8, ours 270.

**Spec:** `docs/plans/2026-11-08-allselected-facts-72-spec.json` (360 items, model ZY, 70 wrong now; `now` = current main). Model ZY: `docs/plans/2026-11-08-allselected-facts-72-model.py` patches `tests.critic3_models.SPEC['ZY']` when imported (copy that model into the test file as literals; do not import the plans file from tests or app code).

**Locked constraint:** `tests/test_iteration82_rules.py` (saved answers on ZO) must keep passing, including `CALCULATE(SUMX(ZO_Fact,CALCULATE(COUNTROWS(ALLSELECTED(ZO_Dim)))),ZO_Cal[Date]<=DATE(2024,2,10))` = 45, and the iteration-169/170 tests.

## Part 1 (Haiku): rule
In the shadowed ALLSELECTED path (`allselected_rows_for` in `analytics_studio/measures.py`), when the restored context comes from an iterator over a many-side table, filter the dimension rows to those reached by the selected fact rows (the facts as filtered by the restored outer context, i.e. without the per-row transition), and add the blank member only if those facts hold an unmatched or blank key. Find out from the spec whether outer CALCULATE filters (on the calendar, on Dim columns, on fact columns, KEEPFILTERS) count as "selected"; where a shape stays unexplained, refuse it.

## Part 2: test
New `tests/test_iteration170_allselected_facts_72.py`: ZY model data as literals, every spec item that was wrong plus 40 that matched, asserting `ours_for('ZY', expr) == powerbi` (float compare).

## Score / gate
0 wrong on the spec, no item changes from match; Opus probes an unseen held-out model and runs the gate.

## Review outcome (2026-11-05)
Shipped as Iteration 171. Locked 531486.
