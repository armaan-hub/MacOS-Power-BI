# Task 88: orphan rows of a filtering fact table and the blank member (orphan-filter-78)

> Haiku codes, Sonnet fixes. Compute, never look up: app code never reads the spec, the model file, fixtures or scratch files; nothing keyed on expression text or table names.

**Spec:** `docs/plans/2026-11-08-orphan-filter-78-spec.json` (live Power BI answers on scratch model ZH, never saved; no `now` field: compute main's answer yourself as the baseline). ZH is defined by `docs/plans/2026-11-08-orphan-filter-78-model.py` (load with importlib; it patches SPEC): A-B many-to-many, U-W one-to-one both ways (both with unmatched keys), F and F2 many-to-one to U, both with orphan keys (they map to U's blank member). About 24 answers are wrong on main.

## A. A fact table filter whose rows include orphans
- `SUMMARIZECOLUMNS(ZH_B[N],"v",CALCULATE(SUM(ZH_F[Amt]),ZH_F2))` Power BI 176, ours 268; `CALCULATE(COUNTROWS(ZH_F),ZH_F2)` Power BI 9, ours 12. F2 has an orphan key (h13). Through the expanded table, that orphan row's U columns are blank; Power BI does not let it keep F's orphan rows (keys h11, h12, also blank on U). Work out the rule from the data (blank on the one side from a filtering table's orphan row does not match another table's orphans? or the expanded-table tuple includes the fact key itself?).
## B. COUNTROWS(U) / VALUES(U[X]) under a fact table filter
- `CALCULATE(COUNTROWS(ZH_U),ZH_F)` Power BI 5, ours 6; `COUNTROWS(CALCULATETABLE(VALUES(ZH_U[X]),ZH_F))` Power BI 6, ours 7; with FILTER(ZH_F, ZH_F[Amt]>10) too; under groups on ZH_B[N] (unrelated to F) and ZH_W[Y]. Find which U rows (and whether the blank member) the F filter keeps, and how COUNTROWS(table) vs VALUES(column) treat the blank member.

## Part 1 (Haiku): A then B in `analytics_studio/measures.py` / `relationships.py`. Refuse what cannot be explained.
## Part 2: `tests/test_iteration177_orphan_filter_78.py`: every fixed item plus 30 already matching, assert ours_for == powerbi (ZH via the model file).
## Score / gate: spec 0 wrong (refusals allowed), nothing changes from match; Opus checks a fresh unseen model and runs the gate.

## Review outcome (2026-11-05)
Shipped as Iteration 177. Locked 531486.
