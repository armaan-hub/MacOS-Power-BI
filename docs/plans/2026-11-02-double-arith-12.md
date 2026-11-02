# Task 22 double-arith-12: Double arithmetic in doubles, Int64 wrap and range, ROUND of huge values

**Coder:** Haiku 5.5 (subagent). **Fixer:** Sonnet 5.5. **Planner / reviewer:** Claude Opus 5.5.
**Spec:** `tools/parity/task22_double_arith_spec.json` (4,051 answers measured live in Power BI Desktop 2.157.879.0 on the iPad guest, standard Facts table; each item has `part`, `expr`, `powerbi`, `now`). Now: 3,763 match, 8 refused, 276 wrong.
**Branch:** `haiku/double-arith-12`.

## Global constraints
- Compute, never look up (`tests/test_no_answer_key_in_app.py`). Never edit saved Power BI answers.
- A locked item that stops matching is a regression: fix the code. If a Part cannot keep every locked item, make the uncertain shape refuse (MeasureError), never guess.
- Values stay `decimal.Decimal` in the engine. A result computed in doubles is stored as `Decimal(float_result)` (the exact binary value), so a later double operation recovers the same double. Text of a Double is already printed from its exact binary value at 15 digits (`dax_typed._significant`, Task 20).
- Do not change XNPV / XIRR internals: making `/` a true binary division broke 6 saved XNPV answers in Task 20. If the Part A change reaches them, keep XNPV on its own arithmetic.
- Do not run the full pytest suite; Claude runs it. Run the spec scorer and the replay after each Part.

## Measured rules (Power BI)

### Part C: Int64 wraps at 64 bits (17 wrong)
`+ - *` of two Int64 operands (whole-number literals, Int64 columns, COUNTROWS, logical values) wrap two's-complement:
`9223372036854775807+1` = -9223372036854775808; `9223372036854775807*2` = -2; `-9223372036854775807-2` = 9223372036854775807;
`3037000500*3037000500` = -9223372036709301616; `4294967296*4294967296` = 0; `9007199254740993*9007199254740993` = 18014398509481985;
`MAX(Facts[Quantity])*9223372036854775807` = 9223372036854775803 (Quantity max is 5). An Int64 beside a Double (`9223372036854775807+1.0`, `+0.5`) is a Double. Check how existing Currency wrap (`_currency_wrap`, Task 20 F5) is written and keep it.

### Part D: functions that need an Int64 (154 wrong)
INT, FLOOR, CEILING, QUOTIENT, MROUND, CONVERT(x,INTEGER) of a value outside the Int64 range (|x| >= 2^63, Infinity, e.g. 9.3E18, 1E19, 1E300, 2^63, -(2^63)) are the error "The result of a conversion or arithmetic operation is either too large or too small."; IFERROR/ISERROR catch it. MOD outside that range is the error ending "…type or the result is too large or too small." (see the spec for the exact text). Inside the range the value is the exact double: `INT(9.223372036854775E18)&"z"` = `9223372036854774784z`. `MOD(1E16+0.5,7)` is the MOD error too: read the spec for MOD's exact boundary and refuse what it does not settle. Also: `INT((x)*1E15)` beyond the range (most Part D items) is the error.

### Part E: ROUND family of huge or non-finite values (29 wrong, 4 refused)
ROUND, ROUNDUP, ROUNDDOWN (any digits), TRUNC and EVEN of a finite value beyond 1E16-ish return the value unchanged: `ROUND(1E300,14)` = 1E+300, `TRUNC(-1E300)` = -1E+300, `EVEN(1E300)` = 1E+300, `ROUND(1E308+7,14)` = 1E+308. TRUNC and ROUNDDOWN of +Infinity are NaN. The engine now gives NaN (Decimal overflow) or refuses. Read the spec for the exact rows.

### Part F: overflow and underflow (19 wrong, 4 refused)
Arithmetic past the Double range is ±Infinity (`SUMX({1,2},1E308-123456.789)` = Infinity, `1E308*10`), below it rounds to the nearest double: `5E-324/2` = 0, `5E-324*9007199254740993` = 4.4501477170144E-308 (subnormal, double rounding). Follows from Part A if Part A is done in doubles; keep the Part F rows as a check.

### Part B: iterators accumulate in doubles, in row order (9 wrong)
SUMX / AVERAGEX of a Double body add in doubles in the table's row order: `SUMX({1E16,1,-1E16},[Value])` = 0, `SUMX({1,1E16,-1E16},[Value])` = 0, `SUMX(Facts,0.1)-0.6` = 1.11022302462516E-16, `SUMX(Facts,Facts[Sales]*0.1)-SUM(Facts[Sales])*0.1` = -4.44089209850063E-16, `SUMX({0.1,0.2,0.3},[Value])=0.6` is False. Int64 and Currency bodies keep their own sums (Currency wraps per Task 20). Check the spec before changing SUM/AVERAGE of a column.

### Part A: Double arithmetic in doubles (48 wrong)
When either operand of `+ - * /` is a Double (a decimal literal, a text number, a Double column value, a Double-typed function result, a Currency beside a Double in `+`/`-`, TRUE() beside a Double), compute in IEEE doubles and keep the exact double:
`(100.1-100)&"z"` = `9.99999999999943E-02z` (the same for `100.1-100.0`, `"100.1"-"100"`, `"100.1"-100`, `CURRENCY(100.1)-100.0`, `100.1-CURRENCY(100)`); `(0.1+0.2)=0.3` False; `(0.1*3)=0.3` False; `(1-0.9)=0.1` False; `(0.3/0.1)=3` False; `(1/3*3)=1` True; `(0.07*100)=7` False; `(3*1.1)=3.3` False; `(MAX(Facts[Sales])+0.1-MAX(Facts[Sales]))&"z"` = `0.100000000000001z`; `(1E15+0.3+MAX(Facts[Sales])/7-1E15+0.3)&"z"` = `3.425z`.
Comparisons of Doubles are exact on the doubles. Int64 with Int64 stays Int64 (Part C); Currency with Currency stays Currency; Currency `*`/`/` Double is Task 21 Part A (already doubles). Date arithmetic keeps its tick rounding unless the spec says otherwise.

## Order for the coder
C, D, E, F, B, A (A last: it touches the most locked answers). After each Part: spec scorer for that Part (0 wrong; refusals allowed and listed), targeted tests, replay `PYTHONPATH=. QT_QPA_PLATFORM=offscreen caffeinate -i python3 tools/parity_check.py` (0 DIFF, 0 CRASH, PARITY GATE PASSED), `git checkout PARITY_LEDGER.md`.

## Tests
`tests/test_iteration111_double_arith_12.py`, one class per Part, values from the spec.

## Review focus
1. Locked answers that match today only because Decimal arithmetic hides a last digit that Power BI's 15-digit text also hides: Part A must not break them (the replay shows it).
2. XNPV / XIRR / financial functions after Part A.
3. Type tests (ISDOUBLE / ISINT64) after Part C wrap: the wrapped value is still Int64.
4. Date + Double: tick rounding versus doubles.
5. Iterators over a Variant body (mixed Int64 and Double rows) after Part B.

## Review outcome (2026-11-02)
Shipped as Iteration 111. Fresh probes on 3 tables: 0 right-to-wrong, about 1,140 wrong-to-right. Gate rounds fixed TRUNC/ROUND with fractional digits (15-digit read), the POWER odd root of a Double exponent, and 8 stale exact-decimal test expectations checked live in Power BI. Locked 436,230. Open items moved to Task 23.
