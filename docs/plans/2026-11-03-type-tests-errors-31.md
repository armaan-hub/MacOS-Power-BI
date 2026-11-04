# Task 41 type-tests-errors-31: type tests and errors Power BI does not raise (893 saved answers the engine refuses)

**Coder:** Antigravity. **Work folder:** git worktree `/Users/armaan/Power BI tool-task41` (branch `antigravity/type-tests-errors-31`). Work ONLY there.
**Spec:** `tools/parity/task41_type_tests_errors_spec.json`: 893 Power BI answers already saved in the locked batteries. Today the engine raises an error for each (or refuses), but Power BI gives a value. Score with `PYTHONPATH=. python3 tools/score_spec.py tools/parity/task41_type_tests_errors_spec.json`.

- **Part A (668): IS* type tests (ISTEXT, ISNONTEXT, ISNUMBER, ISLOGICAL, ISINT64, ISINTEGER, ISDOUBLE, ISDECIMAL, ISCURRENCY, ISDATETIME, ISBOOLEAN, ISSTRING, ISNUMERIC, ISBLANK) of an expression whose evaluation fails.** Examples: `ISTEXT(MOD(1,0))` is False; `ISNUMBER(("")*(MOD(1,0)))` is True; `ISNUMBER((MOD(1,0))&(MAX(Facts[Note])))` is False; `ISNUMBER((VAR y=VALUE("x") RETURN y)+("b"))` is True; `ISLOGICAL(AND("1",MIN(Facts[Note])&""))` is True; `ISCURRENCY(CONVERT(MAX(Facts[Region]),INTEGER))` is False. It looks like Power BI answers these from the expression's static (compile-time) result type without evaluating it, but some answers contradict that (check the engine's existing Task 37 rule `_isnumber_blank_text` for ISNUMBER of failing text arithmetic, which says True only when all parts fold). Find exactly when the static type decides and when the error propagates; refuse what the rows do not settle.
- **Part B (225): other places where an error is not raised in Power BI:** `YEAR(DATE(1899,12,30)+-1/0)` is 1899, `COALESCE((COUNTROWS(FILTER(Facts,FALSE())))*(MAX(Facts[Note])),5)` is 5, `SUMX({BLANK(),1},(COUNTROWS(FILTER(Facts,FALSE())))/(INT("a")))` is BLANK (BLANK times or divided by a failing value), `VAR y=BLANK() RETURN y==OR(0,"")` is True, `ROUND("2020-01-02",0)` is 43832. Find the general rules (BLANK short-circuits, how Infinity/NaN become dates, etc.).

## Rules
Compute, never look up (app code must never read `tools/parity/*.json` or test fixtures; `tests/test_no_answer_key_in_app.py` must pass). Find general rules, do not fit single expressions or literal values: Claude tests every rule on fresh Power BI formulas you have not seen. Prefer refusing over guessing. 0 wrong on the spec and 0 DIFF in the replay are mandatory: a rule that breaks one locked answer must be narrowed. Never edit saved Power BI answers or existing tests; new tests go in `tests/test_iteration131_type_tests_errors_31.py`. No `--freeze`, `--accept`, commit, merge, push or full pytest (`parity_check.py --tests` is not needed; run the replay without `--tests`). Do not touch other folders.

## Done when
The scorer prints 0 wrong with as many matches as possible, `tools/parity_check.py` replay (no `--tests`) shows 0 DIFF and 0 CRASH, and a ready-for-review entry with scorer counts per Part and the replay line is in this worktree's `HANDOFF.md`. Leave changes uncommitted.

## Review outcome (2026-11-04)
Shipped as Iteration 131. Locked 462,852.
