# DAX method guide: how we build a DAX function so that it matches Power BI

Written 2026-11-17 by Team-Thinker (Sonnet 5.5) for the owner and for every coder (Haiku, Antigravity, OpenCode, Codex).
Step 0 (REA) is new today and will be updated after the REA pilot on CALCULATE
(`docs/plans/2026-11-17-rea-msmdsrv-calculate-pilot.md`).

Everything below was checked against the repository on 2026-11-17. A fact that could not be found is written as
"not found in the history". A guess is marked "(guess)".

---

## 1. Purpose and summary

**Purpose.** Give any coder one method to follow when a DAX function is built or fixed. It is a method, not a list of
functions. One real function, CALCULATE, is traced from its first line of code to today (section 4).

**Summary of the method, in one paragraph.** Nobody has read the source code of Power BI's DAX engine. We learn what
Power BI does by asking it. We write many DAX formulas (a "battery"), ask a real Power BI Desktop for the answer to each,
and save the answers. We write code that computes the same answers from DAX rules. We compare our answers with the saved
ones, and every difference teaches us a rule that the documentation did not give. When we cannot compute an answer
exactly, the app refuses instead of guessing. When a slice is finished, its matching answers are locked, and a gate
replays every saved answer on every later change, so a finished slice never breaks again. From 2026-11-17 the method
starts with step 0: read Power BI's own program files with the REA tool to form better questions. REA gives hypotheses
only. Power BI's answers stay the final judge.

### Terms used in this guide

| Term | Meaning |
|---|---|
| Power BI | Microsoft Power BI Desktop, version 2.157.879.0, running in the Windows VM (Parallels, "Windows 11"). Its DAX engine is the program `msmdsrv.exe` (Analysis Services). |
| Power BI answer check | Asking that running Power BI engine for the answer to a DAX formula. Done by `tools/dax_oracle_diff.py` (file name only) and the tools that use it. The script connects to the local Analysis Services port and sends `EVALUATE ROW("v", <formula>)`. |
| Battery | A JSON list of DAX formulas (strings) in `tools/dax_battery_<name>.json`. |
| Freeze | Ask Power BI for the answer to every formula in a battery and write the answers to `tools/parity/<name>.json`. These are the "saved answers". |
| Replay | Run every saved formula in our app and compare with the saved answer. Needs no VM. |
| match | Our answer equals Power BI's. A case where Power BI gives an error and we refuse also counts as a match. |
| refused (`gap-reject` in the tool) | Power BI gives an answer, our app refuses with a message. Not wrong, but not finished. |
| DIFF | Both give an answer and the answers differ. Always a failure. |
| CRASH | Our evaluator raised an unexpected error. Always a failure. |
| Lock | `parity_check.py --accept` writes the id of every matching item to `tools/parity/baseline.json`. A locked item that later stops matching fails the gate ("REGRESSION"). |
| Gate | `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python3 tools/parity_check.py --tests`. It replays every saved answer, runs pytest, and runs the real app (`tools/app_smoke.py`). It must print `PARITY GATE PASSED`. |
| Fresh probe | A formula that is not in any saved file, sent to Power BI for the first time, to test code that may have been fitted to the saved ones. |
| Spec / holdout | A task's measured formulas are split. The coder sees the spec. Team-Planner keeps the holdout back and checks it after the coder is done. |
| Model | The test tables loaded in Power BI and in our app. `Facts` is the standing single table (`tools/dax_oracle_diff.py` builds a 6-row `Facts`; the Task 138 plan says the hunt `Facts` is the fixed VAT sheet). `CB`, `FB`, `ZO`, `ZB`, `ZS`, `ZM`, `FX` are small multi-table models with relationships (`tests/critic3_models.py`, `tools/pbi_model.py`). |

---

## 2. Sources of truth, in order of authority

1. **Power BI's saved answers** (`tools/parity/*.json`). The final authority. They were measured on a real engine, and
   they never change.
2. **A live Power BI answer check** made today for a new formula. Same engine, same authority, but not yet saved. Freeze
   it before it is used as proof.
3. **REA evidence from Power BI's own program files** (new from 2026-11-17). It shows how the engine is built (names,
   code paths). It is static. It never says what a formula returns. Use it to form hypotheses and to choose formulas.
   It is below 1 and 2 because reading code can be wrong, and an answer cannot.
4. **Microsoft's documentation.** Good for a first guess and for the meaning of the arguments. It is incomplete and
   sometimes wrong for edge cases.
5. **Our own reasoning.** The weakest source. Mark it "(guess)" until Power BI confirms it.

**Why this order.** Three incidents from our own history:

- The first CALCULATE code (2026-10-08) was built from documentation only (`6f2f1cb`, `5b5fd8e`). The first Power BI
  checks (2026-10-21) found rules the documentation did not give (section 4, stories 1 and 2). Two old tests that
  encoded the documentation-based assumption had to be corrected (`POWER_BI_FUNCTIONALITY_WORK_LOG.md`, Iteration 66).
- `docs/adr/0001-dax-runtime-and-semantic-oracle.md` (2026-10-12) records that no independent reference engine was connected to
  the app at that time, and that outside libraries' claims alone "do not satisfy the acceptance gate". Nine
  days later (Iteration 64) the reference became the real Power BI engine, asked directly.
- `DAX_COMPATIBILITY_CONTRACT.md` shows what happens with documentation alone: it marks rules as "inference" because "no
  external Tabular engine was used as a differential" check at that time.

---

## 3. The method, step by step

Roles (from `AGENTS.md`, `CLAUDE.md`): Team-Planner (Opus) plans, verifies, merges, and writes no code. Team-Coder
(Haiku, Antigravity, OpenCode, Codex) writes code, one coder at a time. Team-Thinker (Sonnet) reviews and heads the
testing; read-only Haiku testers may run in parallel. Coders never run Power BI, `--freeze`, or `--accept`.

### Step 0. REA inspection (new, from 2026-11-17)

- **What to do.** Before the plan is written, use REA on the Power BI Desktop component that implements the feature.
  Find where the feature lives, which classes and settings it has, and what the code branches on. Write behaviour rules
  in plain words. Do not copy Microsoft code (clean-room rule, `docs/plans/2026-11-17-rea-msmdsrv-calculate-pilot.md`).
- **How.** REA tools (MCP server `rea`): `open_binary` (Ghidra provider) on the target, `xrefs`,
  `resolve_containing_procedure`, `get_call_graph`, `procedure_pseudo_code`, `set_address_name`; for .NET code
  `inspect_managed_members`. Save the session with `close_binary` and `snapshot_path` so a long analysis is never
  repeated. Export evidence with `export_evidence_bundle`.
- **Where it worked before.** On 2026-10-19 REA read the managed (.NET) relationship detector in Power BI's client
  program and gave rules for relationship auto-detection (`POWER_BI_FUNCTIONALITY_WORK_LOG.md`, "REA package inspection
  and relationship key normalization"; `docs/rea-power-bi-desktop-2.157.879.0.md`). The notes said plainly that
  "REA evidence remains static".
- **Limit for the DAX engine.** The DAX engine is native code (`bin\msmdsrv.exe`, SHA-256
  `f71b381764721eed28bd731240ea22528f922f01efc23f11744b26cad23fd3c7`). Microsoft's public symbol server has no PDB for
  this build (404 on 2026-11-17), so function names must be recovered from strings. Whether REA can give readable logic
  for it is the question of the pilot (section 6).
- **Output.** An "REA evidence" section in the plan: what was inspected, Evidence IDs (`ev_...`), what it shows, what REA
  could not establish. If REA gives nothing readable, write that. It is an honest result.
- **Done means.** The plan has an "REA evidence" section, each finding is written as "when X, Power BI does Y (hypothesis)",
  and each hypothesis has at least one formula in the battery (step 3).

### Step 1. Read the documentation and write the expected behaviour

- **What to do.** Read Microsoft's page for the function. Write, in the plan file, the behaviour you expect, in plain
  words, one sentence per rule, and mark each as "documented", "REA hypothesis", or "(guess)". Also list the cases the
  documentation does not cover.
- **File.** `docs/plans/<date>-<task>.md` (plan), with sections: Goal, REA evidence, Expected behaviour, Spec, Rules,
  Results, Review outcome. The existing plans, for example `docs/plans/2026-11-11-dax-calcfilter-141.md`, show the format.
- **Done means.** Someone else can read the plan and say what each formula in the battery should return before Power BI
  is asked. (The history shows this done in the plan and in hand-written tests; whether a per-formula prediction was
  always written down is not found in the history. Do it from now on for new functions.)

### Step 2. Choose the test data and models

- **What to do.** Use the standing data: `tests/Data/Vat File -Aug 2026.xlsx`, sheet `VAT 5%`, header row 12, and the
  small `Facts` table of `tools/dax_oracle_diff.py` (6 rows with a blank, a zero, and a negative value). For anything
  that needs relationships, dates, or blank keys, use the models `CB`, `FB`, `ZO`, `ZB`, `ZS`, `ZM`, `FX`
  (`tests/critic3_models.py`; install them in the live model with `PYTHONPATH=. python tools/pbi_model.py install ZO ZB`).
- **Rules.** Scratch tables are created in Power BI's unsaved model and dropped after the probe. Never save the Power BI
  project. Run the same probes on a second and third data set with rows in another order, because a rule inferred from
  the standard rows may be luck. Print multi-row tables with `TOCSV(table,100)`; the default shows only 10 rows.
- **Done means.** The model can produce every case the plan lists (blank keys, empty result, duplicate rows, and so on).

### Step 3. Design the battery (which formulas to ask)

- **What to do.** Write a JSON list of formulas in `tools/dax_battery_<name>.json`. Build it in layers:
  1. **Simple cases.** One argument form each, on one column. Example: the first battery
     (`tools/dax_battery.json`, 2026-10-21) has nine CALCULATE formulas such as
     `CALCULATE(SUM(Facts[Sales]),Facts[Region]="East")`.
  2. **Every argument form.** Boolean filter, `FILTER(table, ...)`, `ALL`, `REMOVEFILTERS`, `ALLEXCEPT`,
     `ALLSELECTED`, `KEEPFILTERS`, `TREATAS`, `USERELATIONSHIP`, `CROSSFILTER`, table values from VAR.
  3. **Combinations.** Each pair of argument forms, in both orders, and each form nested inside another CALCULATE.
     Single arguments pass easily. Pairs find the rules.
  4. **Edge cases.** Blank and zero, empty tables, text case, a date key column, a row context (inside `SUMX`),
     relationships (active, inactive, one-to-one, many-to-many), blank or orphan keys (the "unknown member" row), duplicate
     rows, the compile-time errors Power BI raises even in a branch that never runs.
  5. **Fresh shapes against cheating.** Random or systematic formulas of the same families that no saved file contains
     (hunt batches of about 540 or 840 formulas, with a seed). Cap every generator loop with a tries counter
     (`while len(out) < N and tries < LIMIT`); uncapped loops hung twice on 2026-11-04.
  6. **A holdout.** Keep part of the measured formulas hidden from the coder (Task 138: 114 spec, 38 holdout, two hidden
     sets of 540).
- **Done means.** The battery has at least one formula for every rule in the plan and for every combination of two
  argument forms the function accepts. List what is not covered in the plan.

### Step 4. Get Power BI's answers (live check, then freeze)

- **Who.** Team-Planner or Team-Thinker. Coders do not run Power BI. If a coder needs an answer, the coder writes the
  formula in `HANDOFF.md` and Team-Planner probes it.
- **Commands.**
  - Quick look: `PYTHONPATH=. python tools/pbi_probe.py expressions.json`.
  - Compare with our app: `PYTHONPATH=. python tools/dax_oracle_diff.py tools/dax_battery_<name>.json` (single table)
    or `PYTHONPATH=. python tools/model_diff.py corpus.json report.json --install ZO ZB` (relationship models).
  - Save the answers: `PYTHONPATH=. python tools/pbi_freeze.py dax_battery_<name>` (writes
    `tools/parity/<name>.json` with the Power BI version and date). Team-Planner then adds the name to `DAX_BATTERIES`
    in `tools/parity_check.py`. `parity_check.py --freeze` re-asks Power BI for every registered battery.
- **Rules.** Run one probe at a time: the scripts create and drop one scratch table `Facts`, and two runs at once
  corrupt each other (found 2026-10-29). The tools take a file lock for this. Run headless only (the guest script runs as
  SYSTEM in session 0, so no window opens). Never use `--current-user`, never send keystrokes, never use the owner's main
  screen. Any VM user-interface work needs the owner's OK. Never save the Power BI project. A transient "could not create
  Facts" means retry. Delete answer caches that contain such errors.
- **Done means.** `tools/parity/<name>.json` exists, every answer is a real answer or an `ERR...` text, and no answer is
  a transient infrastructure error.

### Step 5. Implement

- **What to do.** The coder writes code that computes the answers from DAX rules. Code is in
  `analytics_studio/measures.py` and the `dax_*.py` modules. Put a short comment at each place where Power BI differed
  from the documentation: `# live Power BI (iteration N): <what Power BI does>`. 331 lines of the file mention it
  (`grep -n "live Power BI" analytics_studio/measures.py`), and they are the index of what we learned.
- **Hard rules (AGENTS.md).**
  - Compute, never look up. App code must not read `tools/parity/`, any `dax_battery*.json`, the ledger, or any saved
    file, and must not hold a table of answers keyed by formula text. `tests/test_no_answer_key_in_app.py` fails the build
    on any such reference.
  - No machine paths in tests or app code (`grep -rn "/Users/armaan" tests analytics_studio` must print nothing).
  - Do not edit saved answers, `PARITY_LEDGER.md`, `tools/parity_check.py`, or existing tests.
  - Stay in the plan. If the plan is wrong, write the question in `HANDOFF.md`.
- **Done means.** The coder's targeted tests pass and the coder reports: files changed, tests run with counts, and
  open doubts.

### Step 6. Diff and classify every difference

- **Commands.** `PYTHONPATH=. python tools/check_battery.py dax_battery_<name>` (replay one saved battery, list every
  non-match); `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python3 tools/score_spec.py <spec.json> [PART]` (score a task's
  measured spec: match / refused / wrong). The status rule is `tools/parity_check.py: status()`.
- **Classify each non-match into one of four classes, and write the class down:**

| Class | Sign | Action |
|---|---|---|
| A. Bug in us | The rule is known (documented or learned), our code breaks it | Fix the code. |
| B. Undocumented Power BI behaviour | Power BI answers in a way the documentation does not explain | Find the rule from the pattern across many formulas, write it in words, add fresh probes that test the rule, then implement it. |
| C. A case we must refuse | We cannot compute it exactly (see step 8), or Power BI gives an error that we must also give | Refuse with a clear message. |
| D. Mistake in the test | The harness or the data differs (for example our model stores a blank cell as `None`, while `""` is empty text; column types not passed) | Fix the test setup. Never change the saved answer. |

  Iteration 64 (2026-10-21) had two apparent differences that were class D (harness mistakes) and recorded them so that
  nobody re-opens them (`docs/rea-power-bi-desktop-2.157.879.0.md`, Iteration 64).
- **Done means.** Every non-match has a class, and a class-B rule is written in plain words in the plan.

### Step 7. The fix loop

- **What to do.** Cycle until done: coder fixes, Team-Thinker (with read-only Haiku testers) reviews and tests, failures
  go back to the coder with the report. If a coder fails the same item twice, Team-Thinker fixes it. The loop ends when
  Team-Thinker's verdict is PASS and the gate passes (`CLAUDE.md`, team structure).
- **Watch for fitting.** "First versions fitted the spec but got fresh probes wrong. Prefer refusing"
  (`docs/plans/2026-11-11-dax-rowpos-128.md`, lesson from Tasks 119-137). A change is accepted only when it is right on
  the spec, on the holdout, and on fresh probes, with zero wrong answers. Task 141 reported exactly that: spec, holdout,
  and five hidden sets of 540, "wrong 0 everywhere".
- **Done means.** Spec: 0 wrong. Holdout: 0 wrong. Fresh probes: 0 wrong. Remaining items are matches or refusals, never
  DIFF.

### Step 8. Refuse instead of guessing

- **When refusing is right.**
  - We cannot derive the answer exactly (a last-digit rule, a row order that depends on the engine's storage walk).
  - Fresh probes show that two readings both occur and we cannot tell which applies (Iteration 86 refused "mixed
    readings in one filter").
  - Power BI itself gives an error. Then our app must also give an error. The check counts "Power BI error + our refusal"
    as a match.
  - A shape that used to answer correctly but now cannot be proved is refused until it is measured.
- **How.** Raise `MeasureError` with a message that names the shape. Add a code comment with the Power BI fact that
  justifies the refusal. Add the shape to "Open questions" in `HANDOFF.md` so it becomes work.
- **Why.** A refusal is a correct, honest result (AGENTS.md). A silent wrong answer is the worst result: the user
  trusts it. Today 3,039 of 540,401 saved answers (0.56 %) are refused; none is wrong.
- **Later.** When a refused shape is measured and a rule is found, the refusal is removed and the answers are locked
  (section 4, story 6).
- **Done means.** The refusal is covered by a test, appears in the open list, and does not make any locked item fail.

### Step 9. Lock and run the gate

- **Commands.**
  1. `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python3 tools/parity_check.py --tests` before and after the change. Under
     `caffeinate` when run unattended (a sleeping Mac makes a gate look stalled; judge a stall by CPU time).
  2. When it says `PARITY GATE PASSED` and the slice is verified, `PYTHONPATH=. python tools/parity_check.py --accept`
     locks every matching item. `--accept` refuses to lock while the gate has failures.
- **Done means.** The gate output says `PARITY GATE PASSED`, with DIFF 0 and CRASH 0, the real-app line shows all
  measures equal, and the lock count is recorded in the work log. Current figure (Iteration 282): replay 540,401 saved
  answers, 537,362 match, 3,039 refused, 0 DIFF, 0 CRASH, locked 537,342, pytest about 5,000 passed, real app 575 of 575.
- **Rule.** After each iteration, update the work log, progress, roadmap, and summary files, and remind the owner to run
  `/compact` (`AGENTS.md`).

### Step 10. The regression rule

- A locked item that stops matching is a regression. **Fix the code. Never edit a saved Power BI answer.** The gate
  prints `REGRESSION (was locked)` and fails.
- Stale tests are different. A test that holds a documentation-based expectation can be corrected, but only after Power
  BI confirmed the new value, and the correction is written in the log (Iterations 72 and 82 list such cases).
- If a saved answer itself looks wrong (for example, caused by a bad scratch table), ask Power BI again under a new
  battery name. The old file is not edited. (No case of this is found in the history; the rule comes from `AGENTS.md`.)

### Step 11. Review rules (Team-Thinker, every time)

1. **Answer-key check.** Read the new module for any file read or hard-coded data. Run
   `tests/test_no_answer_key_in_app.py`. Ask Power BI a fresh battery that is not in any saved file. Never accept "all N
   saved items match" as evidence alone. Origin: in Iteration 95, LINEST "matched all 219 saved items" because the code
   loaded `tools/parity/dax_battery_linest.json` at run time and returned the stored text; switching the lookup off made
   26 of 219 differ (`tests/test_no_answer_key_in_app.py` docstring, commit `dbde118`).
2. **Real-app test.** Create each new function as a measure through the real app, offscreen
   (`QT_QPA_PLATFORM=offscreen PYTHONPATH=. python tools/app_smoke.py <dir>`), and compare with Power BI on the iPad
   (Parallels guest) screen. Report it in the review summary.
3. **No worktree paths.** `grep -rn "/Users/armaan" tests analytics_studio` must print nothing. (Task 185 shipped a test
   with a worktree path; it broke main once the worktree was removed.)
4. **Run on several data sets**, not only the standard rows.
5. **Read the diff against the plan.** Scope creep and edits to protected files are sent back.
6. **Verdict.** PASS or FAIL with the failing items. A FAIL goes back to the coder with the Team-Thinker report.

### Step 12. Record

- Plan file: add "Results" and "Review outcome" (Iteration number, lock count).
- `POWER_BI_FUNCTIONALITY_WORK_LOG.md` (iteration entry), `POWER_BI_FUNCTIONALITY_PROGRESS.md`,
  `POWER_BI_FUNCTIONALITY_ROADMAP.md`, `PROJECT_PROGRESS_SUMMARY.md`; `PARITY_LEDGER.md` is regenerated by the gate.
- Add the "REA evidence" IDs to the plan (step 0).

---

## 4. Worked example: CALCULATE, from the first line to today

**Where the code lives.** `analytics_studio/measures.py`: the evaluation entry `if function == "CALCULATE":` (line
23489); filter helpers `_calculate_filter_argument` (2061), `_calculate_boolean_filter_column` (2120),
`_calculate_table_filter_predicate` (2165), `_validate_mixed_filter_clear_calculate` (2257), `_modifier_mix_filters_valid`
(6546); `_TRANSITION_CALLS` (3269, which calls open a context transition); the date-key logic around lines 16986 and
17550; `with_column_filters` (18812); `preevaluate_filter_scalars` (19241); `link_modifiers_settled` (19671); compile-time
`_earlier_too_deep` (3375); `analytics_studio/dax_ct_filters.py` (CALCULATETABLE inside a filter). Line numbers are for
commit `0ca7a33` and will move.

**How much testing sits behind it.** On 2026-11-17, `grep -o "CALCULATE("` finds 50,392 occurrences in the 76 files
`tools/dax_battery*.json`. In the saved answers, 91,009 distinct formulas (of 539,869 saved items in 136 files in
`tools/parity`) contain `CALCULATE(` or `CALCULATETABLE(`. These are counts of text, not of independent cases: many
formulas repeat one shape with different columns.

### 4.1 Timeline

| Date | Iteration / task | Commit | What happened |
|---|---|---|---|
| 2026-10-08 | before iteration numbers | `6f2f1cb`, `5b5fd8e`, `cded5cd` | CALCULATE with context transition, Boolean filters, `KEEPFILTERS`, time-intelligence filters, built from documentation. Tests written by hand (`tests/test_context_transition.py`, `tests/test_calculate_boolean_filters.py`, `tests/test_calculate_advanced_combinations.py`). |
| 2026-10-09 | work-log entries | commit not identified | `REMOVEFILTERS`, `ALL`, `ALLEXCEPT`, `ALLSELECTED`, `USERELATIONSHIP`, each as "bounded" forms that refuse everything else (work log, "Mixed `REMOVEFILTERS` and Boolean filters"). |
| 2026-10-12 | ADR 0001 | n/a | Decision: no outside engine is trusted as the reference. |
| 2026-10-21 | Iteration 64-66 | `059d8f8` | First Power BI check. Battery `tools/dax_battery.json`, first freeze. |
| 2026-10-21/22 | Iteration 72, 76 | `059d8f8` | Locking begins. Refusals added. Scalar side of Boolean filters. |
| 2026-10-22 | Iteration 77-81 | `cf4d141` ... `7f013d3` | Most DIFF groups cleared; `&&` / `||` without short-circuit; ALLSELECTED inside iterators; ALL / REMOVEFILTERS on the expanded table. |
| 2026-10-23 | Iteration 82 | `265027a`, `9590043`, `5602846` | Date-key wipe, modifier mixes, unknown member. |
| 2026-10-24 | Iteration 84 | `99d5616`, `569ad5d`, `2c2f854` | Critic rounds; refusals for shapes that were still wrong. |
| 2026-10-25 | Iteration 86 | `0193534` | CALCULATETABLE inside a Boolean filter: hoist or transition. |
| 2026-11-12 | Iteration 230 (Task 141) | `3180025`, `d6d4bf8`, `222f31e` | Strict equality, KEEPFILTERS, whole-row filter sets. |
| 2026-11-16 | Iteration 260 (Task 172) | `02baa3d`, `d30b71d`, `92ed277` | Compile-time EARLIER check under CALCULATE filter arguments. |

Iterations 64 to 76 are all inside the single commit `059d8f8` (2026-10-22, "Add DAX engine coverage, Power BI parity
gate and Power Query updates"). A separate commit for each of those iterations is not found in the history; the work
log has the per-iteration detail.

### 4.2 Phase A: how we started (2026-10-08, documentation only)

- **Source.** Microsoft's documentation and general DAX knowledge (the exact pages used are not found in the history): the
  filter arguments replace filters on the same column; Boolean filters are shorthand for `FILTER(ALL(column), ...)`;
  `KEEPFILTERS` intersects instead of replacing; a row context becomes a filter context ("context transition").
- **Tests designed.** By hand, per argument form, with expected numbers computed by reading the table.
  `tests/test_calculate_boolean_filters.py` was 3,342 lines when it first appeared (`5b5fd8e`).
- **Expectation.** The documented rules above.
- **Result.** The local evaluator answered each case. There was no Power BI to compare with.
  `DAX_COMPATIBILITY_CONTRACT.md` says "No external Tabular engine was used as a differential" check.
  The work log called each form "bounded" and refused every neighbouring shape, for example "Mixed table-valued `FILTER`
  and time-intelligence arguments are rejected with clear messages; their ordering/context semantics are not
  implemented".

### 4.3 Phase B: the first Power BI check (2026-10-21, Iterations 64-66)

`tools/dax_oracle_diff.py` was built to ask the running Power BI. The first battery (`tools/dax_battery.json`, 93
formulas, frozen 2026-10-21) had nine CALCULATE formulas. These are Power BI's saved answers
(`tools/parity/dax_battery.json`) on the 6-row `Facts` (Sales: 10.5, 20, -1.5, blank, 0, 2.5):

| Formula | Power BI |
|---|---|
| `CALCULATE(SUM(Facts[Sales]),Facts[Region]="East")` | 11.5 |
| `CALCULATE(COUNTROWS(Facts),Facts[Region]<>"East")` | 3 |
| `CALCULATE(SUM(Facts[Sales]),Facts[Sales]>0)` | 33 |
| `CALCULATE(SUM(Facts[Sales]),FILTER(Facts,Facts[Quantity]>2))` | 22.5 |
| `CALCULATE(SUM(Facts[Sales]),ALL(Facts))` | 31.5 |
| `CALCULATE(SUM(Facts[Sales]),REMOVEFILTERS(Facts))` | 31.5 |
| `CALCULATE(COUNTROWS(Facts),Facts[Note]=BLANK())` | 2 |
| `CALCULATE(COUNTROWS(Facts),Facts[Sales]=0)` | 2 |
| `CALCULATE(COUNTROWS(Facts),Facts[Sales]=BLANK())` | 2 |

#### Story 1. A Boolean filter treats BLANK and 0 as equal (Iteration 64, 2026-10-21)

- **Expected.** `Facts[Sales]=0` keeps only the row with 0, so 1 row (guess: the documentation page does not state the
  blank case; a reader would expect 1).
- **Power BI gave.** 2. The blank Sales row and the zero row both pass, and `Facts[Sales]=BLANK()` also gives 2.
- **Found by.** The first battery, in the saved answers. The log records: "`CALCULATE(COUNTROWS(Facts),
  Facts[Sales]=BLANK())` counting both blank and `0` (2 of 6 rows)" (`docs/rea-power-bi-desktop-2.157.879.0.md`,
  Iteration 64). What our app answered before this check is not found in the history.
- **Fixed.** Blank equals 0 (and `""`) in comparisons of a filter. Iteration 82 states the same rule again for the
  "unknown member" work ("BLANK is 0 / "" in comparisons"). The exact commit of this first fix is not found in the history
  (it is inside `059d8f8`).
- **Locked.** The whole first battery is locked in the gate (`PARITY_LEDGER.md`: `dax_battery`, 93 locked).

#### Story 2. Text filters ignore ASCII case (Iteration 66, 2026-10-21)

- **Expected.** The earlier code and two old tests compared text exactly, so `Facts[Region]="east"` would not match
  "East".
- **Power BI gave.** It matches. Power BI's model compares ASCII letters without case, and keeps the first spelling it
  saw (for example "West" and "west" are one value).
- **Found by.** The first table-level check, `tools/table_oracle_diff.py`, on the owner's workbook: 2,738 cell
  differences at first, then real findings (trailing spaces dropped, ASCII case folded, Excel doubles read as
  shortest round trip).
- **Fixed.** `_model_candidate_with_format_errors_as_blank` in `analytics_studio/controller.py` and
  `power_query_values.model_text_normalizer`. "Two old tests encoded the earlier assumption (case-sensitive filters)
  and now state the Power BI behaviour." Result: workbook table 371x10 cells identical, 106 of 108 measures match.
- **Locked.** The workbook answers are replayed by the gate; the lock iteration for this item is not found in the history
  (locking began in Iteration 72).

#### Story 3. A refusal that saved wrong answers (Iteration 72, 2026-10-21)

- **Expected (our assumption).** A Boolean CALCULATE filter nested inside an outer `FILTER(table, ...)` works like any
  other nesting.
- **Power BI gave.** 1, 2, and BLANK where the app gave 3, 4 and 2.
- **Found by.** A regression triage after the batteries were added (15 failing tests). The general path had "swallowed the
  legacy FILTER rowset refusal".
- **Fixed.** Those shapes are refused again (class C). The same iteration corrected a stale test:
  `CALCULATE(COUNTROWS(ALL(Facts[Region])),Facts[Quantity]>3)` is 3 in Power BI, because `ALL(column)` ignores filters
  on its own table.
- **Locked.** 10,580 answers locked in Iteration 72. Seven differences stayed open and were listed, not hidden.

### 4.4 Phase C: finding rules by many probes (2026-10-22 and later)

#### Story 4. The scalar on the right of a Boolean filter is read once, outside (Iteration 76, 2026-10-22)

- **Our app did.** In `CALCULATE(COUNTROWS(Facts), Facts[Quantity] > COUNTROWS(CALCULATETABLE(...)))` it evaluated the
  scalar for each row of the test, so the CALCULATETABLE "transitioned" the test's own row.
- **Power BI gave.** It evaluates the scalar once, in the outer context, before the filter is applied.
- **Found by.** Five rounds of independent testing agents with about 14,000 new probes (the battery
  `dax_battery_boolean_scalar_rhs`, 517 formulas). Round 1 alone found 56 wrong answers in the first version, because
  hoisting was unsound for some CALCULATETABLE forms.
- **Fixed.** `preevaluate_filter_scalars` in `analytics_studio/measures.py` (line 19241): it computes the right-hand side
  once. Shapes whose rule was not established are refused ("the scalar on the left, a CALCULATETABLE scalar below the
  top level").
- **Locked.** Gate on 2026-10-22: replay 31,703 answers, 30,468 match, 1,235 refused, 0 DIFF, 0 CRASH; 30,459 locked (was
  14,870). Trade-off recorded: 16 shapes the old code answered correctly by luck are now refused.

#### Story 5. Replacing a date key first removes the other filters of its table (Iteration 82, 2026-10-23)

This is the example the owner asked for. It was a rule that the documentation does not give and that no reader would
guess.

- **Expected.** The documented rule: a new filter on a column replaces only that column's filter. So, in
  `CALCULATE(CALCULATE(COUNTROWS(CB_Cal), CB_Cal[Date]<=DATE(2023,6,30)), CB_Cal[Year]=2024)` the inner `Date` filter
  leaves the outer `Year=2024` filter alone. The two filters meet and nothing is left.
- **Our app gave (before the fix).** BLANK. For `...CB_Cal[MonthNo]=2` it gave 28. (We re-ran the code of the commit
  before the fix on 2026-11-17 to confirm this; it was not recorded earlier.)
- **Power BI gave.** 181 for both. That is every date from 2023-01-01 to 2023-06-30. The outer `Year` and `MonthNo`
  filters were gone.
- **Found by.** The reverse-engineering round "RE-D", 28,639 probes on the date model `CB` (calendar `CB_Cal`, fact
  `CB_Fact`, dimension `CB_Dim`). The pattern across hundreds of formulas gave the rule (work log, Iteration 82):
  "Replacing a dateTime key column (Boolean test, `FILTER(ALL(key),..)`, `TREATAS`, time intelligence, a row of an
  iteration over the key) first removes every other outer filter of its expanded table (its columns, tables below it,
  one-to-one partners); `KEEPFILTERS`, `ALL(key)`, `VALUES(key)`, `FILTER(Table,..)` and non-key columns do not; date sets
  are computed in the outer context, the wipe happens when they are applied."
- **Control cases that Power BI also answered** (`tests/fixtures_iter82_r10.json`). With `KEEPFILTERS(CB_Cal[Date]<=...)`
  beside `Year=2024` the answer is BLANK: no wipe. `CALCULATE(CALCULATE(COUNTROWS(CB_Cal),CB_Cal[Year]=2023),
  CB_Cal[Year]=2024,CB_Cal[MonthNo]<=2)` is 59 (January and February 2023): `Year` is not the key column, so the outer
  `MonthNo` filter stays. Controls like these are what make the rule exact instead of broad.
- **Fixed.** Commit `5602846` (2026-10-23, "Date-key wipe (R10) ...") in `analytics_studio/measures.py`: for a date set
  (line 16986: `wiped_ids = set(expanded_table_ids(...)) if is_date_key(...)`) and for a Boolean test on the key (line
  17550). The comments say "# live Power BI: applying a date set to a date key column first removes the other outer
  filters of its expanded table". `is_date_key` at line 19371.
- **Tests.** `tests/test_iteration82_rules.py` (`DateKeyWipeTests`, 7 formulas written out by hand) and the saved answers in
  `tests/fixtures_iter82_r10.json` (510 Power BI answers; the test replays them and asserts more than 400).
- **Result.** "Date models: 6,012 of 6,549 probes match (was about 5,400)". Gate after part 2: replay 44,326 match,
  1,190 refused, 0 DIFF, 0 CRASH (the run after the fix is Evidence `ev_95b0db616df4ceea453396b3fb6f9172eb28830c5d7dd085547c616911199898`
  in the work log).
- **Locked.** Together with the other Iteration 82 items. The lock count for this step alone is not found in the history.

#### Story 6. Mixing relationship modifiers with clearing filters; refuse, then restore (Iterations 82-84)

- **Expected (guess).** `USERELATIONSHIP` inside a CALCULATE and `ALL(table)` in the same CALCULATE: the clear removes
  the filters that reach the table, including those through the relationship that was just activated.
- **Power BI gave.** The clear uses only the relationships of the enclosing context. With
  `CALCULATE(CALCULATE(COUNTROWS(FB_Fact), USERELATIONSHIP(FB_Fact[Dt],FB_Cal[Date]), ALL(FB_Fact)), FB_Cal[Year]=2024)` the
  answer is 8 (the outer calendar filter still narrows the fact rows). With the `USERELATIONSHIP` in the outer CALCULATE it
  is 13. (`tests/test_calculate_modifier_mix.py`.)
- **Found by.** A "critic" loop: independent agents asked Power BI about CALCULATE calls that mix `USERELATIONSHIP`,
  `CROSSFILTER`, `ALLSELECTED`, clearing and table filters. Result: "0 to 1,250 of 1,321" matching after commit
  `265027a` (2026-10-23). The test file keeps 281 of the saved answers (`tests/fixtures_calculate_modifier_mix.json`).
  Before it, the app matched none of these mixes.
- **Refusals added where fresh probes still found wrong answers.**
  - "S-1" (Iteration 83): `USERELATIONSHIP` together with a table filter over the many-side table, when rows match no
    member of the related table. 100 silent wrong answers (for example Power BI 33, ours 2,375) became refusals
    (`analytics_studio/measures.py` near line 19826).
  - `ALLSELECTED` over a date column beside several `KEEPFILTERS`, found by a fresh probe in Iteration 84
    (`COUNTROWS(DATESYTD(ALLSELECTED(Fact[Dt])))` under `ALL(Cal)` and two `KEEPFILTERS` on `Cal[Year]` is 4 in Power BI,
    BLANK in ours). Commits `99d5616`, `569ad5d`, `2c2f854` (2026-10-24) add the guard. The code comment states the Power
    BI fact (near line 19667).
- **Later.** `USERELATIONSHIP` beside `CROSSFILTER` was measured and modelled (`link_modifiers_settled`, line 19671: for
  example `CROSSFILTER(r, NONE)` on the activated link is an error in Power BI, and Power BI's error text is reproduced).
  For this pair, what stays refused is what Power BI itself rejects.
- **Why it matters.** Refusal is a tool, not a failure. S-1 turned 100 silent wrong answers into honest messages.

#### Story 7. One filter, two readings (Iteration 86, 2026-10-25)

- **Expected (guess).** A CALCULATETABLE inside a Boolean filter always behaves one way.
- **Power BI gave.** Two ways. `Quantity > COUNTROWS(CALCULATETABLE(Facts, Region="East"))` is 2, and the reversed
  `COUNTROWS(CALCULATETABLE(...)) < Quantity` is 4: in one the scalar is evaluated once ("hoist"), in the other it is
  evaluated per value ("transition").
- **Found by.** 332 saved answers and about 12,500 fresh probes on `Facts` and the models `ZO`, `ZB`.
- **Fixed.** `analytics_studio/dax_ct_filters.py` (commit `0193534`), with the rule written in its docstring. Mixed
  readings, nested CALCULATETABLE, and `ALLSELECTED`/`KEEPFILTERS` among the filters are refused on purpose. 170 formerly
  refused saved answers now match. The fresh probes also exposed a bug in old code (wrong in 32 of 1,200 probes), fixed or
  refused.

#### Story 8. Task 141: filters that are sets of whole rows (Iteration 230, 2026-11-11/12)

- **Problem.** 70 saved answers, and about 213 to 247 of each of five hidden 540-formula sets, were refused because the
  engine did not model `Facts[X]==BLANK()`, `KEEPFILTERS` beside plain filters, and `FILTER(Facts, ...)` combined with
  later filters on its columns.
- **Rule found.** A filter that is a set of whole rows stays one tuple set. Overwriting or clearing columns C projects
  every set that covers C onto its other columns. `KEEPFILTERS` intersects. Strict equality `==` treats 0 and "" as
  different from BLANK.
- **Result.** Spec 0 to 52 of 52, holdout 0 to 16 of 18, hidden sets 538 to 539 of 540 each, a duplicate-row probe 333
  to 536 of 540; wrong 0 everywhere. Locked 537,156 to 537,250. Plan: `docs/plans/2026-11-11-dax-calcfilter-141.md`.
- **Method points.** Spec, holdout, and hidden sets were kept apart; a probe on a table with duplicate rows was added;
  shapes not covered stay refused ("`==` against a computed fraction").

#### Story 9. The gate catches a regression in a locked answer (Iteration 260, 2026-11-16)

- **Problem.** Power BI refuses the whole query when `EARLIER` or `EARLIEST` has fewer outer row contexts than it
  needs. It does this at compile time, even in a branch that never runs, over an empty table, or inside `IFERROR`.
  The app evaluated lazily and answered 1 or "E".
- **First version** (`02baa3d`): a row context was opened only for a bare Boolean filter argument.
- **Gate result.** The replay found 4 locked Power BI answers that the app now refused: `EARLIER` inside
  `KEEPFILTERS(...)` and `ISONORAFTER(...)` filter arguments.
- **Follow-up** (`d30b71d`): every CALCULATE filter argument opens a row context in `_earlier_too_deep`. "That can only
  answer where main already answered, so it cannot add a wrong answer."
- **Result.** Scorer 18/0/2 to 20/0/0; a sweep of 89 valid shapes had 0 over-refusals; 29 invalid shapes were refused.
  Lock stays 537,342. Plan: `docs/plans/2026-11-16-dax-hunt-172.md`.

### 4.5 Where CALCULATE stands on 2026-11-17

- Gate: replay 540,401 saved answers, 537,362 match, 3,039 refused, 0 DIFF, 0 CRASH, locked 537,342.
- Known refusals and open items are in `HANDOFF.md` ("Open questions") and `PARITY_LEDGER.md` (the pending list).
- What the saved answers cannot tell us is in section 6.

### 4.6 What the example shows about the method

1. The first version built from documentation was correct for simple cases and wrong in the places that matter.
2. The biggest rules (blank equals 0, text case, date-key wipe, modifier mixes, hoist or transition) were found only by
   asking Power BI hundreds or thousands of formulas of one family and reading the pattern.
3. Each rule is small, written as one sentence, kept in a code comment, and defended by saved answers.
4. Refusal is part of the method: it turned wrong answers into messages while the rule was still unknown.
5. The gate protected finished work (story 9).

---

## 5. Rules learned

Each rule has the incident or source it came from.

1. **Never edit a saved Power BI answer.** Fix the code. (`AGENTS.md`; parity rule in `CLAUDE.md`.)
2. **Compute, never look up.** (Iteration 95: LINEST read the saved file at run time and "matched" 219 of 219; 26 differed
   once the lookup was off. `tests/test_no_answer_key_in_app.py`.)
3. **Refuse instead of guessing.** (Iteration 72: 1/2/BLANK vs 3/4/2; Iteration 83 S-1: 100 wrong answers made loud.)
4. **Test combinations, not only single arguments.** (Iteration 82: the modifier mixes went from refused to 1,250 of 1,321
   matching only when pairs were probed.)
5. **Probe fresh shapes.** A saved battery is both the specification and the test, so it can pass while computing nothing.
   (Task 138 plan: "first versions fitted the spec but got fresh probes wrong".)
6. **Keep a holdout.** Do not show the coder every measured formula. (Tasks 138, 141, 145: spec plus holdout plus hidden
   sets.)
7. **Probe on more than one data set and row order.** (A rule inferred from the standard 6 rows can be luck; the
   duplicate-row probe of Task 141 moved 333 to 536 of 540.)
8. **Look at many rows.** `TOCSV(table,100)`; the default shows 10 rows and hid most differences once.
9. **Write the rule in one plain sentence and put it in a code comment** (`# live Power BI (iteration N): ...`).
10. **Classify every difference** (bug / undocumented behaviour / must refuse / test mistake) before changing code.
    (Iteration 64: two "differences" were harness mistakes.)
11. **When Power BI errors, the app must error** with the same meaning. (Compile-time `EARLIER`, Task 172;
    `USERELATIONSHIP` + `CROSSFILTER(..NONE)` on one link, `link_modifiers_settled`.)
12. **Run the whole gate before and after a change.** (Task 172: the gate found 4 locked answers that the first version
    broke.)
13. **Lock only after the gate passes and the slice is verified.** `--accept` refuses to lock with failures.
14. **A refused shape that is later measured must be restored and locked, not left refused.** (Story 6.)
15. **Cap every probe generator.** `while len(out) < N and tries < LIMIT` (two hangs on 2026-11-04).
16. **One probe run at a time against the one Power BI**, headless, no window, project never saved. (Scratch table
    collisions, 2026-10-29; windows on the screen, 2026-10-22 to 2026-10-29.)
17. **Never use the owner's main screen or send keystrokes** in the VM. UI work needs the owner's OK.
18. **Corrected tests must be justified by a Power BI answer**, and the correction is written in the log. (Iteration 66,
    72, 82.)
19. **No worktree or machine paths in tests.** (Task 185.)
20. **Run the gate under `caffeinate`** and judge stalls by CPU time (Mac sleep slowed unattended gates).
21. **REA findings are hypotheses.** They add formulas to the battery; they never replace an answer. (From 2026-11-17.)
22. **Clean room.** Write behaviour rules found by REA. Never copy Microsoft code into the app or the docs.

---

## 6. Known gaps and the REA pilot

### What this method cannot prove

- **Untested combinations.** The saved answers are examples. A formula nobody asked about is not covered. CALCULATE has
  many argument forms, and the combinations of three or more are too many to ask. Our confidence comes from families of
  probes, not from a proof.
- **Hidden state.** Row order and tie order depend on the engine's storage walk (several shapes stay refused, for example
  `TOPN` ties, `CONCATENATEX` order).
- **Last-digit numbers.** `COS`, `SIN`, `TAN` and some finance functions differ in the last digit in some cases
  (Task 145, "known limits").
- **Model shapes.** Models other than `Facts`, `CB`, `FB`, `ZO`, `ZB`, `ZS`, `ZM`, `FX` (very wide snowflakes,
  calculation groups, many-to-many chains beyond ZM) were not probed.
- **Power BI versions.** All answers come from 2.157.879.0. A new Power BI version can change a rule.
- **Open items named in the log.** Remaining CALCULATE-related refusals are listed under "Open" in
  `POWER_BI_FUNCTIONALITY_WORK_LOG.md` (for example one-to-one blank members, bidirectional two-fact models `ZS`,
  time intelligence on unmarked date columns). The up-to-date list is in `HANDOFF.md`.

### How REA is meant to close part of the gap

Reading the engine could tell us the real structure of CALCULATE (what is a rule, what is a special case) and list
cases we never thought to ask. The pilot (`docs/plans/2026-11-17-rea-msmdsrv-calculate-pilot.md`) uses these anchors
found in the strings of `bin\msmdsrv.exe` (Power BI 2.157.879.0; UTF-16 text; file offsets from the plan):

| Anchor | File offset | What it suggests |
|---|---|---|
| source path `\Sql\Picasso\Engine\src\md\xl\xlcalculate.cpp` | 0x2c6d690 | The source file of CALCULATE. |
| `XLLogOp_Calculate<XLScaLogOp>` and `XLLogOp_Calculate<XLRelLogOp>` | 0x2c6d4a8, 0x2c6d4e8 | Scalar CALCULATE and CALCULATETABLE (table) operators. |
| `FilterCtxFixer::WrapCalculate` | 0x2d0ecb0 | Where an expression is wrapped in CALCULATE (context transition). |
| `XLMeasureItem::ApplyImplicitCalculate`, `XLCalculationItem::ApplyImplicitCalculate` | 0x2c6c6e0, 0x2c6c660 | The implicit CALCULATE around a measure or a calculation item. |
| setting `ConfigurationSettings\DAX\CalculateBooleanFilter` | 0x2ad6ce0 | A hidden setting that changes Boolean filter handling. |
| `CALCULATE.CONDITIONAL`, `XLCalculateConditional` | 0x2a2f4e0, 0x2c891e8 | Unknown internal variant (to check). |
| `CalculateTable_Vertipaq`, `CalculateTable` | 0x2c6d770 | Storage-engine path. |

Limits: Microsoft's public symbol server has no PDB for this build (`msmdsrv.pdb`, ID
`916AB88E0F2847E498A10E921ED7A0422`, 404 on 2026-11-17), so only strings give names. The pilot passes only when at least
one new rule is found in the code and confirmed by a Power BI answer check. It fails honestly if REA yields only names.
After the pilot, update step 0 of this guide with what worked and what did not. Whether the "date-key wipe" of story 5
or the "hoist or transition" split of story 7 appears in this code is not known today (guess: the wipe may be tied to
`FilterCtxFixer`, but this is not checked).

---

## 7. Checklist for a coder brief (any new DAX function)

Copy this into the brief. A brief without these lines is sent back.

```
Task:            <number> <name>
Function(s):     <names>
Plan file:       docs/plans/<date>-<task>.md

0. REA evidence: component inspected, Evidence IDs, findings (hypotheses), what REA could not establish
1. Expected behaviour (docs, REA hypothesis, guess) in plain sentences
2. Test data and models: Facts (VAT sheet), CB / FB / ZO / ZB / ZS / ZM / FX as needed
3. Battery: tools/dax_battery_<name>.json
   - simple case per argument form
   - every pair of argument forms, both orders, and nested
   - edge cases: blank, zero, empty table, text case, date key, relationships, unknown member, duplicate rows,
     compile-time errors
   - fresh-shape hunt (seeded, capped generator) and a holdout kept by Team-Planner
4. Power BI answers: probed and frozen by Team-Planner / Team-Thinker (the coder does not run Power BI)
5. Code: analytics_studio/<module>; one "# live Power BI (iteration N): ..." comment per learned rule
6. Do not:  read tools/parity, dax_battery*.json, the ledger, or any saved answer; edit saved answers, existing tests,
            PARITY_LEDGER.md, tools/parity_check.py, DAX_COMPATIBILITY_CONTRACT.md; write machine paths in tests;
            run --freeze, --accept, or any Power BI tool; merge or push
7. Refuse (MeasureError) every shape you cannot derive exactly; list each in HANDOFF.md "Open questions"
8. Tests: the named test files only, QT_QPA_PLATFORM=offscreen -p no:cacheprovider; then, for Team-Planner,
   PYTHONPATH=. QT_QPA_PLATFORM=offscreen python3 tools/parity_check.py --tests  -> PARITY GATE PASSED
9. Acceptance numbers: spec wrong = 0, holdout wrong = 0, fresh probes wrong = 0, DIFF 0, CRASH 0
10. Review (Team-Thinker): answer-key check, real-app measure test (offscreen), fresh probes, VM-screen comparison,
    grep -rn "/Users/armaan" tests analytics_studio is empty, verdict PASS/FAIL
11. Record: plan Results + Review outcome, work log, progress, roadmap, summary; lock count
```

---

## Appendix A. Command reference

| Purpose | Command |
|---|---|
| Whole gate | `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python3 tools/parity_check.py --tests` |
| Replay only (no VM, no pytest) | `PYTHONPATH=. python tools/parity_check.py` |
| Lock matching items | `PYTHONPATH=. python tools/parity_check.py --accept` |
| Re-ask Power BI for all registered batteries | `PYTHONPATH=. python tools/parity_check.py --freeze` |
| Freeze one new battery | `PYTHONPATH=. python tools/pbi_freeze.py dax_battery_<name>` |
| Quick Power BI answers | `PYTHONPATH=. python tools/pbi_probe.py expressions.json` |
| Compare a battery | `PYTHONPATH=. python tools/dax_oracle_diff.py tools/dax_battery_<name>.json` |
| Relationship models | `PYTHONPATH=. python tools/pbi_model.py install ZO ZB`, then `tools/model_diff.py corpus.json report.json` |
| Replay one saved battery | `PYTHONPATH=. python tools/check_battery.py dax_battery_<name> [all]` |
| Score a measured spec | `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python3 tools/score_spec.py <spec.json> [PART]` |
| Real app, offscreen | `QT_QPA_PLATFORM=offscreen PYTHONPATH=. python tools/app_smoke.py <dir>` |
| Index of learned rules | `grep -n "live Power BI" analytics_studio/measures.py` |

## Appendix B. Sources used for this guide

`AGENTS.md`, `CLAUDE.md`, `HANDOFF.md`, `POWER_BI_FUNCTIONALITY_WORK_LOG.md` (Iterations 64-66, 72, 76, 80-84, 86, 230,
260), `PARITY_LEDGER.md`, `DAX_COMPATIBILITY_CONTRACT.md`, `docs/adr/0001-dax-runtime-and-semantic-oracle.md`,
`docs/rea-power-bi-desktop-2.157.879.0.md`, `docs/plans/2026-11-11-dax-calcfilter-141.md`,
`docs/plans/2026-11-11-dax-rowpos-128.md`, `docs/plans/2026-11-13-dax-hunt-145.md`,
`docs/plans/2026-11-16-dax-hunt-172.md`, `docs/plans/2026-11-17-rea-msmdsrv-calculate-pilot.md`,
`tools/dax_oracle_diff.py`, `tools/parity_check.py`, `tools/parity/dax_battery.json`, `tests/test_iteration82_rules.py`,
`tests/fixtures_iter82_r10.json`, `tests/test_calculate_modifier_mix.py`, `tests/test_no_answer_key_in_app.py`,
`analytics_studio/measures.py`, `analytics_studio/dax_ct_filters.py`; git history (`git log -S "live Power BI"`,
`git log --grep`); commits named in the text.
