# Task 89: nested ALLNOBLANKROW / ALLSELECTED / column clears under a fact table filter with orphan keys (nested-clear-79)

> Haiku codes, Sonnet fixes. Compute, never look up: app code never reads the spec, the model file, fixtures or scratch files; nothing keyed on expression text or table names.

**Spec:** `docs/plans/2026-11-08-nested-clear-79-spec.json` (300 live Power BI answers on scratch model ZH, never saved; `now` = current main; 33 wrong, 6 refused). Also usable: `docs/plans/2026-11-08-orphan-filter-78-spec3.json` (260 earlier nested-clear items; 8 still wrong) and `-spec.json` (860, must stay 847/0/13). ZH: `docs/plans/2026-11-08-orphan-filter-78-model.py` (importlib; patches SPEC).

Shape: `CALCULATE(CALCULATE(<inner>, <clear>), <table filter>)`, optionally in SUMMARIZECOLUMNS over B[N], W[Y], U[X]. inner: COUNTROWS(VALUES(W[Y] / U[X] / U[K] / W[K])), COUNTROWS(U / W / F), SUM(F[Amt]), SUM(F2[Amt]); clear: ALLNOBLANKROW(U / W / U[X]), ALLSELECTED(U / W / U[X]), REMOVEFILTERS(U[X] / W[Y]), ALL(U[X] / U[K]); table filter: F, F2, FILTER(F,..), FILTER(F2,..). Iteration 177 made whole-table clears end the table filter's expanded-table narrowing; ALLSELECTED and single-column clears keep it.

Known wrong examples: COUNTROWS(VALUES(W[Y])) under ALLNOBLANKROW(U) + an orphan-key table filter: Power BI 3, ours 4 (the one-to-one partner's blank member); SUM(F[Amt]) with ALLSELECTED(U) under FILTER(F2,..) by B[N]: Power BI 176, ours 268; COUNTROWS(F) with ALLSELECTED(U) / REMOVEFILTERS(U[X]) under FILTER(F2,..), blank U[X] group: Power BI 4, ours 7. Work out from the data what each clear does to the narrowing, to the blank members of U and of its one-to-one partner W, and to the fact-to-fact expansion.

## Part 1 (Haiku): fix in `analytics_studio/measures.py` / `relationships.py`. Refuse narrowly what cannot be explained.
## Part 2: `tests/test_iteration178_nested_clear_79.py`: every fixed item plus 30 already matching, assert ours_for == powerbi (numeric-tolerant compare like tests/test_iteration177_orphan_filter_78.py).
## Score / gate: spec 0 wrong, spec3 / spec of Task 88 lose nothing; Opus checks a fresh unseen model and runs the gate.

## Review outcome (2026-11-05)
Shipped as Iteration 178. Locked 531486.
