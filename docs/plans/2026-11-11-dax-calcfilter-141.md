# Task 141 — dax-calcfilter-141: CALCULATE filter-argument combinations

Goal: answer CALCULATE / CALCULATETABLE calls that mix strict-equality filters, KEEPFILTERS, table filters over whole rows
(FILTER(Facts,..), TREATAS, VALUES) and modifiers (ALLSELECTED, ALL, REMOVEFILTERS), which the engine refused.

Spec: 70 refused saved answers (52 spec, 18 holdout), five fresh hidden Power BI sets of 540 random CALCULATE filter
combinations (main refused 213-247 of each, 0 wrong), plus a 540-expression probe on a Facts table with duplicate rows.

Rules (Haiku 5.5 coded the first, Sonnet 5.5 the rest):
- `Facts[X]==value` / `==BLANK()` is an ordinary Boolean filter with strict equality (0 and "" are not blank).
- A filter that is a set of whole rows (FILTER over a table, a multi-column Boolean filter) stays a separate tuple set.
  Overwriting or clearing columns C projects every set covering C onto its other columns; each covered column is the
  intersection of all sets covering it and the plain filters recorded beside them. KEEPFILTERS intersects without removing.
- Boolean filters beside an ALLSELECTED modifier over such a set project or intersect the set instead of refusing.
- Still refused: `==` against a computed fraction, a few iterator-column shapes.

## Results
spec 0 -> 52/52, holdout 0 -> 16/18, hidden1-5 ~300 -> 538-539 of 540 each, duplicate-row probe 333 -> 536 of 540; wrong 0 everywhere.

## Review outcome (2026-11-11)
Shipped as Iteration 230. Locked 537250.
