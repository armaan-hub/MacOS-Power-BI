# Task 27 logical-blank-17: a logical operator's BLANK beside other values (2,763 refusals become answers)

**Coder:** Antigravity. **Work folder:** git worktree `/Users/armaan/Power BI tool-task27` (branch `antigravity/logical-blank-17`). Work ONLY there.
**Spec:** `tools/parity/task27_logical_blank_spec.json`: 2,763 Power BI answers that are already saved (in the batteries named in each item's `battery` field) and that the engine refuses today with "A logical operator ... BLANK ... is not modelled". Part A (1,831): the logical BLANK beside another branch of a conditional (IF, SWITCH, COALESCE, IF.EAGER). Part B (932): the logical BLANK beside a BLANK, a text or an error in arithmetic.

## Background
`x && ""`, `x || ""`, `AND(x,"")`, `OR(x,"")` with an empty text give a typed BLANK whose behaviour Power BI decides by context (Tasks 12, 14, 18, 21 modelled parts of it; see the HANDOFF open questions and `git log --grep "logical"`). Examples: `LEN(SWITCH(TRUE(),FALSE(),OR(0,""),OR(0,"")))` = BLANK; `ISDATETIME((0||"")-(MAX(Facts[Note])))` = False; `SUMX(FILTER(Facts,Facts[Quantity]>2),(2.5&&"")*("2")*("a"))` = BLANK.

## Goal
Turn as many refusals as possible into the measured answers with general rules (group the rows, find the rule per group, implement it, check the group). Every row you cannot settle with a rule stays refused. 0 wrong is mandatory; the number of refusals left is the score.

## Rules
Compute, never look up (app code never reads tools/parity/*.json or tests/fixtures*.json; the spec is scorer input only). Never edit saved Power BI answers or existing tests. No --freeze/--accept/commit/merge/push/full pytest. These answers are already in the saved batteries, so the replay counts them: they move from `gap-reject` to `match`. The replay must stay 0 DIFF, 0 CRASH, PARITY GATE PASSED (then `git checkout PARITY_LEDGER.md`).

## Commands (in the worktree)
Scorer: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python3 tools/score_spec.py tools/parity/task27_logical_blank_spec.json [A|B]`. Tests: `tests/test_iteration117_logical_blank_17.py` (a sample per rule). When done, leave changes uncommitted and write a ready-for-review entry in this worktree's `HANDOFF.md` with scorer counts per Part and the replay line.

## Review outcome (2026-11-03)
Shipped as Iteration 117. Locked 440,890.
