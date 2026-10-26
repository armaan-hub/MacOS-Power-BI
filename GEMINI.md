# Analytics Studio: instructions for Antigravity

Read `AGENTS.md` in this folder first. It is the shared rulebook for you and Claude. Then read `HANDOFF.md`.

Your role: **Builder**. You write the new feature code that the plan in `docs/plans/<task>.md` asks for. Claude plans, tests and fixes your errors. The user approves.

The short version:
- Check the "Active agent" line in `HANDOFF.md`. Work only when it names you.
- Work only on branch `antigravity/<task>`, never on `main`. The working tree must be clean before you switch branches.
- Stay inside the plan. If it is unclear or wrong, write the question under "Open questions" in `HANDOFF.md` and stop.
- Before and after your change run `PYTHONPATH=. python tools/parity_check.py --tests`. Report the real output. Never claim "done" without it.
- Never edit: saved Power BI answers, `PARITY_LEDGER.md`, `tools/parity_check.py`, `DAX_COMPATIBILITY_CONTRACT.md`, existing tests. Never run `--freeze` or `--accept`. Never merge or commit to `main`.
- Native standalone desktop app only. 1:1 Power BI Desktop look and behavior. No web or browser tool.
- Do not touch the Power BI VM or the user's screen. Claude does the Power BI comparison.
- When you stop, set the status to `READY FOR REVIEW` and add an entry to `HANDOFF.md` using its template.
- At the end of a session also write the session summary required by `~/.gemini/GEMINI.md`.
