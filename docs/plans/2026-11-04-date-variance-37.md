# Task 47 date-variance-37: VARX/STDEVX over dates and over one repeated fraction (623 saved answers the engine refuses)

**Coder:** Haiku (haiku-builder). **Fixer/reviewer:** Sonnet (sonnet-fixer). **Planner:** Opus.
**Work folder:** git worktree `/Users/armaan/Power BI tool-task47` (branch `antigravity/date-variance-37`). Work ONLY there.
**Spec:** `tools/parity/task47_date_variance_spec.json`: 623 Power BI answers already saved in the locked batteries (mostly `dax_battery_datestats30_extra`, `dax_battery_typed3_extra`) that the engine refuses today. Score with `PYTHONPATH=. QT_QPA_PLATFORM=offscreen /usr/local/bin/python3 tools/score_spec.py tools/parity/task47_date_variance_spec.json`.

- **Part A (540):** VARX.P / VARX.S / STDEVX.P / STDEVX.S whose body is a date or datetime (DATE(..)+Facts[Quantity], TIME(..)+..., DATE(..)+0.5+Facts[Quantity]*0.25), also inside IF/SWITCH/COALESCE/CALCULATE. Today they refuse with "VARX.P over a date in a conditional is not exact in the local engine." Example: `VARX.P(Facts,DATE(2020,1,1)+Facts[Quantity])` is `2.91666674613953` (exact would be 2.91666666666667).
- **Part B (83):** VARX/STDEVX of one repeated fraction, e.g. `STDEVX.S(CALCULATETABLE(Facts,Facts[Region]="East"),AVERAGE(Facts[Sales]))` is `8.42936970217881E-08` where exact math gives 0. Today they refuse with "... of one repeated fraction carries float noise ...".

**Lead (measured by Opus):** Part A looks like the variance is computed in single precision (float32). numpy `np.var(x.astype(np.float32))` over the six date serials 43834,43833,43832,43835,43831,43836 gives 2.9166667461395264, exactly Power BI's 2.91666674613953. It is not exact for `DATE(1950,1,1)+0.5+Facts[Quantity]*0.25` (Power BI 0.182291686534882, plain float32 np.var 0.1822916716337204), so the exact algorithm differs: try the order of the rows, the accumulation (float32 sums vs double sums of float32 values, pairwise vs sequential, one-pass sum/sum-of-squares vs two-pass), and where the date is converted to float32 (each value, the mean, the deviations). Part B is probably the same kind of accumulation over doubles: find the one algorithm that matches all rows. If no single rule fits a group, keep refusing that group.

## Rules
Compute, never look up (app code must never read `tools/parity/*.json` or test fixtures; `tests/test_no_answer_key_in_app.py` must pass). Find general rules from the arithmetic, do not fit single expressions or literal values: Opus tests the work on fresh, unseen shapes measured live in Power BI. 0 wrong is required; a refusal is acceptable. Do not edit saved Power BI answers or existing tests; add new tests in `tests/test_iteration137_date_variance_37.py`. No `--freeze`, `--accept`, commit, merge or push.

## Done when
The scorer prints 0 wrong with as many matches as possible, `tools/parity_check.py` replay (no `--tests`) shows 0 DIFF and 0 CRASH, and a ready-for-review entry with scorer counts per Part and the replay line is appended to this plan.
