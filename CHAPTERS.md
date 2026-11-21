# Chapters

How chapters work: `docs/plans/2026-11-17-chapters.md`. A closed chapter gets no new features; its saved Power BI answers keep running in the gate, and a break is a regression fixed at once. Saved Power BI answers are never edited.

| # | Chapter | State | Tag | Close report |
|---|---|---|---|---|
| 1 | DAX engine baseline | Closed 2026-11-17 | `chapter-1-dax-baseline` | `docs/chapters/chapter-1.md` |
| 1b | DAX gaps (the 3,039 pending DAX answers) | Open (waiting) | | |
| 2 | Data import and project file | Done list to write | | |
| 3 | Power Query editor screens | Open (current) | | |
| 4 | Power Query M functions | Not started | | |
| 5 | Report view ribbon tabs | Partly built | | |
| 6 | Speed | Not started | | |

## Chapter 1b: DAX hunt, Tasks 184 to 246, closed 2026-11-21

The Chapter 1 section below says a closed chapter gets no new features and that Chapter 3 is current. That is still true for Chapter 1's saved answers: they keep running in the gate and are never edited. But Tasks 184 to 246 (the DAX hunt) changed the Chapter 1 DAX engine after 2026-11-17: they fixed wrong answers and added modelled cases against Power BI answer checks. So Chapter 1 was closed as a baseline, and the hunt that followed is recorded here as Chapter 1b. It ended with Task 246 (merged 60e11eb). The table row "1b DAX gaps" above is the same open work, now handled by the phases below.

New phases from `docs/plans/2026-11-21-team-plan.md` (approved 2026-11-21):
- **Phase 0:** freeze the hunt data into battery files and lock it.
- **Phase 1:** the DAX exit test (one realistic model, about 400 formulas, 0 wrong, 0 crash, at least 97% answered).
- **Stages A to F (speed and scale):** `docs/plans/2026-11-21-scale-plan-v2.md`. Stage A may run beside Phase 0 and Phase 1.
- **Phase 4:** Power Query M functions, running beside Stage D.
- **Phase 5:** report view, after Stage C4.
Chapter 3 (Power Query editor screens) is paused behind these phases, not dropped.

## Chapter 1: DAX engine baseline (closed 2026-11-17)

**Works (locked):** every saved Power BI DAX answer that our app matches.
- Fresh full gate, 2026-11-17 on main `0dd9189`: 540,401 answers replayed; 537,362 match, 0 differ, 0 crash; lock 537,342 ids. (537,362 matching rows = 537,341 unique ids, because 15 expressions repeat with 21 extra rows, + 1 stale locked id no longer in the batteries = 537,342. Every matching answer is locked.)
- Real app run: 575 measures created through the app, 575 equal to Power BI, 0 different.
- pytest: 5,039 passed, 26 xfailed; 2 tests fail only beside other tests and pass alone (`test_whole_number_functions_enforce_signed_int64_range`, `test_group_and_pivot_reject_error_keys_and_typed_category_collisions`).
- Known deviations (imprecise or unspecified in Power BI, each explained): 14, in `tools/parity/known_deviations.json`.

**Not done (moved to Chapter 1b, "DAX gaps"):** 3,039 answers where Power BI gives a value and our app refuses (`gap-reject`). These are unfinished work, not refusals on purpose. Largest groups by leading function (about; counted after stripping a leading VAR…RETURN): MAXX 588, TOCSV 242, CALCULATE 214, CONCATENATEX 185, MINX 133, SUMX 124, COUNTROWS 104, ISLOGICAL 102, the IS* type tests (~650 together), STDEVX/VARX 191, XIRR 47, TOJSON 36. Full list: `PARITY_LEDGER.md`, section "Pending work".

**Out of scope for Chapter 1:** Power Query M, UI screens, speed, DAX shapes never saved from Power BI ("Not yet compared" in `PARITY_LEDGER.md`).
