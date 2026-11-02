# Task 20: never-blank-zero-10 (what ISBLANK evaluates, the sign of zero and NaN, the logical BLANK, Currency limits, Double text)

**Branch:** `haiku/never-blank-zero-10`  **Written by:** Claude Opus 5.5, 2026-11-02  **Status:** see `HANDOFF.md`
**Who builds:** Haiku 5.5, one Part at a time, started by Opus 5.5. A Part that fails twice goes to Sonnet 5.5.

Read first: `AGENTS.md` ("Compute, never look up"). Every rule below was measured in Power BI Desktop on 2026-11-02, about 3,900 designed probes on top of the Task 19 review answers.

## Goal
1,669 items in `tools/parity/task20_never_blank_zero_spec.json` (fields `part`, `expr`, `powerbi`, and `app_answer` or `app_refusal`). 1,129 are wrong today, 535 refused, 5 crash. The spec is for reading and for the scoring script; the app must never read it. Clearing a wrong answer matters most. An honest refusal is better than a wrong answer.

## Part A: what ISBLANK evaluates (`_never_blank`, `measures.py` near line 3099, and the ISBLANK branch near line 16352)
Power BI answers False without evaluating when a static analysis says the argument can never be BLANK. Otherwise it evaluates, and an error is an error. The old "ponytail" rule in the ISBLANK branch, which swallows a function's own error (`own_error`, `swallowed`), is a guess at this and must go, with its exception list. `ISBLANK(FACT(-1))` is an error, `ISBLANK(SQRT(-1))` is False, `ISBLANK(IF(TRUE(),SQRT(-1)))` is an error, `ISBLANK(IF(TRUE(),SQRT(-1),2))` is False.

Replace `_NEVER_BLANK_CALLS` with one table:
- **Never blank whatever the arguments:** EXP LN LOG LOG10 NOT AND OR, the type tests ISBOOLEAN ISCURRENCY ISDATETIME ISDECIMAL ISDOUBLE ISERROR ISINT64 ISINTEGER ISLOGICAL ISNONTEXT ISNUMBER ISNUMERIC ISSTRING ISTEXT, PI RAND NOW TODAY UTCNOW UTCTODAY TRUE FALSE USERNAME USERPRINCIPALNAME USERCULTURE, CONTAINSSTRING CONTAINSSTRINGEXACT EXACT FIND SEARCH FORMAT ISAFTER ISONORAFTER PATHCONTAINS RANDBETWEEN, EFFECT NOMINAL COUPDAYBS COUPDAYS COUPDAYSNC COUPNCD COUPNUM COUPPCD PDURATION RRI SLN TBILLEQ TBILLPRICE TBILLYIELD RATE INTRATE PRICEDISC RECEIVED SYD YIELDDISC ACCRINTM DB DDB DISC MDURATION PRICEMAT VDB YIELDMAT CUMIPMT CUMPRINC YIELD AMORDEGRC AMORLINC ODDLPRICE ODDLYIELD ACCRINT DURATION PRICE ODDFPRICE.
- **Never blank when the first argument is:** ABS CURRENCY DATEVALUE DAY FIXED HOUR INT ISO.CEILING LEFT LEN LOWER MINUTE MONTH PATHLENGTH QUARTER RIGHT SECOND SIGN SQRT TIMEVALUE TRIM TRUNC UNICHAR UPPER VALUE WEEKDAY WEEKNUM YEAR CEILING DOLLARDE DOLLARFR EDATE EOMONTH FLOOR MOD MROUND POWER QUOTIENT REPT ROUND ROUNDDOWN ROUNDUP YEARFRAC MID SUBSTITUTE.
- **Never blank when any argument is:** CONCATENATE DATE TIME.
- **Never blank when the third argument is:** PMT PV NPER FV.
- **Never blank when every argument is:** MAX and MIN of two scalars, ISPMT PPMT IPMT REPLACE.
- **IF with three arguments:** both branches; the condition is not looked at. Two arguments: evaluated.
- `x IN {..}` is never blank, like a comparison.
- `x^y` is judged like POWER: by its base only (measured: `ISBLANK((1/0)^(FACT(-1)))` is False, `ISBLANK((FACT(-1))^(1/0))` an error). This replaces the `*`-style "both sides" for `^`.

**`x^y` and `POWER(x,y)` with an infinite or NaN operand, for every numeric type (measured; this replaces the Currency-only line in Part D).** True is 1, False is 0.
- A BLANK base with a non-BLANK exponent is BLANK, also for infinite or NaN y. A BLANK exponent with a non-BLANK base is 1, also for infinite or NaN x. BLANK^BLANK stays the error.
- x infinite or NaN and y finite: y=0 gives 1, y<0 gives 0, y>0 is the POWER error. x and y both non-finite: the error.
- x finite and y=+Infinity: the error, for every x. x finite and y=-Infinity or NaN: x>=0 gives 0, x<0 the error.
- **Everything else is evaluated**, including SIN COS TAN and the other trigonometry, DEGREES RADIANS, FACT COMBIN COMBINA PERMUT GCD LCM SQRTPI EVEN ODD ISEVEN ISODD UNICODE, the BIT functions, the statistics (NORM.* T.* CHISQ.* BETA.* EXPON.DIST POISSON.DIST CONFIDENCE.*), PATHITEM PATHITEMREVERSE NETWORKDAYS DIVIDE COALESCE IFERROR SWITCH IF.EAGER CALCULATE CONVERT DATEDIFF COMBINEVALUES EVALUATEANDLOG, a VAR block, a measure, and an ERROR call.

So `ISBLANK(1+FACT(-1))` is False (`+`: either side) and `ISBLANK(ABS(FACT(-1)))` is an error (ABS needs its first argument, FACT is evaluated). `ISBLANK(LEFT(MAX(Facts[Note]),-1))` is an error, because a column aggregate can be BLANK. `ISBLANK(VAR y=1+ERROR("x") RETURN ABS(y))` is an error; `ISBLANK(VAR y=BLANK()+ERROR("x") RETURN 1)` is False, because the unused VAR is not evaluated. The Currency-division check in that branch stays.

## Part C: the logical BLANK (do this after A)
`a&&""`, with a true `a`, and `a||""`, with a false `a`, take the right side. An empty text there gives a BLANK typed True/False. Also `TRIM("")`, `LEFT("a",0)`, `AND(a,"")`, `OR(a,"")`. It is an ordinary BLANK at run time, with two exceptions.
1. **Static type stays:** `ISBLANK` is False, `COALESCE` and `IFERROR` return it (printed BLANK, in text empty), `ISNUMBER(x*2)` is True, `ISLOGICAL` True. `ISBLANK(x*2)` and `ISBLANK(x*"a")` are False because `*` of two never-blank operands is never blank.
2. **It cancels an error** like a BLANK that scans nothing, on both sides of `*` and on the left of `/`: `(1&&"")*ERROR("x")` and `ERROR("x")*(1&&"")` are BLANK, `IFERROR((1&&"")*SQRT(-1),7)` BLANK, `(IFERROR((1&&"")*SQRT(-1),7))+0` is 0, `ISERROR((0||"")*ERROR("x"))` False. Remove the refusal `refuse_logical_blank_beside` where this answers it. `CONVERT(1&&"",DATETIME)+1` is `12/31/1899 00:00:00`.

**A left side that needs a scan gives False instead**, not a BLANK: `SUM(Facts[Sales])&&""` is False, `(SUM(..))&&""&"z"` is `FALSEz`, `AND(SUM(..),"")` False, `OR(SUM(..)<-1000,"")` False, and in a row context `Facts[Sales]&&""` and `Facts[Sales]>1&&""` are False, so `COUNTAX(Facts,Facts[Sales]&&"")` counts every row.
- Needs a scan: a column read in a row context, SUM AVERAGE COUNT COUNTA COUNTBLANK, SUMX, MINX or MAXX of anything but a plain column, COUNTROWS(FILTER(..)) with a predicate reading a column, ISEMPTY, LOOKUPVALUE, FIRSTNONBLANK, CALCULATE with a filter that is not ALL, and anything containing one (`1+SUM(..)`, `ABS(SUM(..))`, `IF(SUM(..)>0,1)`, a VAR of one).
- Needs no scan: constants, MAX and MIN of a column, MAXX of a plain column, DISTINCTCOUNT, COUNTROWS of a table or of ALL or VALUES or `FILTER(t,TRUE())`, HASONEVALUE, ISFILTERED, CALCULATE of those with no filter or an ALL filter.
`(COUNTROWS(FILTER(Facts,FALSE())))||""` is False. A false `a` in `a&&""` is plain False, as today. `"a"` or any non-empty text on the right is the conversion error, as today.

## Part B: the sign of zero and NaN (values are `Decimal`, which keeps both signs)
All of this is IEEE on a Double. An Int64 or Currency zero has no sign, so a result is signed only when its static type is Double (`_static_numeric_type`; `/` is always Double).
- `0*-1`, `-(0)`, `-(1-1)`, `(1-1)*-1`, `-(COUNTROWS(Facts)*0)`: 0. `0.0*-1`, `-(0.0)`, `0*-1.0`, `0/-1`, `(1-1)/-1`, `-(SUM(Facts[Sales])*0)`, `(COUNTROWS(Facts)*0)/-1`: -0.
- `-(0.0)+0` is 0, `-(0.0)-0` and `-(0.0)+-(0.0)` -0, `-(0.0)*-1` 0.
- -0 prints as `0` as a bare result and in `FORMAT(x,"0.0")`, and as `-0` in `&`, `CONCATENATEX`, `CONVERT(x,STRING)` and `FORMAT(x,"General Number")`.
- `1/-(0.0)` is -Infinity, `1/(0*-1)` Infinity, `1/(0/-1)` -Infinity.
- Keep the sign through: VAR, `SQRT(-(0.0))` is -0, `VALUE("-0")` is -0 in text, `SUMX({0.0},-[Value])` -0, `MAX(-(0.0),0)` -0. Dropped by ABS ROUND INT TRUNC CEILING FLOOR MOD POWER `^` CURRENCY `"-0"+0`, `MIN(0,-(0.0))`. `SIGN(-(0.0))` is -1 (measured).
- NaN: `0/0`, `Inf-Inf`, `Inf*0`, `Inf/Inf` make `-nan(ind)`. Unary minus flips it to `nan`, twice back. `*` `+` `-` keep the sign of the first NaN operand: `(-(0/0))+(0/0)` is `nan`, `(0/0)+(-(0/0))` `-nan(ind)`, `(0/0)*-1` `-nan(ind)`. ABS gives `nan`. FORMAT prints the same two spellings, a bare result prints `NaN`.
- Underflow: a Double smaller than about 5E-324 is ±0: `(-1E-200)*1E-200` prints 0, and `-0` in text.
- `MAX(1,0/0)` is 1, `MAX(0/0,1)` NaN: the first argument is kept unless the second is greater.
The 4 expected failures in `tests/test_iteration108_convert_currency_9.py` (`PartGSignOfZeroAndNaNOpenTests`) should now pass: list that in your report, do not edit the test; Opus removes the marker.

## Part D: Currency limits
- First, the parser (measured): a sign binds the whole product or quotient that follows it, also after `*` or `/`. `1/-2*3` is -0.166666666666667, that is 1/(-(2*3)). Part B did this for a leading sign only.
- Currency holds value×10000 in a signed 64-bit integer. `+`, `-`, and `*` by a non-Currency, wrap at 64 bits with no error: `CURRENCY(1E14)*10` is -844674407370955.1616, `CURRENCY(922337203685477)+1` is -922337203685477.1616, `CURRENCY(922337203685477)*2` -1.1616, `CURRENCY(1E14)*100` 776627963145224.192. The wrapped value carries on in later arithmetic and text.
- `CURRENCY(x)` of a value outside ±922337203685477.5807 is the overflow error, as is `CURRENCY(1E14)/0.01`. `CURRENCY*CURRENCY` is a Double, no wrap: `CURRENCY(9E14)*CURRENCY(100)` is 9E+16.

## Part E: small rules
1. `IF(ISFILTERED(col),1)`, `IF(ISINSCOPE(col),1)`: a BLANK that reads only the filter context cancels an error also under CALCULATE or CALCULATETABLE with a column filter: `CALCULATE(ISERROR((IF(ISFILTERED(Facts[Region]),1))/(ERROR("x"))),Facts[Quantity]=2)` is False.
2. Arithmetic on text is Double, also for text conversion: `("1E15"+0)&"z"` is `1E+15z`, `LEN("1E15"+0)` 5, `("1000000000000000"+0)&"z"` `1E+15z`.
3. Double to text: take the shortest round-trip digits of the Double, then round to 15 significant half up. `(2/41)&"z"` is `4.87804878048781E-02z`. If this breaks locked items, drop it and report.
4. `FORMAT(1E300,"0")` and `"#,0"` and `"0.00"`: the 15 significant digits then zeros, no `NaN`.
5. `CONVERT(BLANK(),DATETIME)+1` is `12/31/1899 00:00:00`. `SUMX` over a CONVERT to DATETIME of a non-finite value prints `12/30/1899 00:00:00`, `12/31/9999 23:59:59`, `01/01/0100 00:00:00` as a bare result (a date type through SUMX, with VAR and IF).

## Corrections after the first fresh review (2026-11-02, all measured)
The first review scored 67,500 fresh answers on 3 tables: 6,268 wrong to right, but 195 match to wrong and 59 refused to wrong, nearly all from the two wrong rules below. These replace the earlier text where they differ.

**F1. The parser.** A sign after `^` also binds the whole product or quotient that follows, like a sign after `*` or `/`. `2^-1*3` is 0.125, that is 2^(-(1*3)). `2^-1/2` is 0.707106781186547, `2^+1*3` 8, `2^-1+1` 1.5, `2^-1^2` 0.5, `1/2^-1*3` 8, `3*2^-1*3` 0.375, `2^-2/2*4` 0.0625, `2^-MAX(Facts[Quantity])*0` 1. `2^3*4` stays 32. A `--` starts a comment: leave that alone.

**F2. `x^y` and POWER with an infinite or NaN operand (replaces the Part A block).**
- Finite x (a zero of either sign counts as x>=0), non-finite y: y=+Infinity or a positive NaN (`-(0/0)`) is the error. y=-Infinity or a negative NaN (plain `0/0`): x>=0 gives 0, x<0 the error. So `1^(0/0)` is 0 and `1^-(0/0)` an error.
- Non-finite x, finite y: y=0 gives 1. y>0 is the error. y<0: x=+Infinity gives 0. x=-Infinity or NaN gives 0 for a whole y (-1, -2, -3 measured), the error for a fractional y (-0.5, -1.5, -1E-200), and the error for -1E15; refuse a whole y of size 1E9 or more that is not -1E15-like, do not guess.
- x and y both non-finite: the error. BLANK rules stay.
- `(0.0*-1)^0` and `(-(0.0))^0` are 1, because that is a Double minus zero; `0^0`, `0.0^0` and `(0*-1)^0` stay the error. `(0.0*-1)^1E-200` is the error, `(0.0*-1)^0.5` is 0.
- `-(0/0)^0` is -1 by F1's rule that a sign covers the power.

**F3. Functions given Infinity or NaN.** The non-finite refusal in `_scalar_math_value` hid these, and the old ISBLANK rule hid that. Bare values: DEGREES and RADIANS 0, TANH 1, ODD 0, EVEN gives x back, ATAN(±Infinity) is ±π/2. `ATAN` of NaN is a junk value in Power BI (1.7786...): keep it a `MeasureError` refusal, never a runtime error, so ISERROR does not say True. ISEVEN and ISODD of NaN must not crash: they are the error. `CEILING(0,1/0)` is 0. `DIVIDE(1,0/0)` is BLANK, `DIVIDE(1,1/0)` 0. `ISBLANK(IF(TRUE(),QUOTIENT(0/0,1)))` is an error.

**F4. A BLANK first argument does not skip the second.** Today we return BLANK. Measured for y non-finite, `"a"` or `""`:
- The error for ROUND ROUNDUP ROUNDDOWN LEFT RIGHT REPT EDATE EOMONTH, for QUOTIENT and MROUND when y is text.
- BLANK for MOD CEILING FLOOR BITAND with non-finite y, BITAND also with text y; we refuse those today.
- `MOD(BLANK(),BLANK())`, `QUOTIENT(BLANK(),BLANK())` are the error. `LEFT(BLANK(),-1)`, `RIGHT(BLANK(),-1)` the error, `REPT(BLANK(),-1)` BLANK.

**F5. Currency.**
- A wrap happens only between Currency and Currency, Int64 or True/False. With a Double, a date or a text operand: `+` and `-` give a Double with no wrap (`CURRENCY(9E14)+1E15` is 1.9E+15, `CURRENCY(9E14)+1.5` prints 900000000000002). `*` and `/` give a Currency checked for range, the overflow error when too large: `CURRENCY(9E14)*2.0`, `CURRENCY(1E14)*SUM(Facts[Sales])`, `CURRENCY(1)*1E15`, `CURRENCY(1)*"1E15"`, `CURRENCY(1E14)*DATE(2020,1,1)` are errors, `CURRENCY(1)*9E14` is fine.
- SUMX of a Currency body wraps: `SUMX({1,2},CURRENCY(5E14))` is -844674407370955.1616. AVERAGEX divides the wrapped sum: `AVERAGEX({1,2},CURRENCY(5E14))` is -422337203685477.5808.
- `CURRENCY(x)` of a Double out of range is the overflow error (`CURRENCY(1E15)`, `CONVERT(1E15,CURRENCY)`, `ISERROR(CURRENCY(1E15))` True), of a whole-number constant it wraps (`CURRENCY(922337203685478)` is -922337203685477.1616). `ISCURRENCY(CURRENCY(1E15))` stays True for a constant, and is the error when the value reads data.
- `currency_typed` must see through a sign: `CURRENCY(2)/-1.5*-TRUE()` is 1.3333.

## Not in Task 20
`ISNUMBER` of arithmetic on a logical BLANK (`ISNUMBER((1&&"")*2)` True but `/2` False: static-type detail, about 20 items), Double text from the shortest digits (`(2/41)&"z"`, it breaks saved answers), COUNTAX of NaN through IFERROR, conversion errors of constants in empty iterators through COALESCE, `DATEVALUE` of numeric text, `TIME` through FORMAT and DATEVALUE. They stay open.

## Rules
1. One Part at a time, in the order A, C, B, D, E, then stop and report. Do not start the next Part.
2. Tests first, in `tests/test_iteration109_never_blank_zero_10.py`. Compute expected answers from the rule above.
3. Change the fewest lines you can, and reuse what exists.
4. No rule keyed to how an expression looks. No literal text from the spec in the code. No new kind of value. A result that depends on row order stays refused.
5. A refusal raises `MeasureError` (`dax_typed.refusal`), never `MeasureRuntimeError`.
6. After each Part run the scoring script for that Part (`PYTHONPATH=. QT_QPA_PLATFORM=offscreen python <scratchpad>/t20/score.py A`) and the replay (about 2 minutes): `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python tools/parity_check.py`. It must show 0 DIFF, 0 CRASH. `git checkout PARITY_LEDGER.md` after a replay.
7. Never run `--freeze`, `--accept`, commit, merge, push or Power BI. No global replace on `measures.py`. No edits to existing tests or saved answers: list those in your report. Scratch files go in the scratchpad.

## Review outcome (2026-11-02)
Shipped as Iteration 109. Corrections F1 to F5 and the later measured rules are in the work log. Two fresh batches on 3 tables, after removing `--` comment artefacts: 15,623 wrong to right, 3,984 refused to match, 6 crash to match, 108,444 stay matching, 24 match to refused, 425 wrong on both, 0 new wrong answers. Left open: Double arithmetic kept as Decimal (a true binary `/` broke 6 XNPV answers and was undone), type tests of arithmetic around a failing power (refused), and the items listed in `HANDOFF.md`.
