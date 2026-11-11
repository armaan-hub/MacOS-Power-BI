# Task 137 (Iteration 226): nested IFERROR inside type tests (dax-nestiferr-127)

Coder: Haiku 5.5 subagent, reviewer: Sonnet 5.5, planner/gate: Claude Opus 5.5.
Worktree `/Users/armaan/Power BI tool-task137`, branch `antigravity/dax-nestiferr-127` (from main d96dc76).

This is a CORRECTNESS task. Fresh Power BI probes show main gives WRONG answers for type tests over IFERROR whose
branches hold another IFERROR / IF / COALESCE, e.g.
- `ISDOUBLE(IFERROR(IFERROR(1/0,"b"),2))` → Power BI False, we True
- `ISTEXT(IFERROR(MOD(1,0),IFERROR(1/0,"a")))` → Power BI True, we False
- `ISINT64(IFERROR(IFERROR(MOD(1,0),"b"),2))` → Power BI False, we True

Both files below are real Power BI answers (all 600 + 294 measured today on the iPad guest):
- **Spec:** `docs/plans/2026-11-11-dax-nestiferr-127-spec.json` (600 items; main: 499 exact, 92 refused, 9 WRONG).
- **Add-on:** `docs/plans/2026-11-11-dax-nestiferr-127-addon.json` (294 items; main after Iteration 225: 12 WRONG).

Goal: wrong 0 on both, then as many exact as is safe. Opus checks two more hidden sets of 540 (main has 21 wrong
there). Key facts to respect (all measured): `1/0` and `0/0` inside IFERROR are caught like errors for the purpose of
the result type; `SQRT(-1)` is NaN, not an error (`ISDOUBLE(IFERROR(SQRT(-1),DATE(2020,1,1)))` → True) yet
`ISDOUBLE(IFERROR(SQRT(-1),"x"))` → False; IFERROR's result type when the branch types differ is a Variant whose
type test follows the value actually returned. Model the RESULT TYPE of nested IFERROR / IF / COALESCE exactly, or
refuse.

## Rules (binding)
- Compute, never look up: app code never reads `tools/parity/*.json`, the spec, plans, tests or scratch files; no
  tables keyed by expression text.
- Do not run Power BI or any Power BI tool; no merge or push.
- Check with `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python3 tools/parity_check.py` (DIFF 0, CRASH 0, no locked
  change), then `git checkout -- PARITY_LEDGER.md`; pytest with `-p no:cacheprovider` (never `-n`).
- Commit on the branch; report spec and add-on scores, the rule, files changed.
