# Task 55 big-rounding-45: FLOOR / CEILING / MROUND / QUOTIENT / INT of values from 1E15 to 2^53 (220 saved answers the engine refuses)

**Coder:** Haiku (haiku-builder). **Fixer/reviewer:** Sonnet (sonnet-fixer). **Planner:** Opus.
**Work folder:** git worktree `/Users/armaan/Power BI tool-task55` (branch `antigravity/big-rounding-45`). Work ONLY there.
**Spec:** `tools/parity/task55_big_rounding2_spec.json`. Score with `PYTHONPATH=. QT_QPA_PLATFORM=offscreen /usr/local/bin/python3 tools/score_spec.py tools/parity/task55_big_rounding2_spec.json`.

- **Part A (170):** "A rounding to an integer of a power result from 1E15 to 2^53": `MROUND(2^52,3)&"z"` is `4503599627370495z`, `CEILING(2^52+0.25,7)&"z"` is `4503599627370494z` (below the value!), `FLOOR(2^52+0.5,7)&"z"` is `4503599627370494z`, `FLOOR(7*2^50+0.5,1.5)&"z"` is `7.88129934789837E+15z`.
- **Part B (28):** QUOTIENT whose result is from 2^52 to 2^53 (`QUOTIENT(7*2^50+0.5,3)&"z"` is `2627099782632789z`, `QUOTIENT(2^53*1.5+1,2)&"z"` is `6755399441055744z`).
- **Part C (22):** MROUND with an odd product in the same band.

**Lead (Opus):** Iteration 136 (Task 46) made powers square-and-multiply doubles and found (Iteration 128, test_part_c) that QUOTIENT cuts the quotient to 15 significant digits with ties going up. `CEILING(2^52+0.25,7)` giving a value below the input suggests Power BI computes `significance * ROUND(x / significance)` (or a ceil/floor of the 15-digit-rounded quotient) in doubles, so the 15-digit cut of x/significance decides. Test each candidate (15-digit cut of the quotient, then multiply in doubles; ceil/floor before or after the cut; MROUND = significance * round-half-away of the cut quotient) in a scratch script on every row, wire in the one that fits all rows of a group, and keep refusing the rest. The existing guards are in `analytics_studio/measures.py` (grep the refusal messages).

## Rules
Compute, never look up (app code must never read `tools/parity/*.json` or test fixtures; `tests/test_no_answer_key_in_app.py` must pass). Structural rules, at least 5 supporting rows, no counterexample in the full replay (run it after each change; the locked `dax_battery_bigorder28_extra` and `dax_battery_biground36_extra` hold many neighbours). 0 wrong required; a refusal is acceptable. Do not edit saved answers or existing tests (report any test that asserts a refusal this task answers); new tests go in `tests/test_iteration145_big_rounding_45.py`. No `--freeze`, `--accept`, commit, merge or push.

## Done when
The scorer prints 0 wrong with as many matches as possible, the replay shows 0 DIFF and 0 CRASH, the full suite (`-n 12`) has only the two known flaky failures, and a ready-for-review entry with scorer counts per Part and the replay line is appended to this plan.
