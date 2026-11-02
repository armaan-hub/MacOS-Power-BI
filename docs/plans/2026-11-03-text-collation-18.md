# Task 28 text-collation-18: ordering and comparing text with non-ASCII characters (1,657 refusals)

**Coder:** Antigravity. **Work folder:** git worktree `/Users/armaan/Power BI tool-task28` (branch `antigravity/text-collation-18`). Work ONLY there.
**Spec:** `tools/parity/task28_text_collation_spec.json`: 1,657 Power BI answers already saved (battery `dax_battery_misc3_extra2`) that the engine refuses. Part A (1,456): ordering (`<`, `<=`, `>`, `>=`, ISAFTER, MAX/MIN, sort) of text with non-ASCII characters. Part B (201): equality of text that differs only in composed, decomposed or expanded characters (`"ſ"<>"á"`, `"ḑ̌"="ḑ̌"`).

## Why it matters
Real data has accents and other scripts (names, cities). Today any comparison or sort of such text refuses.

## Background
Power BI compares text case-insensitively with a Windows culture-aware collation (VertiPaq; en-US). Task 10 Part D modelled a Latin subset (ligature expansion `æ`, `œ`, `ß`, `ǆ`, `ĳ`, NFD decomposition, primary base letter, secondary accent) and refuses the rest; see `docs/plans/2026-10-29-scalar-misc-3.md` and the code it added (search `collation` / `ligature` in analytics_studio). Examples: `"r̋̀"<"y"` True, `"ı"<="c"` False, `"čûúï"<"ð"` True, `"ſ"<>"á"` True, `"ḑ̌"="ḑ̌"` True.

## Goal
Derive the comparison rules from the spec rows (primary weights per letter including dotless ı, ð, ŉ, ǌ, long s ſ; how combining marks and their order count; ties broken by accents, then case?) and implement them in pure Python (PyICU is not installed; do not add dependencies). Turn as many refusals as possible into the measured answers; whatever the rules do not settle stays refused. 0 wrong is mandatory. Then Claude probes fresh strings in Power BI to check the rules generalize, so prefer real rules over per-character patches.

## Rules
Compute, never look up (app code never reads tools/parity/*.json or tests/fixtures*.json). Never edit saved Power BI answers or existing tests. No --freeze/--accept/commit/merge/push/full pytest. The replay must stay 0 DIFF, 0 CRASH, PARITY GATE PASSED (`PYTHONPATH=. QT_QPA_PLATFORM=offscreen caffeinate -i python3 tools/parity_check.py`, then `git checkout PARITY_LEDGER.md`).

## Commands (in the worktree)
Scorer: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python3 tools/score_spec.py tools/parity/task28_text_collation_spec.json [A|B]`. Tests: `tests/test_iteration118_text_collation_18.py`. When done, leave changes uncommitted and write a ready-for-review entry in this worktree's `HANDOFF.md` with scorer counts per Part and the replay line.
