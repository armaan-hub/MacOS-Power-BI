# Task 30 static-types-20: static types the engine cannot establish yet (1,070 refusals)

**Coder:** Antigravity. **Work folder:** git worktree `/Users/armaan/Power BI tool-task30` (branch `antigravity/static-types-20`). Work ONLY there.
**Spec:** `tools/parity/task30_static_types_spec.json`: 1,070 Power BI answers already saved (battery in each item) that the engine refuses. Each item's `now` field holds today's refusal message.
- Part A (551): "Cannot determine static type for function ISDOUBLE / ISINT64 / ISCURRENCY / …": type tests of arithmetic over dates, times, VAR blocks, logical BLANKs and failing values, e.g. `ISINT64((TIME(1,0,0))+(VAR d=DATE(2020,1,1) RETURN d))` = False, `ISCURRENCY((MAXX({DATE(2020,1,1)},[Value]))-(MAX(BLANK(),DATE(2020,1,1))))` = False, `ISDOUBLE((VAR y=1/0 RETURN y)*(1&&"")*(FALSE()))` = False.
- Part B (265): "== needs operands of a known type": strict equality beside VAR blocks and logical BLANKs, e.g. `IFERROR(VAR y=BLANK() RETURN y==0,7)` = False, `(IF(TRUE(),OR(0,""),1))==FALSE()` = False.
- Part C (254): "COALESCE with branches whose types the local engine cannot establish": e.g. `COUNTAX(ADDCOLUMNS(Facts,"q",COALESCE(OR(0,""),"a")),[q])` = BLANK, `MAXX(Facts,COALESCE(1,INT("a"),"x"))` = 1.

## Goal
The engine infers static types in `left_static_type` / `dax_typed` (see earlier tasks: Task 15 typed-columns-5, Task 16 strict-types-6). Extend the type inference so these shapes get the type Power BI gives them (date - date is a date? date + time? a VAR block takes its RETURN's type; a logical BLANK is True/False; COALESCE joins its branch types), then compute the answers. Turn as many refusals as possible into the measured answers; unsettled rows stay refused. 0 wrong is mandatory. Claude then measures fresh shapes in Power BI, so prefer general typing rules over per-shape patches, and do not widen a rule beyond what the rows show.

## Rules
Compute, never look up (app code never reads tools/parity/*.json or tests/fixtures*.json). Never edit saved Power BI answers or existing tests. No --freeze/--accept/commit/merge/push/full pytest. The replay must stay 0 DIFF, 0 CRASH, PARITY GATE PASSED (`PYTHONPATH=. QT_QPA_PLATFORM=offscreen caffeinate -i python3 tools/parity_check.py`, then `git checkout PARITY_LEDGER.md`).

## Commands (in the worktree)
Scorer: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python3 tools/score_spec.py tools/parity/task30_static_types_spec.json [A|B|C]`. Tests: `tests/test_iteration120_static_types_20.py`. When done, leave changes uncommitted and write a ready-for-review entry in this worktree's `HANDOFF.md` with scorer counts per Part and the replay line.
