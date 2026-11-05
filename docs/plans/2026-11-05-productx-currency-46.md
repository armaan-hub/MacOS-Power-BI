# Task 56 productx-currency-46: PRODUCTX over a Currency in a conditional, COALESCE with unknown branch types in iterator bodies

**Coder:** Haiku (haiku-builder). **Fixer/reviewer:** Sonnet (sonnet-fixer). **Planner:** Opus.
**Work folder:** git worktree `/Users/armaan/Power BI tool-task56` (branch `antigravity/productx-currency-46`). Work ONLY there.
**Spec:** `tools/parity/task56_productx_currency_spec.json`. Score with `PYTHONPATH=. QT_QPA_PLATFORM=offscreen /usr/local/bin/python3 tools/score_spec.py tools/parity/task56_productx_currency_spec.json`.

- **Part A (82):** PRODUCTX whose body holds a CURRENCY inside IF / IF.EAGER / SWITCH / COALESCE (`PRODUCTX(Facts,IF.EAGER(FALSE(),Facts[Region],CURRENCY(3)))`).
- **Part B (23):** COALESCE with branches whose types the engine cannot establish, inside iterator bodies (`IFERROR(COUNTX({1,2},COALESCE(DIVIDE(1,0),LASTNONBLANK(Facts[Region],1))),7)`).

**Lead (Opus):** Task 54's coder found that `CURRENCY(1.23456)` acts as 1.2346 (four decimals) and that `1.2346^4 = 2.32329891992486` matches one row, while a 1E-12 noise row (`728.999999999995`) was not explained by log/exp or per-step rounding. Clue (Opus, checked): 3 over 6 rows is `728.999999999995` and -2 over 6 rows is `63.9999999999994`, about 7E-15 relative below the exact product, far more than double rounding of a running product. Plain exp(6*ln 3) gives 729.0000000000001 and summing ln row by row 729.0000000000007, so neither is it; log2 summed row by row gives 728.9999999999997 (closer, still not it). The noise is about 30 ulps, so try a lower-precision step (float32 logs, a Currency-rounded intermediate, a different log base, or exp/log through a scaled representation). Other candidates for Part A: the running product kept as a Currency (rounded to 4 decimals after each multiply), as a double, or through exp(sum(log)) as PRODUCTX may use for doubles; the static result type (Currency vs Double) decides which. Test each in a scratch script on every row, wire in what fits all rows of a structural group, keep refusing the rest. Part B: find the result type Power BI gives COALESCE when branches mix (the first non-BLANK branch's value, typed as a Variant) on the rows.

## Rules
Compute, never look up (app code must never read `tools/parity/*.json` or test fixtures; `tests/test_no_answer_key_in_app.py` must pass). Structural rules, at least 5 supporting rows, no counterexample in the full replay (run it after each change). 0 wrong required; a refusal is acceptable. Do not edit saved answers or existing tests (report any test that asserts a refusal this task answers); new tests go in `tests/test_iteration146_productx_currency_46.py`. No `--freeze`, `--accept`, commit, merge or push.

## Done when
The scorer prints 0 wrong with as many matches as possible, the replay shows 0 DIFF and 0 CRASH, the full suite (`-n 12`) has only the two known flaky failures, and a ready-for-review entry with scorer counts per Part and the replay line is appended to this plan.

## Ready for review (Task 56, builder)

- **Part A (82):** 21 match, 61 still refused, 0 wrong. Matched: SWITCH / COALESCE bodies with CURRENCY and no IF inside (exact product of the row values), and any one-row PRODUCTX over a conditional Currency body (no product arithmetic). Refused: every IF / IF.EAGER body with several rows, because Power BI adds about 30 ulps of noise there (`728.999999999995`, `63.9999999999994`) that no candidate reproduced.
- **Part B (23):** 0 match, 23 refused, 0 wrong. A constant-first COALESCE rule (first argument a constant number, DATE, TIME or CONVERT of a text number) matched 6 rows but was reverted: DATE / TIME first broke 9 locked answers (typed3_extra, bigorder28_extra, types20_extra), and the number-first subset is only 3 spec rows.
- Scorer: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen /usr/local/bin/python3 tools/score_spec.py tools/parity/task56_productx_currency_spec.json` gives A gap-reject 61, A match 21, B gap-reject 23, 0 wrong.
- Replay (no flags): `replayed 484189 Power BI answers: {'match': 480841, 'gap-reject': 3348, 'DIFF': 0, 'CRASH': 0}; locked 480800`, PARITY GATE PASSED. Ledger restored with git checkout.
- Full suite (`-n 12`): 2 failed, 2698 passed. The failures are the two known flaky tests (`test_query_functions` signed int64, `test_transformations` group/pivot).
- New tests: `tests/test_iteration146_productx_currency_46.py` (6 pass). No existing test was edited. `tests/test_no_answer_key_in_app.py` passes.
- Changes: `analytics_studio/measures.py` helper `_switch_or_coalesce_root_without_if` (about line 3092), its use in the PRODUCTX conditional refusal (about line 19116, also exempts a one-row table).
- Not run: `graphify update .` (project rule) in this worktree.
