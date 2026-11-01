# Task 18: blank-dates-8 (a number minus a date, BLANK in `*` and `/`, LOG of BLANK, COUNTAX of a logical operator, CONVERT in MAXX, ISBLANK of Currency / 0)

**Branch:** `haiku/blank-dates-8`  **Written by:** Claude Opus 5.5, 2026-11-01  **Status:** see `HANDOFF.md`
**Who builds:** Haiku 5.5, one Part at a time, started by Opus 5.5. A Part that fails twice goes to Sonnet 5.5.

Read first: `AGENTS.md` ("Compute, never look up"). Every rule below was measured in Power BI Desktop on 2026-11-01.

## Goal
2,172 items in `tools/parity/task18_blank_dates_spec.json` (fields `part`, `battery`, `expr`, `powerbi`, and `app_answer` or `app_refusal`). 1,421 are wrong today, 751 are refused. The spec is for reading and for the scoring script; the app must never read it. Part names below match the `part` field.

## Part C (85 refused): LOG of BLANK
`LOG10(x)`, `LOG(x)` and `LOG(x,b)` with a BLANK `x` are -Infinity, exactly as `LN(BLANK())` already is, with a real base (`LOG(BLANK(),2)`). `ISBLANK` of it is False, `IFERROR` of it takes the alternate, `&"z"` gives `-infz`, `<0` is True, `MAXX` over rows is BLANK, `MINX`, `SUMX`, `AVERAGEX` are -Infinity, `COUNTX` counts the rows.
A BLANK or zero **base** stays an error: `LOG(2,BLANK())`, `LOG(BLANK(),BLANK())`. `LOG10(0)` and `LOG(0,2)` stay errors. Look at `dax_math.py` line 116 and at `LN` in `measures.py` line 2401.

## Part A (647 wrong): a number minus a date is a number
`COUNTROWS(Facts)-DATE(2020,1,1)` is -43825; the app shows a date in 1780. The result is a date only when the left side has a date type (`DATE`, `TIME`, a VAR holding a date). Otherwise it is a Double: `ISDOUBLE` True, `ISDATETIME` False, `&"z"` gives `-43825z`, and a column of `ADDCOLUMNS` holds the number. `+` is not affected: a number plus a date stays a date. Types come from `_static_numeric_type`, not from the value and not from how the expression looks. When the left side's type is not known statically, keep today's behaviour.

## Part E (118): CONVERT of a True/False column in MAXX and MINX
`MAXX({1&&""},CONVERT([Value],STRING))` is `FALSE`, `MAXX({-3||TRIM("")},CONVERT([Value],STRING))` is `TRUE`: the body is a text, as `SUMX({..},LEN(CONVERT(..)))` and `[Value]&"z"` already show. `CONVERT(..,BOOLEAN)` as a MAXX or MINX body is an error, because these cannot work with True/False. Beside a text in the constructor stays refused.

## Part D (102 refused): COUNTAX of a logical operator
`COUNTAX(Facts,1&&"")` is BLANK (the operator gives a BLANK), `COUNTAX(Facts,0&&"")` and `COUNTAX(Facts,TRUE()||"")` are 6 (True/False values). `COUNTAX(FILTER(Facts,FALSE()),..)` is BLANK. The value is what the scalar path already gives for the same operator: use it, do not write a second rule.

## Part F (86 refused): ISBLANK of Currency divided by 0
`ISBLANK(CURRENCY(1)/0)` is False, also over 0.0, BLANK and a BLANK VAR, and on a row. Only ISBLANK changes: the bare expression, `ISNUMBER` and `+1` stay errors. See `measures.py` line 290.

## Part B (1,134): BLANK in `*` and `/`
- `*`: if either operand is BLANK the result is BLANK, and the other operand is not converted or checked: `"a"*BLANK()`, `BLANK()*ERROR("x")`, `VALUE("x")*BLANK()` are BLANK.
- `/`: only a BLANK **left** operand does this: `BLANK()/"b"` and `BLANK()/ERROR("x")` are BLANK; `"a"/BLANK()` and `ERROR("x")/BLANK()` are errors.
- `+`, `-`, `^` do not change.
- `IFERROR` and `ISBLANK` around them follow: `IFERROR(BLANK()*"b","e")` is BLANK, `ISBLANK(BLANK()*"b")` is True.
- `"a"*"b"` and `"a"*1` stay errors.

## Not in Task 18
`ISBLANK` of `SIN("a")`, `FACT(-1)` and `BLANK()^BLANK()`, `ISTEXT` and `ISNUMBER` of an error, `CALCULATE(COUNTX(Facts,IF(MAX(..)>3,TRUE(),7)),..)`, a text column in `*` or `/`, `TIME(..)-DATE(..)`. No rule has been found or they are refused for a true reason.

## Rules
1. One Part at a time, in the order C, A, E, D, F, B, then stop and report. Do not start the next Part.
2. Tests first, in `tests/test_iteration107_blank_dates_8.py`. Compute expected answers from the rule above.
3. Change the fewest lines you can, and reuse what exists.
4. No rule keyed to how an expression looks. No literal text from the spec in the code. No new kind of value. A result that depends on row order stays refused.
5. A refusal raises `MeasureError` (`dax_typed.refusal`), never `MeasureRuntimeError`.
6. After each Part run the scoring script and the replay (about 2 minutes): `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python tools/parity_check.py`. It must show 0 DIFF, 0 CRASH, `locked 276203`.
7. Never run `--freeze`, `--accept`, commit, merge, push or Power BI. No global replace on `measures.py`. No edits to existing tests or saved answers: list those in your report. Scratch files go in the scratchpad.
