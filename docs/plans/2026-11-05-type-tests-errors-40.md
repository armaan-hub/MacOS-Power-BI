# Task 50 type-tests-errors-40: type tests and BLANK tests of a failing value (Power BI answers, the engine raises or refuses)

**Coder:** Haiku (haiku-builder). **Fixer/reviewer:** Sonnet (sonnet-fixer). **Planner:** Opus.
**Work folder:** git worktree `/Users/armaan/Power BI tool-task50` (branch `antigravity/type-tests-errors-40`). Work ONLY there.
**Spec:** `tools/parity/task50_type_tests_errors_spec.json`: saved Power BI answers (locked batteries) that the engine gets as an error or a refusal today. Score with `PYTHONPATH=. QT_QPA_PLATFORM=offscreen /usr/local/bin/python3 tools/score_spec.py tools/parity/task50_type_tests_errors_spec.json`.

- **Part A:** the engine raises a DAX error ("Cannot convert value ... to type Number", "An argument of function ... wrong data type", "A division by zero", "MOD cannot divide by zero", "x" from ERROR) where Power BI answers, almost always a type test or ISBLANK around the failing value: `ISLOGICAL((FACT(-1))*(2.5))` is False, `ISTEXT((MOD(1,0))*(""))` is False, `ISNONTEXT(NOT("a"))` is True, `VAR q=(COUNTROWS(FILTER(Facts,FALSE())))*(FACT(-1)) RETURN ISBLANK(q)` is True, `"a"||VAR y=1 RETURN ...` is True.
- **Part B:** the engine refuses "A type test of a failing value Power BI may raise the error for" / "A type test of arithmetic around a failing power".

**Lead (Opus):** Task 41 (Iteration 131) started this: see `hidden_failure_verdict` and `static_type_answer` in `measures.py` and the type-test rules there. Power BI type-checks the expression statically: ISTEXT/ISNUMBER/ISLOGICAL/ISCURRENCY/ISDATETIME/ISDOUBLE/ISNONTEXT of an expression whose static result type is known answer from the type without evaluating the failing operand; a BLANK operand under * / can cancel the failure (BLANK()*error is BLANK). Measure each rule on the spec rows before using it, keep it structural (node kinds and static types, at least 5 supporting rows per rule), and keep refusing any group with even one row that does not fit. Task 41's lesson: rules keyed on function names over-fit and broke on fresh shapes.

## Rules
Compute, never look up (app code must never read `tools/parity/*.json` or test fixtures; `tests/test_no_answer_key_in_app.py` must pass). 0 wrong required; a refusal is acceptable. Do not edit saved Power BI answers or existing tests (report any existing test that asserts a refusal or error this task answers); new tests go in `tests/test_iteration140_type_tests_errors_40.py`. No `--freeze`, `--accept`, commit, merge or push.

## Done when
The scorer prints 0 wrong with as many matches as possible, `tools/parity_check.py` replay (no `--tests`) shows 0 DIFF and 0 CRASH, and a ready-for-review entry with scorer counts per Part and the replay line is appended to this plan.

## Review outcome (2026-11-05)
Shipped as Iteration 140. Locked 476211.
