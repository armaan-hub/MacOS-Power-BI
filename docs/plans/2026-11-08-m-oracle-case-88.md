# Task 98 (Iteration 187): oracle answers survive case-insensitive storage (m-oracle-case-88)

Power BI keeps one spelling per case-insensitively-equal string in a column, so oracle answers differing only by case collapsed (live: `"#(0041)"` returned `"a"`). Answers are now stored as upper-case UTF-8 hex and decoded in Python. Re-collected the 174-expression M core battery (`docs/plans/2026-11-08-m-core-battery.json`): only that one answer changed.

## Review outcome (2026-11-05)
Shipped as Iteration 187. Locked 531486.
