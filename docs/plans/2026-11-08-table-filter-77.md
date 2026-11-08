# Task 87: a fact table as a CALCULATE / CALCULATETABLE filter argument on multi-table models (table-filter-77)

> Haiku codes, Sonnet fixes. Compute, never look up: app code never reads the spec, the model file, fixtures or scratch files; nothing keyed on expression text or table names.

**Spec:** `docs/plans/2026-11-08-table-filter-77-spec.json` (616 live Power BI answers on scratch guest models, never saved; `now` = current main; 15 wrong, 20 refused). ZS and ZM are in tests/critic3_models.py; ZJ is defined by `docs/plans/2026-11-08-rankx-sets-75-model.py` (load with importlib; it patches SPEC). Families probed: ISCROSSFILTERED / ISFILTERED, CROSSFILTER, REMOVEFILTERS, ALLEXCEPT, KEEPFILTERS, TOPN, CALCULATETABLE(VALUES), table filter arguments. Only the table-filter-argument family is wrong.

## A. Expanded-table filter (ZS 7)
- `SUMMARIZECOLUMNS(ZS_Sup[Sup],"v",CALCULATE(SUM(ZS_Fact[Qty]),ZS_Fact2))` Power BI `S1=2`, ours 6 (same with groups on Cal[Year], Dim[Cat], Reg[Zone]). A table used as a filter argument filters with its EXPANDED table (the table plus every table reachable on the one side of its many-to-one relationships). It filters by the visible rows of that expanded table as tuples: Fact2 holds (Prod, Dt) pairs, so Fact rows survive only if their Dim row AND their Cal row come from the same Fact2 row's expansion — check from the data whether that is the rule (or whether it is the separate Dim set and Cal set), and implement it.
## B. Orphan / blank member of the expanded table (ZM 4, ZJ 4)
- `SUMMARIZECOLUMNS(ZM_U[X],"v",CALCULATE(SUM(ZM_F2[Amt]),ZM_F))` Power BI has no blank-X row (`x1=100;x2=500;x4=400`), ours adds `=400`. `COUNTROWS(CALCULATETABLE(VALUES(ZM_W[Y]),ZM_F))` per U[X]: Power BI gives 1 only for some X values (rows exist only where the expanded F rows reach), ours lists every X. F's orphan keys map to U's blank member; W is one-to-one (both ways) with U. Work out which group rows exist and what the expanded F filter keeps on U and on W.

## Part 1 (Haiku): A then B in `analytics_studio/measures.py` (and helpers). Refuse what cannot be explained; no guessing.
## Part 2: `tests/test_iteration176_table_filter_77.py`: every fixed item plus 30 already matching, assert ours_for == powerbi (ZJ via the model file).
## Score / gate: spec 0 wrong, nothing changes from match; Opus checks fresh unseen models and runs the gate.

## Review outcome (2026-11-05)
Shipped as Iteration 176. Locked 531486.
