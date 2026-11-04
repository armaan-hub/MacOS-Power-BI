# Task 45 xnpv-blank-swi-35: XNPV with Currency, BLANK beside failing iterators, FIRSTNONBLANK/SUBSTITUTEWITHINDEX of derived tables (190 saved answers the engine refuses)

**Coder:** Antigravity. **Work folder:** git worktree `/Users/armaan/Power BI tool-task45` (branch `antigravity/xnpv-blank-swi-35`). Work ONLY there.
**Spec:** `tools/parity/task45_xnpv_blank_swi_spec.json`: 190 Power BI answers already saved in the locked batteries that the engine refuses today. Score with `PYTHONPATH=. python3 tools/score_spec.py tools/parity/task45_xnpv_blank_swi_spec.json`.

- **Part A (34): XNPV whose values are Currency** (beside a column of unknown type, or a Currency that is BLANK). Examples: `XNPV(ADDCOLUMNS(Facts,"d",DATE(2020,1,1)+Facts[Quantity]),CURRENCY(Facts[Sales])*1.00005,[d],0)` is 31.5015 (a Currency result: four decimals); some DATATABLE cases give a Double (12.9717745468827). Find when XNPV's result is Currency (rounded to four decimals) and when Double, and how a BLANK Currency value counts.
- **Part B (113): BLANK times a failing iterator.** `(IF(FALSE(),1))*(MAXX(Facts,ERROR("x")))` is BLANK; `COUNTX(Facts,(DIVIDE(1,BLANK()))*(SUMX(Facts,ERROR("x"))))` is BLANK; `MAXX({1,2},(SUMX(Facts,ERROR("x")))*(SELECTEDVALUE(Facts[Quantity])))` is BLANK. Refused with "Iterator SUMX/MAXX expression needs a numeric result" or "Iterator arithmetic comparisons need numeric operands". Find exactly when a BLANK operand stops the error of the other operand being raised (Task 41, under review in another worktree, studies the same rule for scalar failures; keep your rule consistent with the shipped engine and narrow).
- **Part C (43): FIRSTNONBLANK over ROW/derived tables, SUBSTITUTEWITHINDEX with a renamed column.** `FIRSTNONBLANK(ROW("a",2^50&""),1)` is 1.12589990684262E+15 (the column value as Power BI shows the text); `MAXX(SUBSTITUTEWITHINDEX(SELECTCOLUMNS(Facts,"Facts[Region]",Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region]),[i])` is 2 (a SELECTCOLUMNS name that spells a column reference matches it). Refused with "FIRSTNONBLANK needs values that come from a column of the model." and "Function SubstituteWithIndex() is not able to detect common columns…".

## Rules
Compute, never look up (app code must never read `tools/parity/*.json` or test fixtures; `tests/test_no_answer_key_in_app.py` must pass). Find general rules, do not fit single expressions or literal values: Claude tests every rule on fresh Power BI formulas you have not seen. Prefer refusing over guessing. 0 wrong on the spec and 0 DIFF in the replay are mandatory: a rule that breaks one locked answer must be narrowed. Never edit saved Power BI answers or existing tests; new tests go in `tests/test_iteration135_xnpv_blank_swi_35.py`. No `--freeze`, `--accept`, commit, merge, push or full pytest (run `tools/parity_check.py` without `--tests`). Do not touch other folders, and do not write files outside this worktree.

## Done when
The scorer prints 0 wrong with as many matches as possible, `tools/parity_check.py` replay (no `--tests`) shows 0 DIFF and 0 CRASH, and a ready-for-review entry with scorer counts per Part and the replay line is in this worktree's `HANDOFF.md`. Leave changes uncommitted.

## Review outcome (2026-11-04)
Shipped as Iteration 135. Locked 468,717.
