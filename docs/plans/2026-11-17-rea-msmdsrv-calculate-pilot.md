# REA pilot: reading CALCULATE inside msmdsrv.exe

Planned by Claude Opus 5.5 (Team-Planner), 2026-11-17. Approved by the user: decompiler build, symbol download (none exists).

## Goal
Find out whether REA can read Power BI's DAX engine well enough to give us CALCULATE rules we did not already know.
The pilot passes if at least one new rule is found in the code AND confirmed by the Power BI answer check.
It fails honestly if, after the steps below, REA yields only names and no readable logic. We report that.

## Target
- `bin\msmdsrv.exe` from Power BI Desktop 2.157.879.0, 75,692,904 bytes,
  SHA-256 f71b381764721eed28bd731240ea22528f922f01efc23f11744b26cad23fd3c7,
  copy at `~/Library/Caches/codex-powerbi-rea/2.157.879.0/native/msmdsrv.exe`.
- Symbols: PDB `msmdsrv.pdb` ID 916AB88E0F2847E498A10E921ED7A0422. Microsoft's public symbol server returns 404 (checked 2026-11-17). No symbols.

## Entry points found in the file (UTF-16 text, checked 2026-11-17)
| Text | File offset | Why it matters |
|---|---|---|
| `\Sql\Picasso\Engine\src\md\xl\xlcalculate.cpp` | 0x2c6d690 | Source file of CALCULATE; code that logs/asserts with it lives there |
| `XLLogOp_Calculate<XLScaLogOp>` / `<XLRelLogOp>` | 0x2c6d4a8 / 0x2c6d4e8 | Scalar CALCULATE vs CALCULATETABLE operators |
| `FilterCtxFixer::WrapCalculate` | 0x2d0ecb0 | Wraps expressions in CALCULATE (context transition) |
| `XLMeasureItem::ApplyImplicitCalculate`, `XLCalculationItem::ApplyImplicitCalculate` | 0x2c6c6e0, 0x2c6c660 | Implicit CALCULATE around measures / calculation items |
| `ConfigurationSettings\DAX\CalculateBooleanFilter` | 0x2ad6ce0 | Hidden setting that changes boolean filter handling |
| `CALCULATE.CONDITIONAL`, `XLCalculateConditional` | 0x2a2f4e0, 0x2c891e8 | Unknown internal variant (check) |
| `CalculateTable_Vertipaq`, `CalculateTable` | 0x2c6d770 | Storage-engine path |

## Steps (Team-Thinker leads; Haiku agents run REA read-only; one coding agent at a time)
1. Open msmdsrv.exe in REA with the Ghidra provider (`open_binary`); full auto-analysis of 75 MB may take hours: run once, save a snapshot (`close_binary snapshot_path`) so it is never repeated.
2. For each entry-point string: `xrefs` on its address, `resolve_containing_procedure`, rename the function after its string (`set_address_name`, e.g. `XLLogOp_Calculate_Sca__ctor_guess`).
3. Build the call graph around them (`get_call_graph`, depth-limited), decompile the core functions (`procedure_pseudo_code`).
4. Thinker writes each candidate rule in plain words: "when X, Power BI does Y", citing REA Evidence IDs and addresses.
5. Each rule becomes 5-20 DAX test formulas. Compare: our app vs Power BI's saved answers; if not covered, run the live Power BI answer check (`tools/dax_oracle_diff.py`) with the user's OK for VM use.
6. Outcome per rule: already known and matching / new and our app already right / new and our app wrong (becomes a coder task) / not confirmable.
7. Report: `docs/rea-msmdsrv-calculate-findings.md` with an "REA evidence" section, and update `docs/dax-method-guide.md` step 0 with what worked.

## Rules
- Clean room: record behaviour rules only. Never paste Microsoft decompiled code into the app or the docs beyond short identifiers.
- REA findings are hypotheses. The Power BI answer check decides.
- Do not touch the VM screen without the user's OK. Do not save the Power BI project.

## Time box
About one working day of agent time for steps 1-6. If step 3 gives no readable logic for any entry point, stop and report.
