# Task 39 nan-inf-iterators-29: Infinity and NaN inside statistical iterators (652 saved answers the engine refuses)

**Coder:** Antigravity. **Work folder:** git worktree `/Users/armaan/Power BI tool-task39` (branch `antigravity/nan-inf-iterators-29`). Work ONLY there.
**Spec:** `tools/parity/task39_nan_inf_iterators_spec.json`: 652 Power BI answers already saved in the locked batteries that the engine refuses today. Score with `PYTHONPATH=. python3 tools/score_spec.py tools/parity/task39_nan_inf_iterators_spec.json`.

- **Part A (228): PRODUCTX, MEDIANX, GEOMEANX, PERCENTILEX.INC/EXC over Infinity or NaN values.** Refused with "<F> over Infinity or NaN values is not modelled by the local engine." Examples: `PRODUCTX(CALCULATETABLE(Facts,Facts[Region]="East"),1/0)` is Infinity; `MEDIANX(Facts,LN(BLANK()))` is -Infinity; `PERCENTILEX.INC(CALCULATETABLE(Facts,Facts[Region]="East"),1/0,0.5)` is Infinity. Work out IEEE double arithmetic (Inf*0, Inf-Inf, NaN ordering in a sort) the way Power BI does it.
- **Part B (143): VARX.P/S and STDEVX.P/S over Infinity or NaN.** Note `STDEVX.P(CALCULATETABLE(Facts,Facts[Region]="East"),1/0)` is 0, not NaN: Power BI's variance of identical infinities is 0. Find the rule for mixed finite/Infinity/NaN rows from the saved answers.
- **Part C (154): MAXX / MINX over a Variant body with NaN beside other numbers.** Refused because the result depends on row order (`MAXX(Facts,IF.EAGER(TRUE(),-Facts[Quantity]/0,"a"))` is NaN; `MINX(Facts,IF.EAGER(Facts[Quantity]>2,Facts[Region],Facts[Sales]/Facts[Quantity]))` is -1.5). Find how NaN compares in Power BI's MAX/MIN walk; answer only what the rule settles and refuse what depends on an unknown row order.
- **Part D (127): SUMX, COUNTX, COUNTAX, AVERAGEX over NaN beside a product with a constant zero** (`SUMX({BLANK(),1},(1/0*0)/(2.5))` is NaN; `COUNTAX(Facts,(1/0*0)*(2.5))` is 0). Power BI may fold `x*0` to 0 at compile time; find exactly when it folds.

## Rules
Compute, never look up (app code must never read `tools/parity/*.json` or test fixtures; `tests/test_no_answer_key_in_app.py` must pass). Find general rules, do not fit single expressions: Claude tests every rule on fresh Power BI formulas you have not seen, and rules that only fit the saved rows fail there. Prefer refusing over guessing. 0 wrong on the spec and 0 DIFF in the replay are mandatory: a rule that breaks one locked answer must be narrowed. Never edit saved Power BI answers or existing tests; new tests go in `tests/test_iteration129_nan_inf_iterators_29.py`. No `--freeze`, `--accept`, commit, merge, push or full pytest. Do not touch other folders.

## Done when
The scorer prints 0 wrong with as many matches as possible, `tools/parity_check.py` replay shows 0 DIFF and 0 CRASH, and a ready-for-review entry with scorer counts per Part and the replay line is in this worktree's `HANDOFF.md`. Leave changes uncommitted.

## Review outcome (2026-11-03)
Shipped as Iteration 129. Locked 457,448.
