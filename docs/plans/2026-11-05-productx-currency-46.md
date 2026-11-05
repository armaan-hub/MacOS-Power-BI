# Task 56 productx-currency-46: PRODUCTX over a Currency in a conditional, COALESCE with unknown branch types in iterator bodies

**Coder:** Haiku (haiku-builder). **Fixer/reviewer:** Sonnet (sonnet-fixer). **Planner:** Opus.
**Work folder:** git worktree `/Users/armaan/Power BI tool-task56` (branch `antigravity/productx-currency-46`). Work ONLY there.
**Spec:** `tools/parity/task56_productx_currency_spec.json`. Score with `PYTHONPATH=. QT_QPA_PLATFORM=offscreen /usr/local/bin/python3 tools/score_spec.py tools/parity/task56_productx_currency_spec.json`.

- **Part A (82):** PRODUCTX whose body holds a CURRENCY inside IF / IF.EAGER / SWITCH / COALESCE (`PRODUCTX(Facts,IF.EAGER(FALSE(),Facts[Region],CURRENCY(3)))`).
- **Part B (23):** COALESCE with branches whose types the engine cannot establish, inside iterator bodies (`IFERROR(COUNTX({1,2},COALESCE(DIVIDE(1,0),LASTNONBLANK(Facts[Region],1))),7)`).

**Lead (Opus):** Task 54's coder found that `CURRENCY(1.23456)` acts as 1.2346 (four decimals) and that `1.2346^4 = 2.32329891992486` matches one row, while a 1E-12 noise row (`728.999999999995`) was not explained by log/exp or per-step rounding. Strong lead (Opus, measured): Python `math.exp(6*math.log(3))` = 728.9999999999995 shows as Power BI's `728.999999999995`, `math.exp(6*math.log(2))` = 63.99999999999994 matches `63.9999999999994` (with the sign from the count of negatives), so PRODUCTX over a conditional Currency body is computed as exp(sum of ln|x|) in doubles with the sign applied, after each value is rounded to Currency's 4 decimals. Other candidates for Part A: the running product kept as a Currency (rounded to 4 decimals after each multiply), as a double, or through exp(sum(log)) as PRODUCTX may use for doubles; the static result type (Currency vs Double) decides which. Test each in a scratch script on every row, wire in what fits all rows of a structural group, keep refusing the rest. Part B: find the result type Power BI gives COALESCE when branches mix (the first non-BLANK branch's value, typed as a Variant) on the rows.

## Rules
Compute, never look up (app code must never read `tools/parity/*.json` or test fixtures; `tests/test_no_answer_key_in_app.py` must pass). Structural rules, at least 5 supporting rows, no counterexample in the full replay (run it after each change). 0 wrong required; a refusal is acceptable. Do not edit saved answers or existing tests (report any test that asserts a refusal this task answers); new tests go in `tests/test_iteration146_productx_currency_46.py`. No `--freeze`, `--accept`, commit, merge or push.

## Done when
The scorer prints 0 wrong with as many matches as possible, the replay shows 0 DIFF and 0 CRASH, the full suite (`-n 12`) has only the two known flaky failures, and a ready-for-review entry with scorer counts per Part and the replay line is appended to this plan.
