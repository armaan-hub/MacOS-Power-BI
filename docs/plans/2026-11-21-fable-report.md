# Analytics Studio: independent investigation (Fable 5.2, 2026-11-21)

Read-only. Nothing in `/Users/armaan/Power BI tool` was changed. No git state command, no full gate, no Power BI, no VM.
Words used: "Power BI answer check" = the same formula run in real Power BI and in the app.
Labels: **confirmed**, **wrong**, **unchecked**, **(guess)**.

## Step 1: Is the brief true?

| Claim in FABLE_BRIEF.md | Verdict | Evidence |
|---|---|---|
| 1,288 commits on main before the Task 245 merge | confirmed | `git rev-list --count 2f62083^1` = 1288; main is now 1291 |
| Task 245 merged as 2f62083, docs as 33781ac | confirmed | `git log --oneline main` |
| Task 246 is being coded now | confirmed | current branch `antigravity/dax-errors-variant-246`, `measures.py` modified |
| Branch name for Task 246 | small mismatch | brief246.md says `...-variant-builders-246`; the real branch is `...-variant-246` |
| pytest 41,261 passed, about 36 minutes | confirmed | `/Users/armaan/pbi_scratch/gate245*.log`: "41261 passed, 26 xfailed ... 2148.01s" |
| Real app 575/575 | confirmed (from the log) | same log: "575 created ... 575 equal to Power BI, 0 different" |
| 540,401 saved answers, 0 different | unchecked by me | taken from the docs and the merge message; I did not run the 36-minute gate |
| The engine computes; it never looks up saved answers | confirmed | no run-time read of `tools/parity` or `dax_battery` in `analytics_studio/`; only comments mention them |
| "The local M engine knows about 76 standard-library names" | **wrong** | `analytics_studio/m_engine/stdlib.py` `GLOBALS` has 651 names; 502 of the 932 names in `pbi_library_names.py` exist locally. Whether each one computes correctly is unchecked |
| "No xfail in tests" | not fully true | the suite reports 26 xfailed |
| Chapter 1 closed, Chapter 3 open (current) but paused | confirmed, and it is a contradiction | `CHAPTERS.md` says a closed chapter "gets no new features", yet Tasks 215 to 246 all change the Chapter 1 DAX engine |

## Step 2: What does the app do today?

Source: `POWER_BI_FUNCTIONALITY_ROADMAP.md` lines 1009 to 1020 (the team's own status table) plus the code files.

| Feature | State | Proof |
|---|---|---|
| Data import: CSV, Excel (.xls/.xlsx/.xlsm), JSON, XML, Parquet, Folder, SQLite, SQL Server, OData, Web | partial (works for these types) | `analytics_studio/file_import.py:189-199`, `sql_server.py`, `odata.py`, `web_import.py`, `folder_import.py` |
| Power Query editor (steps, dialogs, M editor) | partial | `transformations.py` (4,167 lines), `power_query_m.py` (4,760), `local_table_dialogs.py` (13,352), `m_engine/` |
| M engine | partial | 651 global names, 502 of Power BI's 932. Most of the 430 missing names are connectors (Access, Amazon, Azure ...) |
| Data model and relationships | partial | `relationships.py` (1,665), `relationship_dialog.py`, `qml/ModelView.qml` |
| DAX measures | strong on small data, see Step 3 | `measures.py` (26,531 lines) plus 20 `dax_*.py` files |
| Report visuals | partial | `qml/ChartCard.qml` (2,436): column/line combos, scatter, map, matrix, table, card, slicer, KPI, gauge |
| Save and open | works, own format | `project.py:1846,1885` (`.npa`). No PBIX or PBIP |
| Publishing, sharing, RLS, mobile | missing | roadmap table, "Unavailable" rows |

App start: I did not launch the app myself (to avoid writing settings files while the other team works). The gate log shows the real app created 575 measures offscreen. So it starts and works offscreen: confirmed from the log, not by my own run.

## Step 3: How good is the DAX engine?

**Correctness on small tables: very good.** 537,896 of 540,401 saved answers match, 0 differ (docs; unchecked by me).

**Structure: weak and getting weaker.**
- `measures.py` is one file of 26,531 lines, 669 functions. `evaluate()` alone is 2,933 lines; `table_function_rows()` is 1,025 lines.
- The last 5 merges added 7,465 lines (code plus tests) in 2 days. They are not general rules. They are patches that match one formula shape. Example from Task 245 (`git diff 2f62083^1 2f62083 -- analytics_studio`):
  - `_flatten_derived_summarize`: recognises exactly `SUMMARIZE(SUMMARIZE(T, c1, c2), c1, "n", e)` where `e` reads ALLSELECTED, and rewrites it.
  - `_nested_builder_refusal`: a list of formula shapes that are refused because "no rule was measured".
  - The docstrings carry task numbers ("Task 245 (measured)"). The code is a log of patches.
- This means the engine does not hold a model of *why* Power BI gives an answer. It holds a list of shapes. A new shape is a new patch.

**Proof that the hunt does not converge.** Each review probes about 300 fresh shapes. Wrong answers on main *before* each fix:
- Task 243 review: 11 wrong of 310.
- Task 244 review: 18 wrong of 300 (6%), 90 refused (30%).
- Task 245 review: 40 wrong of 315 (12.7%), 22 refused.
After 60 hunt tasks, a new family of shapes still shows 6 to 13% wrong. The space of DAX shapes has no end. This approach has no finish line.

**Speed: the biggest hidden problem.** All 540,401 answers are measured on a table of **6 rows** (`tools/dax_oracle_diff.py:24`, `LOCAL_ROWS`). I timed the engine on larger tables (in memory, read-only):

| Formula | 10,000 rows | 100,000 rows |
|---|---|---|
| `SUM(Facts[Sales])` | 0.01 s | 0.06 s |
| `SUMX(Facts, Facts[Sales]*Facts[Quantity])` | 0.56 s | **6.7 s** |
| `SUMX(VALUES(Facts[Region]), CALCULATE(SUM(Facts[Sales])))` | 0.06 s | 0.71 s |
| `SUMX(Facts, CALCULATE(SUM(Facts[Sales])))` | **20.6 s at only 2,000 rows** | not usable |

The last row grows with the square of the row count. At 100,000 rows it would take hours (guess from the growth rate). One visual needs one answer per cell, so a matrix with 50 cells multiplies these times by 50. Power BI answers these in milliseconds. `CHAPTERS.md` lists "6 Speed: Not started".

**Coverage gaps in the saved answers.** Counted in `tools/parity/dax_battery_*.json`:
- `TOTALYTD(`, `SAMEPERIODLASTYEAR(`, `DATEADD(`, `DATESYTD(`: **0** saved answers in the replayed batteries. (Some measured fixtures exist in `tests/fixtures_iter84_time_intel.json`.)
- `RELATED(`: 170. `USERELATIONSHIP`: 9.
- `TOPN(`: 21,142. `RANKX(`: 4,503.
The half million answers are deep on one flat table and thin on what business users write most: time intelligence and star-schema models.

## Step 4: Are the tests and the proof trustworthy?

**What "PARITY GATE PASSED" checks** (`tools/parity_check.py:80-86, 283-290`):
- Fails on: a different answer, a crash, or a locked answer that stops matching.
- Does **not** fail on a new refusal of an answer that is not locked ("gap-reject" is only listed).
- "Power BI gives an error + the app refuses" counts as a **match** (line 83). So a refusal for the wrong reason can pass.

**Good points.**
- Test files hold literal answers measured in Power BI (`tests/test_dax_nested_builders_245.py`). They do not repeat the code's own output. This is real proof.
- No answer lookup at run time.
- The review compares branch and main on fresh probes. This is a sound method.

**Weak points.**
- Saved answers stopped growing: 540,401 since 2026-11-17. `git log --since=2026-11-17 -- tools/parity` shows 0 changed files. Locked stays at 537,342 while 537,896 match, so 554 matches are not locked.
- All hunt probe data since then lives in `/Users/armaan/pbi_scratch` (5.1 GB, 23 folders), outside git. It is not backed up and the gate does not replay it. Only the few rows copied into pytest files are protected.
- Refusal share on saved answers is low (2,505 of 540,401 = 0.5%). On fresh probes it is 16 to 30%. The low number comes from the batteries being old shapes the engine was built on. Nobody has measured the refusal rate on formulas real users write. That is the number that matters.
- Tests grew from 5,039 (2026-11-17, `CHAPTERS.md`) to 41,261 in 4 days. The gate takes 36 minutes per task.

## Step 5: Is the team working on the right thing?

No. Evidence:
- Cost: about 31 merged tasks from 2026-11-17 to 11-21. Each one costs a brief, a coder run, about 300 Power BI probes, a 36-minute gate, a review, and edits to 5 doc files.
- Gain: pending refusals went from 3,039 to 2,505 in that time. The wrong rate on fresh shapes did not fall (Step 3).
- The shapes are machine-generated, for example `CALCULATE(ISBOOLEAN(SWITCH(TRUE(),HASONEVALUE(...),SUMX(SUMMARIZECOLUMNS(...COALESCE(MIN(Facts[Note]),"none"))...` Nobody writes this in a report.
- Meanwhile: speed is not started, time intelligence has 0 replayed answers, the report UI is partial, Chapter 3 is paused.

The user's order is "finish ALL DAX first, then M". The problem is that "all DAX" has no finish line under random shape hunting. The order can stay. It needs a finish line that can be reached: a fixed test of real-world formulas on a realistic model, plus a speed target.

## Step 6: Top 5 recommendations

1. **Stop the open-ended DAX hunt after Task 246. Replace it with a fixed "DAX exit test".** About 400 formulas that real users write, on a realistic model (date table, 3 to 5 related tables, 10,000+ rows), measured in Power BI. DAX is "finished" when 0 are wrong and a target share is answered. Size: medium. Risk if not done: the hunt runs for months with no end and no user-visible gain.
2. **Fix engine speed.** Add a speed benchmark to the gate, then remove the quadratic context transition and speed up row iterators. The 540,401 saved answers make this safe: any mistake shows at once. Size: large. Risk if not done: the app is unusable on real data, however correct it is.
3. **Save the hunt's probe data into the repo and lock it.** Freeze the `pbi_scratch/w*/` and `review*/` rows as new battery files; lock the 554 unlocked matches. Size: small. Risk if not done: one disk problem loses weeks of Power BI measurements, and new fixes are not guarded.
4. **Stop adding shape patches; split `measures.py` step by step.** New rule: a fix must be a rule about DAX meaning, not a matcher for one shape. If no rule is known, refuse in one central place. Move function families out of `evaluate()` one at a time behind the gate. Size: large, spread over time. Risk if not done: every fix gets slower and more fragile.
5. **Cut the cost per task.** One status file per task (not 5), a faster gate tier, and correct the stale docs (the "76 M functions" number, the 2026-10-26 "paused" header, the chapter contradiction). Then resume Chapter 3 and M with a counted gap list. Size: small. Risk if not done: half of each task's time goes to ceremony.

## Summary for Armaan

- The brief is mostly true. One number is wrong: the M engine has about 650 function names, not 76. About 500 of Power BI's 932 names exist.
- The DAX answers are honest. The app computes them; it does not copy saved answers. The tests use real Power BI answers.
- All 540,000 answers were measured on a table with 6 rows. Nobody has tested the app on big data.
- I tested it: on 100,000 rows a simple SUMX takes 6.7 seconds. One common pattern takes 20 seconds on only 2,000 rows. Power BI does these in milliseconds. This is the biggest problem.
- The last 60 tasks fix strange formulas that no person writes. After each fix, new strange formulas are still 6 to 13% wrong. This work has no end.
- The fixes are patches for single formula shapes. The main code file is 26,500 lines and grows every day. It is getting harder to maintain.
- The most common business formulas (year-to-date, last year, related tables) are barely in the saved answers.
- Five gigabytes of Power BI measurements sit in a scratch folder, not in the project. They can be lost.
- My advice: finish Task 246, then stop the hunt. Build a fixed test of about 400 real-world formulas on a realistic model. That gives DAX a finish line.
- Then fix speed, then go on to Power Query and the report screens. The plan is in `/Users/armaan/pbi_scratch/fable/TEAM_PLAN.md`.

## Added after a completeness check (2026-11-21)

- **Possible wrong display value (unchecked).** In my speed run, `SUMX(Facts, Facts[Sales]*Facts[Quantity])` on 10,000 rows returned `12559005.699999935925006866455`. Power BI would not show that many digits for a Double. It may be the raw value before formatting (guess). Not compared with Power BI.
- **Speed script.** The timing numbers in Step 3 can be reproduced with `/Users/armaan/pbi_scratch/fable/speed_probe.py`.
- **Code map is stale.** `graphify-out/GRAPH_REPORT.md` was built from commit `1b8c8887` on 2026-11-17; about 30 tasks merged since.
- **26 xfailed tests** exist although the rule says no xfail (gate log). I did not read which tests they are.
- **Not investigated at all:** the report UI in the running app, Power Query dialogs, relationship behaviour on real multi-table data, memory use on large files, project save/open on large data.
