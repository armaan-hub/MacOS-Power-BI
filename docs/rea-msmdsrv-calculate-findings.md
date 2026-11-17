# REA pilot findings: CALCULATE inside msmdsrv.exe (Power BI Desktop 2.157.879.0)

Draft by Team-Thinker (Sonnet 5.5), 2026-11-17. Plan: `docs/plans/2026-11-17-rea-msmdsrv-calculate-pilot.md`.
Clean room: behaviour only, no decompiled code. Everything here is a hypothesis until the Power BI answer check confirms it.
The Power BI answer check was NOT run for this draft (no VM use, no `tools/dax_oracle_diff.py`).

## Summary

- Verdict on readability: **partly readable, not enough**. Names, source-file paths and assertion messages are readable. One function
  (the filter-context wrapper) is readable in outline. The core CALCULATE evaluator (filter merging, ordering, KEEPFILTERS, context
  transition) was NOT reached: the strings for `XLLogOp_Calculate`, `CALCULATE.CONDITIONAL`, `XLCalculateConditional` and the
  `CalculateBooleanFilter` setting have no direct references in the file (they are reached through tables/vtables that Ghidra did not resolve).
- The file has no symbols (PDB 404), so every function is `FUN_...`; I renamed five with `_guess` names in the live session (renames are not saved).
- Candidate rules: 4 are plain-words hypotheses, none confirmed, none clearly new. Three look like behaviour our app already has batteries for.
  One (implicit CALCULATE eligibility) is unknown and could be new.
- Pilot pass criterion ("one new rule found in code AND confirmed by the answer check") is **not met** by this draft.
  A fair next step is one cheap answer-check round on the formulas below, then stop or go deeper on the vtables.

## REA evidence

Target: `msmdsrv.exe`, SHA-256 f71b3817...3c7, Ghidra 12.1.4 full analysis. Bundle: `~/Library/Caches/codex-powerbi-rea/2.157.879.0/msmdsrv-calculate-evidence.json` (38 records).

| Component | Address | Evidence ID | What it shows |
|---|---|---|---|
| `xlcalculate.cpp` user | FUN_1014b5800, 0x1014b5800-0x1014b68ab (named `XLCalculate_ExecuteIMBIDrillThrough_guess`) | ev_782897f03b0d7077b9808567145d95e3feb8dedd9f0b3e40c7cb8f4b229e503b (analyze_function; earlier ev_4987a810..., ev_4fcd1295..., ev_b96d114e...) | The only references to `xlcalculate.cpp` are inside a function whose own assertion text says `XLCalculate::ExecuteIMBIDrillThrough` and `Condition failed: spXLTable`. It is a drill-through query executor, NOT the CALCULATE function. One caller (FUN_1011c7bc0), 38 callees. |
| `CalculateTable_Vertipaq` | string 0x10306e570; used at 0x1014b6b9d inside FUN_1014b6b60 (0x1014b6b60-0x1014b6bb4, 85 bytes) | ev_7f9d6cea251b5d4926d5f9af2a483944e702b5aeaefd82904fc57b739d6c5148 (xrefs), ev_216a52fb7005db7d0957d3361d5361ea2e749fdee36c0299777e1170f1c25aa7 (containing function), ev_024cf99bf0a2a750fa66ba2f36c4f20f5bd63fd14e744704d1f2566e8a853dc7 (pseudocode) | A tiny function that only returns the text "CalculateTable_Vertipaq" (a label, probably for trace/profiler events). Shows a CALCULATETABLE storage-engine path exists and is labelled, no logic. |
| `FilterCtxFixer::WrapCalculate` | FUN_101c0cc00, 0x101c0cc00-0x101c0d725 (2849 bytes, 3 ranges); strings 0x10310fa38/0x10310fab0; one caller site 0x101c0d730 | ev_0bbbfee89376cdfe13fc6269d53dbff598f6c9625a7f55ae10882f9ba0452164, ev_0c97498dc461350451ee3d77a333cf8d30d6016944ce7703f14704a65a218117 (xrefs), ev_f18e9de39bbd3df8351909149588ea2fafcb6e70608e8daa4611ce088a58b97e (containing), ev_fb7ec47b125cfa54d50f9f5d3f3d3304ff9b04c008331d3b868e829a414933ff (pseudocode), ev_6e57a18a6b23d4667602fbfdf74c5ff0734cb9b45010cef8216714e210756cf7 (callers) | Readable in outline. Source file `xldq\xldqas_filterctx.cpp` ("DQ over AS": remote/composite-model queries). It builds DAX TEXT: `CALCULATE(` or `CALCULATETABLE(`, then `ALL(`/`ALLSELECTED(` per column, then `USERELATIONSHIP` and `CROSSFILTER` lists, then `)`. |
| `XLCalculationItem::ApplyImplicitCalculate` | FUN_1014a7860, 0x1014a7860-0x1014a7c97 (1075 bytes); string 0x10306d3e8 | ev_3ea5fc8b31d5dfe5d590f4553b147ff49940c869ed08408f696e85dcc91d5833 (xrefs), ev_1c7cda45de46a31a7a30f0f565e509dfdb8c04a80cefc7781d681ff1e93c4975, ev_5e5eabd108634c628852e185dc914fa08646cb13082ea9f18a109ce9229c12e4, ev_d52b5f72dc2819944553f492badd84c664727e2193ee4e6f6e1c4b12b13f0002 (no direct callers: virtual call) | Source file `xl\xlcalculationgrouplogopbuilder.cpp`. Mostly object plumbing. Readable fact: an assertion that the expression id is not in the viewpoint's "ineligible expression" list. |
| `XLMeasureItem::ApplyImplicitCalculate` | FUN_1014a7ca0, 0x1014a7ca0-0x1014a7f54 (693 bytes); string 0x10306d4b8 | ev_b5c659a41a66c211e8bebadfb9390cf852cca3495f5bdf5358dfc8bc84464e06, ev_539b8533b87c5753cc5fac75cba5ae52235b9af5b3f41148ce8bae2e9e2a98dc, ev_96c171fa8e75a56e39ba01b29c3d320d566fd5e95b2245d7eedad31612927810 | Same shape and the same "ineligible expression" assertion; simpler (no model-table lookup). The assertion text itself is at 0x10306d418 (ev_9fac4f8ed3939082d64bc21a3bc2f34f4f3e9c276f445d47c780eee3746794a4). |
| `XLLogOp_Calculate<XLScaLogOp/XLRelLogOp>` | strings 0x10306e2a8, 0x10306e2e8 | ev_9b56fb838c9439c483ba7e17bb6eb665e566068b8edae6dda34224976dfa37d5 (strings), ev_21f9eb95ad1764fe7b807d84899e5f4ac1e09fe8eb6a8bf741e674b74cdc9d31, ev_5cef52f27d77574ea8c484494538da80386dc686b9583f902a853f68c02a72f4 (no xrefs) | Operator names only. No code found. |
| `CALCULATE`, `CALCULATE.CONDITIONAL`, `CALCULATETABLE` function-name table | 0x102e302c8, 0x102e302e0, 0x102e30310 | ev_1d676a3f83d178ac3f1724a6a9c007d87c63d382d1e52c1bb21f19b3ecc6ad75, ev_0bbdf0d1ee01f32d5ff153220c6037f8cc8268a2322e2744eef6eb90dbab9e01, ev_549f43d7b0e2bda8f38a113c0069f8fe9fbfff3626b0ae2d1651f0c96103638e (no xrefs) | Names in a DAX function table, not tied to a handler by REA. |
| `XLCalculateConditional` | string 0x103089fe8 | ev_fd150ee3c2922c987c41a5ac79406af3c392a504aa57bbfece1608e136275b30, ev_3a6cd5d8e3365cc1537d444e1427f404548c418747c8becb24e077fa77d98510 (no xrefs) | Name only. |
| `ConfigurationSettings\DAX\CalculateBooleanFilter` | string 0x102ed7ae0 | ev_dc71811ad05c0a80de36348bf4596252821eb83d3a1a0e9c3e5e2e9cfeca4f2b, ev_b8bac272d244bd924768584f84c44a50d280a468cfa96883217b707761c40a3a (no xrefs) | A hidden setting name exists; the code that reads it was not found. |

Renames done in the live REA session (not persisted): FilterCtxFixer_WrapCalculate_guess (0x101c0cc00), XLCalculationItem_ApplyImplicitCalculate_guess (0x1014a7860), XLMeasureItem_ApplyImplicitCalculate_guess (0x1014a7ca0), XLCalculate_CalculateTable_Vertipaq_name_getter_guess (0x1014b6b60), XLCalculate_ExecuteIMBIDrillThrough_guess (0x1014b5800). Rename evidence: ev_cbb7230f..., ev_b0e2e2f6..., ev_ac9d7167..., ev_d5306817..., ev_598a3200....

What REA could NOT establish:
- The scalar CALCULATE evaluator, the order in which filter arguments are applied, KEEPFILTERS handling, context transition rules. No function was linked to them.
- What `CalculateBooleanFilter` changes, or what `CALCULATE.CONDITIONAL` is (internal variant, not documented).
- Anything about the local import (VertiPaq) path: WrapCalculate belongs to the DirectQuery-over-AS / composite path.
- The call graph around these functions: unresolved virtual calls (no direct callers for the ApplyImplicitCalculate pair). I did not run unbounded call-graph traces.
- Field meaning inside the decompiled structures (all offsets unnamed), so flags such as "viewpoint column flag" are interpretations from loop shapes.

## Candidate rules

Each: "when X, Power BI does Y". All confidence values are about the rule being TRUE for local import models, not about the reading.

R1. When a nested context differs from the outer request in no column and no relationship override, the engine adds no CALCULATE wrapper at all; the wrapper appears only if at least one column's filter state differs or a USERELATIONSHIP/CROSSFILTER override exists.
Evidence: FUN_101c0cc00 (ev_fb7ec47b...) sets a "differs" flag in a first pass and skips output unless it, or either override list, is non-empty. Confidence: low (remote-query only; likely an optimisation, no visible result change). Our app: no result-visible rule. Not testable except as "same result".

R2. When a column is filtered in the outer request but cleared/changed in the inner viewpoint, the engine restores the OUTER selection with ALLSELECTED for that column; when the column is not filtered in the outer request it clears it with ALL. An internal assertion says the restore case requires an "all selected" state, and another says "Unreachable code path" if a column is in the restored set but its flag says otherwise.
Evidence: same function. Confidence: medium that this describes ALLSELECTED = "put back the outer shadow filter", which is documented behaviour. Our app: likely known (batteries `dax_battery_allselected*.json`, `_shadow`, `_iterators`; `analytics_studio/measures.py`, `dax_ct_filters.py`). Verdict: known.

R3. Relationship overrides (USERELATIONSHIP, CROSSFILTER) are part of the filter-context state that is carried into nested evaluation and into generated queries, and they are emitted AFTER the column filters, with USERELATIONSHIP before CROSSFILTER.
Evidence: same function, the two list writers appear in that order. Confidence: medium for "carried as context state"; low for any user-visible ordering effect. Our app: has USERELATIONSHIP/CROSSFILTER code (`relationships.py`, `measures.py`) and batteries (`dax_battery_adversarial.json`, `round2`). Verdict: probably known; the nested-measure case (formulas 11-12) is the part worth a check.

R4. Implicit CALCULATE (the automatic context transition around a measure reference or calculation item) is refused/asserted for expressions that the current viewpoint lists as "ineligible"; the engine expects the planner never to apply it to those.
Evidence: assertion text at 0x10306d418 in both ApplyImplicitCalculate functions (ev_5e5eabd1..., ev_96c171fa...). Confidence: low. What "ineligible" means is unknown (guess: expressions already being evaluated, i.e. recursion or already-wrapped measures, or calculation items already applied). Our app: unknown; this is the only candidate that could be new. Needs the nested-measure formulas below plus calculation groups, which our app may not model.

R5 (not a rule, a lead). `CalculateBooleanFilter` hidden setting and `CALCULATE.CONDITIONAL` exist. No behaviour read. Do not write test formulas until the reading function is found.

## Test formulas

Data: table `VAT` from `tests/Data/Vat File -Aug 2026.xlsx` sheet `VAT 5%`, header row 12. Columns: Date, Particulars, Address, Emirates, Voucher Type, Voucher No., Voucher Ref., TRN, Quantity, Value, Gross Total, Sales, VAT-5%, Discount. I have not checked which values the Emirates and Voucher Type columns contain beyond the first two rows (Sharjah, Ras Al Khaimah; SALES-LOOPS), so the literals below are placeholders to adjust. All expected answers must come from the Power BI answer check, not from this document.

Run each as `EVALUATE ROW("x", <expr>)` or inside `DEFINE MEASURE`:

1. `CALCULATE(SUM(VAT[Sales]), ALL(VAT[Emirates]))`
2. `CALCULATE(SUM(VAT[Sales]), VAT[Emirates]="Sharjah", ALLSELECTED(VAT[Emirates]))` (R2: modifier and filter on the same column)
3. `CALCULATE(CALCULATE(SUM(VAT[Sales]), ALLSELECTED(VAT[Emirates])), VAT[Voucher Type]="SALES-LOOPS")` (R2: nested)
4. `CALCULATE(CALCULATE(SUM(VAT[Sales]), ALLSELECTED()), VAT[Emirates]="Sharjah")` (R2: ALLSELECTED with no argument)
5. `SUMX(VALUES(VAT[Emirates]), CALCULATE(SUM(VAT[Sales]), ALLSELECTED(VAT[Emirates])))` (R2: iterator shadow context)
6. `COUNTROWS(CALCULATETABLE(VAT, VAT[Emirates]="Sharjah", ALL(VAT[Emirates])))` (modifier vs filter order, table form)
7. `CALCULATE(SUM(VAT[Sales]), REMOVEFILTERS(VAT[Emirates]), ALLSELECTED(VAT[Emirates]))` (R2: two modifiers on one column)
8. `CALCULATE(SUM(VAT[Sales]), ALLEXCEPT(VAT, VAT[Emirates]), VAT[Voucher Type]="SALES-LOOPS")` (R2/R1)
9. `CALCULATE(SUM(VAT[Sales]), KEEPFILTERS(VAT[Emirates]="Sharjah"), VAT[Emirates]="Ras Al Khaimah")` (context check, unrelated to a found rule, as control)
10. `CALCULATE(SUM(VAT[Sales]), VAT[Quantity]>50, VAT[Quantity]<200)` (boolean filters on one column: where the hidden setting may act)
11. `DEFINE MEASURE VAT[M1] = SUM(VAT[Sales])  EVALUATE ROW("x", CALCULATE([M1], ALLSELECTED(VAT[Emirates])))` (R4: measure reference under context change)
12. `DEFINE MEASURE VAT[M1] = SUM(VAT[Sales])  MEASURE VAT[M2] = CALCULATE([M1], VAT[Quantity]>50)  EVALUATE ROW("x", CALCULATE([M2], ALLSELECTED(VAT[Quantity])))` (R4: nested measure inside a context that already narrowed the same column)
13. `DEFINE MEASURE VAT[M1] = SUM(VAT[Sales])  EVALUATE ROW("x", SUMX(VALUES(VAT[Voucher Type]), [M1]))` (R4: implicit CALCULATE per row)
14. `DEFINE MEASURE VAT[M1] = SUM(VAT[Sales])  EVALUATE ROW("x", CALCULATE([M1], USERELATIONSHIP(VAT[Date], VAT[Date])))` (R3: expect an error; check the message wording only if useful)

R3 properly needs a model with two relationships to a Dates table (guest scratch tables, per the standing user OK). Not written here.

## Open questions

1. Is R4 "ineligible expression" visible to a user at all (probably only a planner invariant)? If it is only an assertion, there is no rule to test.
2. Where are the vtables for `XLLogOp_Calculate<XLScaLogOp>` and the DAX function table at 0x102e302c8? A bounded search for the code that reads them (data references into the 0x102e30xxx table by index, or `search_bytes` for the 8-byte pointer to the string) is the cheapest next REA step. Worth one try; stop if it needs a vtable walk by hand.
3. Who reads `CalculateBooleanFilter`? The registry-path string has no direct references; the setting likely sits in a name-to-handler table.
4. Our existing batteries and ledger status for R2/R3 were not checked line by line (only file names listed). Before any coder task, check `PARITY_LEDGER.md` for locked items.
5. If the user decides the pilot has failed: the honest result is "REA gives labels and assertions, plus the remote-query wrapper; the evaluator is behind virtual dispatch and has no symbols".
