# Task 64: type tests of a failing value (typeerr-fail-54)

**Goal:**
- Answer pending rows in `tools/parity/task64_typeerr_spec.json` (163 rows, all Part A). They refuse at measures.py ~17825, where `hidden_failure_verdict` returns "refuse".
- Fix 6 wrong answers on main (Part B), listed below.

**Evidence (measurement grid, Power BI 2026-11-06):** `$SP/t64m`
- `cand.json`: 1,500 type tests over failing values (generator `gen.py`).
- `out.txt`: Power BI answers.
- `fresh.json`: `{items:[{expr,powerbi,now}]}`.
- `main.json`: the local engine on main.
- `score.txt`: the score.

Of the 236 grid rows that hit the target refusal, Power BI gives False 163, True 36 and an error 37. So the answer depends on the shape.

**Part B, wrong on main.** Power BI raises an error and main answers False:
- `ISBLANK((ABS("m"))=("t"))`
- `ISLOGICAL((DATE("y",1,1))+(1))`
- `ISLOGICAL((DATE("y",1,1))+(DATE(2020,1,1)))`
- `ISNONTEXT(VAR v=CONVERT("z",INTEGER) RETURN v&"")`
- `ISNONTEXT(VAR v=POWER("p",2) RETURN v&"")`
- `ISTEXT((DATE("y",1,1))+(BLANK()))`

Make them show the error, or refuse.

**Method:**
1. In `$SP/t64/`, extend the shape-family logic of `hidden_failure_verdict`. The relevant features are:
   - the wrapper path: ABS(+), SWITCH(1,1,..), SWITCH(TRUE(),..), IF(1=0,..), VAR..RETURN with suffix, COALESCE, comparison, `+`, IF over a data read;
   - the failing call;
   - the kinds of the other branch or operand;
   - the type test.

   Use the grid rows and every saved battery row of a type test over a failing value as evidence; scratch scripts only.
2. Add a family to the answered set ("static type answers") or to "error" only when every evidence row of that family agrees and the family has at least 5 rows. Otherwise keep "refuse".
3. Compute, never look up. Write no expression-keyed rules.
4. Tests go in `tests/test_iteration154_typeerr_fail_54.py`: answered rows per new family, the 6 Part B rows, and one still-refused family.

**Checks after every change:**
- `tools/score_spec.py` on the spec shows 0 wrong.
- `cd worktree && PYTHONPATH=. QT_QPA_PLATFORM=offscreen python3 $SP/t64m/score.py $SP $SP/t64m/res.json | tail -1` shows 0 DIFF.
- `tools/parity_check.py` shows DIFF 0 and CRASH 0; then run `git checkout -- PARITY_LEDGER.md`.

Run the full pytest at the end. A separate held-out grid will be run by Opus afterwards.
