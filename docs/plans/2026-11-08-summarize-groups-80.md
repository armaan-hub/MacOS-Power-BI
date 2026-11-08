# Task 90: SUMMARIZE / GROUPBY over a fact table grouped by related columns (summarize-groups-80)

> Haiku codes, Sonnet fixes. Compute, never look up: app code never reads the spec, the model file, fixtures or scratch files; nothing keyed on expression text or table names.

**Spec:** `docs/plans/2026-11-08-summarize-groups-80-spec.json` (126 live Power BI answers on ZM and ZJ, never saved; `now` = current main; 7 wrong, 52 refused; compare numerically). ZM is in tests/critic3_models.py; ZJ: `docs/plans/2026-11-08-rankx-sets-75-model.py` (importlib; patches SPEC). Time intelligence on these and the snowflake models is already 100% right.

## A. Wrong: the blank group of SUMMARIZE over a fact grouped through a one-to-one table
- `SUMX(SUMMARIZE(ZM_F2,ZM_W[Y],"s",SUM(ZM_F[Amt])),[s])` Power BI 23, ours 70; per W[Y] group Power BI `=16;y1=3;y2=4`, ours `=48;...`. F2 rows whose U has no W partner (or orphan F2 keys) form the blank W[Y] group; the extension column is evaluated with that row's context transition. Work out which F rows Power BI's blank-group filter keeps (the blank W[Y] value filters W's blank member; through the one-to-one and F's relationship).
- `COUNTROWS(SUMMARIZE(ZM_A,ZM_B[N]))` under TREATAS on ZM_U[K] in a U[X] group: Power BI returns an ERROR, ours BLANK — find why (many-to-many A-B; maybe an ambiguous path) and return an error/refusal, never BLANK.
## B. Refused: GROUPBY / SUMMARIZE with related columns
- `COUNTROWS(GROUPBY(F,U[X]))`, `SUMX(GROUPBY(F,W[Y],"s",SUMX(CURRENTGROUP(),F[Amt])),[s])`, `CONCATENATEX(GROUPBY(F2,W[Y]),W[Y],...)`, `COUNTROWS(SUMMARIZE(A,B[N]))` are refused; Power BI answers are in the spec. Lift a refusal only where the answers settle the rule (GROUPBY over a column of a table reachable many-to-one from the grouped table, including the blank member for orphans).

## Part 1 (Haiku): A then B in `analytics_studio/` (find the SUMMARIZE / GROUPBY code). Refuse what cannot be explained.
## Part 2: `tests/test_iteration179_summarize_groups_80.py`: every fixed item plus 20 already matching (numeric-tolerant compare).
## Score / gate: spec 0 wrong, nothing changes from match; Opus checks unseen models (snowflake GROUPBY over Dim[Cat], one-to-one model ZE) and runs the gate.

## Review outcome (2026-11-05)
Shipped as Iteration 179. Locked 531486.
