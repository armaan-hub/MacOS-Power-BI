# Task 46 big-rounding-36: rounding functions over very large numbers (1,299 saved answers the engine refuses)

**Coder:** Antigravity. **Work folder:** git worktree `/Users/armaan/Power BI tool-task46` (branch `antigravity/big-rounding-36`). Work ONLY there.
**Spec:** `tools/parity/task46_big_rounding_spec.json`: 1,299 Power BI answers already saved in the locked batteries (almost all `dax_battery_bigorder28_extra`) that the engine refuses today. Score with `PYTHONPATH=. python3 tools/score_spec.py tools/parity/task46_big_rounding_spec.json` (per Part: match / refused / WRONG).

- **Part A (513): QUOTIENT and INT** of powers and products beyond 2^52 (`QUOTIENT(3^35+1,3)&"z"`, `QUOTIENT(1.5^104-1,1.5)&"z"`, `INT(...)`), and INT of a product with a failing factor (`INT((MAX(Facts[Sales]))*(DIVIDE(1,0))*(SQRT(-1)))` is BLANK).
- **Part B (553): FLOOR and CEILING** of large values (`CEILING(2^52+0.25,0.5)&"z"` is `4.5035996273705E+15z`, `CEILING(2^52+0.25,2)&"z"` is `4503599627370500z`, `FLOOR(7^20+3,3)&"z"`).
- **Part C (233): MROUND** of large values (`MROUND(2^52,3)&"z"` is `4503599627370495z`, `MROUND(4.6E15,3)&"z"` is `4600000000000000z`).

Most refusals today are "A power beyond 2^53 whose result is not exactly a double" (1,112), "A rounding to an integer of a power result from 1E15 to 2^53" (146), "A QUOTIENT whose result is from 2^52 to 2^53" (23) and "MROUND with an odd product between 2^52 and 5E15" (11). Power BI computes these in IEEE double precision (the power is the correctly rounded double, the rounding works on that double, the result is a double), and shows the text of a double with at most 15 significant digits unless the value is an integer Power BI shows exactly. Model that arithmetic and display; do not special-case values.

## Rules
Compute, never look up (app code must never read `tools/parity/*.json` or test fixtures; `tests/test_no_answer_key_in_app.py` must pass). Find general rules, do not fit single expressions or literal values: Claude tests your work on fresh, unseen shapes on live Power BI, and an answer that differs is worse than a refusal. Keep refusing any shape you cannot model exactly. Do not edit saved Power BI answers or existing tests; add tests in `tests/test_iteration136_big_rounding_36.py`. Do not run `--freeze` or `--accept`, do not commit, merge or push.

## Done when
The scorer prints 0 wrong with as many matches as possible, `tools/parity_check.py` replay (no `--tests`) shows 0 DIFF and 0 CRASH, and a ready-for-review entry with scorer counts per Part and the replay line is in this plan.
