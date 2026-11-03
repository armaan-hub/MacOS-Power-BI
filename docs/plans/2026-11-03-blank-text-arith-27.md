# Task 37 blank-text-arith-27: BLANK from && / || and text conversion in arithmetic (2,020 saved answers the engine refuses)

**Coder:** Antigravity. **Work folder:** git worktree `/Users/armaan/Power BI tool-task37` (branch `antigravity/blank-text-arith-27`). Work ONLY there.
**Spec:** `tools/parity/task37_blank_text_arith_spec.json`: 2,020 Power BI answers already saved in the locked batteries (`dax_battery_convert9_extra`, `blank8_extra`, `strict6_extra`, `currency11_extra`, `never10_extra`) that the engine refuses today. Score with `PYTHONPATH=. python3 tools/score_spec.py tools/parity/task37_blank_text_arith_spec.json`.

- **Part A (829):** refused with "A logical operator's BLANK beside a BLANK, a text or an error in arithmetic is not modelled". `x && ""` and `x || ""` give BLANK in Power BI; that BLANK then meets text, BLANK or an error in `+ - * /`, `&`, `^`, COALESCE, IFERROR, type tests and iterators. Examples: `COALESCE((2.5&&"")*(""),5)` is BLANK; `ISDOUBLE(("2")*(1&&""))` is True; `((1&&"")/(""))&"z"` is `z`; `IFERROR(((IF(1=1,1)&&""))+"a",7)` is 7.
- **Part B (478):** refused with "A logical operator that gives BLANK beside another branch of a conditional is not modelled": the same BLANK as one branch of IF / IF.EAGER / SWITCH, seen by COUNTX, COUNTAX, MAXX, ADDCOLUMNS columns and conditions. Examples: `COUNTAX(ROW("Value",1),IF(1=1,1&&"","a"))+1` is 1; `SUMX(Facts,IF(SWITCH(TRUE(),FALSE(),"a","0"||LEFT("a",0)),1,2))` is 12.
- **Part C (713):** refused with "Cannot convert value '…' of type Text to type Number." while Power BI answers: text meeting BLANK or another text in arithmetic. Examples: `ISNUMBER(("")*("a"))` is True; `(MAX(BLANK(),BLANK()))*(VALUE("x"))` is BLANK; `ISDOUBLE(BLANK()-"abc")` is True; `ISNUMBER("a"^2)` is True; `ISDOUBLE(DATE(2021,3,4)+"TRUE")` is False. Find the rule (when is a text operand never converted, what is the result type), do not special-case expressions.

Read the saved answers as data to discover the rules, then implement general rules in the engine's arithmetic/type code. Many of these rows probably share one or two underlying rules (when an arithmetic operand is BLANK, whether the other operand is converted at all; what type the result has). Where the rows do not settle a case, keep refusing it.

## Rules
Compute, never look up (app code must never read `tools/parity/*.json` or test fixtures; `tests/test_no_answer_key_in_app.py` must pass). 0 wrong on the spec and 0 DIFF in the replay are mandatory: a rule that fixes 500 rows and breaks one locked answer is not acceptable; narrow it. Never edit saved Power BI answers or existing tests; new tests go in `tests/test_iteration127_blank_text_arith_27.py`. No `--freeze`, `--accept`, commit, merge, push or full pytest. Do not touch other folders.

## Done when
The scorer prints 0 wrong with as many matches as possible, `tools/parity_check.py` replay shows 0 DIFF and 0 CRASH, and a ready-for-review entry with scorer counts per Part and the replay line is in this worktree's `HANDOFF.md`. Leave changes uncommitted.
