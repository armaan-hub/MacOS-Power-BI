# Task 96 (Iteration 185): CROSSFILTER directions and CROSSFILTER with USERELATIONSHIP (crossfilter-dirs-86)

DAX close-out finding (2026-11-08, relationship battery on models ZO and ZB of `tests/critic3_models.py`):
one wrong answer class and three refusal gaps.

**Spec:** `docs/plans/2026-11-08-crossfilter-dirs-86-spec.json` — 630 live Power BI cases (`cases.ZO`, `cases.ZB`;
run each expression with `tests.critic3_models.ours_for(model, expression)`). Main: 378 match, 234 refused, 18 wrong.
Target: 0 wrong, as few refusals as possible.

## Measured behaviour (A = first column's table = "left", B = second column's table = "right")
1. **Wrong today:** `USERELATIONSHIP(r)` and `CROSSFILTER(<same relationship r>, NONE)` in the same CALCULATE →
   Power BI error `USERELATIONSHIP and CROSSFILTER functions have been used within a single CALCULATE function to specify
   incompatible settings.` (the app answers). Other directions on the same activated relationship (BOTH, ONEWAY,
   ONEWAY_RIGHTFILTERSLEFT) are accepted and apply to that now-active relationship.
2. **ONEWAY_RIGHTFILTERSLEFT / ONEWAY_LEFTFILTERSRIGHT on a many-to-one relationship:** when the side that filters is
   the ONE side → identical to ONEWAY (one side filters the many side). When the side that filters would be the MANY
   side (e.g. `CROSSFILTER(Fact[Prod],Dim[Prod],ONEWAY_LEFTFILTERSRIGHT)`, `CROSSFILTER(Dim[Prod],Fact[Prod],ONEWAY_RIGHTFILTERSLEFT)`)
   → Power BI error `The CROSSFILTER function cannot be used to enable only the many-side of a many-to-one relationship to filter the one-side.`
   (This error holds even when that relationship is inactive or activated by USERELATIONSHIP.)
3. **CROSSFILTER on an inactive relationship** (no USERELATIONSHIP for it in the same CALCULATE): no effect — the result
   equals the plain model (for NONE, BOTH, ONEWAY, ONEWAY_RIGHTFILTERSLEFT alike).
4. **USERELATIONSHIP(Ship) with CROSSFILTER on the normally-active relationship (Dt) it deactivates:** accepted;
   the spec gives the answers (derive: the deactivated relationship stays inactive, so the CROSSFILTER on it has no effect,
   unless the spec shows otherwise — check every case against the spec).
Today's refusal messages are "CROSSFILTER needs an active relationship in this local subset." and
"CROSSFILTER Oneway_Rightfiltersleft/Oneway_Leftfiltersright is not supported for a many-to-one relationship."; find them in
`analytics_studio/` (grep) — that is where the work goes.

## Part 1 (Haiku)
- [ ] Step 1: test `tests/test_iteration185_crossfilter_dirs_86.py` over all 630 spec cases (spec read in the test only):
  `ERR:` → local is a LOCAL-REJECT / error; else equal via `tools.dax_oracle_diff.same` (a refusal is NOT allowed for the
  value cases covered by rules 1–4).
- [ ] Step 2: run it (fails on main).
- [ ] Step 3: implement rules 1–4.
- [ ] Step 4: run the new test, and every tests/*.py mentioning CROSSFILTER or USERELATIONSHIP, and the iteration 176–184 tests — all pass.
- [ ] Step 5: leave uncommitted, report (Opus commits).
