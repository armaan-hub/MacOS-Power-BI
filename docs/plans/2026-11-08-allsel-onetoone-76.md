# Task 86: ALLSELECTED over one-to-one tables, and tables with two routes through a both-way link (allsel-onetoone-76)

> Haiku codes, Sonnet fixes. Compute, never look up: app code never reads the spec, the model file, fixtures or scratch files; nothing keyed on expression text or table names.

**Spec:** `docs/plans/2026-11-08-allsel-onetoone-76-spec.json` (690 live Power BI answers on scratch guest models, never saved; `now` = current main; 5 wrong, 138 refused). ZM and ZS are in tests/critic3_models.py; ZJ is defined by `docs/plans/2026-11-08-rankx-sets-75-model.py` (load with importlib; it patches SPEC).

## A. Wrong answers first (ZJ 5): a SUMMARIZECOLUMNS filter on the one-to-one partner keeps an unmatched row
- `SUMMARIZECOLUMNS(ZJ_W[Y],TREATAS({"y2","y7"},ZJ_W[Y]),"v",COUNTROWS(ALLSELECTED(ZJ_U)))` Power BI `y2=1;y7=1`, ours 2; `SUMX(ALLSELECTED(ZJ_U),CALCULATE(SUM(ZJ_F[Amt])))` Power BI 46, ours 80. y7's key has no U row (its partner would be U's blank member). In Power BI the selected set of U here does not include U's blank member, so the orphan facts (34) are not in it. Ranks over ALLSELECTED(ZJ_U) are off for the same reason.
## B. Refusals family 1 (ZM 23, ZJ 30): "ALLSELECTED over a table of a one-to-one relationship with unmatched rows is not supported while it is filtered"
- ALLSELECTED(W[Y]) / ALLSELECTED(U[X]) / ALLSELECTED(W) / ALLSELECTED(U) inside SUMMARIZECOLUMNS group rows under TREATAS on U[K], B[N] or W[Y], read by COUNTROWS, CONCATENATEX, SUMX, MAXX, RANKX. Power BI answers are in the spec; replace the refusal with the rule they show (which rows of each one-to-one side, and whether a blank member, the selected set holds). Keep refusing what the data cannot settle.
## C. Refusals family 2 (ZS 85): "A row of a table with two routes to the same table (a both-way link) filters that table in a way not supported"
- ZS: Fact->Dim, Fact2<->Dim (both ways), Dim->Sup, Fact/Fact2->Cal. Group rows on ZS_Sup / ZS_Dim under TREATAS on Cal[Year]/Cal[MonthNo], iterating ALL/ALLSELECTED of Dim or Sup with CALCULATE(SUM(Fact2[Amt])), COUNTROWS(Fact2), SUM(Fact[Amt]) (RANKX, SUMX, COUNTROWS(FILTER(...)), CALCULATE(...,ALL(Sup/Dim))). A Dim or Sup row reached in iteration filters Cal (and the other fact) through Fact2's both-way link and also directly. Work out the rule from the answers; refuse what stays ambiguous.

## Part 1 (Haiku): A, then B, then C in `analytics_studio/measures.py` / `relationships.py`. No guessing.
## Part 2: `tests/test_iteration175_allsel_onetoone_76.py`: every fixed item plus 30 already matching, assert ours_for == powerbi (ZJ via the model file).
## Score / gate: spec 0 wrong, nothing changes from match; Opus checks fresh unseen models (never shown to agents) and runs the gate.

## Review outcome (2026-11-05)
Shipped as Iteration 175. Locked 531486.
