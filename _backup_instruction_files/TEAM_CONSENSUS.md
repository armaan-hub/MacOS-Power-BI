# Team Consensus — plan — M delimiter operations

## Team

Power Query and ETL Architect + BI Compatibility and Data Integrity Auditor

## Round 1 proposals

**Power Query and ETL Architect:** Add the six existing local operations through standard M calls. Use one-item `Splitter.SplitTextByEachDelimiter` for first split; use `Text.Split` and `Table.ExpandListColumn` for split-to-rows; derive every-split column count from table values; wrap delimiter extraction to preserve empty strings; use `QuoteStyle.None` for merge.

**Compatibility Auditor:** Accept only literal forms, explicit empty defaults, and numeric occurrences. Reject fixed-width all-split calls and non-text sources. Cover empty, adjacent, leading, trailing and repeated separators, output width changes, merge order, and unsupported M selectors. Local parser equivalence alone cannot prove execution by Microsoft's Mashup engine.

## Round 2 cross-critique

**Architect on Auditor's proposal:** A fixed output count for splitting every delimiter would fail when refresh changes the number of segments. A data-derived M count is possible and keeps the emitter independent of the current preview. Tests must include an empty table and a later wider input.

**Auditor on Architect's proposal:** The dynamic count must use the current step's actual text values and a minimum of two, with an explicit empty-string default. The parser should recognize only the emitted count expression; accepting arbitrary user-supplied counts would silently change schema. Keep null fidelity and external runtime claims explicitly outside this model.

## Round 3 convergence

**Final consensus:** Implement all six mappings only in the exact bounded shapes above. Validate type state across the whole sequence, preserve the local transform step representation, and make unsupported or lossy shapes remain blocked.

**Key decision:** Every-delimiter column width is calculated from `Table.Column` and `Text.Split` on the current step, with `2` included as the minimum. The width therefore changes with refreshed source data.

**Rejected alternatives:** Static output names/counts and the default null padding are rejected because local output width and blank values differ. Relative-from-end occurrence lists, quote-aware splitting, arbitrary list expansion, and a general M runtime are out of scope here.

## Review follow-up — strict custom M expression typing

The safety review found that `Text.From` could hide invalid nested calls: `Number.Round`'s optional precision was not checked, known-invalid arguments were ignored when a sibling field's type was unknown after header reshaping, and an explicit `null` was conflated with an unknown type. The expression type checker now validates every known argument, distinguishes explicit null from unknown, rejects null in required `Text.Replace`/`Text.Contains`/`Text.StartsWith`/`Text.EndsWith` text parameters, and preserves nullable parameter positions. Positive and negative cases are covered in the focused M suite.

Acceptance after review: `PYTHONPATH=. pytest -q tests/test_power_query_m_editor.py` passes **42 tests and 88 subtests**; `PYTHONPATH=. pytest -q` passes **511 tests and 365 subtests**. This establishes local parser/type-checker and replay behavior only. It does not establish semantic equivalence with Microsoft's Mashup engine or full M support.


## Review follow-up — M locale conversion scope

The compatibility review found three false-acceptance risks in M type conversion: `Currency.Type` was being reduced to ordinary decimal; whole-number conversion did not match M rounding or the signed Int64 range; and decimal conversions allowed values outside Double range. The parser now rejects `Currency.Type`; whole-number conversion with or without a culture uses ties-to-even and enforces Int64 bounds; decimal conversion rejects Double overflow and normalizes underflow to signed zero. Focused tests cover halfway values, both exact boundaries, overflow in both directions, decimal overflow/underflow, and unsupported currency. Microsoft documents the relevant behavior in [Int64.From](https://learn.microsoft.com/en-us/powerquery-m/int64-from), [Currency.From](https://learn.microsoft.com/en-us/powerquery-m/currency-from), and the [M number value specification](https://learn.microsoft.com/en-us/powerquery-m/m-spec-values). The M suite passes **46 tests and 107 subtests**; the complete suite passes **515 tests and 385 subtests**. This remains a bounded local compatibility subset.

## Review follow-up — `Table.Transpose` type safety

The one-argument `Table.Transpose` form round-trips to the local transpose step. Review found false acceptance from numeric-looking text, native numeric semantics, and normalized storage merging null with empty text. Cell-dependent M operations after transpose are now rejected; schema changes and row-position operations remain supported. The optional M `columns` argument remains unsupported. Focused M tests passed **48 tests and 112 subtests**; the complete suite passed **517 tests and 389 subtests**. `py_compile` and `git diff --check` passed. Microsoft documents the operation in [Table.Transpose](https://learn.microsoft.com/en-us/power-query/transpose-table). This verifies local parsing and replay, not the Mashup runtime.
