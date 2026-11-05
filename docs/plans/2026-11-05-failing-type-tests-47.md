# Task 57 failing-type-tests-47: type tests of a failing value, leftovers (Power BI answers, the engine raises or refuses)

**Coder:** Haiku (haiku-builder). **Fixer/reviewer:** Sonnet (sonnet-fixer). **Planner:** Opus.
**Work folder:** git worktree `/Users/armaan/Power BI tool-task57` (branch `antigravity/failing-type-tests-47`). Work ONLY there.
**Spec:** `tools/parity/task57_failing_type_tests_spec.json` (521 rows): saved Power BI answers that the engine gets as an error or a refusal today. Score with `PYTHONPATH=. QT_QPA_PLATFORM=offscreen /usr/local/bin/python3 tools/score_spec.py tools/parity/task57_failing_type_tests_spec.json [PART]`.

- **Part A (118):** ISLOGICAL / ISBOOLEAN around a failing value, e.g. `ISLOGICAL((("a")*(2))||(MAX(Facts[Note])))` is True, `ISLOGICAL(OR(MIN(Facts[Note])&"",0))` is True, `SUMX(Facts,IF(ISLOGICAL(1&&Facts[Note]),1,0))` is 6.
- **Part B (226):** number and date type tests (ISNUMBER, ISDOUBLE, ISINT64, ISCURRENCY, ISDECIMAL, ISINTEGER, ISDATETIME), e.g. `ISDOUBLE((MAX(Facts[Note]))-(BLANK()&&BLANK()))` is True, `ISINT64((MAX(Facts[Note]))*("a"))` is False, `ISCURRENCY("abc"+CURRENCY(MAX(Facts[Sales])))` is False, `ISDATETIME(("a")*(VAR y=1/0 RETURN y))` is False, `ISNONTEXT(INT(CONVERT("z",INTEGER)))` is True.
- **Part C (121):** ISTEXT / ISNONTEXT / ISSTRING / ISBLANK around a failing value.
- **Part D (56):** no type test: the failing value is cancelled or never evaluated, e.g. `"a"||VAR y=1 RETURN COUNTROWS(FILTER(Facts,y=1))`, `COUNTROWS({1&&MIN(Facts[Note])&"",...})`, `MAXX({1,2},("a"*2)*(COUNTROWS(FILTER(Facts,FALSE()))))`.

**Lead (Opus):** Tasks 41 and 50 (Iterations 131 and 140) answered most of this family; read `hidden_failure_verdict`, `static_type_answer` and `_structural_type_answer` in `analytics_studio/measures.py` and the plans `docs/plans/2026-11-05-type-tests-errors-40.md` first. These rows are what those rules still refuse. Power BI type-checks statically: the answer comes from the static result type of the expression (`*` `-` `+` `/` of a text give Double; `||` `&&` OR AND give Boolean; `&` gives Text; INT gives Int64), without evaluating the failing operand. Find which node shapes the existing rules do not cover (group the refused rows by their refusal site), extend the structural rules for those shapes only, measure each rule on the spec rows first (at least 5 supporting rows, no contradicting row), and keep refusing any group with even one row that does not fit. Rules keyed on function names over-fit and broke on fresh shapes before.

## Rules
Compute, never look up (app code must never read `tools/parity/*.json` or test fixtures; `tests/test_no_answer_key_in_app.py` must pass). 0 wrong required; a refusal is acceptable. Do not edit saved Power BI answers or existing tests (report any existing test that asserts a refusal or error this task answers); new tests go in `tests/test_iteration147_failing_type_tests_47.py`. No `--freeze`, `--accept`, commit, merge or push. Use `-p no:cacheprovider` for pytest.

## Done when
The scorer prints 0 wrong with as many matches as possible, `tools/parity_check.py` replay (no `--tests`) shows 0 DIFF and 0 CRASH, and a ready-for-review entry with scorer counts per Part and the replay line is appended to this plan.

## Review outcome (2026-11-05)
Shipped as Iteration 146. Locked 481961.
