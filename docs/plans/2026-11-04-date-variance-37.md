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

## Ready for review (Haiku builder, 2026-11-04)
- **Algorithm (Part A and Part B):** double arithmetic over the rows in row order. VAR.P = (sum of squares / n) minus (sum / n) squared. VAR.S = (sum of squares minus sum squared / n) / (n - 1). STDEV = sqrt of that variance in double. A body that repeats one value adds it as n x value and the squares as (value x value) x n (this is what matched all 78 repeated-fraction rows).
- **Part A scorer (score_spec, 540 rows):** 454 match, 86 gap-reject (refused), 0 wrong. The 86 refusals are date bodies that divide (`/`): the decimal division differs from Power BI's double division in the last digit for 5 rows, so every division date body is refused.
- **Part B scorer (83 rows):** 81 match, 2 gap-reject, 0 wrong.
- **Replay (`tools/parity_check.py`, no flags):** replayed 474966 Power BI answers: match 469272, gap-reject 5694, DIFF 0, CRASH 0; PARITY GATE PASSED. PARITY_LEDGER.md reverted.
- **Pytest (full suite, 45 min):** 2652 passed, 4 failed, 1 xfailed. The 4 failures are existing refusal guards that assert the refusals Task 47 turns into values (not edited, per rules): `tests/test_iteration99_gaps_2_review.py::Gaps2ReviewTest::test_statistical_iterators_with_rows` (STDEVX.S East AVERAGE(Sales), a Part B row); `tests/test_iteration130_date_stats_30.py::DateStats30Tests::test_part_a_varx_p_over_dates_in_conditionals` (a Part A row); `tests/test_iteration108_convert_currency_9.py::SecondReviewCorrectionsTests::test_date_made_from_numbers_keeps_variance_numeric_over_a_column` (VARX.S date body now 3.5); `tests/test_iteration104_typed_columns_5_review.py::OneRepeatedDateHasNoSpreadTest::test_a_refusal_is_not_an_error_for_iferror` (IFERROR(VARX.P(Facts,0.5),7) now a value).
- **Status:** NOT yet ready to lock. The four guard tests need an owner decision (supersede or keep the refusals) before the gate's pytest step can pass.
- **Files:** `analytics_studio/dax_math.py` (double_statistic, repeated-fraction branch of statistic), `analytics_studio/measures.py` (date refusal branch, `_has_division`, `double_dates` switch), `tests/test_iteration137_date_variance_37.py` (new).

## Review outcome (2026-11-04)
Shipped as Iteration 137. Locked 473309.
