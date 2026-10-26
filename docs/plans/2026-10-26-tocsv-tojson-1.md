# Task 6: tocsv-tojson-1 (TOCSV and TOJSON)

**Branch:** `antigravity/tocsv-tojson-1`  **Written by:** Claude, 2026-10-26  **Status:** see `HANDOFF.md`
**Start condition:** Task 5 is DONE; `dax_battery_round2` has been re-frozen by Claude (full multi-line answers); `HANDOFF.md` says Active agent: Antigravity. Branch from `main`.

## Goal
Add `TOCSV(table, [maxRows], [delimiter], [includeHeaders])` and `TOJSON(table, [maxRows])` so that all non-error answers in `tools/parity/dax_battery_tocsv_tojson.json` (185 items) and the 8 TOCSV/TOJSON items from `dax_battery_round2` match. Power BI errors in the JSON stay refused. No VM, no `--freeze`.

## Rules (read exact outputs from the JSON; examples here are only a guide)
**TOCSV**
- Output is text. Rows separated by `\n` (no trailing newline). Header line first unless the 4th argument is `FALSE()`: `TOCSV(ROW("a",1),5,";",FALSE())` is `1`.
- Header cell is `[a]` for computed columns and `'Facts'[Sales]` for model columns. Columns of a model table keep the `'Table'[Col]` form.
- `maxRows` default is 1000 (check `TOCSV(Facts,1000)`), must be a number (`1.5` works as in the JSON; `TRUE()` too: read the JSON for how it is rounded/used), `BLANK` delimiter or `BLANK` includeHeaders behave as in the JSON.
- Delimiter default `,`; a custom delimiter (`;`, `||`) is used between cells. A cell is wrapped in double quotes when it contains the delimiter, a quote or a line break (`"y,z"`, `"x;y"`); inner quotes doubled. BLANK renders as empty. `-0` renders as `-0` for `-0.0` (read the JSON).
- Numbers: up to 15 significant digits (`123456789.123457`), exponent form `-1.5E+300`; dates render as `1/2/2020 3:04:05 AM` / `1/1/2020` (en-US culture, M/d/yyyy; time only when there is a time part); currency `1.5`.
- The first argument must be a table; a scalar is an error (refuse). Duplicate column names are an error.
**TOJSON**
- Layout (tabs for indent, `\n` line breaks): `{`, `"header": [...]`, `"rowCount": N`, `"data": [` with one `[...]` per row, `]`, `}`. Copy the layout character by character from the JSON.
- Numbers: doubles rendered with 4 significant digits after the point as the JSON shows (`0.3`, `1234567.8912`, `0.0`); integers plain; Booleans `true`/`false`; dates/times as ISO text `"2020-01-02T00:00:00"`; text with JSON escapes (`\t`, `\"`, `\\`); BLANK and infinity render as nothing inside the row (`[]` for a single infinite cell; read the JSON).
- `maxRows` of `0` gives BLANK.
- Using TOCSV/TOJSON in a CALCULATE True/False filter is a Power BI error; `COUNTROWS(TOJSON(...))` is an error. Keep refused.

## Where to look
`analytics_studio/measures.py`: existing table functions, `CONCATENATEX`, how a table expression is evaluated to rows with column names (also used by `COUNTROWS(SUMMARIZE(...))`); `tools/dax_oracle_diff.py local()` for how a text result is compared.

## Must NOT change
Anything not in the JSON; saved answers; protected files; existing tests. If a rendering is not in the JSON, refuse and ask in `HANDOFF.md`.

## Acceptance checks
1. New test `tests/test_iteration94_tocsv_tojson_1.py`: failing first. Loads both JSON files and asserts `match` for every item; explicit refusals: `TOCSV("a")`, `TOCSV(ROW("a",1,"a",2))`, `TOJSON(Facts,1,2)`, `COUNTROWS(TOJSON(Facts))`, `TOJSON(ROW("a",UNICHAR(1)))`.
2. Offline gate: group `dax_battery_tocsv_tojson` 0 pending (except items needing an unsupported table function: list them), DIFF 0, CRASH 0.
3. Full `--tests` gate passes; paste real lines. No `--freeze` / `--accept`.

## Hand-over
`READY FOR REVIEW`, `HANDOFF.md` entry, files, items still pending with the reason.
