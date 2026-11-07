# Task 81: ALLSELECTED keeps the relationship blank row (allselected-blank-71)

> Haiku codes, Sonnet reviews/fixes. Compute, never look up: no app code may read the spec json, fixtures or scratch files, and nothing may be keyed on expression text or table names.

**Goal:** `ALLSELECTED(Dim[col])` and `ALLSELECTED(Dim)` return the blank (unknown-member) row of a one-side table when the many side holds unmatched keys, exactly as `ALL(Dim[col])` / `ALL(Dim)` already do. Today we drop it inside SUMMARIZECOLUMNS and ADDCOLUMNS row contexts, so RANKX, COUNTROWS, COUNTX, SUMX, MAXX, CONCATENATEX over ALLSELECTED give wrong answers.

**Evidence (live Power BI, guest scratch models, never saved):** spec `docs/plans/2026-11-07-allselected-blank-71-spec.json`, `{items:[{model, expr, powerbi, now}]}`, 1,464 items on models ZO (orphan and blank fact keys) and ZB (no orphans). Today: 102 wrong, all ALLSELECTED over ZO_Dim / ZO_Dim[Prod] / ZO_Dim[Cat] inside SUMMARIZECOLUMNS or ADDCOLUMNS. Example: `CONCATENATEX(SUMMARIZECOLUMNS(ZO_Dim[Prod],"v",RANKX(ALLSELECTED(ZO_Dim[Prod]),CALCULATE(SUM(ZO_Fact[Amt])))),ZO_Dim[Prod]&"="&[v],";",ZO_Dim[Prod])` Power BI `=3;P1=5;P2=1;P3=2;P4=4;P5=6`, ours `=3;P1=4;P2=1;P3=2;P4=3;P5=5` (the blank row's 75 is missing from the ranked list). ALL, VALUES, DISTINCT, ALLNOBLANKROW already match; ALLSELECTED at the top level and under plain CALCULATE already matches.

## Part 1: fix (Haiku)
- `analytics_studio/measures.py`: find how ALLSELECTED builds its table/column values when an outer row or grouping context exists (SUMMARIZECOLUMNS groups, ADDCOLUMNS rows); compare with the ALL path that already adds the blank row (search `_relationship_blank`/blank row/unknown member handling near the ALL table builders around lines 2400-2900). Make ALLSELECTED include the blank row under the same condition ALL uses (the one side has a blank row because the many side holds keys with no match, or blank keys). ALLSELECTED must still restore only the outer shadow filters; only the blank-row membership changes.
- Do not change ALL, VALUES, DISTINCT or ALLNOBLANKROW.

## Part 2: test
- New `tests/test_iteration169_allselected_blank_71.py`: copy as literal tuples every spec item that was wrong before your change plus 40 spec items that already matched (mix of ALL, VALUES, ALLSELECTED top-level, ZB), and assert `tests.critic3_models.ours_for(model, expr) == powerbi` (number strings compare by float). The test must not read the spec json.

## Score
Script over the whole spec: before/after counts of match / wrong / refused. Required after: 0 wrong, and no item that matched before stops matching.

## Gate (Opus runs)
PARITY GATE PASSED with DIFF 0, CRASH 0, REAL APP 0 wrong; fresh held-out orphan models probed by Opus.
