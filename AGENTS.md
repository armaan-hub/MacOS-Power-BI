# Analytics Studio: shared rules for Claude and Antigravity

Both agents read this file first. `CLAUDE.md` and `GEMINI.md` only point here, so the rules cannot drift apart.
The user (Armaan) decides what gets built and approves what is finished. Neither agent overrules the user.

## Roles (set by the user 2026-10-26)

| | Antigravity (Builder) | Claude (Planner, Tester, Fixer) |
|---|---|---|
| Writes new feature code | YES, this is its job | NO, not until the user says "Claude, code this" |
| Plans and specs | Follows the plan in `HANDOFF.md` | Writes the plan, scope and acceptance checks |
| Tests | Runs tests, does not change existing ones | Writes and maintains tests, runs the parity gate |
| Fixes errors | Fixes its own errors when sent back | Fixes errors found in Antigravity's code |
| Power BI comparison, `--freeze`, `--accept`, ledger | NEVER | YES, with the user's approval |
| Work log, progress, roadmap, summary files | One short entry in `HANDOFF.md` only | Owns and updates all of them |
| Merge and commit | NEVER | Only when the user approves |

If the user explicitly tells Claude to code something, that instruction applies to that task only. Roles then return to the table above.

## The loop

1. **Requirement.** The user states what is needed.
2. **Plan (Claude).** Claude writes a short plan in `docs/plans/<task>.md`: goal, files to touch, what must not be touched, how Power BI behaves, and the acceptance checks. It adds the task to the queue in `HANDOFF.md` with status `PLANNED`.
3. **Build (Antigravity).** Antigravity works only on branch `antigravity/<task>`, stays inside the plan, sets status `BUILDING`, then `READY FOR REVIEW` with a list of files it changed and anything it was unsure about.
4. **Test and review (Claude).** Claude checks out the branch, runs `PYTHONPATH=. python tools/parity_check.py --tests`, and reads the diff against the plan. Status `REVIEWING`.
5. **Fix (Claude).** If anything fails, Claude fixes errors in Antigravity's code directly on that branch, or sends it back with exact failing output when the fix needs a redesign. Status `FIXING`. Repeat step 4.
6. **Compare with Power BI (Claude).** When the gate passes, Claude does the Power BI comparison and saves the answers (`--freeze`). Status `GATE PASSED`.
7. **Approval.** The user approves. Only then does Claude `--accept` the slice, merge the branch, commit, update the logs, and set status `DONE`.

## Who is active

Only one agent works at a time. `HANDOFF.md` has an "Active agent" line. Read it before touching anything. If it names the other agent, do not edit the project, only read. Both agents share one working folder, so the active agent changes the line before it starts and again when it stops. Before switching branches, the working tree must be clean.

## Rules for both agents (standing, from the user)

- **Parity rule.** Every finished feature is compared with Power BI Desktop, locked, and re-tested on every change. A locked item that stops matching is a regression: fix the code, never edit the saved Power BI answers.
- **Gate.** Before and after any code change run `PYTHONPATH=. python tools/parity_check.py --tests`. It must say PARITY GATE PASSED. Never report "done" without the gate output.
- **Never touch:** saved Power BI answers, `PARITY_LEDGER.md`, `tools/parity_check.py`, `DAX_COMPATIBILITY_CONTRACT.md`, existing tests. These are Claude's, with the user's approval.
- **Native desktop app only.** Analytics Studio is a standalone native desktop app with a 1:1 Power BI Desktop UI and behavior. Do not build a web or browser tool.
- **Real-app test (Claude, every review).** Test each new feature in the actual app (create it as a measure through the app, offscreen) and compare with Power BI on the iPad screen; report it.
- **Power BI screen.** Use only the iPad (Parallels guest) screen for Power BI. Never the main Mac screen. Never save the Power BI project. Never pop windows or send keystrokes on the user's screen without the user's OK.
- **Test data.** `tests/Data/Vat File -Aug 2026.xlsx`, sheet `VAT 5%`, header row 12.
- **Long gates.** Run unattended gates under `caffeinate`. Judge stalls by CPU time, not wall time.
- **Scope.** Do the task in the plan, nothing more. If the plan is wrong or unclear, stop and write the question in `HANDOFF.md` instead of guessing.
- **Honest reports.** If a test fails or a step was skipped, say so with the output.
- **No destructive actions** (delete, force push, reset) without the user's OK.

## Handing over

- Antigravity: before stopping, set status and add a short entry to `HANDOFF.md`: what was built, files changed, what was run, open doubts.
- Claude: after each iteration update `POWER_BI_FUNCTIONALITY_WORK_LOG.md`, `POWER_BI_FUNCTIONALITY_PROGRESS.md`, `POWER_BI_FUNCTIONALITY_ROADMAP.md`, `PROJECT_PROGRESS_SUMMARY.md`, and let the gate regenerate `PARITY_LEDGER.md`. Then remind the user to run `/compact`.
- Antigravity also keeps the user's global session-summary rule from `~/.gemini/GEMINI.md`.

## Files to read before starting work

1. `HANDOFF.md` (who is active, current task, open questions)
2. `docs/plans/<task>.md` (the plan for the current task)
3. `PARITY_LEDGER.md` (what is locked and what is pending)
4. `POWER_BI_FUNCTIONALITY_WORK_LOG.md` (latest iteration entries)
5. `POWER_BI_DESKTOP_PARITY_BRAIN.md` and `README.md` (background)

Older reports and inventories are in `_backup_instruction_files/` (see its `MANIFEST.md`). Do not rely on them.
